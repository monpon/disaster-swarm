# Flight control through the ESP32-S3 relay

A handler that flies the E58 by sending the RC stream the drone expects, through the relay (which forwards UDP 8090 to the drone).

```
PYTHONPATH=drone_control python -m control --relay 192.168.5.1 --host 0.0.0.0      # prints the page URL with its token
PYTHONPATH=drone_control pytest drone_control/tests                                 # 49 tests, no hardware needed
```

Open the printed URL (`http://<host>:8770/?token=...`): Arm, Takeoff, then `W/S` forward/back, `A/D` left/right, `R/F` up/down,
`Q/E` turn, `Space` = emergency stop. The live video comes from `imu/live.py` on port 8766 of the same machine.

## What it does

`handler.py` is a state machine, `DISARMED -> ARMED -> FLYING -> LANDING -> ARMED`, with `EMERGENCY` reachable from anywhere
and cleared only by disarming. It starts disarmed and sends neutral sticks.

- Sticks only count while flying, and not for `takeoff_settle` (2 s) after takeoff, while the drone climbs by itself.
- Sticks are normalised -1..1, with a dead zone and expo, scaled by `--limit` (default 0.5 of the usable range) and slew-limited
  (3/s), so a keyboard cannot jerk the drone around. NaNs, strings and booleans are refused.
- Dead-man: no stick message for 0.4 s and the sticks go to neutral (hover); for 3 s and it lands.
- Link: arming and taking off need the relay's telemetry (UDP 9100, 1 Hz). If it stops for 3 s while flying, it lands.
- It lands by itself after `--max-flight` seconds (default 240).
- Takeoff / land / emergency are held for 8 packets (short mode) so one lost datagram cannot swallow them.
- Every command needs the token; one is made up when the page is served beyond localhost.
- `control/link.py` sends RC only: no video request, no stream-stop, so it does not disturb the live page on the same machine.

## Not verified on the real drone

Nothing here has flown the E58. Check with the props off before anything else:

- **Stick directions** (`pitch`, `roll`, `throttle`, `yaw`): `--invert pitch,yaw,...` flips them.
- **Short or extended RC packets** (`--mode`): the drone streams video with either; which one it flies with is not confirmed.
  Extended mode shares one toggle bit for takeoff and land, so the handler sends it once there.
- **That a held takeoff flag is accepted**, and how the drone behaves for the 2 s after it.
- The relay sends telemetry only to the most recent client address: only one controller machine at a time.

## In the database (read-only)

`drone_control/publish_db.py` copies the real drone's state and video into the SpacetimeDB the console reads, next to the
simulation (the sim stays the main data; the real drone shows up as an extra "REAL E58" tile in the Feeds strip, a row in the
Drones tab, and a focus view). It reads what `imu/live.py` (port 8766) and the controller (port 8770, optional) already serve,
and writes only `real/status` (JSON, 2 Hz) and `feed/jpgreal` (the camera as a JPEG). It cannot send the drone anything.

```
python drone_control/publish_db.py --db http://127.0.0.1:3000      # on the machine that runs the sim: it needs the sim's DB identity
```

If the live page stops delivering, the row says `online: false` and the console greys the tile. Flight commands are deliberately
not routed through the database: it has no login, and anyone who could reach it could otherwise make the drone take off.
