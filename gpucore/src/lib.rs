//! GPU core of the disaster-swarm simulator. One `Core` owns every device buffer and kernel; Python
//! calls a few coarse methods per tick (render, fuse, smooth, stream, ...) and never launches a GPU op.
use std::collections::HashMap;
use std::sync::Arc;

use cudarc::driver::{CudaContext, CudaFunction, CudaSlice, CudaStream, DeviceRepr, LaunchConfig, PushKernelArg};
use cudarc::nvrtc::{compile_ptx_with_opts, CompileOptions};
use numpy::{IntoPyArray, PyArrayMethods, PyReadonlyArray1, PyReadonlyArray2, PyReadonlyArray3, PyUntypedArrayMethods};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

mod mc_table;
mod nav;

const MAX_BATCH: usize = 32; // frames processed per call
const PCAP: usize = 6_000_000; // point store capacity (the last slot is reserved)
const SURV_CAP: usize = 64;
const BLOCK: u32 = 256;

#[repr(C)]
#[derive(Clone, Copy)]
struct TsdfDims { nx: i32, ny: i32, nz: i32, ncx: i32, ncy: i32, ncz: i32 }
unsafe impl DeviceRepr for TsdfDims {}

const PLANE_CAP: usize = 64; // detected wall planes per axis
const OPEN_CAP: usize = 512; // detected openings
const CHP: usize = 34; // grid points per chunk side (marching cubes uses 0..32, dual contouring -1..32)
const NSLOTS: usize = CHP * CHP * CHP * 3;
const MAX_TRI: usize = 5 * 32 * 32 * 32;

struct ChunkMesh { ver: i32, t: f64, v: Vec<u16>, n: Vec<i8>, c: Vec<u8>, f: Vec<u32> }

#[repr(C)]
#[derive(Clone, Copy)]
struct MapDims {
    sx: i32, sy: i32, sz: i32, n: i32, pcx: i32, pcy: i32, pcz: i32, pcap: i32, w: i32, h: i32, npix: i32, ns: i32,
}
unsafe impl DeviceRepr for MapDims {}

fn err<E: std::fmt::Display>(e: E) -> PyErr {
    PyRuntimeError::new_err(e.to_string())
}

fn cfg(n: usize) -> LaunchConfig {
    LaunchConfig { grid_dim: (((n as u32) + BLOCK - 1) / BLOCK, 1, 1), block_dim: (BLOCK, 1, 1), shared_mem_bytes: 0 }
}

type R<T> = PyResult<T>;

macro_rules! z {
    ($s:expr, $t:ty, $n:expr) => {
        $s.alloc_zeros::<$t>($n).map_err(err)?
    };
}

fn vec2<T: numpy::Element + Copy>(a: &PyReadonlyArray2<T>) -> Vec<T> {
    a.as_array().iter().copied().collect()
}

#[pyclass]
struct Core {
    stream: Arc<CudaStream>,
    k: HashMap<&'static str, CudaFunction>,
    w: i32,
    h: i32,
    n: usize,
    hfov_deg: f32,
    wdim: [i32; 3],
    pad: i32,
    nsteps: i32,
    step: f32,
    world: CudaSlice<u8>,
    rays: CudaSlice<f32>,
    steps: CudaSlice<f32>,
    colors: CudaSlice<f32>,
    fdepth: CudaSlice<f32>,
    frgb: CudaSlice<u8>,
    free: Vec<u32>,
    depth_tmp: CudaSlice<f32>,
    rgb_tmp: CudaSlice<f32>,
    deg_tmp: CudaSlice<f32>,
    est: CudaSlice<f32>,
    dims: MapDims,
    q_params: [f32; 3],
    carve_max: f32,
    palette: CudaSlice<f32>,
    npal: i32,
    lo: CudaSlice<i32>, csum: CudaSlice<f32>, cnt: CudaSlice<i32>, mat: CudaSlice<u8>, quality: CudaSlice<f32>,
    seen: CudaSlice<f32>, stamp: CudaSlice<i32>, npass: CudaSlice<i32>, vdir: CudaSlice<i32>, lastpass: CudaSlice<f32>,
    vres: CudaSlice<f32>, pvox: CudaSlice<i32>,
    cstamp: CudaSlice<i32>, hstamp: CudaSlice<i32>, delta: CudaSlice<i32>, hitfr: CudaSlice<i32>, qb: CudaSlice<f32>,
    seenb: CudaSlice<f32>, sidebits: CudaSlice<i32>, tmaxb: CudaSlice<f32>, vtmp: CudaSlice<f32>,
    pidx: CudaSlice<i32>, psum: CudaSlice<f32>, pw: CudaSlice<f32>, pcsum: CudaSlice<f32>, praw: CudaSlice<f32>,
    spos: CudaSlice<f32>, pnorm: CudaSlice<f32>, presid: CudaSlice<f32>, pt0: CudaSlice<f32>, nview: CudaSlice<i32>,
    pdir: CudaSlice<i32>, pmiss: CudaSlice<i32>, phid: CudaSlice<u8>, pdrone: CudaSlice<i16>, pcol: CudaSlice<u8>,
    pver: CudaSlice<i32>, prv: CudaSlice<i32>, pdirty: CudaSlice<u8>, pnew: CudaSlice<u8>, pst1: CudaSlice<i32>,
    pst2: CudaSlice<i32>, pgh: CudaSlice<i32>, npts: CudaSlice<i32>, sparse2d: CudaSlice<u8>,
    sent_ver: CudaSlice<i32>, sent_raw: CudaSlice<f32>, sent_sm: CudaSlice<f32>, sent_hid: CudaSlice<u8>,
    seen_sent: CudaSlice<f32>,
    pos_c: CudaSlice<f32>, rot_c: CudaSlice<f32>, ares: CudaSlice<f32>, clear: CudaSlice<f32>,
    surv: CudaSlice<f32>, surv_n: CudaSlice<i32>, cone: Option<CudaSlice<i32>>, ncone: i32,
    interior: CudaSlice<u8>,
    per_mat: CudaSlice<f32>,
    nmat: i32,
    // surface (TSDF + mesher)
    td: TsdfDims,
    lm: CudaSlice<f32>, nlm: i32,
    ts_s: CudaSlice<f32>, ts_w: CudaSlice<f32>, ts_sc: CudaSlice<f32>, ts_wc: CudaSlice<f32>, ts_dirty: CudaSlice<u8>,
    m_field: CudaSlice<f32>, m_obs: CudaSlice<u8>, m_used: CudaSlice<u8>, m_vid: CudaSlice<i32>, m_bsum: CudaSlice<i32>,
    m_tri: CudaSlice<i32>, m_ntri: CudaSlice<i32>, m_total: CudaSlice<i32>, m_pos: CudaSlice<u16>, m_nrm: CudaSlice<i8>,
    m_col: CudaSlice<u8>, m_faces: CudaSlice<u32>, m_table: CudaSlice<i8>, m_kern: CudaSlice<f32>, m_ksum3: f32,
    dc: bool, dc_act: CudaSlice<u8>, dc_pos: CudaSlice<f32>, dc_nrm: CudaSlice<f32>,
    m_planes: CudaSlice<f32>, m_nplanes: CudaSlice<i32>, m_opens: CudaSlice<f32>, nopen: i32,
    planes: Vec<Vec<f32>>, hist: Vec<Vec<f32>>, chunk_hist: HashMap<u32, Vec<(u8, u16)>>, planes_t: f64,
    chunks: HashMap<u32, ChunkMesh>, meshed_at: HashMap<u32, f64>,
    frame_ctr: u32,
    batch_ctr: i32,
    sm_off: i32,
}

#[pymethods]
impl Core {
    /// world: padded (X,Y,Z) uint8 voxel materials; rays: (N,3) body-frame unit rays; steps: (S,) march
    /// distances; colors: (nmat,3); shape: (sx,sy,sz) of the map grid; palette: classifiable colors (K,3).
    #[new]
    #[pyo3(signature = (world, pad, rays, cam_w, cam_h, hfov_deg, steps, step, colors, shape, palette, carve_max, q_near, q_far, q_thresh, slots=4096))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        world: PyReadonlyArray3<u8>,
        pad: i32,
        rays: PyReadonlyArray2<f32>,
        cam_w: i32,
        cam_h: i32,
        hfov_deg: f32,
        steps: PyReadonlyArray1<f32>,
        step: f32,
        colors: PyReadonlyArray2<f32>,
        shape: (i32, i32, i32),
        palette: PyReadonlyArray2<f32>,
        carve_max: f32,
        q_near: f32,
        q_far: f32,
        q_thresh: f32,
        slots: usize,
    ) -> R<Self> {
        let ctx = CudaContext::new(0).map_err(err)?;
        let s = ctx.default_stream();
        let src = [
            include_str!("common.cuh"), include_str!("camera.cu"), include_str!("map.cu"),
            include_str!("align.cu"), include_str!("smooth.cu"), include_str!("stream.cu"), include_str!("comms.cu"), include_str!("mesh.cu"),
        ]
        .join("\n");
        let opts = CompileOptions { fmad: Some(false), arch: Some("compute_80"), ..Default::default() };
        let ptx = compile_ptx_with_opts(src, opts).map_err(err)?;
        let module = ctx.load_module(ptx).map_err(err)?;
        let names: [&'static str; 41] = [
            "render", "degrade_a", "degrade_b", "depthnet", "k_carve", "k_hit", "k_apply", "k_pts_claim", "k_pts_acc",
            "k_pts_fin", "k_align", "k_apply_align", "k_scale_est", "k_clear_ahead", "k_sm_collect", "k_sm_a", "k_sm_b",
            "k_sm_c", "k_sm_d", "k_redirty", "k_vox_collect", "k_vox_pack", "k_pt_cand", "k_pt_decide", "k_pt_pack",
            "k_seen_collect", "k_snr", "k_tsdf", "k_chunk_field", "k_mc_count", "k_scan_block", "k_scan_blocks",
            "k_scan_add", "k_mc_verts", "k_mc_faces", "k_dc_cells", "k_dc_quads", "k_dc_verts", "k_fill_map", "k_fill_tsdf", "k_carve_map",
        ];
        let mut k = HashMap::new();
        for name in names.iter() {
            k.insert(*name, module.load_function(name).map_err(err)?);
        }
        let n_pix = (cam_w * cam_h) as usize;
        let dims_w = world.shape();
        let (sx, sy, sz) = shape;
        let nv = (sx * sy * sz) as usize;
        let (pcx, pcy, pcz) = (((sx as f32) / 0.25).ceil() as i32, ((sy as f32) / 0.25).ceil() as i32, ((sz as f32) / 0.25).ceil() as i32);
        let ncell = (pcx as usize) * (pcy as usize) * (pcz as usize);
        let steps_v: Vec<f32> = steps.as_slice().map_err(err)?.to_vec();
        let ns = steps_v.len() as i32;
        let wflat: Vec<u8> = world.as_array().iter().copied().collect();
        let neg1_f = |n: usize| vec![-1.0f32; n];
        let (tnx, tny, tnz) = (((sx as f32) / 0.2).ceil() as i32, ((sy as f32) / 0.2).ceil() as i32, ((sz as f32) / 0.2).ceil() as i32);
        let td = TsdfDims { nx: tnx, ny: tny, nz: tnz, ncx: (tnx + 31) / 32, ncy: (tny + 31) / 32, ncz: (tnz + 31) / 32 };
        let tn = (tnx as usize) * (tny as usize) * (tnz as usize);
        // Gaussian (sigma 1.2 voxels, 7 taps) for smoothing the distance field; ksum3 = sum of the 3D kernel
        let kern: Vec<f32> = (-3i32..=3).map(|r| (-((r * r) as f32) / (2.0 * 1.2 * 1.2)).exp()).collect();
        let ksum3 = kern.iter().sum::<f32>().powi(3);
        let dims = MapDims { sx, sy, sz, n: nv as i32, pcx, pcy, pcz, pcap: PCAP as i32, w: cam_w, h: cam_h, npix: n_pix as i32, ns };
        Ok(Core {
            k,
            w: cam_w, h: cam_h, n: n_pix, hfov_deg,
            wdim: [dims_w[0] as i32, dims_w[1] as i32, dims_w[2] as i32], pad, nsteps: ns, step,
            world: s.clone_htod(&wflat).map_err(err)?,
            rays: s.clone_htod(&vec2(&rays)).map_err(err)?,
            steps: s.clone_htod(&steps_v).map_err(err)?,
            colors: s.clone_htod(&vec2(&colors)).map_err(err)?,
            fdepth: z!(s, f32, slots * n_pix),
            frgb: z!(s, u8, slots * n_pix * 3),
            free: (0..slots as u32).rev().collect(),
            depth_tmp: z!(s, f32, MAX_BATCH * n_pix),
            rgb_tmp: z!(s, f32, MAX_BATCH * n_pix * 3),
            deg_tmp: z!(s, f32, MAX_BATCH * n_pix * 3),
            est: z!(s, f32, MAX_BATCH * n_pix),
            dims, q_params: [q_near, q_far, q_thresh], carve_max,
            npal: palette.shape()[0] as i32,
            palette: s.clone_htod(&vec2(&palette)).map_err(err)?,
            lo: z!(s, i32, nv), csum: z!(s, f32, nv * 3), cnt: z!(s, i32, nv), mat: z!(s, u8, nv), quality: z!(s, f32, nv),
            seen: s.clone_htod(&neg1_f(nv)).map_err(err)?, stamp: s.clone_htod(&vec![-1i32; nv]).map_err(err)?,
            npass: z!(s, i32, nv), vdir: z!(s, i32, nv), lastpass: s.clone_htod(&vec![-1e9f32; nv]).map_err(err)?,
            vres: z!(s, f32, nv), pvox: z!(s, i32, nv),
            cstamp: z!(s, i32, nv), hstamp: z!(s, i32, nv), delta: z!(s, i32, nv), hitfr: z!(s, i32, nv), qb: z!(s, f32, nv),
            seenb: s.clone_htod(&neg1_f(nv)).map_err(err)?, sidebits: z!(s, i32, nv),
            tmaxb: s.clone_htod(&neg1_f(nv)).map_err(err)?, vtmp: z!(s, f32, nv),
            pidx: s.clone_htod(&vec![-1i32; ncell]).map_err(err)?,
            psum: z!(s, f32, PCAP * 3), pw: z!(s, f32, PCAP), pcsum: z!(s, f32, PCAP * 3), praw: z!(s, f32, PCAP * 3),
            spos: z!(s, f32, PCAP * 3), pnorm: z!(s, f32, PCAP * 3), presid: z!(s, f32, PCAP), pt0: z!(s, f32, PCAP),
            nview: z!(s, i32, PCAP), pdir: z!(s, i32, PCAP), pmiss: z!(s, i32, PCAP), phid: z!(s, u8, PCAP),
            pdrone: z!(s, i16, PCAP), pcol: z!(s, u8, PCAP * 3), pver: z!(s, i32, PCAP), prv: z!(s, i32, PCAP),
            pdirty: z!(s, u8, PCAP), pnew: z!(s, u8, PCAP), pst1: z!(s, i32, PCAP), pst2: z!(s, i32, PCAP),
            pgh: z!(s, i32, PCAP), npts: z!(s, i32, 1), sparse2d: z!(s, u8, (sx * sy) as usize),
            sent_ver: z!(s, i32, PCAP), sent_raw: z!(s, f32, PCAP * 3), sent_sm: z!(s, f32, PCAP * 3), sent_hid: z!(s, u8, PCAP),
            seen_sent: s.clone_htod(&neg1_f(nv)).map_err(err)?,
            pos_c: z!(s, f32, MAX_BATCH * 3), rot_c: z!(s, f32, MAX_BATCH * 9), ares: z!(s, f32, MAX_BATCH * 24),
            clear: z!(s, f32, MAX_BATCH), surv: z!(s, f32, SURV_CAP * 6), surv_n: z!(s, i32, 1), cone: None, ncone: 0,
            interior: z!(s, u8, nv), per_mat: z!(s, f32, 16), nmat: colors.shape()[0] as i32,
            td, lm: z!(s, f32, 8 * 8), nlm: 0, ts_s: z!(s, f32, tn), ts_w: z!(s, f32, tn), ts_sc: z!(s, f32, tn * 3), ts_wc: z!(s, f32, tn),
            ts_dirty: z!(s, u8, (td.ncx * td.ncy * td.ncz) as usize),
            m_field: z!(s, f32, CHP * CHP * CHP), m_obs: z!(s, u8, CHP * CHP * CHP), m_used: z!(s, u8, NSLOTS),
            m_vid: z!(s, i32, NSLOTS), m_bsum: z!(s, i32, NSLOTS / 1024 + 2), m_tri: z!(s, i32, MAX_TRI * 3),
            m_ntri: z!(s, i32, 1), m_total: z!(s, i32, 1), m_pos: z!(s, u16, NSLOTS * 3), m_nrm: z!(s, i8, NSLOTS * 3),
            m_col: z!(s, u8, NSLOTS * 3), m_faces: z!(s, u32, MAX_TRI * 3),
            m_table: s.clone_htod(&mc_table::MC_TRI.to_vec()).map_err(err)?,
            m_kern: s.clone_htod(&kern).map_err(err)?, m_ksum3: ksum3,
            dc: std::env::var("DISASTER_MESH").map(|v| v != "mc").unwrap_or(true),
            dc_act: z!(s, u8, CHP * CHP * CHP), dc_pos: z!(s, f32, CHP * CHP * CHP * 3), dc_nrm: z!(s, f32, CHP * CHP * CHP * 3),
            m_planes: z!(s, f32, 3 * PLANE_CAP), m_nplanes: z!(s, i32, 3), m_opens: z!(s, f32, OPEN_CAP * 8), nopen: 0,
            planes: vec![vec![], vec![], vec![]],
            hist: vec![vec![0.0; (sx as usize) * 20 + 2], vec![0.0; (sy as usize) * 20 + 2], vec![0.0; (sz as usize) * 20 + 2]],
            chunk_hist: HashMap::new(), planes_t: -1e18,
            chunks: HashMap::new(), meshed_at: HashMap::new(),
            frame_ctr: 1, batch_ctr: 0, sm_off: 0,
            stream: s,
        })
    }

    // ------------------------------------------------------------------ frame pool
    fn free_slots(&self) -> usize {
        self.free.len()
    }

    fn free_slot(&mut self, slot: u32) {
        self.free.push(slot);
    }

    /// Render and degrade one frame per drone; returns the pool slot of each frame.
    fn render(
        &mut self,
        poss: PyReadonlyArray2<f32>,
        rots: PyReadonlyArray3<f32>,
        omegas: PyReadonlyArray2<f32>,
        indoors: PyReadonlyArray1<u8>,
        seed: u64,
    ) -> R<Vec<u32>> {
        let m = poss.shape()[0];
        if m == 0 {
            return Ok(vec![]);
        }
        if m > MAX_BATCH || self.free.len() < m {
            return Err(err("render batch too large or frame pool exhausted"));
        }
        let slots: Vec<u32> = (0..m).map(|_| self.free.pop().unwrap()).collect();
        let s = &self.stream;
        let d_pos = s.clone_htod(&vec2(&poss)).map_err(err)?;
        let d_rot = s.clone_htod(&rots.as_array().iter().copied().collect::<Vec<f32>>()).map_err(err)?;
        let d_om = s.clone_htod(&vec2(&omegas)).map_err(err)?;
        let d_in = s.clone_htod(indoors.as_slice().map_err(err)?).map_err(err)?;
        let d_slots = s.clone_htod(&slots).map_err(err)?;
        let (mi, ni) = (m as i32, self.n as i32);
        unsafe {
            s.launch_builder(&self.k["render"])
                .arg(&self.world).arg(&self.wdim[0]).arg(&self.wdim[1]).arg(&self.wdim[2]).arg(&self.pad)
                .arg(&self.rays).arg(&self.steps).arg(&self.nsteps).arg(&self.step).arg(&self.colors)
                .arg(&d_pos).arg(&d_rot).arg(&mi).arg(&ni)
                .arg(&mut self.depth_tmp).arg(&mut self.rgb_tmp)
                .launch(cfg(m * self.n)).map_err(err)?;
        }
        let px_per_rad = self.w as f32 / (self.hfov_deg.to_radians());
        let (exposure, gain_out, gain_in, jpeg) = (1.0f32 / 30.0, 0.04f32, 0.09f32, 8.0f32);
        unsafe {
            s.launch_builder(&self.k["degrade_a"])
                .arg(&self.rgb_tmp).arg(&d_om).arg(&d_in).arg(&mi).arg(&self.w).arg(&self.h)
                .arg(&px_per_rad).arg(&exposure).arg(&gain_out).arg(&gain_in).arg(&seed)
                .arg(&mut self.deg_tmp)
                .launch(cfg(m * self.n)).map_err(err)?;
            s.launch_builder(&self.k["degrade_b"])
                .arg(&self.deg_tmp).arg(&mi).arg(&self.w).arg(&self.h).arg(&jpeg).arg(&d_slots)
                .arg(&mut self.frgb)
                .launch(cfg(m * self.n)).map_err(err)?;
        }
        for (j, &slot) in slots.iter().enumerate() {
            let src = self.depth_tmp.slice(j * self.n..(j + 1) * self.n);
            let mut dst = self.fdepth.slice_mut(slot as usize * self.n..(slot as usize + 1) * self.n);
            s.memcpy_dtod(&src, &mut dst).map_err(err)?;
        }
        Ok(slots)
    }

    fn truth_depth<'py>(&self, py: Python<'py>, slot: u32) -> R<Bound<'py, numpy::PyArray2<f32>>> {
        let v = self.stream.clone_dtoh(&self.fdepth.slice(slot as usize * self.n..(slot as usize + 1) * self.n)).map_err(err)?;
        self.stream.synchronize().map_err(err)?;
        v.into_pyarray(py).reshape([self.h as usize, self.w as usize]).map_err(err)
    }

    fn rgb<'py>(&self, py: Python<'py>, slot: u32) -> R<Bound<'py, numpy::PyArray3<u8>>> {
        let v = self.stream.clone_dtoh(&self.frgb.slice(slot as usize * self.n * 3..(slot as usize + 1) * self.n * 3)).map_err(err)?;
        self.stream.synchronize().map_err(err)?;
        v.into_pyarray(py).reshape([self.h as usize, self.w as usize, 3]).map_err(err)
    }

    /// The monocular-depth estimate of frame `j` of the last `fuse` batch (viewer feed / cue), (H,W).
    fn estimate<'py>(&self, py: Python<'py>, j: usize) -> R<Bound<'py, numpy::PyArray2<f32>>> {
        let v = self.stream.clone_dtoh(&self.est.slice(j * self.n..(j + 1) * self.n)).map_err(err)?;
        self.stream.synchronize().map_err(err)?;
        v.into_pyarray(py).reshape([self.h as usize, self.w as usize]).map_err(err)
    }


    /// Depth estimates of the first `b` frames of the last `fuse` batch, (B,N), after corrections.
    fn estimates<'py>(&self, py: Python<'py>, b: usize) -> R<Bound<'py, numpy::PyArray2<f32>>> {
        let v = self.stream.clone_dtoh(&self.est.slice(0..b * self.n)).map_err(err)?;
        self.stream.synchronize().map_err(err)?;
        v.into_pyarray(py).reshape([b, self.n]).map_err(err)
    }

    /// Degraded RGB frames of several pool slots, (B,N,3) uint8.
    fn rgbs<'py>(&self, py: Python<'py>, slots: Vec<u32>) -> R<Bound<'py, numpy::PyArray3<u8>>> {
        let mut out = Vec::with_capacity(slots.len() * self.n * 3);
        for &sl in &slots {
            let v = self.stream.clone_dtoh(&self.frgb.slice(sl as usize * self.n * 3..(sl as usize + 1) * self.n * 3)).map_err(err)?;
            out.extend_from_slice(&v);
        }
        self.stream.synchronize().map_err(err)?;
        out.into_pyarray(py).reshape([slots.len(), self.n, 3]).map_err(err)
    }
    fn set_sparse2d(&mut self, a: PyReadonlyArray2<u8>) -> R<()> {
        let v: Vec<u8> = a.as_array().iter().copied().collect();
        self.stream.memcpy_htod(&v, &mut self.sparse2d).map_err(err)
    }

    /// Pixel indices (into the H*W frame) of the cone straight ahead, for the forward-clearance check.
    fn set_cone(&mut self, idx: PyReadonlyArray1<i32>) -> R<()> {
        let v = idx.as_slice().map_err(err)?.to_vec();
        self.ncone = v.len() as i32;
        self.cone = Some(self.stream.clone_htod(&v).map_err(err)?);
        Ok(())
    }

    // ------------------------------------------------------------------ fuse
    /// Everything numeric for a batch of received frames: depth network, frame-to-map alignment,
    /// corrections, forward clearance, carving, hits, passes, classification, point store.
    /// poss (B,3), rots (B,3,3) are the VIO poses. Returns a dict of small result arrays.
    #[pyo3(signature = (slots, poss, rots, tcap, drone, thumb, seed, scale_sigma, region_sigma, depth_max, tick))]
    #[allow(clippy::too_many_arguments)]
    fn fuse<'py>(
        &mut self,
        py: Python<'py>,
        slots: Vec<u32>,
        poss: PyReadonlyArray2<f32>,
        rots: PyReadonlyArray3<f32>,
        tcap: PyReadonlyArray1<f32>,
        drone: PyReadonlyArray1<i32>,
        thumb: Vec<u8>,
        seed: u64,
        scale_sigma: f32,
        region_sigma: f32,
        depth_max: f32,
        tick: i32,
    ) -> R<Bound<'py, PyDict>> {
        let b = slots.len();
        if b == 0 || b > MAX_BATCH {
            return Err(err("bad batch size"));
        }
        let s = self.stream.clone();
        let bi = b as i32;
        let d_slots = s.clone_htod(&slots).map_err(err)?;
        let d_thumb = s.clone_htod(&thumb).map_err(err)?;
        let d_pos = s.clone_htod(&vec2(&poss)).map_err(err)?;
        let d_rot = s.clone_htod(&rots.as_array().iter().copied().collect::<Vec<f32>>()).map_err(err)?;
        let d_t = s.clone_htod(tcap.as_slice().map_err(err)?).map_err(err)?;
        let d_dr = s.clone_htod(drone.as_slice().map_err(err)?).map_err(err)?;
        self.batch_ctr += 1;
        let batch_id = self.batch_ctr;
        let fid0 = self.frame_ctr;
        self.frame_ctr += b as u32;
        let dims = self.dims;
        let npix = self.n;
        let pstride = ((npix as i32) / 8000).max(1);  // free-space carving and the TSDF use ~8k pixels per frame
        unsafe {
            // 1. depth network on the true depth
            s.launch_builder(&self.k["depthnet"])
                .arg(&self.fdepth).arg(&d_slots).arg(&d_thumb).arg(&bi).arg(&self.w).arg(&self.h)
                .arg(&scale_sigma).arg(&region_sigma).arg(&depth_max).arg(&seed).arg(&mut self.est)
                .launch(cfg(b * npix)).map_err(err)?;
            // 2. align against the smoothed map (one block per frame)
            let sub = (((npix as i32) + 511) / 512).max(1);  // about 512 alignment samples per frame
            s.launch_builder(&self.k["k_align"])
                .arg(&dims).arg(&sub).arg(&self.td).arg(&d_pos).arg(&d_rot).arg(&self.est).arg(&self.rays)
                .arg(&self.ts_s).arg(&self.ts_w).arg(&self.lm).arg(&self.nlm).arg(&mut self.ares)
                .launch(LaunchConfig { grid_dim: (b as u32, 1, 1), block_dim: (BLOCK, 1, 1), shared_mem_bytes: 0 }).map_err(err)?;
            // 3. apply accepted corrections to pose / rotation / depth scale
            s.launch_builder(&self.k["k_apply_align"])
                .arg(&bi).arg(&self.ares).arg(&d_pos).arg(&d_rot).arg(&mut self.pos_c).arg(&mut self.rot_c)
                .launch(cfg(b)).map_err(err)?;
            s.launch_builder(&self.k["k_scale_est"])
                .arg(&dims).arg(&bi).arg(&self.ares).arg(&mut self.est).launch(cfg(b * npix)).map_err(err)?;
            // 3b. fuse the corrected frames into the signed-distance volume
            let (npx, nbi) = (npix as i32, bi);
            s.launch_builder(&self.k["k_tsdf"])
                .arg(&self.td).arg(&nbi).arg(&npx).arg(&self.pos_c).arg(&self.rot_c).arg(&self.est).arg(&d_slots).arg(&self.frgb)
                .arg(&self.rays).arg(&mut self.ts_s).arg(&mut self.ts_w).arg(&mut self.ts_sc).arg(&mut self.ts_wc)
                .arg(&mut self.ts_dirty).arg(&pstride)
                .launch(cfg(b * npix)).map_err(err)?;
            // 4. nearest obstacle straight ahead (for the brake and the speed governor)
            if let Some(cone) = &self.cone {
                s.launch_builder(&self.k["k_clear_ahead"])
                    .arg(&dims).arg(&bi).arg(&self.est).arg(cone).arg(&self.ncone).arg(&mut self.clear)
                    .launch(cfg(b)).map_err(err)?;
            }
            // 5. carve free space (+ ghost removal), hits, apply, point store
            s.launch_builder(&self.k["k_carve"])
                .arg(&dims).arg(&bi).arg(&self.pos_c).arg(&self.rot_c).arg(&self.est).arg(&self.rays).arg(&self.steps)
                .arg(&self.carve_max).arg(&mut self.cstamp).arg(&mut self.delta).arg(&self.pidx).arg(&mut self.pmiss)
                .arg(&mut self.pver).arg(&mut self.pgh).arg(&fid0).arg(&batch_id).arg(&pstride)
                .launch(cfg(b * npix)).map_err(err)?;
            let zero = [0i32];
            s.memcpy_htod(&zero, &mut self.surv_n).map_err(err)?;
            let scap = SURV_CAP as i32;
            s.launch_builder(&self.k["k_hit"])
                .arg(&dims).arg(&bi).arg(&self.pos_c).arg(&self.rot_c).arg(&self.est).arg(&d_slots).arg(&self.frgb).arg(&d_t)
                .arg(&self.rays).arg(&self.q_params[0]).arg(&self.q_params[1]).arg(&self.q_params[2])
                .arg(&mut self.hstamp).arg(&mut self.delta).arg(&mut self.hitfr).arg(&mut self.csum).arg(&mut self.cnt)
                .arg(&mut self.qb).arg(&mut self.seenb).arg(&mut self.sidebits).arg(&mut self.tmaxb)
                .arg(&fid0).arg(&mut self.surv).arg(&mut self.surv_n).arg(&scap)
                .launch(cfg(b * npix)).map_err(err)?;
            let nv = dims.n;
            s.launch_builder(&self.k["k_apply"])
                .arg(&nv).arg(&tick).arg(&self.palette).arg(&self.npal)
                .arg(&mut self.lo).arg(&mut self.delta).arg(&mut self.hitfr).arg(&mut self.csum).arg(&mut self.cnt)
                .arg(&mut self.qb).arg(&mut self.seenb).arg(&mut self.sidebits).arg(&mut self.tmaxb)
                .arg(&mut self.mat).arg(&mut self.quality).arg(&mut self.seen).arg(&mut self.stamp).arg(&mut self.vdir)
                .arg(&mut self.npass).arg(&mut self.lastpass)
                .launch(cfg(nv as usize)).map_err(err)?;
            s.launch_builder(&self.k["k_pts_claim"])
                .arg(&dims).arg(&bi).arg(&self.pos_c).arg(&self.rot_c).arg(&self.est).arg(&self.rays).arg(&d_t).arg(&d_dr)
                .arg(&self.sparse2d).arg(&mut self.pidx).arg(&mut self.npts).arg(&mut self.pt0).arg(&mut self.pdrone)
                .arg(&mut self.pnew)
                .launch(cfg(b * npix)).map_err(err)?;
            s.launch_builder(&self.k["k_pts_acc"])
                .arg(&dims).arg(&bi).arg(&self.pos_c).arg(&self.rot_c).arg(&self.est).arg(&d_slots).arg(&self.frgb).arg(&self.rays)
                .arg(&self.sparse2d).arg(&self.pidx).arg(&mut self.psum).arg(&mut self.pw).arg(&mut self.pcsum)
                .arg(&mut self.nview).arg(&mut self.pdir).arg(&mut self.pst1).arg(&batch_id)
                .launch(cfg(b * npix)).map_err(err)?;
            s.launch_builder(&self.k["k_pts_fin"])
                .arg(&dims).arg(&bi).arg(&self.pos_c).arg(&self.rot_c).arg(&self.est).arg(&self.rays).arg(&self.pidx)
                .arg(&self.psum).arg(&self.pw).arg(&self.pcsum).arg(&mut self.praw).arg(&mut self.spos).arg(&mut self.pcol)
                .arg(&mut self.pnew).arg(&mut self.pver).arg(&mut self.prv).arg(&mut self.pdirty).arg(&mut self.pst2)
                .arg(&mut self.pvox).arg(&batch_id)
                .launch(cfg(b * npix)).map_err(err)?;
        }
        // one sync: bring back the small results
        let ares = s.clone_dtoh(&self.ares.slice(0..b * 24)).map_err(err)?;
        let pos_c = s.clone_dtoh(&self.pos_c.slice(0..b * 3)).map_err(err)?;
        let rot_c = s.clone_dtoh(&self.rot_c.slice(0..b * 9)).map_err(err)?;
        let clear = if self.cone.is_some() { s.clone_dtoh(&self.clear.slice(0..b)).map_err(err)? } else { vec![12.0; b] };
        let surv_n = s.clone_dtoh(&self.surv_n).map_err(err)?[0].max(0).min(SURV_CAP as i32) as usize;
        let surv = s.clone_dtoh(&self.surv.slice(0..surv_n * 6)).map_err(err)?;
        let npts = s.clone_dtoh(&self.npts).map_err(err)?[0];
        s.synchronize().map_err(err)?;
        let d = PyDict::new(py);
        d.set_item("ares", ares.into_pyarray(py).reshape([b, 24]).map_err(err)?)?;
        d.set_item("pos", pos_c.into_pyarray(py).reshape([b, 3]).map_err(err)?)?;
        d.set_item("rot", rot_c.into_pyarray(py).reshape([b, 3, 3]).map_err(err)?)?;
        d.set_item("clear", clear.into_pyarray(py))?;
        d.set_item("surv", surv.into_pyarray(py).reshape([surv_n, 6]).map_err(err)?)?;
        d.set_item("npts", npts)?;
        Ok(d)
    }

    // ------------------------------------------------------------------ host mirrors
    /// Host copies of the arrays the planner reads: lo (int32), mat, quality, npass, vres, pvox.
    fn host_arrays<'py>(&self, py: Python<'py>) -> R<Bound<'py, PyDict>> {
        let s = &self.stream;
        let d = PyDict::new(py);
        d.set_item("lo", s.clone_dtoh(&self.lo).map_err(err)?.into_pyarray(py))?;
        d.set_item("mat", s.clone_dtoh(&self.mat).map_err(err)?.into_pyarray(py))?;
        d.set_item("quality", s.clone_dtoh(&self.quality).map_err(err)?.into_pyarray(py))?;
        d.set_item("npass", s.clone_dtoh(&self.npass).map_err(err)?.into_pyarray(py))?;
        d.set_item("vres", s.clone_dtoh(&self.vres).map_err(err)?.into_pyarray(py))?;
        d.set_item("pvox", s.clone_dtoh(&self.pvox).map_err(err)?.into_pyarray(py))?;
        s.synchronize().map_err(err)?;
        Ok(d)
    }

    fn npoints(&self) -> R<i32> {
        let v = self.stream.clone_dtoh(&self.npts).map_err(err)?[0];
        self.stream.synchronize().map_err(err)?;
        Ok(v)
    }

    // ------------------------------------------------------------------ smoothing
    /// Smooth up to `max_n` dirty points (PCA plane fit; planar points pulled onto their plane; outliers
    /// flagged). Returns how many were processed.
    fn smooth_step(&mut self, max_n: i32) -> R<i32> {
        let s = self.stream.clone();
        let npts = self.npoints()?;
        if npts <= 0 {
            return Ok(0);
        }
        let mut list = z!(s, i32, max_n as usize);
        let mut cnt = z!(s, i32, 1);
        self.sm_off = (self.sm_off + 7919) % npts.max(1);
        let off = self.sm_off;
        let dims = self.dims;
        unsafe {
            s.launch_builder(&self.k["k_sm_collect"]).arg(&npts).arg(&off).arg(&max_n).arg(&mut self.pdirty).arg(&mut list).arg(&mut cnt)
                .launch(cfg(npts as usize)).map_err(err)?;
        }
        let k = s.clone_dtoh(&cnt).map_err(err)?[0].min(max_n);
        s.synchronize().map_err(err)?;
        if k <= 0 {
            return Ok(0);
        }
        let ku = k as usize;
        let mut o_spos = z!(s, f32, ku * 3);
        let mut o_norm = z!(s, f32, ku * 3);
        let mut o_resid = z!(s, f32, ku);
        let mut o_md = z!(s, f32, ku);
        let mut o_cnt = z!(s, i32, ku);
        let mut stats = z!(s, f64, 3);
        unsafe {
            s.launch_builder(&self.k["k_sm_a"])
                .arg(&dims).arg(&list).arg(&k).arg(&self.pidx).arg(&self.praw).arg(&self.pw).arg(&self.phid)
                .arg(&mut o_spos).arg(&mut o_norm).arg(&mut o_resid).arg(&mut o_md).arg(&mut o_cnt).arg(&mut stats)
                .launch(cfg(ku)).map_err(err)?;
            s.launch_builder(&self.k["k_sm_b"])
                .arg(&dims).arg(&list).arg(&k).arg(&o_spos).arg(&o_norm).arg(&o_resid).arg(&o_md).arg(&o_cnt).arg(&stats)
                .arg(&mut self.spos).arg(&mut self.pnorm).arg(&mut self.presid).arg(&mut self.phid).arg(&mut self.pver)
                .arg(&self.praw).arg(&mut self.vtmp)
                .launch(cfg(ku)).map_err(err)?;
            s.launch_builder(&self.k["k_sm_c"]).arg(&dims).arg(&list).arg(&k).arg(&self.praw).arg(&mut self.vres).arg(&mut self.vtmp)
                .launch(cfg(ku)).map_err(err)?;
            s.launch_builder(&self.k["k_sm_d"]).arg(&dims).arg(&list).arg(&k).arg(&self.praw).arg(&mut self.vtmp)
                .launch(cfg(ku)).map_err(err)?;
        }
        s.synchronize().map_err(err)?;
        Ok(k)
    }

    /// Hidden points get another look as their neighbourhoods fill in.
    fn redirty_hidden(&mut self) -> R<()> {
        let npts = self.npoints()?;
        if npts > 0 {
            unsafe {
                self.stream.launch_builder(&self.k["k_redirty"]).arg(&npts).arg(&self.phid).arg(&mut self.pdirty)
                    .launch(cfg(npts as usize)).map_err(err)?;
            }
        }
        Ok(())
    }

    // ------------------------------------------------------------------ viewer stream
    /// Voxels changed after `tick`: (idx, occupied, material, rgb565, quality u8).
    fn vox_deltas<'py>(&mut self, py: Python<'py>, tick: i32) -> R<Bound<'py, PyDict>> {
        let s = self.stream.clone();
        let nv = self.dims.n;
        let mut list = z!(s, i32, nv as usize);
        let mut cnt = z!(s, i32, 1);
        unsafe {
            s.launch_builder(&self.k["k_vox_collect"]).arg(&nv).arg(&tick).arg(&self.stamp).arg(&mut list).arg(&mut cnt)
                .launch(cfg(nv as usize)).map_err(err)?;
        }
        let k = s.clone_dtoh(&cnt).map_err(err)?[0].max(0);
        s.synchronize().map_err(err)?;
        let ku = k as usize;
        let mut o_occ = z!(s, u8, ku.max(1));
        let mut o_mat = z!(s, u8, ku.max(1));
        let mut o_rgb = z!(s, u16, ku.max(1));
        let mut o_q = z!(s, u8, ku.max(1));
        if ku > 0 {
            unsafe {
                s.launch_builder(&self.k["k_vox_pack"])
                    .arg(&list).arg(&k).arg(&self.lo).arg(&self.csum).arg(&self.cnt).arg(&self.mat).arg(&self.quality)
                    .arg(&mut o_occ).arg(&mut o_mat).arg(&mut o_rgb).arg(&mut o_q)
                    .launch(cfg(ku)).map_err(err)?;
            }
        }
        let d = PyDict::new(py);
        d.set_item("idx", s.clone_dtoh(&list.slice(0..ku)).map_err(err)?.into_pyarray(py))?;
        d.set_item("occ", s.clone_dtoh(&o_occ.slice(0..ku)).map_err(err)?.into_pyarray(py))?;
        d.set_item("mat", s.clone_dtoh(&o_mat.slice(0..ku)).map_err(err)?.into_pyarray(py))?;
        d.set_item("rgb", s.clone_dtoh(&o_rgb.slice(0..ku)).map_err(err)?.into_pyarray(py))?;
        d.set_item("q", s.clone_dtoh(&o_q.slice(0..ku)).map_err(err)?.into_pyarray(py))?;
        s.synchronize().map_err(err)?;
        Ok(d)
    }

    /// Point updates for the viewer: new points and points that moved/flipped visibility since last sent.
    #[pyo3(signature = (full, max_updates, min_move))]
    fn point_updates<'py>(&mut self, py: Python<'py>, full: bool, max_updates: i32, min_move: f32) -> R<Bound<'py, PyDict>> {
        let s = self.stream.clone();
        let npts = self.npoints()?;
        let d = PyDict::new(py);
        let cap = if full { npts.max(1) } else { 40000.min(npts.max(1)) };
        let ucap = if full { npts.max(1) } else { max_updates };
        let mut cand = z!(s, i32, cap as usize);
        let mut cnt = z!(s, i32, 1);
        let mut upd = z!(s, i32, ucap as usize);
        let mut ucnt = z!(s, i32, 1);
        let dims = self.dims;
        let fullf = full as i32;
        if npts > 0 {
            unsafe {
                s.launch_builder(&self.k["k_pt_cand"]).arg(&npts).arg(&fullf).arg(&self.pver).arg(&mut self.sent_ver).arg(&mut cand)
                    .arg(&mut cnt).arg(&cap).launch(cfg(npts as usize)).map_err(err)?;
            }
            let kc = s.clone_dtoh(&cnt).map_err(err)?[0].min(cap).max(0);
            s.synchronize().map_err(err)?;
            if kc > 0 {
                unsafe {
                    s.launch_builder(&self.k["k_pt_decide"])
                        .arg(&cand).arg(&kc).arg(&self.pver).arg(&mut self.sent_ver).arg(&self.praw).arg(&self.spos)
                        .arg(&self.sent_raw).arg(&self.sent_sm).arg(&self.sent_hid).arg(&self.phid).arg(&self.pmiss)
                        .arg(&self.nview).arg(&min_move).arg(&mut upd).arg(&mut ucnt).arg(&ucap)
                        .launch(cfg(kc as usize)).map_err(err)?;
                }
            }
        }
        let ku = s.clone_dtoh(&ucnt).map_err(err)?[0].min(ucap).max(0);
        s.synchronize().map_err(err)?;
        let u = ku as usize;
        let mut o_id = z!(s, u32, u.max(1));
        let mut o_raw = z!(s, u16, u.max(1) * 3);
        let mut o_sm = z!(s, u16, u.max(1) * 3);
        let mut o_col = z!(s, u8, u.max(1) * 3);
        let mut o_flag = z!(s, u8, u.max(1));
        let mut o_res = z!(s, u8, u.max(1));
        let mut o_np = z!(s, u8, u.max(1));
        if u > 0 {
            unsafe {
                s.launch_builder(&self.k["k_pt_pack"])
                    .arg(&dims).arg(&upd).arg(&ku).arg(&self.pver).arg(&mut self.sent_ver).arg(&self.praw).arg(&self.spos)
                    .arg(&mut self.sent_raw).arg(&mut self.sent_sm).arg(&mut self.sent_hid).arg(&self.phid).arg(&self.pmiss)
                    .arg(&self.nview).arg(&self.pcol).arg(&self.presid).arg(&self.npass)
                    .arg(&mut o_id).arg(&mut o_raw).arg(&mut o_sm).arg(&mut o_col).arg(&mut o_flag).arg(&mut o_res).arg(&mut o_np)
                    .launch(cfg(u)).map_err(err)?;
            }
        }
        d.set_item("ids", s.clone_dtoh(&o_id.slice(0..u)).map_err(err)?.into_pyarray(py))?;
        d.set_item("raw", s.clone_dtoh(&o_raw.slice(0..u * 3)).map_err(err)?.into_pyarray(py))?;
        d.set_item("sm", s.clone_dtoh(&o_sm.slice(0..u * 3)).map_err(err)?.into_pyarray(py))?;
        d.set_item("col", s.clone_dtoh(&o_col.slice(0..u * 3)).map_err(err)?.into_pyarray(py))?;
        d.set_item("flag", s.clone_dtoh(&o_flag.slice(0..u)).map_err(err)?.into_pyarray(py))?;
        d.set_item("resid", s.clone_dtoh(&o_res.slice(0..u)).map_err(err)?.into_pyarray(py))?;
        d.set_item("npass", s.clone_dtoh(&o_np.slice(0..u)).map_err(err)?.into_pyarray(py))?;
        d.set_item("npts", npts)?;
        s.synchronize().map_err(err)?;
        Ok(d)
    }

    /// Proper-scan times of surfaces re-scanned since the last call (or all, if `full`): (idx, t u16).
    fn seen_updates<'py>(&mut self, py: Python<'py>, full: bool) -> R<Bound<'py, PyDict>> {
        let s = self.stream.clone();
        let nv = self.dims.n;
        let mut list = z!(s, i32, nv as usize);
        let mut tl = z!(s, u16, nv as usize);
        let mut cnt = z!(s, i32, 1);
        let fullf = full as i32;
        unsafe {
            s.launch_builder(&self.k["k_seen_collect"]).arg(&nv).arg(&fullf).arg(&self.seen).arg(&mut self.seen_sent).arg(&self.lo)
                .arg(&mut list).arg(&mut tl).arg(&mut cnt).launch(cfg(nv as usize)).map_err(err)?;
        }
        let k = s.clone_dtoh(&cnt).map_err(err)?[0].max(0) as usize;
        s.synchronize().map_err(err)?;
        let d = PyDict::new(py);
        d.set_item("idx", s.clone_dtoh(&list.slice(0..k)).map_err(err)?.into_pyarray(py))?;
        d.set_item("t", s.clone_dtoh(&tl.slice(0..k)).map_err(err)?.into_pyarray(py))?;
        s.synchronize().map_err(err)?;
        Ok(d)
    }

    /// Fields of a few points for scoring: raw, smoothed (N,3) and hidden (N,).
    fn gather_points<'py>(&self, py: Python<'py>, ids: Vec<u32>) -> R<Bound<'py, PyDict>> {
        let s = &self.stream;
        let n = ids.len();
        let hi = ids.iter().copied().max().map(|m| m as usize + 1).unwrap_or(1);
        let raw = s.clone_dtoh(&self.praw.slice(0..hi * 3)).map_err(err)?;
        let sm = s.clone_dtoh(&self.spos.slice(0..hi * 3)).map_err(err)?;
        let phid = s.clone_dtoh(&self.phid.slice(0..hi)).map_err(err)?;
        let pmiss = s.clone_dtoh(&self.pmiss.slice(0..hi)).map_err(err)?;
        let nview = s.clone_dtoh(&self.nview.slice(0..hi)).map_err(err)?;
        s.synchronize().map_err(err)?;
        let mut r = Vec::with_capacity(n * 3);
        let mut m = Vec::with_capacity(n * 3);
        let mut h = Vec::with_capacity(n);
        for &i in &ids {
            let i = i as usize;
            r.extend_from_slice(&raw[i * 3..i * 3 + 3]);
            m.extend_from_slice(&sm[i * 3..i * 3 + 3]);
            h.push(u8::from(phid[i] > 0 || (pmiss[i] >= 3 && pmiss[i] > nview[i])));
        }
        let d = PyDict::new(py);
        d.set_item("raw", r.into_pyarray(py).reshape([n, 3]).map_err(err)?)?;
        d.set_item("smooth", m.into_pyarray(py).reshape([n, 3]).map_err(err)?)?;
        d.set_item("hidden", h.into_pyarray(py))?;
        Ok(d)
    }


    // ------------------------------------------------------------------ surface (TSDF + mesher)
    /// Rectangular openings (windows, doors) found in walls, one row each: axis (0 = wall normal to x, 1 = to y),
    /// the wall's two face coordinates, then u0, u1 (along the other horizontal axis) and v0, v1 (height).
    /// Mesh vertices near an opening's edges are snapped onto the rectangle.
    fn set_openings(&mut self, rows: PyReadonlyArray2<f32>) -> R<()> {
        let n = rows.shape()[0].min(OPEN_CAP);
        let mut flat = vec![0.0f32; OPEN_CAP * 8];
        for (i, r) in rows.as_array().outer_iter().take(n).enumerate() {
            for (j, v) in r.iter().take(8).enumerate() {
                flat[i * 8 + j] = *v;
            }
        }
        let changed = n as i32 != self.nopen || {
            let old = self.stream.clone_dtoh(&self.m_opens).map_err(err)?;
            self.stream.synchronize().map_err(err)?;
            old[..n * 8].iter().zip(flat[..n * 8].iter()).any(|(a, b)| (a - b).abs() > 1e-4)
        };
        if changed {
            self.stream.memcpy_htod(&flat, &mut self.m_opens).map_err(err)?;
            self.nopen = n as i32;
            self.mark_all_dirty()?;
        }
        Ok(())
    }

    /// Absolute landmark planes for the aligner, one row each: axis, position, then the extent along the next two axes
    /// (axis+1, axis+2 modulo 3) as lo, hi, lo, hi, and a weight.
    fn set_landmarks(&mut self, rows: PyReadonlyArray2<f32>) -> R<()> {
        let n = rows.shape()[0].min(8);
        let mut flat = vec![0.0f32; 64];
        for (i, r) in rows.as_array().outer_iter().take(n).enumerate() {
            for (j, v) in r.iter().take(8).enumerate() {
                flat[i * 8 + j] = *v;
            }
        }
        self.stream.memcpy_htod(&flat, &mut self.lm).map_err(err)?;
        self.nlm = n as i32;
        Ok(())
    }

    /// A gap that was inspected and is really wall: fill it in the map (voxel layer `layer` across the voxel ranges
    /// a0..a1 x b0..b1 of the two other axes) and in the signed-distance volume (wall face at `face` metres, over
    /// u0..u1 x v0..v1; `sign` is the free side). Axis 0/1/2 = x/y/z; u and v run along axis+1 and axis+2.
    fn fill_patch(&mut self, axis: i32, layer: i32, face: f32, a0: i32, a1: i32, b0: i32, b1: i32,
                  u0: f32, u1: f32, v0: f32, v1: f32, sign: f32, tick: i32) -> R<()> {
        let s = self.stream.clone();
        let (na, nb) = ((a1 - a0).max(0), (b1 - b0).max(0));
        if na * nb > 0 {
            let dims = self.dims;
            unsafe {
                s.launch_builder(&self.k["k_fill_map"])
                    .arg(&dims).arg(&axis).arg(&layer).arg(&a0).arg(&a1).arg(&b0).arg(&b1).arg(&tick)
                    .arg(&mut self.lo).arg(&mut self.mat).arg(&mut self.quality).arg(&mut self.stamp)
                    .launch(cfg((na * nb) as usize)).map_err(err)?;
            }
        }
        let n = (((u1 - u0) / 0.2).ceil().max(0.0) as usize) * (((v1 - v0) / 0.2).ceil().max(0.0) as usize) * 5;
        if n > 0 {
            let td = self.td;
            unsafe {
                s.launch_builder(&self.k["k_fill_tsdf"])
                    .arg(&td).arg(&axis).arg(&face).arg(&u0).arg(&u1).arg(&v0).arg(&v1).arg(&sign)
                    .arg(&mut self.ts_s).arg(&mut self.ts_w).arg(&mut self.ts_sc).arg(&mut self.ts_wc).arg(&mut self.ts_dirty).arg(&0i32)
                    .launch(cfg(n)).map_err(err)?;
            }
        }
        Ok(())
    }

    /// A measured opening: clear the wall layer over the voxel ranges a0..a1 x b0..b1 and two layers outside and
    /// two inside (`step` = the inward direction, +-1) in the map, and write free space across the rectangle into
    /// the signed-distance volume so the mesh opens there too.
    fn carve_patch(&mut self, axis: i32, layer: i32, step: i32, face: f32, a0: i32, a1: i32, b0: i32, b1: i32,
                   u0: f32, u1: f32, v0: f32, v1: f32, tick: i32) -> R<()> {
        let s = self.stream.clone();
        let (na, nb) = ((a1 - a0).max(0), (b1 - b0).max(0));
        let nl = 5i32;
        if na * nb > 0 {
            let dims = self.dims;
            unsafe {
                s.launch_builder(&self.k["k_carve_map"])
                    .arg(&dims).arg(&axis).arg(&layer).arg(&step).arg(&nl).arg(&a0).arg(&a1).arg(&b0).arg(&b1).arg(&tick)
                    .arg(&mut self.lo).arg(&mut self.stamp)
                    .launch(cfg((na * nb * nl) as usize)).map_err(err)?;
            }
        }
        let n = (((u1 - u0) / 0.2).ceil().max(0.0) as usize) * (((v1 - v0) / 0.2).ceil().max(0.0) as usize) * 5;
        if n > 0 {
            let td = self.td;
            let sign = 1.0f32;
            unsafe {
                s.launch_builder(&self.k["k_fill_tsdf"])
                    .arg(&td).arg(&axis).arg(&face).arg(&u0).arg(&u1).arg(&v0).arg(&v1).arg(&sign)
                    .arg(&mut self.ts_s).arg(&mut self.ts_w).arg(&mut self.ts_sc).arg(&mut self.ts_wc).arg(&mut self.ts_dirty).arg(&1i32)
                    .launch(cfg(n)).map_err(err)?;
            }
        }
        Ok(())
    }

    /// The wall planes detected so far, per axis (x, y, z), in metres.
    fn wall_planes(&self) -> Vec<Vec<f32>> {
        self.planes.clone()
    }

    /// Mesh up to `max_chunks` dirty chunks (those not meshed within `min_interval` seconds, least
    /// recently meshed first). Returns how many were meshed.
    #[pyo3(signature = (max_chunks, now, min_interval, budget_ms=30))]
    fn mesh_step(&mut self, max_chunks: usize, now: f64, min_interval: f64, budget_ms: u128) -> R<usize> {
        let s = self.stream.clone();
        let dirty = s.clone_dtoh(&self.ts_dirty).map_err(err)?;
        s.synchronize().map_err(err)?;
        // Chunks that have data but no mesh yet come first (those are holes in the viewer), then the longest-waiting.
        // A chunk that already has a mesh is refreshed at most every 4x `min_interval`: frames re-dirty the chunks in
        // view constantly, and re-meshing those would starve the rest.
        let mut cand: Vec<(u8, f64, u32)> = dirty.iter().enumerate()
            .filter(|(_, &d)| d != 0)
            .map(|(i, _)| {
                let id = i as u32;
                let t = self.meshed_at.get(&id).copied().unwrap_or(-1e18);
                (if self.chunks.contains_key(&id) { 1u8 } else { 0u8 }, t, id)
            })
            .filter(|(_, t, _)| now - *t >= min_interval)
            .collect();
        cand.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal)));
        // a real-time budget instead of a fixed count: the sim runs faster than real time, so a fixed count starved
        let t0 = std::time::Instant::now();
        let mut n = 0;
        for &(_, _, cid) in cand.iter() {
            if n >= max_chunks || (n > 0 && t0.elapsed().as_millis() > budget_ms) { break; }
            self.mesh_chunk_(cid, now)?;
            n += 1;
        }
        if now - self.planes_t > 4.0 && !self.chunks.is_empty() {
            self.planes_t = now;
            self.refresh_planes()?;
        }
        Ok(n)
    }

    /// Diagnostics: per chunk with any signed-distance data: (id, voxels with enough weight, voxels near the surface,
    /// dirty flag, faces in its current mesh or -1 if never meshed).
    fn tsdf_stats(&self) -> R<Vec<(u32, i32, i32, u8, i32, i32, i32)>> {
        let s = self.stream.clone();
        let w = s.clone_dtoh(&self.ts_w).map_err(err)?;
        let sv = s.clone_dtoh(&self.ts_s).map_err(err)?;
        let dirty = s.clone_dtoh(&self.ts_dirty).map_err(err)?;
        s.synchronize().map_err(err)?;
        let td = self.td;
        let mut obs: HashMap<u32, (i32, i32, i32, i32)> = HashMap::new();
        for x in 0..td.nx { for y in 0..td.ny {
            let base = ((x as i64 * td.ny as i64 + y as i64) * td.nz as i64) as usize;
            let cb = (((x / 32) * td.ncy + (y / 32)) * td.ncz) as u32;
            for z in 0..td.nz {
                let ww = w[base + z as usize];
                if ww >= 0.08 {
                    let e = obs.entry(cb + (z / 32) as u32).or_insert((0, 0, 0, 0));
                    e.0 += 1;
                    let dv = sv[base + z as usize] / ww;
                    if dv.abs() < 0.5 { e.1 += 1; }
                    if dv < -0.05 { e.2 += 1; }
                    if dv > 0.05 { e.3 += 1; }
                }
            }
        } }
        let mut out: Vec<_> = obs.into_iter().map(|(c, (o, n, ng, ps))| {
            let f = self.chunks.get(&c).map(|m| (m.f.len() / 3) as i32).unwrap_or(if self.meshed_at.contains_key(&c) { -2 } else { -1 });
            (c, o, n, dirty[c as usize], f, ng, ps)
        }).collect();
        out.sort();
        Ok(out)
    }

    /// Diagnostics: raw signed distance (NaN where unobserved) of one chunk's 33^3 grid points, x-major.
    fn tsdf_chunk(&self, cid: u32) -> R<Vec<f32>> {
        let s = self.stream.clone();
        let td = self.td;
        let (cz, cy, cx) = (cid as i32 % td.ncz, (cid as i32 / td.ncz) % td.ncy, cid as i32 / (td.ncz * td.ncy));
        let w = s.clone_dtoh(&self.ts_w).map_err(err)?;
        let sv = s.clone_dtoh(&self.ts_s).map_err(err)?;
        s.synchronize().map_err(err)?;
        let mut out = Vec::with_capacity(CHP * CHP * CHP);
        for gx in 0..CHP as i32 { for gy in 0..CHP as i32 { for gz in 0..CHP as i32 {
            let (x, y, z) = (cx * 32 + gx, cy * 32 + gy, cz * 32 + gz);
            if x >= td.nx || y >= td.ny || z >= td.nz { out.push(f32::NAN); continue; }
            let q = ((x as i64 * td.ny as i64 + y as i64) * td.nz as i64 + z as i64) as usize;
            out.push(if w[q] >= 0.08 { sv[q] / w[q] } else { f32::NAN });
        } } }
        Ok(out)
    }

    /// (ids, versions, times, face counts, byte sizes) of every meshed chunk.
    fn mesh_info<'py>(&self, py: Python<'py>) -> R<Bound<'py, PyDict>> {
        let mut ids = vec![]; let mut ver = vec![]; let mut t = vec![]; let mut nf = vec![]; let mut nb = vec![];
        for (cid, c) in &self.chunks {
            ids.push(*cid); ver.push(c.ver); t.push(c.t); nf.push((c.f.len() / 3) as i32);
            nb.push((c.v.len() * 2 + c.n.len() + c.c.len() + c.f.len() * 3) as i64);
        }
        let d = PyDict::new(py);
        d.set_item("ids", ids.into_pyarray(py))?;
        d.set_item("ver", ver.into_pyarray(py))?;
        d.set_item("t", t.into_pyarray(py))?;
        d.set_item("nfaces", nf.into_pyarray(py))?;
        d.set_item("nbytes", nb.into_pyarray(py))?;
        Ok(d)
    }

    /// One chunk's mesh: positions (u16, 1 cm units), normals (i8), colours (u8), faces (u32), flat.
    fn mesh_chunk<'py>(&self, py: Python<'py>, cid: u32) -> R<Bound<'py, PyDict>> {
        let c = self.chunks.get(&cid).ok_or_else(|| err("no such chunk"))?;
        let d = PyDict::new(py);
        d.set_item("ver", c.ver)?;
        d.set_item("v", c.v.clone().into_pyarray(py))?;
        d.set_item("n", c.n.clone().into_pyarray(py))?;
        d.set_item("c", c.c.clone().into_pyarray(py))?;
        d.set_item("f", c.f.clone().into_pyarray(py))?;
        Ok(d)
    }

    fn mesh_totals(&self) -> (usize, usize) {
        (self.chunks.values().map(|c| c.f.len() / 3).sum(), self.chunks.len())
    }

    /// Loss (dB) per material for a run of solid cells crossed by a link (index = material id).
    fn set_link_params(&mut self, per_mat: Vec<f32>) -> R<()> {
        let mut v = per_mat;
        v.resize(16, 0.0);
        self.stream.memcpy_htod(&v, &mut self.per_mat).map_err(err)
    }

    /// The building's interior (unexplored interior counts against predicted links).
    fn set_interior(&mut self, a: PyReadonlyArray3<u8>) -> R<()> {
        let v: Vec<u8> = a.as_array().iter().copied().collect();
        self.stream.memcpy_htod(&v, &mut self.interior).map_err(err)
    }

    /// SNR (dB) for P links a[i] -> b[i]; mode 0 = the true building, 1 = the master's map.
    fn link_snr<'py>(&self, py: Python<'py>, a: PyReadonlyArray2<f32>, b: PyReadonlyArray2<f32>, mode: i32) -> R<Bound<'py, numpy::PyArray1<f32>>> {
        let p = a.shape()[0];
        let s = &self.stream;
        if p == 0 {
            return Ok(Vec::<f32>::new().into_pyarray(py));
        }
        let da = s.clone_htod(&vec2(&a)).map_err(err)?;
        let db = s.clone_htod(&vec2(&b)).map_err(err)?;
        let mut out = z!(s, f32, p);
        let pi = p as i32;
        let dims = self.dims;
        unsafe {
            s.launch_builder(&self.k["k_snr"])
                .arg(&mode).arg(&self.world).arg(&self.wdim[0]).arg(&self.wdim[1]).arg(&self.wdim[2]).arg(&self.pad)
                .arg(&dims).arg(&self.lo).arg(&self.mat).arg(&self.interior)
                .arg(&da).arg(&db).arg(&pi).arg(&self.per_mat).arg(&self.nmat).arg(&mut out)
                .launch(cfg(p)).map_err(err)?;
        }
        let v = s.clone_dtoh(&out).map_err(err)?;
        s.synchronize().map_err(err)?;
        Ok(v.into_pyarray(py))
    }

    fn sync(&self) -> R<()> {
        self.stream.synchronize().map_err(err)
    }
}


impl Core {
    fn upload_planes(&mut self) -> R<()> {
        let mut flat = vec![0.0f32; 3 * PLANE_CAP];
        let mut np = [0i32; 3];
        for a in 0..3 {
            for (k, v) in self.planes[a].iter().take(PLANE_CAP).enumerate() {
                flat[a * PLANE_CAP + k] = *v;
            }
            np[a] = self.planes[a].len().min(PLANE_CAP) as i32;
        }
        self.stream.memcpy_htod(&flat, &mut self.m_planes).map_err(err)?;
        self.stream.memcpy_htod(&np.to_vec(), &mut self.m_nplanes).map_err(err)
    }

    fn mark_all_dirty(&mut self) -> R<()> {
        let ids: Vec<u32> = self.chunks.keys().copied().collect();
        for cid in ids {
            let one = [1u8];
            self.stream.memcpy_htod(&one, &mut self.ts_dirty.slice_mut(cid as usize..cid as usize + 1)).map_err(err)?;
            self.meshed_at.remove(&cid);
        }
        Ok(())
    }

    /// Detect flat walls and slabs from the mesh itself: vertices whose normal points along an axis are binned
    /// by their coordinate along it (5 cm bins); sharp peaks are planes. No prior about the building is used.
    fn refresh_planes(&mut self) -> R<()> {
        let mut new: Vec<Vec<f32>> = vec![vec![], vec![], vec![]];
        for a in 0..3 {
            let h = &self.hist[a];
            let n = h.len();
            let win = |i: usize| -> f32 { (i.saturating_sub(3)..(i + 4).min(n)).map(|j| h[j]).sum() };
            let sums: Vec<f32> = (0..n).map(win).collect();
            let mut cand: Vec<(f32, usize)> = (0..n)
                .filter(|&i| sums[i] >= 40.0 && (i.saturating_sub(10)..(i + 11).min(n)).all(|j| sums[j] <= sums[i] + 1e-3))
                .map(|i| (sums[i], i))
                .collect();
            cand.sort_by(|x, y| y.0.partial_cmp(&x.0).unwrap_or(std::cmp::Ordering::Equal));
            let mut picked: Vec<usize> = vec![];
            for (_, i) in cand {
                if picked.iter().all(|&p| (p as i64 - i as i64).abs() > 10) && picked.len() < PLANE_CAP {
                    picked.push(i);
                }
            }
            picked.sort();
            for i in picked {
                let (mut sw, mut sx) = (0.0f64, 0.0f64);
                for j in i.saturating_sub(3)..(i + 4).min(n) {
                    sw += h[j] as f64;
                    sx += h[j] as f64 * (j as f64 * 5.0 + 2.5);
                }
                new[a].push((sx / sw.max(1e-9) / 100.0) as f32);
            }
        }
        let moved = (0..3).any(|a| new[a].len() != self.planes[a].len()
            || new[a].iter().zip(self.planes[a].iter()).any(|(x, y)| (x - y).abs() > 0.08));
        if moved {
            self.planes = new;
            self.upload_planes()?;
            self.mark_all_dirty()?;
        }
        Ok(())
    }

    fn mesh_chunk_(&mut self, cid: u32, now: f64) -> R<()> {
        let s = self.stream.clone();
        let td = self.td;
        let cz = cid as i32 % td.ncz;
        let cy = (cid as i32 / td.ncz) % td.ncy;
        let cx = cid as i32 / (td.ncz * td.ncy);
        let prev_ver = self.chunks.get(&cid).map(|c| c.ver).unwrap_or(0);
        s.memset_zeros(&mut self.ts_dirty.slice_mut(cid as usize..cid as usize + 1)).map_err(err)?;
        self.meshed_at.insert(cid, now);
        s.memset_zeros(&mut self.m_used).map_err(err)?;
        s.memset_zeros(&mut self.m_ntri).map_err(err)?;
        let npts = (CHP * CHP * CHP) as usize;
        let klen = 7i32;
        let max_tri = MAX_TRI as i32;
        let og: i32 = if self.dc { -1 } else { 0 };
        unsafe {
            s.launch_builder(&self.k["k_chunk_field"])
                .arg(&td).arg(&cx).arg(&cy).arg(&cz).arg(&og).arg(&self.ts_s).arg(&self.ts_w).arg(&self.m_kern).arg(&klen).arg(&self.m_ksum3)
                .arg(&mut self.m_field).arg(&mut self.m_obs)
                .launch(cfg(npts)).map_err(err)?;
            if self.dc {
                s.launch_builder(&self.k["k_dc_cells"])
                    .arg(&self.m_field).arg(&self.m_obs).arg(&mut self.dc_act).arg(&mut self.dc_pos).arg(&mut self.dc_nrm)
                    .launch(cfg(npts)).map_err(err)?;
                s.launch_builder(&self.k["k_dc_quads"])
                    .arg(&self.m_field).arg(&self.m_obs).arg(&self.dc_act).arg(&self.dc_pos).arg(&self.dc_nrm)
                    .arg(&mut self.m_used).arg(&mut self.m_tri).arg(&mut self.m_ntri).arg(&max_tri)
                    .launch(cfg(32 * 32 * 32)).map_err(err)?;
            } else {
                s.launch_builder(&self.k["k_mc_count"])
                    .arg(&self.m_field).arg(&self.m_obs).arg(&self.m_table).arg(&mut self.m_used).arg(&mut self.m_tri)
                    .arg(&mut self.m_ntri).arg(&max_tri)
                    .launch(cfg(32 * 32 * 32)).map_err(err)?;
            }
        }
        let ntri = s.clone_dtoh(&self.m_ntri).map_err(err)?[0].max(0).min(max_tri) as usize;
        s.synchronize().map_err(err)?;
        if ntri == 0 {
            if self.chunks.contains_key(&cid) {
                self.chunks.insert(cid, ChunkMesh { ver: prev_ver + 1, t: now, v: vec![], n: vec![], c: vec![], f: vec![] });
            }
            return Ok(());
        }
        let nsl = NSLOTS as i32;
        let nb = ((NSLOTS + 1023) / 1024) as i32;
        unsafe {
            s.launch_builder(&self.k["k_scan_block"]).arg(&self.m_used).arg(&nsl).arg(&mut self.m_vid).arg(&mut self.m_bsum)
                .launch(LaunchConfig { grid_dim: (nb as u32, 1, 1), block_dim: (1024, 1, 1), shared_mem_bytes: 0 }).map_err(err)?;
            s.launch_builder(&self.k["k_scan_blocks"]).arg(&mut self.m_bsum).arg(&nb).arg(&mut self.m_total)
                .launch(LaunchConfig { grid_dim: (1, 1, 1), block_dim: (32, 1, 1), shared_mem_bytes: 0 }).map_err(err)?;
            s.launch_builder(&self.k["k_scan_add"]).arg(&nsl).arg(&mut self.m_vid).arg(&self.m_bsum).launch(cfg(NSLOTS)).map_err(err)?;
        }
        let nv = s.clone_dtoh(&self.m_total).map_err(err)?[0].max(0) as usize;
        s.synchronize().map_err(err)?;
        let (tol, align) = (0.25f32, 0.8f32);
        let nt = ntri as i32;
        unsafe {
            if self.dc {
                let ncell = (CHP * CHP * CHP) as i32;
                s.launch_builder(&self.k["k_dc_verts"])
                    .arg(&td).arg(&cx).arg(&cy).arg(&cz).arg(&ncell).arg(&self.m_used).arg(&self.m_vid).arg(&self.dc_pos).arg(&self.dc_nrm)
                    .arg(&self.ts_sc).arg(&self.ts_wc).arg(&self.m_planes).arg(&self.m_nplanes).arg(&tol).arg(&align)
                    .arg(&self.m_opens).arg(&self.nopen)
                    .arg(&mut self.m_pos).arg(&mut self.m_nrm).arg(&mut self.m_col)
                    .launch(cfg(CHP * CHP * CHP)).map_err(err)?;
            } else {
                s.launch_builder(&self.k["k_mc_verts"])
                    .arg(&td).arg(&cx).arg(&cy).arg(&cz).arg(&nsl).arg(&self.m_used).arg(&self.m_vid).arg(&self.m_field)
                    .arg(&self.ts_sc).arg(&self.ts_wc).arg(&self.m_planes).arg(&self.m_nplanes).arg(&tol).arg(&align)
                    .arg(&self.m_opens).arg(&self.nopen)
                    .arg(&mut self.m_pos).arg(&mut self.m_nrm).arg(&mut self.m_col)
                    .launch(cfg(NSLOTS)).map_err(err)?;
            }
            s.launch_builder(&self.k["k_mc_faces"]).arg(&nt).arg(&self.m_tri).arg(&self.m_vid).arg(&mut self.m_faces)
                .launch(cfg(ntri)).map_err(err)?;
        }
        let v = s.clone_dtoh(&self.m_pos.slice(0..nv * 3)).map_err(err)?;
        let n = s.clone_dtoh(&self.m_nrm.slice(0..nv * 3)).map_err(err)?;
        let c = s.clone_dtoh(&self.m_col.slice(0..nv * 3)).map_err(err)?;
        let f = s.clone_dtoh(&self.m_faces.slice(0..ntri * 3)).map_err(err)?;
        s.synchronize().map_err(err)?;
        // this chunk's vertices vote for wall planes (replacing its previous vote)
        if let Some(old) = self.chunk_hist.remove(&cid) {
            for (ax, bin) in old {
                let h = &mut self.hist[ax as usize];
                if (bin as usize) < h.len() { h[bin as usize] -= 1.0; }
            }
        }
        let mut votes: Vec<(u8, u16)> = vec![];
        for i in 0..nv {
            for a in 0..3usize {
                if (n[i * 3 + a] as i32).abs() > 102 {   // normal within ~37 degrees of the axis
                    let bin = (v[i * 3 + a] / 5) as usize;
                    if bin < self.hist[a].len() {
                        self.hist[a][bin] += 1.0;
                        votes.push((a as u8, bin as u16));
                    }
                }
            }
        }
        self.chunk_hist.insert(cid, votes);
        self.chunks.insert(cid, ChunkMesh { ver: prev_ver + 1, t: now, v, n, c, f });
        Ok(())
    }
}

#[pymodule]
fn gpucore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Core>()?;
    m.add_class::<nav::Nav>()?;
    m.add_function(wrap_pyfunction!(nav::dilate, m)?)?;
    Ok(())
}
