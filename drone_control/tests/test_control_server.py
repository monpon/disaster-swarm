"""The control server (control/server.py): the token, input validation, and that commands reach the handler.

Run: PYTHONPATH=drone_control pytest drone_control/tests/test_control_server.py
"""
import http.client
import json
import threading

import pytest

from control.handler import Config, FlightHandler
from control.server import make_server
from test_handler import FakeLink


@pytest.fixture
def served():
    link = FakeLink()
    h = FlightHandler(link, Config(require_link=False, takeoff_settle=0.0))
    server, token = make_server(h, "127.0.0.1", 0, "secret")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield h, server.server_address[1], token
    server.shutdown()
    server.server_close()


def call(port, method, path, body=None, token=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Token"] = token
    data = raw if raw is not None else (json.dumps(body) if body is not None else None)
    c.request(method, path, body=data, headers=headers)
    r = c.getresponse()
    out = r.read()
    try:
        return r.status, json.loads(out)
    except ValueError:
        return r.status, out


def test_status_is_readable_without_a_token(served):
    h, port, token = served
    code, s = call(port, "GET", "/status")
    assert code == 200 and s["state"] == "disarmed"


def test_the_page_is_served(served):
    h, port, token = served
    code, body = call(port, "GET", "/")
    assert code == 200 and b"EMERGENCY STOP" in body


def test_every_command_needs_the_token(served):
    h, port, token = served
    for path in ("/arm", "/disarm", "/takeoff", "/land", "/emergency", "/calibrate", "/sticks"):
        code, _ = call(port, "POST", path, {"pitch": 0.1} if path == "/sticks" else None)
        assert code == 403, path
        code, _ = call(port, "POST", path, {"pitch": 0.1} if path == "/sticks" else None, token="wrong")
        assert code == 403, path
    assert h.state.value == "disarmed"


def test_token_in_the_query_string_also_works(served):
    h, port, token = served
    code, r = call(port, "POST", f"/arm?token={token}")
    assert code == 200 and r["state"] == "armed"


def test_flow_arm_takeoff_sticks_land(served):
    h, port, token = served
    assert call(port, "POST", "/takeoff", token=token)[0] == 409           # not armed
    assert call(port, "POST", "/arm", token=token)[0] == 200
    assert call(port, "POST", "/takeoff", token=token)[0] == 200
    code, r = call(port, "POST", "/sticks", {"pitch": 0.5, "yaw": -0.25}, token=token)
    assert code == 200 and r["ok"]
    assert h.status()["command"]["pitch"] > 0 and h.status()["command"]["yaw"] < 0
    assert call(port, "POST", "/disarm", token=token)[0] == 409            # land first
    assert call(port, "POST", "/land", token=token)[0] == 200
    assert h.state.value == "landing"


def test_emergency_over_http(served):
    h, port, token = served
    code, r = call(port, "POST", "/emergency", token=token)
    assert code == 200 and r["state"] == "emergency"


def test_sticks_validation(served):
    h, port, token = served
    call(port, "POST", "/arm", token=token)
    call(port, "POST", "/takeoff", token=token)
    assert call(port, "POST", "/sticks", raw="not json", token=token)[0] == 400
    assert call(port, "POST", "/sticks", raw="[1, 2]", token=token)[0] == 400
    assert call(port, "POST", "/sticks", {"altitude": 1}, token=token)[0] == 400
    assert call(port, "POST", "/sticks", raw="", token=token)[0] == 400
    assert call(port, "POST", "/sticks", raw="x" * 5000, token=token)[0] == 400
    for bad in ('{"pitch": NaN}', '{"pitch": Infinity}', '{"pitch": "1"}', '{"pitch": null}', '{"pitch": true}'):
        code, r = call(port, "POST", "/sticks", raw=bad, token=token)
        assert code == 409 and not r["ok"], bad
    assert h.status()["command"] == {"roll": 0.0, "pitch": 0.0, "throttle": 0.0, "yaw": 0.0}


def test_unknown_paths_are_404(served):
    h, port, token = served
    assert call(port, "POST", "/selfdestruct", token=token)[0] == 404
    assert call(port, "GET", "/arm")[0] == 404


def test_a_token_is_made_up_beyond_localhost_and_required():
    link = FakeLink()
    h = FlightHandler(link, Config(require_link=False))
    server, token = make_server(h, "0.0.0.0", 0, None)
    server.server_close()
    assert token and len(token) >= 8
    with pytest.raises(ValueError):
        make_server(h, "0.0.0.0", 0, "")
    server, token = make_server(h, "127.0.0.1", 0, None)    # loopback may go without
    server.server_close()
    assert token is None
