#!/usr/bin/env bash
# Serve the web console (ui/apps/web) from the GX10 so a laptop only needs a browser: http://<gx10>:3001/live
# The console is built on a dev machine (cd ui && bun run build) and the Nitro output copied to ~/console-out; node 22 lives in ~/node.
# It finds the database (ws://<host>:3000) and the 3D viewer (http://<host>:8000) on the same host the page came from.
set -euo pipefail
cd ~/console-out
# node runs as `node server/index.mjs` from ~/console-out, so match on that (and wait for the port to free up)
pkill -f "[s]erver/index.mjs" 2>/dev/null || true
sleep 1
PORT="${PORT:-3001}" HOST=0.0.0.0 NITRO_PORT="${PORT:-3001}" NITRO_HOST=0.0.0.0 \
  setsid nohup ~/node/bin/node server/index.mjs > ~/console.log 2>&1 < /dev/null &
sleep 3
curl -s -o /dev/null -w "console: HTTP %{http_code} on :${PORT:-3001}\n" "http://127.0.0.1:${PORT:-3001}/" || tail -5 ~/console.log
