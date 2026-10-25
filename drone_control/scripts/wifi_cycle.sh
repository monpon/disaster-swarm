#!/usr/bin/env bash
# Run a command while this machine is joined to the drone's wifi, then ALWAYS restore normal wifi.
#
#   scripts/wifi_cycle.sh -- <command...>
#
# Restore order: the connection active before we started, then each name in $FALLBACKS, then
# whatever NetworkManager autoconnects. Runs on EXIT/INT/TERM, so a failed test or Ctrl-C still
# restores wifi. The command's exit code is passed through.
#
# Env: DRONE_SSID (default WIFI_8K__cc220c)  IFACE (wlan0)  FALLBACKS ("FridgeWiFi|Cal Hacks 13.0")
#      JOIN_SUBNET (192\\.168\\.4\\.: grep pattern the joined address must match)
#      JOIN_TRIES (4)  RESTORE_TRIES (3)  CHECK_HOST (1.1.1.1)
set -u
DRONE_SSID=${DRONE_SSID:-WIFI_8K__cc220c}
IFACE=${IFACE:-wlan0}
FALLBACKS=${FALLBACKS:-"FridgeWiFi|Cal Hacks 13.0"}
JOIN_SUBNET=${JOIN_SUBNET:-192\\.168\\.4\\.}
JOIN_TRIES=${JOIN_TRIES:-4}
RESTORE_TRIES=${RESTORE_TRIES:-3}
CHECK_HOST=${CHECK_HOST:-1.1.1.1}

log() { echo "[wifi_cycle] $*" >&2; }
active_con() { nmcli -t -f GENERAL.CONNECTION dev show "$IFACE" 2>/dev/null | cut -d: -f2-; }
online() { ping -c1 -W3 "$CHECK_HOST" >/dev/null 2>&1; }

[ "${1:-}" = "--" ] && shift
[ $# -gt 0 ] || { echo "usage: $0 -- <command...>" >&2; exit 2; }

ORIG=$(active_con)
[ "$ORIG" = "--" ] && ORIG=""
log "original connection: ${ORIG:-<none>}"

restore() {
  trap - EXIT INT TERM
  log "restoring wifi"
  local candidates=() c
  [ -n "$ORIG" ] && [ "$ORIG" != "$DRONE_SSID" ] && candidates+=("$ORIG")
  IFS='|' read -ra extra <<<"$FALLBACKS"
  for c in "${extra[@]}"; do candidates+=("$c"); done
  for attempt in $(seq "$RESTORE_TRIES"); do
    nmcli dev wifi rescan ifname "$IFACE" >/dev/null 2>&1; sleep 3
    for c in "${candidates[@]}"; do
      if nmcli -w 20 con up id "$c" ifname "$IFACE" >/dev/null 2>&1; then
        if online; then log "restored: $c (internet ok)"; return 0; fi
        log "joined $c but no internet, trying next"
      else
        log "could not join $c (attempt $attempt)"
      fi
    done
    nmcli dev connect "$IFACE" >/dev/null 2>&1 && online && { log "restored via autoconnect: $(active_con)"; return 0; }
  done
  log "WARNING: wifi NOT restored. Run: nmcli dev wifi list; nmcli con up id <name>"
  return 1
}
trap restore EXIT INT TERM

joined=0
for i in $(seq "$JOIN_TRIES"); do
  nmcli dev wifi rescan ifname "$IFACE" >/dev/null 2>&1; sleep 4
  if nmcli -w 20 dev wifi connect "$DRONE_SSID" ifname "$IFACE" >/dev/null 2>&1 \
     && ip -4 -br addr show "$IFACE" | grep -q "$JOIN_SUBNET"; then joined=1; break; fi
  log "join attempt $i/$JOIN_TRIES failed"
done
[ "$joined" = 1 ] || { log "could not join $DRONE_SSID (is the drone on?)"; exit 3; }
log "joined $DRONE_SSID: $(ip -4 -br addr show "$IFACE" | awk '{print $3}')"

"$@"
rc=$?
log "command exited $rc"
exit "$rc"
