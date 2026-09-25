/* Mods, data patches only (docs/PLAN-60FPS-MODS.md M1). See mod.c. */
#ifndef SOA_MOD_H
#define SOA_MOD_H

#include "cpu.h"
#include <stddef.h>

#define MOD_API 1

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

/* Call the game's function at `addr` with every register put back after
 * (M4); 0 with the reason in `why` when refused. The API's call_guest adds
 * the safe-point and interrupt-handler checks. */
int mod_call_guest(CpuState* s, uint32_t addr, const uint32_t* ints, uint32_t n_ints, const double* floats,
                   uint32_t n_floats, uint32_t* r3, double* f1, char* why, size_t cap);

#endif
