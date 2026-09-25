/*
 * An example native mod (docs/PLAN-60FPS-MODS.md M3): it logs every map the
 * party enters and every scene change, and counts the frames it saw. It
 * changes nothing in the game; it is the template to copy.
 *
 * Build it beside its mod.ini, from the repository root:
 *
 *     cl /LD /O2 /I runtime examples\mods\map-log\mod.c /Fe:examples\mods\map-log\mod.dll
 *
 * and run the port with SOA_MODS=examples/mods. The DLL is never committed
 * (.gitignore); CI builds it and loads it in the tests.
 */
#include "soa_mod.h"

#include <stdio.h>

static const SoaModApi* g_api;
static unsigned long g_safe_points;

static void on_safe_point(void* user)
{
    (void)user;
    g_safe_points++;
}

static void on_map_loaded(void* user, uint32_t map)
{
    char line[96];
    (void)user;
    snprintf(line, sizeof line, "entered a%03u%c at frame %u (safe point %lu)", (unsigned)(map >> 8),
             (char)(map & 0xFF), g_api->frame(), g_safe_points);
    g_api->log(line);
}

static void on_scene_change(void* user, uint32_t from, uint32_t to)
{
    char line[96];
    (void)user;
    snprintf(line, sizeof line, "scene %u -> %u at frame %u", from, to, g_api->frame());
    g_api->log(line);
}

__declspec(dllexport) int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    /* log is the last member this mod calls, so a port whose table reaches it
     * has everything the mod needs, whatever was appended since. */
    if (version < 1 || api->size < SOA_MOD_HAS(log)) return 1;
    g_api = api;
    api->on_safe_point(on_safe_point, NULL);
    api->on_map_loaded(on_map_loaded, NULL);
    api->on_scene_change(on_scene_change, NULL);
    api->log("map-log loaded: it logs map entries and scene changes, and changes nothing");
    return 0;
}
