#!/usr/bin/env python3
"""Print relay telemetry arriving on a UDP port (default 9100), one compact line per snapshot."""
import argparse
import json
import socket


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", a.port))
    while True:
        data, _ = s.recvfrom(65535)
        if a.raw:
            print(data.decode())
            continue
        d = json.loads(data)
        r = d["relay"]
        print(f"#{d['seq']} up {r['up_pkts']} down {r['down_pkts']} video {r['video_pkts']} rc {r['rc_pkts']} "
              f"sess {r['sessions']} rc={d['rc']} extra={json.dumps(d['extra'])}")


if __name__ == "__main__":
    main()
