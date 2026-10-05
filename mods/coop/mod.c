/*
 * coop (docs/PLAN-GAMEPLAY-MODS.md P10; the comfort-pack spec 3.12, P10b):
 * a second pad commands the party members you give it; player 1 keeps
 * everything else.
 *
 *     SOA_COOP=1      pad 2 chooses party slot 1's commands
 *     SOA_COOP=1,3    slots 1 and 3; slots are 0 to 3, 0 the lead
 *
 * A battle's party input is its phase 1 (the word at 0x8034733C, scene 7),
 * and the member choosing is the word at 0x80347330 (FINDINGS "P10b's
 * spike"). While that member is one of the slots given, the game's port 1
 * reads pad 2 (read_pad, P10a) in place of the person's pad. The game still
 * sees one controller.
 *
 * Handover: when the turn passes between the two pads, the incoming pad is
 * read as neutral until it has no button down, so a thumb resting on A
 * cannot confirm the next member's command.
 *
 * With pad 2 absent, port 1 plays everyone, said once. Each handover and
 * each press forwarded from pad 2 is logged, and at every phase 1 -> 2 edge
 * each member's command type (the s32 at 0x80309174 + 32 * m: 3 Attack,
 * 4 Guard, 5 Item...). Pad 2 is not in recordings yet, so a run it played a
 * part in cannot be replayed; the first forward says so.
 *
 * soa.ini's `coop` sets the same switch, and a recording names it. Built
 * beside its mod.ini by `python tools/recompile.py --link`.
 */
#include "soa_mod.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#define SCENE_BATTLE 7u
#define PHASE 0x8034733Cu    /* u32: the battle's phase machine; 1 is party input */
#define MEMBER 0x80347330u   /* u32: the party slot choosing, in phase 1 */
#define COMMANDS 0x80309174u /* s32 at + 32 * slot: the command type */
#define PHASE_INPUT 1u
#define PHASE_ORDER 2u
#define PORT1 1
#define PAD2 2

static const SoaModApi* g_api;
static unsigned g_slots;        /* bit m: pad 2 plays party slot m */
static int g_owner = PORT1;     /* whose pad the game reads now */
static int g_hold;              /* a handover: neutral until the incoming pad is let go */
static uint16_t g_last2;        /* pad 2's buttons at the last read, for its presses */
static uint32_t g_last_phase = 0xFFFFFFFFu;
static int g_absent_told, g_replay_told;

static void neutral(SoaPad* pad)
{
    pad->buttons = 0;
    pad->stick[0] = pad->stick[1] = 128;
    pad->cstick[0] = pad->cstick[1] = 128;
    pad->trig[0] = pad->trig[1] = 0;
}

/* At phase 1 -> 2, the command each member chose, as the game keeps it. */
static void log_commands(uint32_t frame)
{
    char line[160];
    int m, n;
    n = snprintf(line, sizeof line, "frame %u commands:", frame);
    for (m = 0; m < 4 && n > 0 && (size_t)n < sizeof line; m++) {
        uint32_t v = 0xFFFFFFFFu;
        g_api->read32(COMMANDS + 32u * (uint32_t)m, &v);
        n += snprintf(line + n, sizeof line - (size_t)n, " %d=%d", m, (int32_t)v);
    }
    g_api->log(line);
}

static void on_pad(void* user, uint32_t frame, SoaPad* pad)
{
    uint32_t phase = 0xFFFFFFFFu, member = 0xFFFFFFFFu;
    int battle = g_api->scene() == SCENE_BATTLE, theirs = 0, owner;
    SoaPad two;
    int there = g_api->read_pad(2, &two);
    (void)user;
    if (battle && g_api->read32(PHASE, &phase)) {
        if (g_last_phase == PHASE_INPUT && phase == PHASE_ORDER) log_commands(frame);
        if (phase == PHASE_INPUT && g_api->read32(MEMBER, &member) && member < 4 && (g_slots >> member & 1u)) theirs = 1;
    }
    g_last_phase = battle ? phase : 0xFFFFFFFFu;
    if (theirs && !there && !g_absent_told) {
        g_absent_told = 1;
        g_api->log("pad 2 is not connected: port 1 plays every member");
    }
    owner = theirs && there ? PAD2 : PORT1;
    if (owner != g_owner) {
        char line[96];
        if (owner == PAD2)
            snprintf(line, sizeof line, "frame %u handover: slot %u to pad 2", frame, member);
        else
            snprintf(line, sizeof line, "frame %u handover: back to port 1", frame);
        g_api->log(line);
        g_owner = owner;
        g_hold = 1;
    }
    if (g_hold) {
        uint16_t incoming = owner == PAD2 ? two.buttons : pad->buttons;
        if (incoming) {
            neutral(pad);
            g_last2 = there ? two.buttons : 0;
            return;
        }
        g_hold = 0;
    }
    if (owner == PAD2) {
        uint16_t down = (uint16_t)(two.buttons & ~g_last2);
        if (down) {
            char line[96];
            if (!g_replay_told) {
                g_replay_told = 1;
                g_api->log("pad 2 is not in recordings yet: a run it played a part in cannot be replayed");
            }
            snprintf(line, sizeof line, "frame %u pad 2 press %04X forwarded", frame, down);
            g_api->log(line);
        }
        *pad = two;
    }
    g_last2 = there ? two.buttons : 0;
}

static int env(const char* name, char* out, DWORD cap)
{
    DWORD n = GetEnvironmentVariableA(name, out, cap);
    if (!n) return 0;
    if (n >= cap) snprintf(out, cap, "%s", "(too long)");
    return 1;
}

/* "1" or "1,3": each a party slot from 0 to 3, once. 0 when it is not. */
static unsigned parse_slots(const char* v)
{
    unsigned slots = 0;
    const char* p = v;
    for (;;) {
        if (*p < '0' || *p > '3' || (slots >> (*p - '0') & 1u)) return 0;
        slots |= 1u << (*p - '0');
        p++;
        if (!*p) return slots;
        if (*p != ',') return 0;
        p++;
    }
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    char v[64], line[160];
    int m, n;
    /* read_pad is the last member this mod calls. */
    if (version < 1 || api->size < SOA_MOD_HAS(read_pad)) {
        if (api->size >= SOA_MOD_HAS(log)) api->log("this port has no read_pad (P10a): the mod needs a newer port");
        return 1;
    }
    g_api = api;
    if (!env("SOA_COOP", v, sizeof v) || !v[0]) {
        api->log("off (SOA_COOP unset): port 1 plays every member");
        return 0;
    }
    g_slots = parse_slots(v);
    if (!g_slots) {
        snprintf(line, sizeof line, "SOA_COOP=%s is not party slots 0 to 3, e.g. 1 or 1,3; off", v);
        api->log(line);
        return 0;
    }
    api->pad_filter(on_pad, NULL);
    n = snprintf(line, sizeof line, "pad 2 chooses the commands of party slot(s)");
    for (m = 0; m < 4; m++)
        if (g_slots >> m & 1u) n += snprintf(line + n, sizeof line - (size_t)n, " %d", m);
    snprintf(line + n, sizeof line - (size_t)n, " in battle; port 1 plays the rest");
    api->log(line);
    return 0;
}
