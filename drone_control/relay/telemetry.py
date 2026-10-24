"""Side-channel telemetry. The relayed drone traffic is never modified; extra info rides here."""
from __future__ import annotations

import json
import math
import os
import socket
import sys
import time
from typing import Callable, Optional

Enricher = Callable[[], dict]


def decode_rc(data: bytes) -> Optional[dict]:
    """Decode a wifi_cam RC packet (8-byte short or 20-byte extended), else None."""
    if len(data) == 8 and data[0] == 0x66 and data[7] == 0x99:
        r, p, t, y, flags = data[1:6]
        return {"mode": "short", "roll": r, "pitch": p, "throttle": t, "yaw": y, "flags": flags}
    if len(data) == 20 and data[0] == 0x66 and data[1] == 0x14 and data[19] == 0x99:
        r, p, t, y, f1, f2 = data[2:8]
        return {"mode": "extended", "roll": r, "pitch": p, "throttle": t, "yaw": y, "flags": f1, "flags2": f2}
    return None


class Telemetry:
    def __init__(self, enrichers: list[Enricher] | None = None) -> None:
        self.enrichers = enrichers or []
        self.seq = 0
        self.counters = {"up_pkts": 0, "up_bytes": 0, "down_pkts": 0, "down_bytes": 0,
                         "rc_pkts": 0, "video_pkts": 0, "dropped_no_session": 0}
        self.last_rc: Optional[dict] = None
        self.last_rc_ts: Optional[float] = None
        self.sessions = 0
        self.started = time.time()

    def on_up(self, port_kind: str, data: bytes) -> None:
        c = self.counters
        c["up_pkts"] += 1
        c["up_bytes"] += len(data)
        if port_kind == "cmd":
            rc = decode_rc(data)
            if rc:
                c["rc_pkts"] += 1
                self.last_rc, self.last_rc_ts = rc, time.time()

    def on_down(self, port_kind: str, data: bytes) -> None:
        c = self.counters
        c["down_pkts"] += 1
        c["down_bytes"] += len(data)
        if port_kind == "video":
            c["video_pkts"] += 1

    def snapshot(self) -> dict:
        self.seq += 1
        extra: dict = {}
        for fn in self.enrichers:
            try:
                extra.update(fn())
            except Exception as e:  # an enricher must never break the relay
                extra[f"{getattr(fn, '__name__', 'enricher')}_error"] = repr(e)
        now = time.time()
        return {
            "ts": now,
            "seq": self.seq,
            "uptime_s": round(now - self.started, 1),
            "relay": {**self.counters, "sessions": self.sessions},
            "rc": self.last_rc,
            "rc_age_s": None if self.last_rc_ts is None else round(now - self.last_rc_ts, 3),
            "extra": extra,
        }


class Sinks:
    """Write snapshots as JSON lines to stdout / a file / a UDP endpoint."""

    def __init__(self, udp: tuple[str, int] | None, jsonl_path: str | None, to_stdout: bool) -> None:
        self.udp = udp
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if udp else None
        self.fh = open(jsonl_path, "a", buffering=1) if jsonl_path else None
        self.to_stdout = to_stdout

    def emit(self, snap: dict) -> None:
        line = json.dumps(snap, separators=(",", ":"))
        if self.sock and self.udp:
            try:
                self.sock.sendto(line.encode(), self.udp)
            except OSError:
                pass
        if self.fh:
            self.fh.write(line + "\n")
        if self.to_stdout:
            print(line, flush=True)


# ---- enrichers -------------------------------------------------------------
def host_enricher() -> dict:
    out: dict = {"load1": os.getloadavg()[0]}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            out["cpu_temp_c"] = int(f.read()) / 1000.0
    except OSError:
        pass
    return {"host": out}


def fake_imu_enricher() -> dict:
    """Synthetic IMU so the pipeline can be verified before hardware exists."""
    t = time.time()
    return {"imu": {"fake": True,
                    "accel_g": [0.0, 0.0, 1.0],
                    "gyro_dps": [round(10 * math.sin(t), 3), 0.0, 0.0]}}
