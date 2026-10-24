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
| ESP32-S3, v3 (receive thread) | not measured | | drone refused joins before it ran |

An earlier S3 v2 run with `readinto` produced 0% intact frames. That was a bug: MicroPython's `readinto` keeps
reading until the buffer is full, concatenating datagrams. Do not use it for UDP.

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
2. Treat the S3 as an optional small repeater or IMU node. To reach about 95% it needs the receive-thread change
   (written, untested) and probably a firmware build with a larger `CONFIG_LWIP_UDP_RECVMBOX_SIZE`, or a C rewrite.
3. The Pico 2 W has not been evaluated: it did not enumerate on any cable tried.

## 6. What is not verified

- Pi repeater scripts (`pi/`) have never run on a Pi. First-boot cloud-init config has not been booted.
- Concurrent AP + client on the Pi 3 radio.
- S3 v3, more than one client, runs longer than 10 s, latency.
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
