"""Live drone video + IMU path, served to a browser.

    # through the S3 relay (laptop joined to its AP, relay running on the S3):
    python drone_control/imu/live.py --relay 192.168.5.1
    # IMU over USB only, no drone (board running nothing; this starts board_stream.py):
    python drone_control/imu/live.py --serial /dev/ttyACM0

Then open http://localhost:8765/

Video: sends stream-start to the relay's video port and reassembles JPEG frames
(drone_link.video.FrameStats). No RC packets are sent.
IMU: 18-byte samples batched over UDP 9101 by esp32/relay.py, or CSV lines from
board_stream.py over USB. Both feed the same online tracker.
"""
import argparse
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]   # path.py here; drone_link in drone_control/
from drone_link.packets import STREAM_START, VIDEO_PORT  # noqa: E402
from drone_link.video import FrameStats  # noqa: E402
from path import G, STILL_ACC, STILL_GYRO, STILL_MIN, TILT_GAIN, MAX_DT, from_two_vectors, qmul, qnorm, rotate, unit  # noqa: E402

IMU_PORT = 9101
IMU_REC = 18
TICKS_WRAP = 1 << 30        # MicroPython ticks_us period on the ESP32
CALIBRATE_S = 2.0
DRIFT_HP_HZ = 0.5           # drift filter on velocity and position when the board never pauses
HP_AFTER_S = 1.5            # ... i.e. after this long without a still period (one slide is shorter)
MAX_SPEED = 2.0             # m/s; faster than a hand or a small indoor drone, so it can only be drift


class Tracker:
    """Online version of path.py: gyro + tilt-corrected orientation, ZUPT velocity resets."""

    def __init__(self, log=None):
        self.lock = threading.Lock()
        self.log = log            # raw samples as board_stream.py CSV, replayable with path.py
        self.recalibrate()

    def recalibrate(self):
        with self.lock:
            self.cal = []
            self.cal_t0 = None
            self.bias = None
            self.gref = 1.0
            self.q = (1.0, 0.0, 0.0, 0.0)
            self._zero()

    def zero(self):
        with self.lock:
            self._zero()

    def _zero(self):
        self.v = self.p = (0.0, 0.0, 0.0)
        self.still_run = self.since_still = 0.0
        self.still = self.relative = False
        self.last_t = None
        self.samples = 0

    def update(self, t, a, g):
        with self.lock:
            self.samples += 1
            if self.log:
                self.log.write("%d,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f\n" % (t * 1e6, *a, *g))
            dt = 0.0 if self.last_t is None else t - self.last_t
            self.last_t = t
            if dt < 0 or dt > MAX_DT:      # dropout or reordering: don't integrate across it
                dt = 0.0
                self.v = (0.0, 0.0, 0.0)
            if self.bias is None:
                self.cal.append((a, g))
                if self.cal_t0 is None:
                    self.cal_t0 = t
                if t - self.cal_t0 >= CALIBRATE_S:
                    n = len(self.cal)
                    self.bias = [sum(x[1][i] for x in self.cal) / n for i in range(3)]
                    g0 = unit([sum(x[0][i] for x in self.cal) / n for i in range(3)])
                    self.q = from_two_vectors(g0, (0.0, 0.0, 1.0))
                    # This IMU reads gravity as ~1.037 g; subtracting exactly 1 g leaves a
                    # constant fake acceleration that never looks still.
                    self.gref = sum(math.sqrt(sum(c * c for c in x[0])) for x in self.cal) / n
                return
            w = [math.radians(g[i] - self.bias[i]) for i in range(3)]
            q = qnorm(qmul(self.q, (1.0, 0.5 * w[0] * dt, 0.5 * w[1] * dt, 0.5 * w[2] * dt)))
            amag = math.sqrt(sum(c * c for c in a))
            if abs(amag - self.gref) < 0.1:
                corr = from_two_vectors(unit(rotate(q, a)), (0.0, 0.0, 1.0))
                corr = qnorm((1 + (corr[0] - 1) * TILT_GAIN, *(c * TILT_GAIN for c in corr[1:])))
                q = qnorm(qmul(corr, q))
            self.q = q
            aw = rotate(q, a)
            lin = (aw[0] * G, aw[1] * G, (aw[2] - self.gref) * G)
            gyro = math.degrees(math.sqrt(sum(c * c for c in w)))
            quiet = math.sqrt(sum(c * c for c in lin)) < STILL_ACC and gyro < STILL_GYRO
            self.still_run = self.still_run + dt if quiet else 0.0
            self.still = self.still_run >= STILL_MIN
            self.since_still = 0.0 if self.still else self.since_still + dt
            # Pauses reset velocity; only without them do the drift filters earn their distortion.
            # Then velocity and position both leak toward zero (as path.py's highpass mode), so
            # the path shows motion relative to where the board is held instead of running away.
            self.relative = self.since_still > HP_AFTER_S
            k = 1 / (1 + 2 * math.pi * DRIFT_HP_HZ * dt) if self.relative else 1.0
            if self.still:
                self.v = (0.0, 0.0, 0.0)
            else:
                v = [k * (self.v[c] + lin[c] * dt) for c in range(3)]
                speed = math.sqrt(sum(c * c for c in v))
                self.v = tuple(c * MAX_SPEED / speed for c in v) if speed > MAX_SPEED else tuple(v)
            self.p = tuple(k * (self.p[c] + self.v[c] * dt) for c in range(3))

    def state(self):
        with self.lock:
            return dict(calibrating=self.bias is None, q=[round(c, 5) for c in self.q],
                        p=[round(c, 4) for c in self.p], still=self.still, relative=self.relative)


class Rate:
    """Events per second over a sliding 2 s window."""

    def __init__(self):
        self.times = []

    def tick(self):
        now = time.monotonic()
        self.times.append(now)
        while self.times and now - self.times[0] > 2.0:
            self.times.pop(0)

    def value(self):
        now = time.monotonic()
        recent = [t for t in self.times if now - t <= 2.0]
        return round(len(recent) / 2.0, 1)


class Live:
    def __init__(self, log=None):
        self.tracker = Tracker(log)
        self.imu_rate = Rate()
        self.video_rate = Rate()
        self.frame = None
        self.frame_seq = 0
        self.frame_cond = threading.Condition()
        self.video = FrameStats(on_frame=self._on_frame)
        self.imu_source = None
        self.imu_errors = 0
        self._unwrap = (None, 0)

    def _on_frame(self, jpeg):
        self.video_rate.tick()
        with self.frame_cond:
            self.frame = jpeg
            self.frame_seq += 1
            self.frame_cond.notify_all()

    def imu_sample(self, t, a, g):
        self.imu_rate.tick()
        self.tracker.update(t, a, g)

    # --- sources -------------------------------------------------------------
    def run_video(self, relay_ip):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", 0))
        sock.settimeout(0.5)
        last_start = 0.0
        while True:
            now = time.monotonic()
            # Resend stream start until video flows, then every 5 s as keepalive.
            if now - last_start > (5.0 if self.video.chunks else 0.5):
                try:
                    sock.sendto(STREAM_START, (relay_ip, VIDEO_PORT))
                except OSError:
                    pass
                last_start = now
            try:
                data = sock.recv(4096)
            except OSError:
                continue
            self.video.feed(data)

    def run_imu_udp(self):
        self.imu_source = "relay udp"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", IMU_PORT))
        while True:
            data = sock.recv(2048)
            for o in range(0, len(data) - IMU_REC + 1, IMU_REC):
                t = self._unwrap_us(int.from_bytes(data[o:o + 4], "little"))
                ax, ay, az, _temp, gx, gy, gz = struct.unpack(">7h", data[o + 4:o + IMU_REC])
                self.imu_sample(t / 1e6, (ax / 8192, ay / 8192, az / 8192), (gx / 65.5, gy / 65.5, gz / 65.5))

    def _unwrap_us(self, raw):
        prev, offset = self._unwrap
        if prev is not None and raw < prev - TICKS_WRAP // 2:
            offset += TICKS_WRAP
        self._unwrap = (raw, offset)
        return raw + offset

    def run_imu_serial(self, device):
        self.imu_source = "usb serial"
        script = os.path.join(HERE, "board_stream.py")
        while True:
            proc = subprocess.Popen(["mpremote", "connect", device, "run", script],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for line in proc.stdout:
                if line.startswith("# i2c lost"):
                    self.imu_errors += 1
                parts = line.strip().split(",")
                if len(parts) != 7 or line.startswith("#"):
                    continue
                try:
                    v = [float(x) for x in parts]
                except ValueError:
                    continue
                self.imu_sample(v[0] / 1e6, v[1:4], v[4:7])
            proc.wait()
            time.sleep(1)                      # board reset or unplugged: retry

    def status(self):
        s = self.tracker.state()
        s.update(imu_hz=self.imu_rate.value(), imu_source=self.imu_source, imu_errors=self.imu_errors,
                 video_fps=self.video_rate.value(), video=self.video.summary())
        return s


def make_handler(live):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.path = self.path.split("?", 1)[0]   # the page adds cache-busting queries
            if self.path in ("/", "/live.html"):
                return self._file("live.html", "text/html")
            if self.path == "/viewer.html":           # old bookmark: the live page replaced it
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if self.path == "/runs.html":             # recorded runs
                return self._file("runs.html", "text/html")
            if self.path.startswith("/vendor/") and ".." not in self.path:
                return self._file(self.path.lstrip("/"), "text/javascript")
            if self.path.startswith("/runs/") and ".." not in self.path:
                return self._file(self.path.lstrip("/"), "application/json")
            if self.path == "/video.mjpg":
                return self._mjpeg()
            if self.path == "/events":
                return self._events()
            self.send_error(404)

        def do_POST(self):
            if self.path == "/zero":
                live.tracker.zero()
            elif self.path == "/calibrate":
                live.tracker.recalibrate()
            else:
                return self.send_error(404)
            self.send_response(204)
            self.end_headers()

        def _file(self, rel, ctype):
            with open(os.path.join(HERE, rel), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _mjpeg(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = -1
            try:
                while True:
                    with live.frame_cond:
                        live.frame_cond.wait_for(lambda: live.frame_seq != seen, timeout=5)
                        if live.frame_seq == seen:
                            continue
                        seen, jpeg = live.frame_seq, live.frame
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg))
                    self.wfile.write(jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(b"data: " + json.dumps(live.status()).encode() + b"\n\n")
                    self.wfile.flush()
                    time.sleep(1 / 30)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--relay", help="relay IP for video + UDP IMU (S3 AP: 192.168.5.1)")
    ap.add_argument("--serial", help="read IMU from board_stream.py over this USB device instead of UDP")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if not args.relay and not args.serial:
        ap.error("need --relay and/or --serial")
    os.makedirs(os.path.join(HERE, "runs"), exist_ok=True)
    log_path = os.path.join(HERE, "runs", time.strftime("live-%Y%m%d-%H%M%S.csv"))
    log = open(log_path, "w", buffering=1)
    log.write("# t_us,ax,ay,az,gx,gy,gz\n")
    print(f"raw IMU log: {log_path}", flush=True)
    live = Live(log)
    jobs = []
    if args.relay:
        jobs.append((live.run_video, (args.relay,)))
    jobs.append((live.run_imu_serial, (args.serial,)) if args.serial else (live.run_imu_udp, ()))
    for target, a in jobs:
        threading.Thread(target=target, args=a, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(live))
    server.daemon_threads = True
    print(f"live view: http://localhost:{args.port}/", flush=True)

    def log_status():
        while True:
            time.sleep(5)
            s = live.status()
            print(f"video {s['video_fps']} fps ok {s['video']['ok']}/{s['video']['frames']} | imu {s['imu_hz']} Hz "
                  f"errors {s['imu_errors']} | calibrating {s['calibrating']} still {s['still']} p {s['p']}", flush=True)

    threading.Thread(target=log_status, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
