/*
 * R0, the battle harness, and R1's damage event pulled forward
 * (docs/specs/battle-harness.md).
 *
 * fn_800108EC works out every damage the battle deals -- base r3, element
 * r4, attacker r5, target r6, the value in r3 (battle-system.md 259-268) --
 * and config/hle.txt answers it here: the translated original runs, then each
 * mod's on_damage (mod_damage), and the game gets what the last returns. It
 * has no back-edge, so answering it natively strips no poll.
 *
 * SOA_BATTLE_LOG=1 prints [battle] lines: each damage call, and at each safe
 * point in a battle what changed -- an actor's HP, MP or status, the SP, the
 * turn order -- with the battle's start and end. SOA_BATTLE_FORCE=mode:id:stage@F
 * writes the six-word request (encounters.md:25-42) at the first safe point
 * from frame F with the field running, the step counter zeroed first.
 *
 * R1 (docs/specs/battle-events.md) answers ten more the same way, one per
 * event mods see -- heal, enemy spawn, enemy action, turn order, spirit gain,
 * escape, rewards, effect, round end, ship damage -- and counts each site's
 * calls and the ones a mod changed for the run report.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include "mod.h"
#include "soa_mod.h"
#include "soa_gamedata.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void recomp_fn_800108EC(CpuState* s);
unsigned gx_frame_count(void);
int tick_on_safe_point(void (*fn)(CpuState*));
void hle_on_report(void (*fn)(void));

#define SCENE_BATTLE 7u
#define SCENE_FIELD 6u
#define FIELD_RUNNING 8u
#define SLOTS 12

static int g_log;
static int g_force, g_forced, g_armed_said;
static uint32_t g_force_mode, g_force_id, g_force_stage, g_force_frame;
static unsigned long long g_calls, g_nonzero, g_changed, g_battles;

/* What the last safe point saw, to log only changes. */
static struct {
    int in_battle;
    uint32_t actor[SLOTS];
    int32_t hp[SLOTS];
    uint32_t status[SLOTS];
    uint8_t mp[SLOTS];
    int16_t sp;
    int8_t order[SLOTS];
    uint32_t phase, rounds, start_frame;
    unsigned long long calls_at_start, nonzero_at_start;
} g_seen;

/* Each event site's calls, and how many of them a mod changed (R1's report:
 * with mods off every change count is 0, and a site never called did not
 * test what it says). */
static unsigned long long g_site_calls[MOD_BATTLE_EVENTS], g_site_changed[MOD_BATTLE_EVENTS];
static const char* const k_site[MOD_BATTLE_EVENTS] = {
    "damage", "heal", "enemy spawn", "enemy action", "turn order", "spirit gain",
    "escape", "rewards", "effect", "round end", "ship damage",
};

static void site(int ev, int changed)
{
    g_site_calls[ev]++;
    if (changed) g_site_changed[ev]++;
}

/* The actor slot a pointer is, or -1. */
static int slot_of(CpuState* s, uint32_t actor)
{
    int i;
    for (i = 0; i < SLOTS; i++)
        if (actor && mem_r32(s, SOA_BATTLE_ACTORS + 4u * (uint32_t)i) == actor) return i;
    return -1;
}

void fn_800108EC(CpuState* s)
{
    s->pc = 0x800108ECu; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t base = s->gpr[3], element = s->gpr[4], attacker = s->gpr[5], target = s->gpr[6];
    uint32_t original, returned;
    recomp_fn_800108EC(s);
    original = s->gpr[3];
    returned = mod_event_count(MOD_EV_DAMAGE) ? mod_damage(original, base, attacker, target, element) : original;
    s->gpr[3] = returned;
    g_calls++;
    site(MOD_EV_DAMAGE, returned != original);
    if (returned) g_nonzero++;
    if (g_log) {
        /* the target's multiplier for the element (10 neutral; none past 5) and its Guard bit, as the function
         * reads them (battle-system.md 3.3), so a checker can hold the original to its exact range */
        int mult = element <= 5 && target ? (int16_t)mem_r16(s, target + 40 + 2 * element) : 10;
        int guard = target ? (int)(mem_r32(s, target + 28) & 1) : 0;
        fprintf(stderr, "[battle] frame %u damage %d -> %d -> %d by slot %d on slot %d element %u mult %d guard %d\n",
                gx_frame_count(), (int32_t)base, (int32_t)original, (int32_t)returned, slot_of(s, attacker),
                slot_of(s, target), element, mult, guard);
    }
}

/* ---- R1: the battle's other events (docs/specs/battle-events.md) ---------
 * Each wrapper stores its pc first (test_hle_pc) and runs the translated
 * original; with no mod on its event it reads and writes nothing more. */

void recomp_fn_8006AE20(CpuState* s);
void recomp_fn_800770B8(CpuState* s);
void recomp_fn_8008A424(CpuState* s);
void recomp_fn_80070C18(CpuState* s);
void recomp_fn_8006EF48(CpuState* s);
void recomp_fn_80010340(CpuState* s);
void recomp_fn_8006F4B0(CpuState* s);
void recomp_fn_8002BD88(CpuState* s);
void recomp_fn_8006FD6C(CpuState* s);
void recomp_fn_80146BF4(CpuState* s);

/* Recover HP (calculator 31, and Blue Rogues' heal): source r3 and target r4
 * are slots; the value lands in the target's task's work, +60. */
void fn_8006AE20(CpuState* s)
{
    s->pc = 0x8006AE20u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    int source = (int16_t)s->gpr[3], target = (int16_t)s->gpr[4];
    uint32_t work = 0, value = 0, returned;
    recomp_fn_8006AE20(s);
    if (target >= 0 && target < SLOTS && (mod_event_count(MOD_EV_HEAL) || g_log)) {
        uint32_t task = mem_r32(s, SOA_BATTLE_TASKS + 4u * (uint32_t)target);
        work = task ? mem_r32(s, task + 36) : 0;
        value = work ? mem_r32(s, work + 60) : 0;
    }
    returned = work && mod_event_count(MOD_EV_HEAL) ? mod_heal(value, source, target) : value;
    if (returned != value) mem_w32(s, work + 60, returned);
    site(MOD_EV_HEAL, returned != value);
    if (g_log)
        fprintf(stderr, "[battle] frame %u heal %d -> %d by slot %d on slot %d\n", gx_frame_count(), (int32_t)value,
                (int32_t)returned, source, target);
}

/* An enemy made from its record: actor r3, record r4 (a leaf). */
void fn_800770B8(CpuState* s)
{
    s->pc = 0x800770B8u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t actor = s->gpr[3], record = s->gpr[4];
    int32_t hp;
    uint8_t before[276]; /* the whole actor (battle-system.md 1.2): a mod may scale any of it, not HP alone */
    int changed = 0;
    recomp_fn_800770B8(s);
    hp = (int32_t)mem_r32(s, actor + 20);
    if (mod_event_count(MOD_EV_ENEMY_SPAWN)) {
        memcpy(before, mem_ptr(s, actor), sizeof before);
        mod_enemy_spawn(actor, record);
        changed = memcmp(before, mem_ptr(s, actor), sizeof before) != 0;
    }
    site(MOD_EV_ENEMY_SPAWN, changed);
    if (g_log)
        fprintf(stderr, "[battle] frame %u spawn actor %08X record %08X hp %d -> %d\n", gx_frame_count(), actor, record,
                hp, (int32_t)mem_r32(s, actor + 20));
}

/* An enemy's choice for slot r3: its command record filled, the type in r3. */
void fn_8008A424(CpuState* s)
{
    s->pc = 0x8008A424u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    int slot = (int16_t)s->gpr[3];
    uint32_t cmd = SOA_BATTLE_COMMANDS + 32u * (uint32_t)(slot & 15), type, returned;
    uint8_t before[32];
    int changed = 0;
    recomp_fn_8008A424(s);
    type = returned = s->gpr[3];
    if (mod_event_count(MOD_EV_ENEMY_ACTION) && slot >= 0 && slot < SLOTS) {
        memcpy(before, mem_ptr(s, cmd), sizeof before);
        returned = mod_enemy_action(type, slot, cmd);
        s->gpr[3] = returned;
        changed = returned != type || memcmp(before, mem_ptr(s, cmd), sizeof before) != 0;
    }
    site(MOD_EV_ENEMY_ACTION, changed);
    if (g_log)
        fprintf(stderr, "[battle] frame %u action slot %d type %u -> %u target %d id %d\n", gx_frame_count(), slot, type,
                returned, (int8_t)mem_r8(s, cmd + 4), (int16_t)mem_r16(s, cmd + 6));
}

/* Phase 2, each frame of it: the order is set by the call that leaves it for 3. */
void fn_80070C18(CpuState* s)
{
    s->pc = 0x80070C18u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t was = mem_r32(s, SOA_BATTLE_PHASE);
    int8_t order[SLOTS], mine[SLOTS];
    int i, n, seen = 0, ok = 1, changed = 0;
    recomp_fn_80070C18(s);
    if (was != 2 || mem_r32(s, SOA_BATTLE_PHASE) != 3) return;
    for (i = 0; i < SLOTS; i++) order[i] = (int8_t)mem_r8(s, SOA_BATTLE_TURN_ORDER + (uint32_t)i);
    if (mod_event_count(MOD_EV_TURN_ORDER)) {
        memcpy(mine, order, sizeof mine);
        mod_turn_order(mine);
        /* distinct slots 0-11, up to a -1 or all twelve */
        for (n = 0; n < SLOTS && mine[n] >= 0; n++)
            if (mine[n] >= SLOTS || (seen & (1 << mine[n]))) ok = 0;
            else seen |= 1 << mine[n];
        if (n < SLOTS && mine[n] != -1) ok = 0;
        if (!ok) {
            fprintf(stderr, "[battle] frame %u a mod's turn order is not distinct slots 0-11 ending at -1: the game's "
                            "is kept\n",
                    gx_frame_count());
        } else if (memcmp(mine, order, (size_t)(n < SLOTS ? n + 1 : SLOTS)) != 0) {
            for (i = 0; i < n; i++) mem_w8(s, SOA_BATTLE_TURN_ORDER + (uint32_t)i, (uint8_t)mine[i]);
            if (n < SLOTS) mem_w8(s, SOA_BATTLE_TURN_ORDER + (uint32_t)n, 0xFF);
            memcpy(order, mine, sizeof order);
            changed = 1;
        }
    }
    site(MOD_EV_TURN_ORDER, changed);
    if (g_log) {
        char text[64];
        size_t used = 0;
        for (i = 0; i < SLOTS && order[i] >= 0; i++)
            used += (size_t)snprintf(text + used, sizeof text - used, "%s%d", i ? " " : "", order[i]);
        text[used] = '\0';
        fprintf(stderr, "[battle] frame %u turn order %s%s\n", gx_frame_count(), used ? text : "(none)",
                changed ? " (a mod's)" : "");
    }
}

/* The round's spirit: the gain before the gauge's clamp is read by running the
 * original from 0 with no ceiling, so its own rules still decide it. */
void fn_8006EF48(CpuState* s)
{
    s->pc = 0x8006EF48u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t ctx = mem_r32(s, SOA_BATTLE_CONTEXT);
    int16_t sp, max;
    int32_t sum, amount, now;
    if (!ctx || !mod_event_count(MOD_EV_SPIRIT_GAIN)) {
        sp = ctx ? (int16_t)mem_r16(s, ctx + 8) : 0;
        recomp_fn_8006EF48(s);
        site(MOD_EV_SPIRIT_GAIN, 0);
        if (g_log && ctx)
            fprintf(stderr, "[battle] frame %u spirit %d -> %d of %d\n", gx_frame_count(), sp,
                    (int16_t)mem_r16(s, ctx + 8), (int16_t)mem_r16(s, ctx + 6));
        return;
    }
    sp = (int16_t)mem_r16(s, ctx + 8);
    max = (int16_t)mem_r16(s, ctx + 6);
    mem_w16(s, ctx + 8, 0);
    mem_w16(s, ctx + 6, 0x7FFF);
    recomp_fn_8006EF48(s);
    sum = (int16_t)mem_r16(s, ctx + 8);
    mem_w16(s, ctx + 6, (uint16_t)max);
    amount = mod_spirit_gain(sum);
    now = sp + amount;
    now = now < 0 ? 0 : now > max ? max : now;
    mem_w16(s, ctx + 8, (uint16_t)now);
    mem_w16(s, ctx + 10, (uint16_t)now);
    site(MOD_EV_SPIRIT_GAIN, amount != sum);
    if (g_log)
        fprintf(stderr, "[battle] frame %u spirit %d -> %d of %d, gain %d -> %d\n", gx_frame_count(), sp, now, max, sum,
                amount);
}

/* A Run, the party's or an enemy's, for slot r3: 1 in r3 escapes. */
void fn_80010340(CpuState* s)
{
    s->pc = 0x80010340u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    int slot = (int16_t)s->gpr[3], success, returned;
    recomp_fn_80010340(s);
    success = returned = s->gpr[3] != 0;
    if (mod_event_count(MOD_EV_ESCAPE)) {
        returned = mod_escape(success, slot);
        s->gpr[3] = (uint32_t)returned;
    }
    site(MOD_EV_ESCAPE, returned != success);
    if (g_log)
        fprintf(stderr, "[battle] frame %u escape slot %d %d -> %d\n", gx_frame_count(), slot, success, returned);
}

/* Phase 7, each frame of it: the call that finds the round state at 2 pays. */
void fn_8006F4B0(CpuState* s)
{
    s->pc = 0x8006F4B0u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t ctx = mem_r32(s, SOA_BATTLE_CONTEXT);
    if (ctx && mem_r32(s, SOA_BATTLE_ROUND_STATE) == 2) {
        SoaRewards r, was;
        r.exp = (int32_t)mem_r32(s, ctx + 48);
        r.gold = (int32_t)mem_r32(s, ctx + 52);
        r.magic_exp = (int8_t)mem_r8(s, ctx + 1);
        was = r;
        if (mod_event_count(MOD_EV_REWARDS)) {
            mod_rewards(&r);
            r.exp = r.exp < 0 ? 0 : r.exp;
            r.gold = r.gold < 0 ? 0 : r.gold > 99999999 ? 99999999 : r.gold;
            r.magic_exp = r.magic_exp < 0 ? 0 : r.magic_exp > 127 ? 127 : r.magic_exp;
            if (r.exp != was.exp) mem_w32(s, ctx + 48, (uint32_t)r.exp);
            if (r.gold != was.gold) mem_w32(s, ctx + 52, (uint32_t)r.gold);
            if (r.magic_exp != was.magic_exp) mem_w8(s, ctx + 1, (uint8_t)r.magic_exp);
        }
        site(MOD_EV_REWARDS, r.exp != was.exp || r.gold != was.gold || r.magic_exp != was.magic_exp);
        if (g_log)
            fprintf(stderr, "[battle] frame %u rewards exp %d -> %d gold %d -> %d magic exp %d -> %d\n", gx_frame_count(),
                    was.exp, r.exp, was.gold, r.gold, was.magic_exp, r.magic_exp);
    }
    recomp_fn_8006F4B0(s);
}

/* Every effect applied: msg r3 (+0 target, +6 effect, +8 value), before it is.
 * Every caller drops r3, so a cancelled effect simply returns. */
void fn_8002BD88(CpuState* s)
{
    s->pc = 0x8002BD88u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t msg = s->gpr[3];
    int target = (int16_t)mem_r16(s, msg), cancel = 0;
    int16_t effect = (int16_t)mem_r16(s, msg + 6), e = effect;
    int32_t value = (int32_t)mem_r32(s, msg + 8), v = value;
    if (mod_event_count(MOD_EV_EFFECT)) {
        cancel = mod_effect(target, &e, &v);
        if (e != effect) mem_w16(s, msg + 6, (uint16_t)e);
        if (v != value) {
            /* fn_8002DD8C copied the value from the target's work (+60), and the
             * pop-up and the action's end read it there again: a value changed
             * in the message alone left the action waiting, the pop-up showing
             * the old one (FINDINGS "R1, the battle events"). Written where it still matches, so
             * the follow-up messages with values of their own are left alone. */
            uint32_t task = target >= 0 && target < SLOTS ? mem_r32(s, SOA_BATTLE_TASKS + 4u * (uint32_t)target) : 0;
            uint32_t work = task ? mem_r32(s, task + 36) : 0;
            mem_w32(s, msg + 8, (uint32_t)v);
            if (work && (int32_t)mem_r32(s, work + 60) == value) mem_w32(s, work + 60, (uint32_t)v);
        }
    }
    site(MOD_EV_EFFECT, cancel || e != effect || v != value);
    if (g_log)
        fprintf(stderr, "[battle] frame %u effect %d value %d on slot %d -> effect %d value %d%s\n", gx_frame_count(),
                effect, value, target, e, v, cancel ? ", cancelled" : "");
    if (!cancel) recomp_fn_8002BD88(s);
}

/* Phase 6, each frame of it: the call that moves the round state off 0. */
void fn_8006FD6C(CpuState* s)
{
    s->pc = 0x8006FD6Cu; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t was = mem_r32(s, SOA_BATTLE_ROUND_STATE);
    recomp_fn_8006FD6C(s);
    if (was != 0 || mem_r32(s, SOA_BATTLE_ROUND_STATE) == 0) return;
    if (mod_event_count(MOD_EV_ROUND_END)) mod_round_end(mem_r8(s, SOA_BATTLE_ROUND));
    site(MOD_EV_ROUND_END, 0);
    if (g_log) fprintf(stderr, "[battle] frame %u round %u ends\n", gx_frame_count(), mem_r8(s, SOA_BATTLE_ROUND));
}

/* A ship battle's damage core: the value in r3, before its caller's x10. */
void fn_80146BF4(CpuState* s)
{
    s->pc = 0x80146BF4u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t original, returned;
    recomp_fn_80146BF4(s);
    original = returned = s->gpr[3];
    if (mod_event_count(MOD_EV_SHIP_DAMAGE)) {
        returned = mod_ship_damage(original);
        s->gpr[3] = returned;
    }
    site(MOD_EV_SHIP_DAMAGE, returned != original);
    if (g_log)
        fprintf(stderr, "[battle] frame %u ship damage %d -> %d\n", gx_frame_count(), (int32_t)original,
                (int32_t)returned);
}

/* The turn order as the game keeps it: slots, ending at -1. */
static void read_order(CpuState* s, int8_t* out)
{
    int i, end = 0;
    for (i = 0; i < SLOTS; i++) {
        out[i] = end ? -1 : (int8_t)mem_r8(s, 0x803092F4u + (uint32_t)i);
        if (out[i] < 0) end = 1;
    }
}

static void battle_log_changes(CpuState* s, unsigned frame)
{
    uint32_t ctx = mem_r32(s, SOA_BATTLE_CONTEXT), phase = mem_r32(s, SOA_BATTLE_PHASE);
    int8_t order[SLOTS];
    int i;
    for (i = 0; i < SLOTS; i++) {
        uint32_t a = mem_r32(s, SOA_BATTLE_ACTORS + 4u * (uint32_t)i);
        int32_t hp = a ? (int32_t)mem_r32(s, a + 20) : 0;
        uint32_t status = a ? mem_r32(s, a + 28) : 0;
        uint8_t mp = a ? mem_r8(s, a + 254) : 0;
        if (a != g_seen.actor[i] || hp != g_seen.hp[i] || status != g_seen.status[i] || mp != g_seen.mp[i]) {
            if (a)
                fprintf(stderr, "[battle] frame %u slot %d hp %d/%d mp %u status %08X\n", frame, i, hp,
                        (int32_t)mem_r32(s, a + 24), mp, status);
            else if (g_seen.actor[i])
                fprintf(stderr, "[battle] frame %u slot %d gone\n", frame, i);
            g_changed++;
        }
        g_seen.actor[i] = a;
        g_seen.hp[i] = hp;
        g_seen.status[i] = status;
        g_seen.mp[i] = mp;
    }
    if (ctx) {
        int16_t sp = (int16_t)mem_r16(s, ctx + 8);
        if (sp != g_seen.sp) fprintf(stderr, "[battle] frame %u sp %d/%d\n", frame, sp, (int16_t)mem_r16(s, ctx + 6));
        g_seen.sp = sp;
    }
    read_order(s, order);
    if (memcmp(order, g_seen.order, sizeof order) != 0) {
        char text[80];
        size_t used = 0;
        for (i = 0; i < SLOTS && order[i] >= 0; i++)
            used += (size_t)snprintf(text + used, sizeof text - used, "%s%d", i ? " " : "", order[i]);
        text[used] = '\0';
        fprintf(stderr, "[battle] frame %u order %s\n", frame, used ? text : "(none)");
        memcpy(g_seen.order, order, sizeof order);
    }
    if (phase == 1 && g_seen.phase != 1) g_seen.rounds++;
    g_seen.phase = phase;
}

static void battle_safe_point(CpuState* s)
{
    unsigned frame = gx_frame_count();
    uint32_t scene = mem_r32(s, SOA_SCENE), state = mem_r32(s, SOA_FIELD_STATE);
    if (g_force && !g_forced && frame >= g_force_frame && scene == SCENE_FIELD && state == FIELD_RUNNING) {
        mem_w32(s, SOA_ENCOUNTER_STEPS, 0);
        mem_w32(s, SOA_BATTLE_REQUEST_MODE, g_force_mode);
        mem_w32(s, SOA_BATTLE_REQUEST_ID, g_force_id);
        mem_w32(s, SOA_BATTLE_REQUEST_STAGE, g_force_stage);
        mem_w32(s, SOA_BATTLE_REQUEST_TRANSITION, 0xFFFFFFFFu);
        mem_w32(s, SOA_BATTLE_REQUEST_FORCED, 1); /* last: what fn_800C1C24 reads first */
        g_forced = 1;
        fprintf(stderr, "[battle] frame %u forced: mode %u id %u stage %u, transition random\n", frame, g_force_mode,
                g_force_id, g_force_stage);
    } else if (g_forced && !g_armed_said && scene == SCENE_FIELD && state != FIELD_RUNNING &&
               mem_r32(s, SOA_BATTLE_REQUEST_FORCED)) {
        g_armed_said = 1;
        fprintf(stderr, "[battle] frame %u the request is still armed and the field is in state %u, not 8: it waits "
                        "for the field to run (a map load clears it)\n",
                frame, state);
    }
    if (!g_log) return;
    if (scene == SCENE_BATTLE && !g_seen.in_battle) {
        memset(&g_seen, 0, sizeof g_seen);
        memset(g_seen.order, 0xFF, sizeof g_seen.order);
        g_seen.in_battle = 1;
        g_seen.start_frame = frame;
        g_seen.calls_at_start = g_calls;
        g_seen.nonzero_at_start = g_nonzero;
        g_battles++;
        fprintf(stderr, "[battle] frame %u start: battle %llu on map %08X\n", frame, g_battles,
                mem_r32(s, SOA_MAP_NUMBER));
    }
    if (scene == SCENE_BATTLE) battle_log_changes(s, frame);
    if (scene != SCENE_BATTLE && g_seen.in_battle) {
        g_seen.in_battle = 0;
        fprintf(stderr, "[battle] frame %u end: %u frames, %u rounds, %llu damage calls (%llu nonzero), last phase %u\n",
                frame, frame - g_seen.start_frame, g_seen.rounds, g_calls - g_seen.calls_at_start,
                g_nonzero - g_seen.nonzero_at_start, g_seen.phase);
    }
}

static int g_any_event;

static void battle_report(void)
{
    int ev;
    if (g_log || g_force)
        fprintf(stderr, "[battle] %llu battle(s), %llu damage calls (%llu nonzero), %llu actor changes logged%s\n",
                g_battles, g_calls, g_nonzero, g_changed, g_force ? (g_forced ? "; the request was written" : "; the request was never written") : "");
    if (!g_log && !g_any_event) return;
    for (ev = 0; ev < MOD_BATTLE_EVENTS; ev++)
        fprintf(stderr, "[battle] site %s: %llu call(s), %llu changed by a mod%s\n", k_site[ev], g_site_calls[ev],
                g_site_changed[ev], g_site_calls[ev] ? "" : " -- never called: this run did not test it");
}

void battle_init(void)
{
    const char* log = getenv("SOA_BATTLE_LOG");
    const char* force = getenv("SOA_BATTLE_FORCE");
    g_log = log && atoi(log) ? 1 : 0;
    if (force && *force) {
        if (sscanf(force, "%u:%u:%u@%u", &g_force_mode, &g_force_id, &g_force_stage, &g_force_frame) == 4) {
            g_force = 1;
        } else {
            fprintf(stderr, "[battle] SOA_BATTLE_FORCE=%s is not mode:id:stage@frame (0:0:2@3300 is a101b's party); "
                            "nothing forced\n",
                    force);
        }
    }
    for (int ev = 0; ev < MOD_BATTLE_EVENTS; ev++)
        if (mod_event_count(ev)) g_any_event = 1;
    if (g_log || g_force) tick_on_safe_point(battle_safe_point);
    if (g_log || g_force || g_any_event) hle_on_report(battle_report);
}
