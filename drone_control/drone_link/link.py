"""UDP link to the drone: periodic RC on 8090, stream start on 8080, receive stats."""
from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field

from . import packets as P


@dataclass
class LinkStats:
    tx_packets: int = 0
    rx_packets: int = 0
    rx_bytes: int = 0
    first_rx_ts: float | None = None
    last_rx_ts: float | None = None
    rx_sizes: dict[int, int] = field(default_factory=dict)


class DroneLink:
    """Sends RC at `rate_hz` and tallies video datagrams.

    mode: "short" (8-byte) or "extended" (20-byte, camera_type 2 drones).
    Axes 0..255, 128 centred. One-shot flags ride on the next packet only.
    """

    def __init__(self, ip: str = P.DRONE_IP, rate_hz: float = 40.0, mode: str = "short",
                 video_port: int = P.VIDEO_PORT, cmd_port: int = P.CMD_PORT) -> None:
        if mode not in ("short", "extended"):
            raise ValueError(mode)
        self.ip, self.mode, self.period = ip, mode, 1.0 / rate_hz
        self.video_port, self.cmd_port = video_port, cmd_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.sock.settimeout(0.05)
        self.stats = LinkStats()
        self.on_video_datagram = None  # callback(bytes)
        self._axes = [P.AXIS_MID] * 4  # roll, pitch, throttle, yaw
        self._f1 = self._f2 = 0
        self._persist2 = 0  # extended flags2 (headless/alt-hold) stay latched
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self.sock.sendto(P.STREAM_START, (self.ip, self.video_port))
        for target in (self._tx_loop, self._rx_loop, self._keepalive_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def close(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
        try:
            self.sock.sendto(P.STREAM_STOP, (self.ip, self.video_port))
        except OSError:
            pass
        self.sock.close()

    def set_axes(self, roll=P.AXIS_MID, pitch=P.AXIS_MID, throttle=P.AXIS_MID, yaw=P.AXIS_MID) -> None:
        with self._lock:
            self._axes = [roll, pitch, throttle, yaw]

    def takeoff(self) -> None:
        self._flag(P.FLAG_TAKEOFF, P.EXT_TAKEOFF_OR_LAND)

    def land(self) -> None:
        self._flag(P.FLAG_LAND, P.EXT_TAKEOFF_OR_LAND)

    def emergency_stop(self) -> None:
        self._flag(P.FLAG_EMERGENCY, P.EXT_EMERGENCY)

    def calibrate(self) -> None:
        self._flag(P.FLAG_CALIBRATE, P.EXT_CALIBRATE)

    def flip(self) -> None:
        self._flag(P.FLAG_FLIP, P.EXT_FLIP)

    def _flag(self, short: int, ext: int) -> None:
        with self._lock:
            self._f1 |= short if self.mode == "short" else ext

    def build(self) -> bytes:
        with self._lock:
            roll, pitch, throttle, yaw = self._axes
            f1, self._f1 = self._f1, 0
            f2 = self._persist2
        if self.mode == "short":
            return P.build_short_packet(roll, pitch, throttle, yaw, f1)
        return P.build_extended_packet(roll, pitch, throttle, yaw, f1, f2)

    def _tx_loop(self) -> None:
        next_t = time.monotonic()
        while not self._stop.is_set():
            try:
                self.sock.sendto(self.build(), (self.ip, self.cmd_port))
                self.stats.tx_packets += 1
            except OSError:
                pass
            next_t += self.period
            time.sleep(max(0.0, next_t - time.monotonic()))

    def _keepalive_loop(self) -> None:
        # Resend stream start until video flows, then every 5 s.
        while not self._stop.wait(0.5 if self.stats.rx_packets == 0 else 5.0):
            try:
                self.sock.sendto(P.STREAM_START, (self.ip, self.video_port))
            except OSError:
                pass

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            now = time.monotonic()
            s = self.stats
            s.rx_packets += 1
            s.rx_bytes += len(data)
            s.first_rx_ts = s.first_rx_ts or now
            s.last_rx_ts = now
            s.rx_sizes[len(data)] = s.rx_sizes.get(len(data), 0) + 1
            if self.on_video_datagram:
                self.on_video_datagram(data)
