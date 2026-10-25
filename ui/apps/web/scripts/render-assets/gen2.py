"""Render point cloud + mono drone frames as PNG assets for the Paper mock."""
import math, random, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

random.seed(11)
np.random.seed(11)
OUT = sys.argv[1]
K = 2  # render scale
S, OX, OY = 38.0, 435.0, 150.0
C = math.cos(math.pi / 6)


def proj(x, y, z=0.0):
    return OX + (x - y) * C * S, OY + (x + y) * 0.5 * S - z * S


walls = [
    (0, 0, 6.5, 0, 1), (6.5, 0, 8.0, 0, 1), (9.0, 0, 10.7, 0, 1), (10.7, 0, 14, 0, 0.0),
    (0, 0, 0, 9.5, 1), (0, 9.5, 7.0, 9.5, 1), (8.0, 9.5, 9.8, 9.5, 1), (9.8, 9.5, 14, 9.5, 0.0),
    (14, 0, 14, 3.5, 0.0), (14, 3.5, 14, 5.1, 1), (14, 5.1, 14, 9.5, 0.0),
    (6.5, 0, 6.5, 1.4, 1), (6.5, 2.4, 6.5, 4.0, 1),
    (6.5, 3.5, 8.0, 3.5, 1), (9.2, 3.5, 10.7, 3.5, 1),
    (10.7, 0, 10.7, 3.5, 0.45),
    (10.7, 3.5, 11.5, 3.5, 1), (12.4, 3.5, 14, 3.5, 1),
    (0, 5.1, 4.0, 5.1, 1), (5.0, 5.1, 6.8, 5.1, 1),
    (5.2, 5.1, 5.2, 9.5, 1),
    (6.8, 5.1, 6.8, 7.4, 1), (8.0, 5.1, 8.0, 7.4, 1), (8.0, 5.1, 9.8, 5.1, 1),
    (5.2, 7.4, 6.8, 7.4, 1), (8.0, 7.4, 9.8, 7.4, 1), (9.8, 5.1, 9.8, 9.5, 1),
    (9.8, 5.1, 11.0, 5.1, 1), (12.0, 5.1, 14, 5.1, 1),
]
pts = []


def add(x, y, z, j=0.025):
    pts.append((x + random.gauss(0, j), y + random.gauss(0, j), max(0.0, z + random.gauss(0, j))))


for x1, y1, x2, y2, f in walls:
    L = math.hypot(x2 - x1, y2 - y1)
    if f == 0:
        continue
    for _ in range(int(L * 170)):
        t = random.random() if f == 1 else random.random() ** 2 * 0.6
        z = 1.3 - abs(random.gauss(0, 0.04)) if random.random() < 0.3 else random.uniform(0, 1.3)
        add(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, z)
for _ in range(500):  # closed garage door
    add(11.0 + random.random(), 5.1, random.random() * 1.3, 0.008)

rooms = [(0, 0, 6.5, 5.1, 1), (6.5, 0, 10.7, 3.5, 1), (6.5, 3.5, 14, 5.1, 1), (0, 5.1, 5.2, 9.5, 1),
         (5.2, 5.1, 6.8, 7.4, 1), (6.8, 5.1, 8.0, 7.4, 1), (5.2, 7.4, 9.8, 9.5, 1), (8.0, 5.1, 9.8, 7.4, 0.5),
         (10.7, 0, 12.4, 3.5, 0.25), (11.0, 5.1, 12.0, 6.0, 0.2)]
for x1, y1, x2, y2, d in rooms:
    for _ in range(int((x2 - x1) * (y2 - y1) * 110 * d)):
        add(random.uniform(x1, x2), random.uniform(y1, y2), 0, 0.006)


def box(x1, y1, x2, y2, h, n):
    for _ in range(n):
        r = random.random()
        if r < 0.45:
            add(random.uniform(x1, x2), random.uniform(y1, y2), h, 0.015)
        elif r < 0.72:
            add(random.choice([x1, x2]), random.uniform(y1, y2), random.uniform(0, h), 0.015)
        else:
            add(random.uniform(x1, x2), random.choice([y1, y2]), random.uniform(0, h), 0.015)


box(0.5, 0.4, 3.4, 1.3, 0.8, 1400); box(0.5, 0.25, 3.4, 0.45, 1.0, 300)
box(2.0, 2.4, 3.2, 3.2, 0.45, 450)
box(7.0, 0.1, 10.5, 0.7, 0.92, 1600); 
box(7.6, 1.5, 9.4, 2.3, 0.92, 900)
box(0.4, 6.6, 2.4, 8.8, 0.55, 1500); box(0.4, 8.6, 2.4, 8.9, 1.1, 300)
box(4.3, 8.6, 5.0, 9.3, 1.1, 400)
for i in range(10):  # stair steps
    box(8.1, 5.3 + i * 0.19, 9.7, 5.49 + i * 0.19, 0.2 + i * 0.2, 110)
for _ in range(1800):  # debris
    add(random.gauss(6.4, 0.38), random.gauss(1.9, 0.32), abs(random.gauss(0, 0.45)) * random.random() * 2, 0.05)
for _ in range(520):  # person
    u = random.random()
    add(2.25 + u * 1.55 + random.gauss(0, 0.05), 7.9 + random.gauss(0, 0.13), abs(random.gauss(0.16, 0.07)), 0.01)
for _ in range(260):  # cylinder
    a = random.random() * 6.283
    add(10.2 + 0.13 * math.cos(a), 1.0 + 0.13 * math.sin(a), random.uniform(0, 0.95), 0.004)

W, H = 1019, 636
img = Image.new("RGBA", (W * K, H * K), (0, 0, 0, 0))
dr = ImageDraw.Draw(img, "RGBA")
stops = [(0.0, (184, 184, 179)), (0.5, (138, 138, 134)), (1.0, (92, 92, 89)), (1.4, (40, 40, 38))]


def col(z):
    for (z0, c0), (z1, c1) in zip(stops, stops[1:]):
        if z <= z1:
            t = (z - z0) / (z1 - z0)
            return tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
    return stops[-1][1]


for x, y, z in sorted(pts, key=lambda p: (p[0] + p[1]) * 10 - p[2]):
    px, py = proj(x, y, z)
    r = 0.85 * K
    c = col(z)
    dr.ellipse([px * K - r, py * K - r, px * K + r, py * K + r], fill=c + (215,))
img.save(f"{OUT}/cloud.png")
print("points", len(pts))

# ---------------- mono frames ----------------
FW, FH = 490, 276


def frame(seed, surfaces, objects, light):
    rng = np.random.default_rng(seed)
    base = Image.new("L", (FW, FH), 60)
    d = ImageDraw.Draw(base)
    for poly, v in surfaces + objects:
        d.polygon(poly, fill=v)
    a = np.asarray(base).astype(np.float32)
    yy, xx = np.mgrid[0:FH, 0:FW]
    lx, ly, lr = light
    fall = np.exp(-(((xx - lx) ** 2 + (yy - ly) ** 2) / (2 * lr ** 2)))
    a = a * (0.55 + 0.75 * fall)
    a = np.clip(a, 0, 255)
    im = Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.6))
    a = np.asarray(im).astype(np.float32)
    a += rng.normal(0, 9, a.shape)
    v = ((xx - FW / 2) / (FW / 2)) ** 2 + ((yy - FH / 2) / (FH / 2)) ** 2
    a *= 1 - 0.38 * np.clip(v, 0, 1.6) / 1.6
    a = np.clip(a, 0, 255).astype(np.uint8)
    return Image.fromarray(a).convert("RGB")


def room(bx1, by1, bx2, by2, fl, ce, lw, rw, bw):
    return [([(0, FH), (FW, FH), (bx2, by2), (bx1, by2)], fl), ([(0, 0), (FW, 0), (bx2, by1), (bx1, by1)], ce),
            ([(0, 0), (bx1, by1), (bx1, by2), (0, FH)], lw), ([(FW, 0), (bx2, by1), (bx2, by2), (FW, FH)], rw),
            ([(bx1, by1), (bx2, by1), (bx2, by2), (bx1, by2)], bw)]


f1 = frame(1, room(140, 60, 360, 184, 92, 40, 70, 64, 82),
           [([(192, 80), (280, 80), (280, 140), (192, 140)], 210), ([(234, 80), (238, 80), (238, 140), (234, 140)], 60),
            ([(30, 250), (80, 192), (300, 192), (322, 246)], 34), ([(80, 192), (88, 168), (292, 168), (300, 192)], 46),
            ([(300, 220), (380, 220), (380, 240), (300, 240)], 50), ([(400, 150), (440, 140), (440, 230), (400, 236)], 44)],
           (236, 110, 170))
f2 = frame(2, room(120, 52, 380, 172, 100, 42, 74, 66, 88),
           [([(240, 140), (400, 140), (476, 224), (300, 224)], 150), ([(300, 224), (476, 224), (476, 248), (300, 248)], 54),
            ([(240, 140), (400, 140), (400, 116), (240, 116)], 170),
            ([(64, 236), (90, 214), (150, 210), (210, 216), (246, 228), (250, 244), (190, 250), (110, 252), (70, 250)], 182),
            ([(244, 216), (270, 214), (276, 236), (250, 240)], 172), ([(88, 224), (58, 198), (66, 192), (98, 216)], 168)],
           (170, 200, 150))
f3 = frame(3, room(208, 68, 284, 184, 86, 36, 76, 72, 60),
           [([(220, 84), (272, 84), (272, 184), (220, 184)], 108), ([(258, 132), (264, 132), (264, 138), (258, 138)], 30),
            ([(0, 60), (80, 92), (80, 200), (0, 252)], 56), ([(80, 92), (120, 108), (120, 192), (80, 200)], 42),
            ([(400, 100), (460, 80), (460, 236), (400, 208)], 52)],
           (246, 150, 120))
f4 = frame(4, room(112, 60, 400, 168, 88, 40, 66, 60, 78),
           [([(0, 140), (112, 120), (400, 120), (490, 144), (490, 192), (400, 168), (112, 168), (0, 196)], 150),
            ([(0, 196), (112, 168), (400, 168), (490, 192), (490, 276), (0, 276)], 52),
            ([(336, 130), (368, 130), (368, 212), (336, 212)], 176), ([(344, 118), (360, 118), (360, 132), (344, 132)], 140),
            ([(140, 80), (260, 80), (260, 112), (140, 112)], 52)],
           (300, 120, 160))
for n, im in (("f1", f1), ("f2", f2), ("f3", f3), ("f4", f4)):
    im.save(f"{OUT}/{n}.png")
