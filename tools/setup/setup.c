/*
 * Setup.exe: the player's window (specs/distribution.md R4).
 *
 * It sits at the top of the package the player extracted and builds the game
 * into that same folder, from the player's own disc image:
 *
 *   - it checks the folder first (3.7): a path the port can use, write access,
 *     the space, not Program Files; and Smart App Control, which would block
 *     what the build makes;
 *   - the player picks the image, and Build runs
 *     python\python.exe source\tools\player_build.py with no console window,
 *     its [build] lines turned into the progress bar and every line into the
 *     log pane and build\setup.log;
 *   - Play starts soa.exe in that folder, again with no console window, and
 *     closes. In a folder already built, Setup offers Play and Rebuild.
 *
 * tools/package.py builds it with the package's own compiler, with
 * setup.rc's manifest (common controls 6, the system's DPI).
 *
 * Without a mouse: Setup.exe --disc <image> [--build] [--play] picks the
 * image, starts the build and plays when it is done; --check [--root <folder>]
 * exits with what the checks found for this folder or that one (CHECK_*), its
 * words on stdout, and opens no window.
 */
#ifndef UNICODE /* -municode defines both */
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <commdlg.h>
#include <shellapi.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

/* Past IDOK and IDCANCEL, which IsDialogMessage sends for Enter and Escape. */
enum { ID_CHOOSE = 101, ID_BUILD, ID_PLAY, ID_REBUILD };
/* What --check exits with; tools/tests/test_setup.py holds the same list. */
enum {
    CHECK_OK,
    CHECK_PATH,
    CHECK_PROGRAM_FILES,
    CHECK_WRITE,
    CHECK_SPACE,
    CHECK_SMART_APP_CONTROL,
    CHECK_FORMAT,
    CHECK_INCOMPLETE,
    CHECK_LONG
};
/* The longest path under the root, the package's or the build's, measured by
 * tools/package.py when it builds this (a libc++ header in toolchain/, 90
 * characters, on 2026-10-04): a root longer than MAX_PATH less this cannot
 * hold every file, as Explorer's extraction and the compiler both find. */
#ifndef SETUP_DEEPEST
#define SETUP_DEEPEST 100
#endif
/* What the build needs of the package, whose absence means it was not all
 * extracted: Setup.exe opened from inside the zip has only itself. */
static const wchar_t* const PACKAGE[] = {L"python\\python.exe", L"source\\tools\\player_build.py",
                                         L"toolchain\\bin\\x86_64-w64-mingw32-clang.exe"};
#define WM_BUILD_LINE (WM_APP + 1)
#define WM_BUILD_DONE (WM_APP + 2)
#define NEED_FREE (2ull << 30) /* the image's copy, gen/ and the build: about 1.6 GB (3.7) */
#define MSG_CAP 1024

/* python, the compiler and soa.exe are console programs; started with this,
 * none of them opens a console window. The mutation's 0 must be caught. */
#ifdef SETUP_MUTATE_CONSOLE
#define NO_CONSOLE 0
#else
#define NO_CONSOLE CREATE_NO_WINDOW
#endif

static HWND g_wnd, g_status, g_disc_edit, g_choose, g_build, g_play, g_rebuild, g_log, g_progress;
static wchar_t g_root[MAX_PATH], g_disc[MAX_PATH], g_refusal[MSG_CAP];
static int g_busy, g_blocked, g_auto_build, g_auto_play, g_dpi = 96;
static HANDLE g_job; /* the build's processes, ended with Setup */
static FILE* g_logf;

static void path_join(wchar_t* out, size_t cap, const wchar_t* a, const wchar_t* b)
{
    swprintf(out, cap, L"%ls\\%ls", a, b);
}

static int file_exists(const wchar_t* p)
{
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

static int built(void)
{
    wchar_t exe[MAX_PATH];
    path_join(exe, MAX_PATH, g_root, L"soa.exe");
    return file_exists(exe);
}

/* ---- the checks, before anything is written (3.7) ------------------------- */

/* Asked of the shell: Windows sets the ProgramFiles variable afresh in each
 * process it starts, so the variable says nothing a test could move. */
static int under_folder(const wchar_t* path, REFKNOWNFOLDERID id)
{
    PWSTR dir = NULL;
    int in = 0;
    if (SUCCEEDED(SHGetKnownFolderPath(id, 0, NULL, &dir))) {
        size_t n = wcslen(dir);
        in = !_wcsnicmp(path, dir, n) && (path[n] == L'\\' || !path[n]);
    }
    CoTaskMemFree(dir);
    return in;
}

/* Where Smart App Control is on (1; 2 is its evaluation mode, which blocks
 * nothing), Windows runs no unsigned program, and nothing can sign what this
 * builds on the player's machine (R4, risk 2). */
static int smart_app_control_on(void)
{
    DWORD v = 0, sz = sizeof v;
    return RegGetValueW(HKEY_LOCAL_MACHINE, L"SYSTEM\\CurrentControlSet\\Control\\CI\\Policy",
                        L"VerifiedAndReputablePolicyState", RRF_RT_REG_DWORD, NULL, &v, &sz) == ERROR_SUCCESS &&
           v == 1;
}

/* CHECK_OK when the game can be built in this folder; otherwise what to tell
 * the player is in buf. Nothing is left behind. */
static int folder_problem(wchar_t* buf, size_t cap)
{
    const wchar_t* p;
    wchar_t probe[MAX_PATH];
    ULARGE_INTEGER avail;
    HANDLE h;
    size_t i, len = wcslen(g_root);
    /* settings.c finds the root with the ANSI calls, so a path they cannot
     * spell would lose it silently (3.7) */
    for (p = g_root; *p; p++)
        if (*p < 0x20 || *p > 0x7E) {
            swprintf(buf, cap,
                     L"This folder's path has letters the game cannot read yet:\r\n%ls\r\n"
                     L"Move the whole folder to a plain path, such as C:\\Games\\Skies, and run Setup again.",
                     g_root);
            return CHECK_PATH;
        }
    if (len + 1 + SETUP_DEEPEST >= MAX_PATH) {
        swprintf(buf, cap,
                 L"This folder's path is %u letters long, and with the game's deepest file inside it, it would pass "
                 L"the 260 that Windows allows.\r\nMove the whole folder to a short path, such as C:\\Games\\Skies, "
                 L"and run Setup again.",
                 (unsigned)len);
        return CHECK_LONG;
    }
    if (under_folder(g_root, &FOLDERID_ProgramFiles) || under_folder(g_root, &FOLDERID_ProgramFilesX86)) {
        swprintf(buf, cap,
                 L"This folder is inside Program Files, where Windows does not let the game write its files. "
                 L"Move the whole folder somewhere else, such as C:\\Games\\Skies, and run Setup again.");
        return CHECK_PROGRAM_FILES;
    }
    for (i = 0; i < sizeof PACKAGE / sizeof PACKAGE[0]; i++) {
        path_join(probe, MAX_PATH, g_root, PACKAGE[i]);
        if (!file_exists(probe)) {
            swprintf(buf, cap,
                     L"This folder does not hold the whole package: %ls is missing.\r\n"
                     L"Setup has to run from the folder the zip makes. Right-click the zip, choose Extract All, "
                     L"pick a short folder such as C:\\Games\\Skies, and run Setup.exe from there.",
                     PACKAGE[i]);
            return CHECK_INCOMPLETE;
        }
    }
    path_join(probe, MAX_PATH, g_root, L"setup-write-test.tmp");
    h = CreateFileW(probe, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_FLAG_DELETE_ON_CLOSE, NULL);
    if (h == INVALID_HANDLE_VALUE && GetLastError() != ERROR_FILE_EXISTS) {
        swprintf(buf, cap,
                 L"Setup cannot write in this folder:\r\n%ls\r\n"
                 L"Move the whole folder somewhere you can write, such as C:\\Games\\Skies, and run Setup again.",
                 g_root);
        return CHECK_WRITE;
    }
    if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
    if (!built() && GetDiskFreeSpaceExW(g_root, &avail, NULL, NULL) && avail.QuadPart < NEED_FREE) {
        swprintf(buf, cap,
                 L"The game needs about 2 GB free here, and this drive has %.1f GB. "
                 L"Free some space, or move the whole folder to another drive.",
                 (double)avail.QuadPart / (1u << 30));
        return CHECK_SPACE;
    }
    if (smart_app_control_on()) {
        swprintf(buf, cap,
                 L"Smart App Control is on, and it stops Windows running any program that is not signed. "
                 L"The game is built here, on your PC, from your own disc, so nothing can sign it, and it cannot run "
                 L"while Smart App Control is on.\r\n"
                 L"It is in Windows Security, under App & browser control. Once turned off, Windows cannot turn it "
                 L"back on without being reset, so that choice is yours.");
        return CHECK_SMART_APP_CONTROL;
    }
    return CHECK_OK;
}

/* The formats the build reads (player_build: RVZ, and ISO or GCM as plain
 * images); any other is named, with Dolphin's converter. */
static int disc_problem(const wchar_t* disc, wchar_t* buf, size_t cap)
{
    const wchar_t* ext = wcsrchr(disc, L'.');
    if (ext && wcschr(ext, L'\\')) ext = NULL;
    if (ext && (!_wcsicmp(ext, L".iso") || !_wcsicmp(ext, L".gcm") || !_wcsicmp(ext, L".rvz"))) return CHECK_OK;
    swprintf(buf, cap,
             L"Setup reads disc images saved as ISO, GCM or RVZ, and this one is %ls.\r\n"
             L"Dolphin converts it: right-click the game in Dolphin's list, choose Convert File, and pick ISO or RVZ.",
             ext ? ext : L"none of those");
    return CHECK_FORMAT;
}

/* ---- the build ------------------------------------------------------------ */

static void status(const wchar_t* text) { SetWindowTextW(g_status, text); }

static void log_line(const wchar_t* line)
{
    int n = GetWindowTextLengthW(g_log);
    SendMessageW(g_log, EM_SETSEL, (WPARAM)n, (LPARAM)n);
    SendMessageW(g_log, EM_REPLACESEL, FALSE, (LPARAM)line);
    SendMessageW(g_log, EM_REPLACESEL, FALSE, (LPARAM)L"\r\n");
    if (g_logf) {
        fwprintf(g_logf, L"%ls\n", line);
        fflush(g_logf);
    }
}

typedef struct {
    HANDLE pipe, process;
} Running;

/* One line of the build's UTF-8 to the window, which frees it. */
static void post_line(char* line, size_t n)
{
    int len;
    wchar_t* w;
    if (n && line[n - 1] == '\r') n--;
    line[n] = 0;
    len = MultiByteToWideChar(CP_UTF8, 0, line, -1, NULL, 0);
    w = (wchar_t*)malloc(sizeof(wchar_t) * (size_t)(len > 0 ? len : 1));
    if (!w) return;
    w[0] = 0;
    MultiByteToWideChar(CP_UTF8, 0, line, -1, w, len);
    PostMessageW(g_wnd, WM_BUILD_LINE, 0, (LPARAM)w);
}

/* Every line the build prints, to the window; then its exit status. */
static DWORD WINAPI reader(LPVOID arg)
{
    Running* r = (Running*)arg;
    char buf[4096], line[8192];
    size_t n = 0;
    DWORD got, code = 1, i;
    while (ReadFile(r->pipe, buf, sizeof buf, &got, NULL) && got) {
        for (i = 0; i < got; i++) {
            if (buf[i] == '\n') {
                post_line(line, n);
                n = 0;
            } else {
                if (n == sizeof line - 1) {
                    post_line(line, n);
                    n = 0;
                }
                line[n++] = buf[i];
            }
        }
    }
    if (n) post_line(line, n);
    WaitForSingleObject(r->process, INFINITE);
    GetExitCodeProcess(r->process, &code);
    CloseHandle(r->pipe);
    CloseHandle(r->process);
    free(r);
    PostMessageW(g_wnd, WM_BUILD_DONE, (WPARAM)code, 0);
    return 0;
}

static void set_buttons(void)
{
    int done = built();
    EnableWindow(g_choose, !g_busy && !g_blocked);
    EnableWindow(g_build, !g_busy && !g_blocked && g_disc[0]);
    EnableWindow(g_rebuild, !g_busy && !g_blocked && done);
    EnableWindow(g_play, !g_busy && done);
}

static void start_build(const wchar_t* disc, int rebuild)
{
    wchar_t cmd[4 * MAX_PATH + 64], python[MAX_PATH], logpath[MAX_PATH];
    SECURITY_ATTRIBUTES sa = {sizeof sa, NULL, TRUE};
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    HANDLE rd, wr, nul;
    Running* r;
    path_join(python, MAX_PATH, g_root, L"python\\python.exe");
    swprintf(cmd, sizeof cmd / sizeof cmd[0],
             L"\"%ls\" -X utf8 \"%ls\\source\\tools\\player_build.py\" --disc \"%ls\" --root \"%ls\"%ls", python, g_root,
             disc, g_root, rebuild ? L" --rebuild" : L"");
    if (!CreatePipe(&rd, &wr, &sa, 0)) return;
    SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);
    nul = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);
    memset(&si, 0, sizeof si);
    si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = nul;
    si.hStdOutput = wr;
    si.hStdError = wr;
    path_join(logpath, MAX_PATH, g_root, L"build");
    CreateDirectoryW(logpath, NULL);
    path_join(logpath, MAX_PATH, g_root, L"build\\setup.log");
    if (g_logf) fclose(g_logf);
    g_logf = _wfopen(logpath, L"w, ccs=UTF-8");
    SetWindowTextW(g_log, L"");
    g_refusal[0] = 0;
    /* Suspended until it is in the job, so nothing it starts escapes it. */
    if (!CreateProcessW(python, cmd, NULL, NULL, TRUE, NO_CONSOLE | CREATE_SUSPENDED, NULL, g_root, &si, &pi)) {
        CloseHandle(rd);
        CloseHandle(wr);
        if (nul != INVALID_HANDLE_VALUE) CloseHandle(nul);
        status(L"Setup could not start the build: python\\python.exe is missing. Extract the whole package again, "
               L"into a new folder.");
        return;
    }
    if (g_job) AssignProcessToJobObject(g_job, pi.hProcess);
    ResumeThread(pi.hThread);
    CloseHandle(wr);
    if (nul != INVALID_HANDLE_VALUE) CloseHandle(nul);
    CloseHandle(pi.hThread);
    r = (Running*)malloc(sizeof *r);
    r->pipe = rd;
    r->process = pi.hProcess;
    g_busy = 1;
    SendMessageW(g_progress, PBM_SETPOS, 0, 0);
    status(L"Building the game from your disc. It takes a few minutes, and only once.");
    set_buttons();
    CloseHandle(CreateThread(NULL, 0, reader, r, 0, NULL));
}

/* The bar from the [build] lines: the check, the extraction, the
 * translation, each unit compiled, the link and the mods. */
static void on_line(const wchar_t* line)
{
    int n = 0, m = 0, pos = -1;
    log_line(line);
    if (wcsncmp(line, L"[build] ", 8)) return;
    line += 8;
    if (!wcscmp(line, L"check")) pos = 2;
    else if (!wcscmp(line, L"extract")) pos = 4;
    else if (!wcsncmp(line, L"translate", 9)) pos = 10;
    else if (swscanf(line, L"%d/%d", &n, &m) == 2 && m > 0) pos = 12 + 78 * n / m;
    else if (!wcscmp(line, L"link")) pos = 92;
    else if (!wcsncmp(line, L"mod ", 4)) pos = 96;
    else if (!wcsncmp(line, L"done", 4)) pos = 100;
    else if (!wcsncmp(line, L"refused: ", 9)) swprintf(g_refusal, MSG_CAP, L"%ls", line + 9);
    if (pos >= 0) SendMessageW(g_progress, PBM_SETPOS, (WPARAM)pos, 0);
}

static void play(void)
{
    wchar_t exe[MAX_PATH], cmd[MAX_PATH + 4];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    path_join(exe, MAX_PATH, g_root, L"soa.exe");
    if (!file_exists(exe)) {
        status(L"soa.exe is not in this folder any more. If Windows Security removed it, it is under Virus & threat "
               L"protection > Protection history, where Restore brings it back. Or press Rebuild.");
        set_buttons();
        return;
    }
    swprintf(cmd, sizeof cmd / sizeof cmd[0], L"\"%ls\"", exe);
    memset(&si, 0, sizeof si);
    si.cb = sizeof si;
    /* With a console of its own, soa.exe writes its log under build\logs
     * (settings.c, M5b); this flag keeps that console hidden. */
    if (CreateProcessW(exe, cmd, NULL, NULL, FALSE, NO_CONSOLE, NULL, g_root, &si, &pi)) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        DestroyWindow(g_wnd);
    } else {
        wchar_t msg[MSG_CAP];
        swprintf(msg, MSG_CAP,
                 L"Windows would not start soa.exe (error %lu). If Windows Security blocked it, it says so under "
                 L"Virus & threat protection > Protection history.",
                 GetLastError());
        status(msg);
    }
}

static void on_done(DWORD code)
{
    wchar_t msg[MSG_CAP + 200];
    g_busy = 0;
    if (g_logf) {
        fclose(g_logf);
        g_logf = NULL;
    }
    if (code == 0 && built()) {
        SendMessageW(g_progress, PBM_SETPOS, 100, 0);
        status(L"The game is built. Press Play. From now on, soa.exe in this folder starts it too.");
    } else if (code == 0) {
        status(L"The build finished, but soa.exe is not in this folder. Windows Security may have removed it: "
               L"Virus & threat protection > Protection history shows it, and Restore brings it back.");
    } else if (code == 2) {
        swprintf(msg, sizeof msg / sizeof msg[0], L"This disc image cannot be used: %ls",
                 g_refusal[0] ? g_refusal : L"the log below says why.");
        status(msg);
    } else {
        swprintf(msg, sizeof msg / sizeof msg[0],
                 L"The build stopped. Its log is below, and saved as %ls\\build\\setup.log: send that file with "
                 L"any report.",
                 g_root);
        status(msg);
    }
    set_buttons();
    if (code == 0 && g_auto_play) play();
}

static void choose(void)
{
    OPENFILENAMEW ofn;
    wchar_t file[MAX_PATH] = L"", why[MSG_CAP];
    memset(&ofn, 0, sizeof ofn);
    ofn.lStructSize = sizeof ofn;
    ofn.hwndOwner = g_wnd;
    ofn.lpstrFilter = L"GameCube disc images (*.iso, *.gcm, *.rvz)\0*.iso;*.gcm;*.rvz\0All files\0*.*\0";
    ofn.lpstrFile = file;
    ofn.nMaxFile = MAX_PATH;
    ofn.lpstrTitle = L"Your Skies of Arcadia Legends disc image";
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
    if (!GetOpenFileNameW(&ofn)) return;
    if (disc_problem(file, why, MSG_CAP)) {
        status(why);
        return;
    }
    wcscpy(g_disc, file);
    SetWindowTextW(g_disc_edit, g_disc);
    status(L"Press Build. Setup checks the disc first: it must be the North American GameCube release.");
    set_buttons();
}

/* ---- the window ----------------------------------------------------------- */

static int S(int x) { return MulDiv(x, g_dpi, 96); }

static HWND control(const wchar_t* cls, const wchar_t* text, DWORD style, int x, int y, int w, int h, int id, HFONT f)
{
    HWND c = CreateWindowExW(0, cls, text, WS_CHILD | WS_VISIBLE | style, S(x), S(y), S(w), S(h), g_wnd,
                             (HMENU)(INT_PTR)id, GetModuleHandleW(NULL), NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    return c;
}

static LRESULT CALLBACK proc(HWND h, UINT msg, WPARAM w, LPARAM l)
{
    switch (msg) {
    case WM_CREATE: {
        wchar_t why[MSG_CAP];
        HFONT ui = CreateFontW(-S(12), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                               L"Segoe UI");
        HFONT bold = CreateFontW(-S(15), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                                 L"Segoe UI");
        HFONT mono = CreateFontW(-S(12), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY,
                                 FIXED_PITCH, L"Consolas");
        g_wnd = h;
        control(L"STATIC", L"Skies of Arcadia Legends, built from your own disc", 0, 16, 12, 600, 24, 0, bold);
        g_status = control(L"STATIC", L"", 0, 16, 42, 600, 66, 0, ui);
        g_choose = control(L"BUTTON", L"Choose disc image...", BS_PUSHBUTTON | WS_TABSTOP, 16, 114, 150, 28,
                           ID_CHOOSE, ui);
        g_disc_edit = control(L"EDIT", L"", WS_BORDER | ES_READONLY | ES_AUTOHSCROLL, 176, 116, 440, 24, 0, ui);
        g_build = control(L"BUTTON", L"Build", BS_PUSHBUTTON | WS_TABSTOP, 16, 150, 100, 28, ID_BUILD, ui);
        g_rebuild = control(L"BUTTON", L"Rebuild", BS_PUSHBUTTON | WS_TABSTOP, 126, 150, 100, 28, ID_REBUILD, ui);
        g_play = control(L"BUTTON", L"Play", BS_DEFPUSHBUTTON | WS_TABSTOP, 516, 150, 100, 28, ID_PLAY, ui);
        g_progress = control(PROGRESS_CLASSW, L"", 0, 16, 188, 600, 16, 0, ui);
        SendMessageW(g_progress, PBM_SETRANGE, 0, MAKELPARAM(0, 100));
        g_log = control(L"EDIT", L"", WS_BORDER | WS_VSCROLL | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL,
                        16, 214, 600, 226, 0, mono);
        SendMessageW(g_log, EM_SETLIMITTEXT, 0, 0);
        if (folder_problem(why, MSG_CAP)) {
            g_blocked = 1;
            status(why);
        } else if (g_disc[0] && disc_problem(g_disc, why, MSG_CAP)) {
            g_disc[0] = 0;
            status(why);
        } else if (g_disc[0]) {
            SetWindowTextW(g_disc_edit, g_disc);
            status(L"Press Build. Setup checks the disc first: it must be the North American GameCube release.");
        } else {
            status(built() ? L"The game is built in this folder. Press Play, or Rebuild to build it again from "
                             L"the start."
                           : L"Choose your Skies of Arcadia Legends disc image (ISO, GCM or RVZ). Setup builds "
                             L"the game from it, into this folder.");
        }
        set_buttons();
        if (g_auto_build && g_disc[0] && !g_blocked) start_build(g_disc, 0);
        return 0;
    }
    case WM_COMMAND:
        switch (LOWORD(w)) {
        case ID_CHOOSE:
            choose();
            break;
        case ID_BUILD:
            if (g_disc[0]) start_build(g_disc, 0);
            break;
        case ID_REBUILD: {
            /* the image this folder was built from, as the build copied it */
            wchar_t disc[MAX_PATH];
            path_join(disc, MAX_PATH, g_root, L"extracted\\disc.iso");
            start_build(g_disc[0] ? g_disc : disc, 1);
            break;
        }
        case ID_PLAY:
            play();
            break;
        }
        return 0;
    case WM_BUILD_LINE:
        on_line((const wchar_t*)l);
        free((void*)l);
        return 0;
    case WM_BUILD_DONE:
        on_done((DWORD)w);
        return 0;
    case WM_CTLCOLORSTATIC:
        /* the read-only edits on the window's own colour, not grey on grey */
        if ((HWND)l == g_log || (HWND)l == g_disc_edit) {
            SetBkColor((HDC)w, GetSysColor(COLOR_WINDOW));
            return (LRESULT)GetSysColorBrush(COLOR_WINDOW);
        }
        break;
    case WM_CLOSE:
        if (g_busy && MessageBoxW(h, L"The build is still running. Stop it and close Setup?", L"Setup",
                                  MB_YESNO | MB_ICONQUESTION) != IDYES)
            return 0;
        DestroyWindow(h);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, msg, w, l);
}

/* --check: what the checks found, in words on stdout and as the exit code. */
static int check_only(void)
{
    wchar_t why[MSG_CAP] = L"ready";
    char out[4 * MSG_CAP];
    DWORD wrote;
    int n, code = folder_problem(why, MSG_CAP);
    if (!code && g_disc[0]) code = disc_problem(g_disc, why, MSG_CAP);
    n = WideCharToMultiByte(CP_UTF8, 0, why, -1, out, sizeof out - 2, NULL, NULL);
    if (n > 0) {
        out[n - 1] = '\n';
        WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), out, (DWORD)n, &wrote, NULL);
    }
    return code;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show)
{
    INITCOMMONCONTROLSEX icc = {sizeof icc, ICC_PROGRESS_CLASS | ICC_STANDARD_CLASSES};
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION lim;
    WNDCLASSW wc;
    MSG m;
    RECT rc;
    HDC dc;
    int argc = 0, i, check = 0;
    DWORD n;
    wchar_t root[MAX_PATH] = L"";
    wchar_t** argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    wchar_t* slash;
    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    (void)prev;
    (void)cmdline;
    GetModuleFileNameW(NULL, g_root, MAX_PATH);
    slash = wcsrchr(g_root, L'\\');
    if (slash) *slash = 0;
    for (i = 1; argv && i < argc; i++) {
        if (!wcscmp(argv[i], L"--disc") && i + 1 < argc) {
            GetFullPathNameW(argv[++i], MAX_PATH, g_disc, NULL);
        } else if (!wcscmp(argv[i], L"--build")) {
            g_auto_build = 1;
        } else if (!wcscmp(argv[i], L"--play")) {
            g_auto_play = 1;
        } else if (!wcscmp(argv[i], L"--check")) {
            check = 1;
        } else if (!wcscmp(argv[i], L"--root") && i + 1 < argc) {
            GetFullPathNameW(argv[++i], MAX_PATH, root, NULL);
        }
    }
    if (check && root[0]) wcscpy(g_root, root);
    /* the long form, so C:\PROGRA~1 is Program Files too */
    n = GetLongPathNameW(g_root, root, MAX_PATH);
    if (n && n < MAX_PATH) wcscpy(g_root, root);
    if (check) return check_only();
    /* Closing Setup ends the build it started, the compilers too. */
    g_job = CreateJobObjectW(NULL, NULL);
    if (g_job) {
        memset(&lim, 0, sizeof lim);
        lim.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(g_job, JobObjectExtendedLimitInformation, &lim, sizeof lim);
    }
    dc = GetDC(NULL);
    g_dpi = GetDeviceCaps(dc, LOGPIXELSY);
    ReleaseDC(NULL, dc);
    InitCommonControlsEx(&icc);
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = L"SoaSetup";
    RegisterClassW(&wc);
    rc.left = rc.top = 0;
    rc.right = S(632);
    rc.bottom = S(456);
    AdjustWindowRect(&rc, style, FALSE);
    CreateWindowW(L"SoaSetup", L"Skies of Arcadia Legends - Setup", style, CW_USEDEFAULT, CW_USEDEFAULT,
                  rc.right - rc.left, rc.bottom - rc.top, NULL, NULL, inst, NULL);
    ShowWindow(g_wnd, show);
    while (GetMessageW(&m, NULL, 0, 0) > 0) {
        if (!IsDialogMessageW(g_wnd, &m)) {
            TranslateMessage(&m);
            DispatchMessageW(&m);
        }
    }
    if (g_logf) fclose(g_logf);
    return 0;
}
