/*
 * M7b, the debug actions (docs/specs/debug-actions.md): each one a FINDINGS
 * recipe, written at the safe point, and refused with its reason when the
 * field is not quiet (M7a's test, savenow.c) or the target is not one it can
 * reach.
 *   warp:NNNx  the script name in warp.script, sys15 0 (the default entrance),
 *              then field.state 15, the game's own warp, last; a map of
 *              warp_maps.h only (a script and its geometry, below 500)
 *   part       a warp to 355a, the developers' part menu
 *   ending     story.vars B[76] = 'L': state 8 hands over to the staff roll
 *   fade       fade.direction 0: a field a map load left black comes back
 *   encounters:off / encounters:on   encounter.steps 0 at every safe point
 *              while off, so the roll never passes
 */
#define _CRT_SECURE_NO_WARNINGS
#include "actions.h"
#include "cpu.h"
#include "plat.h"
#include "soa_mod.h"
#include "soa_gamedata.h"
#include "warp_maps.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SCHEDULE_MAX 32
#define ENDING_VAR 76u
#define FIELD_WARP 15u

unsigned gx_frame_count(void);
int tick_on_safe_point(void (*fn)(CpuState*));
const char* field_not_quiet(CpuState* s, int world); /* savenow.c */

static const char* const k_name[ACT_KINDS] = {"", "warp", "part", "ending", "fade", "encounters:off", "encounters:on"};

static struct {
    int kind;
    uint32_t map;
    unsigned frame;
} g_sched[SCHEDULE_MAX];
static int g_sched_n;
static plat_a32 g_req; /* kind << 24 | map, 0 none: the menu's, from the UI thread */
static int g_enc_off;

int actions_encounters_off(void) { return g_enc_off; }
int actions_warp_count(void) { return WARP_MAPS; }
uint32_t actions_warp_map(int i) { return i >= 0 && i < WARP_MAPS ? k_warp_maps[i] : 0; }

static int warpable(uint32_t map)
{
    int i;
    for (i = 0; i < WARP_MAPS; i++)
        if (k_warp_maps[i] == map) return 1;
    return 0;
}

int actions_request(int kind, uint32_t map)
{
    if (kind <= ACT_NONE || kind >= ACT_KINDS) return 0;
    return plat_cas32(&g_req, 0, (int32_t)((uint32_t)kind << 24 | (map & 0xFFFFFFu))) == 0;
}

/* "116c" or "a116c" -> number << 8 | letter, 0 if it is not one. */
static uint32_t map_of(const char* t)
{
    if (t[0] == 'a' && strlen(t) == 5) t++;
    if (strlen(t) != 4 || t[3] < 'a' || t[3] > 'z') return 0;
    if (t[0] < '0' || t[0] > '9' || t[1] < '0' || t[1] > '9' || t[2] < '0' || t[2] > '9') return 0;
    return (uint32_t)((t[0] - '0') * 100 + (t[1] - '0') * 10 + (t[2] - '0')) << 8 | (uint32_t)t[3];
}

int actions_parse(const char* text)
{
    char buf[512], *item, *next;
    int n = 0;
    snprintf(buf, sizeof buf, "%s", text ? text : "");
    for (item = buf; item; item = next) {
        char* at;
        if ((next = strchr(item, ',')) != NULL) *next++ = '\0';
        if (!*item) continue;
        at = strrchr(item, '@');
        char* end = NULL;
        unsigned long frame;
        int kind = ACT_NONE, k;
        uint32_t map = 0;
        while (*item == ' ') item++;
        if (!at || !at[1]) {
            fprintf(stderr, "[action] `%s` is not NAME[:ARG]@FRAME: nothing scheduled\n", item);
            return -1;
        }
        *at = '\0';
        frame = strtoul(at + 1, &end, 10);
        if (*end) {
            fprintf(stderr, "[action] `%s@%s`: the frame is not a number: nothing scheduled\n", item, at + 1);
            return -1;
        }
        if (!strncmp(item, "warp:", 5)) {
            kind = ACT_WARP;
            if (!(map = map_of(item + 5))) {
                fprintf(stderr, "[action] `%s`: a warp names a map like 116c: nothing scheduled\n", item);
                return -1;
            }
        } else {
            for (k = ACT_PART; k < ACT_KINDS; k++)
                if (!strcmp(item, k_name[k])) kind = k;
        }
        if (kind == ACT_NONE) {
            fprintf(stderr, "[action] `%s` is not warp:NNNx, part, ending, fade, encounters:off or encounters:on: "
                            "nothing scheduled\n",
                    item);
            return -1;
        }
        if (g_sched_n == SCHEDULE_MAX) {
            fprintf(stderr, "[action] more than %d actions: nothing past them scheduled\n", SCHEDULE_MAX);
            return -1;
        }
        g_sched[g_sched_n].kind = kind;
        g_sched[g_sched_n].map = map;
        g_sched[g_sched_n].frame = (unsigned)frame;
        g_sched_n++;
        n++;
    }
    return n;
}

static void name_of(uint32_t map, char out[16])
{
    snprintf(out, 16, "%03u%c", map >> 8, (char)(map & 0xFF));
}

/* One action now: written, or refused with its reason. */
static void run(CpuState* s, int kind, uint32_t map)
{
    const char* why = NULL;
    char m[16];
    unsigned f = gx_frame_count();
    if (kind == ACT_ENCOUNTERS_OFF || kind == ACT_ENCOUNTERS_ON) {
        g_enc_off = kind == ACT_ENCOUNTERS_OFF;
        fprintf(stderr, "[action] frame %u: encounters %s\n", f, g_enc_off ? "off" : "on");
        return;
    }
    if (kind == ACT_FADE) {
        if (mem_r32(s, SOA_SCENE) != 6u) why = "not on the field";
    } else {
        why = field_not_quiet(s, kind == ACT_WARP || kind == ACT_PART);
    }
    if (kind == ACT_PART) map = 355u << 8 | 'a';
    name_of(map, m);
    if (!why && (kind == ACT_WARP || kind == ACT_PART) && !warpable(map))
        why = (map >> 8) >= 500u ? "a ship battle starts through op 210, not a warp" : "no script and geometry by that name";
    if (why) {
        fprintf(stderr, "[action] frame %u: %s%s%s refused, %s\n", f, k_name[kind], kind == ACT_WARP ? " to " : "",
                kind == ACT_WARP ? m : "", why);
        return;
    }
    switch (kind) {
    case ACT_WARP:
    case ACT_PART: {
        char script[12];
        int i;
        memset(script, 0, sizeof script);
        snprintf(script, sizeof script, "ME%03u%c.SCT", map >> 8, (char)((map & 0xFF) - 'a' + 'A'));
        for (i = 0; i < 12; i++) mem_w8(s, SOA_WARP_SCRIPT + (uint32_t)i, (uint8_t)script[i]);
        mem_w32(s, SOA_SYS15, 0);
        mem_w32(s, SOA_FIELD_STATE, FIELD_WARP); /* last: what starts it */
        fprintf(stderr, "[action] frame %u: %s to %s\n", f, kind == ACT_PART ? "part select, a warp" : "warp", m);
        break;
    }
    case ACT_ENDING:
        mem_w8(s, SOA_STORY_VARS + ENDING_VAR, 'L');
        fprintf(stderr, "[action] frame %u: the ending (B[76] = 'L')\n", f);
        break;
    case ACT_FADE:
        mem_w32(s, SOA_FADE_DIRECTION, 0);
        fprintf(stderr, "[action] frame %u: the fade turned in\n", f);
        break;
    }
}

void actions_safe_point(CpuState* s)
{
    int i;
    int32_t req;
    unsigned f = gx_frame_count();
    for (i = 0; i < g_sched_n; i++)
        if (g_sched[i].kind != ACT_NONE && f >= g_sched[i].frame) {
            run(s, g_sched[i].kind, g_sched[i].map);
            g_sched[i].kind = ACT_NONE;
        }
    req = plat_load32(&g_req);
    if (req && plat_cas32(&g_req, req, 0) == req) run(s, (int)((uint32_t)req >> 24), (uint32_t)req & 0xFFFFFFu);
    if (g_enc_off) mem_w32(s, SOA_ENCOUNTER_STEPS, 0);
}

void actions_init(void)
{
    const char* text = getenv("SOA_ACTION");
    if (text && *text && actions_parse(text) > 0)
        fprintf(stderr, "[action] SOA_ACTION: %d action(s) scheduled\n", g_sched_n);
    tick_on_safe_point(actions_safe_point);
}
