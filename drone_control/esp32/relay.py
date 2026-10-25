"""ESP32-S3 drone relay (MicroPython). Feature parity target: drone_control/relay (Python relay).

v2 hot path: GC off between 1 Hz collections (collecting costs ~1 ms), sendto retries on out-of-buffer errors, wifi power-save off, one upstream socket per
(client, port kind) so no addr lookup per packet. Telemetry reports max loop gap and retries.

Joins the E58 as a wifi client, runs an AP on the same radio/channel, forwards UDP 8080/8090 both
ways (drone traffic is never modified), and publishes 1 Hz JSON telemetry: counters, decoded RC,
host stats and IMU. Telemetry goes to stdout and, over UDP, to the most recent client at port 9100.

Run: mpremote connect /dev/ttyACM0 run esp32/relay.py   (copy relay.py + mpu.py as main.py/mpu.py to autostart)
"""
import gc
import json
import network
import select
import socket
import time

import _thread
import esp32
import errno

DRONE_SSID = "WIFI_8K__cc220c"
DRONE_IP = "192.168.4.153"
AP_SSID = "s3-relay-test"    # use DRONE_SSID later; distinct while the real drone is nearby
AP_IP = "192.168.5.1"        # must differ from the drone's 192.168.4.x
PORTS = {"video": (8080, 8080), "cmd": (8090, 8090)}   # kind: (listen port, drone port)
TELEMETRY_PORT = 9100
SESSION_IDLE_MS = 30000
USE_IMU = True

try:
    if not USE_IMU:
        raise OSError("imu disabled")
    from mpu import MPU
    imu = MPU()
    imu.calibrate()
    print("IMU ok, WHO_AM_I 0x%02x" % imu.who)
except Exception as e:     # no IMU wired: telemetry just omits it
    imu = None
    print("IMU unavailable:", e)

sta = network.WLAN(network.STA_IF)
ap = network.WLAN(network.AP_IF)
PRINT_TELEMETRY = False   # USB printing in the hot path can stall; telemetry still goes out over UDP


def join_drone():
    sta.active(True)
    try:
        sta.config(pm=network.WLAN.PM_NONE)   # power save adds latency/burstiness
    except Exception as e:
        print("pm:", e)
    if sta.isconnected():
        return True
    sta.disconnect()
    sta.connect(DRONE_SSID)
    t0 = time.ticks_ms()
    while not sta.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > 20000:
            return False
        time.sleep_ms(250)
    return True


while not join_drone():
    print("STA: retrying", DRONE_SSID)
print("STA", sta.ifconfig(), "channel", sta.config("channel"))
ap.active(True)
ap.config(essid=AP_SSID, security=0, channel=sta.config("channel"))
ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, "8.8.8.8"))
print("AP", AP_SSID, ap.ifconfig())

listeners = {}
for kind, (lport, _) in PORTS.items():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", lport))
    s.setblocking(False)
    listeners[kind] = s
KINDS = ("video", "cmd")

poll = select.poll()
for s in listeners.values():
    poll.register(s, select.POLLIN)

sessions = {}      # client ip -> {"video": sock, "cmd": sock, "reply": {kind: addr}, "last": ms}
sock_owner = {}    # id(upstream sock) -> (client ip, kind)
c = {"up_pkts": 0, "up_bytes": 0, "down_pkts": 0, "down_bytes": 0, "rc_pkts": 0,
     "video_pkts": 0, "dropped": 0, "send_retries": 0, "sta_rejoins": 0}
last_rc = [None, 0]
last_client = [None]
started = time.ticks_ms()
seq = 0
max_gap = 0
gc_ms = 0
tele_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
RING = 512
ring = [None] * RING      # video chunks handed from the receive thread to the main loop
ring_w = [0]
ring_r = [0]
ring_max = [0]
RETRY_ERRNOS = (errno.ENOMEM, errno.EAGAIN, 12, 11, 105)   # no buffer space / try again


def decode_rc(d):
    n = len(d)
    if n == 8 and d[0] == 0x66 and d[7] == 0x99:
        return {"mode": "short", "roll": d[1], "pitch": d[2], "throttle": d[3], "yaw": d[4], "flags": d[5]}
    if n == 20 and d[0] == 0x66 and d[1] == 0x14 and d[19] == 0x99:
        return {"mode": "extended", "roll": d[2], "pitch": d[3], "throttle": d[4], "yaw": d[5],
                "flags": d[6], "flags2": d[7]}
    return None


def send(sock, data, addr):
    """sendto with a short retry on out-of-buffer errors instead of dropping the packet."""
    for _ in range(25):
        try:
            sock.sendto(data, addr)
            return True
        except OSError as e:
            if e.args[0] not in RETRY_ERRNOS:
                break
            c["send_retries"] += 1
            time.sleep_ms(1)
    c["dropped"] += 1
    return False


def new_session(ip):
    sess = {"reply": {}, "last": time.ticks_ms()}
    for kind in KINDS:
        us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        us.bind((sta.ifconfig()[0], 0))
        sess[kind] = us
        if kind == "video":
            us.settimeout(0.5)       # blocking receive in its own thread: wakes instantly per packet
        else:
            us.setblocking(False)
            poll.register(us, select.POLLIN)
            sock_owner[id(us)] = (ip, kind)
    sessions[ip] = sess
    _thread.start_new_thread(video_rx, (ip, sess["video"]))
    return sess


def video_rx(ip, us):
    while True:
        sess = sessions.get(ip)
        if sess is None or sess["video"] is not us:
            return
        try:
            d = us.recv(1600)
        except OSError:
            continue                      # timeout, or socket closed (checked at loop top)
        if not d:
            continue
        w = ring_w[0]
        depth = w - ring_r[0]
        if depth >= RING:
            c["dropped"] += 1
            continue
        if depth > ring_max[0]:
            ring_max[0] = depth
        ring[w % RING] = (ip, d)
        ring_w[0] = w + 1


def drop_session(ip):
    sess = sessions.pop(ip)
    for kind in KINDS:
        us = sess[kind]
        if kind != "video":
            poll.unregister(us)
            sock_owner.pop(id(us), None)
        us.close()


def snapshot():
    global seq, max_gap
    seq += 1
    now = time.ticks_ms()
    host = {"free_kb": gc.mem_free() // 1024, "cpu_temp_c": round(esp32.mcu_temperature(), 1),
            "sta_rssi": sta.status("rssi") if sta.isconnected() else None,
            "max_loop_gap_ms": max_gap, "gc_ms": gc_ms, "ring_max": ring_max[0]}
    max_gap = 0
    ring_max[0] = 0
    out = {"seq": seq, "uptime_s": time.ticks_diff(now, started) // 1000,
           "relay": dict(c, sessions=len(sessions)),
           "rc": last_rc[0],
           "rc_age_s": None if last_rc[0] is None else round(time.ticks_diff(now, last_rc[1]) / 1000, 3),
           "extra": {"host": host}}
    if imu:
        try:
            out["extra"]["imu"] = imu.read()
        except Exception as e:
            out["extra"]["imu_error"] = repr(e)
    return out


gc.collect()
gc.disable()    # collected once per telemetry tick below, so packet handling never pauses for GC
next_tele = time.ticks_add(time.ticks_ms(), 1000)
last_loop = time.ticks_ms()
while True:
    if not sta.isconnected():      # drone link lost: rejoin, AP follows the channel
        c["sta_rejoins"] += 1
        join_drone()
    while ring_r[0] < ring_w[0]:            # forward video chunks queued by the receive thread
        r = ring_r[0]
        ip, data = ring[r % RING]
        ring[r % RING] = None
        ring_r[0] = r + 1
        sess = sessions.get(ip)
        dest = sess["reply"].get("video") if sess else None
        if dest is None:
            c["dropped"] += 1
        elif send(listeners["video"], data, dest):
            c["down_pkts"] += 1
            c["down_bytes"] += len(data)
            c["video_pkts"] += 1
    for s, _ev in poll.poll(1):
        owner = sock_owner.get(id(s))
        if owner is not None:                       # drone -> client
            ip, kind = owner
            sess = sessions.get(ip)
            try:
                data = s.recv(1600)   # NOT readinto: on MicroPython it keeps reading until the buffer is full
            except OSError:
                continue
            if not data:
                continue
            dest = sess["reply"].get(kind) if sess else None
            if dest is None:
                c["dropped"] += 1
                continue
            if send(listeners[kind], data, dest):
                c["down_pkts"] += 1
                c["down_bytes"] += len(data)
                if kind == "video":
                    c["video_pkts"] += 1
        else:                                       # client -> drone
            kind = "video" if s is listeners["video"] else "cmd"
            try:
                data, addr = s.recvfrom(1600)
            except OSError:
                continue
            sess = sessions.get(addr[0]) or new_session(addr[0])
            sess["reply"][kind] = addr
            sess["last"] = time.ticks_ms()
            last_client[0] = addr[0]
            if send(sess[kind], data, (DRONE_IP, PORTS[kind][1])):
                c["up_pkts"] += 1
                c["up_bytes"] += len(data)
                if kind == "cmd":
                    rc = decode_rc(data)
                    if rc:
                        c["rc_pkts"] += 1
                        last_rc[0], last_rc[1] = rc, time.ticks_ms()
    now = time.ticks_ms()
    gap = time.ticks_diff(now, last_loop)
    last_loop = now
    if gap > max_gap:
        max_gap = gap
    if time.ticks_diff(now, next_tele) >= 0:
        next_tele = time.ticks_add(now, 1000)
        for ip in [i for i, x in sessions.items() if time.ticks_diff(now, x["last"]) > SESSION_IDLE_MS]:
            drop_session(ip)
        line = json.dumps(snapshot())
        if PRINT_TELEMETRY:
            print(line)
        if last_client[0]:
            try:
                tele_sock.sendto(line, (last_client[0], TELEMETRY_PORT))
            except OSError:
                pass
        t0 = time.ticks_ms()
        gc.collect()
        gc_ms = time.ticks_diff(time.ticks_ms(), t0)
