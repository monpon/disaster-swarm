#!/usr/bin/env bash
# Join the drone on STA_IF, then create AP_IF on the same radio, same channel, same SSID.
# WARNING: wlan0 leaves its current network. If you are connected over wifi/ssh, you lose the session.
set -euo pipefail
CONF=${CONF:-/etc/drone-repeater.conf}
. "$CONF"
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

echo "[1/5] joining $DRONE_SSID on $STA_IF"
nmcli con up drone-uplink ifname "$STA_IF" >/dev/null
for _ in $(seq 20); do
  FREQ=$(iw dev "$STA_IF" link | awk '/freq:/ {print int($2)}')
  [ -n "${FREQ:-}" ] && break
  sleep 1
done
[ -n "${FREQ:-}" ] || { echo "could not associate with the drone"; exit 1; }
if   [ "$FREQ" -ge 2412 ] && [ "$FREQ" -le 2472 ]; then CH=$(( (FREQ - 2407) / 5 )); MODE=g
elif [ "$FREQ" -eq 2484 ]; then CH=14; MODE=g
else CH=$(( (FREQ - 5000) / 5 )); MODE=a; fi
echo "      drone on ${FREQ} MHz = channel $CH (hw_mode=$MODE)"

echo "[2/5] creating $AP_IF on the same radio"
PHY=$(iw dev "$STA_IF" info | awk '/wiphy/ {print "phy"$2}')
iw dev "$AP_IF" del 2>/dev/null || true
iw phy "$PHY" interface add "$AP_IF" type __ap
# give the AP its own MAC (locally administered) so it does not clash with the station
STA_MAC=$(cat /sys/class/net/"$STA_IF"/address)
AP_MAC=$(printf '%02x%s' $(( 0x${STA_MAC:0:2} | 0x02 )) "${STA_MAC:2}")
[ "$AP_MAC" = "$STA_MAC" ] && AP_MAC=$(printf '%s:%02x' "${STA_MAC%:*}" $(( (0x${STA_MAC##*:} + 1) & 0xff )))
ip link set "$AP_IF" address "$AP_MAC"
ip addr replace "$AP_ADDR" dev "$AP_IF"
ip link set "$AP_IF" up

echo "[3/5] hostapd + dnsmasq"
mkdir -p /run/drone-repeater
cat > /run/drone-repeater/hostapd.conf <<HOSTAPD
interface=$AP_IF
driver=nl80211
ssid=$DRONE_SSID
hw_mode=$MODE
channel=$CH
wmm_enabled=1
auth_algs=1
HOSTAPD
AP_IP=${AP_ADDR%/*}
cat > /run/drone-repeater/dnsmasq.conf <<DNSMASQ
interface=$AP_IF
bind-interfaces
port=0
dhcp-range=${AP_IP%.*}.10,${AP_IP%.*}.100,255.255.255.0,12h
dhcp-option=option:router,$AP_IP
pid-file=/run/drone-repeater/dnsmasq.pid
DNSMASQ
hostapd -B -P /run/drone-repeater/hostapd.pid /run/drone-repeater/hostapd.conf
dnsmasq -C /run/drone-repeater/dnsmasq.conf

echo "[4/5] redirect client UDP for $DRONE_IP into relay ports"
for pair in "8080 $RELAY_VIDEO_PORT" "8090 $RELAY_CMD_PORT"; do
  set -- $pair
  iptables -t nat -C PREROUTING -i "$AP_IF" -d "$DRONE_IP" -p udp --dport "$1" -j REDIRECT --to-ports "$2" 2>/dev/null ||
  iptables -t nat -A PREROUTING -i "$AP_IF" -d "$DRONE_IP" -p udp --dport "$1" -j REDIRECT --to-ports "$2"
done

STA_IP=$(ip -4 -o addr show "$STA_IF" | awk '{print $4}' | cut -d/ -f1)
echo "[5/5] up. Start the relay with:"
echo "  python -m relay --upstream-bind $STA_IP --listen-video-port $RELAY_VIDEO_PORT --listen-cmd-port $RELAY_CMD_PORT --stdout"
