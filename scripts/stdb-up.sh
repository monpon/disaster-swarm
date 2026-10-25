#!/usr/bin/env bash
# Bring up the whole stack on the GX10: SpacetimeDB, the swarm_db module, and the simulator publishing into it.
#   scripts/stdb-up.sh            start whatever is not running
#   scripts/stdb-up.sh publish    also re-publish the module (after editing swarm_db/spacetimedb/src/lib.rs)
# Viewers open  http://<host>:8000/?source=db   (add  &stdb=ws://<host>:3000  if the database is elsewhere).
set -euo pipefail
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! curl -s -m 2 -o /dev/null http://127.0.0.1:3000/v1/ping; then
  echo "starting SpacetimeDB on :3000"
  (setsid nohup spacetime start --non-interactive > "$HOME/stdb-server.log" 2>&1 < /dev/null &)
  for _ in $(seq 1 30); do curl -s -m 1 -o /dev/null http://127.0.0.1:3000/v1/ping && break; sleep 1; done
fi

if [ "${1:-}" = "publish" ] || ! spacetime sql --server local swarm "SELECT 1" > /dev/null 2>&1; then
  echo "publishing swarm_db"
  (cd "$ROOT/swarm_db" && spacetime publish --server local --module-path spacetimedb -y swarm)
fi

if ! curl -s -m 2 -o /dev/null http://127.0.0.1:8000/; then
  echo "starting the simulator server (publishing into SpacetimeDB)"
  cd "$ROOT/sim" && source .venv/bin/activate
  STDB_URL=http://127.0.0.1:3000 setsid nohup uvicorn disaster_sim.server:app --host 0.0.0.0 --port 8000 > "$HOME/disaster-swarm-server.log" 2>&1 < /dev/null &
fi
echo "ready: http://$(hostname -I | awk '{print $1}'):8000/?source=db"
