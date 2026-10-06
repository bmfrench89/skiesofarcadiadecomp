/*
 * The game library, found, checked and loaded (specs/android.md 3.3), in a
 * split build (tools/recompile.py --split; Android's arrangement on a
 * desktop): the launcher's main calls soa_run, which loads libsoa_game.so --
 * beside the launcher, or SOA_GAME -- holds it to runtime/elfcheck.c before
 * dlopen, takes its soa_game table, and runs main.c's main (soa_main).
 * <out>/runtime_seam.c, written by recompile.py, gives this side its record,
 * its export list and the forwarders through the table. A single-file build
 * compiles this file to nothing.
 *
 * runtime/game.h gives runtime/android.c the check and the load on their own
 * (L12d): a picked library is checked before it is copied, and loaded before
 * it replaces the one installed, and soa_run then runs the library already
 * loaded. One dlopen at most in a process: the system files' verdict
 * (disc_builtin) is kept for the process, and whatever a refused library's
 * load did stays done.
 */
#ifdef SOA_SPLIT
#include "soa_game.h"
#include "disc.h"
#include "elfcheck.h"
#include "game.h"
#include "plat.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const SoaGame* soa_game_table;
static int g_dlopened; /* dlopen has been called in this process */

/* <out>/runtime_seam.c */
extern const char soa_runtime_record[];
extern const char* const soa_runtime_exports[];
extern const unsigned soa_runtime_export_count;
extern const char* const soa_runtime_libc[];
extern const unsigned soa_runtime_libc_count;

int soa_main(int argc, char** argv); /* main.c's main */

static unsigned short host_machine(void)
{
#if defined(__aarch64__) || defined(_M_ARM64)
    return 183;
#else
    return 62;
#endif
}

int soa_check_game(const char* path, char* why, size_t cap)
{
    ElfWant w;
    w.machine = host_machine();
    w.exports = soa_runtime_exports;
    w.nexports = soa_runtime_export_count;
    w.libc = soa_runtime_libc;
    w.nlibc = soa_runtime_libc_count;
    w.record = soa_runtime_record;
    w.runtime_soname = "libsoa_runtime.so";
#ifdef __ANDROID__
    w.android = 1; /* bionic's C libraries by their own names: a Linux library is refused as one */
#else
    w.android = 0; /* a desktop split build's library needs glibc's, libc.so.6 */
#endif
    w.dol = disc_port_dol_sha1();
    return elf_check(path, &w, why, cap);
}

int soa_game_dlopened(void)
{
    return g_dlopened;
}

/* 0 with soa_game_table set; otherwise nonzero and why. */
int soa_load_game(const char* path, char* why, size_t cap)
{
    void* lib;
    const SoaGame* (*get)(void);
    const SoaGame* g;
    char err[600];
    if (g_dlopened) {
        snprintf(why, cap, "only one game library can be loaded in a run, and one already was: open the app again to use %s",
                 path);
        return 1;
    }
    if (soa_check_game(path, why, cap) != 0) return 1;
    g_dlopened = 1;
    lib = plat_dl_open(path, err, sizeof err);
    if (!lib) {
        snprintf(why, cap, "%s", err);
        return 1;
    }
    get = (const SoaGame* (*)(void))plat_dl_sym(lib, "soa_game");
    g = get ? get() : NULL;
    if (!g || g->abi != SOA_GAME_ABI || g->size < sizeof(SoaGame)) {
        snprintf(why, cap, "%s's table is not this app's (abi %u, the app's %u): rebuild it with this package's Setup", path,
                 g ? g->abi : 0u, SOA_GAME_ABI);
        plat_dl_close(lib);
        return 1;
    }
    /* disc_builtin reads the system files through the table, so they are
     * held to their SHA-1s only now: a library whose copies are damaged is
     * refused here, as the library it is, before it replaces the one
     * installed, rather than later as a disc that will not open. */
    soa_game_table = g;
    if (disc_builtin(err, sizeof err) < 0) {
        fprintf(stderr, "[game] %s: %s\n", path, err);
        snprintf(why, cap, "the system files built into this game library are damaged: rebuild it with Setup");
        soa_game_table = NULL;
        plat_dl_close(lib);
        return 1;
    }
    fprintf(stderr, "[game] %s: %s\n", path, g->record);
    return 0;
}

int soa_run(int argc, char** argv)
{
    char path[1100], why[700];
    const char* env = getenv("SOA_GAME");
    if (argc > 1 && (!strcmp(argv[1], "--help") || !strcmp(argv[1], "-h") || !strcmp(argv[1], "-?")))
        return soa_main(argc, argv);
    if (soa_game_table) return soa_main(argc, argv); /* runtime/android.c loaded it, at the import */
    if (env && *env) {
        snprintf(path, sizeof path, "%s", env);
    } else {
        char exe[1024];
        char* slash;
        if (!plat_exe_path(exe, sizeof exe)) {
            fprintf(stderr, "[game] cannot find this program's folder; set SOA_GAME to the game library\n");
            return 1;
        }
        slash = strrchr(exe, PLAT_SEP[0]);
        if (slash) *slash = '\0';
        snprintf(path, sizeof path, "%s" PLAT_SEP "libsoa_game%s", exe, PLAT_DL_SUFFIX);
    }
    if (soa_load_game(path, why, sizeof why) != 0) {
        fprintf(stderr, "[game] %s\n", why);
        return 1;
    }
    return soa_main(argc, argv);
}
#endif
