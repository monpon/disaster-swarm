"""publish_db.py: the real drone's state and video reach the database, read-only toward the drone.

The real live page (imu/live.py) is started in-process and fed frames and IMU samples; a stand-in database records the calls
the publisher makes. Run: PYTHONPATH=drone_control pytest drone_control/tests/test_publish_db.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
_spec = importlib.util.spec_from_file_location("live", os.path.join(ROOT, "imu", "live.py"))
live_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_mod)

GREF = 1.037
FRAME = b"\xff\xd8" + bytes(range(256)) * 8 + b"\xff\xd9"


class FakeDb:
    def __init__(self):
        self.calls = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.calls.append((self.path, self.headers.get("Authorization"), json.loads(body)))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def start_live():
    live = live_mod.Live(mode="hold")
    server = ThreadingHTTPServer(("127.0.0.1", 0), live_mod.make_handler(live))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop = threading.Event()

    def feed():
        t = 0.0
        while not stop.is_set():
            for _ in range(5):   # 100 Hz of a board sitting still, 20 frames a second
                live.imu_sample(t, (0.0, 0.0, GREF), (0.0, 0.0, 0.0))
                t += 0.01
            live._on_frame(FRAME)
            time.sleep(0.05)

    threading.Thread(target=feed, daemon=True).start()
    return live, server, stop


def run_publisher(home, db_port, live_port, seconds, extra=()):
    env = dict(os.environ, HOME=str(home), PYTHONPATH=ROOT)
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "publish_db.py"), "--db", f"http://127.0.0.1:{db_port}",
                          "--live", f"http://127.0.0.1:{live_port}", "--control", "http://127.0.0.1:1", "--fps", "20", *extra],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(seconds)
    p.terminate()
    return p.communicate(timeout=10)[0], p.returncode


@pytest.fixture
def home(tmp_path):
    (tmp_path / ".swarm_stdb_token").write_text("test-token\n")
    return tmp_path


def test_status_and_video_reach_the_database(home):
    db = FakeDb()
    live, server, stop = start_live()
    try:
        out, _ = run_publisher(home, db.port, server.server_address[1], 4.0)
    finally:
        stop.set()
        server.shutdown()
        db.close()
    assert all(c[1] == "Bearer test-token" for c in db.calls)
    puts = [c for c in db.calls if c[0].endswith("/call/put")]
    blobs = [c for c in db.calls if c[0].endswith("/call/put_blobs")]
    assert puts and blobs, out
    # the status row
    key, ver, text, data = puts[-1][2]
    assert key == "real/status" and data == ""
    st = json.loads(text)
    assert st["online"] is True and st["relay"] == "192.168.5.1" and st["control"] is None
    assert st["imu"]["hz"] > 50 and st["imu"]["mode"] == "hold" and len(st["imu"]["p"]) == 3
    assert st["video"]["fps"] > 5
    # the video rows: the exact JPEG bytes, under the key nothing else reads
    items = [it for c in blobs for it in json.loads(c[2][0])]
    assert items and all(i[0] == "feed/jpgreal" for i in items)
    assert all(bytes.fromhex(i[3]) == FRAME for i in items)
    meta = json.loads(items[-1][2])
    assert meta["bytes"] == len(FRAME)
    assert 8 <= len(items) <= 4.0 * 20 + 2     # --fps 20 caps it


def test_never_writes_anything_but_its_two_keys(home):
    db = FakeDb()
    live, server, stop = start_live()
    try:
        run_publisher(home, db.port, server.server_address[1], 2.5)
    finally:
        stop.set()
        server.shutdown()
        db.close()
    reducers = {c[0].rsplit("/", 1)[1] for c in db.calls}
    assert reducers <= {"put", "put_blobs"}                          # no clear_all, drop_keys, submit_cmd ...
    keys = {c[2][0] for c in db.calls if c[0].endswith("/call/put")}
    keys |= {k[0] for c in db.calls if c[0].endswith("/put_blobs") for k in json.loads(c[2][0])}
    assert keys == {"real/status", "feed/jpgreal"}


def test_reports_offline_when_the_live_page_is_gone(home):
    db = FakeDb()
    try:
        out, _ = run_publisher(home, db.port, 1, 2.0)                # nothing listens on port 1
    finally:
        db.close()
    puts = [c for c in db.calls if c[0].endswith("/call/put")]
    assert puts
    st = json.loads(puts[-1][2][2])
    assert st["online"] is False and st["imu"]["hz"] == 0
    assert not [c for c in db.calls if c[0].endswith("/put_blobs")]  # no stale video


def test_refuses_to_start_without_the_sim_identity(tmp_path):
    db = FakeDb()
    try:
        out, code = run_publisher(tmp_path, db.port, 1, 1.0)
    finally:
        db.close()
    assert "swarm_stdb_token" in out and not db.calls
    assert code == 2


def test_includes_the_flight_controller_state_when_it_runs(home):
    from control.handler import Config, FlightHandler
    from control.server import make_server
    from test_handler import FakeLink
    db = FakeDb()
    live, server, stop = start_live()
    h = FlightHandler(FakeLink(), Config(require_link=False))
    h.arm()
    cs, _ = make_server(h, "127.0.0.1", 0, "t")
    threading.Thread(target=cs.serve_forever, daemon=True).start()
    try:
        env_home = home
        env = dict(os.environ, HOME=str(env_home), PYTHONPATH=ROOT)
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "publish_db.py"), "--db", f"http://127.0.0.1:{db.port}",
                              "--live", f"http://127.0.0.1:{server.server_address[1]}",
                              "--control", f"http://127.0.0.1:{cs.server_address[1]}"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(3.0)
        p.terminate()
        p.communicate(timeout=10)
    finally:
        stop.set()
        server.shutdown()
        cs.shutdown()
        db.close()
    st = json.loads([c for c in db.calls if c[0].endswith("/call/put")][-1][2][2])
    assert st["control"]["state"] == "armed" and st["control"]["sent"] == {"roll": 128, "pitch": 128, "throttle": 128, "yaw": 128}
