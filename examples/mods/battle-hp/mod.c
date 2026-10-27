/*
 * battle-hp, an example of M20's drawing (docs/specs/mod-overlay.md): in a
 * battle, each living enemy's HP as a bar and its numbers, one row an enemy
 * (slots 4-11, actor+20 of +24) in the picture's top-left corner -- R5's
 * first part, without the anchoring to each enemy on the screen, which needs
 * the camera. Drawn at each frame end while the scene is a battle; outside
 * one nothing is drawn, so the rows clear themselves.
 *
 * Build it beside its mod.ini, from the repository root:
 *
 *     cl /LD /O2 /I runtime examples\mods\battle-hp\mod.c /Fe:examples\mods\battle-hp\mod.dll
 */
#include "soa_mod.h"
#include "soa_gamedata.h" /* T9: the game's data by name */

#include <stdio.h>

#define SCENE_BATTLE 7u
#define HP 20u              /* s32, in an actor (battle-system.md 1.2) */
#define HP_MAX 24u
#define STATUS 28u
#define NOT_PRESENT 0x2100u /* unconscious or escaped */
#define BAR_W 120           /* game units; the picture is 640 x 480 of them */

static const SoaModApi* g_api;

static void frame_end(void* user)
{
    int slot, row = 0;
    (void)user;
    if (g_api->scene() != SCENE_BATTLE) return;
    for (slot = 4; slot < 12; slot++) {
        uint32_t a = 0, hp = 0, max = 0, st = 0;
        int32_t x = 10, y = 10 + row * 24, fill;
        char line[32];
        if (!g_api->read32(SOA_BATTLE_ACTORS + 4u * (uint32_t)slot, &a) || !a) continue;
        if (!g_api->read32(a + STATUS, &st) || (st & NOT_PRESENT)) continue;
        if (!g_api->read32(a + HP, &hp) || !g_api->read32(a + HP_MAX, &max) || (int32_t)max <= 0) continue;
        fill = (int32_t)((int64_t)BAR_W * (int32_t)hp / (int32_t)max);
        if (fill < 0) fill = 0;
        g_api->draw_rect(x - 4, y - 3, BAR_W + 8, 22, 0x000000A0u); /* a panel, see-through */
        g_api->draw_rect(x, y, BAR_W, 6, 0x502828FFu);             /* the track */
        g_api->draw_rect(x, y, fill, 6, 0x38D058FFu);              /* what is left */
        snprintf(line, sizeof line, "%d/%d", (int32_t)hp, (int32_t)max);
        g_api->draw_text(x, y + 8, 1, 0xFFFFFFFFu, line);
        row++;
    }
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    if (api->size < SOA_MOD_HAS(draw_text)) {
        api->log("this port cannot draw (M20); nothing shown");
        return 1;
    }
    g_api = api;
    return api->on_frame_end(frame_end, NULL) ? 0 : 1;
}
