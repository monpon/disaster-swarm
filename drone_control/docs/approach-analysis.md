# Drone link: approach analysis (2026-10-24)

Goal: let a small computer on or near the drone control it, observe its traffic, and add information
(IMU, host stats) for a server, while optionally repeating the drone's wifi.

## 1. The drone speaks `wifi_cam`, not `wifi_uav`

The E58 is listed in turbodrone's README as "Tested / implementation unknown". Measured on the real drone:

| Check | `wifi_uav` | `wifi_cam` |
|---|---|---|
| Drone address | 192.168.169.1 (no answer) | 192.168.4.153 (gateway, ping 2 ms) |
| Video | no reply to start-stream | UDP 8080, 1472-byte datagrams after `42 76` |
| RC | n/a | UDP 8090, raw `66 .. 99` 8-byte (short) or 20-byte (extended) |

`drone_link/` implements this. Packet builders match turbodrone byte for byte for both modes.
Short vs extended RC mode is not yet confirmed against flight behaviour (the drone streams video with either).

## 2. Frame-level measurement

Datagram counts are misleading: the drone changes JPEG size between runs (185 to 296 datagrams/s at an identical
24.5 fps). `drone_link/video.py` counts whole frames instead. A frame is intact when its chunk count matches the
header and the reassembled JPEG starts with SOI and ends with EOI (turbodrone's rule). There is no retransmit in
the protocol, so one lost chunk (about 7 per frame) loses the frame: 5% packet loss is about 30% frame loss.

## 3. Results (10 s runs, one client, real drone)

| Path | Frames intact | Frames/s | Notes |
|---|---|---|---|
| Laptop direct to drone | 99.6%, 100% | 24.5 | baseline |
| Python relay on the laptop (loopback) | 95.5%, 99.2% | 23.3 to 24.4 | RC decoded, telemetry, 0 drops |
| ESP32-S3, MicroPython, v1 (poll loop) | 19.2% | 4.6 | 47 dropped sends |
| ESP32-S3, v2 (recv, GC off, send retries, pm off) | 71.4% | 17.6 | 0 drops, 0 retries, GC 1 ms |
| ESP32-S3, v3 (receive thread) | 86.1%, 80.3% | 21.2, 19.8 | 0 drops, 0 retries, longest loop gap 16 to 17 ms, receive queue depth never above 0 |

An earlier S3 v2 run with `readinto` produced 0% intact frames. That was a bug: MicroPython's `readinto` keeps
reading until the buffer is full, concatenating datagrams. Do not use it for UDP.

## 3a. Delivered video per path (summary of every real-drone run)

The drone sends 240x320 (portrait) JPEG frames, about 11.4 KB each, at 24.6 fps. Delivered rate varies run to run
because JPEG size varies (datagrams/s 185 to 296 at the same fps).

| Path | KiB/s delivered | Datagrams/s | Bytes/frame at client | Frames intact | fps |
|---|---|---|---|---|---|
| Direct to drone | 244 to 418 | 185 to 296 | 11,400 | 99.6 to 100% | 24.5 to 24.6 |
| Python relay (laptop) | 242 to 415 | 184 to 294 | 11,400 | 95.5 to 99.2% | 23.3 to 24.4 |
| Python relay, 320x240 q60 | 170 | 126 | 7,065 | 100% | 24.6 |
| Python relay, 240x320 q35 | 135 | 101 | 5,583 | 100% | 24.6 |
| Python relay, 120x160 q50 | 65 | 52 | 2,714 | 100% | 24.5 |
| ESP32-S3 v1 | 233 | 175 | n/a (most frames broken) | 19.2% | 4.6 |
| ESP32-S3 v2 | 237 | 175 | n/a | 71.4% | 17.6 |
| ESP32-S3 v3 | 271 to 274 | 200 to 204 | 11,543 | 86.1%, 80.3% | 21.2, 19.8 |

Note: KiB/s counts every datagram that reached the client, including those of broken frames, so it overstates usable
video on the lossy paths. Frames intact and fps are the metrics to compare.

## 3b. Throughput ceilings (1472-byte UDP datagrams)

What the drone needs: 190 to 300 datagrams/s, 240 to 420 KiB/s of video (direct runs), plus 40 RC packets/s.

| Path | Result | Notes |
|---|---|---|
| Python relay, laptop loopback (`scripts/bench_relay.py`) | 16,000 pkt/s, 22 MiB/s, 0.2% loss | software ceiling, no radio, laptop CPU. 50x the drone's rate. Not measured on a Pi 3. |
| S3 AP, laptop to S3 (`scripts/s3_bench.sh`) | 0% loss to 250 pkt/s (360 KiB/s); 1.7% at 500; 8% at 1000; saturates near 900 pkt/s (1.3 MiB/s) | AP-only, MicroPython sink. Excludes the drone leg and AP + STA contention. |
| S3 AP, S3 to laptop | 2,200 pkt/s, 3.1 MiB/s, 0% loss of what it sent | 7,561 send errors: the S3 saturates its own transmit buffers |

Reading: the S3 receive path is lossless only up to about 250 pkt/s, which is the drone's own rate (190 to 300 pkt/s,
in bursts). That fits the frame loss seen when the S3 receives from the drone (hypothesis: receive-queue overflow),
and it means the receive side, not the transmit side, is the S3's weak point. The real relay also splits one radio
between the drone link and the AP, so its ceiling is lower than these AP-only numbers.

## 3c. Downscaling video in the relay

`relay --downscale WxH --jpeg-quality Q` reassembles each JPEG frame, shrinks it, and re-chunks it in the drone's own
packet format (`relay/transcode.py`), so clients decode it unchanged. The drone link still carries full-size frames.

Measured fact: the drone's frames are already **240x320 (portrait), about 11.3 KB each**, so a 320x240 target does not
reduce the pixel count (it also swaps the aspect ratio and distorts). Real drone, Python relay on the laptop, 10 s:

| Output | Bytes/frame | Client KiB/s | Frames intact | fps | Transcode per frame (laptop) |
|---|---|---|---|---|---|
| native, direct to drone | 11,400 | 275 | 100% | 24.6 | n/a |
| 320x240, q60 (as requested) | 7,065 | 170 | 100% | 24.6 | 4.1 ms |
| 240x320, q35 | 5,583 | 135 | 100% | 24.6 | 1.6 ms |
| 120x160, q50 | 2,714 | 65 | 100% | 24.5 | 0.8 ms |

The savings come from re-encoding at lower quality, not from the resolution change. Smaller output only helps the
client leg: the drone still sends 11 KB frames to the relay. It does not fix the S3 receive loss. Frame budget at 24.6 fps
is 41 ms. Laptop transcode times will be several times slower on a Pi 3 (estimate, not measured).

Not done: the same benchmark on a Pi 3 (the SD card has not been flashed, so no Pi is available yet).

## 4. Approaches compared

| | Pi 3 + Python relay | ESP32-S3 MicroPython | Raspberry Pi Pico 2 W |
|---|---|---|---|
| AP + client on one radio | Linux, well trodden (untested here) | works (measured, channel 1) | MicroPython allows both interfaces; unreliable reports, not tested |
| Video integrity | 95 to 99% | 71% (v2) | not tested (board never enumerated) |
| Decode RC, telemetry, IMU | yes, written and tested | yes (parity code, IMU driver untested without hardware) | n/a |
| Stock phone app via repeater | possible (REDIRECT) | no | no |
| ROS / Docker | yes | micro-ROS in C only | micro-ROS in C only |
| Debuggability | ssh, logs, tcpdump | serial only | serial only |

Why the S3 loses frames (hypothesis, not proven): the drone sends about 7 chunks back to back, and the prebuilt
firmware's UDP receive queue (believed to be about 6 packets) overflows while the loop is busy sending. Evidence:
the S3 forwarded 1757 packets and the laptop received 1752, so the loss is between the drone and the S3.

## 5. Recommendation

1. Use the Pi 3 for the relay, repeater, ROS and IMU. It keeps 95 to 99% of frames and the code exists.
2. Treat the S3 as an optional small repeater or IMU node. The receive-thread change took it from 71% to 80 to 86%
   of frames. The rest looks like about 1% packet loss over the radio (the S3 forwarded 2018 to 2044 packets per run
   against about 2030 to 2060 sent by the drone, and the laptop received 7 fewer than the S3 sent). Software cannot repair
   that: the protocol has no retransmit. Going further would take a custom firmware build or a C rewrite, with no
   guarantee.
   JPEG downscaling cannot run on the S3 under MicroPython (no JPEG codec), so it stays a Pi/laptop feature.
3. The Pico 2 W has not been evaluated: it did not enumerate on any cable tried.

## 6. What is not verified

- Pi repeater scripts (`pi/`) have never run on a Pi. First-boot cloud-init config has not been booted.
- Concurrent AP + client on the Pi 3 radio.
- S3 v3 with more than two runs, more than one client, runs longer than 10 s, latency. Back-to-back S3 runs sometimes fail
  to rejoin the drone for a while (the drone seems to release the old client slowly).
- IMU drivers (`esp32/mpu.py`) and any Pi-side I2C reader.
- RC behaviour in flight (props were off for all tests).

## 7. Operational lessons

- Two of three USB cables were power-only: boards lit up but never enumerated.
- The drone accepts one wifi client. A leftover S3 connection blocked the laptop (auth status 17). The S3 `boot.py`
  and `scripts/s3_relay_test.sh` keep its wifi off outside tests.
- Joining the drone drops internet. Use `scripts/wifi_cycle.sh`: it always restores the previous network, then
  FridgeWiFi, then Cal Hacks 13.0.

## Reproduce

```sh
PYTHONPATH=. python tests/test_packets.py            # packet + frame-stats unit tests (or run the functions)
PYTHONPATH=. python tests/test_relay.py              # loopback end to end, no hardware
scripts/wifi_cycle.sh -- env PYTHONPATH=. python probe.py --seconds 10   # direct baseline
scripts/relay_real_test.sh                           # Python relay to the real drone
scripts/s3_relay_test.sh 10                          # S3 relay (see esp32/README.md)
PYTHONPATH=. python scripts/bench_relay.py            # Python relay ceiling, loopback
scripts/s3_bench.sh                                  # S3 AP throughput (no drone needed)
```
