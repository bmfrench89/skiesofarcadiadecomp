/*
 * VIGetRetraceCount (0x8023F704), answered natively, so that the game's main
 * loop has a safe point and a tick the port can let go early
 * (docs/PLAN-60FPS-MODS.md M2).
 *
 * The original is two instructions, `lwz r3,-27836(r13); blr`: the retrace
 * count at 0x80347A64. Two of its callers are the main loop's:
 *
 *   801DCB84 bl VIGetRetraceCount   the top of the loop, which stores the
 *   801DCB88 stw r3,-28820(r13)     count as the frame's start (0x8034768C)
 *
 *   801DC498 bl VIGetRetraceCount   the frame end's spin, after the XFB copy:
 *   801DC49C lwz r0,-28820(r13)     it goes round while count - start < 1,
 *   801DC4A0 subf r0,r0,r3          each pass behind fn_801C6248(0)'s wait
 *   801DC4A4 cmpli cr0,r0,1         for a retrace -- the immediate that makes
 *   801DC4A8 blt 801DC490           the game two fields a frame
 *
 * Every translated call sets lr first, so the call site is s->lr here:
 *
 * - At 0x801DCB88, before the count is read, the safe-point callbacks run.
 *   Nothing of the frame has started: no GX, no guest thread mid-update --
 *   the one point a mod may call guest code (M4) or change what the frame
 *   does.
 * - At 0x801DC49C, once the tick is unlocked (SOA_UNCAP=N, from frame N), the
 *   answer is the frame's start plus one, so the spin leaves on its first
 *   pass and a frame needs the one field fn_801C6248 waits for, not two. The
 *   game's logic advances once a frame (FINDINGS "H2"), so this is the whole
 *   game at up to twice the speed -- a battle speed-up (M11) or a
 *   measurement, never 60 fps. H3 did the same by zeroing the stored start;
 *   answering here leaves that word as the game wrote it.
 * - Anywhere else, and at both with nothing registered and the tick locked,
 *   it is the original, and selftest's twin case holds it to the recompiled
 *   one.
 */
#include "cpu.h"
#include <stdio.h>

#define RETRACE_COUNT 0x80347A64u      /* r13 - 27836 */
#define FRAME_START_FIELDS 0x8034768Cu /* r13 - 28820 */
#define LR_FRAME_START 0x801DCB88u
#define LR_FRAME_END_SPIN 0x801DC49Cu
#define SAFE_POINT_MAX 8

static void (*g_safe[SAFE_POINT_MAX])(CpuState*);
static int g_safe_n, g_reported;
static unsigned g_unlock_from; /* 0: locked */
static unsigned long long g_safe_points, g_released;

void hle_on_report(void (*fn)(void));
unsigned gx_frame_count(void);

static void tick_report(void)
{
    fprintf(stderr, "[tick] %llu safe points over %u presented frames", g_safe_points, gx_frame_count());
    if (g_unlock_from)
        fprintf(stderr, "; from frame %u the frame end's spin was let go after one field %llu times\n",
                g_unlock_from, g_released);
    else
        fprintf(stderr, "; the tick is locked, two fields a frame\n");
}

static void tick_register_report(void)
{
    if (g_reported) return;
    g_reported = 1;
    hle_on_report(tick_report);
}

/* A callback for the top of every frame; 0 when the table is full. */
int tick_on_safe_point(void (*fn)(CpuState*))
{
    if (g_safe_n == SAFE_POINT_MAX) return 0;
    g_safe[g_safe_n++] = fn;
    return 1;
}

/* Let the frame end's spin go after one field, from frame `frame` on; 0
 * locks it again. */
void tick_unlock_from(unsigned frame)
{
    g_unlock_from = frame;
}

void fn_8023F704(CpuState* s)
{
    s->pc = 0x8023F704u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    tick_register_report();
    if (s->lr == LR_FRAME_START) {
        int i;
        g_safe_points++;
        for (i = 0; i < g_safe_n; i++) g_safe[i](s);
    } else if (s->lr == LR_FRAME_END_SPIN && g_unlock_from && gx_frame_count() >= g_unlock_from) {
        g_released++;
        s->gpr[3] = mem_r32(s, FRAME_START_FIELDS) + 1;
        return;
    }
    s->gpr[3] = mem_r32(s, RETRACE_COUNT);
}
