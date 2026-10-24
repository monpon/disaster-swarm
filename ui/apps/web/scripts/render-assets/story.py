"""Scroll-story data for the landing page.

Builds the same house point cloud as gen2.py, then simulates two searches
along hand-drawn flight paths: four drones splitting the rooms, and one drone
visiting every room in turn. Each point gets the normalized time it is first
seen by each search (1.0 = the swarm finishes). This is an illustration of the
idea, not a measured result.

Outputs (into the given directory):
  story-points.bin  Uint16 x10, Uint16 y10, Uint8 color bin, Uint8 swarm t, Uint8 solo t (7 bytes/point)
  story.json        drone paths (screen px and top-down meters), event and room times
"""
import json, math, random, struct, sys

import numpy as np

random.seed(11)
OUT = sys.argv[1]
S, OX, OY = 38.0, 435.0, 150.0
C = math.cos(math.pi / 6)
SENSE = 2.3  # metres a drone can see around itself


def proj(x, y, z=0.0):
    return OX + (x - y) * C * S, OY + (x + y) * 0.5 * S - z * S


# ---- cloud (same geometry as gen2.py, section cut at 1.3 m) ----
walls = [
    (0, 0, 8.0, 0), (9.0, 0, 10.7, 0), (0, 0, 0, 9.5), (0, 9.5, 7.0, 9.5), (8.0, 9.5, 9.8, 9.5), (14, 3.5, 14, 5.1),
    (6.5, 0, 6.5, 1.4), (6.5, 2.4, 6.5, 4.0), (6.5, 3.5, 8.0, 3.5), (9.2, 3.5, 10.7, 3.5), (10.7, 0, 10.7, 3.5),
    (10.7, 3.5, 11.5, 3.5), (12.4, 3.5, 14, 3.5), (10.7, 0, 14, 0), (14, 0, 14, 3.5),
    (0, 5.1, 4.0, 5.1), (5.0, 5.1, 6.8, 5.1), (5.2, 5.1, 5.2, 9.5), (6.8, 5.1, 6.8, 7.4), (8.0, 5.1, 8.0, 7.4),
    (8.0, 5.1, 9.8, 5.1), (5.2, 7.4, 6.8, 7.4), (8.0, 7.4, 9.8, 7.4), (9.8, 5.1, 9.8, 9.5), (9.8, 5.1, 11.0, 5.1), (12.0, 5.1, 14, 5.1),
]
pts = []


def add(x, y, z, j=0.025):
    pts.append((x + random.gauss(0, j), y + random.gauss(0, j), max(0.0, z + random.gauss(0, j))))


for x1, y1, x2, y2 in walls:
    for _ in range(int(math.hypot(x2 - x1, y2 - y1) * 150)):
        t = random.random()
        z = 1.3 - abs(random.gauss(0, 0.04)) if random.random() < 0.3 else random.uniform(0, 1.3)
        add(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, z)
for _ in range(400):
    add(11.0 + random.random(), 5.1, random.random() * 1.3, 0.008)
rooms_f = [(0, 0, 6.5, 5.1), (6.5, 0, 10.7, 3.5), (6.5, 3.5, 14, 5.1), (0, 5.1, 5.2, 9.5), (5.2, 5.1, 6.8, 7.4),
           (6.8, 5.1, 8.0, 7.4), (5.2, 7.4, 9.8, 9.5), (8.0, 5.1, 9.8, 7.4), (10.7, 0, 14, 3.5)]
for x1, y1, x2, y2 in rooms_f:
    for _ in range(int((x2 - x1) * (y2 - y1) * 80)):
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


box(0.5, 0.4, 3.4, 1.3, 0.8, 1000); box(2.0, 2.4, 3.2, 3.2, 0.45, 350); box(7.0, 0.1, 10.5, 0.7, 0.92, 1100)
box(7.6, 1.5, 9.4, 2.3, 0.92, 650); box(0.4, 6.6, 2.4, 8.8, 0.55, 1100); box(4.3, 8.6, 5.0, 9.3, 1.1, 300)
box(11.2, 0.4, 13.6, 1.2, 0.8, 500)
for i in range(10):
    box(8.1, 5.3 + i * 0.19, 9.7, 5.49 + i * 0.19, 0.2 + i * 0.11, 80)
for _ in range(1300):
    add(random.gauss(6.4, 0.38), random.gauss(1.9, 0.32), abs(random.gauss(0, 0.45)) * random.random() * 2, 0.05)
for _ in range(420):
    add(2.25 + random.random() * 1.55 + random.gauss(0, 0.05), 7.9 + random.gauss(0, 0.13), abs(random.gauss(0.16, 0.07)), 0.01)
for _ in range(200):
    a = random.random() * 6.283
    add(10.2 + 0.13 * math.cos(a), 1.0 + 0.13 * math.sin(a), random.uniform(0, 0.95), 0.004)

P = np.array(pts)

# ---- flight paths (metres) ----
ENTRY = (7.5, 10.2)
# Each drone launches from its own spot at the door and keeps its own lane
# through the shared hallway, so the four never sit on top of each other.
swarm = {
    "D1": [(6.7, 10.3), (6.95, 8.6), (7.15, 6.0), (7.05, 4.3), (5.5, 4.5), (4.5, 3.5), (1.2, 3.8), (1.2, 1.8), (3.5, 1.6), (5.5, 1.0), (5.5, 2.8), (2.5, 2.6)],
    "D2": [(7.2, 10.3), (7.3, 8.3), (7.45, 6.3), (7.4, 4.65), (4.5, 4.6), (4.5, 6.0), (3.6, 6.4), (1.0, 6.2), (1.0, 9.0), (3.8, 8.8), (3.4, 7.2)],
    "D3": [(7.75, 10.3), (7.5, 8.75), (6.2, 8.4), (6.0, 6.3), (7.4, 6.0), (7.6, 4.3), (10.0, 4.3), (12.0, 4.3), (13.4, 4.4), (12.0, 4.3), (11.9, 2.5), (12.8, 1.5), (11.4, 4.2)],
    "D4": [(8.25, 10.3), (8.0, 8.4), (7.75, 6.0), (7.95, 4.25), (8.6, 4.0), (8.6, 2.8), (7.2, 1.2), (10.0, 1.2), (10.0, 2.6), (9.0, 1.6)],
}
solo = [ENTRY, (7.5, 8.5), (6.2, 8.4), (6.0, 6.3), (7.4, 6.0), (7.8, 4.3), (8.6, 2.8), (7.2, 1.2), (10.0, 1.2), (10.0, 2.6),
        (8.6, 4.0), (10.0, 4.3), (12.0, 4.3), (13.4, 4.4), (11.9, 2.5), (12.8, 1.5), (11.4, 4.2), (7.3, 4.4), (5.5, 4.5),
        (4.5, 3.5), (1.2, 3.8), (1.2, 1.8), (3.5, 1.6), (5.5, 1.0), (5.5, 2.8), (4.5, 4.6), (4.5, 6.0), (3.6, 6.4),
        (1.0, 6.2), (1.0, 9.0), (3.8, 8.8), (3.4, 7.2)]
ALT = {"D1": 1.2, "D2": 0.9, "D3": 1.4, "D4": 1.1, "solo": 1.2}


def length(path):
    return sum(math.dist(a, b) for a, b in zip(path, path[1:]))


SPEED = max(length(p) for p in swarm.values())  # metres per unit time; swarm finishes at t=1


def samples(path, step=0.05):
    out = []
    d = 0.0
    for a, b in zip(path, path[1:]):
        seg = math.dist(a, b)
        n = max(1, int(seg / step))
        for i in range(n):
            f = i / n
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, (d + seg * f) / SPEED))
        d += seg
    out.append((path[-1][0], path[-1][1], d / SPEED))
    return np.array(out)


def seen_times(paths):
    best = np.full(len(P), np.inf)
    for path in paths:
        s = samples(path)
        for i in range(0, len(s), 400):
            chunk = s[i:i + 400]
            d = np.hypot(P[:, 0:1] - chunk[None, :, 0], P[:, 1:2] - chunk[None, :, 1])
            t = np.where(d < SENSE, chunk[None, :, 2], np.inf).min(axis=1)
            best = np.minimum(best, t)
    return best


t_swarm = seen_times(swarm.values())
t_solo = seen_times([solo])
SOLO_END = length(solo) / SPEED
print("points", len(P), "solo end", round(SOLO_END, 2), "unseen swarm", int(np.isinf(t_swarm).sum()))

# Normalized timeline: 0..1 covers the solo search too, swarm ends at 1/SOLO_END.
T_MAX = SOLO_END


def q(t):
    return 255 if not np.isfinite(t) else int(round(min(t / T_MAX, 1.0) * 254))


bins = [0.12, 0.6, 1.0]
with open(f"{OUT}/story-points.bin", "wb") as f:
    for (x, y, z), ts, to in zip(P, t_swarm, t_solo):
        px, py = proj(x, y, z)
        cb = 0 if z < bins[0] else 1 if z < bins[1] else 2 if z < bins[2] else 3
        f.write(struct.pack("<HHBBB", int(px * 10), int(py * 10), cb, q(ts), q(to)))


def first_seen(target, paths):
    best = math.inf
    for path in paths:
        for x, y, t in samples(path):
            if math.dist((x, y), target) < SENSE * 0.8:
                best = min(best, t)
                break
    return best / T_MAX


events = {
    "person": {"at": [3.0, 7.9]},
    "blocked": {"at": [6.4, 1.9]},
    "gas": {"at": [10.2, 1.0]},
    "door": {"at": [11.5, 5.1]},
}
for e in events.values():
    e["swarm"] = round(first_seen(e["at"], swarm.values()), 4)
    e["solo"] = round(first_seen(e["at"], [solo]), 4)
    e["px"] = [round(v, 1) for v in proj(e["at"][0], e["at"][1], 0.3)]

rooms = {
    "Living room": (0, 0, 6.5, 5.1), "Kitchen": (6.5, 0, 10.7, 3.5), "Den": (10.7, 0, 14, 3.5), "Hallway": (6.5, 3.5, 14, 5.1),
    "Bedroom": (0, 5.1, 5.2, 9.5), "Bath": (5.2, 5.1, 6.8, 7.4), "Entry": (5.2, 7.4, 9.8, 9.5),
}
room_times = {}
for name, (x1, y1, x2, y2) in rooms.items():
    m = (P[:, 0] >= x1) & (P[:, 0] <= x2) & (P[:, 1] >= y1) & (P[:, 1] <= y2)
    room_times[name] = {
        "box": [x1, y1, x2, y2],
        "swarm": round(float(np.quantile(t_swarm[m], 0.85)) / T_MAX, 4),
        "solo": round(float(np.quantile(t_solo[m], 0.85)) / T_MAX, 4),
    }


def screen_path(path, alt):
    out, d = [], 0.0
    for i, p in enumerate(path):
        if i:
            d += math.dist(path[i - 1], p)
        x, y = proj(p[0], p[1], alt)
        out.append([round(x, 1), round(y, 1), round(d / SPEED / T_MAX, 4), p[0], p[1]])
    return out


data = {
    "note": "Illustration of the search idea, not a measured result.",
    "swarmEnd": round(1 / T_MAX, 4),
    "size": [1019, 636],
    "house": [14, 9.5],
    "drones": {k: screen_path(v, ALT[k]) for k, v in swarm.items()},
    "solo": screen_path(solo, ALT["solo"]),
    "events": events,
    "rooms": room_times,
}
json.dump(data, open(f"{OUT}/story.json", "w"), indent=1)
print(json.dumps({k: (v["swarm"], v["solo"]) for k, v in events.items()}))
print(json.dumps({k: (v["swarm"], v["solo"]) for k, v in room_times.items()}))
