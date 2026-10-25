"""Client for the person detector (object_det/serve.py): frames go out on a background thread, detections come back later.

The detector runs in its own process and environment. If it is not running, the client starts it from the detector
environment when one exists (`DISASTER_DET_PYTHON`, or ~/det/venv), and carries on without it until it answers.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client

import numpy as np

PORT = 8765
AUTH = b"swarm-detector"
PERSON = 2


class PersonDetector:
    def __init__(self) -> None:
        self.jobs: queue.Queue = queue.Queue(maxsize=3)
        self.results: queue.Queue = queue.Queue()
        self.ready = False
        self.busy = False
        self.last_ms = 0.0
        self._proc = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="detector", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- public
    def submit(self, ctx: list, frames: np.ndarray) -> bool:
        """Queue n RGB frames (n, H, W, 3) with their contexts; dropped if the detector is behind or not up."""
        if not self.ready:
            return False
        try:
            self.jobs.put_nowait((ctx, np.ascontiguousarray(frames)))
            return True
        except queue.Full:
            return False

    def poll(self) -> list:
        out = []
        while True:
            try:
                out.append(self.results.get_nowait())
            except queue.Empty:
                return out

    def close(self) -> None:
        self._stop.set()
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass

    # --------------------------------------------------------------- worker
    def _launch(self) -> None:
        py = os.environ.get("DISASTER_DET_PYTHON") or os.path.expanduser("~/det/venv/bin/python")
        here = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(here, "..", "..", "object_det", "serve.py")
        model = os.path.join(here, "..", "..", "object_det", "model.pt")
        if not os.path.exists(model):
            model = os.path.expanduser("~/det/model.pt")
        if os.path.exists(py) and os.path.exists(script) and os.path.exists(model):
            self._proc = subprocess.Popen([py, script, "--model", model, "--port", str(PORT)],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _connect(self):
        try:
            return Client(("127.0.0.1", PORT), authkey=AUTH)
        except OSError:
            return None

    def _run(self) -> None:
        conn = self._connect()
        if conn is None:
            self._launch()
        t0 = time.time()
        while conn is None and not self._stop.is_set() and time.time() - t0 < 180:
            time.sleep(1.0)
            conn = self._connect()
        if conn is None:
            print("person detector not available: survivors will not be detected", file=sys.stderr, flush=True)
            return
        self.ready = True
        while not self._stop.is_set():
            job = self.jobs.get()
            if job is None:
                return
            ctx, frames = job
            self.busy = True
            t = time.perf_counter()
            try:
                conn.send((frames.shape, frames.tobytes()))
                dets = conn.recv()
                self.results.put((ctx, dets))
            except (EOFError, OSError):
                self.ready = False
                return
            finally:
                self.busy = False
                self.last_ms = (time.perf_counter() - t) * 1000
