"""The flight handler (control/handler.py): states, stick shaping, dead-man, failsafes, and the packets that reach a drone.

Run: PYTHONPATH=drone_control pytest drone_control/tests/test_handler.py
"""
import time

import pytest

from control.handler import AXES, Config, FlightHandler, State, shape, to_byte
from control.link import ControlLink
from drone_link import packets as P
from relay.fake_drone import FakeDrone
from relay.telemetry import decode_rc

NEUTRAL = {"roll": 128, "pitch": 128, "throttle": 128, "yaw": 128}
HZ = 50.0
DT = 1.0 / HZ


class FakeLink:
    """Records what the handler tells the link, in the DroneLink API."""

    def __init__(self):
        self.axes = []
        self.flags = []

    def set_axes(self, roll, pitch, throttle, yaw):
        self.axes.append(dict(roll=roll, pitch=pitch, throttle=throttle, yaw=yaw))

    def takeoff(self):
        self.flags.append("takeoff")

    def land(self):
        self.flags.append("land")

    def emergency_stop(self):
        self.flags.append("emergency")

    def calibrate(self):
        self.flags.append("calibrate")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(**kw):
    clock = Clock()
    link = FakeLink()
    kw.setdefault("takeoff_settle", 0.0)   # most tests are not about the settle
    cfg = Config(require_link=kw.pop("require_link", False), **kw)
    return FlightHandler(link, cfg, clock), link, clock


def run(h, clock, seconds, sticks=None):
    """Tick for `seconds`, refreshing the sticks each tick if given. Returns the last tick's report."""
    out = None
    for _ in range(round(seconds * HZ)):
        clock.t += DT
        if sticks:
            h.set_sticks(**sticks)
        out = h.tick()
    return out


def flying(**kw):
    h, link, clock = make(**kw)
    assert h.arm()[0] and h.takeoff()[0]
    run(h, clock, 0.2, {})
    return h, link, clock


# ---------------------------------------------------------------- stick shaping
def test_shape_deadzone_and_endpoints():
    assert shape(0.04, 0.05, 0.3) == 0.0
    assert shape(-0.05, 0.05, 0.3) == 0.0
    assert shape(1.0, 0.05, 0.3) == pytest.approx(1.0)
    assert shape(-1.0, 0.05, 0.3) == pytest.approx(-1.0)
    assert shape(5.0, 0.05, 0.3) == pytest.approx(1.0)          # clamped
    assert shape(0.0501, 0.05, 0.3) == pytest.approx(0.0, abs=1e-3)   # continuous at the edge of the dead zone


def test_shape_expo_softens_the_centre():
    assert 0 < shape(0.5, 0.0, 0.5) < 0.5


def test_bytes_stay_inside_the_usable_range():
    for limit in (0.1, 0.5, 1.0):
        assert P.AXIS_MIN <= to_byte(-1.0, limit) <= P.AXIS_MID <= to_byte(1.0, limit) <= P.AXIS_MAX
    assert to_byte(0.0, 0.5) == 128
    assert to_byte(1.0, 1.0) == P.AXIS_MAX and to_byte(-1.0, 1.0) == P.AXIS_MIN
    assert to_byte(1.0, 0.5) == 164 and to_byte(-1.0, 0.5) == 89


# ---------------------------------------------------------------- states and refusals
def test_starts_disarmed_and_sends_only_neutral():
    h, link, clock = make()
    assert h.state == State.DISARMED
    run(h, clock, 0.5, {"throttle": 1.0, "pitch": 1.0})
    assert all(a == NEUTRAL for a in link.axes) and link.flags == []


def test_takeoff_needs_arm_and_arm_needs_a_confirmed_link():
    h, link, clock = make(require_link=True)
    assert not h.takeoff()[0]
    ok, msg = h.arm()
    assert not ok and "telemetry" in msg
    h.note_telemetry({"rc": None})
    assert h.arm()[0] and h.state == State.ARMED
    assert h.takeoff()[0] and h.state == State.FLYING


def test_cannot_arm_twice_or_takeoff_twice():
    h, link, clock = make()
    assert h.arm()[0] and not h.arm()[0]
    assert h.takeoff()[0] and not h.takeoff()[0]


def test_takeoff_flag_is_held_for_flag_ticks_then_stops():
    h, link, clock = make(flag_ticks=8)
    h.arm()
    h.takeoff()
    run(h, clock, 0.5)
    assert link.flags == ["takeoff"] * 8


def test_extended_mode_sends_toggle_flags_once():
    assert Config(mode="extended").flag_ticks == 1
    h, link, clock = make(mode="extended")
    h.arm()
    h.takeoff()
    run(h, clock, 0.3)
    assert link.flags == ["takeoff"]


def test_sticks_stay_neutral_while_the_drone_settles_after_takeoff():
    h, link, clock = make(takeoff_settle=2.0, slew=100.0, expo=0.0, deadzone=0.0)
    h.arm()
    h.takeoff()
    run(h, clock, 1.8, {"pitch": 1.0})                 # the pilot is already pushing
    assert all(a == NEUTRAL for a in link.axes)
    run(h, clock, 0.4, {"pitch": 1.0})
    assert link.axes[-1]["pitch"] == 164


def test_sticks_are_neutral_until_flying_and_ignored_when_not():
    h, link, clock = make()
    h.arm()
    ok, msg = h.set_sticks(pitch=1.0)
    assert not ok and "ignored" in msg
    run(h, clock, 0.3, {"pitch": 1.0})
    assert link.axes[-1] == NEUTRAL


def test_calibrate_only_on_the_ground():
    h, link, clock = make()
    assert h.calibrate()[0]
    h.arm()
    h.takeoff()
    assert not h.calibrate()[0]


def test_disarm_refused_while_flying_then_allowed_after_landing():
    h, link, clock = flying(land_s=1.0)
    ok, msg = h.disarm()
    assert not ok and "land" in msg
    assert h.land()[0] and h.state == State.LANDING
    run(h, clock, 1.2)
    assert h.state == State.ARMED
    assert h.disarm()[0] and h.state == State.DISARMED


def test_land_flag_goes_out_and_sticks_are_neutral_while_landing():
    h, link, clock = flying()
    link.flags.clear()
    run(h, clock, 0.1, {"pitch": 1.0})
    h.land()
    out = run(h, clock, 0.3, {"pitch": 1.0})     # the pilot keeps pushing: ignored
    assert link.flags.count("land") == 8
    assert out["sticks"]["pitch"] == 128


# ---------------------------------------------------------------- stick output
def test_sticks_reach_the_drone_with_limit_and_slew():
    h, link, clock = flying(limit=0.5, slew=3.0)
    n0 = len(link.axes)
    run(h, clock, 0.02, {"pitch": 1.0})
    assert link.axes[n0]["pitch"] <= 128 + 3         # one 20 ms tick moves at most 3/s * 0.02 = 0.06 of the way
    run(h, clock, 0.6, {"pitch": 1.0})
    assert link.axes[-1]["pitch"] == 164             # limit 0.5 of the +72 range, reached
    assert link.axes[-1]["roll"] == link.axes[-1]["yaw"] == link.axes[-1]["throttle"] == 128


def test_negative_sticks_use_the_lower_range():
    h, link, clock = flying(limit=0.5)
    run(h, clock, 0.6, {"throttle": -1.0})
    assert link.axes[-1]["throttle"] == 89


def test_invert_flips_an_axis():
    h, link, clock = flying(invert=("pitch",))
    run(h, clock, 0.6, {"pitch": 1.0, "roll": 1.0})
    assert link.axes[-1]["pitch"] == 89 and link.axes[-1]["roll"] == 164


def test_garbage_sticks_never_reach_the_drone():
    h, link, clock = flying()
    for bad in (float("nan"), "1", None, True):
        ok, msg = h.set_sticks(pitch=bad)
        assert not ok and "number" in msg
    run(h, clock, 0.3)
    assert link.axes[-1] == NEUTRAL
    assert h.set_sticks(pitch=1e9)[0]                # an out-of-range number is clamped, not rejected
    run(h, clock, 1.0, {"pitch": 1e9})
    assert link.axes[-1]["pitch"] <= P.AXIS_MAX


def test_config_validation():
    for bad in (dict(limit=0.0), dict(limit=1.5), dict(invert=("up",)), dict(mode="long")):
        with pytest.raises(ValueError):
            Config(**bad)


# ---------------------------------------------------------------- dead-man and failsafes
def test_deadman_neutralises_the_sticks_then_lands():
    h, link, clock = flying(input_timeout=0.4, land_after=3.0)
    run(h, clock, 1.0, {"pitch": 1.0})
    assert link.axes[-1]["pitch"] == 164
    run(h, clock, 0.5)                               # the pilot goes silent: after 0.4 s the sticks start back to centre ...
    assert 128 < link.axes[-1]["pitch"] < 164 and h.state == State.FLYING
    run(h, clock, 0.5)                               # ... at the slew rate (about a third of a second)
    assert link.axes[-1]["pitch"] == 128 and h.state == State.FLYING
    run(h, clock, 3.0)
    assert h.state == State.LANDING and "no input" in h.reason
    assert "land" in link.flags


def test_losing_the_relay_lands_the_drone():
    h, link, clock = make(require_link=True, link_timeout=3.0)
    h.note_telemetry({})
    h.arm()
    h.takeoff()
    for _ in range(round(2.0 * HZ)):                 # telemetry keeps coming once a second
        clock.t += DT
        h.set_sticks(pitch=0.5)
        h.tick()
        if round(clock.t * HZ) % 50 == 0:
            h.note_telemetry({})
    assert h.state == State.FLYING
    run(h, clock, 3.5, {"pitch": 0.5})               # it stops
    assert h.state == State.LANDING and "link lost" in h.reason


def test_max_flight_time_lands():
    h, link, clock = flying(max_flight_s=2.0)
    run(h, clock, 2.5, {"pitch": 0.2})
    assert h.state == State.LANDING and "max flight" in h.reason


def test_emergency_stop_is_always_accepted_and_latched():
    for setup in ("disarmed", "armed", "flying", "landing"):
        h, link, clock = make()
        if setup in ("armed", "flying", "landing"):
            h.arm()
        if setup in ("flying", "landing"):
            h.takeoff()
        if setup == "landing":
            h.land()
        assert h.emergency_stop()[0] and h.state == State.EMERGENCY
        link.flags.clear()
        out = run(h, clock, 0.5, {"throttle": 1.0})
        assert out["sticks"] == NEUTRAL
        assert link.flags and set(link.flags) == {"emergency"}     # sent on every tick while latched
        assert not h.arm()[0] and not h.takeoff()[0]
        assert h.disarm()[0] and h.state == State.DISARMED         # only disarm clears it
        link.flags.clear()
        run(h, clock, 0.2)
        assert link.flags == []


def test_shutdown_lands_a_flying_drone_and_centres_the_sticks():
    h, link, clock = flying()
    run(h, clock, 0.6, {"pitch": 1.0})
    h.shutdown()
    assert "land" in link.flags
    assert link.axes[-1] == NEUTRAL


def test_status_reports_what_the_page_needs():
    h, link, clock = make(require_link=True)
    h.note_telemetry({"rc": {"roll": 128}, "rc_age_s": 0.02})
    s = h.status()
    assert s["state"] == "disarmed" and s["link_ok"] and s["relay_rc_age_s"] == 0.02
    assert set(s["sent"]) == set(AXES) and s["limit"] == 0.5


# ---------------------------------------------------------------- the packets that reach a (fake) drone
def test_packets_on_the_wire():
    drone = FakeDrone("127.0.0.2", 28080, 28090).start()
    link = ControlLink("127.0.0.2", rate_hz=100.0, mode="short", video_port=28080, cmd_port=28090)
    h = FlightHandler(link, Config(require_link=False, slew=100.0, expo=0.0, deadzone=0.0, takeoff_settle=0.3))
    link.start()
    h.start()
    try:
        time.sleep(0.3)
        h.arm()
        h.takeoff()
        deadline = time.time() + 1.0
        while time.time() < deadline:
            h.set_sticks(pitch=1.0)
            time.sleep(0.02)
        h.emergency_stop()
        time.sleep(0.3)
    finally:
        h.shutdown()
        link.close()
        drone.close()
    rcs = [decode_rc(d) for d, _ in drone.rc]
    assert rcs and all(r is not None and r["mode"] == "short" for r in rcs)
    assert rcs[0] == {"mode": "short", "roll": 128, "pitch": 128, "throttle": 128, "yaw": 128, "flags": 0}   # neutral first
    assert any(r["flags"] & P.FLAG_TAKEOFF for r in rcs)                          # the takeoff flag arrived
    assert any(r["pitch"] == 164 and r["roll"] == 128 for r in rcs)               # the forward stick, limited to half range
    assert any(r["flags"] & P.FLAG_EMERGENCY for r in rcs)                        # and the emergency stop
    takeoff_at = next(i for i, r in enumerate(rcs) if r["flags"] & P.FLAG_TAKEOFF)
    stick_at = next(i for i, r in enumerate(rcs) if r["pitch"] == 164)
    assert stick_at - takeoff_at >= 20                                            # sticks only after the settle (0.3 s at 100 Hz, minus jitter)
    assert not any(r["flags"] & P.FLAG_LAND for r in rcs[:takeoff_at])
