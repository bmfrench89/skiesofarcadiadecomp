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
 */
#define _CRT_SECURE_NO_WARNINGS
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
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
    {"scale", "SOA_SCALE", "window scale, default 2"},
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
};
#define N_SETTINGS (sizeof k_settings / sizeof k_settings[0])

static char g_disc[1024];

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

/* Where soa.ini lives: beside the executable. */
static int settings_path(char* out, size_t cap)
{
#ifdef _WIN32
    char exe[1024];
    char* slash;
    DWORD n = GetModuleFileNameA(NULL, exe, sizeof exe);
    if (!n || n >= sizeof exe) return 0;
    slash = strrchr(exe, '\\');
    if (!slash) slash = strrchr(exe, '/');
    if (slash) slash[1] = '\0';
    else exe[0] = '\0';
    snprintf(out, cap, "%ssoa.ini", exe);
    return 1;
#else
    snprintf(out, cap, "soa.ini");
    return 1;
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
            snprintf(g_disc, sizeof g_disc, "%s", value);
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
        set_env(k_settings[i].env, value);
        applied++;
    }
    fclose(f);
    fprintf(stderr, "[settings] %s: %u setting(s) applied, %u overridden by the environment%s%s\n", path, applied,
            overridden, g_disc[0] ? "; disc " : "", g_disc);
    return g_disc[0] ? g_disc : NULL;
}
