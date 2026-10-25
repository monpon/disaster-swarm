#!/usr/bin/env bash
# Laptop -> relay (loopback) -> REAL drone, through scripts/wifi_cycle.sh. Wifi is always restored.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=.
body() {
  local jl=/tmp/relay_real.jsonl; rm -f "$jl"
  local ip; ip=$(ip -4 -o addr show "${IFACE:-wlan0}" | awk '{print $4}' | cut -d/ -f1)
  python -m relay --listen-ip 127.0.0.1 --listen-video-port 18080 --listen-cmd-port 18090 \
      --upstream-bind "$ip" --telemetry-jsonl "$jl" --fake-imu ${RELAY_ARGS:-} >/tmp/relay_real.log 2>&1 &
  local rp=$!
  sleep 1
  timeout 30 python probe.py --ip 127.0.0.1 --video-port 18080 --cmd-port 18090 --seconds "${SECONDS_TEST:-6}"
  local rc=$?
  kill "$rp" 2>/dev/null; wait "$rp" 2>/dev/null
  echo "last telemetry:"; tail -1 "$jl" | python -c "import sys,json; d=json.loads(sys.stdin.read()); print(json.dumps({k:d[k] for k in ('relay','rc','extra')}))" 2>/dev/null
  return $rc
}
scripts/wifi_cycle.sh -- bash -c "$(declare -f body); body"
