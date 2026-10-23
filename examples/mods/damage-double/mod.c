/*
 * An example native mod for R0's damage event (docs/specs/battle-harness.md):
 * every damage the battle works out, doubled, at most 9999. It is the check
 * R0's log proves itself on -- SOA_BATTLE_LOG=1 prints each call's original
 * and what it returned, and `python tools/battle.py check <log> --double`
 * holds every one to min(2 x original, 9999).
 *
 * Build it beside its mod.ini, from the repository root:
 *
 *     cl /LD /O2 /I runtime examples\mods\damage-double\mod.c /Fe:examples\mods\damage-double\mod.dll
 *
 * The DLL is never committed (.gitignore).
 */
#include "soa_mod.h"

static uint32_t doubled(void* user, uint32_t value, uint32_t base, uint32_t attacker, uint32_t target, uint32_t element)
{
    (void)user;
    (void)base;
    (void)attacker;
    (void)target;
    (void)element;
    return value > 4999 ? 9999 : value * 2;
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    if (api->size < SOA_MOD_HAS(on_damage)) {
        api->log("this port has no on_damage (R0); nothing doubled");
        return 1;
    }
    return api->on_damage(doubled, 0) ? 0 : 1;
}
