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
