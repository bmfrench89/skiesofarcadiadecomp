/*
 * Boot the recompiled program.
 *
 * Builds the MEM1 image the console's boot code and apploader would have left
 * behind -- the DOL's sections at their virtual addresses, BSS zeroed, the
 * FST parked below the arena, the low-memory globals the OS reads at start
 * -- then jumps to the DOL entry point exactly as the apploader would.
 *
 *     soa.exe [extracted-dir]
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include "gxr.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef ENTRY_FN
#define ENTRY_FN fn_80003140 /* __start */
#endif
#define STR2(x) #x
#define STR(x) STR2(x)
void ENTRY_FN(CpuState* s);
void hle_report(void);
void hle_dump(CpuState* s, uint32_t pc);
void threads_init(CpuState* s);
void dvd_init(const char* path);
int selftest(CpuState* s);
int gx_replay(CpuState* s, const char* base);
void gxr_enable(int on);
void gxr_set_output(const char* png_path);
void watch_init(void);
void window_start(void);
void gx_set_frame_limit(unsigned frames);
void gx_set_frame_hook(void (*fn)(CpuState*, unsigned)); /* SOA_POKE; see gx.c */
unsigned gx_frame_count(void);
void gxr_draw_every_frame(void);
int irq_in_handler(void);
void hle_clock_start(void);
/* Set while gx.c is inside the command-stream parse. The sampler reads it
 * because a clock pair there would cost more than the parse. */
extern int g_gx_parsing;

/* A loop that never touches hardware never trips the MMIO spin detector, so
 * a second thread waits SOA_WATCHDOG seconds without a video frame and then
 * reports the block the guest is in. It defaults to 20 seconds headless and
 * to off when a window is open, since a window means a person is driving and
 * a timeout would cut them off mid-play; an explicit SOA_WATCHDOG wins
 * either way. It times a stall, not the run: a run that is still presenting
 * frames is working, and killing it is what made a long SOA_FRAMES run
 * impossible headless. */
#ifdef _WIN32
#include <process.h>
#include <windows.h>
static CpuState* g_state;

/* ---- naming a block address ---------------------------------------------
 *
 * A sample is the address of a basic block, not of a function: cpu.h says so,
 * and the recompiler stores it at every label. config/functions.tsv is the
 * inventory tools/ builds -- sorted by address, with each function's size --
 * so a block resolves to the function containing it by binary search on
 * containment. Equality would miss every block but the first of each
 * function, which is what made the old profile a list of addresses.
 *
 * Read once, at the report, on the reporting thread: 320 KB and a sort of
 * 7,144 rows at exit, and nothing in any hot path touches it. It is the first
 * file the binary opens out of config/, so a run started from anywhere but
 * the repository root will not find it -- the header below says which file it
 * used and how many rows it got, so a table of bare hex reads as "no
 * inventory here" rather than as "these functions have no names". Most rows
 * in that file are still fn_XXXXXXXX, which the header also says, for the
 * same reason.
 */
typedef struct {
    uint32_t addr, size;
    const char* name;
} Sym;
static Sym* g_syms;
static unsigned g_nsyms;
static char* g_symtext;
static char g_sympath[512];
static int g_sym_tried;

static int sym_cmp(const void* a, const void* b)
{
    uint32_t x = ((const Sym*)a)->addr, y = ((const Sym*)b)->addr;
    return x < y ? -1 : x > y ? 1 : 0;
}

static void sym_load(void)
{
    const char* env = getenv("SOA_SYMBOLS");
    FILE* f;
    long len;
    size_t got, lines = 0, i;
    char* line;
    int first = 1;
    if (g_sym_tried) return;
    g_sym_tried = 1;
    snprintf(g_sympath, sizeof g_sympath, "%s", env && *env ? env : "config/functions.tsv");
    f = fopen(g_sympath, "rb");
    if (!f) return;
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (len <= 0) { fclose(f); return; }
    g_symtext = (char*)malloc((size_t)len + 1);
    if (!g_symtext) { fclose(f); return; }
    got = fread(g_symtext, 1, (size_t)len, f);
    fclose(f);
    g_symtext[got] = 0;
    for (i = 0; i < got; i++)
        if (g_symtext[i] == '\n') lines++;
    g_syms = (Sym*)malloc(sizeof(Sym) * (lines + 1));
    if (!g_syms) { free(g_symtext); g_symtext = NULL; return; }
    /* address, size, name, then six columns this does not need. The file is
     * written with CRLF; the name ends at the tab after it either way. */
    for (line = g_symtext; line && *line;) {
        char* eol = strchr(line, '\n');
        if (eol) *eol = 0;
        if (first) first = 0; /* the header row */
        else {
            char* t1 = strchr(line, '\t');
            char* t2 = t1 ? strchr(t1 + 1, '\t') : NULL;
            char* t3 = t2 ? strchr(t2 + 1, '\t') : NULL;
            if (t3) {
                Sym* e = &g_syms[g_nsyms];
                *t1 = *t2 = *t3 = 0;
                e->addr = (uint32_t)strtoul(line, NULL, 0);
                e->size = (uint32_t)strtoul(t1 + 1, NULL, 10);
                e->name = t2 + 1;
                if (e->addr && e->size) g_nsyms++;
            }
        }
        line = eol ? eol + 1 : NULL;
    }
    qsort(g_syms, g_nsyms, sizeof g_syms[0], sym_cmp);
}

/* The function containing pc, and where it starts. NULL when no row contains
 * it -- the inventory has ten small gaps, and a run without config/ has none
 * of it at all. */
static const char* sym_name(uint32_t pc, uint32_t* start)
{
    unsigned lo = 0, hi;
    /* Loaded before the bound is read, not after: reading g_nsyms first made
     * the first lookup of every run search an empty table and answer NULL,
     * which showed up as exactly one function in the report going unnamed. */
    sym_load();
    hi = g_nsyms;
    if (!hi) return NULL;
    while (lo < hi) {
        unsigned mid = lo + (hi - lo) / 2;
        if (g_syms[mid].addr <= pc) lo = mid + 1;
        else hi = mid;
    }
    if (!lo) return NULL;
    lo--;
    if (pc - g_syms[lo].addr >= g_syms[lo].size) return NULL;
    if (start) *start = g_syms[lo].addr;
    return g_syms[lo].name;
}

/* " (name+0xNN)" for the bare addresses this file prints, or "" when there is
 * no inventory to name them from. One static buffer: every caller is on a
 * stop path, one at a time. */
static const char* block_name(uint32_t pc)
{
    static char buf[128];
    uint32_t start = 0;
    const char* n = sym_name(pc, &start);
    if (!n) return "";
    if (pc == start) snprintf(buf, sizeof buf, " (%s)", n);
    else snprintf(buf, sizeof buf, " (%s+0x%X)", n, pc - start);
    return buf;
}

/* ---- the sampler ---------------------------------------------------------
 *
 * Its own thread, started before the guest and never stopped until the
 * report. The old one was the watchdog's second job, zeroed its samples on
 * every presented frame and only ever printed from the stall path, so a
 * healthy run produced no profile at all and every saved one covered a stall.
 * Splitting the two jobs is the whole fix: the watchdog still watches for a
 * stall, this samples the run.
 *
 * Each tick reads three words the guest thread is writing -- its block
 * address, the renderer phase, and the parse marker -- and charges the wall
 * interval since the previous tick to whichever of them applies, phase first,
 * then the parse, then the block. That ordering is what makes the buckets
 * disjoint: a sample belongs to a renderer phase or to a guest function,
 * never to both. The reads are plain aligned loads with no coherence between
 * them; at a millisecond and a half apart the window in which they can
 * disagree is nanoseconds, which is worth one sentence rather than a lock
 * that would change what is being measured.
 *
 * Weighted by that interval rather than counted, because the pacer is jittery
 * by design: counting would over-represent whatever happens to be running
 * when the timer fires early. The weights are seconds, which is also what
 * makes this table comparable with the renderer's timers.
 *
 * What it cannot tell you: anything shorter than its period. It answers "what
 * share of the thread went where" over a run, never "how long did one frame's
 * prepare take" -- the timers in gxr.c answer that. And it samples the guest
 * thread only, so the workers are absent from it by construction and measured
 * by the busy/idle pair in gxr.c instead.
 */
#define PROF_SLOTS 65536          /* a count per distinct block; a run of any length fits */
#define PROF_PERIOD_100NS 14000   /* 1.4 ms, which is what a high-resolution timer delivers */
#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 0x00000002
#endif

static uint32_t g_prof_key[PROF_SLOTS]; /* block address, bit 0 set inside a handler */
static uint64_t g_prof_tk[PROF_SLOTS];  /* performance-counter ticks charged to it */
static uint64_t g_prof_phase[T_COUNT];
static uint64_t g_prof_parse;   /* inside gx.c's command-stream parse */
static uint64_t g_prof_noblock; /* before the guest ran a block at all */
static uint64_t g_prof_lost;    /* the table filled: more distinct blocks than slots */
static uint64_t g_prof_samples, g_prof_span;
static int g_prof_on;
/* Enough rows for the plan's top ten and a little context. The report is
 * printed at the end of every run and is already long, so the rest go into
 * one line that says how much they came to; SOA_PROFILE=N asks for N. */
static int g_prof_rows = 12;
static volatile long g_prof_stop, g_prof_stopped;

static void prof_add(uint32_t key, uint64_t dt)
{
    unsigned h = (unsigned)((key * 2654435761u) >> 16) & (PROF_SLOTS - 1), i;
    /* The probe is bounded rather than allowed to walk the whole table: a run
     * with more distinct blocks than this has room for would otherwise turn
     * every sample into a scan of 65,536 slots, on a thread that wakes 700
     * times a second, and the profiler would start showing up in the program
     * it is measuring. Sixty-four is far past what a half-full table needs,
     * and what falls off the end is counted and named in the report rather
     * than dropped. */
    for (i = 0; i < 64; i++) {
        unsigned k = (h + i) & (PROF_SLOTS - 1);
        if (g_prof_key[k] == key) { g_prof_tk[k] += dt; return; }
        if (!g_prof_key[k]) { g_prof_key[k] = key; g_prof_tk[k] = dt; return; }
    }
    g_prof_lost += dt;
}

static unsigned __stdcall sampler(void* arg)
{
    HANDLE timer = (HANDLE)arg;
    LARGE_INTEGER prev, now;
    uint32_t rnd = 0x9E3779B9u;
    QueryPerformanceCounter(&prev);
    while (!g_prof_stop) {
        LARGE_INTEGER due;
        uint64_t dt;
        uint32_t pc;
        int ph;
        /* Twenty per cent of jitter on purpose. A fixed period against a
         * 60 Hz retrace and a 30 Hz present can lock onto one phase of the
         * frame and systematically over-count whatever runs there -- and two
         * runs would then agree with each other and with nothing else, which
         * is the one failure the "same top ten twice" check cannot see. */
        rnd ^= rnd << 13;
        rnd ^= rnd >> 17;
        rnd ^= rnd << 5;
        if (timer) {
            due.QuadPart = -(LONGLONG)(PROF_PERIOD_100NS * 4 / 5 + rnd % (PROF_PERIOD_100NS * 2 / 5 + 1));
            if (SetWaitableTimer(timer, &due, 0, NULL, NULL, FALSE)) WaitForSingleObject(timer, 1000);
            else Sleep(1);
        } else Sleep(1); /* ~15.6 ms, so about a twelfth of the samples */
        QueryPerformanceCounter(&now);
        dt = (uint64_t)(now.QuadPart - prev.QuadPart);
        prev = now;
        g_prof_samples++;
        g_prof_span += dt;
        ph = g_gxr_phase;
        if (ph > T_HOST && ph < T_COUNT) { g_prof_phase[ph] += dt; continue; }
        if (g_gx_parsing) { g_prof_parse += dt; continue; }
        pc = g_state ? g_state->pc : 0u;
        if (!pc) { g_prof_noblock += dt; continue; }
        /* Block addresses are 4-aligned; bit 0 tags samples taken in a handler. */
        prof_add((pc & ~1u) | (irq_in_handler() ? 1u : 0u), dt);
    }
    g_prof_stopped = 1;
    return 0;
}

static void profile_start(CpuState* s)
{
    const char* env = getenv("SOA_PROFILE");
    HANDLE timer;
    uintptr_t h;
    g_state = s;
    if (env) {
        int n = atoi(env);
        if (!n) return; /* SOA_PROFILE=0: one fewer thread on the machine */
        if (n > 1) g_prof_rows = n;
    }
    /* A high-resolution waitable timer delivers about 1.4 ms here where
     * Sleep(1) delivers 15.9, which is eleven times the samples -- and unlike
     * timeBeginPeriod it does not raise the timer resolution for the whole
     * process. That would change the scheduling quantum the renderer's
     * Sleep(0) backoff rides on, and that backoff is one of the things being
     * measured. Older Windows refuses the flag; then a plain timer, and
     * failing that Sleep(1) and a twelfth of the resolution. */
    timer = CreateWaitableTimerExW(NULL, NULL, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    if (!timer) timer = CreateWaitableTimerExW(NULL, NULL, 0, TIMER_ALL_ACCESS);
    h = _beginthreadex(NULL, 0, sampler, timer, 0, NULL);
    if (!h) {
        fprintf(stderr, "[profile] cannot start the sampler thread; this run has no profile\n");
        if (timer) CloseHandle(timer);
        return;
    }
    CloseHandle((HANDLE)h);
    g_prof_on = 1;
}

typedef struct {
    uint32_t key; /* function start, bit 0 set inside a handler; 0 for a named bucket */
    const char* name;
    uint64_t tk;
} Row;

static int row_key_cmp(const void* a, const void* b)
{
    uint32_t x = ((const Row*)a)->key, y = ((const Row*)b)->key;
    return x < y ? -1 : x > y ? 1 : 0;
}

/* Heaviest first, and a total order rather than only a ranking: qsort is not
 * stable, so two rows the sort called equal could come out either way round,
 * and "the same top ten twice" would then fail on a tie that was never a
 * difference. */
static int row_tk_cmp(const void* a, const void* b)
{
    const Row *p = (const Row*)a, *q = (const Row*)b;
    if (p->tk != q->tk) return p->tk < q->tk ? 1 : -1;
    if (p->key != q->key) return p->key < q->key ? -1 : 1;
    if (!p->name || !q->name) return (p->name ? 0 : 1) - (q->name ? 0 : 1);
    return strcmp(p->name, q->name);
}

/* Every phase gets a row whether or not it fired, so the vocabulary the
 * report uses for the renderer is the same in the table and in the [gxr]
 * lines above it. */
static const char* const PHASE_NAME[T_COUNT] = {
    "[host]", "[gxr] vertex setup", "[gxr] TEV setup", "[gxr] texture decode",
    "[gxr] EFB copy", "[gxr] PNG write", "[gxr] waiting for the workers", "[gxr] rasterizing inline",
};


void profile_report(void)
{
    static Row rows[PROF_SLOTS + T_COUNT + 4];
    unsigned n = 0, i, j, shown;
    uint64_t total = 0, named = 0, printed = 0;
    double hz, span;
    LARGE_INTEGER f;
    if (!g_prof_on) return;
    /* Stop the one writer before reading its table, and bound the wait: a
     * sampler that has wedged must not hold up an exit path. */
    g_prof_stop = 1;
    for (i = 0; i < 200 && !g_prof_stopped; i++) Sleep(1);
    QueryPerformanceFrequency(&f);
    hz = (double)f.QuadPart;
    span = hz > 0.0 ? (double)g_prof_span / hz : 0.0;
    if (!g_prof_samples || span <= 0.0) {
        fprintf(stderr, "[profile] no samples\n");
        return;
    }
    /* Fold each block onto the function containing it. Two blocks of one
     * function ranked separately is what made the old table jitter between
     * runs, and folding is also what lets a row carry a name at all. */
    for (i = 0; i < PROF_SLOTS; i++) {
        uint32_t pc, start;
        const char* name;
        if (!g_prof_key[i] || !g_prof_tk[i]) continue;
        pc = g_prof_key[i] & ~1u;
        start = pc;
        name = sym_name(pc, &start);
        rows[n].key = start | (g_prof_key[i] & 1u);
        rows[n].name = name;
        rows[n].tk = g_prof_tk[i];
        if (name) named += g_prof_tk[i];
        n++;
    }
    qsort(rows, n, sizeof rows[0], row_key_cmp);
    for (i = 0, j = 0; i < n; i++) {
        if (j && rows[j - 1].key == rows[i].key) rows[j - 1].tk += rows[i].tk;
        else rows[j++] = rows[i];
    }
    n = j;
    for (i = T_HOST + 1; i < T_COUNT; i++) {
        if (!g_prof_phase[i]) continue;
        rows[n].key = 0;
        rows[n].name = PHASE_NAME[i];
        rows[n].tk = g_prof_phase[i];
        n++;
    }
    if (g_prof_parse) {
        rows[n].key = 0;
        rows[n].name = "[gx] command-stream parse";
        rows[n++].tk = g_prof_parse;
    }
    if (g_prof_noblock) {
        rows[n].key = 0;
        rows[n].name = "[boot] before the guest's first block";
        rows[n++].tk = g_prof_noblock;
    }
    if (g_prof_lost) {
        rows[n].key = 0;
        rows[n].name = "[profile] past the sample table's reach";
        rows[n++].tk = g_prof_lost;
    }
    for (i = 0; i < n; i++) total += rows[i].tk;
    qsort(rows, n, sizeof rows[0], row_tk_cmp);
    fprintf(stderr,
            "[profile] %llu samples at %.0f Hz over %.1fs of wall clock, each weighted by the "
            "interval it covers; %u entries, %.0f%% of the time named from %s (%u rows, most of "
            "them still fn_XXXXXXXX). H = in an interrupt handler.\n",
            (unsigned long long)g_prof_samples, (double)g_prof_samples / span, span, n,
            total ? 100.0 * named / total : 0.0, g_nsyms ? g_sympath : "no symbol file (run from the repository root, or set SOA_SYMBOLS)",
            g_nsyms);
    shown = n < (unsigned)g_prof_rows ? n : (unsigned)g_prof_rows;
    for (i = 0; i < shown; i++) {
        double pct = total ? 100.0 * rows[i].tk / total : 0.0;
        printed += rows[i].tk;
        if (!rows[i].key) fprintf(stderr, "  %5.1f%%           %s\n", pct, rows[i].name);
        else if (rows[i].name)
            fprintf(stderr, "  %5.1f%%  %08X %s%s\n", pct, rows[i].key & ~1u, rows[i].name,
                    (rows[i].key & 1u) ? " H" : "");
        else
            fprintf(stderr, "  %5.1f%%  %08X (no row in the inventory covers it)%s\n", pct,
                    rows[i].key & ~1u, (rows[i].key & 1u) ? " H" : "");
    }
    if (n > shown)
        fprintf(stderr, "  %5.1f%%           the other %u entries\n",
                total ? 100.0 * (total - printed) / total : 0.0, n - shown);
    /* Two independent measurements of the same seconds, printed side by side
     * rather than reconciled in private. They disagree by sampling error and
     * by anything this does not know about -- a phase entered on a path with
     * no boundary, a clock miscalibrated -- so a gap much wider than the
     * sampling error is a defect in one of them, and the only way to see it
     * is to print it. */
    gxr_timing_finish();
    if (gxr_producer_span() > 0.0) {
        int worst = 0;
        double gap = -1.0;
        for (i = T_HOST + 1; i < T_COUNT; i++) {
            double d = gxr_seconds(g_gxr_ticks[i]) - (double)g_prof_phase[i] / hz;
            if (d < 0.0) d = -d;
            if (d > gap) { gap = d; worst = (int)i; }
        }
        fprintf(stderr, "[profile] sampler against timers, widest of the %d renderer phases: %s "
                        "%.2fs timed, %.2fs sampled, %.1f%% of the run apart\n",
                T_COUNT - 1, PHASE_NAME[worst], gxr_seconds(g_gxr_ticks[worst]),
                (double)g_prof_phase[worst] / hz, 100.0 * gap / span);
    }
}

void guest_backtrace(CpuState* s, uint32_t sp);
static unsigned __stdcall watchdog(void* arg)
{
    unsigned secs = (unsigned)(uintptr_t)arg;
    unsigned frames = gx_frame_count();
    ULONGLONG t0 = GetTickCount64();
    /* Watching for a stall is the whole of this thread's job now. It used to
     * sample as well, and zero its samples on every presented frame, which is
     * why the only profile it could ever print was of a stall. The sampler
     * above runs the whole time instead.
     *
     * Sleep(1) is really ~15 ms at the default timer resolution, so pace the
     * wait by the clock rather than by counting sleeps. */
    for (;;) {
        unsigned now;
        Sleep(1);
        /* Every frame presented restarts the clock, so the timeout means what
         * the message says -- nothing happened for this long. A boot that
         * never reaches its first frame still reports, on time. */
        now = gx_frame_count();
        if (now != frames) { frames = now; t0 = GetTickCount64(); continue; }
        if (GetTickCount64() - t0 >= (ULONGLONG)secs * 1000u) break;
    }
    fprintf(stderr, "[watchdog] no video frame for %us (SOA_WATCHDOG=0 disables it, SOA_WATCHDOG=s "
                    "changes the timeout); %u frames so far, last block %08X%s\n", secs, frames,
            g_state->pc, block_name(g_state->pc));
    hle_dump(g_state, g_state->pc);
    fprintf(stderr, "  backtrace from r1:");
    guest_backtrace(g_state, g_state->gpr[1]);
    hle_report(); /* which prints the profile, on this path and on every other */
    _exit(5);
    return 0;
}
static int g_watchdog_on;

/* Returns the timeout it armed, so the startup line can say what will end
 * the run rather than guess. */
static unsigned start_watchdog(CpuState* s, int windowed)
{
    const char* env = getenv("SOA_WATCHDOG");
    unsigned secs = env ? (unsigned)atoi(env) : (windowed ? 0u : 20u);
    g_state = s;
    if (secs) {
        /* Only report a timeout there is really a thread behind: the startup
         * line says what will end the run, and a thread that never started
         * would make that a lie. */
        uintptr_t h = _beginthreadex(NULL, 0, watchdog, (void*)(uintptr_t)secs, 0, NULL);
        if (!h) {
            fprintf(stderr, "[watchdog] cannot start the watchdog thread; nothing will time this run out\n");
            return 0;
        }
        CloseHandle((HANDLE)h);
        g_watchdog_on = 1;
    }
    return secs;
}

/* The window standing down the watchdog is only safe while the window turns
 * up; if it fails to open, the run would be headless with nothing watching
 * it at all. window.c calls this on that path. */
void watchdog_fallback(void)
{
    const char* env = getenv("SOA_WATCHDOG");
    if (g_watchdog_on || !g_state || (env && !atoi(env))) return;
    fprintf(stderr, "[watchdog] no window after all; arming the headless default\n");
    start_watchdog(g_state, 0);
}
#else
static unsigned start_watchdog(CpuState* s, int windowed) { (void)s; (void)windowed; return 0; }
void watchdog_fallback(void) {}
/* No sampler off Windows: there is no worker pool there either, and the
 * report says nothing rather than print an empty table. */
static void profile_start(CpuState* s) { (void)s; }
void profile_report(void) {}
#endif

/* ---- the MEM1 image, and the 8 MB of it that is not RAM ------------------
 *
 * mem_ptr masks an effective address with MEM_MASK and returns a pointer.
 * That is the whole of the guest's address translation and it runs on every
 * load and store in 55 MB of generated C, so it cannot afford to check
 * anything. The mask covers 32 MB and the console has 24, which leaves the
 * top eighth of the window -- 0x81800000 up, and its uncached and real-mode
 * aliases -- pointing past the end of the RAM. Narrowing the mask is not on:
 * 24 MB is not a power of two, so folding the range back would put a test on
 * every guest memory access to pay for an address the game should never form.
 *
 * Instead the image is the mask's whole range, and the part of it above the
 * RAM is reserved rather than committed. mem_ptr is untouched and the common
 * case costs exactly what it cost before; a stray access lands in reserved
 * address space and faults, and the handler below reports it, commits the
 * range and lets the run carry on against zeroed pages rather than against
 * the host heap. Committing all of it at the first fault is also what holds
 * this to a single message: afterwards there is nothing left up there to
 * fault on, so a guest loop cannot turn the tripwire into a stream.
 */
static int g_mem_guarded;

#ifdef _WIN32
/* Reserved past the mask's range as well, so an 8-byte load that starts in
 * its last bytes has somewhere to land. 64K because that is the granularity
 * VirtualAlloc reserves in. */
#define MEM_RESERVE_BYTES ((SIZE_T)MEM_MASK + 1u + 0x10000u)
static uint8_t* g_mem_base;
static CpuState* g_mem_state;
/* The thread that built the image is the one that runs the guest, so a fault
 * on any other is the runtime's own code and s->pc belongs to neither it nor
 * the moment. Say which kind of fault it was rather than print a block
 * address that had nothing to do with it. */
static DWORD g_mem_tid;

static LONG CALLBACK mem_guard(EXCEPTION_POINTERS* ep)
{
    const EXCEPTION_RECORD* er = ep->ExceptionRecord;
    static volatile LONG reported;
    uintptr_t off;
    int storing, committed, guest;
    /* Every other fault in the process belongs to somebody else. The
     * subtraction is unsigned, so an address below the image gives a huge
     * offset and falls out of the range test with it. */
    if (er->ExceptionCode != EXCEPTION_ACCESS_VIOLATION || er->NumberParameters < 2 || !g_mem_base)
        return EXCEPTION_CONTINUE_SEARCH;
    off = (uintptr_t)er->ExceptionInformation[1] - (uintptr_t)g_mem_base;
    if (off < MEM1_SIZE || off >= MEM_RESERVE_BYTES) return EXCEPTION_CONTINUE_SEARCH;
    storing = er->ExceptionInformation[0] != 0;
    guest = GetCurrentThreadId() == g_mem_tid;
    /* Commit first: the report walks the guest stack, and that walk must not
     * fault its way back in here. A commit that fails leaves the access
     * violation standing and the process dies of it -- so say so first,
     * because the message is the entire point of the mechanism and a bare
     * access violation explains nothing. */
    committed = VirtualAlloc(g_mem_base + MEM1_SIZE, MEM_RESERVE_BYTES - MEM1_SIZE, MEM_COMMIT,
                             PAGE_READWRITE)
                != NULL;
    if (!InterlockedExchange(&reported, 1)) {
        CpuState* s = g_mem_state;
        char who[192];
        if (guest) snprintf(who, sizeof who, "from block %08X%s", s ? s->pc : 0u,
                            block_name(s ? s->pc : 0u));
        else snprintf(who, sizeof who, "on a runtime thread, not the guest's");
        /* Reported in the cached window, because the mask has already thrown
         * away which of the three windows the guest used, and as the address
         * the access reached rather than the one it started from: an access
         * straddling the end of the RAM stops at the first byte past it. */
        fprintf(stderr,
                "[mem] %s %s reached %08X, past the console's 24 MB of RAM; the port "
                "keeps zeroed scratch up there so that it does not reach the host heap. An address "
                "up there means the port is not modelling something. Reported once.%s\n",
                storing ? "a store" : "a load", who, 0x80000000u + (uint32_t)off,
                committed ? "" : " The scratch could not be committed, so this access violation "
                                 "stands and the process is about to die of it.");
        /* Only for the thread the registers belong to, and only once the
         * scratch is there to walk through. */
        if (s && guest && committed) {
            fprintf(stderr, "  backtrace from r1:");
            guest_backtrace(s, s->gpr[1]);
        }
    }
    return committed ? EXCEPTION_CONTINUE_EXECUTION : EXCEPTION_CONTINUE_SEARCH;
}
#endif

/* The image every window folds onto. Off Windows, and if the reservation or
 * the handler will not take, the whole range is ordinary zeroed memory:
 * nothing the guest can do reaches the host heap either way, there is just
 * nothing to say that it tried. */
static uint8_t* mem_alloc(CpuState* s)
{
#ifdef _WIN32
    uint8_t* p = (uint8_t*)VirtualAlloc(NULL, MEM_RESERVE_BYTES, MEM_RESERVE, PAGE_NOACCESS);
    if (p) {
        if (VirtualAlloc(p, MEM1_SIZE, MEM_COMMIT, PAGE_READWRITE)
            && AddVectoredExceptionHandler(1, mem_guard)) {
            g_mem_base = p;
            g_mem_state = s;
            g_mem_tid = GetCurrentThreadId();
            g_mem_guarded = 1;
            return p;
        }
        VirtualFree(p, 0, MEM_RELEASE);
    }
    fprintf(stderr, "[mem] cannot reserve the guarded MEM1 window (error %lu); running without the "
                    "out-of-range tripwire\n",
            (unsigned long)GetLastError());
#endif
    (void)s;
    return (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
}

/* SOA_MEMPOKE=addr[,addr...] stores a word at each guest address and reads it
 * back, before the game runs. Nothing in a working run goes near the range the
 * tripwire covers, which would leave the tripwire itself untested until the
 * day it mattered; this is how to fire it on purpose, and a list of addresses
 * past the RAM is how to see that it still only says so once. It happens
 * before the disc is read, so it needs no disc. */
static void mem_poke(CpuState* s)
{
    const char* p = getenv("SOA_MEMPOKE");
    if (!p || !*p) return;
    if (!g_mem_guarded)
        fprintf(stderr, "[mem] SOA_MEMPOKE: no tripwire is armed, so an out-of-range address will be "
                        "silent\n");
    while (*p) {
        char* end;
        uint32_t ea = (uint32_t)strtoul(p, &end, 0);
        if (end == p) break; /* not a number: stop rather than spin on it */
        /* The hardware window is not memory and this runs before dvd_init,
         * threads_init and the first GX state exist: a store to 0xCC008000
         * would enter the write-gather pipe, and one to 0xCC006000 a device
         * model that has not been set up. The switch is here to fire the
         * tripwire, which is about RAM. */
        if (is_mmio(ea))
            fprintf(stderr, "[mem] SOA_MEMPOKE: %08X is in the hardware window (MMIO or the "
                            "write-gather pipe), which is not set up yet; skipped\n", ea);
        else {
            mem_w32(s, ea, 0xDEADBEEFu);
            fprintf(stderr, "[mem] SOA_MEMPOKE: %08X <- DEADBEEF, reads back %08X\n", ea,
                    mem_r32(s, ea));
        }
        p = end + (*end == ',' ? 1 : 0);
    }
}

/* SOA_POKE=frame:addr=value[,frame:addr=value...] stores one 32-bit word into
 * guest memory at the end of the named frame, once, and says what was there
 * before. PLAN D2 asked for this and gave the reason: nothing in runtime/ could
 * write guest memory while the game ran, so every question of the form "what
 * does the game do if this variable says that" needed a recompile to answer.
 *
 * SOA_MEMPOKE above is a different thing and stays: it fires before the disc is
 * read, to test the out-of-range tripwire. This one fires inside the run.
 *
 * Fired on the first frame at or after the target rather than on equality: a
 * frame number can be skipped -- SOA_SNAP skips rasterizing, the game can
 * present nothing across a long load -- and a poke that silently never
 * happened would be read as the game ignoring it, which is the worst possible
 * failure for a switch whose whole purpose is answering that question.
 *
 * Addresses are the game's, so the useful ones are worth naming here. The
 * field's own map identity, verified against the three MEM1 images in
 * build/fifo (all of which say a101b, which is what the trace says loaded):
 *   0x80311AC4  map number, a word          -- 101
 *   0x80311AC8  map letter, top byte        -- 0x62000000 is 'b'
 *   0x80311AEC  field state, a word         -- 8 is the steady per-frame update
 * `/field/a%03d%c.mld` is sprintf'd from the first two (0x801017A8). */
/* Three words warp the field, so the limit is really "how many maps can one
 * run visit": 256 items is 85 of them. */
#define POKE_MAX 256

typedef struct {
    unsigned frame;
    uint32_t ea, value;
    int done;
} Poke;

static Poke g_pokes[POKE_MAX];
static int g_poke_n = -1; /* -1 until SOA_POKE has been read */

/* One number of an item, or 0 if it is not one. strtoul alone read three
 * things nobody typed and armed them without a word: MSVC's unsigned long is
 * 32 bits, so 0x100000000 saturated to FFFFFFFF (and a frame past 2^32 never
 * fired); base 0 read 0101 as octal 65; and it skips spaces and takes a sign,
 * so -1 was FFFFFFFF. */
static int poke_number(const char** p, int base, uint32_t* out)
{
    const char* s = *p;
    char* end;
    unsigned long long v;
    if (*s < '0' || *s > '9') return 0;
    if (base == 0 && s[0] == '0' && s[1] >= '0' && s[1] <= '9') return 0;
    v = strtoull(s, &end, base);
    if (end == s || v > 0xFFFFFFFFull) return 0;
    *out = (uint32_t)v;
    *p = end;
    return 1;
}

static void poke_parse(void)
{
    const char* p = getenv("SOA_POKE");
    g_poke_n = 0;
    if (!p || !*p) return;
    while (*p && g_poke_n < POKE_MAX) {
        const char* item = p; /* a refusal quotes the whole item, not the half of it that failed */
        uint32_t frame, ea, value;
        if (!poke_number(&p, 10, &frame) || *p != ':') { p = item; break; }
        p++;
        if (!poke_number(&p, 0, &ea) || *p != '=') { p = item; break; }
        p++;
        if (!poke_number(&p, 0, &value) || (*p && *p != ',')) { p = item; break; }
        g_pokes[g_poke_n].frame = frame;
        g_pokes[g_poke_n].ea = ea;
        g_pokes[g_poke_n].value = value;
        g_poke_n++;
        p += *p == ',' ? 1 : 0;
    }
    /* Refusing quietly is what a switch must never do: a run driven by a
     * mistyped poke looks exactly like a run whose poke did nothing. */
    if (*p)
        fprintf(stderr, "[poke] SOA_POKE: stopped at %.32s -- each item is frame:addr=value, "
                        "decimal frame, 0x addresses and values accepted, up to %d items; "
                        "%d parsed\n", p, POKE_MAX, g_poke_n);
    else if (g_poke_n)
        fprintf(stderr, "[poke] %d poke(s) armed\n", g_poke_n);
}

/* SOA_PEEK=addr@N[-M][,...] reads a word at the end of frame N, or of every
 * frame from N to M, and prints it with the game's retrace count -- the read
 * half of SOA_POKE without having to write the value back. SOA_WATCH cannot
 * serve here: it stops after 201 hits and says which store, not which frame, so
 * "how many fields does this fade take" had no answer without a tracepoint and
 * a retranslation. Peeks fire before pokes in the same hook, so a peek and a
 * poke of one word at one frame read what the game wrote. Its own list, not a
 * share of SOA_POKE's 256. */
#define PEEK_MAX 256
#define VI_RETRACE_COUNT 0x80347A64u /* the VI library's retraceCount */

typedef struct {
    uint32_t ea;
    unsigned first, last, done;
} Peek;

static Peek g_peeks[PEEK_MAX];
static int g_peek_n = -1;

static void peek_parse(void)
{
    const char* p = getenv("SOA_PEEK");
    g_peek_n = 0;
    if (!p || !*p) return;
    while (*p && g_peek_n < PEEK_MAX) {
        const char* item = p;
        uint32_t ea, first, last;
        if (!poke_number(&p, 0, &ea) || *p != '@') { p = item; break; }
        p++;
        if (!poke_number(&p, 10, &first)) { p = item; break; }
        last = first;
        if (*p == '-') {
            p++;
            if (!poke_number(&p, 10, &last) || last < first) { p = item; break; }
        }
        if (*p && *p != ',') { p = item; break; }
        g_peeks[g_peek_n].ea = ea;
        g_peeks[g_peek_n].first = first;
        g_peeks[g_peek_n].last = last;
        g_peeks[g_peek_n].done = 0;
        g_peek_n++;
        p += *p == ',' ? 1 : 0;
    }
    if (*p)
        fprintf(stderr, "[peek] SOA_PEEK: stopped at %.32s -- each item is addr@frame or addr@first-last, "
                        "up to %d items; %d parsed\n", p, PEEK_MAX, g_peek_n);
    else if (g_peek_n)
        fprintf(stderr, "[peek] %d peek(s) armed\n", g_peek_n);
}

static void peek_at_frame(CpuState* s, unsigned frame)
{
    int i;
    if (g_peek_n < 0) peek_parse();
    for (i = 0; i < g_peek_n; i++) {
        Peek* k = &g_peeks[i];
        /* A single frame fires once on the first frame at or after it, as a
         * poke does; a range fires on every frame inside it that is presented. */
        if (k->done || frame < k->first) continue;
        if (k->first == k->last) k->done = 1;
        else if (frame > k->last) { k->done = 1; continue; }
        if (is_mmio(k->ea)) {
            fprintf(stderr, "[peek] frame %u: %08X is in the hardware window, not memory; skipped\n", frame, k->ea);
            k->done = 1;
            continue;
        }
        fprintf(stderr, "[peek] frame %u: %08X = %08X (retrace %u)\n", frame, k->ea, mem_r32(s, k->ea),
                mem_r32(s, VI_RETRACE_COUNT));
    }
}

void poke_at_frame(CpuState* s, unsigned frame);

void poke_at_frame(CpuState* s, unsigned frame)
{
    int i;
    peek_at_frame(s, frame);
    if (g_poke_n < 0) poke_parse();
    for (i = 0; i < g_poke_n; i++) {
        if (g_pokes[i].done || frame < g_pokes[i].frame) continue;
        g_pokes[i].done = 1;
        if (is_mmio(g_pokes[i].ea)) {
            fprintf(stderr, "[poke] frame %u: %08X is in the hardware window, not memory; skipped\n",
                    frame, g_pokes[i].ea);
            continue;
        }
        fprintf(stderr, "[poke] frame %u: %08X <- %08X (was %08X)\n", frame, g_pokes[i].ea,
                g_pokes[i].value, mem_r32(s, g_pokes[i].ea));
        mem_w32(s, g_pokes[i].ea, g_pokes[i].value);
    }
}

#define ARENA_HI 0x81700000u
#define GEKKO_PVR 0x00083214u

static void w32(uint8_t* mem, uint32_t ea, uint32_t v)
{
    v = BSWAP32(v);
    memcpy(mem + (ea & MEM_MASK), &v, 4);
}
static uint32_t be32(const uint8_t* p)
{
    uint32_t v;
    memcpy(&v, p, 4);
    return BSWAP32(v);
}

static uint8_t* slurp(const char* path, size_t* size)
{
    FILE* f = fopen(path, "rb");
    uint8_t* buf;
    long n;
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return NULL; }
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    /* A directory, or a file that cannot be seeked, gives a negative length,
     * and malloc(0) may hand back nothing at all: either way the read below
     * would run on a pointer this function never got. */
    buf = n > 0 ? (uint8_t*)malloc((size_t)n) : NULL;
    if (!buf) { fclose(f); fprintf(stderr, "cannot read %s\n", path); return NULL; }
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(buf); return NULL; }
    fclose(f);
    *size = (size_t)n;
    return buf;
}

/* DOL header: 7 text + 11 data sections, then BSS and the entry point. */
static int load_dol(uint8_t* mem, const uint8_t* dol, size_t size)
{
    int i;
    if (size < 0x100) { /* the header itself is read below */
        fprintf(stderr, "main.dol is %zu bytes, too short to hold a DOL header\n", size);
        return 0;
    }
    for (i = 0; i < 18; i++) {
        uint32_t off = be32(dol + i * 4);
        uint32_t addr = be32(dol + 0x48 + i * 4);
        uint32_t len = be32(dol + 0x90 + i * 4);
        uint32_t dest = addr & MEM_MASK;
        if (!len) continue;
        /* Offset, address and length all come out of the file and all three
         * are 32-bit, so every bound here is written as a difference: as a
         * sum, a corrupt or crafted header wraps it and the memcpy below
         * copies gigabytes out of a small buffer into the image. */
        if (off > size || len > size - off || dest >= MEM1_SIZE || len > MEM1_SIZE - dest) {
            fprintf(stderr, "DOL section %d out of range\n", i);
            return 0;
        }
        memcpy(mem + dest, dol + off, len);
    }
    /* BSS is already zero: the image comes back zeroed, however it was got. */
    return 1;
}

/* What the boot ROM and apploader leave in the OS low-memory area. Values
 * follow the GameCube's documented layout; the OS reads several of them
 * during OSInit. */
static void setup_low_memory(uint8_t* mem, const uint8_t* boot, uint32_t fst_addr, uint32_t fst_max)
{
    memcpy(mem, boot, 0x20); /* game ID, maker, disc, version, streaming, magic */
    w32(mem, 0x80000020u, 0x0D15EA5Eu); /* standard boot code magic */
    w32(mem, 0x80000024u, 0x00000001u); /* version */
    w32(mem, 0x80000028u, MEM1_SIZE);   /* physical memory size */
    w32(mem, 0x8000002Cu, 0x00000003u); /* console type: retail production board */
    w32(mem, 0x80000030u, 0x00000000u); /* arena lo: let the OS derive it */
    w32(mem, 0x80000034u, fst_addr);    /* arena hi: the FST sits just above it */
    w32(mem, 0x80000038u, fst_addr);    /* FST location */
    w32(mem, 0x8000003Cu, fst_max);     /* FST max size */
    w32(mem, 0x800000CCu, 0x00000000u); /* video mode: NTSC */
    w32(mem, 0x800000D0u, MEM1_SIZE);   /* simulated memory size (mirror) */
    w32(mem, 0x800000F0u, MEM1_SIZE);   /* simulated memory size */
    w32(mem, 0x800000F8u, 0x09A7EC80u); /* bus clock, 162 MHz */
    w32(mem, 0x800000FCu, 0x1CF7C580u); /* CPU clock, 486 MHz */
}

/* snprintf returns the length it wanted, not the length it wrote, so clamp
 * before using the total as an offset again. */
#define STOP_ADD(buf, n, ...)                                            \
    do {                                                                 \
        (n) += snprintf((buf) + (n), sizeof(buf) - (size_t)(n), __VA_ARGS__); \
        if ((n) > (int)sizeof(buf) - 1) (n) = (int)sizeof(buf) - 1;      \
    } while (0)

/* One line before the guest starts. Which mode the port is in, what will end
 * the run and how to drive it are exactly the three things the switch names
 * used to answer wrongly, so say them outright. The keys are window.c's
 * mapping; keep the two in step. */
static void print_mode(int windowed, int rendering, int scripted, unsigned frames, unsigned snap,
                       unsigned watchdog_secs)
{
    char stop[256], snaps[80];
    int n = 0;
    stop[0] = '\0';
    snaps[0] = '\0';
    /* A snapshot needs something to snapshot: without SOA_RENDER the EFB copy
     * hook never reaches the renderer, so no PNG is ever written. Say that
     * rather than promise files that will not appear. */
    if (snap && rendering)
        snprintf(snaps, sizeof snaps, ", a snapshot to build/frames every %u frames", snap);
    if (frames) STOP_ADD(stop, n, "stopping after %u frames", frames);
    if (windowed) STOP_ADD(stop, n, "%sEscape or closing the window quits", n ? ", " : "");
    if (watchdog_secs)
        STOP_ADD(stop, n, "%swatchdog if no frame for %us (SOA_WATCHDOG=0 disables it)", n ? ", " : "",
                 watchdog_secs);
    if (!n) snprintf(stop, sizeof stop, "nothing will stop it -- Ctrl-C to quit");
    if (windowed)
        fprintf(stderr, "[run] window%s%s; %s; keys X=A Z=B C=X V=Y, Enter or Space=START, Q=L E=R R=Z, "
                        "T/F/G/H=D-pad up/left/down/right, arrows or WASD=stick, IJKL=C-stick\n",
                rendering ? "" : " (blank until SOA_RENDER=1: nothing is drawn without it)", snaps, stop);
    else if (snap && rendering)
        fprintf(stderr, "[run] headless%s; %s\n", snaps, stop);
    else if (snap)
        fprintf(stderr, "[run] headless; SOA_SNAP is set but SOA_RENDER is not, so nothing is drawn and "
                        "no snapshot is written; %s\n", stop);
    else if (rendering)
        fprintf(stderr, "[run] headless, rendering with nowhere to put it -- SOA_WINDOW=1 for a window, "
                        "SOA_SNAP=n for PNGs in build/frames; %s\n", stop);
    else
        fprintf(stderr, "[run] headless; %s\n", stop);
    if (scripted)
        fprintf(stderr, "[run] SOA_PAD drives the controller%s\n",
                windowed ? "; the keyboard and gamepad add to it" : "");
}

static void usage(void)
{
    fprintf(stderr,
            "soa.exe [extracted-dir]             run the game (default directory: extracted)\n"
            "soa.exe --replay build/fifo/0000    render one captured frame to <base>.png\n"
            "\n"
            "Environment (PowerShell: $env:SOA_RENDER='1'):\n"
            "  SOA_RENDER=1     draw the game; a window opens unless SOA_SNAP or SOA_PAD is set\n"
            "  SOA_WINDOW=0|1   force the window off or on\n"
            "  SOA_FRAMES=n     run n video frames (numbered 0..n-1), then stop and print the report\n"
            "  SOA_SNAP=n       write build/frames/NNNN.png every n frames; needs SOA_RENDER=1\n"
            "  SOA_WATCHDOG=s   report and stop after s seconds with no frame (default 20 headless,\n"
            "                   off when a window is open; 0 disables it)\n"
            "  SOA_MMIO=1       log the first few accesses of every hardware register\n"
            "  SOA_PROFILE=n    0 turns off the end-of-run sampling profile; n>1 shows n rows\n"
            "  SOA_PAD=f:btns   scripted controller, e.g. 1700:start (implies no window)\n"
            "  SOA_MEMPOKE=a,b  store a word at each guest address before boot; an address past the\n"
            "                   console's 24 MB, e.g. 0x81800000, fires the MEM1 tripwire\n"
            "The rest of the switches, and the keyboard mapping, are in README.md.\n");
}

int main(int argc, char** argv)
{
    const char* dir = argc > 1 && argv[1][0] != '-' ? argv[1] : "extracted";
    char path[1024];
    uint8_t *dol, *boot, *fst;
    size_t dol_size, boot_size, fst_size;
    uint32_t fst_addr, fst_max;
    static CpuState s;

    /* An option we do not know is a typo, not a directory: saying so beats
     * booting the game as though nothing had been asked for. */
    if (argc > 1 && argv[1][0] == '-') {
        int replay = strcmp(argv[1], "--replay") == 0;
        if (strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "-?") == 0) {
            usage();
            return 0;
        }
        if (!replay || argc < 3) {
            fprintf(stderr, "%s: %s\n", argv[1],
                    replay ? "--replay needs the base path of a captured frame" : "unknown option");
            usage();
            return 1;
        }
    }

    /* Before anything else this process does, so that "wall seconds" in the
     * report means the run and not the part of it that asked first. */
    hle_clock_start();
    s.mem = mem_alloc(&s);
    if (!s.mem) { fprintf(stderr, "cannot allocate MEM1\n"); return 1; }
    mem_poke(&s);
    /* Read SOA_POKE here rather than at the first frame that needs it, so a
     * mistyped item is refused while the person who typed it is still looking,
     * instead of sixteen thousand frames later in a run that appears to have
     * ignored them. The pokes themselves still fire at their own frames. */
    poke_parse();
    peek_parse();
    watch_init(); /* here with the others, so SOA_WATCH is read before the disc is */
    gx_set_frame_hook(poke_at_frame);

    snprintf(path, sizeof path, "%s/sys/main.dol", dir);
    dol = slurp(path, &dol_size);
    snprintf(path, sizeof path, "%s/sys/boot.bin", dir);
    boot = slurp(path, &boot_size);
    snprintf(path, sizeof path, "%s/sys/fst.bin", dir);
    fst = slurp(path, &fst_size);
    if (!dol || !boot || !fst) {
        fprintf(stderr, "[boot] %s does not look like an extracted disc (sys/main.dol, sys/boot.bin and "
                        "sys/fst.bin live there); run: python tools/extract.py <your disc dump> --iso\n", dir);
        return 1;
    }

    if (!load_dol(s.mem, dol, dol_size)) return 1;

    /* The apploader parks the FST at the top of memory, 32-byte aligned, and
     * ends the arena where it starts. Both files are bounded before they are
     * believed: boot.bin's header is read as far as 0x430, and an FST larger
     * than the arena would make the subtraction below underflow into an
     * arbitrary destination offset -- this is the one write into the image
     * here that is not a device model's, so it carries its own bound. */
    if (boot_size < 0x430) {
        fprintf(stderr, "[boot] sys/boot.bin is %zu bytes; the disc header is 0x440\n", boot_size);
        return 1;
    }
    if (fst_size == 0 || fst_size > ARENA_HI - 0x80000000u) {
        fprintf(stderr, "[boot] sys/fst.bin is %zu bytes, which does not fit under the arena at "
                        "%08X\n", fst_size, ARENA_HI);
        return 1;
    }
    fst_max = be32(boot + 0x42C);
    fst_addr = (ARENA_HI - (uint32_t)fst_size) & ~31u;
    memcpy(s.mem + (fst_addr & MEM_MASK), fst, fst_size);
    setup_low_memory(s.mem, boot, fst_addr, fst_max);

    s.spr[287] = GEKKO_PVR;
    s.msr = 0x00002030u; /* FP | IR | DR -- __init_hardware rewrites it anyway */

    fprintf(stderr, "[boot] DOL %zu bytes, FST %zu bytes at %08X; entering %s\n", dol_size,
            fst_size, fst_addr, STR(ENTRY_FN));
    snprintf(path, sizeof path, "%s/disc.iso", dir);
    dvd_init(path);
    threads_init(&s);
    if (getenv("SOA_SELFTEST")) return selftest(&s) ? 7 : 0;
    if (argc > 2 && strcmp(argv[1], "--replay") == 0) {
        /* Render one captured frame (see gx.c frame capture) to <base>.png. */
        char png[1024];
        snprintf(png, sizeof png, "%s.png", argv[2]);
        gxr_enable(1);
        gxr_set_output(png);
        return gx_replay(&s, argv[2]);
    }
    {
        /* A window when rendering for a person: SOA_RENDER is set and neither
         * of the two switches that mean nobody is watching -- SOA_SNAP, which
         * writes frames to disk, and SOA_PAD, which drives the controller from
         * a script the live keyboard would otherwise override. SOA_WINDOW
         * forces it either way. SOA_FRAMES has no bearing here -- it only says
         * when to stop. */
        const char* r = getenv("SOA_RENDER");
        const char* w = getenv("SOA_WINDOW");
        const char* f = getenv("SOA_FRAMES");
        const char* snapenv = getenv("SOA_SNAP");
        const char* pad = getenv("SOA_PAD");
        unsigned frames = f ? (unsigned)atoi(f) : 0u;
        unsigned snap = snapenv ? (unsigned)atoi(snapenv) : 0u;
        int rendering = r && atoi(r);
        int scripted = pad && *pad;
        int want = rendering && !snap && !scripted;
        unsigned secs;
        if (w) want = atoi(w) != 0;
#ifndef _WIN32
        want = 0; /* window.c is stubs off Windows; do not promise a window or a quit key */
#endif
        gx_set_frame_limit(frames);
        /* Skipping the frames between snapshots is a headless speed-up. A
         * window asked for alongside them wants every frame drawn, or it
         * shows the clear colour all but one frame in N. */
        if (want && snap) gxr_draw_every_frame();
        /* The watchdog has to know about the window, so decide the window
         * first; window_open() cannot answer yet, the UI thread has not run. */
        secs = start_watchdog(&s, want);
        profile_start(&s);
        print_mode(want, rendering, scripted, frames, snap, secs);
        if (want) window_start(); /* after the line above: the UI thread prints from its own thread */
    }
    ENTRY_FN(&s);

    fprintf(stderr, "[boot] entry point returned\n");
    hle_report();
    return 0;
}
