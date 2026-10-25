#!/usr/bin/env bash
# Run esp32/relay.py on the S3, join its AP from this laptop, probe through it, capture its telemetry,
# then ALWAYS switch the S3's wifi off (it would otherwise hold the drone's only client slot) and
# restore the laptop's wifi.
#
#   scripts/s3_relay_test.sh [seconds]      (S3 on /dev/ttyACM0, drone powered on)
set -u
cd "$(dirname "$0")/.."
export PATH=$HOME/.local/bin:$PATH PYTHONPATH=.
SECS=${1:-10}
PORT=${S3_PORT:-/dev/ttyACM0}
TELE=/tmp/s3_tele.jsonl

s3_wifi_off() {
  newgrp uucp >/dev/null 2>&1 <<EOF
timeout 25 mpremote connect $PORT exec "
import network
for i in (network.STA_IF, network.AP_IF):
    w = network.WLAN(i)
    if w.active():
        w.active(False)"
EOF
}
trap s3_wifi_off EXIT

s3_wifi_off
rm -f /tmp/s3_run.log "$TELE"
# The host side is time-limited so it can never be orphaned; the S3 keeps running until s3_wifi_off.
( newgrp uucp >/tmp/s3_run.log 2>&1 <<EOF
timeout $((SECS + 40)) mpremote connect $PORT run esp32/relay.py
EOF
) &
for _ in $(seq 40); do grep -q "^AP " /tmp/s3_run.log 2>/dev/null && break; sleep 1; done
head -4 /tmp/s3_run.log | cut -c1-140
grep -q "^AP " /tmp/s3_run.log || { echo "S3 did not come up"; exit 1; }

body() {
  python - "$1" <<'PY' &
import socket, sys, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("", 9100)); s.settimeout(0.5)
end = time.time() + float(sys.argv[1]) + 6
with open("/tmp/s3_tele.jsonl", "w") as f:
    while time.time() < end:
        try: f.write(s.recvfrom(65535)[0].decode() + "\n"); f.flush()
        except socket.timeout: pass
PY
  sleep 1
  python probe.py --ip 192.168.5.1 --seconds "$1"
  wait
}
DRONE_SSID=s3-relay-test JOIN_SUBNET='192\.168\.5\.' \
  scripts/wifi_cycle.sh -- bash -c "$(declare -f body); body $SECS"

echo "--- S3 telemetry (last snapshot captured on the laptop):"
tail -1 "$TELE" 2>/dev/null | python -c "
import sys, json
l = sys.stdin.read().strip()
if not l: print('none captured'); sys.exit()
d = json.loads(l)
print(json.dumps({'relay': d['relay'], 'host': d['extra'].get('host'), 'rc': d['rc']}))"
