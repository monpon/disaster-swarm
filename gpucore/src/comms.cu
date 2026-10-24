// Radio propagation: SNR of many links in one kernel. A link's loss is free-space loss plus, for every run
// of solid material the straight segment crosses, a loss set by the run's dominant material and its thickness
// (plus a small charge per sample of unexplored interior when predicting through the master's own map).
#define COMMS_STEP 0.5f
#define TX_DBM 20.0f
#define NOISE_DBM (-92.0f)
#define THICK_DB 3.0f
#define UNKNOWN_DB 0.2f

// mode 0: the true world (padded material volume); mode 1: the master's map (log-odds + classified material + interior mask)
extern "C" __global__ void k_snr(
    int mode, const unsigned char* __restrict__ world, int wx, int wy, int wz, int pad,
    MapDims d, const int* __restrict__ lo, const unsigned char* __restrict__ mat, const unsigned char* __restrict__ interior,
    const float* __restrict__ a, const float* __restrict__ b, int P, const float* __restrict__ per_mat, int nmat,
    float* __restrict__ out)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= P) return;
    float ax = a[i*3], ay = a[i*3+1], az = a[i*3+2];
    float dx = b[i*3] - ax, dy = b[i*3+1] - ay, dz = b[i*3+2] - az;
    float dist = sqrtf(dx*dx + dy*dy + dz*dz);
    int n = (int)floorf(dist / COMMS_STEP); if (n < 1) n = 1;
    int cnt[16];
    bool in_run = false; int runlen = 0; float loss = 0.0f; int unk = 0;
    for (int k = 0; k <= n; k++) {
        bool occ = false, u = false; int m = 0;
        if (k < n) {
            float t = ((float)k + 0.5f) / (float)n;
            float x = ax + dx*t, y = ay + dy*t, z = az + dz*t;
            if (mode == 0) {
                long long ix = (long long)floorf(x) + pad, iy = (long long)floorf(y) + pad, iz = (long long)floorf(z) + pad;
                if (ix >= 0 && iy >= 0 && iz >= 0 && ix < wx && iy < wy && iz < wz) {
                    m = (int)world[(ix * wy + iy) * wz + iz]; occ = m != 0;
                }
            } else {
                int v = vox_of(d, x, y, z);
                if (v >= 0) {
                    int l = lo[v]; occ = l >= 4; m = (int)mat[v];
                    u = interior[v] && l > -3 && l < 4;
                }
            }
            if (u) unk++;
        }
        if (occ) {
            if (!in_run) { in_run = true; runlen = 0; for (int q = 0; q < 16; q++) cnt[q] = 0; }
            cnt[m & 15]++; runlen++;
        } else if (in_run) {
            int major = 0, best = cnt[0];
            for (int q = 1; q < nmat; q++) if (cnt[q] > best) { best = cnt[q]; major = q; }
            float len = (float)runlen * COMMS_STEP;
            loss += per_mat[major] + THICK_DB * fmaxf(0.0f, len - 1.5f);
            in_run = false;
        }
    }
    loss += UNKNOWN_DB * (float)unk;
    float pl = 40.0f + 20.0f * log10f(fmaxf(dist, 1.0f));
    out[i] = TX_DBM - pl - loss - NOISE_DBM;
}
