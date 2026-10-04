/*
 * gxv: the Vulkan backend. See gxv.h for what it draws and what it refuses,
 * and specs/gpu-backend.md 3.2-3.3 for the design it follows.
 *
 * One queue, one command buffer, recorded as the renderer's commands arrive
 * and submitted when something must wait for the GPU: a screen copy, the
 * renderer's finish, or a full vertex ring. Every submission is waited for on
 * a fence before the next is recorded, so nothing here is ever in flight
 * behind the CPU's back (V5; V6 moves it to a thread of its own).
 *
 * Built two ways. With SOA_GXV=1 it is the backend, compiled against
 * Vulkan-Headers and the shaders in runtime/gxv/ as glslang made them
 * (tools/soa/shaders.py): tools/gpuspike.py always builds it so, and
 * recompile.py --link does when tools/fetch_gpu.py has filled vendor/.
 * Without it, it is the few lines at the end that say this build has no
 * backend, and need neither.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "gxv.h"
#include <stdio.h>

#if SOA_GXV
#define VK_NO_PROTOTYPES
#include "plat.h"
#include <vulkan/vulkan_core.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

#include "raster_vert.h"
#include "raster_vert_noinvariant.h"
#include "raster_frag.h"
#include "raster_frag_alpha.h"
#include "raster_frag_lod.h"
#include "raster_frag_fog.h"
#include "raster_frag_interlock.h"
#include "tevdiff_comp.h"
#include "tevdiff_comp_clamp.h"
#include "loddiff_comp.h"
#include "loddiff_comp_lod.h"
#include "loddiff_comp_lodmin.h"
#include "copy_comp.h"
#include "copy_comp_rounding.h"
#include "copy_comp_intensity.h"
#include "present_vert.h"
#include "present_frag.h"
#include "present_frag_offset.h"
#include "picture.h"

/* The shader reads a Vertex as 39 floats; gxr.h's layout is what it reads. */
typedef char gxv_vertex_is_39_floats[sizeof(Vertex) == 39 * sizeof(float) ? 1 : -1];

/* ---- the entry points, resolved at run time --------------------------- */

#define GXV_GLOBAL(X) X(vkCreateInstance) X(vkEnumerateInstanceLayerProperties) X(vkEnumerateInstanceExtensionProperties)
#define GXV_INSTANCE(X)                                                                                  \
    X(vkDestroyInstance) X(vkEnumeratePhysicalDevices) X(vkGetPhysicalDeviceProperties)                  \
    X(vkGetPhysicalDeviceQueueFamilyProperties) X(vkGetPhysicalDeviceMemoryProperties)                   \
    X(vkGetPhysicalDeviceFormatProperties) X(vkCreateDevice) X(vkGetDeviceProcAddr) X(vkEnumerateDeviceExtensionProperties)
#define GXV_DEVICE(X)                                                                                    \
    X(vkDestroyDevice) X(vkGetDeviceQueue) X(vkDeviceWaitIdle) X(vkCreateBuffer) X(vkDestroyBuffer)      \
    X(vkGetBufferMemoryRequirements) X(vkAllocateMemory) X(vkFreeMemory) X(vkBindBufferMemory)          \
    X(vkMapMemory) X(vkCreateImage) X(vkDestroyImage) X(vkGetImageMemoryRequirements)                   \
    X(vkBindImageMemory) X(vkCreateImageView) X(vkDestroyImageView) X(vkCreateRenderPass)               \
    X(vkDestroyRenderPass) X(vkCreateFramebuffer) X(vkDestroyFramebuffer) X(vkCreateShaderModule)        \
    X(vkDestroyShaderModule) X(vkCreateDescriptorSetLayout) X(vkDestroyDescriptorSetLayout)              \
    X(vkCreatePipelineLayout) X(vkDestroyPipelineLayout) X(vkCreateGraphicsPipelines)                    \
    X(vkDestroyPipeline) X(vkCreateDescriptorPool) X(vkDestroyDescriptorPool)                            \
    X(vkAllocateDescriptorSets) X(vkUpdateDescriptorSets) X(vkCreateCommandPool)                         \
    X(vkDestroyCommandPool) X(vkAllocateCommandBuffers) X(vkBeginCommandBuffer) X(vkEndCommandBuffer)    \
    X(vkCreateFence) X(vkDestroyFence) X(vkWaitForFences) X(vkResetFences) X(vkQueueSubmit)              \
    X(vkCreateQueryPool) X(vkDestroyQueryPool) X(vkGetQueryPoolResults) X(vkCmdResetQueryPool)           \
    X(vkCmdWriteTimestamp) X(vkCmdBeginRenderPass) X(vkCmdEndRenderPass) X(vkCmdBindPipeline)            \
    X(vkCmdBindDescriptorSets) X(vkCmdBindIndexBuffer) X(vkCmdPushConstants) X(vkCmdSetScissor) X(vkCmdSetViewport)          \
    X(vkCmdDraw) X(vkCmdDrawIndexed) X(vkCmdClearAttachments) X(vkCmdPipelineBarrier)                    \
    X(vkCmdCopyImageToBuffer) X(vkCmdClearColorImage) X(vkCmdClearDepthStencilImage)                    \
    X(vkCreateComputePipelines) X(vkCmdDispatch) X(vkCmdCopyBufferToImage) X(vkCmdBeginQuery) X(vkCmdEndQuery)    \
    X(vkCreatePipelineCache) X(vkDestroyPipelineCache) X(vkGetPipelineCacheData)

#define GXV_DECLARE(name) static PFN_##name name;
static PFN_vkGetInstanceProcAddr vkGetInstanceProcAddr;
GXV_GLOBAL(GXV_DECLARE)
GXV_INSTANCE(GXV_DECLARE)
GXV_DEVICE(GXV_DECLARE)

/* ---- state ---------------------------------------------------------------- */

#define RING_BYTES (32u << 20)     /* the vertex ring: about 215k vertices */
#define READBACK_BYTES (EFB_W * EFB_H * 4)
#define MAX_QUADS 16384            /* a draw's count is 16 bits: 65535 vertices */
#define ARENA_BYTES (64u << 20)    /* the bump allocator's blocks, eight at most a memory type */
#define ARENA_BLOCKS 8
#define DEST_BYTES (16u << 20)     /* a copy's bytes: 1024 rows of 1024 RGBA8 texels, at any stride */
#define IMAGE_BYTES (1024u * 1024u * 4u)
#define PIPE_SLOTS 4096           /* the pipeline cache: open addressing on the state key */
#define GXV_DRAW_WORDS 208        /* a draw's record (raster.frag describes it) */
#define DRAWREC_BYTES (16u << 20) /* the draw records: about 20,000 of them */
#define POOL_BYTES (128u << 20)   /* the texel pool, or the device's storage-buffer limit */
#define TEXREC_WORDS 33           /* a texture's record: eleven offsets, widths and heights */
#define TEXREC_BYTES (1u << 20)
#define NO_TEXTURE 0xFFFFFFFFu

enum { T_TRIS, T_STRIP, T_FAN, T_LINES, T_LSTRIP, T_POINTS };

typedef struct {
    VkDeviceMemory mem;
    VkDeviceSize used, size;
    uint8_t* map;
} Arena;

static void* g_lib;
static VkInstance g_inst;
static VkPhysicalDevice g_phys;
static VkDevice g_dev;
static VkQueue g_queue;
static uint32_t g_family;
static VkPhysicalDeviceProperties g_props;
static VkPhysicalDeviceMemoryProperties g_memprops;
static Arena g_arena[VK_MAX_MEMORY_TYPES][ARENA_BLOCKS];
static VkImage g_color, g_depth;
static VkImageView g_color_view, g_depth_view;
static VkRenderPass g_pass;
static VkFramebuffer g_fb;
static VkBuffer g_ring, g_quad_idx, g_readback, g_destbuf, g_imagebuf, g_screenbuf;
static uint8_t *g_ring_map, *g_readback_map, *g_dest_map, *g_image_map, *g_screen_map;
static uint32_t* g_quad_map;
static VkDescriptorSetLayout g_dsl;
static VkDescriptorPool g_dpool;
static VkDescriptorSet g_dset;
static VkPipelineLayout g_layout;
static VkShaderModule g_vs, g_fs;
/* A pipeline: the state's key and, specialised (V7), the TEV's shape --
 * the words tev.glsl's constants take, compared whole, never by a hash; the
 * interpreter's pipeline for a state has the shape all zero. `ready`
 * publishes `pipe`: 1 made, 0 compiling on the compiler thread, -1 failed.
 * Only the draw path (the consumer, or the producer inline) fills a slot;
 * the compiler thread writes a specialised slot's pipe and then its ready. */
#define TEV_SHAPE_WORDS (3 + 16 * 4)
static struct {
    uint32_t key; /* 0: free */
    uint32_t shape[TEV_SHAPE_WORDS];
    VkPipeline pipe;
    plat_a32 ready;
} g_pipes[PIPE_SLOTS];
/* SOA_GPU_SPECIALIZE: 1, the default, the shape as constants, compiled on a
 * thread of their own while the interpreter draws -- the same pixels, so the
 * switch cannot be seen; wait, compiled on the draw path, so that every draw
 * is drawn specialised (the check that they are the interpreter's pixels);
 * 0, the interpreter alone. */
enum { SPEC_OFF, SPEC_BACKGROUND, SPEC_WAIT };
static int g_specialize = -1;
static unsigned long long g_n_spec, g_n_interim;
static PlatLock g_queue_lock; /* the queue's submissions and presents (V8): the consumer's and the window's */
static int g_inst_surface, g_dev_swapchain; /* the surface extensions on the instance, the swap chain's on the device */
static int g_started; /* gxv_start succeeded: the renderer's backend */ /* specialised pipelines asked for; draws the interpreter drew meanwhile */
/* The distinct shapes seen, for the report: the pipelines should number a
 * few for each (V7's Done), not one for each draw. */
#define SHAPE_SLOTS 1024
static uint64_t g_shape_seen[SHAPE_SLOTS];
static unsigned g_n_shapes;
static VkBuffer g_drawbuf, g_poolbuf, g_texrecbuf;
static uint8_t *g_draw_map, *g_pool_map, *g_texrec_map;
static uint32_t g_draw_used, g_pool_used, g_pool_cap, g_texrec_used; /* words, texels, words */
/* Which textures the pool holds this submission: a cache slot's generation
 * and record, valid while its epoch is the current one. */
static struct {
    uint32_t gen, rec, epoch;
} g_resident[1024];
static uint32_t g_epoch = 1;
static VkCommandPool g_cpool;
static VkCommandBuffer g_cb;
static VkFence g_fence;
static VkQueryPool g_qpool;
static int g_timestamps, g_precise;

static int g_rec, g_inpass;      /* the command buffer is recording; the EFB pass is begun */
static VkPipeline g_bound;
static uint32_t g_ring_used;     /* bytes, a multiple of sizeof(Vertex) */
static Vertex* g_tmp;            /* a rebuilt draw, before it goes into the ring */
static unsigned g_tmp_cap;
static GxvUploadHook g_hook;
/* The mutations (gxv_set_mutation); 1 and 2 of g_mut_copy pick copy.comp's
 * rounding and intensity variants. */
static int g_mut_unclipped, g_mut_unseeded, g_mut_copy, g_mut_tev, g_mut_frag, g_mut_nofilter;
static unsigned long long g_skip_draw; /* the draw --mutate skip-draw:N leaves out, 1-based; 0 none */
static int g_mut_noinvariant, g_mut_lodmin, g_mut_pool_inplace, g_mut_late;
static int g_mut_spec_stages; /* --mutate spec-stages (V7): the specialised shape a stage short */
static int g_mut_compile_wait; /* --mutate compile-wait (V7): the draw path waits for the compiler thread */
/* --mutate late-readback (V6b): a copy's bytes put in guest RAM only when the
 * next command comes, after the consumer has counted the copy -- what 3.7's
 * "copies count only once their bytes are in guest RAM" forbids. */
static uint8_t *g_late_ram, *g_late_bytes;
static size_t g_late_n;
static void late_land(void)
{
    if (g_late_ram) memcpy(g_late_ram, g_late_bytes, g_late_n);
    g_late_ram = NULL;
}

/* Copies to a texture land late (V7, 3.6). Each is recorded into regions of
 * its own -- its bytes in g_destbuf, seeded from guest RAM; its decoded image
 * in g_imagebuf and in the texel pool -- and is counted as soon as it is
 * recorded. It lands, its bytes into guest RAM and its image into the
 * producer's copy image, when the submission it is in is done (land_all),
 * and gxr is told (gxr_backend_landed); every producer wait for what a copy
 * wrote waits for that. A draw later in the same submission that samples
 * the copy's image samples the pool's (g_cimg) with no wait at all. */
#define LAND_MAX 64
static struct {
    uint8_t* ram;      /* where its bytes go in guest RAM */
    uint32_t guest;    /* the same, as a masked guest address, for overlaps */
    uint32_t dest_at;  /* byte offset of its bytes in g_destbuf */
    uint32_t extent;   /* how many */
    uint8_t* image;    /* the producer's copy image, or NULL */
    uint32_t image_at; /* texel offset of its image in g_imagebuf */
    uint32_t texels;
} g_land[LAND_MAX];
static unsigned g_land_n;
static uint32_t g_dest_used, g_image_used; /* bytes and texels this submission's copies hold */
static struct {
    const uint8_t* cpu; /* the producer's copy image, which a draw's TexCfg names */
    uint32_t rec;       /* the pool's, in g_texrecbuf */
} g_cimg[LAND_MAX];
static unsigned g_cimg_n;
static long long g_seq_cur; /* every command below it has been run here */
static unsigned long long g_n_land_waits, g_n_cimg_served;
/* --mutate land-at-copy: every copy waited for and landed at the copy, as V6
 * did; --mutate cimg-cpu: a draw samples the producer's copy image, not yet
 * landed, instead of the pool's. */
static int g_mut_land_at_copy, g_mut_cimg_cpu;
static int g_mut_present; /* --mutate present (V8): present.frag one column over */
/* Logic ops (V4b): native (Vulkan's logicOp, where the device has it), blend
 * (OR and AND as blends, exact when an operand is 0 or 255, 3.5) or snapshot
 * (the EFB copied out before the draw and the op done in the shader). */
enum { LOGIC_NATIVE, LOGIC_BLEND, LOGIC_SNAPSHOT, LOGIC_INTERLOCK };
/* g_logic_mode: a route forced for every logic draw (SOA_GPU_LOGICOP,
 * gxv_set_logicop), or -1, each draw routed by logic_route (V10).
 * LOGIC_INTERLOCK (V10): the op done in the shader on the EFB itself, read
 * and written inside fragment-shader interlock, for a draw that may overlap
 * itself, where the device has VK_EXT_fragment_shader_interlock. */
static int g_logic_mode = -1, g_has_logicop, g_has_interlock;
static unsigned long long g_logic_routes[4];
static int g_core; /* SOA_GPU_FEATURES=core (3.10): every optional feature treated as absent */
/* Dynamic state (V7's budget; VK_EXT_extended_dynamic_state, where the device
 * has it): cull, the topology within its class and the depth test, write and
 * compare set by draw rather than built into the pipeline, so a state that
 * differs from one already made only in those needs no pipeline of its own --
 * which is what every draw-path stall of the cold soak was (FINDINGS "V7,
 * fifth"). SOA_GPU_EDS=0, or SOA_GPU_FEATURES=core, builds them in. g_dyn_*
 * are the values last set in this command buffer, -1 unknown. */
static int g_eds;
static int g_dyn_cull = -1, g_dyn_topo = -1, g_dyn_zen = -1, g_dyn_zupd = -1, g_dyn_zf = -1;
static PFN_vkCmdSetCullModeEXT p_vkCmdSetCullModeEXT;
static PFN_vkCmdSetPrimitiveTopologyEXT p_vkCmdSetPrimitiveTopologyEXT;
static PFN_vkCmdSetDepthTestEnableEXT p_vkCmdSetDepthTestEnableEXT;
static PFN_vkCmdSetDepthWriteEnableEXT p_vkCmdSetDepthWriteEnableEXT;
static PFN_vkCmdSetDepthCompareOpEXT p_vkCmdSetDepthCompareOpEXT;
static VkShaderModule g_fs_il;   /* raster.frag built with GXV_LOGIC_INTERLOCK */
static VkRenderPass g_pass_il;   /* the interlock route's pass: no attachments */
static VkFramebuffer g_fb_il;
/* The logic and copy mutations: every logic op drawn as a copy, the AND as
 * one, the ORs as ones, OR and AND swapped; copies to a texture skipped, or
 * written 32 bytes on. */
enum { MUT_LOGIC_NONE, MUT_LOGIC_COPY, MUT_AND_COPY, MUT_OR_COPY, MUT_OR_AND };
static int g_mut_logic, g_mut_skip_copies, g_mut_dest32;
static unsigned long long g_n_logic;
/* --mutate measure: an occlusion query around every draw, to find the
 * frame's largest -- the one the skip-draw mutation leaves out (V4a). */
#define OCC_QUERIES 16384
static int g_measure;
static VkQueryPool g_occ;
static unsigned g_occ_used;
static unsigned long long g_occ_draw[OCC_QUERIES];
/* The five draws that passed the most samples, most first. */
static unsigned long long g_top_draw[5], g_top_samples[5];
/* The consumer's own time: in the backend's entry points, less the waits
 * for the GPU (V4a's `time`). */
static uint64_t g_consumer_ns, g_wait_ns;
static char g_devname[VK_MAX_PHYSICAL_DEVICE_NAME_SIZE];

static unsigned long long g_n_draws, g_n_rebuilt, g_n_verts, g_n_submits, g_n_clears, g_n_copies, g_n_pipes;

/* The pipeline cache (V7): every pipeline made through it, its data loaded
 * from a file at start (SOA_GPU_PIPELINES, by default build/gxv-pipelines.bin;
 * off for none) and written back by the consumer at a frame's end when new
 * pipelines were made, at most once a second. The driver checks the data's
 * header and ignores another device's. Each creation is timed, and with
 * VK_EXT_pipeline_creation_feedback each says whether the cache had it. */
static VkPipelineCache g_pcache;
static char g_pcache_path[512];
static size_t g_pcache_loaded;
static unsigned long long g_pipes_saved, g_pipes_hit, g_pipe_ns_max, g_pipe_ns_total;
static uint64_t g_pcache_saved_ns;
static int g_feedback;
#define PIPE_FRAMES 48
static unsigned long long g_pipe_frame[PIPE_FRAMES]; /* the screen copies before each of the first pipelines */
static double g_gpu_ms;

typedef struct {
    float wd, ht, xorig, yorig, zrange, farz;
    uint32_t base;
    uint32_t record; /* in the draw records, in words */
} PushDraw;

static void say(const char* fmt, ...)
{
    char line[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    fprintf(stderr, "[gxv] %s\n", line); /* one call: the compiler thread says too */
}

#define VKCHECK(call)                                                        \
    do {                                                                     \
        VkResult r_ = (call);                                                \
        if (r_ != VK_SUCCESS) {                                              \
            say("%s failed: VkResult %d (%s:%d)", #call, (int)r_, __FILE__, __LINE__); \
            return 0;                                                        \
        }                                                                    \
    } while (0)

/* ---- the loader ------------------------------------------------------------- */

/* The host's loader, which the GPU driver installs; SOA_GPU_LOADER names
 * another, and a missing one is how the fallback is tested (3.11). */
static int load_loader(char* why, size_t cap)
{
#ifdef _WIN32
    const char* path = "vulkan-1.dll";
#else
    const char* path = "libvulkan.so.1";
#endif
    const char* forced = getenv("SOA_GPU_LOADER");
    char err[512];
    g_lib = plat_dl_open(forced ? forced : path, err, sizeof err);
#ifndef _WIN32
    if (!g_lib && !forced) g_lib = plat_dl_open("libvulkan.so", err, sizeof err);
#endif
    if (!g_lib) { snprintf(why, cap, "no Vulkan loader: %s", err); return 0; }
    *(void**)&vkGetInstanceProcAddr = plat_dl_sym(g_lib, "vkGetInstanceProcAddr");
    if (!vkGetInstanceProcAddr) { snprintf(why, cap, "the Vulkan loader has no vkGetInstanceProcAddr"); return 0; }
#define GXV_LOAD_GLOBAL(name) name = (PFN_##name)vkGetInstanceProcAddr(NULL, #name);
    GXV_GLOBAL(GXV_LOAD_GLOBAL)
    if (!vkCreateInstance) { snprintf(why, cap, "the Vulkan loader has no vkCreateInstance"); return 0; }
    return 1;
}

static int load_instance(char* why, size_t cap)
{
    int missing = 0;
#define GXV_LOAD_INSTANCE(name)                                                     \
    name = (PFN_##name)vkGetInstanceProcAddr(g_inst, #name);                        \
    if (!name && !missing++) snprintf(why, cap, "the Vulkan instance has no %s", #name);
    GXV_INSTANCE(GXV_LOAD_INSTANCE)
    return !missing;
}

static int load_device(char* why, size_t cap)
{
    int missing = 0;
#define GXV_LOAD_DEVICE(name)                                                       \
    name = (PFN_##name)vkGetDeviceProcAddr(g_dev, #name);                           \
    if (!name && !missing++) snprintf(why, cap, "the Vulkan device has no %s", #name);
    GXV_DEVICE(GXV_LOAD_DEVICE)
    return !missing;
}

/* ---- memory: a bump allocator per memory type ----------------------------- */

static int find_type(uint32_t bits, VkMemoryPropertyFlags want)
{
    uint32_t i;
    for (i = 0; i < g_memprops.memoryTypeCount; i++)
        if ((bits >> i & 1) && (g_memprops.memoryTypes[i].propertyFlags & want) == want) return (int)i;
    return -1;
}

/* Memory for one resource, out of its type's block. Nothing is ever freed
 * on its own: the spike's resources live as long as the device. Every offset
 * is aligned to bufferImageGranularity as well, so a buffer and an optimal
 * image can share a block without aliasing each other's pages. */
static int bind_memory(const VkMemoryRequirements* req, VkMemoryPropertyFlags want, VkDeviceMemory* mem,
                       VkDeviceSize* off, uint8_t** map)
{
    int t = find_type(req->memoryTypeBits, want), k;
    Arena* a = NULL;
    VkDeviceSize align = req->alignment, gran = g_props.limits.bufferImageGranularity, o = 0;
    if (t < 0) { say("no memory type with properties %#x for bits %#x", (unsigned)want, req->memoryTypeBits); return 0; }
    if (gran > align) align = gran;
    for (k = 0; k < ARENA_BLOCKS; k++) {
        a = &g_arena[t][k];
        if (!a->mem) {
            VkMemoryAllocateInfo ai = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
            ai.allocationSize = req->size > ARENA_BYTES ? req->size : ARENA_BYTES;
            ai.memoryTypeIndex = (uint32_t)t;
            VKCHECK(vkAllocateMemory(g_dev, &ai, NULL, &a->mem));
            a->size = ai.allocationSize;
            if (g_memprops.memoryTypes[t].propertyFlags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)
                VKCHECK(vkMapMemory(g_dev, a->mem, 0, VK_WHOLE_SIZE, 0, (void**)&a->map));
        }
        o = (a->used + align - 1) / align * align;
        if (o + req->size <= a->size) break;
    }
    if (k == ARENA_BLOCKS) { say("memory type %d: all %d blocks are full", t, ARENA_BLOCKS); return 0; }
    a->used = o + req->size;
    *mem = a->mem;
    *off = o;
    if (map) *map = a->map ? a->map + o : NULL;
    return 1;
}

/* A buffer the host maps. One the host reads back goes in cached memory
 * where there is any: reading the write-combined kind ran copydiff's GPU side
 * at about a twentieth of the CPU's speed. */
static int make_buffer(VkDeviceSize size, VkBufferUsageFlags usage, int host_reads, VkBuffer* buf, uint8_t** map)
{
    VkBufferCreateInfo bi = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    VkMemoryRequirements req;
    VkDeviceMemory mem;
    VkDeviceSize off;
    VkMemoryPropertyFlags want = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    bi.size = size;
    bi.usage = usage;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    VKCHECK(vkCreateBuffer(g_dev, &bi, NULL, buf));
    vkGetBufferMemoryRequirements(g_dev, *buf, &req);
    if (host_reads && find_type(req.memoryTypeBits, want | VK_MEMORY_PROPERTY_HOST_CACHED_BIT) >= 0) want |= VK_MEMORY_PROPERTY_HOST_CACHED_BIT;
    if (!bind_memory(&req, want, &mem, &off, map)) return 0;
    VKCHECK(vkBindBufferMemory(g_dev, *buf, mem, off));
    return 1;
}

static int make_image(VkFormat fmt, VkImageUsageFlags usage, VkImageAspectFlags aspect, VkImage* img, VkImageView* view)
{
    VkImageCreateInfo ii = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    VkImageViewCreateInfo vi = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    VkMemoryRequirements req;
    VkDeviceMemory mem;
    VkDeviceSize off;
    ii.imageType = VK_IMAGE_TYPE_2D;
    ii.format = fmt;
    ii.extent.width = EFB_W;
    ii.extent.height = EFB_H;
    ii.extent.depth = 1;
    ii.mipLevels = 1;
    ii.arrayLayers = 1;
    ii.samples = VK_SAMPLE_COUNT_1_BIT;
    ii.tiling = VK_IMAGE_TILING_OPTIMAL;
    ii.usage = usage;
    ii.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    ii.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    VKCHECK(vkCreateImage(g_dev, &ii, NULL, img));
    vkGetImageMemoryRequirements(g_dev, *img, &req);
    if (!bind_memory(&req, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, &mem, &off, NULL)) return 0;
    VKCHECK(vkBindImageMemory(g_dev, *img, mem, off));
    vi.image = *img;
    vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
    vi.format = fmt;
    vi.subresourceRange.aspectMask = aspect;
    vi.subresourceRange.levelCount = 1;
    vi.subresourceRange.layerCount = 1;
    VKCHECK(vkCreateImageView(g_dev, &vi, NULL, view));
    return 1;
}

/* ---- the command buffer --------------------------------------------------- */

static void barrier_image(VkImage img, VkImageAspectFlags aspect, VkImageLayout from, VkImageLayout to,
                          VkPipelineStageFlags src_stage, VkAccessFlags src, VkPipelineStageFlags dst_stage, VkAccessFlags dst)
{
    VkImageMemoryBarrier b = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
    b.srcAccessMask = src;
    b.dstAccessMask = dst;
    b.oldLayout = from;
    b.newLayout = to;
    b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = img;
    b.subresourceRange.aspectMask = aspect;
    b.subresourceRange.levelCount = 1;
    b.subresourceRange.layerCount = 1;
    vkCmdPipelineBarrier(g_cb, src_stage, dst_stage, 0, 0, NULL, 0, NULL, 1, &b);
}

/* Each submission starts with a full memory barrier: the one before it has
 * finished (its fence was waited on), and this makes what it wrote visible to
 * everything this one does, whatever stage did the writing. */
static int begin_cb(void)
{
    VkCommandBufferBeginInfo bi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER};
    if (g_rec) return 1;
    bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    VKCHECK(vkBeginCommandBuffer(g_cb, &bi));
    g_dyn_cull = g_dyn_topo = g_dyn_zen = g_dyn_zupd = g_dyn_zf = -1;
    mb.srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT;
    mb.dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
    vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
    if (g_timestamps) {
        vkCmdResetQueryPool(g_cb, g_qpool, 0, 2);
        vkCmdWriteTimestamp(g_cb, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, g_qpool, 0);
    }
    if (g_measure) vkCmdResetQueryPool(g_cb, g_occ, 0, OCC_QUERIES);
    g_occ_used = 0;
    g_rec = 1;
    g_bound = VK_NULL_HANDLE;
    return 1;
}

static int begin_pass(void)
{
    VkRenderPassBeginInfo rb = {VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    if (!begin_cb()) return 0;
    if (g_inpass) return 1;
    rb.renderPass = g_pass;
    rb.framebuffer = g_fb;
    rb.renderArea.extent.width = EFB_W;
    rb.renderArea.extent.height = EFB_H;
    vkCmdBeginRenderPass(g_cb, &rb, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdBindDescriptorSets(g_cb, VK_PIPELINE_BIND_POINT_GRAPHICS, g_layout, 0, 1, &g_dset, 0, NULL);
    vkCmdBindIndexBuffer(g_cb, g_quad_idx, 0, VK_INDEX_TYPE_UINT32);
    g_inpass = 1;
    g_bound = VK_NULL_HANDLE;
    return 1;
}

static void end_pass(void)
{
    if (g_inpass) vkCmdEndRenderPass(g_cb);
    g_inpass = 0;
}

/* V10's interlock route, one draw: the EFB out of its pass and into GENERAL,
 * where the shader reads and writes it as a storage image, a pass of no
 * attachments for the draw, and the EFB back after (end_interlock). */
static int begin_interlock(void)
{
    VkRenderPassBeginInfo rb = {VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    if (!begin_cb()) return 0;
    end_pass();
    barrier_image(g_color, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_GENERAL,
                  VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
                  VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT);
    rb.renderPass = g_pass_il;
    rb.framebuffer = g_fb_il;
    rb.renderArea.extent.width = EFB_W;
    rb.renderArea.extent.height = EFB_H;
    vkCmdBeginRenderPass(g_cb, &rb, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdBindDescriptorSets(g_cb, VK_PIPELINE_BIND_POINT_GRAPHICS, g_layout, 0, 1, &g_dset, 0, NULL);
    vkCmdBindIndexBuffer(g_cb, g_quad_idx, 0, VK_INDEX_TYPE_UINT32);
    g_bound = VK_NULL_HANDLE;
    return 1;
}

static void end_interlock(void)
{
    vkCmdEndRenderPass(g_cb);
    barrier_image(g_color, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                  VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, VK_ACCESS_SHADER_WRITE_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                  VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT);
    g_bound = VK_NULL_HANDLE;
}

/* What the submission just done held for guest RAM (V7): each copy's bytes
 * into RAM and its image into the producer's copy image, the pool's copy of
 * it gone with the submission, and gxr told. --mutate late-readback (V6b)
 * tells gxr first and puts the bytes in RAM only at the next command. */
static void land_all(void)
{
    unsigned i;
    if (!g_land_n) return;
    for (i = 0; i < g_land_n; i++) {
        const uint8_t* bytes = g_dest_map + g_land[i].dest_at;
        if (g_mut_late) {
            uint8_t* keep = (uint8_t*)realloc(g_late_bytes, g_land[i].extent);
            late_land();
            if (keep) {
                g_late_bytes = keep;
                memcpy(g_late_bytes, bytes, g_land[i].extent);
                g_late_ram = g_land[i].ram;
                g_late_n = g_land[i].extent;
            }
        } else {
            memcpy(g_land[i].ram, bytes, g_land[i].extent);
        }
        if (g_land[i].image) memcpy(g_land[i].image, g_image_map + (size_t)g_land[i].image_at * 4, (size_t)g_land[i].texels * 4);
    }
    g_land_n = 0;
    g_cimg_n = 0;
    g_dest_used = 0;
    g_image_used = 0;
    gxr_backend_landed(g_seq_cur);
}

/* Submit what is recorded and wait for it. The vertex ring is free again. */
static int submit_wait(void)
{
    VkSubmitInfo si = {VK_STRUCTURE_TYPE_SUBMIT_INFO};
    VkResult r;
    if (!g_rec) return 1;
    end_pass();
    if (g_timestamps) vkCmdWriteTimestamp(g_cb, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, g_qpool, 1);
    VKCHECK(vkEndCommandBuffer(g_cb));
    si.commandBufferCount = 1;
    si.pCommandBuffers = &g_cb;
    plat_lock(&g_queue_lock); /* the presenter submits and presents on this queue too (V8) */
    r = vkQueueSubmit(g_queue, 1, &si, g_fence);
    plat_unlock(&g_queue_lock);
    if (r != VK_SUCCESS) {
        say("vkQueueSubmit failed: VkResult %d", (int)r);
        return 0;
    }
    {
        uint64_t t0 = plat_mono_ns();
        VKCHECK(vkWaitForFences(g_dev, 1, &g_fence, VK_TRUE, UINT64_MAX));
        g_wait_ns += plat_mono_ns() - t0;
    }
    VKCHECK(vkResetFences(g_dev, 1, &g_fence));
    g_rec = 0;
    g_ring_used = 0;
    g_draw_used = 0;
    g_pool_used = 0;
    g_texrec_used = 0;
    g_epoch++;
    g_n_submits++;
    land_all();
    if (g_timestamps) {
        uint64_t ts[2];
        if (vkGetQueryPoolResults(g_dev, g_qpool, 0, 2, sizeof ts, ts, sizeof ts[0], VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT) == VK_SUCCESS)
            g_gpu_ms += (double)(ts[1] - ts[0]) * g_props.limits.timestampPeriod / 1e6;
    }
    if (g_measure && g_occ_used) {
        static uint64_t samples[OCC_QUERIES];
        unsigned q;
        if (vkGetQueryPoolResults(g_dev, g_occ, 0, g_occ_used, sizeof(uint64_t) * g_occ_used, samples, sizeof(uint64_t),
                                  VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT) == VK_SUCCESS)
            for (q = 0; q < g_occ_used; q++) {
                int k = 5;
                while (k > 0 && samples[q] > g_top_samples[k - 1]) k--;
                if (k < 5) {
                    memmove(&g_top_samples[k + 1], &g_top_samples[k], (4 - (size_t)k) * sizeof g_top_samples[0]);
                    memmove(&g_top_draw[k + 1], &g_top_draw[k], (4 - (size_t)k) * sizeof g_top_draw[0]);
                    g_top_samples[k] = samples[q];
                    g_top_draw[k] = g_occ_draw[q];
                }
            }
        g_occ_used = 0;
    }
    return 1;
}

/* ---- pipelines ------------------------------------------------------------ */

/* GX's z_func and Vulkan's compare ops are the same eight, in the same order
 * (gxr.c depth_test: incoming against stored), spelled out rather than cast. */
static const VkCompareOp k_zfunc[8] = {
    VK_COMPARE_OP_NEVER,   VK_COMPARE_OP_LESS,      VK_COMPARE_OP_EQUAL,            VK_COMPARE_OP_LESS_OR_EQUAL,
    VK_COMPARE_OP_GREATER, VK_COMPARE_OP_NOT_EQUAL, VK_COMPARE_OP_GREATER_OR_EQUAL, VK_COMPARE_OP_ALWAYS};

static const VkPrimitiveTopology k_topo[6] = {
    VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_FAN,
    VK_PRIMITIVE_TOPOLOGY_LINE_LIST,     VK_PRIMITIVE_TOPOLOGY_LINE_STRIP,     VK_PRIMITIVE_TOPOLOGY_POINT_LIST};

/* The CPU's culling (raster_triangle) on its signed area (b - a) x (c - a)
 * in screen space, y down: mode 1 drops area < 0, mode 2 drops area > 0, mode
 * 3 drops every triangle. Vulkan's area has the opposite sign in the same
 * coordinates, so with COUNTER_CLOCKWISE front faces "front" is the CPU's
 * area < 0: mode 1 culls front faces and mode 2 back faces. */
static const VkCullModeFlags k_cull[4] = {VK_CULL_MODE_NONE, VK_CULL_MODE_FRONT_BIT, VK_CULL_MODE_BACK_BIT,
                                          VK_CULL_MODE_FRONT_AND_BACK};

/* GX's blend factors as Vulkan's (3.5). As a source factor 2 and 3 are the
 * destination's colour, as a destination factor the source's. */
static const VkBlendFactor k_src_factor[8] = {
    VK_BLEND_FACTOR_ZERO,      VK_BLEND_FACTOR_ONE,       VK_BLEND_FACTOR_DST_COLOR,
    VK_BLEND_FACTOR_ONE_MINUS_DST_COLOR, VK_BLEND_FACTOR_SRC_ALPHA, VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
    VK_BLEND_FACTOR_DST_ALPHA, VK_BLEND_FACTOR_ONE_MINUS_DST_ALPHA};
static const VkBlendFactor k_dst_factor[8] = {
    VK_BLEND_FACTOR_ZERO,      VK_BLEND_FACTOR_ONE,       VK_BLEND_FACTOR_SRC_COLOR,
    VK_BLEND_FACTOR_ONE_MINUS_SRC_COLOR, VK_BLEND_FACTOR_SRC_ALPHA, VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
    VK_BLEND_FACTOR_DST_ALPHA, VK_BLEND_FACTOR_ONE_MINUS_DST_ALPHA};

/* The logic op a draw is drawn with, or -1: GX's 0-15, which Vulkan's
 * VkLogicOp numbers the same way. A blend overrides it, as on the CPU. The
 * mutations change it here, so every mode draws them alike. 3, COPY, is no
 * logic op at all. */
static int draw_lop(const DrawCmd* D)
{
    int lop;
    if (D->px.blend_en || !D->px.logic_en) return -1;
    lop = (int)(D->px.lop & 15);
    if (g_mut_logic == MUT_LOGIC_COPY || (g_mut_logic == MUT_AND_COPY && lop == 1) || (g_mut_logic == MUT_OR_COPY && lop == 7))
        return 3;
    if (g_mut_logic == MUT_OR_AND) lop = lop == 7 ? 1 : lop == 1 ? 7 : lop;
    return lop;
}

/* V10: how a logic draw is drawn, or -1 for a draw that is not one. Forced
 * (SOA_GPU_LOGICOP); or native, where the device has logicOp; or, without it,
 * a snapshot for one quad, which cannot overlap itself (every logic draw in
 * this game, 3.5); else the interlock, where the device has it and the draw
 * tests no depth (its pass has no depth attachment); else blend for OR and AND
 * and a snapshot for the rest, said once, as neither is exact for a draw that
 * overlaps itself. */
static int logic_route(const DrawCmd* D, int lop)
{
    static int said;
    if (lop < 0 || lop == 3) return -1;
    if (g_logic_mode >= 0) return g_logic_mode;
    if (g_has_logicop) return LOGIC_NATIVE;
    if (D->prim == 0x80 && D->count == 4) return LOGIC_SNAPSHOT;
    if (g_has_interlock && !D->px.z_en) return LOGIC_INTERLOCK;
    if (!said++)
        say("draw %llu: logic op %d on %u vertices (primitive %#x) may overlap itself, and this device has neither "
            "logicOp nor %s: drawn %s, exact only where it does not overlap",
            g_n_draws + 1, lop, D->count, D->prim, D->px.z_en ? "an interlock route for a depth-tested draw" : "interlock",
            lop == 1 || lop == 7 ? "as a blend" : "from a snapshot");
    return lop == 1 || lop == 7 ? LOGIC_BLEND : LOGIC_SNAPSHOT;
}

static int fragment_module(void)
{
    VkShaderModuleCreateInfo si = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    if (!g_vs) {
        si.codeSize = g_mut_noinvariant ? sizeof raster_vert_noinvariant : sizeof raster_vert;
        si.pCode = g_mut_noinvariant ? raster_vert_noinvariant : raster_vert;
        VKCHECK(vkCreateShaderModule(g_dev, &si, NULL, &g_vs));
    }
    if (g_fs) return 1;
    si.codeSize = g_mut_frag == 1 ? sizeof raster_frag_alpha : g_mut_frag == 2 ? sizeof raster_frag_lod
                : g_mut_frag == 3 ? sizeof raster_frag_fog : sizeof raster_frag;
    si.pCode = g_mut_frag == 1 ? raster_frag_alpha : g_mut_frag == 2 ? raster_frag_lod
             : g_mut_frag == 3 ? raster_frag_fog : raster_frag;
    VKCHECK(vkCreateShaderModule(g_dev, &si, NULL, &g_fs));
    if (g_has_interlock && !g_fs_il) {
        si.codeSize = sizeof raster_frag_interlock;
        si.pCode = raster_frag_interlock;
        VKCHECK(vkCreateShaderModule(g_dev, &si, NULL, &g_fs_il));
    }
    return 1;
}

/* The TEV's shape, as tev.glsl's specialization constants take it: SC_ON,
 * the stage count, word 1's compares and logic, and each stage's words 0-3,
 * zero past the last stage -- from the words gxv_pack_tev wrote for the
 * draw's record. */
static void tev_shape(const uint32_t* packed, uint32_t* shape)
{
    unsigned st, j;
    memset(shape, 0, TEV_SHAPE_WORDS * sizeof *shape);
    shape[0] = 1;
    shape[1] = packed[0] - (g_mut_spec_stages && packed[0] > 1);
    shape[2] = packed[1] & 0xFFFF0000u;
    for (st = 0; st < packed[0] && st < 16; st++)
        for (j = 0; j < 4; j++) shape[3 + st * 4 + j] = packed[18 + st * 5 + j];
}

static void shape_seen(const uint32_t* shape)
{
    uint64_t h = 1469598103934665603ull;
    unsigned i, slot;
    for (i = 0; i < TEV_SHAPE_WORDS; i++) h = (h ^ shape[i]) * 1099511628211ull;
    h |= 1;
    for (slot = (unsigned)(h >> 7) & (SHAPE_SLOTS - 1), i = 0; i < SHAPE_SLOTS; i++, slot = (slot + 1) & (SHAPE_SLOTS - 1)) {
        if (g_shape_seen[slot] == h) return;
        if (!g_shape_seen[slot]) {
            g_shape_seen[slot] = h;
            g_n_shapes++;
            return;
        }
    }
}

/* The fixed-function state a pipeline is made for; pipe_state gives its key. */
typedef struct {
    int topo, z_en, z_upd, blend_en, subtract, lop, route;
    unsigned cull, zf, mask, sfac, dfac;
} PipeState;

static uint32_t pipe_state(int topo, const DrawCmd* D, PipeState* S)
{
    unsigned blend;
    S->topo = topo;
    S->z_en = D->px.z_en != 0;
    S->zf = S->z_en ? (D->px.z_func & 7) : 0;
    S->z_upd = S->z_en && D->px.z_upd;
    S->mask = (D->px.col_upd ? 1u : 0u) | (D->px.alpha_upd ? 2u : 0u);
    S->cull = topo <= T_FAN ? (D->rc.cull & 3) : 0;
    S->lop = draw_lop(D);
    S->blend_en = D->px.blend_en != 0;
    S->subtract = D->px.subtract != 0;
    S->sfac = D->px.sfac & 7;
    S->dfac = D->px.dfac & 7;
    S->route = S->blend_en ? -1 : logic_route(D, S->lop);
    /* The blend field: a blend's factors, or -- the blend being off -- a logic
     * op's number above bit 0, which never collides with a blend's, and its
     * route above that (V10). */
    blend = S->blend_en ? 1u | S->sfac << 1 | S->dfac << 4 | (S->subtract ? 1u : 0u) << 7
          : S->lop >= 0 && S->lop != 3 ? (unsigned)S->lop << 1 | 0x20u | (unsigned)(S->route & 3) << 6 : 0u;
    if (g_eds) {
        /* Dynamic: the key keeps only the topology's class. */
        uint32_t cls = topo <= T_FAN ? T_TRIS : topo <= T_LSTRIP ? T_LINES : T_POINTS;
        return 1u + ((((cls * 4 * 2 * 8 * 2) * 4 + S->mask) << 8) | blend);
    }
    return 1u + ((((((((uint32_t)topo * 4 + S->cull) * 2 + (uint32_t)S->z_en) * 8 + S->zf) * 2 + (uint32_t)S->z_upd) * 4 +
                   S->mask) << 8) | blend);
}

/* One pipeline for the state S: the interpreter's when shape is NULL, else
 * specialised on it. Any thread: it reads only what gxv_init and the first
 * draw (fragment_module) set, and the pipeline cache is the driver's to
 * synchronise. *ns is the creation's time, *hit whether the cache had it. */
static VkResult pipe_make(const PipeState* S, const uint32_t* shape, VkPipeline* out, uint64_t* ns, int* hit)
{
    VkSpecializationMapEntry spec_map[TEV_SHAPE_WORDS];
    VkSpecializationInfo spec = {0};
    unsigned i;
    VkPipelineShaderStageCreateInfo st[2] = {{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO},
                                             {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO}};
    VkPipelineVertexInputStateCreateInfo vin = {VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia = {VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO};
    VkViewport vp = {0.0f, 0.0f, (float)EFB_W, (float)EFB_H, 0.0f, 1.0f};
    VkRect2D sc = {{0, 0}, {EFB_W, EFB_H}};
    VkPipelineViewportStateCreateInfo vps = {VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO};
    VkPipelineRasterizationStateCreateInfo rs = {VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};
    VkPipelineMultisampleStateCreateInfo ms = {VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};
    VkPipelineDepthStencilStateCreateInfo ds = {VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO};
    VkPipelineColorBlendAttachmentState ba = {0};
    VkPipelineColorBlendStateCreateInfo cb = {VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};
    VkDynamicState dyn[6] = {VK_DYNAMIC_STATE_SCISSOR,
                             VK_DYNAMIC_STATE_CULL_MODE_EXT,
                             VK_DYNAMIC_STATE_PRIMITIVE_TOPOLOGY_EXT,
                             VK_DYNAMIC_STATE_DEPTH_TEST_ENABLE_EXT,
                             VK_DYNAMIC_STATE_DEPTH_WRITE_ENABLE_EXT,
                             VK_DYNAMIC_STATE_DEPTH_COMPARE_OP_EXT};
    VkPipelineDynamicStateCreateInfo dys = {VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO};
    VkGraphicsPipelineCreateInfo pi = {VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};
    VkPipelineCreationFeedbackEXT fb = {0};
    VkPipelineCreationFeedbackCreateInfoEXT fci = {VK_STRUCTURE_TYPE_PIPELINE_CREATION_FEEDBACK_CREATE_INFO_EXT};
    uint64_t t0;
    VkResult r;

    st[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    st[0].module = g_vs;
    st[0].pName = "main";
    st[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    st[1].module = g_fs;
    st[1].pName = "main";
    if (shape) {
        for (i = 0; i < TEV_SHAPE_WORDS; i++) {
            spec_map[i].constantID = i;
            spec_map[i].offset = i * 4;
            spec_map[i].size = 4;
        }
        spec.mapEntryCount = TEV_SHAPE_WORDS;
        spec.pMapEntries = spec_map;
        spec.dataSize = TEV_SHAPE_WORDS * sizeof *shape;
        spec.pData = shape;
        st[1].pSpecializationInfo = &spec;
    }
    ia.topology = k_topo[S->topo];
    vps.viewportCount = 1;
    vps.pViewports = &vp;
    vps.scissorCount = 1;
    vps.pScissors = &sc;
    rs.polygonMode = VK_POLYGON_MODE_FILL;
    rs.cullMode = k_cull[S->cull];
    rs.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rs.lineWidth = 1.0f;
    ms.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
    ds.depthTestEnable = (VkBool32)S->z_en;
    ds.depthWriteEnable = (VkBool32)S->z_upd;
    ds.depthCompareOp = k_zfunc[S->zf];
    ba.colorWriteMask = ((S->mask & 1) ? VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT : 0) |
                        ((S->mask & 2) ? VK_COLOR_COMPONENT_A_BIT : 0);
    /* blend_pixel: the colour blended by the factors, or the destination
     * less the source with the factors ignored; the alpha stored as the
     * source gives it, never blended. */
    if (S->blend_en) {
        ba.blendEnable = VK_TRUE;
        if (S->subtract) {
            ba.colorBlendOp = VK_BLEND_OP_REVERSE_SUBTRACT;
            ba.srcColorBlendFactor = VK_BLEND_FACTOR_ONE;
            ba.dstColorBlendFactor = VK_BLEND_FACTOR_ONE;
        } else {
            ba.colorBlendOp = VK_BLEND_OP_ADD;
            ba.srcColorBlendFactor = k_src_factor[S->sfac];
            ba.dstColorBlendFactor = k_dst_factor[S->dfac];
        }
        ba.alphaBlendOp = VK_BLEND_OP_ADD;
        ba.srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE;
        ba.dstAlphaBlendFactor = VK_BLEND_FACTOR_ZERO;
    }
    if (!S->blend_en && S->lop >= 0 && S->lop != 3) {
        if (S->route == LOGIC_NATIVE) {
            /* All four channels: the CPU applies the op to RGB and stores the
             * source alpha, which nothing in this game reads (3.5). */
            cb.logicOpEnable = VK_TRUE;
            cb.logicOp = (VkLogicOp)S->lop;
        } else if (S->route == LOGIC_BLEND) {
            /* OR as src(1 - dst) + dst, AND as src dst; the alpha stored as it is. */
            ba.blendEnable = VK_TRUE;
            ba.colorBlendOp = VK_BLEND_OP_ADD;
            ba.srcColorBlendFactor = S->lop == 7 ? VK_BLEND_FACTOR_ONE_MINUS_DST_COLOR : VK_BLEND_FACTOR_DST_COLOR;
            ba.dstColorBlendFactor = S->lop == 7 ? VK_BLEND_FACTOR_ONE : VK_BLEND_FACTOR_ZERO;
            ba.alphaBlendOp = VK_BLEND_OP_ADD;
            ba.srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE;
            ba.dstAlphaBlendFactor = VK_BLEND_FACTOR_ZERO;
        }
        /* snapshot: the shader computes it, against the EFB read before */
    }
    cb.attachmentCount = 1;
    cb.pAttachments = &ba;
    if (!S->blend_en && S->lop >= 0 && S->lop != 3 && S->route == LOGIC_INTERLOCK) {
        /* V10: the interlock variant, in a pass of no attachments: the shader
         * writes the EFB itself, and there is no depth to test. */
        st[1].module = g_fs_il;
        st[1].pSpecializationInfo = NULL;
        cb.attachmentCount = 0;
        cb.pAttachments = NULL;
        ds.depthTestEnable = VK_FALSE;
        ds.depthWriteEnable = VK_FALSE;
    }
    dys.dynamicStateCount = g_eds ? 6 : 1;
    dys.pDynamicStates = dyn;
    if (g_eds) /* the class's first topology: the draw sets its own */
        ia.topology = k_topo[S->topo <= T_FAN ? T_TRIS : S->topo <= T_LSTRIP ? T_LINES : T_POINTS];
    pi.stageCount = 2;
    pi.pStages = st;
    pi.pVertexInputState = &vin;
    pi.pInputAssemblyState = &ia;
    pi.pViewportState = &vps;
    pi.pRasterizationState = &rs;
    pi.pMultisampleState = &ms;
    pi.pDepthStencilState = &ds;
    pi.pColorBlendState = &cb;
    pi.pDynamicState = &dys;
    pi.layout = g_layout;
    pi.renderPass = cb.attachmentCount ? g_pass : g_pass_il;
    if (g_feedback) {
        fci.pPipelineCreationFeedback = &fb;
        pi.pNext = &fci;
    }
    t0 = plat_mono_ns();
    r = vkCreateGraphicsPipelines(g_dev, g_pcache, 1, &pi, NULL, out);
    *ns = plat_mono_ns() - t0;
    *hit = (fb.flags & VK_PIPELINE_CREATION_FEEDBACK_VALID_BIT_EXT) &&
           (fb.flags & VK_PIPELINE_CREATION_FEEDBACK_APPLICATION_PIPELINE_CACHE_HIT_BIT_EXT);
    return r;
}

/* The compiler thread (V7): specialised pipelines made off the draw path. A
 * ring with one producer, the draw path, and one consumer, the thread: each
 * job a state and its slot, the slot's key and shape written before the job
 * is put. The thread's figures are written by it alone and read by the
 * report. */
#define JOBS 256
static struct {
    PipeState S;
    unsigned slot;
} g_jobs[JOBS];
static plat_a64 g_jobs_head, g_jobs_tail; /* only rise: put by the draw path, taken by the thread */
static plat_a32 g_compiler_stop, g_compiler_running;
static plat_a64 g_bg_made, g_bg_hit, g_bg_failed, g_bg_ns_max, g_bg_ns_total;
static PlatThread g_compiler;
/* A test knob: SOA_GPU_COMPILE_STALL=<ms>, the thread sleeping that long
 * before each pipeline -- a driver with no shader cache of its own, as on a
 * first launch, so a check can see the draw path not wait for it. */
static unsigned g_compile_stall_ms;

static void compiler_main(void* arg)
{
    int64_t tail = plat_load64(&g_jobs_tail);
    (void)arg;
    while (!plat_load32(&g_compiler_stop)) {
        int64_t head = plat_load64(&g_jobs_head);
        PipeState S;
        unsigned slot;
        VkPipeline p = VK_NULL_HANDLE;
        uint64_t ns;
        int hit;
        if (tail == head) {
            plat_wait64(&g_jobs_head, head, 50);
            continue;
        }
        S = g_jobs[tail % JOBS].S;
        slot = g_jobs[tail % JOBS].slot;
        plat_xchg64(&g_jobs_tail, ++tail); /* the job read: its place free for the draw path */
        if (g_compile_stall_ms) plat_sleep_ms(g_compile_stall_ms);
        if (pipe_make(&S, g_pipes[slot].shape, &p, &ns, &hit) == VK_SUCCESS) {
            g_pipes[slot].pipe = p;
            plat_store64_relaxed(&g_bg_made, plat_load64(&g_bg_made) + 1);
            if (hit) plat_store64_relaxed(&g_bg_hit, plat_load64(&g_bg_hit) + 1);
            if ((int64_t)ns > plat_load64(&g_bg_ns_max)) plat_store64_relaxed(&g_bg_ns_max, (int64_t)ns);
            plat_store64_relaxed(&g_bg_ns_total, plat_load64(&g_bg_ns_total) + (int64_t)ns);
            plat_cas32(&g_pipes[slot].ready, 0, 1); /* after pipe: the draw path reads pipe once it sees 1 */
            say("pipeline made on the compiler thread in %.2f ms%s", (double)ns / 1e6, hit ? ", from the cache" : "");
        } else {
            say("a specialised pipeline failed on the compiler thread; the interpreter draws its state");
            plat_store64_relaxed(&g_bg_failed, plat_load64(&g_bg_failed) + 1);
            plat_cas32(&g_pipes[slot].ready, 0, -1);
        }
    }
    plat_cas32(&g_compiler_running, 1, 0);
}

/* SOA_GPU_SPECIALIZE, and the compiler thread where it is wanted; with no
 * thread to be had, the interpreter alone rather than a stall at each new
 * shape. */
static void compiler_start(void)
{
    const char* sp = getenv("SOA_GPU_SPECIALIZE");
    g_specialize = !sp || !*sp || !strcmp(sp, "1") ? SPEC_BACKGROUND : !strcmp(sp, "wait") ? SPEC_WAIT
                 : !strcmp(sp, "0")                 ? SPEC_OFF
                                                    : -1;
    if (g_specialize < 0) {
        say("SOA_GPU_SPECIALIZE=%s is not 0, 1 or wait; specialising in the background", sp);
        g_specialize = SPEC_BACKGROUND;
    }
    if (g_specialize != SPEC_BACKGROUND) return;
    if ((sp = getenv("SOA_GPU_COMPILE_STALL")) != NULL && atoi(sp) > 0) {
        g_compile_stall_ms = (unsigned)atoi(sp);
        say("SOA_GPU_COMPILE_STALL: the compiler thread sleeps %u ms before each pipeline; this run is a test",
            g_compile_stall_ms);
    }
    plat_cas32(&g_compiler_stop, 1, 0);
    plat_cas32(&g_compiler_running, 0, 1);
    if (!plat_thread_start(&g_compiler, compiler_main, NULL, 0)) {
        plat_cas32(&g_compiler_running, 1, 0);
        say("no thread for the pipeline compiler; the TEV is interpreted");
        g_specialize = SPEC_OFF;
    }
}

/* The thread finishes the pipeline it is making, if any, and leaves the rest
 * queued: their slots stay at 0, their pipes null. */
static void compiler_stop(void)
{
    if (!plat_load32(&g_compiler_running)) return;
    plat_cas32(&g_compiler_stop, 0, 1);
    plat_wake_all64(&g_jobs_head);
    while (plat_load32(&g_compiler_running)) plat_sleep_ms(1);
}

/* Where key and shape's pipeline is, 1 and its slot; 0 and the free slot it
 * would go in; -1 when the table is full. */
static int pipe_find(uint32_t key, const uint32_t* shape, unsigned* at)
{
    uint32_t h = key;
    unsigned i, slot, probes;
    for (i = 0; i < TEV_SHAPE_WORDS; i++) h = (h ^ shape[i]) * 16777619u;
    slot = (h * 2654435761u) >> 20 & (PIPE_SLOTS - 1);
    for (probes = 0; probes < PIPE_SLOTS; probes++, slot = (slot + 1) & (PIPE_SLOTS - 1)) {
        if (g_pipes[slot].key == key && !memcmp(g_pipes[slot].shape, shape, TEV_SHAPE_WORDS * sizeof *shape)) {
            *at = slot;
            return 1;
        }
        if (!g_pipes[slot].key) {
            *at = slot;
            return 0;
        }
    }
    return -1;
}

/* A pipeline made on the draw path, timed into the report's figures, and its
 * slot filled -- a failed specialised one too, at -1, so it is not tried
 * again. */
static VkPipeline pipe_put(unsigned slot, uint32_t key, const PipeState* S, const uint32_t* shape)
{
    static const uint32_t interp[TEV_SHAPE_WORDS];
    VkPipeline p = VK_NULL_HANDLE;
    uint64_t ns;
    int hit;
    VkResult r = pipe_make(S, shape, &p, &ns, &hit);
    if (r != VK_SUCCESS) {
        say("vkCreateGraphicsPipelines failed: VkResult %d", (int)r);
        if (!shape) return VK_NULL_HANDLE;
        p = VK_NULL_HANDLE;
    } else {
        if (hit) g_pipes_hit++;
        if (ns > g_pipe_ns_max) g_pipe_ns_max = ns;
        g_pipe_ns_total += ns;
        if (g_n_pipes < PIPE_FRAMES) g_pipe_frame[g_n_pipes] = g_n_copies;
        g_n_pipes++;
        /* One line each, which soak.py check counts against the map loads
         * around it (V7's budget). */
        say("pipeline made on the draw path at frame %llu in %.2f ms%s (state %08x)", g_n_copies, (double)ns / 1e6,
            hit ? ", from the cache" : "", key);
    }
    memcpy(g_pipes[slot].shape, shape ? shape : interp, sizeof interp);
    g_pipes[slot].pipe = p;
    g_pipes[slot].ready = p ? 1 : -1;
    g_pipes[slot].key = key;
    return p;
}

/* The draw's pipeline. Specialised: its shape's, once made; until then --
 * queued for the compiler thread the first time the shape is seen with this
 * state -- the interpreter's for the state, which gives the same pixels.
 * tev is the draw's TEV as draw_record packed it. */
static VkPipeline pipeline(int topo, const DrawCmd* D, const uint32_t* tev, PipeState* out)
{
    static const uint32_t interp[TEV_SHAPE_WORDS]; /* the interpreter's: no shape */
    static int said_full;
    uint32_t shape[TEV_SHAPE_WORDS];
    PipeState S;
    uint32_t key = pipe_state(topo, D, &S);
    *out = S;
    unsigned slot;
    int at;
    if (!fragment_module()) return VK_NULL_HANDLE; /* before any job: the thread uses the modules */
    if (g_specialize < 0) compiler_start();
    if (g_specialize != SPEC_OFF && S.route != LOGIC_INTERLOCK) {
        tev_shape(tev, shape);
        at = pipe_find(key, shape, &slot);
        if (at > 0) {
            int32_t ready = plat_load32(&g_pipes[slot].ready);
            if (ready > 0) return g_pipes[slot].pipe;
            if (ready == 0) g_n_interim++;
        } else if (at == 0) {
            int64_t head = plat_load64(&g_jobs_head);
            if (g_specialize == SPEC_WAIT) {
                VkPipeline p;
                shape_seen(shape);
                g_n_spec++;
                if ((p = pipe_put(slot, key, &S, shape)) != VK_NULL_HANDLE) return p;
            } else if (head - plat_load64(&g_jobs_tail) < JOBS) {
                shape_seen(shape);
                g_n_spec++;
                memcpy(g_pipes[slot].shape, shape, sizeof shape);
                g_pipes[slot].ready = 0;
                g_pipes[slot].key = key;
                g_jobs[head % JOBS].S = S;
                g_jobs[head % JOBS].slot = slot;
                plat_inc64(&g_jobs_head); /* publishes the slot and the job */
                plat_wake_all64(&g_jobs_head);
                if (g_mut_compile_wait) {
                    while (!plat_load32(&g_pipes[slot].ready)) plat_sleep_ms(1);
                    if (plat_load32(&g_pipes[slot].ready) > 0) return g_pipes[slot].pipe;
                }
                g_n_interim++;
            } else {
                g_n_interim++; /* the ring full: asked again at the next draw */
            }
        } else if (!said_full) {
            said_full = 1;
            say("the pipeline table is full; new shapes are interpreted");
        }
    }
    at = pipe_find(key, interp, &slot);
    if (at > 0) return g_pipes[slot].pipe;
    if (at < 0) {
        say("the pipeline table is full");
        return VK_NULL_HANDLE;
    }
    return pipe_put(slot, key, &S, NULL);
}

/* ---- the backend ------------------------------------------------------------ */

/* What the spike cannot draw yet, or NULL: logic ops are V4b's, and a
 * constant alpha, which nothing in the corpus sets (2.2), would need
 * dual-source blending to store (3.4). Refused rather than drawn wrong. */
static const char* unsupported(const DrawCmd* D)
{
    int lop = draw_lop(D);
    if (logic_route(D, lop) == LOGIC_BLEND && lop != 1 && lop != 7)
        return "a logic op other than OR and AND, which the blend approximation cannot draw (3.5)";
    if (D->px.const_alpha >= 0) return "a constant alpha (3.4: the corpus has none)";
    return NULL;
}

/* ---- textures and the draw's record ------------------------------------------ */

static unsigned tex_texels(const TexCfg* C)
{
    unsigned n = 0;
    int l;
    for (l = 0; l < C->nlevels && l < MAX_MIPS; l++) n += (unsigned)(C->lw[l] * C->lh[l]);
    return n;
}

/* A texture's levels into the pool, once a submission for each cache slot
 * and generation: a slot re-decoded mid-frame gets a fresh allocation, and
 * nothing is overwritten before the submission that reads it is done. */
static uint32_t upload_texture(const TexCfg* C)
{
    uint32_t* rec;
    unsigned id = (unsigned)C->tex_id, n = tex_texels(C);
    int l;
    if (!C->level[0] || C->nlevels < 1 || C->w <= 0 || C->h <= 0 || id >= 1024) return NO_TEXTURE;
    /* A copy's image from this submission: the pool's, which the copy wrote
     * there; the producer's is filled only when the copy lands (V7). From an
     * earlier submission it has landed, and is uploaded as any texture. */
    if (C->copy_image && !g_mut_cimg_cpu) {
        unsigned i;
        for (i = 0; i < g_cimg_n; i++)
            if (g_cimg[i].cpu == C->level[0]) {
                g_n_cimg_served++;
                return g_cimg[i].rec;
            }
    }
    if (g_resident[id].epoch == g_epoch && g_resident[id].gen == C->tex_gen) return g_resident[id].rec;
    if (g_mut_pool_inplace && g_resident[id].epoch == g_epoch) {
        /* --mutate pool-in-place (test_gxv_queue.py): the slot's new contents
         * over its old allocation, which draws already recorded in this
         * submission still sample -- what 3.2's append-only rule forbids. */
        const uint32_t* old = (const uint32_t*)g_texrec_map + g_resident[id].rec;
        if (old[11] == (uint32_t)C->lw[0] && old[22] == (uint32_t)C->lh[0]) {
            memcpy(g_pool_map + (size_t)old[0] * 4, C->level[0], (size_t)C->lw[0] * C->lh[0] * 4);
            g_resident[id].gen = C->tex_gen;
            return g_resident[id].rec;
        }
    }
    if (g_pool_used + n > g_pool_cap || (g_texrec_used + TEXREC_WORDS) * 4 > TEXREC_BYTES) return NO_TEXTURE - 1; /* full */
    rec = (uint32_t*)g_texrec_map + g_texrec_used;
    memset(rec, 0, TEXREC_WORDS * 4);
    for (l = 0; l < C->nlevels && l < MAX_MIPS; l++) {
        size_t texels = (size_t)C->lw[l] * C->lh[l];
        rec[l] = g_pool_used;
        rec[11 + l] = (uint32_t)C->lw[l];
        rec[22 + l] = (uint32_t)C->lh[l];
        memcpy(g_pool_map + (size_t)g_pool_used * 4, C->level[l], texels * 4);
        g_pool_used += (uint32_t)texels;
    }
    g_resident[id].gen = C->tex_gen;
    g_resident[id].rec = g_texrec_used;
    g_resident[id].epoch = g_epoch;
    g_texrec_used += TEXREC_WORDS;
    return g_resident[id].rec;
}

static uint32_t float_bits(float f)
{
    uint32_t u;
    memcpy(&u, &f, 4);
    return u;
}

/* The draw's record, as raster.frag's header lays it out; each map a stage
 * samples uploaded first. 0 when the pool cannot take them, and nothing was
 * written: the caller submits, which frees the pool, and asks again. Built
 * here and copied out whole: dst is mapped device memory, uncached, where
 * every |= below would be a read across the bus (V6a's profile put
 * gxv_pack_tev, writing there, first among the consumer's own work). */
static int draw_record(const DrawCmd* D, uint32_t* dst, uint32_t* tev)
{
    uint32_t r[GXV_DRAW_WORDS];
    uint32_t recs[8];
    unsigned st, m, i, needed = 0, maps = 0;
    for (m = 0; m < 8; m++) recs[m] = NO_TEXTURE;
    for (st = 0; st < D->tev.stages; st++)
        if (D->tev.st[st].texen) maps |= 1u << (D->tev.st[st].texmap & 7);
    for (m = 0; m < 8; m++)
        if ((maps >> m) & 1) needed += tex_texels(&D->tev.tex[m]);
    if (g_pool_used + needed > g_pool_cap || (g_texrec_used + 8 * TEXREC_WORDS) * 4 > TEXREC_BYTES) return 0;
    for (m = 0; m < 8; m++)
        if ((maps >> m) & 1) recs[m] = upload_texture(&D->tev.tex[m]);
    memset(r, 0, sizeof r);
    gxv_pack_tev(&D->tev, r);
    memcpy(tev, r, GXV_TEV_WORDS * sizeof *tev); /* the pipeline's shape is taken from these */
    r[98] = (D->ntex & 255) | (D->nchan & 3) << 8 | (D->miptex & 255) << 16;
    for (i = 0; i < 8; i++) r[99] |= (uint32_t)(D->texmap_of[i] & 7) << (3 * i);
    r[100] = (D->px.fog_type & 7) | (D->px.fog_proj & 1) << 3 | (D->px.fog_b_shift & 31) << 8;
    r[101] = float_bits(D->px.fog_a);
    r[102] = float_bits(D->px.fog_c);
    r[103] = D->px.fog_b_mag;
    r[104] = (uint32_t)D->px.fog_color[0] | (uint32_t)D->px.fog_color[1] << 8 | (uint32_t)D->px.fog_color[2] << 16;
    {
        int lop = draw_lop(D), route = logic_route(D, lop);
        uint32_t masks = (D->px.col_upd ? 1u : 0u) | (D->px.alpha_upd ? 2u : 0u);
        if (route == LOGIC_SNAPSHOT) r[105] = 1u | (uint32_t)lop << 1;
        if (route == LOGIC_INTERLOCK) r[105] = 1u | (uint32_t)lop << 1 | masks << 5;
    }
    for (m = 0; m < 8; m++) {
        const TexCfg* C = &D->tev.tex[m];
        uint32_t* w = r + 108 + 12 * m;
        w[0] = recs[m];
        if (recs[m] == NO_TEXTURE) continue;
        w[1] = (C->wrap_s & 3) | (C->wrap_t & 3) << 2 | (C->linear ? 16u : 0u) | (C->mip ? 32u : 0u);
        w[2] = float_bits(C->lod_bias);
        w[3] = float_bits(C->min_lod);
        w[4] = float_bits(C->max_lod);
        w[5] = float_bits(C->scale_s);
        w[6] = float_bits(C->scale_t);
        w[7] = float_bits(C->su0);
        w[8] = float_bits(C->sv0);
        w[9] = (uint32_t)C->nlevels;
        w[10] = (uint32_t)C->w;
        w[11] = (uint32_t)C->h;
    }
    memcpy(dst, r, sizeof r);
    return 1;
}

static int tmp_reserve(unsigned n)
{
    if (n <= g_tmp_cap) return 1;
    {
        unsigned cap = g_tmp_cap ? g_tmp_cap : 1024;
        Vertex* p;
        while (cap < n) cap *= 2;
        p = (Vertex*)realloc(g_tmp, (size_t)cap * sizeof(Vertex));
        if (!p) { say("cannot allocate %u vertices for a rebuilt draw", cap); return 0; }
        g_tmp = p;
        g_tmp_cap = cap;
    }
    return 1;
}

static unsigned g_tmp_n;
static int tmp_push(const Vertex* v)
{
    if (!tmp_reserve(g_tmp_n + 1)) return 0;
    g_tmp[g_tmp_n++] = *v;
    return 1;
}

/* One triangle as the CPU's emit_triangle takes it: wholly inside, copied in
 * its vertex order; crossing, through the renderer's own clip_polygon and
 * fanned from its first vertex; nothing left, dropped. */
static int rebuild_triangle(const Vertex* a, const Vertex* b, const Vertex* c)
{
    Vertex in[3], out[16];
    unsigned n, i;
    if (gxr_vertex_unclipped(a) && gxr_vertex_unclipped(b) && gxr_vertex_unclipped(c))
        return tmp_push(a) && tmp_push(b) && tmp_push(c);
    in[0] = *a;
    in[1] = *b;
    in[2] = *c;
    n = gxr_clip_polygon(in, 3, out);
    for (i = 1; i + 1 < n; i++)
        if (!tmp_push(&out[0]) || !tmp_push(&out[i]) || !tmp_push(&out[i + 1])) return 0;
    return 1;
}

/* A draw with a vertex outside the CPU's clip volume, rebuilt as a list in
 * the order draw_command walks it (3.3). Lines and points are not clipped on
 * the CPU: a segment or point with w <= 0 is skipped, and the rest drawn. */
static int rebuild(const DrawCmd* D, int* topo)
{
    const Vertex* v = D->v;
    unsigned count = D->count, i;
    g_tmp_n = 0;
    switch (D->prim) {
    case 0x80:
        for (i = 0; i + 3 < count; i += 4)
            if (!rebuild_triangle(&v[i], &v[i + 1], &v[i + 2]) || !rebuild_triangle(&v[i], &v[i + 2], &v[i + 3])) return 0;
        *topo = T_TRIS;
        break;
    case 0x90:
        for (i = 0; i + 2 < count; i += 3)
            if (!rebuild_triangle(&v[i], &v[i + 1], &v[i + 2])) return 0;
        *topo = T_TRIS;
        break;
    case 0x98:
        for (i = 2; i < count; i++)
            if (!((i & 1) ? rebuild_triangle(&v[i - 1], &v[i - 2], &v[i]) : rebuild_triangle(&v[i - 2], &v[i - 1], &v[i]))) return 0;
        *topo = T_TRIS;
        break;
    case 0xA0:
        for (i = 2; i < count; i++)
            if (!rebuild_triangle(&v[0], &v[i - 1], &v[i])) return 0;
        *topo = T_TRIS;
        break;
    case 0xA8:
        for (i = 0; i + 1 < count; i += 2)
            if (v[i].w > 0.0f && v[i + 1].w > 0.0f && (!tmp_push(&v[i]) || !tmp_push(&v[i + 1]))) return 0;
        *topo = T_LINES;
        break;
    case 0xB0:
        for (i = 1; i < count; i++)
            if (v[i - 1].w > 0.0f && v[i].w > 0.0f && (!tmp_push(&v[i - 1]) || !tmp_push(&v[i]))) return 0;
        *topo = T_LINES;
        break;
    case 0xB8:
        for (i = 0; i < count; i++)
            if (v[i].w > 0.0f && !tmp_push(&v[i])) return 0;
        *topo = T_POINTS;
        break;
    default: break;
    }
    return 1;
}

static int needs_rebuild(const DrawCmd* D)
{
    unsigned i;
    int tri = D->prim < 0xA8;
    if (g_mut_unclipped) return 0;
    for (i = 0; i < D->count; i++)
        if (tri ? !gxr_vertex_unclipped(&D->v[i]) : !(D->v[i].w > 0.0f)) return 1;
    return 0;
}

static int efb_to_buffer(VkPipelineStageFlags reader);

static void describe_draw(const DrawCmd* D)
{
    unsigned st, i;
    say("draw %llu: prim %#x, %u vertices, cull %u, scissor %d,%d-%d,%d, z_en %d z_func %u z_upd %d, blend %d (%u, %u, sub %d), "
        "logic %d (%u), masks %d%d, ntex %#x nchan %#x, %u stages, fast %u/%u, alpha_always %d, fog %u",
        g_n_draws, D->prim, D->count, D->rc.cull, D->rc.scissor.x0, D->rc.scissor.y0, D->rc.scissor.x1, D->rc.scissor.y1,
        D->px.z_en, D->px.z_func, D->px.z_upd, D->px.blend_en, D->px.sfac, D->px.dfac, D->px.subtract, D->px.logic_en,
        D->px.lop, D->px.col_upd, D->px.alpha_upd, D->ntex, D->nchan, D->tev.stages, D->tev.fast_c, D->tev.fast_a,
        D->tev.alpha_always, D->px.fog_type);
    for (st = 0; st < D->tev.stages; st++) {
        const Stage* S = &D->tev.st[st];
        if (!S->texen) continue;
        {
            const TexCfg* C = &D->tev.tex[S->texmap];
            say("  stage %u samples map %u (coord %u): %dx%d, %d levels, linear %d, mip %d, wrap %u/%u, lod %.2f..%.2f bias %.2f, scale %.0fx%.0f",
                st, S->texmap, S->texcoord, C->w, C->h, C->nlevels, C->linear, C->mip, C->wrap_s, C->wrap_t, C->min_lod, C->max_lod,
                C->lod_bias, C->scale_s, C->scale_t);
        }
    }
    say("  viewport wd %.3f ht %.3f xorig %.3f yorig %.3f zrange %.1f farz %.1f", D->rc.wd, D->rc.ht, D->rc.xorig, D->rc.yorig,
        D->rc.zrange, D->rc.farz);
    for (i = 0; i < D->count && i < 16; i++) {
        const Vertex* v = &D->v[i];
        float iw = v->w != 0.0f ? 1.0f / v->w : 0.0f;
        say("  v%u clip (%.9g, %.9g, %.9g, %.9g) screen (%.2f, %.2f) depth %.6f col0 (%.2f %.2f %.2f %.2f) tex0 (%.4f, %.4f, %.4f)", i,
            v->x, v->y, v->z, v->w, D->rc.xorig + v->x * iw * D->rc.wd, D->rc.yorig + v->y * iw * D->rc.ht,
            (D->rc.farz + v->z * iw * D->rc.zrange) / 16777216.0f, v->col[0].r, v->col[0].g, v->col[0].b, v->col[0].a,
            v->tex[0][0], v->tex[0][1], v->tex[0][2]);
    }
}

static int gxv_draw(const DrawCmd* D)
{
    const char* why = unsupported(D);
    const Vertex* up = D->v;
    unsigned n = D->count, first;
    int topo, rebuilt = 0, quads = 0;
    const Rect* s = &D->rc.scissor;
    VkRect2D sc;
    PushDraw pc;
    uint32_t tev[GXV_TEV_WORDS]; /* the draw's TEV words, for its pipeline */
    int route;
    PipeState ps; /* the draw's state, which dynamic state sets (V7) */
    VkPipeline p;

    static int ztop_said;
    if (why) { say("draw refused: it needs %s", why); return 0; }
    /* The late depth test the shader gives is the CPU's order except for a
     * ztop draw whose alpha test can reject, which the corpus has none of
     * (3.4); said once if one comes. */
    if (D->px.ztop && !D->tev.alpha_always && !ztop_said++)
        say("draw %llu, after %llu screen copies, is ztop with an alpha test that can reject: the GPU tests depth "
            "after the TEV, the CPU before (tripwire, 3.4; SOA_GPU_DRAW=%llu describes it)",
            g_n_draws + 1, g_n_copies, g_n_draws + 1);
    switch (D->prim) {
    case 0x80: topo = T_TRIS; quads = 1; n = n / 4 * 4; break;
    case 0x90: topo = T_TRIS; n = n / 3 * 3; break;
    case 0x98: topo = T_STRIP; break;
    case 0xA0: topo = T_FAN; break;
    case 0xA8: topo = T_LINES; n = n / 2 * 2; break;
    case 0xB0: topo = T_LSTRIP; break;
    case 0xB8: topo = T_POINTS; break;
    default: say("draw refused: primitive %#x", D->prim); return 0;
    }
    g_n_draws++;
    if (g_skip_draw && g_n_draws == g_skip_draw) return 1;
    {
        /* SOA_GPU_DRAW=N: draw N's state, for a bisection's first diverging draw. */
        static long long want = -2;
        if (want == -2) want = getenv("SOA_GPU_DRAW") ? atoll(getenv("SOA_GPU_DRAW")) : -1;
        if ((long long)g_n_draws == want) describe_draw(D);
    }
    if (needs_rebuild(D)) {
        if (!rebuild(D, &topo)) return 0;
        up = g_tmp;
        n = g_tmp_n;
        quads = 0;
        rebuilt = 1;
        g_n_rebuilt++;
    }
    if (g_hook) g_hook(D, up, n, rebuilt);
    if (n == 0) return 1;
    if (quads && n / 4 > MAX_QUADS) { say("draw refused: %u quads, more than the index buffer's %u", n / 4, MAX_QUADS); return 0; }
    if ((size_t)n * sizeof(Vertex) > RING_BYTES) { say("draw refused: %u vertices do not fit the vertex ring", n); return 0; }
    /* The scissor, inclusive, on the EFB; an empty one draws nothing. */
    {
        int x0 = s->x0 < 0 ? 0 : s->x0, y0 = s->y0 < 0 ? 0 : s->y0;
        int x1 = s->x1 > EFB_W - 1 ? EFB_W - 1 : s->x1, y1 = s->y1 > EFB_H - 1 ? EFB_H - 1 : s->y1;
        if (x1 < x0 || y1 < y0) return 1;
        sc.offset.x = x0;
        sc.offset.y = y0;
        sc.extent.width = (uint32_t)(x1 - x0 + 1);
        sc.extent.height = (uint32_t)(y1 - y0 + 1);
    }
    if (g_ring_used + (size_t)n * sizeof(Vertex) > RING_BYTES && !submit_wait()) return 0;
    if ((g_draw_used + GXV_DRAW_WORDS) * 4 > DRAWREC_BYTES && !submit_wait()) return 0;
    if (!draw_record(D, (uint32_t*)g_draw_map + g_draw_used, tev)) {
        if (!submit_wait()) return 0;
        if (!draw_record(D, (uint32_t*)g_draw_map + g_draw_used, tev)) {
            say("draw refused: its textures do not fit the %u-texel pool", g_pool_cap);
            return 0;
        }
    }
    route = logic_route(D, draw_lop(D));
    if (route >= 0) {
        g_n_logic++;
        g_logic_routes[route]++;
        /* The EFB as it is before this draw, where the shader reads the
         * destination from. Exact while the draw's triangles do not overlap
         * each other, which every logic draw here satisfies (one full-screen
         * quad each, 3.5); the interlock route is for those that may. */
        if (route == LOGIC_SNAPSHOT && !efb_to_buffer(VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT)) return 0;
    }
    if (route == LOGIC_INTERLOCK ? !begin_interlock() : !begin_pass()) return 0;
    p = pipeline(topo, D, tev, &ps);
    if (!p) return 0;
    first = g_ring_used / (uint32_t)sizeof(Vertex);
    memcpy(g_ring_map + g_ring_used, up, (size_t)n * sizeof(Vertex));
    g_ring_used += n * (uint32_t)sizeof(Vertex);
    g_n_verts += n;
    if (p != g_bound) { vkCmdBindPipeline(g_cb, VK_PIPELINE_BIND_POINT_GRAPHICS, p); g_bound = p; }
    vkCmdSetScissor(g_cb, 0, 1, &sc);
    if (g_eds) {
        /* What the pipeline no longer holds; the interlock's pass has no depth. */
        int il = route == LOGIC_INTERLOCK;
        int cull = (int)ps.cull, zen = il ? 0 : ps.z_en, zupd = il ? 0 : ps.z_upd, zf = (int)ps.zf;
        if (cull != g_dyn_cull) { p_vkCmdSetCullModeEXT(g_cb, k_cull[cull]); g_dyn_cull = cull; }
        if (ps.topo != g_dyn_topo) { p_vkCmdSetPrimitiveTopologyEXT(g_cb, k_topo[ps.topo]); g_dyn_topo = ps.topo; }
        if (zen != g_dyn_zen) { p_vkCmdSetDepthTestEnableEXT(g_cb, (VkBool32)zen); g_dyn_zen = zen; }
        if (zupd != g_dyn_zupd) { p_vkCmdSetDepthWriteEnableEXT(g_cb, (VkBool32)zupd); g_dyn_zupd = zupd; }
        if (zf != g_dyn_zf) { p_vkCmdSetDepthCompareOpEXT(g_cb, k_zfunc[zf]); g_dyn_zf = zf; }
    }
    pc.wd = D->rc.wd;
    pc.ht = D->rc.ht;
    pc.xorig = D->rc.xorig;
    pc.yorig = D->rc.yorig;
    pc.zrange = D->rc.zrange;
    pc.farz = D->rc.farz;
    pc.base = first;
    pc.record = g_draw_used;
    g_draw_used += GXV_DRAW_WORDS;
    vkCmdPushConstants(g_cb, g_layout, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof pc, &pc);
    if (g_measure && g_occ_used == OCC_QUERIES) {
        say("measure: more than %u draws in one submission; the rest are not counted", OCC_QUERIES);
        g_measure = 0;
    }
    if (g_measure) {
        g_occ_draw[g_occ_used] = g_n_draws;
        vkCmdBeginQuery(g_cb, g_occ, g_occ_used, g_precise ? VK_QUERY_CONTROL_PRECISE_BIT : 0);
    }
    if (quads) vkCmdDrawIndexed(g_cb, n / 4 * 6, 1, 0, 0, 0);
    else vkCmdDraw(g_cb, n, 1, 0, 0);
    if (g_measure) vkCmdEndQuery(g_cb, g_occ, g_occ_used++);
    if (route == LOGIC_INTERLOCK) end_interlock();
    return 1;
}

/* efb_clear's rectangle and values, unmasked: vkCmdClearAttachments ignores
 * the pipeline's scissor and write masks, as the CPU's clear does. */
static int clear_rect(int x0, int y0, int w, int h, uint32_t ar, uint32_t gb, uint32_t z)
{
    VkClearAttachment ca[2];
    VkClearRect cr;
    int x1 = x0 + w, y1 = y0 + h;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > EFB_W) x1 = EFB_W;
    if (y1 > EFB_H) y1 = EFB_H;
    if (x1 <= x0 || y1 <= y0) return 1;
    if (!begin_pass()) return 0;
    memset(ca, 0, sizeof ca);
    ca[0].aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    ca[0].colorAttachment = 0;
    ca[0].clearValue.color.float32[0] = (float)(ar & 0xFF) / 255.0f;
    ca[0].clearValue.color.float32[1] = (float)((gb >> 8) & 0xFF) / 255.0f;
    ca[0].clearValue.color.float32[2] = (float)(gb & 0xFF) / 255.0f;
    ca[0].clearValue.color.float32[3] = (float)((ar >> 8) & 0xFF) / 255.0f;
    ca[1].aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
    ca[1].clearValue.depthStencil.depth = (float)(z & 0xFFFFFFu) / 16777216.0f;
    cr.rect.offset.x = x0;
    cr.rect.offset.y = y0;
    cr.rect.extent.width = (uint32_t)(x1 - x0);
    cr.rect.extent.height = (uint32_t)(y1 - y0);
    cr.baseArrayLayer = 0;
    cr.layerCount = 1;
    vkCmdClearAttachments(g_cb, 2, ca, 1, &cr);
    g_n_clears++;
    return 1;
}

static int gxv_clear(const DrawCmd* D)
{
    int x0 = (int)(D->cp_tl & 0x3FF), y0 = (int)((D->cp_tl >> 10) & 0x3FF);
    int w = (int)(D->cp_wh & 0x3FF) + 1, h = (int)((D->cp_wh >> 10) & 0x3FF) + 1;
    return clear_rect(x0, y0, w, h, D->cp_ar, D->cp_gb, D->cp_z);
}

/* gxr_reset_efb's fill: the clear registers over the whole EFB, z 0 standing
 * for the farthest depth. */
static void gxv_reset_efb(const uint32_t* bp)
{
    uint32_t z = bp[0x51] & 0xFFFFFFu;
    if (!clear_rect(0, 0, EFB_W, EFB_H, bp[0x4F], bp[0x50], z ? z : 0xFFFFFFu)) say("the EFB reset failed");
}

/* ---- compute passes: the copies and tevdiff -------------------------------- */

/* A compute pipeline over a few storage buffers and a push constant block,
 * made on first use: a mutation picks the SPIR-V before that. */
typedef struct {
    VkDescriptorSetLayout dsl;
    VkPipelineLayout layout;
    VkDescriptorPool pool;
    VkDescriptorSet set;
    VkShaderModule mod;
    VkPipeline pipe;
} Compute;

static Compute g_copy_cs, g_tev_cs, g_lod_cs;

static int compute_make(Compute* c, const uint32_t* code, size_t bytes, unsigned nbuf, uint32_t push_bytes)
{
    VkDescriptorSetLayoutBinding b[5];
    VkDescriptorSetLayoutCreateInfo li = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, push_bytes};
    VkPipelineLayoutCreateInfo pli = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 5};
    VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    VkDescriptorSetAllocateInfo ai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    VkShaderModuleCreateInfo si = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    VkComputePipelineCreateInfo ci = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    unsigned i;
    for (i = 0; i < nbuf; i++) {
        b[i].binding = i;
        b[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        b[i].descriptorCount = 1;
        b[i].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        b[i].pImmutableSamplers = NULL;
    }
    li.bindingCount = nbuf;
    li.pBindings = b;
    VKCHECK(vkCreateDescriptorSetLayout(g_dev, &li, NULL, &c->dsl));
    pli.setLayoutCount = 1;
    pli.pSetLayouts = &c->dsl;
    pli.pushConstantRangeCount = 1;
    pli.pPushConstantRanges = &pr;
    VKCHECK(vkCreatePipelineLayout(g_dev, &pli, NULL, &c->layout));
    dpi.maxSets = 1;
    dpi.poolSizeCount = 1;
    dpi.pPoolSizes = &ps;
    VKCHECK(vkCreateDescriptorPool(g_dev, &dpi, NULL, &c->pool));
    ai.descriptorPool = c->pool;
    ai.descriptorSetCount = 1;
    ai.pSetLayouts = &c->dsl;
    VKCHECK(vkAllocateDescriptorSets(g_dev, &ai, &c->set));
    si.codeSize = bytes;
    si.pCode = code;
    VKCHECK(vkCreateShaderModule(g_dev, &si, NULL, &c->mod));
    ci.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    ci.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    ci.stage.module = c->mod;
    ci.stage.pName = "main";
    ci.layout = c->layout;
    VKCHECK(vkCreateComputePipelines(g_dev, g_pcache, 1, &ci, NULL, &c->pipe));
    return 1;
}

static void compute_bind(Compute* c, const VkBuffer* bufs, unsigned n)
{
    VkDescriptorBufferInfo bi[5];
    VkWriteDescriptorSet w[5];
    unsigned i;
    for (i = 0; i < n; i++) {
        bi[i].buffer = bufs[i];
        bi[i].offset = 0;
        bi[i].range = VK_WHOLE_SIZE;
        memset(&w[i], 0, sizeof w[i]);
        w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        w[i].dstSet = c->set;
        w[i].dstBinding = i;
        w[i].descriptorCount = 1;
        w[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        w[i].pBufferInfo = &bi[i];
    }
    vkUpdateDescriptorSets(g_dev, n, w, 0, NULL);
}

static void compute_free(Compute* c)
{
    if (c->pipe) vkDestroyPipeline(g_dev, c->pipe, NULL);
    if (c->mod) vkDestroyShaderModule(g_dev, c->mod, NULL);
    if (c->pool) vkDestroyDescriptorPool(g_dev, c->pool, NULL);
    if (c->layout) vkDestroyPipelineLayout(g_dev, c->layout, NULL);
    if (c->dsl) vkDestroyDescriptorSetLayout(g_dev, c->dsl, NULL);
    memset(c, 0, sizeof *c);
}

static void run_compute(Compute* c, const void* push, uint32_t push_bytes, uint32_t count)
{
    vkCmdBindPipeline(g_cb, VK_PIPELINE_BIND_POINT_COMPUTE, c->pipe);
    vkCmdBindDescriptorSets(g_cb, VK_PIPELINE_BIND_POINT_COMPUTE, c->layout, 0, 1, &c->set, 0, NULL);
    vkCmdPushConstants(g_cb, c->layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, push_bytes, push);
    vkCmdDispatch(g_cb, (count + 63) / 64, 1, 1);
}

/* Everything the compute passes wrote, visible to the host. */
static void compute_to_host(void)
{
    VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER};
    mb.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    mb.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
}

/* ---- copies ----------------------------------------------------------------- */

/* The push constants copy.comp reads (its Copy block). */
typedef struct {
    int32_t x0, y0, w, h;
    uint32_t mode, texfmt, flags, chans, taps, row_bytes, ow, oh, count;
    uint32_t dest_at, image_at, pool_at; /* the copy's regions, in words (V7) */
    uint32_t screen_at;                  /* a screen copy's slot, in words (V8) */
} CopyPush;

/* gxr.c's copy_texfmt, copy_row_stride and copy_extent, and copy_to_texture's
 * channel choice, written again here because they are static there. copydiff
 * holds the two sides to the same bytes, so they cannot drift apart
 * unnoticed. 99 is a copy the CPU refuses. */
static unsigned copy_texfmt(uint32_t v, unsigned* chan_a, unsigned* chan_b)
{
    unsigned tpf = (v >> 3) & 15, fmt = tpf / 2 + (tpf & 1) * 8;
    *chan_a = 0;
    *chan_b = 3;
    if ((v >> 15) & 1) return fmt <= 3 ? fmt : 99;
    switch (fmt) {
    case 0: return 0;
    case 1: case 8: return 1;
    case 9: *chan_a = 1; return 1;
    case 10: *chan_a = 2; return 1;
    case 7: *chan_a = 3; return 1;
    case 2: return 2;
    case 3: return 3;
    case 11: *chan_b = 1; return 3;
    case 12: *chan_a = 1; *chan_b = 2; return 3;
    case 4: return 4;
    case 5: return 5;
    case 6: return 6;
    default: return 99;
    }
}

static void tile_shape(unsigned texfmt, unsigned* tw, unsigned* th, unsigned* bpt)
{
    switch (texfmt) {
    case 0: *tw = 8; *th = 8; *bpt = 32; break;
    case 1: case 2: *tw = 8; *th = 4; *bpt = 32; break;
    case 3: case 4: case 5: *tw = 4; *th = 4; *bpt = 32; break;
    default: *tw = 4; *th = 4; *bpt = 64; break;
    }
}

static unsigned g_img_w, g_img_h, g_img_at; /* the last copy's image, for the self test and copydiff */
static unsigned long long g_n_tex_copies, g_n_refused;

/* The EFB's colour into the readback buffer, where the copy shader reads it. */
static int efb_to_buffer(VkPipelineStageFlags reader)
{
    VkBufferImageCopy rg;
    VkBufferMemoryBarrier bb = {VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};
    VkMemoryBarrier war = {VK_STRUCTURE_TYPE_MEMORY_BARRIER};
    if (!begin_cb()) return 0;
    end_pass();
    /* A snapshot or copy before this one may still be read. */
    war.srcAccessMask = VK_ACCESS_SHADER_READ_BIT;
    war.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT | VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &war, 0, NULL, 0, NULL);
    barrier_image(g_color, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                  VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
                  VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_READ_BIT);
    memset(&rg, 0, sizeof rg);
    rg.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    rg.imageSubresource.layerCount = 1;
    rg.imageExtent.width = EFB_W;
    rg.imageExtent.height = EFB_H;
    rg.imageExtent.depth = 1;
    vkCmdCopyImageToBuffer(g_cb, g_color, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, g_readback, 1, &rg);
    barrier_image(g_color, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                  VK_PIPELINE_STAGE_TRANSFER_BIT, 0, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                  VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT);
    bb.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    bb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
    bb.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    bb.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    bb.buffer = g_readback;
    bb.size = VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_TRANSFER_BIT, reader, 0, 0, NULL, 1, &bb, 0, NULL);
    return 1;
}

static int copy_pipeline(void)
{
    VkBuffer bufs[5];
    const uint32_t* code = copy_comp;
    size_t bytes = sizeof copy_comp;
    if (g_copy_cs.pipe) return 1;
    if (g_mut_copy == 1) { code = copy_comp_rounding; bytes = sizeof copy_comp_rounding; }
    if (g_mut_copy == 2) { code = copy_comp_intensity; bytes = sizeof copy_comp_intensity; }
    if (!compute_make(&g_copy_cs, code, bytes, 5, sizeof(CopyPush))) return 0;
    bufs[0] = g_readback;
    bufs[1] = g_destbuf;
    bufs[2] = g_imagebuf;
    bufs[3] = g_screenbuf;
    bufs[4] = g_poolbuf;
    compute_bind(&g_copy_cs, bufs, 5);
    return 1;
}

static void copy_rect(const DrawCmd* D, CopyPush* p)
{
    memset(p, 0, sizeof *p);
    p->x0 = (int32_t)(D->cp_tl & 0x3FF);
    p->y0 = (int32_t)((D->cp_tl >> 10) & 0x3FF);
    p->w = (int32_t)(D->cp_wh & 0x3FF) + 1;
    p->h = (int32_t)((D->cp_wh >> 10) & 0x3FF) + 1;
    p->taps = D->cp_f_up | (uint32_t)D->cp_f_mid << 8 | (uint32_t)D->cp_f_dn << 16;
    if (!(D->cp_f_up == 0 && D->cp_f_dn == 0 && D->cp_f_mid == 64)) p->flags |= 4u;
}

/* The screen buffer's slots (V8): three for the presenter's triple buffer;
 * a fourth, SCREEN_SCRATCH, for gxv_read_depth and the presenter's check;
 * and a fifth, SCREEN_HOST, the window's own frame (V8b: P5a's filters,
 * which run on the CPU, then presented by the GPU). The consumer writes g_scr_back; g_scr_middle is the newest it has
 * finished, with SCREEN_FRESH set until the presenter takes it, which it
 * does by swapping its own g_scr_front in; so neither ever writes or reads
 * a slot the other holds. A slot's size is written before it is published. */
#define SCREEN_SLOTS 5
#define SCREEN_SCRATCH 3
#define SCREEN_HOST 4
#define SCREEN_FRESH 4
static unsigned g_scr_back = 0, g_scr_front = 2;
static plat_a64 g_scr_middle = 1;
static int g_scr_w[SCREEN_SLOTS], g_scr_h[SCREEN_SLOTS];

/* A copy to the screen, as copy_to_screen makes it: min(w, 640) by
 * min(h, 528), the filter on RGB, alpha 255, black outside the EFB. */
static int copy_screen(const DrawCmd* D)
{
    CopyPush p;
    int sw, sh;
    copy_rect(D, &p);
    if (g_mut_nofilter) p.flags &= ~4u;
    sw = p.w > EFB_W ? EFB_W : p.w;
    sh = p.h > EFB_H ? EFB_H : p.h;
    p.mode = 2;
    p.count = (uint32_t)(sw * sh);
    p.screen_at = g_scr_back * (READBACK_BYTES / 4);
    if (!copy_pipeline() || !efb_to_buffer(VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT)) return 0;
    run_compute(&g_copy_cs, &p, sizeof p, p.count);
    compute_to_host();
    if (!submit_wait()) return 0;
    gxr_backend_screen(g_screen_map + (size_t)g_scr_back * READBACK_BYTES, sw, sh);
    g_scr_w[g_scr_back] = sw;
    g_scr_h[g_scr_back] = sh;
    g_scr_back = (unsigned)(plat_xchg64(&g_scr_middle, (int64_t)(g_scr_back | SCREEN_FRESH)) & 3);
    g_n_copies++;
    return 1;
}

/* A copy still to land whose bytes overlap [guest, guest + bytes). */
static int land_overlaps(uint32_t guest, uint32_t bytes)
{
    unsigned i;
    for (i = 0; i < g_land_n; i++)
        if (guest < g_land[i].guest + g_land[i].extent && guest + bytes > g_land[i].guest) return 1;
    return 0;
}

/* A submission made to land copies -- the report's readback waits, which
 * the copies to a texture must outnumber (V7's Done). */
static int land_wait(void)
{
    if (g_land_n) g_n_land_waits++;
    return submit_wait();
}

/* A copy to a texture, as copy_to_texture makes it: the bytes into guest
 * RAM over the copy's span, and its decoded image -- into the pool for the
 * draws after it in this submission (V7's copy image), and into the
 * producer's image when it lands. A format the CPU refuses, or a span past
 * the end of memory, leaves RAM untouched, as there. */
static int copy_texture(const DrawCmd* D)
{
    CopyPush p;
    unsigned chan_a, chan_b, texfmt = copy_texfmt(D->cp_v, &chan_a, &chan_b), tw, th, bpt;
    uint32_t dest = (D->cp_dest & 0x1FFFFFu) << 5, natural, row_bytes, rows, cols, extent, texels;
    int half = (D->cp_v >> 9) & 1;
    uint8_t* ram;
    if (texfmt == 99) { g_n_refused++; return 1; }
    if (g_mut_skip_copies) return 1;
    if (g_mut_dest32) dest += 32;
    copy_rect(D, &p);
    p.ow = (uint32_t)(half ? p.w / 2 : p.w);
    p.oh = (uint32_t)(half ? p.h / 2 : p.h);
    tile_shape(texfmt, &tw, &th, &bpt);
    natural = (p.ow + tw - 1) / tw * bpt;
    row_bytes = (D->cp_stride & 0x3FFu) * 32u;
    if (row_bytes < natural) row_bytes = natural;
    rows = (p.oh + th - 1) / th;
    cols = (p.ow + tw - 1) / tw;
    extent = rows && cols ? (rows - 1) * row_bytes + cols * bpt : 0;
    if ((dest & MEM_MASK) + (size_t)extent > MEM1_SIZE) { g_n_refused++; return 1; }
    if (extent > DEST_BYTES || (size_t)p.ow * p.oh * 4 > IMAGE_BYTES) {
        say("copy refused: %ux%u, %u bytes, more than the copy buffers hold", p.ow, p.oh, extent);
        return 0;
    }
    if (!extent) return 1;
    texels = p.ow * p.oh;
    /* Regions of its own in this submission, and no copy still to land under
     * its bytes, whose seed must hold what that copy wrote. */
    if (g_land_n == LAND_MAX || g_dest_used + extent > DEST_BYTES || g_image_used + texels > IMAGE_BYTES / 4 ||
        land_overlaps(dest & MEM_MASK, extent)) {
        if (!land_wait()) return 0;
    }
    if (g_pool_used + texels > g_pool_cap || (g_texrec_used + TEXREC_WORDS) * 4 > TEXREC_BYTES) {
        if (!submit_wait()) return 0;
    }
    p.texfmt = texfmt;
    p.flags |= ((D->cp_v >> 15) & 1) | (uint32_t)half << 1 | 8u;
    p.chans = chan_a | chan_b << 2;
    p.row_bytes = row_bytes;
    p.dest_at = g_dest_used / 4;
    p.image_at = g_image_used;
    p.pool_at = g_pool_used;
    ram = mem_ptr(D->s, dest | 0x80000000u);
    /* Seeded from RAM: what the copy does not write keeps its bytes.
     * --mutate unseeded writes back whatever the buffer held instead. */
    if (!g_mut_unseeded) memcpy(g_dest_map + g_dest_used, ram, extent);
    if (!copy_pipeline() || !efb_to_buffer(VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT)) return 0;
    p.mode = 0;
    p.count = extent / 4;
    run_compute(&g_copy_cs, &p, sizeof p, p.count);
    p.mode = 1;
    p.count = texels;
    run_compute(&g_copy_cs, &p, sizeof p, p.count);
    compute_to_host();
    {
        /* The image in the pool, for the draws after it in this submission. */
        VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER};
        uint32_t* rec = (uint32_t*)g_texrec_map + g_texrec_used;
        mb.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
        mb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
        vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, 0, 1, &mb, 0, NULL, 0,
                             NULL);
        memset(rec, 0, TEXREC_WORDS * 4);
        rec[0] = g_pool_used;
        rec[11] = p.ow;
        rec[22] = p.oh;
        if (D->cp_image) {
            g_cimg[g_cimg_n].cpu = D->cp_image;
            g_cimg[g_cimg_n].rec = g_texrec_used;
            g_cimg_n++;
        }
        g_texrec_used += TEXREC_WORDS;
        g_pool_used += texels;
    }
    g_land[g_land_n].ram = ram;
    g_land[g_land_n].guest = dest & MEM_MASK;
    g_land[g_land_n].dest_at = g_dest_used;
    g_land[g_land_n].extent = extent;
    g_land[g_land_n].image = D->cp_image;
    g_land[g_land_n].image_at = g_image_used;
    g_land[g_land_n].texels = texels;
    g_land_n++;
    g_img_at = g_image_used;
    g_dest_used += extent;
    g_image_used += texels;
    /* For ramdiff: which bytes, and the EFB as of which draw. A frame makes
     * two or three; a live run makes one or two a frame, which the report
     * counts instead of listing. */
    if (g_n_tex_copies < 8)
        say("copy to texture at %08X, %u bytes, format %u, after draw %llu", dest, extent, texfmt, g_n_draws);
    else if (g_n_tex_copies == 8)
        say("copies to a texture after the eighth are counted in the report, not listed");
    g_img_w = p.ow;
    g_img_h = p.oh;
    g_n_tex_copies++;
    /* V6's protocol, a mutation now, and late-readback's base. */
    if ((g_mut_land_at_copy || g_mut_late) && !land_wait()) return 0;
    return 1;
}

static int gxv_copy(const DrawCmd* D)
{
    return (D->cp_v & 0x4000u) ? copy_screen(D) : copy_texture(D);
}

/* The depth buffer as 24-bit values, 640x528, for a bisection to compare
 * with the CPU's g_efb_z: what each pixel's depth test was against. */
int gxv_read_depth(uint32_t* out)
{
    VkBufferImageCopy rg;
    VkBufferMemoryBarrier bb = {VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};
    unsigned i;
    if (!begin_cb()) return 0;
    end_pass();
    barrier_image(g_depth, VK_IMAGE_ASPECT_DEPTH_BIT, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                  VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT,
                  VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_READ_BIT);
    memset(&rg, 0, sizeof rg);
    rg.bufferOffset = (VkDeviceSize)SCREEN_SCRATCH * READBACK_BYTES; /* not a slot the presenter may hold */
    rg.imageSubresource.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
    rg.imageSubresource.layerCount = 1;
    rg.imageExtent.width = EFB_W;
    rg.imageExtent.height = EFB_H;
    rg.imageExtent.depth = 1;
    vkCmdCopyImageToBuffer(g_cb, g_depth, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, g_screenbuf, 1, &rg);
    barrier_image(g_depth, VK_IMAGE_ASPECT_DEPTH_BIT, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL,
                  VK_PIPELINE_STAGE_TRANSFER_BIT, 0, VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT,
                  VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT);
    bb.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    bb.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    bb.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    bb.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    bb.buffer = g_screenbuf;
    bb.size = VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 0, NULL, 1, &bb, 0, NULL);
    if (!submit_wait()) return 0;
    for (i = 0; i < (unsigned)(EFB_W * EFB_H); i++) {
        float f;
        memcpy(&f, g_screen_map + (size_t)SCREEN_SCRATCH * READBACK_BYTES + 4 * (size_t)i, 4);
        out[i] = (uint32_t)(f * 16777216.0f); /* zq * 2^-24 exactly, as written */
    }
    return 1;
}

const uint8_t* gxv_last_copy_image(unsigned* w, unsigned* h)
{
    *w = g_img_w;
    *h = g_img_h;
    return g_image_map + (size_t)g_img_at * 4;
}

/* The self test's EFB, uploaded: the GPU's own copy of what the CPU path
 * holds in g_efb. */
int gxv_load_efb(const uint8_t* rgba)
{
    VkBufferImageCopy rg;
    if (!begin_cb()) return 0;
    end_pass();
    memcpy(g_readback_map, rgba, READBACK_BYTES);
    barrier_image(g_color, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                  VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
                  VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT);
    memset(&rg, 0, sizeof rg);
    rg.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    rg.imageSubresource.layerCount = 1;
    rg.imageExtent.width = EFB_W;
    rg.imageExtent.height = EFB_H;
    rg.imageExtent.depth = 1;
    vkCmdCopyBufferToImage(g_cb, g_readback, g_color, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &rg);
    barrier_image(g_color, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                  VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                  VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT);
    return submit_wait();
}

/* ---- the TEV ---------------------------------------------------------------- */

/* A TevSetup as tev.glsl reads it; its header describes the words. */
void gxv_pack_tev(const TevSetup* T, uint32_t* o)
{
    unsigned st, i, j;
    memset(o, 0, GXV_TEV_WORDS * sizeof *o);
    o[0] = T->stages;
    o[1] = (uint32_t)T->aref0 | (uint32_t)T->aref1 << 8 | T->acomp0 << 16 | T->acomp1 << 19 | T->alogic << 22;
    for (i = 0; i < 4; i++)
        for (j = 0; j < 4; j++) o[2 + i * 4 + j] = (uint32_t)T->reg_init[i][j];
    for (st = 0; st < T->stages && st < 16; st++) {
        const Stage* S = &T->st[st];
        uint32_t* w = o + 18 + st * 5;
        for (i = 0; i < 3; i++) {
            w[0] |= (uint32_t)S->ia[i] << (5 * i) | (uint32_t)S->ib[i] << (15 + 5 * i);
            w[1] |= (uint32_t)S->ic[i] << (5 * i) | (uint32_t)S->id[i] << (15 + 5 * i);
        }
        w[2] = (uint32_t)S->ja | (uint32_t)S->jb << 5 | (uint32_t)S->jc << 10 | (uint32_t)S->jd << 15 |
               (uint32_t)(S->texmap & 7) << 20 | (uint32_t)(S->texcoord & 7) << 23 | (uint32_t)(S->texen & 1) << 26 |
               (uint32_t)(S->chan & 7) << 27;
        w[3] = (uint32_t)S->cbias | (uint32_t)S->cop << 2 | (uint32_t)S->cclamp << 3 | (uint32_t)S->cshift << 4 |
               (uint32_t)S->cdest << 6 | (uint32_t)S->abias << 8 | (uint32_t)S->aop << 10 | (uint32_t)S->aclamp << 11 |
               (uint32_t)S->ashift << 12 | (uint32_t)S->adest << 14;
        for (i = 0; i < 4; i++) w[3] |= (uint32_t)(S->rswap[i] & 3) << (16 + 2 * i) | (uint32_t)(S->tswap[i] & 3) << (24 + 2 * i);
        for (i = 0; i < 4; i++) w[4] |= (uint32_t)(S->konst[i] & 0xFF) << (8 * i);
    }
}

static VkBuffer g_tev_setups, g_tev_inputs, g_tev_results;
static uint8_t *g_tev_setups_map, *g_tev_inputs_map, *g_tev_results_map;
static unsigned g_tev_cap;

/* tevdiff's GPU half: n packed setups (GXV_TEV_WORDS each) and their inputs
 * (ten words each: ras0, ras1, the eight maps' texels) through tevdiff.comp,
 * into two words a case: the RGBA bytes and the alpha test. The buffers are
 * made for the first n asked for, and a larger n later is refused. */
int gxv_tev_run(const uint32_t* setups, const uint32_t* inputs, uint32_t* results, unsigned n)
{
    struct { uint32_t count, setup_words; } p = {n, GXV_TEV_WORDS};
    if (!g_tev_cs.pipe) {
        VkBuffer bufs[3];
        const uint32_t* code = g_mut_tev ? tevdiff_comp_clamp : tevdiff_comp;
        size_t bytes = g_mut_tev ? sizeof tevdiff_comp_clamp : sizeof tevdiff_comp;
        if (!make_buffer((VkDeviceSize)n * GXV_TEV_WORDS * 4, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 0, &g_tev_setups, &g_tev_setups_map) ||
            !make_buffer((VkDeviceSize)n * 40, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 0, &g_tev_inputs, &g_tev_inputs_map) ||
            !make_buffer((VkDeviceSize)n * 8, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 1, &g_tev_results, &g_tev_results_map) ||
            !compute_make(&g_tev_cs, code, bytes, 3, sizeof p))
            return 0;
        bufs[0] = g_tev_setups;
        bufs[1] = g_tev_inputs;
        bufs[2] = g_tev_results;
        compute_bind(&g_tev_cs, bufs, 3);
        g_tev_cap = n;
    }
    if (n > g_tev_cap) { say("tevdiff: %u cases, more than the %u its buffers were made for", n, g_tev_cap); return 0; }
    memcpy(g_tev_setups_map, setups, (size_t)n * GXV_TEV_WORDS * 4);
    memcpy(g_tev_inputs_map, inputs, (size_t)n * 40);
    if (!begin_cb()) return 0;
    end_pass();
    run_compute(&g_tev_cs, &p, sizeof p, n);
    compute_to_host();
    if (!submit_wait()) return 0;
    memcpy(results, g_tev_results_map, (size_t)n * 8);
    return 1;
}

static VkBuffer g_lod_inputs, g_lod_results;
static uint8_t *g_lod_inputs_map, *g_lod_results_map;
static unsigned g_lod_cap;

/* loddiff's GPU half: n cases of one kind (GXV_LOD_WORDS words each; 0 the
 * level, 1 the formula, loddiff.comp says how they are laid out) through
 * lod.glsl, into three words a case. The --mutate lod and lodmin variants are
 * lod.glsl's. As with tevdiff, a larger n than the first is refused. */
int gxv_lod_run(unsigned kind, const uint32_t* inputs, uint32_t* results, unsigned n)
{
    struct { uint32_t count, kind; } p = {n, kind};
    if (!g_lod_cs.pipe) {
        VkBuffer bufs[2];
        const uint32_t* code = g_mut_frag == 2 ? loddiff_comp_lod : g_mut_lodmin ? loddiff_comp_lodmin : loddiff_comp;
        size_t bytes = g_mut_frag == 2 ? sizeof loddiff_comp_lod : g_mut_lodmin ? sizeof loddiff_comp_lodmin : sizeof loddiff_comp;
        if (!make_buffer((VkDeviceSize)n * GXV_LOD_WORDS * 4, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 0, &g_lod_inputs, &g_lod_inputs_map) ||
            !make_buffer((VkDeviceSize)n * 12, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 1, &g_lod_results, &g_lod_results_map) ||
            !compute_make(&g_lod_cs, code, bytes, 2, sizeof p))
            return 0;
        bufs[0] = g_lod_inputs;
        bufs[1] = g_lod_results;
        compute_bind(&g_lod_cs, bufs, 2);
        g_lod_cap = n;
    }
    if (n > g_lod_cap) { say("loddiff: %u cases, more than the %u its buffers were made for", n, g_lod_cap); return 0; }
    memcpy(g_lod_inputs_map, inputs, (size_t)n * GXV_LOD_WORDS * 4);
    if (!begin_cb()) return 0;
    end_pass();
    run_compute(&g_lod_cs, &p, sizeof p, n);
    compute_to_host();
    if (!submit_wait()) return 0;
    memcpy(results, g_lod_results_map, (size_t)n * 12);
    return 1;
}

static void gxv_finish(void)
{
    if (!land_wait()) say("a submission failed");
}

/* The consumer has nothing to run (V7): land what it holds, since a producer
 * waiting for that publishes nothing more. Nothing to land, nothing done --
 * the producer may be in reset_efb, after a drain, as this is called. */
static void timed_idle(void)
{
    uint64_t t0, w0;
    if (!g_land_n) return;
    late_land();
    t0 = plat_mono_ns();
    w0 = g_wait_ns;
    if (!land_wait()) say("a submission failed");
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
}

static int timed_draw(const DrawCmd* D)
{
    late_land();
    g_seq_cur = D->seq;
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    int r = gxv_draw(D);
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
    g_seq_cur = D->seq + 1;
    return r;
}

/* A frame's cost, each screen copy ending one (V6a's budget, 3.11): the
 * consumer's own time and the GPU's since the last, kept for the report's
 * p50, p95 and p99. The first FRAME_STATS frames are kept; the count goes on. */
#define FRAME_STATS 65536
static float g_frame_consumer_ms[FRAME_STATS], g_frame_gpu_ms[FRAME_STATS];
static unsigned g_frames_seen;
static uint64_t g_frame_consumer0;
static double g_frame_gpu0;

static void pcache_open(void)
{
    const char* path = getenv("SOA_GPU_PIPELINES");
    VkPipelineCacheCreateInfo ci = {VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO};
    void* data = NULL;
    long n = 0;
    FILE* f;
    if (path && (!strcmp(path, "off") || !strcmp(path, "0"))) return;
    snprintf(g_pcache_path, sizeof g_pcache_path, "%s", path && *path ? path : "build/gxv-pipelines.bin");
    f = fopen(g_pcache_path, "rb");
    if (f) {
        if (fseek(f, 0, SEEK_END) == 0 && (n = ftell(f)) > 0 && n < (64L << 20) && fseek(f, 0, SEEK_SET) == 0) {
            data = malloc((size_t)n);
            if (data && fread(data, 1, (size_t)n, f) != (size_t)n) {
                free(data);
                data = NULL;
            }
        }
        fclose(f);
    }
    ci.initialDataSize = data ? (size_t)n : 0;
    ci.pInitialData = data;
    if (vkCreatePipelineCache(g_dev, &ci, NULL, &g_pcache) != VK_SUCCESS) {
        ci.initialDataSize = 0; /* data the driver refused outright: start empty */
        ci.pInitialData = NULL;
        if (vkCreatePipelineCache(g_dev, &ci, NULL, &g_pcache) != VK_SUCCESS) g_pcache = VK_NULL_HANDLE;
    }
    g_pcache_loaded = data ? (size_t)n : 0;
    free(data);
}

/* Only the consumer calls this (and gxv_shutdown, after it has stopped);
 * the compiler thread may be making a pipeline through the cache meanwhile,
 * which the driver synchronises. Written beside and renamed over, so a run
 * killed mid-write leaves the old file. */
static void pcache_save(void)
{
    size_t n = 0;
    void* data;
    char tmp[600];
    FILE* f;
    if (!g_pcache || !g_pcache_path[0]) return;
    g_pipes_saved = g_n_pipes + (unsigned long long)plat_load64(&g_bg_made);
    g_pcache_saved_ns = plat_mono_ns();
    if (vkGetPipelineCacheData(g_dev, g_pcache, &n, NULL) != VK_SUCCESS || !n || !(data = malloc(n))) return;
    if (vkGetPipelineCacheData(g_dev, g_pcache, &n, data) == VK_SUCCESS) {
        snprintf(tmp, sizeof tmp, "%s.tmp", g_pcache_path);
        if ((f = fopen(tmp, "wb")) != NULL) {
            int ok = fwrite(data, 1, n, f) == n;
            ok = fclose(f) == 0 && ok;
            remove(ok ? g_pcache_path : tmp);
            if (ok && rename(tmp, g_pcache_path) != 0) remove(tmp);
        }
    }
    free(data);
}

static void frame_mark(void)
{
    if (g_n_pipes + (unsigned long long)plat_load64(&g_bg_made) != g_pipes_saved &&
        plat_mono_ns() - g_pcache_saved_ns > 1000000000ull)
        pcache_save();
    if (g_frames_seen < FRAME_STATS) {
        g_frame_consumer_ms[g_frames_seen] = (float)((double)(g_consumer_ns - g_frame_consumer0) / 1e6);
        g_frame_gpu_ms[g_frames_seen] = (float)(g_gpu_ms - g_frame_gpu0);
    }
    g_frames_seen++;
    g_frame_consumer0 = g_consumer_ns;
    g_frame_gpu0 = g_gpu_ms;
}

static int timed_copy(const DrawCmd* D)
{
    late_land();
    g_seq_cur = D->seq;
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    int r = gxv_copy(D);
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
    if (r && (D->cp_v & 0x4000u)) frame_mark();
    g_seq_cur = D->seq + 1;
    /* Nothing of this copy's, or before it, still to land: say so now. */
    if (!g_land_n) gxr_backend_landed(g_seq_cur);
    return r;
}

static int timed_clear(const DrawCmd* D)
{
    late_land();
    g_seq_cur = D->seq;
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    int r = gxv_clear(D);
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
    g_seq_cur = D->seq + 1;
    return r;
}

static void timed_reset_efb(const uint32_t* bp)
{
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    gxv_reset_efb(bp);
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
}

static void timed_finish(void)
{
    late_land();
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    gxv_finish();
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
}

/* Its own thread (V6a): the renderer runs every command on it, and the
 * producer calls nothing here but reset_efb, after a drain, when that thread
 * is idle. */
static const GxrBackend g_gxv = {"vulkan", timed_draw, timed_copy, timed_clear, timed_reset_efb, timed_finish, gxv_report, 1, 1,
                                  timed_idle};

const GxrBackend* gxv_backend(void) { return &g_gxv; }

int gxv_set_logicop(const char* mode)
{
    if (!strcmp(mode, "native")) {
        if (!g_has_logicop) { say("--logicop native: this device has no logicOp"); return 0; }
        g_logic_mode = LOGIC_NATIVE;
    } else if (!strcmp(mode, "blend")) g_logic_mode = LOGIC_BLEND;
    else if (!strcmp(mode, "snapshot")) g_logic_mode = LOGIC_SNAPSHOT;
    else if (!strcmp(mode, "interlock")) {
        if (!g_has_interlock) { say("--logicop interlock: this device has no fragment-shader interlock"); return 0; }
        g_logic_mode = LOGIC_INTERLOCK;
    } else return 0;
    return 1;
}
const char* gxv_device_name(void) { return g_devname; }
void gxv_set_upload_hook(GxvUploadHook h) { g_hook = h; }

int gxv_set_mutation(const char* name)
{
    if (!strcmp(name, "unclipped")) g_mut_unclipped = 1;
    else if (!strcmp(name, "unseeded")) g_mut_unseeded = 1;
    else if (!strcmp(name, "rounding")) g_mut_copy = 1;
    else if (!strcmp(name, "intensity")) g_mut_copy = 2;
    else if (!strcmp(name, "clamp")) g_mut_tev = 1;
    else if (!strcmp(name, "alpha")) g_mut_frag = 1;
    else if (!strcmp(name, "lod")) g_mut_frag = 2;
    else if (!strcmp(name, "fog")) g_mut_frag = 3;
    else if (!strcmp(name, "nofilter")) g_mut_nofilter = 1;
    else if (!strcmp(name, "noinvariant")) g_mut_noinvariant = 1;
    else if (!strcmp(name, "lodmin")) g_mut_lodmin = 1;
    else if (!strcmp(name, "pool-in-place")) g_mut_pool_inplace = 1;
    else if (!strcmp(name, "late-readback")) g_mut_late = 1;
    else if (!strcmp(name, "spec-stages")) g_mut_spec_stages = 1;
    else if (!strcmp(name, "compile-wait")) g_mut_compile_wait = 1;
    else if (!strcmp(name, "land-at-copy")) g_mut_land_at_copy = 1;
    else if (!strcmp(name, "cimg-cpu")) g_mut_cimg_cpu = 1;
    else if (!strcmp(name, "present")) g_mut_present = 1;
    else if (!strcmp(name, "measure")) g_measure = 1;
    else if (!strcmp(name, "logic-copy")) g_mut_logic = MUT_LOGIC_COPY;
    else if (!strcmp(name, "and-copy")) g_mut_logic = MUT_AND_COPY;
    else if (!strcmp(name, "or-copy")) g_mut_logic = MUT_OR_COPY;
    else if (!strcmp(name, "or-and")) g_mut_logic = MUT_OR_AND;
    else if (!strcmp(name, "skip-copies")) g_mut_skip_copies = 1;
    else if (!strcmp(name, "dest+32")) g_mut_dest32 = 1;
    else if (!strncmp(name, "skip-draw:", 10) && atoi(name + 10) > 0) g_skip_draw = (unsigned long long)atoi(name + 10);
    else return 0;
    return 1;
}

static int cmp_float(const void* a, const void* b)
{
    float x = *(const float*)a, y = *(const float*)b;
    return x < y ? -1 : x > y;
}

/* The per-frame line: p50, p95 and p99 of the consumer's and the GPU's
 * milliseconds a frame, over sorted copies (the report may run while the
 * consumer is still writing the lists, from the watchdog). */
static void report_frames(void)
{
    unsigned n = g_frames_seen < FRAME_STATS ? g_frames_seen : FRAME_STATS, k;
    float *c, *g;
    if (!n) return;
    c = (float*)malloc(sizeof(float) * n);
    g = (float*)malloc(sizeof(float) * n);
    if (!c || !g) {
        free(c);
        free(g);
        return;
    }
    memcpy(c, g_frame_consumer_ms, sizeof(float) * n);
    memcpy(g, g_frame_gpu_ms, sizeof(float) * n);
    qsort(c, n, sizeof(float), cmp_float);
    qsort(g, n, sizeof(float), cmp_float);
#define PCT(a, p) (a)[(size_t)((double)(n - 1) * (p))]
    k = g_frames_seen;
    say("a frame, over %u frame%s: consumer ms p50 %.2f p95 %.2f p99 %.2f; GPU ms p50 %.2f p95 %.2f p99 %.2f%s", k,
        k == 1 ? "" : "s", PCT(c, 0.50), PCT(c, 0.95), PCT(c, 0.99), PCT(g, 0.50), PCT(g, 0.95), PCT(g, 0.99),
        g_timestamps ? "" : " (no timestamps: GPU ms read 0)");
#undef PCT
    free(c);
    free(g);
}

static void present_report(void);
static void present_shutdown(void);
static void queue_idle(void);

/* The pipelines made on the draw path, where a creation stalls the frame:
 * how many, how many the cache already had, the longest and total creation,
 * and the frames (screen copies before) the first were made in. Then the
 * specialised ones: how many for how many shapes, and those the compiler
 * thread made, timed the same way. */
static void report_pipelines(void)
{
    char frames[PIPE_FRAMES * 12 + 8];
    size_t at = 0;
    unsigned long long i, n = g_n_pipes < PIPE_FRAMES ? g_n_pipes : PIPE_FRAMES;
    frames[0] = 0;
    for (i = 0; i < n; i++) at += (size_t)snprintf(frames + at, sizeof frames - at, " %llu", g_pipe_frame[i]);
    char hits[64];
    long long made = plat_load64(&g_bg_made), failed = plat_load64(&g_bg_failed);
    if (g_feedback) snprintf(hits, sizeof hits, "%llu of them from the cache", g_pipes_hit);
    else snprintf(hits, sizeof hits, "the device not saying which came from the cache");
    say("pipelines: %llu made on the draw path, %s; the longest %.2f ms, %.1f ms in all; made at frames%s%s; cache %s, "
        "%zu bytes loaded",
        g_n_pipes, hits, (double)g_pipe_ns_max / 1e6, (double)g_pipe_ns_total / 1e6, frames,
        g_n_pipes > PIPE_FRAMES ? " ..." : "", g_pcache ? g_pcache_path : "off", g_pcache_loaded);
    if (g_specialize == SPEC_OFF) {
        say("pipelines not specialised (SOA_GPU_SPECIALIZE=0): the TEV is interpreted");
        return;
    }
    say("pipelines specialised on the TEV's shape: %llu for %u distinct shapes, %.1f a shape; %s",
        g_n_spec, g_n_shapes, g_n_shapes ? (double)g_n_spec / g_n_shapes : 0.0,
        g_specialize == SPEC_WAIT ? "made on the draw path (SOA_GPU_SPECIALIZE=wait)" : "made on the compiler thread");
    if (g_specialize != SPEC_BACKGROUND) return;
    if (g_feedback) snprintf(hits, sizeof hits, "%lld of them from the cache", plat_load64(&g_bg_hit));
    say("the compiler thread: %lld made, %s; the longest %.2f ms, %.1f ms in all; %lld failed, %lld still to make; "
        "%llu draws drawn by the interpreter while theirs was made",
        made, hits, (double)plat_load64(&g_bg_ns_max) / 1e6, (double)plat_load64(&g_bg_ns_total) / 1e6, failed,
        (long long)g_n_spec - made - failed, g_n_interim);
}

void gxv_report(void)
{
    say("%llu draws (%llu rebuilt by clipping), %llu vertices, %llu clears, %llu screen copies, %llu copies to a "
        "texture (%llu refused), %llu pipelines, %llu submissions, GPU %.3f ms%s",
        g_n_draws, g_n_rebuilt, g_n_verts, g_n_clears, g_n_copies, g_n_tex_copies, g_n_refused,
        g_n_pipes + (unsigned long long)plat_load64(&g_bg_made), g_n_submits, g_gpu_ms,
        g_timestamps ? "" : " (this queue has no timestamps)");
    say("consumer %.3f ms, waiting for the GPU %.3f ms", (double)g_consumer_ns / 1e6, (double)g_wait_ns / 1e6);
    say("copies to a texture: %llu, landed with the submissions they were in but for %llu readback waits of their own; "
        "%llu samplers served by a copy image from the pool",
        g_n_tex_copies, g_n_land_waits, g_n_cimg_served);
    report_pipelines();
    report_frames();
    present_report();
    say("logic ops: %llu draws: %llu native, %llu from a snapshot, %llu through the interlock, %llu as blends", g_n_logic,
        g_logic_routes[LOGIC_NATIVE], g_logic_routes[LOGIC_SNAPSHOT], g_logic_routes[LOGIC_INTERLOCK], g_logic_routes[LOGIC_BLEND]);
    if (g_measure)
        say("largest draws (draw:samples) %llu:%llu %llu:%llu %llu:%llu %llu:%llu %llu:%llu%s", g_top_draw[0], g_top_samples[0],
            g_top_draw[1], g_top_samples[1], g_top_draw[2], g_top_samples[2], g_top_draw[3], g_top_samples[3], g_top_draw[4],
            g_top_samples[4], g_precise ? "" : " (not precise)");
}

/* ---- set-up --------------------------------------------------------------- */

/* The device: SOA_GPU_DEVICE=<n> picks one; otherwise the first discrete GPU,
 * then the first integrated, then anything with a graphics queue. */
static int pick_device(char* why, size_t cap)
{
    VkPhysicalDevice devs[16];
    uint32_t n = 16, i, best = UINT32_MAX, best_rank = 0;
    const char* want = getenv("SOA_GPU_DEVICE");
    if (vkEnumeratePhysicalDevices(g_inst, &n, devs) < 0 || n == 0) { snprintf(why, cap, "no Vulkan device"); return 0; }
    for (i = 0; i < n; i++) {
        VkQueueFamilyProperties q[16];
        uint32_t nq = 16, f, rank;
        VkPhysicalDeviceProperties p;
        vkGetPhysicalDeviceProperties(devs[i], &p);
        vkGetPhysicalDeviceQueueFamilyProperties(devs[i], &nq, q);
        for (f = 0; f < nq; f++)
            if (q[f].queueFlags & VK_QUEUE_GRAPHICS_BIT) break;
        if (f == nq) continue;
        rank = p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU ? 3 : p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU ? 2 : 1;
        if (want && *want) rank = (uint32_t)atoi(want) == i ? 4 : 0;
        if (rank > best_rank) { best_rank = rank; best = i; g_family = f; }
    }
    if (best == UINT32_MAX) { snprintf(why, cap, "no Vulkan device with a graphics queue%s", want ? " (SOA_GPU_DEVICE)" : ""); return 0; }
    g_phys = devs[best];
    vkGetPhysicalDeviceProperties(g_phys, &g_props);
    vkGetPhysicalDeviceMemoryProperties(g_phys, &g_memprops);
    snprintf(g_devname, sizeof g_devname, "%s", g_props.deviceName);
    {
        VkQueueFamilyProperties q[16];
        uint32_t nq = 16;
        vkGetPhysicalDeviceQueueFamilyProperties(g_phys, &nq, q);
        g_timestamps = q[g_family].timestampValidBits > 0 && g_props.limits.timestampPeriod > 0.0f;
    }
    return 1;
}

static int make_device(char* why, size_t cap)
{
    float prio = 1.0f;
    VkDeviceQueueCreateInfo qi = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    VkDeviceCreateInfo di = {VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    VkPhysicalDeviceFeatures feat;
    VkFormatProperties fp;
    VkResult r;
    vkGetPhysicalDeviceFormatProperties(g_phys, VK_FORMAT_D32_SFLOAT, &fp);
    if (!(fp.optimalTilingFeatures & VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT)) {
        snprintf(why, cap, "%s cannot render to D32_SFLOAT", g_devname);
        return 0;
    }
    vkGetPhysicalDeviceFormatProperties(g_phys, VK_FORMAT_R8G8B8A8_UNORM, &fp);
    if (!(fp.optimalTilingFeatures & VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT)) {
        snprintf(why, cap, "%s cannot render to R8G8B8A8_UNORM", g_devname);
        return 0;
    }
    memset(&feat, 0, sizeof feat); /* core features only (3.10), but for the one measuring needs */
    {
        /* core: every optional feature as absent (3.10). nologicop: logicOp
         * alone, the interlock kept -- V10's routing as a GPU with interlock
         * and no logicOp would take it. */
        const char* fs = getenv("SOA_GPU_FEATURES");
        g_core = fs && !strcmp(fs, "core") ? 1 : fs && !strcmp(fs, "nologicop") ? 2 : 0;
    }
    {
        VkPhysicalDeviceFeatures have;
        PFN_vkGetPhysicalDeviceFeatures get = (PFN_vkGetPhysicalDeviceFeatures)vkGetInstanceProcAddr(g_inst, "vkGetPhysicalDeviceFeatures");
        if (get) {
            get(g_phys, &have);
            feat.occlusionQueryPrecise = have.occlusionQueryPrecise;
            g_precise = have.occlusionQueryPrecise != 0;
            feat.logicOp = g_core ? VK_FALSE : have.logicOp; /* 3.5's first choice for logic ops */
            g_has_logicop = feat.logicOp != 0;
            feat.fragmentStoresAndAtomics = g_core == 1 ? VK_FALSE : have.fragmentStoresAndAtomics; /* V10's interlock route */
        }
    }
    qi.queueFamilyIndex = g_family;
    qi.queueCount = 1;
    qi.pQueuePriorities = &prio;
    di.queueCreateInfoCount = 1;
    di.pQueueCreateInfos = &qi;
    di.pEnabledFeatures = &feat;
    {
        /* VK_EXT_pipeline_creation_feedback, where the device has it: only
         * for the report's count of pipelines the disk cache had (V7). */
        static const char* names[4];
        static VkPhysicalDeviceFragmentShaderInterlockFeaturesEXT ilf = {
            VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FRAGMENT_SHADER_INTERLOCK_FEATURES_EXT};
        static VkPhysicalDeviceExtendedDynamicStateFeaturesEXT edf = {
            VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTENDED_DYNAMIC_STATE_FEATURES_EXT};
        const char* eds_off = getenv("SOA_GPU_EDS");
        uint32_t n = 0, i, k = 0;
        int has_swapchain = 0, has_il = 0, has_eds = 0;
        VkExtensionProperties* props;
        if (vkEnumerateDeviceExtensionProperties(g_phys, NULL, &n, NULL) == VK_SUCCESS && n &&
            (props = (VkExtensionProperties*)malloc(sizeof *props * n)) != NULL) {
            if (vkEnumerateDeviceExtensionProperties(g_phys, NULL, &n, props) == VK_SUCCESS)
                for (i = 0; i < n; i++) {
                    if (!strcmp(props[i].extensionName, VK_EXT_PIPELINE_CREATION_FEEDBACK_EXTENSION_NAME)) g_feedback = 1;
                    if (!strcmp(props[i].extensionName, VK_KHR_SWAPCHAIN_EXTENSION_NAME)) has_swapchain = 1;
                    if (!strcmp(props[i].extensionName, VK_EXT_FRAGMENT_SHADER_INTERLOCK_EXTENSION_NAME)) has_il = 1;
                    if (!strcmp(props[i].extensionName, VK_EXT_EXTENDED_DYNAMIC_STATE_EXTENSION_NAME)) has_eds = 1;
                }
            free(props);
        }
        if (g_core == 1) g_feedback = 0;
        if (g_feedback) names[k++] = VK_EXT_PIPELINE_CREATION_FEEDBACK_EXTENSION_NAME;
        /* V10's interlock route, where the device has pixel interlock and
         * stores from the fragment stage; not under SOA_GPU_FEATURES=core. */
        if (has_il && feat.fragmentStoresAndAtomics) {
            PFN_vkGetPhysicalDeviceFeatures2 feat2 =
                (PFN_vkGetPhysicalDeviceFeatures2)vkGetInstanceProcAddr(g_inst, "vkGetPhysicalDeviceFeatures2");
            VkPhysicalDeviceFeatures2 f2 = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
            f2.pNext = &ilf;
            if (feat2) feat2(g_phys, &f2);
            if (ilf.fragmentShaderPixelInterlock) {
                ilf.pNext = NULL;
                ilf.fragmentShaderSampleInterlock = VK_FALSE;
                ilf.fragmentShaderShadingRateInterlock = VK_FALSE;
                di.pNext = &ilf;
                names[k++] = VK_EXT_FRAGMENT_SHADER_INTERLOCK_EXTENSION_NAME;
                g_has_interlock = 1;
            }
        }
        if (!g_has_interlock) feat.fragmentStoresAndAtomics = VK_FALSE;
        /* Dynamic state (V7), where the device has it; not under core. */
        if (has_eds && g_core != 1 && !(eds_off && !strcmp(eds_off, "0"))) {
            PFN_vkGetPhysicalDeviceFeatures2 feat2 =
                (PFN_vkGetPhysicalDeviceFeatures2)vkGetInstanceProcAddr(g_inst, "vkGetPhysicalDeviceFeatures2");
            VkPhysicalDeviceFeatures2 f2 = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
            f2.pNext = &edf;
            if (feat2) feat2(g_phys, &f2);
            if (edf.extendedDynamicState) {
                edf.pNext = (void*)di.pNext;
                di.pNext = &edf;
                names[k++] = VK_EXT_EXTENDED_DYNAMIC_STATE_EXTENSION_NAME;
                g_eds = 1;
            }
        }
        /* The window's swap chain (V8), where the instance has a surface. */
        if (g_inst_surface && has_swapchain) {
            names[k++] = VK_KHR_SWAPCHAIN_EXTENSION_NAME;
            g_dev_swapchain = 1;
        }
        di.enabledExtensionCount = k;
        di.ppEnabledExtensionNames = k ? names : NULL;
    }
    r = vkCreateDevice(g_phys, &di, NULL, &g_dev);
    if (r != VK_SUCCESS) { snprintf(why, cap, "vkCreateDevice on %s failed: VkResult %d", g_devname, (int)r); return 0; }
    if (!load_device(why, cap)) return 0;
    vkGetDeviceQueue(g_dev, g_family, 0, &g_queue);
    if (g_eds) {
        p_vkCmdSetCullModeEXT = (PFN_vkCmdSetCullModeEXT)vkGetDeviceProcAddr(g_dev, "vkCmdSetCullModeEXT");
        p_vkCmdSetPrimitiveTopologyEXT = (PFN_vkCmdSetPrimitiveTopologyEXT)vkGetDeviceProcAddr(g_dev, "vkCmdSetPrimitiveTopologyEXT");
        p_vkCmdSetDepthTestEnableEXT = (PFN_vkCmdSetDepthTestEnableEXT)vkGetDeviceProcAddr(g_dev, "vkCmdSetDepthTestEnableEXT");
        p_vkCmdSetDepthWriteEnableEXT = (PFN_vkCmdSetDepthWriteEnableEXT)vkGetDeviceProcAddr(g_dev, "vkCmdSetDepthWriteEnableEXT");
        p_vkCmdSetDepthCompareOpEXT = (PFN_vkCmdSetDepthCompareOpEXT)vkGetDeviceProcAddr(g_dev, "vkCmdSetDepthCompareOpEXT");
        if (!p_vkCmdSetCullModeEXT || !p_vkCmdSetPrimitiveTopologyEXT || !p_vkCmdSetDepthTestEnableEXT ||
            !p_vkCmdSetDepthWriteEnableEXT || !p_vkCmdSetDepthCompareOpEXT)
            g_eds = 0;
    }
    pcache_open();
    return 1;
}

static int make_pass(void)
{
    VkAttachmentDescription at[2];
    VkAttachmentReference cref = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    VkAttachmentReference dref = {1, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL};
    VkSubpassDescription sp;
    VkRenderPassCreateInfo ri = {VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO};
    VkFramebufferCreateInfo fi = {VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};
    VkImageView views[2];
    memset(at, 0, sizeof at);
    memset(&sp, 0, sizeof sp);
    /* The EFB persists: every pass loads what the last one stored. */
    at[0].format = VK_FORMAT_R8G8B8A8_UNORM;
    at[0].samples = VK_SAMPLE_COUNT_1_BIT;
    at[0].loadOp = VK_ATTACHMENT_LOAD_OP_LOAD;
    at[0].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    at[0].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    at[0].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    at[0].initialLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    at[0].finalLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    at[1] = at[0];
    at[1].format = VK_FORMAT_D32_SFLOAT;
    at[1].initialLayout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;
    at[1].finalLayout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;
    sp.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    sp.colorAttachmentCount = 1;
    sp.pColorAttachments = &cref;
    sp.pDepthStencilAttachment = &dref;
    ri.attachmentCount = 2;
    ri.pAttachments = at;
    ri.subpassCount = 1;
    ri.pSubpasses = &sp;
    VKCHECK(vkCreateRenderPass(g_dev, &ri, NULL, &g_pass));
    views[0] = g_color_view;
    views[1] = g_depth_view;
    fi.renderPass = g_pass;
    fi.attachmentCount = 2;
    fi.pAttachments = views;
    fi.width = EFB_W;
    fi.height = EFB_H;
    fi.layers = 1;
    VKCHECK(vkCreateFramebuffer(g_dev, &fi, NULL, &g_fb));
    if (g_has_interlock) {
        /* V10's interlock route: a subpass of no attachments, 640 x 528. */
        VkSubpassDescription none;
        memset(&none, 0, sizeof none);
        none.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
        ri.attachmentCount = 0;
        ri.pAttachments = NULL;
        ri.pSubpasses = &none;
        VKCHECK(vkCreateRenderPass(g_dev, &ri, NULL, &g_pass_il));
        fi.renderPass = g_pass_il;
        fi.attachmentCount = 0;
        fi.pAttachments = NULL;
        VKCHECK(vkCreateFramebuffer(g_dev, &fi, NULL, &g_fb_il));
    }
    return 1;
}

static int make_layout(void)
{
    VkDescriptorSetLayoutBinding b[6];
    VkDescriptorPoolSize psi[2];
    VkDescriptorImageInfo ii = {VK_NULL_HANDLE, VK_NULL_HANDLE, VK_IMAGE_LAYOUT_GENERAL};
    VkDescriptorSetLayoutCreateInfo li = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    VkPushConstantRange pr = {VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(PushDraw)};
    VkPipelineLayoutCreateInfo pi = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 5};
    VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    VkDescriptorSetAllocateInfo ai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    VkDescriptorBufferInfo bi[5];
    VkWriteDescriptorSet w[5];
    VkShaderModuleCreateInfo si = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    VkBuffer bufs[5];
    unsigned i;
    /* 0 the vertices (the vertex stage); 1 the draw records, 2 the texel
     * pool, 3 the texture records, 4 the EFB snapshot (the fragment stage). */
    bufs[0] = g_ring;
    bufs[1] = g_drawbuf;
    bufs[2] = g_poolbuf;
    bufs[3] = g_texrecbuf;
    bufs[4] = g_readback;
    for (i = 0; i < 5; i++) {
        b[i].binding = i;
        b[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        b[i].descriptorCount = 1;
        b[i].stageFlags = i == 0 ? VK_SHADER_STAGE_VERTEX_BIT : VK_SHADER_STAGE_FRAGMENT_BIT;
        b[i].pImmutableSamplers = NULL;
    }
    li.bindingCount = 5;
    if (g_has_interlock) {
        /* 5: the EFB itself, for V10's interlock route. */
        b[5].binding = 5;
        b[5].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
        b[5].descriptorCount = 1;
        b[5].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
        b[5].pImmutableSamplers = NULL;
        li.bindingCount = 6;
    }
    li.pBindings = b;
    VKCHECK(vkCreateDescriptorSetLayout(g_dev, &li, NULL, &g_dsl));
    pi.setLayoutCount = 1;
    pi.pSetLayouts = &g_dsl;
    pi.pushConstantRangeCount = 1;
    pi.pPushConstantRanges = &pr;
    VKCHECK(vkCreatePipelineLayout(g_dev, &pi, NULL, &g_layout));
    dpi.maxSets = 1;
    psi[0] = ps;
    psi[1].type = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
    psi[1].descriptorCount = 1;
    dpi.poolSizeCount = g_has_interlock ? 2 : 1;
    dpi.pPoolSizes = psi;
    VKCHECK(vkCreateDescriptorPool(g_dev, &dpi, NULL, &g_dpool));
    ai.descriptorPool = g_dpool;
    ai.descriptorSetCount = 1;
    ai.pSetLayouts = &g_dsl;
    VKCHECK(vkAllocateDescriptorSets(g_dev, &ai, &g_dset));
    if (g_has_interlock) {
        VkWriteDescriptorSet wi = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
        ii.imageView = g_color_view;
        wi.dstSet = g_dset;
        wi.dstBinding = 5;
        wi.descriptorCount = 1;
        wi.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
        wi.pImageInfo = &ii;
        vkUpdateDescriptorSets(g_dev, 1, &wi, 0, NULL);
    }
    for (i = 0; i < 5; i++) {
        bi[i].buffer = bufs[i];
        bi[i].offset = 0;
        bi[i].range = VK_WHOLE_SIZE;
        memset(&w[i], 0, sizeof w[i]);
        w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        w[i].dstSet = g_dset;
        w[i].dstBinding = i;
        w[i].descriptorCount = 1;
        w[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        w[i].pBufferInfo = &bi[i];
    }
    vkUpdateDescriptorSets(g_dev, 5, w, 0, NULL);
    (void)si;
    return 1;
}

static int make_commands(void)
{
    VkCommandPoolCreateInfo pi = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    VkCommandBufferAllocateInfo ai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    VkFenceCreateInfo fi = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    VkQueryPoolCreateInfo qi = {VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO};
    pi.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pi.queueFamilyIndex = g_family;
    VKCHECK(vkCreateCommandPool(g_dev, &pi, NULL, &g_cpool));
    ai.commandPool = g_cpool;
    ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    ai.commandBufferCount = 1;
    VKCHECK(vkAllocateCommandBuffers(g_dev, &ai, &g_cb));
    VKCHECK(vkCreateFence(g_dev, &fi, NULL, &g_fence));
    if (g_timestamps) {
        qi.queryType = VK_QUERY_TYPE_TIMESTAMP;
        qi.queryCount = 2;
        VKCHECK(vkCreateQueryPool(g_dev, &qi, NULL, &g_qpool));
    }
    qi.queryType = VK_QUERY_TYPE_OCCLUSION;
    qi.queryCount = OCC_QUERIES;
    VKCHECK(vkCreateQueryPool(g_dev, &qi, NULL, &g_occ));
    return 1;
}

/* The EFB's images start UNDEFINED; one submission puts them in the layouts
 * the render pass expects and fills them as gxr_reset_efb would with every
 * register zero (black, the farthest depth). */
static int init_images(void)
{
    VkClearColorValue black = {{0.0f, 0.0f, 0.0f, 0.0f}};
    VkClearDepthStencilValue farthest = {16777215.0f / 16777216.0f, 0};
    VkImageSubresourceRange cr = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    VkImageSubresourceRange dr = {VK_IMAGE_ASPECT_DEPTH_BIT, 0, 1, 0, 1};
    if (!begin_cb()) return 0;
    barrier_image(g_color, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                  VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, 0, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT);
    barrier_image(g_depth, VK_IMAGE_ASPECT_DEPTH_BIT, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                  VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, 0, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT);
    vkCmdClearColorImage(g_cb, g_color, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &black, 1, &cr);
    vkCmdClearDepthStencilImage(g_cb, g_depth, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &farthest, 1, &dr);
    barrier_image(g_color, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                  VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                  VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT);
    barrier_image(g_depth, VK_IMAGE_ASPECT_DEPTH_BIT, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL,
                  VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT,
                  VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT,
                  VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT);
    return submit_wait();
}

/* 3.2: the pool is the smaller of 128 MB and the largest storage buffer
 * the device can bind (128 MB is Vulkan's guaranteed minimum). */
static VkDeviceSize pool_bytes(void)
{
    VkDeviceSize b = POOL_BYTES;
    if (g_props.limits.maxStorageBufferRange < b) b = g_props.limits.maxStorageBufferRange & ~(VkDeviceSize)3;
    g_pool_cap = (uint32_t)(b / 4);
    return b;
}

/* SOA_GPU_VALIDATE=1: each of the validation layer's warnings and errors
 * into the log, one line each, the first 200 of them and then a count. */
static int g_debug_utils;
static VkDebugUtilsMessengerEXT g_messenger;
static plat_a32 g_n_validation;
static VKAPI_ATTR VkBool32 VKAPI_CALL debug_print(VkDebugUtilsMessageSeverityFlagBitsEXT sev, VkDebugUtilsMessageTypeFlagsEXT type,
                                                  const VkDebugUtilsMessengerCallbackDataEXT* data, void* user)
{
    int32_t n = plat_inc32(&g_n_validation);
    (void)type;
    (void)user;
    if (n <= 200)
        say("validation %s: %s", sev & VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT ? "error" : "warning",
            data && data->pMessage ? data->pMessage : "(no message)");
    else if (n == 201)
        say("validation: more than 200 messages; the rest are not printed");
    return VK_FALSE;
}

int gxv_init(char* why, size_t cap)
{
    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO};
    VkInstanceCreateInfo ii = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    const char* layer = "VK_LAYER_KHRONOS_validation";
    const char* val = getenv("SOA_GPU_VALIDATE");
    VkResult r;
    unsigned i;
    why[0] = 0;
    if (!load_loader(why, cap)) return 0;
    app.pApplicationName = "soa-gpuspike";
    app.apiVersion = VK_API_VERSION_1_1;
    ii.pApplicationInfo = &app;
    /* SOA_GPU_VALIDATE=1 asks for the Khronos validation layer, where one is
     * installed (it comes with the Vulkan SDK, which nothing here needs). */
    if (val && atoi(val)) {
        VkLayerProperties lp[64];
        uint32_t n = 64, k;
        int have = 0;
        if (vkEnumerateInstanceLayerProperties && vkEnumerateInstanceLayerProperties(&n, lp) >= 0)
            for (k = 0; k < n; k++)
                if (!strcmp(lp[k].layerName, layer)) have = 1;
        if (have) { ii.enabledLayerCount = 1; ii.ppEnabledLayerNames = &layer; }
        say("SOA_GPU_VALIDATE: %s", have ? "the validation layer is on" : "no validation layer is installed; running without it");
    }
    {
        /* The window's surface (V8), where the loader has it; nothing else
         * needs it, and a run with no window never uses it. And, with the
         * validation layer on, VK_EXT_debug_utils, so its messages reach the
         * log (debug_print). */
        static const char* names[3];
        uint32_t n = 0, k, found = 0, m = 0;
        int has_debug = 0;
        VkExtensionProperties* props;
        if (vkEnumerateInstanceExtensionProperties && vkEnumerateInstanceExtensionProperties(NULL, &n, NULL) == VK_SUCCESS &&
            n && (props = (VkExtensionProperties*)malloc(sizeof *props * n)) != NULL) {
            if (vkEnumerateInstanceExtensionProperties(NULL, &n, props) == VK_SUCCESS)
                for (k = 0; k < n; k++) {
#ifdef _WIN32
                    if (!strcmp(props[k].extensionName, VK_KHR_SURFACE_EXTENSION_NAME) ||
                        !strcmp(props[k].extensionName, "VK_KHR_win32_surface"))
                        found++;
#endif
                    if (!strcmp(props[k].extensionName, VK_EXT_DEBUG_UTILS_EXTENSION_NAME)) has_debug = 1;
                }
            free(props);
        }
        if (found == 2) {
            names[m++] = VK_KHR_SURFACE_EXTENSION_NAME;
            names[m++] = "VK_KHR_win32_surface";
            g_inst_surface = 1;
        }
        if (ii.enabledLayerCount && has_debug) {
            names[m++] = VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
            g_debug_utils = 1;
        }
        ii.enabledExtensionCount = m;
        ii.ppEnabledExtensionNames = m ? names : NULL;
    }
    r = vkCreateInstance(&ii, NULL, &g_inst);
    if (r == VK_SUCCESS && g_debug_utils) {
        PFN_vkCreateDebugUtilsMessengerEXT make =
            (PFN_vkCreateDebugUtilsMessengerEXT)vkGetInstanceProcAddr(g_inst, "vkCreateDebugUtilsMessengerEXT");
        VkDebugUtilsMessengerCreateInfoEXT di = {VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT};
        di.messageSeverity = VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT;
        di.messageType = VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT |
                         VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT;
        di.pfnUserCallback = debug_print;
        if (!make || make(g_inst, &di, NULL, &g_messenger) != VK_SUCCESS) say("SOA_GPU_VALIDATE: no debug messenger");
    }
    if (r != VK_SUCCESS) { snprintf(why, cap, "vkCreateInstance failed: VkResult %d (no Vulkan 1.1 driver?)", (int)r); return 0; }
    if (!load_instance(why, cap) || !pick_device(why, cap) || !make_device(why, cap)) return 0;
    if (!make_image(VK_FORMAT_R8G8B8A8_UNORM, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT |
                                                  (g_has_interlock ? VK_IMAGE_USAGE_STORAGE_BIT : 0),
                    VK_IMAGE_ASPECT_COLOR_BIT, &g_color, &g_color_view) ||
        !make_image(VK_FORMAT_D32_SFLOAT,
                    VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
                    VK_IMAGE_ASPECT_DEPTH_BIT, &g_depth, &g_depth_view) ||
        !make_buffer(RING_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 0, &g_ring, &g_ring_map) ||
        !make_buffer((VkDeviceSize)MAX_QUADS * 6 * 4, VK_BUFFER_USAGE_INDEX_BUFFER_BIT, 0, &g_quad_idx, (uint8_t**)&g_quad_map) ||
        !make_buffer(READBACK_BYTES, VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
                     0, &g_readback, &g_readback_map) ||
        !make_buffer(DEST_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 1, &g_destbuf, &g_dest_map) ||
        !make_buffer(IMAGE_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 1, &g_imagebuf, &g_image_map) ||
        !make_buffer((VkDeviceSize)READBACK_BYTES * SCREEN_SLOTS, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT, 1,
                     &g_screenbuf, &g_screen_map) ||
        !make_buffer(DRAWREC_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 0, &g_drawbuf, &g_draw_map) ||
        !make_buffer(pool_bytes(), VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 0, &g_poolbuf, &g_pool_map) ||
        !make_buffer(TEXREC_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 0, &g_texrecbuf, &g_texrec_map) || !make_pass() ||
        !make_layout() || !make_commands() || !init_images()) {
        snprintf(why, cap, "setting up on %s failed (see above)", g_devname);
        return 0;
    }
    /* Quads as two triangles each, (0, 1, 2) and (0, 2, 3): draw_command's split. */
    for (i = 0; i < MAX_QUADS; i++) {
        uint32_t* q = g_quad_map + i * 6, b = i * 4;
        q[0] = b; q[1] = b + 1; q[2] = b + 2; q[3] = b; q[4] = b + 2; q[5] = b + 3;
    }
    if (g_logic_mode < 0) {
        const char* forced = getenv("SOA_GPU_LOGICOP");
        if (forced && *forced && !gxv_set_logicop(forced))
            say("SOA_GPU_LOGICOP=%s is not native, blend, snapshot or interlock here; ignored", forced);
    }
    compiler_start();
    /* The start line (3.11), which a live run's log is judged by. */
    say("Vulkan %u.%u.%u on %s (driver %#x): logicOp %s; EFB %ux%u RGBA8 + D32F; logic ops %s; timestamps %s; "
        "interlock %s%s%s",
        VK_API_VERSION_MAJOR(g_props.apiVersion), VK_API_VERSION_MINOR(g_props.apiVersion),
        VK_API_VERSION_PATCH(g_props.apiVersion), g_devname, g_props.driverVersion, g_has_logicop ? "yes" : "no", EFB_W,
        EFB_H,
        g_logic_mode == LOGIC_NATIVE ? "native"
        : g_logic_mode == LOGIC_BLEND ? "as blends"
        : g_logic_mode == LOGIC_SNAPSHOT ? "from a snapshot"
        : g_logic_mode == LOGIC_INTERLOCK ? "through the interlock"
        : g_has_logicop ? "native"
                        : "routed by draw",
        g_timestamps ? "on" : "unavailable", g_has_interlock ? "yes" : "no", g_eds ? "; dynamic state" : "",
        g_core == 1 ? "; SOA_GPU_FEATURES=core" : g_core == 2 ? "; SOA_GPU_FEATURES=nologicop" : "");
    return 1;
}

int gxv_start(char* why, size_t cap)
{
    /* A check's knob: one of gxv_set_mutation's, which gpuspike.py contrast
     * hands soa.exe alone to prove the two binaries' pictures can differ. */
    const char* m = getenv("SOA_GPU_MUTATE");
    if (m && *m && !gxv_set_mutation(m)) {
        snprintf(why, cap, "SOA_GPU_MUTATE=%s is not a mutation gxv has", m);
        return 0;
    }
    if (!gxv_init(why, cap)) return 0;
    gxr_set_backend(gxv_backend());
    g_started = 1;
    return 1;
}

void gxv_shutdown(void)
{
    unsigned i;
    if (!g_dev) return;
    compiler_stop();
    queue_idle();
    present_shutdown();
    for (i = 0; i < PIPE_SLOTS; i++)
        if (g_pipes[i].key && g_pipes[i].pipe) vkDestroyPipeline(g_dev, g_pipes[i].pipe, NULL);
    if (g_qpool) vkDestroyQueryPool(g_dev, g_qpool, NULL);
    if (g_occ) vkDestroyQueryPool(g_dev, g_occ, NULL);
    vkDestroyFence(g_dev, g_fence, NULL);
    vkDestroyCommandPool(g_dev, g_cpool, NULL);
    if (g_vs) vkDestroyShaderModule(g_dev, g_vs, NULL);
    if (g_fs) vkDestroyShaderModule(g_dev, g_fs, NULL);
    if (g_fs_il) vkDestroyShaderModule(g_dev, g_fs_il, NULL);
    if (g_fb_il) vkDestroyFramebuffer(g_dev, g_fb_il, NULL);
    if (g_pass_il) vkDestroyRenderPass(g_dev, g_pass_il, NULL);
    vkDestroyDescriptorPool(g_dev, g_dpool, NULL);
    vkDestroyPipelineLayout(g_dev, g_layout, NULL);
    vkDestroyDescriptorSetLayout(g_dev, g_dsl, NULL);
    vkDestroyFramebuffer(g_dev, g_fb, NULL);
    vkDestroyRenderPass(g_dev, g_pass, NULL);
    vkDestroyBuffer(g_dev, g_ring, NULL);
    vkDestroyBuffer(g_dev, g_quad_idx, NULL);
    vkDestroyBuffer(g_dev, g_readback, NULL);
    vkDestroyBuffer(g_dev, g_destbuf, NULL);
    vkDestroyBuffer(g_dev, g_imagebuf, NULL);
    vkDestroyBuffer(g_dev, g_screenbuf, NULL);
    vkDestroyBuffer(g_dev, g_drawbuf, NULL);
    vkDestroyBuffer(g_dev, g_poolbuf, NULL);
    vkDestroyBuffer(g_dev, g_texrecbuf, NULL);
    if (g_tev_setups) {
        vkDestroyBuffer(g_dev, g_tev_setups, NULL);
        vkDestroyBuffer(g_dev, g_tev_inputs, NULL);
        vkDestroyBuffer(g_dev, g_tev_results, NULL);
    }
    if (g_lod_inputs) {
        vkDestroyBuffer(g_dev, g_lod_inputs, NULL);
        vkDestroyBuffer(g_dev, g_lod_results, NULL);
    }
    pcache_save();
    if (g_pcache) vkDestroyPipelineCache(g_dev, g_pcache, NULL);
    g_pcache = VK_NULL_HANDLE;
    compute_free(&g_copy_cs);
    compute_free(&g_tev_cs);
    compute_free(&g_lod_cs);
    vkDestroyImageView(g_dev, g_color_view, NULL);
    vkDestroyImageView(g_dev, g_depth_view, NULL);
    vkDestroyImage(g_dev, g_color, NULL);
    vkDestroyImage(g_dev, g_depth, NULL);
    for (i = 0; i < VK_MAX_MEMORY_TYPES; i++) {
        unsigned k;
        for (k = 0; k < ARENA_BLOCKS; k++)
            if (g_arena[i][k].mem) vkFreeMemory(g_dev, g_arena[i][k].mem, NULL);
    }
    vkDestroyDevice(g_dev, NULL);
    if (g_messenger) {
        PFN_vkDestroyDebugUtilsMessengerEXT gone =
            (PFN_vkDestroyDebugUtilsMessengerEXT)vkGetInstanceProcAddr(g_inst, "vkDestroyDebugUtilsMessengerEXT");
        if (plat_load32(&g_n_validation)) say("validation: %d message(s) in all", (int)plat_load32(&g_n_validation));
        if (gone) gone(g_inst, g_messenger, NULL);
        g_messenger = VK_NULL_HANDLE;
    }
    vkDestroyInstance(g_inst, NULL);
    g_dev = VK_NULL_HANDLE;
    free(g_tmp);
    plat_dl_close(g_lib);
    g_lib = NULL;
}

/* ---- the presenter (V8) ---------------------------------------------------------
 *
 * The window's picture from the GPU: the newest screen copy, still in the
 * screen buffer, drawn into a Vulkan swap chain on the window by present.frag
 * -- picture_scale's layout and nearest neighbour, as a shader -- and
 * presented. The window's own thread calls it, where the DXGI presenter ran;
 * the consumer goes on drawing meanwhile. Each frame is presented `interval`
 * times in FIFO order, a refresh each, which is what DXGI's sync interval did
 * (H8): two at 60 Hz, four at 120. g_present_lock keeps shutdown off a
 * present in progress; the queue itself is g_queue_lock's. */
typedef struct {
    VkStructureType sType;
    const void* pNext;
    VkFlags flags;
    void* hinstance;
    void* hwnd;
} GxvWin32SurfaceInfo; /* VkWin32SurfaceCreateInfoKHR, without <windows.h> */
typedef VkResult(VKAPI_PTR* GxvCreateWin32Surface)(VkInstance, const GxvWin32SurfaceInfo*, const VkAllocationCallbacks*,
                                                   VkSurfaceKHR*);
#define GXV_STYPE_WIN32_SURFACE ((VkStructureType)1000009000)

#define SWAP_MAX 8
#define CHECK_BYTES (2560u * 1600u * 4u) /* the presenter's check: its largest target */
static VkBuffer g_chk; /* the check's readback, made at its first use */
static uint8_t* g_chk_map;
static PlatLock g_present_lock;
static int g_present_dead;
static VkSurfaceKHR g_surface;
static VkSwapchainKHR g_swap;
static VkFormat g_swap_format;
static VkExtent2D g_swap_ext;
static uint32_t g_swap_n;
static VkImage g_swap_img[SWAP_MAX];
static VkImageView g_swap_view[SWAP_MAX];
static VkFramebuffer g_swap_fb[SWAP_MAX];
static VkSemaphore g_swap_ready[SWAP_MAX], g_swap_done[SWAP_MAX];
static unsigned g_swap_k;
static int g_swap_stale, g_swap_want_w, g_swap_want_h;
static VkRenderPass g_pres_pass, g_pres_check_pass;
static VkPipeline g_pres_pipe;
static VkPipelineLayout g_pres_layout;
static VkDescriptorSetLayout g_pres_dsl;
static VkDescriptorPool g_pres_dpool;
static VkDescriptorSet g_pres_set;
static VkCommandPool g_pres_cpool;
static VkCommandBuffer g_pres_cb;
static VkFence g_pres_fence;
static unsigned long long g_n_presents, g_n_present_frames, g_n_present_images, g_n_swap_made;
static PFN_vkDestroySurfaceKHR p_vkDestroySurfaceKHR;
static PFN_vkGetPhysicalDeviceSurfaceSupportKHR p_vkGetPhysicalDeviceSurfaceSupportKHR;
static PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR p_vkGetPhysicalDeviceSurfaceCapabilitiesKHR;
static PFN_vkGetPhysicalDeviceSurfaceFormatsKHR p_vkGetPhysicalDeviceSurfaceFormatsKHR;
static PFN_vkCreateSwapchainKHR p_vkCreateSwapchainKHR;
static PFN_vkDestroySwapchainKHR p_vkDestroySwapchainKHR;
static PFN_vkGetSwapchainImagesKHR p_vkGetSwapchainImagesKHR;
static PFN_vkAcquireNextImageKHR p_vkAcquireNextImageKHR;
static PFN_vkQueuePresentKHR p_vkQueuePresentKHR;
static PFN_vkCreateSemaphore p_vkCreateSemaphore;
static PFN_vkDestroySemaphore p_vkDestroySemaphore;

int gxv_running(void)
{
    return g_started;
}

/* A render pass of one colour attachment in fmt, written whole: to present,
 * or (the check) to copy out. */
static VkRenderPass present_pass(VkFormat fmt, VkImageLayout final)
{
    VkAttachmentDescription at = {0};
    VkAttachmentReference ref = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    VkSubpassDescription sp = {0};
    VkSubpassDependency dep = {0};
    VkRenderPassCreateInfo ri = {VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO};
    VkRenderPass pass = VK_NULL_HANDLE;
    at.format = fmt;
    at.samples = VK_SAMPLE_COUNT_1_BIT;
    at.loadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE; /* every pixel is drawn: the picture or black */
    at.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    at.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    at.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    at.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    at.finalLayout = final;
    sp.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    sp.colorAttachmentCount = 1;
    sp.pColorAttachments = &ref;
    /* The acquire's semaphore waits at colour output; the image's layout
     * change must wait there too. */
    dep.srcSubpass = VK_SUBPASS_EXTERNAL;
    dep.dstSubpass = 0;
    dep.srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dep.dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dep.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    ri.attachmentCount = 1;
    ri.pAttachments = &at;
    ri.subpassCount = 1;
    ri.pSubpasses = &sp;
    ri.dependencyCount = 1;
    ri.pDependencies = &dep;
    if (vkCreateRenderPass(g_dev, &ri, NULL, &pass) != VK_SUCCESS) return VK_NULL_HANDLE;
    return pass;
}

/* The pipeline, its layout and its one descriptor (the screen buffer, whole),
 * made once for the pass's format. */
static int present_pipeline(VkRenderPass pass)
{
    VkDescriptorSetLayoutBinding b = {0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL};
    VkDescriptorSetLayoutCreateInfo li = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    VkPushConstantRange pr = {VK_SHADER_STAGE_FRAGMENT_BIT, 0, 7 * 4};
    VkPipelineLayoutCreateInfo pli = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1};
    VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    VkDescriptorSetAllocateInfo ai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    VkDescriptorBufferInfo bi = {0};
    VkWriteDescriptorSet w = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
    VkShaderModuleCreateInfo si = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    VkShaderModule vs = VK_NULL_HANDLE, fs = VK_NULL_HANDLE;
    VkPipelineShaderStageCreateInfo st[2] = {{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO},
                                             {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO}};
    VkPipelineVertexInputStateCreateInfo vin = {VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia = {VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO};
    VkPipelineViewportStateCreateInfo vps = {VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO};
    VkPipelineRasterizationStateCreateInfo rs = {VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};
    VkPipelineMultisampleStateCreateInfo ms = {VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};
    VkPipelineColorBlendAttachmentState ba = {0};
    VkPipelineColorBlendStateCreateInfo cb = {VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};
    VkDynamicState dyn[2] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dys = {VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO};
    VkGraphicsPipelineCreateInfo pi = {VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};
    VkResult r;
    if (g_pres_pipe) return 1;
    li.bindingCount = 1;
    li.pBindings = &b;
    if (vkCreateDescriptorSetLayout(g_dev, &li, NULL, &g_pres_dsl) != VK_SUCCESS) return 0;
    pli.setLayoutCount = 1;
    pli.pSetLayouts = &g_pres_dsl;
    pli.pushConstantRangeCount = 1;
    pli.pPushConstantRanges = &pr;
    if (vkCreatePipelineLayout(g_dev, &pli, NULL, &g_pres_layout) != VK_SUCCESS) return 0;
    dpi.maxSets = 1;
    dpi.poolSizeCount = 1;
    dpi.pPoolSizes = &ps;
    if (vkCreateDescriptorPool(g_dev, &dpi, NULL, &g_pres_dpool) != VK_SUCCESS) return 0;
    ai.descriptorPool = g_pres_dpool;
    ai.descriptorSetCount = 1;
    ai.pSetLayouts = &g_pres_dsl;
    if (vkAllocateDescriptorSets(g_dev, &ai, &g_pres_set) != VK_SUCCESS) return 0;
    bi.buffer = g_screenbuf;
    bi.range = VK_WHOLE_SIZE;
    w.dstSet = g_pres_set;
    w.descriptorCount = 1;
    w.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    w.pBufferInfo = &bi;
    vkUpdateDescriptorSets(g_dev, 1, &w, 0, NULL);
    si.codeSize = sizeof present_vert;
    si.pCode = present_vert;
    if (vkCreateShaderModule(g_dev, &si, NULL, &vs) != VK_SUCCESS) return 0;
    si.codeSize = g_mut_present ? sizeof present_frag_offset : sizeof present_frag;
    si.pCode = g_mut_present ? present_frag_offset : present_frag;
    if (vkCreateShaderModule(g_dev, &si, NULL, &fs) != VK_SUCCESS) {
        vkDestroyShaderModule(g_dev, vs, NULL);
        return 0;
    }
    st[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    st[0].module = vs;
    st[0].pName = "main";
    st[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    st[1].module = fs;
    st[1].pName = "main";
    ia.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    vps.viewportCount = 1;
    vps.scissorCount = 1;
    rs.polygonMode = VK_POLYGON_MODE_FILL;
    rs.cullMode = VK_CULL_MODE_NONE;
    rs.lineWidth = 1.0f;
    ms.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
    ba.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
    cb.attachmentCount = 1;
    cb.pAttachments = &ba;
    dys.dynamicStateCount = 2;
    dys.pDynamicStates = dyn;
    pi.stageCount = 2;
    pi.pStages = st;
    pi.pVertexInputState = &vin;
    pi.pInputAssemblyState = &ia;
    pi.pViewportState = &vps;
    pi.pRasterizationState = &rs;
    pi.pMultisampleState = &ms;
    pi.pColorBlendState = &cb;
    pi.pDynamicState = &dys;
    pi.layout = g_pres_layout;
    pi.renderPass = pass;
    r = vkCreateGraphicsPipelines(g_dev, g_pcache, 1, &pi, NULL, &g_pres_pipe);
    vkDestroyShaderModule(g_dev, vs, NULL);
    vkDestroyShaderModule(g_dev, fs, NULL);
    return r == VK_SUCCESS;
}

/* The presenter's command buffer and fence, its own pool: the window's
 * thread records it, never the consumer's. */
static int present_commands(void)
{
    VkCommandPoolCreateInfo pi = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    VkCommandBufferAllocateInfo ai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    VkFenceCreateInfo fi = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    if (g_pres_cpool) return 1;
    pi.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pi.queueFamilyIndex = g_family;
    if (vkCreateCommandPool(g_dev, &pi, NULL, &g_pres_cpool) != VK_SUCCESS) return 0;
    ai.commandPool = g_pres_cpool;
    ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    ai.commandBufferCount = 1;
    if (vkAllocateCommandBuffers(g_dev, &ai, &g_pres_cb) != VK_SUCCESS) return 0;
    fi.flags = VK_FENCE_CREATE_SIGNALED_BIT;
    return vkCreateFence(g_dev, &fi, NULL, &g_pres_fence) == VK_SUCCESS;
}

/* The present pass into fb (w x h), from screen slot `slot` laid out by
 * picture_layout(mode): recorded into the presenter's command buffer, whose
 * previous use the caller has waited for. */
static void present_record(VkRenderPass pass, VkFramebuffer fb, int w, int h, unsigned slot, int mode)
{
    VkCommandBufferBeginInfo bi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    VkRenderPassBeginInfo rb = {VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER};
    VkViewport vp = {0.0f, 0.0f, (float)w, (float)h, 0.0f, 1.0f};
    VkRect2D sc = {{0, 0}, {(uint32_t)w, (uint32_t)h}};
    PicRect r = picture_layout(g_scr_w[slot], g_scr_h[slot], w, h, mode);
    struct {
        int32_t rx, ry, rw, rh;
        uint32_t w, h, at;
    } pc;
    pc.rx = r.x;
    pc.ry = r.y;
    pc.rw = r.w;
    pc.rh = r.h;
    pc.w = (uint32_t)g_scr_w[slot];
    pc.h = (uint32_t)g_scr_h[slot];
    pc.at = slot * (READBACK_BYTES / 4);
    bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    vkBeginCommandBuffer(g_pres_cb, &bi);
    /* The screen copy was written by an earlier submission's compute pass,
     * or by the host for the check: visible to this pass's fragment reads. */
    mb.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT | VK_ACCESS_HOST_WRITE_BIT;
    mb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
    vkCmdPipelineBarrier(g_pres_cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_HOST_BIT,
                         VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
    rb.renderPass = pass;
    rb.framebuffer = fb;
    rb.renderArea.extent.width = (uint32_t)w;
    rb.renderArea.extent.height = (uint32_t)h;
    vkCmdBeginRenderPass(g_pres_cb, &rb, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdBindPipeline(g_pres_cb, VK_PIPELINE_BIND_POINT_GRAPHICS, g_pres_pipe);
    vkCmdBindDescriptorSets(g_pres_cb, VK_PIPELINE_BIND_POINT_GRAPHICS, g_pres_layout, 0, 1, &g_pres_set, 0, NULL);
    vkCmdSetViewport(g_pres_cb, 0, 1, &vp);
    vkCmdSetScissor(g_pres_cb, 0, 1, &sc);
    vkCmdPushConstants(g_pres_cb, g_pres_layout, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof pc, &pc);
    vkCmdDraw(g_pres_cb, 3, 1, 0, 0);
    vkCmdEndRenderPass(g_pres_cb);
}

static void swap_free(void)
{
    uint32_t i;
    for (i = 0; i < g_swap_n; i++) {
        if (g_swap_fb[i]) vkDestroyFramebuffer(g_dev, g_swap_fb[i], NULL);
        if (g_swap_view[i]) vkDestroyImageView(g_dev, g_swap_view[i], NULL);
        g_swap_fb[i] = VK_NULL_HANDLE;
        g_swap_view[i] = VK_NULL_HANDLE;
    }
}

/* The swap chain for the window's client, w x h, FIFO (every device has it),
 * an 8-bit UNORM format so each byte arrives as it was drawn. A swap chain
 * that exists is passed as the old one and freed after. */
static int swap_make(int w, int h)
{
    VkSurfaceCapabilitiesKHR caps;
    VkSurfaceFormatKHR fmts[64];
    uint32_t nf = 64, i, want;
    VkSwapchainCreateInfoKHR ci = {VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR};
    VkSwapchainKHR old = g_swap, made = VK_NULL_HANDLE;
    VkFormat fmt = VK_FORMAT_UNDEFINED;
    if (p_vkGetPhysicalDeviceSurfaceCapabilitiesKHR(g_phys, g_surface, &caps) != VK_SUCCESS) return 0;
    if (p_vkGetPhysicalDeviceSurfaceFormatsKHR(g_phys, g_surface, &nf, fmts) < 0 || !nf) return 0;
    for (i = 0; i < nf && fmt == VK_FORMAT_UNDEFINED; i++)
        if (fmts[i].format == VK_FORMAT_B8G8R8A8_UNORM) fmt = fmts[i].format;
    for (i = 0; i < nf && fmt == VK_FORMAT_UNDEFINED; i++)
        if (fmts[i].format == VK_FORMAT_R8G8B8A8_UNORM) fmt = fmts[i].format;
    if (fmt == VK_FORMAT_UNDEFINED) {
        say("the window's surface offers no 8-bit UNORM format");
        return 0;
    }
    if (g_swap_format && fmt != g_swap_format) return 0; /* the pipeline was made for the first */
    g_swap_format = fmt;
    if (caps.currentExtent.width != 0xFFFFFFFFu) {
        g_swap_ext = caps.currentExtent;
    } else {
        g_swap_ext.width = (uint32_t)w;
        g_swap_ext.height = (uint32_t)h;
    }
    if (!g_swap_ext.width || !g_swap_ext.height) return 0; /* minimised */
    want = caps.minImageCount + 1 < 3 ? 3 : caps.minImageCount + 1;
    if (caps.maxImageCount && want > caps.maxImageCount) want = caps.maxImageCount;
    if (want > SWAP_MAX) want = SWAP_MAX;
    ci.surface = g_surface;
    ci.minImageCount = want;
    ci.imageFormat = fmt;
    ci.imageColorSpace = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;
    ci.imageExtent = g_swap_ext;
    ci.imageArrayLayers = 1;
    ci.imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
    ci.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
    ci.preTransform = caps.currentTransform;
    ci.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    ci.presentMode = VK_PRESENT_MODE_FIFO_KHR;
    ci.clipped = VK_TRUE;
    ci.oldSwapchain = old;
    if (p_vkCreateSwapchainKHR(g_dev, &ci, NULL, &made) != VK_SUCCESS) return 0;
    swap_free();
    if (old) p_vkDestroySwapchainKHR(g_dev, old, NULL);
    g_swap = made;
    g_swap_n = SWAP_MAX;
    if (p_vkGetSwapchainImagesKHR(g_dev, g_swap, &g_swap_n, g_swap_img) < 0) return 0;
    if (!g_pres_pass && !(g_pres_pass = present_pass(fmt, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR))) return 0;
    if (!present_pipeline(g_pres_pass)) return 0;
    for (i = 0; i < g_swap_n; i++) {
        VkImageViewCreateInfo vi = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        VkFramebufferCreateInfo fi = {VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};
        vi.image = g_swap_img[i];
        vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
        vi.format = fmt;
        vi.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        vi.subresourceRange.levelCount = 1;
        vi.subresourceRange.layerCount = 1;
        if (vkCreateImageView(g_dev, &vi, NULL, &g_swap_view[i]) != VK_SUCCESS) return 0;
        fi.renderPass = g_pres_pass;
        fi.attachmentCount = 1;
        fi.pAttachments = &g_swap_view[i];
        fi.width = g_swap_ext.width;
        fi.height = g_swap_ext.height;
        fi.layers = 1;
        if (vkCreateFramebuffer(g_dev, &fi, NULL, &g_swap_fb[i]) != VK_SUCCESS) return 0;
    }
    g_n_swap_made++;
    g_swap_stale = 0;
    return 1;
}

/* Everything outstanding on the queue finished, under its lock: only for a
 * swap chain remade, which is rare (a resize). */
static void queue_idle(void)
{
    plat_lock(&g_queue_lock);
    vkDeviceWaitIdle(g_dev);
    plat_unlock(&g_queue_lock);
}

int gxv_present_open(void* hinstance, void* native_window, int w, int h, char* why, size_t cap)
{
    GxvCreateWin32Surface create;
    GxvWin32SurfaceInfo si;
    VkBool32 ok = VK_FALSE;
    VkSemaphoreCreateInfo sm = {VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    unsigned i;
    if (!g_started) { snprintf(why, cap, "the GPU is not drawing"); return 0; }
    if (!g_inst_surface || !g_dev_swapchain) {
        snprintf(why, cap, "the Vulkan driver offers no window surface or swap chain");
        return 0;
    }
    create = (GxvCreateWin32Surface)vkGetInstanceProcAddr(g_inst, "vkCreateWin32SurfaceKHR");
#define GXV_PRES_I(name) p_##name = (PFN_##name)vkGetInstanceProcAddr(g_inst, #name);
#define GXV_PRES_D(name) p_##name = (PFN_##name)vkGetDeviceProcAddr(g_dev, #name);
    GXV_PRES_I(vkDestroySurfaceKHR)
    GXV_PRES_I(vkGetPhysicalDeviceSurfaceSupportKHR)
    GXV_PRES_I(vkGetPhysicalDeviceSurfaceCapabilitiesKHR)
    GXV_PRES_I(vkGetPhysicalDeviceSurfaceFormatsKHR)
    GXV_PRES_D(vkCreateSwapchainKHR)
    GXV_PRES_D(vkDestroySwapchainKHR)
    GXV_PRES_D(vkGetSwapchainImagesKHR)
    GXV_PRES_D(vkAcquireNextImageKHR)
    GXV_PRES_D(vkQueuePresentKHR)
    GXV_PRES_D(vkCreateSemaphore)
    GXV_PRES_D(vkDestroySemaphore)
    if (!create || !p_vkDestroySurfaceKHR || !p_vkGetPhysicalDeviceSurfaceSupportKHR || !p_vkGetPhysicalDeviceSurfaceCapabilitiesKHR ||
        !p_vkGetPhysicalDeviceSurfaceFormatsKHR || !p_vkCreateSwapchainKHR || !p_vkDestroySwapchainKHR || !p_vkGetSwapchainImagesKHR ||
        !p_vkAcquireNextImageKHR || !p_vkQueuePresentKHR || !p_vkCreateSemaphore || !p_vkDestroySemaphore) {
        snprintf(why, cap, "the Vulkan driver lacks an entry point the swap chain needs");
        return 0;
    }
    memset(&si, 0, sizeof si);
    si.sType = GXV_STYPE_WIN32_SURFACE;
    si.hinstance = hinstance;
    si.hwnd = native_window;
    if (create(g_inst, &si, NULL, &g_surface) != VK_SUCCESS) {
        snprintf(why, cap, "vkCreateWin32SurfaceKHR failed");
        return 0;
    }
    if (p_vkGetPhysicalDeviceSurfaceSupportKHR(g_phys, g_family, g_surface, &ok) != VK_SUCCESS || !ok) {
        snprintf(why, cap, "the queue the GPU draws on cannot present to this window");
        return 0;
    }
    for (i = 0; i < SWAP_MAX; i++)
        if (p_vkCreateSemaphore(g_dev, &sm, NULL, &g_swap_ready[i]) != VK_SUCCESS ||
            p_vkCreateSemaphore(g_dev, &sm, NULL, &g_swap_done[i]) != VK_SUCCESS) {
            snprintf(why, cap, "vkCreateSemaphore failed");
            return 0;
        }
    if (!present_commands() || !swap_make(w, h)) {
        snprintf(why, cap, "the swap chain could not be made for a %dx%d client", w, h);
        return 0;
    }
    say("presenting from the GPU: a %ux%u swap chain of %u images, FIFO, format %d (V8)", g_swap_ext.width,
        g_swap_ext.height, g_swap_n, (int)g_swap_format);
    return 1;
}

void gxv_present_resize(int w, int h)
{
    g_swap_want_w = w;
    g_swap_want_h = h;
    g_swap_stale = 1;
}

/* One present of slot `slot`: acquire, draw, submit, present. -1 when the
 * swap chain must be remade first, 0 on failure. */
static int present_once(unsigned slot, int mode)
{
    uint32_t img = 0;
    unsigned k = g_swap_k;
    VkResult r;
    VkSubmitInfo si = {VK_STRUCTURE_TYPE_SUBMIT_INFO};
    VkPresentInfoKHR pi = {VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};
    VkPipelineStageFlags wait = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    vkWaitForFences(g_dev, 1, &g_pres_fence, VK_TRUE, UINT64_MAX);
    r = p_vkAcquireNextImageKHR(g_dev, g_swap, UINT64_MAX, g_swap_ready[k], VK_NULL_HANDLE, &img);
    if (r == VK_ERROR_OUT_OF_DATE_KHR) return -1;
    if (r != VK_SUCCESS && r != VK_SUBOPTIMAL_KHR) return 0;
    g_swap_k = (k + 1) % g_swap_n;
    vkResetFences(g_dev, 1, &g_pres_fence);
    present_record(g_pres_pass, g_swap_fb[img], (int)g_swap_ext.width, (int)g_swap_ext.height, slot, mode);
    vkEndCommandBuffer(g_pres_cb);
    si.waitSemaphoreCount = 1;
    si.pWaitSemaphores = &g_swap_ready[k];
    si.pWaitDstStageMask = &wait;
    si.commandBufferCount = 1;
    si.pCommandBuffers = &g_pres_cb;
    si.signalSemaphoreCount = 1;
    si.pSignalSemaphores = &g_swap_done[img];
    pi.waitSemaphoreCount = 1;
    pi.pWaitSemaphores = &g_swap_done[img];
    pi.swapchainCount = 1;
    pi.pSwapchains = &g_swap;
    pi.pImageIndices = &img;
    plat_lock(&g_queue_lock);
    r = vkQueueSubmit(g_queue, 1, &si, g_pres_fence);
    if (r == VK_SUCCESS) r = p_vkQueuePresentKHR(g_queue, &pi);
    plat_unlock(&g_queue_lock);
    g_n_presents++;
    if (r == VK_ERROR_OUT_OF_DATE_KHR || r == VK_SUBOPTIMAL_KHR) g_swap_stale = 1;
    else if (r != VK_SUCCESS) return 0;
    return 1;
}

/* A frame of the host's, BGRA as window.c keeps it, into slot `slot` as the
 * RGBA words present.frag reads; the presenter's last read of the slot is
 * waited for first. */
static void upload_bgra(unsigned slot, const uint8_t* bgra, int w, int h)
{
    uint8_t* d = g_screen_map + (size_t)slot * READBACK_BYTES;
    size_t i, n = (size_t)w * h;
    if (g_pres_fence) vkWaitForFences(g_dev, 1, &g_pres_fence, VK_TRUE, UINT64_MAX);
    for (i = 0; i < n; i++, d += 4, bgra += 4) {
        d[0] = bgra[2];
        d[1] = bgra[1];
        d[2] = bgra[0];
        d[3] = bgra[3];
    }
    g_scr_w[slot] = w;
    g_scr_h[slot] = h;
}

/* Slot `slot` presented `interval` times, the swap chain remade where it
 * must be; under g_present_lock. */
static int present_slot(unsigned slot, unsigned interval, int mode)
{
    unsigned n, tries;
    int ok = 1;
    if (interval < 1) interval = 1;
    for (n = 0; n < interval && ok; n++)
        for (tries = 0; tries < 2; tries++) {
            int r;
            if (g_swap_stale) {
                queue_idle();
                if (!swap_make(g_swap_want_w, g_swap_want_h)) {
                    ok = 0; /* minimised, or no swap chain: try again at the next frame */
                    break;
                }
            }
            r = present_once(slot, mode);
            if (r > 0) break;
            if (r == 0) {
                ok = 0;
                break;
            }
            g_swap_stale = 1;
        }
    return ok;
}

int gxv_present_image(const uint8_t* bgra, int w, int h, unsigned interval, int mode)
{
    int ok;
    if (!bgra || w < 1 || h < 1 || (size_t)w * h * 4 > READBACK_BYTES) return 0;
    plat_lock(&g_present_lock);
    if (g_present_dead || !g_swap) {
        plat_unlock(&g_present_lock);
        return 0;
    }
    upload_bgra(SCREEN_HOST, bgra, w, h);
    g_n_present_images++;
    ok = present_slot(SCREEN_HOST, interval, mode);
    plat_unlock(&g_present_lock);
    return ok;
}

int gxv_present(int fresh, unsigned interval, int mode, int* shown_w, int* shown_h)
{
    int ok;
    plat_lock(&g_present_lock);
    if (g_present_dead || !g_swap) {
        plat_unlock(&g_present_lock);
        return 0;
    }
    if (fresh && (plat_load64(&g_scr_middle) & SCREEN_FRESH)) {
        /* What the last present read of the slot it gives back is done. */
        vkWaitForFences(g_dev, 1, &g_pres_fence, VK_TRUE, UINT64_MAX);
        g_scr_front = (unsigned)(plat_xchg64(&g_scr_middle, (int64_t)g_scr_front) & 3);
        g_n_present_frames++;
    }
    if (!g_scr_w[g_scr_front]) { /* nothing drawn yet */
        plat_unlock(&g_present_lock);
        return 0;
    }
    ok = present_slot(g_scr_front, interval, mode);
    if (shown_w) *shown_w = g_scr_w[g_scr_front];
    if (shown_h) *shown_h = g_scr_h[g_scr_front];
    plat_unlock(&g_present_lock);
    return ok;
}

/* The presenter's check (test_gxv_present.py): bgra (w x h), as window.c
 * keeps a frame, through upload_bgra and the present pass into a dw x dh
 * image of the swap chain's usual format, B8G8R8A8_UNORM, read back into
 * out, row by row. Not with a window open. */
int gxv_present_check(const uint8_t* bgra, int w, int h, int dw, int dh, int mode, uint8_t* out)
{
    VkImage img;
    VkImageView view;
    VkFramebuffer fb;
    VkImageViewCreateInfo vi = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    VkFramebufferCreateInfo fi = {VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};
    VkImageCreateInfo ii = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    VkMemoryRequirements req;
    VkDeviceMemory mem;
    VkDeviceSize off;
    VkBufferImageCopy rg;
    VkSubmitInfo si = {VK_STRUCTURE_TYPE_SUBMIT_INFO};
    VkBufferMemoryBarrier bb = {VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};

    if (!g_dev || w < 1 || h < 1 || w * h * 4 > (int)READBACK_BYTES || dw < 1 || dh < 1 || (size_t)dw * dh * 4 > CHECK_BYTES)
        return 0;
    if (!g_chk && !make_buffer(CHECK_BYTES, VK_BUFFER_USAGE_TRANSFER_DST_BIT, 1, &g_chk, &g_chk_map)) return 0;
    if (!g_pres_check_pass && !(g_pres_check_pass = present_pass(VK_FORMAT_B8G8R8A8_UNORM, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL)))
        return 0;
    if (!present_pipeline(g_pres_check_pass) || !present_commands()) return 0;
    ii.imageType = VK_IMAGE_TYPE_2D;
    ii.format = VK_FORMAT_B8G8R8A8_UNORM;
    ii.extent.width = (uint32_t)dw;
    ii.extent.height = (uint32_t)dh;
    ii.extent.depth = 1;
    ii.mipLevels = 1;
    ii.arrayLayers = 1;
    ii.samples = VK_SAMPLE_COUNT_1_BIT;
    ii.tiling = VK_IMAGE_TILING_OPTIMAL;
    ii.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    if (vkCreateImage(g_dev, &ii, NULL, &img) != VK_SUCCESS) return 0;
    vkGetImageMemoryRequirements(g_dev, img, &req);
    if (!bind_memory(&req, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, &mem, &off, NULL) ||
        vkBindImageMemory(g_dev, img, mem, off) != VK_SUCCESS)
        return 0;
    vi.image = img;
    vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
    vi.format = VK_FORMAT_B8G8R8A8_UNORM;
    vi.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    vi.subresourceRange.levelCount = 1;
    vi.subresourceRange.layerCount = 1;
    if (vkCreateImageView(g_dev, &vi, NULL, &view) != VK_SUCCESS) return 0;
    fi.renderPass = g_pres_check_pass;
    fi.attachmentCount = 1;
    fi.pAttachments = &view;
    fi.width = (uint32_t)dw;
    fi.height = (uint32_t)dh;
    fi.layers = 1;
    if (vkCreateFramebuffer(g_dev, &fi, NULL, &fb) != VK_SUCCESS) return 0;
    /* The image into the scratch slot as the window's own frame goes. */
    upload_bgra(SCREEN_SCRATCH, bgra, w, h);
    vkResetFences(g_dev, 1, &g_pres_fence);
    present_record(g_pres_check_pass, fb, dw, dh, SCREEN_SCRATCH, mode);
    memset(&rg, 0, sizeof rg);
    rg.bufferOffset = 0;
    rg.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    rg.imageSubresource.layerCount = 1;
    rg.imageExtent.width = (uint32_t)dw;
    rg.imageExtent.height = (uint32_t)dh;
    rg.imageExtent.depth = 1;
    vkCmdCopyImageToBuffer(g_pres_cb, img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, g_chk, 1, &rg);
    bb.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    bb.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    bb.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    bb.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    bb.buffer = g_chk;
    bb.size = VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(g_pres_cb, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 0, NULL, 1, &bb, 0, NULL);
    vkEndCommandBuffer(g_pres_cb);
    si.commandBufferCount = 1;
    si.pCommandBuffers = &g_pres_cb;
    plat_lock(&g_queue_lock);
    vkQueueSubmit(g_queue, 1, &si, g_pres_fence);
    plat_unlock(&g_queue_lock);
    vkWaitForFences(g_dev, 1, &g_pres_fence, VK_TRUE, UINT64_MAX);
    memcpy(out, g_chk_map, (size_t)dw * dh * 4);
    vkDestroyFramebuffer(g_dev, fb, NULL);
    vkDestroyImageView(g_dev, view, NULL);
    vkDestroyImage(g_dev, img, NULL);
    return 1;
}

static void present_report(void)
{
    if (g_swap || g_n_presents)
        say("presented from the GPU: %llu screen copies taken, %llu images of the window's own (P5a's filters, V8b), %llu "
            "presents, %llu swap chains made",
            g_n_present_frames, g_n_present_images, g_n_presents, g_n_swap_made);
}

static void present_shutdown(void)
{
    unsigned i;
    plat_lock(&g_present_lock);
    g_present_dead = 1;
    plat_unlock(&g_present_lock);
    swap_free();
    if (g_swap) p_vkDestroySwapchainKHR(g_dev, g_swap, NULL);
    g_swap = VK_NULL_HANDLE;
    for (i = 0; i < SWAP_MAX; i++) {
        if (g_swap_ready[i]) p_vkDestroySemaphore(g_dev, g_swap_ready[i], NULL);
        if (g_swap_done[i]) p_vkDestroySemaphore(g_dev, g_swap_done[i], NULL);
    }
    if (g_surface) p_vkDestroySurfaceKHR(g_inst, g_surface, NULL);
    g_surface = VK_NULL_HANDLE;
    if (g_pres_pipe) vkDestroyPipeline(g_dev, g_pres_pipe, NULL);
    if (g_pres_layout) vkDestroyPipelineLayout(g_dev, g_pres_layout, NULL);
    if (g_pres_dsl) vkDestroyDescriptorSetLayout(g_dev, g_pres_dsl, NULL);
    if (g_pres_dpool) vkDestroyDescriptorPool(g_dev, g_pres_dpool, NULL);
    if (g_pres_pass) vkDestroyRenderPass(g_dev, g_pres_pass, NULL);
    if (g_pres_check_pass) vkDestroyRenderPass(g_dev, g_pres_check_pass, NULL);
    if (g_pres_fence) vkDestroyFence(g_dev, g_pres_fence, NULL);
    if (g_chk) vkDestroyBuffer(g_dev, g_chk, NULL);
    if (g_pres_cpool) vkDestroyCommandPool(g_dev, g_pres_cpool, NULL);
}

int gxv_built(void) { return 1; }

#else /* SOA_GXV */

/* This build has no backend: vendor/ held no glslang or Vulkan-Headers when
 * it was linked. */
int gxv_built(void) { return 0; }

int gxv_start(char* why, size_t cap)
{
    snprintf(why, cap, "this build has no GPU backend: run `python tools/fetch_gpu.py`, then `python tools/recompile.py --link`");
    return 0;
}

int gxv_running(void) { return 0; }

int gxv_present_open(void* hinstance, void* native_window, int w, int h, char* why, size_t cap)
{
    (void)hinstance;
    (void)native_window;
    (void)w;
    (void)h;
    snprintf(why, cap, "this build has no GPU backend");
    return 0;
}

int gxv_present_image(const uint8_t* bgra, int w, int h, unsigned interval, int mode)
{
    (void)bgra;
    (void)w;
    (void)h;
    (void)interval;
    (void)mode;
    return 0;
}

int gxv_present(int fresh, unsigned interval, int mode, int* shown_w, int* shown_h)
{
    (void)fresh;
    (void)interval;
    (void)mode;
    (void)shown_w;
    (void)shown_h;
    return 0;
}

void gxv_present_resize(int w, int h)
{
    (void)w;
    (void)h;
}

#endif
