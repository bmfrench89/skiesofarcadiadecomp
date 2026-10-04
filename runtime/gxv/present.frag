// The presenter's fragment stage (specs/gpu-backend.md V8): picture_scale
// (runtime/picture.c) as a shader. The screen copy, w x h RGBA words in the
// screen buffer from `at`, goes into the target at the rectangle
// picture_layout chose, nearest neighbour by the same integer arithmetic --
// source column x * w / rect.w, row y * h / rect.h -- and black outside it,
// so the picture is picture_scale's, pixel for pixel. The target is UNORM:
// each byte comes out as it went in.
//
// A screen copy at the EFB's scale (V9a) sets `area`: along a side where the
// copy is larger than the rectangle, each target pixel is instead the mean
// of its footprint, [x * w, (x + 1) * w) in units of 1 / rect.w, every
// source column weighted by its exact overlap -- picture_scale_area's
// integer arithmetic, so the picture is that function's, pixel for pixel.
#version 450

layout(std430, set = 0, binding = 0) readonly buffer Screen { uint screen[]; };

layout(push_constant) uniform Present {
    int rx, ry, rw, rh; // the rectangle in the target
    uint w, h;          // the screen copy's size
    uint at;            // its first word in the buffer
    uint area;          // 1: averaged along a side it shrinks on (V9a)
} pc;

layout(location = 0) out vec4 colour;

// The source columns (or rows) target column x covers: the first, the last,
// and whether they are weighted by overlap (else the nearest, weight 1).
uvec3 footprint(uint x, uint s, uint r)
{
    if (pc.area == 0u || s <= r) {
        uint n = x * s / r;
        if (n >= s) n = s - 1u;
        return uvec3(n, n, 0u);
    }
    return uvec3(x * s / r, ((x + 1u) * s - 1u) / r, 1u);
}

// Source column c's share of target column x, in units of 1 / r.
uint overlap(uint c, uint x, uint s, uint r, uint weighted)
{
    if (weighted == 0u) return 1u;
    return min((c + 1u) * r, (x + 1u) * s) - max(c * r, x * s);
}

void main()
{
    int x = int(gl_FragCoord.x) - pc.rx, y = int(gl_FragCoord.y) - pc.ry;
    if (x < 0 || y < 0 || x >= pc.rw || y >= pc.rh) {
        colour = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
#ifdef GXV_MUTATE_PRESENT
    x += 1; // the presenter's mutation: one column over
#endif
    if (pc.area == 0u) {
        uint sx = uint(x) * pc.w / uint(pc.rw), sy = uint(y) * pc.h / uint(pc.rh);
        if (sx >= pc.w) sx = pc.w - 1u;
        uint v = screen[pc.at + sy * pc.w + sx];
        colour = vec4(float(v & 255u), float((v >> 8) & 255u), float((v >> 16) & 255u), 255.0) / 255.0;
        return;
    }
    uvec3 fx = footprint(uint(x), pc.w, uint(pc.rw)), fy = footprint(uint(y), pc.h, uint(pc.rh));
    uvec3 sum = uvec3(0u);
    uint total = 0u;
    for (uint r = fy.x; r <= fy.y; r++) {
        uint wy = overlap(r, uint(y), pc.h, uint(pc.rh), fy.z);
        for (uint c = fx.x; c <= fx.y; c++) {
            uint wgt = wy * overlap(c, uint(x), pc.w, uint(pc.rw), fx.z), v = screen[pc.at + r * pc.w + c];
            sum += wgt * uvec3(v & 255u, (v >> 8) & 255u, (v >> 16) & 255u);
            total += wgt;
        }
    }
    uvec3 o = (sum + total / 2u) / total;
    colour = vec4(vec3(o), 255.0) / 255.0;
}
