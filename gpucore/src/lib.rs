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

const MAX_BATCH: usize = 32; // frames processed per call
const PCAP: usize = 6_000_000; // point store capacity (the last slot is reserved)
const SURV_CAP: usize = 64;
const BLOCK: u32 = 256;

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
            include_str!("align.cu"), include_str!("smooth.cu"), include_str!("stream.cu"),
        ]
        .join("\n");
        let opts = CompileOptions { fmad: Some(false), arch: Some("compute_80"), ..Default::default() };
        let ptx = compile_ptx_with_opts(src, opts).map_err(err)?;
        let module = ctx.load_module(ptx).map_err(err)?;
        let names: [&'static str; 26] = [
            "render", "degrade_a", "degrade_b", "depthnet", "k_carve", "k_hit", "k_apply", "k_pts_claim", "k_pts_acc",
            "k_pts_fin", "k_align", "k_apply_align", "k_scale_est", "k_clear_ahead", "k_sm_collect", "k_sm_a", "k_sm_b",
            "k_sm_c", "k_sm_d", "k_redirty", "k_vox_collect", "k_vox_pack", "k_pt_cand", "k_pt_decide", "k_pt_pack",
            "k_seen_collect",
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
        unsafe {
            // 1. depth network on the true depth
            s.launch_builder(&self.k["depthnet"])
                .arg(&self.fdepth).arg(&d_slots).arg(&d_thumb).arg(&bi).arg(&self.w).arg(&self.h)
                .arg(&scale_sigma).arg(&region_sigma).arg(&depth_max).arg(&seed).arg(&mut self.est)
                .launch(cfg(b * npix)).map_err(err)?;
            // 2. align against the smoothed map (one block per frame)
            let sub = 3i32;
            s.launch_builder(&self.k["k_align"])
                .arg(&dims).arg(&sub).arg(&d_pos).arg(&d_rot).arg(&self.est).arg(&self.rays).arg(&d_t).arg(&d_dr)
                .arg(&self.pidx).arg(&self.spos).arg(&self.pnorm).arg(&self.pt0).arg(&self.pdrone).arg(&self.phid)
                .arg(&self.pmiss).arg(&self.nview).arg(&self.npts).arg(&mut self.ares)
                .launch(LaunchConfig { grid_dim: (b as u32, 1, 1), block_dim: (BLOCK, 1, 1), shared_mem_bytes: 0 }).map_err(err)?;
            // 3. apply accepted corrections to pose / rotation / depth scale
            s.launch_builder(&self.k["k_apply_align"])
                .arg(&bi).arg(&self.ares).arg(&d_pos).arg(&d_rot).arg(&mut self.pos_c).arg(&mut self.rot_c)
                .launch(cfg(b)).map_err(err)?;
            s.launch_builder(&self.k["k_scale_est"])
                .arg(&dims).arg(&bi).arg(&self.ares).arg(&mut self.est).launch(cfg(b * npix)).map_err(err)?;
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
                .arg(&mut self.pver).arg(&mut self.pgh).arg(&fid0).arg(&batch_id)
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

    fn sync(&self) -> R<()> {
        self.stream.synchronize().map_err(err)
    }
}

#[pymodule]
fn gpucore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Core>()?;
    Ok(())
}
