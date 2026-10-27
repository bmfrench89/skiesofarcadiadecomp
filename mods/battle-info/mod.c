/*
 * battle-info (PLAN-GAMEPLAY-MODS R5, docs/specs/battle-info.md): what a
 * battle does not show, drawn over the picture (M20) -- each living enemy's
 * HP, the round's turn order once the game has set it, and a log of what
 * the round did to each side's HP. The party is P1 to P4 by slot (0-3) and
 * the enemies A to H by slot (4-11): no names, which would be the game's
 * own text (gameplay Q5). Each part is off until set, and at the defaults
 * the mod registers nothing.
 *
 * Everything is read at each frame end from the battle's memory, as R0's
 * log reads it (runtime/battle.c): an actor's HP at +20 of +24, its status
 * at +28, the order at battle.turn_order from battle.order_cursor, the slot
 * acting at battle.acting. The log is HP seen to change between two frame
 * ends -- a blow, a heal, poison at the round's end -- so it holds what
 * landed, never what was only worked out; a drop while a slot acts is put to
 * that slot. With the log on, each line drawn goes to the port's log too, and
 * with the HP on, each change in what a row shows, which tools/battle.py info
 * holds to R0's own lines.
 *
 * Built by tools/recompile.py --link (mod.dll, never committed).
 */
#include "soa_mod.h"
#include "soa_gamedata.h" /* T9: the game's data by name */

#include <stdio.h>
#include <string.h>

#define SCENE_BATTLE 7u
#define SLOTS 12
#define HP 20u     /* s32 */
#define HP_MAX 24u /* s32 */
#define STATUS 28u
#define KO 0x100u
#define ESCAPED 0x2000u
#define PASSED_OVER (0x6500u | 0x02000000u) /* phase 3 skips the slot (fn_800708C0) */
#define DECIDED 7u /* the phase from which the battle is won (7), lost (8) or fled (9) */
#define LINES 5    /* the log's lines on screen */
#define LINE_LEN 24
#define BOTTOM 470 /* where the bottom corners' panels end, in game units */

static const SoaModApi* g_api;
static int g_hp, g_order, g_log;
static int32_t g_size = 1;

/* What the last frame end saw of each slot: its actor, HP, max and status. */
static uint32_t g_actor[SLOTS], g_status[SLOTS];
static int32_t g_cur[SLOTS], g_max[SLOTS];
static int32_t g_shown[SLOTS][2]; /* the HP a row last showed, for the log line */
static uint32_t g_round, g_phase;
static int g_in_battle, g_fought;
static char g_lines[LINES][LINE_LEN];
static int g_line_n;
static char g_order_said[48]; /* the order line last logged, "" while none is shown */

static void label(int slot, char out[4])
{
    if (slot < 4) snprintf(out, 4, "P%d", slot + 1);
    else snprintf(out, 4, "%c", 'A' + (slot - 4));
}

static void say(const char* text)
{
    char line[96];
    if (g_line_n == LINES) {
        memmove(g_lines[0], g_lines[1], sizeof g_lines[0] * (LINES - 1));
        g_line_n--;
    }
    snprintf(g_lines[g_line_n++], LINE_LEN, "%s", text);
    snprintf(line, sizeof line, "frame %u: %s", g_api->frame(), text);
    g_api->log(line);
}

static void forget(void)
{
    memset(g_actor, 0, sizeof g_actor);
    memset(g_shown, 0, sizeof g_shown);
    g_line_n = 0;
    g_round = 0;
    g_order_said[0] = '\0';
    g_fought = 0;
}

/* One slot's change since the last frame end, into the log. */
static void changed(int slot, uint32_t a, int acting)
{
    uint32_t st = 0;
    int32_t hp = 0, max = 0;
    char who[4], by[4], text[LINE_LEN];
    g_api->read32(a + HP, (uint32_t*)&hp);
    g_api->read32(a + HP_MAX, (uint32_t*)&max);
    g_api->read32(a + STATUS, &st);
    label(slot, who);
    if (g_actor[slot] == a) {
        if (g_log && hp != g_cur[slot]) {
            if (hp < g_cur[slot] && acting >= 0 && acting < SLOTS && acting != slot) {
                label(acting, by);
                snprintf(text, sizeof text, "%s > %s -%d", by, who, (int)(g_cur[slot] - hp));
            } else {
                snprintf(text, sizeof text, "%s %+d", who, (int)(hp - g_cur[slot]));
            }
            say(text);
        }
        if (g_log && (st & KO) && !(g_status[slot] & KO)) {
            snprintf(text, sizeof text, "%s down", who);
            say(text);
        }
        if (g_log && (st & ESCAPED) && !(g_status[slot] & ESCAPED)) {
            snprintf(text, sizeof text, "%s fled", who);
            say(text);
        }
    }
    g_actor[slot] = a;
    g_cur[slot] = hp;
    g_max[slot] = max;
    g_status[slot] = st;
}

static void panel(int32_t x, int32_t y, int32_t w, int32_t h)
{
    g_api->draw_rect(x - 3, y - 3, w + 6, h + 6, 0x00000090u);
}

/* An enemy still in the fight, with a max to measure it by: a row. */
static int has_row(int slot)
{
    return g_actor[slot] && !(g_status[slot] & (KO | ESCAPED)) && g_max[slot] > 0;
}

/* Each living enemy: its letter, HP and a bar, a row each, in the bottom-left
 * corner -- the top is the game's while the party chooses (the Spirit gauge
 * across it, the target's name at its right). The bar grows less than the
 * text, so at size 3 the rows still leave the log its corner. */
static void draw_hp(void)
{
    const int32_t s = g_size, bar = 48 + 16 * s, row = 12 * s + 4, x = 10;
    int32_t y0, cells = 9; /* the numbers' width: "9999/9999", or a boss's more */
    int slot, rows = 0;
    for (slot = 4; slot < SLOTS; slot++)
        if (has_row(slot)) {
            char text[LINE_LEN];
            int n = snprintf(text, sizeof text, "%d/%d", (int)g_cur[slot], (int)g_max[slot]);
            if (n > cells) cells = n;
            rows++;
        }
    if (!rows) return;
    y0 = BOTTOM - (rows * row - 4);
    panel(x, y0, 6 * s * 3 + bar + 6 * s * (cells + 1), rows * row - 4);
    rows = 0;
    for (slot = 4; slot < SLOTS; slot++) {
        char who[4], text[LINE_LEN];
        int32_t y = y0 + rows * row, fill;
        if (!has_row(slot)) continue;
        label(slot, who);
        fill = (int32_t)((int64_t)bar * (g_cur[slot] < 0 ? 0 : g_cur[slot]) / g_max[slot]);
        if (fill > bar) fill = bar;
        g_api->draw_text(x, y, (uint32_t)s, 0xFFFFFFFFu, who);
        g_api->draw_rect(x + 6 * s * 2, y + 3 * s, bar, 4 * s, 0x502828FFu);
        g_api->draw_rect(x + 6 * s * 2, y + 3 * s, fill, 4 * s, 0x38D058FFu);
        snprintf(text, sizeof text, "%d/%d", (int)g_cur[slot], (int)g_max[slot]);
        g_api->draw_text(x + 6 * s * 3 + bar, y, (uint32_t)s, 0xFFFFFFFFu, text);
        if (g_shown[slot][0] != g_cur[slot] || g_shown[slot][1] != g_max[slot]) {
            char line[64];
            g_shown[slot][0] = g_cur[slot];
            g_shown[slot][1] = g_max[slot];
            snprintf(line, sizeof line, "frame %u: slot %d shows %d/%d", g_api->frame(), slot, (int)g_cur[slot],
                     (int)g_max[slot]);
            g_api->log(line);
        }
        rows++;
    }
}

/* The round's order from the slot acting on, top right: who acts now in
 * yellow, then the rest; only once the game has set it (phases 3 to 5),
 * when the game's own gauge has left the top. A slot phase 3 would pass over
 * is left out, by the game's own test (fn_800708C0: status 0x6500, or
 * 0x02000000); the slot at the cursor, fallen during its own turn, takes
 * its yellow with it. */
static void draw_order(uint32_t phase)
{
    const int32_t s = g_size, cw = 6 * s;
    int8_t order[SLOTS];
    uint8_t cursor = 0;
    char who[SLOTS][4];
    char text[48];
    int i, n = 0, len = 0, acting = 0, used = 0;
    int32_t x, y = 10;
    if (phase < 3 || phase > 5) {
        g_order_said[0] = '\0';
        return;
    }
    if (!g_api->read_bytes(SOA_BATTLE_TURN_ORDER, order, sizeof order) ||
        !g_api->read8(SOA_BATTLE_ORDER_CURSOR, &cursor))
        return;
    for (i = cursor; i < SLOTS && order[i] >= 0 && order[i] < SLOTS; i++) {
        int slot = order[i];
        if (!g_actor[slot] || (g_status[slot] & PASSED_OVER)) continue;
        if (i == cursor) acting = 1;
        label(slot, who[n]);
        len += (int)strlen(who[n]) + (n ? 1 : 0);
        n++;
    }
    if (!n) return;
    text[0] = '\0';
    for (i = 0; i < n; i++) used += snprintf(text + used, sizeof text - (size_t)used, "%s%s", i ? " " : "", who[i]);
    if (strcmp(text, g_order_said) != 0) { /* each order shown, once, for tools/battle.py info */
        char line[80];
        snprintf(g_order_said, sizeof g_order_said, "%s", text);
        snprintf(line, sizeof line, "frame %u: order %s", g_api->frame(), text);
        g_api->log(line);
    }
    x = 640 - 10 - len * cw;
    panel(x, y, len * cw, 9 * s);
    for (i = 0; i < n; i++) {
        g_api->draw_text(x, y, (uint32_t)s, i == 0 && acting ? 0xFFE060FFu : 0xFFFFFFFFu, who[i]);
        x += ((int32_t)strlen(who[i]) + 1) * cw;
    }
}

/* The log's last lines, newest at the bottom, in the bottom-right corner, as
 * wide as its longest line. */
static void draw_log(void)
{
    const int32_t s = g_size, cw = 6 * s, h = g_line_n * 9 * s, y0 = BOTTOM - h;
    int32_t w = 0, x;
    int i;
    if (!g_line_n) return;
    for (i = 0; i < g_line_n; i++)
        if ((int32_t)strlen(g_lines[i]) * cw > w) w = (int32_t)strlen(g_lines[i]) * cw;
    x = 640 - 10 - w;
    panel(x, y0, w, h);
    for (i = 0; i < g_line_n; i++) g_api->draw_text(x, y0 + i * 9 * s, (uint32_t)s, 0xFFFFFFFFu, g_lines[i]);
}

static void frame_end(void* user)
{
    uint32_t phase = 0, round = 0;
    uint8_t acting = 0xFF, r8 = 0;
    int slot;
    (void)user;
    if (g_api->scene() != SCENE_BATTLE) {
        if (g_in_battle) forget();
        g_in_battle = 0;
        return;
    }
    g_api->read32(SOA_BATTLE_PHASE, &phase);
    if (!g_in_battle || (phase == 0 && g_phase != 0)) forget(); /* a battle begun, or begun again (Try again) */
    g_phase = phase;
    g_in_battle = 1;
    g_api->read8(SOA_BATTLE_ACTING, &acting);
    if (g_api->read8(SOA_BATTLE_ROUND, &r8)) round = r8;
    if (g_log && round && round != g_round && g_round) {
        char text[LINE_LEN];
        snprintf(text, sizeof text, "round %u", round);
        say(text);
    }
    g_round = round;
    for (slot = 0; slot < SLOTS; slot++) {
        uint32_t a = 0;
        if (!g_api->read32(SOA_BATTLE_ACTORS + 4u * (uint32_t)slot, &a) || !a) {
            g_actor[slot] = 0;
            continue;
        }
        changed(slot, a, phase >= 3 && phase <= 5 ? (int)(int8_t)acting : -1);
    }
    /* Once the battle is decided the screen is the game's: its results, or
     * its Try again, whose options sit low and left (fn_80009874's text at
     * 160,360 and 160,384), where the rows are. Decided only after this
     * battle's own phases began: the last battle's 7 lasts until the game's
     * setup writes 0 (0x8000A2AC). */
    if (phase < DECIDED) g_fought = 1;
    else if (g_fought) return;
    if (g_hp) draw_hp();
    if (g_order) draw_order(phase);
    if (g_log) draw_log();
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    int64_t v = 0;
    char line[64];
    (void)version;
    if (api->size < SOA_MOD_HAS(draw_text)) {
        api->log("this port cannot draw (M20); nothing shown");
        return 1;
    }
    g_api = api;
    g_hp = api->option_int("hp", &v) && v;
    g_order = api->option_int("order", &v) && v;
    g_log = api->option_int("log", &v) && v;
    if (api->option_int("size", &v)) g_size = (int32_t)v;
    if (!g_hp && !g_order && !g_log) {
        api->log("every part off: nothing registered");
        return 0;
    }
    snprintf(line, sizeof line, "on:%s%s%s; text size %d", g_hp ? " hp" : "", g_order ? " order" : "",
             g_log ? " log" : "", (int)g_size);
    api->log(line);
    return api->on_frame_end(frame_end, NULL) ? 0 : 1;
}
