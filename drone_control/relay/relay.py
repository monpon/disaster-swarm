#!/usr/bin/env python3
"""Transparent UDP relay for the E58 (wifi_cam): clients -> relay -> drone.

One upstream socket per client IP, shared by video and command traffic, because the drone
answers to the source port it was contacted from. Drone traffic passes through unchanged;
counters, decoded RC and extra fields are published on the telemetry side channel.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

from .telemetry import Sinks, Telemetry, fake_imu_enricher, host_enricher
from .transcode import FrameAssembler, Transcoder

log = logging.getLogger("relay")
SESSION_IDLE_S = 30.0


class Session:
    """State for one client IP: an upstream socket plus where to send each drone port's replies."""

    def __init__(self, relay: "Relay", client_ip: str) -> None:
        self.relay, self.client_ip = relay, client_ip
        self.transport: asyncio.DatagramTransport | None = None
        self.reply_to: dict[int, tuple[str, int]] = {}  # drone port -> client addr
        self.last_seen = time.monotonic()
        self.assembler = FrameAssembler()

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: _Upstream(self), local_addr=(self.relay.upstream_bind, 0))

    def close(self) -> None:
        if self.transport:
            self.transport.close()


class _Upstream(asyncio.DatagramProtocol):
    def __init__(self, session: Session) -> None:
        self.s = session

    def datagram_received(self, data: bytes, addr) -> None:
        relay = self.s.relay
        kind = relay.kind_by_drone_port.get(addr[1])
        client = self.s.reply_to.get(addr[1])
        if kind is None or client is None or relay.listeners.get(kind) is None:
            relay.telemetry.counters["dropped_no_session"] += 1
            return
        relay.telemetry.on_down(kind, data)
        self.s.last_seen = time.monotonic()
        tc = relay.transcoder
        if tc is not None and kind == "video" and len(data) > 8:
            done = self.s.assembler.feed(data)
            if done:
                loop, tx = relay.loop, relay.listeners[kind]
                tc.submit(done[0], done[1], lambda pkts: loop.call_soon_threadsafe(
                    lambda: [tx.sendto(p, client) for p in pkts]))
            return                                  # video is re-encoded: originals are not forwarded
        relay.listeners[kind].sendto(data, client)


class _Listener(asyncio.DatagramProtocol):
    def __init__(self, relay: "Relay", kind: str) -> None:
        self.relay, self.kind = relay, kind
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.ensure_future(self.relay.from_client(self.kind, data, addr))


class Relay:
    def __init__(self, drone_ip: str, ports: dict[str, tuple[int, int]], listen_ip: str,
                 upstream_bind: str, telemetry: Telemetry, sinks: Sinks, interval: float,
                 transcoder: Transcoder | None = None) -> None:
        # ports: kind -> (listen_port, drone_port)
        self.drone_ip, self.ports, self.listen_ip = drone_ip, ports, listen_ip
        self.upstream_bind, self.telemetry, self.sinks, self.interval = upstream_bind, telemetry, sinks, interval
        self.transcoder = transcoder
        self.loop = None
        self.kind_by_drone_port = {dp: k for k, (_, dp) in ports.items()}
        self.listeners: dict[str, asyncio.DatagramTransport] = {}
        self.sessions: dict[str, Session] = {}
        self._opening: dict[str, asyncio.Future] = {}

    async def from_client(self, kind: str, data: bytes, addr) -> None:
        s = self.sessions.get(addr[0])
        if s is None:
            fut = self._opening.get(addr[0])
            if fut is None:
                fut = self._opening[addr[0]] = asyncio.ensure_future(self._new_session(addr[0]))
            s = await fut
        s.last_seen = time.monotonic()
        drone_port = self.ports[kind][1]
        s.reply_to[drone_port] = addr
        self.telemetry.on_up(kind, data)
        s.transport.sendto(data, (self.drone_ip, drone_port))

    async def _new_session(self, client_ip: str) -> Session:
        s = Session(self, client_ip)
        await s.open()
        self.sessions[client_ip] = s
        self._opening.pop(client_ip, None)
        self.telemetry.sessions = len(self.sessions)
        log.info("session open: %s", client_ip)
        return s

    async def run(self) -> None:
        loop = self.loop = asyncio.get_running_loop()
        for kind, (lport, _) in self.ports.items():
            transport, _ = await loop.create_datagram_endpoint(
                lambda k=kind: _Listener(self, k), local_addr=(self.listen_ip, lport))
            self.listeners[kind] = transport
            log.info("listening %s on %s:%d -> %s:%d", kind, self.listen_ip, lport, self.drone_ip, self.ports[kind][1])
        while True:
            await asyncio.sleep(self.interval)
            now = time.monotonic()
            for ip, s in list(self.sessions.items()):
                if now - s.last_seen > SESSION_IDLE_S:
                    s.close()
                    del self.sessions[ip]
                    log.info("session expired: %s", ip)
            self.telemetry.sessions = len(self.sessions)
            self.sinks.emit(self.telemetry.snapshot())


def parse_hostport(v: str) -> tuple[str, int]:
    host, _, port = v.rpartition(":")
    return host, int(port)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drone-ip", default="192.168.4.153")
    ap.add_argument("--drone-video-port", type=int, default=8080)
    ap.add_argument("--drone-cmd-port", type=int, default=8090)
    ap.add_argument("--listen-ip", default="0.0.0.0")
    ap.add_argument("--listen-video-port", type=int, default=8080)
    ap.add_argument("--listen-cmd-port", type=int, default=8090)
    ap.add_argument("--upstream-bind", default="0.0.0.0", help="local address for the drone-facing sockets")
    ap.add_argument("--telemetry-udp", type=parse_hostport, default=("127.0.0.1", 9100), metavar="HOST:PORT")
    ap.add_argument("--no-telemetry-udp", action="store_true")
    ap.add_argument("--telemetry-jsonl", default=None)
    ap.add_argument("--stdout", action="store_true", help="print telemetry lines")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--downscale", default=None, metavar="WxH", help="re-encode video to this size, e.g. 320x240")
    ap.add_argument("--jpeg-quality", type=int, default=60)
    ap.add_argument("--fake-imu", action="store_true", help="add synthetic extra.imu to telemetry")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    enrichers = [host_enricher] + ([fake_imu_enricher] if a.fake_imu else [])
    tc = None
    if a.downscale:
        w, h = (int(x) for x in a.downscale.lower().split("x"))
        tc = Transcoder((w, h), a.jpeg_quality)
        enrichers.append(lambda: {"transcode": tc.summary()})
    relay = Relay(
        a.drone_ip,
        {"video": (a.listen_video_port, a.drone_video_port), "cmd": (a.listen_cmd_port, a.drone_cmd_port)},
        a.listen_ip, a.upstream_bind, Telemetry(enrichers),
        Sinks(None if a.no_telemetry_udp else a.telemetry_udp, a.telemetry_jsonl, a.stdout), a.interval, tc)
    try:
        asyncio.run(relay.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
