// Frame-to-map alignment: one block per frame. Point-to-plane Gauss-Newton with priors (pose + depth
// scale) against the smoothed point cloud, then the observable-subspace projection for the VIO.
#define MAXM 640
#define A_SIGMA_R 0.10f
#define A_HUBER 0.25f
#define A_MAX_DIST2 0.36f
#define A_TRUST_AGE 8.0f
#define A_ITERS 4

__device__ void rodrigues(const float* w, float* R) {   // R row-major
    float th = sqrtf(w[0]*w[0] + w[1]*w[1] + w[2]*w[2]);
    float a, b;
    if (th < 1e-9f) { a = 1.0f; b = 0.5f; } else { a = sinf(th) / th; b = (1.0f - cosf(th)) / (th * th); }
    float K[9] = {0, -w[2], w[1], w[2], 0, -w[0], -w[1], w[0], 0};
    float K2[9];
    for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) { float s = 0; for (int k = 0; k < 3; k++) s += K[i*3+k] * K[k*3+j]; K2[i*3+j] = s; }
    for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) R[i*3+j] = (i == j ? 1.0f : 0.0f) + a * K[i*3+j] + b * K2[i*3+j];
}
__device__ void log_so3(const float* R, float* w) {
    float tr = R[0] + R[4] + R[8];
    float th = acosf(fminf(fmaxf((tr - 1.0f) / 2.0f, -1.0f), 1.0f));
    float vx = R[7] - R[5], vy = R[2] - R[6], vz = R[3] - R[1];
    float k = th > 1e-6f ? th / (2.0f * fmaxf(sinf(th), 1e-9f)) : 0.5f;
    w[0] = vx * k; w[1] = vy * k; w[2] = vz * k;
}
__device__ void matmul3(const float* A, const float* B, float* C) {
    float T[9];
    for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) { float s = 0; for (int k = 0; k < 3; k++) s += A[i*3+k] * B[k*3+j]; T[i*3+j] = s; }
    for (int i = 0; i < 9; i++) C[i] = T[i];
}
// Solve A x = b for an n x n system (Gaussian elimination, partial pivoting). A is n x (n+1) augmented.
__device__ void solve_aug(float* A, int n, float* x) {
    for (int c = 0; c < n; c++) {
        int p = c; float best = fabsf(A[c*(n+1)+c]);
        for (int r = c + 1; r < n; r++) { float v = fabsf(A[r*(n+1)+c]); if (v > best) { best = v; p = r; } }
        if (p != c) for (int k = 0; k <= n; k++) { float t = A[c*(n+1)+k]; A[c*(n+1)+k] = A[p*(n+1)+k]; A[p*(n+1)+k] = t; }
        float piv = A[c*(n+1)+c]; if (fabsf(piv) < 1e-12f) piv = 1e-12f;
        for (int r = c + 1; r < n; r++) {
            float f = A[r*(n+1)+c] / piv;
            for (int k = c; k <= n; k++) A[r*(n+1)+k] -= f * A[c*(n+1)+k];
        }
    }
    for (int r = n - 1; r >= 0; r--) {
        float s = A[r*(n+1)+n];
        for (int k = r + 1; k < n; k++) s -= A[r*(n+1)+k] * x[k];
        float piv = A[r*(n+1)+r]; if (fabsf(piv) < 1e-12f) piv = 1e-12f;
        x[r] = s / piv;
    }
}
// Symmetric 6x6 eigen decomposition (cyclic Jacobi). Returns eigenvalues in ev, eigenvectors as columns of V (row-major 6x6).
__device__ void jacobi6(float* A, float* ev, float* V) {
    for (int i = 0; i < 36; i++) V[i] = (i / 6 == i % 6) ? 1.0f : 0.0f;
    for (int sweep = 0; sweep < 30; sweep++) {
        float off = 0;
        for (int i = 0; i < 6; i++) for (int j = i + 1; j < 6; j++) off += A[i*6+j] * A[i*6+j];
        if (off < 1e-20f) break;
        for (int p = 0; p < 5; p++) for (int q = p + 1; q < 6; q++) {
            float apq = A[p*6+q]; if (fabsf(apq) < 1e-30f) continue;
            float th = (A[q*6+q] - A[p*6+p]) / (2.0f * apq);
            float t = (th >= 0 ? 1.0f : -1.0f) / (fabsf(th) + sqrtf(th * th + 1.0f));
            float c = rsqrtf(t * t + 1.0f), s = t * c;
            for (int k = 0; k < 6; k++) { float akp = A[k*6+p], akq = A[k*6+q]; A[k*6+p] = c*akp - s*akq; A[k*6+q] = s*akp + c*akq; }
            for (int k = 0; k < 6; k++) { float apk = A[p*6+k], aqk = A[q*6+k]; A[p*6+k] = c*apk - s*aqk; A[q*6+k] = s*apk + c*aqk; }
            for (int k = 0; k < 6; k++) { float vkp = V[k*6+p], vkq = V[k*6+q]; V[k*6+p] = c*vkp - s*vkq; V[k*6+q] = s*vkp + c*vkq; }
        }
    }
    for (int i = 0; i < 6; i++) ev[i] = A[i*6+i];
}

// ---- frame-to-model residual. The model is the signed-distance volume (value / gradient by trilinear
// interpolation of the 8 surrounding voxels, no search radius) plus absolute landmark planes. Returns false
// where the model has nothing to say.
#define A_MAX_DEPTH 40.0f
#define A_LM_CAP 1.0f
__device__ bool sample_tsdf(const TsdfDims& t, const float* __restrict__ S, const float* __restrict__ W,
                            float px, float py, float pz, float& r, float* n)
{
    float gx = px / T_VOXEL - 0.5f, gy = py / T_VOXEL - 0.5f, gz = pz / T_VOXEL - 0.5f;
    int ix = (int)floorf(gx), iy = (int)floorf(gy), iz = (int)floorf(gz);
    float fx = gx - ix, fy = gy - iy, fz = gz - iz;
    if (ix < 0 || iy < 0 || iz < 0 || ix + 1 >= t.nx || iy + 1 >= t.ny || iz + 1 >= t.nz) return false;
    float v[8];
    for (int c = 0; c < 8; c++) {
        long long q = tidx(t, ix + (c & 1), iy + ((c >> 1) & 1), iz + ((c >> 2) & 1));
        float w = W[q];
        if (w < T_MIN_W) return false;
        v[c] = S[q] / w;
    }
    float wx[2] = {1.0f - fx, fx}, wy[2] = {1.0f - fy, fy}, wz[2] = {1.0f - fz, fz};
    float val = 0, g0 = 0, g1 = 0, g2 = 0;
    for (int c = 0; c < 8; c++) {
        int cx = c & 1, cy = (c >> 1) & 1, cz = (c >> 2) & 1;
        val += v[c] * wx[cx] * wy[cy] * wz[cz];
        g0 += v[c] * (cx ? 1.0f : -1.0f) * wy[cy] * wz[cz];
        g1 += v[c] * (cy ? 1.0f : -1.0f) * wx[cx] * wz[cz];
        g2 += v[c] * (cz ? 1.0f : -1.0f) * wx[cx] * wy[cy];
    }
    float gn = sqrtf(g0*g0 + g1*g1 + g2*g2);
    if (fabsf(val) > 0.9f || gn < 0.15f) return false;      // outside the band, or too flat to say where the surface is
    r = val / fmaxf(gn, 0.5f) * T_VOXEL;                    // metres from the surface along the gradient
    n[0] = g0 / gn; n[1] = g1 / gn; n[2] = g2 / gn;
    return true;
}
// Surface normal of a pixel from its neighbours' depths (world frame); false at depth edges.
__device__ bool img_normal(const MapDims& d, const float* R, const float* rays, const float* e, int n, float depth, float* nv) {
    const int K = 3;
    int px = n % d.W, py = n / d.W;
    if (px < K || py < K || px >= d.W - K || py >= d.H - K) return false;
    int off[4] = {-K, K, -K * d.W, K * d.W};
    float P[4][3];
    for (int k = 0; k < 4; k++) {
        int m = n + off[k];
        float dm = e[m];
        if (!(dm > 0.0f) || fabsf(dm - depth) > 0.15f * depth) return false;
        float dx, dy, dz; world_dir(R, rays, m, dx, dy, dz);
        P[k][0] = dx * dm; P[k][1] = dy * dm; P[k][2] = dz * dm;
    }
    float u[3] = {P[1][0]-P[0][0], P[1][1]-P[0][1], P[1][2]-P[0][2]}, w[3] = {P[3][0]-P[2][0], P[3][1]-P[2][1], P[3][2]-P[2][2]};
    float c0 = u[1]*w[2] - u[2]*w[1], c1 = u[2]*w[0] - u[0]*w[2], c2 = u[0]*w[1] - u[1]*w[0];
    float l = sqrtf(c0*c0 + c1*c1 + c2*c2);
    if (l < 1e-9f) return false;
    nv[0] = c0 / l; nv[1] = c1 / l; nv[2] = c2 / l;
    return true;
}
// kind: 0 = signed-distance model, 1 = landmark plane
__device__ bool model_residual(const TsdfDims& t, const float* __restrict__ S, const float* __restrict__ W,
                               const float* __restrict__ lm, int nlm, const float* nimg, float px, float py, float pz,
                               float& r, float* n, int& kind, float& wk)
{
    kind = 0; wk = 1.0f;
    if (nlm > 0 && (nimg[0] != 0.0f || nimg[1] != 0.0f || nimg[2] != 0.0f)) {
        float p[3] = {px, py, pz};
        float best = A_LM_CAP; bool ok = false;
        for (int q = 0; q < nlm; q++) {
            const float* L = lm + q * 8;
            int a = (int)L[0];
            float dd = fabsf(p[a] - L[1]);
            if (dd >= best || fabsf(nimg[a]) < 0.85f) continue;
            float p1 = p[(a + 1) % 3], p2 = p[(a + 2) % 3];
            if (p1 < L[2] - 0.8f || p1 > L[3] + 0.8f || p2 < L[4] - 0.8f || p2 > L[5] + 0.8f) continue;
            best = dd; r = p[a] - L[1]; n[0] = n[1] = n[2] = 0.0f; n[a] = 1.0f; wk = L[6]; ok = true;
        }
        if (ok) { kind = 1; return true; }
    }
    return sample_tsdf(t, S, W, px, py, pz, r, n);
}

// one block per frame; ares: B x 24 floats
extern "C" __global__ void k_align(
    MapDims d, int sub, TsdfDims t, const float* __restrict__ poss, const float* __restrict__ rots, const float* __restrict__ est,
    const float* __restrict__ rays, const float* __restrict__ S, const float* __restrict__ W,
    const float* __restrict__ lm, int nlm, float* __restrict__ ares)
{
    __shared__ float sa[MAXM*3], simg[MAXM*3], sdep[MAXM];
    __shared__ float H[49], rhs[7], red[64];
    __shared__ float Rtot[9], ttot[3], stot;
    __shared__ float dR[9], dx7[7];
    __shared__ int ngood_s, nland_s, inl_s, nfin_s;
    int b = blockIdx.x, tid = threadIdx.x;
    int M = (d.N + sub - 1) / sub; if (M > MAXM) M = MAXM;
    const float* R = rots + b*9;
    const float* e = est + (long long)b * d.N;
    float cx = poss[b*3], cy = poss[b*3+1], cz = poss[b*3+2];
    if (tid == 0) { for (int i = 0; i < 9; i++) Rtot[i] = (i % 4 == 0) ? 1.0f : 0.0f; ttot[0] = ttot[1] = ttot[2] = 0; stot = 0;
                    ngood_s = 0; nland_s = 0; inl_s = 0; nfin_s = 0; }
    __syncthreads();
    // ---- the points to align: back-projected pixels, with the normal their neighbours give
    for (int i = tid; i < M; i += blockDim.x) {
        int n = i * sub;
        float depth = e[n];
        float a0 = 0, a1 = 0, a2 = 0, nv[3] = {0, 0, 0};
        float dd = 0.0f;
        if (depth > 0.0f && depth <= A_MAX_DEPTH) {
            float dx, dy, dz; world_dir(R, rays, n, dx, dy, dz);
            a0 = dx*depth; a1 = dy*depth; a2 = dz*depth; dd = depth;
            if (nlm > 0 && !img_normal(d, R, rays, e, n, depth, nv)) { nv[0] = nv[1] = nv[2] = 0.0f; }
        }
        sa[i*3] = a0; sa[i*3+1] = a1; sa[i*3+2] = a2; sdep[i] = dd;
        simg[i*3] = nv[0]; simg[i*3+1] = nv[1]; simg[i*3+2] = nv[2];
    }
    __syncthreads();
    float prior[7] = {1.0f/(0.05f*0.05f), 1.0f/(0.05f*0.05f), 1.0f/(0.05f*0.05f), 4.0f, 4.0f, 4.0f, 1.0f/(0.04f*0.04f)};
    float Hlast[49], rms0 = 0.0f;
    for (int it = 0; it < A_ITERS; it++) {
        for (int i = tid; i < 49 + 7 + 1; i += blockDim.x) { if (i < 49) H[i] = 0; else if (i < 56) rhs[i-49] = 0; else red[0] = 0; }
        __syncthreads();
        float lH[28]; float lr[7]; float lrr = 0.0f;
        for (int k = 0; k < 28; k++) lH[k] = 0; for (int k = 0; k < 7; k++) lr[k] = 0;
        for (int i = tid; i < M; i += blockDim.x) {
            float dep = sdep[i];
            if (dep <= 0.0f) continue;
            float ax = sa[i*3], ay = sa[i*3+1], az = sa[i*3+2];
            float r, nn[3], wk; int kind;
            if (!model_residual(t, S, W, lm, nlm, simg + i*3, cx + ax, cy + ay, cz + az, r, nn, kind, wk)) continue;
            if (it == 0) { atomicAdd(&ngood_s, 1); if (kind == 1) atomicAdd(&nland_s, 1); lrr += r * r; }
            float nx = nn[0], ny = nn[1], nz = nn[2];
            float ar = fabsf(r);
            float w = (ar < A_HUBER ? 1.0f : A_HUBER / fmaxf(ar, 1e-9f)) * wk / (1.0f + (dep / 8.0f) * (dep / 8.0f));
            float J[7] = {ay*nz - az*ny, az*nx - ax*nz, ax*ny - ay*nx, nx, ny, nz, nx*ax + ny*ay + nz*az};
            int k = 0;
            for (int p = 0; p < 7; p++) { lr[p] += -w * J[p] * r; for (int q = p; q < 7; q++) lH[k++] += w * J[p] * J[q]; }
        }
        int k = 0;
        for (int p = 0; p < 7; p++) { atomicAdd(&rhs[p], lr[p]); for (int q = p; q < 7; q++) { atomicAdd(&H[p*7+q], lH[k]); k++; } }
        if (it == 0) atomicAdd(&red[0], lrr);
        __syncthreads();
        if (tid == 0) {
            if (it == 0) rms0 = sqrtf(red[0] / fmaxf((float)ngood_s, 1.0f));
            float A[7*8];
            for (int p = 0; p < 7; p++) for (int q = 0; q < 7; q++) {
                float h = (q >= p ? H[p*7+q] : H[q*7+p]) / (A_SIGMA_R * A_SIGMA_R);
                Hlast[p*7+q] = h;
                A[p*8+q] = h + (p == q ? prior[p] : 0.0f);
            }
            float xacc[7]; log_so3(Rtot, xacc); xacc[3] = ttot[0]; xacc[4] = ttot[1]; xacc[5] = ttot[2]; xacc[6] = stot;
            for (int p = 0; p < 7; p++) A[p*8+7] = rhs[p] / (A_SIGMA_R * A_SIGMA_R) - prior[p] * xacc[p];
            float x[7]; solve_aug(A, 7, x);
            rodrigues(x, dR);
            for (int p = 0; p < 7; p++) dx7[p] = x[p];
            matmul3(dR, Rtot, Rtot);
            float nt[3]; for (int i = 0; i < 3; i++) nt[i] = dR[i*3]*ttot[0] + dR[i*3+1]*ttot[1] + dR[i*3+2]*ttot[2] + x[3+i];
            ttot[0] = nt[0]; ttot[1] = nt[1]; ttot[2] = nt[2];
            stot = (1.0f + stot) * (1.0f + x[6]) - 1.0f;
        }
        __syncthreads();
        for (int i = tid; i < M; i += blockDim.x) {
            float ax = sa[i*3] * (1.0f + dx7[6]), ay = sa[i*3+1] * (1.0f + dx7[6]), az = sa[i*3+2] * (1.0f + dx7[6]);
            sa[i*3]   = dR[0]*ax + dR[1]*ay + dR[2]*az + dx7[3];
            sa[i*3+1] = dR[3]*ax + dR[4]*ay + dR[5]*az + dx7[4];
            sa[i*3+2] = dR[6]*ax + dR[7]*ay + dR[8]*az + dx7[5];
        }
        __syncthreads();
    }
    // ---- final residual and inliers
    if (tid == 0) { red[1] = 0; red[2] = 0; }
    __syncthreads();
    float lrr = 0; int linl = 0, lfin = 0;
    for (int i = tid; i < M; i += blockDim.x) {
        float dep = sdep[i];
        if (dep <= 0.0f) continue;
        float r, nn[3], wk; int kind;
        if (!model_residual(t, S, W, lm, nlm, simg + i*3, cx + sa[i*3], cy + sa[i*3+1], cz + sa[i*3+2], r, nn, kind, wk)) continue;
        lrr += r * r; lfin++; if (fabsf(r) < A_HUBER) linl++;
    }
    atomicAdd(&red[1], lrr); atomicAdd(&inl_s, linl); atomicAdd(&nfin_s, lfin);
    __syncthreads();
    if (tid == 0) {
        float* o = ares + b * 24;
        for (int i = 0; i < 24; i++) o[i] = 0.0f;
        float rms1 = sqrtf(red[1] / fmaxf((float)nfin_s, 1.0f));
        float lw[3]; log_so3(Rtot, lw);
        float ang = sqrtf(lw[0]*lw[0] + lw[1]*lw[1] + lw[2]*lw[2]);
        float tn = sqrtf(ttot[0]*ttot[0] + ttot[1]*ttot[1] + ttot[2]*ttot[2]);
        bool fit = rms1 <= 0.95f * rms0 || rms1 < 0.05f;
        bool accept = ngood_s >= 80 && inl_s >= 60 && fit && tn <= 1.5f && ang <= 0.17453293f && fabsf(stot) <= 0.15f;
        o[0] = accept ? 1.0f : 0.0f;
        // why a frame was rejected: 1 too few correspondences, 2 too few inliers, 3 fit did not improve, 4 translation too big,
        // 5 rotation too big, 6 depth scale too big
        o[22] = accept ? 0.0f : ngood_s < 80 ? 1.0f : inl_s < 60 ? 2.0f : !fit ? 3.0f : tn > 1.5f ? 4.0f
                : ang > 0.17453293f ? 5.0f : 6.0f;
        o[23] = (float)ngood_s;
        o[1] = ttot[0]; o[2] = ttot[1]; o[3] = ttot[2];
        for (int i = 0; i < 9; i++) o[4+i] = Rtot[i];
        o[13] = 1.0f + stot;
        // "cross" is how much of the evidence is independent of this drone's own earlier (drifted) frames: landmarks fully,
        // the signed-distance model only a little (it can be made of this drone's own view)
        o[18] = ngood_s > 0 ? ((float)nland_s + 0.25f * (float)(ngood_s - nland_s)) / (float)ngood_s : 0.0f;
        o[19] = (float)inl_s; o[20] = rms0; o[21] = rms1;
        if (accept) {   // directions the view actually constrains: depth scale eliminated first, then eigen-split
            float Hs[36], ev[6], V[36], pw[6];
            for (int i = 0; i < 6; i++) pw[i] = sqrtf(prior[i]);
            float den = Hlast[6*7+6] + prior[6];
            for (int i = 0; i < 6; i++) for (int j = 0; j < 6; j++)
                Hs[i*6+j] = (Hlast[i*7+j] - Hlast[i*7+6] * Hlast[6*7+j] / den) / (pw[i] * pw[j]);
            jacobi6(Hs, ev, V);
            float x[6] = {lw[0], lw[1], lw[2], ttot[0], ttot[1], ttot[2]};
            float xs[6]; for (int i = 0; i < 6; i++) xs[i] = x[i] * pw[i];
            float xo[6] = {0, 0, 0, 0, 0, 0};
            for (int e2 = 0; e2 < 6; e2++) {
                if (ev[e2] < 4.0f) continue;
                float c = 0; for (int i = 0; i < 6; i++) c += V[i*6+e2] * xs[i];
                for (int i = 0; i < 6; i++) xo[i] += V[i*6+e2] * c;
            }
            for (int i = 0; i < 6; i++) xo[i] /= pw[i];
            o[14] = xo[3]; o[15] = xo[4]; o[16] = xo[5]; o[17] = xo[2];
        }
    }
}

// Apply accepted corrections: corrected pose/rotation per frame, and scale the depth estimates.
extern "C" __global__ void k_apply_align(int B, const float* __restrict__ ares, const float* __restrict__ poss, const float* __restrict__ rots,
                                         float* __restrict__ pos_c, float* __restrict__ rot_c)
{
    int b = blockIdx.x * blockDim.x + threadIdx.x;
    if (b >= B) return;
    const float* a = ares + b * 24;
    bool acc = a[0] > 0.5f;
    for (int i = 0; i < 3; i++) pos_c[b*3+i] = poss[b*3+i] + (acc ? a[1+i] : 0.0f);
    if (acc) { float C[9]; matmul3(a + 4, rots + b*9, C); for (int i = 0; i < 9; i++) rot_c[b*9+i] = C[i]; }
    else for (int i = 0; i < 9; i++) rot_c[b*9+i] = rots[b*9+i];
}
extern "C" __global__ void k_scale_est(MapDims d, int B, const float* __restrict__ ares, float* __restrict__ est) {
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)B * d.N) return;
    const float* a = ares + (idx / d.N) * 24;
    if (a[0] > 0.5f) est[idx] *= a[13];
}
// Nearest obstacle straight ahead in each frame (drift-immune), over a cone of pixels.
extern "C" __global__ void k_clear_ahead(MapDims d, int B, const float* __restrict__ est, const int* __restrict__ cone, int nc, float* __restrict__ clear) {
    int b = blockIdx.x * blockDim.x + threadIdx.x;
    if (b >= B) return;
    float m = 12.0f;
    for (int i = 0; i < nc; i++) { float v = est[(long long)b * d.N + cone[i]]; if (v > 0.0f && v < m) m = v; }
    clear[b] = m;
}
