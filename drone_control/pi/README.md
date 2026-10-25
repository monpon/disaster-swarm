# Pi networking: relay + repeater

```
 client (phone / server)            Pi                               drone
 wifi "WIFI_8K__cc220c"  ──AP_IF──> REDIRECT ──> relay ──UPLINK_IF──> 192.168.4.153
 192.168.5.x                        :18080/:18090   |
                                                    └─> telemetry (UDP 9100, jsonl, stdout)
```

The relay never edits drone traffic. Added info (relay counters, decoded RC, host stats, later IMU)
goes out on the telemetry side channel as one JSON object per second under `extra`.

## 1. Verify on a laptop, no hardware (works now)

```sh
cd drone_control
PYTHONPATH=. python tests/test_relay.py          # DroneLink -> relay -> FakeDrone, asserts forwarding + telemetry
```

Manual, three terminals:

```sh
PYTHONPATH=. python -m relay.fake_drone --video-port 28080 --cmd-port 28090
PYTHONPATH=. python -m relay --drone-ip 127.0.0.2 --drone-video-port 28080 --drone-cmd-port 28090 \
    --listen-ip 127.0.0.1 --listen-video-port 18080 --listen-cmd-port 18090 --fake-imu --stdout
PYTHONPATH=. python probe.py --ip 127.0.0.1 --video-port 18080 --cmd-port 18090
PYTHONPATH=. python -m relay.tail                # pretty telemetry on UDP 9100
```

`--fake-imu` adds a synthetic `extra.imu`. A real IMU node later just adds another enricher in
`relay/telemetry.py`.

## 2. Through the real drone, still on one machine

Join the drone wifi, then relay on loopback and point the probe at the relay:

```sh
PYTHONPATH=. python -m relay --listen-ip 127.0.0.1 --listen-video-port 18080 --listen-cmd-port 18090 \
    --upstream-bind <your wlan0 ip> --stdout
PYTHONPATH=. python probe.py --ip 127.0.0.1 --video-port 18080 --cmd-port 18090
```

## 3. Pi repeater, single onboard radio (no dongle)

The one radio runs as a client of the drone (`wlan0`) and as an AP (`ap0`, virtual) at the same time.
Both must share a channel, so `repeater-up` joins the drone first, reads its channel, then starts the AP on it.

```sh
sudo cp pi/repeater.conf.example /etc/drone-repeater.conf
sudo pi/setup-repeater.sh        # one-time install
# do this from the Pi console or ethernet/tailscale-over-ethernet: wlan0 leaves your wifi
sudo repeater-up                 # prints the exact relay command
PYTHONPATH=. python -m relay --upstream-bind <wlan0 ip> --listen-video-port 18080 --listen-cmd-port 18090 --stdout
sudo repeater-down               # stop; then `nmcli con up <your wifi>`
```

Verify: join the Pi's AP from a laptop, run `probe.py --ip 192.168.4.153` there (default ports); video
should flow, and telemetry should show `video_pkts` / `rc_pkts` rising.

Notes: throughput is shared, relayed video crosses the radio twice (about 2x 324 KiB/s, fine). If the AP
fails to start, check `iw list | grep -A8 "valid interface combinations"` shows `managed` + `AP` with
`#channels <= 1` (true for Pi 3/4/5/Zero 2 W).

## Known risks

- Scripts are untested on hardware. Concurrent AP+STA on the onboard chip can be flaky; if it is, a USB dongle as `AP_IF` is the fallback.
- Run the setup over ethernet or a monitor: wlan0 leaves your current wifi.
- While the Pi is a drone client, the real drone's SSID and the Pi's AP share a name and channel; keep phones/laptops away from the real drone's AP or they may associate with it instead.
- The stock phone app may insist the wifi gateway is `192.168.4.153` (turbodrone docs/research/wifi_cam.md
  mentions a gateway comparison). The AP is on 192.168.5.0/24, so the stock app may refuse to connect.
  Scripts and ROS clients that send to 192.168.4.153 are fine. Fix if needed: put the drone-side radio in a
  network namespace and give the AP side the real 192.168.4.x addresses.
- Only one wifi client at a time can join the drone, so the drone is exclusive to the Pi once it is up.
