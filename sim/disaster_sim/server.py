"""WebSocket server streaming the simulation to the browser viewer.

    uvicorn disaster_sim.server:app --port 8000
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Request, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import SimConfig
from .sysmon import SysMon
from .protocol import make_stream, feed_message, state_message, world_message
from .sim import Simulation

LOOP_HZ = 60
BROADCAST_HZ = 20
SEEN_EVERY = 10  # proper-scan time deltas every Nth broadcast (2 Hz)
FEED_HZ = 4
SIM_SLICE_S = 0.05  # the sim thread works at most this long before re-checking the clock


def dumps(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


class SimServer:
    def __init__(self):
        self.sim = Simulation(SimConfig())
        self.pub_on = bool(os.environ.get("STDB_URL"))   # SpacetimeDB is on: its publisher is the only reader of the map cursors
        self.stream = make_stream(self.sim)
        self.running = True
        self.speed = 1.0
        self.clients: dict[WebSocket, int | None] = {}  # socket -> selected drone (camera feed)
        self.event_idx = 0
        self.rtf = 0.0  # achieved real-time factor
        self.mon = SysMon()
        self.loop_ms = 0.0  # CPU time the server loop spends per tick
        self.dirty_world = False
        self.broadcasts = 0
        # The simulation steps in its own thread so planning, physics and fusion never compete
        # with the websocket loop. `lock` is held per step and while a message is assembled
        # from the sim, so a broadcast always sees a consistent state.
        self.lock = threading.RLock()
        self._stop = False
        self._thread = threading.Thread(target=self._sim_loop, name="sim", daemon=True)

    def start(self) -> None:
        sys.setswitchinterval(0.0005)  # hand the GIL to the web loop quickly
        self._thread.start()

    def _sim_loop(self) -> None:
        debt, last, steps = 0.0, time.perf_counter(), 0
        window: list[tuple[float, float]] = []
        while not self._stop:
            now = time.perf_counter()
            wall_dt, last = now - last, now
            sim_t0 = self.sim.t
            if self.running:
                debt = min(debt + wall_dt * self.speed, 2.0)
                t_start = now
                while debt >= self.sim.dt and time.perf_counter() - t_start < SIM_SLICE_S and not self._stop:
                    with self.lock:
                        self.sim.step()
                    debt -= self.sim.dt
                    steps += 1
                    if steps % 5 == 0:
                        time.sleep(0.0002)  # a breath for the web loop (it needs the lock and the GIL)
                self.loop_ms = self.loop_ms * 0.9 + (time.perf_counter() - t_start) * 1000 * 0.1
            else:
                debt = 0.0
            window.append((now, self.sim.t - sim_t0 if self.running else 0.0))
            window = [(t, d) for (t, d) in window if now - t < 1.0]
            self.rtf = sum(d for _, d in window)
            if not self.running or debt < self.sim.dt:
                time.sleep(0.001)

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
            with self.lock:
                self.sim.advance(msg.get("seconds", 0.5))
        elif cmd == "reset":
            with self.lock:
                cfg = self.sim.cfg.updated(**msg.get("config", {}))
                self.sim.reset(cfg)
                self.stream = make_stream(self.sim)
                self.event_idx = 0
                self.dirty_world = True

    def snapshot(self) -> dict:
        with self.lock:
            return state_message(self.sim, self.stream, 0, self.extra(), True, full=True, with_map=not self.pub_on)

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
        last_broadcast = last_feed = 0.0
        while True:
            now = time.perf_counter()
            if self.dirty_world:
                self.dirty_world = False
                with self.lock:
                    world = world_message(self.sim)
                    snap = self.snapshot()
                    if not self.pub_on:
                        self.stream.deltas()  # advance the shared cursor past the snapshot
                        self.stream.seen()
                    self.event_idx = len(self.sim.master.events)
                await self.broadcast(world)
                await self.broadcast(snap)
            elif self.clients and now - last_broadcast >= 1.0 / BROADCAST_HZ:
                last_broadcast = now
                self.broadcasts += 1
                with self.lock:
                    msg = state_message(self.sim, self.stream, self.event_idx, self.extra(),
                                        with_seen=self.broadcasts % SEEN_EVERY == 0, with_map=not self.pub_on)
                    self.event_idx = len(self.sim.master.events)
                await self.broadcast(msg)
            if self.clients and now - last_feed >= 1.0 / FEED_HZ:
                last_feed = now
                for ws, drone in list(self.clients.items()):
                    if drone is not None:
                        with self.lock:
                            fm = feed_message(self.sim, int(drone))
                        await self.send(ws, dumps(fm))
            await asyncio.sleep(max(0.0, 1.0 / LOOP_HZ - (time.perf_counter() - now)))


server = SimServer()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    server.start()
    if os.environ.get("STDB_URL"):   # serve the live state through SpacetimeDB too
        from .stdb import StdbPublisher
        server.pub = StdbPublisher(server, os.environ["STDB_URL"], os.environ.get("STDB_DB", "swarm"))
    task = asyncio.create_task(server.run())
    yield
    server._stop = True
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    with server.lock:
        world = world_message(server.sim)
    await ws.send_text(dumps(world))
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


@app.get("/config")
async def config() -> dict:
    """Where the viewer should read its data from: SpacetimeDB when the server publishes into it."""
    return {"source": "db" if server.pub_on else "ws"}


@app.get("/stdb")
async def stdb_stats() -> dict:
    pub = getattr(server, "pub", None)
    return pub.stats() if pub else {"enabled": False}


@app.get("/entries")
async def entries() -> list:
    """Every entry point with how it was measured and how the attempts went."""
    out = []
    for e in server.sim.master.entries:
        out.append({"id": e.id, "side": e.side, "center": [round(float(v), 2) for v in e.center], "w": round(float(e.w), 2),
                    "h": round(float(e.h), 2), "fitted": e.fitted, "confirmed": e.confirmed, "quality": round(e.quality, 2),
                    "rect": None if e.rect is None else [e.rect[0], round(e.rect[1], 2), [round(v, 2) for v in e.rect[2]],
                                                         [round(v, 2) for v in e.rect[3]]],
                    "fails": e.fails, "ok": e.ok, "retired": e.retired, "blocked": e.blocked, "fail_log": e.fail_log[-6:]})
    return out


@app.get("/checks")
async def checks() -> list:
    """The gap / opening checks: what state each is in and why it may be waiting."""
    m = server.sim.master
    return [{"id": q["id"], "prio": q["prio"], "entry": q.get("entry"), "side": q["side"], "state": q["state"], "tries": q["tries"],
             "looks": q["looks"], "center": [round(float(v), 1) for v in q["center"]], "drone": q.get("drone"),
             "retry_in": round(max(0.0, q.get("retry_t", 0.0) - m.t_now), 1), "why": q.get("why", "")} for q in m.suspects if q["prio"] == 0 or q["state"] != "new"][:60]


@app.get("/meshdebug")
async def meshdebug(cid: int = -1, all: int = 0) -> dict:
    """Chunks that hold signed-distance data, with how much of it is near a surface and what their mesh is:
    a chunk with surface voxels and no faces is a hole in the viewer."""
    core = getattr(server.sim, "core", None)
    if core is None:
        return {"error": "no rust core"}
    if cid >= 0:
        return {"cid": cid, "grid": [None if v != v else round(v, 3) for v in core.tsdf_chunk(cid)]}
    rows = core.tsdf_stats()
    nc = server.sim.master.surface.core.mesh_totals()
    holes = [r for r in rows if r[2] > 200 and r[4] < 1]
    if all:
        return {"rows": [list(map(int, r)) for r in rows]}
    return {"chunks_with_data": len(rows), "holes": len(holes), "totals": [int(v) for v in nc],
            "hole_rows": [list(map(int, r)) for r in holes[:60]], "dirty": int(sum(r[3] for r in rows)),
            "sample": [list(map(int, r)) for r in rows[:30]]}


@app.get("/profile")
async def profile(secs: float = 20.0, thread: str = "sim") -> dict:
    """Where the sim thread spends its time: a 100 Hz stack sampler (cumulative % per function,
    and the busiest lines). `curl http://host:8000/profile?secs=20`."""
    ident = next((t.ident for t in threading.enumerate() if t.name == thread), None)
    if ident is None:
        return {"error": f"no thread {thread!r}", "threads": [t.name for t in threading.enumerate()]}
    cum, own, total = collections.Counter(), collections.Counter(), 0
    end = time.time() + min(secs, 120.0)
    while time.time() < end:
        f = sys._current_frames().get(ident)
        stack = []
        while f is not None:
            stack.append(f"{f.f_code.co_filename.rsplit('/', 1)[-1]}:{f.f_code.co_name}:{f.f_lineno}")
            f = f.f_back
        if stack:
            total += 1
            own[stack[0]] += 1
            for k in set(stack):
                cum[k] += 1
        await asyncio.sleep(0.01)
    pct = lambda c, n: {k: round(100 * v / max(total, 1), 1) for k, v in c.most_common(n)}
    return {"samples": total, "cumulative": pct(cum, 40), "self": pct(own, 15)}


@app.post("/clienterr")
async def client_error(request: Request) -> dict:
    """Browser-side errors and diagnostics, so a blank viewer can be debugged from the server log."""
    print("CLIENT:", (await request.body()).decode("utf8", "replace")[:2000], flush=True)
    return {"ok": True}


_dist = Path(__file__).resolve().parents[2] / "ui" / "viewer" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
