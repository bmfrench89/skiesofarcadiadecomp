/*
 * The screen and the controller: a Win32 window on its own thread that
 * shows each frame the renderer copies out, and live input from the
 * keyboard or an XInput gamepad for controller port 1.
 *
 * Keyboard: arrows/WASD main stick, IJKL C-stick, X = A, Z = B, C = X,
 * V = Y, Enter/Space = START, R = Z, Q = L, E = R, T/F/G/H = D-pad,
 * Escape closes. Gamepad: the obvious mapping, triggers to L/R, RB to Z.
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
static int g_scale = 2;
static uint8_t* g_bgra; /* the frame converted for GDI */
static int g_shown_w, g_shown_h;

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

static void note_present(void)
{
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    if (g_pt_n == g_pt_cap) {
        size_t cap = g_pt_cap ? g_pt_cap * 2 : 4096;
        LONGLONG* p = (LONGLONG*)realloc(g_pt, cap * sizeof *g_pt);
        if (!p) return;
        g_pt = p;
        g_pt_cap = cap;
    }
    g_pt[g_pt_n++] = now.QuadPart;
    if (!g_drift_started) {
        g_host0 = now.QuadPart;
        g_guest0 = irq_retrace_count();
        g_drift_started = 1;
    }
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

/* The histogram, in refreshes of the display, and the drift. */
static void present_report(void)
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
            g_dxgi ? "dxgi flip model" : "gdi, 8 ms poll", n, period_ms, 1000.0 / period_ms, bins[0], bins[1],
            bins[2], bins[3], bins[4], 1000.0 * (double)d[n / 2] / (double)g_qpf.QuadPart,
            1000.0 * (double)d[(n * 99) / 100] / (double)g_qpf.QuadPart);
    free(d);
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

/* g_bgra (the frame, w x h) scaled by whole pixels into the back buffer and
 * presented, held for two refreshes. */
static void dxgi_present(int w, int h)
{
    ID3D11Texture2D* bb = NULL;
    int y, x, sx = g_bw / w, sy = g_bh / h;
    if (sx < 1) sx = 1;
    if (sy < 1) sy = 1;
    for (y = 0; y < g_bh; y++) {
        const uint32_t* src = (const uint32_t*)(g_bgra + (size_t)(y / sy < h ? y / sy : h - 1) * w * 4);
        uint32_t* dst = (uint32_t*)(g_scaled + (size_t)y * g_bw * 4);
        for (x = 0; x < g_bw; x++) dst[x] = src[x / sx < w ? x / sx : w - 1];
    }
    if (FAILED(IDXGISwapChain1_GetBuffer(g_sc, 0, &IID_ID3D11Texture2D, (void**)&bb)) || !bb) return;
    ID3D11DeviceContext_UpdateSubresource(g_ctx, (ID3D11Resource*)bb, 0, NULL, g_scaled, (UINT)g_bw * 4, 0);
    ID3D11Texture2D_Release(bb);
    IDXGISwapChain1_Present(g_sc, g_interval, 0);
    note_present();
}

static LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_CLOSE:
    case WM_DESTROY:
        g_open = 0;
        PostQuitMessage(0);
        return 0;
    case WM_KEYDOWN:
        if (w == VK_ESCAPE) { g_open = 0; PostQuitMessage(0); }
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(h, &ps);
        if (g_dxgi) {
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
            SetStretchBltMode(dc, COLORONCOLOR);
            StretchDIBits(dc, 0, 0, rc.right, rc.bottom, 0, 0, g_shown_w, g_shown_h, g_bgra, &bi, DIB_RGB_COLORS, SRCCOPY);
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

static void present(void)
{
    int w, h, x, y;
    const uint8_t* src = gxr_screen(&w, &h);
    if (!g_bgra) g_bgra = (uint8_t*)malloc((size_t)EFB_W * EFB_H * 4);
    for (y = 0; y < h; y++) {
        const uint8_t* s = src + (size_t)y * EFB_W * 4;
        uint8_t* d = g_bgra + (size_t)y * w * 4;
        for (x = 0; x < w; x++) { d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; d[3] = 255; s += 4; d += 4; }
    }
    g_shown_w = w; g_shown_h = h;
    if (g_dxgi) dxgi_present(w, h);
    else InvalidateRect(g_hwnd, NULL, FALSE);
}

static unsigned __stdcall ui_thread(void* arg)
{
    WNDCLASSA wc;
    RECT rc = {0, 0, 640 * g_scale, 480 * g_scale};
    MSG msg;
    long last = -1;
    (void)arg;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = wndproc;
    wc.hInstance = GetModuleHandle(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.lpszClassName = "SoaWindow";
    RegisterClassA(&wc);
    AdjustWindowRect(&rc, WS_OVERLAPPEDWINDOW & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX, FALSE);
    g_hwnd = CreateWindowA("SoaWindow", "Skies of Arcadia Legends -- native", WS_OVERLAPPEDWINDOW & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX,
                           CW_USEDEFAULT, CW_USEDEFAULT, rc.right - rc.left, rc.bottom - rc.top, NULL, NULL, wc.hInstance, NULL);
    if (!g_hwnd) {
        /* The watchdog stood down because this window was coming; without
         * either, nothing would ever end the run. */
        fprintf(stderr, "[window] CreateWindow failed; the run continues headless\n");
        g_open = 0;
        watchdog_fallback();
        return 0;
    }
    ShowWindow(g_hwnd, SW_SHOW);
    QueryPerformanceFrequency(&g_qpf);
    {
        const char* p = getenv("SOA_PRESENTER");
        RECT cr;
        GetClientRect(g_hwnd, &cr);
        DEVMODEA dm;
        double hz;
        memset(&dm, 0, sizeof dm);
        dm.dmSize = sizeof dm;
        g_refresh_ms = refresh_ms();
        hz = g_refresh_ms > 0.0 ? 1000.0 / g_refresh_ms : 60.0;
        /* A 30-a-second frame is held for a whole number of refreshes only
         * when the display's rate is a multiple of 30: two at 60 Hz, four at
         * 120. Anything else takes the next refresh, and H9 is the answer. */
        if (hz / 30.0 - (double)(int)(hz / 30.0 + 0.5) < 0.02 && hz / 30.0 - (double)(int)(hz / 30.0 + 0.5) > -0.02)
            g_interval = (UINT)(hz / 30.0 + 0.5);
        else
            g_interval = 1;
        if (g_interval < 1) g_interval = 1;
        if (g_interval > 4) g_interval = 4;
        if (!(p && !strcmp(p, "gdi"))) {
            g_dxgi = dxgi_start(g_hwnd, cr.right, cr.bottom);
            if (!g_dxgi) fprintf(stderr, "[window] the DXGI presenter could not start; presenting with GDI\n");
        }
        hle_on_report(present_report);
        fprintf(stderr, "[window] the display refreshes every %.2f ms (%.1f Hz; the mode says %lu Hz)%s\n",
                g_refresh_ms, hz, EnumDisplaySettingsA(NULL, ENUM_CURRENT_SETTINGS, &dm) ? dm.dmDisplayFrequency : 0ul,
                g_interval == 1 ? ", not a multiple of 30: each frame takes the next refresh" : "");
    }
    g_open = 1;
    if (g_dxgi)
        fprintf(stderr, "[window] open at %dx, presenting with a DXGI flip-model swap chain, each frame held %u "
                        "refresh(es)\n", g_scale, g_interval);
    else
        fprintf(stderr, "[window] open at %dx, presenting with GDI on an 8 ms poll\n", g_scale);
    for (;;) {
        long now;
        while (PeekMessage(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) {
                g_open = 0;
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
        if (now != last) { last = now; present(); }
        MsgWaitForMultipleObjects(0, NULL, FALSE, 8, QS_ALLINPUT);
    }
}

void window_start(void)
{
    const char* env = getenv("SOA_SCALE");
    uintptr_t h;
    if (env && atoi(env) > 0) g_scale = atoi(env);
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

/* Controller state for port 1 from the keyboard (when the window has the
 * focus) and gamepad 0. Returns 0 when there is no window.
 *
 * The two halves treat focus differently on purpose and it shows up in a
 * recording: the keyboard is read only while the window is in front, so
 * alt-tabbing releases every key, while the gamepad is read whatever has the
 * focus and keeps driving the game. A recording is faithful to both -- it
 * writes down what the port returned -- but a keyboard session interrupted
 * by another window records the neutral input the guest really saw. */
static int g_pad_present;
static ULONGLONG g_pad_probe_at;

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
        if (K(VK_RETURN) || K(VK_SPACE)) b |= 0x1000; /* START */
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
    memset(&xs, 0, sizeof xs);
    if (g_pad_present || GetTickCount64() >= g_pad_probe_at) {
        g_pad_present = XInputGetState(0, &xs) == ERROR_SUCCESS;
        if (!g_pad_present) g_pad_probe_at = GetTickCount64() + 1000;
    }
    if (g_pad_present) {
        const XINPUT_GAMEPAD* g = &xs.Gamepad;
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
        if (g->bLeftTrigger > 30) { b |= 0x0040; lt = g->bLeftTrigger; }
        if (g->bRightTrigger > 30) { b |= 0x0020; rt = g->bRightTrigger; }
        if (abs(g->sThumbLX) > 7849 || abs(g->sThumbLY) > 7849) { sx = 128 + g->sThumbLX / 258; sy = 128 + g->sThumbLY / 258; }
        if (abs(g->sThumbRX) > 8689 || abs(g->sThumbRY) > 8689) { cx = 128 + g->sThumbRX / 258; cy = 128 + g->sThumbRY / 258; }
    }
    *buttons = b;
    stick[0] = (uint8_t)(sx < 0 ? 0 : sx > 255 ? 255 : sx);
    stick[1] = (uint8_t)(sy < 0 ? 0 : sy > 255 ? 255 : sy);
    cstick[0] = (uint8_t)(cx < 0 ? 0 : cx > 255 ? 255 : cx);
    cstick[1] = (uint8_t)(cy < 0 ? 0 : cy > 255 ? 255 : cy);
    trig[0] = (uint8_t)lt;
    trig[1] = (uint8_t)rt;
    return 1;
}
#else
#include <stdint.h>
void window_start(void) {}
int window_open(void) { return 0; }
int window_pad(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2]) { (void)buttons; (void)stick; (void)cstick; (void)trig; return 0; }
#endif
