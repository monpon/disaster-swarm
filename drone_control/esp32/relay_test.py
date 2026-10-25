"""ESP32-S3 feasibility test: join the drone as a wifi client, run a test AP on the same radio,
forward UDP 8080/8090 both ways, and print throughput/drops.

Run:  mpremote run esp32/relay_test.py     (keeps printing stats; Ctrl-C to stop)
Then join wifi AP_SSID from a laptop and run:  python probe.py --ip 192.168.5.1
"""
import network
import select
import socket
import time

DRONE_SSID = "WIFI_8K__cc220c"
DRONE_IP = "192.168.4.153"
AP_SSID = "s3-relay-test"   # distinct name for the test so the laptop can pick it unambiguously
AP_IP = "192.168.5.1"       # different subnet from the drone (192.168.4.x) or lwIP routing clashes
PORTS = {"video": (8080, 8080), "cmd": (8090, 8090)}   # kind: (listen port, drone port)

sta = network.WLAN(network.STA_IF)
sta.active(True)
sta.connect(DRONE_SSID)
t0 = time.time()
while not sta.isconnected():
    if time.time() - t0 > 30:
        raise SystemExit("STA: could not join " + DRONE_SSID)
    time.sleep(0.5)
print("STA ip", sta.ifconfig(), "channel", sta.config("channel"))

ap = network.WLAN(network.AP_IF)
ap.active(True)  # the AP interface must be active before it accepts config
ap.config(essid=AP_SSID, security=0, channel=sta.config("channel"))
ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, "8.8.8.8"))
print("AP", AP_SSID, ap.ifconfig(), "channel", ap.config("channel"))

socks = {}
for kind, (lport, _) in PORTS.items():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", lport))
    s.setblocking(False)
    socks[kind] = s
up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
up.bind((sta.ifconfig()[0], 0))
up.setblocking(False)
kind_by_dport = {dp: k for k, (_, dp) in PORTS.items()}

poll = select.poll()
for s in list(socks.values()) + [up]:
    poll.register(s, select.POLLIN)
client = {}
stat = {"up": 0, "down": 0, "down_bytes": 0, "drop": 0}
last = time.ticks_ms()

while True:
    for s, _ev in poll.poll(100):
        try:
            data, addr = s.recvfrom(1600)
        except OSError:
            continue
        if s is up:
            kind = kind_by_dport.get(addr[1])
            if kind and kind in client:
                try:
                    socks[kind].sendto(data, client[kind])
                    stat["down"] += 1
                    stat["down_bytes"] += len(data)
                except OSError:
                    stat["drop"] += 1
            else:
                stat["drop"] += 1
        else:
            for kind, ls in socks.items():
                if s is ls:
                    client[kind] = addr
                    try:
                        up.sendto(data, (DRONE_IP, PORTS[kind][1]))
                        stat["up"] += 1
                    except OSError:
                        stat["drop"] += 1
    now = time.ticks_ms()
    if time.ticks_diff(now, last) >= 2000:
        dt = time.ticks_diff(now, last) / 1000
        print("up %d/s down %d/s %d KiB/s drop %d clients %d" % (
            stat["up"] / dt, stat["down"] / dt, stat["down_bytes"] / dt / 1024, stat["drop"], len(ap.status("stations"))))
        stat.update(up=0, down=0, down_bytes=0)
        last = now
