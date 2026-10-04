// The EFB pass's fragment stage (specs/gpu-backend.md 3.4): the TEV
// (tev.glsl, which tevdiff holds exact against tev_pixel) with texture
// sampling transcribed from gxr_tev.c's sample and sample_level, the level of
// detail from screen derivatives with span_lod's formula, the alpha test,
// fog as fog_apply does it, and depth quantised as depth_test compares it.
// Blending and the write masks are the pipeline's (3.5).
//
// A draw's record, gxv_draw_record's, GXV_DRAW_WORDS words at pc.record:
//   0-97     the TEV setup, gxv_pack_tev's (tev.glsl describes it)
//   98       ntex | nchan << 8 | miptex << 16: the texcoord slots
//            interpolated, the colour channels, the slots with mipmaps
//   99       texmap_of: the map each texcoord slot feeds, three bits a slot
//   100      fog: type | proj << 3 | b_shift << 8
//   101-104  fog: a, c (float bits), b_mag, colour (r | g << 8 | b << 16)
//   105      a logic op the shader draws: 1 | lop << 1 | mask << 5, or 0. Against
//            the EFB's snapshot; or, built with GXV_LOGIC_INTERLOCK (V10), against
//            the EFB itself, read and written in primitive order, the write
//            masks (colour 1, alpha 2) applied here, there being no attachment
//   106      the EFB's width in samples, S*640, the snapshot's stride (V9a)
//   107      the factor on the texture coordinates' derivatives (float bits):
//            1, or S for SOA_GPU_SCALE_LOD=native (V9a)
//   108-     twelve words for each of the eight maps:
//     0  the texture's record in the texture table, or ~0 for none
//     1  wrap_s | wrap_t << 2 | linear << 4 | mip << 5
//     2-8  lod_bias, min_lod, max_lod, scale_s, scale_t, su0, sv0 (float bits)
//     9-11 nlevels, w, h
// A texture's record, 34 words: each level's offset in the pool (in texels),
// then its width, then its height, eleven each; then the scale its texels are
// at, 0 or 1 for the game's own, S for a copy image at the EFB's scale (V9a),
// whose level 0 is S times the size its draw declares.
#version 450
#extension GL_GOOGLE_include_directive : require
#ifdef GXV_LOGIC_INTERLOCK
#extension GL_ARB_fragment_shader_interlock : require
layout(pixel_interlock_ordered) in;
#endif

layout(std430, set = 0, binding = 1) readonly buffer Draws { uint dw[]; };
layout(std430, set = 0, binding = 2) readonly buffer Pool { uint pool[]; };
layout(std430, set = 0, binding = 3) readonly buffer TexRecs { uint texrec[]; };
layout(std430, set = 0, binding = 4) readonly buffer Snapshot { uint snap[]; }; // the EFB before this draw, S*640 x S*528
#ifdef GXV_LOGIC_INTERLOCK
layout(set = 0, binding = 5, rgba8) uniform coherent image2D efb_image; // the EFB itself (V10)
#endif

layout(push_constant) uniform Draw {
    float wd, ht, xorig, yorig, zrange, farz;
    uint base;
    uint record;
} pc;

layout(location = 0) noperspective in float i_depth;
layout(location = 1) in vec4 i_col0;
layout(location = 2) in vec4 i_col1;
layout(location = 3) in vec4 i_tex[8];

#ifndef GXV_LOGIC_INTERLOCK
layout(location = 0) out vec4 o_color; // none for the interlock: its pass has no attachment
#endif

const uint DRAW_CHANNELS = 98u, DRAW_TEXMAP_OF = 99u, DRAW_FOG = 100u, DRAW_LOGIC = 105u, DRAW_STRIDE = 106u,
           DRAW_DERIV = 107u, DRAW_MAPS = 108u, MAP_WORDS = 12u, TEXREC_SCALE = 33u;
const uint NO_TEXTURE = 0xFFFFFFFFu;

vec3 g_tc[8];   // each texcoord slot's s, t, q at this pixel
float g_lod[8]; // and its level of detail

uint tev_word(uint i) { return dw[pc.record + i]; }
float rec_float(uint i) { return uintBitsToFloat(dw[pc.record + i]); }

// ---- sampling: gxr_tev.c's sample and sample_level -------------------------

#include "lod.glsl"

// C's division and remainder truncate toward zero; GLSL leaves % of a
// negative number undefined, so the remainder is built from the division.
int c_rem(int a, int b) { return a - b * (a / b); }

int fast_floor(float f)
{
    int i = int(f);
    return f < float(i) ? i - 1 : i;
}

int wrap_coord(int i, int size, int mask, uint mode)
{
    if (mode == 0u) return i < 0 ? 0 : (i >= size ? size - 1 : i);
    if (mode == 1u) {
        if (mask >= 0) return i & mask;
        i = c_rem(i, size);
        return i < 0 ? i + size : i;
    }
    int period = 2 * size;
    if (mask >= 0) {
        i &= period - 1;
        return i < size ? i : period - 1 - i;
    }
    i = c_rem(i, period);
    if (i < 0) i += period;
    return i < size ? i : period - 1 - i;
}

ivec4 unpack_rgba(uint v) { return ivec4(v & 255u, (v >> 8) & 255u, (v >> 16) & 255u, v >> 24); }

ivec4 texel(uint rec, int l, int w, int x, int y) { return unpack_rgba(pool[texrec[rec + uint(l)] + uint(y * w + x)]); }

ivec4 sample_level(uint rec, uint flags, int l, float u, float v)
{
    int w = int(texrec[rec + 11u + uint(l)]), h = int(texrec[rec + 22u + uint(l)]);
    int mask_s = (w & (w - 1)) == 0 ? w - 1 : -1, mask_t = (h & (h - 1)) == 0 ? h - 1 : -1;
    uint ws = flags & 3u, wt = (flags >> 2) & 3u;
    if ((flags & 16u) == 0u) {
        int x = wrap_coord(fast_floor(u), w, mask_s, ws), y = wrap_coord(fast_floor(v), h, mask_t, wt);
        return texel(rec, l, w, x, y);
    }
    float fu = u - 0.5, fv = v - 0.5;
    int x0 = fast_floor(fu), y0 = fast_floor(fv);
    int ax = int((fu - float(x0)) * 256.0), ay = int((fv - float(y0)) * 256.0);
    if (uint(ax) > 255u) ax = 0;
    if (uint(ay) > 255u) ay = 0;
    int xa = wrap_coord(x0, w, mask_s, ws), xb = wrap_coord(x0 + 1, w, mask_s, ws);
    int ya = wrap_coord(y0, h, mask_t, wt), yb = wrap_coord(y0 + 1, h, mask_t, wt);
    ivec4 top = texel(rec, l, w, xa, ya) * (256 - ax) + texel(rec, l, w, xb, ya) * ax;
    ivec4 bot = texel(rec, l, w, xa, yb) * (256 - ax) + texel(rec, l, w, xb, yb) * ax;
    return (top * (256 - ay) + bot * ay + 32768) >> 16;
}

ivec4 tex_sample(uint map, float s, float t, float lod)
{
    uint m = DRAW_MAPS + map * MAP_WORDS;
    uint rec = tev_word(m), flags = tev_word(m + 1u);
    int nlevels = int(tev_word(m + 9u)), w = int(tev_word(m + 10u)), h = int(tev_word(m + 11u));
    if (rec == NO_TEXTURE || w <= 0 || h <= 0) return ivec4(0);
    int l = gx_level(lod, rec_float(m + 2u), rec_float(m + 3u), rec_float(m + 4u), nlevels, (flags & 32u) != 0u);
    vec2 uv = gx_level_uv(s, t, l, rec_float(m + 7u), rec_float(m + 8u), rec_float(m + 5u), rec_float(m + 6u),
                          int(texrec[rec + 11u + uint(l)]), int(texrec[rec + 22u + uint(l)]), w, h);
    // A copy image at the EFB's scale (V9a): the game's texel coordinates,
    // in the S x S texels each of its own became.
    uint k = texrec[rec + TEXREC_SCALE];
#ifndef GXV_MUTATE_COPY_SCALE
    if (k > 1u) uv *= float(k);
#endif
    return sample_level(rec, flags, l, uv.x, uv.y);
}

// The texel a stage samples: its coordinate's s/q, t/q and level of detail,
// as tev_pixel divides them, through its map.
ivec4 tev_sample(uint map, uint coord)
{
    vec3 tc = g_tc[coord];
    float q = tc.z;
    float s = q != 0.0 ? tc.x / q : tc.x, t = q != 0.0 ? tc.y / q : tc.y;
    return tex_sample(map, s, t, g_lod[coord]);
}

#include "tev.glsl"

// ---- fog: fog_apply --------------------------------------------------------

ivec3 fogged(ivec3 c, uint zs)
{
    uint f0 = tev_word(DRAW_FOG);
    uint type = f0 & 7u;
#ifdef GXV_MUTATE_FOG
    type = 0u;
#endif
    if (type == 0u) return c;
    precise float ze, f;
    float a = rec_float(DRAW_FOG + 1u), cc = rec_float(DRAW_FOG + 2u);
    if (((f0 >> 3) & 1u) == 0u) {
        int denom = int(tev_word(DRAW_FOG + 3u)) - int(zs >> ((f0 >> 8) & 31u));
        if (denom == 0) return c;
        ze = (a * 16777215.0) / float(denom);
    } else {
        ze = a * (float(zs) / 16777215.0);
    }
    f = ze - cc;
    if (f < 0.0) f = 0.0;
    if (f > 1.0) f = 1.0;
    if (type == 2u) {
    } else if (type == 4u) {
        f = 1.0 - exp2(-8.0 * f);
    } else if (type == 5u) {
        f = 1.0 - exp2(-8.0 * f * f);
    } else if (type == 6u) {
        f = exp2(-8.0 * (1.0 - f));
    } else if (type == 7u) {
        f = exp2(-8.0 * (1.0 - f) * (1.0 - f));
    } else {
        return c;
    }
    int fi = min(int(f * 256.0), 256);
    uint col = tev_word(DRAW_FOG + 4u);
    ivec3 fc = ivec3(col & 255u, (col >> 8) & 255u, (col >> 16) & 255u);
    return (c * (256 - fi) + fc * fi) >> 8;
}

// blend_pixel's logic ops, on the RGB bytes; the alpha is the source's.
uvec3 logic_op(uint lop, uvec3 s, uvec3 d)
{
    switch (lop) {
    case 0u: return uvec3(0u);
    case 1u: return s & d;
    case 2u: return s & ~d;
    case 3u: return s;
    case 4u: return ~s & d;
    case 5u: return d;
    case 6u: return s ^ d;
    case 7u: return s | d;
    case 8u: return ~(s | d);
    case 9u: return ~(s ^ d);
    case 10u: return ~d;
    case 11u: return s | ~d;
    case 12u: return ~s;
    case 13u: return ~s | d;
    case 14u: return ~(s & d);
    default: return uvec3(255u);
    }
}

// The CPU's colour: perspective-correct, then int(c * 255 + 0.5), clamped.
ivec4 quantised(vec4 c) { return clamp(ivec4(c * 255.0 + 0.5), ivec4(0), ivec4(255)); }

void main()
{
    uint ch = tev_word(DRAW_CHANNELS), texmap_of = tev_word(DRAW_TEXMAP_OF);
    uint ntex = ch & 255u, nchan = (ch >> 8) & 3u, miptex = (ch >> 16) & 255u;
    uint i;
    float deriv = rec_float(DRAW_DERIV);
    // Every slot's derivatives, in uniform control flow; span_lod's formula on
    // them where the slot's map has mipmaps. The CPU evaluates it at a span's
    // two ends and interpolates; that difference is by design (3.4). At scale
    // they are the scaled pixel's, unless word 107 puts them back (V9a).
    for (i = 0u; i < 8u; i++) {
        vec4 tc = i_tex[i];
        vec2 dx = dFdxFine(tc.xy), dy = dFdyFine(tc.xy);
        if (deriv != 1.0) {
            dx *= deriv;
            dy *= deriv;
        }
        bool interpolated = ((ntex >> i) & 1u) != 0u;
        g_tc[i] = interpolated ? tc.xyz : vec3(0.0, 0.0, 1.0);
        g_lod[i] = 0.0;
        if (interpolated && ((miptex >> i) & 1u) != 0u) {
            uint m = DRAW_MAPS + ((texmap_of >> (3u * i)) & 7u) * MAP_WORDS;
            g_lod[i] = gx_lod(dx, dy, tc.z != 0.0 ? tc.z : 1.0, rec_float(m + 5u), rec_float(m + 6u));
        }
    }
    ivec4 ras0 = (nchan & 1u) != 0u ? quantised(i_col0) : ivec4(0);
    ivec4 ras1 = (nchan & 2u) != 0u ? quantised(i_col1) : ivec4(0);
    ivec4 outc;
    bool pass;
    tev_run(ras0, ras1, outc, pass);
#ifndef GXV_MUTATE_ALPHA
    if (!pass) discard;
#endif
    // The 24-bit z, truncated, as depth_test and fog_apply both take it.
    uint zs = uint(clamp(i_depth, 0.0, 1.0) * 16777215.0);
    outc.rgb = fogged(outc.rgb, zs);
    uint logic = tev_word(DRAW_LOGIC);
#ifdef GXV_LOGIC_INTERLOCK
    // V10: a logic op on a draw that may overlap itself. The EFB pixel is read
    // and written inside the interlock, so each fragment sees the ones before
    // it in primitive order, as the CPU's rows do. The pass has no attachments
    // (and no depth test: the route is taken only with it off).
    ivec2 at = ivec2(gl_FragCoord.xy);
    uint masks = (logic >> 5) & 3u;
    beginInvocationInterlockARB();
    uvec4 d = uvec4(imageLoad(efb_image, at) * 255.0 + 0.5);
    uvec4 o = d;
    if ((masks & 1u) != 0u) o.rgb = logic_op((logic >> 1) & 15u, uvec3(outc.rgb), d.rgb) & 255u;
    if ((masks & 2u) != 0u) o.a = uint(outc.a);
    imageStore(efb_image, at, vec4(o) / 255.0);
    endInvocationInterlockARB();
#else
    if ((logic & 1u) != 0u) {
        uvec4 d = uvec4(unpack_rgba(snap[uint(gl_FragCoord.y) * tev_word(DRAW_STRIDE) + uint(gl_FragCoord.x)]));
        outc.rgb = ivec3(logic_op((logic >> 1) & 15u, uvec3(outc.rgb), d.rgb) & 255u);
    }
    o_color = vec4(outc) / 255.0;
#endif
    gl_FragDepth = float(zs) / 16777216.0;
}
