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
#include "raster_frag.h"

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
    X(vkCmdCopyImageToBuffer) X(vkCmdClearColorImage) X(vkCmdClearDepthStencilImage)

#define GXV_DECLARE(name) static PFN_##name name;
static PFN_vkGetInstanceProcAddr vkGetInstanceProcAddr;
GXV_GLOBAL(GXV_DECLARE)
GXV_INSTANCE(GXV_DECLARE)
GXV_DEVICE(GXV_DECLARE)

/* ---- state ---------------------------------------------------------------- */

#define RING_BYTES (32u << 20)     /* the vertex ring: about 215k vertices */
#define READBACK_BYTES (EFB_W * EFB_H * 4)
#define MAX_QUADS 16384            /* a draw's count is 16 bits: 65535 vertices */
#define ARENA_BYTES (64u << 20)    /* one bump-allocated block per memory type */
#define NPIPE (6 * 4 * 2 * 8 * 2 * 4)

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
static Arena g_arena[VK_MAX_MEMORY_TYPES];
static VkImage g_color, g_depth;
static VkImageView g_color_view, g_depth_view;
static VkRenderPass g_pass;
static VkFramebuffer g_fb;
static VkBuffer g_ring, g_quad_idx, g_readback;
static uint8_t *g_ring_map, *g_readback_map;
static uint32_t* g_quad_map;
static VkDescriptorSetLayout g_dsl;
static VkDescriptorPool g_dpool;
static VkDescriptorSet g_dset;
static VkPipelineLayout g_layout;
static VkShaderModule g_vs, g_fs;
static VkPipeline g_pipe[NPIPE];
static VkCommandPool g_cpool;
static VkCommandBuffer g_cb;
static VkFence g_fence;
static VkQueryPool g_qpool;
static int g_timestamps;

static int g_rec, g_inpass;      /* the command buffer is recording; the EFB pass is begun */
static VkPipeline g_bound;
static uint32_t g_ring_used;     /* bytes, a multiple of sizeof(Vertex) */
static Vertex* g_tmp;            /* a rebuilt draw, before it goes into the ring */
static unsigned g_tmp_cap;
static uint8_t* g_screen_buf;
static GxvUploadHook g_hook;
static int g_mut_unclipped;
static char g_devname[VK_MAX_PHYSICAL_DEVICE_NAME_SIZE];

static unsigned long long g_n_draws, g_n_rebuilt, g_n_verts, g_n_submits, g_n_clears, g_n_copies, g_n_pipes;
static double g_gpu_ms;

typedef struct {
    float wd, ht, xorig, yorig, zrange, farz;
    uint32_t base;
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
    int t = find_type(req->memoryTypeBits, want);
    Arena* a;
    VkDeviceSize align = req->alignment, gran = g_props.limits.bufferImageGranularity, o;
    if (t < 0) { say("no memory type with properties %#x for bits %#x", (unsigned)want, req->memoryTypeBits); return 0; }
    if (gran > align) align = gran;
    a = &g_arena[t];
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
    if (o + req->size > a->size) { say("memory type %d's block is full (%llu of %llu bytes)", t, (unsigned long long)o, (unsigned long long)a->size); return 0; }
    a->used = o + req->size;
    *mem = a->mem;
    *off = o;
    if (map) *map = a->map ? a->map + o : NULL;
    return 1;
}

static int make_buffer(VkDeviceSize size, VkBufferUsageFlags usage, VkBuffer* buf, uint8_t** map)
{
    VkBufferCreateInfo bi = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    VkMemoryRequirements req;
    VkDeviceMemory mem;
    VkDeviceSize off;
    bi.size = size;
    bi.usage = usage;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    VKCHECK(vkCreateBuffer(g_dev, &bi, NULL, buf));
    vkGetBufferMemoryRequirements(g_dev, *buf, &req);
    if (!bind_memory(&req, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT, &mem, &off, map)) return 0;
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
    VKCHECK(vkWaitForFences(g_dev, 1, &g_fence, VK_TRUE, UINT64_MAX));
    VKCHECK(vkResetFences(g_dev, 1, &g_fence));
    g_rec = 0;
    g_ring_used = 0;
    g_n_submits++;
    if (g_timestamps) {
        uint64_t ts[2];
        if (vkGetQueryPoolResults(g_dev, g_qpool, 0, 2, sizeof ts, ts, sizeof ts[0], VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT) == VK_SUCCESS)
            g_gpu_ms += (double)(ts[1] - ts[0]) * g_props.limits.timestampPeriod / 1e6;
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

static VkPipeline pipeline(int topo, const DrawCmd* D)
{
    int z_en = D->px.z_en != 0;
    unsigned zf = z_en ? (D->px.z_func & 7) : 0;
    int z_upd = z_en && D->px.z_upd;
    unsigned mask = (D->px.col_upd ? 1u : 0u) | (D->px.alpha_upd ? 2u : 0u);
    unsigned cull = topo <= T_FAN ? (D->rc.cull & 3) : 0;
    unsigned key = ((((((unsigned)topo * 4 + cull) * 2 + (unsigned)z_en) * 8 + zf) * 2 + (unsigned)z_upd) * 4) + mask;
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

    if (g_pipe[key]) return g_pipe[key];
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
    r = vkCreateGraphicsPipelines(g_dev, VK_NULL_HANDLE, 1, &pi, NULL, &g_pipe[key]);
    if (r != VK_SUCCESS) { say("vkCreateGraphicsPipelines failed: VkResult %d", (int)r); return VK_NULL_HANDLE; }
    g_n_pipes++;
    return g_pipe[key];
}

/* ---- the backend ------------------------------------------------------------ */

/* What V3a cannot draw, or NULL. Each is a later slice's work, and a draw
 * that needs it is refused rather than drawn as if it did not. */
static const char* unsupported(const DrawCmd* D)
{
    if (D->tev.fast_c != 1 || D->tev.fast_a != 2) return "a TEV shape other than the vertex colour (V3b's tev.glsl)";
    if (!(D->nchan & 1)) return "no colour channel 0";
    if (!D->tev.alpha_always) return "an alpha test that can reject (V4a)";
    if (D->px.blend_en || D->px.logic_en) return "blending or a logic op (V4a)";
    if (D->px.const_alpha >= 0) return "a constant alpha (3.4)";
    if (D->px.fog_type) return "fog (V4a)";
    return NULL;
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

    if (why) { say("draw refused: it needs %s", why); return 0; }
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
    vkCmdPushConstants(g_cb, g_layout, VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof pc, &pc);
    if (quads) vkCmdDrawIndexed(g_cb, n / 4 * 6, 1, 0, 0, 0);
    else vkCmdDraw(g_cb, n, 1, 0, 0);
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

/* Read the whole EFB back into g_readback_map. */
static int readback(void)
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
    bb.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    bb.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    bb.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    bb.buffer = g_readback;
    bb.size = VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 0, NULL, 1, &bb, 0, NULL);
    return submit_wait();
}

/* A copy to the screen, as copy_to_screen makes it from the EFB read back:
 * RGB copied (or the vertical filter, filter_sample's arithmetic) and alpha
 * 255, black outside the EFB. The GPU copy encoder is V3b's; a copy to a
 * texture is refused until then. */
static int gxv_copy(const DrawCmd* D)
{
    int x0 = (int)(D->cp_tl & 0x3FF), y0 = (int)((D->cp_tl >> 10) & 0x3FF);
    int w = (int)(D->cp_wh & 0x3FF) + 1, h = (int)((D->cp_wh >> 10) & 0x3FF) + 1;
    int filtered = !(D->cp_f_up == 0 && D->cp_f_dn == 0 && D->cp_f_mid == 64);
    int ytop = y0 < 0 ? 0 : y0, ybot = y0 + h - 1 > EFB_H - 1 ? EFB_H - 1 : y0 + h - 1;
    int x, y, k;
    const uint8_t* efb = g_readback_map;
    if (!(D->cp_v & 0x4000u)) { say("copy refused: a copy to a texture (V3b's copy.comp)"); return 0; }
    if (w > EFB_W) w = EFB_W;
    if (h > EFB_H) h = EFB_H;
    if (!readback()) return 0;
    for (y = 0; y < h; y++) {
        int sy = y0 + y;
        for (x = 0; x < w; x++) {
            int sx = x0 + x;
            uint8_t* o = g_screen_buf + ((size_t)y * w + x) * 4;
            if (sx >= 0 && sy >= 0 && sx < EFB_W && sy < EFB_H) {
                if (filtered) {
                    int ya = sy - 1 < ytop ? ytop : sy - 1, yb = sy + 1 > ybot ? ybot : sy + 1;
                    for (k = 0; k < 3; k++) {
                        unsigned v = D->cp_f_up * efb[((size_t)ya * EFB_W + sx) * 4 + k] +
                                     D->cp_f_mid * efb[((size_t)sy * EFB_W + sx) * 4 + k] +
                                     D->cp_f_dn * efb[((size_t)yb * EFB_W + sx) * 4 + k];
                        v >>= 6;
                        o[k] = (uint8_t)(v > 255u ? 255u : v);
                    }
                } else {
                    memcpy(o, efb + ((size_t)sy * EFB_W + sx) * 4, 3);
                }
                o[3] = 255;
            } else {
                o[0] = o[1] = o[2] = 0;
                o[3] = 255;
            }
        }
    }
    gxr_backend_screen(g_screen_buf, w, h);
    g_n_copies++;
    return 1;
}

static void gxv_finish(void)
{
    if (!submit_wait()) say("a submission failed");
}

static const GxrBackend g_gxv = {"vulkan", gxv_draw, gxv_copy, gxv_clear, gxv_reset_efb, gxv_finish};

const GxrBackend* gxv_backend(void) { return &g_gxv; }
const char* gxv_device_name(void) { return g_devname; }
void gxv_set_upload_hook(GxvUploadHook h) { g_hook = h; }

int gxv_set_mutation(const char* name)
{
    if (!strcmp(name, "unclipped")) { g_mut_unclipped = 1; return 1; }
    return 0;
}

void gxv_report(void)
{
    say("%llu draws (%llu rebuilt by clipping), %llu vertices, %llu clears, %llu screen copies, %llu pipelines, "
        "%llu submissions, GPU %.3f ms%s",
        g_n_draws, g_n_rebuilt, g_n_verts, g_n_clears, g_n_copies, g_n_pipes, g_n_submits, g_gpu_ms,
        g_timestamps ? "" : " (this queue has no timestamps)");
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
    memset(&feat, 0, sizeof feat); /* core features only (3.10) */
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
    VkDescriptorSetLayoutBinding b = {0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_VERTEX_BIT, NULL};
    VkDescriptorSetLayoutCreateInfo li = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    VkPushConstantRange pr = {VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof(PushDraw)};
    VkPipelineLayoutCreateInfo pi = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1};
    VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    VkDescriptorSetAllocateInfo ai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    VkDescriptorBufferInfo bi = {0};
    VkWriteDescriptorSet w = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
    VkShaderModuleCreateInfo si = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    li.bindingCount = 1;
    li.pBindings = &b;
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
    bi.buffer = g_ring;
    bi.range = VK_WHOLE_SIZE;
    w.dstSet = g_dset;
    w.descriptorCount = 1;
    w.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    w.pBufferInfo = &bi;
    vkUpdateDescriptorSets(g_dev, 1, &w, 0, NULL);
    si.codeSize = sizeof raster_vert;
    si.pCode = raster_vert;
    VKCHECK(vkCreateShaderModule(g_dev, &si, NULL, &g_vs));
    si.codeSize = sizeof raster_frag;
    si.pCode = raster_frag;
    VKCHECK(vkCreateShaderModule(g_dev, &si, NULL, &g_fs));
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
        !make_buffer(RING_BYTES, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &g_ring, &g_ring_map) ||
        !make_buffer((VkDeviceSize)MAX_QUADS * 6 * 4, VK_BUFFER_USAGE_INDEX_BUFFER_BIT, &g_quad_idx, (uint8_t**)&g_quad_map) ||
        !make_buffer(READBACK_BYTES, VK_BUFFER_USAGE_TRANSFER_DST_BIT, &g_readback, &g_readback_map) || !make_pass() ||
        !make_layout() || !make_commands() || !init_images()) {
        snprintf(why, cap, "setting up on %s failed (see above)", g_devname);
        return 0;
    }
    /* Quads as two triangles each, (0, 1, 2) and (0, 2, 3): draw_command's split. */
    for (i = 0; i < MAX_QUADS; i++) {
        uint32_t* q = g_quad_map + i * 6, b = i * 4;
        q[0] = b; q[1] = b + 1; q[2] = b + 2; q[3] = b; q[4] = b + 2; q[5] = b + 3;
    }
    g_screen_buf = (uint8_t*)malloc(READBACK_BYTES);
    if (!g_screen_buf) { snprintf(why, cap, "cannot allocate the screen buffer"); return 0; }
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
    for (i = 0; i < NPIPE; i++)
        if (g_pipe[i]) vkDestroyPipeline(g_dev, g_pipe[i], NULL);
    if (g_qpool) vkDestroyQueryPool(g_dev, g_qpool, NULL);
    vkDestroyFence(g_dev, g_fence, NULL);
    vkDestroyCommandPool(g_dev, g_cpool, NULL);
    vkDestroyShaderModule(g_dev, g_vs, NULL);
    vkDestroyShaderModule(g_dev, g_fs, NULL);
    vkDestroyDescriptorPool(g_dev, g_dpool, NULL);
    vkDestroyPipelineLayout(g_dev, g_layout, NULL);
    vkDestroyDescriptorSetLayout(g_dev, g_dsl, NULL);
    vkDestroyFramebuffer(g_dev, g_fb, NULL);
    vkDestroyRenderPass(g_dev, g_pass, NULL);
    vkDestroyBuffer(g_dev, g_ring, NULL);
    vkDestroyBuffer(g_dev, g_quad_idx, NULL);
    vkDestroyBuffer(g_dev, g_readback, NULL);
    vkDestroyImageView(g_dev, g_color_view, NULL);
    vkDestroyImageView(g_dev, g_depth_view, NULL);
    vkDestroyImage(g_dev, g_color, NULL);
    vkDestroyImage(g_dev, g_depth, NULL);
    for (i = 0; i < VK_MAX_MEMORY_TYPES; i++)
        if (g_arena[i].mem) vkFreeMemory(g_dev, g_arena[i].mem, NULL);
    vkDestroyDevice(g_dev, NULL);
    vkDestroyInstance(g_inst, NULL);
    g_dev = VK_NULL_HANDLE;
    free(g_tmp);
    free(g_screen_buf);
}
