/*
 * M7a, save now (docs/specs/save-now.md): the game's own save menu, opened
 * wherever the field is quiet, and a Continue from such a save landing where
 * it was made.
 *
 * The request is the one word a save point writes (save.request = 1, the
 * variant 0): the save-point task every loaded field has then opens the menu.
 * Two things follow from saving off a save point, both through X2's chunk
 * `soa.savenow` (runtime/savext.c calls the three savenow_* below):
 *   - every Continue sets sys15 to 20000, "back from my save point", and a map
 *     with no save point (no op 138 in its script, save_point_maps.h) has no
 *     such branch: a116c's stops in op 235. So after the load of a save-now
 *     save, sys15 = 0, and the player lands where the save was made;
 *   - for the game alone (a P3 export, Dolphin), a save made off a save point
 *     carries the last save-point map in its map word and letter, its own in
 *     the chunk, which the port puts back before the game reads the block.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include "plat.h"
#include "save_point_maps.h"
#include "soa_mod.h"
#include "soa_gamedata.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SCENE_FIELD 6u
#define FIELD_RUNNING 8u
#define FLAG_EVENT 1087u
#define BLOCK_MAP 5808u    /* the block's map word (map.number and map.picker on a load) */
#define BLOCK_LETTER 5812u /* and its letter */
#define CHUNK_LEN 12u      /* "SN1", the real map and letter, the fallback's */

unsigned gx_frame_count(void);
int tick_on_safe_point(void (*fn)(CpuState*));

static plat_a32 g_pending; /* set by the UI thread (the menu), taken by the guest's */
static int g_opened, g_frame_set;
static unsigned g_at_frame;
static uint32_t g_last_sp; /* number << 8 | letter of the last save-point map entered, 0 none */
static char g_why[96];     /* the last refusal, for the menu */

int savenow_is_save_point(uint32_t map)
{
    int i;
    for (i = 0; i < SAVE_POINT_MAPS; i++)
        if (k_save_point_maps[i] == map) return 1;
    return 0;
}

static uint32_t current_map(CpuState* s)
{
    return mem_r32(s, SOA_MAP_NUMBER) << 8 | mem_r8(s, SOA_MAP_LETTER);
}

/* Ask for a save now; the next safe point decides. */
void savenow_request(void) { plat_cas32(&g_pending, 0, 1); }

const char* savenow_refusal(void) { return g_why; }

/* Whether the save menu now open is one this port asked for. */
int savenow_opened(void) { return g_opened; }

/* Why the field is not quiet (the lab's test), or NULL when it is; the world
 * map passes too where `world` (M7b's warps start from it). */
const char* field_not_quiet(CpuState* s, int world)
{
    uint32_t flags = mem_r32(s, SOA_STORY_FLAGS + (FLAG_EVENT / 32u) * 4u);
    uint32_t scene = mem_r32(s, SOA_SCENE), map = mem_r32(s, SOA_MAP_NUMBER);
    if (scene == 7u) return "in a battle";
    if (scene != SCENE_FIELD) return "not on the field";
    if (mem_r32(s, SOA_FIELD_STATE) != FIELD_RUNNING) return "while the field loads";
    if (map >= 500u) return "in a ship battle";
    if (map == 99u && !world) return "on the world map (not built)";
    if ((flags >> (FLAG_EVENT % 32u)) & 1u || mem_r32(s, SOA_SCRIPT_ENTRY_BUSY) == 1u) return "during an event";
    if (mem_r32(s, SOA_SAVE_REQUEST) == 1u) return "a save is open";
    return NULL;
}

static const char* not_quiet(CpuState* s) { return field_not_quiet(s, 0); }

/* At each safe point: the last save-point map, SOA_SAVE_NOW's frame, and a
 * pending request written or refused. */
void savenow_safe_point(CpuState* s)
{
    uint32_t map;
    const char* why;
    if (mem_r32(s, SOA_SCENE) == SCENE_FIELD && mem_r32(s, SOA_FIELD_STATE) == FIELD_RUNNING) {
        map = current_map(s);
        if (savenow_is_save_point(map)) g_last_sp = map;
    }
    if (g_frame_set && gx_frame_count() >= g_at_frame) {
        g_frame_set = 0;
        savenow_request();
    }
    if (plat_cas32(&g_pending, 1, 0) != 1) return;
    if ((why = not_quiet(s)) != NULL) {
        snprintf(g_why, sizeof g_why, "not now: %s", why);
        fprintf(stderr, "[savenow] frame %u: save now refused, %s\n", gx_frame_count(), why);
        return;
    }
    mem_w32(s, SOA_SAVE_VARIANT, 0);
    mem_w32(s, SOA_SAVE_REQUEST, 1);
    g_opened = 1;
    map = current_map(s);
    fprintf(stderr, "[savenow] frame %u: the save menu asked for on a%03u%c%s\n", gx_frame_count(), map >> 8,
            (char)(map & 0xFF), savenow_is_save_point(map) ? "" : ", off a save point");
}

static void put32(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24), p[1] = (uint8_t)(v >> 16), p[2] = (uint8_t)(v >> 8), p[3] = (uint8_t)v;
}
static uint32_t get32(const uint8_t* p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

/* X2's snapshot: for a save this port opened, the chunk (its length into buf,
 * 0 for none), and off a save point the block's map word and letter set to
 * the last save-point map. */
uint32_t savenow_snapshot(CpuState* s, uint32_t block, uint8_t* buf, uint32_t cap)
{
    uint32_t map, number, fallback = 0;
    uint8_t letter;
    if (!g_opened || cap < CHUNK_LEN) return 0;
    g_opened = 0;
    number = mem_r32(s, block + BLOCK_MAP);
    letter = mem_r8(s, block + BLOCK_LETTER);
    map = number << 8 | letter;
    if (!savenow_is_save_point(map) && g_last_sp) {
        fallback = g_last_sp;
        mem_w32(s, block + BLOCK_MAP, fallback >> 8);
        mem_w8(s, block + BLOCK_LETTER, (uint8_t)fallback);
    }
    memcpy(buf, "SN1", 4);
    put32(buf + 4, map);
    put32(buf + 8, fallback);
    fprintf(stderr, "[savenow] the save holds a%03u%c%s\n", map >> 8, (char)(map & 0xFF),
            fallback ? ", and for the game alone the last save point's map" : "");
    if (fallback)
        fprintf(stderr, "[savenow] fallback: a%03u%c\n", fallback >> 8, (char)(fallback & 0xFF));
    else if (!savenow_is_save_point(map))
        fprintf(stderr, "[savenow] no save point visited yet this run: the save keeps a%03u%c, which the game "
                        "alone cannot Continue onto\n",
                map >> 8, (char)(map & 0xFF));
    return CHUNK_LEN;
}

static int g_loaded_savenow;

/* X2's load, before the game copies the block: the chunk's own map back where
 * the block still holds its fallback. */
void savenow_load_pre(CpuState* s, uint32_t block, const uint8_t* chunk, uint32_t n)
{
    uint32_t map, fallback, have;
    g_loaded_savenow = 0;
    if (!chunk || n < CHUNK_LEN || memcmp(chunk, "SN1", 4) != 0) return;
    g_loaded_savenow = 1;
    map = get32(chunk + 4);
    fallback = get32(chunk + 8);
    have = mem_r32(s, block + BLOCK_MAP) << 8 | mem_r8(s, block + BLOCK_LETTER);
    if (getenv("SOA_SAVENOW_NO_RESTORE")) return; /* M7a's mutation, for its Done */
    if (fallback && have == fallback) {
        mem_w32(s, block + BLOCK_MAP, map >> 8);
        mem_w8(s, block + BLOCK_LETTER, (uint8_t)map);
        fprintf(stderr, "[savenow] a save-now save: a%03u%c put back over its fallback a%03u%c\n", map >> 8,
                (char)(map & 0xFF), fallback >> 8, (char)(fallback & 0xFF));
    } else if (fallback) {
        fprintf(stderr, "[savenow] a save-now save saved again elsewhere (it holds a%03u%c, not its fallback): left "
                        "as it is\n",
                have >> 8, (char)(have & 0xFF));
        g_loaded_savenow = 0;
    }
}

/* After the copy: sys15 = 0, so the player lands where the save was made. */
void savenow_load_post(CpuState* s)
{
    if (!g_loaded_savenow) return;
    g_loaded_savenow = 0;
    if (getenv("SOA_SAVENOW_NO_RESTORE")) return;
    mem_w32(s, SOA_SYS15, 0);
    fprintf(stderr, "[savenow] sys15 0: the player lands where the save was made\n");
}

void savenow_init(void)
{
    const char* at = getenv("SOA_SAVE_NOW");
    if (at && *at) {
        g_at_frame = (unsigned)strtoul(at, NULL, 10);
        g_frame_set = 1;
    }
    tick_on_safe_point(savenow_safe_point);
}
