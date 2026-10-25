#!/usr/bin/env bash
# Raspberry Pi OS (Bookworm, NetworkManager), single onboard radio. UNTESTED ON HARDWARE.
# Installs packages and the drone-uplink profile, then installs repeater-up/down helpers.
# Run `sudo repeater-up` to start; `sudo repeater-down` to stop.
set -euo pipefail
CONF=${1:-/etc/drone-repeater.conf}
[ -f "$CONF" ] || { echo "missing $CONF (see pi/repeater.conf.example)"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)

apt-get install -y hostapd dnsmasq iptables iw >/dev/null
# hostapd/dnsmasq are started by repeater-up, not at boot
systemctl unmask hostapd
systemctl disable --now hostapd dnsmasq >/dev/null 2>&1 || true

# NetworkManager must not touch the virtual AP interface
AP_IF=$(. "$CONF"; echo "$AP_IF")
mkdir -p /etc/NetworkManager/conf.d
echo -e "[keyfile]\nunmanaged-devices=interface-name:$AP_IF" > /etc/NetworkManager/conf.d/90-drone-ap-unmanaged.conf
systemctl reload NetworkManager || true

# uplink profile: join the drone (open network), never become the default route
. "$CONF"
nmcli con delete drone-uplink >/dev/null 2>&1 || true
nmcli con add type wifi ifname "$STA_IF" con-name drone-uplink ssid "$DRONE_SSID" \
  connection.autoconnect no ipv4.never-default yes ipv4.method auto

install -m 755 "$HERE/repeater-up.sh" /usr/local/sbin/repeater-up
install -m 755 "$HERE/repeater-down.sh" /usr/local/sbin/repeater-down
echo "installed. Next: sudo repeater-up   (this will drop wlan0 from your current wifi!)"
