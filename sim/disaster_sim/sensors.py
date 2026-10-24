"""Forward-facing gimbal camera: scans ground/roof cells and building wall patches.

The gimbal follows the drone's heading (yaw) and holds a commanded downward pitch
regardless of airframe attitude: steep for mapping ground and roofs, nearly level for
scanning building walls. Line of sight is checked against the true heightmap, so
structures hide whatever is behind them.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import SimConfig
from .world import World

MIN_AGL = 2.0
OCCLUSION_SAMPLES = 14


@dataclass
class Detection:
    drone: int
    x: float
    y: float
    range: float


@dataclass
class View:
    """What one camera saw this frame."""
    cells: np.ndarray  # flat grid indices
    cell_dist: np.ndarray
    patches: np.ndarray  # facade patch indices
    patch_dist: np.ndarray
    patch_facing: np.ndarray  # cos(angle between view ray and wall normal)


def camera_axes(yaw: float, pitch: float):
    """Forward, right and up unit vectors for a camera at `yaw`, tilted down by `pitch`."""
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    fwd = np.array([cy * cp, sy * cp, -sp])
    right = np.array([sy, -cy, 0.0])
    up = np.cross(right, fwd)
    return fwd, right, up


class Camera:
    def __init__(self, world: World, rng: np.random.Generator, cfg: SimConfig):
        self.world = world
        self.rng = rng
        self.tan_h = np.tan(np.deg2rad(cfg.cam_hfov_deg) / 2)
        self.tan_v = np.tan(np.deg2rad(cfg.cam_vfov_deg) / 2)
        self.range = cfg.cam_range
        self.detect_range = cfg.detect_range
        n = world.n
        self.xs, _ = world.cell_center(np.arange(n), np.arange(n))
        f = world.facades
        # Sample points sit just off the wall so rays don't clip their own building.
        self.patch_pts = f.center + f.normal * 0.3
        self.patch_normals = f.normal

    def _in_frustum(self, d: np.ndarray, fwd, right, up) -> np.ndarray:
        zc = d @ fwd
        xc = d @ right
        yc = d @ up
        dist = np.sqrt((d ** 2).sum(axis=-1))
        safe = np.maximum(zc, 1e-6)
        return (zc > 0.5) & (np.abs(xc) <= self.tan_h * safe) & (np.abs(yc) <= self.tan_v * safe) & (dist <= self.range)

    def _visible(self, cam: np.ndarray, pts: np.ndarray, stop_short: float = 0.0) -> np.ndarray:
        """Line-of-sight test from `cam` to each point in `pts` (M,3) against the heightmap.

        `stop_short` ends each ray that many meters before its target, so a point on a
        building is not occluded by the building it belongs to.
        """
        if len(pts) == 0:
            return np.zeros(0, dtype=bool)
        dist = np.sqrt(((pts - cam[None, :]) ** 2).sum(axis=1))
        s_max = np.clip(1.0 - stop_short / np.maximum(dist, 1e-6), 0.0, 0.98)
        s = np.linspace(0.04, 1.0, OCCLUSION_SAMPLES)[None, :, None] * s_max[:, None, None]
        ray = cam[None, None, :] + s * (pts[:, None, :] - cam[None, None, :])
        w = self.world
        inb = w.in_bounds(ray[..., 0], ray[..., 1])
        h = np.where(inb, w.height_at(ray[..., 0], ray[..., 1]), 0.0)
        return ~(h > ray[..., 2] + 0.3).any(axis=1)

    def view(self, cam: np.ndarray, yaw: float, pitch: float) -> View:
        w = self.world
        r = self.range
        fwd, right, up = camera_axes(yaw, pitch)

        # Ground and roof cells (top surfaces). Structures taller than the camera are
        # seen by their face just below camera height.
        i0, j0 = w.cell_of(cam[0] - r, cam[1] - r)
        i1, j1 = w.cell_of(cam[0] + r, cam[1] + r)
        X, Y = np.meshgrid(self.xs[i0:i1 + 1], self.xs[j0:j1 + 1], indexing="ij")
        H = w.heightmap[i0:i1 + 1, j0:j1 + 1]
        Z = np.minimum(H, cam[2] - 1.0)
        d = np.stack([X - cam[0], Y - cam[1], Z - cam[2]], axis=-1)
        inside = self._in_frustum(d, fwd, right, up)
        cells, cell_dist = np.zeros(0, dtype=int), np.zeros(0)
        if inside.any():
            ii, jj = np.nonzero(inside)
            pts = np.stack([X[ii, jj], Y[ii, jj], Z[ii, jj]], axis=1)
            vis = self._visible(cam, pts, stop_short=0.75 * w.cfg.cell_size)
            cells = (ii[vis] + i0) * w.n + (jj[vis] + j0)
            cell_dist = np.sqrt(((pts[vis] - cam[None, :]) ** 2).sum(axis=1))

        # Wall patches: must face the camera, sit in the frustum and be unoccluded.
        patches, patch_dist, facing = np.zeros(0, dtype=int), np.zeros(0), np.zeros(0)
        if len(self.patch_pts):
            d = self.patch_pts - cam[None, :]
            dist = np.sqrt((d ** 2).sum(axis=1))
            cos = -(d * self.patch_normals).sum(axis=1) / np.maximum(dist, 1e-6)
            cand = np.flatnonzero((cos > 0.15) & (dist <= r))
            if len(cand):
                cand = cand[self._in_frustum(d[cand], fwd, right, up)]
            if len(cand):
                vis = self._visible(cam, self.patch_pts[cand], stop_short=1.2)
                patches = cand[vis]
                patch_dist = dist[patches]
                facing = cos[patches]
        return View(cells, cell_dist, patches, patch_dist, facing)

    def sense(self, pos: np.ndarray, yaw: np.ndarray, pitch: np.ndarray, active: np.ndarray):
        """Returns (agl, cam_on, views, detections) for all drones; views[i] is a View or None."""
        w = self.world
        ground = np.where(w.in_bounds(pos[:, 0], pos[:, 1]), w.height_at(pos[:, 0], pos[:, 1]), 0.0)
        agl = pos[:, 2] - ground
        cam_on = active & (agl > MIN_AGL)
        views = [self.view(pos[i], yaw[i], pitch[i]) if cam_on[i] else None for i in range(len(pos))]

        detections: list[Detection] = []
        for i in np.flatnonzero(cam_on):
            fwd, right, up = camera_axes(yaw[i], pitch[i])
            for s in w.survivors:
                target = np.array([s.x, s.y, s.z + 0.5])
                d = target - pos[i]
                dist = float(np.linalg.norm(d))
                if dist > self.detect_range or not self._in_frustum(d[None, :], fwd, right, up)[0]:
                    continue
                if not self._visible(pos[i], target[None, :])[0]:
                    continue
                p = np.clip(1.2 - dist / self.detect_range, 0.1, 0.95)
                if self.rng.random() < p:
                    sigma = 0.3 + 0.03 * dist
                    nx, ny = self.rng.normal(0, sigma, 2)
                    detections.append(Detection(int(i), s.x + nx, s.y + ny, dist))
        return agl, cam_on, views, detections
