// Point-cloud smoothing: Gaussian-weighted PCA plane fit per dirty point over its 5x5x5-cell neighbourhood;
// planar points are pulled onto their plane (edges and corners untouched); isolated points flagged as outliers.
#define S_SIGMA 0.30
#define S_ALPHA 0.8
#define S_MAXMOVE 0.30

__device__ void eig3_min(const double* A, double* lam_min, double* vec, double* trace) {   // A symmetric 3x3 (row-major)
    double a00 = A[0], a01 = A[1], a02 = A[2], a11 = A[4], a12 = A[5], a22 = A[8];
    double p1 = a01*a01 + a02*a02 + a12*a12;
    double q = (a00 + a11 + a22) / 3.0;
    *trace = a00 + a11 + a22;
    double lam;
    if (p1 < 1e-30) { lam = fmin(fmin(a00, a11), a22); }
    else {
        double p2 = (a00-q)*(a00-q) + (a11-q)*(a11-q) + (a22-q)*(a22-q) + 2.0*p1;
        double p = sqrt(p2 / 6.0);
        double b00 = (a00-q)/p, b01 = a01/p, b02 = a02/p, b11 = (a11-q)/p, b12 = a12/p, b22 = (a22-q)/p;
        double det = b00*(b11*b22 - b12*b12) - b01*(b01*b22 - b12*b02) + b02*(b01*b12 - b11*b02);
        double r = fmin(fmax(det / 2.0, -1.0), 1.0);
        double phi = acos(r) / 3.0;
        lam = q + 2.0*p*cos(phi + 2.0*3.14159265358979323846/3.0);   // smallest
    }
    *lam_min = lam;
    // eigenvector: the largest cross product of two rows of (A - lam I)
    double r0[3] = {a00-lam, a01, a02}, r1[3] = {a01, a11-lam, a12}, r2[3] = {a02, a12, a22-lam};
    double c0[3] = {r0[1]*r1[2]-r0[2]*r1[1], r0[2]*r1[0]-r0[0]*r1[2], r0[0]*r1[1]-r0[1]*r1[0]};
    double c1[3] = {r0[1]*r2[2]-r0[2]*r2[1], r0[2]*r2[0]-r0[0]*r2[2], r0[0]*r2[1]-r0[1]*r2[0]};
    double c2[3] = {r1[1]*r2[2]-r1[2]*r2[1], r1[2]*r2[0]-r1[0]*r2[2], r1[0]*r2[1]-r1[1]*r2[0]};
    double n0 = c0[0]*c0[0]+c0[1]*c0[1]+c0[2]*c0[2], n1 = c1[0]*c1[0]+c1[1]*c1[1]+c1[2]*c1[2], n2 = c2[0]*c2[0]+c2[1]*c2[1]+c2[2]*c2[2];
    const double* c = c0; double nn = n0;
    if (n1 > nn) { c = c1; nn = n1; } if (n2 > nn) { c = c2; nn = n2; }
    if (nn < 1e-30) { vec[0] = 0; vec[1] = 0; vec[2] = 1; return; }
    double s = 1.0 / sqrt(nn); vec[0] = c[0]*s; vec[1] = c[1]*s; vec[2] = c[2]*s;
}

// Select up to maxn dirty points (rotating start so a backlog is served fairly); clears their dirty flag.
extern "C" __global__ void k_sm_collect(int npts, int off, int maxn, unsigned char* pdirty, int* list, int* cnt) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= npts) return;
    int id = (i + off) % npts;
    if (!pdirty[id]) return;
    int k = atomicAdd(cnt, 1);
    if (k < maxn) { list[k] = id; pdirty[id] = 0; }
    else atomicSub(cnt, 1);
}
extern "C" __global__ void k_sm_a(
    MapDims d, const int* __restrict__ list, int K, const int* __restrict__ pidx, const float* __restrict__ praw, const float* __restrict__ pw,
    const unsigned char* __restrict__ phid,
    float* o_spos, float* o_norm, float* o_resid, float* o_md, int* o_cnt, double* stats)   // stats: sum md, sum md2, n
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= K) return;
    int id = list[i];
    double c0x = praw[id*3], c0y = praw[id*3+1], c0z = praw[id*3+2];
    int gx = (int)floor(c0x / POINT_CELL), gy = (int)floor(c0y / POINT_CELL), gz = (int)floor(c0z / POINT_CELL);
    double sg = 1e-9, cx = 0, cy = 0, cz = 0; int nv = 0; double mdsum = 0;
    // pass 1: weights and centroid
    for (int ox = -2; ox <= 2; ox++) for (int oy = -2; oy <= 2; oy++) for (int oz = -2; oz <= 2; oz++) {
        int ax = gx + ox, ay = gy + oy, az = gz + oz;
        if (ax < 0 || ay < 0 || az < 0 || ax >= d.pcx || ay >= d.pcy || az >= d.pcz) continue;
        int pid = pidx[((long long)ax * d.pcy + ay) * d.pcz + az];
        if (pid < 0) continue;
        bool center = (ox == 0 && oy == 0 && oz == 0);
        if (!center && phid[pid] != 0) continue;
        double px = praw[pid*3], py = praw[pid*3+1], pz = praw[pid*3+2];
        double dd = (px-c0x)*(px-c0x) + (py-c0y)*(py-c0y) + (pz-c0z)*(pz-c0z);
        double w = exp(-dd / (2.0*S_SIGMA*S_SIGMA)) * fmin(fmax((double)pw[pid], 0.02), 2.0);
        sg += w; cx += w*px; cy += w*py; cz += w*pz; nv++; mdsum += sqrt(dd);
    }
    cx /= sg; cy /= sg; cz /= sg;
    double C[9] = {0,0,0,0,0,0,0,0,0};
    for (int ox = -2; ox <= 2; ox++) for (int oy = -2; oy <= 2; oy++) for (int oz = -2; oz <= 2; oz++) {
        int ax = gx + ox, ay = gy + oy, az = gz + oz;
        if (ax < 0 || ay < 0 || az < 0 || ax >= d.pcx || ay >= d.pcy || az >= d.pcz) continue;
        int pid = pidx[((long long)ax * d.pcy + ay) * d.pcz + az];
        if (pid < 0) continue;
        bool center = (ox == 0 && oy == 0 && oz == 0);
        if (!center && phid[pid] != 0) continue;
        double px = praw[pid*3], py = praw[pid*3+1], pz = praw[pid*3+2];
        double dd = (px-c0x)*(px-c0x) + (py-c0y)*(py-c0y) + (pz-c0z)*(pz-c0z);
        double w = exp(-dd / (2.0*S_SIGMA*S_SIGMA)) * fmin(fmax((double)pw[pid], 0.02), 2.0);
        double vx = px-cx, vy = py-cy, vz = pz-cz;
        C[0] += w*vx*vx; C[1] += w*vx*vy; C[2] += w*vx*vz; C[4] += w*vy*vy; C[5] += w*vy*vz; C[8] += w*vz*vz;
    }
    for (int k = 0; k < 9; k++) C[k] /= sg;
    C[3] = C[1]; C[6] = C[2]; C[7] = C[5];
    double lam, nrm[3], tr; eig3_min(C, &lam, nrm, &tr);
    bool planar = (lam < 0.05 * (tr + 1e-12)) && nv >= 8;
    double off = (c0x-cx)*nrm[0] + (c0y-cy)*nrm[1] + (c0z-cz)*nrm[2];
    double mx = 0, my = 0, mz = 0;
    if (planar) { mx = -S_ALPHA*off*nrm[0]; my = -S_ALPHA*off*nrm[1]; mz = -S_ALPHA*off*nrm[2];
        double mn = sqrt(mx*mx + my*my + mz*mz); if (mn > S_MAXMOVE) { double s = S_MAXMOVE / mn; mx *= s; my *= s; mz *= s; } }
    o_spos[i*3] = (float)(c0x + mx); o_spos[i*3+1] = (float)(c0y + my); o_spos[i*3+2] = (float)(c0z + mz);
    o_norm[i*3] = planar ? (float)nrm[0] : 0.0f; o_norm[i*3+1] = planar ? (float)nrm[1] : 0.0f; o_norm[i*3+2] = planar ? (float)nrm[2] : 0.0f;
    o_resid[i] = (float)sqrt(fmax(lam, 0.0));
    int cnt = nv - 1;
    double md = mdsum / (double)(cnt > 1 ? cnt : 1);
    o_md[i] = (float)md; o_cnt[i] = cnt;
    if (cnt > 0) { atomicAdd(&stats[0], md); atomicAdd(&stats[1], md*md); atomicAdd(&stats[2], 1.0); }
}
// Write the results back, flag outliers, per-voxel roughness (max of the batch).
extern "C" __global__ void k_sm_b(
    MapDims d, const int* __restrict__ list, int K, const float* __restrict__ o_spos, const float* __restrict__ o_norm,
    const float* __restrict__ o_resid, const float* __restrict__ o_md, const int* __restrict__ o_cnt, const double* __restrict__ stats,
    float* spos, float* pnorm, float* presid, unsigned char* phid, int* pver, const float* __restrict__ praw, float* vtmp)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= K) return;
    int id = list[i];
    double nh = stats[2], mu = 0, sd = 0;
    if (nh > 0) { mu = stats[0] / nh; double var = stats[1] / nh - mu*mu; sd = sqrt(var > 0 ? var : 0); }
    bool outlier = (o_cnt[i] < 3) || ((double)o_md[i] > mu + 3.0 * sd);
    for (int k = 0; k < 3; k++) { spos[id*3+k] = o_spos[i*3+k]; pnorm[id*3+k] = o_norm[i*3+k]; }
    presid[id] = o_resid[i]; phid[id] = outlier ? 1 : 0; pver[id] += 1;
    int v = vox_of(d, praw[id*3], praw[id*3+1], praw[id*3+2]);
    if (v >= 0) atomic_max_f(&vtmp[v], o_resid[i]);
}
extern "C" __global__ void k_sm_c(MapDims d, const int* __restrict__ list, int K, const float* __restrict__ praw, float* vres, float* vtmp) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= K) return;
    int id = list[i];
    int v = vox_of(d, praw[id*3], praw[id*3+1], praw[id*3+2]);
    if (v >= 0) vres[v] = vtmp[v];
}
extern "C" __global__ void k_sm_d(MapDims d, const int* __restrict__ list, int K, const float* __restrict__ praw, float* vtmp) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= K) return;
    int id = list[i];
    int v = vox_of(d, praw[id*3], praw[id*3+1], praw[id*3+2]);
    if (v >= 0) vtmp[v] = 0.0f;
}
extern "C" __global__ void k_redirty(int npts, const unsigned char* __restrict__ phid, unsigned char* pdirty) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < npts && phid[i]) pdirty[i] = 1;
}
