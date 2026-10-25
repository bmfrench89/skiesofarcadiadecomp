/*
 * The screen and the controller: a Win32 window on its own thread that
 * shows each frame the renderer copies out, and live input from the
 * keyboard or an XInput gamepad for controller port 1.
 *
 * Keyboard: arrows/WASD main stick, IJKL C-stick, X = A, Z = B, C = X,
 * V = Y, Enter/Space = START, R = Z, Q = L, E = R, T/F/G/H = D-pad,
 * Escape closes (or leaves fullscreen). F11 or Alt+Enter toggles borderless
 * fullscreen (H19a). Gamepad: the obvious mapping, triggers to L/R, RB to Z;
 * LB, View and the stick clicks are host buttons (CH1).
 *
 * window_pad() reports the whole controller -- both sticks at their real
 * positions and both triggers at their real values, not just the twelve
 * buttons -- because si.c writes that down under SOA_PAD_RECORD and replays
 * it under SOA_PAD_FILE, and a recording that kept only the buttons could
 * not repeat a walk across a field.
 */
#ifdef _WIN32
#define _CRT_SECURE_NO_WARNINGS
#define COBJMACROS
#include "cpu.h"
#include "gxr.h"
#include "picture.h"
#include "gxv.h"
#include "interp_rate.h"
#include "clock.h"
#include "menu.h"
#include <windows.h>
#include <xinput.h>
#include <process.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <dwmapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "xinput9_1_0.lib")
#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "dxguid.lib")
#pragma comment(lib, "dwmapi.lib")

long gxr_presented(void);
void hle_report(void);
void hle_on_report(void (*fn)(void));
uint64_t irq_retrace_count(void);
void watchdog_fallback(void);

static HWND g_hwnd;
static volatile int g_open;
static int g_scale; /* SOA_SCALE, or 0: the largest whole multiple of 640x480 that fits the monitor */
static uint8_t* g_bgra; /* the frame converted for GDI */
static int g_shown_w, g_shown_h;
static int g_ring_on;     /* the frames come from gxr's screen ring (H17b) */
static GxrShown g_frame;  /* the ring's slot being shown: the UI thread's until its next take */
/* H17b: refreshes each image is held while in-between images are shown (1 at
 * 60 Hz, 2 at 120), 0 while they are not; and what was shown, for the report. */
static unsigned g_mid_ivl;
static plat_a32 g_shown_mid, g_shown_cut, g_shown_none;
static void interp_pace(double hz);
static HMONITOR g_monitor; /* H17c-b: the monitor the display's rate was read from */
static HANDLE g_fresh_ev;  /* H17c-b: set when the GPU publishes a frame, which the loop waits on */
static void fresh_signal(void) { SetEvent(g_fresh_ev); }
/* H17d: why interp_pace shows no in-between image, as the player is told it
 * (NULL while they are shown); and the rate they are shown at. */
static char g_interp_tell[80];
static int g_interp_off;
static unsigned g_interp_hz;
static int g_pace_ready;   /* the presenter is chosen, so a move may pace again */

/* ---- the paced presenter (PLAN-60FPS-MODS H8) ----------------------------
 *
 * The window used to be painted with GDI whenever the 8 ms poll below saw a
 * new frame: no relation to the display's refresh, so a frame at 30 a second
 * was held for one refresh, then three, then two, as the poll and the vblank
 * drifted past each other. This is a DXGI flip-model swap chain instead: each
 * new frame is copied into the back buffer (scaled by whole pixels on the CPU,
 * as GDI's COLORONCOLOR did, so it looks the same) and presented with a sync
 * interval of 2, which holds it for exactly two refreshes -- 30 frames a
 * second paced to a 60 Hz display. SOA_PRESENTER=gdi keeps the old path, and
 * the old path is also what runs if DXGI cannot start. Both paths record the
 * time of every present for the report, which is the histogram H8 asks for,
 * and the guest's retraces are set against the host's refreshes over the
 * session, the drift H9 needs. Nothing here touches g_screen, so no frame
 * hash can move. */
static int g_dxgi; /* 1 when the flip-model presenter is running */
static int g_vk;   /* 1 when the GPU presents its own picture (V8: gxv's swap chain) */
static ID3D11Device* g_dev;
static ID3D11DeviceContext* g_ctx;
static IDXGISwapChain1* g_sc;
static uint8_t* g_scaled; /* the back buffer's contents, client-sized */
static int g_bw, g_bh;
static LARGE_INTEGER g_qpf;
static LONGLONG* g_pt; /* QPC time of each present */
static size_t g_pt_n, g_pt_cap;
static uint64_t g_guest0;
static LONGLONG g_host0; /* QPC at the first present */
static int g_drift_started;
static UINT g_interval = 2;     /* refreshes each frame is held */
static double g_refresh_ms = 0; /* the display's refresh period, as DWM measures it */
static unsigned g_present_failed, g_resize_failed;
static PicFilterState* g_filters; /* P5a: gamma, colour-blind, flash limit; NULL with none set */
static int g_flash;               /* the flash limiter is on: the CPU decides its blend, even with the GPU presenting */
static LONGLONG* g_pw;            /* QPC ticks of each present's own work, the frame to the back buffer */
static size_t g_pw_n, g_pw_cap;
static LONGLONG g_pw_t0;
static SRWLOCK g_times_lock = SRWLOCK_INIT; /* g_pt and g_pw: the window appends, the report reads */

/* ---- the window that fits (H19a) ------------------------------------------
 * The client is any size now: the picture goes in it by picture_layout --
 * the largest whole multiple of the frame (`scaler = integer`, the default)
 * or the largest 4:3 that fits (`fit`) -- centred, with black bars. Borderless
 * fullscreen (F11, Alt+Enter, the View+LB chord) is a WS_POPUP over the
 * monitor, with the window's placement put back on the way out. */
static int g_scaler = PICTURE_INTEGER;
static int g_fullscreen;
static WINDOWPLACEMENT g_placement;
static volatile int g_resized;     /* WM_SIZE seen: the swap chain follows at the loop */
static int g_client_w, g_client_h; /* the client as WM_SIZE last said, 0x0 minimised */
static ULONGLONG g_mouse_at;       /* the last mouse movement, for hiding the cursor */
static int g_unfocused_mute;       /* `unfocused = mute` (M5b) */
static int g_unfocused_pause;      /* `unfocused = pause` (M19) */
int tick_turbo_now(void);          /* M11a: 60 images a second while on */
static int g_turbo_shown;          /* the turbo state g_interval was chosen for */
void clock_pause(int on);
static volatile int g_away;        /* another window is in front */
void audio_set_muted(int on);
#define WM_APP_FULLSCREEN (WM_APP + 1)
#define WM_APP_MENU (WM_APP + 7) /* M8: View+LS from the guest thread */
int tick_turbo_toggle(void);
/* The menu (M8, menu.c), on this thread: toggled, and a key into it. */
static void menu_toggle_ui(void);
static void menu_key(int key);

static void note_present(void)
{
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    AcquireSRWLockExclusive(&g_times_lock);
    if (g_pt_n == g_pt_cap) {
        size_t cap = g_pt_cap ? g_pt_cap * 2 : 4096;
        LONGLONG* p = (LONGLONG*)realloc(g_pt, cap * sizeof *g_pt);
        if (!p) {
            ReleaseSRWLockExclusive(&g_times_lock);
            return;
        }
        g_pt = p;
        g_pt_cap = cap;
    }
    g_pt[g_pt_n++] = now.QuadPart;
    if (!g_drift_started) {
        g_host0 = now.QuadPart;
        g_guest0 = irq_retrace_count();
        g_drift_started = 1;
    }
    ReleaseSRWLockExclusive(&g_times_lock);
}

/* The present's own work, from the frame read to the back buffer written --
 * the conversion, P5a's filters, the scaler, the upload -- and not the wait
 * for the display, for the report's p99 and max. */
static void note_present_work(void)
{
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    AcquireSRWLockExclusive(&g_times_lock);
    if (g_pw_n == g_pw_cap) {
        size_t cap = g_pw_cap ? g_pw_cap * 2 : 4096;
        LONGLONG* p = (LONGLONG*)realloc(g_pw, cap * sizeof *g_pw);
        if (!p) {
            ReleaseSRWLockExclusive(&g_times_lock);
            return;
        }
        g_pw = p;
        g_pw_cap = cap;
    }
    g_pw[g_pw_n++] = now.QuadPart - g_pw_t0;
    ReleaseSRWLockExclusive(&g_times_lock);
}

/* The display's refresh period, from DWM's own measurement: what the sync
 * interval has to be counted in. */
static double refresh_ms(void)
{
    DWM_TIMING_INFO ti;
    memset(&ti, 0, sizeof ti);
    ti.cbSize = sizeof ti;
    if (SUCCEEDED(DwmGetCompositionTimingInfo(NULL, &ti)) && ti.qpcRefreshPeriod && g_qpf.QuadPart)
        return 1000.0 * (double)ti.qpcRefreshPeriod / (double)g_qpf.QuadPart;
    return 0.0;
}

static int cmp_ll(const void* a, const void* b)
{
    LONGLONG x = *(const LONGLONG*)a, y = *(const LONGLONG*)b;
    return (x > y) - (x < y);
}

/* The histogram, in refreshes of the display, and the drift; the report
 * runs on whichever thread stops the run, so it reads under the lock. */
static void present_report_locked(void);
static void present_report(void)
{
    AcquireSRWLockExclusive(&g_times_lock);
    present_report_locked();
    ReleaseSRWLockExclusive(&g_times_lock);
}

static void present_report_locked(void)
{
    double period_ms = g_refresh_ms > 0.0 ? g_refresh_ms : 1000.0 / 60.0;
    size_t i, n = g_pt_n > 1 ? g_pt_n - 1 : 0;
    unsigned bins[5] = {0, 0, 0, 0, 0};
    LONGLONG* d;
    if (!n || !(d = (LONGLONG*)malloc(n * sizeof *d))) {
        fprintf(stderr, "[present] %s: fewer than two frames presented\n", g_dxgi ? "dxgi" : "gdi");
        return;
    }
    for (i = 0; i < n; i++) {
        double ms = 1000.0 * (double)(g_pt[i + 1] - g_pt[i]) / (double)g_qpf.QuadPart;
        int r = (int)(ms / period_ms + 0.5);
        bins[r < 1 ? 0 : (r > 4 ? 4 : r)]++;
        d[i] = g_pt[i + 1] - g_pt[i];
    }
    qsort(d, n, sizeof *d, cmp_ll);
    fprintf(stderr,
            "[present] %s: %zu intervals between presents at a %.2f ms refresh (%.1f Hz): under 1 refresh %u, 1: %u, "
            "2: %u, 3: %u, 4 or more: %u; p50 %.1f ms, p99 %.1f ms\n",
            g_vk ? "vulkan swap chain, from the GPU" : g_dxgi ? "dxgi flip model" : "gdi, 8 ms poll", n, period_ms, 1000.0 / period_ms, bins[0], bins[1],
            bins[2], bins[3], bins[4], 1000.0 * (double)d[n / 2] / (double)g_qpf.QuadPart,
            1000.0 * (double)d[(n * 99) / 100] / (double)g_qpf.QuadPart);
    free(d);
    n = g_pw_n;
    if (n && (d = (LONGLONG*)malloc(n * sizeof *d)) != NULL) {
        /* P5a: the present's own work, which the filters add to (a copy:
         * the window may still be presenting) */
        memcpy(d, g_pw, n * sizeof *d);
        qsort(d, n, sizeof *d, cmp_ll);
        fprintf(stderr, "[present] the work of a present, the frame to the back buffer%s: p50 %.2f ms, p99 %.2f ms, max %.2f ms over %zu\n",
                g_filters ? " with the picture's filters" : "", 1000.0 * (double)d[n / 2] / (double)g_qpf.QuadPart,
                1000.0 * (double)d[(n * 99) / 100] / (double)g_qpf.QuadPart, 1000.0 * (double)d[n - 1] / (double)g_qpf.QuadPart, n);
        free(d);
    }
    if (g_filters) {
        unsigned long long frames, held;
        double most;
        picture_filter_counts(g_filters, &frames, &held, &most);
        if (g_vk && !g_flash)
            fprintf(stderr, "[picture] the filters ran on the GPU, at the size it drew (V8b); [gxv] counts the frames\n");
        else
            fprintf(stderr, "[picture] %llu frame(s) filtered%s; the flash limiter held %llu back, and at most %.2f%% of the "
                            "picture flashed more than three times in a second (the limit is under 25%%)\n",
                    frames, g_vk ? " on the CPU for the flash limiter's decision, which the GPU applied (V8b)" : "", held,
                    100.0 * most);
    }
    fprintf(stderr, "[present] %u failed present(s), %u failed resize(s)\n", g_present_failed, g_resize_failed);
    if (gxr_interp() && g_vk) {
        unsigned long long m, c, z;
        gxv_present_interp_counts(&m, &c, &z);
        fprintf(stderr, "[interp] shown by the GPU's presenter: %llu in-between images; %llu frames held at a cut, %llu "
                        "with none (over budget, or not built)\n", m, c, z);
    } else if (gxr_interp())
        fprintf(stderr, "[interp] shown: %ld in-between images; %ld frames held at a cut, %ld with none (over budget, or "
                        "not built); %ld frames replaced in the ring before they were shown\n",
                (long)plat_load32(&g_shown_mid), (long)plat_load32(&g_shown_cut), (long)plat_load32(&g_shown_none),
                gxr_ring_missed());
    if (g_drift_started && g_pt_n > 1) {
        /* the guest's VI against the wall clock, and so against the display:
         * H9 locks the two only where the display's rate is a multiple of 60 */
        double secs = (double)(g_pt[g_pt_n - 1] - g_host0) / (double)g_qpf.QuadPart;
        double guest = (double)(irq_retrace_count() - g_guest0);
        if (secs > 1.0)
            fprintf(stderr, "[present] the guest's VI ran %.3f Hz over %.1f s of presents, the display %.3f Hz (H9)\n",
                    guest / secs, secs, 1000.0 / period_ms);
    }
}

static int dxgi_start(HWND h, int w, int ht)
{
    IDXGIDevice1* dd = NULL;
    IDXGIAdapter* ad = NULL;
    IDXGIFactory2* f = NULL;
    DXGI_SWAP_CHAIN_DESC1 d;
    D3D_FEATURE_LEVEL fl;
    HRESULT hr = D3D11CreateDevice(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL, D3D11_CREATE_DEVICE_BGRA_SUPPORT, NULL, 0,
                                   D3D11_SDK_VERSION, &g_dev, &fl, &g_ctx);
    if (FAILED(hr)) return 0;
    if (SUCCEEDED(ID3D11Device_QueryInterface(g_dev, &IID_IDXGIDevice1, (void**)&dd))) {
        IDXGIDevice1_SetMaximumFrameLatency(dd, 1);
        if (SUCCEEDED(IDXGIDevice1_GetAdapter(dd, &ad))) IDXGIAdapter_GetParent(ad, &IID_IDXGIFactory2, (void**)&f);
    }
    if (f) {
        memset(&d, 0, sizeof d);
        d.Width = (UINT)w;
        d.Height = (UINT)ht;
        d.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        d.SampleDesc.Count = 1;
        d.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        d.BufferCount = 2;
        d.Scaling = DXGI_SCALING_STRETCH;
        d.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
        d.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
        hr = IDXGIFactory2_CreateSwapChainForHwnd(f, (IUnknown*)g_dev, h, &d, NULL, NULL, &g_sc);
        if (SUCCEEDED(hr)) IDXGIFactory2_MakeWindowAssociation(f, h, DXGI_MWA_NO_ALT_ENTER);
    }
    if (f) IDXGIFactory2_Release(f);
    if (ad) IDXGIAdapter_Release(ad);
    if (dd) IDXGIDevice1_Release(dd);
    if (!g_sc) {
        ID3D11DeviceContext_Release(g_ctx);
        ID3D11Device_Release(g_dev);
        g_ctx = NULL;
        g_dev = NULL;
        return 0;
    }
    g_bw = w;
    g_bh = ht;
    g_scaled = (uint8_t*)calloc((size_t)w * ht, 4);
    return g_scaled != NULL;
}

/* g_bgra (the frame, w x h) into the back buffer where picture_layout puts
 * it -- nearest neighbour, so whole pixels at `integer` -- with black bars
 * round it, and presented, held for g_interval refreshes. */
static void dxgi_present(int w, int h)
{
    ID3D11Texture2D* bb = NULL;
    PicRect r = picture_layout(w, h, g_bw, g_bh, g_scaler);
    if (g_bw < 1 || g_bh < 1 || r.w < 1 || r.h < 1) return;
    picture_scale(g_bgra, w, h, g_scaled, g_bw, g_bh, g_scaler);
    menu_draw(g_scaled, g_bw, g_bh, g_bw * 4); /* M8: over the scaled copy only, when it is open */
    if (FAILED(IDXGISwapChain1_GetBuffer(g_sc, 0, &IID_ID3D11Texture2D, (void**)&bb)) || !bb) {
        g_present_failed++;
        return;
    }
    ID3D11DeviceContext_UpdateSubresource(g_ctx, (ID3D11Resource*)bb, 0, NULL, g_scaled, (UINT)g_bw * 4, 0);
    ID3D11Texture2D_Release(bb);
    note_present_work();
    if (FAILED(IDXGISwapChain1_Present(g_sc, g_interval, 0))) g_present_failed++;
    note_present();
}

/* The swap chain to the client's new size: no back buffer is held between
 * presents, so ResizeBuffers can run as it is. */
static void dxgi_resize(int w, int h)
{
    uint8_t* s;
    if (w < 1 || h < 1 || (w == g_bw && h == g_bh)) return;
    if (FAILED(IDXGISwapChain1_ResizeBuffers(g_sc, 0, (UINT)w, (UINT)h, DXGI_FORMAT_UNKNOWN, 0))) {
        g_resize_failed++;
        return;
    }
    s = (uint8_t*)realloc(g_scaled, (size_t)w * h * 4);
    if (!s) {
        g_resize_failed++;
        return;
    }
    g_scaled = s;
    g_bw = w;
    g_bh = h;
}

void si_set_motor_sink(void (*fn)(unsigned speed));
void si_set_motor_window(int open);
void si_motor_stop(void);

/* The rumble motor's sink (si.c, M18): both of port 1's motors at the speed
 * si.c asks for. A pad that is not there refuses the call, which is fine. */
static int g_pad_slot = -1; /* the XInput slot port 1 follows, or -1 for none */

static void motor(unsigned speed)
{
    XINPUT_VIBRATION v;
    int slot = g_pad_slot;
    v.wLeftMotorSpeed = v.wRightMotorSpeed = (WORD)speed;
    if (slot >= 0) XInputSetState((DWORD)slot, &v);
}

/* The monitor the window is on. */
static RECT monitor_rect(HWND h, int work)
{
    MONITORINFO mi;
    RECT r = {0, 0, 640, 480};
    memset(&mi, 0, sizeof mi);
    mi.cbSize = sizeof mi;
    if (GetMonitorInfoA(MonitorFromWindow(h, MONITOR_DEFAULTTOPRIMARY), &mi)) r = work ? mi.rcWork : mi.rcMonitor;
    return r;
}

#define WINDOW_STYLE WS_OVERLAPPEDWINDOW

/* Borderless fullscreen on and off, on the UI thread. */
static void set_fullscreen(int on)
{
    if (!g_hwnd || on == g_fullscreen) return;
    if (on) {
        RECT m = monitor_rect(g_hwnd, 0);
        memset(&g_placement, 0, sizeof g_placement);
        g_placement.length = sizeof g_placement;
        GetWindowPlacement(g_hwnd, &g_placement);
        SetWindowLongPtrA(g_hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE);
        SetWindowPos(g_hwnd, HWND_TOP, m.left, m.top, m.right - m.left, m.bottom - m.top,
                     SWP_FRAMECHANGED | SWP_NOOWNERZORDER);
    } else {
        SetWindowLongPtrA(g_hwnd, GWL_STYLE, WINDOW_STYLE | WS_VISIBLE);
        SetWindowPlacement(g_hwnd, &g_placement);
        SetWindowPos(g_hwnd, NULL, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
    }
    g_fullscreen = on;
}

/* The cursor goes in fullscreen, and after two seconds of no movement in a window. */
static int cursor_hidden(void)
{
    return g_fullscreen || GetTickCount64() - g_mouse_at > 2000;
}

static LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_ACTIVATEAPP:
        if (!w) si_motor_stop(); /* the person looked away: nothing buzzes on the desk */
        g_away = !w;
        if (g_unfocused_mute) audio_set_muted(g_away); /* and, asked, nothing plays or reads the pad */
        if (g_unfocused_pause) clock_pause(g_away);    /* or the game holds, and its clock with it */
        return DefWindowProc(h, m, w, l);
    case WM_POWERBROADCAST:
        /* A sleep the system announces: the game holds and its clock does
         * not count the time (M19). One it does not announce -- Modern
         * Standby -- is the clock's gap rule's. */
        if (w == PBT_APMSUSPEND) {
            si_motor_stop();
            clock_pause(1);
        } else if (w == PBT_APMRESUMEAUTOMATIC || w == PBT_APMRESUMESUSPEND) {
            clock_pause(0);
        }
        return TRUE;
    case WM_CLOSE:
    case WM_DESTROY:
        g_open = 0;
        PostQuitMessage(0);
        return 0;
    case WM_KEYDOWN:
        if (w == VK_F1) {
            menu_toggle_ui();
            return 0;
        }
        if (menu_is_open()) {
            /* the menu has the keyboard: the game is held and its pad withheld */
            if (w == VK_UP) menu_key(MENU_UP);
            else if (w == VK_DOWN) menu_key(MENU_DOWN);
            else if (w == VK_LEFT) menu_key(MENU_LEFT);
            else if (w == VK_RIGHT) menu_key(MENU_RIGHT);
            else if (w == VK_PRIOR) menu_key(MENU_BIG_LEFT);
            else if (w == VK_NEXT) menu_key(MENU_BIG_RIGHT);
            else if (w == VK_RETURN || w == VK_SPACE) menu_key(MENU_OK);
            else if (w == VK_ESCAPE || w == VK_BACK) menu_key(MENU_BACK);
            return 0;
        }
        if (w == VK_ESCAPE) {
            if (g_fullscreen) set_fullscreen(0); /* Escape leaves fullscreen first (Q-O3) */
            else { g_open = 0; PostQuitMessage(0); }
        } else if (w == VK_F11) set_fullscreen(!g_fullscreen);
        return 0;
    case WM_SYSKEYDOWN:
        if (w == VK_RETURN && (l & (1 << 29))) { /* Alt+Enter; window_pad keeps it from pressing START */
            set_fullscreen(!g_fullscreen);
            return 0;
        }
        return DefWindowProc(h, m, w, l);
    case WM_APP_MENU:
        menu_toggle_ui();
        return 0;
    case WM_APP_FULLSCREEN:
        set_fullscreen(w == 2 ? !g_fullscreen : (int)w);
        return 0;
    case WM_SIZE:
        g_client_w = LOWORD(l);
        g_client_h = HIWORD(l);
        g_resized = 1;
        if (!g_dxgi) InvalidateRect(h, NULL, FALSE);
        return 0;
    case WM_MOVE:
        /* H17c-b: moved to another monitor, perhaps at another rate */
        if (g_pace_ready && gxr_interp_display() && MonitorFromWindow(h, MONITOR_DEFAULTTONEAREST) != g_monitor) {
            double hz;
            g_refresh_ms = refresh_ms();
            hz = g_refresh_ms > 0.0 ? 1000.0 / g_refresh_ms : 60.0;
            interp_pace(hz);
        }
        return 0;
    case WM_DPICHANGED: {
        const RECT* r = (const RECT*)l;
        SetWindowPos(h, NULL, r->left, r->top, r->right - r->left, r->bottom - r->top, SWP_NOZORDER | SWP_NOACTIVATE);
        return 0;
    }
    case WM_MOUSEMOVE:
        g_mouse_at = GetTickCount64();
        return 0;
    case WM_SETCURSOR:
        if (LOWORD(l) == HTCLIENT && cursor_hidden()) {
            SetCursor(NULL);
            return TRUE;
        }
        return DefWindowProc(h, m, w, l);
    case WM_TIMER:
        if (cursor_hidden()) {
            POINT p;
            if (GetCursorPos(&p) && WindowFromPoint(p) == h) SetCursor(NULL);
        }
        return 0;
    case WM_DISPLAYCHANGE: {
        double hz;
        g_refresh_ms = refresh_ms();
        hz = g_refresh_ms > 0.0 ? 1000.0 / g_refresh_ms : 60.0;
        g_interval = present_interval(hz, 30);
        interp_pace(hz);
        fprintf(stderr, "[window] the display changed: %.1f Hz, each frame held %u refresh(es)\n", hz, g_interval);
        return DefWindowProc(h, m, w, l);
    }
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(h, &ps);
        if (g_dxgi || g_vk) {
            /* the swap chain owns the client area; GDI must not draw over it */
        } else if (!(g_bgra && g_shown_w)) {
            /* Nothing rasterized yet (or SOA_RENDER unset, so nothing ever
             * will be): the class has no background brush and WM_ERASEBKGND
             * is refused, so without this the client area shows whatever was
             * behind the window. The startup line promises blank; make it so. */
            RECT rc;
            GetClientRect(h, &rc);
            FillRect(dc, &rc, (HBRUSH)GetStockObject(BLACK_BRUSH));
        } else {
            BITMAPINFO bi;
            RECT rc;
            GetClientRect(h, &rc);
            memset(&bi, 0, sizeof bi);
            bi.bmiHeader.biSize = sizeof bi.bmiHeader;
            bi.bmiHeader.biWidth = g_shown_w;
            bi.bmiHeader.biHeight = -g_shown_h; /* top-down */
            bi.bmiHeader.biPlanes = 1;
            bi.bmiHeader.biBitCount = 32;
            bi.bmiHeader.biCompression = BI_RGB;
            {
                /* the same rectangle the DXGI path uses, and the bars round it */
                PicRect r = picture_layout(g_shown_w, g_shown_h, rc.right, rc.bottom, g_scaler);
                RECT bar;
                HBRUSH black = (HBRUSH)GetStockObject(BLACK_BRUSH);
                SetRect(&bar, 0, 0, rc.right, r.y); FillRect(dc, &bar, black);
                SetRect(&bar, 0, r.y + r.h, rc.right, rc.bottom); FillRect(dc, &bar, black);
                SetRect(&bar, 0, r.y, r.x, r.y + r.h); FillRect(dc, &bar, black);
                SetRect(&bar, r.x + r.w, r.y, rc.right, r.y + r.h); FillRect(dc, &bar, black);
                SetStretchBltMode(dc, COLORONCOLOR);
                if (menu_is_open() && rc.right > 0 && rc.bottom > 0) {
                    /* M8: the picture scaled into a client-sized copy, the menu over that, drawn 1:1 */
                    static uint8_t* buf;
                    static size_t cap;
                    size_t need = (size_t)rc.right * (size_t)rc.bottom * 4;
                    if (need > cap) {
                        free(buf);
                        buf = (uint8_t*)malloc(need);
                        cap = buf ? need : 0;
                    }
                    if (buf) {
                        picture_scale(g_bgra, g_shown_w, g_shown_h, buf, rc.right, rc.bottom, g_scaler);
                        menu_draw(buf, rc.right, rc.bottom, rc.right * 4);
                        bi.bmiHeader.biWidth = rc.right;
                        bi.bmiHeader.biHeight = -rc.bottom;
                        if (!StretchDIBits(dc, 0, 0, rc.right, rc.bottom, 0, 0, rc.right, rc.bottom, buf, &bi,
                                           DIB_RGB_COLORS, SRCCOPY))
                            g_present_failed++;
                    }
                } else if (!StretchDIBits(dc, r.x, r.y, r.w, r.h, 0, 0, g_shown_w, g_shown_h, g_bgra, &bi, DIB_RGB_COLORS, SRCCOPY))
                    g_present_failed++;
            }
            note_present();
        }
        EndPaint(h, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        return 1;
    default:
        return DefWindowProc(h, m, w, l);
    }
}

/* The renderer's newest frame into g_bgra and through P5a's filters, timed
 * at the display's clock so the flash limiter counts seconds as shown; the
 * answer is the limiter's blend, 1 where it held nothing back. */
static double filter_image(LARGE_INTEGER t0, const uint8_t* src, int w, int h)
{
    int x, y;
    double a = 1.0;
    if (!g_bgra) g_bgra = (uint8_t*)malloc((size_t)EFB_W * EFB_H * 4);
    for (y = 0; y < h; y++) {
        const uint8_t* s = src + (size_t)y * EFB_W * 4;
        uint8_t* d = g_bgra + (size_t)y * w * 4;
        for (x = 0; x < w; x++) { d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; d[3] = 255; s += 4; d += 4; }
    }
    if (g_filters) {
        static unsigned logged;
        a = picture_filter(g_filters, g_bgra, w, h, (double)t0.QuadPart / (double)g_qpf.QuadPart);
        if (a < 1.0 && logged++ < 20)
            fprintf(stderr, "[picture] frame %ld: held back from a flash, shown %.0f%% of the way%s\n", gxr_presented(),
                    100.0 * a, logged == 20 ? " (the last of these lines)" : "");
    }
    g_shown_w = w; g_shown_h = h;
    return a;
}

static double filter_on_cpu(LARGE_INTEGER t0)
{
    int w, h;
    const uint8_t* src = g_ring_on ? g_frame.real : gxr_screen(&w, &h);
    if (g_ring_on) { w = g_frame.w; h = g_frame.h; }
    return filter_image(t0, src, w, h);
}

/* H17d (D-45's visible fallback): what smooth motion is doing, told to the
 * player in a notice when it changes -- shown, refused and why, paused over
 * budget, back -- and logged, so a machine that cannot keep up says so. */
static void interp_tell(void)
{
    static int was = -1;
    int now;
    char line[120];
    if (!gxr_interp() || !g_pace_ready) return;
    now = g_interp_off ? 2 : gxr_interp_running() ? 1 : 0;
    if (now == was) return;
    if (now == 2) snprintf(line, sizeof line, "Smooth motion off: %s", g_interp_tell);
    else if (now == 0) snprintf(line, sizeof line, "Smooth motion paused: the game is running behind");
    else if (was == 0) snprintf(line, sizeof line, "Smooth motion on again");
    else if (g_interp_hz) snprintf(line, sizeof line, "Smooth motion: %u images a second, the display's rate", g_interp_hz);
    else snprintf(line, sizeof line, "Smooth motion: 60 images a second");
    menu_notice(line, 4000);
    fprintf(stderr, "[notice] %s\n", line);
    was = now;
}

/* H17c-b: the refresh of the monitor the window is on, as its display mode
 * gives it (DWM's timing is the primary display's), rounded as RT64 rounds
 * it; 0 when it cannot be read. */
static unsigned monitor_hz(void)
{
    MONITORINFOEXW mi;
    DEVMODEW dm;
    HMONITOR m = MonitorFromWindow(g_hwnd, MONITOR_DEFAULTTONEAREST);
    g_monitor = m;
    memset(&mi, 0, sizeof mi);
    mi.cbSize = sizeof mi;
    memset(&dm, 0, sizeof dm);
    dm.dmSize = sizeof dm;
    if (!m || !GetMonitorInfoW(m, (MONITORINFO*)&mi) || !EnumDisplaySettingsW(mi.szDevice, ENUM_CURRENT_SETTINGS, &dm) ||
        dm.dmDisplayFrequency < 2)
        return 0;
    return interp_rate_round((double)dm.dmDisplayFrequency);
}

/* H17b: whether in-between images are shown -- DXGI's presenter, frames from
 * the ring, the display at a whole multiple of 60 Hz, turbo off -- and the
 * producer told, so it builds none that nobody would see. Said when it
 * changes. */
static void interp_pace(double hz)
{
    static int said = -1;
    const char* why = NULL;
    unsigned n = present_interp(hz);
    if (!gxr_interp()) return;
    if (gxr_interp_display() && g_vk) {
        /* H17c-b: at the display's own rate, the monitor's the window is on,
         * one image a refresh, each frame given its images by the producer */
        unsigned rate = monitor_hz();
        if (!rate) rate = interp_rate_round(hz);
        if (g_turbo_shown) why = "turbo is on, which shows 60 real frames a second instead";
        else if (rate < INTERP_RATE_MIN) why = "the display refreshes under 30 times a second";
        gxr_interp_rate(why ? 0u : rate);
        gxv_present_display(why ? 0u : rate);
        g_mid_ivl = why ? 0 : 1;
        gxv_present_interp(g_mid_ivl);
        gxr_interp_show(!why);
        if (!why) g_interval = 1;
        g_interp_off = why != NULL;
        g_interp_hz = rate;
        snprintf(g_interp_tell, sizeof g_interp_tell, "%s",
                 g_turbo_shown ? "turbo is on" : "the display refreshes under 30 times a second");
        if (said != (int)(why ? 0 : rate)) {
            said = (int)(why ? 0 : rate);
            if (!why)
                fprintf(stderr, "[interp] in-between images at the display's own rate, %u Hz, one image a refresh (H17c-b); "
                                "the newest frame reaches the screen up to a frame later than without\n", rate);
            else
                fprintf(stderr, "[interp] in-between images not shown, so none is built: %s (%u Hz)\n", why, rate);
        }
        return;
    }
    if (gxr_interp_display()) {
        static int told;
        if (!told++)
            fprintf(stderr, "[interp] SOA_INTERP=display needs the GPU's presenter; one in-between image at 60, 120, 180 "
                            "or 240 Hz, as SOA_INTERP=1\n");
    }
    /* a check's knob: shown at any rate, one refresh an image, so the path runs on a display that
     * cannot pace it evenly (85 Hz); never for play */
    if (!n && getenv("SOA_INTERP_ANYRATE") && atoi(getenv("SOA_INTERP_ANYRATE"))) n = 1;
    if (!g_vk && (!g_ring_on || !g_dxgi)) why = "the presenter is neither DXGI's flip model nor the GPU's";
    else if (!n) why = "the display is not at a whole multiple of 60 Hz";
    else if (g_turbo_shown) why = "turbo is on, which shows 60 real frames a second instead";
    g_mid_ivl = why ? 0 : n;
    g_interp_off = why != NULL;
    g_interp_hz = 0;
    if (!g_vk && (!g_ring_on || !g_dxgi))
        snprintf(g_interp_tell, sizeof g_interp_tell, "this presenter cannot pace them");
    else if (!n)
        snprintf(g_interp_tell, sizeof g_interp_tell, "the display is at %.0f Hz; interp = display serves any rate", hz);
    else
        snprintf(g_interp_tell, sizeof g_interp_tell, "turbo is on");
    if (g_vk) gxv_present_interp(g_mid_ivl); /* V12b: the GPU's presenter shows them */
    gxr_interp_show(g_mid_ivl != 0);
    if (g_mid_ivl) g_interval = g_mid_ivl;
    if (said != (int)g_mid_ivl) {
        said = (int)g_mid_ivl;
        if (g_mid_ivl)
            fprintf(stderr, "[interp] in-between images shown at %.1f Hz, each image held %u refresh(es); every real frame "
                            "a 60 Hz refresh later than without\n", hz, g_mid_ivl);
        else
            fprintf(stderr, "[interp] in-between images not shown, so none is built: %s (%.1f Hz)\n", why, hz);
    }
}

/* The frame on screen: a new one from the renderer (`fresh`), converted and
 * through P5a's filters, or the one already shown, again at a new client
 * size -- which the flash limiter must not see twice. */
static void present(int fresh)
{
    LARGE_INTEGER t0;
    QueryPerformanceCounter(&t0);
    g_pw_t0 = t0.QuadPart;
    if (g_vk) {
        /* The GPU's own picture (V8), through P5a's filters on the GPU at
         * the size it was drawn (V8b). The CPU filters the native picture
         * only for the flash limiter, whose blend the GPU then applies. */
        int w = 0, h = 0;
        double a = fresh && g_flash ? filter_on_cpu(t0) : 1.0;
        if (gxv_present(fresh, g_interval, g_scaler, a, &w, &h)) {
            g_shown_w = w;
            g_shown_h = h;
            note_present_work();
            note_present();
        }
        return;
    }
    if (fresh && g_ring_on && g_mid_ivl && g_dxgi) {
        /* H17b: the image between the frame before and this one, for one 60 Hz
         * refresh, unless the frame is a cut or had none; then the frame. With
         * a frame latency of one, the second present waits for the first. */
        if (g_frame.mid && !g_frame.cut) {
            filter_image(t0, g_frame.mid, g_frame.w, g_frame.h);
            dxgi_present(g_shown_w, g_shown_h);
            plat_inc32(&g_shown_mid);
            QueryPerformanceCounter(&t0);
            g_pw_t0 = t0.QuadPart;
        } else {
            plat_inc32(g_frame.cut ? &g_shown_cut : &g_shown_none);
        }
    }
    if (fresh || !g_shown_w) filter_on_cpu(t0);
    if (g_dxgi) dxgi_present(g_shown_w, g_shown_h);
    else {
        InvalidateRect(g_hwnd, NULL, FALSE);
        UpdateWindow(g_hwnd); /* the paint -- its scale -- inside the time taken, as DXGI's is */
        note_present_work();
    }
}

/* ---- M8: the menu (docs/specs/menu.md) ------------------------------------ */

static int g_menu_turbo; /* turbo as the menu shows it: a toggle lands at the next safe point */

/* What the menu asks of the window. */
static void menu_act(int act)
{
    if (act & MENU_ACT_FULLSCREEN) set_fullscreen(!g_fullscreen);
    if (act & MENU_ACT_TURBO) {
        tick_turbo_toggle(); /* applied at the safe point, when the game runs again */
        g_menu_turbo = !g_menu_turbo;
    }
    menu_set_state(g_fullscreen, g_menu_turbo);
    if (act & MENU_ACT_CLOSE) {
        clock_pause_for(CLOCK_PAUSE_MENU, 0);
        fprintf(stderr, "[menu] closed\n");
    }
    if (act & MENU_ACT_QUIT) PostMessageA(g_hwnd, WM_CLOSE, 0, 0);
    if (act & MENU_ACT_SAVE_NOW) savenow_request(); /* M7a: the next safe point decides */
    if ((act & (MENU_ACT_REDRAW | MENU_ACT_CLOSE | MENU_ACT_FULLSCREEN)) && g_shown_w) present(0);
}

static void menu_key(int key)
{
    menu_act(menu_input(key));
}

/* F1 or View+LS: the menu opened -- the game held under the menu's own
 * reason, and drawn again, since no frame will come while it is held -- or
 * closed. The Vulkan presenter blends it over its picture (M8b). */
static void menu_toggle_ui(void)
{
    if (menu_is_open()) {
        menu_key(MENU_TOGGLE);
        return;
    }
    if (!g_shown_w) return; /* nothing drawn yet to draw it over */
    g_menu_turbo = tick_turbo_now();
    menu_set_state(g_fullscreen, g_menu_turbo);
    menu_open();
    clock_pause_for(CLOCK_PAUSE_MENU, 1);
    fprintf(stderr, "[menu] open at frame %ld\n", gxr_presented());
    present(0);
}

/* The pad while the menu is open, read here, on the UI thread: the game is
 * held at its safe point and polls nothing. The d-pad or the left stick
 * moves, A enters, B goes back, LB and RB step an int by a tenth, View+LS
 * closes; a held direction repeats after 400 ms, every 110 ms. */
static void menu_pad(void)
{
    static const struct {
        WORD mask;
        int key;
    } k_map[] = {{XINPUT_GAMEPAD_DPAD_UP, MENU_UP},          {XINPUT_GAMEPAD_DPAD_DOWN, MENU_DOWN},
                 {XINPUT_GAMEPAD_DPAD_LEFT, MENU_LEFT},      {XINPUT_GAMEPAD_DPAD_RIGHT, MENU_RIGHT},
                 {XINPUT_GAMEPAD_LEFT_SHOULDER, MENU_BIG_LEFT}, {XINPUT_GAMEPAD_RIGHT_SHOULDER, MENU_BIG_RIGHT},
                 {XINPUT_GAMEPAD_A, MENU_OK},                {XINPUT_GAMEPAD_B, MENU_BACK}};
    static WORD last;
    static int fresh = 1, held = -1;
    static DWORD next;
    const WORD chord = XINPUT_GAMEPAD_BACK | XINPUT_GAMEPAD_LEFT_THUMB;
    XINPUT_STATE xs;
    WORD btn;
    DWORD now = GetTickCount();
    size_t i;
    if (!menu_is_open()) {
        fresh = 1;
        held = -1;
        return;
    }
    if (g_pad_slot < 0 || XInputGetState((DWORD)g_pad_slot, &xs) != ERROR_SUCCESS) return;
    btn = xs.Gamepad.wButtons;
    if (xs.Gamepad.sThumbLY > 16000) btn |= XINPUT_GAMEPAD_DPAD_UP;
    if (xs.Gamepad.sThumbLY < -16000) btn |= XINPUT_GAMEPAD_DPAD_DOWN;
    if (xs.Gamepad.sThumbLX < -16000) btn |= XINPUT_GAMEPAD_DPAD_LEFT;
    if (xs.Gamepad.sThumbLX > 16000) btn |= XINPUT_GAMEPAD_DPAD_RIGHT;
    if (fresh) { /* what opened it is still held: nothing until it is let go */
        fresh = 0;
        last = btn;
        return;
    }
    if ((btn & chord) == chord && (last & chord) != chord) {
        last = btn;
        menu_toggle_ui();
        return;
    }
    for (i = 0; i < sizeof k_map / sizeof k_map[0]; i++)
        if ((btn & k_map[i].mask) && !(last & k_map[i].mask)) {
            held = (int)i;
            next = now + 400;
            last = btn;
            menu_key(k_map[i].key);
            return;
        }
    if (held >= 0 && (btn & k_map[held].mask) && k_map[held].key <= MENU_BIG_RIGHT && (LONG)(now - next) >= 0) {
        next = now + 110;
        menu_key(k_map[held].key);
    }
    if (held >= 0 && !(btn & k_map[held].mask)) held = -1;
    last = btn;
}

/* The View+LS chord (CH1), from the guest thread: posted to this one. */
int window_menu_toggle(void)
{
    if (!g_open || !g_hwnd) return 0;
    PostMessageA(g_hwnd, WM_APP_MENU, 0, 0);
    return 1;
}

/* SOA_WINDOW_TEST's menu@F (M8's check): the menu opened over frame F, and
 * the game's picture (g_screen, whose hash the frame lines carry) and the
 * converted frame (g_bgra) hashed before and after a present with it open --
 * both must be unchanged, the menu drawn into the scaled copy alone -- the
 * presented buffer written as a BMP to look at, and the menu closed. */
static uint32_t fnv_bytes(const uint8_t* p, size_t n)
{
    uint32_t h = 2166136261u;
    size_t i;
    for (i = 0; i < n; i++) h = (h ^ p[i]) * 16777619u;
    return h;
}

static void menu_check(long frame)
{
    unsigned long long screen0, screen1;
    uint32_t frame0, frame1;
    size_t n = g_bgra ? (size_t)g_shown_w * (size_t)g_shown_h * 4 : 0; /* the GPU presenter converts none */
    char path[600];
    const char* dir = getenv("SOA_FRAMES_DIR");
    FILE* f;
    screen0 = gxr_screen_hash();
    frame0 = fnv_bytes(g_bgra, n);
    menu_toggle_ui();
    if (!menu_is_open()) {
        fprintf(stderr, "[window] frame %ld: the menu did not open\n", frame);
        return;
    }
    present(0);
    screen1 = gxr_screen_hash();
    frame1 = fnv_bytes(g_bgra, n);
    fprintf(stderr, "[window] frame %ld: menu open; the game's picture %016llx before, %016llx after; the converted "
                    "frame %08x before, %08x after: %s\n", frame, screen0, screen1, frame0, frame1,
            screen0 == screen1 && frame0 == frame1 ? "unchanged" : "CHANGED");
    snprintf(path, sizeof path, "%s/menu-%ld.bmp", dir && *dir ? dir : "build", frame);
    if (g_dxgi && g_scaled && (f = fopen(path, "wb")) != NULL) {
        /* a 32-bit top-down BMP of the buffer the swap chain was given */
        uint8_t hdr[54] = {'B', 'M'};
        uint32_t size = 54u + (uint32_t)g_bw * (uint32_t)g_bh * 4u, v;
        int i;
        for (i = 0; i < 4; i++) hdr[2 + i] = (uint8_t)(size >> (8 * i));
        hdr[10] = 54;
        hdr[14] = 40;
        for (i = 0; i < 4; i++) hdr[18 + i] = (uint8_t)((uint32_t)g_bw >> (8 * i));
        v = (uint32_t)(-g_bh);
        for (i = 0; i < 4; i++) hdr[22 + i] = (uint8_t)(v >> (8 * i));
        hdr[26] = 1;
        hdr[28] = 32;
        fwrite(hdr, 1, sizeof hdr, f);
        fwrite(g_scaled, 1, (size_t)g_bw * (size_t)g_bh * 4, f);
        fclose(f);
        fprintf(stderr, "[window] frame %ld: the menu as presented, %dx%d: %s\n", frame, g_bw, g_bh, path);
    }
    menu_toggle_ui(); /* closed again: the game is held while it is open, and no later frame would come */
}

/* SOA_WINDOW_TEST=fs@300,win@600,size:1000x700@900 (H19a's check): at each
 * presented frame named, fullscreen, windowed or a client size, then one
 * [window] line with what came of it. Checked by tools/tests/test_picture.py. */
typedef struct { long frame; int kind, w, h; } WindowAct; /* kind 0 fs, 1 win, 2 size, 3 menu (M8) */
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
        else if (!strncmp(p, "menu@", 5)) { a.kind = 3; p += 5; }
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
    RECT cr, mon = monitor_rect(g_hwnd, 0);
    PicRect r;
    int sw = g_shown_w ? g_shown_w : 640, sh = g_shown_h ? g_shown_h : 480;
    GetClientRect(g_hwnd, &cr);
    r = picture_layout(sw, sh, cr.right, cr.bottom, g_scaler);
    fprintf(stderr, "[window] frame %ld: client %ldx%ld, image %dx%d at +%d+%d, from %dx%d, monitor %ldx%ld, mode %s %s\n",
            frame, cr.right, cr.bottom, r.w, r.h, r.x, r.y, sw, sh, mon.right - mon.left, mon.bottom - mon.top,
            g_scaler == PICTURE_FIT ? "fit" : "integer", g_fullscreen ? "fullscreen" : "window");
}

/* The client size a window of `scale` would need, as the window's outer size. */
static SIZE outer_size(int cw, int ch, UINT dpi)
{
    typedef BOOL(WINAPI * AdjustForDpi)(LPRECT, DWORD, BOOL, DWORD, UINT);
    AdjustForDpi adj = (AdjustForDpi)(void*)GetProcAddress(GetModuleHandleA("user32.dll"), "AdjustWindowRectExForDpi");
    RECT rc = {0, 0, cw, ch};
    SIZE s;
    if (adj) adj(&rc, WINDOW_STYLE, FALSE, 0, dpi);
    else AdjustWindowRect(&rc, WINDOW_STYLE, FALSE);
    s.cx = rc.right - rc.left;
    s.cy = rc.bottom - rc.top;
    return s;
}

static unsigned __stdcall ui_thread(void* arg)
{
    WNDCLASSA wc;
    MSG msg;
    long last = -1;
    SIZE outer;
    UINT dpi = 96;
    (void)arg;
    {
        /* Per-monitor DPI awareness, before any window: the client is then
         * physical pixels, which is what whole-pixel scaling needs. */
        typedef BOOL(WINAPI * SetCtx)(HANDLE);
        typedef UINT(WINAPI * GetDpi)(void);
        HMODULE u = GetModuleHandleA("user32.dll");
        SetCtx set = (SetCtx)(void*)GetProcAddress(u, "SetProcessDpiAwarenessContext");
        GetDpi get = (GetDpi)(void*)GetProcAddress(u, "GetDpiForSystem");
        if (!set || !set((HANDLE)-4 /* DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 */)) SetProcessDPIAware();
        if (get) dpi = get();
    }
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = wndproc;
    wc.hInstance = GetModuleHandle(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.lpszClassName = "SoaWindow";
    RegisterClassA(&wc);
    if (!g_scale) {
        /* The largest whole multiple of 640x480 whose window fits the work area. */
        MONITORINFO mi;
        RECT work = {0, 0, 1280, 1024};
        memset(&mi, 0, sizeof mi);
        mi.cbSize = sizeof mi;
        {
            POINT o = {0, 0};
            if (GetMonitorInfoA(MonitorFromPoint(o, MONITOR_DEFAULTTOPRIMARY), &mi)) work = mi.rcWork;
        }
        for (g_scale = 1; g_scale < 16; g_scale++) {
            SIZE s = outer_size(640 * (g_scale + 1), 480 * (g_scale + 1), dpi);
            if (s.cx > work.right - work.left || s.cy > work.bottom - work.top) break;
        }
    }
    outer = outer_size(640 * g_scale, 480 * g_scale, dpi);
    g_hwnd = CreateWindowA("SoaWindow", "Skies of Arcadia Legends -- native", WINDOW_STYLE, CW_USEDEFAULT, CW_USEDEFAULT,
                           outer.cx, outer.cy, NULL, NULL, wc.hInstance, NULL);
    if (!g_hwnd) {
        /* The watchdog stood down because this window was coming; without
         * either, nothing would ever end the run. */
        fprintf(stderr, "[window] CreateWindow failed; the run continues headless\n");
        g_open = 0;
        watchdog_fallback();
        return 0;
    }
    ShowWindow(g_hwnd, SW_SHOW);
    SetTimer(g_hwnd, 1, 500, NULL);
    g_mouse_at = GetTickCount64();
    QueryPerformanceFrequency(&g_qpf);
    {
        const char* p = getenv("SOA_PRESENTER");
        const char* fs = getenv("SOA_FULLSCREEN");
        const char* sc = getenv("SOA_SCALER");
        const char* uf = getenv("SOA_UNFOCUSED");
        if (uf && !strcmp(uf, "mute")) g_unfocused_mute = 1;
        else if (uf && !strcmp(uf, "pause")) g_unfocused_pause = 1;
        else if (uf && *uf && strcmp(uf, "run"))
            fprintf(stderr, "[window] SOA_UNFOCUSED=%s is not run, mute or pause; run\n", uf);
        RECT cr;
        DEVMODEA dm;
        double hz;
        GetClientRect(g_hwnd, &cr);
        memset(&dm, 0, sizeof dm);
        dm.dmSize = sizeof dm;
        g_refresh_ms = refresh_ms();
        hz = g_refresh_ms > 0.0 ? 1000.0 / g_refresh_ms : 60.0;
        /* A 30-a-second frame is held for a whole number of refreshes only
         * when the display's rate is a multiple of 30: two at 60 Hz, four at
         * 120. Anything else takes the next refresh, and H9 is the answer. */
        g_interval = present_interval(hz, 30);
        if (sc && !strcmp(sc, "fit")) g_scaler = PICTURE_FIT;
        else if (sc && *sc && strcmp(sc, "integer"))
            fprintf(stderr, "[window] SOA_SCALER=%s is not integer or fit; integer\n", sc);
        {
            PicFilters pf;
            char why[160];
            if (!picture_filters_parse(&pf, getenv("SOA_GAMMA"), getenv("SOA_COLORBLIND"), getenv("SOA_COLORBLIND_MODE"),
                                       getenv("SOA_FLASH_LIMIT"), why, sizeof why))
                fprintf(stderr, "[picture] %s\n", why);
            if (picture_filters_any(&pf) && (g_filters = picture_filters_new(&pf)) != NULL) {
                picture_filters_name(&pf, why, sizeof why);
                fprintf(stderr, "[picture] %s\n", why);
                g_flash = pf.flash_limit;
            }
        }
        /* With the GPU drawing, the GPU presents (V8), unless SOA_PRESENTER
         * names another, and P5a's filters run on the GPU at the size it drew
         * (V8b): where their pass cannot be made, DXGI presents and the CPU
         * filters, rather than the window losing them. */
        if (gxv_running() && !(p && (!strcmp(p, "gdi") || !strcmp(p, "dxgi")))) {
            char why[256];
            PicTables tables;
            if (g_filters) picture_filter_tables(g_filters, &tables);
            if (g_filters && !gxv_present_filters(&tables))
                fprintf(stderr, "[window] the GPU's filter pass could not be made; presenting with DXGI\n");
            else if (gxv_present_open(GetModuleHandle(NULL), g_hwnd, cr.right, cr.bottom, why, sizeof why))
            {
                g_vk = 1;
                gxv_present_overlay(menu_draw_overlay); /* M8b: the menu blended over the GPU's picture */
                if ((g_fresh_ev = CreateEventW(NULL, FALSE, FALSE, NULL)) != NULL) gxv_on_publish(fresh_signal);
            } else
                fprintf(stderr, "[window] the GPU presenter could not start: %s; presenting with DXGI\n", why);
        }
        if (!g_vk && !(p && !strcmp(p, "gdi"))) {
            g_dxgi = dxgi_start(g_hwnd, cr.right, cr.bottom);
            if (!g_dxgi) fprintf(stderr, "[window] the DXGI presenter could not start; presenting with GDI\n");
        }
        hle_on_report(present_report);
        g_pace_ready = 1;
        interp_pace(hz);
        fprintf(stderr, "[window] the display refreshes every %.2f ms (%.1f Hz; the mode says %lu Hz)%s\n",
                g_refresh_ms, hz, EnumDisplaySettingsA(NULL, ENUM_CURRENT_SETTINGS, &dm) ? dm.dmDisplayFrequency : 0ul,
                g_interval == 1 ? ", not a multiple of 30: each frame takes the next refresh" : "");
        if (fs && atoi(fs)) set_fullscreen(1);
    }
    window_test_parse();
    g_open = 1;
    si_set_motor_sink(motor);
    si_set_motor_window(1);
    if (g_vk)
        fprintf(stderr, "[window] open at %dx, presenting from the GPU with a Vulkan swap chain, each frame held %u "
                        "refresh(es)\n", g_scale, g_interval);
    else if (g_dxgi)
        fprintf(stderr, "[window] open at %dx, presenting with a DXGI flip-model swap chain, each frame held %u "
                        "refresh(es)\n", g_scale, g_interval);
    else
        fprintf(stderr, "[window] open at %dx, presenting with GDI on an 8 ms poll\n", g_scale);
    for (;;) {
        long now;
        int logged_resize = 0;
        while (PeekMessage(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) {
                g_open = 0;
                si_set_motor_window(0);
                si_motor_stop();
                fprintf(stderr, "[window] closed\n");
                hle_report();
                /* Closing the window is how a recording session ends, and
                 * _exit() does not flush stdio: without this the last of what
                 * the player did would be lost in a buffer. gx.c's frame-limit
                 * path does the same thing for the same reason. */
                fflush(NULL);
                _exit(0);
            }
            TranslateMessage(&msg);
            DispatchMessage(&msg);
        }
        now = gxr_presented();
        if (tick_turbo_now() != g_turbo_shown) {
            /* At turbo the game makes up to 60 images a second, and holding each
             * for two refreshes at 60 Hz would show only 30 of them (M11a). */
            double hz = g_refresh_ms > 0.0 ? 1000.0 / g_refresh_ms : 60.0;
            g_turbo_shown = tick_turbo_now();
            g_interval = present_interval(hz, g_turbo_shown ? 60 : 30);
            interp_pace(hz);
            fprintf(stderr, "[window] frame %ld: turbo %s, each frame held %u refresh(es)\n", now,
                    g_turbo_shown ? "on" : "off", g_interval);
        }
        if (g_act_i < g_act_n && now >= g_acts[g_act_i].frame) {
            const WindowAct* a = &g_acts[g_act_i++];
            if (a->kind == 3) {
                menu_check(now);
                continue;
            }
            if (a->kind == 0) set_fullscreen(1);
            else if (a->kind == 1) set_fullscreen(0);
            else {
                SIZE s;
                set_fullscreen(0);
                s = outer_size(a->w, a->h, dpi);
                SetWindowPos(g_hwnd, NULL, 0, 0, s.cx, s.cy, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
            }
            while (PeekMessage(&msg, NULL, 0, 0, PM_REMOVE)) { /* the size messages the switch sent */
                TranslateMessage(&msg);
                DispatchMessage(&msg);
            }
            logged_resize = 1;
        }
        if (g_resized) {
            g_resized = 0;
            if (g_client_w > 0 && g_client_h > 0) { /* minimised is 0x0: no resize, no present */
                if (g_dxgi) dxgi_resize(g_client_w, g_client_h);
                if (g_vk) gxv_present_resize(g_client_w, g_client_h);
                if (g_shown_w) present(0); /* the last frame again, at the new size */
            }
        }
        if (logged_resize) window_line(now);
        if (g_ring_on) {
            if (gxr_ring_take(&g_frame)) present(1);
        } else if (g_vk) {
            /* the GPU's slot, not the count: with in-between images the count
             * rises at the real copy, a copy before the slot is published, and
             * a present between the two showed the frame before again while
             * the new one waited, or was replaced unseen (5% of frames) */
            if (gxv_screen_fresh()) present(1);
        } else if (now != last) {
            last = now;
            present(1);
        }
        menu_pad();
        interp_tell();
        /* woken by input, by the GPU publishing a frame (H17c-b: one found at
         * the next poll could be a timer tick late), or after 8 ms */
        MsgWaitForMultipleObjects(g_fresh_ev ? 1u : 0u, g_fresh_ev ? &g_fresh_ev : NULL, FALSE, 8, QS_ALLINPUT);
    }
}

void window_start(void)
{
    const char* env = getenv("SOA_SCALE");
    uintptr_t h;
    if (env && atoi(env) > 0) g_scale = atoi(env);
    /* The CPU renderer's frames through the screen ring (H17b, B1), taken
     * before the first command; the GPU's presenter has its own. */
    if (!gxv_running()) {
        gxr_ring_enable();
        g_ring_on = 1;
    }
    h = _beginthreadex(NULL, 0, ui_thread, NULL, 0, NULL);
    if (!h) {
        /* Same hole as a failed CreateWindow, one step earlier: the watchdog
         * stood down for a window that is not coming. */
        fprintf(stderr, "[window] cannot start the UI thread; the run continues headless\n");
        watchdog_fallback();
        return;
    }
    CloseHandle((HANDLE)h);
}

int window_open(void)
{
    return g_open;
}

/* The View+LB chord (CH1): fullscreen on or off, posted to the UI thread that
 * owns the window. 0 with no window to switch. */
int window_toggle_fullscreen(void)
{
    if (!g_open || !g_hwnd) return 0;
    PostMessageA(g_hwnd, WM_APP_FULLSCREEN, 2, 0);
    return 1;
}

/* Controller state for port 1 from the keyboard (when the window has the
 * focus) and gamepad 0. Returns 0 when there is no window.
 *
 * The two halves treat focus differently on purpose and it shows up in a
 * recording: the keyboard is read only while the window is in front, so
 * alt-tabbing releases every key, while the gamepad is read whatever has the
 * focus and keeps driving the game. A recording is faithful to both -- it
 * writes down what the port returned -- but a keyboard session interrupted
 * by another window records the neutral input the guest really saw. */
static ULONGLONG g_pad_probe_at;
static WORD g_pad_xbuttons; /* the last XInput buttons window_pad read, for window_host */

/* One XInput pad in the game's terms, for port 1 and port 2 alike: the
 * buttons as si.c packs them, a stick only past its dead zone, a trigger only
 * past its threshold. The sticks and triggers are left as they are otherwise
 * (the keyboard's, or centre). Pad 2 once passed its sticks raw -- a resting
 * stick's drift reached the game when couch co-op handed it pad 2 (P10b). */
static uint16_t map_xinput(const XINPUT_GAMEPAD* g, int* sx, int* sy, int* cx, int* cy, int* lt, int* rt)
{
    uint16_t b = 0;
    if (g->wButtons & XINPUT_GAMEPAD_A) b |= 0x0100;
    if (g->wButtons & XINPUT_GAMEPAD_B) b |= 0x0200;
    if (g->wButtons & XINPUT_GAMEPAD_X) b |= 0x0400;
    if (g->wButtons & XINPUT_GAMEPAD_Y) b |= 0x0800;
    if (g->wButtons & XINPUT_GAMEPAD_START) b |= 0x1000;
    if (g->wButtons & XINPUT_GAMEPAD_RIGHT_SHOULDER) b |= 0x0010;
    if (g->wButtons & XINPUT_GAMEPAD_DPAD_UP) b |= 0x0008;
    if (g->wButtons & XINPUT_GAMEPAD_DPAD_DOWN) b |= 0x0004;
    if (g->wButtons & XINPUT_GAMEPAD_DPAD_LEFT) b |= 0x0001;
    if (g->wButtons & XINPUT_GAMEPAD_DPAD_RIGHT) b |= 0x0002;
    if (g->bLeftTrigger > 30) { b |= 0x0040; *lt = g->bLeftTrigger; }
    if (g->bRightTrigger > 30) { b |= 0x0020; *rt = g->bRightTrigger; }
    if (abs(g->sThumbLX) > 7849 || abs(g->sThumbLY) > 7849) { *sx = 128 + g->sThumbLX / 258; *sy = 128 + g->sThumbLY / 258; }
    if (abs(g->sThumbRX) > 8689 || abs(g->sThumbRY) > 8689) { *cx = 128 + g->sThumbRX / 258; *cy = 128 + g->sThumbRY / 258; }
    return b;
}

static uint8_t stick_byte(int v)
{
    return (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
}

int window_pad(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2])
{
    XINPUT_STATE xs;
    uint16_t b = 0;
    int sx = 128, sy = 128, cx = 128, cy = 128, lt = 0, rt = 0;
    if (!g_open) return 0;
    if (GetForegroundWindow() == g_hwnd) {
#define K(vk) (GetAsyncKeyState(vk) & 0x8000)
        if (K('X')) b |= 0x0100; /* A */
        if (K('Z')) b |= 0x0200; /* B */
        if (K('C')) b |= 0x0400; /* X */
        if (K('V')) b |= 0x0800; /* Y */
        if ((K(VK_RETURN) && !K(VK_MENU)) || K(VK_SPACE)) b |= 0x1000; /* START; Alt+Enter is fullscreen */
        if (K('R')) b |= 0x0010; /* Z */
        if (K('Q')) { b |= 0x0040; lt = 255; }
        if (K('E')) { b |= 0x0020; rt = 255; }
        if (K('T')) b |= 0x0008; if (K('G')) b |= 0x0004; if (K('F')) b |= 0x0001; if (K('H')) b |= 0x0002;
        if (K(VK_LEFT) || K('A')) sx = 0;
        if (K(VK_RIGHT) || K('D')) sx = 255;
        if (K(VK_UP) || K('W')) sy = 255;
        if (K(VK_DOWN) || K('S')) sy = 0;
        if (K('J')) cx = 0; if (K('L')) cx = 255; if (K('I')) cy = 255; if (K('K')) cy = 0;
#undef K
    }
    /* XInputGetState on a port with nothing in it is a slow call: it goes out
     * to the driver and comes back ERROR_DEVICE_NOT_CONNECTED. This runs on
     * the guest thread at least twice per frame, so with no gamepad plugged
     * in the port would be paying for the absence on the one thread whose
     * rate decides how many frames a second of play takes -- which is the
     * coordinate a recording is keyed by. Ask once a second while nothing is
     * there; a pad plugged in mid-session is picked up within a second of
     * plugging it in. The statics are safe unlocked because every caller of
     * window_pad is si.c on the guest thread. */
    /* Port 1 follows the pad (CH1, the M8 amendment): the first connected
     * slot of the four, found by probing all of them once a second while
     * none is, and kept until it goes -- so a pad Windows put in slot 1 or 2
     * still plays. */
    memset(&xs, 0, sizeof xs);
    if (g_pad_slot >= 0 && XInputGetState((DWORD)g_pad_slot, &xs) != ERROR_SUCCESS) {
        g_pad_slot = -1;
        g_pad_probe_at = GetTickCount64() + 1000;
        memset(&xs, 0, sizeof xs);
    }
    if (g_pad_slot < 0 && GetTickCount64() >= g_pad_probe_at) {
        DWORD slot;
        for (slot = 0; slot < XUSER_MAX_COUNT && g_pad_slot < 0; slot++)
            if (XInputGetState(slot, &xs) == ERROR_SUCCESS) g_pad_slot = (int)slot;
        if (g_pad_slot < 0) {
            g_pad_probe_at = GetTickCount64() + 1000;
            memset(&xs, 0, sizeof xs);
        }
    }
    if (g_unfocused_mute && g_away) memset(&xs, 0, sizeof xs); /* unfocused = mute: the pad is not read */
    g_pad_xbuttons = g_pad_slot >= 0 && !(g_unfocused_mute && g_away) ? xs.Gamepad.wButtons : 0;
    if (g_pad_slot >= 0 && !(g_unfocused_mute && g_away)) b |= map_xinput(&xs.Gamepad, &sx, &sy, &cx, &cy, &lt, &rt);
    *buttons = b;
    stick[0] = stick_byte(sx);
    stick[1] = stick_byte(sy);
    cstick[0] = stick_byte(cx);
    cstick[1] = stick_byte(cy);
    trig[0] = (uint8_t)lt;
    trig[1] = (uint8_t)rt;
    return 1;
}

/* Port 2 (P10a): the next connected XInput pad after port 1's, probed once a
 * second while there is none, and kept until it goes -- read for mods only
 * (si.c's si_read_pad), never shown to the game by the port itself. Mapped
 * as port 1 is (map_xinput), and like port 1 read as let go under
 * `unfocused = mute` while another window is in front -- still connected, so
 * a co-op mod does not hand its turns to port 1. */
static int g_pad2_slot = -1;
static ULONGLONG g_pad2_probe_at;

int window_pad2(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2])
{
    XINPUT_STATE xs;
    uint16_t b = 0;
    int sx = 128, sy = 128, cx = 128, cy = 128, lt = 0, rt = 0;
    if (!g_open) return 0;
    memset(&xs, 0, sizeof xs);
    if (g_pad2_slot >= 0 && (g_pad2_slot == g_pad_slot || XInputGetState((DWORD)g_pad2_slot, &xs) != ERROR_SUCCESS)) {
        g_pad2_slot = -1;
        g_pad2_probe_at = GetTickCount64() + 1000;
    }
    if (g_pad2_slot < 0) {
        DWORD slot;
        if (GetTickCount64() < g_pad2_probe_at) return 0;
        for (slot = 0; slot < XUSER_MAX_COUNT && g_pad2_slot < 0; slot++)
            if ((int)slot != g_pad_slot && XInputGetState(slot, &xs) == ERROR_SUCCESS) g_pad2_slot = (int)slot;
        if (g_pad2_slot < 0) {
            g_pad2_probe_at = GetTickCount64() + 1000;
            return 0;
        }
    }
    if (!(g_unfocused_mute && g_away)) b = map_xinput(&xs.Gamepad, &sx, &sy, &cx, &cy, &lt, &rt);
    *buttons = b;
    stick[0] = stick_byte(sx);
    stick[1] = stick_byte(sy);
    cstick[0] = stick_byte(cx);
    cstick[1] = stick_byte(cy);
    trig[0] = (uint8_t)lt;
    trig[1] = (uint8_t)rt;
    return 1;
}

/* The host buttons (CH1): LB, View and the stick clicks of the pad port 1
 * follows, as window_pad last read it, and Tab as LB while the window has
 * the focus. None is mapped to a GameCube button, and si.c keeps them out
 * of the report: they are the port's and the mods', never the game's. */
int window_host(uint16_t* host)
{
    uint16_t h = 0;
    WORD x = g_pad_xbuttons;
    if (!g_open) return 0;
    if (x & XINPUT_GAMEPAD_LEFT_SHOULDER) h |= 0x1;
    if (x & XINPUT_GAMEPAD_BACK) h |= 0x2;
    if (x & XINPUT_GAMEPAD_LEFT_THUMB) h |= 0x4;
    if (x & XINPUT_GAMEPAD_RIGHT_THUMB) h |= 0x8;
    if (GetForegroundWindow() == g_hwnd && (GetAsyncKeyState(VK_TAB) & 0x8000)) h |= 0x1;
    *host = h;
    return 1;
}
#elif !defined(SOA_SDL) /* with SDL, window_sdl.c is the window (portability L10) */
#include <stdint.h>
void window_start(void) {}
int window_open(void) { return 0; }
int window_host(uint16_t* host) { (void)host; return 0; }
int window_toggle_fullscreen(void) { return 0; }
int window_menu_toggle(void) { return 0; }
int window_pad2(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2]) { (void)buttons; (void)stick; (void)cstick; (void)trig; return 0; }
int window_pad(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2]) { (void)buttons; (void)stick; (void)cstick; (void)trig; return 0; }
#endif
