#!/usr/bin/env python3
"""Verify the drone speaks WiFi_CAM. Props off. Sends neutral RC only; never takeoff."""
import argparse
import subprocess
import sys
import time

from drone_link import DroneLink
from drone_link.video import FrameStats
from drone_link.packets import DRONE_IP


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=DRONE_IP)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--video-port", type=int, default=8080)
    ap.add_argument("--cmd-port", type=int, default=8090)
    ap.add_argument("--rate", type=float, default=40.0)
    ap.add_argument("--mode", choices=["short", "extended"], default="short")
    a = ap.parse_args()

    ping = subprocess.run(["ping", "-c", "3", "-W", "1", a.ip], capture_output=True, text=True)
    print(ping.stdout.strip().splitlines()[-2:] or ping.stderr)

    link = DroneLink(a.ip, a.rate, a.mode, a.video_port, a.cmd_port)
    frames = FrameStats()
    link.on_video_datagram = frames.feed
    t0 = time.monotonic()
    link.start()
    time.sleep(a.seconds)
    link.close()
    s, dt = link.stats, time.monotonic() - t0
    print(f"tx {s.tx_packets} ({s.tx_packets / dt:.1f}/s)  rx {s.rx_packets} datagrams, "
          f"{s.rx_bytes / dt / 1024:.0f} KiB/s")
    print("rx datagram sizes:", sorted(s.rx_sizes.items(), key=lambda kv: -kv[1])[:4])
    if s.first_rx_ts:
        print(f"first rx after {s.first_rx_ts - t0:.3f}s")
    print("frames:", frames.summary())
    ok = s.rx_packets > 0
    print("VERDICT:", "wifi_cam video flowing" if ok else "no video - protocol unverified")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
