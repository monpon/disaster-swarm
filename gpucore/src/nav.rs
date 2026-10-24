//! Path planning on the master's navigation grid, in native code: weighted 3D A* over the cleared
//! space (same moves, costs, corner rules and line-of-sight pruning as the Python planner it
//! replaces), clearance-checked straight legs, and the grid dilations the master needs.
use std::cmp::Reverse;
use std::collections::BinaryHeap;

use numpy::{IntoPyArray, PyArrayMethods, PyReadonlyArray3, PyUntypedArrayMethods};
use pyo3::prelude::*;

const NEAR_WALL_COST: f32 = 1.5;
const HEURISTIC_WEIGHT: f32 = 1.5;
const BODY_CLEARANCE: f64 = 0.40;
// (dx, dy, dz, cost): 8 horizontal neighbours + straight up/down
const MOVES: [(i32, i32, i32, f32); 10] = [
    (1, 0, 0, 1.0), (-1, 0, 0, 1.0), (0, 1, 0, 1.0), (0, -1, 0, 1.0),
    (1, 1, 0, 1.414), (1, -1, 0, 1.414), (-1, 1, 0, 1.414), (-1, -1, 0, 1.414),
    (0, 0, 1, 1.0), (0, 0, -1, 1.0),
];

#[derive(Clone, Copy, PartialEq, PartialOrd)]
struct F(f32);
impl Eq for F {}
impl Ord for F {
    fn cmp(&self, o: &Self) -> std::cmp::Ordering {
        self.partial_cmp(o).unwrap_or(std::cmp::Ordering::Equal)
    }
}

#[pyclass]
pub struct Nav {
    sx: i32,
    sy: i32,
    sz: i32,
    pas: Vec<u8>,
    near: Vec<u8>,
    g: Vec<f32>,
    parent: Vec<i32>,
    ver: Vec<u32>,
    cur_ver: u32,
}

fn dilate6(mask: &[u8], sx: usize, sy: usize, sz: usize, iters: usize) -> Vec<u8> {
    let mut cur = mask.to_vec();
    let syz = sy * sz;
    for _ in 0..iters {
        let mut nxt = cur.clone();
        for x in 0..sx {
            for y in 0..sy {
                let row = x * syz + y * sz;
                for z in 0..sz {
                    let i = row + z;
                    if cur[i] != 0 {
                        continue;
                    }
                    let hit = (x > 0 && cur[i - syz] != 0) || (x + 1 < sx && cur[i + syz] != 0)
                        || (y > 0 && cur[i - sz] != 0) || (y + 1 < sy && cur[i + sz] != 0)
                        || (z > 0 && cur[i - 1] != 0) || (z + 1 < sz && cur[i + 1] != 0);
                    if hit {
                        nxt[i] = 1;
                    }
                }
            }
        }
        cur = nxt;
    }
    cur
}

impl Nav {
    #[inline]
    fn flat(&self, x: i32, y: i32, z: i32) -> usize {
        ((x * self.sy + y) * self.sz + z) as usize
    }
    #[inline]
    fn inb(&self, x: i32, y: i32, z: i32) -> bool {
        x >= 0 && y >= 0 && z >= 0 && x < self.sx && y < self.sy && z < self.sz
    }
    #[inline]
    fn ok_(&self, x: i32, y: i32, z: i32) -> bool {
        self.inb(x, y, z) && self.pas[self.flat(x, y, z)] == 1
    }

    fn nearest_ok_(&self, v: [i32; 3], radius: i32) -> Option<[i32; 3]> {
        if self.ok_(v[0], v[1], v[2]) {
            return Some(v);
        }
        let (mut best, mut bd) = (None, i64::MAX);
        for dx in -radius..=radius {
            for dy in -radius..=radius {
                for dz in -radius..=radius {
                    let d = (dx * dx + dy * dy + 2 * dz * dz) as i64;
                    if d < bd && self.ok_(v[0] + dx, v[1] + dy, v[2] + dz) {
                        best = Some([v[0] + dx, v[1] + dy, v[2] + dz]);
                        bd = d;
                    }
                }
            }
        }
        best
    }

    fn line_clear_(&self, a: [i32; 3], b: [i32; 3], body: f64, vertical_legs: bool) -> bool {
        let a = [a[0] as f64 + 0.5, a[1] as f64 + 0.5, a[2] as f64 + 0.5];
        let b = [b[0] as f64 + 0.5, b[1] as f64 + 0.5, b[2] as f64 + 0.5];
        let d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
        let dh = (d[0] * d[0] + d[1] * d[1]).sqrt();
        if vertical_legs && d[2].abs() >= 1.0 && dh >= 1.0 {
            return false;
        }
        let len = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt();
        let n = (len / 0.35).ceil() as i32 + 1;
        let hn = dh;
        let h = if hn > 1e-6 { [-d[1] / hn * body, d[0] / hn * body, 0.0] } else { [body, 0.0, 0.0] };
        let vertical = d[2].abs() > 1e-6 || dh < 1e-6;
        let mut h2 = [0.0f64; 3];
        let mut use_h2 = false;
        if vertical {
            let c = [d[1] * h[2] - d[2] * h[1], d[2] * h[0] - d[0] * h[2], d[0] * h[1] - d[1] * h[0]];
            let cn = (c[0] * c[0] + c[1] * c[1] + c[2] * c[2]).sqrt();
            if cn > 1e-6 {
                h2 = [c[0] / cn * body, c[1] / cn * body, c[2] / cn * body];
                use_h2 = true;
            }
        }
        let steps = if n > 1 { n - 1 } else { 1 };
        for i in 0..n {
            let t = i as f64 / steps as f64;
            let c = [a[0] + d[0] * t, a[1] + d[1] * t, a[2] + d[2] * t];
            let mut offs: Vec<[f64; 3]> = vec![[0.0; 3], h, [-h[0], -h[1], -h[2]]];
            if use_h2 {
                offs.push(h2);
                offs.push([-h2[0], -h2[1], -h2[2]]);
            }
            for o in &offs {
                let (x, y, z) = ((c[0] + o[0]).floor() as i32, (c[1] + o[1]).floor() as i32, (c[2] + o[2]).floor() as i32);
                if !self.inb(x, y, z) || self.pas[self.flat(x, y, z)] != 1 {
                    return false;
                }
            }
        }
        true
    }

    fn prune(&self, cells: &[[i32; 3]]) -> Vec<[i32; 3]> {
        let mut out = vec![cells[0]];
        let mut i = 0usize;
        while i + 1 < cells.len() {
            let mut j = (i + 12).min(cells.len() - 1);
            while j > i + 1 && !self.line_clear_(cells[i], cells[j], BODY_CLEARANCE, true) {
                j -= 1;
            }
            out.push(cells[j]);
            i = j;
        }
        out
    }
}

#[pymethods]
impl Nav {
    /// passable, occupied: (X,Y,Z) arrays (nonzero = true). `near` (passable cells next to an occupied
    /// one) is computed here.
    #[new]
    fn new(passable: PyReadonlyArray3<u8>, occupied: PyReadonlyArray3<u8>) -> PyResult<Self> {
        let sh = passable.shape();
        let (sx, sy, sz) = (sh[0], sh[1], sh[2]);
        let pas: Vec<u8> = passable.as_array().iter().map(|&v| u8::from(v != 0)).collect();
        let occ: Vec<u8> = occupied.as_array().iter().map(|&v| u8::from(v != 0)).collect();
        let d = dilate6(&occ, sx, sy, sz, 1);
        let near: Vec<u8> = d.iter().zip(pas.iter()).map(|(&a, &p)| u8::from(a != 0 && p != 0)).collect();
        let n = sx * sy * sz;
        Ok(Nav { sx: sx as i32, sy: sy as i32, sz: sz as i32, pas, near, g: vec![0.0; n], parent: vec![-1; n], ver: vec![0; n], cur_ver: 0 })
    }

    fn ok(&self, v: [i32; 3]) -> bool {
        self.ok_(v[0], v[1], v[2])
    }

    #[pyo3(signature = (v, radius=3))]
    fn nearest_ok(&self, v: [i32; 3], radius: i32) -> Option<[i32; 3]> {
        self.nearest_ok_(v, radius)
    }

    #[pyo3(signature = (a, b, body=0.40, vertical_legs=false))]
    fn line_clear(&self, a: [i32; 3], b: [i32; 3], body: f64, vertical_legs: bool) -> bool {
        let _ = BODY_CLEARANCE;
        self.line_clear_(a, b, body, vertical_legs)
    }

    /// Voxel path from start to goal pruned to line-of-sight waypoints, or None. With `partial`, an
    /// unreachable goal gives the path to the reachable cell nearest to it.
    #[pyo3(signature = (start, goal, max_expansions=25000, partial=false))]
    fn astar(&mut self, start: [f64; 3], goal: [f64; 3], max_expansions: i64, partial: bool) -> Option<Vec<[i32; 3]>> {
        let fl = |v: [f64; 3]| [v[0].floor() as i32, v[1].floor() as i32, v[2].floor() as i32];
        let s = self.nearest_ok_(fl(start), 3)?;
        let g = self.nearest_ok_(fl(goal), 3)?;
        if self.line_clear_(s, g, BODY_CLEARANCE, true) {
            return Some(vec![s, g]);
        }
        let (sx, sy, sz) = (self.sx, self.sy, self.sz);
        let syz = sy * sz;
        let sf = self.flat(s[0], s[1], s[2]) as i32;
        let gf = self.flat(g[0], g[1], g[2]) as i32;
        let h = |f: i32| -> f32 {
            let x = f / syz;
            let r = f % syz;
            let y = r / sz;
            let z = r % sz;
            let dx = (x - g[0]).abs() as f32;
            let dy = (y - g[1]).abs() as f32;
            HEURISTIC_WEIGHT * (dx.max(dy) + 0.414 * dx.min(dy) + (z - g[2]).abs() as f32)
        };
        // Among equal-cost routes prefer the one that hugs the straight start-goal line (the usual cross-product
        // tie-break): grid A* otherwise picks an arbitrary staircase, and the choice flips as the map changes.
        let (s0, s1) = (s[0], s[1]);
        let hk = |f: i32| -> f32 {
            let x = f / syz;
            let y = (f % syz) / sz;
            let cross = ((x - g[0]) * (s1 - g[1]) - (s0 - g[0]) * (y - g[1])).abs() as f32;
            h(f) + 0.002 * cross
        };
        self.cur_ver = self.cur_ver.wrapping_add(1);
        let ver = self.cur_ver;
        let mut open: BinaryHeap<Reverse<(F, F, i32)>> = BinaryHeap::new();
        self.ver[sf as usize] = ver;
        self.g[sf as usize] = 0.0;
        self.parent[sf as usize] = -1;
        open.push(Reverse((F(hk(sf)), F(0.0), sf)));
        let (mut near_f, mut near_h) = (sf, h(sf));
        let mut exp = 0i64;
        let mut found = false;
        while let Some(Reverse((_, F(gc), cur))) = open.pop() {
            if cur == gf {
                found = true;
                break;
            }
            if gc > self.g[cur as usize] {
                continue;
            }
            let hc = h(cur);
            if hc < near_h {
                near_f = cur;
                near_h = hc;
            }
            exp += 1;
            if exp > max_expansions {
                break;
            }
            let x = cur / syz;
            let r = cur % syz;
            let y = r / sz;
            let z = r % sz;
            for &(dx, dy, dz, c) in MOVES.iter() {
                let (nx, ny, nz) = (x + dx, y + dy, z + dz);
                if nx < 0 || ny < 0 || nz < 0 || nx >= sx || ny >= sy || nz >= sz {
                    continue;
                }
                let nf = cur + dx * syz + dy * sz + dz;
                if self.pas[nf as usize] == 0 {
                    continue;
                }
                if dx != 0 && dy != 0 {
                    let a = (cur + dx * syz) as usize;
                    let b = (cur + dy * sz) as usize;
                    if self.pas[a] == 0 || self.pas[b] == 0 {
                        continue; // no corner cutting
                    }
                    if self.near[a] != 0 || self.near[b] != 0 {
                        continue; // pass openings and corners square-on, not diagonally
                    }
                }
                let ng = gc + c + if self.near[nf as usize] != 0 { NEAR_WALL_COST } else { 0.0 };
                let better = self.ver[nf as usize] != ver || ng < self.g[nf as usize];
                if better {
                    self.ver[nf as usize] = ver;
                    self.g[nf as usize] = ng;
                    self.parent[nf as usize] = cur;
                    open.push(Reverse((F(ng + hk(nf)), F(ng), nf)));
                }
            }
        }
        let mut end = gf;
        if !found && !(self.ver[gf as usize] == ver && self.parent[gf as usize] != -1) {
            if !partial || near_f == sf {
                return None;
            }
            end = near_f;
        }
        let mut path = vec![end];
        let mut guard = 0;
        while self.parent[*path.last().unwrap() as usize] != -1 && guard < 1_000_000 {
            path.push(self.parent[*path.last().unwrap() as usize]);
            guard += 1;
        }
        path.reverse();
        let cells: Vec<[i32; 3]> = path.iter().map(|&f| {
            let x = f / syz;
            let r = f % syz;
            [x, r / sz, r % sz]
        }).collect();
        Some(self.prune(&cells))
    }
}

/// Binary dilation with the 6-neighbourhood (`scipy.ndimage.binary_dilation` defaults), `iters` times.
#[pyfunction]
pub fn dilate<'py>(py: Python<'py>, mask: PyReadonlyArray3<u8>, iters: usize) -> PyResult<Bound<'py, numpy::PyArray3<u8>>> {
    let sh = mask.shape();
    let m: Vec<u8> = mask.as_array().iter().map(|&v| u8::from(v != 0)).collect();
    let d = dilate6(&m, sh[0], sh[1], sh[2], iters);
    d.into_pyarray(py).reshape([sh[0], sh[1], sh[2]])
}
