# gpucore: the simulator's GPU core in Rust

A PyO3 extension (`import gpucore`) that owns all GPU state of the simulator and runs it as CUDA
kernels compiled at startup with NVRTC (no `nvcc` needed), via the `cudarc` crate:

| Part | File | What it does |
|---|---|---|
| Camera | `src/camera.cu` | batched voxel ray march, toy-camera degradation, mono-depth stand-in |
| Map | `src/map.cu` | carving, hits, scan passes, material classification, colored point store (all atomics) |
| Alignment | `src/align.cu` | frame-to-map Gauss-Newton with priors, observable-subspace projection |
| Smoothing | `src/smooth.cu` | PCA plane fit per point, outlier flags |
| Viewer stream | `src/stream.cu` | changed voxels / points / scan times compacted on the device |
| Radio | `src/comms.cu` | SNR of many links in one kernel (true world or the master's map) |
| Planner | `src/nav.rs` | native A* (same moves/costs/pruning as the Python planner) and grid dilations (CPU) |

Build (needs Rust and a CUDA 13 driver; run inside the simulator's venv):

    pip install maturin
    cd gpucore && maturin develop --release

The Python side picks it up automatically (`disaster_sim/rustcore.py`). `DISASTER_CORE=torch` forces the
PyTorch implementation, which stays as the reference and as the fallback for machines without the crate.
Parity tests live in `sim/tests/test_rust_*.py` (run on a machine with the GPU, `python -m tests.test_rust_map`).
