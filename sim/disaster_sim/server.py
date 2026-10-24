"""WebSocket server streaming the simulation to the browser viewer.

    uvicorn disaster_sim.server:app --port 8000
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import SimConfig
from .protocol import snapshot_message, state_message, world_message
from .sim import Simulation

LOOP_HZ = 60
BROADCAST_HZ = 20
SEEN_EVERY = 10  # send the last-seen grid every Nth broadcast (2 Hz)
MAX_COMPUTE_PER_TICK = 0.012  # seconds of CPU per loop tick, keeps the socket responsive


class SimServer:
    def __init__(self):
        self.sim = Simulation(SimConfig())
        self.running = True
        self.speed = 1.0
        self.clients: set[WebSocket] = set()
        self.map_tick = -1
        self.event_idx = 0
        self.rtf = 0.0  # achieved real-time factor
        self.dirty_world = False
        self.broadcasts = 0

    def extra(self) -> dict:
        return {"running": self.running, "speed": self.speed, "rtf": round(self.rtf, 2)}

    def handle(self, msg: dict) -> None:
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
            self.map_tick = -1
            self.event_idx = 0
            self.dirty_world = True

    async def send(self, ws: WebSocket, payload: dict) -> bool:
        try:
            await ws.send_text(json.dumps(payload, separators=(",", ":")))
            return True
        except Exception:
            return False

    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        text = json.dumps(payload, separators=(",", ":"))
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def run(self) -> None:
        sim_debt = 0.0
        last = time.perf_counter()
        last_broadcast = 0.0
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
            else:
                sim_debt = 0.0
                rtf_window.append((now, 0.0))
            rtf_window = [(t, d) for (t, d) in rtf_window if now - t < 1.0]
            self.rtf = sum(d for _, d in rtf_window)

            if self.dirty_world:
                self.dirty_world = False
                await self.broadcast(world_message(self.sim))
                await self.broadcast(snapshot_message(self.sim, self.extra()))
                self.map_tick = self.sim.master.tick
                self.event_idx = len(self.sim.master.events)
            elif now - last_broadcast >= 1.0 / BROADCAST_HZ:
                last_broadcast = now
                self.broadcasts += 1
                msg = state_message(self.sim, self.map_tick, self.event_idx, self.extra(),
                                    include_seen=self.broadcasts % SEEN_EVERY == 0)
                self.map_tick = self.sim.master.tick
                self.event_idx = len(self.sim.master.events)
                await self.broadcast(msg)
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
    await server.send(ws, world_message(server.sim))
    # The snapshot carries the full map; later diffs come from the shared broadcast.
    await server.send(ws, snapshot_message(server.sim, server.extra()))
    server.clients.add(ws)
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "control":
                server.handle(msg)
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        server.clients.discard(ws)


_dist = Path(__file__).resolve().parents[2] / "ui" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
