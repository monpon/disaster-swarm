#!/usr/bin/env python3
"""Forwarding ceiling of the Python relay on this machine (loopback, fake drone, no hardware).

A fake drone blasts 1472-byte datagrams at a target rate through the relay to a client; reports what
arrived. Loopback has no radio, so this is the software ceiling only.

  PYTHONPATH=. python scripts/bench_relay.py
"""
import asyncio
import socket
import threading
import time

from relay.fake_drone import FakeDrone
from relay.relay import Relay
from relay.telemetry import Sinks, Telemetry

BASE = 38000
PAYLOAD = bytes(1472)


def run(rate_pps: int, idx: int, secs: float = 3.0) -> dict:
    DV, DC, LV, LC = (BASE + idx * 10 + k for k in range(4))   # fresh ports per run
    drone = FakeDrone("127.0.0.2", DV, DC, rate=1).start()
    relay = Relay("127.0.0.2", {"video": (LV, DV), "cmd": (LC, DC)}, "127.0.0.1", "0.0.0.0",
                  Telemetry(), Sinks(None, None, False), 5.0)
    loop = asyncio.new_event_loop()

    def go():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(relay.run())
        except (RuntimeError, asyncio.CancelledError):
            pass
    threading.Thread(target=go, daemon=True).start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cli.bind(("127.0.0.1", 0))
    cli.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
    cli.settimeout(0.2)
    cli.sendto(b"\x42\x76", ("127.0.0.1", LV))     # opens the session; fake drone learns the client
    for _ in range(40):
        if drone.stream_to:
            break
        time.sleep(0.05)
    target = drone.stream_to
    assert target, "fake drone never saw the start command through the relay"
    stop = threading.Event()
    sent = [0]

    def blast():
        t0 = time.perf_counter()
        n = 0
        while not stop.is_set():
            due = int((time.perf_counter() - t0) * rate_pps)
            while n < due:
                drone.video.sendto(PAYLOAD, target)
                n += 1
            time.sleep(0.0005)
        sent[0] = n
    t = threading.Thread(target=blast, daemon=True)
    t.start()
    got = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < secs:
        try:
            got += len(cli.recvfrom(4096)[0]) > 0
        except socket.timeout:
            pass
    stop.set()
    t.join()
    elapsed = time.perf_counter() - t0
    drone.close()
    loop.call_soon_threadsafe(loop.stop)
    return {"offered_pps": rate_pps, "sent": sent[0], "received": got,
            "loss_pct": round(100 * (1 - got / max(sent[0], 1)), 1),
            "fwd_pps": round(got / elapsed), "fwd_MiB_s": round(got * 1472 / elapsed / 2**20, 2)}


if __name__ == "__main__":
    for i, rate in enumerate((500, 1000, 2000, 4000, 8000, 16000)):
        print(run(rate, i), flush=True)
