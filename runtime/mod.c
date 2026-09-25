/*
 * Mods, data patches only (docs/PLAN-60FPS-MODS.md M1).
 *
 * SOA_MODS=<dir> names a folder of mods; every subfolder holding a mod.ini
 * is one, loaded in name order so that two runs apply them the same way:
 *
 *   mods/encounters-off/mod.ini
 *       name = Encounters off
 *       api = 1
 *       dol_sha1 = 8c0e278126fa3b0173400fdb632038172743cc13
 *   mods/encounters-off/patches.txt
 *       # trigger    address      value   conditions (all must hold)
 *       every_frame  0x80346d28 = 0       when scene=6
 *
 * A patch writes one 32-bit word at the end of a frame. Its trigger is
 * every_frame; once, the first frame its conditions hold; or on_map_load,
 * the first frame the field is running (state 8) in a map other than the
 * one it was last seen running in -- so a reload of the same map after a
 * battle is not a load, and a patch applied there never compounds. The
 * conditions read the scene id (0x803475CC: 6 is the field, 7 battle), the
 * field state (0x80311AEC) and the committed map, number and letter
 * (0x80311AC0 and the byte at 0x80311AC8; 0x80311AC4 is the picker's working
 * copy, FINDINGS "131e renders").
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
 * With SOA_MODS unset nothing here runs and nothing is printed.
 */
#include "mod.h"
#include "soa_mod.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <dirent.h>
#endif

#define MOD_MAX 32
#define PATCH_MAX 1024
#define LINE_MAX_LEN 512

#define SCENE_ID 0x803475CCu
#define FIELD_STATE 0x80311AECu
#define MAP_NUMBER 0x80311AC0u
#define MAP_LETTER 0x80311AC8u
#define FIELD_RUNNING 8u
#define STORY_FLAGS 0x80310B3Cu

enum { T_EVERY_FRAME, T_ONCE, T_MAP_LOAD };
static const char* const k_trigger[] = {"every_frame", "once", "on_map_load"};

typedef struct {
    uint32_t ea, value;
    uint8_t trigger, has_scene, has_state, has_map, fired;
    uint32_t scene, state, map_number;
    uint8_t map_letter;
    unsigned mod, line, first_frame;
    unsigned long long applied;
} Patch;

typedef struct {
    char dir[64];   /* the folder's name: what the recording names */
    char name[96];  /* what mod.ini calls it */
    uint32_t hash;  /* FNV-1a of mod.ini, patches.txt and mod.dll, for the recording */
    unsigned first, count;
    void* dll;          /* the loaded mod.dll, or NULL */
    unsigned callbacks; /* what it registered */
} Mod;

static Mod g_mods[MOD_MAX];
static int g_mod_n;
static Patch g_patches[PATCH_MAX];
static unsigned g_patch_n;
static uint32_t g_last_map = 0xFFFFFFFFu;
static char g_describe[300]; /* fits si.c's config line; later mods are left off */
static unsigned long long g_maps_loaded;

/* ---- SHA-1, for the DOL a mod names ------------------------------------ */

static uint32_t rol(uint32_t x, int k) { return (x << k) | (x >> (32 - k)); }

static void sha1_block(uint32_t h[5], const uint8_t* p)
{
    uint32_t w[80], a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f, k, t;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    for (i = 0; i < 80; i++) {
        if (i < 20) { f = (b & c) | (~b & d); k = 0x5A827999u; }
        else if (i < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1u; }
        else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDCu; }
        else { f = b ^ c ^ d; k = 0xCA62C1D6u; }
        t = rol(a, 5) + f + e + k + w[i];
        e = d; d = c; c = rol(b, 30); b = a; a = t;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
}

static void sha1_hex(const uint8_t* data, size_t n, char hex[41])
{
    uint32_t h[5] = {0x67452301u, 0xEFCDAB89u, 0x98BADCFEu, 0x10325476u, 0xC3D2E1F0u};
    uint8_t last[128];
    size_t i, rem = n % 64, full = n - rem, pad = rem < 56 ? 64 : 128;
    uint64_t bits = (uint64_t)n * 8;
    for (i = 0; i < full; i += 64) sha1_block(h, data + i);
    memset(last, 0, sizeof last);
    memcpy(last, data + full, rem);
    last[rem] = 0x80;
    for (i = 0; i < 8; i++) last[pad - 1 - i] = (uint8_t)(bits >> (8 * i));
    sha1_block(h, last);
    if (pad == 128) sha1_block(h, last + 64);
    for (i = 0; i < 5; i++) snprintf(hex + 8 * i, 9, "%08x", h[i]);
}

static uint32_t fnv1a(uint32_t h, const char* p, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) h = (h ^ (uint8_t)p[i]) * 16777619u;
    return h;
}

/* ---- the DOL's code, which no patch may write -------------------------- */

static uint32_t be32p(const uint8_t* p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

/* The text section `ea` falls in, or -1. Sections 0-6 of a DOL are code. */
static int in_text(const uint8_t* dol, size_t size, uint32_t ea, uint32_t* lo, uint32_t* hi)
{
    int i;
    if (size < 0x100) return -1;
    for (i = 0; i < 7; i++) {
        uint32_t addr = be32p(dol + 0x48 + i * 4), len = be32p(dol + 0x90 + i * 4);
        if (len && ea + 3 >= addr && ea < addr + len) {
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

static void parse_patch(Where* w, char* line, const uint8_t* dol, size_t dol_size, unsigned mod)
{
    char* tok[16];
    char where[64];
    int n = split(line, tok, 16), i;
    uint32_t lo, hi;
    Patch p;
    if (n == 0) return;
    memset(&p, 0, sizeof p);
    if (n < 0) { refuse(w, "too many words on one line%s%s", "", ""); return; }
    if (n < 4 || strcmp(tok[2], "=") != 0) {
        refuse(w, "a patch is `trigger 0x80346d28 = value [when condition...]`%s%s", "", "");
        return;
    }
    for (i = 0; i < 3 && strcmp(tok[0], k_trigger[i]) != 0; i++) {}
    if (i == 3) { refuse(w, "`%s` is not a trigger: every_frame, once or on_map_load%s", tok[0], ""); return; }
    p.trigger = (uint8_t)i;
    if (!parse_address(tok[1], &p.ea)) {
        refuse(w, "`%s` is not an address: a lowercase 0x and exactly eight hex digits, as in "
                  "0x80346d28%s", tok[1], "");
        return;
    }
    if (is_mmio(p.ea)) { refuse(w, "%s is in the hardware window, not memory%s", tok[1], ""); return; }
    if (p.ea < 0x80000000u || p.ea >= 0x80000000u + MEM1_SIZE) {
        refuse(w, "%s is outside the console's 24 MB of RAM, 0x80000000-0x817fffff%s", tok[1], "");
        return;
    }
    if (p.ea & 3) { refuse(w, "%s is not word-aligned, and a patch writes a whole 32-bit word%s", tok[1], ""); return; }
    if ((i = in_text(dol, dol_size, p.ea, &lo, &hi)) >= 0) {
        snprintf(where, sizeof where, "text section %d, %08x-%08x", i, lo, hi);
        refuse(w, "%s is inside the game's code (%s); a patch writes data only", tok[1], where);
        return;
    }
    if (!parse_u32(tok[3], &p.value)) {
        refuse(w, "`%s` is not a 32-bit value: 0x and up to eight hex digits, or decimal%s", tok[3], "");
        return;
    }
    if (n > 4) {
        if (strcmp(tok[4], "when") != 0 || n == 5) {
            refuse(w, "after the value comes `when` and one or more conditions, not `%s`%s", tok[4], "");
            return;
        }
        for (i = 5; i < n && !w->failed; i++) parse_condition(w, &p, tok[i]);
        if (w->failed) return;
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

/* The next line of `text`, copied into `line` (at most LINE_MAX_LEN). */
static int next_line(const char** text, char* line)
{
    const char* p = *text;
    size_t n = 0;
    if (!*p) return 0;
    while (*p && *p != '\n') {
        if (n < LINE_MAX_LEN - 1) line[n++] = *p;
        p++;
    }
    if (*p) p++;
    line[n] = '\0';
    *text = p;
    return 1;
}

/* ---- native mods: mod.dll on SoaModApi (PLAN M3) ------------------------ */

#define CB_MAX 64
enum { CB_FRAME_END, CB_SAFE_POINT, CB_MAP_LOADED, CB_SCENE_CHANGE, CB_PAD_FILTER, CB_KINDS };

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

/* RAM, aligned to the width, and for a write not the game's code. */
static int api_ok(uint32_t addr, uint32_t n, uint32_t align, int write)
{
    int i;
    if (!g_s || addr < 0x80000000u || addr >= 0x80000000u + MEM1_SIZE || n > 0x80000000u + MEM1_SIZE - addr)
        return 0;
    if (align > 1 && (addr & (align - 1))) return 0;
    if (write)
        for (i = 0; i < 7; i++)
            if (g_text[i][1] > g_text[i][0] && addr < g_text[i][1] && addr + n > g_text[i][0]) return 0;
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
static int api_write8(uint32_t a, uint8_t v) { if (!api_ok(a, 1, 1, 1)) return 0; mem_w8(g_s, a, v); return 1; }
static int api_write16(uint32_t a, uint16_t v) { if (!api_ok(a, 2, 2, 1)) return 0; mem_w16(g_s, a, v); return 1; }
static int api_write32(uint32_t a, uint32_t v) { if (!api_ok(a, 4, 4, 1)) return 0; mem_w32(g_s, a, v); return 1; }
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

static int api_register(int kind, void* fn, void* user)
{
    if (!fn || g_cb_n[kind] == CB_MAX) return 0;
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

static int api_pad_filter(void (*fn)(void*, uint32_t, SoaPad*), void* user)
{
    return api_register(CB_PAD_FILTER, (void*)fn, user);
}

static void api_log(const char* line)
{
    fprintf(stderr, "[mod] %s: %s\n", g_cur_mod >= 0 && g_cur_mod < g_mod_n ? g_mods[g_cur_mod].dir : g_cur_dir,
            line ? line : "");
}

static const SoaModApi g_api = {
    sizeof(SoaModApi), SOA_MOD_API_VERSION,
    api_read8, api_read16, api_read32, api_read_f32, api_read_bytes,
    api_write8, api_write16, api_write32, api_write_f32, api_write_bytes,
    api_scene, api_field_state, api_map, api_story_flag, api_frame,
    api_on_frame_end, api_on_safe_point, api_on_map_loaded, api_on_scene_change,
    api_log,
    api_pad_filter,
};

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

/* The top of the main loop (tick.c): the safe point, then what it derives --
 * a scene change, and a map loaded, which is the field running (state 8)
 * after a load state (3 or 5) was seen: every story warp, name warp and
 * return from a battle passes through both (FINDINGS "How the story's own
 * warps run"), so a reload of the same map is a load too. */
static void mod_safe_point(CpuState* s)
{
    uint32_t scene = mem_r32(s, SCENE_ID), state = mem_r32(s, FIELD_STATE);
    int i;
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
    g_cur_mod = -1;
}

/* mod.dll, when there is one: loaded by full path, its soa_mod_init called
 * with the API; anything it registered is taken back if it refuses. 1 on
 * success, 0 (having said why) otherwise. */
static int load_dll(Where* w, const char* path, Mod* m, unsigned* dll_hash)
{
#ifdef _WIN32
    char full[MAX_PATH];
    HMODULE h;
    SoaModInit init;
    int before[CB_KINDS], k, rc;
    size_t n = 0;
    char* bytes = slurp_text(path, &n);
    if (!bytes) return -1; /* no mod.dll: nothing to load */
    *dll_hash = fnv1a(2166136261u, bytes, n);
    free(bytes);
    if (!GetFullPathNameA(path, sizeof full, full, NULL)) {
        refuse(w, "cannot resolve %s%s", path, "");
        return 0;
    }
    h = LoadLibraryExA(full, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!h) {
        char code[16];
        snprintf(code, sizeof code, "%lu", (unsigned long)GetLastError());
        refuse(w, "Windows would not load it (error %s)%s", code, "");
        return 0;
    }
    init = (SoaModInit)(void (*)(void))GetProcAddress(h, "soa_mod_init");
    if (!init) {
        FreeLibrary(h);
        refuse(w, "it exports no soa_mod_init%s%s", "", "");
        return 0;
    }
    for (k = 0; k < CB_KINDS; k++) before[k] = g_cb_n[k];
    g_cur_mod = g_mod_n;
    snprintf(g_cur_dir, sizeof g_cur_dir, "%s", m->dir);
    rc = init(&g_api, SOA_MOD_API_VERSION);
    g_cur_mod = -1;
    if (rc != 0) {
        char code[16];
        for (k = 0; k < CB_KINDS; k++) g_cb_n[k] = before[k];
        FreeLibrary(h);
        snprintf(code, sizeof code, "%d", rc);
        refuse(w, "its soa_mod_init refused, returning %s%s", code, "");
        return 0;
    }
    m->dll = (void*)h;
    for (k = 0; k < CB_KINDS; k++) m->callbacks += (unsigned)(g_cb_n[k] - before[k]);
    return 1;
#else
    size_t n = 0;
    char* bytes = slurp_text(path, &n);
    (void)m;
    (void)dll_hash;
    if (!bytes) return -1;
    free(bytes);
    refuse(w, "mod.dll needs Windows%s%s", "", "");
    return 0;
#endif
}

static void load_one(CpuState* s, const char* root, const char* dir, const char* dol_sha1,
                     const uint8_t* dol, size_t dol_size)
{
    char path[600], ppath[600], dpath[600], line[LINE_MAX_LEN], *tok[8];
    char *ini, *patches;
    const char* t;
    size_t ini_n = 0, patches_n = 0;
    int have_api = 0, dll;
    unsigned dll_hash = 0;
    Where w;
    Mod m;
    unsigned before = g_patch_n;
    (void)s;
    memset(&m, 0, sizeof m);
    snprintf(m.dir, sizeof m.dir, "%s", dir);
    snprintf(path, sizeof path, "%s/%s/mod.ini", root, dir);
    snprintf(ppath, sizeof ppath, "%s/%s/patches.txt", root, dir);
    snprintf(dpath, sizeof dpath, "%s/%s/mod.dll", root, dir);
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
    for (t = ini; next_line(&t, line);) {
        char* eq;
        w.line++;
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
            } else if (!strcmp(key, "api")) {
                have_api = 1;
                if (strcmp(val, "1") != 0) refuse(&w, "api = %s, and this port speaks api %s", val, "1");
            } else if (!strcmp(key, "dol_sha1")) {
                size_t i;
                char lower[48];
                snprintf(lower, sizeof lower, "%s", val);
                for (i = 0; lower[i]; i++) lower[i] = (char)tolower((unsigned char)lower[i]);
                if (strcmp(lower, dol_sha1) != 0)
                    refuse(&w, "made for the DOL with SHA-1 %s, and this is %s", val, dol_sha1);
                else
                    m.hash = 1; /* seen and matching; replaced by the content hash below */
            } else {
                refuse(&w, "`%s` is not a mod.ini key: name, api or dol_sha1%s", key, "");
            }
        }
    }
    w.line = 0;
    if (!w.failed && !m.name[0]) refuse(&w, "no `name = `%s%s", "", "");
    if (!w.failed && !have_api) refuse(&w, "no `api = 1`%s%s", "", "");
    if (!w.failed && !m.hash) refuse(&w, "no `dol_sha1 = ` naming the DOL it was made for%s%s", "", "");
    if (w.failed) { free(ini); return; }

    patches = slurp_text(ppath, &patches_n);
    if (patches) {
        w.path = ppath;
        for (t = patches; next_line(&t, line) && !w.failed;) {
            w.line++;
            parse_patch(&w, line, dol, dol_size, (unsigned)g_mod_n);
        }
        if (!w.failed && g_patch_n == before) {
            w.line = 0;
            refuse(&w, "no patches in it%s%s", "", "");
        }
    }
    dll = -1;
    if (!w.failed) {
        w.path = dpath;
        w.line = 0;
        dll = load_dll(&w, dpath, &m, &dll_hash);
        if (dll < 0 && !patches) {
            w.path = path;
            refuse(&w, "no patches.txt and no mod.dll beside it, so it would do nothing%s%s", "", "");
        }
    }
    if (w.failed) {
        g_patch_n = before; /* refused whole */
    } else {
        m.hash = fnv1a(fnv1a(2166136261u, ini, ini_n), patches ? patches : "", patches_n) ^ dll_hash;
        m.first = before;
        m.count = g_patch_n - before;
        g_mods[g_mod_n++] = m;
        fprintf(stderr, "[mod] loaded %s (%s/%s): %u patch(es)%s, api %d, the DOL it names\n", m.name, root, dir,
                m.count, m.dll ? " and mod.dll" : "", MOD_API);
    }
    free(ini);
    free(patches);
}

static int cmp_name(const void* a, const void* b) { return strcmp((const char*)a, (const char*)b); }

int mod_load(CpuState* s, const char* dir, const uint8_t* dol, size_t dol_size)
{
    static char names[MOD_MAX * 2][64];
    int n = 0, i;
    char sha[41];
    size_t used = 0;
#ifdef _WIN32
    char pattern[600];
    WIN32_FIND_DATAA fd;
    HANDLE h;
    snprintf(pattern, sizeof pattern, "%s/*", dir);
    h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) {
        fprintf(stderr, "[mod] SOA_MODS=%s is not a folder this port can read; no mods\n", dir);
        return 0;
    }
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || fd.cFileName[0] == '.') continue;
        if (n < MOD_MAX * 2 && strlen(fd.cFileName) < 64) snprintf(names[n++], 64, "%s", fd.cFileName);
    } while (FindNextFileA(h, &fd));
    FindClose(h);
#else
    DIR* d = opendir(dir);
    struct dirent* e;
    if (!d) {
        fprintf(stderr, "[mod] SOA_MODS=%s is not a folder this port can read; no mods\n", dir);
        return 0;
    }
    while ((e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        if (n < MOD_MAX * 2 && strlen(e->d_name) < 64) snprintf(names[n++], 64, "%s", e->d_name);
    }
    closedir(d);
#endif
    qsort(names, (size_t)n, sizeof names[0], cmp_name);
    sha1_hex(dol, dol_size, sha);
    g_s = s;
    if (dol_size >= 0x100)
        for (i = 0; i < 7; i++) {
            g_text[i][0] = be32p(dol + 0x48 + i * 4);
            g_text[i][1] = g_text[i][0] + be32p(dol + 0x90 + i * 4);
        }
    for (i = 0; i < n; i++) load_one(s, dir, names[i], sha, dol, dol_size);
    g_describe[0] = '\0';
    for (i = 0; i < g_mod_n; i++) {
        int k = snprintf(g_describe + used, sizeof g_describe - used, "%s%s:%08x", i ? "," : "mods=",
                         g_mods[i].dir, g_mods[i].hash);
        if (k < 0 || (size_t)k >= sizeof g_describe - used) break;
        used += (size_t)k;
    }
    if (g_cb_n[CB_SAFE_POINT] || g_cb_n[CB_MAP_LOADED] || g_cb_n[CB_SCENE_CHANGE]) tick_on_safe_point(mod_safe_point);
    if (g_cb_n[CB_PAD_FILTER]) si_set_pad_filter(mod_pad);
    fprintf(stderr, "[mod] SOA_MODS=%s: %d mod(s) loaded, %u patch(es)\n", dir, g_mod_n, g_patch_n);
    return g_mod_n;
}

/* ---- every frame ------------------------------------------------------- */

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
    loaded = state == FIELD_RUNNING && key != g_last_map;
    if (state == FIELD_RUNNING) g_last_map = key;
    for (i = 0; i < g_patch_n; i++) {
        Patch* p = &g_patches[i];
        if (p->trigger == T_ONCE && p->fired) continue;
        if (p->trigger == T_MAP_LOAD && !loaded) continue;
        if (p->has_scene && scene != p->scene) continue;
        if (p->has_state && state != p->state) continue;
        if (p->has_map && (number != p->map_number || letter != p->map_letter)) continue;
        mem_w32(s, p->ea, p->value);
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
            fprintf(stderr, "[mod] %s mod.dll: %u callback(s); called at %llu frame end(s), %llu safe point(s), "
                            "%llu map load(s), %llu scene change(s), %llu controller read(s)\n", g_mods[m].dir,
                    g_mods[m].callbacks, calls[CB_FRAME_END], calls[CB_SAFE_POINT], calls[CB_MAP_LOADED],
                    calls[CB_SCENE_CHANGE], calls[CB_PAD_FILTER]);
        }
        for (i = g_mods[m].first; i < g_mods[m].first + g_mods[m].count; i++) {
            const Patch* p = &g_patches[i];
            if (p->applied)
                fprintf(stderr, "[mod] %s patches.txt:%u: %s %08X = %08X applied %llu time(s), first at frame %u\n",
                        g_mods[m].dir, p->line, k_trigger[p->trigger], p->ea, p->value, p->applied, p->first_frame);
            else
                fprintf(stderr, "[mod] %s patches.txt:%u: %s %08X = %08X never applied: its conditions never "
                                "held\n", g_mods[m].dir, p->line, k_trigger[p->trigger], p->ea, p->value);
        }
    }
}
