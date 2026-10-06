/*
 * The game library's checks before dlopen (specs/android.md 3.3): the
 * machine, a shared object, 16 KB pages, no text relocations, the libraries
 * it needs, the build record in its .note.soa, every symbol it imports, and
 * its one export. Portable C over the file's bytes, so it compiles in every
 * build; only a split build (runtime/game.c) and the tests call it.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "elfcheck.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    ET_DYN = 3,
    PT_LOAD = 1,
    SHT_DYNAMIC = 6,
    SHT_DYNSYM = 11,
    DT_NEEDED = 1,
    DT_TEXTREL = 22,
    DT_FLAGS = 30,
    DF_TEXTREL = 4,
    STB_WEAK = 2,
    MIN_ALIGN = 16384
};

typedef struct {
    FILE* f;
    long size;
} Elf;

static uint16_t u16(const uint8_t* p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t u32(const uint8_t* p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t u64(const uint8_t* p) { return (uint64_t)u32(p) | (uint64_t)u32(p + 4) << 32; }

/* `n` bytes at `off`, or NULL when they are not all in the file. */
static uint8_t* read_at(Elf* e, uint64_t off, uint64_t n)
{
    uint8_t* b;
    if (off > (uint64_t)e->size || n > (uint64_t)e->size - off || n > (64u << 20)) return NULL;
    b = (uint8_t*)malloc(n ? (size_t)n : 1);
    if (!b) return NULL;
    if (fseek(e->f, (long)off, SEEK_SET) != 0 || fread(b, 1, (size_t)n, e->f) != (size_t)n) {
        free(b);
        return NULL;
    }
    return b;
}

static const char* machine_name(unsigned m)
{
    switch (m) {
    case 3: return "32-bit x86";
    case 40: return "32-bit ARM";
    case 62: return "x86-64";
    case 183: return "64-bit ARM (AArch64)";
    default: return "another machine";
    }
}

int elf_record_field(const char* record, const char* key, char* out, size_t cap)
{
    size_t k = strlen(key);
    const char* p = record;
    while (p && *p) {
        while (*p == ' ') p++;
        if (!strncmp(p, key, k) && p[k] == '=') {
            size_t n = strcspn(p + k + 1, " ");
            if (n >= cap) n = cap - 1;
            memcpy(out, p + k + 1, n);
            out[n] = '\0';
            return 1;
        }
        p = strchr(p, ' ');
    }
    return 0;
}

static int listed(const char* name, const char* const* list, unsigned n)
{
    unsigned i;
    for (i = 0; i < n; i++)
        if (!strcmp(name, list[i])) return 1;
    return 0;
}

/* A C library the game may need: libc, libm or libdl, any version suffix. */
static int c_library(const char* name)
{
    static const char* const ok[] = {"libc.so", "libm.so", "libdl.so"};
    unsigned i;
    for (i = 0; i < 3; i++) {
        size_t n = strlen(ok[i]);
        if (!strncmp(name, ok[i], n) && (name[n] == '\0' || name[n] == '.')) return 1;
    }
    return 0;
}

/* The record in a .note.soa section's bytes: name "SOA", the record as its
 * description. */
static int note_record(const uint8_t* b, uint64_t n, char* out, size_t cap)
{
    uint64_t at = 0;
    while (at + 12 <= n) {
        uint32_t namesz = u32(b + at), descsz = u32(b + at + 4);
        uint64_t name = at + 12, desc = name + ((namesz + 3u) & ~3u);
        if (desc + descsz > n) return 0;
        if (namesz == 4 && !memcmp(b + name, "SOA", 4)) {
            size_t len = 0;
            while (len < descsz && b[desc + len]) len++;
            if (len >= cap) len = cap - 1;
            memcpy(out, b + desc, len);
            out[len] = '\0';
            return 1;
        }
        at = desc + ((descsz + 3u) & ~3u);
    }
    return 0;
}

static int check(Elf* e, const char* path, const ElfWant* w, char* why, size_t cap)
{
    uint8_t h[64];
    uint8_t *ph = NULL, *sh = NULL, *shstr = NULL, *dyn = NULL, *sym = NULL, *str = NULL, *note = NULL;
    uint64_t phoff, shoff, dynsz = 0, symsz = 0, strsz = 0, notesz = 0;
    unsigned phnum, shnum, shstrndx, i, machine;
    int needs_runtime = 0, has_table = 0, rc = 1;
    char record[512], mine[128], theirs[128];
    const char* keys[] = {"abi", "mode", "baked"};

    if (fread(h, 1, 64, e->f) != 64 || memcmp(h, "\177ELF", 4) != 0) {
        snprintf(why, cap, "%s is not a library for this system", path);
        return 1;
    }
    if (h[4] != 2 || h[5] != 1) {
        snprintf(why, cap, "%s is not a 64-bit library for this system", path);
        return 1;
    }
    machine = u16(h + 18);
    if (machine != w->machine) {
        snprintf(why, cap, "this library was built for %s, not this device (%s): rebuild it for this device with Setup",
                 machine_name(machine), machine_name(w->machine));
        return 1;
    }
    if (u16(h + 16) != ET_DYN) {
        snprintf(why, cap, "%s is a program, not a game library", path);
        return 1;
    }
    phoff = u64(h + 32);
    shoff = u64(h + 40);
    phnum = u16(h + 56);
    shnum = u16(h + 60);
    shstrndx = u16(h + 62);
    if (u16(h + 54) != 56 || u16(h + 58) != 64 || !(ph = read_at(e, phoff, (uint64_t)phnum * 56)) ||
        !(sh = read_at(e, shoff, (uint64_t)shnum * 64)) || shstrndx >= shnum) {
        snprintf(why, cap, "%s is damaged: its headers are not where it says", path);
        goto done;
    }
    for (i = 0; i < phnum; i++) {
        const uint8_t* p = ph + (size_t)i * 56;
        if (u32(p) == PT_LOAD && u64(p + 48) < MIN_ALIGN) {
            snprintf(why, cap, "this library was built for %llu-byte pages, and devices may use 16 KB ones: rebuild it with this "
                               "package's Setup", (unsigned long long)u64(p + 48));
            goto done;
        }
    }
    shstr = read_at(e, u64(sh + (size_t)shstrndx * 64 + 24), u64(sh + (size_t)shstrndx * 64 + 32));
    for (i = 0; i < shnum && shstr; i++) {
        const uint8_t* s = sh + (size_t)i * 64;
        uint32_t type = u32(s + 4), name = u32(s);
        uint64_t off = u64(s + 24), size = u64(s + 32);
        if (type == SHT_DYNAMIC && !dyn) {
            dyn = read_at(e, off, size);
            dynsz = size;
        } else if (type == SHT_DYNSYM && !sym) {
            uint32_t link = u32(s + 40);
            sym = read_at(e, off, size);
            symsz = size;
            if (link < shnum) {
                strsz = u64(sh + (size_t)link * 64 + 32);
                str = read_at(e, u64(sh + (size_t)link * 64 + 24), strsz);
            }
        } else if (name < u64(sh + (size_t)shstrndx * 64 + 32) && !strcmp((const char*)shstr + name, ".note.soa")) {
            note = read_at(e, off, size);
            notesz = size;
        }
    }
    if (!dyn || !sym || !str || strsz == 0 || str[strsz - 1] != '\0') {
        snprintf(why, cap, "%s has no dynamic symbols: it is not a library this package built", path);
        goto done;
    }
    for (i = 0; i + 16 <= dynsz; i += 16) {
        uint64_t tag = u64(dyn + i), val = u64(dyn + i + 8);
        if (tag == 0) break;
        if (tag == DT_TEXTREL || (tag == DT_FLAGS && (val & DF_TEXTREL))) {
            snprintf(why, cap, "this library has text relocations, which Android refuses to load: rebuild it with this package");
            goto done;
        }
        if (tag == DT_NEEDED) {
            const char* name = val < strsz ? (const char*)str + val : "";
            if (!strcmp(name, w->runtime_soname)) needs_runtime = 1;
            else if (!c_library(name)) {
                snprintf(why, cap, "this library needs %s, which this app does not have: rebuild it with this package", name);
                goto done;
            }
        }
    }
    if (!needs_runtime) {
        snprintf(why, cap, "this library was not built against this app's runtime (it does not need %s): rebuild it with "
                           "this package", w->runtime_soname);
        goto done;
    }
    if (!note || !note_record(note, notesz, record, sizeof record)) {
        snprintf(why, cap, "this library carries no build record: it was not made by this package's Setup");
        goto done;
    }
    for (i = 0; i < 3; i++) {
        if (!elf_record_field(record, keys[i], theirs, sizeof theirs)) theirs[0] = '\0';
        if (!elf_record_field(w->record, keys[i], mine, sizeof mine)) mine[0] = '\0';
        if (strcmp(mine, theirs) != 0) {
            snprintf(why, cap, "this library was built from other sources than this app (its %s is %s, the app's %s): "
                               "rebuild it with this package's Setup", keys[i], theirs[0] ? theirs : "missing", mine);
            goto done;
        }
    }
    for (i = 0; i + 24 <= symsz; i += 24) {
        const uint8_t* s = sym + i;
        uint32_t name = u32(s);
        const char* n = name < strsz ? (const char*)str + name : "";
        uint16_t shndx = u16(s + 6);
        if (!*n) continue;
        if (shndx != 0) {
            if (!strcmp(n, "soa_game")) has_table = 1;
            continue;
        }
        if ((s[4] >> 4) == STB_WEAK) continue; /* an optional import: absent is fine */
        if (!listed(n, w->exports, w->nexports) && !listed(n, w->libc, w->nlibc)) {
            snprintf(why, cap, "this library needs %s, which this app's runtime does not have: rebuild it with this "
                               "package's Setup", n);
            goto done;
        }
    }
    if (!has_table) {
        snprintf(why, cap, "%s has no soa_game table: it is not a game library", path);
        goto done;
    }
    rc = 0;
done:
    free(ph);
    free(sh);
    free(shstr);
    free(dyn);
    free(sym);
    free(str);
    free(note);
    return rc;
}

int elf_check(const char* path, const ElfWant* want, char* why, size_t cap)
{
    Elf e;
    int rc;
    e.f = fopen(path, "rb");
    if (!e.f) {
        snprintf(why, cap, "cannot open %s", path);
        return 1;
    }
    if (fseek(e.f, 0, SEEK_END) != 0 || (e.size = ftell(e.f)) < 64 || fseek(e.f, 0, SEEK_SET) != 0) {
        fclose(e.f);
        snprintf(why, cap, "%s is not a library for this system", path);
        return 1;
    }
    rc = check(&e, path, want, why, cap);
    fclose(e.f);
    return rc;
}
