/*
 * An example native mod for X2's save extension (docs/specs/save-extension.md),
 * with R1's rewards event (docs/specs/battle-events.md): it counts the battles
 * won since New Game, says the count at each victory, and keeps it in the save
 * file itself -- a 4-byte chunk filed under its id -- so loading a save brings
 * back that save's count, and New Game starts again from 0.
 *
 * A save made with it still loads anywhere: the chunk sits where the game never
 * looks. Loaded without this mod, the port keeps the chunk and writes it back at
 * the next save; `python tools/savext.py show <card>` lists it.
 *
 * Build it beside its mod.ini, from the repository root:
 *
 *     python tools/mod.py build examples/mods/battle-tally
 *
 * The DLL is never committed (.gitignore).
 */
#include "soa_mod.h"

#include <stdio.h>

static const SoaModApi* A;
static uint32_t g_won;

static void said(const char* what)
{
    char line[96];
    snprintf(line, sizeof line, "%s: %u battle(s) won in this save", what, g_won);
    A->log(line);
}

static void victory(void* user, SoaRewards* rewards)
{
    (void)user;
    (void)rewards; /* read only: the rewards stay as the game set them */
    g_won++;
    said("a victory");
}

static int32_t save(void* user, uint8_t* buf, uint32_t cap)
{
    (void)user;
    if (cap < 4) return -1;
    buf[0] = (uint8_t)(g_won >> 24);
    buf[1] = (uint8_t)(g_won >> 16);
    buf[2] = (uint8_t)(g_won >> 8);
    buf[3] = (uint8_t)g_won;
    return 4;
}

static void load(void* user, const uint8_t* data, uint32_t size)
{
    (void)user;
    /* none: a save from before the mod, or from the game alone */
    g_won = data && size == 4 ? (uint32_t)data[0] << 24 | (uint32_t)data[1] << 16 | (uint32_t)data[2] << 8 | data[3] : 0;
    said("loaded");
}

static void new_game(void* user)
{
    (void)user;
    g_won = 0;
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    A = api;
    if (api->size < SOA_MOD_HAS(on_new_game)) {
        api->log("this port has no save extension (X2): update it");
        return 1;
    }
    return api->on_rewards(victory, 0) && api->on_save(save, 0) && api->on_load(load, 0) &&
                   api->on_new_game(new_game, 0)
               ? 0
               : 1;
}
