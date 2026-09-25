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
