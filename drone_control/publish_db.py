"""Publish the real drone's state and video into the SpacetimeDB the console reads, next to (never instead of) the simulation.

    python drone_control/publish_db.py --db http://127.0.0.1:3000 [--live http://127.0.0.1:8766] [--control http://127.0.0.1:8770]

Read-only toward the drone: it only reads what `imu/live.py` (IMU tracker, video, link stats) and, if running, the flight
controller (`python -m control`) already serve over HTTP, and writes two things:

    entity  real/status   JSON, twice a second: IMU pose, video and link health, flight-controller state
    bulk    feed/jpgreal  the latest camera frame as a JPEG (up to --fps frames a second)

It never sends a command to the drone and has no way to: flight control stays on the controller's own authenticated page.
Rows are written with the simulator's database identity (~/.swarm_stdb_token, so run it on the machine that runs the sim); a
database identity without write rights would be silently ignored, so it refuses to start without that token.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import threading
import time
import urllib.parse

STATUS_KEY = "real/status"
FEED_KEY = "feed/jpgreal"
TOKEN_PATH = os.path.expanduser("~/.swarm_stdb_token")


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


class Db:
    """The two calls this needs, over HTTP with a kept-alive connection (same conventions as the simulator's publisher)."""

    def __init__(self, url: str, db: str, token: str):
        u = urllib.parse.urlparse(url)
        self.host, self.port, self.db, self.token = u.hostname, u.port or 3000, db, token
        self.conn = None
        self.bytes = 0

    def call(self, reducer: str, *args) -> None:
        body = dumps(list(args))
        for attempt in (0, 1):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
                self.conn.request("POST", f"/v1/database/{self.db}/call/{reducer}", body=body,
                                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
                r = self.conn.getresponse()
                data = r.read()
                if r.status != 200:
                    raise RuntimeError(f"{reducer}: HTTP {r.status} {data[:200]!r}")
                self.bytes += len(body)
                return
            except (OSError, http.client.HTTPException):
                self.conn = None
                if attempt:
                    raise

    def put(self, key: str, text: str) -> None:
        self.call("put", key, 0, text, "")

    def put_blob(self, key: str, meta: str, data: bytes) -> None:
        self.call("put_blobs", dumps([[key, 0, meta, data.hex()]]))


class Latest:
    """The newest value from a source thread, with when it arrived."""

    def __init__(self):
        self.lock = threading.Lock()
        self.value, self.at, self.seq = None, 0.0, 0

    def set(self, v) -> None:
        with self.lock:
            self.value, self.at, self.seq = v, time.monotonic(), self.seq + 1

    def get(self):
        with self.lock:
            return self.value, self.at, self.seq


def http_get(base: str, path: str, timeout: float = 5.0):
    u = urllib.parse.urlparse(base)
    c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    c.request("GET", path)
    return c, c.getresponse()


def follow_events(base: str, out: Latest, stop: threading.Event) -> None:
    """The live page's server-sent state (IMU pose, video and link stats)."""
    while not stop.is_set():
        try:
            c, r = http_get(base, "/events", timeout=5.0)
            while not stop.is_set():
                line = r.readline()
                if not line:
                    break
                if line.startswith(b"data:"):
                    out.set(json.loads(line[5:]))
        except (OSError, http.client.HTTPException, ValueError):
            pass
        stop.wait(1.0)


def follow_control(base: str, out: Latest, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            c, r = http_get(base, "/status", timeout=3.0)
            out.set(json.loads(r.read()))
            c.close()
        except (OSError, http.client.HTTPException, ValueError):
            out.set(None)
        stop.wait(0.5)


def follow_video(base: str, out: Latest, stop: threading.Event) -> None:
    """Whole JPEG frames from the live page's multipart MJPEG stream (it writes `--frame`, headers, a blank line, the bytes)."""
    while not stop.is_set():
        try:
            c, r = http_get(base, "/video.mjpg", timeout=5.0)
            while not stop.is_set():
                length = None
                while True:   # headers up to the blank line
                    line = r.readline()
                    if not line:
                        raise EOFError
                    line = line.strip()
                    if not line:
                        if length is not None:
                            break
                        continue
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                if not 0 < length <= 2_000_000:
                    raise ValueError("frame size")
                jpeg = r.read(length)
                if len(jpeg) == length and jpeg[:2] == b"\xff\xd8":
                    out.set(jpeg)
        except (OSError, http.client.HTTPException, ValueError, EOFError):
            pass
        stop.wait(1.0)


def build_status(events, ctrl, relay: str, now_wall: float) -> dict:
    """Everything the console shows about the real drone. `online` means the IMU/video side is delivering right now."""
    online = bool(events and events.get("imu_hz", 0) > 0)
    ev = events or {}
    st = {
        "t": round(now_wall, 2),
        "online": online,
        "relay": relay,
        "imu": {"hz": ev.get("imu_hz", 0), "source": ev.get("imu_source"), "mode": ev.get("mode"), "still": ev.get("still"),
                "calibrating": ev.get("calibrating"), "p": ev.get("p"), "q": ev.get("q"), "errors": ev.get("imu_errors")},
        "video": {"fps": ev.get("video_fps", 0), **{k: v for k, v in (ev.get("video") or {}).items() if k in ("frames", "ok", "ok_pct", "ok_fps")}},
        "control": None,
    }
    if ctrl:
        st["control"] = {k: ctrl.get(k) for k in ("state", "reason", "link_ok", "relay_rc_age_s", "flight_s", "sent", "limit", "mode")}
    return st


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="http://127.0.0.1:3000", help="SpacetimeDB address")
    ap.add_argument("--name", default="swarm", help="database name")
    ap.add_argument("--live", default="http://127.0.0.1:8766", help="the live page (imu/live.py)")
    ap.add_argument("--control", default="http://127.0.0.1:8770", help="the flight controller (optional; its status only)")
    ap.add_argument("--relay", default="192.168.5.1")
    ap.add_argument("--fps", type=float, default=10.0, help="most video frames written a second")
    a = ap.parse_args()

    if not os.path.exists(TOKEN_PATH):
        print(f"no {TOKEN_PATH}: this needs the simulator's database identity (run it where the sim runs)", file=sys.stderr)
        return 2
    db = Db(a.db, a.name, open(TOKEN_PATH).read().strip())
    stop = threading.Event()
    events, ctrl, video = Latest(), Latest(), Latest()
    for fn, base, out in ((follow_events, a.live, events), (follow_control, a.control, ctrl), (follow_video, a.live, video)):
        threading.Thread(target=fn, args=(base, out, stop), daemon=True).start()
    print(f"publishing real/status and {FEED_KEY} to {a.db} ({a.name}); live {a.live}, control {a.control}", flush=True)

    last_status = last_frame = 0.0
    sent_seq = 0
    errors = 0
    try:
        while True:
            now = time.monotonic()
            try:
                if now - last_status >= 0.5:
                    last_status = now
                    ev, ev_at, _ = events.get()
                    if ev is not None and now - ev_at > 3.0:
                        ev = None    # the page stopped sending: report the drone offline, not the last pose forever
                    ct, ct_at, _ = ctrl.get()
                    db.put(STATUS_KEY, dumps(build_status(ev, ct, a.relay, time.time())))
                jpeg, jpeg_at, seq = video.get()
                if jpeg is not None and seq != sent_seq and now - jpeg_at < 2.0 and now - last_frame >= 1.0 / a.fps:
                    sent_seq, last_frame = seq, now
                    db.put_blob(FEED_KEY, dumps({"t": round(time.time(), 2), "seq": seq, "bytes": len(jpeg)}), jpeg)
                errors = 0
            except (OSError, http.client.HTTPException, RuntimeError) as e:
                errors += 1
                if errors in (1, 10):
                    print(f"database write failed ({e}); retrying", flush=True)
                time.sleep(min(2.0, 0.2 * errors))
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
