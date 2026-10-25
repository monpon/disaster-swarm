#!/usr/bin/env bash
set -u
CONF=${CONF:-/etc/drone-repeater.conf}
. "$CONF"
for pidf in /run/drone-repeater/hostapd.pid /run/drone-repeater/dnsmasq.pid; do
  [ -f "$pidf" ] && kill "$(cat "$pidf")" 2>/dev/null
done
for pair in "8080 $RELAY_VIDEO_PORT" "8090 $RELAY_CMD_PORT"; do
  set -- $pair
  iptables -t nat -D PREROUTING -i "$AP_IF" -d "$DRONE_IP" -p udp --dport "$1" -j REDIRECT --to-ports "$2" 2>/dev/null
done
iw dev "$AP_IF" del 2>/dev/null
nmcli con down drone-uplink >/dev/null 2>&1
echo "down. wlan0 is free; reconnect your normal wifi (nmcli con up <name>)."
