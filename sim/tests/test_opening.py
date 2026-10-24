"""fit_opening on synthetic frames: a wall with rectangular holes, seen from 6 m."""
import numpy as np

from disaster_sim.opening import fit_opening

W, H, HFOV, VFOV = 360, 240, 90.0, 64.0


def body_rays():
    """The camera model of camera.Intrinsics (nose-fixed, no tilt), without importing torch."""
    u = np.tan(np.deg2rad(HFOV) / 2) * ((np.arange(W) + 0.5) / W * 2 - 1)
    v = np.tan(np.deg2rad(VFOV) / 2) * (1 - (np.arange(H) + 0.5) / H * 2)
    fwd, right = np.array([1.0, 0.0, 0.0]), np.array([0.0, -1.0, 0.0])
    up = np.cross(right, fwd)
    d = (fwd[None, None, :] + u[None, :, None] * right[None, None, :] + v[:, None, None] * up[None, None, :]).reshape(-1, 3)
    return d / np.linalg.norm(d, axis=1, keepdims=True)


def frame(holes, pos, yaw=0.0, face=50.0, far=30.0):
    """Wall at x = face (axis 0) with holes [(y0, y1, z0, z1), ...]; depth along each ray, 0 where nothing is hit."""
    c, s = np.cos(yaw), np.sin(yaw)
    rays = body_rays()
    dirs = np.stack([c * rays[:, 0] - s * rays[:, 1], s * rays[:, 0] + c * rays[:, 1], rays[:, 2]], axis=1)
    t = (face - pos[0]) / np.where(np.abs(dirs[:, 0]) < 1e-6, 1e-6, dirs[:, 0])
    P = pos + dirs * t[:, None]
    hole = np.zeros(len(t), dtype=bool)
    for y0, y1, z0, z1 in holes:
        hole |= (P[:, 1] >= y0) & (P[:, 1] <= y1) & (P[:, 2] >= z0) & (P[:, 2] <= z1)
    depth = np.where(t > 0, t, 0.0)
    depth = np.where(hole, 0.0, depth)          # looks through: no return
    return depth.reshape(H, W), rays


def check(holes, expect, pos=np.array([44.0, 65.0, 3.0]), tol=0.35):
    depth, rays = frame(holes, pos)
    fit = fit_opening(depth, rays, pos, 0.0, 0, 50.0, np.array([50.0, expect[0], expect[1]]))
    return fit


def test_door():
    f = check([(63.5, 66.5, 1.0, 4.0)], (65.0, 2.5))
    assert f["ok"] and abs(f["w"] - 3.0) < 0.4 and abs(f["h"] - 3.0) < 0.4, f
    assert abs((f["u0"] + f["u1"]) / 2 - 65.0) < 0.3


def test_dock():
    f = check([(62.5, 67.5, 1.0, 5.0)], (65.0, 3.0))
    assert f["ok"] and abs(f["w"] - 5.0) < 0.5 and abs(f["h"] - 4.0) < 0.5, f


def test_two_windows_split():
    holes = [(60.0, 63.0, 1.0, 3.0), (67.0, 70.0, 1.0, 3.0)]
    a = check(holes, (61.5, 2.0), pos=np.array([44.0, 65.0, 2.0]))
    b = check(holes, (68.5, 2.0), pos=np.array([44.0, 65.0, 2.0]))
    assert a["ok"] and b["ok"] and abs(a["w"] - 3.0) < 0.5 and abs(b["w"] - 3.0) < 0.5
    assert a["u1"] < b["u0"]


def test_slot_rejected():
    f = check([(64.6, 65.4, 1.0, 4.0)], (65.0, 2.5))
    assert f is None or not f["ok"]


def test_drift_does_not_open_the_wall():
    """The pose estimate is 1.5 m out: the plane is assumed at x = 50 but the wall really is at 51.5."""
    pos = np.array([44.0, 65.0, 3.0])
    depth, rays = frame([], pos, face=51.5)
    f = fit_opening(depth, rays, pos, 0.0, 0, 50.0, np.array([50.0, 65.0, 2.5]))
    assert f is None or not f["ok"], f
    depth, rays = frame([(63.5, 66.5, 1.0, 4.0)], pos, face=51.5)
    f = fit_opening(depth, rays, pos, 0.0, 0, 50.0, np.array([50.0, 65.0, 2.5]))
    assert f is not None and f["ok"] and abs(f["w"] - 3.0) < 0.5 and abs(f["h"] - 3.0) < 0.5, f


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(name, "ok")
