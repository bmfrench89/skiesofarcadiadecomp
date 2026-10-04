// The presenter's vertex stage (specs/gpu-backend.md V8): one triangle that
// covers the whole target, so the fragment stage sees every pixel once.
#version 450

void main()
{
    vec2 p = vec2(float((gl_VertexIndex << 1) & 2), float(gl_VertexIndex & 2));
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
