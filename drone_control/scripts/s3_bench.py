#!/usr/bin/env python3
"""Laptop side of the S3 throughput test (laptop must be joined to the S3's 's3-bench' AP)."""
import socket
import sys
import time

S3 = ("192.168.5.1", 9200)
PAYLOAD = b"D" + bytes(1471)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", 0))
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)


def wait_for(prefix: bytes, timeout: float):
    sock.settimeout(timeout)
    try:
        while True:
            d, _ = sock.recvfrom(4096)
            if d[:1] == prefix:
                return d
    except socket.timeout:
        return None


def uplink(rate_pps: int, secs: float = 4.0) -> dict:
    sock.sendto(b"E", S3); wait_for(b"R", 1.0)                      # reset counters
    t0 = time.perf_counter(); n = 0
    while time.perf_counter() - t0 < secs:
        due = int((time.perf_counter() - t0) * rate_pps)
        while n < due:
            sock.sendto(PAYLOAD, S3); n += 1
        time.sleep(0.0005)
    time.sleep(0.3)
    sock.sendto(b"E", S3)
    r = wait_for(b"R", 2.0)
    got, nbytes, span = (int(x) for x in r[1:].split(b",")) if r else (0, 0, 1)
    span = max(span, 1) / 1000
    return {"dir": "laptop->S3", "offered_pps": rate_pps, "sent": n, "received": got,
            "loss_pct": round(100 * (1 - got / max(n, 1)), 1),
            "pps": round(got / span), "KiB_s": round(nbytes / span / 1024)}


def downlink(secs: float = 4.0) -> dict:
    sock.sendto(b"T%.1f" % secs, S3)
    t0 = time.perf_counter(); got = nbytes = 0
    sock.settimeout(0.2)
    while True:
        try:
            d, _ = sock.recvfrom(4096)
        except socket.timeout:
            if time.perf_counter() - t0 > secs + 3: break
            continue
        if d[:1] == b"F":
            break
        got += 1; nbytes += len(d)
    dt = secs
    f = d if d[:1] == b"F" else b"F0,0"
    sent, errs = (int(x) for x in f[1:].split(b","))
    return {"dir": "S3->laptop", "S3_sent": sent, "S3_send_errors": errs, "received": got,
            "loss_pct": round(100 * (1 - got / max(sent, 1)), 1),
            "pps": round(got / dt), "KiB_s": round(nbytes / dt / 1024)}


if __name__ == "__main__":
    for rate in (100, 250, 500, 1000, 2000):
        print(uplink(rate), flush=True)
    print(downlink(), flush=True)
