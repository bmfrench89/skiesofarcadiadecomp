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
#include "cpu.h"
#include "gxr.h"
#include <windows.h>
#include <xinput.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "xinput9_1_0.lib")

long gxr_presented(void);
void hle_report(void);
void watchdog_fallback(void);

static HWND g_hwnd;
static volatile int g_open;
static int g_scale = 2;
static uint8_t* g_bgra; /* the frame converted for GDI */
static int g_shown_w, g_shown_h;

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
        if (!(g_bgra && g_shown_w)) {
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
    InvalidateRect(g_hwnd, NULL, FALSE);
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
    g_open = 1;
    fprintf(stderr, "[window] open at %dx\n", g_scale); /* the keys and the quit key are in the startup line */
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
