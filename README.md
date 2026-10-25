<p align="center">
  <a href="https://vimeo.com/1239251813"><img src="docs/media/thumbnail.jpg" alt="Watch the Mayfly demo video on Vimeo" width="100%"></a>
</p>

# Mayfly

**A swarm of cheap drones that maps a collapsed building in parallel, so rescuers know where people are before anyone goes in.**

When a building comes down, the first hour is mostly spent finding out what's inside. Today a rescue team typically sends one specialized indoor drone, flown by one pilot, room by room. Mayfly sends several small drones at once. They split the building between them, fly without a pilot each, and merge what they see into one live 3D map. The map marks people, blocked passages and hazards, and the crew gets a route.

Built at Cal Hacks 13.0. ▶ **[Watch the demo video (3:52)](https://vimeo.com/1239251813)**

| | |
|---|---|
| Demo video | https://vimeo.com/1239251813 (3:52) |
| Live web console | https://sonic-magenta-5w7whpr.tmp.now/ (reads the live mission from the GX10 through a tunnel) |
| Live simulator + 3D viewer | https://clouds-msg-diversity-serial.trycloudflare.com/?stdb=wss://aircraft-pressure-deal-michel.trycloudflare.com (served from the GX10; the `?stdb=` part is the database tunnel and is required) |
| If the live links are down | Both depend on a running sim and a tunnel, so they can be offline. The console then shows demo data. Run it yourself: [Quick start](#quick-start) |
| Sponsors used | [SpacetimeDB](https://spacetimedb.com) (all live state), [Presage](https://presagetech.com) (vitals, see the honesty notes) |

- [Demo video](#demo-video)
- [Honesty notes](#honesty-notes-read-before-judging)
- [Why this matters](#the-need)
- [What it does](#the-product) and [screens](#screens)
- [How it works](#system-architecture)
- [Competition](#competition) and [market](#market-fit)
- [Hackathon tracks](#hackathon-tracks)
- [Quick start](#quick-start) and [repository map](#repository-map)
- [Works cited](#works-cited)

---

## Demo video

[![Watch the Mayfly demo on Vimeo](docs/media/thumbnail.jpg)](https://vimeo.com/1239251813)

▶ **[Watch on Vimeo (3:52)](https://vimeo.com/1239251813)**: the problem, the product, a live walkthrough of the console, the technical design, and what's next. The video is a Remotion project in `video/`.

---

## Honesty notes (read before judging)

- Everything in the live view is a **simulation**. The simulator is the main way to run Mayfly.
- **Vitals are simulated.** The real Presage SDK was tested only on rendered video clips with an injected pulse (`vitals/`).
  It needs a real face and shoulders shot, so it does not run on the simulated people.
- The **flight controller has been tested against a fake drone and has never flown the real drone.** Stick directions and RC
  mode are unverified on hardware.
- The real drone reaches the database only while the ESP32 relay board is attached and joined to the GX10's network.
- The IMU path is dead reckoning from a cheap sensor. It drifts, and is a demonstration, not navigation.

In more detail:

| Part | Status |
|---|---|
| E58 video + IMU through the ESP32-S3 relay | **Working on real hardware.** Measured video from a direct link: 24.5–24.6 fps with 99.6–100% of frames intact. Through the S3 relay: 21.2 and 19.8 fps with 86.1% and 80.3% intact. The protocol splits each frame into about 7 chunks, so 5% packet loss costs about 30% of frames [8]. The real drone shows up in the console as a live tile. |
| Flying the real drone from code | **Built, not flown.** The flight handler (`drone_control/control/`, 49 tests) has only been tested with props off. Flight commands deliberately don't go through the database, because it has no auth for them yet. |
| Multi-drone swarm, shared map, planner | **Simulated.** Everything runs in our simulator on the GX10 with simulated VIO and a mono-depth stand-in. Plan-assisted demo mode is labelled *SIMULATION* in the viewer. |
| Object detection | **Real model.** YOLO26m runs on frames rendered by the simulator and on the live E58 stream (`live_drone_detection.py`). |
| Vitals | **Benchmarked.** When SmartSpectra accepts a clip, injected heart rate comes back within 0.5 bpm after about 12 s of warm-up. On our simulated *drone-quality* clips (shake, noise, JPEG q35) it returned `ChestNotVisible`. Live vitals in the sim are a labelled stand-in. |
| Console screens | Live from SpacetimeDB for drones, survivors, map, events and feeds. Mission setup and address search are mocked. The landing page's one-vs-many race is an illustration, not a measurement. |

## The need

After an earthquake or a structural collapse, rescue crews face the same question in every building: *is anyone in there, and where?*

The tools are slow for structural reasons, not because people aren't trying:

- **One drone at a time.** Specialized indoor drones are built to be flown into one building by one pilot. Mapping a whole structure means visiting every room in sequence.
- **They are expensive.** A BRINC LEMUR 2 was listed at **$29,999** per unit in a county sheriff's equipment procurement [3]. Teams usually own one or two.
- **Every minute of searching is a minute not spent rescuing.** Crews are entering unstable buildings to learn what a sensor could have told them.

Research on multi-robot exploration points the other way. A 2024 study in *Sensors* found a collaborative two-robot team cut indoor mapping time by **about 50%** [1]. A 2024 *IEEE RA-L* paper reported a **26.4%** improvement in indoor exploration with up to three aerial robots against its baseline [2]. Those are results from the cited studies, not measurements of Mayfly, but they are why we built a swarm instead of a better single drone.

There is also a responder-safety argument. Every room a drone clears is a room a firefighter doesn't have to walk into blind. That leaves crews' time and energy for the rescue itself.

## The product

<p align="center"><img src="docs/media/one-vs-many.jpg" alt="One drone versus the swarm searching the same house" width="90%"></p>

A rescue lead uses Mayfly from a browser:

1. **Start a mission.** Look up the address and pick the incident type (earthquake, structural collapse, gas leak…). Floor plan and building records load automatically.
2. **Launch.** Check which drones are ready and pick a search pattern (for example *split by room*). Launch them all with one click.
3. **Watch the map build.** Every drone's camera feeds one shared 3D point-cloud map, with a coverage meter ("62% mapped, 2 rooms left") and each drone's path.
4. **Act on findings.** People, closed doors, blocked passages and gas cylinders appear as pins with a confidence score. A found person shows a snapshot and estimated breathing and pulse.
5. **Brief the crew.** Send a route to the crew channel ("left from the front door, first door on the left, 7 m; gas cylinder is in the kitchen, not on this route").

<p align="center"><img src="docs/media/survivor.jpg" alt="Survivor finding with snapshot and vitals in the live console" width="90%"></p>

The console says what it can't do, too: cameras need light, so it's not for heavy smoke; pulse readings are estimates, not diagnoses; and the incident commander approves routes and can stop every drone.

## Screens

Web captures are from this branch at 1440 x 900 and 390 x 844, using the demo mission at 418 Elm St. Simulator and hardware shots come from the team's own recordings.

### Console, desktop

| New mission | Mission setup |
| --- | --- |
| <img src="docs/screenshots/desktop-new-mission.jpg" width="420" alt="Find the building and pick the incident type"> | <img src="docs/screenshots/desktop-setup.jpg" width="420" alt="Floor plan, geofence and four drones ready to launch"> |

| Live mission | Fleet |
| --- | --- |
| <img src="docs/screenshots/desktop-live.jpg" width="420" alt="Shared 3D map, four drone feeds, findings and the crew channel"> | <img src="docs/screenshots/desktop-fleet.jpg" width="420" alt="Fleet page with a drone's camera, health and hardware profile"> |

| Detection settings | Edge server |
| --- | --- |
| <img src="docs/screenshots/desktop-detection.jpg" width="420" alt="Detection classes, thresholds and what gets spoken to the crew"> | <img src="docs/screenshots/desktop-edge.jpg" width="420" alt="Edge server status and the services running on it"> |

### Simulator and hardware

| Simulator, split view | Console, 32-drone swarm |
| --- | --- |
| <img src="docs/screenshots/sim-split.jpg" width="420" alt="Simulator: the building on the left, the fused map with drone labels and planned paths on the right"> | <img src="docs/screenshots/console-swarm-map.jpg" width="420" alt="Console map with a 32-drone simulated swarm, entries and findings"> |

| Drone camera in the console | Our drone |
| --- | --- |
| <img src="docs/screenshots/console-drone-camera.jpg" width="420" alt="A simulated drone's camera view, expanded in the console"> | <img src="docs/screenshots/hardware-drone.jpg" width="420" alt="The E58 quadcopter with the ESP32-S3 relay mounted on top"> |

### Landing page, desktop

| Hero | One drone vs. the swarm |
| --- | --- |
| <img src="docs/screenshots/desktop-landing.jpg" width="420" alt="Landing page hero with the console preview"> | <img src="docs/screenshots/desktop-race.jpg" width="420" alt="One drone and the swarm search the same house side by side"> |

| One shared map | Checking on people |
| --- | --- |
| <img src="docs/screenshots/desktop-map-story.jpg" width="420" alt="The map story: findings, coverage and the crew's route"> | <img src="docs/screenshots/desktop-vitals.jpg" width="420" alt="Pulse read from the camera, shown as example output"> |

### Landing page, phone

| Hero | One vs. many | One map | Vitals |
| --- | --- | --- | --- |
| <img src="docs/screenshots/phone-landing.jpg" width="200" alt="Landing page hero on a phone"> | <img src="docs/screenshots/phone-race.jpg" width="200" alt="Race comparison on a phone"> | <img src="docs/screenshots/phone-map-story.jpg" width="200" alt="Map story on a phone"> | <img src="docs/screenshots/phone-vitals.jpg" width="200" alt="Vitals section on a phone"> |

## System architecture

The drones don't think. Each one is a cheap quadcopter with a camera and an IMU. It streams what it sees to one GPU computer and flies where it is told. All the intelligence, from mapping to planning to detection, lives in one place.

```mermaid
flowchart LR
  subgraph Field["On the drones"]
    D1["E58 quadcopter<br/>camera"]:::hw
    R1["ESP32-S3 relay<br/>+ MPU-6500 IMU"]:::hw
    D1 -- "UDP 8080 video<br/>UDP 8090 RC" --> R1
  end

  subgraph Base["One GPU computer (ASUS GX10)"]
    M["Master<br/>(Python)"]
    G["gpucore<br/>Rust + CUDA via NVRTC"]:::core
    MAP["Shared 3D map<br/>TSDF fusion · frame-to-map alignment"]
    P["Planner<br/>frontiers · A* · relay backbone"]
    Y["YOLO26m detector<br/>person · door · fire · smoke"]
    V["Vitals<br/>Presage SmartSpectra*"]
    M --> G --> MAP --> P
    M --> Y
    M --> V
  end

  subgraph Out["Rescue team"]
    DB[("SpacetimeDB<br/>entity · bulk · event · cmd")]
    UI["Web console<br/>TanStack Start + three.js"]
    CREW["Crew channel"]
    DB --> UI --> CREW
    UI -- "commands" --> DB
  end

  R1 -- "Wi-Fi: video 9100/9101 telemetry + IMU" --> M
  P -- "waypoints" --> M
  M -- "state 5 Hz · feeds 15 fps JPEG" --> DB

  classDef hw fill:#fff1ea,stroke:#c2410c,color:#151515
  classDef core fill:#ff5a1f,stroke:#c2410c,color:#fff
```

<sub>*SmartSpectra was benchmarked offline; vitals in the live simulator come from a stand-in that labels its numbers as simulated. See below.</sub>

### The pieces

| Component | Where | What it does |
|---|---|---|
| **Drone link** | `drone_control/` | Talks to an E58 toy quadcopter with the reverse-engineered `wifi_cam` protocol from Turbodrone [7]: JPEG video on UDP 8080, RC on UDP 8090. |
| **ESP32-S3 relay** | `drone_control/esp32/relay.py` | MicroPython. Joins the drone's Wi-Fi as a client and runs its own AP on the same radio. Forwards video and RC both ways and streams the MPU-6500 at 100 Hz. |
| **Simulator + master** | `sim/disaster_sim/` | Seeded buildings and survivors, quadrotor physics with cascaded PID, camera, VIO drift, depth error and a lossy ESP mesh radio. The master fuses every drone's frames into one map and plans where each goes next. |
| **gpucore** | `gpucore/` | The simulator's GPU core, written as a PyO3 extension. CUDA kernels are compiled at startup with NVRTC: voxel ray-march camera, map fusion, Gauss-Newton alignment, plane fitting, viewer streaming, radio SNR, plus a native A* planner. A PyTorch implementation remains as the reference and fallback. |
| **Detection** | `object_det/` | A YOLO26m checkpoint on Ultralytics [4][5] with four classes: fire, smoke, person, door. It runs as a ROS 2 node (`/detections`, `vision_msgs`) and as a local FP16 GPU service the simulator calls. |
| **Vitals** | `vitals/` | Benchmark of Presage SmartSpectra on clips built from real photos with injected pulse and breathing [9]. |
| **Live state** | `swarm_db/` | SpacetimeDB module (Rust → WASM) [10]. Only the simulator's identity can write state; viewers can only submit commands. |
| **Console** | `ui/apps/web` | TanStack Start, React 19, Tailwind v4 and an embedded three.js point-cloud viewer. Every browser sees the same mission state. |

### How a search plays out

```mermaid
sequenceDiagram
  participant Lead as Rescue lead
  participant UI as Console
  participant DB as SpacetimeDB
  participant M as Master + gpucore
  participant D as Drones
  Lead->>UI: Launch 4 drones
  UI->>DB: submit_cmd(launch)
  DB->>M: cmd
  M->>D: scouts take nearest frontiers; perimeter team flies the outside
  loop 20 Hz position loop, 5 Hz state
    D-->>M: IMU + JPEG frames over the mesh
    M->>M: fuse into TSDF map, align to walls/roof, detect
    M->>D: next stretch (replanned without stopping)
    M-->>DB: drones, map, findings, feeds
    DB-->>UI: live tables
  end
  M-->>DB: person found + vitals estimate
  UI->>Lead: pin, snapshot, route
  Lead->>UI: Send route to crew
```

The planner does a few things a single drone can't:

- Scouts take frontiers nearest the base first.
- Once the building is located, a perimeter team flies the outside while the rest go in through openings confirmed for 5 seconds.
- Some drones hold back as a relay backbone to keep the mesh connected.
- A forward-clear speed governor uses fresh depth, with an emergency brake and a battery return reserve.

## Competition

| | Mayfly | BRINC LEMUR 2 | Flyability Elios 3 | Skydio X10 |
|---|---|---|---|---|
| Form factor | Many small drones, one base computer | One specialized indoor drone | One caged inspection drone | One autonomous drone |
| Search model | Parallel: the building is split between drones | Sequential, one pilot | Sequential, one pilot | One drone per pilot |
| Unit cost | Toy-class airframes + one GPU box | $29,999 listed [3] | — | — |

The incumbents make excellent single aircraft: caged airframes that bounce off walls, lidar, ruggedized radios. We aren't trying to out-build them on one drone. Mayfly bets that for *search*, coverage per minute matters more than the capability of any one airframe, and that coverage scales with the number of drones in the air.

## Market fit

| Market | 2026 | 2033 | Growth |
|---|---|---|---|
| Drone-as-first-responder | $3.5B | $11B | 17.7% a year, more than 3× |
| Global drones | $96.4B | $182.4B | ~1.9× |

<sub>Grand View Research [13]. The first row is the segment Mayfly sells into.</sub>

- **Who buys:** urban search and rescue teams, fire departments and county sheriffs, the same buyers who already procure single indoor drones. In the US alone FEMA's National Urban Search & Rescue Response System has 28 task forces [11], and many fire departments run their own technical rescue teams.
- **Why they'd switch:** one LEMUR 2 costs about the same as a GPU base station plus a box of small drones. When a drone is crushed in a collapse, the team loses a cheap airframe, not its only one.
- **How it fits their workflow:** it runs from a browser on the incident network, briefs the crew over the radio channel they already use, and keeps a person in charge of every route.
- **Beyond earthquakes:** welfare checks, gas leaks and post-blast assessment, any time someone needs to know what's inside before going in.

## What's next

- Real swarm flight tests: fly the E58 through the relay, then several at once.
- A Raspberry Pi relay (scripts exist and are untested) to replace the S3 and fix its frame loss.
- Live vitals from drone-quality video, by finding which degradation breaks SmartSpectra.
- Ground robots like Boston Dynamics Spot joining the same map, for rubble drones can't fly through.

## Hackathon tracks

<!-- Edit this table to match the tracks we actually submitted to on Devpost. -->

| Track | Why Mayfly fits |
|---|---|
| **Social impact / public safety** | Finds trapped people faster and keeps responders out of unsearched rooms. |
| **Hardware** | Real E58 drone, custom ESP32-S3 Wi-Fi relay with a live IMU stream, reverse-engineered RC protocol. |
| **Presage** | SmartSpectra vitals pipeline and benchmark on synthetic, real-photo-based clips (`vitals/`). |
| **SpacetimeDB** | The whole mission state, including map blobs, camera feeds, events and commands, lives in one SpacetimeDB module that every console subscribes to (`swarm_db/`). |
| **ASUS / GPU computing** | `gpucore` CUDA kernels and the YOLO26 FP16 service run on the ASUS Ascent GX10. |
| **AI / computer vision** | YOLO26m detection of people, doors, fire and smoke; TSDF map fusion; frontier planning. |

## Quick start

Needs Python 3.11+, and for the full simulator an NVIDIA GPU with CUDA (developed on an ASUS GX10, aarch64) and a Rust toolchain.

```bash
# 1. simulator (Python)
cd sim
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"      # add ".[gpu]" for the torch smoothing path
.venv/bin/uvicorn disaster_sim.server:app --port 8000           # http://localhost:8000 serves the 3D viewer

# 2. the viewer it serves (built once)
cd ../ui/viewer && npm install && npm run build

# 3. live state through SpacetimeDB (recommended): database, module, and the sim publishing into it
cd ../.. && scripts/stdb-up.sh        # needs the SpacetimeDB CLI and the wasm32-unknown-unknown Rust target

# 4. the web console, in dev mode (http://localhost:3001/live)
cd ui && bun install && cd apps/web && npx vite dev
#    pointing at a sim on another machine:  http://localhost:3001/live?stdb=ws://<sim host>:3000
```

Tests and a headless run:

```bash
cd sim && .venv/bin/python -m pytest -q
cd sim && .venv/bin/python -m disaster_sim.headless --seconds 600 --seed 1 --drones 6
cd drone_control && PYTHONPATH=.:tests pytest tests        # 54 tests: IMU tracker, flight handler, controller server, DB publisher
```

More detail lives next to the code: `gpucore/README.md`, `object_det/README.md`, `vitals/README.md`, `drone_control/control/README.md`, `drone_control/esp32/README.md`. The demo video is a Remotion project in `video/`.

## Repository map

| Path | What is in it |
|---|---|
| `sim/disaster_sim/` | The simulator (Python). See the table below. |
| `gpucore/` | Rust + CUDA core (PyO3): camera rendering, depth fusion, TSDF map, alignment, mesher, radio |
| `object_det/` | YOLO person detector served on loopback `127.0.0.1:8765` (`serve.py`); the sim calls it |
| `swarm_db/spacetimedb/` | SpacetimeDB module (Rust): the `entity`, `bulk`, `event` and `cmd` tables and their reducers |
| `ui/apps/web/` | Web console: TanStack Start + React, `routes/` (landing, setup, live, fleet) and `components/live/` |
| `ui/viewer/` | Three.js 3D viewer (Vite); also embedded in the console as the point cloud (`?embed=cloud`) |
| `drone_control/` | Real hardware: `esp32/` relay firmware, `imu/` live page and path tracker, `control/` flight handler + HTTP API, `publish_db.py` |
| `vitals/` | Presage experiments: sample images, rendered clips, benchmark results |
| `scripts/` | `stdb-up.sh` (database + sim), `console-up.sh` (serve the built console) |

Simulator modules (`sim/disaster_sim/`):

| Area | Files |
|---|---|
| World and people | `building.py`, `entry.py`, `opening.py`, `materials.py`, `humans.py`, `floorplan.py` |
| Drones | `physics.py` (quadrotor dynamics), `control.py` (cascaded PID), `pilot.py`, `esp.py` |
| Sensing and mapping | `camera.py`, `rustcore.py` (bridge to `gpucore`), `gpu.py`, `voxelmap.py`, `surface.py`, `smoothing.py`, `align.py`, `estimation.py` |
| Radio | `comms.py`, `radio.py`, `packets.py`, `gcomms.py` |
| Master and planning | `master.py`, `planner3d.py` |
| People finding | `detector.py` (YOLO client), `presage.py` (simulated vitals) |
| Server and state | `sim.py` (the simulation loop), `server.py` (FastAPI), `protocol.py`, `stdb.py` (SpacetimeDB publisher), `config.py` |

## Live state through SpacetimeDB

With `STDB_URL` set, the simulator publishes everything the viewers show into a SpacetimeDB database named `swarm` (port 3000),
and the viewer and console read only from it, so any number of browsers see the same state. Without `STDB_URL` the viewer uses
the simulator's websocket instead (`?source=ws` forces this).

- **Tables:** `entity` (key, ver, text JSON, binary data), `bulk` (voxels, points, scan freshness, meshes, camera feeds),
  `event` (mission log) and `cmd` (commands from viewers). Reducers: `put`, `put_blobs`, `drop_keys`, `submit_cmd`, `clear_all`.
- **Keys the console uses:** `drone/<n>`, `plan/<floor>`, `feed/jpg<n>` (15 fps JPEG camera feeds), `real/status` and
  `feed/jpgreal` (the real drone).
- **Writes:** only the simulator's identity (token in `~/.swarm_stdb_token`) can write state. Viewers can only submit commands.
- **Commands:** `play`, `pause`, `speed`, `step`, `reset` and `select` (which drones' feeds to stream).
- `GET /stdb` on the sim server returns the publisher's counters. Regenerate the viewer's bindings after editing the module:
  `spacetime generate --lang typescript --out-dir ui/viewer/src/db/bindings --module-path swarm_db/spacetimedb`.
- The console finds the database at `?stdb=`, else the `VITE_STDB_URL` build variable, else `ws://<page host>:3000`. The viewer
  address works the same way (`?viewer=`, `VITE_VIEWER_URL`, else `http://<page host>:8000/`). The hosted console is built with
  both set to Cloudflare tunnels to the GX10 (a `wss://` address is required from an HTTPS page).

## Real drone

`drone_control/` connects real hardware, always next to the simulator and never instead of it. The sim stays the main path.

- **Link:** E58 drone Wi-Fi AP (video UDP 8080, RC UDP 8090) to an ESP32-S3 relay (`esp32/relay.py`, its own AP at `192.168.5.1`,
  telemetry UDP 9100, IMU UDP 9101).
- **Live page:** `drone_control/imu/live.py` (port 8766) serves the rotated video and a 3D path from the IMU. Path modes:
  `hold` (default, slow leak) and `recentre`.
- **Flight handler:** `python -m control` in `drone_control/` (see `drone_control/control/README.md`). Sticks are shaped and
  slew-limited, neutral until flying, with a dead-man timeout (0.4 s neutral, then land after 3 s), a link-loss landing, and a
  latched emergency stop. Its HTTP API needs a token and is never routed through the database.
- **Database sync:** `drone_control/publish_db.py` is read-only toward the drone and writes `real/status` and `feed/jpgreal`.

## Controls

Click a drone (or a fleet row) to follow it, `Esc` stops following, `O` overview, `Space` play/pause, `0–9` jump to drone. The
*Mission control* panel sets speed, scenario (seed, drones, wind, packet loss, camera tilt) and view layers.

## Notes for AI agents and contributors

- **Start here:** `sim/disaster_sim/sim.py` (loop), `master.py` (decisions), `stdb.py` (what is published),
  `ui/apps/web/src/lib/swarm.ts` (console data store), `ui/viewer/src/main.ts` (viewer entry).
- **The sim palette is load-bearing.** `materials.py` colours are classified by the master from camera pixels, and the doorframe
  yellow drives entry detection. Change how things *look* only in the viewer (`ui/viewer/src/scene/textures.ts`, `realview.ts`).
- **Detector:** `cfg.detector` is on by default and uses the loopback service on port 8765. On the GX10 the live drone page uses
  8766 for this reason.
- **Do not commit secrets.** The Presage API key belongs only in the gitignored `vitals/.env`.
- **Label simulated things as simulated** in any UI text or doc. Keep the real/simulated distinction honest.
- **Console deploy:** `ui/apps/web` builds with `NITRO_PRESET=vercel npx vite build` for Vercel. Set `VITE_STDB_URL` and
  `VITE_VIEWER_URL` at build time (they are compiled in). From the repo root, `scripts/console-up.sh` serves the built console
  on port 3001 from the GX10.
- **Verify before claiming:** run the tests above after changing the sim or `drone_control`; typecheck the console with
  `cd ui/apps/web && npx tsc --noEmit`.

## Works cited

**Research and market evidence**

1. Xia et al., *Sensors* (2024). Collaborative two-ground-robot indoor mapping experiment; about 50% less indoor mapping time.
2. Kim et al., *IEEE Robotics and Automation Letters* (2024). Up to three aerial robots compared with the paper's baseline; 26.4% improvement in indoor exploration performance.
3. Santa Clara County Sheriff's Office, equipment listing. BRINC LEMUR 2 procurement cost, $29,999 per unit.

**Technology**

4. Jocher, Glenn, et al. "Ultralytics YOLO26: Unified Real-Time End-to-End Vision Models." *arXiv*, 2 June 2026, [arxiv.org/abs/2606.03748](https://arxiv.org/abs/2606.03748).
5. Sapkota, Ranjan, et al. "YOLO26: Key Architectural Enhancements and Performance Benchmarking for Real-Time Object Detection." *arXiv*, 29 Sept. 2025, [arxiv.org/abs/2509.25164](https://arxiv.org/abs/2509.25164).
6. Lajoie, Pierre-Yves, and Giovanni Beltrame. "Swarm-SLAM: Sparse Decentralized Collaborative Simultaneous Localization and Mapping Framework for Multi-Robot Systems." *IEEE Robotics and Automation Letters*, vol. 9, no. 1, Nov. 2023, pp. 475–82, [doi.org/10.1109/lra.2023.3333742](https://doi.org/10.1109/lra.2023.3333742). Related work on collaborative multi-robot mapping.
7. Richards, Marshall, et al. *marshallrichards/turbodrone: Reverse Engineering the Best-selling Drones on Amazon to Control Programmatically*. Commit 2c09cf8, 26 June 2026, [github.com/marshallrichards/turbodrone](https://github.com/marshallrichards/turbodrone).
8. Mayfly team. *Drone link approach analysis*, `drone_control/docs/approach-analysis.md` (our own measurements).
9. Presage Technologies. SmartSpectra SDK (`@smartspectra/node-sdk` 3.4.0), [presagetech.com](https://presagetech.com).
10. Clockwork Labs. SpacetimeDB, [spacetimedb.com](https://spacetimedb.com).
11. FEMA. National Urban Search & Rescue (US&R) Response System, [fema.gov/emergency-managers/national-preparedness/frameworks/urban-search-rescue](https://www.fema.gov/emergency-managers/national-preparedness/frameworks/urban-search-rescue).
12. Cheng, Tianheng, et al. "YOLO-World: Real-Time Open-Vocabulary Object Detection." *arXiv*, 30 Jan. 2024, [arxiv.org/abs/2401.17270](https://arxiv.org/abs/2401.17270). Its weights are in the repo (`yolov8m-worldv2.pt`); the shipped detector is YOLO26m.
13. Grand View Research. Drone market and drone-as-first-responder market size estimates, 2026–2033 (global drones $96.4B → $182.4B; drone-as-first-responder $3.5B → $11B at 17.7% CAGR).

**Media in the demo video.** Stock footage and photos are public domain or Creative Commons. Authors and licences are listed per file in `video/public/stock/CREDITS.md`. Competitor names and logos are used only to identify products.
## Team

Built at CalHacks 13.
