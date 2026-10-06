/*
 * The game library's loader (specs/android.md 3.3, L12d), for the runtime's
 * own files: runtime/game.c defines these in a split build, and
 * runtime/android.c calls them before soa_run when a player imports a library.
 * Not in soa_game.h, which the game library itself includes.
 */
#ifndef SOA_GAME_LOADER_H
#define SOA_GAME_LOADER_H
#include <stddef.h>

/* 0 when the library at `path` -- a file, or /proc/self/fd/N read through
 * its descriptor -- may be loaded by this runtime: runtime/elfcheck.c with
 * this runtime's exports, C library names and record, and the executable it
 * plays (disc_port_dol_sha1); otherwise nonzero and why, in the player's
 * words. Loads nothing. */
int soa_check_game(const char* path, char* why, size_t cap);

/* soa_check_game, then dlopen, the table held to this runtime's abi, and the
 * system files built into it held to their SHA-1s (disc_builtin): 0 with the
 * table in soa_game_table, or nonzero and why. A library is dlopened at most
 * once in a process: a second call after any dlopen is refused. */
int soa_load_game(const char* path, char* why, size_t cap);

/* 1 once any library has been dlopened in this process, accepted or not. */
int soa_game_dlopened(void);

#endif
