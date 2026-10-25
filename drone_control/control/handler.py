"""Flight handler: turns pilot intent (arm, takeoff, sticks, land) into the RC stream the E58 expects, with safety built in.

Everything the drone gets goes through here. The handler owns a small state machine

    DISARMED --arm--> ARMED --takeoff--> FLYING --land--> LANDING --(land_s)--> ARMED --disarm--> DISARMED
        any state --emergency_stop--> EMERGENCY (latched, motors cut) --disarm--> DISARMED

and a tick (50 Hz) that decides what the link sends:

  * Sticks are only passed through while FLYING, and not until `takeoff_settle` after the takeoff flag. In every other state
    (and during the settle) the sticks are neutral.
  * Sticks are normalised (-1..1), given a dead zone and expo, scaled by `limit` (a gentle 0.5 by default), and slew-limited,
    so a keyboard cannot jerk the drone from hover to full tilt.
  * A dead-man: if no stick command arrives for `input_timeout` the sticks go neutral (hover); after `land_after` the drone
    lands itself. The same happens if the relay's telemetry goes quiet (link lost) or `max_flight_s` runs out.
  * Takeoff / land / emergency are one-shot flags in the RC packet; the handler holds each for `flag_ticks` ticks so a lost
    UDP packet cannot swallow it.

The handler never touches the network itself: it drives a link object with `set_axes(roll, pitch, throttle, yaw)` and the
one-shot flag methods of drone_link.DroneLink, so tests can use a fake. Nothing here has flown a real drone: the sign of each
stick on the E58 is unverified, hence `invert`.
"""
from __future__ import annotations

import enum
import json
import socket
import threading
import time
from dataclasses import dataclass

from drone_link import packets as P

AXES = ("roll", "pitch", "throttle", "yaw")


class State(str, enum.Enum):
    DISARMED = "disarmed"
    ARMED = "armed"
    FLYING = "flying"
    LANDING = "landing"
    EMERGENCY = "emergency"


@dataclass
class Config:
    limit: float = 0.5           # stick travel as a fraction of the drone's usable range (1.0 = full)
    deadzone: float = 0.05       # normalised input below this is zero
    expo: float = 0.3            # 0 = linear, 1 = cubic: softer around the centre
    slew: float = 3.0            # largest change of a normalised axis per second
    input_timeout: float = 0.4   # no stick command for this long: sticks go neutral (hover)
    land_after: float = 3.0      # ... and after this long without one, land
    link_timeout: float = 3.0    # relay telemetry older than this counts as a lost link
    require_link: bool = True    # refuse to arm/takeoff without telemetry, and land when it stops
    max_flight_s: float = 240.0  # land by themselves after this long in the air
    land_s: float = 6.0          # how long a landing is assumed to take
    takeoff_settle: float = 2.0  # after takeoff the sticks stay neutral this long: the drone is climbing by itself
    flag_ticks: int = 8          # ticks a takeoff / land / emergency flag is held (50 Hz); extended mode toggles, see below
    tick_hz: float = 50.0
    invert: tuple = ()           # axes whose direction is reversed, e.g. ("pitch",): unverified on the real drone
    mode: str = "short"          # RC packet layout of the link ("short" or "extended")

    def __post_init__(self):
        if not 0.0 < self.limit <= 1.0:
            raise ValueError("limit must be in (0, 1]")
        bad = [a for a in self.invert if a not in AXES]
        if bad:
            raise ValueError(f"unknown axes to invert: {bad}")
        if self.mode not in ("short", "extended"):
            raise ValueError("mode must be 'short' or 'extended'")
        if self.mode == "extended":
            self.flag_ticks = 1   # takeoff and land share one toggle bit there: a held flag could toggle twice


def shape(v: float, deadzone: float, expo: float) -> float:
    """Dead zone, then expo, on a -1..1 stick value (continuous at the edge of the dead zone)."""
    v = max(-1.0, min(1.0, float(v)))
    a = abs(v)
    if a <= deadzone:
        return 0.0
    a = (a - deadzone) / (1.0 - deadzone)
    a = (1.0 - expo) * a + expo * a ** 3
    return a if v > 0 else -a


def to_byte(v: float, limit: float) -> int:
    """A shaped -1..1 value to an RC byte around the neutral 128, inside the drone's usable range."""
    span = (P.AXIS_MAX - P.AXIS_MID) if v >= 0 else (P.AXIS_MID - P.AXIS_MIN)
    return int(round(P.AXIS_MID + v * limit * span))


class FlightHandler:
    def __init__(self, link, config: Config | None = None, clock=time.monotonic):
        self.link = link
        self.cfg = config or Config()
        self.clock = clock
        self.lock = threading.RLock()
        self.state = State.DISARMED
        self.reason = "disarmed"
        self._cmd = {a: 0.0 for a in AXES}       # what the pilot asked for (shaped, signed, -1..1)
        self._cur = {a: 0.0 for a in AXES}       # what is being sent (slew-limited)
        self._flag = None                        # "takeoff" | "land" | "calibrate" (emergency is a state)
        self._flag_left = 0
        now = clock()
        self._last_tick = now
        self._last_input = now
        self._t_takeoff = now
        self._t_land = now
        self._tele = None                        # last relay telemetry dict
        self._tele_ts = None
        self._stop = threading.Event()
        self._thread = None
        self.log: list[tuple[float, str]] = []   # (time, what happened), newest last

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Run the tick on its own thread (tests call `tick` directly instead)."""
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="flight-handler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        period = 1.0 / self.cfg.tick_hz
        nxt = self.clock()
        while not self._stop.is_set():
            self.tick()
            nxt += period
            time.sleep(max(0.0, nxt - self.clock()))

    def shutdown(self) -> None:
        """Hover and land if flying, leave the sticks neutral, and stop ticking."""
        with self.lock:
            if self.state == State.FLYING:
                self._begin_landing("shutdown")
            elif self.state != State.EMERGENCY:
                self.state = State.DISARMED
            self._cmd = {a: 0.0 for a in AXES}
            self._cur = {a: 0.0 for a in AXES}
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=1.0)
            self._thread = None
        for _ in range(max(2, self.cfg.flag_ticks + 2)):   # let the neutral sticks and the land flag reach the link
            self.tick()
            time.sleep(1.0 / self.cfg.tick_hz)

    # ------------------------------------------------------------------ telemetry (link health)
    def note_telemetry(self, d: dict) -> None:
        """The relay's 1 Hz status packet. Its `rc` and `rc_age_s` show the relay is receiving our RC stream."""
        with self.lock:
            self._tele, self._tele_ts = d, self.clock()

    def link_ok(self, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        if not self.cfg.require_link:
            return True
        with self.lock:
            return self._tele_ts is not None and now - self._tele_ts <= self.cfg.link_timeout

    # ------------------------------------------------------------------ commands: each returns (ok, message)
    def arm(self) -> tuple[bool, str]:
        with self.lock:
            if self.state != State.DISARMED:
                return False, f"cannot arm while {self.state.value}"
            if not self.link_ok():
                return False, "no relay telemetry: link not confirmed"
            self.state, self.reason = State.ARMED, "armed"
            self._note("armed")
            return True, "armed"

    def disarm(self) -> tuple[bool, str]:
        with self.lock:
            if self.state == State.FLYING:
                return False, "land first (or use emergency stop)"
            self.state, self.reason = State.DISARMED, "disarmed"
            self._flag, self._flag_left = None, 0
            self._cmd = {a: 0.0 for a in AXES}
            self._note("disarmed")
            return True, "disarmed"

    def takeoff(self) -> tuple[bool, str]:
        with self.lock:
            if self.state != State.ARMED:
                return False, f"takeoff needs the drone armed (it is {self.state.value})"
            if not self.link_ok():
                return False, "no relay telemetry: link not confirmed"
            now = self.clock()
            self.state, self.reason = State.FLYING, "takeoff"
            self._t_takeoff = self._last_input = now
            self._cmd = {a: 0.0 for a in AXES}
            self._cur = {a: 0.0 for a in AXES}
            self._set_flag("takeoff")
            self._note("takeoff")
            return True, "takeoff"

    def land(self) -> tuple[bool, str]:
        with self.lock:
            if self.state != State.FLYING:
                return False, f"not flying (it is {self.state.value})"
            self._begin_landing("pilot")
            return True, "landing"

    def emergency_stop(self) -> tuple[bool, str]:
        """Cut the motors. Always accepted, in every state, and latched until disarm."""
        with self.lock:
            self.state, self.reason = State.EMERGENCY, "emergency stop"
            self._flag, self._flag_left = None, 0
            self._cmd = {a: 0.0 for a in AXES}
            self._cur = {a: 0.0 for a in AXES}
            self._note("EMERGENCY STOP")
            return True, "emergency stop"

    def calibrate(self) -> tuple[bool, str]:
        """The drone's gyro calibration. Only on the ground."""
        with self.lock:
            if self.state not in (State.DISARMED, State.ARMED):
                return False, f"calibrate on the ground only (it is {self.state.value})"
            self._set_flag("calibrate")
            return True, "calibrating: keep the drone level and still"

    def set_sticks(self, roll=0.0, pitch=0.0, throttle=0.0, yaw=0.0) -> tuple[bool, str]:
        """Normalised sticks (-1..1; +pitch forward, +roll right, +throttle up, +yaw clockwise: unverified on the E58).
        Refreshes the dead-man. Accepted but ignored unless flying."""
        vals = dict(roll=roll, pitch=pitch, throttle=throttle, yaw=yaw)
        for k, v in vals.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:   # a NaN or a string must never reach the drone
                return False, f"{k} must be a number"
        with self.lock:
            for a in AXES:
                s = shape(vals[a], self.cfg.deadzone, self.cfg.expo)
                self._cmd[a] = -s if a in self.cfg.invert else s
            self._last_input = self.clock()
            if self.state != State.FLYING:
                return False, f"sticks ignored while {self.state.value}"
            return True, "ok"

    # ------------------------------------------------------------------ internals
    def _note(self, what: str) -> None:
        self.log.append((self.clock(), what))
        del self.log[:-50]

    def _set_flag(self, name: str) -> None:
        self._flag, self._flag_left = name, self.cfg.flag_ticks

    def _begin_landing(self, why: str) -> None:
        self.state, self.reason = State.LANDING, f"landing ({why})"
        self._t_land = self.clock()
        self._cmd = {a: 0.0 for a in AXES}
        self._set_flag("land")
        self._note(f"landing: {why}")

    def tick(self, now: float | None = None) -> dict:
        """Decide and send one RC update. Returns what was sent (for tests and the status page)."""
        with self.lock:
            now = self.clock() if now is None else now
            dt = max(0.0, min(0.1, now - self._last_tick))
            self._last_tick = now
            cfg = self.cfg

            if self.state == State.FLYING:
                if not self.link_ok(now):
                    self._begin_landing("link lost")
                elif now - self._last_input > cfg.land_after:
                    self._begin_landing("no input")
                elif now - self._t_takeoff > cfg.max_flight_s:
                    self._begin_landing("max flight time")
            elif self.state == State.LANDING and now - self._t_land > cfg.land_s:
                self.state, self.reason = State.ARMED, "landed"
                self._note("landed")

            # target sticks: the pilot's only while flying and still talking to us, otherwise neutral
            live = (self.state == State.FLYING and now - self._last_input <= cfg.input_timeout
                    and now - self._t_takeoff >= cfg.takeoff_settle)
            target = self._cmd if live else {a: 0.0 for a in AXES}
            step = cfg.slew * dt
            for a in AXES:
                if self.state == State.EMERGENCY:
                    self._cur[a] = 0.0
                else:
                    self._cur[a] += max(-step, min(step, target[a] - self._cur[a]))
            sticks = {a: to_byte(self._cur[a], cfg.limit) for a in AXES}
            self.link.set_axes(roll=sticks["roll"], pitch=sticks["pitch"], throttle=sticks["throttle"], yaw=sticks["yaw"])

            sent_flag = None
            if self.state == State.EMERGENCY:
                sent_flag = "emergency"          # held for as long as the stop is latched
                self.link.emergency_stop()
            elif self._flag and self._flag_left > 0:
                sent_flag = self._flag
                getattr(self.link, self._flag)()
                self._flag_left -= 1
                if self._flag_left == 0:
                    self._flag = None
            return {"sticks": sticks, "flag": sent_flag, "state": self.state.value}

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        with self.lock:
            now = self.clock()
            tele = self._tele or {}
            return {
                "state": self.state.value,
                "reason": self.reason,
                "link_ok": self.link_ok(now),
                "telemetry_age_s": None if self._tele_ts is None else round(now - self._tele_ts, 2),
                "relay_rc": tele.get("rc"),
                "relay_rc_age_s": tele.get("rc_age_s"),
                "sent": {a: to_byte(self._cur[a], self.cfg.limit) for a in AXES},
                "command": {a: round(self._cmd[a], 3) for a in AXES},
                "flight_s": round(now - self._t_takeoff, 1) if self.state in (State.FLYING, State.LANDING) else 0.0,
                "limit": self.cfg.limit,
                "invert": list(self.cfg.invert),
                "mode": self.cfg.mode,
                "log": [(round(now - t, 1), w) for t, w in self.log[-8:]],
            }


class TelemetryListener:
    """Receives the relay's 1 Hz JSON status on UDP 9100 and hands it to the handler (that is how link health is known)."""

    def __init__(self, handler: FlightHandler, port: int = 9100):
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", port))
        self.sock.settimeout(0.3)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="telemetry", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(4096)
                self.handler.note_telemetry(json.loads(data.decode().strip().splitlines()[-1]))
            except (socket.timeout, ValueError, OSError):
                continue

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self.sock.close()
