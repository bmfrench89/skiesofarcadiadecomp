/*
 * difficulty (docs/PLAN-GAMEPLAY-MODS.md R3; docs/specs/battle-mods.md 4):
 * Easy, Hard and Nightmare. Each enemy is scaled as the game makes it, at
 * on_enemy_spawn -- a battle's setup and Call Allies both -- and the rewards
 * at on_rewards. Percent, by preset (the spec's table, a first proposal):
 *
 *               hp  attack  defense  magdef  speed  rewards
 *     easy      50      75      100     100    100      100
 *     normal   100     100      100     100    100      100
 *     hard     150     125      100     100    100      125
 *     nightmare 200    150      125     125    125      150
 *
 * Each column is an option of its own as well, `preset` by default; a number
 * there wins over the preset. In the actor (battle-system.md 1.2): hp scales
 * HP and max HP (+20, +24); attack scales Attack (+148) and Will (+130, an
 * enemy's magic); defense Defense (+150); magdef MagDef (+152); speed Quick
 * (+136). Each s16 has a base copy, of +128..+137 at +232 and of
 * +148..+157 at +242, scaled the same way, so a round's restore or a buff
 * starts from the scaled value. Rounded down; a positive value stays at
 * least 1, an s16 at most 32767, and 0 or less is left as it is.
 *
 * The record, which every enemy of the kind shares and which stays loaded
 * for the next battle on the map, is written in one place only and only for
 * the battle: its max HP (+36), scaled once, because the boss music
 * (fn_8007D42C) weighs the bosses' HP against their records' max HP -- left
 * alone, Easy would play a boss's below-half music from its first frame.
 * Another enemy of the kind is then made with the scaled HP already, and is
 * not scaled again. When the scene leaves the battle each is put back, where
 * it still holds the scaled value; a change there would compound.
 *
 * Ship battles make their enemies and pay their rewards in the field's ship
 * driver, past both events, and are left as the game has them.
 *
 * At normal with no number set nothing is registered.
 *
 * Built beside its mod.ini by `python tools/recompile.py --link`, or:
 *
 *     cl /LD /O2 /I runtime mods\difficulty\mod.c /Fe:mods\difficulty\mod.dll
 */
#include "soa_mod.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define HP 20u /* s32s, in an actor */
#define HP_MAX 24u
#define WILL 130u /* s16s */
#define QUICK 136u
#define ATTACK 148u
#define DEFENSE 150u
#define MAGDEF 152u
#define BASE_OF_128 (232u - 128u) /* where +128..+137's base copies sit, less 128 */
#define BASE_OF_148 (242u - 148u)
#define RECORD_HP_MAX 36u /* s32, in an enemy record */
#define RECORDS 16        /* records a battle's spawns can name: 8 slots, and Call Allies */
#define SCENE_BATTLE 7u

enum { K_HP, K_ATTACK, K_DEFENSE, K_MAGDEF, K_SPEED, K_REWARDS, KNOBS };
static const char* const k_knob[KNOBS] = {"hp", "attack", "defense", "magdef", "speed", "rewards"};
static const char* const k_preset[4] = {"easy", "normal", "hard", "nightmare"};
static const int k_preset_pct[4][KNOBS] = {
    {50, 75, 100, 100, 100, 100},
    {100, 100, 100, 100, 100, 100},
    {150, 125, 100, 100, 100, 125},
    {200, 150, 125, 125, 125, 150},
};
static const char* const k_mult[] = {"0", "0.25", "0.5", "0.75", "1", "1.25", "1.5", "2", "2.5", "3", "4"};
static const int k_mult_pct[] = {0, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400};

static const SoaModApi* g_api;
static int g_pct[KNOBS];

/* The records whose max HP this battle scaled: where, what it held, what it
 * was given. */
static struct {
    uint32_t at, was, now;
} g_rec[RECORDS];
static int g_nrec;

static const char* option(const char* name)
{
    return g_api->size >= SOA_MOD_HAS(option) ? g_api->option(name) : NULL;
}

/* An option's multiplier in percent, or -1 for `preset` (and one not set). */
static int pct_of(const char* name)
{
    const char* v = option(name);
    unsigned i;
    for (i = 0; v && i < sizeof k_mult / sizeof k_mult[0]; i++)
        if (!strcmp(v, k_mult[i])) return k_mult_pct[i];
    return -1;
}

static int64_t scaled(int64_t v, int pct, int64_t most)
{
    int64_t x;
    if (v <= 0) return v;
    x = v * pct / 100;
    return x < 1 ? 1 : x > most ? most : x;
}

static void scale32(uint32_t at, int pct)
{
    uint32_t v;
    if (g_api->read32(at, &v)) g_api->write32(at, (uint32_t)(int32_t)scaled((int32_t)v, pct, INT32_MAX));
}

/* An s16 stat and its base copy. */
static void scale16(uint32_t at, uint32_t base, int pct)
{
    uint16_t v;
    if (g_api->read16(at, &v)) g_api->write16(at, (uint16_t)(int16_t)scaled((int16_t)v, pct, 32767));
    if (g_api->read16(base, &v)) g_api->write16(base, (uint16_t)(int16_t)scaled((int16_t)v, pct, 32767));
}

static int16_t s16_at(uint32_t at)
{
    uint16_t v = 0;
    g_api->read16(at, &v);
    return (int16_t)v;
}

static int32_t s32_at(uint32_t at)
{
    uint32_t v = 0;
    g_api->read32(at, &v);
    return (int32_t)v;
}

/* The actor's HP for this spawn. The first enemy of a kind this battle scales
 * its record's max HP too, and was made from the record as the game has it;
 * a later one was made from the record already scaled. 1 when this actor's
 * HP is to be scaled. */
static int record_hp(uint32_t record)
{
    char line[128];
    uint32_t was;
    int i;
    for (i = 0; i < g_nrec; i++)
        if (g_rec[i].at == record) return 0;
    if (g_nrec == RECORDS || !g_api->read32(record + RECORD_HP_MAX, &was)) {
        snprintf(line, sizeof line, "record %08X: no room to put it back, so left as it is", record);
        g_api->log(line);
        return 1;
    }
    g_rec[g_nrec].at = record;
    g_rec[g_nrec].was = was;
    g_rec[g_nrec].now = (uint32_t)(int32_t)scaled((int32_t)was, g_pct[K_HP], INT32_MAX);
    g_api->write32(record + RECORD_HP_MAX, g_rec[g_nrec].now);
    g_nrec++;
    return 1;
}

/* One field of the spawn's line, when it moved. */
static size_t moved(char* line, size_t n, size_t cap, const char* name, int32_t was, int32_t now)
{
    if (was == now || n >= cap) return n;
    return n + (size_t)snprintf(line + n, cap - n, ", %s %d -> %d", name, was, now);
}

static void spawn(void* user, uint32_t actor, uint32_t record)
{
    static const struct {
        const char* name;
        uint32_t at;
    } k_field[] = {{"Attack", ATTACK}, {"Will", WILL}, {"Defense", DEFENSE}, {"MagDef", MAGDEF}, {"Quick", QUICK}};
    char line[256];
    int32_t hp0 = s32_at(actor + HP), was[5];
    size_t n, i;
    (void)user;
    for (i = 0; i < 5; i++) was[i] = s16_at(actor + k_field[i].at);
    if (g_pct[K_HP] != 100 && record_hp(record)) {
        scale32(actor + HP, g_pct[K_HP]);
        scale32(actor + HP_MAX, g_pct[K_HP]);
    }
    if (g_pct[K_ATTACK] != 100) {
        scale16(actor + ATTACK, actor + ATTACK + BASE_OF_148, g_pct[K_ATTACK]);
        scale16(actor + WILL, actor + WILL + BASE_OF_128, g_pct[K_ATTACK]);
    }
    if (g_pct[K_DEFENSE] != 100) scale16(actor + DEFENSE, actor + DEFENSE + BASE_OF_148, g_pct[K_DEFENSE]);
    if (g_pct[K_MAGDEF] != 100) scale16(actor + MAGDEF, actor + MAGDEF + BASE_OF_148, g_pct[K_MAGDEF]);
    if (g_pct[K_SPEED] != 100) scale16(actor + QUICK, actor + QUICK + BASE_OF_128, g_pct[K_SPEED]);
    n = (size_t)snprintf(line, sizeof line, "spawn %08X: HP %d -> %d", actor, hp0, s32_at(actor + HP));
    for (i = 0; i < 5; i++) n = moved(line, n, sizeof line, k_field[i].name, was[i], s16_at(actor + k_field[i].at));
    g_api->log(line);
}

/* Leaving the battle: each record put back, where it still holds what this
 * mod gave it (the map may have freed and reused it since). */
static void scene_change(void* user, uint32_t from, uint32_t to)
{
    char line[128];
    int i;
    (void)user;
    (void)to;
    if (from != SCENE_BATTLE) return;
    for (i = 0; i < g_nrec; i++) {
        uint32_t now = 0;
        if (g_api->read32(g_rec[i].at + RECORD_HP_MAX, &now) && now == g_rec[i].now) {
            g_api->write32(g_rec[i].at + RECORD_HP_MAX, g_rec[i].was);
            snprintf(line, sizeof line, "record %08X: max HP %d put back to %d", g_rec[i].at, (int32_t)now,
                     (int32_t)g_rec[i].was);
        } else {
            snprintf(line, sizeof line, "record %08X: max HP %d, not this mod's %d any more; left as it is",
                     g_rec[i].at, (int32_t)now, (int32_t)g_rec[i].now);
        }
        g_api->log(line);
    }
    g_nrec = 0;
}

/* A reward times pct, rounded down, at most `most`: no floor of 1, so x0 pays
 * nothing and a reward of 1 at x0.5 pays 0. */
static int32_t paid(int32_t v, int pct, int64_t most)
{
    int64_t x = (int64_t)v * pct / 100;
    return (int32_t)(x > most ? most : x);
}

static void rewards(void* user, SoaRewards* r)
{
    (void)user;
    r->exp = paid(r->exp, g_pct[K_REWARDS], INT32_MAX);
    r->gold = paid(r->gold, g_pct[K_REWARDS], INT32_MAX);
    r->magic_exp = paid(r->magic_exp, g_pct[K_REWARDS], 127);
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    char line[192];
    const char* preset;
    int p = 1, k, n = 0, enemies = 0;
    g_api = api;
    /* on_enemy_spawn and on_rewards are R1's; on_rewards is the later member. */
    if (version < 1 || api->size < SOA_MOD_HAS(on_rewards)) {
        api->log("this port has no battle events (R1); nothing scaled");
        return 1;
    }
    preset = option("preset");
    for (k = 0; preset && k < 4; k++)
        if (!strcmp(preset, k_preset[k])) p = k;
    for (k = 0; k < KNOBS; k++) {
        int own = pct_of(k_knob[k]);
        g_pct[k] = own >= 0 ? own : k_preset_pct[p][k];
        if (k != K_REWARDS && g_pct[k] != 100) enemies = 1;
    }
    n = snprintf(line, sizeof line, "%s:", k_preset[p]);
    for (k = 0; k < KNOBS; k++)
        n += snprintf(line + n, sizeof line - (size_t)n, " %s x%d.%02d", k_knob[k], g_pct[k] / 100, g_pct[k] % 100);
    if (enemies) api->on_enemy_spawn(spawn, NULL);
    if (g_pct[K_HP] != 100) api->on_scene_change(scene_change, NULL);
    if (g_pct[K_REWARDS] != 100) api->on_rewards(rewards, NULL);
    if (!enemies && g_pct[K_REWARDS] == 100) snprintf(line + n, sizeof line - (size_t)n, "; nothing registered");
    api->log(line);
    return 0;
}
