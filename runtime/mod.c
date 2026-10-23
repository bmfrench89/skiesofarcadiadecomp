/*
 * Mods, data patches only (docs/PLAN-60FPS-MODS.md M1).
 *
 * SOA_MODS=<dir> names a folder of mods; every subfolder holding a mod.ini
 * is one, loaded in name order so that two runs apply them the same way:
 *
 *   examples/mods/encounters-off/mod.ini
 *       manifest = 2
 *       id = encounters-off
 *       version = 1.0
 *       name = Encounters off
 *       authors = the port's authors
 *       api = 1
 *       dol_sha1 = 8c0e278126fa3b0173400fdb632038172743cc13
 *   examples/mods/encounters-off/patches.txt
 *       # trigger    address      value   conditions (all must hold)
 *       every_frame  0x80346d28 = 0       when scene=6
 *
 * A patch writes one 32-bit word at the end of a frame. Its trigger is
 * every_frame; once, the first frame its conditions hold; or on_map_load,
 * the first frame the field is running (state 8) after a load -- a load state
 * (3 or 5) seen since it last ran, or a different map. A reload of the same
 * map after a battle is a load: it puts the map's words back as the disc has
 * them, so a patch has to be applied again, and a store applied once per load
 * cannot compound (the review of 2026-09-25 caught the older rule, a change of
 * map only, leaving the rest of a stay unpatched after the first battle). The
 * conditions read the scene id (0x803475CC: 6 is the field, 7 battle), the
 * field state (0x80311AEC) and the committed map, number and letter
 * (0x80311AC0 and the byte at 0x80311AC8; 0x80311AC4 is the picker's working
 * copy, FINDINGS "131e renders").
 *
 * M6 (docs/PLAN-60FPS-MODS.md) widens the line without changing it: an
 * optional width before the address, u8, u16 or u32 (the default), or s8,
 * s16 or s32, whose values may be negative and whose products clamp signed;
 * an address that is the word at another taken as a pointer, plus an offset
 * (`[0x803474bc]+2`); a run of targets, `+z*132` on the address and
 * `for z=0..7` after the value, one target per z; and `*= k` in place of
 * `= value`, which multiplies what is there by k (up to 65535, with up to
 * four decimals), clamped to the width:
 *
 *       on_map_load  u16  [0x803474bc]+2+z*132  *= 0.5  for z=0..7
 *
 * halves the eight zones' encounter rates of the table the map loaded
 * (docs/research/encounters.md). `*=` runs on_map_load only, and remembers
 * what it wrote at each target: a load that left the word as it was finds
 * its own value there and leaves it, so a factor never compounds. Map 099
 * keeps its encounter table apart (fn_800C1A50), so a patch on that pointer
 * is not applied there, and one that names the map is refused. A pointer
 * that is null is passed over; a target outside RAM, off its width's
 * alignment or in the game's code is passed over and said once. An M6
 * patch applied on a map load logs each target as `address: was -> now`.
 *
 * T9 (docs/specs/game-names.md): a name wherever an address goes, from
 * config/gamedata.txt (docs/MODDING-NAMES.md), its width the name's unless
 * the line gives one, an index in brackets or the `for`'s z:
 *
 *       on_map_load  encounter.table[z].rate  *= 0.5  for z=0..7
 *
 * is the patch above.
 *
 * A mod with any fault is refused whole and says why, with the file and
 * line: a mod half-applied is worse than one that is not there. Refused are
 * a badly spelled address (a lowercase 0x and exactly eight hex digits, the
 * rule the binding lists follow -- there a miss is dropped without a word,
 * here it is said out loud), an address in the hardware window, outside the
 * console's 24 MB, not word-aligned or inside the DOL's code; a value that
 * is not a 32-bit number; an unknown trigger, condition or mod.ini key; an
 * API other than this one; and a DOL other than the one the mod names.
 *
 * A mod may instead, or as well, hold a mod.dll: native code on the versioned
 * API in soa_mod.h (M3), loaded once the mod.ini checks pass and refused whole,
 * with its callbacks taken back, if its soa_mod_init declines.
 *
 * The manifest (docs/PLAN-GAMEPLAY-MODS.md section F, "Manifest v2"). A
 * mod.ini without `manifest` is version 1: name, api and dol_sha1, and the
 * recording names the mod by its folder. `manifest = 2` adds a stable `id`
 * (lowercase letters, digits, '.', '_' and '-', a letter or digit first, under
 * 64 characters) and a `version` (letters, digits, '.', '+' and '-', under 32),
 * both required, and `authors`, optional; the recording names the mod
 * id@version, and two mods with one id are refused, the second naming the
 * first -- a save's chunk of a mod's data will be keyed by it. In either
 * version `api` is the least API the mod needs: a port that speaks more still
 * loads it, one that speaks less refuses it. A key beginning `x_` is kept for
 * later ports: this one says it does not know it and loads the mod anyway,
 * where any other unknown key refuses it, so a misspelling is still caught.
 *
 * Options (M16, docs/specs/mod-options.md). A manifest 2 mod.ini may declare
 * up to 16, `option = NAME TYPE [DOMAIN] DEFAULT`, of the types int (with
 * LO..HI), bool, enum (with A|B|C), string and seed. SOA_MOD_OPT sets them,
 * `ID.NAME=VALUE` entries apart by spaces, and settings.c adds soa.ini's
 * `ID.NAME = VALUE` lines to it; a value outside its option's domain, an
 * undeclared name or a key given twice refuses the mod, naming the entry.
 * patches.txt's `${NAME}` is the value, put in before the line is read, a
 * DLL reads it through the API's option calls, and the recording carries
 * the values that are not their defaults after the mod's hash.
 *
 * The order (M17, docs/specs/mod-order.md). SOA_MOD_ORDER lists mods by id
 * (a version 1 mod by its folder): those load first, in its order, the rest
 * by folder name, and `-ID` turns one off. A mod.ini's `overrides = ID, ...`
 * loads it after each mod it names. Two mods whose patches can write the same
 * bytes on one frame -- direct addresses, or offsets through one pointer word,
 * conditions that can both hold -- refuse the later one with both lines,
 * unless one overrides the other or both write the one value there. Each
 * loaded mod's writes are listed a line a patch, a DLL's callbacks in one.
 *
 * With SOA_MODS unset nothing here runs and nothing is printed.
 */
#include "mod.h"
#include "sha1.h"
#include "soa_mod.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "plat.h"

/* A native mod's library beside its mod.ini: mod.dll on Windows, mod.so
 * elsewhere (portability L9). */
#define MOD_LIB "mod" PLAT_DL_SUFFIX

#define MOD_MAX 32
#define PATCH_MAX 1024
#define LINE_MAX_LEN 512

#define SCENE_ID 0x803475CCu
#define FIELD_STATE 0x80311AECu
#define MAP_NUMBER 0x80311AC0u
#define MAP_LETTER 0x80311AC8u
#define FIELD_RUNNING 8u
#define STORY_FLAGS 0x80310B3Cu
#define ENCOUNTER_TABLE 0x803474BCu /* the map's .ect, loaded in state 3 (research/encounters.md) */
#define WORLD_MAP 99u               /* whose encounters read a sub-table of their own (fn_800C1A50) */
#define FOR_MAX 64                  /* targets one `for` may run */
#define SLOT_MAX 4096               /* *= targets across all mods */

enum { T_EVERY_FRAME, T_ONCE, T_MAP_LOAD };
static const char* const k_trigger[] = {"every_frame", "once", "on_map_load"};

typedef struct {
    uint32_t ea, value; /* the address, or the pointer's (ptr); the value, or the factor's numerator (mul) */
    uint8_t trigger, has_scene, has_state, has_map, fired;
    uint8_t width, sign, ptr, mul, warned; /* M6: bytes, signed, through a pointer, *=, said once */
    uint32_t off, stride, z0, z1, den;     /* M6: the pointer's offset, the step and run of z, the factor's divisor */
    unsigned slot;                         /* M6: *= its first target's place in g_slots */
    uint32_t scene, state, map_number;
    uint8_t map_letter;
    unsigned mod, line, first_frame;
    unsigned long long applied, nulls;
} Patch;

/* What a *= patch last wrote at one target, and at which map: a load that
 * left the word as it was finds this there, and nothing compounds (M6). */
typedef struct {
    uint32_t key, addr, wrote;
    uint8_t set;
} Slot;

typedef struct {
    char dir[64];   /* the folder's name: what the recording names a version 1 mod by */
    char name[96];  /* what mod.ini calls it */
    char id[64];    /* manifest 2: its stable id, and its version -- the recording's id@version */
    char version[32];
    char overrides[256]; /* M17: the ids, or version 1 folders, its writes may land on: "a,b" */
    uint32_t hash;  /* FNV-1a of mod.ini, patches.txt and mod.dll, for the recording */
    unsigned first, count;
    void* dll;          /* the loaded mod.dll, or NULL */
    unsigned callbacks; /* what it registered */
    unsigned long long writes; /* guest writes its callbacks made that the API took (the report) */
} Mod;

/* An option a mod declares in its mod.ini (M16, docs/specs/mod-options.md):
 * its domain, its default and the value in effect, both in one spelling. */
#define OPTION_MAX 16
enum { O_INT, O_BOOL, O_ENUM, O_STRING, O_SEED };
static const char* const k_otype[] = {"int", "bool", "enum", "string", "seed"};

typedef struct {
    char name[32];
    uint8_t type, set; /* set: SOA_MOD_OPT gave it a value */
    long long lo, hi;  /* int's range */
    char choices[128]; /* enum's A|B|C */
    char def[64], value[64];
} Option;

static Mod g_mods[MOD_MAX];
static int g_mod_n;
/* Each mod's options by its slot in g_mods, filled as it loads: a value the
 * API hands out stays where it is for the run, init included. */
static Option g_opts[MOD_MAX][OPTION_MAX];
static int g_opt_n[MOD_MAX];
/* The mods SOA_MOD_ORDER turned off, by what it names them (M8's page). */
static char g_off[MOD_MAX * 2][64];
static int g_off_n;
static Patch g_patches[PATCH_MAX];
static unsigned g_patch_n;
static Slot g_slots[SLOT_MAX];
static unsigned g_slot_n;
static uint32_t g_last_map = 0xFFFFFFFFu;
static int g_patch_reload; /* a load state (3 or 5) seen at a frame end since the field last ran */
static char g_describe[300]; /* fits si.c's config line; later mods are left off */
static unsigned long long g_maps_loaded;

/* SHA-1, for the DOL a mod names, is sha1.c's (moved there by disc-layer I1). */

static uint32_t fnv1a(uint32_t h, const char* p, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) h = (h ^ (uint8_t)p[i]) * 16777619u;
    return h;
}

/* ---- the DOL's code, which no patch may write -------------------------- */

static uint32_t be32p(const uint8_t* p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

/* The text section the `n` bytes at `ea` touch, or -1. Sections 0-6 of a DOL
 * are code. */
static int in_text(const uint8_t* dol, size_t size, uint32_t ea, uint32_t n, uint32_t* lo, uint32_t* hi)
{
    int i;
    if (size < 0x100) return -1;
    for (i = 0; i < 7; i++) {
        uint32_t addr = be32p(dol + 0x48 + i * 4), len = be32p(dol + 0x90 + i * 4);
        if (len && ea + (n - 1) >= addr && ea < addr + len) {
            *lo = addr;
            *hi = addr + len;
            return i;
        }
    }
    return -1;
}

/* ---- parsing ----------------------------------------------------------- */

typedef struct {
    const char* path;
    unsigned line;
    int failed;
} Where;

static void refuse(Where* w, const char* fmt, const char* a, const char* b)
{
    char msg[512];
    snprintf(msg, sizeof msg, fmt, a, b);
    if (w->line) fprintf(stderr, "[mod] %s:%u: %s; the mod is not loaded\n", w->path, w->line, msg);
    else fprintf(stderr, "[mod] %s: %s; the mod is not loaded\n", w->path, msg);
    w->failed = 1;
}

/* Split on spaces and tabs, a '#' ending the line. */
static int split(char* line, char** tok, int max)
{
    int n = 0;
    char* p = line;
    char* hash = strchr(line, '#');
    if (hash) *hash = '\0';
    for (;;) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (!*p) break;
        if (n == max) return -1;
        tok[n++] = p;
        while (*p && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') p++;
        if (*p) *p++ = '\0';
    }
    return n;
}

static int is_hex(char c) { return isxdigit((unsigned char)c) != 0; }

/* The binding lists' rule: a lowercase 0x and exactly eight hex digits. */
static int parse_address(const char* t, uint32_t* out)
{
    int i;
    if (strlen(t) != 10 || t[0] != '0' || t[1] != 'x') return 0;
    for (i = 2; i < 10; i++)
        if (!is_hex(t[i])) return 0;
    *out = (uint32_t)strtoul(t + 2, NULL, 16);
    return 1;
}

/* 0x and one to eight hex digits, or decimal with no leading zero. */
static int parse_u32(const char* t, uint32_t* out)
{
    size_t i, n = strlen(t);
    unsigned long long v;
    if (n > 2 && t[0] == '0' && t[1] == 'x') {
        if (n > 10) return 0;
        for (i = 2; i < n; i++)
            if (!is_hex(t[i])) return 0;
        *out = (uint32_t)strtoul(t + 2, NULL, 16);
        return 1;
    }
    if (!n || n > 10 || (t[0] == '0' && n > 1)) return 0;
    for (i = 0; i < n; i++)
        if (t[i] < '0' || t[i] > '9') return 0;
    v = strtoull(t, NULL, 10);
    if (v > 0xFFFFFFFFull) return 0;
    *out = (uint32_t)v;
    return 1;
}

/* `116a` or `a116a`. */
static int parse_map(const char* t, uint32_t* number, uint8_t* letter)
{
    if (t[0] == 'a' && strlen(t) == 5) t++;
    if (strlen(t) != 4 || !isdigit((unsigned char)t[0]) || !isdigit((unsigned char)t[1]) ||
        !isdigit((unsigned char)t[2]) || t[3] < 'a' || t[3] > 'z')
        return 0;
    *number = (uint32_t)((t[0] - '0') * 100 + (t[1] - '0') * 10 + (t[2] - '0'));
    *letter = (uint8_t)t[3];
    return 1;
}

static void parse_condition(Where* w, Patch* p, char* t)
{
    char* eq = strchr(t, '=');
    uint32_t v;
    if (!eq) { refuse(w, "`%s` is not a condition: scene=N, state=N or map=NNNx%s", t, ""); return; }
    *eq = '\0';
    if (!strcmp(t, "scene") || !strcmp(t, "state")) {
        if (!parse_u32(eq + 1, &v)) { refuse(w, "`%s` is not a number for %s", eq + 1, t); return; }
        if (t[1] == 'c') { p->has_scene = 1; p->scene = v; }
        else { p->has_state = 1; p->state = v; }
    } else if (!strcmp(t, "map")) {
        if (!parse_map(eq + 1, &p->map_number, &p->map_letter)) {
            refuse(w, "`%s` is not a map: NNNx, as in map=116a%s", eq + 1, "");
            return;
        }
        p->has_map = 1;
    } else {
        refuse(w, "`%s` is not a condition this port knows: scene, state or map%s", t, "");
    }
}

/* ---- M6: widths, pointers, runs of targets, *= ------------------------- */

typedef struct {
    const char* name;
    uint8_t width, sign;
} Width;
static const Width k_width[] = {{"u8", 1, 0}, {"u16", 2, 0}, {"u32", 4, 0}, {"s8", 1, 1}, {"s16", 2, 1}, {"s32", 4, 1}};

static const Width* find_width(const char* t)
{
    size_t i;
    for (i = 0; i < sizeof k_width / sizeof k_width[0]; i++)
        if (!strcmp(t, k_width[i].name)) return &k_width[i];
    return NULL;
}

static const char* width_name(const Patch* p)
{
    size_t i;
    for (i = 0; i < sizeof k_width / sizeof k_width[0]; i++)
        if (k_width[i].width == p->width && k_width[i].sign == p->sign) return k_width[i].name;
    return "u32";
}

/* `0x` and exactly eight hex digits at *s, and no ninth: the binding lists' rule. */
static int scan_address(const char** s, uint32_t* out)
{
    char buf[11];
    if (strlen(*s) < 10 || is_hex((*s)[10])) return 0;
    memcpy(buf, *s, 10);
    buf[10] = '\0';
    if (!parse_address(buf, out)) return 0;
    *s += 10;
    return 1;
}

/* A number at *s, up to the next '+' or the end: parse_u32's spellings. */
static int scan_number(const char** s, uint32_t* out)
{
    char buf[16];
    size_t n = strcspn(*s, "+");
    if (!n || n >= sizeof buf) return 0;
    memcpy(buf, *s, n);
    buf[n] = '\0';
    if (!parse_u32(buf, out)) return 0;
    *s += n;
    return 1;
}

/* The address: `0x80346d28`, or `[0x803474bc]`, the word there taken as a
 * pointer, which may add `+N`; either may end `+z*N`, the step between the
 * targets a `for` runs. */
/* T9 (docs/specs/game-names.md): the game's data by name, generated from
 * config/gamedata.txt, each address proved against the code that reaches it.
 * A path has [] where an index goes; ptr: the base is a pointer the offset and
 * index are taken through. */
typedef struct {
    const char* path;
    uint32_t base, stride, off;
    int width; /* bytes, negative for signed */
    int ptr;
} GameName;
static const GameName k_names[] = {
#include "gamedata_names.h"
};

/* A name where an address goes: `party.gold`, `party.character[1].hp`,
 * `encounter.table[z].rate`, the index a number or the `for`'s z. Its width is
 * the name's unless the line gave one. 1, or 0 with nothing set. */
static int parse_name(Patch* p, const char* t, int width_given)
{
    char path[96];
    size_t n = 0;
    const char* s = t;
    int has_index = 0, index_z = 0;
    uint32_t index = 0;
    unsigned i;
    while (*s && *s != '[' && n + 1 < sizeof path) path[n++] = *s++;
    if (*s == '[') {
        s++;
        if (s[0] == 'z' && s[1] == ']') {
            index_z = 1;
            s += 2;
        } else {
            char* end;
            if (*s < '0' || *s > '9') return 0;
            index = (uint32_t)strtoul(s, &end, 10);
            if (*end != ']') return 0;
            s = end + 1;
        }
        has_index = 1;
        if (n + 2 >= sizeof path) return 0;
        path[n++] = '[';
        path[n++] = ']';
    }
    while (*s && n + 1 < sizeof path) path[n++] = *s++;
    if (*s) return 0;
    path[n] = '\0';
    for (i = 0; i < sizeof k_names / sizeof k_names[0]; i++) {
        const GameName* g = &k_names[i];
        if (strcmp(g->path, path) != 0) continue;
        if (has_index != (g->stride != 0)) return 0;
        p->ptr = (uint8_t)g->ptr;
        p->ea = g->base;
        if (g->ptr) {
            p->off = g->off + (index_z ? 0 : index * g->stride);
        } else {
            p->ea = g->base + g->off + (index_z ? 0 : index * g->stride);
        }
        if (index_z) p->stride = g->stride;
        if (!width_given) {
            p->width = (uint8_t)(g->width < 0 ? -g->width : g->width);
            p->sign = g->width < 0;
        }
        return 1;
    }
    return 0;
}

static int parse_target(Where* w, Patch* p, const char* t, int width_given)
{
    const char* s = t;
    int has_off = 0;
    if (*s >= 'a' && *s <= 'z') {
        if (parse_name(p, t, width_given)) return 1;
        refuse(w, "`%s` is not a name the game's data has (docs/MODDING-NAMES.md lists them, an index in brackets "
                  "where one goes, as in party.character[1].hp)%s", t, "");
        return 0;
    }
    if (*s == '[') {
        s++;
        if (!scan_address(&s, &p->ea) || *s++ != ']') goto bad;
        p->ptr = 1;
    } else if (!scan_address(&s, &p->ea)) {
        goto bad;
    }
    while (*s == '+') {
        s++;
        if (s[0] == 'z' && s[1] == '*') {
            s += 2;
            if (p->stride || !scan_number(&s, &p->stride) || !p->stride || p->stride > 0xFFFF) goto bad;
        } else if (!p->ptr || has_off || p->stride || !scan_number(&s, &p->off) || p->off > 0xFFFFFF) {
            goto bad;
        } else {
            has_off = 1;
        }
    }
    if (!*s) return 1;
bad:
    refuse(w, "`%s` is not an address: a lowercase 0x and exactly eight hex digits, as in 0x80346d28, or "
              "the word at one taken as a pointer, as in [0x803474bc]+2, either with +z*N to step a `for`%s", t, "");
    return 0;
}

/* `z=A..B`, A no more than B. */
static int parse_range(const char* t, uint32_t* a, uint32_t* b)
{
    char buf[16];
    const char* dots;
    if (strncmp(t, "z=", 2) != 0) return 0;
    t += 2;
    dots = strstr(t, "..");
    if (!dots || dots == t || (size_t)(dots - t) >= sizeof buf) return 0;
    memcpy(buf, t, (size_t)(dots - t));
    buf[dots - t] = '\0';
    return parse_u32(buf, a) && parse_u32(dots + 2, b) && *a <= *b && *b <= 0xFFFF;
}

/* A factor for *=: 0 to 65535, with up to four decimals (`2`, `0.5`). */
static int parse_factor(const char* t, uint32_t* num, uint32_t* den)
{
    unsigned long long n = 0;
    uint32_t d = 1;
    int digits = 0, frac = -1;
    if (t[0] == '0' && isdigit((unsigned char)t[1])) return 0; /* 05: no leading zero, as values */
    for (; *t; t++) {
        if (*t == '.' && frac < 0) {
            frac = 0;
            continue;
        }
        if (*t < '0' || *t > '9' || (frac >= 0 && ++frac > 4)) return 0;
        n = n * 10 + (unsigned)(*t - '0');
        if (frac >= 0) d *= 10;
        if (++digits > 9) return 0;
    }
    if (!digits || frac == 0 || n > 65535ull * d) return 0;
    *num = (uint32_t)n;
    *den = d;
    return 1;
}

/* A value for `=` that the width holds: 0x and hex digits or decimal, and a
 * signed width's negative in decimal. */
static int parse_value(const char* t, const Patch* p, uint32_t* out)
{
    uint32_t v, max = p->width == 4 ? 0xFFFFFFFFu : (1u << (8 * p->width)) - 1;
    if (p->sign && t[0] == '-') {
        if (t[1] < '1' || t[1] > '9' || !parse_u32(t + 1, &v) || v > (max >> 1) + 1) return 0;
        *out = (0u - v) & max;
        return 1;
    }
    if (!parse_u32(t, &v) || v > max) return 0;
    if (p->sign && t[0] != '0' && v > (max >> 1)) return 0; /* a decimal past the signed range */
    *out = v;
    return 1;
}

static void parse_patch(Where* w, char* line, const uint8_t* dol, size_t dol_size, unsigned mod)
{
    char* tok[16];
    char where[64], addr[16];
    int n = split(line, tok, 16), i, at = 1;
    uint32_t lo, hi, z;
    const Width* wd;
    Patch p;
    if (n == 0) return;
    memset(&p, 0, sizeof p);
    p.width = 4;
    p.den = 1;
    if (n < 0) { refuse(w, "too many words on one line%s%s", "", ""); return; }
    if (n > 1 && (wd = find_width(tok[1])) != NULL) {
        p.width = wd->width;
        p.sign = wd->sign;
        at = 2;
    }
    if (at == 1 && n > 2 && tok[1][0] != '0' && tok[1][0] != '[' && strcmp(tok[2], "=") != 0 &&
        strcmp(tok[2], "*=") != 0) { /* a name is followed by = or *=, so it is not caught here */
        refuse(w, "`%s` is not a width: u8, u16, u32, s8, s16 or s32%s", tok[1], "");
        return;
    }
    if (n < at + 3 || (strcmp(tok[at + 1], "=") != 0 && strcmp(tok[at + 1], "*=") != 0)) {
        refuse(w, "a patch is `trigger [width] 0x80346d28 = value [for z=A..B] [when condition...]`%s%s", "", "");
        return;
    }
    for (i = 0; i < 3 && strcmp(tok[0], k_trigger[i]) != 0; i++) {}
    if (i == 3) { refuse(w, "`%s` is not a trigger: every_frame, once or on_map_load%s", tok[0], ""); return; }
    p.trigger = (uint8_t)i;
    if (!parse_target(w, &p, tok[at], at == 2)) return;
    snprintf(addr, sizeof addr, "0x%08x", p.ea);
    if (is_mmio(p.ea)) { refuse(w, "%s is in the hardware window, not memory%s", addr, ""); return; }
    if (p.ea < 0x80000000u || p.ea >= 0x80000000u + MEM1_SIZE) {
        refuse(w, "%s is outside the console's 24 MB of RAM, 0x80000000-0x817fffff%s", addr, "");
        return;
    }
    if (p.ptr && (p.ea & 3)) {
        refuse(w, "the pointer at %s is not word-aligned, and a pointer is a whole 32-bit word%s", addr, "");
        return;
    }
    if (!p.ptr && (p.ea & (p.width - 1u))) {
        if (p.width == 4) refuse(w, "%s is not word-aligned, and a patch writes a whole 32-bit word%s", addr, "");
        else refuse(w, "%s is not aligned for a %s, which a patch writes whole", addr, width_name(&p));
        return;
    }
    if ((p.off | p.stride) & (p.width - 1u)) {
        refuse(w, "%s steps or offsets by bytes a %s cannot start on: each must be a multiple of its size", tok[at],
               width_name(&p));
        return;
    }
    p.mul = tok[at + 1][0] == '*';
    if (p.mul && p.trigger != T_MAP_LOAD) {
        refuse(w, "`*=` multiplies what is there, so it runs once a map load: on_map_load, not %s%s", tok[0], "");
        return;
    }
    if (p.mul && !parse_factor(tok[at + 2], &p.value, &p.den)) {
        refuse(w, "`%s` is not a factor: 0 to 65535, with up to four decimals, as in 0.5%s", tok[at + 2], "");
        return;
    }
    if (!p.mul && !parse_value(tok[at + 2], &p, &p.value)) {
        if (p.width == 4 && !p.sign)
            refuse(w, "`%s` is not a 32-bit value: 0x and up to eight hex digits, or decimal%s", tok[at + 2], "");
        else
            refuse(w, "`%s` is not a value a %s holds: 0x and hex digits, or decimal (negative for an s width)",
                   tok[at + 2], width_name(&p));
        return;
    }
    i = at + 3;
    if (i < n && !strcmp(tok[i], "for")) {
        if (i + 1 == n || !parse_range(tok[i + 1], &p.z0, &p.z1)) {
            refuse(w, "`for` takes z=A..B, A no more than B, as in for z=0..7%s%s", "", "");
            return;
        }
        if (!p.stride) { refuse(w, "`for` runs z through the address's +z*N, and %s has none%s", tok[at], ""); return; }
        if (p.z1 - p.z0 >= FOR_MAX) { refuse(w, "%s runs more than 64 targets%s", tok[i + 1], ""); return; }
        i += 2;
    } else if (p.stride) {
        refuse(w, "%s steps by z, and no `for z=A..B` after the value says how far%s", tok[at], "");
        return;
    }
    if (i < n) {
        if (strcmp(tok[i], "when") != 0 || i + 1 == n) {
            refuse(w, "after the value comes `when` and one or more conditions (a `for z=A..B` before them when the "
                      "address steps), not `%s`%s", tok[i], "");
            return;
        }
        for (i++; i < n && !w->failed; i++) parse_condition(w, &p, tok[i]);
        if (w->failed) return;
    }
    if (p.ptr && p.ea == ENCOUNTER_TABLE && p.has_map && p.map_number == WORLD_MAP) {
        refuse(w, "map 099 keeps its encounter table apart (fn_800C1A50), so %s is not its%s", tok[at], "");
        return;
    }
    for (z = p.z0; !p.ptr && z <= p.z1; z++) {
        unsigned long long ea = (unsigned long long)p.ea + (unsigned long long)z * p.stride;
        if (ea + (p.width - 1u) >= 0x80000000ull + MEM1_SIZE) {
            snprintf(where, sizeof where, "z=%u is %llx", z, ea);
            refuse(w, "%s runs outside the console's 24 MB of RAM (%s)", tok[at], where);
            return;
        }
        if ((i = in_text(dol, dol_size, (uint32_t)ea, p.width, &lo, &hi)) >= 0) {
            snprintf(where, sizeof where, "text section %d, %08x-%08x", i, lo, hi);
            refuse(w, "%s is inside the game's code (%s); a patch writes data only", z ? tok[at] : addr, where);
            return;
        }
    }
    if (p.mul) {
        unsigned count = p.z1 - p.z0 + 1;
        if (g_slot_n + count > SLOT_MAX) { refuse(w, "more than 4096 `*=` targets across all mods%s%s", "", ""); return; }
        p.slot = g_slot_n;
        memset(&g_slots[g_slot_n], 0, count * sizeof g_slots[0]);
        g_slot_n += count;
    }
    if (g_patch_n == PATCH_MAX) { refuse(w, "more than 1024 patches across all mods%s%s", "", ""); return; }
    p.mod = mod;
    p.line = w->line;
    g_patches[g_patch_n++] = p;
}

/* A whole file into memory, NUL-terminated. */
static char* slurp_text(const char* path, size_t* size)
{
    FILE* f = fopen(path, "rb");
    char* buf;
    long n;
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    buf = (char*)malloc((size_t)(n < 0 ? 0 : n) + 1);
    if (buf && n >= 0 && fread(buf, 1, (size_t)n, f) == (size_t)n) {
        buf[n] = '\0';
        *size = (size_t)n;
    } else {
        free(buf);
        buf = NULL;
    }
    fclose(f);
    return buf;
}

/* The next line of `text`, copied into `line`: 1, or 2 when it was longer
 * than LINE_MAX_LEN - 1 and had to be cut -- which the callers refuse, since
 * a cut token can parse as a different valid one (`state=18` as `state=1`). */
static int next_line(const char** text, char* line)
{
    const char* p = *text;
    size_t n = 0;
    int cut = 0;
    if (!*p) return 0;
    while (*p && *p != '\n') {
        if (n < LINE_MAX_LEN - 1) line[n++] = *p;
        else cut = 1;
        p++;
    }
    if (*p) p++;
    line[n] = '\0';
    *text = p;
    return cut ? 2 : 1;
}

/* ---- native mods: mod.dll on SoaModApi (PLAN M3) ------------------------ */

#define CB_MAX 64
enum {
    CB_FRAME_END, CB_SAFE_POINT, CB_MAP_LOADED, CB_SCENE_CHANGE, CB_PAD_FILTER, CB_PROJECTION, CB_TEXTURE, CB_DAMAGE,
    CB_KINDS
};

typedef struct {
    void* fn;
    void* user;
    int mod;
    unsigned long long calls;
} Callback;

static Callback g_cb[CB_KINDS][CB_MAX];
static int g_cb_n[CB_KINDS];
static CpuState* g_s;
static uint32_t g_text[7][2]; /* the DOL's code sections, [lo, hi): no mod writes there */
static int g_cur_mod = -1;    /* whose callback, or whose init, is running: log names it */
static char g_cur_dir[64];
static uint32_t g_last_scene;
static int g_seen_scene, g_loading;

unsigned gx_frame_count(void);
int tick_on_safe_point(void (*fn)(CpuState*));
void si_set_pad_filter(void (*fn)(unsigned frame, void* pad));
void gxr_set_projection_filter(void (*fn)(float p[6], int orthographic));
void gxr_set_texture_provider(int (*fn)(uint64_t hash, uint32_t fmt, uint32_t w, uint32_t h, const uint8_t* rgba,
                                        const uint8_t** out, uint32_t* out_w, uint32_t* out_h));
void gxr_hook_hazard(uint32_t addr, uint32_t bytes);

/* RAM, aligned to the width, and for a write not the game's code. A mod runs
 * at a frame end or the safe point with the frame's copies possibly still
 * running (PLAN-60FPS-MODS H14), so an access that overlaps one waits for it. */
static int api_ok(uint32_t addr, uint32_t n, uint32_t align, int write)
{
    int i;
    if (!g_s || addr < 0x80000000u || addr >= 0x80000000u + MEM1_SIZE || n > 0x80000000u + MEM1_SIZE - addr)
        return 0;
    if (align > 1 && (addr & (align - 1))) return 0;
    if (write)
        for (i = 0; i < 7; i++)
            if (g_text[i][1] > g_text[i][0] && addr < g_text[i][1] && addr + n > g_text[i][0]) return 0;
    gxr_hook_hazard(addr, n);
    return 1;
}

static int api_read8(uint32_t a, uint8_t* o) { if (!api_ok(a, 1, 1, 0)) return 0; *o = mem_r8(g_s, a); return 1; }
static int api_read16(uint32_t a, uint16_t* o) { if (!api_ok(a, 2, 2, 0)) return 0; *o = mem_r16(g_s, a); return 1; }
static int api_read32(uint32_t a, uint32_t* o) { if (!api_ok(a, 4, 4, 0)) return 0; *o = mem_r32(g_s, a); return 1; }
static int api_read_f32(uint32_t a, float* o)
{
    uint32_t v;
    if (!api_read32(a, &v)) return 0;
    memcpy(o, &v, 4);
    return 1;
}
static int api_read_bytes(uint32_t a, void* o, uint32_t n)
{
    if (!api_ok(a, n, 1, 0)) return 0;
    memcpy(o, mem_ptr(g_s, a), n);
    return 1;
}
/* A write the API took, counted against the mod whose callback made it. */
static void wrote(void)
{
    if (g_cur_mod >= 0 && g_cur_mod < g_mod_n) g_mods[g_cur_mod].writes++;
}

static int api_write8(uint32_t a, uint8_t v) { if (!api_ok(a, 1, 1, 1)) return 0; mem_w8(g_s, a, v); wrote(); return 1; }
static int api_write16(uint32_t a, uint16_t v) { if (!api_ok(a, 2, 2, 1)) return 0; mem_w16(g_s, a, v); wrote(); return 1; }
static int api_write32(uint32_t a, uint32_t v) { if (!api_ok(a, 4, 4, 1)) return 0; mem_w32(g_s, a, v); wrote(); return 1; }
static int api_write_f32(uint32_t a, float v)
{
    uint32_t u;
    memcpy(&u, &v, 4);
    return api_write32(a, u);
}
static int api_write_bytes(uint32_t a, const void* in, uint32_t n)
{
    if (!api_ok(a, n, 1, 1)) return 0;
    memcpy(mem_ptr(g_s, a), in, n);
    wrote();
    return 1;
}

static uint32_t api_scene(void) { return g_s ? mem_r32(g_s, SCENE_ID) : 0; }
static uint32_t api_field_state(void) { return g_s ? mem_r32(g_s, FIELD_STATE) : 0; }
static uint32_t api_map(void) { return g_s ? (mem_r32(g_s, MAP_NUMBER) << 8) | mem_r8(g_s, MAP_LETTER) : 0; }
static int api_story_flag(uint32_t n)
{
    uint32_t w;
    if (!api_read32(STORY_FLAGS + (n / 32) * 4, &w)) return 0;
    return (int)((w >> (n % 32)) & 1);
}
static uint32_t api_frame(void) { return gx_frame_count(); }

/* Registration is open only while a soa_mod_init runs: the dispatchers are
 * wired into tick.c, si.c and the renderer once, when loading ends, so a
 * callback registered later would be accepted and never called (the review
 * of 2026-09-25). Refusing it makes the 0 say so. */
static int g_in_init;

static int api_register(int kind, void* fn, void* user)
{
    if (!fn || !g_in_init || g_cb_n[kind] == CB_MAX) return 0;
    g_cb[kind][g_cb_n[kind]].fn = fn;
    g_cb[kind][g_cb_n[kind]].user = user;
    g_cb[kind][g_cb_n[kind]].mod = g_cur_mod;
    g_cb_n[kind]++;
    return 1;
}
static int api_on_frame_end(void (*fn)(void*), void* user) { return api_register(CB_FRAME_END, (void*)fn, user); }
static int api_on_safe_point(void (*fn)(void*), void* user) { return api_register(CB_SAFE_POINT, (void*)fn, user); }
static int api_on_map_loaded(void (*fn)(void*, uint32_t), void* user)
{
    return api_register(CB_MAP_LOADED, (void*)fn, user);
}
static int api_on_scene_change(void (*fn)(void*, uint32_t, uint32_t), void* user)
{
    return api_register(CB_SCENE_CHANGE, (void*)fn, user);
}

static int api_on_damage(uint32_t (*fn)(void*, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t), void* user)
{
    return api_register(CB_DAMAGE, (void*)fn, user);
}

uint32_t mod_damage(uint32_t value, uint32_t base, uint32_t attacker, uint32_t target, uint32_t element)
{
    int i, was = g_cur_mod;
    for (i = 0; i < g_cb_n[CB_DAMAGE]; i++) {
        g_cur_mod = g_cb[CB_DAMAGE][i].mod;
        g_cb[CB_DAMAGE][i].calls++;
        value = ((uint32_t(*)(void*, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t))g_cb[CB_DAMAGE][i].fn)(
            g_cb[CB_DAMAGE][i].user, value, base, attacker, target, element);
    }
    g_cur_mod = was;
    return (int32_t)value < 0 ? 0 : value > 9999 ? 9999 : value;
}

static int api_pad_filter(void (*fn)(void*, uint32_t, SoaPad*), void* user)
{
    return api_register(CB_PAD_FILTER, (void*)fn, user);
}
static int api_projection_filter(void (*fn)(void*, float*, int), void* user)
{
    return api_register(CB_PROJECTION, (void*)fn, user);
}
static int api_texture_provider(int (*fn)(void*, uint64_t, uint32_t, uint32_t, uint32_t, const uint8_t*, SoaImage*),
                                void* user)
{
    return api_register(CB_TEXTURE, (void*)fn, user);
}

static void api_log(const char* line)
{
    fprintf(stderr, "[mod] %s: %s\n", g_cur_mod >= 0 && g_cur_mod < g_mod_n ? g_mods[g_cur_mod].dir : g_cur_dir,
            line ? line : "");
}

static int api_call_guest(uint32_t addr, const uint32_t* ints, uint32_t n_ints, const double* floats,
                          uint32_t n_floats, uint32_t* r3, double* f1);

/* The host buttons (CH1): si.c's, through a setter main.c calls, so this
 * file still links alone -- test_mods.py's driver hands it a stub. */
static uint32_t (*g_host_fn)(void);

void mod_set_host_buttons(uint32_t (*fn)(void))
{
    g_host_fn = fn;
}

static uint32_t api_host_buttons(void)
{
    return g_host_fn ? g_host_fn() : 0;
}

/* Pad 2 (P10a): si.c's, through a setter main.c calls, like the host buttons. */
static int (*g_pad_reader)(unsigned port, void* out);

void mod_set_pad_reader(int (*fn)(unsigned port, void* out))
{
    g_pad_reader = fn;
}

static int api_read_pad(uint32_t port, SoaPad* out)
{
    if (!out) return 0;
    memset(out, 0, sizeof *out);
    out->stick[0] = out->stick[1] = out->cstick[0] = out->cstick[1] = 128;
    return port == 2 && g_pad_reader ? g_pad_reader(port, out) : 0;
}

/* M16: the calling mod's option `name` -- the mod whose init or callback is
 * running, the one in its init not yet counted in g_mod_n -- or NULL. */
static const Option* find_option(int mod, const char* name)
{
    int i;
    if (!name || mod < 0 || mod >= MOD_MAX || (mod >= g_mod_n && !(g_in_init && mod == g_mod_n))) return NULL;
    for (i = 0; i < g_opt_n[mod]; i++)
        if (!strcmp(g_opts[mod][i].name, name)) return &g_opts[mod][i];
    return NULL;
}

static const char* api_option(const char* name)
{
    const Option* o = find_option(g_cur_mod, name);
    return o ? o->value : NULL;
}

static int api_option_int(const char* name, int64_t* out)
{
    const Option* o = find_option(g_cur_mod, name);
    if (!o || !out || o->type == O_ENUM || o->type == O_STRING) return 0;
    *out = (int64_t)strtoll(o->value, NULL, 10);
    return 1;
}

static const SoaModApi g_api = {
    sizeof(SoaModApi), SOA_MOD_API_VERSION,
    api_read8, api_read16, api_read32, api_read_f32, api_read_bytes,
    api_write8, api_write16, api_write32, api_write_f32, api_write_bytes,
    api_scene, api_field_state, api_map, api_story_flag, api_frame,
    api_on_frame_end, api_on_safe_point, api_on_map_loaded, api_on_scene_change,
    api_log,
    api_pad_filter,
    api_projection_filter,
    api_texture_provider,
    api_call_guest,
    api_host_buttons,
    api_read_pad,
    api_option,
    api_option_int,
    api_on_damage,
};

/* Each texture decode, from gxr_tev.c: the first provider that answers wins. */
static int mod_texture(uint64_t hash, uint32_t fmt, uint32_t w, uint32_t h, const uint8_t* rgba, const uint8_t** out,
                       uint32_t* out_w, uint32_t* out_h)
{
    int i;
    for (i = 0; i < g_cb_n[CB_TEXTURE]; i++) {
        SoaImage img = {0, 0, NULL};
        int got;
        g_cur_mod = g_cb[CB_TEXTURE][i].mod;
        g_cb[CB_TEXTURE][i].calls++;
        got = ((int (*)(void*, uint64_t, uint32_t, uint32_t, uint32_t, const uint8_t*, SoaImage*))g_cb[CB_TEXTURE][i].fn)(
            g_cb[CB_TEXTURE][i].user, hash, fmt, w, h, rgba, &img);
        if (got && img.rgba && img.w && img.h) {
            if (img.w > 4096 || img.h > 4096) {
                /* the renderer's limit; the next provider may have one that fits */
                fprintf(stderr, "[mod] %s: texture %016llx: a %ux%u image is refused, 4096 on a side is the most\n",
                        g_mods[g_cur_mod].dir, (unsigned long long)hash, img.w, img.h);
                continue;
            }
            *out = img.rgba;
            *out_w = img.w;
            *out_h = img.h;
            g_cur_mod = -1;
            return 1;
        }
    }
    g_cur_mod = -1;
    return 0;
}

/* Each new projection, from gxr.c: each mod's filter in load order. */
static void mod_projection(float p[6], int orthographic)
{
    int i;
    for (i = 0; i < g_cb_n[CB_PROJECTION]; i++) {
        g_cur_mod = g_cb[CB_PROJECTION][i].mod;
        g_cb[CB_PROJECTION][i].calls++;
        ((void (*)(void*, float*, int))g_cb[CB_PROJECTION][i].fn)(g_cb[CB_PROJECTION][i].user, p, orthographic);
    }
    g_cur_mod = -1;
}

/* Every controller read, from si.c: each mod's filter in load order. */
static void mod_pad(unsigned frame, void* pad)
{
    int i;
    for (i = 0; i < g_cb_n[CB_PAD_FILTER]; i++) {
        g_cur_mod = g_cb[CB_PAD_FILTER][i].mod;
        g_cb[CB_PAD_FILTER][i].calls++;
        ((void (*)(void*, uint32_t, SoaPad*))g_cb[CB_PAD_FILTER][i].fn)(g_cb[CB_PAD_FILTER][i].user, frame,
                                                                         (SoaPad*)pad);
    }
    g_cur_mod = -1;
}

/* ---- calling the game from a mod (PLAN M4) ------------------------------ */

int dispatch_known(uint32_t addr); /* gen/dispatch.c */
int irq_in_handler(void);

typedef struct {
    uint32_t gpr[32];
    Fpr fpr[32];
    uint32_t cr, xer, lr, ctr, fpscr, msr, pc;
    uint32_t gqr[8];
} GuestRegs;

static int g_at_safe_point; /* set while a safe-point, scene or map callback runs */

/* The DOL's code sections, so a patch, an API write and a call can be checked
 * against them; main.c notes them whether or not any mod loads, since the self
 * test calls through mod_call_guest too. */
void mod_note_dol(const uint8_t* dol, size_t dol_size)
{
    int i;
    if (dol_size < 0x100) return;
    for (i = 0; i < 7; i++) {
        g_text[i][0] = be32p(dol + 0x48 + i * 4);
        g_text[i][1] = g_text[i][0] + be32p(dol + 0x90 + i * 4);
    }
}

/* Call the game's function at `addr` as irq.c calls an interrupt handler:
 * every register saved, the arguments in r3..r10 and f1..f8, the function
 * dispatched, r3 and f1 taken, every register put back -- so the frame the
 * game is about to run never sees the call. Refused, with the reason in
 * `why`: an address that is not a function of this program (dispatching one
 * would trap and end the run), more than eight of either kind, or r2 and r13
 * not the game's small-data bases. A GQR the callee leaves changed is put back
 * and reported in `why` on success. The callee may sleep the thread; the call
 * returns when it runs again. */
int mod_call_guest(CpuState* s, uint32_t addr, const uint32_t* ints, uint32_t n_ints, const double* floats,
                   uint32_t n_floats, uint32_t* r3, double* f1, char* why, size_t cap)
{
    GuestRegs saved;
    uint32_t i;
    int gqr_moved;
    why[0] = '\0';
    if (n_ints > 8 || n_floats > 8) {
        snprintf(why, cap, "%u int and %u float arguments, and 8 of each is the most", n_ints, n_floats);
        return 0;
    }
    if (!dispatch_known(addr)) {
        snprintf(why, cap, "%08X is not the start of a function in this program", addr);
        return 0;
    }
    if (s->gpr[2] != 0x80350000u || s->gpr[13] != 0x8034E720u) {
        snprintf(why, cap, "r2 %08X and r13 %08X are not the game's 80350000 and 8034E720", s->gpr[2], s->gpr[13]);
        return 0;
    }
    memcpy(saved.gpr, s->gpr, sizeof saved.gpr);
    memcpy(saved.fpr, s->fpr, sizeof saved.fpr);
    memcpy(saved.gqr, s->gqr, sizeof saved.gqr);
    saved.cr = s->cr; saved.xer = s->xer; saved.lr = s->lr; saved.ctr = s->ctr;
    saved.fpscr = s->fpscr; saved.msr = s->msr; saved.pc = s->pc;
    for (i = 0; i < n_ints; i++) s->gpr[3 + i] = ints[i];
    for (i = 0; i < n_floats; i++) s->fpr[1 + i].ps0 = s->fpr[1 + i].ps1 = floats[i];
    dispatch(s, addr);
    if (r3) *r3 = s->gpr[3];
    if (f1) *f1 = s->fpr[1].ps0;
    gqr_moved = memcmp(saved.gqr, s->gqr, sizeof saved.gqr) != 0;
    memcpy(s->gpr, saved.gpr, sizeof saved.gpr);
    memcpy(s->fpr, saved.fpr, sizeof saved.fpr);
    memcpy(s->gqr, saved.gqr, sizeof saved.gqr);
    s->cr = saved.cr; s->xer = saved.xer; s->lr = saved.lr; s->ctr = saved.ctr;
    s->fpscr = saved.fpscr; s->msr = saved.msr; s->pc = saved.pc;
    if (gqr_moved) snprintf(why, cap, "%08X left a GQR changed; it is put back", addr);
    return 1;
}

/* The API's call_guest: mod_call_guest, from a safe-point callback only and
 * never inside an interrupt handler -- the frame end runs inside the XFB
 * copy, the filters inside the renderer and the pad read, and none of those
 * is a point where the game's code may run. */
static int api_call_guest(uint32_t addr, const uint32_t* ints, uint32_t n_ints, const double* floats,
                          uint32_t n_floats, uint32_t* r3, double* f1)
{
    char why[160];
    const char* dir = g_cur_mod >= 0 && g_cur_mod < g_mod_n ? g_mods[g_cur_mod].dir : g_cur_dir;
    int ok;
    if (!g_at_safe_point) {
        fprintf(stderr, "[mod] %s: call_guest(%08X) refused: only a safe-point, scene or map callback may call the "
                        "game\n", dir, addr);
        return 0;
    }
    if (irq_in_handler()) {
        fprintf(stderr, "[mod] %s: call_guest(%08X) refused: inside an interrupt handler\n", dir, addr);
        return 0;
    }
    ok = mod_call_guest(g_s, addr, ints, n_ints, floats, n_floats, r3, f1, why, sizeof why);
    if (!ok) fprintf(stderr, "[mod] %s: call_guest(%08X) refused: %s\n", dir, addr, why);
    else if (why[0]) fprintf(stderr, "[mod] %s: call_guest: %s\n", dir, why);
    return ok;
}

/* The top of the main loop (tick.c): the safe point, then what it derives --
 * a scene change, and a map loaded, which is the field running (state 8)
 * after a load state (3 or 5) was seen: every story warp, name warp and
 * return from a battle passes through both (FINDINGS "How the story's own
 * warps run"), so a reload of the same map is a load too. */
static void mod_safe_point(CpuState* s)
{
    uint32_t scene = mem_r32(s, SCENE_ID), state = mem_r32(s, FIELD_STATE);
    int i;
    g_at_safe_point = 1;
    for (i = 0; i < g_cb_n[CB_SAFE_POINT]; i++) {
        g_cur_mod = g_cb[CB_SAFE_POINT][i].mod;
        g_cb[CB_SAFE_POINT][i].calls++;
        ((void (*)(void*))g_cb[CB_SAFE_POINT][i].fn)(g_cb[CB_SAFE_POINT][i].user);
    }
    if (g_seen_scene && scene != g_last_scene)
        for (i = 0; i < g_cb_n[CB_SCENE_CHANGE]; i++) {
            g_cur_mod = g_cb[CB_SCENE_CHANGE][i].mod;
            g_cb[CB_SCENE_CHANGE][i].calls++;
            ((void (*)(void*, uint32_t, uint32_t))g_cb[CB_SCENE_CHANGE][i].fn)(g_cb[CB_SCENE_CHANGE][i].user,
                                                                               g_last_scene, scene);
        }
    g_last_scene = scene;
    g_seen_scene = 1;
    if (state == 3 || state == 5) {
        g_loading = 1;
    } else if (state == FIELD_RUNNING && g_loading) {
        uint32_t map = (mem_r32(s, MAP_NUMBER) << 8) | mem_r8(s, MAP_LETTER);
        g_loading = 0;
        g_maps_loaded++;
        for (i = 0; i < g_cb_n[CB_MAP_LOADED]; i++) {
            g_cur_mod = g_cb[CB_MAP_LOADED][i].mod;
            g_cb[CB_MAP_LOADED][i].calls++;
            ((void (*)(void*, uint32_t))g_cb[CB_MAP_LOADED][i].fn)(g_cb[CB_MAP_LOADED][i].user, map);
        }
    }
    g_at_safe_point = 0;
    g_cur_mod = -1;
}

/* mod.dll, when there is one: loaded by full path, its soa_mod_init called
 * with the API; anything it registered is taken back if it refuses. 1 on
 * success, 0 (having said why) otherwise. */
static int load_dll(Where* w, const char* path, Mod* m, unsigned* dll_hash)
{
    char full[1100], err[600];
    void* h;
    SoaModInit init;
    int before[CB_KINDS], k, rc;
    size_t n = 0;
    char* bytes = slurp_text(path, &n);
    if (!bytes) return -1; /* no library: nothing to load */
    *dll_hash = fnv1a(2166136261u, bytes, n);
    free(bytes);
    if (!plat_realpath(path, full, sizeof full)) {
        refuse(w, "cannot resolve %s%s", path, "");
        return 0;
    }
    /* by its full path, so a library it needs beside it is found there too */
    h = plat_dl_open(full, err, sizeof err);
    if (!h) {
        refuse(w, "the system would not load it: %s%s", err, "");
        return 0;
    }
    init = (SoaModInit)(void (*)(void))plat_dl_sym(h, "soa_mod_init");
    if (!init) {
        char why[300];
        snprintf(why, sizeof why, "%s", plat_dl_why());
        plat_dl_close(h);
        refuse(w, "it exports no soa_mod_init (%s)%s", why, "");
        return 0;
    }
    for (k = 0; k < CB_KINDS; k++) before[k] = g_cb_n[k];
    g_cur_mod = g_mod_n;
    snprintf(g_cur_dir, sizeof g_cur_dir, "%s", m->dir);
    g_in_init = 1;
    rc = init(&g_api, SOA_MOD_API_VERSION);
    g_in_init = 0;
    g_cur_mod = -1;
    if (rc != 0) {
        char code[16];
        for (k = 0; k < CB_KINDS; k++) g_cb_n[k] = before[k];
        plat_dl_close(h);
        snprintf(code, sizeof code, "%d", rc);
        refuse(w, "its soa_mod_init refused, returning %s%s", code, "");
        return 0;
    }
    m->dll = h;
    for (k = 0; k < CB_KINDS; k++) m->callbacks += (unsigned)(g_cb_n[k] - before[k]);
    return 1;
}

/* A manifest 2 id: lowercase letters, digits, '.', '_' and '-', a letter or
 * digit first, under 64 characters. */
static int good_id(const char* s)
{
    size_t i, n = strlen(s);
    if (!n || n >= 64 || !(islower((unsigned char)s[0]) || isdigit((unsigned char)s[0]))) return 0;
    for (i = 0; i < n; i++)
        if (!(islower((unsigned char)s[i]) || isdigit((unsigned char)s[i]) || s[i] == '.' || s[i] == '_' || s[i] == '-'))
            return 0;
    return 1;
}

/* A version: letters, digits, '.', '+' and '-', a letter or digit first,
 * under 32 characters -- nothing that could break the recording's line. */
static int good_version(const char* s)
{
    size_t i, n = strlen(s);
    if (!n || n >= 32 || !isalnum((unsigned char)s[0])) return 0;
    for (i = 0; i < n; i++)
        if (!(isalnum((unsigned char)s[i]) || s[i] == '.' || s[i] == '+' || s[i] == '-')) return 0;
    return 1;
}

/* ---- M16: options a mod declares (docs/specs/mod-options.md) ------------ */

/* What an enum's choice and a string may hold: nothing that could break a
 * patches.txt line or the recording's config line. */
static int word_ok(const char* s, size_t max)
{
    size_t i, n = strlen(s);
    if (!n || n > max) return 0;
    for (i = 0; i < n; i++)
        if (!(isalnum((unsigned char)s[i]) || s[i] == '.' || s[i] == '_' || s[i] == '+' || s[i] == '-')) return 0;
    return 1;
}

/* A signed decimal that fits 32 bits, no leading zero, no `-0`. */
static int parse_int(const char* t, long long* out)
{
    const char* d = t[0] == '-' ? t + 1 : t;
    size_t i, n = strlen(d);
    long long v;
    if (!n || n > 10 || (d[0] == '0' && (n > 1 || d != t))) return 0;
    for (i = 0; i < n; i++)
        if (d[i] < '0' || d[i] > '9') return 0;
    v = strtoll(t, NULL, 10);
    if (v < -2147483648ll || v > 2147483647ll) return 0;
    *out = v;
    return 1;
}

/* Whether `v` is one of `choices` ("a|b|c"), spelled alike. */
static int one_of(const char* choices, const char* v)
{
    size_t n = strlen(v);
    const char* p = choices;
    for (;;) {
        const char* bar = strchr(p, '|');
        size_t k = bar ? (size_t)(bar - p) : strlen(p);
        if (k == n && !strncmp(p, v, n)) return 1;
        if (!bar) return 0;
        p = bar + 1;
    }
}

/* `v` checked against the option's domain and put in its one spelling. */
static int option_value(const Option* o, const char* v, char* canon, size_t cap)
{
    long long i;
    uint32_t u;
    switch (o->type) {
    case O_INT:
        if (!parse_int(v, &i) || i < o->lo || i > o->hi) return 0;
        snprintf(canon, cap, "%lld", i);
        return 1;
    case O_BOOL:
        if (strcmp(v, "0") != 0 && strcmp(v, "1") != 0) return 0;
        break;
    case O_ENUM:
        if (!one_of(o->choices, v)) return 0;
        break;
    case O_STRING:
        if (!word_ok(v, 63)) return 0;
        break;
    default:
        if (!parse_u32(v, &u)) return 0;
        snprintf(canon, cap, "%u", u);
        return 1;
    }
    snprintf(canon, cap, "%s", v);
    return 1;
}

/* What a value of the option has to be, for a refusal. */
static void option_domain(const Option* o, char* out, size_t cap)
{
    switch (o->type) {
    case O_INT: snprintf(out, cap, "a whole number from %lld to %lld", o->lo, o->hi); break;
    case O_BOOL: snprintf(out, cap, "0 or 1"); break;
    case O_ENUM: snprintf(out, cap, "one of %s", o->choices); break;
    case O_STRING: snprintf(out, cap, "1 to 63 letters, digits, '.', '_', '+' and '-'"); break;
    default: snprintf(out, cap, "a 32-bit number, 0x and hex digits or decimal"); break;
    }
}

/* `option = NAME TYPE [DOMAIN] DEFAULT`, into the mod's next slot. */
static void parse_option(Where* w, Option* opts, int* n, char* val)
{
    char *tok[5], why[160];
    Option o;
    int k = split(val, tok, 5), i, want;
    size_t c;
    memset(&o, 0, sizeof o);
    if (k < 3) {
        refuse(w, "an option is `option = NAME TYPE [DOMAIN] DEFAULT`, as in option = factor enum 0|0.5|1 0.5%s%s", "", "");
        return;
    }
    c = strlen(tok[0]);
    if (c >= sizeof o.name || !islower((unsigned char)tok[0][0])) c = 0;
    for (i = 0; c && tok[0][i]; i++)
        if (!(islower((unsigned char)tok[0][i]) || isdigit((unsigned char)tok[0][i]) || tok[0][i] == '_')) c = 0;
    if (!c) {
        refuse(w, "option `%s`: a name is a lowercase letter, then lowercase letters, digits and '_', under 32 "
                  "characters%s", tok[0], "");
        return;
    }
    snprintf(o.name, sizeof o.name, "%s", tok[0]);
    for (i = 0; i < *n; i++)
        if (!strcmp(opts[i].name, o.name)) { refuse(w, "option `%s` is declared twice%s", o.name, ""); return; }
    if (*n == OPTION_MAX) { refuse(w, "more than %s options; option `%s` is one too many", "16", o.name); return; }
    for (i = 0; i < 5 && strcmp(tok[1], k_otype[i]) != 0; i++) {}
    if (i == 5) { refuse(w, "`%s` is not an option's type: int, bool, enum, string or seed%s", tok[1], ""); return; }
    o.type = (uint8_t)i;
    want = o.type == O_INT || o.type == O_ENUM ? 4 : 3;
    if (k != want) {
        refuse(w, "option `%s`: %s", o.name,
               want == 4 ? "an int or enum is NAME TYPE DOMAIN DEFAULT, as in rate int 0..127 32"
                         : "a bool, string or seed is NAME TYPE DEFAULT, as in scenes bool 1");
        return;
    }
    if (o.type == O_INT) {
        char* dots = strstr(tok[2], "..");
        int ok = dots != NULL;
        if (ok) {
            *dots = '\0';
            ok = parse_int(tok[2], &o.lo) && parse_int(dots + 2, &o.hi) && o.lo <= o.hi;
            *dots = '.';
        }
        if (!ok) {
            refuse(w, "option `%s`: `%s` is not a range: LO..HI, whole numbers, LO no more than HI", o.name, tok[2]);
            return;
        }
    } else if (o.type == O_ENUM) {
        char copy[128], *p = copy;
        int count = 0, ok = strlen(tok[2]) < sizeof o.choices;
        snprintf(copy, sizeof copy, "%s", tok[2]);
        while (ok) {
            char* bar = strchr(p, '|');
            if (bar) *bar = '\0';
            ok = word_ok(p, 31) && ++count <= 16;
            /* a repeat: the choice already among the ones before it */
            if (ok && p != copy) {
                p[-1] = '\0';
                ok = !one_of(copy, p);
                p[-1] = '|';
            }
            if (!bar) break;
            *bar = '|';
            p = bar + 1;
        }
        if (!ok) {
            refuse(w, "option `%s`: `%s` is not a list of choices: 1 to 16, A|B|C, each 1 to 31 letters, digits, "
                      "'.', '_', '+' and '-', no two alike, under 128 characters in all", o.name, tok[2]);
            return;
        }
        snprintf(o.choices, sizeof o.choices, "%s", tok[2]);
    }
    if (!option_value(&o, tok[want - 1], o.def, sizeof o.def)) {
        char msg[300];
        option_domain(&o, why, sizeof why);
        snprintf(msg, sizeof msg, "option `%s`: its default, %.40s, is not %s", o.name, tok[want - 1], why);
        refuse(w, "%s%s", msg, "");
        return;
    }
    snprintf(o.value, sizeof o.value, "%s", o.def);
    opts[(*n)++] = o;
}

/* One `ID.NAME=VALUE` entry of SOA_MOD_OPT, split in place: 1, or 0 when it
 * is not one. The id may hold '.', a name never does, so the last '.'
 * before the '=' parts them. */
static int opt_entry(char* e, char** id, char** name, char** value)
{
    char *eq = strchr(e, '='), *dot;
    if (!eq) return 0;
    *eq = '\0';
    dot = strrchr(e, '.');
    if (!dot || dot == e || !dot[1]) { *eq = '='; return 0; }
    *dot = '\0';
    *id = e;
    *name = dot + 1;
    *value = eq + 1;
    return 1;
}

#define OPT_ENV_MAX 4096

/* SOA_MOD_OPT's entries that name the mod `id`, onto its options: an
 * undeclared name, a value outside its domain, or one key given twice
 * refuses the mod, naming the entry: 0. */
static int apply_options(const char* id, Option* opts, int n)
{
    const char* env = getenv("SOA_MOD_OPT");
    char buf[OPT_ENV_MAX], *tok[256], *eid, *name, *value, why[200];
    int k, i, j;
    Where w;
    if (!env || !*env) return 1;
    w.path = "SOA_MOD_OPT";
    w.line = 0;
    w.failed = 0;
    snprintf(buf, sizeof buf, "%s", env);
    k = split(buf, tok, 256);
    for (i = 0; i < k && !w.failed; i++) {
        char entry[300];
        snprintf(entry, sizeof entry, "%s", tok[i]);
        if (!opt_entry(tok[i], &eid, &name, &value) || strcmp(eid, id) != 0) continue;
        for (j = 0; j < n && strcmp(opts[j].name, name) != 0; j++) {}
        if (j == n) { refuse(&w, "`%s`: the mod declares no option `%s`", entry, name); break; }
        if (opts[j].set) { refuse(&w, "`%s`: option `%s` is given twice", entry, name); break; }
        if (!option_value(&opts[j], value, opts[j].value, sizeof opts[j].value)) {
            option_domain(&opts[j], why, sizeof why);
            refuse(&w, "`%s`: the value is not %s", entry, why);
            break;
        }
        opts[j].set = 1;
    }
    return !w.failed;
}

/* The entries no loaded mod reads, said once loading ends, and entries that
 * are not ID.NAME=VALUE at all. */
static void check_option_entries(void)
{
    const char* env = getenv("SOA_MOD_OPT");
    char buf[OPT_ENV_MAX], *tok[256], *id, *name, *value;
    int k, i, m;
    if (!env || !*env) return;
    if (strlen(env) >= sizeof buf) fprintf(stderr, "[mod] SOA_MOD_OPT is longer than %d characters; the rest is not read\n", OPT_ENV_MAX - 1);
    snprintf(buf, sizeof buf, "%s", env);
    k = split(buf, tok, 256);
    if (k < 0) fprintf(stderr, "[mod] SOA_MOD_OPT holds more than 256 entries; the rest are not read\n");
    for (i = 0; i < k; i++) {
        char entry[300];
        snprintf(entry, sizeof entry, "%s", tok[i]);
        if (!opt_entry(tok[i], &id, &name, &value)) {
            fprintf(stderr, "[mod] SOA_MOD_OPT: `%s` is not ID.NAME=VALUE; passed over\n", entry);
            continue;
        }
        for (m = 0; m < g_mod_n && strcmp(g_mods[m].id, id) != 0; m++) {}
        if (m == g_mod_n)
            fprintf(stderr, "[mod] SOA_MOD_OPT: `%s`: no mod with id `%s` is loaded; it does nothing\n", entry, id);
    }
}

/* `${NAME}` on a patches.txt line replaced by the option's value, before the
 * line is read; a '#' ends what is replaced, as it ends the line. 0, having
 * refused, on a `$` that does not begin a declared option's `${NAME}`. */
static int substitute(Where* w, char* line, const Option* opts, int n)
{
    char out[LINE_MAX_LEN];
    size_t used = 0;
    const char* p = line;
    if (!strchr(line, '$')) return 1;
    while (*p && *p != '#') {
        const char* add = p;
        size_t len = 1;
        if (*p == '$') {
            const char* end = p[1] == '{' ? strchr(p + 2, '}') : NULL;
            char name[40];
            int j;
            if (!end || end == p + 2 || (size_t)(end - p - 2) >= sizeof name) {
                refuse(w, "a `$` begins ${NAME}, the name of an option the mod declares%s%s", "", "");
                return 0;
            }
            memcpy(name, p + 2, (size_t)(end - p - 2));
            name[end - p - 2] = '\0';
            for (j = 0; j < n && strcmp(opts[j].name, name) != 0; j++) {}
            if (j == n) {
                refuse(w, "`${%s}` names no option the mod declares%s", name, "");
                return 0;
            }
            add = opts[j].value;
            len = strlen(add);
            p = end + 1;
        } else {
            p++;
        }
        if (used + len >= sizeof out) {
            refuse(w, "longer than %s characters once its options are put in%s", "511", "");
            return 0;
        }
        memcpy(out + used, add, len);
        used += len;
    }
    out[used] = '\0';
    memcpy(line, out, used + 1);
    return 1;
}

/* ---- M17: the order, mods turned off, conflicts (docs/specs/mod-order.md) - */

/* What a list names a mod by: its id, or a version 1 mod's folder. */
static const char* mod_key(const Mod* m) { return m->id[0] ? m->id : m->dir; }

/* Whether the comma-separated `list` holds `name`. */
static int in_list(const char* list, const char* name)
{
    size_t n = strlen(name);
    const char* p = list;
    if (!n) return 0;
    while (*p) {
        const char* comma = strchr(p, ',');
        size_t k = comma ? (size_t)(comma - p) : strlen(p);
        if (k == n && !strncmp(p, name, n)) return 1;
        if (!comma) break;
        p = comma + 1;
    }
    return 0;
}

/* `overrides = a, b`: ids, by the id rule, into "a,b". */
static void parse_overrides(Where* w, char* val, char* out, size_t cap)
{
    char* tok[32];
    size_t used = 0;
    int k, i;
    char* c;
    for (c = val; *c; c++)
        if (*c == ',') *c = ' ';
    k = split(val, tok, 32);
    if (k <= 0) { refuse(w, "`overrides` names the ids of mods whose writes this one's may land on, a, b%s%s", "", ""); return; }
    for (i = 0; i < k; i++) {
        int n;
        if (!good_id(tok[i])) {
            refuse(w, "overrides: `%s` is not an id: lowercase letters, digits, '.', '_' and '-', a letter or digit "
                      "first%s", tok[i], "");
            return;
        }
        n = snprintf(out + used, cap - used, "%s%s", used ? "," : "", tok[i]);
        if (n < 0 || (size_t)n >= cap - used) { refuse(w, "`overrides` names more than %s characters of ids%s", "255", ""); return; }
        used += (size_t)n;
    }
}

/* Whether two patches' conditions can hold on one frame: not when both name
 * a scene, a state or a map and the two differ. */
static int conds_can_meet(const Patch* a, const Patch* b)
{
    if (a->has_scene && b->has_scene && a->scene != b->scene) return 0;
    if (a->has_state && b->has_state && a->state != b->state) return 0;
    if (a->has_map && b->has_map && (a->map_number != b->map_number || a->map_letter != b->map_letter)) return 0;
    return 1;
}

/* Whether two patches' bytes can meet, known before the game runs: two
 * direct patches, or two through one pointer word, compared on every target;
 * a direct and a pointer patch, or two pointers, cannot be. The first byte
 * they share, an address or the pointer's offset, in *at. */
static int bytes_meet(const Patch* a, const Patch* b, uint32_t* at)
{
    uint32_t za, zb;
    unsigned long long abase, bbase;
    if (a->ptr != b->ptr || (a->ptr && a->ea != b->ea)) return 0;
    abase = a->ptr ? a->off : a->ea;
    bbase = b->ptr ? b->off : b->ea;
    for (za = a->z0; za <= a->z1; za++) {
        unsigned long long lo = abase + (unsigned long long)za * a->stride, hi = lo + a->width;
        for (zb = b->z0; zb <= b->z1; zb++) {
            unsigned long long lo2 = bbase + (unsigned long long)zb * b->stride, hi2 = lo2 + b->width;
            if (lo < hi2 && lo2 < hi) {
                *at = (uint32_t)(lo > lo2 ? lo : lo2);
                return 1;
            }
        }
    }
    return 0;
}

/* The same value written over the same targets by both: no conflict. */
static int same_write(const Patch* a, const Patch* b)
{
    return !a->mul && !b->mul && a->width == b->width && a->value == b->value && a->ptr == b->ptr &&
           a->ea == b->ea && a->off == b->off && a->stride == b->stride && a->z0 == b->z0 && a->z1 == b->z1;
}

/* The patches from `first` on, the mod `m`'s, against every earlier mod's:
 * bytes that can meet when both can apply refuse it, unless one of the two
 * names the other in `overrides`, which is said. */
static void check_conflicts(Where* w, unsigned first, const Mod* m)
{
    unsigned i, j;
    for (i = first; i < g_patch_n && !w->failed; i++)
        for (j = 0; j < first; j++) {
            const Patch *p = &g_patches[i], *q = &g_patches[j];
            const Mod* o = &g_mods[q->mod];
            char at[40], other[160];
            uint32_t byte;
            if (!conds_can_meet(p, q) || !bytes_meet(p, q, &byte)) continue;
            if (same_write(p, q)) continue; /* the one value at the one place: neither undoes the other */
            if (p->ptr) snprintf(at, sizeof at, "[%08X]+%u", p->ea, byte);
            else snprintf(at, sizeof at, "%08X", byte);
            if (in_list(m->overrides, mod_key(o)) || in_list(o->overrides, mod_key(m))) {
                int mine = in_list(m->overrides, mod_key(o));
                fprintf(stderr, "[mod] %s/patches.txt:%u overrides %s/patches.txt:%u at %s\n", mine ? m->dir : o->dir,
                        mine ? p->line : q->line, mine ? o->dir : m->dir, mine ? q->line : p->line, at);
                continue;
            }
            snprintf(other, sizeof other, "%s/patches.txt:%u", o->dir, q->line);
            w->line = p->line;
            refuse(w, "it writes %s, as %s does, and both can apply on one frame; one of the two mods must name "
                      "the other in `overrides`", at, other);
            return;
        }
}

static void describe_patch(const Patch* p, char* buf, size_t cap);

/* What a loaded mod writes and registers, a line each (M17). */
static void list_mod(int mi)
{
    static const char* const k_kind[CB_KINDS] = {"frame end", "safe point", "map load", "scene change",
                                                 "controller read", "projection", "texture"};
    const Mod* m = &g_mods[mi];
    char what[200], when[96], kinds[160];
    unsigned i;
    int k, c;
    size_t used = 0;
    for (i = m->first; i < m->first + m->count; i++) {
        const Patch* p = &g_patches[i];
        int n = 0;
        when[0] = '\0';
        if (p->has_scene) n += snprintf(when + n, sizeof when - (size_t)n, " scene=%u", p->scene);
        if (p->has_state) n += snprintf(when + n, sizeof when - (size_t)n, " state=%u", p->state);
        if (p->has_map) snprintf(when + n, sizeof when - (size_t)n, " map=%03u%c", p->map_number, p->map_letter);
        describe_patch(p, what, sizeof what);
        fprintf(stderr, "[mod] %s writes, patches.txt:%u: %s%s%s\n", m->dir, p->line, what, when[0] ? " when" : "",
                when);
    }
    kinds[0] = '\0';
    for (k = 0; k < CB_KINDS; k++)
        for (c = 0; c < g_cb_n[k]; c++)
            if (g_cb[k][c].mod == mi) {
                int n = snprintf(kinds + used, sizeof kinds - used, "%s%s", used ? ", " : "", k_kind[k]);
                if (n > 0 && (size_t)n < sizeof kinds - used) used += (size_t)n;
                break;
            }
    if (kinds[0]) fprintf(stderr, "[mod] %s registers: %s\n", m->dir, kinds);
}

static void load_one(CpuState* s, const char* root, const char* dir, const char* dol_sha1,
                     const uint8_t* dol, size_t dol_size, int has_files, unsigned files_hash)
{
    char path[600], ppath[600], dpath[600], line[LINE_MAX_LEN], *tok[8];
    char *ini, *patches;
    const char* t;
    size_t ini_n = 0, patches_n = 0;
    int have_api = 0, dll, got, manifest = 1, have_manifest = 0, i;
    const char* v2_key = NULL; /* the first manifest 2 key seen, for a version 1 manifest that uses one */
    unsigned dll_hash = 0;
    char num[16];
    Where w;
    Mod m;
    Option* opts;
    int* opt_n;
    unsigned before = g_patch_n, slots_before = g_slot_n;
    (void)s;
    memset(&m, 0, sizeof m);
    snprintf(m.dir, sizeof m.dir, "%s", dir);
    snprintf(path, sizeof path, "%s/%s/mod.ini", root, dir);
    snprintf(ppath, sizeof ppath, "%s/%s/patches.txt", root, dir);
    snprintf(dpath, sizeof dpath, "%s/%s/" MOD_LIB, root, dir);
    ini = slurp_text(path, &ini_n);
    if (!ini) return; /* not a mod: the caller only asks about folders */
    w.path = path;
    w.failed = 0;
    w.line = 0;
    if (g_mod_n == MOD_MAX) {
        refuse(&w, "more than %s mods%s", "32", "");
        free(ini);
        return;
    }
    opts = g_opts[g_mod_n];
    opt_n = &g_opt_n[g_mod_n];
    *opt_n = 0;
    for (t = ini; (got = next_line(&t, line)) != 0;) {
        char* eq;
        w.line++;
        if (got == 2) {
            refuse(&w, "a line longer than %s characters%s", "511", "");
            continue;
        }
        if ((eq = strchr(line, '#')) != NULL) *eq = '\0';
        if (!(eq = strchr(line, '='))) {
            if (split(line, tok, 8) != 0) refuse(&w, "`%s` is not `key = value`%s", line, "");
            continue;
        }
        *eq = '\0';
        if (split(line, tok, 8) != 1) { refuse(&w, "a key is one word%s%s", "", ""); continue; }
        {
            char* key = tok[0];
            char* val = eq + 1;
            size_t vl;
            while (*val == ' ' || *val == '\t') val++;
            vl = strlen(val);
            while (vl && (val[vl - 1] == ' ' || val[vl - 1] == '\t' || val[vl - 1] == '\r')) val[--vl] = '\0';
            if (!strcmp(key, "name")) {
                snprintf(m.name, sizeof m.name, "%s", val);
            } else if (!strcmp(key, "manifest")) {
                have_manifest = 1;
                if (!strcmp(val, "1")) manifest = 1;
                else if (!strcmp(val, "2")) manifest = 2;
                else refuse(&w, "manifest = %s, and this port reads manifests %s", val, "1 and 2");
            } else if (!strcmp(key, "id")) {
                if (!v2_key) v2_key = "id";
                if (!good_id(val))
                    refuse(&w, "id = %s: an id is lowercase letters, digits, '.', '_' and '-', a letter or digit first, under 64 characters%s", val, "");
                else snprintf(m.id, sizeof m.id, "%s", val);
            } else if (!strcmp(key, "version")) {
                if (!v2_key) v2_key = "version";
                if (!good_version(val))
                    refuse(&w, "version = %s: a version is letters, digits, '.', '+' and '-', a letter or digit first, under 32 characters%s", val, "");
                else snprintf(m.version, sizeof m.version, "%s", val);
            } else if (!strcmp(key, "authors")) {
                if (!v2_key) v2_key = "authors";
            } else if (!strcmp(key, "api")) {
                /* The least API the mod needs: a newer port loads it too. */
                char* end;
                long need = strtol(val, &end, 10);
                have_api = 1;
                snprintf(num, sizeof num, "%d", MOD_API);
                if (!*val || *end || need < 1) refuse(&w, "api = %s is not a version number; this port speaks api %s", val, num);
                else if (need > MOD_API) refuse(&w, "api = %s, and this port speaks api %s", val, num);
            } else if (!strcmp(key, "dol_sha1")) {
                size_t i;
                char lower[48];
                snprintf(lower, sizeof lower, "%s", val);
                for (i = 0; lower[i]; i++) lower[i] = (char)tolower((unsigned char)lower[i]);
                if (strcmp(lower, dol_sha1) != 0)
                    refuse(&w, "made for the DOL with SHA-1 %s, and this is %s", val, dol_sha1);
                else
                    m.hash = 1; /* seen and matching; replaced by the content hash below */
            } else if (!strcmp(key, "overrides")) {
                if (!v2_key) v2_key = "overrides";
                parse_overrides(&w, val, m.overrides, sizeof m.overrides);
            } else if (!strcmp(key, "option")) {
                if (!v2_key) v2_key = "option";
                parse_option(&w, opts, opt_n, val);
            } else if (!strncmp(key, "x_", 2)) {
                fprintf(stderr, "[mod] %s:%u: `%s` is not a key this port knows; a key beginning x_ is kept for later ports, so the mod loads without it\n",
                        path, w.line, key);
            } else {
                refuse(&w, "`%s` is not a mod.ini key: manifest, id, version, name, authors, api, dol_sha1, option or overrides%s", key, "");
            }
        }
    }
    w.line = 0;
    if (!w.failed && manifest == 1 && v2_key)
        refuse(&w, "`%s` is a manifest 2 key, and this mod.ini has %s", v2_key, have_manifest ? "manifest = 1" : "no `manifest = 2`");
    if (!w.failed && manifest == 2 && !m.id[0]) refuse(&w, "manifest 2 and no `id = `%s%s", "", "");
    if (!w.failed && manifest == 2 && !m.version[0]) refuse(&w, "manifest 2 and no `version = `%s%s", "", "");
    for (i = 0; !w.failed && m.id[0] && i < g_mod_n; i++)
        if (!strcmp(g_mods[i].id, m.id)) refuse(&w, "its id, %s, is already the mod's in folder %s", m.id, g_mods[i].dir);
    if (!w.failed && !m.name[0]) refuse(&w, "no `name = `%s%s", "", "");
    if (!w.failed && !have_api) refuse(&w, "no `api = %s`%s", manifest == 2 ? "" : "1", "");
    if (!w.failed && !m.hash) refuse(&w, "no `dol_sha1 = ` naming the DOL it was made for%s%s", "", "");
    if (w.failed || (m.id[0] && !apply_options(m.id, opts, *opt_n))) {
        free(ini);
        return;
    }

    patches = slurp_text(ppath, &patches_n);
    if (patches) {
        w.path = ppath;
        for (t = patches; !w.failed && (got = next_line(&t, line)) != 0;) {
            w.line++;
            if (got == 2) refuse(&w, "a line longer than %s characters%s", "511", "");
            else if (substitute(&w, line, opts, *opt_n)) parse_patch(&w, line, dol, dol_size, (unsigned)g_mod_n);
        }
        if (!w.failed && g_patch_n == before) {
            w.line = 0;
            refuse(&w, "no patches in it%s%s", "", "");
        }
        if (!w.failed) check_conflicts(&w, before, &m);
    }
    dll = -1;
    if (!w.failed) {
        w.path = dpath;
        w.line = 0;
        dll = load_dll(&w, dpath, &m, &dll_hash);
        if (dll < 0 && !patches && !has_files) {
            w.path = path;
            refuse(&w, "no patches.txt, no " MOD_LIB " and no files.txt beside it, so it would do nothing%s%s", "", "");
        }
    }
    if (w.failed) {
        g_patch_n = before; /* refused whole */
        g_slot_n = slots_before;
    } else {
        /* files.txt and every source it places count too (I6): what a mod puts on the disc is in its hash */
        m.hash = fnv1a(fnv1a(2166136261u, ini, ini_n), patches ? patches : "", patches_n) ^ dll_hash ^ files_hash;
        m.first = before;
        m.count = g_patch_n - before;
        g_mods[g_mod_n++] = m;
        if (m.id[0])
            fprintf(stderr, "[mod] loaded %s (%s/%s, %s@%s): %u patch(es)%s%s, api %d, the DOL it names\n", m.name, root, dir,
                    m.id, m.version, m.count, m.dll ? " and " MOD_LIB : "", has_files ? " and files.txt" : "", MOD_API);
        else
            fprintf(stderr, "[mod] loaded %s (%s/%s): %u patch(es)%s%s, api %d, the DOL it names\n", m.name, root, dir,
                    m.count, m.dll ? " and " MOD_LIB : "", has_files ? " and files.txt" : "", MOD_API);
        for (i = 0; i < *opt_n; i++)
            if (opts[i].set)
                fprintf(stderr, "[mod] %s: option %s = %s, from SOA_MOD_OPT (its default %s)\n", dir, opts[i].name,
                        opts[i].value, opts[i].def);
        list_mod(g_mod_n - 1);
    }
    free(ini);
    free(patches);
}

/* `[name=value;...]` for each of mod `m`'s options away from its default,
 * in the order declared, or "" when there are none. */
static void option_text(int m, char* out, size_t cap)
{
    size_t used = 0;
    int i;
    out[0] = '\0';
    for (i = 0; i < g_opt_n[m]; i++) {
        const Option* o = &g_opts[m][i];
        int k;
        if (!strcmp(o->value, o->def)) continue;
        k = snprintf(out + used, cap - used, "%s%s=%s", used ? ";" : "[", o->name, o->value);
        if (k < 0 || (size_t)k >= cap - used) break;
        used += (size_t)k;
    }
    if (used && used + 1 < cap) {
        out[used] = ']';
        out[used + 1] = '\0';
    }
}

/* One folder before anything loads (M17): what a list names it by, what it
 * overrides, and whether it is turned off or cannot be ordered. */
typedef struct {
    char key[64];
    char overrides[256];
    int rank, off, bad;
} Planned;

/* `id` and `overrides` from a mod.ini, read as plain text: its place in the
 * order must not depend on whether the rest of the file is right, which
 * load_one says. */
static void peek_ini(const char* path, const char* folder, Planned* p)
{
    size_t n = 0;
    char* ini = slurp_text(path, &n);
    const char* t;
    char line[LINE_MAX_LEN];
    snprintf(p->key, sizeof p->key, "%s", folder);
    p->overrides[0] = '\0';
    if (!ini) return;
    for (t = ini; next_line(&t, line) != 0;) {
        char *eq, *key, *val, *tok[32];
        int k, i;
        size_t used = 0;
        if ((eq = strchr(line, '#')) != NULL) *eq = '\0';
        if (!(eq = strchr(line, '='))) continue;
        *eq = '\0';
        key = line;
        val = eq + 1;
        if (split(key, tok, 2) != 1) continue;
        key = tok[0];
        if (!strcmp(key, "id")) {
            if (split(val, tok, 2) == 1 && good_id(tok[0])) snprintf(p->key, sizeof p->key, "%s", tok[0]);
        } else if (!strcmp(key, "overrides")) {
            char* c;
            for (c = val; *c; c++)
                if (*c == ',') *c = ' ';
            k = split(val, tok, 32);
            for (i = 0; i < k; i++) {
                int w = snprintf(p->overrides + used, sizeof p->overrides - used, "%s%s", used ? "," : "", tok[i]);
                if (w < 0 || (size_t)w >= sizeof p->overrides - used) break;
                used += (size_t)w;
            }
        }
    }
    free(ini);
}

/* SOA_MOD_ORDER onto the planned folders: each name it lists gets its place
 * (rank), and `-NAME` turns that mod off. */
static void read_order(const char* dir, Planned* plan, int n)
{
    const char* env = getenv("SOA_MOD_ORDER");
    char buf[2048], *p, *next;
    int rank = 0, i;
    if (!env || !*env) return;
    snprintf(buf, sizeof buf, "%s", env);
    for (p = buf; p; p = next) {
        char* tok[2];
        int off;
        next = strchr(p, ',');
        if (next) *next++ = '\0';
        if (split(p, tok, 2) != 1) {
            if (*p && split(p, tok, 2) != 0) fprintf(stderr, "[mod] SOA_MOD_ORDER: `%s` is not one name; passed over\n", p);
            continue;
        }
        off = tok[0][0] == '-';
        for (i = 0; i < n && strcmp(plan[i].key, tok[0] + off) != 0; i++) {}
        if (i == n)
            fprintf(stderr, "[mod] SOA_MOD_ORDER: `%s` names no mod in %s; passed over\n", tok[0] + off, dir);
        else if (plan[i].rank >= 0)
            fprintf(stderr, "[mod] SOA_MOD_ORDER: `%s` is named twice; its second place is passed over\n", tok[0] + off);
        else {
            plan[i].rank = rank++;
            plan[i].off = off;
        }
    }
}

/* The order mods load in: the list's first, then the rest by folder name;
 * then each mod moved after every mod it overrides, so its write lands
 * last. Two that override each other cannot be ordered and are marked bad. */
static int plan_order(const char* dir, char (*folders)[64], Planned* plan, int n, int* order)
{
    int i, j, k = 0, pass, moved = 1;
    for (i = 0; i < n; i++)
        if (plan[i].rank >= 0) order[k++] = i;
    for (i = 1; i < k; i++) /* by rank: insertion, k is small */
        for (j = i; j > 0 && plan[order[j - 1]].rank > plan[order[j]].rank; j--) {
            int t = order[j];
            order[j] = order[j - 1];
            order[j - 1] = t;
        }
    for (i = 0; i < n; i++)
        if (plan[i].rank < 0) order[k++] = i;
    for (i = 0; i < k; i++)
        for (j = i + 1; j < k; j++)
            if (in_list(plan[order[i]].overrides, plan[order[j]].key) &&
                in_list(plan[order[j]].overrides, plan[order[i]].key) && !plan[order[i]].off && !plan[order[j]].off) {
                plan[order[i]].bad = plan[order[j]].bad = 1;
                fprintf(stderr, "[mod] %s/%s and %s/%s each name the other in `overrides`, so which wins cannot be "
                                "known; neither is loaded\n", dir, folders[order[i]], dir, folders[order[j]]);
            }
    for (pass = 0; moved && pass <= k * k; pass++) {
        moved = 0;
        for (i = 0; i < k && !moved; i++)
            for (j = i + 1; j < k && !moved; j++) {
                int a = order[i], t;
                if (plan[a].bad || plan[order[j]].bad || !in_list(plan[a].overrides, plan[order[j]].key)) continue;
                for (t = i; t < j; t++) order[t] = order[t + 1];
                order[j] = a;
                moved = 1;
                if (!plan[a].off && !plan[order[j - 1]].off)
                    fprintf(stderr, "[mod] %s/%s loads after %s, which it overrides\n", dir, folders[a],
                            plan[order[j - 1]].key);
            }
    }
    if (moved) fprintf(stderr, "[mod] the mods' `overrides` go round in a circle; the order stands as it is\n");
    return k;
}

static int cmp_name(const void* a, const void* b) { return strcmp((const char*)a, (const char*)b); }

/* One folder under SOA_MODS: kept for loading, or -- a name too long for the
 * table, or one folder past what it holds -- said so, never dropped quietly. */
typedef struct {
    char (*names)[64];
    int* n;
    const char* dir;
} Folders;
static void note_folder(char (*names)[64], int* n, const char* dir, const char* name);
static void each_folder(const char* name, void* u)
{
    Folders* f = (Folders*)u;
    note_folder(f->names, f->n, f->dir, name);
}

static void note_folder(char (*names)[64], int* n, const char* dir, const char* name)
{
    if (strlen(name) >= 64)
        fprintf(stderr, "[mod] %s/%s: a mod's folder name has to be under 64 characters; not read\n", dir, name);
    else if (*n == MOD_MAX * 2)
        fprintf(stderr, "[mod] %s/%s: more than %d folders in %s; not read\n", dir, name, MOD_MAX * 2, dir);
    else
        snprintf(names[(*n)++], 64, "%s", name);
}

/* The folders under SOA_MODS and their order (M17), worked out once: the
 * files pass (I6) and mod_load share it, so what it says is said once. */
static struct {
    int done, n, k;
    char dir[600];
    char names[MOD_MAX * 2][64];
    Planned plan[MOD_MAX * 2];
    int order[MOD_MAX * 2];
} g_plan;

static int plan_mods(const char* dir)
{
    int i;
    Folders folders;
    if (g_plan.done && !strcmp(g_plan.dir, dir)) return 1;
    memset(&g_plan, 0, sizeof g_plan);
    snprintf(g_plan.dir, sizeof g_plan.dir, "%s", dir);
    folders.names = g_plan.names;
    folders.n = &g_plan.n;
    folders.dir = dir;
    if (plat_list_dirs(dir, each_folder, &folders) < 0) {
        fprintf(stderr, "[mod] SOA_MODS=%s is not a folder this port can read; no mods\n", dir);
        return 0;
    }
    qsort(g_plan.names, (size_t)g_plan.n, sizeof g_plan.names[0], cmp_name);
    for (i = 0; i < g_plan.n; i++) {
        char path[600];
        snprintf(path, sizeof path, "%s/%s/mod.ini", dir, g_plan.names[i]);
        peek_ini(path, g_plan.names[i], &g_plan.plan[i]);
        g_plan.plan[i].rank = -1;
        g_plan.plan[i].off = g_plan.plan[i].bad = 0;
    }
    read_order(dir, g_plan.plan, g_plan.n);
    g_plan.k = plan_order(dir, g_plan.names, g_plan.plan, g_plan.n, g_plan.order);
    g_plan.done = 1;
    return 1;
}

/* ---- I6: files.txt, before the file table is parked --------------------- */

typedef struct {
    int refused;      /* the scan refused it (said); mod_load passes it over */
    int has_files;    /* it has a files.txt the scan accepted */
    unsigned hash;    /* over files.txt and every source */
    int first, count; /* its lines in g_ops */
} FilesMod;
static FilesMod g_files[MOD_MAX * 2]; /* by place in g_plan.names */
static DiscFileOp* g_ops;
static int g_ops_n, g_ops_cap;

/* A source path in a mod's folder: relative, forward slashes, nothing that
 * climbs out. */
static int source_ok(const char* p)
{
    const char* s = p;
    if (!*p || p[0] == '/' || p[0] == '\\' || strchr(p, ':') || strchr(p, '\\')) return 0;
    while (*s) {
        const char* slash = strchr(s, '/');
        size_t len = slash ? (size_t)(slash - s) : strlen(s);
        if (len == 0 || (len == 2 && s[0] == '.' && s[1] == '.')) return 0;
        if (!slash) break;
        s = slash + 1;
    }
    return 1;
}

/* A source's bytes, up to one past 16 MiB (vfst.c refuses what is over). */
static uint8_t* read_source(const char* path, uint32_t* n)
{
    FILE* f = fopen(path, "rb");
    uint8_t *buf, *more;
    size_t cap = 1u << 16, used = 0, got;
    if (!f) return NULL;
    buf = (uint8_t*)malloc(cap);
    while (buf && (got = fread(buf + used, 1, cap - used, f)) > 0) {
        used += got;
        if (used > (16u << 20)) break;
        if (used == cap) {
            more = (uint8_t*)realloc(buf, cap * 2);
            if (!more) {
                free(buf);
                buf = NULL;
                break;
            }
            buf = more;
            cap *= 2;
        }
    }
    fclose(f);
    *n = (uint32_t)used;
    return buf;
}

static DiscFileOp* new_op(void)
{
    if (g_ops_n == g_ops_cap) {
        int cap = g_ops_cap ? g_ops_cap * 2 : 64;
        DiscFileOp* more = (DiscFileOp*)realloc(g_ops, (size_t)cap * sizeof *more);
        if (!more) return NULL;
        g_ops = more;
        g_ops_cap = cap;
    }
    memset(&g_ops[g_ops_n], 0, sizeof g_ops[0]);
    return &g_ops[g_ops_n++];
}

/* One folder's files.txt: its lines as ops, its hash; 0 refused (said). */
static int scan_one(const char* dir, int at, const char* sha)
{
    static char folders[MOD_MAX * 2][700]; /* each op's `mod`, kept for the run */
    const char* name = g_plan.names[at];
    char path[700], ipath[700], line[LINE_MAX_LEN], *tok[8];
    char *text, *ini;
    const char* t;
    size_t text_n = 0, ini_n = 0;
    int got, i;
    Where w;
    FilesMod* fm = &g_files[at];
    snprintf(path, sizeof path, "%s/%s/files.txt", dir, name);
    text = slurp_text(path, &text_n);
    if (!text) return 1; /* no files.txt: nothing for this pass */
    snprintf(folders[at], sizeof folders[at], "%s/%s", dir, name);
    fm->first = g_ops_n;
    fm->hash = fnv1a(2166136261u, text, text_n);
    /* the mod.ini's DOL hash and id, which no line may be placed without */
    snprintf(ipath, sizeof ipath, "%s/%s/mod.ini", dir, name);
    ini = slurp_text(ipath, &ini_n);
    w.path = ipath;
    w.failed = 0;
    w.line = 0;
    if (!ini) {
        refuse(&w, "a files.txt and no mod.ini beside it%s%s", "", "");
    } else {
        int sha_ok = 0;
        for (t = ini; !w.failed && (got = next_line(&t, line)) != 0;) {
            char* eq;
            w.line++;
            if (got == 2 || !(eq = strchr(line, '='))) continue;
            *eq = '\0';
            if (split(line, tok, 2) == 1 && !strcmp(tok[0], "dol_sha1")) {
                char lower[48];
                size_t k;
                char* val = eq + 1;
                while (*val == ' ' || *val == '\t') val++;
                for (k = strlen(val); k && strchr(" \t\r\n", val[k - 1]); k--) val[k - 1] = '\0';
                snprintf(lower, sizeof lower, "%s", val);
                for (k = 0; lower[k]; k++) lower[k] = (char)tolower((unsigned char)lower[k]);
                if (strcmp(lower, sha) != 0) refuse(&w, "made for the DOL with SHA-1 %s, and this is %s", val, sha);
                else sha_ok = 1;
            }
        }
        if (!w.failed && !sha_ok) {
            w.line = 0;
            refuse(&w, "no `dol_sha1 = ` naming the DOL it was made for%s%s", "", "");
        }
        for (i = 0; !w.failed && i < at; i++) /* the same id earlier in the order (load_one says it for the rest) */
            if (g_files[i].has_files && !g_files[i].refused && !strcmp(g_plan.plan[i].key, g_plan.plan[at].key) &&
                strcmp(g_plan.plan[at].key, name) != 0)
                refuse(&w, "its id, %s, is already the mod's in folder %s", g_plan.plan[at].key, g_plan.names[i]);
    }
    free(ini);
    w.path = path;
    w.line = 0;
    for (t = text; !w.failed && (got = next_line(&t, line)) != 0;) {
        int n;
        DiscFileOp* op;
        w.line++;
        if (got == 2) {
            refuse(&w, "a line longer than %s characters%s", "511", "");
            break;
        }
        n = split(line, tok, 8);
        if (n == 0) continue;
        if (!strcmp(tok[0], "delta") || !strcmp(tok[0], "swap")) {
            refuse(&w, "`%s` is not built yet (%s); replace, add and alias are", tok[0], tok[0][0] == 'd' ? "I7" : "I8");
            break;
        }
        if (strcmp(tok[0], "replace") && strcmp(tok[0], "add") && strcmp(tok[0], "alias")) {
            refuse(&w, "`%s` is not a verb: replace, add or alias%s", tok[0], "");
            break;
        }
        if (n != 3) {
            refuse(&w, "a line is `%s <path on the disc> %s`", tok[0], tok[0][1] == 'l' ? "<path on the disc>" : "<file in this folder>");
            break;
        }
        op = new_op();
        if (!op) {
            refuse(&w, "out of memory%s%s", "", "");
            break;
        }
        op->verb = tok[0][0] == 'r' ? DISC_REPLACE : tok[0][0] == 'a' && tok[0][1] == 'd' ? DISC_ADD : DISC_ALIAS;
        snprintf(op->path, sizeof op->path, "%s", tok[1]);
        op->mod = folders[at];
        op->line = (unsigned)w.line;
        op->mod_index = at;
        if (op->verb == DISC_ALIAS) {
            snprintf(op->target, sizeof op->target, "%s", tok[2]);
            fm->hash = fnv1a(fm->hash, tok[2], strlen(tok[2]));
        } else {
            char spath[1000];
            uint8_t* data;
            if (!source_ok(tok[2])) {
                refuse(&w, "`%s` is not a file in this folder: a relative path, forward slashes, no ..%s", tok[2], "");
                break;
            }
            snprintf(spath, sizeof spath, "%s/%s/%s", dir, name, tok[2]);
            data = read_source(spath, &op->size);
            if (!data) {
                refuse(&w, "cannot read %s%s", spath, "");
                break;
            }
            op->data = data; /* kept for the run: the drive serves it */
            fm->hash = fnv1a(fm->hash, (const char*)data, op->size);
        }
    }
    free(text);
    if (w.failed) {
        for (i = fm->first; i < g_ops_n; i++)
            if (g_ops[i].verb != DISC_ALIAS) free((void*)g_ops[i].data);
        g_ops_n = fm->first;
        fm->refused = 1;
        return 0;
    }
    fm->count = g_ops_n - fm->first;
    fm->has_files = 1;
    return 1;
}

int mod_scan_files(const char* dir, const uint8_t* dol, size_t dol_size, DiscFileOp** ops)
{
    char sha[41];
    int i;
    *ops = NULL;
    if (!plan_mods(dir)) return 0;
    sha1_hex(dol, dol_size, sha);
    for (i = 0; i < g_plan.k; i++) {
        int at = g_plan.order[i];
        if (!g_plan.plan[at].off && !g_plan.plan[at].bad) scan_one(dir, at, sha);
    }
    *ops = g_ops;
    return g_ops_n;
}

int mod_load(CpuState* s, const char* dir, const uint8_t* dol, size_t dol_size)
{
    int i;
    char sha[41];
    size_t used = 0;
    if (!plan_mods(dir)) return 0;
    sha1_hex(dol, dol_size, sha);
    g_s = s;
    mod_note_dol(dol, dol_size);
    {
        char (*names)[64] = g_plan.names;
        Planned* plan = g_plan.plan;
        int* order = g_plan.order;
        int k = g_plan.k;
        for (i = 0; i < k; i++) {
            int at = order[i];
            FilesMod* fm = &g_files[at];
            if (plan[at].off) {
                fprintf(stderr, "[mod] %s/%s is turned off by SOA_MOD_ORDER; not loaded\n", dir, names[at]);
                if (g_off_n < MOD_MAX * 2) snprintf(g_off[g_off_n++], sizeof g_off[0], "%s", plan[at].key);
            } else if (!plan[at].bad && !fm->refused && !(fm->has_files && fm->count && g_ops[fm->first].refused)) {
                int before = g_mod_n;
                load_one(s, dir, names[at], sha, dol, dol_size, fm->has_files, fm->hash);
                /* never half a mod: its files are on the disc now, the table parked */
                if (fm->has_files && fm->count && g_mod_n == before) {
                    fprintf(stderr, "[mod] %s/%s was refused after its files were placed on the disc; fix it or "
                                    "remove it\n", dir, names[at]);
                    exit(9);
                }
            }
        }
    }
    check_option_entries();
    /* The recording's line: every mod by name and hash while they fit -- a
     * manifest 2 mod as id@version, a version 1 mod by its folder -- 24 bytes
     * kept back so the rest can still be named, as a count and one hash over
     * all of them, rather than cut off mid-entry or dropped. The hash takes
     * each by the same name the line would have given it, so a manifest 2
     * mod past the line is still keyed by id and not by where it sits. A mod
     * with an option away from its default carries the values after its hash
     * (M16), so a mod at its defaults reads as it always did. */
    g_describe[0] = '\0';
    for (i = 0; i < g_mod_n; i++) {
        size_t room = sizeof g_describe - 24 - used;
        char opt[OPTION_MAX * 100];
        int k;
        option_text(i, opt, sizeof opt);
        k = g_mods[i].id[0]
                ? snprintf(g_describe + used, room, "%s%s@%s:%08x%s", i ? "," : "mods=", g_mods[i].id,
                           g_mods[i].version, g_mods[i].hash, opt)
                : snprintf(g_describe + used, room, "%s%s:%08x", i ? "," : "mods=", g_mods[i].dir, g_mods[i].hash);
        if (k < 0 || (size_t)k >= room) {
            g_describe[used] = '\0';
            break;
        }
        used += (size_t)k;
    }
    if (i < g_mod_n) {
        uint32_t rest = 2166136261u;
        int left = g_mod_n - i;
        for (; i < g_mod_n; i++) {
            char key[sizeof g_mods[i].id + sizeof g_mods[i].version + 1], opt[OPTION_MAX * 100];
            if (g_mods[i].id[0]) snprintf(key, sizeof key, "%s@%s", g_mods[i].id, g_mods[i].version);
            else snprintf(key, sizeof key, "%s", g_mods[i].dir);
            option_text(i, opt, sizeof opt);
            rest = fnv1a(fnv1a(fnv1a(rest, key, strlen(key)), (const char*)&g_mods[i].hash, 4), opt, strlen(opt));
        }
        snprintf(g_describe + used, sizeof g_describe - used, "%s+%d more:%08x", used ? "," : "mods=", left, rest);
    }
    if (g_cb_n[CB_SAFE_POINT] || g_cb_n[CB_MAP_LOADED] || g_cb_n[CB_SCENE_CHANGE]) tick_on_safe_point(mod_safe_point);
    if (g_cb_n[CB_PAD_FILTER]) si_set_pad_filter(mod_pad);
    if (g_cb_n[CB_PROJECTION]) gxr_set_projection_filter(mod_projection);
    if (g_cb_n[CB_TEXTURE]) gxr_set_texture_provider(mod_texture);
    fprintf(stderr, "[mod] SOA_MODS=%s: %d mod(s) loaded, %u patch(es)\n", dir, g_mod_n, g_patch_n);
    return g_mod_n;
}

/* ---- every frame ------------------------------------------------------- */

static int is_m6(const Patch* p) { return p->width != 4 || p->sign || p->ptr || p->mul || p->stride; }

/* Whether a patch may write the `n` bytes at `ea`: in RAM, on its alignment,
 * and outside the DOL's code. A pointer's target is known only now. */
static int target_ok(unsigned long long ea, uint32_t n)
{
    int i;
    if (ea < 0x80000000ull || ea + n > 0x80000000ull + MEM1_SIZE || (ea & (n - 1u))) return 0;
    for (i = 0; i < 7; i++)
        if (g_text[i][1] > g_text[i][0] && ea < g_text[i][1] && ea + n > g_text[i][0]) return 0;
    return 1;
}

static uint32_t read_n(CpuState* s, uint32_t ea, uint32_t n)
{
    return n == 1 ? mem_r8(s, ea) : n == 2 ? mem_r16(s, ea) : mem_r32(s, ea);
}

static void write_n(CpuState* s, uint32_t ea, uint32_t n, uint32_t v)
{
    if (n == 1) mem_w8(s, ea, (uint8_t)v);
    else if (n == 2) mem_w16(s, ea, (uint16_t)v);
    else mem_w32(s, ea, v);
}

/* was times the factor, toward zero, clamped to the width: unsigned, or for
 * an s width signed, as the game would read it back. */
static uint32_t scaled(uint32_t was, const Patch* p)
{
    unsigned bits = 8u * p->width;
    uint32_t mask = bits == 32 ? 0xFFFFFFFFu : (1u << bits) - 1;
    if (p->sign) {
        long long hi = (1ll << (bits - 1)) - 1, lo = -hi - 1, v = (long long)(was & mask);
        if (v > hi) v -= 1ll << bits;
        v = v * (long long)p->value / (long long)p->den;
        return (uint32_t)(v < lo ? lo : v > hi ? hi : v) & mask;
    } else {
        unsigned long long v = (unsigned long long)(was & mask) * p->value / p->den;
        return v > mask ? mask : (uint32_t)v;
    }
}

/* The patch as its line wrote it, for the log and the report. */
static void describe_patch(const Patch* p, char* buf, size_t cap)
{
    char target[48], value[24];
    int n = p->ptr ? snprintf(target, sizeof target, "[%08X]", p->ea) : snprintf(target, sizeof target, "%08X", p->ea);
    if (p->ptr && p->off) n += snprintf(target + n, sizeof target - (size_t)n, "+%u", p->off);
    if (p->stride) snprintf(target + n, sizeof target - (size_t)n, "+z*%u", p->stride);
    if (!p->mul) snprintf(value, sizeof value, "= %0*X", 2 * p->width, p->value);
    else if (p->den == 1) snprintf(value, sizeof value, "*= %u", p->value);
    else {
        int digits = p->den == 10 ? 1 : p->den == 100 ? 2 : p->den == 1000 ? 3 : 4;
        snprintf(value, sizeof value, "*= %u.%0*u", p->value / p->den, digits, p->value % p->den);
    }
    if (p->stride)
        snprintf(buf, cap, "%s %s %s %s for z=%u..%u", k_trigger[p->trigger], width_name(p), target, value, p->z0, p->z1);
    else
        snprintf(buf, cap, "%s %s %s %s", k_trigger[p->trigger], width_name(p), target, value);
}

/* An M6 patch's targets written; how many. A null pointer is passed over (a
 * map without an encounter table has one), and so is a target a patch may
 * not write, said once. *= leaves a target holding what it wrote there at
 * this map, so a load that did not put the word back is not multiplied
 * again. */
static unsigned apply_patch(CpuState* s, Patch* p, uint32_t key, unsigned frame)
{
    unsigned long long base = p->ea, ea;
    uint32_t z, was, now;
    unsigned written = 0;
    if (p->ptr) {
        if (p->ea == ENCOUNTER_TABLE && key >> 8 == WORLD_MAP) {
            if (!(p->warned & 2))
                fprintf(stderr, "[mod] %s patches.txt:%u: not applied on map 099, which keeps its encounter table "
                                "apart (fn_800C1A50); said once\n", g_mods[p->mod].dir, p->line);
            p->warned |= 2;
            return 0;
        }
        base = mem_r32(s, p->ea);
        if (!base) {
            p->nulls++;
            return 0;
        }
        base += p->off;
    }
    for (z = p->z0; z <= p->z1; z++) {
        ea = base + (unsigned long long)z * p->stride;
        if (!target_ok(ea, p->width)) {
            if (!(p->warned & 1))
                fprintf(stderr, "[mod] %s patches.txt:%u: at frame %u, z=%u is %08llX, which is outside RAM, off a "
                                "%s's alignment or in the game's code: not written, here or later; said once\n",
                        g_mods[p->mod].dir, p->line, frame, z, ea, width_name(p));
            p->warned |= 1;
            continue;
        }
        was = read_n(s, (uint32_t)ea, p->width);
        if (p->mul) {
            Slot* sl = &g_slots[p->slot + (z - p->z0)];
            if (sl->set && sl->key == key && sl->addr == (uint32_t)ea && sl->wrote == was) continue;
            now = scaled(was, p);
            sl->set = 1;
            sl->key = key;
            sl->addr = (uint32_t)ea;
            sl->wrote = now;
        } else {
            now = p->value;
        }
        gxr_hook_hazard((uint32_t)ea, p->width);
        write_n(s, (uint32_t)ea, p->width, now);
        written++;
        if (p->trigger == T_MAP_LOAD)
            fprintf(stderr, "[mod] %s patches.txt:%u: %08X: %0*X -> %0*X\n", g_mods[p->mod].dir, p->line,
                    (uint32_t)ea, 2 * p->width, was, 2 * p->width, now);
    }
    return written;
}

void mod_frame(CpuState* s, unsigned frame)
{
    uint32_t scene, state, number, key;
    uint8_t letter;
    int loaded;
    unsigned i;
    int c;
    if (!g_patch_n && !g_cb_n[CB_FRAME_END]) return;
    scene = mem_r32(s, SCENE_ID);
    state = mem_r32(s, FIELD_STATE);
    number = mem_r32(s, MAP_NUMBER);
    letter = mem_r8(s, MAP_LETTER);
    key = (number << 8) | letter;
    if (state == 3 || state == 5) g_patch_reload = 1;
    loaded = state == FIELD_RUNNING && (key != g_last_map || g_patch_reload);
    if (state == FIELD_RUNNING) {
        g_last_map = key;
        g_patch_reload = 0;
    }
    for (i = 0; i < g_patch_n; i++) {
        Patch* p = &g_patches[i];
        if (p->trigger == T_ONCE && p->fired) continue;
        if (p->trigger == T_MAP_LOAD && !loaded) continue;
        if (p->has_scene && scene != p->scene) continue;
        if (p->has_state && state != p->state) continue;
        if (p->has_map && (number != p->map_number || letter != p->map_letter)) continue;
        if (is_m6(p)) {
            if (!apply_patch(s, p, key, frame)) continue;
        } else {
            gxr_hook_hazard(p->ea, 4);
            mem_w32(s, p->ea, p->value);
        }
        if (!p->applied) p->first_frame = frame;
        p->applied++;
        p->fired = 1;
    }
    for (c = 0; c < g_cb_n[CB_FRAME_END]; c++) {
        g_cur_mod = g_cb[CB_FRAME_END][c].mod;
        g_cb[CB_FRAME_END][c].calls++;
        ((void (*)(void*))g_cb[CB_FRAME_END][c].fn)(g_cb[CB_FRAME_END][c].user);
    }
    g_cur_mod = -1;
}

const char* mod_describe(void) { return g_describe; }

/* Whether a mod with this manifest 2 id is loaded: settings.c asks, for a
 * setting only that mod reads. */
/* ---- M8: what the menu's Mods page reads (docs/specs/menu.md) --------- */

int mod_menu_count(void) { return g_mod_n; }

/* Mod m's name, and the key a list names it by (its id, or a version 1
 * mod's folder); NULL past the end. */
const char* mod_menu_name(int m, const char** key)
{
    if (m < 0 || m >= g_mod_n) return NULL;
    if (key) *key = mod_key(&g_mods[m]);
    return g_mods[m].name;
}

int mod_menu_option_count(int m) { return m >= 0 && m < g_mod_n ? g_opt_n[m] : 0; }

/* Mod m's option i: its name, type (0 int, 1 bool, 2 enum, 3 string, 4
 * seed), int range, enum choices ("a|b"), value in effect and default. */
int mod_menu_option(int m, int i, ModMenuOption* out)
{
    const Option* o;
    if (m < 0 || m >= g_mod_n || i < 0 || i >= g_opt_n[m]) return 0;
    o = &g_opts[m][i];
    out->name = o->name;
    out->type = o->type;
    out->lo = o->lo;
    out->hi = o->hi;
    out->choices = o->choices;
    out->value = o->value;
    out->def = o->def;
    return 1;
}

/* The mods turned off, so the page can turn one back on. */
int mod_menu_off_count(void) { return g_off_n; }
const char* mod_menu_off_key(int i) { return i >= 0 && i < g_off_n ? g_off[i] : NULL; }

int mod_loaded(const char* id)
{
    int i;
    for (i = 0; i < g_mod_n; i++)
        if (g_mods[i].id[0] && !strcmp(g_mods[i].id, id)) return 1;
    return 0;
}

void mod_report(void)
{
    int m;
    if (g_cb_n[CB_SAFE_POINT] || g_cb_n[CB_MAP_LOADED] || g_cb_n[CB_SCENE_CHANGE])
        fprintf(stderr, "[mod] the safe point saw %llu map load(s)\n", g_maps_loaded);
    for (m = 0; m < g_mod_n; m++) {
        unsigned i;
        if (g_mods[m].dll) {
            unsigned long long calls[CB_KINDS] = {0};
            int k, c;
            for (k = 0; k < CB_KINDS; k++)
                for (c = 0; c < g_cb_n[k]; c++)
                    if (g_cb[k][c].mod == m) calls[k] += g_cb[k][c].calls;
            fprintf(stderr, "[mod] %s " MOD_LIB ": %u callback(s); called at %llu frame end(s), %llu safe point(s), "
                            "%llu map load(s), %llu scene change(s), %llu controller read(s), %llu projection(s), "
                            "%llu texture(s); %llu write(s)\n",
                    g_mods[m].dir, g_mods[m].callbacks, calls[CB_FRAME_END], calls[CB_SAFE_POINT],
                    calls[CB_MAP_LOADED], calls[CB_SCENE_CHANGE], calls[CB_PAD_FILTER], calls[CB_PROJECTION],
                    calls[CB_TEXTURE], g_mods[m].writes);
        }
        for (i = g_mods[m].first; i < g_mods[m].first + g_mods[m].count; i++) {
            const Patch* p = &g_patches[i];
            if (is_m6(p)) {
                char what[160], why[160] = "";
                size_t k;
                describe_patch(p, what, sizeof what);
                if (p->nulls) snprintf(why, sizeof why, "; its pointer was null %llu time(s)", p->nulls);
                k = strlen(why);
                if (p->warned & 2) k += (size_t)snprintf(why + k, sizeof why - k, "; passed over on map 099");
                if (p->warned & 1) snprintf(why + k, sizeof why - k, "; a target it may not write passed over");
                if (p->applied)
                    fprintf(stderr, "[mod] %s patches.txt:%u: %s applied %llu time(s), first at frame %u%s\n",
                            g_mods[m].dir, p->line, what, p->applied, p->first_frame, why);
                else
                    fprintf(stderr, "[mod] %s patches.txt:%u: %s never applied%s\n", g_mods[m].dir, p->line, what,
                            why[0] ? why : ": its conditions never held");
                continue;
            }
            if (p->applied)
                fprintf(stderr, "[mod] %s patches.txt:%u: %s %08X = %08X applied %llu time(s), first at frame %u\n",
                        g_mods[m].dir, p->line, k_trigger[p->trigger], p->ea, p->value, p->applied, p->first_frame);
            else
                fprintf(stderr, "[mod] %s patches.txt:%u: %s %08X = %08X never applied: its conditions never "
                                "held\n", g_mods[m].dir, p->line, k_trigger[p->trigger], p->ea, p->value);
        }
    }
}
