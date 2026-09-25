/*
 * The player's settings file (docs/PLAN-60FPS-MODS.md M5): soa.ini beside
 * soa.exe, so the port can be started without a terminal.
 *
 *     # soa.ini
 *     disc = C:\Games\Skies\extracted
 *     render = 1
 *     mods = C:\Games\Skies\mods
 *
 * Each key stands for one of the switches README.md documents, and the file
 * sets that switch only where the environment has not: an environment
 * variable always wins, so a command line can override a player's file. A key
 * this port does not know is reported with its line and ignored, never
 * dropped in silence. `disc` is the extracted directory the port reads when
 * none is given on the command line.
 *
 * Checks never read it: SOA_SETTINGS=0 turns it off, and scenario.py,
 * perfbench.py and the self test all run with the file off, so a player's
 * settings can never move a check.
 *
 * A first run without a terminal (M5b): the port root is the exe's folder,
 * or the parent of the nearest folder named gen that sits beside runtime\ --
 * the repository every player builds in -- and soa.ini is <root>\soa.ini
 * first, then the one beside the exe. Its relative paths are the root's, not
 * the current directory's (a double-click starts in gen\), and when a file
 * was read the card, the disc, the mods folder and rendering have defaults
 * under the root. The environment keeps its own meaning throughout.
 */
#define _CRT_SECURE_NO_WARNINGS
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <io.h>
#include <windows.h>
#endif

typedef struct {
    const char* key;
    const char* env;
    const char* what;
    int recorded; /* changes what the game does, so a pad recording names it (settings_recorded) */
    const char* mod;     /* read by the DLL mod with this id, not by the port (settings_check_mods) */
    const char* choices; /* "a|b|c": the only values its reader takes; no other is recorded */
} Setting;

/* The switches a player would use. Each later enhancement adds its line here,
 * off by default (PLAN M5). */
static const Setting k_settings[] = {
    {"render", "SOA_RENDER", "1 draws the game"},
    {"window", "SOA_WINDOW", "0 or 1: force the window off or on"},
    {"scale", "SOA_SCALE", "the window's starting size in multiples of 640x480; by default the largest that fits"},
    {"threads", "SOA_THREADS", "rasterizer threads"},
    {"mods", "SOA_MODS", "a folder of mods"},
    {"card", "SOA_CARD", "the memory card image for slot A"},
    {"record", "SOA_PAD_RECORD", "record controller input to this file"},
    {"nosound", "SOA_NOSOUND", "1 opens no audio device"},
    {"uncap", "SOA_UNCAP", "from this frame on, a frame waits one field: the whole game up to twice as fast"},
    {"seed", "SOA_SEED", "a number: the game's field-load and battle-start reseeds follow it (P6)", 1},
    {"encounters", "SOA_ENCOUNTERS", "off, half, normal or double: how often random battles come (mod encounter-rate)",
     1, "encounter-rate", "off|half|normal|double"},
    {"encounters_hold_b", "SOA_ENCOUNTERS_HOLD_B", "0: holding B no longer keeps random battles away (mod encounter-rate)",
     1, "encounter-rate", "0|1"},
    {"fullscreen", "SOA_FULLSCREEN", "1 starts in borderless fullscreen (F11, Alt+Enter or View+LB toggle it)"},
    {"scaler", "SOA_SCALER", "integer (whole multiples, the default) or fit (the largest 4:3 that fits)"},
    {"unfocused", "SOA_UNFOCUSED", "run (the default) or mute: with another window in front, mute ignores the pad and silences the game"},
    {"rumble", "SOA_RUMBLE", "0 to 100: how hard the pad rumbles when the game asks; default 100, 0 is off"},
    {"autotext", "SOA_AUTOTEXT", "0, on or a number of frames: a complete page of dialogue turns itself (mod autotext)", 1,
     "autotext", NULL},
};
#define N_SETTINGS (sizeof k_settings / sizeof k_settings[0])

static char g_disc[1024];
static int g_loaded; /* a soa.ini was read: the root's defaults apply */

static void set_env(const char* name, const char* value)
{
#ifdef _WIN32
    _putenv_s(name, value);
#else
    setenv(name, value, 1);
#endif
}

static void trim(char* s)
{
    size_t n = strlen(s), i = 0;
    while (n && isspace((unsigned char)s[n - 1])) s[--n] = '\0';
    while (s[i] && isspace((unsigned char)s[i])) i++;
    if (i) memmove(s, s + i, n - i + 1);
}

/* The keys whose values are paths: relative in soa.ini means under the root. */
static const char* const k_path_keys[] = {"mods", "card", "record"};

static char* last_sep(char* s)
{
    char* a = strrchr(s, '\\');
    char* b = strrchr(s, '/');
    return a > b ? a : b;
}

static int is_dir(const char* p)
{
#ifdef _WIN32
    DWORD a = GetFileAttributesA(p);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
#else
    FILE* f = fopen(p, "r");
    if (f) fclose(f);
    return f != NULL;
#endif
}

static int file_exists(const char* p)
{
    FILE* f = fopen(p, "rb");
    if (f) fclose(f);
    return f != NULL;
}

/* Two paths spelled alike, case aside (Windows paths ignore case). */
static int same_text(const char* a, const char* b)
{
    while (*a && tolower((unsigned char)*a) == tolower((unsigned char)*b)) a++, b++;
    return tolower((unsigned char)*a) == tolower((unsigned char)*b);
}

static int is_absolute(const char* p)
{
    return p[0] == '\\' || p[0] == '/' || (p[0] && p[1] == ':');
}

/* The port root for an executable at `exe`: the parent of the nearest
 * ancestor folder named gen whose parent holds runtime\ -- so gen\soa.exe
 * and gen\clang\soa.exe find the same root -- else the exe's own folder. */
int settings_root_for(const char* exe, char* out, size_t cap)
{
    char dir[1024], cur[1024], probe[1100];
    char* sep;
    snprintf(dir, sizeof dir, "%s", exe);
    sep = last_sep(dir);
    if (!sep) {
        snprintf(out, cap, ".");
        return 1;
    }
    *sep = '\0';
    snprintf(cur, sizeof cur, "%s", dir);
    while ((sep = last_sep(cur)) != NULL) {
        const char* name = sep + 1;
        if ((name[0] == 'g' || name[0] == 'G') && (name[1] == 'e' || name[1] == 'E') && (name[2] == 'n' || name[2] == 'N') &&
            !name[3]) {
            *sep = '\0';
            snprintf(probe, sizeof probe, "%s/runtime", cur);
            if (is_dir(probe)) {
                snprintf(out, cap, "%s", cur);
                return 1;
            }
            continue;
        }
        *sep = '\0';
    }
    snprintf(out, cap, "%s", dir);
    return 1;
}

static char g_root[1024];

/* The port root: SOA_ROOT when set (tests), else settings_root_for the exe. */
const char* settings_root(void)
{
    if (!g_root[0]) {
        const char* env = getenv("SOA_ROOT");
        if (env && *env) snprintf(g_root, sizeof g_root, "%s", env);
        else {
#ifdef _WIN32
            char exe[1024];
            DWORD n = GetModuleFileNameA(NULL, exe, sizeof exe);
            if (n && n < sizeof exe) settings_root_for(exe, g_root, sizeof g_root);
            else snprintf(g_root, sizeof g_root, ".");
#else
            snprintf(g_root, sizeof g_root, ".");
#endif
        }
    }
    return g_root;
}

/* `rel` joined to the root, unless it is absolute. */
static void under_root(const char* rel, char* out, size_t cap)
{
    if (is_absolute(rel)) snprintf(out, cap, "%s", rel);
    else snprintf(out, cap, "%s\\%s", settings_root(), rel);
}

/* Which soa.ini: SOA_SETTINGS naming a file (tests); else <root>\soa.ini,
 * then the one beside the exe. 0 when there is none to read. */
static int settings_path(char* out, size_t cap)
{
    const char* env = getenv("SOA_SETTINGS");
    char beside[1024];
    if (env && *env) {
        snprintf(out, cap, "%s", env);
        return 1;
    }
    snprintf(out, cap, "%s\\soa.ini", settings_root());
#ifdef _WIN32
    {
        char exe[1024];
        char* sep;
        DWORD n = GetModuleFileNameA(NULL, exe, sizeof exe);
        if (!n || n >= sizeof exe) return file_exists(out);
        sep = last_sep(exe);
        if (sep) sep[1] = '\0';
        else exe[0] = '\0';
        snprintf(beside, sizeof beside, "%ssoa.ini", exe);
    }
#else
    snprintf(beside, sizeof beside, "soa.ini");
#endif
    if (file_exists(out)) {
        if (file_exists(beside) && !same_text(beside, out))
            fprintf(stderr, "[settings] %s is used; the one beside the exe, %s, is not\n", out, beside);
        return 1;
    }
    snprintf(out, cap, "%s", beside);
    return file_exists(out);
}

/* Whether to hide the console and send the log to a file (M5b): only when
 * the process owns its console (one process on it: started from Explorer or
 * a front end, not a terminal) and stderr is that console (a character
 * device, not a pipe or a file: scenario.py reading the port through a pipe
 * from a parent with no console also gets a console of its own). */
int should_hide_console(unsigned procs, unsigned stderr_type)
{
    return procs == 1 && stderr_type == 2 /* FILE_TYPE_CHAR */;
}

/* When should_hide_console says so: stderr and stdout to
 * <root>\build\logs\soa-YYYYMMDD-HHMMSS.log, unbuffered (every stop path
 * leaves through _exit), and the console freed. `path` gets the file. */
int settings_console_to_log(char* path, size_t cap)
{
#ifdef _WIN32
    DWORD procs[4];
    DWORD n = GetConsoleProcessList(procs, 4);
    SYSTEMTIME t;
    char dir[1100];
    if (!should_hide_console((unsigned)n, (unsigned)GetFileType(GetStdHandle(STD_ERROR_HANDLE)))) return 0;
    GetLocalTime(&t);
    snprintf(dir, sizeof dir, "%s\\build", settings_root());
    CreateDirectoryA(dir, NULL);
    snprintf(dir, sizeof dir, "%s\\build\\logs", settings_root());
    CreateDirectoryA(dir, NULL);
    snprintf(path, cap, "%s\\soa-%04u%02u%02u-%02u%02u%02u.log", dir, t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute,
             t.wSecond);
    {
        /* Writable before the console goes, or the run would have nowhere to say so. */
        FILE* f = fopen(path, "w");
        if (!f) return 0;
        fclose(f);
    }
    /* In this order, measured: the console freed first, then stderr reopened
     * on the file and stdout pointed at the same descriptor. Two opens of one
     * file keep two offsets and overwrite each other's lines, and reopening
     * with the console still attached lost every line after FreeConsole. */
    FreeConsole();
    if (!freopen(path, "w", stderr)) return 0;
    _dup2(_fileno(stderr), _fileno(stdout));
    setvbuf(stderr, NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);
    return 1;
#else
    (void)path;
    (void)cap;
    return 0;
#endif
}

/* What a recorded key's owner says is in effect, where it has said: seed.c
 * for `seed`, so the recording names the seed that was pinned rather than
 * the text in the environment -- a refused value names none, and 0x3039 and
 * 12345 name the same one. "" records nothing. */
static char g_record_as[N_SETTINGS][64];
static int g_record_as_set[N_SETTINGS];

void settings_record_as(const char* key, const char* value)
{
    size_t i;
    for (i = 0; i < N_SETTINGS; i++)
        if (!strcmp(k_settings[i].key, key)) {
            snprintf(g_record_as[i], sizeof g_record_as[i], "%s", value ? value : "");
            g_record_as_set[i] = 1;
        }
}

/* Whether `v` is one of `choices` ("a|b|c"); any value when there are none. */
static int is_choice(const char* choices, const char* v)
{
    size_t n = strlen(v);
    const char* p = choices;
    if (!choices) return 1;
    while (p && *p) {
        const char* bar = strchr(p, '|');
        size_t k = bar ? (size_t)(bar - p) : strlen(p);
        if (k == n && !strncmp(p, v, n)) return 1;
        p = bar ? bar + 1 : NULL;
    }
    return 0;
}

/* A setting a DLL mod reads does nothing without that mod, and says so once
 * mods have loaded -- and, doing nothing, is not recorded. `loaded` answers
 * whether a mod with an id is loaded (mod.c's mod_loaded). */
void settings_check_mods(int (*loaded)(const char* id))
{
    size_t i;
    for (i = 0; i < N_SETTINGS; i++) {
        const char* v = k_settings[i].mod ? getenv(k_settings[i].env) : NULL;
        if (!v || !*v || loaded(k_settings[i].mod)) continue;
        fprintf(stderr, "[settings] `%s = %s` is set, and no mod with id `%s` is loaded; it does nothing\n",
                k_settings[i].key, v, k_settings[i].mod);
        settings_record_as(k_settings[i].key, "");
    }
}

/* "key=value ..." for every recorded setting that is set, for the pad
 * recording's config line: a recording made with a seed says which, and one
 * made with none of them keeps the line it always had. A value its reader
 * refuses is not one it runs with, so it is not recorded either. Empty when
 * none is set. */
const char* settings_recorded(char* out, size_t cap)
{
    size_t i, used = 0;
    out[0] = '\0';
    for (i = 0; i < N_SETTINGS; i++) {
        const char* v = !k_settings[i].recorded ? NULL : g_record_as_set[i] ? g_record_as[i] : getenv(k_settings[i].env);
        int k;
        if (!v || !*v || !is_choice(k_settings[i].choices, v)) continue;
        k = snprintf(out + used, cap - used, "%s%s=%s", used ? " " : "", k_settings[i].key, v);
        if (k < 0 || (size_t)k >= cap - used) {
            out[used] = '\0'; /* no half a value: the replay would read it as a different one */
            fprintf(stderr, "[pad] the config line was cut at %zu bytes, before %s\n", used, k_settings[i].key);
            break;
        }
        used += (size_t)k;
    }
    return out;
}

/* Read soa.ini, if there is one and SOA_SETTINGS is not 0, into the
 * environment where the environment is silent. Returns the `disc` directory
 * it names, or NULL. */
const char* settings_load(void)
{
    const char* off = getenv("SOA_SETTINGS");
    char path[1100], line[1200];
    FILE* f;
    unsigned lineno = 0, applied = 0, overridden = 0;
    if (off && !strcmp(off, "0")) return NULL;
    if (!settings_path(path, sizeof path)) return NULL;
    g_loaded = 1;
    f = fopen(path, "r");
    if (!f) return NULL;
    while (fgets(line, sizeof line, f)) {
        char *eq, *hash, *key, *value;
        size_t i;
        lineno++;
        if ((hash = strchr(line, '#')) != NULL) *hash = '\0';
        trim(line);
        if (!line[0]) continue;
        if (!(eq = strchr(line, '='))) {
            fprintf(stderr, "[settings] %s:%u: `%s` is not `key = value`; ignored\n", path, lineno, line);
            continue;
        }
        *eq = '\0';
        key = line;
        value = eq + 1;
        trim(key);
        trim(value);
        if (!strcmp(key, "disc")) {
            under_root(value, g_disc, sizeof g_disc);
            continue;
        }
        for (i = 0; i < N_SETTINGS; i++)
            if (!strcmp(key, k_settings[i].key)) break;
        if (i == N_SETTINGS) {
            fprintf(stderr, "[settings] %s:%u: `%s` is not a setting this port knows (disc", path, lineno, key);
            for (i = 0; i < N_SETTINGS; i++) fprintf(stderr, ", %s", k_settings[i].key);
            fprintf(stderr, "); ignored\n");
            continue;
        }
        if (getenv(k_settings[i].env)) {
            overridden++;
            fprintf(stderr, "[settings] %s = %s is overridden by %s=%s in the environment\n", key, value,
                    k_settings[i].env, getenv(k_settings[i].env));
            continue;
        }
        {
            char path_value[1200];
            size_t k;
            for (k = 0; k < sizeof k_path_keys / sizeof k_path_keys[0]; k++)
                if (!strcmp(key, k_path_keys[k]) && *value) {
                    under_root(value, path_value, sizeof path_value);
                    value = path_value;
                    break;
                }
            set_env(k_settings[i].env, value);
        }
        applied++;
    }
    fclose(f);
    {
        /* Defaults under the root, for a file that did not name them. */
        char p[1200];
        size_t i;
        int mod_key = 0;
        if (!getenv("SOA_CARD")) {
            under_root("build\\cards\\slotA.raw", p, sizeof p);
            set_env("SOA_CARD", p);
        }
        if (!g_disc[0]) under_root("extracted", g_disc, sizeof g_disc);
        for (i = 0; i < N_SETTINGS; i++)
            if (k_settings[i].mod && getenv(k_settings[i].env) && *getenv(k_settings[i].env)) mod_key = 1;
        if (mod_key && !getenv("SOA_MODS")) {
            under_root("mods", p, sizeof p);
            set_env("SOA_MODS", p);
        }
        if (!getenv("SOA_RENDER")) set_env("SOA_RENDER", "1");
    }
    fprintf(stderr, "[settings] %s: %u setting(s) applied, %u overridden by the environment%s%s\n", path, applied,
            overridden, g_disc[0] ? "; disc " : "", g_disc);
    return g_disc[0] ? g_disc : NULL;
}
