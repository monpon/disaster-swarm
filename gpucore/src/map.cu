// Map fusion on the device: occupancy carving, surface hits, scan passes, material classification,
// and the colored point store. Everything is dense/atomic: no sorting, no host round trips.
//
// Per-voxel arrays are length n (x slowest, then y, z). Frames come from the frame pool (uint8 rgb)
// and the depth-network estimate buffer (float, B x N), with corrected poses.

#define HIT_INC 6
#define MISS_DEC 2
#define LO_MIN_V (-30)
#define LO_MAX_V 40
#define OCC_T_V 4
#define FREE_T_V (-3)
#define GHOST_MARGIN 1.0f
#define PASS_GAP 15.0f
#define PASS_RANGE 8.0f
#define POINT_CELL 0.25f
#define POINT_MAX_RANGE 10.0f

// ip: 0 sx 1 sy 2 sz 3 n 4 pcx 5 pcy 6 pcz 7 pcap 8 W 9 H 10 N 11 ns
struct MapDims { int sx, sy, sz, n, pcx, pcy, pcz, pcap, W, H, N, ns; };

__device__ __forceinline__ void world_dir(const float* R, const float* rays, int n, float& dx, float& dy, float& dz) {
    float bx = rays[n*3], by = rays[n*3+1], bz = rays[n*3+2];
    dx = R[0]*bx + R[1]*by + R[2]*bz;
    dy = R[3]*bx + R[4]*by + R[5]*bz;
    dz = R[6]*bx + R[7]*by + R[8]*bz;
}
__device__ __forceinline__ int vox_of(const MapDims& d, float x, float y, float z) {
    int ix = (int)floorf(x), iy = (int)floorf(y), iz = (int)floorf(z);
    if (ix < 0 || iy < 0 || iz < 0 || ix >= d.sx || iy >= d.sy || iz >= d.sz) return -1;
    return (ix * d.sy + iy) * d.sz + iz;
}
__device__ __forceinline__ long long cell_of(const MapDims& d, float x, float y, float z) {
    int cx = (int)floorf(x / POINT_CELL), cy = (int)floorf(y / POINT_CELL), cz = (int)floorf(z / POINT_CELL);
    if (cx < 0 || cy < 0 || cz < 0 || cx >= d.pcx || cy >= d.pcy || cz >= d.pcz) return -1;
    return ((long long)cx * d.pcy + cy) * d.pcz + cz;
}
__device__ __forceinline__ void atomic_max_f(float* addr, float v) {   // for floats that stay >= -1 (int ordering holds for same-sign; mixed -1 / positive also ordered)
    atomicMax((int*)addr, __float_as_int(v));
}

// ---------------------------------------------------------------- carving + ghost removal
extern "C" __global__ void k_carve(
    MapDims d, int B, const float* __restrict__ poss, const float* __restrict__ rots, const float* __restrict__ est,
    const float* __restrict__ rays, const float* __restrict__ steps, float carve_max,
    int* cstamp, int* delta, const int* __restrict__ pidx, int* pmiss, int* pver, int* pgh,
    unsigned int frame_id0, int batch_id)
{
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)B * d.N) return;
    int b = (int)(idx / d.N), n = (int)(idx % d.N);
    float dx, dy, dz; world_dir(rots + b*9, rays, n, dx, dy, dz);
    float px = poss[b*3], py = poss[b*3+1], pz = poss[b*3+2];
    float depth = est[idx];
    bool hit = depth > 0.0f;
    float reach = hit ? depth - 0.6f : carve_max;
    int fid = (int)(frame_id0 + b);
    for (int k = 0; k < d.ns; k++) {
        float s = steps[k];
        if (s >= reach) break;
        float x = px + dx*s, y = py + dy*s, z = pz + dz*s;
        int v = vox_of(d, x, y, z);
        if (v >= 0 && atomicExch(&cstamp[v], fid) != fid) atomicAdd(&delta[v], -MISS_DEC);
        if (hit && s < depth - GHOST_MARGIN) {   // a ray passing well in front of its hit contradicts any point here
            long long key = cell_of(d, x, y, z);
            if (key >= 0) {
                int pid = pidx[key];
                if (pid >= 0 && atomicExch(&pgh[pid], batch_id) != batch_id) { atomicAdd(&pmiss[pid], 1); atomicAdd(&pver[pid], 1); }
            }
        }
    }
}

// ---------------------------------------------------------------- hits
// surv: survivor-colored pixels, appended (b, x, y, z, dist) up to surv_cap
extern "C" __global__ void k_hit(
    MapDims d, int B, const float* __restrict__ poss, const float* __restrict__ rots, const float* __restrict__ est,
    const unsigned int* __restrict__ slots, const unsigned char* __restrict__ frgb, const float* __restrict__ tcap,
    const float* __restrict__ rays, float q_near, float q_far, float q_thresh,
    int* hstamp, int* delta, int* hitfr, float* csum, int* cnt, float* qb, float* seenb, int* sidebits, float* tmaxb,
    unsigned int frame_id0, float* surv, int* surv_n, int surv_cap)
{
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)B * d.N) return;
    int b = (int)(idx / d.N), n = (int)(idx % d.N);
    float depth = est[idx];
    if (!(depth > 0.0f)) return;
    float dx, dy, dz; world_dir(rots + b*9, rays, n, dx, dy, dz);
    float hx = poss[b*3] + dx*(depth + 0.15f), hy = poss[b*3+1] + dy*(depth + 0.15f), hz = poss[b*3+2] + dz*(depth + 0.15f);
    int v = vox_of(d, hx, hy, hz);
    if (v < 0) return;
    int fid = (int)(frame_id0 + b);
    if (atomicExch(&hstamp[v], fid) != fid) { atomicAdd(&delta[v], HIT_INC); atomicAdd(&hitfr[v], 1); }
    const unsigned char* px = frgb + ((long long)slots[b] * d.N + n) * 3;
    float r = px[0], g = px[1], bl = px[2];
    atomicAdd(&csum[v*3], r); atomicAdd(&csum[v*3+1], g); atomicAdd(&csum[v*3+2], bl);
    atomicAdd(&cnt[v], 1);
    float q = fminf(fmaxf(1.0f - (depth - q_near) / (q_far - q_near), 0.0f), 1.0f);
    atomic_max_f(&qb[v], q);
    float t = tcap[b];
    if (q >= q_thresh) atomic_max_f(&seenb[v], t);
    if (depth <= PASS_RANGE) {   // which side of the surface the camera sees (axis of the look direction)
        float lx = -dx, ly = -dy, lz = -dz;
        float ax = fabsf(lx), ay = fabsf(ly), az = fabsf(lz);
        int axis = 0; float best = ax; if (ay > best) { axis = 1; best = ay; } if (az > best) { axis = 2; }
        float comp = axis == 0 ? lx : (axis == 1 ? ly : lz);
        int side = axis * 2 + (comp < 0.0f ? 1 : 0);
        atomicOr(&sidebits[v], 1 << side);
        atomic_max_f(&tmaxb[v], t);
    }
    if (r > 150.0f && g < 0.33f * r && bl < 0.45f * r) {   // a person's heat signature, by colour ratio
        int k = atomicAdd(surv_n, 1);
        if (k < surv_cap) { float* o = surv + k * 6; o[0] = (float)b; o[1] = hx; o[2] = hy; o[3] = hz; o[4] = depth; o[5] = 0.0f; }
    }
}

// Apply the batch to every voxel it touched, reclassify surfaces, stamp changes for the viewer, clear scratch.
extern "C" __global__ void k_apply(
    int n, int tick, const float* __restrict__ palette, int npal,
    int* lo, int* delta, int* hitfr, float* csum, int* cnt, float* qb, float* seenb, int* sidebits, float* tmaxb,
    unsigned char* mat, float* quality, float* seen, int* stamp, int* vdir, int* npass, float* lastpass)
{
    int v = blockIdx.x * blockDim.x + threadIdx.x;
    if (v >= n) return;
    int dl = delta[v], hc = hitfr[v], sb = sidebits[v];
    if (dl == 0 && hc == 0 && sb == 0) return;
    int old_lo = lo[v];
    int new_lo = min(max(old_lo + dl, LO_MIN_V), LO_MAX_V);
    lo[v] = new_lo;
    bool was_occ = old_lo >= OCC_T_V, now_occ = new_lo >= OCC_T_V;
    bool was_unknown = old_lo > FREE_T_V && !was_occ, now_free = new_lo <= FREE_T_V;
    bool changed = (was_occ && !now_occ) || (was_unknown && now_free);
    if (hc > 0) {
        float oq = quality[v];
        float nq = fmaxf(oq, qb[v]);
        quality[v] = nq;
        seen[v] = fmaxf(seen[v], seenb[v]);
        // classify the running mean colour (brightness-normalised chroma + log luminance)
        float c = fmaxf((float)cnt[v], 1.0f);
        float r = csum[v*3] / c, g = csum[v*3+1] / c, b = csum[v*3+2] / c;
        float lum = r + g + b + 1.0f;
        float best = 1e30f; int bi = 1;
        for (int m = 0; m < npal; m++) {
            float pr = palette[m*3], pg = palette[m*3+1], pb = palette[m*3+2];
            float plum = pr + pg + pb + 1.0f;
            float d0 = (r/lum - pr/plum) * 600.0f, d1 = (g/lum - pg/plum) * 600.0f, d2 = (b/lum - pb/plum) * 600.0f;
            float dl2 = (logf(lum) - logf(plum)) * 60.0f;
            float dd = d0*d0 + d1*d1 + d2*d2 + dl2*dl2;
            if (dd < best) { best = dd; bi = m + 1; }
        }
        unsigned char om = mat[v];
        mat[v] = (unsigned char)bi;
        if (now_occ != was_occ || (now_occ && (om != bi || floorf(nq * 8.0f) > floorf(oq * 8.0f)))) changed = true;
    }
    if (sb != 0) {   // a fresh visit: a new side, or a long pause since the last pass
        float tm = tmaxb[v];
        if ((sb & ~vdir[v]) != 0 || (tm - lastpass[v] > PASS_GAP)) { npass[v] += 1; lastpass[v] = tm; }
        vdir[v] |= sb;
    }
    if (changed) stamp[v] = tick;
    delta[v] = 0; hitfr[v] = 0; sidebits[v] = 0; qb[v] = 0.0f; seenb[v] = -1.0f; tmaxb[v] = -1.0f;
}

// ---------------------------------------------------------------- point store
// P1: claim the cell of every surface point and allocate an id for new cells (one winner per cell).
extern "C" __global__ void k_pts_claim(
    MapDims d, int B, const float* __restrict__ poss, const float* __restrict__ rots, const float* __restrict__ est,
    const float* __restrict__ rays, const float* __restrict__ tcap, const int* __restrict__ drone,
    const unsigned char* __restrict__ sparse2d,
    int* pidx, int* npts, float* pt0, short* pdrone, unsigned char* pnew)
{
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)B * d.N) return;
    int b = (int)(idx / d.N), n = (int)(idx % d.N);
    float depth = est[idx];
    if (!(depth > 0.0f) || depth > POINT_MAX_RANGE) return;
    float dx, dy, dz; world_dir(rots + b*9, rays, n, dx, dy, dz);
    float x = poss[b*3] + dx*depth, y = poss[b*3+1] + dy*depth, z = poss[b*3+2] + dz*depth;
    long long key = cell_of(d, x, y, z);
    if (key < 0) return;
    if (z < 1.15f) {   // open ground outside the building: every other cell
        int gx = min(max((int)floorf(x), 0), d.sx - 1), gy = min(max((int)floorf(y), 0), d.sy - 1);
        int cx = (int)floorf(x / POINT_CELL), cy = (int)floorf(y / POINT_CELL);
        if (sparse2d[gx * d.sy + gy] && !((cx % 2 == 0) && (cy % 2 == 0))) return;
    }
    if (pidx[key] != -1) return;
    if (atomicCAS(&pidx[key], -1, -2) != -1) return;   // someone else is allocating this cell
    int id = atomicAdd(npts, 1);
    if (id >= d.pcap - 1) { atomicSub(npts, 1); pidx[key] = -1; return; }
    pt0[id] = tcap[b]; pdrone[id] = (short)drone[b]; pnew[id] = 1;
    __threadfence();
    pidx[key] = id;
}

// P2: accumulate every surface point into its cell's running weighted mean (weight 1/range^2).
extern "C" __global__ void k_pts_acc(
    MapDims d, int B, const float* __restrict__ poss, const float* __restrict__ rots, const float* __restrict__ est,
    const unsigned int* __restrict__ slots, const unsigned char* __restrict__ frgb, const float* __restrict__ rays,
    const unsigned char* __restrict__ sparse2d, const int* __restrict__ pidx,
    float* psum, float* pw, float* pcsum, int* nview, int* pdir, int* pst1, int batch_id)
{
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)B * d.N) return;
    int b = (int)(idx / d.N), n = (int)(idx % d.N);
    float depth = est[idx];
    if (!(depth > 0.0f) || depth > POINT_MAX_RANGE) return;
    float dx, dy, dz; world_dir(rots + b*9, rays, n, dx, dy, dz);
    float x = poss[b*3] + dx*depth, y = poss[b*3+1] + dy*depth, z = poss[b*3+2] + dz*depth;
    long long key = cell_of(d, x, y, z);
    if (key < 0) return;
    int pid = pidx[key];
    if (pid < 0) return;   // thinned out (ground) or the store is full
    if (z < 1.15f) {
        int gx = min(max((int)floorf(x), 0), d.sx - 1), gy = min(max((int)floorf(y), 0), d.sy - 1);
        int cx = (int)floorf(x / POINT_CELL), cy = (int)floorf(y / POINT_CELL);
        if (sparse2d[gx * d.sy + gy] && !((cx % 2 == 0) && (cy % 2 == 0))) return;
    }
    float w = 1.0f / fmaxf(depth, 1.0f) / fmaxf(depth, 1.0f);
    atomicAdd(&psum[pid*3], w*x); atomicAdd(&psum[pid*3+1], w*y); atomicAdd(&psum[pid*3+2], w*z);
    atomicAdd(&pw[pid], w);
    const unsigned char* px = frgb + ((long long)slots[b] * d.N + n) * 3;
    atomicAdd(&pcsum[pid*3], w*px[0]); atomicAdd(&pcsum[pid*3+1], w*px[1]); atomicAdd(&pcsum[pid*3+2], w*px[2]);
    if (atomicExch(&pst1[pid], batch_id) != batch_id) atomicAdd(&nview[pid], 1);   // one view per cell per batch
    float lx = -dx, ly = -dy, lz = -dz;   // side facing the camera
    float ax = fabsf(dx), ay = fabsf(dy), az = fabsf(dz);
    int axis = 0; float best = ax; if (ay > best) { axis = 1; best = ay; } if (az > best) { axis = 2; }
    float comp = axis == 0 ? dx : (axis == 1 ? dy : dz);
    atomicOr(&pdir[pid], 1 << (axis * 2 + (comp > 0.0f ? 1 : 0)));
    (void)lx; (void)ly; (void)lz;
}

// P3: once per touched point: new position, color, smoothing offset kept, versions bumped, marked dirty.
extern "C" __global__ void k_pts_fin(
    MapDims d, int B, const float* __restrict__ poss, const float* __restrict__ rots, const float* __restrict__ est,
    const float* __restrict__ rays, const int* __restrict__ pidx,
    const float* __restrict__ psum, const float* __restrict__ pw, const float* __restrict__ pcsum,
    float* praw, float* spos, unsigned char* pcol, unsigned char* pnew, int* pver, int* prv, unsigned char* pdirty,
    int* pst2, int* pvox, int batch_id)
{
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)B * d.N) return;
    int b = (int)(idx / d.N), n = (int)(idx % d.N);
    float depth = est[idx];
    if (!(depth > 0.0f) || depth > POINT_MAX_RANGE) return;
    float dx, dy, dz; world_dir(rots + b*9, rays, n, dx, dy, dz);
    float x = poss[b*3] + dx*depth, y = poss[b*3+1] + dy*depth, z = poss[b*3+2] + dz*depth;
    long long key = cell_of(d, x, y, z);
    if (key < 0) return;
    int pid = pidx[key];
    if (pid < 0) return;
    if (atomicExch(&pst2[pid], batch_id) == batch_id) return;   // another pixel of this cell is finishing it
    float w = pw[pid];
    if (!(w > 0.0f)) return;
    float nx = psum[pid*3] / w, ny = psum[pid*3+1] / w, nz = psum[pid*3+2] / w;
    if (pnew[pid]) {
        spos[pid*3] = nx; spos[pid*3+1] = ny; spos[pid*3+2] = nz;
        pnew[pid] = 0;
        int v = vox_of(d, nx, ny, nz);
        if (v >= 0) atomicAdd(&pvox[v], 1);
    } else {   // keep the smoothing offset: shift the smoothed position by the same amount as the raw one
        spos[pid*3] += nx - praw[pid*3]; spos[pid*3+1] += ny - praw[pid*3+1]; spos[pid*3+2] += nz - praw[pid*3+2];
    }
    praw[pid*3] = nx; praw[pid*3+1] = ny; praw[pid*3+2] = nz;
    for (int k = 0; k < 3; k++) pcol[pid*3+k] = (unsigned char)fminf(fmaxf(pcsum[pid*3+k] / w, 0.0f), 255.0f);
    pver[pid] += 1; prv[pid] += 1; pdirty[pid] = 1;
}
