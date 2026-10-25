"""ESP32-S3 raw UDP throughput over its own AP (no drone needed). Pair with scripts/s3_bench.py on a laptop.

AP-only: this measures the radio + MicroPython socket ceiling in each direction. It does not include
the client-to-drone leg the real relay also uses (AP + STA at once), so real relay numbers will be lower.
Protocol on UDP 9200: 'D...' data packet (counted); 'E' = report count back and reset;
'T<secs>' = blast 1472-byte packets at the sender for <secs>, then send 'F<sent>'.
"""
import network
import socket
import time

AP_SSID, AP_IP = "s3-bench", "192.168.5.1"
ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(essid=AP_SSID, security=0, channel=1)
ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, "8.8.8.8"))
print("AP", AP_SSID, ap.ifconfig())

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", 9200))
s.settimeout(0.5)
n = b_ = 0
t_first = t_last = 0
payload = bytes(1472)
while True:
    try:
        d, a = s.recvfrom(2000)
    except OSError:
        continue
    c = d[:1]
    if c == b"D":
        now = time.ticks_ms()
        if n == 0:
            t_first = now
        t_last = now
        n += 1
        b_ += len(d)
    elif c == b"E":
        s.sendto(b"R%d,%d,%d" % (n, b_, time.ticks_diff(t_last, t_first)), a)
        n = b_ = 0
    elif c == b"T":
        secs = float(d[1:] or b"4")
        end = time.ticks_add(time.ticks_ms(), int(secs * 1000))
        sent = errs = 0
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            try:
                s.sendto(payload, a)
                sent += 1
            except OSError:
                errs += 1
        time.sleep_ms(300)
        s.sendto(b"F%d,%d" % (sent, errs), a)
