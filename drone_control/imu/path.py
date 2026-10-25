"""Reconstruct orientation and a movement path from a board_stream.py CSV log.

    python drone_control/imu/path.py <log.csv> <out.json> [gx,gy,gz bias in deg/s]

IMU-only position drifts quadratically, so this leans on two assumptions:
  - the board is held still for ~2 s at the start (gyro bias, initial tilt)
  - the board pauses now and then; during still periods velocity is reset to
    zero (ZUPT) and the drift accumulated since the last pause is removed
    linearly from that segment's velocity.
Orientation uses gyro integration with a gentle accel tilt correction
(complementary filter). Yaw has no reference and will drift slowly.
"""
import json
import math
import os
import sys

G = 9.80665
STILL_ACC = 0.4       # gravity-removed world accel below this (m/s^2) ...
STILL_GYRO = 6.0      # ... and |gyro| below this (deg/s) counts as still
HIGHPASS_HZ = 0.5     # drift filter cutoff when there are no still periods
MAX_DT = 0.05        # sample gap (s) treated as a dropout
STILL_MIN = 0.15     # seconds a sample window must stay still
TILT_GAIN = 0.002     # accel correction per sample when near 1 g; ~2.5 s time constant at 200 Hz,
                      # stronger gains mistake sideways acceleration for tilt


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def rotate(q, v):
    w, x, y, z = qmul(qmul(q, (0.0, *v)), (q[0], -q[1], -q[2], -q[3]))
    return (x, y, z)


def from_two_vectors(u, v):
    """Shortest rotation taking unit vector u onto unit vector v."""
    d = sum(a * b for a, b in zip(u, v))
    c = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return qnorm((1 + d, *c)) if d > -0.9999 else (0.0, 1.0, 0.0, 0.0)


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) != 7 or line.startswith("#"):
                continue
            try:
                rows.append([float(p) for p in parts])
            except ValueError:
                continue
    for r in rows:
        r[0] /= 1e6
    return rows


def main(src, out, bias=None):
    rows = load(src)
    if len(rows) < 100:
        sys.exit(f"only {len(rows)} samples in {src}")
    t0 = rows[0][0]
    calib = [r for r in rows if r[0] - t0 < 2.0]
    if bias is None:   # else: the board moved at the start, bias comes from a still run
        bias = [sum(r[i] for r in calib) / len(calib) for i in (4, 5, 6)]
    g0 = unit([sum(r[i] for r in calib) / len(calib) for i in (1, 2, 3)])
    q = from_two_vectors(g0, (0.0, 0.0, 1.0))    # body -> world, world z up
    # Measured gravity magnitude: this IMU reads ~1.037 g, and subtracting exactly 1 g
    # leaves a constant fake acceleration. Assumes the start window is still (or nearly).
    gref = sum(math.sqrt(r[1] ** 2 + r[2] ** 2 + r[3] ** 2) for r in calib) / len(calib)

    n = len(rows)
    acc_w, quats, still = [], [], []
    prev_t = rows[0][0]
    gaps = 0
    for r in rows:
        dt = max(r[0] - prev_t, 0.0)
        prev_t = r[0]
        if dt > MAX_DT:   # I2C dropout: don't integrate across it
            dt = 0.0
            gaps += 1
        w = [math.radians(r[4 + i] - bias[i]) for i in range(3)]
        q = qnorm(qmul(q, (1.0, 0.5 * w[0] * dt, 0.5 * w[1] * dt, 0.5 * w[2] * dt)))
        a = (r[1], r[2], r[3])
        amag = math.sqrt(sum(c * c for c in a))
        if abs(amag - gref) < 0.1:   # nudge tilt toward measured gravity
            corr = from_two_vectors(unit(rotate(q, a)), (0.0, 0.0, 1.0))
            corr = qnorm((1 + (corr[0] - 1) * TILT_GAIN, *(c * TILT_GAIN for c in corr[1:])))
            q = qnorm(qmul(corr, q))
        aw = rotate(q, a)
        acc_w.append((aw[0] * G, aw[1] * G, (aw[2] - gref) * G))
        quats.append(q)
        gyro = math.sqrt(sum(c * c for c in w)) * 180 / math.pi
        lin = math.sqrt(sum(c * c for c in acc_w[-1]))
        still.append(lin < STILL_ACC and gyro < STILL_GYRO)

    # Require stillness to persist for STILL_MIN before trusting it.
    rate = n / (rows[-1][0] - t0)
    span = max(1, int(STILL_MIN * rate))
    run = 0
    zupt = [False] * n
    for i in range(n):
        run = run + 1 if still[i] else 0
        if run >= span:
            for j in range(i - span + 1, i + 1):
                zupt[j] = True

    vel = [(0.0, 0.0, 0.0)] * n
    v = (0.0, 0.0, 0.0)
    seg_start = 0
    for i in range(1, n):
        dt = rows[i][0] - rows[i - 1][0]
        if dt > MAX_DT:   # velocity is unknown after a dropout; restart from rest
            dt = 0.0
            v = (0.0, 0.0, 0.0)
            seg_start = i
        if zupt[i]:
            if not zupt[i - 1] and i - seg_start > 1:
                # Remove drift linearly so velocity ends the moving segment at zero.
                length = i - seg_start
                for j in range(seg_start, i):
                    k = (j - seg_start) / length
                    vel[j] = tuple(vel[j][c] - v[c] * k for c in range(3))
            v = (0.0, 0.0, 0.0)
            seg_start = i
        else:
            v = tuple(v[c] + acc_w[i][c] * dt for c in range(3))
        vel[i] = v

    # Without any still period nothing bounds the double integration, so fall back
    # to high-passing velocity and position: drift goes, and so does slow travel,
    # leaving motion relative to where the board is held.
    position_mode = "zupt" if any(zupt) else "highpass"
    pos = [(0.0, 0.0, 0.0)]
    if position_mode == "zupt":
        for i in range(1, n):
            dt = rows[i][0] - rows[i - 1][0]
            dt = 0.0 if dt > MAX_DT else dt
            pos.append(tuple(pos[-1][c] + vel[i][c] * dt for c in range(3)))
    else:
        v = vf = p = pf = (0.0, 0.0, 0.0)
        rc = 1 / (2 * math.pi * HIGHPASS_HZ)
        for i in range(1, n):
            dt = rows[i][0] - rows[i - 1][0]
            if dt > MAX_DT:
                dt, v, vf = 0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
            k = rc / (rc + dt) if dt else 1.0
            v_new = tuple(v[c] + acc_w[i][c] * dt for c in range(3))
            vf = tuple(k * (vf[c] + v_new[c] - v[c]) for c in range(3))
            v = v_new
            p_new = tuple(p[c] + vf[c] * dt for c in range(3))
            pf = tuple(k * (pf[c] + p_new[c] - p[c]) for c in range(3))
            p = p_new
            pos.append(pf)

    step = max(1, int(rate // 50))   # downsample to ~50 Hz for the viewer
    frames = [dict(t=round(rows[i][0] - t0, 3), p=[round(c, 4) for c in pos[i]],
                   q=[round(c, 5) for c in quats[i]], still=zupt[i],
                   a=[round(c, 3) for c in rows[i][1:4]], g=[round(rows[i][4 + c] - bias[c], 2) for c in range(3)])
              for i in range(0, n, step)]
    summary = dict(samples=n, rate_hz=round(rate, 1), duration_s=round(rows[-1][0] - t0, 2), dropouts=gaps,
                   position_mode=position_mode,
                   gyro_bias_dps=[round(b, 3) for b in bias], still_pct=round(100 * sum(zupt) / n, 1),
                   extent_m=[round(max(p[c] for p in pos) - min(p[c] for p in pos), 3) for c in range(3)])
    with open(out, "w") as f:
        json.dump(dict(summary=summary, frames=frames), f)
    # viewer.html lists runs from runs.json next to the outputs
    out_dir = os.path.dirname(os.path.abspath(out))
    runs = sorted(p for p in os.listdir(out_dir) if p.endswith(".json") and p != "runs.json")
    with open(os.path.join(out_dir, "runs.json"), "w") as f:
        json.dump(runs, f)
    print(json.dumps(summary))


if __name__ == "__main__":
    # optional third arg: gyro bias "gx,gy,gz" in deg/s from a run that started still
    main(sys.argv[1], sys.argv[2], [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else None)
