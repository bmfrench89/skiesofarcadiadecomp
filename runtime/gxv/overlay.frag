// The menu over the presented picture (M8b, docs/specs/menu.md): the
// overlay the window drew on the CPU, one B G R A word a pixel of the target,
// blended over the present pass's picture (the pipeline's alpha blend).
#version 450

layout(std430, binding = 0) readonly buffer Overlay { uint px[]; };

layout(push_constant) uniform Push { int w; } pc;

layout(location = 0) out vec4 colour;

void main()
{
    ivec2 at = ivec2(gl_FragCoord.xy);
    uint v = px[at.y * pc.w + at.x];
#ifdef GXV_MUTATE_OVERLAY
    v |= 0xFF000000u; // every pixel opaque: the picture under the panel lost
#endif
    colour = vec4(float((v >> 16) & 255u), float((v >> 8) & 255u), float(v & 255u), float(v >> 24)) / 255.0;
}
