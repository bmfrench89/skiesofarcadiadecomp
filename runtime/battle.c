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
    returned = mod_damage(original, base, attacker, target, element);
    s->gpr[3] = returned;
    g_calls++;
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

static void battle_report(void)
{
    if (g_log || g_force)
        fprintf(stderr, "[battle] %llu battle(s), %llu damage calls (%llu nonzero), %llu actor changes logged%s\n",
                g_battles, g_calls, g_nonzero, g_changed, g_force ? (g_forced ? "; the request was written" : "; the request was never written") : "");
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
    if (g_log || g_force) {
        tick_on_safe_point(battle_safe_point);
        hle_on_report(battle_report);
    }
}
