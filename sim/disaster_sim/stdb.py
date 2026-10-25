"""Publishes the live simulation into SpacetimeDB (module `swarm_db`), where every viewer subscribes to it, and takes the
viewers' commands back out of it.

The publisher runs on its own thread: it builds its rows from the simulation (under the server's lock, briefly), compares them
with what it last sent and writes only what changed, over the database's HTTP API. The sim never waits for it. Rows (see
swarm_db/spacetimedb/src/lib.rs): `entity` keyed by path ("drone/3", "candidate/2", "entry/1", "metrics", "links", "targets",
"found", "history", "plan/<floor>", "world"), plus an append-only `event` log and a `cmd` queue the viewers write to.
"""
from __future__ import annotations

import http.client
import json
import os
import threading
import time
import traceback
import urllib.parse

import numpy as np

from .floorplan import floorplan
from .protocol import MAX_TARGETS, feed_arrays, preview_frames, world_message

PERIOD_S = 0.2  # entities are published at 5 Hz
CMD_PERIOD_S = 0.25
PLAN_PERIOD_S = 1.0
HISTORY_PERIOD_S = 5.0
FEED_PERIOD_S = 0.25
SELECT_TTL_S = 12.0
JPEG_PERIOD_S = 1 / 15   # the console's camera feeds: live views rendered this often
JPEG_MAX_DRONES = 6
JPEG_QUALITY = 80
VBLOCK = 4096   # voxels per vox/<b> and seen/<b> row
PBLOCK = 64   # points per pt/<b> row (small: point refinements are scattered, and a block is rewritten whole)
MAP_BUDGET = 1_200_000   # bytes of map blocks written per round (oldest first, so nothing starves)
POST_LIMIT = 1_400_000   # bytes of JSON per HTTP call
MESH_LIMIT = 16


def _dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


class StdbClient:
    """The few calls the publisher needs, over HTTP with a kept-alive connection."""

    def __init__(self, url: str, db: str):
        u = urllib.parse.urlparse(url)
        self.host, self.port, self.db = u.hostname, u.port or 3000, db
        self.conn: http.client.HTTPConnection | None = None
        self.token_path = os.path.expanduser("~/.swarm_stdb_token")
        self.token = open(self.token_path).read().strip() if os.path.exists(self.token_path) else None
        self.bytes = 0

    def _request(self, path: str, body: str):
        for attempt in (0, 1):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPConnection(self.host, self.port, timeout=15)
                headers = {"Content-Type": "application/json"}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"
                self.conn.request("POST", path, body=body, headers=headers)
                r = self.conn.getresponse()
                data = r.read()
                if self.token is None and r.getheader("spacetime-identity-token"):
                    self.token = r.getheader("spacetime-identity-token")
                    with open(self.token_path, "w") as f:
                        f.write(self.token)
                if r.status != 200:
                    raise RuntimeError(f"{path}: HTTP {r.status} {data[:200]!r}")
                self.bytes += len(body)
                return data
            except (OSError, http.client.HTTPException):
                self.conn = None
                if attempt:
                    raise

    def call(self, reducer: str, *args) -> None:
        self._request(f"/v1/database/{self.db}/call/{reducer}", _dumps(list(args)))

    def sql(self, query: str) -> list[list]:
        out = json.loads(self._request(f"/v1/database/{self.db}/sql", query))
        return out[0]["rows"] if out else []


class StdbPublisher:
    def __init__(self, server, url: str, db: str = "swarm"):
        self.server = server
        self.client = StdbClient(url, db)
        self.world_ver = 0
        self._b = None  # the building we last published
        self.sent: dict[str, str] = {}  # entity key -> the JSON last written
        self.event_idx = 0
        self._t_plan = self._t_hist = self._t_cmd = 0.0
        self.rounds = self.errors = 0
        self._claimed = False
        self.sel: dict[str, tuple] = {}   # viewer id -> (selected drone, when): whose camera feed to publish
        self._t_feed = 0.0
        self.jpeg_sent: dict[int, float] = {}   # drone -> t of the last frame sent as JPEG
        self.jpeg_client = StdbClient(url, db)
        self.m = None   # the map mirror (see _reset_map)
        self.last_ms = 0.0
        self.last_error = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="stdb", daemon=True)
        self._thread.start()
        self._jthread = threading.Thread(target=self._jpeg_run, name="stdb-jpeg", daemon=True)
        self._jthread.start()

    def stop(self) -> None:
        self._stop.set()

    def stats(self) -> dict:
        return {"rounds": self.rounds, "errors": self.errors, "last_ms": round(self.last_ms, 1), "mb_sent": round(self.client.bytes / 1e6, 1),
                "rows_cached": len(self.sent), "last_error": self.last_error}

    # ------------------------------------------------------------------ loop
    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                self._round()
                self.rounds += 1
            except Exception as e:  # the database being down must never take the sim with it
                self.errors += 1
                self.last_error = f"{type(e).__name__}: {e}"
                if self.errors <= 3:
                    traceback.print_exc()
                time.sleep(1.0)
            self.last_ms = (time.perf_counter() - t0) * 1000
            time.sleep(max(0.0, PERIOD_S - (time.perf_counter() - t0)))

    def _round(self) -> None:
        srv, now = self.server, time.time()
        world = plan = hist = None
        with srv.lock:
            sim = srv.sim
            if sim.b is not self._b:
                world = _dumps(world_message(sim))
                self._b = sim.b
                self.event_idx = 0
            items = self._entities(sim, srv.extra())
            events = sim.master.events[self.event_idx:]
            self.event_idx = len(sim.master.events)
            if now - self._t_plan >= PLAN_PERIOD_S or world is not None:
                self._t_plan, plan = now, floorplan(sim)
            if now - self._t_hist >= HISTORY_PERIOD_S or world is not None:
                self._t_hist = now
                step = max(1, len(sim.history) // 400)
                hist = _dumps(sim.history[::step])
            if world is not None:
                self._reset_map(sim)
            mesh = self._pull_map(sim)
            feeds = self._feeds(sim, now)
        c = self.client
        if not self._claimed:   # the first caller owns the write reducers; viewers can only submit commands
            c.call("claim_writer")
            self._claimed = True
        if world is not None:   # a new mission: forget the old rows
            c.call("clear_all")
            self.sent.clear()
            self.world_ver += 1
            c.call("put", "world", self.world_ver, world, "")
        changed = [[k, v] for k, v in items.items() if self.sent.get(k) != v]
        if changed:
            c.call("put_many", _dumps(changed))
            self.sent.update(changed)
        if events:
            c.call("add_events", _dumps([[e["t"], e["level"], e["text"]] for e in events]))
        if hist is not None and self.sent.get("history_all") != hist:
            self.sent["history_all"] = hist
            c.call("put", "history_all", 0, hist, "")
        if plan is not None:
            import base64
            meta = _dumps({k: plan[k] for k in ("x0", "y0", "w", "h", "story")})
            for k, f in enumerate(plan["floors"]):
                key = f"plan/{k}"
                if self.sent.get(key) != f:
                    self.sent[key] = f
                    c.call("put", key, 0, meta, base64.b64decode(f).hex())
        self._send_blobs(mesh, feeds)
        if now - self._t_cmd >= CMD_PERIOD_S:
            self._t_cmd = now
            self._commands()

    # ---------------------------------------------------------------- content
    def _entities(self, sim, extra: dict) -> dict[str, str]:
        m = sim.master
        items = {f"drone/{d['id']}": _dumps(d) for d in sim.drone_states()}
        items.update({f"candidate/{c.id}": _dumps(c.to_dict()) for c in m.candidates})
        items.update({f"entry/{e.id}": _dumps(e.to_dict()) for e in m.entries})
        items["metrics"] = _dumps({**sim.metrics(), **extra})
        items["links"] = _dumps(sim.radio_mesh())
        items["found"] = _dumps(sim.found_survivor_ids())
        items["targets"] = _dumps([[int(g["voxel"][0]), int(g["voxel"][1]), int(g["voxel"][2]),
                                    0 if g["tile"][0] == "frontier" else 1] for g in m.targets[:MAX_TARGETS]])
        items["history"] = _dumps(sim.history[-1] if sim.history else None)
        return items

    # --------------------------------------------------------------- commands
    def _commands(self) -> None:
        """Run what the viewers asked for (play, pause, speed, step, reset ...), then take it off the queue."""
        for seq, name, args in self.client.sql("SELECT * FROM cmd"):
            try:
                if name == "select":   # a viewer picked a drone: publish its camera feed while it keeps looking
                    a = json.loads(args)
                    ds = a.get("drones") if a.get("drones") is not None else [a.get("drone")]
                    self.sel[str(a.get("client", ""))] = ([d for d in ds if d is not None], time.time(), a.get("drones") is not None)
                    self.client.call("ack_cmd", seq)
                    continue
                msg = {"type": "control", "cmd": name, **(json.loads(args) if args else {})}
                self.server.handle(None, msg)
            except Exception:
                traceback.print_exc()
            self.client.call("ack_cmd", seq)

    # -------------------------------------------------------------- 3D map
    def _reset_map(self, sim) -> None:
        """A new mission: fresh mirrors and cursors (the first pull is a full one)."""
        n = sim.master.map.n
        nb = (n + VBLOCK - 1) // VBLOCK
        self.m = {
            "full": True, "tick": -1, "sent_chunks": {}, "sent_n": 0,
            "vrgb": np.zeros(nb * VBLOCK, "<u2"), "vq": np.zeros(nb * VBLOCK, "u1"), "seen": np.zeros(nb * VBLOCK, "<u2"),
            "cap": 0, "valid": np.zeros(0, "u1"), "pos": np.zeros((0, 3), "<u2"), "spos": np.zeros((0, 3), "<u2"),
            "col": np.zeros((0, 3), "u1"), "flag": np.zeros(0, "u1"), "resid": np.zeros(0, "u1"), "npass": np.zeros(0, "u1"),
            "dirty": {},   # row key -> True, in the order it first became dirty
        }

    def _grow_points(self, top: int) -> None:
        m = self.m
        if top <= m["cap"]:
            return
        cap = max(top + PBLOCK, int(m["cap"] * 1.5), 65536)
        cap = (cap + PBLOCK - 1) // PBLOCK * PBLOCK
        for k, shape, dt in (("valid", (cap,), "u1"), ("pos", (cap, 3), "<u2"), ("spos", (cap, 3), "<u2"), ("col", (cap, 3), "u1"),
                             ("flag", (cap,), "u1"), ("resid", (cap,), "u1"), ("npass", (cap,), "u1")):
            a = np.zeros(shape, dt)
            a[:len(m[k])] = m[k]
            m[k] = a
        m["cap"] = cap

    def _pull_map(self, sim) -> list:
        """Read what changed in the map since the last round (under the server lock) into the mirrors and mark the blocks
        dirty; returns the changed mesh chunks as (key, ver, meta, bytes)."""
        m, mp = self.m, sim.master.map
        if m is None or not getattr(mp, "rust", False):
            return []
        core, full = mp.core, m["full"]
        v = core.vox_deltas(-1 if full else m["tick"])
        m["tick"] = sim.master.tick
        idx, occ = np.asarray(v["idx"]), np.asarray(v["occ"]).astype(bool)
        o = np.flatnonzero(occ)
        if len(o):
            ii = idx[o].astype(np.int64)
            m["vrgb"][ii] = np.asarray(v["rgb"])[o]
            m["vq"][ii] = np.asarray(v["q"])[o]
            for b in np.unique(ii // VBLOCK):
                m["dirty"].setdefault(f"vox/{int(b)}", True)
        p = core.point_updates(full, 2000, 0.06)
        ids = np.asarray(p["ids"]).astype(np.int64)
        if len(ids):
            self._grow_points(int(ids.max()) + 1)
            m["valid"][ids] = 1
            m["pos"][ids] = np.asarray(p["raw"]).reshape(-1, 3)
            m["spos"][ids] = np.asarray(p["sm"]).reshape(-1, 3)
            m["col"][ids] = np.asarray(p["col"]).reshape(-1, 3)
            m["flag"][ids], m["resid"][ids], m["npass"][ids] = np.asarray(p["flag"]), np.asarray(p["resid"]), np.asarray(p["npass"])
            for b in np.unique(ids // PBLOCK):
                m["dirty"].setdefault(f"pt/{int(b)}", True)
        s = core.seen_updates(full)
        si = np.asarray(s["idx"]).astype(np.int64)
        if len(si):
            m["seen"][si] = np.asarray(s["t"])
            for b in np.unique(si // VBLOCK):
                m["dirty"].setdefault(f"seen/{int(b)}", True)
        m["full"] = False
        out = []
        for cid, c in sim.master.surface.updates(m["sent_chunks"], full, limit=10 ** 9 if full else MESH_LIMIT, budget=2_000_000):
            m["sent_n"] += 1
            m["sent_chunks"][cid] = (c["ver"], m["sent_n"])
            vv, nn, cc, ff = np.asarray(c["v"], "<u2"), np.asarray(c["n"], "i1"), np.asarray(c["c"], "u1"), np.asarray(c["f"])
            wide = len(vv) // 3 >= 65536
            ff = ff.astype("<u4" if wide else "<u2")
            meta = _dumps({"nv": len(vv) // 3, "w": wide, "lv": vv.nbytes, "ln": nn.nbytes, "lc": cc.nbytes, "lf": ff.nbytes})
            out.append((f"mesh/{cid}", int(c["ver"]), meta, vv.tobytes() + nn.tobytes() + cc.tobytes() + ff.tobytes()))
        return out

    def _block(self, key: str) -> bytes:
        m = self.m
        kind, b = key.split("/")
        b = int(b)
        if kind == "vox":
            s = slice(b * VBLOCK, (b + 1) * VBLOCK)
            return m["vrgb"][s].tobytes() + m["vq"][s].tobytes()
        if kind == "seen":
            return m["seen"][b * VBLOCK:(b + 1) * VBLOCK].tobytes()
        s = slice(b * PBLOCK, (b + 1) * PBLOCK)   # pt
        return (m["valid"][s].tobytes() + m["pos"][s].tobytes() + m["spos"][s].tobytes() + m["col"][s].tobytes()
                + m["flag"][s].tobytes() + m["resid"][s].tobytes() + m["npass"][s].tobytes())

    def _feeds(self, sim, now: float) -> list:
        """The camera feed (frame + depth) of every drone a viewer has selected recently, a few times a second."""
        if now - self._t_feed < FEED_PERIOD_S:
            return []
        self._t_feed = now
        self.sel = {k: v for k, v in self.sel.items() if now - v[1] < SELECT_TTL_S}
        out = []
        for d in sorted({d for v in self.sel.values() if not v[2] for d in v[0]}):
            a = feed_arrays(sim, int(d))
            if a is None:
                continue
            meta = _dumps({k: a[k] for k in ("t", "age", "w", "h", "frames", "backlog", "jpeg_kb")})
            out.append((f"feed/{int(d)}", 0, meta, np.ascontiguousarray(a["rgb"], "u1").tobytes() + np.ascontiguousarray(a["depth"], "u1").tobytes()))
        return out

    def _jpeg_run(self) -> None:
        """Camera feeds for the console: JPEG frames (no depth), on their own thread and connection so a heavy map round never
        delays them, written as soon as the drone's frame changes."""
        import io
        from PIL import Image
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                now = time.time()
                want = sorted({d for v in list(self.sel.values()) if v[2] and now - v[1] < SELECT_TTL_S for d in v[0]})
                batch = []
                want = want[:JPEG_MAX_DRONES]
                with self.server.lock:
                    sim = self.server.sim
                    frames = preview_frames(sim, want) if want else None
                    t_sim = round(float(sim.t), 2)
                    if frames is None:   # no render room (or not the Rust core): fall back to what the master last received
                        old = {d: feed_arrays(sim, int(d), depth=False) for d in want}
                        frames = None
                if frames is not None:
                    pairs = [(d, frames[j], t_sim, 0.0) for j, d in enumerate(want)]
                else:
                    pairs = [(d, a["rgb"], a["t"], a["age"]) for d, a in old.items() if a is not None and self.jpeg_sent.get(int(d)) != a["t"]]
                for d, rgb, t, age in pairs:
                    self.jpeg_sent[int(d)] = t
                    buf = io.BytesIO()
                    Image.fromarray(np.ascontiguousarray(rgb, "u1")).save(buf, "JPEG", quality=JPEG_QUALITY)
                    meta = _dumps({"t": t, "age": age, "w": int(rgb.shape[1]), "h": int(rgb.shape[0])})
                    batch.append([f"feed/jpg{int(d)}", 0, meta, buf.getvalue().hex()])
                if batch:
                    self.jpeg_client.call("put_blobs", _dumps(batch))
            except Exception:
                traceback.print_exc()
                time.sleep(1.0)
            time.sleep(max(0.0, JPEG_PERIOD_S - (time.perf_counter() - t0)))

    def _send_blobs(self, mesh: list, feeds: list) -> None:
        """Write mesh chunks, feeds and dirty map blocks (oldest first, within a byte budget) in a few big calls."""
        items = list(mesh) + list(feeds)
        if self.m is not None:
            budget = MAP_BUDGET
            for key in list(self.m["dirty"].keys()):
                data = self._block(key)
                items.append((key, 0, "{}", data))
                del self.m["dirty"][key]
                budget -= len(data)
                if budget <= 0:
                    break
        batch, size = [], 0
        for key, ver, meta, data in items:
            batch.append([key, ver, meta, data.hex()])
            size += len(data) * 2 + len(meta) + len(key) + 32
            if size >= POST_LIMIT:
                self.client.call("put_blobs", _dumps(batch))
                batch, size = [], 0
        if batch:
            self.client.call("put_blobs", _dumps(batch))
