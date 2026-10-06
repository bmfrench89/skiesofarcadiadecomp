/*
 * The APK's entry (specs/android.md 3.8, 3.14, L12d). SDLActivity loads SDL3 and
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
 * - imports the game's two files, the game library and the disc, the first
 *   time, and checks them again at every launch (L12d, "The import" below),
 *   then runs the port through runtime/game.c with the library it loaded;
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
#include <dirent.h>
#include <errno.h>
#include <jni.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "disc.h"
#include "game.h"
#include "import.h"

int soa_run(int argc, char** argv);     /* runtime/game.c */
extern const char soa_runtime_record[]; /* generated/runtime_seam.c, tools/android.py's */

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

/* ---- The import (specs/android.md L12d) -------------------------------------
 *
 * The player picks the two files with SoaActivity's own picker, and each comes
 * as a descriptor N with a permission to open it again, never as a path the
 * app may open: every check reads /proc/self/fd/N through N itself (plat.h).
 * The game library comes first, always, since a disc is checked against the
 * library it will play with (disc.c). A picked library is checked through its
 * descriptor before a byte is copied, copied into noBackupFilesDir, loaded
 * from the copy, and only then put in place of the one installed, so a pick
 * that will not load never costs the player the library they had. A picked
 * disc is checked through its descriptor before anything is copied, and then
 * read where it lies, on this launch and every one after, when import.c says
 * it may be (this phone's storage, a file that seeks, a permission kept), or
 * copied into noBackupFilesDir/copy otherwise. disc.txt says which, written
 * only once the disc is accepted.
 *
 * The prompts are SDL's message boxes, drawn by SoaActivity, and the picks
 * SoaActivity's picker, both called from this thread, which they block:
 * nothing else runs before the port does, and the UI thread never waits on
 * this one. Whatever the player does meanwhile comes back here as an answer.
 * Back in the picker is a cancel, which shows the prompt again; an activity
 * destroyed ends the run at once, inside the second SDL gives this thread
 * before it tears down what a window would need; a pick that came back to a
 * process started after the one that asked waits in a pending file.
 *
 * A check run (SOA_CHECK_RUN, which only a debuggable build's extras set)
 * without SOA_IMPORT is L12c's, untouched. With it, each box is logged and
 * answered here with its first button, the picks come from the pick extra
 * (or the picker, with SOA_IMPORT_PICKER=1), a refusal or a cancel ends the
 * run with 1, and soa.ini is never written. */

#define TITLE "SoA port" /* the app's label (AndroidManifest.xml) */
#define QUIT "Quit"
/* The prompts, drafts for the owner's look (the settled design, section 6). */
#define LIB_PROMPT                                                                                                  \
    "This app plays Skies of Arcadia Legends from your own disc, with two files your PC makes from it.\n\n"        \
    "First the game library, libsoa_game.so, which Setup makes for this phone. Copy it to this phone (its "       \
    "Download folder is fine), then pick it."
#define MODS_NOTE "Mods are not on Android yet."
#define DISC_PROMPT                                                                                                 \
    "Now the disc: the store your PC made of it (GEAE8P.soadisc, the better choice, since it can tell when a copy " \
    "is damaged), or an image of it (.iso or .gcm). Copy it to this phone, then pick it. It is read where it is, " \
    "so leave it there."

#define URI_MAX 2048
enum { LIBRARY, DISC }; /* SoaActivity.pick's kinds, and the pending files' */
static const char* const KIND[] = {"library", "disc"};
/* SoaActivity.openFd's answers that are not a descriptor */
enum { OPEN_SECURITY = -2, OPEN_MISSING = -3, OPEN_OTHER = -4, OPEN_CANCELLED = -5 };

#if defined(__aarch64__)
#define HOST_MACHINE 183 /* EM_AARCH64, as runtime/game.c holds a library to */
#else
#define HOST_MACHINE 62 /* EM_X86_64 */
#endif

static struct {
    const char* root; /* filesDir: soa.ini, soa.log, the card */
    char nb[1024];    /* noBackupFilesDir: the library, disc.txt, the pending picks, the disc's copy */
    char game[1100];  /* SOA_GAME: the library installed */
    int check;        /* a check run: its boxes answered here; a refusal or a cancel ends it */
    int picker;       /* pick() may open the system's picker */
    int loaded;       /* a library is loaded in this process: the one installed */
} g;

/* What SoaActivity.describe says of a picked file. */
typedef struct {
    char name[256];      /* the name the player knows it by, for messages; never a path */
    int64_t size;        /* the provider's, or -1 */
    char authority[256]; /* the provider's */
    int kept;            /* the permission to read it will outlive this launch */
} Doc;

/* disc.txt: the disc accepted last, and how it is read. */
typedef struct {
    char uri[URI_MAX], name[256], authority[256];
    char copy[1100]; /* its copy, or "" when it is read in place */
} Stored;

/* A copy's progress dialog says what it copies. */
typedef struct {
    const char* name;
} CopyUi;

static int flag(const char* name)
{
    const char* v = getenv(name);
    return v && *v && strcmp(v, "0") != 0;
}

static int exists(const char* path)
{
    struct stat st;
    return lstat(path, &st) == 0;
}

/* s made whole UTF-8 in place, as NewStringUTF insists on in a debuggable app
 * (CheckJNI aborts the process otherwise): a byte that neither begins nor
 * continues a character becomes '?', and a character cut short at the end,
 * as a cut at a buffer's size leaves one, goes. */
static void whole_utf8(char* s)
{
    unsigned char* p = (unsigned char*)s;
    while (*p) {
        int n = *p < 0x80 ? 0 : (*p & 0xE0) == 0xC0 ? 1 : (*p & 0xF0) == 0xE0 ? 2 : (*p & 0xF8) == 0xF0 ? 3 : -1;
        int i = 1;
        while (n > 0 && i <= n && (p[i] & 0xC0) == 0x80) i++;
        if (n > 0 && i <= n && !p[i]) {
            *p = '\0';
            return;
        }
        if (n < 0 || i <= n) {
            *p++ = '?';
            continue;
        }
        p += n + 1;
    }
}

/* A size as a player reads one. */
static const char* amount(uint64_t n, char* buf, size_t cap)
{
    if (n >= (uint64_t)1 << 30)
        snprintf(buf, cap, "%.1f GB", (double)n / (double)((uint64_t)1 << 30));
    else
        snprintf(buf, cap, "%llu MB", (unsigned long long)(n >> 20));
    return buf;
}

/* Every place a message may name a picked file by -- its descriptor's path,
 * its copy's .tmp, its copy -- replaced by the name the player picked. */
static void name_in(char* why, size_t cap, const char* name, const char* a, const char* b, const char* c)
{
    if (a && *a) import_name_in(why, cap, a, name);
    if (b && *b) import_name_in(why, cap, b, name);
    if (c && *c) import_name_in(why, cap, c, name);
}

/* The first line of a small file into out: 1; 0 when there is none. */
static int first_line(const char* path, char* out, size_t cap)
{
    FILE* f = fopen(path, "r");
    out[0] = '\0';
    if (!f) return 0;
    if (!fgets(out, (int)cap, f)) out[0] = '\0';
    fclose(f);
    out[strcspn(out, "\r\n")] = '\0';
    return out[0] != '\0';
}

/* ---- SoaActivity, from this thread (the settled design, decision 25) ----- */

static JNIEnv* g_env;
static jobject g_act; /* SoaActivity, held for the process: it is the only one (singleInstance) */
static jmethodID g_pick, g_open, g_describe, g_release, g_tidy, g_status, g_error;
static jfieldID g_destroyed;

static _Noreturn void closed(void)
{
    fprintf(stderr, "[import] the app was closed during the import\n");
    finish(0);
}

/* A Java exception left pending, said and cleared: 1 when there was one. Each
 * JNI call is followed by this, since SDL's thread may make no other call with
 * one pending, and a debuggable app aborts if it does. */
static int caught(const char* what)
{
    if (!(*g_env)->ExceptionCheck(g_env)) return 0;
    (*g_env)->ExceptionDescribe(g_env); /* to logcat, with its stack */
    (*g_env)->ExceptionClear(g_env);
    fprintf(stderr, "[import] %s threw (logcat has the exception)\n", what);
    return 1;
}

/* After every call into Java: once SoaActivity is destroyed, the run ends,
 * with no box, no Java call and no port after it, while SDL still waits for
 * this thread (SoaActivity.onDestroy). */
static void alive(void)
{
    jboolean gone = (*g_env)->GetBooleanField(g_env, g_act, g_destroyed);
    if (caught("destroyed") || gone) closed();
}

/* Each call in a local frame of its own: this thread entered native code once
 * and never goes back to Java, so a reference left behind would stay for the
 * life of the process. */
static int frame(void)
{
    if ((*g_env)->PushLocalFrame(g_env, 16) == 0) return 1;
    caught("PushLocalFrame");
    return 0;
}

static void unframe(void) { (*g_env)->PopLocalFrame(g_env, NULL); }

static jstring jtext(const char* s)
{
    static char buf[8192];
    jstring j;
    snprintf(buf, sizeof buf, "%s", s ? s : "");
    whole_utf8(buf);
    j = (*g_env)->NewStringUTF(g_env, buf);
    return caught("NewStringUTF") ? NULL : j;
}

/* A Java string into out: 1 when it fitted whole. */
static int ctext(jstring s, char* out, size_t cap)
{
    const char* c;
    size_t n;
    out[0] = '\0';
    if (!s) return 0;
    c = (*g_env)->GetStringUTFChars(g_env, s, NULL);
    if (!c) {
        caught("GetStringUTFChars");
        return 0;
    }
    n = strlen(c);
    snprintf(out, cap, "%s", c);
    (*g_env)->ReleaseStringUTFChars(g_env, s, c);
    whole_utf8(out);
    return n < cap;
}

static jmethodID method(jclass cls, const char* name, const char* sig)
{
    jmethodID m = (*g_env)->GetMethodID(g_env, cls, name, sig);
    return caught(name) ? NULL : m;
}

/* SoaActivity's side of the import, found on the activity SDL holds, by
 * GetObjectClass: FindClass on this thread would ask the system's class
 * loader, which has none of the app's classes. 1, or 0 when any is missing. */
static int java_init(void)
{
    jobject act;
    jclass cls;
    g_env = (JNIEnv*)SDL_GetAndroidJNIEnv();
    if (!g_env) return 0;
    act = (jobject)SDL_GetAndroidActivity();
    if (caught("getContext") || !act) return 0;
    g_act = (*g_env)->NewGlobalRef(g_env, act);
    cls = (*g_env)->GetObjectClass(g_env, act);
    (*g_env)->DeleteLocalRef(g_env, act);
    if (!g_act || !cls) return 0;
    g_pick = method(cls, "pick", "(IZ)Ljava/lang/String;");
    g_open = method(cls, "openFd", "(Ljava/lang/String;)I");
    g_describe = method(cls, "describe", "(Ljava/lang/String;)Ljava/lang/String;");
    g_release = method(cls, "release", "(Ljava/lang/String;)V");
    g_tidy = method(cls, "tidyGrants", "([Ljava/lang/String;)I");
    g_status = method(cls, "status", "(Ljava/lang/String;I)Z");
    g_error = method(cls, "lastError", "()Ljava/lang/String;");
    g_destroyed = (*g_env)->GetFieldID(g_env, cls, "destroyed", "Z");
    if (caught("destroyed")) g_destroyed = NULL;
    (*g_env)->DeleteLocalRef(g_env, cls);
    return g_pick && g_open && g_describe && g_release && g_tidy && g_status && g_error && g_destroyed;
}

/* java_init failed: this APK's C and Java do not agree (a method renamed, or
 * one a shrinker took), and no import can run. A player sees no log, so it is
 * said on the screen before the app closes, with SDL's own box, which needs
 * none of what is missing. */
static void damaged(void)
{
    static const SDL_MessageBoxButtonData close1 = {
        SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT | SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT, 1, "Close"};
    SDL_MessageBoxData d;
    int id = 0;
    memset(&d, 0, sizeof d);
    d.flags = SDL_MESSAGEBOX_ERROR;
    d.title = TITLE;
    d.message = "This copy of the app is damaged: a part of it is missing, so it cannot ask for the game's files. "
                "Install the app again.";
    d.numbuttons = 1;
    d.buttons = &close1;
    SDL_ShowMessageBox(&d, &id);
}

/* What SoaActivity said of its last failure, for the log. */
static void java_error(char* out, size_t cap)
{
    jstring s;
    out[0] = '\0';
    if (!frame()) return;
    s = (jstring)(*g_env)->CallObjectMethod(g_env, g_act, g_error);
    if (!caught("lastError")) ctext(s, out, cap);
    unframe();
}

/* The file the player picked, as its URI: 1. 0 when nothing was -- Back in
 * the picker, the launcher's icon, a check run's queue run dry -- with what
 * SoaActivity said of it, if anything, in why. Ends the run once the app has
 * gone (SoaActivity answers null). */
static int java_pick(int kind, char* uri, size_t cap, char* why, size_t wcap)
{
    jstring s;
    int gone = 0, whole = 1;
    uri[0] = why[0] = '\0';
    if (!frame()) return 0;
    s = (jstring)(*g_env)->CallObjectMethod(g_env, g_act, g_pick, (jint)kind, (jboolean)(g.picker != 0));
    if (caught("pick")) s = NULL;
    else gone = !s;
    if (s) whole = ctext(s, uri, cap);
    unframe();
    alive();
    if (gone) closed();
    if (!whole) {
        snprintf(why, wcap, "the address of the file picked is longer than %u bytes", (unsigned)cap - 1);
        uri[0] = '\0';
    } else if (!uri[0]) {
        java_error(why, wcap);
    }
    return uri[0] != '\0';
}

/* SoaActivity.describe: the name, the size, the provider and whether the
 * permission is kept, a line each. */
static void describe(const char* uri, Doc* d)
{
    static char text[1024];
    char *p = text, *nl;
    memset(d, 0, sizeof *d);
    d->size = -1;
    text[0] = '\0';
    if (frame()) {
        jstring u = jtext(uri), s = NULL;
        if (u) {
            s = (jstring)(*g_env)->CallObjectMethod(g_env, g_act, g_describe, u);
            if (caught("describe")) s = NULL;
        }
        if (s) ctext(s, text, sizeof text);
        unframe();
    }
    alive();
    if ((nl = strchr(p, '\n')) != NULL) *nl = '\0';
    snprintf(d->name, sizeof d->name, "%s", p);
    whole_utf8(d->name);
    p = nl ? nl + 1 : p + strlen(p);
    if ((nl = strchr(p, '\n')) != NULL) *nl = '\0';
    d->size = *p ? strtoll(p, NULL, 10) : -1;
    p = nl ? nl + 1 : p + strlen(p);
    if ((nl = strchr(p, '\n')) != NULL) *nl = '\0';
    snprintf(d->authority, sizeof d->authority, "%s", p);
    p = nl ? nl + 1 : p + strlen(p);
    d->kept = *p == '1';
    if (!d->name[0]) snprintf(d->name, sizeof d->name, "the file you picked");
}

/* A descriptor for uri (SoaActivity.openFd), or one of OPEN_* with why in the
 * player's words; SoaActivity's own words go to the log. */
static int open_fd(const char* uri, char* why, size_t cap)
{
    char err[600] = "";
    int fd = OPEN_OTHER;
    if (frame()) {
        jstring u = jtext(uri);
        if (u) {
            fd = (*g_env)->CallIntMethod(g_env, g_act, g_open, u);
            if (caught("openFd")) fd = OPEN_OTHER;
        }
        unframe();
    }
    alive();
    if (fd >= 0) return fd;
    if (fd < OPEN_CANCELLED || fd == -1) fd = OPEN_OTHER;
    java_error(err, sizeof err);
    if (err[0]) fprintf(stderr, "[import] opening %s: %s\n", uri, err);
    if (fd == OPEN_SECURITY)
        snprintf(why, cap, "the permission to read it is gone");
    else if (fd == OPEN_MISSING)
        snprintf(why, cap, "it is not where it was (moved, deleted, or on storage that was removed)");
    else if (fd == OPEN_CANCELLED)
        snprintf(why, cap, "opening it was cancelled");
    else
        snprintf(why, cap, "it could not be opened%s%s%s", err[0] ? " (" : "", err, err[0] ? ")" : "");
    return fd;
}

static void java_release(const char* uri)
{
    if (frame()) {
        jstring u = jtext(uri);
        if (u) {
            (*g_env)->CallVoidMethod(g_env, g_act, g_release, u);
            caught("release");
        }
        unframe();
    }
    alive();
}

/* Every permission kept but those in keep released: how many. */
static int java_tidy(const char* const* keep, int n)
{
    jint k = 0;
    int i;
    if (frame()) {
        jclass str = (*g_env)->FindClass(g_env, "java/lang/String"); /* the system's own: found from any thread */
        jobjectArray all = NULL;
        if (!caught("FindClass") && str) {
            all = (*g_env)->NewObjectArray(g_env, n, str, NULL);
            if (caught("NewObjectArray")) all = NULL;
        }
        for (i = 0; all && i < n; i++) {
            jstring u = jtext(keep[i]);
            if (!u) all = NULL;
            else (*g_env)->SetObjectArrayElement(g_env, all, i, u);
        }
        if (all) {
            k = (*g_env)->CallIntMethod(g_env, g_act, g_tidy, all);
            if (caught("tidyGrants")) k = 0;
        }
        unframe();
    }
    alive();
    return (int)k;
}

/* The progress dialog (SoaActivity.status): text and how far, in thousandths
 * (-1 for not known); NULL hides it. 1 once its Cancel was pressed. */
static int java_status(const char* text, int permille)
{
    jboolean stop = JNI_FALSE;
    if (frame()) {
        jstring t = text ? jtext(text) : NULL;
        if (!text || t) {
            stop = (*g_env)->CallBooleanMethod(g_env, g_act, g_status, t, (jint)permille);
            if (caught("status")) stop = JNI_FALSE;
        }
        unframe();
    }
    alive();
    return stop != JNI_FALSE;
}

/* ---- boxes, refusals, cancels -------------------------------------------- */

/* text on one line for the log: each run of line breaks as " / " */
static void one_line(const char* text, char* out, size_t cap)
{
    size_t o = 0;
    while (*text && o + 4 < cap) {
        if (*text == '\n') {
            while (*text == '\n') text++;
            memcpy(out + o, " / ", 3);
            o += 3;
            continue;
        }
        out[o++] = *text++;
    }
    out[o] = '\0';
}

/* A box, answered: the index of the button. SDL_ShowMessageBox from this
 * thread, before any window; SoaActivity draws it (its
 * messageboxShowMessageBox) and blocks this thread until a button is pressed.
 * The first button is the default, and Quit the one Escape and a pad's B
 * mean. A check run never shows it: it is logged and answered with its first
 * button. Any answer but a button -- the activity gone, a box SoaActivity
 * could not show -- ends the run. */
static int box(const char* text, const char* const* buttons, int n)
{
    static char msg[4096], flat[4200];
    SDL_MessageBoxButtonData b[4];
    SDL_MessageBoxData d;
    int id = -1, i, shown;
    snprintf(msg, sizeof msg, "%s", text);
    whole_utf8(msg);
    one_line(msg, flat, sizeof flat);
    fprintf(stderr, "[import] box: %s\n", flat);
    if (g.check) return 0;
    if (n > 4) n = 4;
    for (i = 0; i < n; i++) {
        b[i].flags = i == 0 ? SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT
                     : !strcmp(buttons[i], QUIT) ? SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT
                                                 : 0;
        b[i].buttonID = i + 1; /* 0 and -1 are what SoaActivity answers when it has gone */
        b[i].text = buttons[i];
    }
    memset(&d, 0, sizeof d);
    d.flags = SDL_MESSAGEBOX_INFORMATION | SDL_MESSAGEBOX_BUTTONS_LEFT_TO_RIGHT;
    d.title = TITLE;
    d.message = msg;
    d.numbuttons = n;
    d.buttons = b;
    shown = SDL_ShowMessageBox(&d, &id);
    /* SDL calls SoaActivity without asking for an exception afterwards */
    if (caught("messageboxShowMessageBox")) shown = 0;
    alive();
    if (!shown || id < 1 || id > n) {
        fprintf(stderr, "[import] the box was not answered (%s)\n", shown ? "no button" : SDL_GetError());
        closed();
    }
    fprintf(stderr, "[import] answered: %s\n", buttons[id - 1]);
    return id - 1;
}

/* A picked file refused, by the caller, who has closed its descriptor and let
 * its permission and its pending file go (decision 18). Said in the log with
 * the name the player knows it by, and in the next box; a check run ends here,
 * with 1. */
static void refused(const char* name, const char* words, char* said, size_t cap)
{
    fprintf(stderr, "[import] refused %s: %s\n", name, words);
    if (g.check) finish(1);
    snprintf(said, cap, "%s cannot be used: %s", name, words);
}

/* Nothing picked: Back in the picker, the launcher's icon, an open or a copy
 * cancelled, or a check run's queue run dry. The player is asked again; a
 * check run ends here, with 1. */
static void cancelled(int kind, const char* why)
{
    fprintf(stderr, "[import] cancelled (%s)\n", KIND[kind]);
    if (why && *why) fprintf(stderr, "[import] %s\n", why);
    if (g.check) finish(1);
}

/* ---- files of the import ------------------------------------------------- */

/* no_backup/pending_<kind>: a pick SoaActivity received and kept the
 * permission for, written before anything is told of it, so a pick that comes
 * back to a process started after the one that asked is not lost. Gone once
 * the pick is accepted or refused. */
static void pending_path(int kind, char* out, size_t cap) { snprintf(out, cap, "%s/pending_%s", g.nb, KIND[kind]); }

static int pending(int kind, char* uri, size_t cap)
{
    char path[1100];
    pending_path(kind, path, sizeof path);
    return first_line(path, uri, cap);
}

static void pending_clear(int kind)
{
    char path[1100];
    pending_path(kind, path, sizeof path);
    unlink(path);
}

/* A pick that is done with, whichever way: its permission released, unless
 * the disc accepted before is that same file, and its pending file gone. */
static void drop(const char* uri, int kind, const Stored* st)
{
    if (!st || strcmp(st->uri, uri) != 0) java_release(uri);
    pending_clear(kind);
}

static int stored_read(Stored* s)
{
    char path[1100];
    static char line[URI_MAX + 64];
    FILE* f;
    memset(s, 0, sizeof *s);
    snprintf(path, sizeof path, "%s/disc.txt", g.nb);
    f = fopen(path, "r");
    if (!f) return 0;
    while (fgets(line, sizeof line, f)) {
        char* eq;
        line[strcspn(line, "\r\n")] = '\0';
        if (!(eq = strchr(line, '='))) continue; /* the key ends at the first '=': a URI may hold more */
        *eq++ = '\0';
        if (!strcmp(line, "uri")) snprintf(s->uri, sizeof s->uri, "%s", eq);
        else if (!strcmp(line, "name")) snprintf(s->name, sizeof s->name, "%s", eq);
        else if (!strcmp(line, "authority")) snprintf(s->authority, sizeof s->authority, "%s", eq);
        else if (!strcmp(line, "copy")) snprintf(s->copy, sizeof s->copy, "%s", eq);
    }
    fclose(f);
    if (!s->name[0]) snprintf(s->name, sizeof s->name, "the disc");
    return s->uri[0] || s->copy[0];
}

/* disc.txt, whole or not at all (import_write_text): written only for a disc
 * disc_open accepted, so the next launch never reopens a refused one. */
static int stored_write(const Stored* s, char* why, size_t cap)
{
    char path[1100];
    static char text[URI_MAX + 1800];
    snprintf(path, sizeof path, "%s/disc.txt", g.nb);
    snprintf(text, sizeof text, "uri=%s\nname=%s\nauthority=%s\ncopy=%s\n", s->uri, s->name, s->authority, s->copy);
    return import_write_text(path, text, why, cap);
}

/* ---- the checks ---------------------------------------------------------- */

/* soa_load_game, its words naming the file as the player knows it. */
static int load(const char* path, const char* name, char* why, size_t cap)
{
    if (soa_load_game(path, why, cap) != 0) {
        import_name_in(why, cap, path, name);
        return 1;
    }
    g.loaded = 1;
    return 0;
}

/* The disc at path, as disc_open sees it, and closed again (decision 19). The
 * run's own SOA_DISC_VERIFY and SOA_DISC_FLIP are main's, armed when it opens
 * the disc for the game: set aside here and put back, so a check run's
 * corruption is armed once, and a verify switch is not taken for a reason to
 * pick another disc. */
/* Whether the last disc refused was refused by check_disc for its file table
 * not being the library's (I3): then the library may be the half that is
 * wrong, and the box offers another. Taken from check_disc's own disc_open,
 * never read from disc.c later: a pick refused before any disc_open (not
 * opened, the library picked as the disc, a stream refused as it came) would
 * otherwise find the last check's answer still there. */
static int g_by_build;

static int check_disc(const char* path, char* why, size_t cap)
{
    static char verify[1024], flip[1024];
    const char *v = getenv("SOA_DISC_VERIFY"), *f = getenv("SOA_DISC_FLIP");
    int had_v = v != NULL, had_f = f != NULL, rc;
    if (had_v) snprintf(verify, sizeof verify, "%s", v);
    if (had_f) snprintf(flip, sizeof flip, "%s", f);
    unsetenv("SOA_DISC_VERIFY");
    unsetenv("SOA_DISC_FLIP");
    rc = disc_open(path, why, cap);
    g_by_build = rc != 0 && disc_refused_by_build();
    disc_close();
    if (had_v) setenv("SOA_DISC_VERIFY", verify, 1);
    if (had_f) setenv("SOA_DISC_FLIP", flip, 1);
    return rc;
}

/* A copy's progress, shown with a Cancel the copy stops at (import_copy). */
static int shown(uint64_t done, int64_t expect, void* user)
{
    const CopyUi* ui = (const CopyUi*)user;
    char text[600], a[32], b[32];
    if (expect >= 0)
        snprintf(text, sizeof text, "Copying %s into the app: %s of %s", ui->name, amount(done, a, sizeof a),
                 amount((uint64_t)expect, b, sizeof b));
    else
        snprintf(text, sizeof text, "Copying %s into the app: %s so far", ui->name, amount(done, a, sizeof a));
    return java_status(text, expect > 0 ? (int)(done * 1000 / (uint64_t)expect) : -1);
}

/* How far into a Windows file elf_check reads to name it as one: to the end
 * of its COFF header, 24 bytes from where the file's e_lfanew, the last four
 * of the first 64, says it starts. */
static uint64_t pe_named_by(const uint8_t* h)
{
    return ((uint64_t)h[60] | (uint64_t)h[61] << 8 | (uint64_t)h[62] << 16 | (uint64_t)h[63] << 24) + 24;
}

/* A real Windows file's header is within its first few hundred bytes: one
 * said to be further than this is not waited for, and is refused in the
 * words for a file that is no library at all. */
#define PE_PEEK_MAX ((uint64_t)64 << 10)

/* A stream's first bytes, before the rest of a library is copied: an ELF for
 * this device, 64-bit, little-endian, a shared object. Anything else is
 * refused in runtime/elfcheck.c's words for it, which name the .tmp, put right
 * by the caller, and are the words a file read whole gets: an ELF's first
 * refusal is about its first 64 bytes, the ones here, and a Windows file's
 * about the header it says is further in, which take_library has the copy
 * bring in before it asks. */
static int peek_library(const char* tmp, uint64_t have, void* user, char* why, size_t cap)
{
    uint8_t h[64];
    size_t n = 0;
    FILE* f = fopen(tmp, "rb");
    (void)have;
    (void)user;
    if (f) {
        n = fread(h, 1, sizeof h, f);
        fclose(f);
    }
    if (n == sizeof h && !memcmp(h, "\177ELF", 4) && h[4] == 2 && h[5] == 1 &&
        (unsigned)(h[18] | h[19] << 8) == HOST_MACHINE && (h[16] | h[17] << 8) == 3)
        return 0;
    return soa_check_game(tmp, why, cap) != 0;
}

/* A stream's first MiB, before the rest of a disc is copied: this game, this
 * revision, an image or a store (disc_identify). */
static int peek_disc(const char* tmp, uint64_t have, void* user, char* why, size_t cap)
{
    (void)have;
    (void)user;
    return disc_identify(tmp, why, cap) != 0;
}

/* ---- the game library (decision 8, the flow's LIBRARY) -------------------- */

/* One library the player picked, from its descriptor to the one installed:
 * 1 once it is loaded and in place; 0 refused, why in the player's words; -1
 * cancelled. Its descriptor is closed and its permission and pending file
 * gone, whichever. */
static int take_library(const char* uri, const Doc* d, char* why, size_t cap)
{
    char fdpath[32], dir[1100], tmp[1200];
    const char *slash = strrchr(g.game, '/'), *base;
    uint8_t head[IMPORT_HEAD];
    size_t got = 0;
    uint64_t copied = 0;
    int64_t size = -1;
    int fd, kind, rc, now, placed = 1;
    ImportCopy c;
    CopyUi ui;
    fd = open_fd(uri, why, cap);
    if (fd < 0) {
        drop(uri, LIBRARY, NULL);
        return fd == OPEN_CANCELLED ? -1 : 0;
    }
    snprintf(fdpath, sizeof fdpath, "/proc/self/fd/%d", fd);
    /* the copy beside the library it replaces, since a rename cannot cross folders */
    if (slash) {
        snprintf(dir, sizeof dir, "%.*s", (int)(slash - g.game), g.game);
        base = slash + 1;
    } else {
        snprintf(dir, sizeof dir, ".");
        base = g.game;
    }
    snprintf(tmp, sizeof tmp, "%s/%s.tmp", dir, base);
    kind = import_classify(fd, &size);
    ui.name = d->name;
    memset(&c, 0, sizeof c);
    c.fd = fd;
    c.expect = kind == IMPORT_FILE ? size : d->size;
    c.progress = shown;
    c.user = &ui;
    rc = import_head(&c, head, sizeof head, &got, why, cap);
    if (rc == IMPORT_OK) {
        int what = import_sniff(head, got);
        if (what == IMPORT_STORE || what == IMPORT_ISO || what == IMPORT_RVZ) {
            snprintf(why, cap, "%s is the disc, not the game library: pick libsoa_game.so, which Setup makes for this phone",
                     d->name);
            rc = IMPORT_REFUSED;
        } else if (kind == IMPORT_FILE && soa_check_game(fdpath, why, cap) != 0) {
            rc = IMPORT_REFUSED; /* refused through its descriptor, before a byte is copied */
        }
    }
    if (rc == IMPORT_OK) {
        c.head = head;
        c.nhead = got;
        c.dir = dir;
        c.name = base;
        c.limit = IMPORT_LIBRARY_LIMIT;
        c.peek_at = IMPORT_LIBRARY_PEEK;
        c.peek = kind == IMPORT_FILE ? NULL : peek_library; /* a file was checked whole above */
        if (c.peek && got >= 64 && import_sniff(head, got) == IMPORT_PE) {
            /* asked once the header it names a Windows file by is in */
            uint64_t at = pe_named_by(head);
            if (at > c.peek_at && at <= PE_PEEK_MAX) c.peek_at = at;
        }
        rc = import_copy(&c, &copied, why, cap);
    }
    java_status(NULL, -1);
    close(fd);
    if (rc != IMPORT_OK) {
        name_in(why, cap, d->name, fdpath, tmp, NULL);
        drop(uri, LIBRARY, NULL);
        return rc == IMPORT_CANCELLED ? -1 : 0;
    }
    if (c.expect > 0) /* 0 is no size, as import.c holds a copy to (held_to) */
        fprintf(stderr, "[import] copied %llu of %lld bytes to %s\n", (unsigned long long)copied, (long long)c.expect, tmp);
    else
        fprintf(stderr, "[import] copied %llu bytes, its size not given, to %s\n", (unsigned long long)copied, tmp);
    now = !soa_game_dlopened();
    if (now) {
        /* loaded from the copy, and only then put in place: the mapping stays
         * good through the rename */
        if (load(tmp, d->name, why, cap) != 0) {
            unlink(tmp);
            drop(uri, LIBRARY, NULL);
            return 0;
        }
        if (import_place(tmp, g.game, 0, why, cap) != 0) {
            fprintf(stderr, "[import] %s; this run plays it all the same, and the next asks again\n", why);
            placed = 0;
        }
    } else if (soa_check_game(tmp, why, cap) != 0 || import_place(tmp, g.game, 1, why, cap) != 0) {
        /* a library is loaded already, and a process loads one at most: this
         * one is checked as a file, put in place with the old one kept as
         * .old, and loaded by the next launch */
        name_in(why, cap, d->name, tmp, NULL, NULL);
        unlink(tmp);
        drop(uri, LIBRARY, NULL);
        return 0;
    }
    drop(uri, LIBRARY, NULL); /* the copy no longer needs the permission */
    if (placed) fprintf(stderr, "[import] library %s: installed as %s\n", d->name, g.game);
    if (!now) {
        static const char* const close1[] = {"Close"};
        box("The new game library is in place. Open the app again to use it.", close1, 1);
        finish(0);
    }
    return 1;
}

/* The game library, loaded before anything of the disc is opened (decision
 * 20): the one installed, unless the run was asked to pick again; otherwise,
 * or when it will not load, one the player picks. Returns with a library
 * loaded; a run that has to start again ends here. */
static void library(int forced)
{
    static char said[2048], text[4096], uri[URI_MAX];
    char why[1024], old[1200];
    int keep = 0, again = 0;
    said[0] = '\0';
    snprintf(old, sizeof old, "%s.old", g.game);
    if (g.loaded) {
        keep = 1; /* asked from the disc's box, with one loaded: it stays on offer */
    } else {
        if (!exists(g.game) && exists(old) && rename(old, g.game) == 0)
            fprintf(stderr, "[import] %s put back: the library meant to replace it never arrived\n", g.game);
        if (forced) {
            keep = exists(g.game);
        } else if (!pending(LIBRARY, uri, sizeof uri) && exists(g.game)) {
            if (load(g.game, "libsoa_game.so", why, sizeof why) == 0) {
                unlink(old);
                return;
            }
            if (exists(old)) {
                /* the library a run already holding one put in place will not
                 * load: the one before it comes back */
                char why2[1024];
                rename(old, g.game);
                snprintf(said, sizeof said, "The game library you picked last could not be used: %s", why);
                if (!soa_game_dlopened() && load(g.game, "libsoa_game.so", why2, sizeof why2) == 0) {
                    static const char* const ok[] = {"OK"};
                    box(said, ok, 1);
                    return;
                }
                if (soa_game_dlopened()) {
                    static const char* const close1[] = {"Close"};
                    snprintf(text, sizeof text, "%s\n\nThe one before it is back. Open the app again.", said);
                    box(text, close1, 1);
                    finish(0);
                }
                snprintf(said + strlen(said), sizeof said - strlen(said), "\n\nThe one before it cannot be used either: %s",
                         why2);
            } else {
                snprintf(said, sizeof said, "The game library you imported no longer fits this version of the app: %s",
                         why);
            }
        }
    }
    for (;;) {
        Doc d;
        int r;
        if (pending(LIBRARY, uri, sizeof uri)) {
            fprintf(stderr, "[import] pending library pick from an earlier process: %s\n", uri);
        } else {
            static const char* const first[] = {"Pick", QUIT};
            static const char* const another[] = {"Pick another", QUIT};
            static const char* const choose[] = {"Pick a new one", QUIT, "Keep this one"};
            int a;
            snprintf(text, sizeof text, "%s%s%s\n\n%s", said, said[0] ? "\n\n" : "", LIB_PROMPT, MODS_NOTE);
            a = keep ? box(text, choose, 3) : box(text, again ? another : first, 2);
            if (a == 1) finish(0);
            if (keep && a == 2) {
                if (g.loaded || load(g.game, "libsoa_game.so", why, sizeof why) == 0) return;
                snprintf(said, sizeof said, "The game library you have cannot be used: %s", why);
                keep = again = 0;
                continue;
            }
            if (!java_pick(LIBRARY, uri, sizeof uri, why, sizeof why)) {
                cancelled(LIBRARY, why);
                snprintf(said, sizeof said, "%s", why);
                again = 0;
                continue;
            }
        }
        describe(uri, &d);
        r = take_library(uri, &d, why, sizeof why);
        if (r > 0) return;
        if (r < 0) {
            cancelled(LIBRARY, why);
            said[0] = '\0';
            again = 0;
            continue;
        }
        refused(d.name, why, said, sizeof said);
        again = 1;
    }
}

/* ---- the disc (decisions 16-19, the flow's DISC) ------------------------- */

/* A disc that passed its checks through fd, put where the port will read it:
 * in place, as /proc/self/fd/N, fd left open for the run; or, when import.c
 * says it may not be read there and allow_copy, copied into copy/ and fd
 * closed. 0 with the path and *copied; 1 refused, why in the player's words;
 * -1 cancelled. */
static int copy_disc(int fd, const char* uri, const Doc* d, const uint8_t* head, size_t got, int64_t size,
                     const char* reason, char* path, size_t pcap, char* why, size_t cap);

static int place(int fd, const char* uri, const Doc* d, const uint8_t* head, size_t got, int64_t size, int allow_copy,
                 char* path, size_t pcap, int* copied, char* why, size_t cap)
{
    const char* reason = NULL;
    *copied = 0;
    if (import_in_place(d->authority, fd, d->kept, &reason)) {
        snprintf(path, pcap, "/proc/self/fd/%d", fd);
        fprintf(stderr, "[android] disc %s: %s, grant kept, read in place as %s\n", d->name, uri, path);
        if (g.check) {
            /* what the port did before L12d, opening the path again by name:
             * measured for FINDINGS, and never relied on */
            char probe[1400];
            import_probe(fd, probe, sizeof probe);
            fprintf(stderr, "[import] reopen probe: %s\n", probe);
        }
        return 0;
    }
    if (!allow_copy) {
        snprintf(why, cap, "%s could not be read where it is (%s)", d->name, reason);
        close(fd);
        return 1;
    }
    *copied = 1;
    return copy_disc(fd, uri, d, head, got, size, reason, path, pcap, why, cap);
}

static int copy_disc(int fd, const char* uri, const Doc* d, const uint8_t* head, size_t got, int64_t size,
                     const char* reason, char* path, size_t pcap, char* why, size_t cap)
{
    char dir[1100], tmp[1200], final[1200], fdpath[32];
    const char* name = import_copy_name(import_sniff(head, got)); /* by its content, never the provider's name */
    int file = import_classify(fd, NULL) == IMPORT_FILE, rc;
    uint64_t copied = 0;
    ImportCopy c;
    CopyUi ui;
    snprintf(fdpath, sizeof fdpath, "/proc/self/fd/%d", fd);
    snprintf(dir, sizeof dir, "%s/copy", g.nb);
    if (mkdir(dir, 0700) != 0 && errno != EEXIST) {
        snprintf(why, cap, "cannot make %s: %s", dir, strerror(errno));
        close(fd);
        return 1;
    }
    snprintf(final, sizeof final, "%s/%s", dir, name);
    snprintf(tmp, sizeof tmp, "%s.tmp", final);
    fprintf(stderr, "[android] disc %s: %s, %s: copying to %s\n", d->name, uri, reason, tmp);
    ui.name = d->name;
    memset(&c, 0, sizeof c);
    c.fd = fd;
    c.head = head;
    c.nhead = got;
    c.dir = dir;
    c.name = name;
    c.expect = file ? size : d->size; /* a stream's provider is held to the size it gave */
    c.limit = IMPORT_DISC_LIMIT;
    c.peek_at = IMPORT_DISC_PEEK;
    c.peek = file ? NULL : peek_disc; /* a file was checked whole through its descriptor */
    c.progress = shown;
    c.user = &ui;
    rc = import_copy(&c, &copied, why, cap);
    java_status(NULL, -1);
    close(fd);
    if (rc == IMPORT_OK) {
        if (c.expect > 0) /* 0 is no size, as import.c holds a copy to (held_to) */
            fprintf(stderr, "[import] copied %llu of %lld bytes to %s\n", (unsigned long long)copied, (long long)c.expect,
                    tmp);
        else
            fprintf(stderr, "[import] copied %llu bytes, its size not given, to %s\n", (unsigned long long)copied, tmp);
        /* the copy is the disc the port will read: checked as such before it
         * takes the place of any copy before it */
        if (check_disc(tmp, why, cap) != 0 || import_place(tmp, final, 0, why, cap) != 0) {
            unlink(tmp);
            rc = IMPORT_REFUSED;
        }
    }
    if (rc != IMPORT_OK) {
        name_in(why, cap, d->name, fdpath, tmp, final);
        return rc == IMPORT_CANCELLED ? -1 : 1;
    }
    snprintf(path, pcap, "%s", final);
    return 0;
}

/* One disc the player picked: 1 with the path the port opens and disc.txt
 * written; 0 refused, why in the player's words; -1 cancelled. A refused
 * pick's descriptor, permission and pending file go at once; an accepted
 * one's predecessor's copy and permission go once disc.txt names it. */
static int take_disc(const char* uri, const Doc* d, const Stored* st, char* path, size_t pcap, char* why, size_t cap)
{
    char fdpath[32];
    uint8_t head[IMPORT_HEAD];
    size_t got = 0;
    int64_t size = -1;
    int fd, kind, rc, copied = 0;
    ImportCopy c;
    CopyUi ui;
    Stored now;
    g_by_build = 0;
    fd = open_fd(uri, why, cap);
    if (fd < 0) {
        drop(uri, DISC, st);
        return fd == OPEN_CANCELLED ? -1 : 0;
    }
    snprintf(fdpath, sizeof fdpath, "/proc/self/fd/%d", fd);
    kind = import_classify(fd, &size);
    ui.name = d->name;
    memset(&c, 0, sizeof c);
    c.fd = fd;
    c.expect = kind == IMPORT_FILE ? size : d->size;
    c.progress = shown;
    c.user = &ui;
    rc = import_head(&c, head, sizeof head, &got, why, cap);
    java_status(NULL, -1); /* shown only while a stream kept its first bytes back */
    if (rc == IMPORT_OK && import_sniff(head, got) == IMPORT_ELF) {
        snprintf(why, cap, "%s is the game library, not the disc: pick the store (.soadisc) or the image (.iso, .gcm) of "
                           "your disc", d->name);
        rc = IMPORT_REFUSED;
    }
    /* id, revision, executable, file table, extents: all through the
     * descriptor, before a byte is copied */
    if (rc == IMPORT_OK && kind == IMPORT_FILE && check_disc(fdpath, why, cap) != 0) rc = IMPORT_REFUSED;
    if (rc != IMPORT_OK) {
        close(fd);
        name_in(why, cap, d->name, fdpath, NULL, NULL);
        drop(uri, DISC, st);
        return rc == IMPORT_CANCELLED ? -1 : 0;
    }
    rc = place(fd, uri, d, head, got, kind == IMPORT_FILE ? size : -1, 1, path, pcap, &copied, why, cap);
    if (rc != 0) {
        drop(uri, DISC, st);
        return rc < 0 ? -1 : 0;
    }
    memset(&now, 0, sizeof now);
    snprintf(now.uri, sizeof now.uri, "%s", uri);
    snprintf(now.name, sizeof now.name, "%s", d->name);
    snprintf(now.authority, sizeof now.authority, "%s", d->authority);
    if (copied) snprintf(now.copy, sizeof now.copy, "%s", path);
    if (stored_write(&now, why, cap) != 0) fprintf(stderr, "[import] %s; the next launch asks for the disc again\n", why);
    if (copied) java_release(uri); /* the copy no longer needs it */
    if (st->uri[0] && strcmp(st->uri, uri) != 0) java_release(st->uri);
    if (st->copy[0] && strcmp(st->copy, now.copy) != 0 && unlink(st->copy) == 0)
        fprintf(stderr, "[import] removed %s, the copy of the disc before\n", st->copy);
    pending_clear(DISC);
    return 1;
}

/* The disc accepted before, checked again: its copy, or, with none, its URI
 * opened again and placed (and, when it may not be read in place any more
 * and allow_copy, copied, disc.txt saying so). 0 with the path, *fd the
 * descriptor read in place or -1; 1 with why in the player's words. */
static int stored_disc(Stored* st, int allow_copy, char* path, size_t pcap, int* fd, char* why, size_t cap)
{
    int rewrite = 0;
    *fd = -1;
    g_by_build = 0;
    if (st->copy[0] && exists(st->copy)) {
        snprintf(path, pcap, "%s", st->copy);
        fprintf(stderr, "[android] disc %s: %s, copied before, read as %s\n", st->name, st->uri, path);
    } else if (!st->uri[0]) {
        snprintf(why, cap, "the copy of %s in this app is gone", st->name);
        return 1;
    } else {
        Doc d;
        uint8_t head[IMPORT_HEAD];
        size_t got = 0;
        int64_t size = -1;
        int n, copied = 0, rc;
        char reason[600], fdpath[32];
        ImportCopy c;
        CopyUi ui;
        describe(st->uri, &d);
        snprintf(d.name, sizeof d.name, "%s", st->name); /* the name it was picked by */
        n = open_fd(st->uri, reason, sizeof reason);
        if (n < 0) {
            snprintf(why, cap, "%s cannot be read now: %s", st->name, reason);
            return 1;
        }
        snprintf(fdpath, sizeof fdpath, "/proc/self/fd/%d", n);
        ui.name = st->name;
        memset(&c, 0, sizeof c);
        c.fd = n;
        c.expect = import_classify(n, &size) == IMPORT_FILE ? size : d.size;
        c.progress = shown;
        c.user = &ui;
        /* its first bytes, which name a copy should it need one */
        rc = import_head(&c, head, sizeof head, &got, reason, sizeof reason);
        java_status(NULL, -1);
        if (rc != IMPORT_OK) {
            close(n);
            name_in(reason, sizeof reason, st->name, fdpath, NULL, NULL);
            snprintf(why, cap, "%s cannot be read now: %s", st->name, reason);
            return 1;
        }
        rc = place(n, st->uri, &d, head, got, c.expect, allow_copy, path, pcap, &copied, why, cap);
        if (rc != 0) {
            if (rc < 0) snprintf(why, cap, "copying %s was cancelled", st->name);
            return 1;
        }
        if (copied) java_release(st->uri); /* the copy, checked as it was made, no longer needs it */
        else *fd = n;
        rewrite = copied || st->copy[0]; /* read another way than disc.txt says */
        if (rewrite) snprintf(st->copy, sizeof st->copy, "%s", copied ? path : "");
    }
    if (check_disc(path, why, cap) != 0) {
        name_in(why, cap, st->name, path, NULL, NULL);
        if (*fd >= 0) close(*fd);
        *fd = -1;
        return 1;
    }
    if (rewrite && stored_write(st, why, cap) != 0) fprintf(stderr, "[import] %s\n", why);
    return 0;
}

/* The disc, into path: the one accepted before, checked again; or, when the
 * run was asked to pick again or that one fails, one the player picks.
 * Returns the URI it was picked by, whose permission and copy the run keeps
 * whether or not disc.txt could be written to say so. */
static const char* disc(int forced, char* path, size_t pcap)
{
    static Stored st;
    static char said[2048], text[4096], uri[URI_MAX], held[1200];
    char why[1024];
    int have = stored_read(&st), works = 0, by_build = 0, again = 0, held_fd = -1;
    said[0] = held[0] = '\0';
    /* the disc imported before: checked, unless a pick is waiting; when the
     * run was asked to pick again only to know whether to offer to keep it,
     * which a check run never takes */
    if (have && !pending(DISC, uri, sizeof uri) && !(forced && g.check)) {
        works = stored_disc(&st, !forced, held, sizeof held, &held_fd, why, sizeof why) == 0;
        if (works && !forced) {
            snprintf(path, pcap, "%s", held);
            return st.uri;
        }
        if (!works) {
            snprintf(said, sizeof said, "%s", why);
            by_build = g_by_build;
        }
    }
    for (;;) {
        Doc d;
        int r;
        if (pending(DISC, uri, sizeof uri)) {
            fprintf(stderr, "[import] pending disc pick from an earlier process: %s\n", uri);
        } else {
            const char* b[4];
            int n = 0, a, lib = -1, keep = -1;
            b[n++] = again ? "Pick another" : "Pick";
            b[n++] = QUIT;
            if (by_build) lib = n, b[n++] = "Pick another library"; /* the library may be the half that is wrong */
            if (forced && works) keep = n, b[n++] = "Keep this one";
            snprintf(text, sizeof text, "%s%s%s", said, said[0] ? "\n\n" : "", DISC_PROMPT);
            a = box(text, b, n);
            if (a == 1) finish(0);
            if (a == keep) {
                snprintf(path, pcap, "%s", held);
                return st.uri;
            }
            if (a == lib) {
                library(1);
                by_build = 0;
                continue;
            }
            if (!java_pick(DISC, uri, sizeof uri, why, sizeof why)) {
                cancelled(DISC, why);
                snprintf(said, sizeof said, "%s", why);
                again = 0;
                continue;
            }
        }
        describe(uri, &d);
        r = take_disc(uri, &d, &st, path, pcap, why, sizeof why);
        if (r > 0) {
            if (held_fd >= 0) close(held_fd);
            return uri;
        }
        if (r < 0) {
            cancelled(DISC, why);
            said[0] = '\0';
            again = 0;
            continue;
        }
        by_build = g_by_build;
        refused(d.name, why, said, sizeof said);
        again = 1;
    }
}

/* ---- before the port ----------------------------------------------------- */

/* L12c kept the library in filesDir; it lives in noBackupFilesDir now
 * (decision 23), which neither a backup nor a move to a new phone carries.
 * Moved once, or dropped when one is there already. */
static void move_library(void)
{
    char old[1100];
    snprintf(old, sizeof old, "%s/libsoa_game.so", g.root);
    snprintf(g.game, sizeof g.game, "%s/libsoa_game.so", g.nb);
    if (!strcmp(old, g.game) || !exists(old)) return;
    if (exists(g.game)) {
        if (unlink(old) == 0) fprintf(stderr, "[android] library %s removed: %s is the one used\n", old, g.game);
        return;
    }
    if (rename(old, g.game) == 0) {
        fprintf(stderr, "[android] library moved from %s to %s\n", old, g.game);
    } else {
        fprintf(stderr, "[android] cannot move %s to %s: %s; it is used where it is\n", old, g.game, strerror(errno));
        snprintf(g.game, sizeof g.game, "%s", old);
    }
}

/* What the import keeps, and nothing more (decision 18): the permission for
 * the disc this run plays (uri), for the one disc.txt names and for the picks
 * waiting, every other released; this run's disc (path) and the copy disc.txt
 * names, every other file in copy/ removed. The run's own disc is kept
 * whatever disc.txt says, since disc.txt may not have been written (a device
 * too full for it): the next launch asks for the disc again then, but this
 * one plays the disc it was given. */
static void tidy(const char* uri, const char* path)
{
    static Stored st;
    static char lib[URI_MAX], dsc[URI_MAX];
    char dir[1100], p[1400];
    const char* keep[4];
    int n = 0, k;
    DIR* dp;
    struct dirent* e;
    if (uri && *uri) keep[n++] = uri;
    if (stored_read(&st) && st.uri[0]) keep[n++] = st.uri;
    if (pending(LIBRARY, lib, sizeof lib)) keep[n++] = lib;
    if (pending(DISC, dsc, sizeof dsc)) keep[n++] = dsc;
    k = java_tidy(keep, n);
    if (k > 0) fprintf(stderr, "[import] released %d permission(s) no disc uses\n", k);
    snprintf(dir, sizeof dir, "%s/copy", g.nb);
    if (!(dp = opendir(dir))) return;
    while ((e = readdir(dp)) != NULL) {
        struct stat s;
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        snprintf(p, sizeof p, "%s/%s", dir, e->d_name);
        if (!strcmp(p, path) || !strcmp(p, st.copy) || lstat(p, &s) != 0 || !S_ISREG(s.st_mode)) continue;
        if (unlink(p) == 0) fprintf(stderr, "[import] removed %s, which no disc uses\n", p);
    }
    closedir(dp);
}

/* SOA_IMPORT=forget: the permission to read the disc disc.txt names released,
 * disc.txt kept, as a permission lost would leave it (a check's mutation). */
static _Noreturn void forget(void)
{
    static Stored st;
    if (stored_read(&st) && st.uri[0]) {
        java_release(st.uri);
        fprintf(stderr, "[import] released the permission to read %s (%s); disc.txt is kept\n", st.name, st.uri);
    } else {
        fprintf(stderr, "[import] nothing to forget: disc.txt names no disc\n");
    }
    finish(0);
}

/* The port, with the disc the import placed (R8: argv[1] names the disc, and
 * beats soa.ini's), picked by disc_uri. A check's --check-disc checks it; a
 * check's other options and the self test take argv as given. The first
 * launch writes soa.ini with the window on, since without one settings.c
 * never defaults SOA_RENDER and no window opens; a check run never writes it. */
static _Noreturn void run(int argc, char** argv, char* disc_path, const char* disc_uri)
{
    static char* args[64];
    char ini[1100], why[600];
    int n = 0, i;
    tidy(disc_uri, disc_path);
    snprintf(ini, sizeof ini, "%s/soa.ini", g.root);
    if (!g.check && !exists(ini)) {
        if (import_write_text(ini, "render = 1\n", why, sizeof why) == 0)
            fprintf(stderr, "[import] wrote %s: render = 1\n", ini);
        else
            fprintf(stderr, "[import] %s\n", why);
    }
    args[n++] = argv[0];
    if (argc > 1 && !strcmp(argv[1], "--check-disc")) {
        args[n++] = argv[1];
        args[n++] = disc_path;
    } else if ((argc > 1 && argv[1][0] == '-') || getenv("SOA_SELFTEST")) {
        for (i = 1; i < argc && n < 63; i++) args[n++] = argv[i];
    } else {
        args[n++] = disc_path; /* a disc a check named is the imported one's to replace */
        for (i = 2; i < argc && n < 63; i++) args[n++] = argv[i];
    }
    args[n] = NULL;
    finish(soa_run(n, args));
}

int SDL_main(int argc, char** argv)
{
    static char path[1200];
    const char* root = SDL_GetAndroidInternalStoragePath();
    const char *nb = getenv("SOA_NOBACKUP"), *game = getenv("SOA_GAME"), *imp = getenv("SOA_IMPORT"), *from;
    int swept, k;
    SDL_SetMainReady();
    SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");
    if (!root || chdir(root) != 0) {
        __android_log_print(ANDROID_LOG_ERROR, "soa", "[android] no data root (%s)", root ? root : "none");
        _exit(1);
    }
    setenv("SOA_ROOT", root, 1);
    logs_start();
    fprintf(stderr, "[android] data root %s\n", root);
    fprintf(stderr, "[android] runtime record %s\n", soa_runtime_record);
    disc_set_phone_words(1); /* before anything opens: no refusal on a phone names the PC's tools */
    g.root = root;
    snprintf(g.nb, sizeof g.nb, "%s", nb && *nb ? nb : root); /* SoaActivity sets it; filesDir as L12c had it */
    if (game && *game) {
        snprintf(g.game, sizeof g.game, "%s", game); /* a check's own library, where it put it */
    } else {
        move_library();
        setenv("SOA_GAME", g.game, 1);
    }
    g.check = flag("SOA_CHECK_RUN");
    if (imp && (!*imp || !strcmp(imp, "0"))) imp = NULL;
    if (g.check && !imp) finish(soa_run(argc, argv)); /* every L12c check, as it was */
    if (imp && strcmp(imp, "1") && strcmp(imp, "library") && strcmp(imp, "disc") && strcmp(imp, "forget")) {
        fprintf(stderr, "[import] SOA_IMPORT=%s: it is 1, library, disc or forget\n", imp);
        finish(1);
    }
    if (!java_init()) {
        fprintf(stderr, "[import] SoaActivity's side of the import is missing (logcat says what)\n");
        if (!g.check) damaged();
        finish(1);
    }
    g.picker = !g.check || flag("SOA_IMPORT_PICKER");
    if (imp && !strcmp(imp, "forget")) forget();
    /* what a process killed mid-copy left: its .tmp files, never anything whole */
    swept = import_sweep(g.nb);
    snprintf(path, sizeof path, "%s/copy", g.nb);
    k = import_sweep(path);
    swept = (swept > 0 ? swept : 0) + (k > 0 ? k : 0);
    if (swept) fprintf(stderr, "[import] removed %d unfinished file(s) an import that stopped left\n", swept);
    library((imp && !strcmp(imp, "library")) || flag("SOA_REIMPORT"));
    from = disc((imp && !strcmp(imp, "disc")) || flag("SOA_REIMPORT"), path, sizeof path);
    run(argc, argv, path, from);
}
#endif
