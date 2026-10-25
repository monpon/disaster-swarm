"""WiFi_CAM wire format (E58 verified: gateway 192.168.4.153, video on UDP 8080).

Layout from turbodrone's wifi_cam adapter (Apache-2.0). RC goes to UDP 8090 as a raw
`66 ... 99` packet: 8 bytes ("short") or 20 bytes ("extended").
"""
from __future__ import annotations

DRONE_IP = "192.168.4.153"
VIDEO_PORT = 8080
CMD_PORT = 8090

STREAM_START = b"\x42\x76"
STREAM_STOP = b"\x42\x77"

START_MARKER = 0x66
END_MARKER = 0x99
AXIS_MID = 128
# Turbodrone's usable stick range for this family.
AXIS_MIN, AXIS_MAX = 50, 200

# short-packet flags
FLAG_TAKEOFF = 0x01
FLAG_LAND = 0x02
FLAG_EMERGENCY = 0x04
FLAG_FLIP = 0x08
FLAG_HEADLESS = 0x10
FLAG_CALIBRATE = 0x80

# extended-packet flags (flags1)
EXT_TAKEOFF_OR_LAND = 0x01
EXT_EMERGENCY = 0x02
EXT_CALIBRATE = 0x04
EXT_FLIP = 0x08
# extended flags2
EXT_HEADLESS = 0x01
EXT_ALT_HOLD = 0x02


def _axis(v: int) -> int:
    return _escape(max(0, min(255, int(v))))


def _escape(v: int) -> int:
    v &= 0xFF
    return (v + 1) & 0xFF if v in (START_MARKER, END_MARKER) else v


def _xor(data) -> int:
    c = 0
    for b in data:
        c ^= b
    return c & 0xFF


def build_short_packet(roll=AXIS_MID, pitch=AXIS_MID, throttle=AXIS_MID, yaw=AXIS_MID, flags=0) -> bytes:
    p = bytearray(8)
    p[0] = START_MARKER
    p[1], p[2], p[3], p[4] = _axis(roll), _axis(pitch), _axis(throttle), _axis(yaw)
    p[5] = flags & 0xFF
    p[6] = _escape(_xor(p[1:6]))
    p[7] = END_MARKER
    return bytes(p)


def build_extended_packet(roll=AXIS_MID, pitch=AXIS_MID, throttle=AXIS_MID, yaw=AXIS_MID,
                          flags1=0, flags2=0) -> bytes:
    p = bytearray(20)
    p[0] = START_MARKER
    p[1] = 0x14
    p[2], p[3], p[4], p[5] = _axis(roll), _axis(pitch), _axis(throttle), _axis(yaw)
    p[6], p[7] = flags1 & 0xFF, flags2 & 0xFF
    p[18] = _escape(_xor(p[2:18]))
    p[19] = END_MARKER
    return bytes(p)
