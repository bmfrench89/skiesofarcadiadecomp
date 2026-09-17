/*
 * The graphics processor's front end: write-gather pipe, command stream,
 * register shadows, and the interrupts the pixel engine raises.
 *
 * Vertex submission is inlined into game code (SPEC section 7), so the only
 * faithful place to see it is the byte stream the CPU pushes through the
 * write-gather pipe at 0xCC008000. This module reassembles that stream and
 * walks it as the command processor would: CP/XF/BP register loads are
 * shadowed, display lists are followed, and draw commands are stepped over
 * using the vertex size the VCD/VAT registers imply. Nothing is rendered yet;
 * what matters first is that GXDrawDone and GXSetDrawSync produce the
 * PE_FINISH and PE_TOKEN interrupts the game sleeps on.
 *
 * The CPU FIFO in main memory is not modelled: the stream is consumed as it
 * is written, so the FIFO always reads as empty and the GP as idle, which is
 * exactly what the SDK's flow control and the game's GP-hang detector want.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GP_PIPE 0xCC008000u
#define CP_BASE 0xCC000000u
#define PE_BASE 0xCC001000u
#define PI_FIFO_BASE 0xCC00300Cu
#define PI_FIFO_TOP 0xCC003010u
#define PI_FIFO_WPTR 0xCC003014u

/* CP register shadow (indices are the CP register numbers). */
static uint32_t g_cp[0x100];
static uint32_t g_xf[0x1100]; /* 0x000-0xFFF matrix memory, 0x1000-0x10FF registers */
static uint32_t g_bp[0x100];
static uint16_t g_cp_mmio[0x40]; /* the CP's own MMIO registers, by half-word index */
static uint16_t g_pe_mmio[8];
static uint32_t g_pi_fifo[3];

/* PE_ISR at 0xCC00100A: bit0 token enable, bit1 finish enable, bit2 token, bit3 finish. */
#define PE_ISR 5
#define PE_TOKEN 7
#define ISR_TOKEN_EN 0x1u
#define ISR_FINISH_EN 0x2u
#define ISR_TOKEN 0x4u
#define ISR_FINISH 0x8u

static uint64_t g_bytes, g_cmds, g_draws, g_verts, g_dl_calls, g_bp_loads, g_xf_loads, g_cp_loads;
static uint64_t g_finishes, g_tokens, g_efb_copies, g_xfb_copies, g_unknown;
static uint32_t g_last_unknown;

/* ---- frame capture ---------------------------------------------------
 * SOA_FIFO_DUMP=a,b,c names frame numbers (frames end at a copy to the
 * XFB). For each, NNNN.regs holds the CP/XF/BP shadows as the frame began,
 * NNNN.fifo the bytes the CPU pushed during it, NNNN.ram all of MEM1 as it
 * ended: everything a replay needs to render it offline. They go to
 * SOA_FIFO_DIR, which defaults to build/fifo. */
static uint8_t* g_cap;
static size_t g_cap_len, g_cap_cap;
static uint32_t g_cap_cp[0x100], g_cap_xf[0x1100], g_cap_bp[0x100];
static unsigned g_frame;
static const char* g_dump_list = NULL;
static int g_dump_checked;

/* SOA_FRAMES=n stops the run here rather than in the renderer, so it counts
 * the frames the game presents whether or not anything is being drawn, and
 * counts the same ones SOA_PAD scripts against. main sets it once the guest
 * is about to run, which keeps --replay and the selftest out of it. */
static unsigned g_frame_limit;
void hle_report(void);
void gxr_flush(void);

void gx_set_frame_limit(unsigned frames)
{
    g_frame_limit = frames;
}

static int frame_wanted(unsigned frame)
{
    const char* p;
    if (!g_dump_checked) { g_dump_checked = 1; g_dump_list = getenv("SOA_FIFO_DUMP"); }
    for (p = g_dump_list; p && *p;) {
        char* end;
        unsigned long n = strtoul(p, &end, 10);
        if (end == p) break;
        if (n == frame) return 1;
        p = *end == ',' ? end + 1 : end;
    }
    return 0;
}

static void cap_append(const uint8_t* p, size_t n)
{
    if (!g_dump_list) return;
    if (g_cap_len + n > g_cap_cap) {
        size_t want = g_cap_cap ? g_cap_cap * 2 : (1u << 20);
        while (want < g_cap_len + n) want *= 2;
        g_cap = (uint8_t*)realloc(g_cap, want);
        g_cap_cap = want;
    }
    memcpy(g_cap + g_cap_len, p, n);
    g_cap_len += n;
}

static void write_file(const char* path, const void* data, size_t len)
{
    FILE* f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "[gx] cannot write %s\n", path); return; }
    fwrite(data, 1, len, f);
    fclose(f);
}

/* Where captures land. build/fifo is the corpus config/fifo_manifest.tsv
 * pins frame hashes against, so a capturing run must be able to write
 * somewhere else: overwriting a capture silently invalidates the hash that
 * was blessed from it, and the streams are not in the repository to restore
 * from. SOA_FIFO_DIR is how a scenario says "not the corpus". */
static const char* dump_dir(void)
{
    static const char* dir;
    if (!dir) {
        dir = getenv("SOA_FIFO_DIR");
        if (!dir || !*dir) dir = "build/fifo";
    }
    return dir;
}

static void frame_end(CpuState* s)
{
    char path[256];
    if (frame_wanted(g_frame)) {
        const char* dir = dump_dir();
        snprintf(path, sizeof path, "%s/%04u.regs", dir, g_frame);
        {
            FILE* f = fopen(path, "wb");
            if (f) {
                fwrite(g_cap_cp, 4, 0x100, f);
                fwrite(g_cap_xf, 4, 0x1100, f);
                fwrite(g_cap_bp, 4, 0x100, f);
                fclose(f);
            } else fprintf(stderr, "[gx] cannot write %s (mkdir %s)\n", path, dir);
        }
        snprintf(path, sizeof path, "%s/%04u.fifo", dir, g_frame);
        write_file(path, g_cap, g_cap_len);
        snprintf(path, sizeof path, "%s/%04u.ram", dir, g_frame);
        write_file(path, s->mem, MEM1_SIZE);
        fprintf(stderr, "[gx] captured frame %u into %s: %zu command bytes\n", g_frame, dir,
                g_cap_len);
    }
    g_frame++;
    if (g_frame_limit && g_frame >= g_frame_limit) {
        /* The copy for this frame is already queued (load_bp calls the
         * renderer before us), so flushing here finishes it -- any snapshot
         * is written and the counters are real before the report. Leave with
         * _exit for the reason window.c does: the rasterizer's workers are
         * spinning, and CRT teardown around them can hang. */
        fprintf(stderr, "[boot] %u frames done (SOA_FRAMES)\n", g_frame);
        gxr_flush();
        hle_report();
        fflush(NULL);
        _exit(0);
    }
    g_cap_len = 0;
    memcpy(g_cap_cp, g_cp, sizeof g_cp);
    memcpy(g_cap_xf, g_xf, sizeof g_xf);
    memcpy(g_cap_bp, g_bp, sizeof g_bp);
}

/* ---- vertex size from the current VCD/VAT --------------------------- */

static unsigned comp_size(unsigned fmt)
{
    return fmt == 4 ? 4 : (fmt >= 2 ? 2 : 1); /* u8 s8 u16 s16 f32 */
}

static unsigned color_size(unsigned comp)
{
    static const unsigned t[8] = {2, 3, 4, 2, 3, 4, 4, 4}; /* 565 888 888x 4444 6666 8888 */
    return t[comp & 7];
}

static unsigned attr_size(unsigned vcd, unsigned direct_size)
{
    switch (vcd & 3) {
    case 0: return 0;            /* not present */
    case 1: return direct_size;  /* inline */
    case 2: return 1;            /* 8-bit index */
    default: return 2;           /* 16-bit index */
    }
}

static unsigned vertex_size(unsigned vat)
{
    uint32_t lo = g_cp[0x50], hi = g_cp[0x60];
    uint32_t a = g_cp[0x70 + vat], b = g_cp[0x80 + vat], c = g_cp[0x90 + vat];
    unsigned size = 0, i;
    unsigned tc[8][2] = {
        {(a >> 21) & 1, (a >> 22) & 7}, {(b >> 0) & 1, (b >> 1) & 7},
        {(b >> 9) & 1, (b >> 10) & 7},  {(b >> 18) & 1, (b >> 19) & 7},
        {(b >> 27) & 1, (b >> 28) & 7}, {(c >> 5) & 1, (c >> 6) & 7},
        {(c >> 14) & 1, (c >> 15) & 7}, {(c >> 23) & 1, (c >> 24) & 7},
    };

    size += lo & 1; /* position matrix index */
    for (i = 0; i < 8; i++) size += (lo >> (1 + i)) & 1; /* texture matrix indices */

    size += attr_size((lo >> 9) & 3, ((a & 1) ? 3 : 2) * comp_size((a >> 1) & 7));

    {
        unsigned vcd = (lo >> 11) & 3, elems = (a >> 9) & 1, fmt = (a >> 10) & 7;
        if (vcd >= 2 && elems && ((a >> 31) & 1))
            size += 3 * (vcd == 2 ? 1 : 2); /* NBT with three separate indices */
        else
            size += attr_size(vcd, (elems ? 9 : 3) * comp_size(fmt));
    }

    size += attr_size((lo >> 13) & 3, color_size((a >> 14) & 7));
    size += attr_size((lo >> 15) & 3, color_size((a >> 18) & 7));

    for (i = 0; i < 8; i++)
        size += attr_size((hi >> (2 * i)) & 3, (tc[i][0] ? 2 : 1) * comp_size(tc[i][1]));
    return size;
}

/* ---- command stream --------------------------------------------------- */

void gxr_bp_written(CpuState* s, uint32_t reg, uint32_t value);
void gxr_draw(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize);
void gxr_report(void);
void gxr_reset_efb(void);
void gxr_flush(void);

static void load_bp(CpuState* s, uint32_t v)
{
    uint32_t reg = v >> 24;
    g_bp[reg] = v & 0xFFFFFFu;
    g_bp_loads++;
    switch (reg) {
    case 0x45: /* PE_DONE: draw done, optionally with the finish interrupt */
        if (v & 2) {
            g_pe_mmio[PE_ISR] |= ISR_FINISH;
            g_finishes++;
        }
        break;
    case 0x47: /* PE_TOKEN: token without interrupt */
        g_pe_mmio[PE_TOKEN] = (uint16_t)v;
        break;
    case 0x48: /* PE_TOKEN_INT */
        g_pe_mmio[PE_TOKEN] = (uint16_t)v;
        g_pe_mmio[PE_ISR] |= ISR_TOKEN;
        g_tokens++;
        break;
    case 0x52: /* EFB copy: to a texture or to the XFB -- a frame, when the latter */
        g_efb_copies++;
        gxr_bp_written(s, reg, v & 0xFFFFFFu);
        if (v & 0x4000u) { g_xfb_copies++; frame_end(s); }
        return;
    default: break;
    }
    gxr_bp_written(s, reg, v & 0xFFFFFFu);
}

static uint32_t be32(const uint8_t* p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static uint16_t be16(const uint8_t* p)
{
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

/* Parse as many whole commands as `len` bytes hold; return how many bytes
 * were consumed. A command cut off by the end of the buffer is left for the
 * next call. */
static size_t parse(CpuState* s, const uint8_t* p, size_t len, int in_display_list)
{
    size_t off = 0;
    while (off < len) {
        uint8_t op = p[off];
        size_t need;
        if (op == 0x00) { off += 1; g_cmds++; continue; }
        if (op == 0x48) { off += 1; g_cmds++; continue; } /* invalidate vertex cache */
        if (op == 0x08) { /* CP register */
            need = 6;
            if (off + need > len) break;
            g_cp[p[off + 1]] = be32(p + off + 2);
            g_cp_loads++;
        } else if (op == 0x10) { /* XF registers */
            uint32_t count, addr;
            if (off + 5 > len) break;
            count = be16(p + off + 1) + 1u;
            addr = be16(p + off + 3);
            need = 5 + 4 * (size_t)count;
            if (off + need > len) break;
            {
                uint32_t i;
                for (i = 0; i < count; i++)
                    if (addr + i < 0x1100) g_xf[addr + i] = be32(p + off + 5 + 4 * i);
            }
            g_xf_loads++;
        } else if (op == 0x20 || op == 0x28 || op == 0x30 || op == 0x38) { /* indexed XF (GXLoadPosMtxIndx etc.) */
            uint32_t index, v, count, addr, array, base, stride, src, i;
            need = 5;
            if (off + need > len) break;
            index = be16(p + off + 1);
            v = be16(p + off + 3);
            count = (v >> 12) + 1;
            addr = v & 0xFFF;
            array = 12 + ((op - 0x20) >> 3);
            base = g_cp[0xA0 + array] & 0x1FFFFFFFu;
            stride = g_cp[0xB0 + array] & 0xFFu;
            src = base + index * stride;
            /* count comes out of the command stream, so 4 * count can
             * overflow and wrap the sum back under the limit. Subtract. */
            if (count <= MEM1_SIZE / 4 && (src & MEM_MASK) <= MEM1_SIZE - 4 * count) {
                for (i = 0; i < count; i++)
                    if (addr + i < 0x1100) g_xf[addr + i] = mem_r32(s, (src | 0x80000000u) + 4 * i);
            }
            g_xf_loads++;
        } else if (op == 0x40) { /* display list */
            uint32_t addr, size;
            need = 9;
            if (off + need > len) break;
            addr = be32(p + off + 1);
            size = be32(p + off + 5);
            g_dl_calls++;
            /* size is the guest's, and the same wrap applies to it. */
            if (!in_display_list && size <= MEM1_SIZE && (addr & MEM_MASK) <= MEM1_SIZE - size) {
                size_t done = parse(s, mem_ptr(s, addr), size, 1);
                if (done != size) {
                    static int warned;
                    if (!warned++) fprintf(stderr, "[gx] display list at %08X: %zu of %u bytes parsed\n", addr, done, size);
                }
            }
        } else if (op == 0x61) { /* BP register */
            need = 5;
            if (off + need > len) break;
            load_bp(s, be32(p + off + 1));
        } else if (op >= 0x80 && op < 0xC0) { /* draw */
            unsigned vat = op & 7, count, vsize;
            if (off + 3 > len) break;
            count = be16(p + off + 1);
            vsize = vertex_size(vat);
            need = 3 + (size_t)count * vsize;
            if (off + need > len) break;
            g_draws++;
            g_verts += count;
            gxr_draw(s, op, count, p + off + 3, vsize);
        } else {
            if (g_unknown++ == 0 || g_last_unknown != op)
                fprintf(stderr, "[gx] unknown command byte %02X (%s)\n", op, in_display_list ? "display list" : "pipe");
            g_last_unknown = op;
            need = 1; /* resync one byte at a time */
        }
        off += need;
        g_cmds++;
    }
    return off;
}

/* ---- write-gather pipe ------------------------------------------------ */

#define PIPE_CAP 65536
static uint8_t g_pipe[PIPE_CAP];
static size_t g_pipe_len;

static void pipe_flush(CpuState* s)
{
    size_t done = parse(s, g_pipe, g_pipe_len, 0);
    if (done) {
        memmove(g_pipe, g_pipe + done, g_pipe_len - done);
        g_pipe_len -= done;
    }
}

void gx_pipe_write(CpuState* s, unsigned size, uint64_t v)
{
    unsigned i;
    if (g_pipe_len + size > PIPE_CAP) {
        static int warned;
        if (!warned++) fprintf(stderr, "[gx] pipe buffer full at %zu bytes; a command is not parsing\n", g_pipe_len);
        g_pipe_len = 0;
    }
    for (i = 0; i < size; i++) g_pipe[g_pipe_len++] = (uint8_t)(v >> (8 * (size - 1 - i)));
    cap_append(g_pipe + g_pipe_len - size, size);
    g_bytes += size;
    pipe_flush(s);
}

uint64_t gx_pipe_bytes(void) { return g_bytes; }

/* ---- MMIO ------------------------------------------------------------- */

int gx_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out)
{
    (void)s;
    if (ea >= CP_BASE && ea < CP_BASE + 0x80 && size == 2) {
        unsigned idx = (ea - CP_BASE) >> 1;
        switch (ea - CP_BASE) {
        case 0x00: *out = 0x000Cu; return 1; /* status: read idle, command idle */
        case 0x30: case 0x32: *out = 0; return 1; /* read/write distance: FIFO empty */
        case 0x38: *out = g_cp_mmio[0x34 >> 1]; return 1; /* read ptr == write ptr */
        case 0x3A: *out = g_cp_mmio[0x36 >> 1]; return 1;
        default: *out = g_cp_mmio[idx]; return 1;
        }
    }
    if (ea >= PE_BASE && ea < PE_BASE + 0x10 && size == 2) {
        *out = g_pe_mmio[(ea - PE_BASE) >> 1];
        return 1;
    }
    if (size == 4 && ea >= PI_FIFO_BASE && ea <= PI_FIFO_WPTR) {
        *out = g_pi_fifo[(ea - PI_FIFO_BASE) >> 2];
        return 1;
    }
    return 0;
}

int gx_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v)
{
    if (ea >= GP_PIPE && ea < GP_PIPE + 0x100) {
        gx_pipe_write(s, size, v);
        return 1;
    }
    if (ea >= CP_BASE && ea < CP_BASE + 0x80 && size == 2) {
        g_cp_mmio[(ea - CP_BASE) >> 1] = (uint16_t)v;
        return 1;
    }
    if (ea >= PE_BASE && ea < PE_BASE + 0x10 && size == 2) {
        unsigned idx = (ea - PE_BASE) >> 1;
        if (idx == PE_ISR) /* enables are stored; status bits are write-one-to-clear */
            g_pe_mmio[PE_ISR] = (uint16_t)((g_pe_mmio[PE_ISR] & (ISR_TOKEN | ISR_FINISH) & ~(v & (ISR_TOKEN | ISR_FINISH))) | (v & (ISR_TOKEN_EN | ISR_FINISH_EN)));
        else
            g_pe_mmio[idx] = (uint16_t)v;
        return 1;
    }
    if (size == 4 && ea >= PI_FIFO_BASE && ea <= PI_FIFO_WPTR) {
        g_pi_fifo[(ea - PI_FIFO_BASE) >> 2] = (uint32_t)v & 0x1FFFFFFFu;
        return 1;
    }
    return 0;
}

/* Bit 0: a token interrupt is due; bit 1: a finish interrupt is due. */
unsigned gx_pe_irq_pending(void)
{
    unsigned isr = g_pe_mmio[PE_ISR], due = 0;
    if ((isr & ISR_TOKEN) && (isr & ISR_TOKEN_EN)) due |= 1;
    if ((isr & ISR_FINISH) && (isr & ISR_FINISH_EN)) due |= 2;
    return due;
}

void gx_report(void)
{
    fprintf(stderr,
            "[gx] %llu pipe bytes, %llu commands: %llu BP, %llu XF, %llu CP loads, %llu display "
            "lists, %llu draws (%llu vertices); %llu draw-dones, %llu tokens, %llu EFB copies, "
            "%llu unknown bytes\n",
            (unsigned long long)g_bytes, (unsigned long long)g_cmds, (unsigned long long)g_bp_loads,
            (unsigned long long)g_xf_loads, (unsigned long long)g_cp_loads,
            (unsigned long long)g_dl_calls, (unsigned long long)g_draws,
            (unsigned long long)g_verts, (unsigned long long)g_finishes,
            (unsigned long long)g_tokens, (unsigned long long)g_efb_copies,
            (unsigned long long)g_unknown);
    gxr_report();
}

/* ---- replay ------------------------------------------------------------
 * Feed a captured frame through the same parser with MEM1 restored, so the
 * renderer sees exactly what it saw in the game. */
unsigned gx_frame_count(void) { return g_frame; }
const uint32_t* gx_cp_regs(void) { return g_cp; }
const uint32_t* gx_xf_regs(void) { return g_xf; }
const uint32_t* gx_bp_regs(void) { return g_bp; }

int gx_replay(CpuState* s, const char* base)
{
    char path[512];
    FILE* f;
    uint8_t* fifo;
    size_t len, done;

    snprintf(path, sizeof path, "%s.regs", base);
    f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "[gx] cannot open %s\n", path); return 1; }
    if (fread(g_cp, 4, 0x100, f) != 0x100 || fread(g_xf, 4, 0x1100, f) != 0x1100 || fread(g_bp, 4, 0x100, f) != 0x100) {
        fprintf(stderr, "[gx] short register file %s\n", path); fclose(f); return 1;
    }
    fclose(f);

    snprintf(path, sizeof path, "%s.ram", base);
    f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "[gx] cannot open %s\n", path); return 1; }
    if (fread(s->mem, 1, MEM1_SIZE, f) != MEM1_SIZE) { fprintf(stderr, "[gx] short RAM file\n"); fclose(f); return 1; }
    fclose(f);

    snprintf(path, sizeof path, "%s.fifo", base);
    f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "[gx] cannot open %s\n", path); return 1; }
    fseek(f, 0, SEEK_END);
    len = (size_t)ftell(f);
    fseek(f, 0, SEEK_SET);
    fifo = (uint8_t*)malloc(len ? len : 1);
    if (fread(fifo, 1, len, f) != len) { fprintf(stderr, "[gx] short FIFO file\n"); fclose(f); return 1; }
    fclose(f);

    gxr_reset_efb();
    done = parse(s, fifo, len, 0);
    gxr_flush();
    fprintf(stderr, "[gx] replayed %zu of %zu bytes\n", done, len);
    gx_report();
    free(fifo);
    return 0;
}
