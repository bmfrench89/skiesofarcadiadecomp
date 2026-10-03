// The EFB pass's fragment stage as V3a has it: the vertex colour only, which
// is the TEV shape the geometry checks draw with (one stage, RASC and RASA;
// tev_prepare's fast_c 1, fast_a 2). V4a puts tev.glsl, which V3b's tevdiff
// holds exact against tev_pixel, in its place.
#version 450

layout(location = 0) noperspective in float i_depth;
layout(location = 1) in vec4 i_col0;

layout(location = 0) out vec4 o_color;

void main()
{
    // The CPU's colour: perspective-correct, then int(c * 255 + 0.5), which
    // truncates, clamped to 0..255 (raster_triangle).
    ivec4 c = clamp(ivec4(i_col0 * 255.0 + 0.5), ivec4(0), ivec4(255));
    o_color = vec4(c) / 255.0;
    // Depth quantised as depth_test does (truncating to 24 bits), stored as
    // zq * 2^-24, which D32_SFLOAT holds exactly: the compare is then the
    // CPU's compare of the same integers.
    gl_FragDepth = float(uint(clamp(i_depth, 0.0, 1.0) * 16777215.0)) / 16777216.0;
}
