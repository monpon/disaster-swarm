"""HTTP front for the flight handler: a JSON API and a keyboard page.

    GET  /               the control page (token in the URL: /?token=...)
    GET  /status         the handler's status (read-only, no token)
    POST /arm /disarm /takeoff /land /emergency /calibrate      (token)
    POST /sticks         {"roll": -1..1, "pitch": ..., "throttle": ..., "yaw": ...}   (token)

Every POST needs the token (header `X-Token`, or `?token=`), because whoever can POST can fly the drone. On a non-loopback
address a token is mandatory; the server makes one up and prints it if none is given.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_BODY = 4096
ACTIONS = {"/arm": "arm", "/disarm": "disarm", "/takeoff": "takeoff", "/land": "land", "/emergency": "emergency_stop",
           "/calibrate": "calibrate"}


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def make_server(handler, host: str, port: int, token: str | None) -> tuple[ThreadingHTTPServer, str | None]:
    if token is None and not is_loopback(host):
        token = secrets.token_urlsafe(9)
    if not is_loopback(host) and not token:
        raise ValueError("a token is required when serving beyond this machine")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not token:
                return True
            given = self.headers.get("X-Token") or parse_qs(urlparse(self.path).query).get("token", [""])[0]
            return hmac.compare_digest(given.encode(), token.encode())

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/control.html"):
                with open(os.path.join(HERE, "control.html"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/status":
                self._json(200, handler.status())
            else:
                self.send_error(404)

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ACTIONS and path != "/sticks":
                return self.send_error(404)
            if not self._authorized():
                return self._json(403, {"ok": False, "message": "bad or missing token"})
            if path == "/sticks":
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if not 0 < n <= MAX_BODY:
                        raise ValueError("body size")
                    d = json.loads(self.rfile.read(n), parse_constant=lambda c: float("nan"))   # NaN/Infinity -> rejected below
                    if not isinstance(d, dict) or set(d) - {"roll", "pitch", "throttle", "yaw"}:
                        raise ValueError("fields")
                except (ValueError, UnicodeDecodeError):
                    return self._json(400, {"ok": False, "message": "send JSON like {\"pitch\": 0.5} with roll/pitch/throttle/yaw in -1..1"})
                ok, msg = handler.set_sticks(**d)
                return self._json(200 if ok else 409, {"ok": ok, "message": msg})
            ok, msg = getattr(handler, ACTIONS[path])()
            self._json(200 if ok else 409, {"ok": ok, "message": msg, "state": handler.state.value})

    server = ThreadingHTTPServer((host, port), H)
    server.daemon_threads = True
    return server, token
