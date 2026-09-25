/* Mods, data patches only (docs/PLAN-60FPS-MODS.md M1). See mod.c. */
#ifndef SOA_MOD_H
#define SOA_MOD_H

#include "cpu.h"
#include "soa_mod.h"
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

/* Apply the loaded patches; called once a frame from the frame hook, after
 * SOA_PEEK and SOA_POKE. Memory writes only: it runs inside the XFB copy. */
void mod_frame(CpuState* s, unsigned frame);

/* "mods=dir:hash,..." for the pad recording's config line, "" with none. */
const char* mod_describe(void);

/* One line per patch: how often it was applied, and first at which frame. */
void mod_report(void);

/* The DOL's code sections, noted whether or not a mod loads (main.c). */
void mod_note_dol(const uint8_t* dol, size_t dol_size);
void mod_set_host_buttons(uint32_t (*fn)(void)); /* CH1: si.c's host buttons, for the API */

/* Call the game's function at `addr` with every register put back after
 * (M4); 0 with the reason in `why` when refused. The API's call_guest adds
 * the safe-point and interrupt-handler checks. */
int mod_call_guest(CpuState* s, uint32_t addr, const uint32_t* ints, uint32_t n_ints, const double* floats,
                   uint32_t n_floats, uint32_t* r3, double* f1, char* why, size_t cap);

#endif
