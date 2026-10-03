// The level of detail, included by raster.frag and loddiff.comp so that
// loddiff (specs/gpu-backend.md V5) holds the fragment stage's own code
// against gxr's: span_lod's formula on a pixel's derivatives, and the level
// sample() reads with s and t scaled to its texels (gxr_tev.c's SAMPLE_AT).

// span_lod's formula. dx and dy are s's and t's screen derivatives, q the
// coordinate's q (1 where it is 0), sc_s and sc_t the map's scales.
float gx_lod(vec2 dx, vec2 dy, float q, float sc_s, float sc_t)
{
    float dsdx = dx.x / q * sc_s, dsdy = dy.x / q * sc_s, dtdx = dx.y / q * sc_t, dtdy = dy.y / q * sc_t;
#ifdef GXV_MUTATE_LODMIN
    float f = min(dsdx * dsdx + dtdx * dtdx, dsdy * dsdy + dtdy * dtdy);
#else
    float f = max(dsdx * dsdx + dtdx * dtdx, dsdy * dsdy + dtdy * dtdy);
#endif
    return f <= 1e-12 ? -16.0 : 0.5 * log2(f);
}

// SAMPLE_AT's level: the level of detail biased, clamped and rounded, within
// the levels there are; 0 where the map has no mipmaps.
int gx_level(float lod, float bias, float min_lod, float max_lod, int nlevels, bool mip)
{
    if (!mip || nlevels <= 1) return 0;
#ifdef GXV_MUTATE_LOD
    float L = lod + bias + 1.0;
#else
    float L = lod + bias;
#endif
    if (L < min_lod) L = min_lod;
    if (L > max_lod) L = max_lod;
    int l = int(L + 0.5);
    if (l >= nlevels) l = nlevels - 1;
    if (l < 0) l = 0;
    return l;
}

// a / d for a texture side d, rounded to nearest even as C's division is.
// Vulkan lets a GPU's division be 2.5 ULP out, and on this machine's GPU it
// was one ULP out in 5% of loddiff's cases with a side that is not a power
// of two. A power of two is a scaling, exact; any other side is divided out
// of a's 24-bit significand in integers, a bit at a time.
float gx_div_side(float a, int d)
{
    if ((d & (d - 1)) == 0) return ldexp(a, -findMSB(d));
    if (a == 0.0) return a;
    int e;
    float fm = frexp(abs(a), e);
    uint m = uint(ldexp(fm, 24)), D = uint(d);
    uint q = m / D, r = m - q * D;
    int k = 0;
    while (q < (1u << 24)) { // 25 bits: 24 to keep and a guard bit
        r <<= 1;
        q <<= 1;
        if (r >= D) {
            q |= 1u;
            r -= D;
        }
        k++;
    }
    uint keep = q >> 1;
    if ((q & 1u) != 0u && (r != 0u || (keep & 1u) != 0u)) keep++;
    float v = ldexp(float(keep), e - 24 - k + 1);
    return a < 0.0 ? -v : v;
}

// SAMPLE_AT's scale: s and t in level l's texels. su0 and sv0 are level 0's
// factors as the CPU keeps them; lw and lh are level l's size, w and h the
// texture's.
vec2 gx_level_uv(float s, float t, int l, float su0, float sv0, float sc_s, float sc_t, int lw, int lh, int w, int h)
{
    if (l == 0) return vec2(s * su0, t * sv0);
    return vec2(s * gx_div_side(sc_s * float(lw), w), t * gx_div_side(sc_t * float(lh), h));
}
