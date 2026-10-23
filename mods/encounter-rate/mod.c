/*
 * encounter-rate (docs/PLAN-GAMEPLAY-MODS.md P1; the comfort-pack spec 3.4):
 * how often random battles come in the field, and hold B for none.
 *
 * The game keeps an encounter multiplier, the signed byte at 0x8030B7AD:
 * -1 (0xFF) is the normal rate, and anything else multiplies the odds by
 * byte/50 (read at 0x800C2000). It sets that byte itself from the party's
 * accessories -- the effect-84 value of the last of characters 0-5 whose
 * accessory has one; on this disc accessory 210 (100: twice the battles) and
 * 211 (5: a tenth) -- when a map loads or equipment changes. This mod works
 * out the same base every frame, never reading the byte back (it holds the
 * mod's own last write), and writes from it:
 *
 *     SOA_ENCOUNTERS=half     base / 2, truncated: 50 -> 25, 100 -> 50, 5 -> 2
 *     SOA_ENCOUNTERS=double   min(base * 2, 127): 50 -> 100, 100 -> 127
 *     SOA_ENCOUNTERS=off      0
 *     SOA_ENCOUNTERS=normal   nothing -- and unset is normal
 *
 * where base is 50 when no accessory has the effect. While B is held in the
 * field it writes 0, no random battles, unless SOA_ENCOUNTERS_HOLD_B=0; at
 * normal, the first frame after B is let go puts the game's own value back,
 * once, so a tap of B does not leave battles off until the next map. Only in
 * the field (scene 6), from the frame end. The byte lies below the saved
 * party block, so nothing written here reaches a save.
 *
 * soa.ini's `encounters` and `encounters_hold_b` set the same two switches.
 * The mod.ini declares them as options too (M16b), `rate` and `hold_b`, set
 * as `encounter-rate.rate = half` in soa.ini or by SOA_MOD_OPT; the
 * switches above, where set, win over them, and say so.
 *
 * SOA_ENCOUNTERS_TEST=1 is the test mode P1b's check reads (the comfort-pack
 * spec 3.4; tools/encounter_check.py): trials of the kinds 0.5, 1, 2, 0 and
 * hold in turn, each started in the running field by writing 480 to the step
 * counter, and ended by a battle, by 600 moving frames (the counter's own
 * increments) or, as stuck, by 3000 frames with fewer. A hold trial is k = 1
 * with B held. Each ends in a line, `trial n kind zone0 rate0 zone1 rate1
 * moved battle|clear|stuck`, the zone and its table rate read at both ends.
 * In a battle it flees and presses on: the escape override at 0x8030B7AB
 * held at 100, A every 30 frames outside the party's input and on the
 * results screen after, and,
 * while the party's commands are taken (0x8034733C = 1), up three times and A
 * at the menu's pace -- the wheel opens on Attack and Run is three slots up
 * (encounters.md).
 * Built beside its mod.ini by `python tools/recompile.py --link`, or:
 *
 *     cl /LD /O2 /I runtime mods\encounter-rate\mod.c /Fe:mods\encounter-rate\mod.dll
 */
#include "soa_mod.h"
#include "soa_gamedata.h" /* T9: the game's data by name, each proved against its code */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h> /* env() */
#endif

#define MULTIPLIER SOA_ENCOUNTER_MULTIPLIER /* s8: -1 the normal rate, else the odds x byte/50 */
#define PARTY SOA_PARTY_CHARACTER      /* character c's block at PARTY + 92c */
#define ACCESSORY 20u          /* the u16 accessory id, in a block */
#define ITEMS SOA_TABLES_ACCESSORIES      /* accessory records, 40 bytes each, id 160 first */
#define EFFECTS 24u            /* four {u8 code, u8, s16 value}, in a record */
#define ENCOUNTER_EFFECT 84
#define SCENE_FIELD 6u
#define SCENE_BATTLE 7u
#define FIELD_RUNNING 8u
#define STEP_COUNTER SOA_ENCOUNTER_STEPS /* frames moved since the last reset; the roll reads it */
#define ZONE SOA_ENCOUNTER_ZONE         /* u16: the ground's zone, 1-8 counted */
#define WORLD_MAP 99u
#define WORLD_ZONE SOA_ENCOUNTER_ZONE_SKY   /* the world map's zone: the low half of this word */
#define TABLE SOA_ENCOUNTER_TABLE        /* the map's .ect: a zone's rate is the u16 at +2 + (zone - 1) * 132 */
#define ESCAPE SOA_BATTLE_OVERRIDE_ESCAPE_PARTY       /* the party's escape override */
#define PHASE SOA_BATTLE_PHASE        /* 1 while a battle takes the party's commands */
#define TRIAL_START 480u
#define TRIAL_MOVES 600u
#define TRIAL_FRAMES 3000u
#define WHEEL_LEAD 60u  /* frames of nothing while the wheel turns into view */
#define WHEEL_BEAT 70u  /* a press and the 60 frames of nothing after it */

enum { P_NORMAL, P_HALF, P_DOUBLE, P_OFF }; /* not NORMAL/DOUBLE: windows.h has a DOUBLE */
static const char* const k_preset[] = {"normal", "half", "double", "off"};

static const SoaModApi* g_api;
static int g_preset = P_NORMAL, g_hold_b = 1;
static int g_b;     /* B held at the last controller read in the field */
static int g_dirty; /* the byte holds a value of this mod's, not the game's */
static int g_shown_base = -1000, g_shown_who = -2;

/* The test mode's trial: whether one runs, its kind, and what it has seen. */
enum { K_HALF, K_ONE, K_TWO, K_ZERO, K_HOLD, K_KINDS };
static const char* const k_kind[K_KINDS] = {"0.5", "1", "2", "0", "hold"};
static const int k_kind_preset[K_KINDS] = {P_HALF, P_NORMAL, P_DOUBLE, P_OFF, P_NORMAL};
static int g_test, g_running, g_kind, g_seen_field;
static unsigned g_trials;
static uint32_t g_wheel; /* 1 + the frame the party's input began, or 0 */
static uint32_t g_last_count, g_moved, g_start, g_zone0, g_rate0;

/* The game's own reckoning, from the party: the base (50 when no accessory
 * has the effect), the byte the game would hold (0xFF then), and whose
 * accessory decided it -- the last character with one, as the game has it. */
static int base_now(int* game, int* who, unsigned* item)
{
    int base = 50;
    unsigned c, e;
    *game = 0xFF;
    *who = -1;
    *item = 0;
    for (c = 0; c < 6; c++) {
        uint16_t id;
        if (!g_api->read16(PARTY + 92u * c + ACCESSORY, &id) || id < 160 || id > 239) continue;
        for (e = 0; e < 4; e++) {
            uint32_t at = ITEMS + (id - 160u) * 40u + EFFECTS + 4u * e;
            uint8_t code;
            uint16_t v;
            if (!g_api->read8(at, &code) || code != ENCOUNTER_EFFECT || !g_api->read16(at + 2, &v)) continue;
            base = (int16_t)v;
            *game = (uint8_t)v;
            *who = (int)c;
            *item = id;
        }
    }
    return base;
}

/* The zone underfoot and its rate in the map's table; rate 0 outside 1-8.
 * The world map, 99, reads its zone from the low half of the word at
 * 0x80346CD4 (0x800C1F70), and fn_800C1A50 points the table at its region's
 * sub-table (research/encounters.md). */
static void zone_rate(uint32_t* zone, uint32_t* rate)
{
    uint16_t z = 0, r = 0;
    uint32_t table = 0, world = 0;
    if ((g_api->map() >> 8) == WORLD_MAP) {
        if (g_api->read32(WORLD_ZONE, &world)) z = (uint16_t)world;
    } else {
        g_api->read16(ZONE, &z);
    }
    if (z >= 1 && z <= 8 && g_api->read32(TABLE, &table) && table) g_api->read16(table + 2u + (z - 1u) * 132u, &r);
    *zone = z;
    *rate = r;
}

static void trial_end(const char* how)
{
    char line[128];
    uint32_t zone1, rate1;
    zone_rate(&zone1, &rate1);
    snprintf(line, sizeof line, "trial %u %s %u %u %u %u %u %s", g_trials, k_kind[g_kind], g_zone0, g_rate0, zone1,
             rate1, g_moved, how);
    g_api->log(line);
    g_trials++;
    g_running = 0;
}

/* The title's attract demo, which runs as a field: maps 299 and 297
 * (tools/soak.py's ATTRACT); 299 also loads at boot, before any Continue. */
static int attract(void)
{
    uint32_t number = g_api->map() >> 8;
    return number == 299u || number == 297u;
}

/* Each frame end in the test mode: a trial started in the running field,
 * its moving frames counted, and ended; in a battle, the escape held. */
static void trial_frame(void)
{
    uint32_t scene = g_api->scene(), now = g_api->frame(), count = 0;
    if (scene == SCENE_BATTLE) {
        g_api->write8(ESCAPE, 100);
        if (g_running) trial_end("battle");
        return;
    }
    if (scene != SCENE_FIELD) return;
    if (attract()) return; /* the title's own demo: no trial, and the title's presses left alone */
    g_seen_field = 1;
    if (!g_running) {
        if (g_api->field_state() != FIELD_RUNNING) return;
        g_kind = (int)(g_trials % K_KINDS);
        g_preset = k_kind_preset[g_kind];
        if (!g_api->write32(STEP_COUNTER, TRIAL_START)) return;
        g_last_count = TRIAL_START;
        g_moved = 0;
        g_start = now;
        zone_rate(&g_zone0, &g_rate0);
        g_running = 1;
        /* B counts as held from this frame end, not from the next controller
         * read: otherwise the next frame's roll runs at normal odds before
         * the hold's 0 lands (run p1b long-e's trial 69, a battle at 0
         * moving frames) */
        if (g_kind == K_HOLD) g_b = 1;
        return;
    }
    /* the counter only goes up, but a map load resets it: count the rises */
    if (g_api->read32(STEP_COUNTER, &count)) {
        if (count > g_last_count) g_moved += count - g_last_count;
        g_last_count = count;
    }
    if (g_moved >= TRIAL_MOVES) trial_end("clear");
    else if (now - g_start >= TRIAL_FRAMES) trial_end("stuck");
}

static void put(int v)
{
    if (g_api->write8(MULTIPLIER, (uint8_t)v)) g_dirty = 1;
}

static void on_frame_end(void* user)
{
    int game, who, base;
    unsigned item;
    (void)user;
    if (g_test) trial_frame();
    if (g_api->scene() != SCENE_FIELD) return;
    base = base_now(&game, &who, &item);
    if (base != g_shown_base || who != g_shown_who) {
        char line[96];
        if (who < 0) snprintf(line, sizeof line, "base %d (none)", base);
        else snprintf(line, sizeof line, "base %d (character %d's accessory %u)", base, who, item);
        g_api->log(line);
        g_shown_base = base;
        g_shown_who = who;
    }
    if (g_hold_b && g_b) {
        put(0);
        return;
    }
    if (g_preset == P_NORMAL) {
        /* Only ever the restore: the game's value, once, after this mod's own. */
        if (g_dirty && g_api->write8(MULTIPLIER, (uint8_t)game)) g_dirty = 0;
        return;
    }
    if (base < 0) return; /* an effect this disc does not have: leave the game be */
    put(g_preset == P_HALF ? base / 2 : g_preset == P_DOUBLE ? (base * 2 > 127 ? 127 : base * 2) : 0);
}

static void on_pad(void* user, uint32_t frame, SoaPad* pad)
{
    (void)user;
    (void)frame;
    if (g_test && g_seen_field && !attract() &&
        (g_api->scene() != SCENE_FIELD || g_api->field_state() != FIELD_RUNNING)) {
        /* Run: from Attack, where the wheel opens, up three times and A, at
         * the lab's menu pace -- nothing for 60 frames while the wheel turns
         * into view, then each press held (4 frames for a slot, under the
         * game's 6-frame repeat; 10 for A) and 60 frames of nothing -- and
         * again from the top while the party's commands are still taken.
         * The sticks are held centred: the walk's would turn the wheel. */
        uint32_t phase = 0;
        if (g_api->scene() == SCENE_BATTLE && g_api->read32(PHASE, &phase) && phase == 1) {
            uint32_t into, beat, within;
            if (!g_wheel) g_wheel = frame + 1;
            into = frame - (g_wheel - 1);
            pad->buttons = 0;
            pad->stick[0] = pad->stick[1] = pad->cstick[0] = pad->cstick[1] = 128;
            if (into >= WHEEL_LEAD) {
                beat = (into - WHEEL_LEAD) / WHEEL_BEAT % 4u;
                within = (into - WHEEL_LEAD) % WHEEL_BEAT;
                if (beat < 3 && within < 4) pad->buttons = SOA_PAD_UP;
                if (beat == 3 && within < 10) pad->buttons = SOA_PAD_A;
            }
        } else {
            /* the rest of a battle, and the results screen after it, which
             * waits for A with the scene back at the field's and the field
             * not yet running: A every 30 frames, and nothing of the walk's
             * (its START would pause). Only once the field has been seen,
             * and never on the title's demo maps, so the title's own presses
             * are left alone. */
            g_wheel = 0;
            pad->buttons = frame % 30u < 4u ? SOA_PAD_A : 0;
            pad->stick[0] = pad->stick[1] = pad->cstick[0] = pad->cstick[1] = 128;
        }
        return;
    }
    if (g_test && g_running && g_kind == K_HOLD && g_api->scene() == SCENE_FIELD) pad->buttons |= SOA_PAD_B;
    g_b = (pad->buttons & SOA_PAD_B) && g_api->scene() == SCENE_FIELD;
}

/* An option the mod.ini declares, or NULL on a port without option calls
 * (M16b): the value is already checked against its domain at load. */
static const char* option(const SoaModApi* api, const char* name)
{
    return api->size >= SOA_MOD_HAS(option) ? api->option(name) : NULL;
}

/* An environment variable as the mod sees it: 1 with its value, 0 unset. */
static int env(const char* name, char* out, unsigned cap)
{
#ifdef _WIN32
    DWORD n = GetEnvironmentVariableA(name, out, cap); /* the process's environment */
    if (!n) return 0;
    if (n >= cap) snprintf(out, cap, "%s", "(too long)"); /* no value this mod takes: refused with its line */
#else
    const char* v = getenv(name); /* libc's, which settings.c's setenv writes (portability L10) */
    if (!v) return 0;
    snprintf(out, cap, "%s", strlen(v) < cap ? v : "(too long)"); /* no value this mod takes: refused with its line */
#endif
    return 1;
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    char v[32], line[160];
    int i;
    /* pad_filter is the last member this mod calls. */
    if (version < 1 || api->size < SOA_MOD_HAS(pad_filter)) return 1;
    g_api = api;
    const char *rate = option(api, "rate"), *hold = option(api, "hold_b");
    if (rate)
        for (i = 0; i < 4; i++)
            if (!strcmp(rate, k_preset[i])) g_preset = i;
    if (hold) g_hold_b = strcmp(hold, "0") != 0;
    if (env("SOA_ENCOUNTERS", v, sizeof v) && v[0]) {
        if (rate && strcmp(rate, "normal") != 0) {
            snprintf(line, sizeof line, "SOA_ENCOUNTERS=%s is set, and wins over the option rate = %s", v, rate);
            api->log(line);
        }
        g_preset = P_NORMAL;
        for (i = 0; i < 4 && strcmp(v, k_preset[i]); i++) {}
        if (i < 4) g_preset = i;
        else {
            snprintf(line, sizeof line, "SOA_ENCOUNTERS=%s is not off, half, normal or double; the game's own rate", v);
            api->log(line);
        }
    }
    if (env("SOA_ENCOUNTERS_HOLD_B", v, sizeof v) && v[0]) {
        if (hold && strcmp(hold, "1") != 0) {
            snprintf(line, sizeof line, "SOA_ENCOUNTERS_HOLD_B=%s is set, and wins over the option hold_b = %s", v, hold);
            api->log(line);
        }
        g_hold_b = 1;
        if (!strcmp(v, "0")) g_hold_b = 0;
        else if (strcmp(v, "1")) {
            snprintf(line, sizeof line, "SOA_ENCOUNTERS_HOLD_B=%s is not 0 or 1; holding B keeps battles away", v);
            api->log(line);
        }
    }
    if (env("SOA_ENCOUNTERS_TEST", v, sizeof v) && !strcmp(v, "1")) {
        g_test = 1;
        g_hold_b = 1; /* the hold trials need it */
        api->log("test mode: trials of 0.5, 1, 2, 0 and hold in turn, each from a step counter of 480 to a battle, "
                 "600 moving frames, or stuck at 3000 frames");
    }
    api->on_frame_end(on_frame_end, NULL);
    if (g_hold_b) api->pad_filter(on_pad, NULL); /* without it, the read path is left as it was */
    snprintf(line, sizeof line, "random battles %s in the field; holding B keeps them away %s", k_preset[g_preset],
             g_hold_b ? "on" : "off");
    api->log(line);
    return 0;
}
