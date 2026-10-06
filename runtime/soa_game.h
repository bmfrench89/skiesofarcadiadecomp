/*
 * The game library's one export (specs/android.md 3.2): what the runtime
 * needs from the translated code, in one table. tools/recompile.py writes
 * <out>/game_table.c, which fills it, into every build.
 *
 * A single-file build (soa.exe, gen/linux/soa) links the table and calls the
 * translated code directly; the self test holds the one to the other. A
 * split build (recompile.py --split: libsoa_runtime.so and libsoa_game.so,
 * Android's arrangement) reaches the game only through the table, which
 * runtime/game.c loads: <out>/runtime_seam.c gives the runtime forwarders
 * under the names it calls, and disc.c reads the system files from here.
 */
#ifndef SOA_GAME_H
#define SOA_GAME_H
#include "cpu.h"
#include <stddef.h>
#include <stdint.h>

#define SOA_GAME_ABI 1u

typedef void (*SoaFn)(CpuState* s);

typedef struct {
    uint32_t abi;  /* SOA_GAME_ABI */
    uint32_t size; /* sizeof(SoaGame) */
    const char* record; /* "abi=1 mode=... baked=... dol=... profile=...", as in the ELF note */
    SoaFn entry;        /* __start */
    void (*dispatch)(CpuState* s, uint32_t addr);
    int (*dispatch_known)(uint32_t addr);
    /* the player's system files (disc-layer I3) */
    const uint32_t *dol, *boot, *fst;
    const size_t *dol_size, *boot_size, *fst_size;
    const char *dol_sha1, *boot_sha1, *fst_sha1;
    /* the translated body at a guest address the self test runs, or NULL */
    SoaFn (*twin)(uint32_t addr);
} SoaGame;

#if defined(_MSC_VER)
#define SOA_GAME_EXPORT
#else
#define SOA_GAME_EXPORT __attribute__((visibility("default")))
#endif

/* <out>/game_table.c */
SOA_GAME_EXPORT const SoaGame* soa_game(void);

#ifdef SOA_SPLIT
/* runtime/game.c: the loaded library's table */
extern const SoaGame* soa_game_table;
#endif

#endif
