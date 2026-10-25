#!/usr/bin/env bash
# S3 AP throughput: runs esp32/bench.py on the S3, joins its AP, runs scripts/s3_bench.py.
# Wifi on the laptop is always restored; the S3's wifi is always switched off afterwards.
set -u
cd "$(dirname "$0")/.."
export PATH=$HOME/.local/bin:$PATH PYTHONPATH=.
PORT=${S3_PORT:-/dev/ttyACM0}
s3_wifi_off() {
  newgrp uucp >/dev/null 2>&1 <<EOF2
timeout 25 mpremote connect $PORT exec "
import network
for i in (network.STA_IF, network.AP_IF):
    w = network.WLAN(i)
    if w.active():
        w.active(False)"
EOF2
}
trap s3_wifi_off EXIT
s3_wifi_off
rm -f /tmp/s3_bench_run.log
( newgrp uucp >/tmp/s3_bench_run.log 2>&1 <<EOF3
timeout 90 mpremote connect $PORT run esp32/bench.py
EOF3
) &
for _ in $(seq 30); do grep -q "^AP " /tmp/s3_bench_run.log 2>/dev/null && break; sleep 1; done
grep -q "^AP " /tmp/s3_bench_run.log || { echo "S3 did not come up"; exit 1; }
DRONE_SSID=s3-bench JOIN_SUBNET='192\.168\.5\.' scripts/wifi_cycle.sh -- python scripts/s3_bench.py
