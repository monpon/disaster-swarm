// What the viewer needs, compacted on the device: changed voxels, changed points, re-scanned surfaces.

extern "C" __global__ void k_vox_collect(int n, int tick, const int* __restrict__ stamp, int* list, int* cnt) {
    int v = blockIdx.x * blockDim.x + threadIdx.x;
    if (v < n && stamp[v] > tick) { int k = atomicAdd(cnt, 1); list[k] = v; }
}
extern "C" __global__ void k_vox_pack(const int* __restrict__ list, int K, const int* __restrict__ lo, const float* __restrict__ csum,
    const int* __restrict__ cnt, const unsigned char* __restrict__ mat, const float* __restrict__ quality,
    unsigned char* o_occ, unsigned char* o_mat, unsigned short* o_rgb, unsigned char* o_q)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= K) return;
    int v = list[i];
    o_occ[i] = lo[v] >= 4 ? 1 : 0;
    o_mat[i] = mat[v];
    float c = fmaxf((float)cnt[v], 1.0f);
    int r = (int)fminf(fmaxf(csum[v*3] / c, 0.0f), 255.0f), g = (int)fminf(fmaxf(csum[v*3+1] / c, 0.0f), 255.0f), b = (int)fminf(fmaxf(csum[v*3+2] / c, 0.0f), 255.0f);
    o_rgb[i] = (unsigned short)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
    o_q[i] = (unsigned char)rintf(quality[v] * 255.0f);
}

// ---- point updates
extern "C" __global__ void k_pt_cand(int npts, int full, const int* __restrict__ pver, int* sent_ver, int* cand, int* cnt, int cap) {
    int id = blockIdx.x * blockDim.x + threadIdx.x;
    if (id >= npts) return;
    if (full) sent_ver[id] = -1;
    if (sent_ver[id] != pver[id]) { int k = atomicAdd(cnt, 1); if (k < cap) cand[k] = id; else atomicSub(cnt, 1); }
}
__device__ __forceinline__ bool pt_hidden(const unsigned char* phid, const int* pmiss, const int* nview, int id) {
    return phid[id] > 0 || (pmiss[id] >= 3 && pmiss[id] > nview[id]);
}
extern "C" __global__ void k_pt_decide(const int* __restrict__ cand, int K, const int* __restrict__ pver, int* sent_ver,
    const float* __restrict__ praw, const float* __restrict__ spos, const float* __restrict__ sent_raw, const float* __restrict__ sent_sm,
    const unsigned char* __restrict__ sent_hid, const unsigned char* __restrict__ phid, const int* __restrict__ pmiss, const int* __restrict__ nview,
    float min_move, int* upd, int* ucnt, int ucap)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= K) return;
    int id = cand[i];
    bool hid = pt_hidden(phid, pmiss, nview, id);
    bool moved = sent_ver[id] < 0 || (hid != (sent_hid[id] != 0));
    for (int k = 0; k < 3 && !moved; k++)
        if (fabsf(praw[id*3+k] - sent_raw[id*3+k]) > min_move || fabsf(spos[id*3+k] - sent_sm[id*3+k]) > min_move) moved = true;
    if (!moved) { sent_ver[id] = pver[id]; return; }   // nothing a viewer could see: considered synced
    int k = atomicAdd(ucnt, 1);
    if (k < ucap) upd[k] = id; else atomicSub(ucnt, 1);
}
extern "C" __global__ void k_pt_pack(MapDims d, const int* __restrict__ upd, int K, const int* __restrict__ pver, int* sent_ver,
    const float* __restrict__ praw, const float* __restrict__ spos, float* sent_raw, float* sent_sm, unsigned char* sent_hid,
    const unsigned char* __restrict__ phid, const int* __restrict__ pmiss, const int* __restrict__ nview,
    const unsigned char* __restrict__ pcol, const float* __restrict__ presid, const int* __restrict__ npass_vox,
    unsigned int* o_id, unsigned short* o_raw, unsigned short* o_sm, unsigned char* o_col, unsigned char* o_flag, unsigned char* o_resid, unsigned char* o_npass)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= K) return;
    int id = upd[i];
    bool hid = pt_hidden(phid, pmiss, nview, id);
    sent_ver[id] = pver[id]; sent_hid[id] = hid ? 1 : 0;
    o_id[i] = (unsigned int)id;
    for (int k = 0; k < 3; k++) {
        sent_raw[id*3+k] = praw[id*3+k]; sent_sm[id*3+k] = spos[id*3+k];
        o_raw[i*3+k] = (unsigned short)fminf(fmaxf(rintf(praw[id*3+k] / 0.05f), 0.0f), 65535.0f);
        o_sm[i*3+k] = (unsigned short)fminf(fmaxf(rintf(fminf(fmaxf(spos[id*3+k], 0.0f), 3200.0f) / 0.05f), 0.0f), 65535.0f);
        o_col[i*3+k] = pcol[id*3+k];
    }
    int conf = min(nview[id] / 2, 3);
    o_flag[i] = (unsigned char)((hid ? 1 : 0) | (conf << 1));
    o_resid[i] = (unsigned char)fminf(rintf(presid[id] * 255.0f), 255.0f);
    int v = vox_of(d, praw[id*3], praw[id*3+1], praw[id*3+2]);
    o_npass[i] = (unsigned char)(v >= 0 ? min(npass_vox[v], 255) : 0);
}

// ---- scan times of re-scanned surfaces
extern "C" __global__ void k_seen_collect(int n, int full, const float* __restrict__ seen, float* seen_sent, const int* __restrict__ lo,
    int* list, unsigned short* tlist, int* cnt)
{
    int v = blockIdx.x * blockDim.x + threadIdx.x;
    if (v >= n) return;
    float s = seen[v];
    bool changed = full ? (s >= 0.0f) : (s != seen_sent[v]);
    if (changed && lo[v] >= 4) {
        int k = atomicAdd(cnt, 1);
        list[k] = v;
        tlist[k] = (unsigned short)fminf(rintf(s * 2.0f) + 1.0f, 65535.0f);
    }
    if (!full) seen_sent[v] = s;
}
