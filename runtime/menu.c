/*
 * The in-game menu (M8a, docs/specs/menu.md): pages of rows a person moves
 * through with the pad or the keyboard, and the drawing of them over the
 * presented picture.
 *
 * Main: Resume, Mods, Settings, Fullscreen and Turbo (applied now), Save now
 * (M7a: the game's save menu, wherever the field is quiet), Debug (M7b: warp,
 * part select, the fade fix, the encounter toggle, the ending), Quit.
 * Mods: each mod, on or off (soa.ini's mod_order, `-ID` off); entered, its
 * declared options (M16). Settings: every soa.ini key with a closed set of
 * values. A change other than fullscreen and turbo is written to soa.ini at
 * once, keeping the rest of the file (settings_set), and the page says the
 * game reads it at its next start: options are fixed when a mod loads.
 *
 * Nothing here knows the window or the system. The window code turns keys
 * and the pad into menu_input calls, acts on the bits that come back, and
 * draws with menu_draw into its scaled buffer -- never the game's picture,
 * which the frame hashes are taken from. The font is the port's own: 5x7
 * glyphs for printable ASCII, drawn in 6x9 cells at a whole-number scale, g,
 * j, p, q and y a row lower so their tails hang below the line.
 */
#include "menu.h"
#include "actions.h"

#include "mod.h"
#include "plat.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* settings.c's side (M8). */
int settings_set(const char* key, const char* value);
int settings_menu_count(void);
int settings_menu_item(int index, const char** key, const char** choices, const char** what, const char** value);

/* ---- the font ------------------------------------------------------------ */

/* Printable ASCII, ' ' to '~', each 7 rows of 5, '#' lit. */
static const char* const k_font[95][7] = {
    {".....", ".....", ".....", ".....", ".....", ".....", "....."}, /* ' ' */
    {"..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."}, /* ! */
    {".#.#.", ".#.#.", ".#.#.", ".....", ".....", ".....", "....."}, /* " */
    {".#.#.", ".#.#.", "#####", ".#.#.", "#####", ".#.#.", ".#.#."}, /* # */
    {"..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."}, /* $ */
    {"##...", "##..#", "...#.", "..#..", ".#...", "#..##", "...##"}, /* % */
    {".##..", "#..#.", "#.#..", ".#...", "#.#.#", "#..#.", ".##.#"}, /* & */
    {".##..", "..#..", ".#...", ".....", ".....", ".....", "....."}, /* ' */
    {"...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."}, /* ( */
    {".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."}, /* ) */
    {".....", "..#..", "#.#.#", ".###.", "#.#.#", "..#..", "....."}, /* * */
    {".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."}, /* + */
    {".....", ".....", ".....", ".....", ".##..", "..#..", ".#..."}, /* , */
    {".....", ".....", ".....", "#####", ".....", ".....", "....."}, /* - */
    {".....", ".....", ".....", ".....", ".....", ".##..", ".##.."}, /* . */
    {".....", "....#", "...#.", "..#..", ".#...", "#....", "....."}, /* / */
    {".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."}, /* 0 */
    {"..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."}, /* 1 */
    {".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"}, /* 2 */
    {"#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."}, /* 3 */
    {"...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."}, /* 4 */
    {"#####", "#....", "####.", "....#", "....#", "#...#", ".###."}, /* 5 */
    {"..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."}, /* 6 */
    {"#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."}, /* 7 */
    {".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."}, /* 8 */
    {".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."}, /* 9 */
    {".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."}, /* : */
    {".....", ".##..", ".##..", ".....", ".##..", "..#..", ".#..."}, /* ; */
    {"...#.", "..#..", ".#...", "#....", ".#...", "..#..", "...#."}, /* < */
    {".....", ".....", "#####", ".....", "#####", ".....", "....."}, /* = */
    {".#...", "..#..", "...#.", "....#", "...#.", "..#..", ".#..."}, /* > */
    {".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."}, /* ? */
    {".###.", "#...#", "....#", ".##.#", "#.#.#", "#.#.#", ".###."}, /* @ */
    {".###.", "#...#", "#...#", "#...#", "#####", "#...#", "#...#"}, /* A */
    {"####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."}, /* B */
    {".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."}, /* C */
    {"###..", "#..#.", "#...#", "#...#", "#...#", "#..#.", "###.."}, /* D */
    {"#####", "#....", "#....", "####.", "#....", "#....", "#####"}, /* E */
    {"#####", "#....", "#....", "####.", "#....", "#....", "#...."}, /* F */
    {".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"}, /* G */
    {"#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"}, /* H */
    {".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."}, /* I */
    {"..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."}, /* J */
    {"#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"}, /* K */
    {"#....", "#....", "#....", "#....", "#....", "#....", "#####"}, /* L */
    {"#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"}, /* M */
    {"#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"}, /* N */
    {".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."}, /* O */
    {"####.", "#...#", "#...#", "####.", "#....", "#....", "#...."}, /* P */
    {".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"}, /* Q */
    {"####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"}, /* R */
    {".####", "#....", "#....", ".###.", "....#", "....#", "####."}, /* S */
    {"#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."}, /* T */
    {"#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."}, /* U */
    {"#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."}, /* V */
    {"#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."}, /* W */
    {"#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"}, /* X */
    {"#...#", "#...#", "#...#", ".#.#.", "..#..", "..#..", "..#.."}, /* Y */
    {"#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"}, /* Z */
    {".###.", ".#...", ".#...", ".#...", ".#...", ".#...", ".###."}, /* [ */
    {".....", "#....", ".#...", "..#..", "...#.", "....#", "....."}, /* backslash */
    {".###.", "...#.", "...#.", "...#.", "...#.", "...#.", ".###."}, /* ] */
    {"..#..", ".#.#.", "#...#", ".....", ".....", ".....", "....."}, /* ^ */
    {".....", ".....", ".....", ".....", ".....", ".....", "#####"}, /* _ */
    {".#...", "..#..", "...#.", ".....", ".....", ".....", "....."}, /* ` */
    {".....", ".....", ".###.", "....#", ".####", "#...#", ".####"}, /* a */
    {"#....", "#....", "#.##.", "##..#", "#...#", "#...#", "####."}, /* b */
    {".....", ".....", ".###.", "#....", "#....", "#...#", ".###."}, /* c */
    {"....#", "....#", ".##.#", "#..##", "#...#", "#...#", ".####"}, /* d */
    {".....", ".....", ".###.", "#...#", "#####", "#....", ".###."}, /* e */
    {"..##.", ".#..#", ".#...", "###..", ".#...", ".#...", ".#..."}, /* f */
    {".....", ".####", "#...#", "#...#", ".####", "....#", ".###."}, /* g */
    {"#....", "#....", "#.##.", "##..#", "#...#", "#...#", "#...#"}, /* h */
    {"..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###."}, /* i */
    {"...#.", ".....", "..##.", "...#.", "...#.", "#..#.", ".##.."}, /* j */
    {"#....", "#....", "#..#.", "#.#..", "##...", "#.#..", "#..#."}, /* k */
    {".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."}, /* l */
    {".....", ".....", "##.#.", "#.#.#", "#.#.#", "#...#", "#...#"}, /* m */
    {".....", ".....", "#.##.", "##..#", "#...#", "#...#", "#...#"}, /* n */
    {".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###."}, /* o */
    {".....", "####.", "#...#", "#...#", "####.", "#....", "#...."}, /* p */
    {".....", ".####", "#...#", "#...#", ".####", "....#", "....#"}, /* q */
    {".....", ".....", "#.##.", "##..#", "#....", "#....", "#...."}, /* r */
    {".....", ".....", ".###.", "#....", ".###.", "....#", "####."}, /* s */
    {".#...", ".#...", "###..", ".#...", ".#...", ".#..#", "..##."}, /* t */
    {".....", ".....", "#...#", "#...#", "#...#", "#..##", ".##.#"}, /* u */
    {".....", ".....", "#...#", "#...#", "#...#", ".#.#.", "..#.."}, /* v */
    {".....", ".....", "#...#", "#...#", "#.#.#", "#.#.#", ".#.#."}, /* w */
    {".....", ".....", "#...#", ".#.#.", "..#..", ".#.#.", "#...#"}, /* x */
    {".....", ".....", "#...#", "#...#", ".####", "....#", ".###."}, /* y */
    {".....", ".....", "#####", "...#.", "..#..", ".#...", "#####"}, /* z */
    {"...#.", "..#..", "..#..", ".#...", "..#..", "..#..", "...#."}, /* { */
    {"..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."}, /* | */
    {".#...", "..#..", "..#..", "...#.", "..#..", "..#..", ".#..."}, /* } */
    {".....", ".....", ".#...", "#.#.#", "...#.", ".....", "....."}, /* ~ */
};

#define CELL_W 6
#define CELL_H 9
#define COLS 46     /* characters a row of the panel holds: 640 wide draws it at scale 2 */
#define ROWS_SHOWN 12 /* item rows on screen at once; more scroll */

/* ---- the model ----------------------------------------------------------- */

enum { PAGE_MAIN, PAGE_MODS, PAGE_MOD, PAGE_SETTINGS, PAGE_DEBUG, PAGES };
enum {
    K_RESUME, K_PAGE_MODS, K_PAGE_SETTINGS, K_FULLSCREEN, K_TURBO, K_SAVE_NOW, K_PAGE_DEBUG, K_QUIT, K_MOD, K_MOD_OFF,
    K_OPTION, K_SETTING, K_DBG_WARP, K_DBG_PART, K_DBG_FADE, K_DBG_ENC, K_DBG_ENDING
};

typedef struct {
    int kind, ref;
    char label[40];
    char value[40];
} Item;

static plat_a32 g_open;
static int g_page, g_sel[PAGES], g_top[PAGES], g_mod; /* g_mod: the mod PAGE_MOD shows */
static int g_warp;                                     /* M7b: the warp row's map, an index of actions_warp_map */
static int g_fullscreen, g_turbo;
static char g_status[96];

/* What this menu has written this run: soa.ini's new values, which the
 * game has not read yet, shown in place of the values in effect. */
#define EDITS 64
static struct {
    char key[80], value[64];
} g_edits[EDITS];
static int g_edit_n;

static const char* edited(const char* key)
{
    int i;
    for (i = 0; i < g_edit_n; i++)
        if (!strcmp(g_edits[i].key, key)) return g_edits[i].value;
    return NULL;
}

static void save(const char* key, const char* value)
{
    int i;
    if (!settings_set(key, value)) {
        snprintf(g_status, sizeof g_status, "could not save %s: the log says why", key);
        return;
    }
    for (i = 0; i < g_edit_n && strcmp(g_edits[i].key, key) != 0; i++) {}
    if (i == g_edit_n) {
        if (g_edit_n == EDITS) return;
        g_edit_n++;
    }
    snprintf(g_edits[i].key, sizeof g_edits[i].key, "%s", key);
    snprintf(g_edits[i].value, sizeof g_edits[i].value, "%s", value);
    snprintf(g_status, sizeof g_status, "saved; the game reads it when it next starts");
}

/* The next or previous of "a|b|c" from `now` (a value not in the list goes
 * to the first or the last). */
static void cycle(const char* choices, const char* now, int dir, char* out, size_t cap)
{
    const char* list[32];
    size_t len[32];
    int n = 0, at = -1, i;
    const char* p = choices;
    while (p && *p && n < 32) {
        const char* bar = strchr(p, '|');
        len[n] = bar ? (size_t)(bar - p) : strlen(p);
        list[n] = p;
        if (len[n] == strlen(now) && !strncmp(p, now, len[n])) at = n;
        n++;
        p = bar ? bar + 1 : NULL;
    }
    if (!n) {
        snprintf(out, cap, "%s", now);
        return;
    }
    i = at < 0 ? (dir > 0 ? 0 : n - 1) : (at + dir + n) % n;
    snprintf(out, cap, "%.*s", (int)len[i], list[i]);
}

/* soa.ini's mod_order as it will be read next: this run's edit, else the
 * value in effect. */
static const char* order_now(void)
{
    const char* e = edited("mod_order");
    const char* v = getenv("SOA_MOD_ORDER");
    return e ? e : v ? v : "";
}

/* Whether the list turns `key` off. */
static int turned_off(const char* key)
{
    const char* p = order_now();
    size_t n = strlen(key);
    while (*p) {
        while (*p == ' ' || *p == ',') p++;
        if (*p == '-' && !strncmp(p + 1, key, n) && (p[1 + n] == ',' || p[1 + n] == ' ' || !p[1 + n])) return 1;
        while (*p && *p != ',') p++;
    }
    return 0;
}

/* mod_order with `key` turned on or off, every other entry kept. */
static void set_mod_on(const char* key, int on)
{
    char out[512];
    size_t used = 0, n = strlen(key);
    const char* p = order_now();
    out[0] = '\0';
    while (*p) {
        const char *a, *b;
        while (*p == ' ' || *p == ',') p++;
        a = p;
        while (*p && *p != ',') p++;
        b = p;
        while (b > a && b[-1] == ' ') b--;
        if (b == a) continue;
        if ((size_t)(b - a) == n + (*a == '-') && !strncmp(a + (*a == '-'), key, n)) continue; /* this mod's entry */
        used += (size_t)snprintf(out + used, sizeof out - used, "%s%.*s", used ? "," : "", (int)(b - a), a);
        if (used >= sizeof out) return;
    }
    if (!on) snprintf(out + used, sizeof out - used, "%s-%s", used ? "," : "", key);
    save("mod_order", out);
}

static int items(Item* it, int max)
{
    int n = 0, i, m;
#define ADD(k, r, l, v)                                                   \
    do {                                                                  \
        if (n < max) {                                                    \
            it[n].kind = (k);                                             \
            it[n].ref = (r);                                              \
            snprintf(it[n].label, sizeof it[n].label, "%s", (l));         \
            snprintf(it[n].value, sizeof it[n].value, "%s", (v));         \
            n++;                                                          \
        }                                                                 \
    } while (0)
    switch (g_page) {
    case PAGE_MAIN:
        ADD(K_RESUME, 0, "Resume", "");
        ADD(K_PAGE_MODS, 0, "Mods", ">");
        ADD(K_PAGE_SETTINGS, 0, "Settings", ">");
        ADD(K_FULLSCREEN, 0, "Fullscreen", g_fullscreen ? "on" : "off");
        ADD(K_TURBO, 0, "Turbo", g_turbo ? "on" : "off");
        ADD(K_SAVE_NOW, 0, "Save now", "");
        ADD(K_PAGE_DEBUG, 0, "Debug", ">");
        ADD(K_QUIT, 0, "Quit", "");
        break;
    case PAGE_DEBUG: {
        /* M7b: each taken with A, which closes the menu; the next safe point decides */
        uint32_t map = actions_warp_map(g_warp);
        char v[16];
        snprintf(v, sizeof v, "< %03u%c >", map >> 8, (char)(map & 0xFF));
        ADD(K_DBG_WARP, 0, "Warp to", v);
        ADD(K_DBG_PART, 0, "Part select", "");
        ADD(K_DBG_FADE, 0, "Fade fix", "");
        ADD(K_DBG_ENC, 0, "Encounters", actions_encounters_off() ? "off" : "on");
        ADD(K_DBG_ENDING, 0, "The ending", "");
        break;
    }
    case PAGE_MODS:
        for (m = 0; m < mod_menu_count(); m++) {
            const char* key = "";
            const char* name = mod_menu_name(m, &key);
            char v[40];
            snprintf(v, sizeof v, "%s%s", turned_off(key) ? "off" : "on", mod_menu_option_count(m) ? "  >" : "");
            ADD(K_MOD, m, name, v);
        }
        for (i = 0; i < mod_menu_off_count(); i++) ADD(K_MOD_OFF, i, mod_menu_off_key(i), turned_off(mod_menu_off_key(i)) ? "off" : "on");
        if (!n) ADD(K_RESUME, -1, "(no mods loaded)", "");
        break;
    case PAGE_MOD:
        for (i = 0; i < mod_menu_option_count(g_mod); i++) {
            ModMenuOption o;
            const char* key = "";
            char full[128];
            const char* e;
            mod_menu_option(g_mod, i, &o);
            mod_menu_name(g_mod, &key);
            snprintf(full, sizeof full, "%s.%s", key, o.name);
            e = edited(full);
            ADD(K_OPTION, i, o.name, e ? e : o.value);
        }
        break;
    default:
        for (i = 0; i < settings_menu_count(); i++) {
            const char *key, *choices, *what, *value;
            const char* e;
            settings_menu_item(i, &key, &choices, &what, &value);
            e = edited(key);
            ADD(K_SETTING, i, key, e ? e : *value ? value : "default");
        }
        break;
    }
#undef ADD
    return n;
}

int menu_is_open(void) { return plat_load32(&g_open) != 0; }

void menu_open(void)
{
    g_page = PAGE_MAIN;
    memset(g_sel, 0, sizeof g_sel);
    memset(g_top, 0, sizeof g_top);
    g_status[0] = '\0';
    plat_cas32(&g_open, 0, 1);
}

void menu_close(void) { plat_cas32(&g_open, 1, 0); }

void menu_set_state(int fullscreen, int turbo)
{
    g_fullscreen = fullscreen;
    g_turbo = turbo;
}

/* Left or right on an item: its value changed, and saved where it is a
 * soa.ini value. */
static int change(const Item* it, int dir, int big)
{
    char v[64];
    switch (it->kind) {
    case K_DBG_WARP: {
        int count = actions_warp_count(), step = big ? (count / 10 > 1 ? count / 10 : 1) : 1;
        if (count) g_warp = ((g_warp + dir * step) % count + count) % count;
        return MENU_ACT_REDRAW;
    }
    case K_FULLSCREEN:
        return MENU_ACT_FULLSCREEN | MENU_ACT_REDRAW;
    case K_TURBO:
        return MENU_ACT_TURBO | MENU_ACT_REDRAW;
    case K_MOD: {
        const char* key = "";
        mod_menu_name(it->ref, &key);
        set_mod_on(key, turned_off(key));
        return MENU_ACT_REDRAW;
    }
    case K_MOD_OFF:
        set_mod_on(mod_menu_off_key(it->ref), turned_off(mod_menu_off_key(it->ref)));
        return MENU_ACT_REDRAW;
    case K_OPTION: {
        ModMenuOption o;
        const char* key = "";
        char full[128];
        mod_menu_option(g_mod, it->ref, &o);
        mod_menu_name(g_mod, &key);
        snprintf(full, sizeof full, "%s.%s", key, o.name);
        if (o.type == 2) cycle(o.choices, it->value, dir, v, sizeof v);
        else if (o.type == 1) snprintf(v, sizeof v, "%s", strcmp(it->value, "0") ? "0" : "1");
        else if (o.type == 0) {
            long long now = strtoll(it->value, NULL, 10), step = big ? (o.hi - o.lo) / 10 : 1;
            now += dir * (step ? step : 1);
            snprintf(v, sizeof v, "%lld", now < o.lo ? o.lo : now > o.hi ? o.hi : now);
        } else {
            snprintf(g_status, sizeof g_status, "%s is set in soa.ini or SOA_MOD_OPT, not here", o.name);
            return MENU_ACT_REDRAW;
        }
        save(full, v);
        return MENU_ACT_REDRAW;
    }
    case K_SETTING: {
        const char *key, *choices, *what, *value;
        settings_menu_item(it->ref, &key, &choices, &what, &value);
        cycle(choices, strcmp(it->value, "default") ? it->value : "", dir, v, sizeof v);
        save(key, v);
        return MENU_ACT_REDRAW;
    }
    default:
        return 0;
    }
}

int menu_input(int key)
{
    Item it[64];
    int n, *sel = &g_sel[g_page];
    if (!menu_is_open()) return 0;
    n = items(it, 64);
    if (*sel >= n) *sel = n ? n - 1 : 0;
    switch (key) {
    case MENU_TOGGLE:
        menu_close();
        return MENU_ACT_CLOSE | MENU_ACT_REDRAW;
    case MENU_UP:
        if (n) *sel = (*sel + n - 1) % n;
        return MENU_ACT_REDRAW;
    case MENU_DOWN:
        if (n) *sel = (*sel + 1) % n;
        return MENU_ACT_REDRAW;
    case MENU_BACK:
        g_status[0] = '\0';
        if (g_page == PAGE_MAIN) {
            menu_close();
            return MENU_ACT_CLOSE | MENU_ACT_REDRAW;
        }
        g_page = g_page == PAGE_MOD ? PAGE_MODS : PAGE_MAIN;
        return MENU_ACT_REDRAW;
    case MENU_LEFT:
    case MENU_RIGHT:
    case MENU_BIG_LEFT:
    case MENU_BIG_RIGHT:
        if (!n) return 0;
        return change(&it[*sel], key == MENU_LEFT || key == MENU_BIG_LEFT ? -1 : 1,
                      key == MENU_BIG_LEFT || key == MENU_BIG_RIGHT);
    case MENU_OK:
        if (!n) return 0;
        switch (it[*sel].kind) {
        case K_RESUME:
            if (it[*sel].ref < 0) return 0;
            menu_close();
            return MENU_ACT_CLOSE | MENU_ACT_REDRAW;
        case K_PAGE_MODS:
            g_page = PAGE_MODS;
            g_status[0] = '\0';
            return MENU_ACT_REDRAW;
        case K_PAGE_SETTINGS:
            g_page = PAGE_SETTINGS;
            g_status[0] = '\0';
            return MENU_ACT_REDRAW;
        case K_SAVE_NOW:
            menu_close();
            return MENU_ACT_SAVE_NOW | MENU_ACT_CLOSE | MENU_ACT_REDRAW;
        case K_PAGE_DEBUG:
            g_page = PAGE_DEBUG;
            g_status[0] = '\0';
            return MENU_ACT_REDRAW;
        case K_DBG_WARP:
        case K_DBG_PART:
        case K_DBG_FADE:
        case K_DBG_ENC:
        case K_DBG_ENDING: {
            static const int k_act[] = {ACT_WARP, ACT_PART, ACT_FADE, ACT_ENCOUNTERS_OFF, ACT_ENDING};
            int act = k_act[it[*sel].kind - K_DBG_WARP];
            if (act == ACT_ENCOUNTERS_OFF && actions_encounters_off()) act = ACT_ENCOUNTERS_ON;
            actions_request(act, act == ACT_WARP ? actions_warp_map(g_warp) : 0);
            menu_close();
            return MENU_ACT_CLOSE | MENU_ACT_REDRAW;
        }
        case K_QUIT:
            menu_close();
            return MENU_ACT_QUIT | MENU_ACT_CLOSE;
        case K_MOD:
            if (!mod_menu_option_count(it[*sel].ref)) return change(&it[*sel], 1, 0);
            g_mod = it[*sel].ref;
            g_sel[PAGE_MOD] = g_top[PAGE_MOD] = 0;
            g_page = PAGE_MOD;
            g_status[0] = '\0';
            return MENU_ACT_REDRAW;
        default:
            return change(&it[*sel], 1, 0);
        }
    default:
        return 0;
    }
}

/* ---- the drawing --------------------------------------------------------- */

typedef struct {
    uint8_t* px;
    int w, h, stride, s;
    int alpha; /* M8b: drawing an overlay for the GPU, alpha its own, over nothing */
} Canvas;

static void fill(const Canvas* c, int x, int y, int w, int h, uint32_t rgb)
{
    int i, j;
    for (j = y < 0 ? 0 : y; j < y + h && j < c->h; j++) {
        uint8_t* row = c->px + (size_t)j * (size_t)c->stride;
        for (i = x < 0 ? 0 : x; i < x + w && i < c->w; i++) {
            row[i * 4 + 0] = (uint8_t)(rgb & 0xFF);
            row[i * 4 + 1] = (uint8_t)(rgb >> 8 & 0xFF);
            row[i * 4 + 2] = (uint8_t)(rgb >> 16 & 0xFF);
            if (c->alpha) row[i * 4 + 3] = 0xFF;
        }
    }
}

/* The panel's ground: the picture under it dimmed to a quarter. As an
 * overlay, the colour and alpha that blend to the same -- 11 at 191/255 over
 * a picture value p gives about p/4 + 8. */
static void dim(const Canvas* c, int x, int y, int w, int h)
{
    int i, j, k;
    for (j = y < 0 ? 0 : y; j < y + h && j < c->h; j++) {
        uint8_t* row = c->px + (size_t)j * (size_t)c->stride;
        for (i = x < 0 ? 0 : x; i < x + w && i < c->w; i++) {
            if (c->alpha) {
                row[i * 4 + 0] = row[i * 4 + 1] = row[i * 4 + 2] = 11;
                row[i * 4 + 3] = 191;
                continue;
            }
            for (k = 0; k < 3; k++) row[i * 4 + k] = (uint8_t)(row[i * 4 + k] / 4 + 8);
        }
    }
}

static void text(const Canvas* c, int x, int y, const char* s, uint32_t rgb)
{
    for (; *s; s++, x += CELL_W * c->s) {
        int ch = (unsigned char)*s, r, col, drop;
        if (ch < 32 || ch > 126) ch = '?';
        drop = ch == 'g' || ch == 'j' || ch == 'p' || ch == 'q' || ch == 'y'; /* their tails below the line, in the cell's spare row */
        for (r = 0; r < 7; r++)
            for (col = 0; col < 5; col++)
                if (k_font[ch - 32][r][col] == '#')
                    fill(c, x + col * c->s, y + (r + 1 + drop) * c->s, c->s, c->s, rgb);
    }
}

#define INK 0xE8E8E8u
#define TITLE 0xF0C860u
#define BAR 0x284880u
#define PICKED 0xFFF0A0u
#define FAINT 0x9AA0AAu

static void draw(uint8_t* bgra, int w, int h, int stride, int alpha);

/* H17d: the notice and until when it shows. */
static char g_notice[96];
static uint64_t g_notice_until;

void menu_notice(const char* text, unsigned ms)
{
    snprintf(g_notice, sizeof g_notice, "%s", text && ms ? text : "");
    g_notice_until = text && ms ? plat_mono_ns() + (uint64_t)ms * 1000000u : 0;
}

int menu_notice_showing(void)
{
    if (g_notice[0] && plat_mono_ns() >= g_notice_until) g_notice[0] = '\0';
    return g_notice[0] != '\0';
}

static void notice_draw(uint8_t* bgra, int w, int h, int stride, int alpha);

void menu_draw(uint8_t* bgra, int w, int h, int stride)
{
    draw(bgra, w, h, stride, 0);
    notice_draw(bgra, w, h, stride, 0);
}

/* M8b: the same as an overlay the GPU blends over the picture: the buffer
 * cleared to nothing, the panel's ground translucent, the rest opaque. 1 when
 * the menu is open and was drawn, 0 (and nothing written) when it is not. */
int menu_draw_overlay(uint8_t* bgra, int w, int h, int stride)
{
    int j, open = menu_is_open(), told = menu_notice_showing();
    if ((!open && !told) || !bgra || w <= 0 || h <= 0) return 0;
    for (j = 0; j < h; j++) memset(bgra + (size_t)j * (size_t)stride, 0, (size_t)w * 4);
    draw(bgra, w, h, stride, 1);
    notice_draw(bgra, w, h, stride, 1);
    return 1;
}

/* H17d: the notice on a dimmed band in the lower-left corner, at the scale
 * the menu's panel would have. */
static void notice_draw(uint8_t* bgra, int w, int h, int stride, int alpha)
{
    Canvas c;
    int n, bw, bh, x0, y0;
    if (!menu_notice_showing() || !bgra || w <= 0 || h <= 0) return;
    c.px = bgra;
    c.w = w;
    c.h = h;
    c.stride = stride;
    c.alpha = alpha;
    c.s = w / ((COLS + 2) * CELL_W);
    if (h / ((ROWS_SHOWN + 7) * CELL_H) < c.s) c.s = h / ((ROWS_SHOWN + 7) * CELL_H);
    if (c.s < 1) c.s = 1;
    n = (int)strlen(g_notice);
    bw = (n + 2) * CELL_W * c.s;
    bh = 2 * CELL_H * c.s;
    x0 = CELL_W * c.s;
    y0 = h - bh - CELL_H * c.s;
    if (bw > w - x0) bw = w - x0;
    if (y0 < 0) y0 = 0;
    dim(&c, x0, y0, bw, bh);
    text(&c, x0 + CELL_W * c.s, y0 + CELL_H * c.s / 2, g_notice, INK);
}

static void draw(uint8_t* bgra, int w, int h, int stride, int alpha)
{
    static const char* const k_title[] = {"Skies of Arcadia", "Mods", "", "Settings", "Debug"};
    Item it[64];
    Canvas c;
    int n, rows, pw, ph, x0, y0, i, line = 0, *top, *sel;
    char head[64], row[COLS + 1];
    if (!menu_is_open() || !bgra || w <= 0 || h <= 0) return;
    c.px = bgra;
    c.w = w;
    c.h = h;
    c.stride = stride;
    c.alpha = alpha;
    n = items(it, 64);
    rows = n < ROWS_SHOWN ? n : ROWS_SHOWN;
    c.s = w / ((COLS + 2) * CELL_W);
    if (h / ((ROWS_SHOWN + 7) * CELL_H) < c.s) c.s = h / ((ROWS_SHOWN + 7) * CELL_H);
    if (c.s < 1) c.s = 1;
    pw = (COLS + 2) * CELL_W * c.s;
    ph = (rows + 7) * CELL_H * c.s;
    x0 = (w - pw) / 2;
    y0 = (h - ph) / 2;
    dim(&c, x0, y0, pw, ph);
    fill(&c, x0, y0, pw, c.s, FAINT);
    fill(&c, x0, y0 + ph - c.s, pw, c.s, FAINT);
    fill(&c, x0, y0, c.s, ph, FAINT);
    fill(&c, x0 + pw - c.s, y0, c.s, ph, FAINT);
    x0 += CELL_W * c.s;
    y0 += CELL_H * c.s / 2;
    if (g_page == PAGE_MOD) {
        const char* key = "";
        snprintf(head, sizeof head, "Mods > %s", mod_menu_name(g_mod, &key));
    } else {
        snprintf(head, sizeof head, "%s", k_title[g_page]);
    }
    text(&c, x0, y0 + line++ * CELL_H * c.s, head, TITLE);
    line++;
    sel = &g_sel[g_page];
    top = &g_top[g_page];
    if (*sel < *top) *top = *sel;
    if (*sel >= *top + rows) *top = *sel - rows + 1;
    for (i = *top; i < *top + rows && i < n; i++, line++) {
        int y = y0 + line * CELL_H * c.s, picked = i == *sel;
        int gap = COLS - (int)strlen(it[i].label) - (int)strlen(it[i].value) - 2;
        snprintf(row, sizeof row, "%s%*s%s", it[i].label, gap > 1 ? gap : 1, "", it[i].value);
        if (picked) fill(&c, x0 - CELL_W * c.s / 2, y, (COLS + 1) * CELL_W * c.s, CELL_H * c.s, BAR);
        text(&c, x0 + CELL_W * c.s, y, row, picked ? PICKED : INK);
    }
    line++;
    text(&c, x0, y0 + line++ * CELL_H * c.s, n > rows ? "Up/Down: choose (more below)" : "Up/Down: choose", FAINT);
    text(&c, x0, y0 + line++ * CELL_H * c.s, "Left/Right: change   A: enter   B: back", FAINT);
    if (g_status[0]) text(&c, x0, y0 + line * CELL_H * c.s, g_status, TITLE);
}
