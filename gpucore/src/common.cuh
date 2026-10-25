// Shared device helpers: counter-based RNG (reproducible, no state), small vector math.
#define PI_F 3.14159265358979f

__device__ __forceinline__ unsigned int hash32(unsigned int x) {
    x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16; return x;
}
__device__ __forceinline__ float urand(unsigned long long seed, unsigned long long ctr) {
    unsigned int a = hash32((unsigned int)(seed) ^ hash32((unsigned int)(ctr)) ^ hash32((unsigned int)(ctr >> 32) + 0x9e3779b9U));
    unsigned int b = hash32(a + (unsigned int)(seed >> 32) + 0x85ebca6bU);
    return (float)((a ^ (b << 7)) >> 8) * (1.0f / 16777216.0f) + (0.5f / 16777216.0f);
}
// standard normal via Box-Muller, deterministic in (seed, ctr)
__device__ __forceinline__ float nrand(unsigned long long seed, unsigned long long ctr) {
    float u1 = urand(seed, ctr * 2ULL), u2 = urand(seed, ctr * 2ULL + 1ULL);
    return sqrtf(-2.0f * logf(u1)) * cosf(2.0f * PI_F * u2);
}

// signed-distance volume (filled by k_tsdf in mesh.cu, also the alignment target)
#define T_VOXEL 0.2f
#define T_MU 0.5f
#define T_MIN_W 0.015f   /* a single sighting of a surface is enough to mesh it */
struct TsdfDims { int nx, ny, nz, ncx, ncy, ncz; };
__device__ __forceinline__ long long tidx(const TsdfDims& t, int x, int y, int z) { return ((long long)x * t.ny + y) * t.nz + z; }

// Which pixels of a big frame take part in carving / surface fusion (1 in `s`). Hashed rather than `n % s`: with the
// frame width a multiple of s, `n % s` keeps the same image columns in every row and leaves vertical stripes of
// unobserved voxels between them.
__device__ __forceinline__ bool keep_pixel(int n, int s) {
    if (s <= 1) return true;
    unsigned h = (unsigned)n * 2654435761u; h ^= h >> 15; h *= 2246822519u; h ^= h >> 13;
    return (h % (unsigned)s) == 0;
}
