"""The live IMU tracker (imu/live.py): why the path used to snap back to the origin, and that the default mode does not.

The board is simulated with an exact sensor: identity orientation, no gyro, gravity of 1.037 g on z (what the real IMU reads),
and world acceleration that follows a known path. Run: PYTHONPATH=drone_control pytest drone_control/tests/test_tracker.py
"""
import importlib.util
import math
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("live", os.path.join(HERE, "..", "imu", "live.py"))
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)

G = 9.80665
GREF = 1.037   # g
DT = 0.01


def tracker(mode, **kw):
    t = live.Tracker(mode=mode, **kw)
    return t


def feed(tr, t0, seconds, accel):
    """Feed `seconds` of samples starting at t0 with world acceleration accel(t) -> (ax, ay, az) in m/s^2; returns the end time."""
    n = round(seconds / DT)
    for i in range(n):
        t = t0 + i * DT
        ax, ay, az = accel(t - t0)
        tr.update(t, (ax / G, ay / G, GREF + az / G), (0.0, 0.0, 0.0))
    return t0 + n * DT


def settle(tr):
    """The two seconds of holding still that calibrates the gyro bias and the tilt reference."""
    return feed(tr, 0.0, 2.5, lambda t: (0.0, 0.0, 0.0))


def move_then_tremble(tr, distance=0.5, move_s=1.0, tremble_s=6.0):
    """Slide `distance` m along x in `move_s` (minimum-jerk: starts and ends at rest), then keep the board
    shaking (never still, no net motion) for `tremble_s`. Returns (position right after the move, position trace while shaking)."""
    t0 = settle(tr)

    def move(t):
        s = t / move_s   # minimum-jerk position 10s^3 - 15s^4 + 6s^5; acceleration is its second derivative
        return ((60 * s - 180 * s ** 2 + 120 * s ** 3) * distance / move_s ** 2, 0.0, 0.0)

    t1 = feed(tr, t0, move_s, move)
    # a pause between the move and the shaking lets the tracker see the board come to rest
    t1 = feed(tr, t1, 0.3, lambda t: (0.0, 0.0, 0.0))
    after_move = tr.state()["p"][0]
    trace = []
    for i in range(round(tremble_s / DT)):
        t = t1 + i * DT
        a = 1.2 * math.sin(2 * math.pi * 3 * (t - t1))
        tr.update(t, (a / G, 0.0, GREF), (0.0, 0.0, 0.0))
        trace.append(tr.state()["p"][0])
    return after_move, trace


def worst_fall(trace, window_s=0.6, floor=0.1):
    """The biggest fraction of the position lost in any `window_s` (only counted while the position is above `floor` m)."""
    n = round(window_s / DT)
    return max((trace[i] - trace[i + n]) / trace[i] for i in range(len(trace) - n) if trace[i] > floor)


def test_move_is_measured():
    """0.5 m reads as about 0.4: the tilt correction mistakes part of the push for tilt (with it off, 0.496), and hold
    mode's slow leak costs a little more."""
    after_move, _ = move_then_tremble(tracker("hold"))
    assert 0.32 < after_move < 0.55


def test_recentre_mode_pulls_position_back_to_the_origin():
    """The old behaviour: after 1.5 s without a pause the drift filter drains the position to zero within a second or so."""
    after_move, trace = move_then_tremble(tracker("recentre"))
    assert after_move > 0.4
    assert abs(trace[-1]) < 0.1
    assert worst_fall(trace) > 0.5   # more than half the position gone in 0.6 s: the snap


def test_hold_mode_fades_slowly_and_never_snaps():
    after_move, trace = move_then_tremble(tracker("hold"))
    assert after_move > 0.3
    assert worst_fall(trace) < 0.25            # at most a quarter in 0.6 s: a slow fade, not a snap
    assert trace[round(1.5 / DT) - 1] > 0.8 * after_move   # still there 1.5 s into continuous motion (recentre mode: ~0 by then)
    assert trace[-1] > 0.35 * after_move       # and a good part is left after 6 s of continuous shaking


def test_hold_mode_keeps_position_at_rest():
    """The leak only runs while the board is moving: a board left where it ended up stays there."""
    tr = tracker("hold")
    t0 = settle(tr)
    t1 = feed(tr, t0, 1.0, lambda t: ((60 * t - 180 * t ** 2 + 120 * t ** 3) * 0.5, 0.0, 0.0))
    t1 = feed(tr, t1, 0.5, lambda t: (0.0, 0.0, 0.0))
    p1 = tr.state()["p"][0]
    feed(tr, t1, 30.0, lambda t: (0.0, 0.0, 0.0))
    assert tr.state()["p"][0] == pytest.approx(p1, abs=1e-6)


def test_hold_mode_is_the_default():
    assert live.Tracker().mode == "hold"


def test_velocity_still_cannot_run_away_in_hold_mode():
    """A constant accelerometer error would otherwise grow the speed forever; the velocity leak bounds it."""
    tr = tracker("hold")
    t0 = settle(tr)
    # 0.3 m/s^2 of fake push plus shaking so the board never looks still
    feed(tr, t0, 12.0, lambda t: (0.3 + 1.2 * math.sin(2 * math.pi * 3 * t), 0.0, 0.0))
    speed = math.sqrt(sum(c * c for c in tr.v))
    assert speed < 0.5   # without the leak: 0.3 m/s^2 * 12 s = 3.6 m/s (capped at MAX_SPEED)


def test_mode_can_be_switched_and_is_reported():
    tr = tracker("hold")
    assert tr.state()["mode"] == "hold"
    tr.set_mode("recentre")
    assert tr.state()["mode"] == "recentre"
    with pytest.raises(ValueError):
        tr.set_mode("sideways")


def test_pauses_still_anchor_the_path_in_both_modes():
    """Velocity is zeroed in still periods, so a board at rest does not drift off whatever the mode."""
    for mode in ("hold", "recentre"):
        tr = tracker(mode)
        t0 = settle(tr)
        feed(tr, t0, 10.0, lambda t: (0.0, 0.0, 0.0))
        assert max(abs(c) for c in tr.state()["p"]) < 0.02
