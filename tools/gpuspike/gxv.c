/*
 * gxv: the GPU spike's Vulkan backend. See gxv.h for what it draws and what
 * it refuses, and specs/gpu-backend.md 3.2-3.3 for the design it follows.
 *
 * One queue, one command buffer, recorded as the renderer's commands arrive
 * and submitted when something must wait for the GPU: a screen copy, the
 * renderer's finish, or a full vertex ring. Every submission is waited for on
 * a fence before the next is recorded, so nothing here is ever in flight
 * behind the CPU's back -- the spike measures correctness, and V4a the
 * pipelining.
 *
 * Built only by tools/gpuspike.py, never into soa.exe.
 */
#define _CRT_SECURE_NO_WARNINGS
#define VK_NO_PROTOTYPES
#include "gxv.h"
#include <vulkan/vulkan_core.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#include "raster_vert.h"
#include "raster_vert_noinvariant.h"
#include "raster_frag.h"
#include "raster_frag_alpha.h"
#include "raster_frag_lod.h"
#include "raster_frag_fog.h"
#include "tevdiff_comp.h"
#include "tevdiff_comp_clamp.h"
#include "copy_comp.h"
#include "copy_comp_rounding.h"
#include "copy_comp_intensity.h"

/* The shader reads a Vertex as 39 floats; gxr.h's layout is what it reads. */
typedef char gxv_vertex_is_39_floats[sizeof(Vertex) == 39 * sizeof(float) ? 1 : -1];

/* ---- the entry points, resolved at run time --------------------------- */

#define GXV_GLOBAL(X) X(vkCreateInstance) X(vkEnumerateInstanceLayerProperties)
#define GXV_INSTANCE(X)                                                                                  \
    X(vkDestroyInstance) X(vkEnumeratePhysicalDevices) X(vkGetPhysicalDeviceProperties)                  \
    X(vkGetPhysicalDeviceQueueFamilyProperties) X(vkGetPhysicalDeviceMemoryProperties)                   \
    X(vkGetPhysicalDeviceFormatProperties) X(vkCreateDevice) X(vkGetDeviceProcAddr)
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
    X(vkCmdBindDescriptorSets) X(vkCmdBindIndexBuffer) X(vkCmdPushConstants) X(vkCmdSetScissor)          \
    X(vkCmdDraw) X(vkCmdDrawIndexed) X(vkCmdClearAttachments) X(vkCmdPipelineBarrier)                    \
    X(vkCmdCopyImageToBuffer) X(vkCmdClearColorImage) X(vkCmdClearDepthStencilImage)                    \
    X(vkCreateComputePipelines) X(vkCmdDispatch) X(vkCmdCopyBufferToImage) X(vkCmdBeginQuery) X(vkCmdEndQuery)

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
static struct {
    uint32_t key; /* 0: free */
    VkPipeline pipe;
} g_pipes[PIPE_SLOTS];
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
static int g_mut_noinvariant;
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
static double g_gpu_ms;

typedef struct {
    float wd, ht, xorig, yorig, zrange, farz;
    uint32_t base;
    uint32_t record; /* in the draw records, in words */
} PushDraw;

static void say(const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fputs("[gxv] ", stderr);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
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

static int load_loader(char* why, size_t cap)
{
#ifdef _WIN32
    HMODULE m = LoadLibraryA("vulkan-1.dll");
    if (!m) { snprintf(why, cap, "no Vulkan loader: LoadLibrary(vulkan-1.dll) failed (error %lu)", GetLastError()); return 0; }
    g_lib = m;
    vkGetInstanceProcAddr = (PFN_vkGetInstanceProcAddr)(void (*)(void))GetProcAddress(m, "vkGetInstanceProcAddr");
#else
    void* m = dlopen("libvulkan.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!m) m = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
    if (!m) { snprintf(why, cap, "no Vulkan loader: dlopen(libvulkan.so.1) failed: %s", dlerror()); return 0; }
    g_lib = m;
    *(void**)&vkGetInstanceProcAddr = dlsym(m, "vkGetInstanceProcAddr");
#endif
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

/* Submit what is recorded and wait for it. The vertex ring is free again. */
static int submit_wait(void)
{
    VkSubmitInfo si = {VK_STRUCTURE_TYPE_SUBMIT_INFO};
    if (!g_rec) return 1;
    end_pass();
    if (g_timestamps) vkCmdWriteTimestamp(g_cb, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, g_qpool, 1);
    VKCHECK(vkEndCommandBuffer(g_cb));
    si.commandBufferCount = 1;
    si.pCommandBuffers = &g_cb;
    VKCHECK(vkQueueSubmit(g_queue, 1, &si, g_fence));
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
    return 1;
}

static VkPipeline pipeline(int topo, const DrawCmd* D)
{
    int z_en = D->px.z_en != 0;
    unsigned zf = z_en ? (D->px.z_func & 7) : 0;
    int z_upd = z_en && D->px.z_upd;
    unsigned mask = (D->px.col_upd ? 1u : 0u) | (D->px.alpha_upd ? 2u : 0u);
    unsigned cull = topo <= T_FAN ? (D->rc.cull & 3) : 0;
    unsigned blend = D->px.blend_en ? 1u | (D->px.sfac & 7) << 1 | (D->px.dfac & 7) << 4 | (D->px.subtract ? 1u : 0u) << 7 : 0u;
    uint32_t key = 1u + ((((((((uint32_t)topo * 4 + cull) * 2 + (uint32_t)z_en) * 8 + zf) * 2 + (uint32_t)z_upd) * 4 + mask) << 8) | blend);
    unsigned slot = (key * 2654435761u) >> 20 & (PIPE_SLOTS - 1), probes;
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
    VkDynamicState dyn[1] = {VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dys = {VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO};
    VkGraphicsPipelineCreateInfo pi = {VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};
    VkResult r;

    for (probes = 0; probes < PIPE_SLOTS; probes++, slot = (slot + 1) & (PIPE_SLOTS - 1)) {
        if (g_pipes[slot].key == key) return g_pipes[slot].pipe;
        if (!g_pipes[slot].key) break;
    }
    if (probes == PIPE_SLOTS) { say("the pipeline cache is full"); return VK_NULL_HANDLE; }
    if (!fragment_module()) return VK_NULL_HANDLE;
    st[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    st[0].module = g_vs;
    st[0].pName = "main";
    st[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    st[1].module = g_fs;
    st[1].pName = "main";
    ia.topology = k_topo[topo];
    vps.viewportCount = 1;
    vps.pViewports = &vp;
    vps.scissorCount = 1;
    vps.pScissors = &sc;
    rs.polygonMode = VK_POLYGON_MODE_FILL;
    rs.cullMode = k_cull[cull];
    rs.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rs.lineWidth = 1.0f;
    ms.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
    ds.depthTestEnable = (VkBool32)z_en;
    ds.depthWriteEnable = (VkBool32)z_upd;
    ds.depthCompareOp = k_zfunc[zf];
    ba.colorWriteMask = ((mask & 1) ? VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT : 0) |
                        ((mask & 2) ? VK_COLOR_COMPONENT_A_BIT : 0);
    /* blend_pixel: the colour blended by the factors, or the destination
     * less the source with the factors ignored; the alpha stored as the
     * source gives it, never blended. */
    if (blend) {
        ba.blendEnable = VK_TRUE;
        if (D->px.subtract) {
            ba.colorBlendOp = VK_BLEND_OP_REVERSE_SUBTRACT;
            ba.srcColorBlendFactor = VK_BLEND_FACTOR_ONE;
            ba.dstColorBlendFactor = VK_BLEND_FACTOR_ONE;
        } else {
            ba.colorBlendOp = VK_BLEND_OP_ADD;
            ba.srcColorBlendFactor = k_src_factor[D->px.sfac & 7];
            ba.dstColorBlendFactor = k_dst_factor[D->px.dfac & 7];
        }
        ba.alphaBlendOp = VK_BLEND_OP_ADD;
        ba.srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE;
        ba.dstAlphaBlendFactor = VK_BLEND_FACTOR_ZERO;
    }
    cb.attachmentCount = 1;
    cb.pAttachments = &ba;
    dys.dynamicStateCount = 1;
    dys.pDynamicStates = dyn;
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
    pi.renderPass = g_pass;
    r = vkCreateGraphicsPipelines(g_dev, VK_NULL_HANDLE, 1, &pi, NULL, &g_pipes[slot].pipe);
    if (r != VK_SUCCESS) { say("vkCreateGraphicsPipelines failed: VkResult %d", (int)r); return VK_NULL_HANDLE; }
    g_pipes[slot].key = key;
    g_n_pipes++;
    return g_pipes[slot].pipe;
}

/* ---- the backend ------------------------------------------------------------ */

/* What the spike cannot draw yet, or NULL: logic ops are V4b's, and a
 * constant alpha, which nothing in the corpus sets (2.2), would need
 * dual-source blending to store (3.4). Refused rather than drawn wrong. */
static const char* unsupported(const DrawCmd* D)
{
    if (!D->px.blend_en && D->px.logic_en) return "a logic op (V4b)";
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
    if (g_resident[id].epoch == g_epoch && g_resident[id].gen == C->tex_gen) return g_resident[id].rec;
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
 * written: the caller submits, which frees the pool, and asks again. */
static int draw_record(const DrawCmd* D, uint32_t* r)
{
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
    memset(r, 0, GXV_DRAW_WORDS * 4);
    gxv_pack_tev(&D->tev, r);
    r[98] = (D->ntex & 255) | (D->nchan & 3) << 8 | (D->miptex & 255) << 16;
    for (i = 0; i < 8; i++) r[99] |= (uint32_t)(D->texmap_of[i] & 7) << (3 * i);
    r[100] = (D->px.fog_type & 7) | (D->px.fog_proj & 1) << 3 | (D->px.fog_b_shift & 31) << 8;
    r[101] = float_bits(D->px.fog_a);
    r[102] = float_bits(D->px.fog_c);
    r[103] = D->px.fog_b_mag;
    r[104] = (uint32_t)D->px.fog_color[0] | (uint32_t)D->px.fog_color[1] << 8 | (uint32_t)D->px.fog_color[2] << 16;
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

static int gxv_draw(const DrawCmd* D)
{
    const char* why = unsupported(D);
    const Vertex* up = D->v;
    unsigned n = D->count, first;
    int topo, rebuilt = 0, quads = 0;
    const Rect* s = &D->rc.scissor;
    VkRect2D sc;
    PushDraw pc;
    VkPipeline p;

    static int ztop_said;
    if (why) { say("draw refused: it needs %s", why); return 0; }
    /* The late depth test the shader gives is the CPU's order except for a
     * ztop draw whose alpha test can reject, which the corpus has none of
     * (3.4); said once if one comes. */
    if (D->px.ztop && !D->tev.alpha_always && !ztop_said++)
        say("a ztop draw with an alpha test that can reject: the GPU tests depth after the TEV, the CPU before (tripwire, 3.4)");
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
    if (!draw_record(D, (uint32_t*)g_draw_map + g_draw_used)) {
        if (!submit_wait()) return 0;
        if (!draw_record(D, (uint32_t*)g_draw_map + g_draw_used)) {
            say("draw refused: its textures do not fit the %u-texel pool", g_pool_cap);
            return 0;
        }
    }
    if (!begin_pass()) return 0;
    p = pipeline(topo, D);
    if (!p) return 0;
    first = g_ring_used / (uint32_t)sizeof(Vertex);
    memcpy(g_ring_map + g_ring_used, up, (size_t)n * sizeof(Vertex));
    g_ring_used += n * (uint32_t)sizeof(Vertex);
    g_n_verts += n;
    if (p != g_bound) { vkCmdBindPipeline(g_cb, VK_PIPELINE_BIND_POINT_GRAPHICS, p); g_bound = p; }
    vkCmdSetScissor(g_cb, 0, 1, &sc);
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

static Compute g_copy_cs, g_tev_cs;

static int compute_make(Compute* c, const uint32_t* code, size_t bytes, unsigned nbuf, uint32_t push_bytes)
{
    VkDescriptorSetLayoutBinding b[4];
    VkDescriptorSetLayoutCreateInfo li = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, push_bytes};
    VkPipelineLayoutCreateInfo pli = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 4};
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
    VKCHECK(vkCreateComputePipelines(g_dev, VK_NULL_HANDLE, 1, &ci, NULL, &c->pipe));
    return 1;
}

static void compute_bind(Compute* c, const VkBuffer* bufs, unsigned n)
{
    VkDescriptorBufferInfo bi[4];
    VkWriteDescriptorSet w[4];
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

static unsigned g_img_w, g_img_h;
static unsigned long long g_n_tex_copies, g_n_refused;

/* The EFB's colour into the readback buffer, where the copy shader reads it. */
static int efb_to_buffer(void)
{
    VkBufferImageCopy rg;
    VkBufferMemoryBarrier bb = {VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};
    if (!begin_cb()) return 0;
    end_pass();
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
    vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 0, NULL, 1, &bb, 0, NULL);
    return 1;
}

static int copy_pipeline(void)
{
    VkBuffer bufs[4];
    const uint32_t* code = copy_comp;
    size_t bytes = sizeof copy_comp;
    if (g_copy_cs.pipe) return 1;
    if (g_mut_copy == 1) { code = copy_comp_rounding; bytes = sizeof copy_comp_rounding; }
    if (g_mut_copy == 2) { code = copy_comp_intensity; bytes = sizeof copy_comp_intensity; }
    if (!compute_make(&g_copy_cs, code, bytes, 4, sizeof(CopyPush))) return 0;
    bufs[0] = g_readback;
    bufs[1] = g_destbuf;
    bufs[2] = g_imagebuf;
    bufs[3] = g_screenbuf;
    compute_bind(&g_copy_cs, bufs, 4);
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
    if (!copy_pipeline() || !efb_to_buffer()) return 0;
    run_compute(&g_copy_cs, &p, sizeof p, p.count);
    compute_to_host();
    if (!submit_wait()) return 0;
    gxr_backend_screen(g_screen_map, sw, sh);
    g_n_copies++;
    return 1;
}

/* A copy to a texture, as copy_to_texture makes it: the bytes into guest
 * RAM over the copy's span, and its decoded image (V7's copy image; kept for
 * the self test). A format the CPU refuses, or a span past the end of
 * memory, leaves RAM untouched, as there. */
static int copy_texture(const DrawCmd* D)
{
    CopyPush p;
    unsigned chan_a, chan_b, texfmt = copy_texfmt(D->cp_v, &chan_a, &chan_b), tw, th, bpt;
    uint32_t dest = (D->cp_dest & 0x1FFFFFu) << 5, natural, row_bytes, rows, cols, extent;
    int half = (D->cp_v >> 9) & 1;
    uint8_t* ram;
    if (texfmt == 99) { g_n_refused++; return 1; }
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
    p.texfmt = texfmt;
    p.flags |= ((D->cp_v >> 15) & 1) | (uint32_t)half << 1;
    p.chans = chan_a | chan_b << 2;
    p.row_bytes = row_bytes;
    ram = mem_ptr(D->s, dest | 0x80000000u);
    /* Seeded from RAM: what the copy does not write keeps its bytes.
     * --mutate unseeded writes back whatever the buffer held instead. */
    if (!g_mut_unseeded) memcpy(g_dest_map, ram, extent);
    if (!copy_pipeline() || !efb_to_buffer()) return 0;
    p.mode = 0;
    p.count = extent / 4;
    run_compute(&g_copy_cs, &p, sizeof p, p.count);
    p.mode = 1;
    p.count = p.ow * p.oh;
    run_compute(&g_copy_cs, &p, sizeof p, p.count);
    compute_to_host();
    if (!submit_wait()) return 0;
    memcpy(ram, g_dest_map, extent);
    g_img_w = p.ow;
    g_img_h = p.oh;
    if (D->cp_image) memcpy(D->cp_image, g_image_map, (size_t)p.ow * p.oh * 4);
    g_n_tex_copies++;
    return 1;
}

static int gxv_copy(const DrawCmd* D)
{
    return (D->cp_v & 0x4000u) ? copy_screen(D) : copy_texture(D);
}

const uint8_t* gxv_last_copy_image(unsigned* w, unsigned* h)
{
    *w = g_img_w;
    *h = g_img_h;
    return g_image_map;
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

static void gxv_finish(void)
{
    if (!submit_wait()) say("a submission failed");
}

static int timed_draw(const DrawCmd* D)
{
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    int r = gxv_draw(D);
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
    return r;
}

static int timed_copy(const DrawCmd* D)
{
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    int r = gxv_copy(D);
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
    return r;
}

static int timed_clear(const DrawCmd* D)
{
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    int r = gxv_clear(D);
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
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
    uint64_t t0 = plat_mono_ns(), w0 = g_wait_ns;
    gxv_finish();
    g_consumer_ns += plat_mono_ns() - t0 - (g_wait_ns - w0);
}

static const GxrBackend g_gxv = {"vulkan", timed_draw, timed_copy, timed_clear, timed_reset_efb, timed_finish};

const GxrBackend* gxv_backend(void) { return &g_gxv; }
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
    else if (!strcmp(name, "measure")) g_measure = 1;
    else if (!strncmp(name, "skip-draw:", 10) && atoi(name + 10) > 0) g_skip_draw = (unsigned long long)atoi(name + 10);
    else return 0;
    return 1;
}

void gxv_report(void)
{
    say("%llu draws (%llu rebuilt by clipping), %llu vertices, %llu clears, %llu screen copies, %llu copies to a "
        "texture (%llu refused), %llu pipelines, %llu submissions, GPU %.3f ms%s",
        g_n_draws, g_n_rebuilt, g_n_verts, g_n_clears, g_n_copies, g_n_tex_copies, g_n_refused, g_n_pipes, g_n_submits, g_gpu_ms,
        g_timestamps ? "" : " (this queue has no timestamps)");
    say("consumer %.3f ms, waiting for the GPU %.3f ms", (double)g_consumer_ns / 1e6, (double)g_wait_ns / 1e6);
    if (g_measure)
        say("largest draws (draw:samples) %llu:%llu %llu:%llu %llu:%llu %llu:%llu %llu:%llu%s", g_top_draw[0], g_top_samples[0],
            g_top_draw[1], g_top_samples[1], g_top_draw[2], g_top_samples[2], g_top_draw[3], g_top_samples[3], g_top_draw[4],
            g_top_samples[4], g_precise ? "" : " (not precise)");
}

/* ---- set-up --------------------------------------------------------------- */

/* The device: GXV_DEVICE=<n> picks one; otherwise the first discrete GPU,
 * then the first integrated, then anything with a graphics queue. */
static int pick_device(char* why, size_t cap)
{
    VkPhysicalDevice devs[16];
    uint32_t n = 16, i, best = UINT32_MAX, best_rank = 0;
    const char* want = getenv("GXV_DEVICE");
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
    if (best == UINT32_MAX) { snprintf(why, cap, "no Vulkan device with a graphics queue%s", want ? " (GXV_DEVICE)" : ""); return 0; }
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
        VkPhysicalDeviceFeatures have;
        PFN_vkGetPhysicalDeviceFeatures get = (PFN_vkGetPhysicalDeviceFeatures)vkGetInstanceProcAddr(g_inst, "vkGetPhysicalDeviceFeatures");
        if (get) {
            get(g_phys, &have);
            feat.occlusionQueryPrecise = have.occlusionQueryPrecise;
            g_precise = have.occlusionQueryPrecise != 0;
        }
    }
    qi.queueFamilyIndex = g_family;
    qi.queueCount = 1;
    qi.pQueuePriorities = &prio;
    di.queueCreateInfoCount = 1;
    di.pQueueCreateInfos = &qi;
    di.pEnabledFeatures = &feat;
    r = vkCreateDevice(g_phys, &di, NULL, &g_dev);
    if (r != VK_SUCCESS) { snprintf(why, cap, "vkCreateDevice on %s failed: VkResult %d", g_devname, (int)r); return 0; }
    if (!load_device(why, cap)) return 0;
    vkGetDeviceQueue(g_dev, g_family, 0, &g_queue);
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
    return 1;
}

static int make_layout(void)
{
    VkDescriptorSetLayoutBinding b[4];
    VkDescriptorSetLayoutCreateInfo li = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    VkPushConstantRange pr = {VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(PushDraw)};
    VkPipelineLayoutCreateInfo pi = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 4};
    VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    VkDescriptorSetAllocateInfo ai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    VkDescriptorBufferInfo bi[4];
    VkWriteDescriptorSet w[4];
    VkShaderModuleCreateInfo si = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    VkBuffer bufs[4];
    unsigned i;
    /* 0 the vertices (the vertex stage); 1 the draw records, 2 the texel
     * pool, 3 the texture records (the fragment stage). */
    bufs[0] = g_ring;
    bufs[1] = g_drawbuf;
    bufs[2] = g_poolbuf;
    bufs[3] = g_texrecbuf;
    for (i = 0; i < 4; i++) {
        b[i].binding = i;
        b[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        b[i].descriptorCount = 1;
        b[i].stageFlags = i == 0 ? VK_SHADER_STAGE_VERTEX_BIT : VK_SHADER_STAGE_FRAGMENT_BIT;
        b[i].pImmutableSamplers = NULL;
    }
    li.bindingCount = 4;
    li.pBindings = b;
    VKCHECK(vkCreateDescriptorSetLayout(g_dev, &li, NULL, &g_dsl));
    pi.setLayoutCount = 1;
    pi.pSetLayouts = &g_dsl;
    pi.pushConstantRangeCount = 1;
    pi.pPushConstantRanges = &pr;
    VKCHECK(vkCreatePipelineLayout(g_dev, &pi, NULL, &g_layout));
    dpi.maxSets = 1;
    dpi.poolSizeCount = 1;
    dpi.pPoolSizes = &ps;
    VKCHECK(vkCreateDescriptorPool(g_dev, &dpi, NULL, &g_dpool));
    ai.descriptorPool = g_dpool;
    ai.descriptorSetCount = 1;
    ai.pSetLayouts = &g_dsl;
    VKCHECK(vkAllocateDescriptorSets(g_dev, &ai, &g_dset));
    for (i = 0; i < 4; i++) {
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
    vkUpdateDescriptorSets(g_dev, 4, w, 0, NULL);
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

int gxv_init(char* why, size_t cap)
{
    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO};
    VkInstanceCreateInfo ii = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    const char* layer = "VK_LAYER_KHRONOS_validation";
    const char* val = getenv("GXV_VALIDATE");
    VkResult r;
    unsigned i;
    why[0] = 0;
    if (!load_loader(why, cap)) return 0;
    app.pApplicationName = "soa-gpuspike";
    app.apiVersion = VK_API_VERSION_1_1;
    ii.pApplicationInfo = &app;
    /* GXV_VALIDATE=1 asks for the Khronos validation layer, where one is
     * installed (it comes with the Vulkan SDK, which nothing here needs). */
    if (val && atoi(val)) {
        VkLayerProperties lp[64];
        uint32_t n = 64, k;
        int have = 0;
        if (vkEnumerateInstanceLayerProperties && vkEnumerateInstanceLayerProperties(&n, lp) >= 0)
            for (k = 0; k < n; k++)
                if (!strcmp(lp[k].layerName, layer)) have = 1;
        if (have) { ii.enabledLayerCount = 1; ii.ppEnabledLayerNames = &layer; }
        say("GXV_VALIDATE: %s", have ? "the validation layer is on" : "no validation layer is installed; running without it");
    }
    r = vkCreateInstance(&ii, NULL, &g_inst);
    if (r != VK_SUCCESS) { snprintf(why, cap, "vkCreateInstance failed: VkResult %d (no Vulkan 1.1 driver?)", (int)r); return 0; }
    if (!load_instance(why, cap) || !pick_device(why, cap) || !make_device(why, cap)) return 0;
    if (!make_image(VK_FORMAT_R8G8B8A8_UNORM, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
                    VK_IMAGE_ASPECT_COLOR_BIT, &g_color, &g_color_view) ||
        !make_image(VK_FORMAT_D32_SFLOAT, VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
                    VK_IMAGE_ASPECT_DEPTH_BIT, &g_depth, &g_depth_view) ||
        !make_buffer(RING_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 0, &g_ring, &g_ring_map) ||
        !make_buffer((VkDeviceSize)MAX_QUADS * 6 * 4, VK_BUFFER_USAGE_INDEX_BUFFER_BIT, 0, &g_quad_idx, (uint8_t**)&g_quad_map) ||
        !make_buffer(READBACK_BYTES, VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
                     0, &g_readback, &g_readback_map) ||
        !make_buffer(DEST_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 1, &g_destbuf, &g_dest_map) ||
        !make_buffer(IMAGE_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 1, &g_imagebuf, &g_image_map) ||
        !make_buffer(READBACK_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, 1, &g_screenbuf, &g_screen_map) ||
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
    say("device %s (Vulkan %u.%u.%u, driver %#x), timestamps %s", g_devname, VK_API_VERSION_MAJOR(g_props.apiVersion),
        VK_API_VERSION_MINOR(g_props.apiVersion), VK_API_VERSION_PATCH(g_props.apiVersion), g_props.driverVersion,
        g_timestamps ? "on" : "unavailable");
    return 1;
}

void gxv_shutdown(void)
{
    unsigned i;
    if (!g_dev) return;
    vkDeviceWaitIdle(g_dev);
    for (i = 0; i < PIPE_SLOTS; i++)
        if (g_pipes[i].key) vkDestroyPipeline(g_dev, g_pipes[i].pipe, NULL);
    if (g_qpool) vkDestroyQueryPool(g_dev, g_qpool, NULL);
    if (g_occ) vkDestroyQueryPool(g_dev, g_occ, NULL);
    vkDestroyFence(g_dev, g_fence, NULL);
    vkDestroyCommandPool(g_dev, g_cpool, NULL);
    if (g_vs) vkDestroyShaderModule(g_dev, g_vs, NULL);
    if (g_fs) vkDestroyShaderModule(g_dev, g_fs, NULL);
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
    compute_free(&g_copy_cs);
    compute_free(&g_tev_cs);
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
    vkDestroyInstance(g_inst, NULL);
    g_dev = VK_NULL_HANDLE;
    free(g_tmp);
}
