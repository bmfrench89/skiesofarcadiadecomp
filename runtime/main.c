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
unsigned gx_frame_count(void);
void gxr_draw_every_frame(void);
int irq_in_handler(void);

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

/* Sample the guest's block address every millisecond while waiting, so the
 * report is a profile of what the guest spent its time in, not one snapshot. */
#define SAMPLES 8192
static uint32_t g_samples[SAMPLES];

static int cmp_desc(const void* a, const void* b)
{
    const uint32_t* x = (const uint32_t*)a;
    const uint32_t* y = (const uint32_t*)b;
    return x[1] < y[1] ? 1 : x[1] > y[1] ? -1 : 0;
}

static void profile_report(unsigned n)
{
    static uint32_t hist[SAMPLES][2]; /* addr, count */
    unsigned i, j, k = 0, shown;
    for (i = 0; i < n; i++) {
        for (j = 0; j < k; j++)
            if (hist[j][0] == g_samples[i]) { hist[j][1]++; break; }
        if (j == k) { hist[k][0] = g_samples[i]; hist[k][1] = 1; k++; }
    }
    qsort(hist, k, sizeof hist[0], cmp_desc);
    fprintf(stderr, "[profile] %u samples over %u blocks; top (H = inside an interrupt handler):\n",
            n, k);
    shown = k < 16 ? k : 16;
    for (i = 0; i < shown; i++)
        fprintf(stderr, "  %5.1f%%  %08X %s\n", 100.0 * hist[i][1] / n, hist[i][0] & ~1u,
                (hist[i][0] & 1u) ? "H" : "");
}

void guest_backtrace(CpuState* s, uint32_t sp);
static unsigned __stdcall watchdog(void* arg)
{
    unsigned secs = (unsigned)(uintptr_t)arg;
    unsigned n = 0, frames = gx_frame_count();
    ULONGLONG t0 = GetTickCount64();
    /* Sleep(1) is really ~15 ms at the default timer resolution, so pace the
     * wait by the clock rather than by counting sleeps. */
    for (;;) {
        unsigned now;
        Sleep(1);
        /* Block addresses are 4-aligned; bit 0 tags samples taken in a handler. */
        if (n < SAMPLES) g_samples[n++] = g_state->pc | (irq_in_handler() ? 1u : 0u);
        /* Every frame presented restarts the clock, so the timeout means what
         * the message says -- nothing happened for this long -- and the
         * profile below covers the stall rather than the whole run. A boot
         * that never reaches its first frame still reports, on time. */
        now = gx_frame_count();
        if (now != frames) { frames = now; n = 0; t0 = GetTickCount64(); continue; }
        if (GetTickCount64() - t0 >= (ULONGLONG)secs * 1000u) break;
    }
    fprintf(stderr, "[watchdog] no video frame for %us (SOA_WATCHDOG=0 disables it, SOA_WATCHDOG=s "
                    "changes the timeout); %u frames so far, last block %08X\n", secs, frames, g_state->pc);
    hle_dump(g_state, g_state->pc);
    fprintf(stderr, "  backtrace from r1:");
    guest_backtrace(g_state, g_state->gpr[1]);
    profile_report(n);
    hle_report();
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
#endif

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
    buf = (uint8_t*)malloc((size_t)n);
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(buf); return NULL; }
    fclose(f);
    *size = (size_t)n;
    return buf;
}

/* DOL header: 7 text + 11 data sections, then BSS and the entry point. */
static int load_dol(uint8_t* mem, const uint8_t* dol, size_t size)
{
    int i;
    for (i = 0; i < 18; i++) {
        uint32_t off = be32(dol + i * 4);
        uint32_t addr = be32(dol + 0x48 + i * 4);
        uint32_t len = be32(dol + 0x90 + i * 4);
        if (!len) continue;
        if (off + len > size || (addr & MEM_MASK) + len > MEM1_SIZE) {
            fprintf(stderr, "DOL section %d out of range\n", i);
            return 0;
        }
        memcpy(mem + (addr & MEM_MASK), dol + off, len);
    }
    /* BSS is already zero: the image came from calloc. */
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
            "  SOA_PAD=f:btns   scripted controller, e.g. 1700:start (implies no window)\n"
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

    s.mem = (uint8_t*)calloc(1, MEM1_SIZE);
    if (!s.mem) { fprintf(stderr, "cannot allocate MEM1\n"); return 1; }

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
     * ends the arena where it starts. */
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
    watch_init();
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
        print_mode(want, rendering, scripted, frames, snap, secs);
        if (want) window_start(); /* after the line above: the UI thread prints from its own thread */
    }
    ENTRY_FN(&s);

    fprintf(stderr, "[boot] entry point returned\n");
    hle_report();
    return 0;
}
