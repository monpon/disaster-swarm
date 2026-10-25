"""Run the flight controller:

    # through the ESP32-S3 relay (this machine joined to its network, relay running):
    PYTHONPATH=drone_control python -m control --relay 192.168.5.1 --host 0.0.0.0

Starts the RC stream (neutral sticks, drone disarmed), listens for the relay's telemetry on UDP 9100, and serves the control
page. Nothing moves until someone arms and takes off. Props off until the stick directions have been checked.
"""
import argparse
import sys

from drone_link import packets as P

from .handler import Config, FlightHandler, TelemetryListener
from .link import ControlLink
from .server import make_server


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--relay", help="the relay's address (S3 AP: 192.168.5.1); same as --ip")
    ap.add_argument("--ip", default=None, help="drone or relay address (default: the drone's own, 192.168.4.153)")
    ap.add_argument("--cmd-port", type=int, default=P.CMD_PORT)
    ap.add_argument("--mode", choices=("short", "extended"), default="short", help="RC packet layout (unconfirmed for this drone)")
    ap.add_argument("--rate", type=float, default=40.0, help="RC packets per second")
    ap.add_argument("--limit", type=float, default=0.5, help="stick travel as a fraction of the usable range (0-1]")
    ap.add_argument("--invert", default="", help="comma list of axes to reverse: roll,pitch,throttle,yaw")
    ap.add_argument("--max-flight", type=float, default=240.0, help="seconds in the air before it lands itself")
    ap.add_argument("--no-link-check", action="store_true", help="do not require relay telemetry (only for testing against a fake drone)")
    ap.add_argument("--telemetry-port", type=int, default=9100)
    ap.add_argument("--host", default="127.0.0.1", help="address to serve the control page on (0.0.0.0 for other machines)")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--token", default=None, help="password for every command (made up when serving beyond localhost)")
    a = ap.parse_args()

    invert = tuple(x for x in a.invert.split(",") if x)
    cfg = Config(limit=a.limit, invert=invert, mode=a.mode, max_flight_s=a.max_flight, require_link=not a.no_link_check)
    ip = a.relay or a.ip or P.DRONE_IP
    link = ControlLink(ip, a.rate, a.mode, cmd_port=a.cmd_port)
    handler = FlightHandler(link, cfg)
    tele = None if a.no_link_check else TelemetryListener(handler, a.telemetry_port)
    server, token = make_server(handler, a.host, a.port, a.token)
    link.start()
    handler.start()
    q = f"?token={token}" if token else ""
    print(f"RC to {ip}:{a.cmd_port} ({a.mode}), disarmed, sticks neutral, limit {a.limit}, inverted: {list(invert) or 'none'}", flush=True)
    print(f"control page: http://{'localhost' if a.host in ('0.0.0.0', '') else a.host}:{a.port}/{q}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        handler.shutdown()
        link.close()
        if tele:
            tele.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
