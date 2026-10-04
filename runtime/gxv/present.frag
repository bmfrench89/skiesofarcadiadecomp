// The presenter's fragment stage (specs/gpu-backend.md V8): picture_scale
// (runtime/picture.c) as a shader. The screen copy, w x h RGBA words in the
// screen buffer from `at`, goes into the target at the rectangle
// picture_layout chose, nearest neighbour by the same integer arithmetic --
// source column x * w / rect.w, row y * h / rect.h -- and black outside it,
// so the picture is picture_scale's, pixel for pixel. The target is UNORM:
// each byte comes out as it went in.
#version 450

layout(std430, set = 0, binding = 0) readonly buffer Screen { uint screen[]; };

layout(push_constant) uniform Present {
    int rx, ry, rw, rh; // the rectangle in the target
    uint w, h;          // the screen copy's size
    uint at;            // its first word in the buffer
} pc;

layout(location = 0) out vec4 colour;

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
    uint sx = uint(x) * pc.w / uint(pc.rw), sy = uint(y) * pc.h / uint(pc.rh);
    if (sx >= pc.w) sx = pc.w - 1u;
    uint v = screen[pc.at + sy * pc.w + sx];
    colour = vec4(float(v & 255u), float((v >> 8) & 255u), float((v >> 16) & 255u), 255.0) / 255.0;
}
