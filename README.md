# Mayfly
CalHacks 13 submission

**Live site: https://disaster-swarm.vercel.app/** (the web console; it shows demo data unless it is pointed at a running simulator, see below)

Mayfly is a search-and-rescue drone swarm simulator, plus the tooling to connect it to real hardware. A single central master
computer orchestrates every drone over a lossy, delayed radio link. The drones fly into an unknown collapsed building, build a
3D map of it together, find people with a YOLO detector, and rank them by urgency. Everything is simulated except the hardware
section at the end.

- **Simulator:** Python plus a Rust/CUDA core (`gpucore`, built with NVRTC and PyO3) that renders every drone camera and fuses
  depth into a TSDF map. Dual contouring turns it into flat walls and rectangular openings. Runs on a GPU machine (an ASUS GX10).
- **People and triage:** jointed human figures, detected by YOLO (`object_det/`). Each survivor gets a *simulated* Presage-style
  vitals reading and an urgency tier. The real Presage SDK was tested only on rendered clips with an injected pulse (`vitals/`).
- **Live state in SpacetimeDB:** the sim publishes drones, survivors, the floor plan, the 3D point cloud and 15 fps camera feeds
  into one database; the viewer and the web console only subscribe, so any number of browsers see the same mission.
- **Web console** (`ui/apps/web`, TanStack Start): mission setup, a live view with the 3D cloud and floor plans, a scrollable feed
  per drone with scanning highlights, and findings with vitals.
- **Real hardware** (`drone_control/`): an ESP32-S3 relay forwards an E58 drone's UDP video and IMU data; a live page shows video
  and a tracked path; a flight handler with failsafes and a read-only database publisher sit on top. The flight controller has been
  tested against a fake drone and has never flown the real one.

Built with [SpacetimeDB](https://spacetimedb.com) and [Presage](https://presagetech.com).

## The web console

The console is a TanStack Start app (`ui/apps/web`). The hosted copy at https://disaster-swarm.vercel.app/ runs on its demo
data. It reads live data from a SpacetimeDB at `ws://<page host>:3000` (override with `?stdb=ws://host:3000`), so for a live
mission serve it next to the sim (`scripts/console-up.sh`) or open it locally with `?stdb=` pointing at the sim's machine:

```bash
cd ui && bun install && cd apps/web && npx vite dev     # http://localhost:3001/live?stdb=ws://<sim host>:3000
```

## Run

```bash
# backend (Python 3.11+)
cd sim
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn disaster_sim.server:app --port 8000

# frontend
cd ui/viewer
npm install
npm run build      # served by the backend at http://localhost:8000
# or, for live-reload development:
npm run dev        # http://localhost:5173 (proxies /ws to :8000)
```

Headless run and tests:

```bash
cd sim
.venv/bin/python -m disaster_sim.headless --seconds 600 --seed 1 --drones 6
.venv/bin/python -m pytest -q
```

## How it works

| Layer | File | What it does |
|---|---|---|
| World | `sim/disaster_sim/world.py` | Seeded city: buildings, collapsed buildings, rubble, survivors, heightmap |
| Physics | `physics.py` | Rigid-body quadrotors (motor lag, drag, wind gusts, battery), vectorized |
| Flight control | `control.py` | Cascaded PID: position → velocity → attitude → body rate → motors |
| Camera | `sensors.py` | Forward-facing, gimbal-stabilized, 35° down; frustum and line-of-sight checks against structures |
| Onboard autopilot | `autopilot.py` | Follows master commands; obstacle reflex using the drone's local map |
| Radio | `comms.py` | Latency, jitter, packet loss |
| Master | `master.py` | Merges maps, picks frontier vantage points (Hungarian assignment), A* around obstacles, investigates and confirms survivors, sends drones home on low battery, keeps drones separated |
| Server | `server.py` | FastAPI WebSocket streaming 20 Hz state to the viewer |
| Viewer | `ui/src` | Three.js: flight view, master-map view, telemetry, controls |

Controls: click a drone (or a fleet row) to follow it, `Esc` stops following, `O` overview,
`Space` play/pause, `0–9` jump to drone. The *Mission control* panel sets speed, scenario
(seed, drones, wind, packet loss, camera tilt...) and view layers.

## Live state through SpacetimeDB

With `STDB_URL` set, the simulator publishes everything the viewer shows (drones, survivors and triage, entries, the mission log,
the 2D floor plan, the 3D mesh, point cloud and scan freshness, and the camera feed of the drone you select) into a
[SpacetimeDB](https://spacetimedb.com) database (module `swarm_db/`), and the viewer reads only from it, so any number of browsers
see the same live state and play/pause/speed/reset go back through it as commands. Without `STDB_URL` the viewer uses the
simulator's websocket as before.

```bash
scripts/stdb-up.sh            # SpacetimeDB on :3000, the swarm_db module, and the simulator publishing into it
scripts/stdb-up.sh publish    # re-publish the module after editing swarm_db/spacetimedb/src/lib.rs
# viewers: http://<host>:8000/      (the page asks /config where to read from; ?source=ws forces the websocket)
# console:  http://<host>:3001/live   (scripts/console-up.sh serves the built web console from the GX10; build it with `cd ui && bun run build`,
#            copy ui/apps/web/.output to ~/console-out there, node 22 in ~/node)
# real drone: drone_control/publish_db.py puts its status and video in the same database (read-only; see drone_control/control/README.md)
```

Needs the SpacetimeDB CLI (`curl -sSf https://install.spacetimedb.com | sh`) and the `wasm32-unknown-unknown` Rust target.
Only the simulator's identity (its token is kept in `~/.swarm_stdb_token`) can write the state; viewers can only submit commands.
`GET /stdb` shows the publisher's counters. Regenerate the viewer's bindings after changing the module:
`spacetime generate --lang typescript --out-dir ui/viewer/src/db/bindings --module-path swarm_db/spacetimedb`.
