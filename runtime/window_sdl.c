/*
 * The screen and the controller off Windows (portability L10): an SDL3
 * window on its own thread, as window.c's Win32 one is, showing each frame
 * the renderer copies out, with live input from the keyboard or any gamepad
 * SDL knows for controller ports 1 and 2. Built only when SOA_SDL is defined,
 * which tools/recompile.py does on Linux when tools/fetch_sdl.py has filled
 * vendor/sdl3; window.c keeps Windows (D2).
 *
 * It does what window.c does, in the same words where the words are shared:
 * the keyboard layout (arrows/WASD main stick, IJKL C-stick, X = A, Z = B,
 * C = X, V = Y, Enter/Space = START, R = Z, Q = L, E = R, T/F/G/H = D-pad;
 * Escape leaves fullscreen or closes, F11 or Alt+Enter toggles borderless
 * fullscreen), the gamepad mapping with XInput's dead zones and trigger
 * threshold, the host buttons (LB, View, the stick clicks, Tab), rumble on
 * port 1, `unfocused` mute and pause, SOA_SCALE, SOA_SCALER, SOA_FULLSCREEN,
 * P5a's filters, SOA_WINDOW_TEST, and the [present] report.
 *
 * The frame is scaled on the CPU by picture_scale, as the DXGI presenter
 * scales it, into a client-sized texture that the renderer shows 1:1, held
 * for g_interval refreshes by the renderer's vsync where it allows that.
 *
 * Every SDL call is on the window's thread. The guest thread asks for the
 * pads through window_pad, so this thread reads the keyboard and the pads
 * after each batch of events and leaves what it read under a lock; a key or
 * a stick moving is an event, so the wait below ends at once. The motor is
 * the other way round: si.c's sink leaves the speed, and this thread applies
 * it and wakes for it.
 */
#ifdef SOA_SDL
#include <SDL3/SDL.h>
#include "cpu.h"
#include "gxr.h"
#include "picture.h"
#include "plat.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

long gxr_presented(void);
void hle_report(void);
void hle_on_report(void (*fn)(void));
uint64_t irq_retrace_count(void);
void watchdog_fallback(void);
void si_set_motor_sink(void (*fn)(unsigned speed));
void si_set_motor_window(int open);
void si_motor_stop(void);
int tick_turbo_now(void);
void clock_pause(int on);
void audio_set_muted(int on);

/* ---- SDL's start, shared with audio_sdl.c ----------------------------------
 * The window's thread and the sound's both start parts of SDL, and SDL's
 * init counts are not made for two threads at once: one lock. SDL's own
 * SIGINT and SIGTERM handlers stay out, so a signal means what it means
 * without a window. */
static PlatLock g_init_lock;

int soa_sdl_init(unsigned flags, const char** why)
{
    static int once;
    int ok;
    plat_lock(&g_init_lock);
    if (!once) {
        once = 1;
        SDL_SetHint(SDL_HINT_NO_SIGNAL_HANDLERS, "1");
        SDL_SetAppMetadata("Skies of Arcadia Legends -- native", NULL, "soa");
    }
    ok = SDL_InitSubSystem((SDL_InitFlags)flags);
    if (!ok && why) *why = SDL_GetError();
    plat_unlock(&g_init_lock);
    return ok;
}

static SDL_Window* g_win;
static SDL_Renderer* g_ren;
static SDL_Texture* g_tex;
static volatile int g_open;
static int g_scale; /* SOA_SCALE, or 0: the largest whole multiple of 640x480 that fits the display */
static uint8_t* g_bgra; /* the frame converted, BGRA, for P5a and the scaler */
static int g_shown_w, g_shown_h;
static uint8_t* g_scaled; /* the texture's contents, client-sized */
static int g_bw, g_bh;
static Uint32 g_wake; /* the event type that wakes this thread: data 1 fullscreen, 2 the motor */

/* ---- the paced presenter: window.c's H8, on SDL's renderer ---------------- */
static unsigned g_interval = 2;  /* refreshes each frame is held */
static int g_vsync;              /* what the renderer agreed to hold each present for: 0 none */
static double g_refresh_ms = 0;  /* the display's refresh period, as SDL's mode says */
static unsigned g_present_failed, g_resize_failed;
static PicFilterState* g_filters; /* P5a: gamma, colour-blind, flash limit; NULL with none set */
static uint64_t* g_pt;            /* plat_mono_raw at each present */
static size_t g_pt_n, g_pt_cap;
static uint64_t* g_pw; /* the ticks of each present's own work, the frame to the texture */
static size_t g_pw_n, g_pw_cap;
static uint64_t g_pw_t0;
static uint64_t g_guest0, g_host0;
static int g_drift_started;
static PlatLock g_times_lock; /* g_pt and g_pw: the window appends, the report reads */

/* ---- the window that fits (H19a) ------------------------------------------ */
static int g_scaler = PICTURE_INTEGER;
static int g_fullscreen;
static volatile int g_resized;
static uint64_t g_mouse_at; /* SDL_GetTicks at the last mouse movement, for hiding the cursor */
static int g_unfocused_mute; /* `unfocused = mute` (M5b) */
static int g_unfocused_pause; /* `unfocused = pause` (M19) */
static int g_turbo_shown;
static volatile int g_away; /* another window has the focus */

static void times_append(uint64_t** a, size_t* n, size_t* cap, uint64_t v)
{
    plat_lock(&g_times_lock);
    if (*n == *cap) {
        size_t c = *cap ? *cap * 2 : 4096;
        uint64_t* p = (uint64_t*)realloc(*a, c * sizeof *p);
        if (!p) {
            plat_unlock(&g_times_lock);
            return;
        }
        *a = p;
        *cap = c;
    }
    (*a)[(*n)++] = v;
    plat_unlock(&g_times_lock);
}

static void note_present(void)
{
    uint64_t now = plat_mono_raw();
    times_append(&g_pt, &g_pt_n, &g_pt_cap, now);
    if (!g_drift_started) {
        g_host0 = now;
        g_guest0 = irq_retrace_count();
        g_drift_started = 1;
    }
}

static void note_present_work(void)
{
    times_append(&g_pw, &g_pw_n, &g_pw_cap, plat_mono_raw() - g_pw_t0);
}

static int cmp_u64(const void* a, const void* b)
{
    uint64_t x = *(const uint64_t*)a, y = *(const uint64_t*)b;
    return (x > y) - (x < y);
}

static double ms_of(uint64_t ticks) { return 1000.0 * (double)ticks / plat_mono_hz(); }

/* window.c's report, line for line: the histogram in refreshes of the
 * display, the present's own work, P5a's counts, the failures and the drift. */
static void present_report(void)
{
    double period_ms = g_refresh_ms > 0.0 ? g_refresh_ms : 1000.0 / 60.0;
    size_t i, n;
    unsigned bins[5] = {0, 0, 0, 0, 0};
    uint64_t* d;
    char what[96];
    plat_lock(&g_times_lock);
    n = g_pt_n > 1 ? g_pt_n - 1 : 0;
    snprintf(what, sizeof what, "sdl3 %s renderer", g_ren ? SDL_GetRendererName(g_ren) : "no");
    if (!n || !(d = (uint64_t*)malloc(n * sizeof *d))) {
        fprintf(stderr, "[present] %s: fewer than two frames presented\n", what);
        plat_unlock(&g_times_lock);
        return;
    }
    for (i = 0; i < n; i++) {
        int r = (int)(ms_of(g_pt[i + 1] - g_pt[i]) / period_ms + 0.5);
        bins[r < 1 ? 0 : (r > 4 ? 4 : r)]++;
        d[i] = g_pt[i + 1] - g_pt[i];
    }
    qsort(d, n, sizeof *d, cmp_u64);
    fprintf(stderr,
            "[present] %s: %zu intervals between presents at a %.2f ms refresh (%.1f Hz): under 1 refresh %u, 1: %u, "
            "2: %u, 3: %u, 4 or more: %u; p50 %.1f ms, p99 %.1f ms\n",
            what, n, period_ms, 1000.0 / period_ms, bins[0], bins[1], bins[2], bins[3], bins[4], ms_of(d[n / 2]),
            ms_of(d[(n * 99) / 100]));
    free(d);
    n = g_pw_n;
    if (n && (d = (uint64_t*)malloc(n * sizeof *d)) != NULL) {
        memcpy(d, g_pw, n * sizeof *d);
        qsort(d, n, sizeof *d, cmp_u64);
        fprintf(stderr, "[present] the work of a present, the frame to the back buffer%s: p50 %.2f ms, p99 %.2f ms, max %.2f ms over %zu\n",
                g_filters ? " with the picture's filters" : "", ms_of(d[n / 2]), ms_of(d[(n * 99) / 100]), ms_of(d[n - 1]), n);
        free(d);
    }
    if (g_filters) {
        unsigned long long frames, held;
        double most;
        picture_filter_counts(g_filters, &frames, &held, &most);
        fprintf(stderr, "[picture] %llu frame(s) filtered; the flash limiter held %llu back, and at most %.2f%% of the "
                        "picture flashed more than three times in a second (the limit is under 25%%)\n",
                frames, held, 100.0 * most);
    }
    fprintf(stderr, "[present] %u failed present(s), %u failed resize(s)\n", g_present_failed, g_resize_failed);
    if (g_drift_started && g_pt_n > 1) {
        double secs = (double)(g_pt[g_pt_n - 1] - g_host0) / plat_mono_hz();
        double guest = (double)(irq_retrace_count() - g_guest0);
        if (secs > 1.0)
            fprintf(stderr, "[present] the guest's VI ran %.3f Hz over %.1f s of presents, the display %.3f Hz (H9)\n",
                    guest / secs, secs, 1000.0 / period_ms);
    }
    plat_unlock(&g_times_lock);
}

/* The refresh period of the display the window is on, from its mode; 0
 * when the mode does not say. */
static double refresh_ms(void)
{
    const SDL_DisplayMode* m = SDL_GetCurrentDisplayMode(SDL_GetDisplayForWindow(g_win));
    if (m && m->refresh_rate_numerator > 0 && m->refresh_rate_denominator > 0)
        return 1000.0 * (double)m->refresh_rate_denominator / (double)m->refresh_rate_numerator;
    if (m && m->refresh_rate > 0.0f) return 1000.0 / (double)m->refresh_rate;
    return 0.0;
}

/* The renderer's vsync to g_interval refreshes, or every refresh where it
 * holds only one: this loop presents only a new frame, so 30 frames a
 * second still take every other refresh at 60 Hz, as the next refresh
 * rather than a promise. */
static void set_vsync(void)
{
    if (SDL_SetRenderVSync(g_ren, (int)g_interval)) g_vsync = (int)g_interval;
    else if (SDL_SetRenderVSync(g_ren, 1)) g_vsync = 1;
    else g_vsync = 0;
}

static void pace(int fps)
{
    double hz = g_refresh_ms > 0.0 ? 1000.0 / g_refresh_ms : 60.0;
    g_interval = present_interval(hz, fps);
    set_vsync();
}

/* ---- rumble (si.c, M18) ---------------------------------------------------- */
static plat_a64 g_motor_want; /* the speed si.c asked for, 0-65535 */
static unsigned g_motor_applied;
static uint64_t g_motor_at;

static void wake(int what)
{
    SDL_Event e;
    SDL_zero(e);
    e.type = g_wake;
    e.user.code = what;
    SDL_PushEvent(&e); /* the one SDL call made from other threads: SDL says it may be */
}

static void motor(unsigned speed)
{
    plat_xchg64(&g_motor_want, (int64_t)speed);
    if (g_wake) wake(2);
}

/* ---- the pads -------------------------------------------------------------- */
#define MAX_PADS 8
static SDL_Gamepad* g_pads[MAX_PADS]; /* in the order they came: port 1 is the first, port 2 the next */
static int g_npads;

typedef struct {
    int present;
    uint16_t buttons;
    uint8_t stick[2], cstick[2], trig[2];
} PadOut;
static PadOut g_out1, g_out2;
static uint16_t g_host_out;
static PlatLock g_in_lock;

/* The letters by the layout in use, as Win32's virtual keys are: the key
 * that types an X is A, wherever it is. */
enum { KX, KZ, KC, KV, KR, KQ, KE, KT, KG, KF, KH, KA, KD, KW, KS, KJ, KL, KI, KK, KCOUNT };
static const SDL_Keycode g_letters[KCOUNT] = {SDLK_X, SDLK_Z, SDLK_C, SDLK_V, SDLK_R, SDLK_Q, SDLK_E,
                                              SDLK_T, SDLK_G, SDLK_F, SDLK_H, SDLK_A, SDLK_D, SDLK_W,
                                              SDLK_S, SDLK_J, SDLK_L, SDLK_I, SDLK_K};
static SDL_Scancode g_sc[KCOUNT];

static void read_layout(void)
{
    int i;
    for (i = 0; i < KCOUNT; i++) g_sc[i] = SDL_GetScancodeFromKey(g_letters[i], NULL);
}

static uint8_t stick_byte(int v)
{
    return (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
}

/* One gamepad in the game's terms, for port 1 and port 2 alike: window.c's
 * map_xinput with SDL's names. XInput's triggers are 0-255 and SDL's 0-32767,
 * and SDL's Y axes point down where XInput's point up. */
static uint16_t map_pad(SDL_Gamepad* g, int* sx, int* sy, int* cx, int* cy, int* lt, int* rt)
{
    uint16_t b = 0;
    int l = SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_LEFT_TRIGGER) * 255 / 32767;
    int r = SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) * 255 / 32767;
    int lx = SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_LEFTX), ly = -(int)SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_LEFTY);
    int rx = SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_RIGHTX), ry = -(int)SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_RIGHTY);
    if (ly > 32767) ly = 32767;
    if (ry > 32767) ry = 32767;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_SOUTH)) b |= 0x0100;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_EAST)) b |= 0x0200;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_WEST)) b |= 0x0400;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_NORTH)) b |= 0x0800;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_START)) b |= 0x1000;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER)) b |= 0x0010;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_DPAD_UP)) b |= 0x0008;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_DPAD_DOWN)) b |= 0x0004;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_DPAD_LEFT)) b |= 0x0001;
    if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_DPAD_RIGHT)) b |= 0x0002;
    if (l > 30) { b |= 0x0040; *lt = l; }
    if (r > 30) { b |= 0x0020; *rt = r; }
    if (abs(lx) > 7849 || abs(ly) > 7849) { *sx = 128 + lx / 258; *sy = 128 + ly / 258; }
    if (abs(rx) > 8689 || abs(ry) > 8689) { *cx = 128 + rx / 258; *cy = 128 + ry / 258; }
    return b;
}

static void pad_out(PadOut* o, uint16_t b, int sx, int sy, int cx, int cy, int lt, int rt)
{
    o->present = 1;
    o->buttons = b;
    o->stick[0] = stick_byte(sx);
    o->stick[1] = stick_byte(sy);
    o->cstick[0] = stick_byte(cx);
    o->cstick[1] = stick_byte(cy);
    o->trig[0] = (uint8_t)lt;
    o->trig[1] = (uint8_t)rt;
}

/* The keyboard (while the window has the focus) and the pads, read here and
 * left for window_pad, window_pad2 and window_host. */
static void read_input(void)
{
    PadOut p1, p2;
    uint16_t b = 0, host = 0;
    int sx = 128, sy = 128, cx = 128, cy = 128, lt = 0, rt = 0;
    int muted = g_unfocused_mute && g_away;
    memset(&p2, 0, sizeof p2);
    if (SDL_GetKeyboardFocus() == g_win) {
        const bool* k = SDL_GetKeyboardState(NULL);
        int alt = (SDL_GetModState() & SDL_KMOD_ALT) != 0;
#define K(i) k[g_sc[i]]
        if (K(KX)) b |= 0x0100; /* A */
        if (K(KZ)) b |= 0x0200; /* B */
        if (K(KC)) b |= 0x0400; /* X */
        if (K(KV)) b |= 0x0800; /* Y */
        if ((k[SDL_SCANCODE_RETURN] && !alt) || k[SDL_SCANCODE_SPACE]) b |= 0x1000; /* START; Alt+Enter is fullscreen */
        if (K(KR)) b |= 0x0010; /* Z */
        if (K(KQ)) { b |= 0x0040; lt = 255; }
        if (K(KE)) { b |= 0x0020; rt = 255; }
        if (K(KT)) b |= 0x0008;
        if (K(KG)) b |= 0x0004;
        if (K(KF)) b |= 0x0001;
        if (K(KH)) b |= 0x0002;
        if (k[SDL_SCANCODE_LEFT] || K(KA)) sx = 0;
        if (k[SDL_SCANCODE_RIGHT] || K(KD)) sx = 255;
        if (k[SDL_SCANCODE_UP] || K(KW)) sy = 255;
        if (k[SDL_SCANCODE_DOWN] || K(KS)) sy = 0;
        if (K(KJ)) cx = 0;
        if (K(KL)) cx = 255;
        if (K(KI)) cy = 255;
        if (K(KK)) cy = 0;
        if (k[SDL_SCANCODE_TAB]) host |= 0x1;
#undef K
    }
    if (g_npads > 0 && !muted) {
        SDL_Gamepad* g = g_pads[0];
        b |= map_pad(g, &sx, &sy, &cx, &cy, &lt, &rt);
        if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER)) host |= 0x1;
        if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_BACK)) host |= 0x2;
        if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_LEFT_STICK)) host |= 0x4;
        if (SDL_GetGamepadButton(g, SDL_GAMEPAD_BUTTON_RIGHT_STICK)) host |= 0x8;
    }
    pad_out(&p1, b, sx, sy, cx, cy, lt, rt);
    if (g_npads > 1) {
        /* port 2 (P10a): connected, and let go while another window has the
         * focus under `unfocused = mute`, so a co-op mod keeps its player */
        int sx2 = 128, sy2 = 128, cx2 = 128, cy2 = 128, lt2 = 0, rt2 = 0;
        uint16_t b2 = muted ? 0 : map_pad(g_pads[1], &sx2, &sy2, &cx2, &cy2, &lt2, &rt2);
        pad_out(&p2, b2, sx2, sy2, cx2, cy2, lt2, rt2);
    }
    plat_lock(&g_in_lock);
    g_out1 = p1;
    g_out2 = p2;
    g_host_out = host;
    plat_unlock(&g_in_lock);
}

static void pad_added(SDL_JoystickID id)
{
    SDL_Gamepad* g;
    if (g_npads == MAX_PADS || !(g = SDL_OpenGamepad(id))) return;
    g_pads[g_npads++] = g;
    fprintf(stderr, "[window] gamepad \"%s\" is port %d's\n", SDL_GetGamepadName(g), g_npads);
    g_motor_applied = 0; /* port 1 may be a new pad: the motor again */
}

static void pad_removed(SDL_JoystickID id)
{
    int i;
    for (i = 0; i < g_npads; i++)
        if (SDL_GetGamepadID(g_pads[i]) == id) {
            fprintf(stderr, "[window] gamepad \"%s\" left port %d\n", SDL_GetGamepadName(g_pads[i]), i + 1);
            SDL_CloseGamepad(g_pads[i]);
            memmove(&g_pads[i], &g_pads[i + 1], (size_t)(g_npads - i - 1) * sizeof g_pads[0]);
            g_npads--;
            g_motor_applied = 0;
            return;
        }
}

/* The speed si.c last asked for, on port 1's pad. SDL's rumble lasts as long
 * as it is told to, so a motor that stays on is told again each second, and
 * stops by itself within 1.5 s of the program that started it ending. */
static void apply_motor(void)
{
    unsigned want = (unsigned)plat_load64(&g_motor_want);
    uint64_t now = SDL_GetTicks();
    if (!g_npads) return;
    if (want == g_motor_applied && (!want || now - g_motor_at < 1000)) return;
    SDL_RumbleGamepad(g_pads[0], (Uint16)want, (Uint16)want, want ? 1500 : 0);
    g_motor_applied = want;
    g_motor_at = now;
}

/* ---- the window ----------------------------------------------------------- */
static void set_fullscreen(int on)
{
    if (!g_win || on == g_fullscreen) return;
    SDL_SetWindowFullscreenMode(g_win, NULL); /* borderless, at the desktop's mode */
    SDL_SetWindowFullscreen(g_win, on != 0);
    g_fullscreen = on;
}

static void close_window(void)
{
    g_open = 0;
    si_set_motor_window(0);
    si_motor_stop();
    apply_motor();
    fprintf(stderr, "[window] closed\n");
    hle_report();
    /* window.c's reason: closing is how a recording ends, and _exit does not flush */
    fflush(NULL);
    _exit(0);
}

/* The renderer's newest frame into g_bgra and through P5a's filters, timed
 * at the display's clock so the flash limiter counts seconds as shown. */
static void filter_on_cpu(uint64_t t0)
{
    int w, h, x, y;
    const uint8_t* src = gxr_screen(&w, &h);
    if (!g_bgra) g_bgra = (uint8_t*)malloc((size_t)EFB_W * EFB_H * 4);
    if (!g_bgra) return;
    for (y = 0; y < h; y++) {
        const uint8_t* s = src + (size_t)y * EFB_W * 4;
        uint8_t* d = g_bgra + (size_t)y * w * 4;
        for (x = 0; x < w; x++) { d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; d[3] = 255; s += 4; d += 4; }
    }
    if (g_filters) {
        static unsigned logged;
        double a = picture_filter(g_filters, g_bgra, w, h, (double)t0 / plat_mono_hz());
        if (a < 1.0 && logged++ < 20)
            fprintf(stderr, "[picture] frame %ld: held back from a flash, shown %.0f%% of the way%s\n", gxr_presented(),
                    100.0 * a, logged == 20 ? " (the last of these lines)" : "");
    }
    g_shown_w = w;
    g_shown_h = h;
}

/* g_bgra into a client-sized texture where picture_layout puts it, nearest
 * neighbour with black bars -- the DXGI presenter's picture_scale -- shown
 * 1:1 and presented, held by the renderer's vsync. */
static void sdl_present(int w, int h)
{
    int bw = 0, bh = 0;
    PicRect r;
    if (!g_bgra || !SDL_GetCurrentRenderOutputSize(g_ren, &bw, &bh) || bw < 1 || bh < 1) return;
    if (bw != g_bw || bh != g_bh) {
        uint8_t* s = (uint8_t*)realloc(g_scaled, (size_t)bw * bh * 4);
        if (g_tex) SDL_DestroyTexture(g_tex);
        g_tex = s ? SDL_CreateTexture(g_ren, SDL_PIXELFORMAT_XRGB8888, SDL_TEXTUREACCESS_STREAMING, bw, bh) : NULL;
        if (s) g_scaled = s;
        if (!g_tex) {
            g_resize_failed++;
            g_bw = g_bh = 0;
            return;
        }
        SDL_SetTextureScaleMode(g_tex, SDL_SCALEMODE_NEAREST);
        g_bw = bw;
        g_bh = bh;
    }
    r = picture_layout(w, h, g_bw, g_bh, g_scaler);
    if (r.w < 1 || r.h < 1) return;
    picture_scale(g_bgra, w, h, g_scaled, g_bw, g_bh, g_scaler);
    if (!SDL_UpdateTexture(g_tex, NULL, g_scaled, g_bw * 4) || !SDL_RenderTexture(g_ren, g_tex, NULL, NULL)) {
        g_present_failed++;
        return;
    }
    note_present_work();
    if (!SDL_RenderPresent(g_ren)) g_present_failed++;
    note_present();
}

/* A new frame from the renderer (`fresh`), or the one shown, at a new size. */
static void present(int fresh)
{
    g_pw_t0 = plat_mono_raw();
    if (fresh || !g_shown_w) filter_on_cpu(g_pw_t0);
    if (g_shown_w) sdl_present(g_shown_w, g_shown_h);
}

/* SOA_WINDOW_TEST=fs@300,win@600,size:1000x700@900 (H19a's check), as window.c. */
typedef struct { long frame; int kind, w, h; } WindowAct; /* kind 0 fs, 1 win, 2 size */
static WindowAct g_acts[16];
static int g_act_n, g_act_i;

static void window_test_parse(void)
{
    const char* p = getenv("SOA_WINDOW_TEST");
    while (p && *p && g_act_n < 16) {
        WindowAct a;
        char* end;
        memset(&a, 0, sizeof a);
        if (!strncmp(p, "fs@", 3)) { a.kind = 0; p += 3; }
        else if (!strncmp(p, "win@", 4)) { a.kind = 1; p += 4; }
        else if (!strncmp(p, "size:", 5)) {
            a.kind = 2;
            a.w = (int)strtol(p + 5, &end, 10);
            if (*end != 'x') break;
            a.h = (int)strtol(end + 1, &end, 10);
            if (*end != '@') break;
            p = end + 1;
        } else break;
        a.frame = strtol(p, &end, 10);
        if (end == p) break;
        g_acts[g_act_n++] = a;
        p = *end == ',' ? end + 1 : end;
    }
    if (p && *p) fprintf(stderr, "[window] SOA_WINDOW_TEST not understood from \"%s\" on; that part is ignored\n", p);
}

static void window_line(long frame)
{
    int cw = 0, ch = 0, sw = g_shown_w ? g_shown_w : 640, sh = g_shown_h ? g_shown_h : 480;
    const SDL_DisplayMode* m = SDL_GetCurrentDisplayMode(SDL_GetDisplayForWindow(g_win));
    PicRect r;
    SDL_GetWindowSizeInPixels(g_win, &cw, &ch);
    r = picture_layout(sw, sh, cw, ch, g_scaler);
    fprintf(stderr, "[window] frame %ld: client %dx%d, image %dx%d at +%d+%d, from %dx%d, monitor %dx%d, mode %s %s\n",
            frame, cw, ch, r.w, r.h, r.x, r.y, sw, sh, m ? (int)(m->w * m->pixel_density) : 0,
            m ? (int)(m->h * m->pixel_density) : 0, g_scaler == PICTURE_FIT ? "fit" : "integer",
            g_fullscreen ? "fullscreen" : "window");
}

static void on_focus(int away)
{
    if (away) si_motor_stop(); /* nothing buzzes on the desk while the person looks elsewhere */
    g_away = away;
    if (g_unfocused_mute) audio_set_muted(away);
    if (g_unfocused_pause) clock_pause(away);
}

static void on_event(const SDL_Event* e)
{
    switch (e->type) {
    case SDL_EVENT_QUIT:
    case SDL_EVENT_WINDOW_CLOSE_REQUESTED:
        close_window();
        break;
    case SDL_EVENT_KEY_DOWN:
        if (e->key.repeat) break;
        if (e->key.key == SDLK_ESCAPE) {
            if (g_fullscreen) set_fullscreen(0); /* Escape leaves fullscreen first (Q-O3) */
            else close_window();
        } else if (e->key.key == SDLK_F11 || (e->key.key == SDLK_RETURN && (e->key.mod & SDL_KMOD_ALT))) {
            set_fullscreen(!g_fullscreen);
        }
        break;
    case SDL_EVENT_KEYMAP_CHANGED:
        read_layout();
        break;
    case SDL_EVENT_WINDOW_FOCUS_GAINED:
        on_focus(0);
        break;
    case SDL_EVENT_WINDOW_FOCUS_LOST:
        on_focus(1);
        break;
    case SDL_EVENT_WILL_ENTER_BACKGROUND: /* a phone's home button, a system's sleep: the game holds (M19) */
        si_motor_stop();
        clock_pause(1);
        break;
    case SDL_EVENT_DID_ENTER_FOREGROUND:
        clock_pause(0);
        break;
    case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED:
        g_resized = 1;
        break;
    case SDL_EVENT_WINDOW_ENTER_FULLSCREEN:
        g_fullscreen = 1;
        break;
    case SDL_EVENT_WINDOW_LEAVE_FULLSCREEN:
        g_fullscreen = 0;
        break;
    case SDL_EVENT_WINDOW_DISPLAY_CHANGED:
    case SDL_EVENT_DISPLAY_CURRENT_MODE_CHANGED: {
        double hz;
        g_refresh_ms = refresh_ms();
        pace(g_turbo_shown ? 60 : 30);
        hz = g_refresh_ms > 0.0 ? 1000.0 / g_refresh_ms : 60.0;
        fprintf(stderr, "[window] the display changed: %.1f Hz, each frame held %u refresh(es)\n", hz, g_interval);
        break;
    }
    case SDL_EVENT_MOUSE_MOTION:
        g_mouse_at = SDL_GetTicks();
        break;
    case SDL_EVENT_GAMEPAD_ADDED:
        pad_added(e->gdevice.which);
        break;
    case SDL_EVENT_GAMEPAD_REMOVED:
        pad_removed(e->gdevice.which);
        break;
    default:
        if (e->type == g_wake && e->user.code == 1) set_fullscreen(!g_fullscreen);
        break;
    }
}

/* The cursor goes in fullscreen, and after two seconds of no movement in a window. */
static void cursor(void)
{
    int hide = g_fullscreen || SDL_GetTicks() - g_mouse_at > 2000;
    if (hide && SDL_CursorVisible()) SDL_HideCursor();
    else if (!hide && !SDL_CursorVisible()) SDL_ShowCursor();
}

/* The largest whole multiple of 640x480 whose window fits the display's
 * usable area, a title bar's height left over (SDL cannot say how tall the
 * frame is before there is one). */
static int fit_scale(void)
{
    SDL_Rect u = {0, 0, 1280, 1024};
    int s;
    SDL_GetDisplayUsableBounds(SDL_GetPrimaryDisplay(), &u);
    for (s = 1; s < 16; s++)
        if (640 * (s + 1) > u.w || 480 * (s + 1) + 40 > u.h) break;
    return s;
}

static void headless(const char* what, const char* why)
{
    /* the watchdog stood down because this window was coming; without either,
     * nothing would ever end the run */
    fprintf(stderr, "[window] %s: %s; the run continues headless\n", what, why);
    g_open = 0;
    watchdog_fallback();
}

static void ui_thread(void* arg)
{
    const char* why = "";
    long last = -1;
    (void)arg;
    if (!soa_sdl_init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD, &why)) {
        headless("SDL could not start its video", why);
        return;
    }
    g_wake = SDL_RegisterEvents(1);
    if (!g_scale) g_scale = fit_scale();
    g_win = SDL_CreateWindow("Skies of Arcadia Legends -- native", 640 * g_scale, 480 * g_scale,
                             SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIGH_PIXEL_DENSITY);
    if (!g_win || !(g_ren = SDL_CreateRenderer(g_win, NULL))) {
        headless(g_win ? "SDL could not make a renderer" : "SDL could not make a window", SDL_GetError());
        return;
    }
    g_mouse_at = SDL_GetTicks();
    read_layout();
    {
        const char* fs = getenv("SOA_FULLSCREEN");
        const char* sc = getenv("SOA_SCALER");
        const char* uf = getenv("SOA_UNFOCUSED");
        const SDL_DisplayMode* m = SDL_GetCurrentDisplayMode(SDL_GetDisplayForWindow(g_win));
        double hz;
        if (uf && !strcmp(uf, "mute")) g_unfocused_mute = 1;
        else if (uf && !strcmp(uf, "pause")) g_unfocused_pause = 1;
        else if (uf && *uf && strcmp(uf, "run"))
            fprintf(stderr, "[window] SOA_UNFOCUSED=%s is not run, mute or pause; run\n", uf);
        if (sc && !strcmp(sc, "fit")) g_scaler = PICTURE_FIT;
        else if (sc && *sc && strcmp(sc, "integer"))
            fprintf(stderr, "[window] SOA_SCALER=%s is not integer or fit; integer\n", sc);
        {
            PicFilters pf;
            char text[160];
            if (!picture_filters_parse(&pf, getenv("SOA_GAMMA"), getenv("SOA_COLORBLIND"), getenv("SOA_COLORBLIND_MODE"),
                                       getenv("SOA_FLASH_LIMIT"), text, sizeof text))
                fprintf(stderr, "[picture] %s\n", text);
            if (picture_filters_any(&pf) && (g_filters = picture_filters_new(&pf)) != NULL) {
                picture_filters_name(&pf, text, sizeof text);
                fprintf(stderr, "[picture] %s\n", text);
            }
        }
        g_refresh_ms = refresh_ms();
        hz = g_refresh_ms > 0.0 ? 1000.0 / g_refresh_ms : 60.0;
        pace(30); /* a 30-a-second frame held a whole number of refreshes only where the rate is a multiple of 30 (H9) */
        hle_on_report(present_report);
        fprintf(stderr, "[window] the display refreshes every %.2f ms (%.1f Hz; the mode says %.2f Hz)%s\n", g_refresh_ms,
                hz, m ? (double)m->refresh_rate : 0.0,
                g_interval == 1 ? ", not a multiple of 30: each frame takes the next refresh" : "");
        if (fs && atoi(fs)) set_fullscreen(1);
    }
    window_test_parse();
    read_input(); /* before the port can ask: an unread snapshot is the stick hard left and down */
    g_open = 1;
    si_set_motor_sink(motor);
    si_set_motor_window(1);
    fprintf(stderr, "[window] open at %dx, presenting with SDL3's %s renderer (video %s), each frame held %u refresh(es)%s\n",
            g_scale, SDL_GetRendererName(g_ren), SDL_GetCurrentVideoDriver(), g_interval,
            g_vsync == (int)g_interval ? "" : g_vsync ? " by this loop, the renderer holding one" : " by this loop, the renderer holding none");
    for (;;) {
        SDL_Event e;
        long now;
        int logged_resize = 0;
        while (SDL_PollEvent(&e)) on_event(&e);
        apply_motor();
        read_input();
        cursor();
        now = gxr_presented();
        if (tick_turbo_now() != g_turbo_shown) {
            /* at turbo the game makes up to 60 images a second (M11a) */
            g_turbo_shown = tick_turbo_now();
            pace(g_turbo_shown ? 60 : 30);
            fprintf(stderr, "[window] frame %ld: turbo %s, each frame held %u refresh(es)\n", now,
                    g_turbo_shown ? "on" : "off", g_interval);
        }
        if (g_act_i < g_act_n && now >= g_acts[g_act_i].frame) {
            const WindowAct* a = &g_acts[g_act_i++];
            if (a->kind == 0) set_fullscreen(1);
            else if (a->kind == 1) set_fullscreen(0);
            else {
                set_fullscreen(0);
                SDL_SyncWindow(g_win);
                SDL_SetWindowSize(g_win, a->w, a->h);
            }
            SDL_SyncWindow(g_win); /* what the switch asked of the window system, done */
            while (SDL_PollEvent(&e)) on_event(&e);
            logged_resize = 1;
        }
        if (g_resized) {
            g_resized = 0;
            if (g_shown_w) present(0); /* the last frame again, at the new size */
        }
        if (logged_resize) window_line(now);
        if (now != last) { last = now; present(1); }
        SDL_WaitEventTimeout(NULL, 8);
    }
}

void window_start(void)
{
    static PlatThread t;
    const char* env = getenv("SOA_SCALE");
    if (env && atoi(env) > 0) g_scale = atoi(env);
    if (!plat_thread_start(&t, ui_thread, NULL, 0)) {
        fprintf(stderr, "[window] cannot start the UI thread; the run continues headless\n");
        watchdog_fallback();
        return;
    }
    plat_thread_detach(&t);
}

int window_open(void)
{
    return g_open;
}

/* The View+LB chord (CH1): fullscreen on or off, on the window's thread. */
int window_toggle_fullscreen(void)
{
    if (!g_open) return 0;
    wake(1);
    return 1;
}

/* Port 1: the keyboard while the window has the focus, and the first pad. */
int window_pad(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2])
{
    PadOut o;
    if (!g_open) return 0;
    plat_lock(&g_in_lock);
    o = g_out1;
    plat_unlock(&g_in_lock);
    *buttons = o.buttons;
    memcpy(stick, o.stick, 2);
    memcpy(cstick, o.cstick, 2);
    memcpy(trig, o.trig, 2);
    return 1;
}

/* Port 2 (P10a): the next pad, for mods only; 0 with none. */
int window_pad2(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2])
{
    PadOut o;
    if (!g_open) return 0;
    plat_lock(&g_in_lock);
    o = g_out2;
    plat_unlock(&g_in_lock);
    if (!o.present) return 0;
    *buttons = o.buttons;
    memcpy(stick, o.stick, 2);
    memcpy(cstick, o.cstick, 2);
    memcpy(trig, o.trig, 2);
    return 1;
}

/* The host buttons (CH1): LB, View and the stick clicks of port 1's pad, and Tab. */
int window_host(uint16_t* host)
{
    if (!g_open) return 0;
    plat_lock(&g_in_lock);
    *host = g_host_out;
    plat_unlock(&g_in_lock);
    return 1;
}
#endif
