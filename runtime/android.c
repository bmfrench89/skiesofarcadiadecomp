/*
 * The APK's entry (specs/android.md 3.8, 3.14). SDLActivity loads SDL3 and
 * libsoa_runtime.so, and calls SDL_main here on SDL's thread. It:
 *
 * - makes the app's own storage the data root, as SOA_ROOT and as the working
 *   directory, so soa.ini, the card and every relative path land there rather
 *   than in /system/bin or / (settings.c's root, main.c's "extracted");
 * - sends stderr and stdout to logcat (tag soa) and to soa.log in that root,
 *   the run before kept as soa.log.1, through a pipe and a thread, so the
 *   report's lines read as the PC's do (tools/android.py pulls the file);
 * - keeps the window landscape: SDL replaces the manifest's orientation with
 *   its own when the window is made, and for a resizable window with no hint
 *   that is any orientation at all;
 * - looks for the game library in the root unless SOA_GAME names one, and
 *   runs the port through runtime/game.c, which checks it before dlopen;
 * - ends with "[exit] N" and _exit(N) once the log is flushed: adb cannot see
 *   an app's exit status, and SDLActivity keeps the process after SDL_main
 *   returns, so a second launch would otherwise run over this one's statics.
 *   The runtime's own ways out end the same way -- _Exit after the frame
 *   limit's or the watchdog's report, _exit after a window's close, exit(N)
 *   from a trap -- because the library is linked with --wrap for all three.
 *   Without it the report's last lines were still in the pipe when the
 *   process went, and the [exit] line never came (FINDINGS "L12c").
 *
 * Built only for Android with SDL (android/app/src/main/cpp/CMakeLists.txt);
 * every other build compiles it to nothing.
 */
#if defined(__ANDROID__) && defined(SOA_SDL)
#include <SDL3/SDL.h>
#define SDL_MAIN_HANDLED /* SDL_main is defined below as it is, not by renaming main */
#include <SDL3/SDL_main.h>
#include <android/log.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int soa_run(int argc, char** argv); /* runtime/game.c */

static int g_pipe[2] = {-1, -1};
static FILE* g_log;
static pthread_t g_logger;
static int g_logging;

static void emit(const char* line)
{
    __android_log_write(ANDROID_LOG_INFO, "soa", line);
    if (g_log) fprintf(g_log, "%s\n", line);
}

/* Lines from the pipe to logcat and the file, until every writer has closed it. */
static void* logger(void* arg)
{
    char buf[2048];
    size_t have = 0;
    ssize_t n;
    (void)arg;
    while ((n = read(g_pipe[0], buf + have, sizeof buf - 1 - have)) > 0) {
        char *line = buf, *nl;
        have += (size_t)n;
        buf[have] = '\0';
        while ((nl = strchr(line, '\n')) != NULL) {
            *nl = '\0';
            emit(line);
            line = nl + 1;
        }
        have = (size_t)(buf + have - line);
        memmove(buf, line, have);
        if (have == sizeof buf - 1) { /* a line longer than the buffer, as far as it goes */
            buf[have] = '\0';
            emit(buf);
            have = 0;
        }
        if (g_log) fflush(g_log);
    }
    if (have) {
        buf[have] = '\0';
        emit(buf);
    }
    if (g_log) fflush(g_log);
    return NULL;
}

static void logs_start(void)
{
    rename("soa.log", "soa.log.1");
    g_log = fopen("soa.log", "w");
    if (pipe(g_pipe) != 0) return;
    dup2(g_pipe[1], 1);
    dup2(g_pipe[1], 2);
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);
    g_logging = pthread_create(&g_logger, NULL, logger, NULL) == 0;
}

static void logs_end(void)
{
    fflush(stdout);
    fflush(stderr);
    close(1);
    close(2);
    close(g_pipe[1]);
    if (g_logging) pthread_join(g_logger, NULL);
    if (g_log) fclose(g_log);
}

_Noreturn void __real__exit(int status);

/* Once, from whichever thread gets here first; a second caller waits for its
 * _exit rather than closing what the first is draining. */
static _Noreturn void finish(int rc)
{
    static atomic_flag once = ATOMIC_FLAG_INIT;
    if (atomic_flag_test_and_set(&once))
        for (;;) pause();
    fprintf(stderr, "[exit] %d\n", rc);
    logs_end();
    __real__exit(rc);
}

void __wrap_exit(int status);
void __wrap__exit(int status);
void __wrap__Exit(int status);
void __wrap_exit(int status) { finish(status); }
void __wrap__exit(int status) { finish(status); }
void __wrap__Exit(int status) { finish(status); }

int SDL_main(int argc, char** argv)
{
    const char* root = SDL_GetAndroidInternalStoragePath();
    char game[1100];
    SDL_SetMainReady();
    SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");
    if (!root || chdir(root) != 0) {
        __android_log_print(ANDROID_LOG_ERROR, "soa", "[android] no data root (%s)", root ? root : "none");
        _exit(1);
    }
    setenv("SOA_ROOT", root, 1);
    logs_start();
    fprintf(stderr, "[android] data root %s\n", root);
    if (!getenv("SOA_GAME") || !*getenv("SOA_GAME")) {
        snprintf(game, sizeof game, "%s/libsoa_game.so", root);
        setenv("SOA_GAME", game, 1);
    }
    finish(soa_run(argc, argv));
}
#endif
