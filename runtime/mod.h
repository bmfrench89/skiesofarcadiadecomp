/* Mods, data patches only (docs/PLAN-60FPS-MODS.md M1). See mod.c. */
#ifndef SOA_MOD_H
#define SOA_MOD_H

#include "cpu.h"
#include "soa_mod.h"
#include "disc.h"
#include <stddef.h>

/* The mod API this port speaks: soa_mod.h's version, one constant, so the
 * manifest check and the DLL handshake cannot drift apart. Overridable only
 * so a test can build a port that speaks a later one and show that a
 * manifest's `api` is a minimum (test_mods.py). */
#ifndef MOD_API
#define MOD_API ((int)SOA_MOD_API_VERSION)
#endif

/* Load every mod under `dir` (a folder of mod folders), checking each against
 * the DOL the port booted. A mod with any fault is refused whole, out loud.
 * Returns how many loaded. */
int mod_load(CpuState* s, const char* dir, const uint8_t* dol, size_t dol_size);

/* T1's pass before the file table is parked (I6, docs/specs/disc-layer.md
 * §3.8.2): each mod's files.txt under `dir`, in load order, its sources read
 * into memory kept for the run. No mod code runs. A mod with a fault in its
 * mod.ini's DOL hash, its id or its files.txt is refused whole, said once,
 * and mod_load passes it over; so does one the build refuses (the ops'
 * `refused`). The lines, in *ops; how many. */
int mod_scan_files(const char* dir, const uint8_t* dol, size_t dol_size, DiscFileOp** ops);

/* R0: a damage the battle worked out, through every mod's on_damage in load
 * order; what the game gets, held to 0-9999 (runtime/battle.c calls it). */
uint32_t mod_damage(uint32_t value, uint32_t base, uint32_t attacker, uint32_t target, uint32_t element);

/* R1 (docs/specs/battle-events.md): the battle's other events, each through
 * every mod's callback in load order, from runtime/battle.c's wrappers.
 * mod_event_count says how many callbacks an event has: with none, a wrapper
 * reads and writes nothing. A fault inside one stops the run, exit 10,
 * naming the mod and the event. */
enum {
    MOD_EV_DAMAGE, MOD_EV_HEAL, MOD_EV_ENEMY_SPAWN, MOD_EV_ENEMY_ACTION, MOD_EV_TURN_ORDER, MOD_EV_SPIRIT_GAIN,
    MOD_EV_ESCAPE, MOD_EV_REWARDS, MOD_EV_EFFECT, MOD_EV_ROUND_END, MOD_EV_SHIP_DAMAGE,
    MOD_BATTLE_EVENTS,
    /* X2 (docs/specs/save-extension.md): the save's, from runtime/savext.c */
    MOD_EV_SAVE = MOD_BATTLE_EVENTS, MOD_EV_LOAD, MOD_EV_NEW_GAME,
    MOD_EVENTS
};
struct SoaRewards;
int mod_event_count(int ev);
uint32_t mod_heal(uint32_t value, int source, int target);       /* held to 0-9999 */
void mod_enemy_spawn(uint32_t actor, uint32_t record);
uint32_t mod_enemy_action(uint32_t type, int slot, uint32_t cmd);
void mod_turn_order(int8_t order[12]);
int32_t mod_spirit_gain(int32_t amount);
int mod_escape(int success, int slot);                           /* 0 or 1 */
void mod_rewards(struct SoaRewards* r);
int mod_effect(int target, int16_t* effect, int32_t* value);     /* 1: cancelled */
void mod_round_end(uint32_t round);
uint32_t mod_ship_damage(uint32_t value);                        /* held to 0 or more */

/* X2: the save's callbacks, one of each a mod at most, every one a mod with a
 * manifest 2 id. ev is MOD_EV_SAVE or MOD_EV_LOAD and i below
 * mod_event_count(ev): the mod's id; its chunk written into buf (bytes, or -1
 * for none); its chunk handed over (data NULL and size 0 for none). */
const char* mod_save_id(int ev, int i);
int32_t mod_save_call(int i, uint8_t* buf, uint32_t cap);
void mod_load_call(int i, const uint8_t* data, uint32_t size);
void mod_new_game(void);

/* Apply the loaded patches; called once a frame from the frame hook, after
 * SOA_PEEK and SOA_POKE. Memory writes only: it runs inside the XFB copy. */
void mod_frame(CpuState* s, unsigned frame);

/* "mods=dir:hash,..." for the pad recording's config line, "" with none. */
const char* mod_describe(void);

/* One line per patch: how often it was applied, and first at which frame. */
void mod_report(void);

/* M8's Mods page: the loaded mods, their declared options, and the ones
 * SOA_MOD_ORDER turned off (mod.c; docs/specs/menu.md). Read on the UI
 * thread; nothing here changes once mod_load has returned. */
typedef struct ModMenuOption {
    const char* name;
    int type; /* 0 int, 1 bool, 2 enum, 3 string, 4 seed */
    long long lo, hi;
    const char* choices; /* an enum's "a|b|c" */
    const char* value;   /* in effect this run */
    const char* def;
} ModMenuOption;
int mod_menu_count(void);
const char* mod_menu_name(int m, const char** key);
int mod_menu_option_count(int m);
int mod_menu_option(int m, int i, ModMenuOption* out);
int mod_menu_off_count(void);
const char* mod_menu_off_key(int i);

/* The DOL's code sections, noted whether or not a mod loads (main.c). */
void mod_note_dol(const uint8_t* dol, size_t dol_size);
void mod_set_host_buttons(uint32_t (*fn)(void)); /* CH1: si.c's host buttons, for the API */
void mod_set_pad_reader(int (*fn)(unsigned port, void* out)); /* P10a: si.c's pad 2, for the API */

/* Call the game's function at `addr` with every register put back after
 * (M4); 0 with the reason in `why` when refused. The API's call_guest adds
 * the safe-point and interrupt-handler checks. */
int mod_call_guest(CpuState* s, uint32_t addr, const uint32_t* ints, uint32_t n_ints, const double* floats,
                   uint32_t n_floats, uint32_t* r3, double* f1, char* why, size_t cap);

#endif
