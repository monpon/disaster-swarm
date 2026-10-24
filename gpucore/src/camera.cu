// Camera: batched ray march through the true voxel world, toy-camera degradation, mono-depth stand-in.
// world: uint8 voxel materials padded by `pad` on every side (below ground = asphalt, elsewhere air).

__device__ __forceinline__ int mat_at(const unsigned char* world, int wx, int wy, int wz, int pad, float x, float y, float z) {
    long long ix = (long long)floorf(x) + pad, iy = (long long)floorf(y) + pad, iz = (long long)floorf(z) + pad;
    if (ix < 0 || iy < 0 || iz < 0 || ix >= wx || iy >= wy || iz >= wz) return 0;   // beyond the padded volume: air
    return (int)world[(ix * wy + iy) * wz + iz];
}

extern "C" __global__ void render(
    const unsigned char* __restrict__ world, int wx, int wy, int wz, int pad,
    const float* __restrict__ rays,      // (N,3) body-frame unit rays
    const float* __restrict__ steps, int ns, float step,
    const float* __restrict__ colors,    // (nmat,3)
    const float* __restrict__ poss,      // (M,3)
    const float* __restrict__ rots,      // (M,9) row-major
    int M, int N,
    float* __restrict__ depth_out,       // (M,N) metres, 0 = no return
    float* __restrict__ rgb_out)         // (M,N,3) floats, before degradation
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= M * N) return;
    int m = idx / N, n = idx % N;
    const float* R = rots + m * 9;
    float bx = rays[n*3], by = rays[n*3+1], bz = rays[n*3+2];
    // world-frame direction = R @ ray
    float dx = R[0]*bx + R[1]*by + R[2]*bz;
    float dy = R[3]*bx + R[4]*by + R[5]*bz;
    float dz = R[6]*bx + R[7]*by + R[8]*bz;
    float px = poss[m*3], py = poss[m*3+1], pz = poss[m*3+2];
    int first = -1;
    for (int k = 0; k < ns; k++) {
        float s = steps[k];
        if (mat_at(world, wx, wy, wz, pad, px + dx*s, py + dy*s, pz + dz*s) != 0) { first = k; break; }
    }
    bool hit = first >= 0;
    float* rgb = rgb_out + (long long)idx * 3;
    if (!hit) {
        depth_out[idx] = 0.0f;
        rgb[0] = 18.0f; rgb[1] = 22.0f; rgb[2] = 30.0f;
        return;
    }
    float depth = steps[first];
    float hx = px + dx*depth, hy = py + dy*depth, hz = pz + dz*depth;
    int hit_mat = mat_at(world, wx, wy, wz, pad, hx, hy, hz);
    // refine: if the half-step before the hit is already solid, the surface is closer
    float bd = depth - step * 0.5f;
    if (mat_at(world, wx, wy, wz, pad, px + dx*bd, py + dy*bd, pz + dz*bd) != 0) depth = bd;
    // which voxel face did the ray cross (for shading)
    float pd = steps[first > 0 ? first - 1 : 0]; if (pd < 0.0f) pd = 0.0f;
    int cx = (int)floorf(hx), cy = (int)floorf(hy), cz = (int)floorf(hz);
    int qx = (int)floorf(px + dx*pd), qy = (int)floorf(py + dy*pd), qz = (int)floorf(pz + dz*pd);
    float c0 = fabsf((float)(cx - qx)), c1 = fabsf((float)(cy - qy)), c2 = fabsf((float)(cz - qz));
    float ax = fabsf(dx), ay = fabsf(dy), az = fabsf(dz);
    int axis;
    if (c0 + c1 + c2 > 0.0f) {
        float v0 = c0*ax, v1 = c1*ay, v2 = c2*az;
        axis = 0; float best = v0; if (v1 > best) { axis = 1; best = v1; } if (v2 > best) { axis = 2; }
    } else {
        axis = 0; float best = ax; if (ay > best) { axis = 1; best = ay; } if (az > best) { axis = 2; }
    }
    float facing = axis == 0 ? ax : (axis == 1 ? ay : az);
    float shade = 0.8f + 0.2f * facing + ((axis == 2 && dz < 0.0f) ? 0.05f : 0.0f);
    rgb[0] = colors[hit_mat*3] * shade; rgb[1] = colors[hit_mat*3+1] * shade; rgb[2] = colors[hit_mat*3+2] * shade;
    depth_out[idx] = depth < 0.05f ? 0.05f : depth;
}

// Pass 1: motion blur (integer image shift by body rotation during the exposure) + sensor gain noise.
extern "C" __global__ void degrade_a(
    const float* __restrict__ rgb_in,    // (M,N,3)
    const float* __restrict__ omegas,    // (M,3) body rates rad/s
    const unsigned char* __restrict__ indoors,   // (M)
    int M, int W, int H, float px_per_rad, float exposure,
    float gain_out, float gain_in, unsigned long long seed,
    float* __restrict__ tmp)             // (M,N,3)
{
    int N = W * H;
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)M * N) return;
    int m = (int)(idx / N), n = (int)(idx % N);
    int y = n / W, x = n % W;
    int dx = (int)rintf(fabsf(omegas[m*3+2]) * exposure * px_per_rad);
    int dy = (int)rintf(fabsf(omegas[m*3+1]) * exposure * px_per_rad);
    const float* src = rgb_in + (long long)m * N * 3;
    float c[3];
    for (int k = 0; k < 3; k++) {
        float v = src[n*3+k];
        if (dx > 0 || dy > 0) {
            int y1 = ((y - dy) % H + H) % H, x1 = ((x - dx) % W + W) % W;
            int y2 = ((y - dy/2) % H + H) % H, x2 = ((x - dx/2) % W + W) % W;
            v = (v + src[(y1*W + x1)*3 + k] + src[(y2*W + x2)*3 + k]) / 3.0f;
        }
        c[k] = v;
    }
    float sigma = indoors[m] ? gain_in : gain_out;
    float g = 1.0f + sigma * nrand(seed, (unsigned long long)idx * 4ULL);
    for (int k = 0; k < 3; k++)
        tmp[idx*3 + k] = c[k] * g + nrand(seed, (unsigned long long)idx * 4ULL + 1ULL + k) * sigma * 60.0f;
}

// Pass 2: JPEG-like 2x2 chroma blend toward the block mean, quantise, write the uint8 frame into its slot.
extern "C" __global__ void degrade_b(
    const float* __restrict__ tmp, int M, int W, int H, float jpeg_step,
    const unsigned int* __restrict__ slots,
    unsigned char* __restrict__ frgb)    // (SLOTS,N,3)
{
    int N = W * H;
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)M * N) return;
    int m = (int)(idx / N), n = (int)(idx % N);
    int y = n / W, x = n % W;
    int hb = H - (H % 2), wb = W - (W % 2);
    const float* img = tmp + (long long)m * N * 3;
    for (int k = 0; k < 3; k++) {
        float v = img[n*3+k];
        if (y < hb && x < wb) {
            int y0 = y & ~1, x0 = x & ~1;
            float mean = (img[(y0*W+x0)*3+k] + img[(y0*W+x0+1)*3+k] + img[((y0+1)*W+x0)*3+k] + img[((y0+1)*W+x0+1)*3+k]) * 0.25f;
            v = 0.6f * v + 0.4f * mean;
        }
        v = rintf(v / jpeg_step) * jpeg_step;
        v = fminf(fmaxf(v, 0.0f), 255.0f);
        frgb[((long long)slots[m] * N + n) * 3 + k] = (unsigned char)v;
    }
}

// Monocular depth network stand-in on the true depth of B frames (reads slots, writes (B,N) estimates):
// 3x3 blend across depth edges, per-frame scale error, blocky 4x4 region errors, pixel noise.
extern "C" __global__ void depthnet(
    const float* __restrict__ fdepth, const unsigned int* __restrict__ slots, const unsigned char* __restrict__ thumb,
    int B, int W, int H, float scale_sigma, float region_sigma, float depth_max, unsigned long long seed,
    float* __restrict__ out)             // (B,N)
{
    int N = W * H;
    long long idx = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (long long)B * N) return;
    int b = (int)(idx / N), n = (int)(idx % N);
    int y = n / W, x = n % W;
    const float* d = fdepth + (long long)slots[b] * N;
    float dc = d[n];
    bool valid = dc > 0.0f;
    float q = thumb[b] ? 1.6f : 1.0f;
    if (!valid) { out[idx] = 0.0f; return; }
    float sum = 0.0f; int cnt = 0;
    for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++) {
        int yy = min(max(y + j, 0), H - 1), xx = min(max(x + i, 0), W - 1);   // replicate padding
        float v = d[yy * W + xx];
        if (v > 0.0f) { sum += v; cnt++; }
    }
    float blur = sum / (float)(cnt > 0 ? cnt : 1);
    float dd = 0.75f * dc + 0.25f * blur;
    float scale = expf(nrand(seed, (unsigned long long)b * 7919ULL + 1ULL) * scale_sigma * q);
    int bw = (W + 3) / 4;
    float region = nrand(seed ^ 0x5bd1e995ULL, (unsigned long long)b * 65537ULL + (unsigned long long)((y / 4) * bw + (x / 4))) * region_sigma * q;
    float noise = nrand(seed ^ 0x27d4eb2fULL, (unsigned long long)idx) * 0.02f;
    float est = dd * scale * (1.0f + region + noise);
    out[idx] = (est > 0.1f && est < depth_max) ? est : 0.0f;
}
