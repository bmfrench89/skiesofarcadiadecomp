/*
 * gxv: the GPU spike's Vulkan backend (specs/gpu-backend.md V3a). A
 * GxrBackend (runtime/gxr_cmd.h) that draws the renderer's commands into an
 * EFB of its own, headless: no window, no swapchain, a screen copy read back
 * and handed to gxr_backend_screen.
 *
 * V3a draws geometry only: the vertex stage of 3.3 (the CPU's own clipping,
 * the depth varying, invariant positions), the CPU's culling, scissor, depth
 * test and write masks, and the vertex colour. A draw that needs more -- a
 * TEV shape other than the vertex colour, an alpha test that can reject,
 * blending, a logic op, fog -- or a copy to a texture is refused: the backend
 * says which, and the renderer stops the run, rather than drawing it wrong.
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

/* For the self test: called with each draw's vertices as they were uploaded,
 * after any rebuild, and whether the draw was rebuilt. */
typedef void (*GxvUploadHook)(const DrawCmd* D, const Vertex* up, unsigned n, int rebuilt);
void gxv_set_upload_hook(GxvUploadHook h);
/* The self test's mutations, which must make it fail: "unclipped" uploads
 * every draw as it is, a vertex outside the clip volume or not. */
int gxv_set_mutation(const char* name);

#endif
