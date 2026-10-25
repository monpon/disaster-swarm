"""Marching cubes on the GPU (PyTorch), for the surface mesher.

Uses the classic Bourke/Lewiner case table (taken from scikit-image so there is no table
to mistype). Every cube of a chunk is classified at once; triangles are generated for all
active cubes in one go and vertices are shared by edge, so no CPU loop touches the volume.
"""
from __future__ import annotations

import base64

import numpy as np

CORNERS = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)])
EDGES = np.array([(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)])


def _triangle_table() -> np.ndarray:
    from skimage.measure._marching_cubes_lewiner_luts import CASESCLASSIC
    shape, data = CASESCLASSIC
    return np.frombuffer(base64.b64decode(data), dtype=np.int8).reshape(shape).astype(np.int64)


class GpuMarchingCubes:
    def __init__(self, torch, device):
        self.torch, self.device = torch, device
        self.tri = torch.as_tensor(_triangle_table(), device=device)  # (256, 16) edge ids, -1 pad
        self.corners = torch.as_tensor(CORNERS, device=device)
        self.edge_a = torch.as_tensor(EDGES[:, 0], device=device)
        self.edge_b = torch.as_tensor(EDGES[:, 1], device=device)
        self.bits = (1 << torch.arange(8, device=device)).view(8, 1, 1, 1)

    def __call__(self, vol, cube_ok):
        """vol (X,Y,Z) float, cube_ok (X-1,Y-1,Z-1) bool -> verts (V,3) in voxel units,
        faces (F,3) indices. The surface is where vol crosses 0 (negative = inside)."""
        torch = self.torch
        X, Y, Z = vol.shape
        cs = [vol[dx:X - 1 + dx, dy:Y - 1 + dy, dz:Z - 1 + dz] for dx, dy, dz in CORNERS.tolist()]
        inside = torch.stack([c < 0 for c in cs])  # (8, X-1, Y-1, Z-1)
        idx = (inside.long() * self.bits).sum(0)
        active = cube_ok & (idx > 0) & (idx < 255)
        cells = active.nonzero()  # (K, 3)
        if len(cells) == 0:
            return vol.new_zeros((0, 3)), torch.zeros((0, 3), dtype=torch.long, device=vol.device)
        rows = self.tri[idx[active]]  # (K, 16)
        tri_e = rows[:, :15].reshape(-1, 3)  # up to 5 triangles per cube
        base = cells.repeat_interleave(5, dim=0)
        ok = tri_e[:, 0] >= 0
        tri_e, base = tri_e[ok], base[ok]  # (F, 3) edge ids, (F, 3) cell origins
        e = tri_e.reshape(-1)
        bc = base.repeat_interleave(3, dim=0)
        pa = bc + self.corners[self.edge_a[e]]
        pb = bc + self.corners[self.edge_b[e]]
        va = vol[pa[:, 0], pa[:, 1], pa[:, 2]]
        vb = vol[pb[:, 0], pb[:, 1], pb[:, 2]]
        t = (va / (va - vb)).clamp(0, 1)
        v = pa.float() + t[:, None] * (pb - pa).float()
        # Share vertices by edge: key = lower corner of the edge + its axis.
        lo = torch.minimum(pa, pb)
        axis = ((pb - pa) != 0).long().argmax(dim=1)
        key = ((lo[:, 0] * Y + lo[:, 1]) * Z + lo[:, 2]) * 3 + axis
        uniq, inv = torch.unique(key, return_inverse=True)
        verts = torch.zeros((len(uniq), 3), device=vol.device, dtype=v.dtype)
        verts[inv] = v
        return verts, inv.reshape(-1, 3)
