/*
 * gxv: the GPU spike's Vulkan backend (specs/gpu-backend.md V3a). A
 * GxrBackend (runtime/gxr_cmd.h) that draws the renderer's commands into an
 * EFB of its own, headless: no window, no swapchain, a screen copy read back
 * and handed to gxr_backend_screen.
 *
 * It draws (V3a, V4a): the vertex stage of 3.3 (the CPU's own clipping, the
 * depth varying, invariant positions), the CPU's culling, scissor, depth test
 * and write masks; the TEV with texture sampling, the alpha test and fog in
 * the fragment stage; and blending by 3.5's table. It copies (V3b): every EFB
 * copy, to a texture or the screen, is copy.comp, byte for byte the CPU's.
 * Logic ops are drawn one of three ways (V4b, gxv_set_logicop). A draw with
 * a constant alpha, or a logic op the chosen way cannot draw, is refused: the
 * backend says which, and the renderer stops the run, rather than drawing it
 * wrong.
 */
#ifndef SOA_GXV_H
#define SOA_GXV_H

#include "gxr_cmd.h"
#include <stddef.h>

/* Load the host's Vulkan (vulkan-1.dll, libvulkan.so.1) and set everything up.
 * 1 on success; 0 with the reason in why -- no loader, no device, a missing
 * format -- which a caller reports as a skip, never as a pass. */
int gxv_init(char* why, size_t cap);
const GxrBackend* gxv_backend(void);
const char* gxv_device_name(void);
/* What ran: draws, the draws rebuilt by clipping, vertices uploaded,
 * submissions, and the GPU's own time for them (timestamp queries). */
void gxv_report(void);
void gxv_shutdown(void);

/* The TEV (V3b's tevdiff): a TevSetup packed as tev.glsl reads it, and n
 * of them run through tevdiff.comp. inputs is ten words a case -- the two
 * raster colours, then the texel each of the eight maps gives -- and results
 * two: the RGBA bytes and whether the alpha test passed. */
#define GXV_TEV_WORDS (18 + 16 * 5)
void gxv_pack_tev(const TevSetup* T, uint32_t* out);
int gxv_tev_run(const uint32_t* setups, const uint32_t* inputs, uint32_t* results, unsigned n);

/* For copydiff: the GPU's EFB set to these 640x528 RGBA pixels, and the
 * decoded image of the last copy to a texture. */
int gxv_load_efb(const uint8_t* rgba);
const uint8_t* gxv_last_copy_image(unsigned* w, unsigned* h);
/* The depth buffer as 24-bit values, 640x528, row by row. */
int gxv_read_depth(uint32_t* out);

/* For the self test: called with each draw's vertices as they were uploaded,
 * after any rebuild, and whether the draw was rebuilt. */
typedef void (*GxvUploadHook)(const DrawCmd* D, const Vertex* up, unsigned n, int rebuilt);
void gxv_set_upload_hook(GxvUploadHook h);
/* The self test's mutations, each of which must make it fail: "unclipped"
 * uploads every draw as it is, a vertex outside the clip volume or not;
 * "unseeded" writes a copy's buffer back without first reading RAM into it;
 * "rounding" rounds the copy filter where the C truncates; "intensity"
 * rounds the intensity where the C truncates; "clamp" swaps tev.glsl's two
 * clamps; "alpha", "lod" and "fog" are raster.frag with the alpha test off,
 * the level of detail one higher and fog off; "nofilter" is the screen copy
 * unfiltered; "skip-draw:N" leaves out draw N; "noinvariant" drops
 * `invariant gl_Position`; "logic-copy", "and-copy", "or-copy" and "or-and"
 * draw every logic op, the AND, the ORs as copies, or swap OR and AND;
 * "skip-copies" leaves copies to a texture out, and "dest+32" writes them 32
 * bytes on. "measure" changes no pixel: it counts each draw's samples and
 * reports the five largest. Set before the first draw or copy. */
int gxv_set_mutation(const char* name);
/* How logic ops are drawn (3.5, V4b): "native", Vulkan's logicOp, the default
 * where the device has it; "blend", OR and AND as blends; "snapshot", the EFB
 * copied out before the draw and the op done in the shader, the default
 * otherwise. Set after gxv_init and before the first draw. */
int gxv_set_logicop(const char* mode);

#endif
