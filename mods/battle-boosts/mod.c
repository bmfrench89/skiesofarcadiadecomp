/*
 * battle-boosts (docs/PLAN-GAMEPLAY-MODS.md R4; docs/specs/battle-mods.md 3):
 * boosts and assists for every battle, each an option of its mod.ini, each
 * default the game's own. At the defaults nothing is registered, so a battle
 * runs as it would without the mod.
 *
 *   exp, gold, magic_exp   on_rewards: each times 0, 0.5, 1, 1.5, 2, 3 or 4,
 *                          rounded down; magic EXP held to 127 (gold is held
 *                          to 99,999,999 by the port and again by the game)
 *   full_spirit            at the first safe point of a battle with the phase
 *                          at 1 or 2 -- its first round's input, or after an
 *                          ambush its AI -- SP and SP after reservations
 *                          become the maximum, unless a living member's
 *                          equipment holds SP at 0 (status 0x10000)
 *   escape                 on_escape: a party Run (slots 0-3) always gets
 *                          away; an enemy's roll stays its own
 *   no_ko                  party members only. on_damage holds a blow to
 *                          HP - 1. on_effect cancels a death that landed
 *                          (effect 5, and 6's death branch), its KO result
 *                          made a miss; turns 6's damage branch and 68 into
 *                          effect 0 held the same way, a KO result made a
 *                          hit; and holds effect 0 and every effect whose
 *                          applier lands as effect 0's (the spec's section
 *                          2; not 66, which heals a party member).
 *                          on_round_end clears a member's bit of the
 *                          lethal-poison word, before the round's end acts on
 *                          it, and leaves them at 1 HP with the low-HP bit.
 *                          Each override is a log line. It stands down in a
 *                          battle whose defeat carries the story on (defeat
 *                          condition 2, ctx+4: event battle 26 at the home
 *                          base, where Run is not offered either), which
 *                          could otherwise end only in a victory.
 *
 * SOA_BOOSTS_TEST is the switch the real-battle check reads (the spec's 7.2):
 * `lowhp` holds every party character's HP at 1 between battles, so the next
 * battle starts with them there through the game's own setup, as one begun
 * hurt does; `poison` poisons the living members at its first round as well.
 * With no_ko off it is how the check shows a member fainting. (Written to the
 * actors in the first round instead, the members took the game's low-HP
 * stance without its animation, and the story's first battle stalled at its
 * next blow: FINDINGS "Battle mods".)
 *
 * Built beside its mod.ini by `python tools/recompile.py --link`, or:
 *
 *     cl /LD /O2 /I runtime mods\battle-boosts\mod.c /Fe:mods\battle-boosts\mod.dll
 */
#include "soa_mod.h"
#include "soa_gamedata.h" /* T9: the game's data by name, each proved against its code */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h> /* env() */
#endif

#define SCENE_BATTLE 7u
#define PARTY 4             /* slots 0-3 the party, 4-11 the enemies */
#define HP 20u              /* s32, in an actor (battle-system.md 1.2) */
#define STATUS 28u          /* u32 */
#define NOT_PRESENT 0x2100u /* unconscious or escaped */
#define POISONED 0x80u
#define LOW_HP 0x8000u      /* HP at or below a quarter of the maximum, which fn_80010474 keeps */
#define RESULT_HIT 8u       /* s8, in a slot's result record (battle.results, 16 bytes a slot) */
#define HIT_MISS 0
#define HIT_HIT 1
#define HIT_KO 5
#define NO_SPIRIT 0x10000u  /* equipment that holds SP at 0 */
#define CTX_SP_MAX 6u       /* s16s, in the battle's context */
#define CTX_SP 8u
#define CTX_SP_FREE 10u     /* SP after the round's reservations */
#define CTX_DEFEAT 4u       /* u8, the event's defeat condition: 1 Try again, 2 the story carries on */
#define DEFEAT_GOES_ON 2
#define CHARACTERS 6        /* party.character[6], 92 bytes each */
#define CHAR_HP 24u         /* s16, in a character */

static const SoaModApi* g_api;
static int g_exp = 2, g_gold = 2, g_magic = 2; /* in halves: 2 is x1 */
static int g_spirit, g_escape, g_no_ko;
static int g_test;    /* 1 lowhp, 2 poison */
static int g_started; /* this battle's first round has been seen */
static uint32_t g_round;   /* the round number at the last safe point in a battle */
static uint32_t g_said_ctx; /* the context no_ko last said it stands down for */
static int g_lowered; /* the test switch has said it lowered the party */

static const char* const k_mult[] = {"0", "0.5", "1", "1.5", "2", "3", "4"};
static const int k_halves[] = {0, 1, 2, 3, 4, 6, 8};

static const char* option(const char* name)
{
    return g_api->size >= SOA_MOD_HAS(option) ? g_api->option(name) : NULL;
}

/* An option of the multiplier enum, in halves; x1 for one not set. */
static int halves(const char* name)
{
    const char* v = option(name);
    int i;
    for (i = 0; v && i < 7; i++)
        if (!strcmp(v, k_mult[i])) return k_halves[i];
    return 2;
}

static int on(const char* name)
{
    const char* v = option(name);
    return v && !strcmp(v, "1");
}

/* v times halves / 2, rounded down, in 64 bits. */
static int32_t times(int32_t v, int h)
{
    int64_t x = (int64_t)v * h / 2;
    return x > INT32_MAX ? INT32_MAX : (int32_t)x;
}

/* An environment variable as the mod sees it: 1 with its value, 0 unset. */
static int env(const char* name, char* out, unsigned cap)
{
#ifdef _WIN32
    DWORD n = GetEnvironmentVariableA(name, out, cap); /* the process's environment */
    if (!n) return 0;
    if (n >= cap) snprintf(out, cap, "%s", "(too long)");
#else
    const char* v = getenv(name);
    if (!v) return 0;
    snprintf(out, cap, "%s", strlen(v) < cap ? v : "(too long)");
#endif
    return 1;
}

static uint32_t actor(int slot)
{
    uint32_t a = 0;
    g_api->read32(SOA_BATTLE_ACTORS + 4u * (uint32_t)slot, &a);
    return a;
}

/* The party slot an actor pointer is, or -1. */
static int party_slot(uint32_t a)
{
    int slot;
    for (slot = 0; a && slot < PARTY; slot++)
        if (actor(slot) == a) return slot;
    return -1;
}

static int32_t hp_of(uint32_t a)
{
    uint32_t v = 0;
    g_api->read32(a + HP, &v);
    return (int32_t)v;
}

/* No knock-outs for this battle: not where losing carries the story on,
 * which the assist would turn into a battle that cannot end. Said once. */
static int guarding(void)
{
    uint32_t ctx = 0;
    uint8_t defeat = 0;
    if (!g_api->read32(SOA_BATTLE_CONTEXT, &ctx) || !ctx || !g_api->read8(ctx + CTX_DEFEAT, &defeat) ||
        defeat != DEFEAT_GOES_ON)
        return 1;
    if (ctx != g_said_ctx) {
        g_api->log("no knock-outs stands down for this battle: losing it carries the story on (defeat condition 2)");
        g_said_ctx = ctx;
    }
    return 0;
}

/* The most a blow may take and leave the member standing at 1. */
static int32_t room(int32_t hp)
{
    return hp > 1 ? hp - 1 : 0;
}

static void rewards(void* user, SoaRewards* r)
{
    (void)user;
    r->exp = times(r->exp, g_exp);
    r->gold = times(r->gold, g_gold);
    r->magic_exp = times(r->magic_exp, g_magic);
    if (r->magic_exp > 127) r->magic_exp = 127;
}

static int escape(void* user, int success, int slot)
{
    char line[96];
    (void)user;
    if (slot < 0 || slot >= PARTY || success) return success;
    snprintf(line, sizeof line, "escape: slot %d's Run failed its roll; it gets away", slot);
    g_api->log(line);
    return 1;
}

static uint32_t damage(void* user, uint32_t value, uint32_t base, uint32_t attacker, uint32_t target,
                       uint32_t element)
{
    char line[128];
    int slot = party_slot(target);
    int32_t hp, most;
    (void)user;
    (void)base;
    (void)attacker;
    (void)element;
    if (slot < 0 || (int32_t)value <= 0 || !guarding()) return value;
    hp = hp_of(target);
    most = room(hp);
    if ((int32_t)value <= most) return value;
    snprintf(line, sizeof line, "no knock-out: a blow of %u on slot %d held to %d (HP %d)", value, slot, most, hp);
    g_api->log(line);
    return (uint32_t)most;
}

/* Effect 0, and the effects whose applier calls effect 0's from inside its
 * own (the spec's section 2): what lands as damage. 66 is left out, a heal
 * when its target is a party member. */
static int lands_as_damage(int e)
{
    switch (e) {
    case 0: case 4: case 8: case 17: case 44: case 61: case 62: case 65: case 69: case 70: case 72:
        return 1;
    default:
        return 0;
    }
}

/* A death the assist stops must not stay a KO in the target's result record,
 * which the action and the target's reaction read: it becomes what the game
 * shows when a death does not land, a miss, or for a blow whose damage still
 * lands, a hit. The result's old value, or -1 when it was not a KO. */
static int unmark_ko(int slot, int now)
{
    uint32_t at = SOA_BATTLE_RESULTS + 16u * (uint32_t)slot + RESULT_HIT;
    uint8_t r;
    if (!g_api->read8(at, &r) || (int8_t)r != HIT_KO) return -1;
    g_api->write8(at, (uint8_t)now);
    return HIT_KO;
}

static int effect(void* user, int target, int16_t* e, int32_t* value)
{
    char line[192];
    uint32_t a;
    int32_t hp, most;
    (void)user;
    if (target < 0 || target >= PARTY || !(a = actor(target)) || !guarding()) return 0;
    hp = hp_of(a);
    most = room(hp);
    /* A death that landed: effect 5, or 6's death branch, whose calculator
     * leaves the resolver's -1 for a value and the hit result at KO
     * (fn_8006AB6C, 0x8006AB9C-0x8006ABD8). Applied as effect 0, that -1
     * would add 1 HP; cancelled with the result made a miss, it is a death
     * spell that missed, a state the game knows. */
    if (*e == 5 || (*e == 6 && *value < 0)) {
        int was = unmark_ko(target, HIT_MISS);
        snprintf(line, sizeof line, "no knock-out: effect %d on slot %d cancelled%s (HP %d)", *e, target,
                 was == HIT_KO ? ", its KO result made a miss" : "", hp);
        g_api->log(line);
        return 1;
    }
    if (*e == 6 || *e == 68) {
        int32_t was = *value;
        int16_t which = *e;
        int ko = unmark_ko(target, HIT_HIT);
        *e = 0;
        if (*value < 0) *value = 0;
        if (*value > most) *value = most;
        snprintf(line, sizeof line, "no knock-out: effect %d value %d on slot %d -> effect 0 value %d%s (HP %d)", which,
                 was, target, *value, ko == HIT_KO ? ", its KO result made a hit" : "", hp);
        g_api->log(line);
        return 0;
    }
    if (lands_as_damage(*e) && *value > most) {
        snprintf(line, sizeof line, "no knock-out: effect %d value %d on slot %d held to %d (HP %d)", *e, *value,
                 target, most, hp);
        g_api->log(line);
        *value = most;
    }
    return 0;
}

/* The round's end has just set the lethal-poison bits and moved its state on;
 * the next state acts on them. A member left at 1 HP gets the low-HP bit too,
 * as fn_80010474 gives it after any HP change and as a round's non-lethal
 * poison leaves it -- between rounds, the moment the game itself sets it. */
static void round_end(void* user, uint32_t round)
{
    char line[160];
    uint32_t word = 0, was;
    int slot;
    (void)user;
    if (!g_api->read32(SOA_BATTLE_POISON_LETHAL, &word) || !(word & ((1u << PARTY) - 1u)) || !guarding()) return;
    was = word;
    for (slot = 0; slot < PARTY; slot++) {
        uint32_t a, st = 0;
        if (!(word & (1u << slot))) continue;
        word &= ~(1u << slot);
        if (!(a = actor(slot))) continue;
        snprintf(line, sizeof line, "no knock-out: round %u, poison would have knocked out slot %d: HP %d -> 1", round,
                 slot, hp_of(a));
        g_api->log(line);
        g_api->write32(a + HP, 1);
        if (g_api->read32(a + STATUS, &st) && !(st & LOW_HP)) g_api->write32(a + STATUS, st | LOW_HP);
    }
    g_api->write32(SOA_BATTLE_POISON_LETHAL, word);
    snprintf(line, sizeof line, "no knock-out: lethal-poison word %08X -> %08X", was, word);
    g_api->log(line);
}

static void fill_spirit(uint32_t ctx)
{
    char line[96];
    uint16_t max = 0, sp = 0;
    int slot;
    for (slot = 0; slot < PARTY; slot++) {
        uint32_t a = actor(slot), st = 0;
        if (a && g_api->read32(a + STATUS, &st) && !(st & NOT_PRESENT) && (st & NO_SPIRIT)) {
            g_api->log("full spirit: a member's equipment holds SP at 0; left as it is");
            return;
        }
    }
    if (!g_api->read16(ctx + CTX_SP_MAX, &max) || !g_api->read16(ctx + CTX_SP, &sp)) return;
    g_api->write16(ctx + CTX_SP, max);
    g_api->write16(ctx + CTX_SP_FREE, max);
    snprintf(line, sizeof line, "full spirit: SP %d -> %d of %d", (int16_t)sp, (int16_t)max, (int16_t)max);
    g_api->log(line);
}

/* SOA_BOOSTS_TEST between battles: every party character at 1 HP. */
static void test_characters(void)
{
    char line[96];
    int c, n = 0;
    for (c = 0; c < CHARACTERS; c++) {
        uint32_t at = SOA_PARTY_CHARACTER + 92u * (uint32_t)c + CHAR_HP;
        uint16_t hp;
        if (g_api->read16(at, &hp) && (int16_t)hp > 1) {
            g_api->write16(at, 1);
            n++;
        }
    }
    if (n && !g_lowered) {
        snprintf(line, sizeof line, "test: %d character(s) at 1 HP from frame %u", n, g_api->frame());
        g_api->log(line);
        g_lowered = 1;
    }
}

/* SOA_BOOSTS_TEST at a battle's first round: what each living member came in
 * with, and for 2 poison. */
static void test_party(void)
{
    char line[96];
    int slot;
    for (slot = 0; slot < PARTY; slot++) {
        uint32_t a = actor(slot), st = 0;
        if (!a || !g_api->read32(a + STATUS, &st) || (st & NOT_PRESENT)) continue;
        snprintf(line, sizeof line, "test: slot %d at HP %d%s", slot, hp_of(a), g_test == 2 ? ", poisoned" : "");
        g_api->log(line);
        if (g_test == 2) g_api->write32(a + STATUS, st | POISONED);
    }
}

static void safe_point(void* user)
{
    uint32_t ctx = 0, phase = 0;
    uint8_t round = 0;
    (void)user;
    if (g_api->scene() != SCENE_BATTLE) {
        g_started = 0;
        g_round = 0;
        if (g_test) test_characters();
        return;
    }
    /* A battle begun again inside scene 7 -- Try again rebuilds it there, the
     * phase back to 0 and the round to 1 (fn_8006F424, fn_8000A118) -- is a
     * new battle too. */
    g_api->read32(SOA_BATTLE_PHASE, &phase);
    g_api->read8(SOA_BATTLE_ROUND, &round);
    if (phase == 0 || round < g_round) g_started = 0;
    g_round = round;
    if (g_started || !g_api->read32(SOA_BATTLE_CONTEXT, &ctx) || !ctx || (phase != 1 && phase != 2)) return;
    g_started = 1;
    if (g_spirit) fill_spirit(ctx);
    if (g_test) test_party();
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    char v[32], line[192];
    size_t n = 0;
    g_api = api;
    /* on_round_end is the last member this mod calls (R1). */
    if (version < 1 || api->size < SOA_MOD_HAS(on_round_end)) {
        api->log("this port has no battle events (R1); nothing boosted");
        return 1;
    }
    g_exp = halves("exp");
    g_gold = halves("gold");
    g_magic = halves("magic_exp");
    g_spirit = on("full_spirit");
    g_escape = on("escape");
    g_no_ko = on("no_ko");
    if (env("SOA_BOOSTS_TEST", v, sizeof v) && v[0]) {
        g_test = !strcmp(v, "lowhp") ? 1 : !strcmp(v, "poison") ? 2 : 0;
        snprintf(line, sizeof line, "SOA_BOOSTS_TEST=%s: %s", v,
                 g_test == 1   ? "every party character at 1 HP between battles"
                 : g_test == 2 ? "every party character at 1 HP between battles, poisoned at the first round"
                               : "not lowhp or poison; nothing done");
        api->log(line);
    }
    if (g_exp != 2 || g_gold != 2 || g_magic != 2) {
        api->on_rewards(rewards, NULL);
        n += (size_t)snprintf(line + n, sizeof line - n, "%sexp x%s, gold x%s, magic EXP x%s", n ? "; " : "",
                              option("exp"), option("gold"), option("magic_exp"));
    }
    if (g_spirit) n += (size_t)snprintf(line + n, sizeof line - n, "%sfull spirit", n ? "; " : "");
    if (g_escape) {
        api->on_escape(escape, NULL);
        n += (size_t)snprintf(line + n, sizeof line - n, "%sescape", n ? "; " : "");
    }
    if (g_no_ko) {
        api->on_damage(damage, NULL);
        api->on_effect(effect, NULL);
        api->on_round_end(round_end, NULL);
        n += (size_t)snprintf(line + n, sizeof line - n, "%sno knock-outs", n ? "; " : "");
    }
    if (g_spirit || g_test) api->on_safe_point(safe_point, NULL);
    api->log(n          ? line
             : g_test ? "every option at its default: only the test switch acts"
                      : "every option at its default: nothing registered");
    return 0;
}
