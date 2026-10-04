// The EFB pass's vertex stage (specs/gpu-backend.md 3.3): the CPU renderer's
// screen mapping, from clip-space vertices the consumer has already clipped
// with the renderer's own functions.
//
// Vertex pulling: the frame's Vertex records (runtime/gxr.h) as they are, 39
// floats each -- x, y, z, w; sx, sy; depth; col[2] (r, g, b, a); tex[8][3] --
// in one storage buffer, so there is no vertex input state to get wrong.
#version 450

layout(std430, set = 0, binding = 0) readonly buffer Verts { float v[]; };

// RasterCfg's viewport with its offsets applied, where this draw's first
// vertex is in the buffer (in vertices), and its record (raster.frag's).
layout(push_constant) uniform Draw {
    float wd, ht, xorig, yorig, zrange, farz;
    uint base;
    uint record;
} pc;

// The game draws the same vertices more than once under different TEV and
// blend states and relies on LEQUAL ties; every pipeline must place them alike.
// GXV_MUTATE_NOINVARIANT drops the qualifier, for V4a's finding on whether
// this GPU needs it.
#ifndef GXV_MUTATE_NOINVARIANT
invariant gl_Position;
#endif

// A point's size in samples: S at the EFB's scale (V9a), where the device
// has largePoints, so a native pixel's centre is covered as the CPU covers it.
layout(constant_id = 0) const float POINT_SIZE = 1.0;

layout(location = 0) noperspective out float o_depth;
layout(location = 1) out vec4 o_col0;
layout(location = 2) out vec4 o_col1;
layout(location = 3) out vec4 o_tex[8]; // s, t, q; perspective-correct, as the CPU's planes of value/w

void main()
{
    uint o = (pc.base + uint(gl_VertexIndex)) * 39u;
    float x = v[o], y = v[o + 1u], z = v[o + 2u], w = v[o + 3u];
    // The GPU's divide and the full 640x528 viewport turn this into the CPU's
    // sx = xorig + x/w*wd, sy = yorig + y/w*ht (to_screen). z is held at 0.5w,
    // inside the GPU's own depth clip volume, so the GPU never cuts what the
    // CPU keeps: depth travels in its own varying below.
    gl_Position = vec4(x * pc.wd / 320.0 + (pc.xorig / 320.0 - 1.0) * w,
                       y * pc.ht / 264.0 + (pc.yorig / 264.0 - 1.0) * w,
                       0.5 * w, w);
    // to_screen's depth, interpolated linearly in screen space as the CPU's
    // plane is, under precise so no multiply-add is fused.
    precise float iw = 1.0 / w;
    precise float d = (pc.farz + z * iw * pc.zrange) / 16777216.0;
    o_depth = d;
    o_col0 = vec4(v[o + 7u], v[o + 8u], v[o + 9u], v[o + 10u]);
    o_col1 = vec4(v[o + 11u], v[o + 12u], v[o + 13u], v[o + 14u]);
    for (uint k = 0u; k < 8u; k++) o_tex[k] = vec4(v[o + 15u + 3u * k], v[o + 16u + 3u * k], v[o + 17u + 3u * k], 0.0);
    gl_PointSize = POINT_SIZE;
}
