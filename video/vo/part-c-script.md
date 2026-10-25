# Part C: technical section script

Runs 2:56.3 to 3:24.3 in the full cut (28 s). Times below are relative to the start of Part C.
Everything said here is backed by the code on `origin/main`. Things that are simulated are labelled on screen.

| Time | Narration | On screen (hand-drawn diagram, camera pans left to right) |
|---|---|---|
| 0.3 | "Each drone is a cheap E58 quadcopter." | Draws **1 · On the drone**. The **E58 quadcopter** box sketches in with a quad doodle. **Drone photo** and **Drone flying** slots appear underneath. |
| 3.0 | "An ESP32-S3 relay streams its camera over Wi-Fi…" | Arrow labelled **UDP** draws into **ESP32-S3 relay + MPU-6500 IMU**, with the note "Turbodrone wifi_cam protocol". Citation at the bottom: Turbodrone. |
| 6.2 | "…to one GPU computer." | Arrow labelled **Wi-Fi** draws into a dashed frame, **2 · One GPU computer (ASUS GX10)**. |
| 7.9 | "Our Rust and CUDA core…" | Camera pans right. The orange **Rust + CUDA core (gpucore)** box draws. |
| 9.6 | "…fuses every view into one shared 3D map…" | Arrow into **Shared 3D map: TSDF fusion + alignment**. |
| 11.8 | "…and plans each drone's next move." | Arrow down to **Planner: frontiers · A\***. |
| 13.9 | "YOLO26 spots people, doors and fire." | **YOLO26: person · door · fire · smoke** draws, then **Presage SmartSpectra: vitals · benchmarked**. Ultralytics and Presage logos top right. The **Simulator** slot appears. Citations: YOLO26 papers. |
| 16.9 | "It all syncs through SpacetimeDB to the console." | Camera pans right to **3 · To the crew**: **SpacetimeDB**, then **Web console**, then **Rescue crew**, plus a **Simulator view** slot. |
| 20.4 | "The full swarm runs in our simulator;" | Camera zooms out to the whole architecture. Tag: **Full swarm: simulated today**. |
| 21.9 | "our real drone streams live today." | Orange tag next to the E58: **Real E58: streams live** (with a tone). |
| 23.7 | "Next: real swarm flights, and robots like Boston Dynamics Spot." | Crossfade to the **Next up** slide. Check-marked bullets: Real swarm flight tests · Ground robots: Boston Dynamics Spot · Live vitals from drone video. Two Spot photos slide in polaroid-style. |
| 27.7 | (end) | Quick fade into Part D. |

## Team media slots

Drop files into `video/public/team/` and re-render. Each slot shows the file automatically and a dashed placeholder until then.

| File | Slot |
|---|---|
| `drone_photo.jpg` | Photo of the in-person E58 + ESP32-S3 relay |
| `drone_flight.mp4` | Footage of the drone flying (H.264, any length; the first ~6 s are shown) |
| `simulator.png` | Simulator screenshot (three.js viewer or sim GUI) |
| `simulator_2.png` | Second simulator or console view |

Landscape 3:2 images fit best.

## Facts deliberately left out

- **YOLO-World:** the repo contains `yolov8m-worldv2.pt`, but no code loads it. The live model is YOLO26m (4 classes: fire, smoke, person, door).
- **Presage:** SmartSpectra was only benchmarked offline. Live vitals in the simulator come from `SimulatedPresage`, so the diagram says "benchmarked".
- **Flight control:** the real E58 has not been flown by this code (`drone_control/control/README.md`). The diagram has no command arrow back to the real drone.
- **Speedups:** the numbers in commit messages are simulator real-time factors, not drone latency, so none are quoted.
