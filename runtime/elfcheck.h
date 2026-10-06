/*
 * A game library checked before it is loaded (specs/android.md 3.3): read
 * from the file's own headers, so a library built for another machine,
 * another page size or another build of the runtime is refused in words a
 * player can act on, rather than by dlopen's. ELF, 64-bit, little-endian:
 * Android and Linux on x86-64 and AArch64. A Windows file is named as one,
 * since copying the wrong file over from the PC is the likeliest mistake.
 */
#ifndef SOA_ELFCHECK_H
#define SOA_ELFCHECK_H
#include <stddef.h>

typedef struct {
    unsigned short machine;       /* the host's: 62 x86-64, 183 AArch64 */
    const char* const* exports;   /* what a game import may name from the runtime */
    unsigned nexports;
    const char* const* libc;      /* and from the C library */
    unsigned nlibc;
    const char* record;           /* the runtime's: its abi, mode and baked must agree */
    const char* runtime_soname;   /* "libsoa_runtime.so" */
    int android;                  /* 1: the C libraries only by bionic's names, libc.so, libm.so and libdl.so,
                                   * so a Linux library (libc.so.6) is refused as one; 0: any version after them */
    const char* dol;              /* 40 hex, the executable this runtime plays: the record's dol= must equal
                                   * it; NULL or "" holds the record to none */
} ElfWant;

/* 0 when `path` may be loaded; otherwise nonzero and why, in the player's
 * words, in `why`. A /proc/self/fd/N path is read through descriptor N. */
int elf_check(const char* path, const ElfWant* want, char* why, size_t cap);

/* The value of `key` in a record ("abi=1 mode=no-decomp baked=..."), its
 * fields apart by spaces alone, into out, cut to fit; 0 when the record has
 * no such key. tools/soa/elfcheck.py's _field reads a record the same way. */
int elf_record_field(const char* record, const char* key, char* out, size_t cap);

#endif
