// Surface fusion and meshing. A truncated signed-distance volume (0.2 m voxels) accumulates every aligned
// frame (running weighted sums, atomics); dirty 32^3-voxel chunks are meshed on demand: observed-only Gaussian
// smoothing of the distance field, marching cubes with vertices shared by edge, normals from the smoothed
// field's gradient, colours from the colour volume, and vertices snapped onto assumed-straight wall planes.

#define T_BEHIND 0.5f
#define T_BAND_STEP 0.1f
#define T_FREE_STEP 0.2f
#define T_MAX_DEPTH 20.0f
#define T_MIN_DEPTH 0.3f
#define T_FREE_W 0.3f
#define CH 32
#define CHP 34            /* grid points per chunk side: CH + 2 (marching cubes uses points 0..CH, dual contouring -1..CH) */
#define PADV 3            /* smoothing context around a chunk */
#define WIN (CHP + 2 * PADV)


// mark the voxel's chunk dirty, and the neighbours whose smoothing / cell window reaches it
__device__ __forceinline__ void mark_dirty(const TsdfDims& t, unsigned char* dirty, int ix, int iy, int iz) {
    int lx = ix % CH, ly = iy % CH, lz = iz % CH;
    int cx = ix / CH, cy = iy / CH, cz = iz / CH;
    int dx0 = lx < PADV + 1 ? -1 : 0, dx1 = lx >= CH - PADV - 1 ? 1 : 0;
    int dy0 = ly < PADV + 1 ? -1 : 0, dy1 = ly >= CH - PADV - 1 ? 1 : 0;
    int dz0 = lz < PADV + 1 ? -1 : 0, dz1 = lz >= CH - PADV - 1 ? 1 : 0;
    for (int a = dx0; a <= dx1; a++) for (int b = dy0; b <= dy1; b++) for (int c = dz0; c <= dz1; c++) {
        int X = cx + a, Y = cy + b, Z = cz + c;
        if (X < 0 || Y < 0 || Z < 0 || X >= t.ncx || Y >= t.ncy || Z >= t.ncz) continue;
        dirty[(X * t.ncy + Y) * t.ncz + Z] = 1;
    }
}

// ---- integrate B frames: free space in front of each hit, and a band around it (signed distance)
extern "C" __global__ void k_tsdf(
    TsdfDims t, int B, int N, const float* __restrict__ poss, const float* __restrict__ rots, const float* __restrict__ est,
    const unsigned int* __restrict__ slots, const unsigned char* __restrict__ frgb, const float* __restrict__ rays,
    float* S, float* W, float* Sc, float* Wc, unsigned char* dirty, int pstride)
{
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)B * N) return;
    int b = (int)(idx / N), n = (int)(idx % N);
    if (!keep_pixel(n, pstride)) return;
    float depth = est[idx];
    if (!(depth > T_MIN_DEPTH) || depth > T_MAX_DEPTH) return;
    const float* R = rots + b*9;
    float bx = rays[n*3], by = rays[n*3+1], bz = rays[n*3+2];
    float dx = R[0]*bx + R[1]*by + R[2]*bz, dy = R[3]*bx + R[4]*by + R[5]*bz, dz = R[6]*bx + R[7]*by + R[8]*bz;
    float px = poss[b*3], py = poss[b*3+1], pz = poss[b*3+2];
    float wf = 4.0f / fmaxf(depth, 1.0f) / fmaxf(depth, 1.0f);
    const unsigned char* c = frgb + ((long long)slots[b] * N + n) * 3;
    float cr = c[0], cg = c[1], cb = c[2];
    // band around the surface: offsets -MU .. +BEHIND
    for (float off = -T_MU; off <= T_BEHIND + 1e-4f; off += T_BAND_STEP) {
        float s = depth + off;
        int ix = (int)floorf((px + dx*s) / T_VOXEL), iy = (int)floorf((py + dy*s) / T_VOXEL), iz = (int)floorf((pz + dz*s) / T_VOXEL);
        if (ix < 0 || iy < 0 || iz < 0 || ix >= t.nx || iy >= t.ny || iz >= t.nz) continue;
        long long v = tidx(t, ix, iy, iz);
        float sdf = fminf(fmaxf(-off / T_MU, -1.0f), 1.0f);
        atomicAdd(&S[v], wf * sdf); atomicAdd(&W[v], wf);
        if (fabsf(off) <= 0.2f) { atomicAdd(&Sc[v*3], wf*cr); atomicAdd(&Sc[v*3+1], wf*cg); atomicAdd(&Sc[v*3+2], wf*cb); atomicAdd(&Wc[v], wf); }
        mark_dirty(t, dirty, ix, iy, iz);
    }
    // free space in front of the band
    for (float s = T_MIN_DEPTH; s < depth - T_MU; s += T_FREE_STEP) {
        int ix = (int)floorf((px + dx*s) / T_VOXEL), iy = (int)floorf((py + dy*s) / T_VOXEL), iz = (int)floorf((pz + dz*s) / T_VOXEL);
        if (ix < 0 || iy < 0 || iz < 0 || ix >= t.nx || iy >= t.ny || iz >= t.nz) continue;
        long long v = tidx(t, ix, iy, iz);
        atomicAdd(&S[v], wf * T_FREE_W); atomicAdd(&W[v], wf * T_FREE_W);
        mark_dirty(t, dirty, ix, iy, iz);
    }
}

// ---- chunk field: observed-only Gaussian smoothing of the distance over a (CHP)^3 grid.
// field[i] = value at grid point i (unobserved points hold 1.0); obs[i] = observed (and weight enough)
extern "C" __global__ void k_chunk_field(
    TsdfDims t, int ci, int cj, int ck, int og, const float* __restrict__ S, const float* __restrict__ W,
    const float* __restrict__ kern, int klen, float ksum3, float* field, unsigned char* obs)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= CHP * CHP * CHP) return;
    int gx = i / (CHP * CHP), gy = (i / CHP) % CHP, gz = i % CHP;
    int X = ci * CH + gx + og, Y = cj * CH + gy + og, Z = ck * CH + gz + og;
    bool inb = X >= 0 && Y >= 0 && Z >= 0 && X < t.nx && Y < t.ny && Z < t.nz;
    float w0 = 0.0f, v0 = 1.0f;
    if (inb) { long long v = tidx(t, X, Y, Z); w0 = W[v]; if (w0 >= T_MIN_W) v0 = S[v] / w0; }
    bool ob = inb && w0 >= T_MIN_W;
    obs[i] = ob ? 1 : 0;
    if (!ob) { field[i] = 1.0f; return; }
    int r = klen / 2;
    float num = 0.0f, den = 0.0f;
    for (int a = -r; a <= r; a++) for (int b = -r; b <= r; b++) for (int c = -r; c <= r; c++) {
        int x = X + a, y = Y + b, z = Z + c;
        if (x < 0 || y < 0 || z < 0 || x >= t.nx || y >= t.ny || z >= t.nz) continue;
        long long v = tidx(t, x, y, z);
        float w = W[v];
        if (w < T_MIN_W) continue;
        float kw = kern[a + r] * kern[b + r] * kern[c + r];
        num += kw * (S[v] / w); den += kw;
    }
    field[i] = (den / ksum3 > 0.25f) ? num / den : v0;
}

// ---- marching cubes. Cube (x,y,z) has corners (x..x+1, y..y+1, z..z+1) of the grid; a cube is meshed only
// when all 8 of its corners were observed. Vertices live on edge slots (lower corner + axis) so neighbours share them.
__device__ __constant__ int c_corner[8][3] = {{0,0,0},{1,0,0},{1,1,0},{0,1,0},{0,0,1},{1,0,1},{1,1,1},{0,1,1}};
__device__ __constant__ int c_edge[12][2] = {{0,1},{1,2},{2,3},{3,0},{4,5},{5,6},{6,7},{7,4},{0,4},{1,5},{2,6},{3,7}};

__device__ __forceinline__ int slot_of(int x, int y, int z, int axis) { return ((x * CHP + y) * CHP + z) * 3 + axis; }

extern "C" __global__ void k_mc_count(
    const float* __restrict__ field, const unsigned char* __restrict__ obs, const signed char* __restrict__ tri,
    unsigned char* edge_used, int* tri_slots, int* ntri, int max_tri)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= CH * CH * CH) return;
    int x = i / (CH * CH), y = (i / CH) % CH, z = i % CH;
    int idx = 0;
    for (int c = 0; c < 8; c++) {
        int gi = ((x + c_corner[c][0]) * CHP + (y + c_corner[c][1])) * CHP + (z + c_corner[c][2]);
        if (!obs[gi]) return;                 // not fully observed
        if (field[gi] < 0.0f) idx |= 1 << c;
    }
    if (idx == 0 || idx == 255) return;
    for (int k = 0; k < 15; k += 3) {
        int e0 = tri[idx * 16 + k];
        if (e0 < 0) break;
        int s[3];
        for (int q = 0; q < 3; q++) {
            int e = tri[idx * 16 + k + q];
            int ca = c_edge[e][0], cb = c_edge[e][1];
            int ax = x + min(c_corner[ca][0], c_corner[cb][0]), ay = y + min(c_corner[ca][1], c_corner[cb][1]), az = z + min(c_corner[ca][2], c_corner[cb][2]);
            int axis = (c_corner[ca][0] != c_corner[cb][0]) ? 0 : ((c_corner[ca][1] != c_corner[cb][1]) ? 1 : 2);
            s[q] = slot_of(ax, ay, az, axis);
            edge_used[s[q]] = 1;
        }
        int pos = atomicAdd(ntri, 1);
        if (pos < max_tri) { tri_slots[pos*3] = s[0]; tri_slots[pos*3+1] = s[1]; tri_slots[pos*3+2] = s[2]; }
    }
}

// exclusive prefix sum of edge_used over nslots entries: per-block scan, block totals, add offsets
extern "C" __global__ void k_scan_block(const unsigned char* __restrict__ used, int nslots, int* out, int* block_sum) {
    __shared__ int sh[1024];
    int tid = threadIdx.x, i = blockIdx.x * 1024 + tid;
    int v = (i < nslots) ? (int)used[i] : 0;
    sh[tid] = v;
    __syncthreads();
    for (int off = 1; off < 1024; off <<= 1) {
        int a = (tid >= off) ? sh[tid - off] : 0;
        __syncthreads(); sh[tid] += a; __syncthreads();
    }
    if (i < nslots) out[i] = sh[tid] - v;   // exclusive within the block
    if (tid == 1023) block_sum[blockIdx.x] = sh[1023];
}
extern "C" __global__ void k_scan_blocks(int* block_sum, int nb, int* total) {   // one thread: nb is small
    if (threadIdx.x == 0 && blockIdx.x == 0) { int acc = 0; for (int b = 0; b < nb; b++) { int v = block_sum[b]; block_sum[b] = acc; acc += v; } *total = acc; }
}
extern "C" __global__ void k_scan_add(int nslots, int* out, const int* __restrict__ block_sum) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < nslots) out[i] += block_sum[i / 1024];
}

// Flat walls: a vertex whose normal points along an axis and that sits near a detected wall plane goes
// exactly onto it. Rectangular openings: a vertex on a wall near the edge of a detected window or door goes
// exactly onto that edge.
__device__ void snap_vertex(float* w, float* nv, const float* __restrict__ planes, const int* __restrict__ nplanes,
                            float snap_tol, float snap_align, const float* __restrict__ opens, int nopen)
{
    for (int a = 0; a < 3; a++) {
        int np = nplanes[a];
        float bestd = snap_tol; int bk = -1;
        for (int k = 0; k < np; k++) {
            float dd = fabsf(w[a] - planes[a * 64 + k]);
            if (dd < bestd && fabsf(nv[a]) > snap_align) { bestd = dd; bk = k; }
        }
        if (bk >= 0) {
            float sg = nv[a] > 0.0f ? 1.0f : -1.0f;
            w[a] = planes[a * 64 + bk]; nv[0] = 0; nv[1] = 0; nv[2] = 0; nv[a] = sg;
            if (a < 2) {   // walls normal to x or y can have openings; u runs along the other horizontal axis, v is up
                int ua = 1 - a;
                for (int q = 0; q < nopen; q++) {
                    const float* o = opens + q * 8;
                    if ((int)o[0] != a) continue;
                    if (fabsf(w[a] - o[1]) > 0.15f && fabsf(w[a] - o[2]) > 0.15f) continue;
                    float u = w[ua], v = w[2], T = 0.3f;
                    if (u < o[3] - T || u > o[4] + T || v < o[5] - T || v > o[6] + T) continue;
                    if (fabsf(u - o[3]) < T) u = o[3]; else if (fabsf(u - o[4]) < T) u = o[4];
                    if (fabsf(v - o[5]) < T) v = o[5]; else if (fabsf(v - o[6]) < T) v = o[6];
                    w[ua] = u; w[2] = v;
                    break;
                }
            }
        }
    }
}

// vertices: one per used edge slot, written at its compact id
extern "C" __global__ void k_mc_verts(
    TsdfDims t, int ci, int cj, int ck, int nslots, const unsigned char* __restrict__ edge_used, const int* __restrict__ vid,
    const float* __restrict__ field, const float* __restrict__ Sc, const float* __restrict__ Wc,
    const float* __restrict__ planes, const int* __restrict__ nplanes, float snap_tol, float snap_align,
    const float* __restrict__ opens, int nopen,
    unsigned short* o_pos, signed char* o_nrm, unsigned char* o_col)
{
    int sl = blockIdx.x * blockDim.x + threadIdx.x;
    if (sl >= nslots || !edge_used[sl]) return;
    int axis = sl % 3, cell = sl / 3;
    int gz = cell % CHP, gy = (cell / CHP) % CHP, gx = cell / (CHP * CHP);
    int nx_ = gx + (axis == 0), ny_ = gy + (axis == 1), nz_ = gz + (axis == 2);
    float f0 = field[(gx * CHP + gy) * CHP + gz], f1 = field[(nx_ * CHP + ny_) * CHP + nz_];
    float tt = fminf(fmaxf(f0 / (f0 - f1), 0.0f), 1.0f);
    float p[3] = {(float)gx, (float)gy, (float)gz};
    p[axis] += tt;
    // normal: gradient of the smoothed field at the nearest grid point (central differences, one-sided at the edge)
    int qx = min(max((int)rintf(p[0]), 0), CHP - 1), qy = min(max((int)rintf(p[1]), 0), CHP - 1), qz = min(max((int)rintf(p[2]), 0), CHP - 1);
    float g[3];
    for (int a = 0; a < 3; a++) {
        int lo[3] = {qx, qy, qz}, hi[3] = {qx, qy, qz};
        lo[a] = max(lo[a] - 1, 0); hi[a] = min(hi[a] + 1, CHP - 1);
        g[a] = (field[(hi[0] * CHP + hi[1]) * CHP + hi[2]] - field[(lo[0] * CHP + lo[1]) * CHP + lo[2]]) / (float)max(hi[a] - lo[a], 1);
    }
    float gn = sqrtf(g[0]*g[0] + g[1]*g[1] + g[2]*g[2]); if (gn < 1e-6f) gn = 1e-6f;
    float nv[3] = {g[0]/gn, g[1]/gn, g[2]/gn};
    float w[3];
    for (int a = 0; a < 3; a++) w[a] = (p[a] + (float)((a == 0 ? ci : (a == 1 ? cj : ck)) * CH) + 0.5f) * T_VOXEL;
    snap_vertex(w, nv, planes, nplanes, snap_tol, snap_align, opens, nopen);
    int id = vid[sl];
    for (int a = 0; a < 3; a++) {
        o_pos[id*3+a] = (unsigned short)fminf(fmaxf(rintf(w[a] / 0.01f), 0.0f), 65535.0f);
        o_nrm[id*3+a] = (signed char)rintf(nv[a] * 127.0f);
    }
    // colour of the nearest voxel
    int X = ci * CH + qx, Y = cj * CH + qy, Z = ck * CH + qz;
    float cr = 128, cg = 128, cb = 128;
    if (X < t.nx && Y < t.ny && Z < t.nz) {
        long long v = tidx(t, X, Y, Z);
        float wc = Wc[v];
        if (wc > 0.0f) { cr = Sc[v*3] / wc; cg = Sc[v*3+1] / wc; cb = Sc[v*3+2] / wc; }
    }
    o_col[id*3] = (unsigned char)fminf(fmaxf(cr, 0.0f), 255.0f); o_col[id*3+1] = (unsigned char)fminf(fmaxf(cg, 0.0f), 255.0f); o_col[id*3+2] = (unsigned char)fminf(fmaxf(cb, 0.0f), 255.0f);
}

extern "C" __global__ void k_mc_faces(int ntri, const int* __restrict__ tri_slots, const int* __restrict__ vid, unsigned int* o_faces) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= ntri) return;
    for (int q = 0; q < 3; q++) o_faces[i*3+q] = (unsigned int)vid[tri_slots[i*3+q]];
}

// =====================================================================================================
// Dual contouring. One vertex per cell that the surface crosses, placed where the planes through the edge crossings
// (with the field's gradient as their normals) meet: flat walls stay flat and corners come out sharp, with one quad
// per crossing edge instead of marching cubes' sawtooth. The window is points -1..CH of the chunk (index = local + 1),
// so a chunk owns the quads of the edges that START inside it and still sees the cells on its lower border; the
// neighbour recomputes the same vertices from the same global field, so there are no cracks.
// =====================================================================================================
__device__ void jacobi3(float* A, float* ev, float* V) {   // symmetric 3x3, eigenvectors in the columns of V
    for (int i = 0; i < 9; i++) V[i] = (i % 4 == 0) ? 1.0f : 0.0f;
    for (int sweep = 0; sweep < 12; sweep++) {
        float off = A[1]*A[1] + A[2]*A[2] + A[5]*A[5];
        if (off < 1e-14f) break;
        for (int p = 0; p < 2; p++) for (int q = p + 1; q < 3; q++) {
            float apq = A[p*3+q]; if (fabsf(apq) < 1e-20f) continue;
            float th = (A[q*3+q] - A[p*3+p]) / (2.0f * apq);
            float t = (th >= 0 ? 1.0f : -1.0f) / (fabsf(th) + sqrtf(th * th + 1.0f));
            float c = rsqrtf(t * t + 1.0f), s = t * c;
            for (int k = 0; k < 3; k++) { float akp = A[k*3+p], akq = A[k*3+q]; A[k*3+p] = c*akp - s*akq; A[k*3+q] = s*akp + c*akq; }
            for (int k = 0; k < 3; k++) { float apk = A[p*3+k], aqk = A[q*3+k]; A[p*3+k] = c*apk - s*aqk; A[q*3+k] = s*apk + c*aqk; }
            for (int k = 0; k < 3; k++) { float vkp = V[k*3+p], vkq = V[k*3+q]; V[k*3+p] = c*vkp - s*vkq; V[k*3+q] = s*vkp + c*vkq; }
        }
    }
    for (int i = 0; i < 3; i++) ev[i] = A[i*3+i];
}
__device__ __forceinline__ int fidx(int x, int y, int z) { return (x * CHP + y) * CHP + z; }
__device__ void field_grad(const float* __restrict__ field, int x, int y, int z, float* g) {
    int p[3] = {x, y, z};
    for (int a = 0; a < 3; a++) {
        int lo[3] = {x, y, z}, hi[3] = {x, y, z};
        lo[a] = max(p[a] - 1, 0); hi[a] = min(p[a] + 1, CHP - 1);
        g[a] = (field[fidx(hi[0], hi[1], hi[2])] - field[fidx(lo[0], lo[1], lo[2])]) / (float)max(hi[a] - lo[a], 1);
    }
}

// one thread per cell (window cells 0..CHP-2 per axis); position/normal per active cell, in window units
extern "C" __global__ void k_dc_cells(const float* __restrict__ field, const unsigned char* __restrict__ obs,
                                      unsigned char* act, float* cpos, float* cnrm)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= CHP * CHP * CHP) return;
    int cx = i / (CHP * CHP), cy = (i / CHP) % CHP, cz = i % CHP;
    act[i] = 0;
    if (cx >= CHP - 1 || cy >= CHP - 1 || cz >= CHP - 1) return;
    int idx = 0;
    for (int c = 0; c < 8; c++) {
        int gi = fidx(cx + c_corner[c][0], cy + c_corner[c][1], cz + c_corner[c][2]);
        if (!obs[gi]) return;
        if (field[gi] < 0.0f) idx |= 1 << c;
    }
    if (idx == 0 || idx == 255) return;
    float m[3] = {0, 0, 0}, nsum[3] = {0, 0, 0};
    float pts[12][3], nrm[12][3]; int ne = 0;
    for (int e = 0; e < 12; e++) {
        int ca = c_edge[e][0], cb = c_edge[e][1];
        if (((idx >> ca) & 1) == ((idx >> cb) & 1)) continue;
        int ax = cx + c_corner[ca][0], ay = cy + c_corner[ca][1], az = cz + c_corner[ca][2];
        int bx = cx + c_corner[cb][0], by = cy + c_corner[cb][1], bz = cz + c_corner[cb][2];
        float fa = field[fidx(ax, ay, az)], fb = field[fidx(bx, by, bz)];
        float tt = fminf(fmaxf(fa / (fa - fb), 0.0f), 1.0f);
        pts[ne][0] = c_corner[ca][0] + tt * (c_corner[cb][0] - c_corner[ca][0]);
        pts[ne][1] = c_corner[ca][1] + tt * (c_corner[cb][1] - c_corner[ca][1]);
        pts[ne][2] = c_corner[ca][2] + tt * (c_corner[cb][2] - c_corner[ca][2]);
        float ga[3], gb[3];
        field_grad(field, ax, ay, az, ga); field_grad(field, bx, by, bz, gb);
        float g[3] = {ga[0] + tt * (gb[0] - ga[0]), ga[1] + tt * (gb[1] - ga[1]), ga[2] + tt * (gb[2] - ga[2])};
        float gn = sqrtf(g[0]*g[0] + g[1]*g[1] + g[2]*g[2]);
        if (gn < 1e-6f) { g[0] = 0; g[1] = 0; g[2] = 1; gn = 1; }
        for (int k = 0; k < 3; k++) { nrm[ne][k] = g[k] / gn; m[k] += pts[ne][k]; nsum[k] += nrm[ne][k]; }
        ne++;
    }
    if (ne == 0) return;
    for (int k = 0; k < 3; k++) m[k] /= (float)ne;
    // least-squares point: minimise sum (n . (x - p))^2, pulled to the mass point where the planes do not pin it down
    float A[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0}, bv[3] = {0, 0, 0};
    for (int e = 0; e < ne; e++) {
        float d = nrm[e][0]*(pts[e][0]-m[0]) + nrm[e][1]*(pts[e][1]-m[1]) + nrm[e][2]*(pts[e][2]-m[2]);
        for (int p = 0; p < 3; p++) { bv[p] += nrm[e][p] * d; for (int q = 0; q < 3; q++) A[p*3+q] += nrm[e][p] * nrm[e][q]; }
    }
    float ev[3], V[9]; jacobi3(A, ev, V);
    float emax = fmaxf(ev[0], fmaxf(ev[1], ev[2]));
    float x[3] = {m[0], m[1], m[2]};
    for (int k = 0; k < 3; k++) {
        if (ev[k] < 0.15f * emax || ev[k] < 1e-6f) continue;     // not constrained along this direction: stay at the mass point
        float c = V[0*3+k]*bv[0] + V[1*3+k]*bv[1] + V[2*3+k]*bv[2];
        for (int p = 0; p < 3; p++) x[p] += V[p*3+k] * c / ev[k];
    }
    for (int p = 0; p < 3; p++) x[p] = fminf(fmaxf(x[p], 0.0f), 1.0f);
    float nl = sqrtf(nsum[0]*nsum[0] + nsum[1]*nsum[1] + nsum[2]*nsum[2]); if (nl < 1e-6f) nl = 1.0f;
    act[i] = 1;
    for (int p = 0; p < 3; p++) { cpos[i*3+p] = x[p]; cnrm[i*3+p] = nsum[p] / nl; }
}

// one thread per window point that starts a chunk-owned edge (window 1..CH on each axis): a quad for every
// axis edge the surface crosses whose four cells all have a vertex
extern "C" __global__ void k_dc_quads(const float* __restrict__ field, const unsigned char* __restrict__ obs,
                                      const unsigned char* __restrict__ act, const float* __restrict__ cpos,
                                      const float* __restrict__ cnrm, unsigned char* used, int* tri_slots, int* ntri, int max_tri)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= CH * CH * CH) return;
    int px = 1 + i / (CH * CH), py = 1 + (i / CH) % CH, pz = 1 + i % CH;
    int p[3] = {px, py, pz};
    for (int a = 0; a < 3; a++) {
        int q[3] = {px, py, pz}; q[a] += 1;
        int gp = fidx(px, py, pz), gq = fidx(q[0], q[1], q[2]);
        if (!obs[gp] || !obs[gq]) continue;
        if ((field[gp] < 0.0f) == (field[gq] < 0.0f)) continue;
        int u = (a + 1) % 3, v = (a + 2) % 3;
        const int du[4] = {-1, 0, 0, -1}, dv[4] = {-1, -1, 0, 0};
        int cell[4]; bool ok = true;
        for (int k = 0; k < 4; k++) {
            int c[3] = {px, py, pz}; c[u] += du[k]; c[v] += dv[k];
            cell[k] = fidx(c[0], c[1], c[2]);
            if (!act[cell[k]]) { ok = false; break; }
        }
        if (!ok) continue;
        float P[4][3], ns[3] = {0, 0, 0};
        for (int k = 0; k < 4; k++) {
            int c[3] = {px, py, pz}; c[u] += du[k]; c[v] += dv[k];
            for (int d = 0; d < 3; d++) { P[k][d] = c[d] + cpos[cell[k]*3+d]; ns[d] += cnrm[cell[k]*3+d]; }
        }
        float e1[3] = {P[1][0]-P[0][0], P[1][1]-P[0][1], P[1][2]-P[0][2]}, e2[3] = {P[2][0]-P[0][0], P[2][1]-P[0][1], P[2][2]-P[0][2]};
        float gn[3] = {e1[1]*e2[2]-e1[2]*e2[1], e1[2]*e2[0]-e1[0]*e2[2], e1[0]*e2[1]-e1[1]*e2[0]};
        bool flip = gn[0]*ns[0] + gn[1]*ns[1] + gn[2]*ns[2] < 0.0f;
        int pos = atomicAdd(ntri, 2);
        if (pos + 1 >= max_tri) continue;
        int t0[3] = {cell[0], cell[1], cell[2]}, t1[3] = {cell[0], cell[2], cell[3]};
        if (flip) { t0[1] = cell[2]; t0[2] = cell[1]; t1[1] = cell[3]; t1[2] = cell[2]; }
        for (int k = 0; k < 3; k++) { tri_slots[pos*3+k] = t0[k]; tri_slots[(pos+1)*3+k] = t1[k]; }
        for (int k = 0; k < 4; k++) used[cell[k]] = 1;
    }
}

// vertices: one per used cell, at its compact id
extern "C" __global__ void k_dc_verts(
    TsdfDims t, int ci, int cj, int ck, int ncell, const unsigned char* __restrict__ used, const int* __restrict__ vid,
    const float* __restrict__ cpos, const float* __restrict__ cnrm, const float* __restrict__ Sc, const float* __restrict__ Wc,
    const float* __restrict__ planes, const int* __restrict__ nplanes, float snap_tol, float snap_align,
    const float* __restrict__ opens, int nopen,
    unsigned short* o_pos, signed char* o_nrm, unsigned char* o_col)
{
    int cell = blockIdx.x * blockDim.x + threadIdx.x;
    if (cell >= ncell || !used[cell]) return;
    int cz = cell % CHP, cy = (cell / CHP) % CHP, cx = cell / (CHP * CHP);
    float w[3], nv[3];
    float base[3] = {(float)cx, (float)cy, (float)cz};
    int off[3] = {ci * CH - 1, cj * CH - 1, ck * CH - 1};
    for (int a = 0; a < 3; a++) {
        w[a] = (base[a] + cpos[cell*3+a] + (float)off[a] + 0.5f) * T_VOXEL;
        nv[a] = cnrm[cell*3+a];
    }
    snap_vertex(w, nv, planes, nplanes, snap_tol, snap_align, opens, nopen);
    int id = vid[cell];
    for (int a = 0; a < 3; a++) {
        o_pos[id*3+a] = (unsigned short)fminf(fmaxf(rintf(w[a] / 0.01f), 0.0f), 65535.0f);
        o_nrm[id*3+a] = (signed char)rintf(nv[a] * 127.0f);
    }
    int X = off[0] + (int)rintf(base[0] + cpos[cell*3]), Y = off[1] + (int)rintf(base[1] + cpos[cell*3+1]), Z = off[2] + (int)rintf(base[2] + cpos[cell*3+2]);
    float cr = 128, cg = 128, cb = 128;
    if (X >= 0 && Y >= 0 && Z >= 0 && X < t.nx && Y < t.ny && Z < t.nz) {
        long long v = tidx(t, X, Y, Z);
        float wc = Wc[v];
        if (wc > 0.0f) { cr = Sc[v*3] / wc; cg = Sc[v*3+1] / wc; cb = Sc[v*3+2] / wc; }
    }
    o_col[id*3] = (unsigned char)fminf(fmaxf(cr, 0.0f), 255.0f); o_col[id*3+1] = (unsigned char)fminf(fmaxf(cg, 0.0f), 255.0f); o_col[id*3+2] = (unsigned char)fminf(fmaxf(cb, 0.0f), 255.0f);
}

// The same wall, as a heavy synthetic observation in the signed-distance volume: a band of +-0.4 m around the wall
// face over the rectangle; `sign` says which side is free (+1 / -1 along the axis).
extern "C" __global__ void k_fill_tsdf(TsdfDims t, int axis, float face, float u0, float u1, float v0, float v1, float sign,
                                       float* S, float* W, float* Sc, float* Wc, unsigned char* dirty, int is_free)
{
    long long i = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    int nu = (int)ceilf((u1 - u0) / T_VOXEL), nv = (int)ceilf((v1 - v0) / T_VOXEL);
    const int NW = 5;
    if (i >= (long long)nu * nv * NW) return;
    int iu = (int)(i / ((long long)nv * NW)), iv = (int)((i / NW) % nv), iw = (int)(i % NW);
    float p[3];
    p[axis] = face + (iw - 2) * T_VOXEL;
    p[(axis + 1) % 3] = u0 + (iu + 0.5f) * T_VOXEL;
    p[(axis + 2) % 3] = v0 + (iv + 0.5f) * T_VOXEL;
    int ix = (int)floorf(p[0] / T_VOXEL), iy = (int)floorf(p[1] / T_VOXEL), iz = (int)floorf(p[2] / T_VOXEL);
    if (ix < 0 || iy < 0 || iz < 0 || ix >= t.nx || iy >= t.ny || iz >= t.nz) return;
    long long v = tidx(t, ix, iy, iz);
    float sdf = is_free ? 1.0f : fminf(fmaxf(sign * (p[axis] - face) / T_MU, -1.0f), 1.0f);
    const float w = 6.0f;
    atomicAdd(&S[v], w * sdf); atomicAdd(&W[v], w);
    if (is_free) { mark_dirty(t, dirty, ix, iy, iz); return; }
    atomicAdd(&Sc[v*3], w * 150.0f); atomicAdd(&Sc[v*3+1], w * 150.0f); atomicAdd(&Sc[v*3+2], w * 150.0f); atomicAdd(&Wc[v], w);
    mark_dirty(t, dirty, ix, iy, iz);
}
