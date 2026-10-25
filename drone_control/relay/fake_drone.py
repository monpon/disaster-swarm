#!/usr/bin/env python3
"""Stand-in E58 for local verification: streams 1472-byte datagrams after `42 76`, logs RC packets."""
import argparse
import socket
import threading
import time


class FakeDrone:
    def __init__(self, ip="127.0.0.2", video_port=8080, cmd_port=8090, rate=100.0):
        self.video = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.video.bind((ip, video_port))
        self.video.settimeout(0.05)
        self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd.bind((ip, cmd_port))
        self.cmd.settimeout(0.05)
        self.rate = rate
        self.rc: list[tuple[bytes, tuple]] = []
        self.stream_to = None
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=f, daemon=True) for f in (self._ctl, self._rc, self._stream)]

    def start(self):
        for t in self._threads:
            t.start()
        return self

    def close(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1)
        self.video.close()
        self.cmd.close()

    def _ctl(self):
        while not self._stop.is_set():
            try:
                data, addr = self.video.recvfrom(2048)
            except socket.timeout:
                continue
            if data == b"\x42\x76":
                self.stream_to = addr
            elif data == b"\x42\x77":
                self.stream_to = None

    def _rc(self):
        while not self._stop.is_set():
            try:
                data, addr = self.cmd.recvfrom(2048)
            except socket.timeout:
                continue
            self.rc.append((data, addr))

    def _stream(self):
        n = 0
        while not self._stop.is_set():
            if self.stream_to:
                n += 1
                self.video.sendto(n.to_bytes(8, "big") + bytes(1464), self.stream_to)
            time.sleep(1 / self.rate)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="127.0.0.2")
    ap.add_argument("--video-port", type=int, default=28080)
    ap.add_argument("--cmd-port", type=int, default=28090)
    a = ap.parse_args()
    FakeDrone(a.ip, a.video_port, a.cmd_port).start()
    print(f"fake drone on {a.ip} video:{a.video_port} cmd:{a.cmd_port}")
    while True:
        time.sleep(60)
