"""WebSocket server streaming the simulation to the browser viewer.

    uvicorn disaster_sim.server:app --port 8000
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Request, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import SimConfig
from .sysmon import SysMon
from .protocol import MapStream, feed_message, state_message, world_message
from .sim import Simulation

LOOP_HZ = 60
BROADCAST_HZ = 20
SEEN_EVERY = 10  # proper-scan time deltas every Nth broadcast (2 Hz)
FEED_HZ = 4
MAX_COMPUTE_PER_TICK = 0.012  # seconds of CPU per loop tick, keeps the socket responsive


def dumps(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


class SimServer:
    def __init__(self):
        self.sim = Simulation(SimConfig())
        self.stream = MapStream(self.sim)
        self.running = True
        self.speed = 1.0
        self.clients: dict[WebSocket, int | None] = {}  # socket -> selected drone (camera feed)
        self.event_idx = 0
        self.rtf = 0.0  # achieved real-time factor
        self.mon = SysMon()
        self.loop_ms = 0.0  # CPU time the server loop spends per tick
        self.dirty_world = False
        self.broadcasts = 0

    def extra(self) -> dict:
        return {"running": self.running, "speed": self.speed, "rtf": round(self.rtf, 2), "sys": self.mon.data,
                "loop_ms": round(self.loop_ms, 1)}

    def handle(self, ws: WebSocket, msg: dict) -> None:
        if msg.get("type") == "select":
            self.clients[ws] = msg.get("drone")
            return
        cmd = msg.get("cmd")
        if cmd == "play":
            self.running = True
        elif cmd == "pause":
            self.running = False
        elif cmd == "toggle":
            self.running = not self.running
        elif cmd == "speed":
            self.speed = float(min(max(msg.get("value", 1.0), 0.1), 16.0))
        elif cmd == "step":
            self.sim.advance(msg.get("seconds", 0.5))
        elif cmd == "reset":
            cfg = self.sim.cfg.updated(**msg.get("config", {}))
            self.sim.reset(cfg)
            self.stream = MapStream(self.sim)
            self.event_idx = 0
            self.dirty_world = True

    def snapshot(self) -> dict:
        return state_message(self.sim, self.stream, 0, self.extra(), True, full=True)

    async def send(self, ws: WebSocket, text: str) -> bool:
        try:
            await ws.send_text(text)
            return True
        except Exception:
            self.clients.pop(ws, None)
            return False

    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        text = dumps(payload)
        for ws in list(self.clients):
            await self.send(ws, text)

    async def run(self) -> None:
        sim_debt = 0.0
        last = time.perf_counter()
        last_broadcast = last_feed = 0.0
        rtf_window: list[tuple[float, float]] = []
        while True:
            now = time.perf_counter()
            wall_dt, last = now - last, now
            if self.running:
                sim_debt = min(sim_debt + wall_dt * self.speed, 1.0)
                t_start, sim_t0 = time.perf_counter(), self.sim.t
                while sim_debt >= self.sim.dt and time.perf_counter() - t_start < MAX_COMPUTE_PER_TICK:
                    self.sim.step()
                    sim_debt -= self.sim.dt
                rtf_window.append((now, self.sim.t - sim_t0))
                self.loop_ms = self.loop_ms * 0.9 + (time.perf_counter() - t_start) * 1000 * 0.1
            else:
                sim_debt = 0.0
                rtf_window.append((now, 0.0))
            rtf_window = [(t, d) for (t, d) in rtf_window if now - t < 1.0]
            self.rtf = sum(d for _, d in rtf_window)

            if self.dirty_world:
                self.dirty_world = False
                await self.broadcast(world_message(self.sim))
                await self.broadcast(self.snapshot())
                self.stream.deltas()  # advance the shared cursor past the snapshot
                self.stream.seen()
                self.event_idx = len(self.sim.master.events)
            elif self.clients and now - last_broadcast >= 1.0 / BROADCAST_HZ:
                last_broadcast = now
                self.broadcasts += 1
                msg = state_message(self.sim, self.stream, self.event_idx, self.extra(),
                                    with_seen=self.broadcasts % SEEN_EVERY == 0)
                self.event_idx = len(self.sim.master.events)
                await self.broadcast(msg)
            if self.clients and now - last_feed >= 1.0 / FEED_HZ:
                last_feed = now
                for ws, drone in list(self.clients.items()):
                    if drone is not None:
                        await self.send(ws, dumps(feed_message(self.sim, int(drone))))
            await asyncio.sleep(max(0.0, 1.0 / LOOP_HZ - (time.perf_counter() - now)))


server = SimServer()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(server.run())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    await ws.send_text(dumps(world_message(server.sim)))
    # The snapshot carries the full map; later deltas come from the shared broadcast.
    await ws.send_text(dumps(server.snapshot()))
    server.clients[ws] = None
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") in ("control", "select"):
                server.handle(ws, msg)
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        server.clients.pop(ws, None)


@app.post("/clienterr")
async def client_error(request: Request) -> dict:
    """Browser-side errors and diagnostics, so a blank viewer can be debugged from the server log."""
    print("CLIENT:", (await request.body()).decode("utf8", "replace")[:2000], flush=True)
    return {"ok": True}


_dist = Path(__file__).resolve().parents[2] / "ui" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
