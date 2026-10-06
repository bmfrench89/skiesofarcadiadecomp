/*
 * A game library checked before it is loaded (specs/android.md 3.3): read
 * from the file's own headers, so a library built for another machine,
 * another page size or another build of the runtime is refused in words a
 * player can act on, rather than by dlopen's. ELF, 64-bit, little-endian:
 * Android and Linux on x86-64 and AArch64.
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
} ElfWant;

/* 0 when `path` may be loaded; otherwise nonzero and why, in the player's
 * words, in `why`. */
int elf_check(const char* path, const ElfWant* want, char* why, size_t cap);

/* The value of `key` in a record ("abi=1 mode=no-decomp baked=..."), into
 * out; 0 when the record has no such key. */
int elf_record_field(const char* record, const char* key, char* out, size_t cap);

#endif
