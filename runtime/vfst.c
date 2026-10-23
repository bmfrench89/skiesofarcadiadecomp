/*
 * T1's virtual disc, its core (I6, docs/specs/disc-layer.md §3.8): mods'
 * `files.txt` lines -- replace, add, alias -- turned into a rebuilt file
 * table and the extents the drive serves past the image's end.
 *
 * The rebuild walks the base table's own tree in its own order, emitting each
 * directory's entries, then the files mods add to it, then its end index; the
 * base's string table is kept verbatim and new names appended. So an empty
 * overlay gives the base back byte for byte, a replace changes exactly two
 * words, and an add or alias moves only the entries after it. The result is
 * checked before anyone parks it: every path resolved through a twin of the
 * SDK's linear walk (DVDConvertPathToEntrynum, 0x8023A4B0) to where it
 * should be.
 *
 * Virtual extents start at 0x57060000, the image's end plus 32 KiB, each
 * 32 KiB-aligned with 32 KiB between, in mod and line order, and end below
 * 2 GiB (§3.8.4). Their bytes are the mods' own, in host memory the caller
 * keeps for the run.
 */
#include "disc.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ENTRY 12
#define ALIGN (32u * 1024u)
#define MEM_CAP (256u << 20) /* every mod's sources together (§3.8.1) */
#define SOURCE_CAP (16u << 20)
#define HEAP4_WARN 3750000u  /* heap 4's largest free block, measured (beyond-gamecube.md §4) */
#define NAME_MAX_DISC 256

typedef struct {
    uint64_t off;
    uint32_t size;
    const uint8_t* data;
    char path[NAME_MAX_DISC];
} VExtent;

static VExtent* g_vx;
static int g_vx_n;
static unsigned long long g_vx_reads, g_vx_bytes;

static uint32_t be32(const uint8_t* p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static void put32(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

/* ---- the table as entries ------------------------------------------------- */

typedef struct {
    uint8_t dir;
    uint32_t name;    /* offset into the string table */
    uint32_t a, b;    /* file: offset, length; directory: parent, next */
    int add_dir;      /* an added file: the base directory it goes in */
    uint32_t new_idx; /* in the rebuilt table */
} Ent;

typedef struct {
    const uint8_t* fst;
    size_t n;
    uint32_t count, strtab;
    Ent* e;      /* base entries, then added ones */
    uint32_t ne, cap;
    char* str;   /* the string table, base verbatim, then new names */
    size_t str_n, str_cap;
} Table;

static const char* name_of(const Table* t, uint32_t i) { return t->str + t->e[i].name; }

static int parse(Table* t, const uint8_t* fst, size_t n, char* why, size_t cap)
{
    uint32_t i;
    memset(t, 0, sizeof *t);
    t->fst = fst;
    t->n = n;
    if (n < ENTRY || !fst[0]) { snprintf(why, cap, "the file table's root is not a directory"); return 0; }
    t->count = be32(fst + 8);
    if (t->count == 0 || (size_t)t->count * ENTRY > n) { snprintf(why, cap, "the file table's count is %u", t->count); return 0; }
    t->strtab = t->count * ENTRY;
    t->cap = t->count + 64;
    t->e = (Ent*)calloc(t->cap, sizeof *t->e);
    t->str_cap = n - t->strtab + 4096;
    t->str = (char*)malloc(t->str_cap);
    if (!t->e || !t->str) { snprintf(why, cap, "out of memory"); return 0; }
    t->str_n = n - t->strtab;
    memcpy(t->str, fst + t->strtab, t->str_n);
    for (i = 0; i < t->count; i++) {
        const uint8_t* p = fst + (size_t)i * ENTRY;
        Ent* x = &t->e[i];
        x->dir = p[0] ? 1 : 0;
        x->name = (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
        x->a = be32(p + 4);
        x->b = be32(p + 8);
        x->add_dir = -1;
        if (i && (x->name >= t->str_n || !memchr(t->str + x->name, 0, t->str_n - x->name))) {
            snprintf(why, cap, "entry %u's name runs off the string table", i);
            return 0;
        }
        if (x->dir && i && (x->b <= i || x->b > t->count)) { snprintf(why, cap, "directory %u's range is broken", i); return 0; }
    }
    t->ne = t->count;
    return 1;
}

static void drop(Table* t)
{
    free(t->e);
    free(t->str);
    memset(t, 0, sizeof *t);
}

static int ieq(const char* a, const char* b, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        if (tolower((unsigned char)a[i]) != tolower((unsigned char)b[i])) return 0;
    return 1;
}

/* The SDK's walk over base entries [0, count): from the root, each
 * component matched case-insensitively among a directory's own entries,
 * subdirectories' ranges skipped. The entry, or -1. With `dir_only` the last
 * component must be a directory; `""` is the root. */
static int walk(const Table* t, const char* path)
{
    uint32_t d = 0;
    const char* s = path;
    if (!*s) return 0;
    for (;;) {
        const char* slash = strchr(s, '/');
        size_t len = slash ? (size_t)(slash - s) : strlen(s);
        uint32_t i = d + 1, end = d == 0 ? t->count : t->e[d].b;
        int found = -1;
        while (i < end) {
            const char* nm = name_of(t, i);
            if (strlen(nm) == len && ieq(nm, s, len)) { found = (int)i; break; }
            i = t->e[i].dir ? t->e[i].b : i + 1;
        }
        if (found < 0) return -1;
        if (!slash) return found;
        if (!t->e[found].dir) return -1;
        d = (uint32_t)found;
        s = slash + 1;
    }
}

/* An added entry (index >= count) with this path, or -1. */
static int added(const Table* t, const char* path)
{
    uint32_t i;
    for (i = t->count; i < t->ne; i++) {
        char full[NAME_MAX_DISC * 2];
        const char* dirname = t->e[i].add_dir > 0 ? NULL : "";
        size_t used = 0;
        if (t->e[i].add_dir > 0) { /* rebuild the directory's path */
            int chain[32], depth = 0, d = t->e[i].add_dir, k;
            while (d > 0 && depth < 32) {
                chain[depth++] = d;
                d = (int)t->e[d].a;
            }
            for (k = depth - 1; k >= 0; k--)
                used += (size_t)snprintf(full + used, sizeof full - used, "%s/", name_of(t, (uint32_t)chain[k]));
        }
        (void)dirname;
        snprintf(full + used, sizeof full - used, "%s", name_of(t, i));
        if (strlen(full) == strlen(path) && ieq(full, path, strlen(path))) return (int)i;
    }
    return -1;
}

static int find(const Table* t, const char* path)
{
    int i = walk(t, path);
    return i >= 0 ? i : added(t, path);
}

static uint32_t add_name(Table* t, const char* name)
{
    size_t len = strlen(name) + 1;
    uint32_t at = (uint32_t)t->str_n;
    if (t->str_n + len > t->str_cap) {
        size_t c = (t->str_cap + len) * 2;
        char* more = (char*)realloc(t->str, c);
        if (!more) return 0xFFFFFFFFu;
        t->str = more;
        t->str_cap = c;
    }
    memcpy(t->str + t->str_n, name, len);
    t->str_n += len;
    return at;
}

static int add_entry(Table* t, int dir, const char* name, uint32_t off, uint32_t len)
{
    uint32_t nm = add_name(t, name);
    Ent* x;
    if (nm == 0xFFFFFFFFu) return -1;
    if (t->ne == t->cap) {
        Ent* more = (Ent*)realloc(t->e, (size_t)t->cap * 2 * sizeof *more);
        if (!more) return -1;
        t->e = more;
        t->cap *= 2;
    }
    x = &t->e[t->ne];
    memset(x, 0, sizeof *x);
    x->name = nm;
    x->a = off;
    x->b = len;
    x->add_dir = dir;
    return (int)t->ne++;
}

/* ---- the rebuilt table ------------------------------------------------------ */

typedef struct {
    uint8_t* out;
    uint32_t n;
} Emit;

static void emit_entry(const Table* t, Emit* m, uint32_t i, uint32_t a, uint32_t b)
{
    uint8_t* p = m->out + (size_t)m->n * ENTRY;
    p[0] = t->e[i].dir;
    p[1] = (uint8_t)(t->e[i].name >> 16);
    p[2] = (uint8_t)(t->e[i].name >> 8);
    p[3] = (uint8_t)t->e[i].name;
    put32(p + 4, a);
    put32(p + 8, b);
    m->n++;
}

/* Directory d (a base entry), its own entries in base order, then the files
 * added to it; the new index of its parent given. */
static void emit_dir(Table* t, Emit* m, uint32_t d, uint32_t parent_new)
{
    uint32_t me = m->n, i, end = d == 0 ? t->count : t->e[d].b;
    t->e[d].new_idx = me;
    emit_entry(t, m, d, d == 0 ? 0 : parent_new, 0); /* next written below */
    i = d + 1;
    while (i < end) {
        if (t->e[i].dir) {
            emit_dir(t, m, i, me);
            i = t->e[i].b;
        } else {
            t->e[i].new_idx = m->n;
            emit_entry(t, m, i, t->e[i].a, t->e[i].b);
            i++;
        }
    }
    for (i = t->count; i < t->ne; i++)
        if ((uint32_t)t->e[i].add_dir == d) {
            t->e[i].new_idx = m->n;
            emit_entry(t, m, i, t->e[i].a, t->e[i].b);
        }
    put32(m->out + (size_t)me * ENTRY + 8, m->n);
}

static int serialise(Table* t, uint8_t** out, size_t* out_n)
{
    size_t bytes = (size_t)t->ne * ENTRY + t->str_n;
    Emit m;
    m.out = (uint8_t*)malloc(bytes);
    m.n = 0;
    if (!m.out) return 0;
    emit_dir(t, &m, 0, 0);
    memcpy(m.out + (size_t)t->ne * ENTRY, t->str, t->str_n);
    *out = m.out;
    *out_n = bytes;
    return m.n == t->ne;
}

/* ---- the build ---------------------------------------------------------------- */

static void say_refused(const DiscFileOp* op, const char* fmt, const char* a, const char* b)
{
    char msg[600];
    snprintf(msg, sizeof msg, fmt, a, b);
    fprintf(stderr, "[mod] %s/files.txt:%u: %s; the mod is not loaded\n", op->mod, op->line, msg);
}

static int valid_path(const char* p)
{
    size_t n = strlen(p), i;
    const char* s = p;
    if (!n || n > 255 || p[0] == '/' || p[n - 1] == '/') return 0;
    for (i = 0; i < n; i++)
        if (p[i] < 0x21 || p[i] > 0x7E || p[i] == '\\') return 0;
    while (*s) { /* no empty, . or .. component */
        const char* slash = strchr(s, '/');
        size_t len = slash ? (size_t)(slash - s) : strlen(s);
        if (len == 0 || (len == 1 && s[0] == '.') || (len == 2 && s[0] == '.' && s[1] == '.')) return 0;
        if (!slash) break;
        s = slash + 1;
    }
    return 1;
}

/* Who named a path first, for the collision message. */
typedef struct {
    char path[NAME_MAX_DISC];
    const DiscFileOp* op;
} Claim;

/* One attempt at the whole build, skipping refused mods. 1 built, 2 a mod
 * was refused (marked; build again without it), -1 two mods collide, 0 an
 * error in `why`. */
static int build_pass(Table* t, DiscFileOp* ops, int nops, char* why, size_t cap)
{
    Claim* claims = (Claim*)calloc((size_t)nops + 1, sizeof *claims);
    int nclaims = 0, k, c, phase, result = 1;
    uint64_t cursor = DISC_OVERLAY_BASE;
    size_t mem = 0;
    g_vx_n = 0;
    if (!claims) { snprintf(why, cap, "out of memory"); return 0; }
    /* Phase 1 (replace, add) for every mod, then phase 2 (alias), so an alias
     * reads a replacement whatever order the mods come in. */
    for (phase = 1; phase <= 2 && result == 1; phase++) {
        for (k = 0; k < nops && result == 1; k++) {
            DiscFileOp* op = &ops[k];
            const char* slash;
            char dir[NAME_MAX_DISC];
            int at, d;
            if (op->refused || (phase == 1) != (op->verb != DISC_ALIAS)) continue;
            if (!valid_path(op->path)) {
                say_refused(op, "`%s` is not a disc path: forward slashes, no leading slash, no . or .., printable "
                                "ASCII, at most 255 characters%s", op->path, "");
                goto refuse;
            }
            for (c = 0; c < nclaims; c++)
                if (strlen(claims[c].path) == strlen(op->path) && ieq(claims[c].path, op->path, strlen(op->path))) break;
            if (c < nclaims) {
                if (claims[c].op->mod_index == op->mod_index) {
                    char other[16];
                    snprintf(other, sizeof other, "%u", claims[c].op->line);
                    say_refused(op, "%s is named twice in this files.txt (line %s too)", op->path, other);
                    goto refuse;
                }
                fprintf(stderr,
                        "[mod] two mods place %s: %s/files.txt:%u and %s/files.txt:%u; remove one (an `overrides` "
                        "declaration is the planned way to let one win)\n",
                        op->path, claims[c].op->mod, claims[c].op->line, op->mod, op->line);
                snprintf(why, cap, "two mods place %s", op->path);
                result = -1;
                break;
            }
            slash = strrchr(op->path, '/');
            snprintf(dir, sizeof dir, "%.*s", slash ? (int)(slash - op->path) : 0, op->path);
            if (op->verb == DISC_REPLACE || op->verb == DISC_ADD) {
                VExtent* v;
                if (op->size > SOURCE_CAP) {
                    say_refused(op, "%s's source is over 16 MiB%s", op->path, "");
                    goto refuse;
                }
                if (mem + op->size > MEM_CAP) {
                    char total[32];
                    snprintf(total, sizeof total, "%llu", (unsigned long long)(mem + op->size));
                    say_refused(op, "every mod's files together would take %s bytes, past the 256 MiB the overlay "
                                    "holds%s", total, "");
                    goto refuse;
                }
                if (cursor + op->size > DISC_OVERLAY_END) {
                    say_refused(op, "%s would end past 2 GiB on the disc, which the game's reads may not reach%s",
                                op->path, "");
                    goto refuse;
                }
                if (op->verb == DISC_REPLACE) {
                    at = walk(t, op->path);
                    if (at < 0 || t->e[at].dir) {
                        say_refused(op, "replace %s: no such file on the disc%s", op->path, "");
                        goto refuse;
                    }
                    t->e[at].a = (uint32_t)cursor;
                    t->e[at].b = op->size;
                } else {
                    if (find(t, op->path) >= 0) {
                        say_refused(op, "add %s: it is on the disc already (replace it, or add another name)%s",
                                    op->path, "");
                        goto refuse;
                    }
                    d = walk(t, dir);
                    if (d < 0 || !t->e[d].dir) {
                        say_refused(op, "add %s: its directory is not on the disc, and a mod adds no directories%s",
                                    op->path, "");
                        goto refuse;
                    }
                    if (add_entry(t, d, slash ? slash + 1 : op->path, (uint32_t)cursor, op->size) < 0) {
                        snprintf(why, cap, "out of memory");
                        result = 0;
                        break;
                    }
                }
                if (op->size > HEAP4_WARN && !op->warned) {
                    op->warned = 1;
                    fprintf(stderr, "[mod] %s/files.txt:%u: %s is %u bytes, more than heap 4's largest free block "
                                    "(about 3.75 MB); the game may not find room for it\n",
                            op->mod, op->line, op->path, op->size);
                }
                v = &g_vx[g_vx_n++];
                v->off = cursor;
                v->size = op->size;
                v->data = op->data;
                snprintf(v->path, sizeof v->path, "%s", op->path);
                op->offset = (uint32_t)cursor;
                mem += op->size;
                cursor = (cursor + op->size + ALIGN - 1) / ALIGN * ALIGN + ALIGN;
            } else { /* alias */
                int target, j;
                if (find(t, op->path) >= 0) {
                    say_refused(op, "alias %s: that name is on the disc already%s", op->path, "");
                    goto refuse;
                }
                for (j = 0; j < nops; j++)
                    if (j != k && ops[j].verb == DISC_ALIAS && !ops[j].refused &&
                        strlen(ops[j].path) == strlen(op->target) && ieq(ops[j].path, op->target, strlen(op->target)))
                        break;
                if (j < nops) {
                    say_refused(op, "alias %s: its target, %s, is itself an alias", op->path, op->target);
                    goto refuse;
                }
                target = find(t, op->target);
                if (target < 0 || t->e[target].dir) {
                    say_refused(op, "alias %s: its target, %s, is not a file on the disc or one a mod adds", op->path,
                                op->target);
                    goto refuse;
                }
                d = walk(t, dir);
                if (d < 0 || !t->e[d].dir) {
                    say_refused(op, "alias %s: its directory is not on the disc%s", op->path, "");
                    goto refuse;
                }
                for (c = 0; c < nclaims; c++) /* a base file another mod replaced: the alias reads the replacement */
                    if (claims[c].op->verb == DISC_REPLACE && claims[c].op->mod_index != op->mod_index &&
                        strlen(claims[c].path) == strlen(op->target) &&
                        ieq(claims[c].path, op->target, strlen(op->target)) && !op->warned) {
                        op->warned = 1;
                        fprintf(stderr, "[mod] %s's alias %s reads %s's replacement of %s\n", op->mod, op->path,
                                claims[c].op->mod, op->target);
                    }
                if (add_entry(t, d, slash ? slash + 1 : op->path, t->e[target].a, t->e[target].b) < 0) {
                    snprintf(why, cap, "out of memory");
                    result = 0;
                    break;
                }
                op->offset = t->e[target].a;
                op->size = t->e[target].b;
            }
            snprintf(claims[nclaims].path, sizeof claims[0].path, "%s", op->path);
            claims[nclaims++].op = op;
            continue;
        refuse: /* the whole mod, and build again without it */
            for (c = 0; c < nops; c++)
                if (ops[c].mod_index == op->mod_index) ops[c].refused = 1;
            result = 2;
        }
    }
    free(claims);
    return result;
}

int disc_overlay_build(const uint8_t* fst, size_t fst_n, DiscFileOp* ops, int nops, uint8_t** out, size_t* out_n,
                       char* why, size_t cap)
{
    Table t;
    int r;
    *out = NULL;
    *out_n = 0;
    if (why && cap) why[0] = '\0';
    disc_overlay_reset();
    g_vx = (VExtent*)calloc((size_t)nops + 1, sizeof *g_vx);
    if (!g_vx) { snprintf(why, cap, "out of memory"); return 0; }
    /* A refused mod leaves nothing behind: the build runs again without it,
     * and the refused set only grows, so this ends. */
    do {
        if (!parse(&t, fst, fst_n, why, cap)) return 0;
        r = build_pass(&t, ops, nops, why, cap);
        if (r != 1) drop(&t);
    } while (r == 2);
    if (r != 1) {
        g_vx_n = 0;
        return r;
    }
    if (!serialise(&t, out, out_n)) {
        snprintf(why, cap, "the rebuilt file table did not come out whole");
        drop(&t);
        g_vx_n = 0;
        return 0;
    }
    drop(&t);
    /* Checked before anyone parks it: every base path where it was, or where
     * its replacement is; every added or aliased path where it should be. */
    if (!disc_overlay_check(fst, fst_n, *out, *out_n, ops, nops, why, cap)) {
        free(*out);
        *out = NULL;
        g_vx_n = 0;
        return 0;
    }
    return 1;
}

int disc_overlay_check(const uint8_t* base, size_t base_n, const uint8_t* fst, size_t n, const DiscFileOp* ops,
                       int nops, char* why, size_t cap)
{
    Table b, r;
    uint32_t i, added_n = 0;
    int k, ok = 1;
    if (!parse(&b, base, base_n, why, cap)) return 0;
    if (!parse(&r, fst, n, why, cap)) { drop(&b); return 0; }
    for (k = 0; k < nops; k++)
        if (!ops[k].refused && ops[k].verb != DISC_REPLACE) added_n++;
    if (r.count != b.count + added_n) {
        snprintf(why, cap, "the rebuilt table has %u entries, not %u", r.count, b.count + added_n);
        ok = 0;
    }
    /* every base file by its path, through the twin of the SDK's walk */
    for (i = 1; ok && i < b.count; i++) {
        char path[NAME_MAX_DISC * 2];
        uint32_t chain[32], depth = 0, d, j;
        size_t used = 0;
        int at, replaced = -1;
        if (b.e[i].dir) continue;
        for (d = 0; d < i;) { /* the directories holding i, from the root */
            uint32_t end = d == 0 ? b.count : b.e[d].b, x = d + 1, next = 0;
            while (x < end && x <= i) {
                if (b.e[x].dir && i < b.e[x].b && x < i) { next = x; break; }
                x = b.e[x].dir ? b.e[x].b : x + 1;
            }
            if (!next) break;
            chain[depth++] = next;
            d = next;
        }
        for (j = 0; j < depth; j++) used += (size_t)snprintf(path + used, sizeof path - used, "%s/", name_of(&b, chain[j]));
        snprintf(path + used, sizeof path - used, "%s", name_of(&b, i));
        at = walk(&r, path);
        for (k = 0; k < nops; k++)
            if (!ops[k].refused && ops[k].verb == DISC_REPLACE && strlen(ops[k].path) == strlen(path) &&
                ieq(ops[k].path, path, strlen(path)))
                replaced = k;
        if (at < 0) {
            snprintf(why, cap, "%s no longer resolves in the rebuilt table", path);
            ok = 0;
        } else if (replaced >= 0 ? (r.e[at].a != ops[replaced].offset || r.e[at].b != ops[replaced].size)
                                 : (r.e[at].a != b.e[i].a || r.e[at].b != b.e[i].b)) {
            snprintf(why, cap, "%s resolves to 0x%08X +%u in the rebuilt table, not where it should", path, r.e[at].a, r.e[at].b);
            ok = 0;
        }
    }
    for (k = 0; ok && k < nops; k++) {
        int at;
        if (ops[k].refused || ops[k].verb == DISC_REPLACE) continue;
        at = walk(&r, ops[k].path);
        if (at < 0 || r.e[at].a != ops[k].offset) {
            snprintf(why, cap, "%s, which a mod places, does not resolve to it in the rebuilt table", ops[k].path);
            ok = 0;
        }
    }
    drop(&b);
    drop(&r);
    return ok;
}

/* ---- serving ------------------------------------------------------------------ */

uint32_t disc_overlay_read(uint64_t offset, uint8_t* dst, uint32_t length)
{
    uint32_t got = 0;
    int i;
    memset(dst, 0, length);
    for (i = 0; i < g_vx_n; i++) {
        const VExtent* v = &g_vx[i];
        uint64_t lo = offset > v->off ? offset : v->off;
        uint64_t hi = offset + length < v->off + v->size ? offset + length : v->off + v->size;
        if (lo >= hi) continue;
        memcpy(dst + (lo - offset), v->data + (lo - v->off), (size_t)(hi - lo));
        got += (uint32_t)(hi - lo);
    }
    return got;
}

void disc_overlay_count(uint32_t bytes)
{
    g_vx_reads++;
    g_vx_bytes += bytes;
}

const char* disc_overlay_name(uint64_t offset, uint64_t* start, uint32_t* size)
{
    int i;
    for (i = 0; i < g_vx_n; i++)
        if (offset >= g_vx[i].off && offset - g_vx[i].off < g_vx[i].size) {
            if (start) *start = g_vx[i].off;
            if (size) *size = g_vx[i].size;
            return g_vx[i].path;
        }
    return NULL;
}

int disc_overlay_extents(void) { return g_vx_n; }

void disc_overlay_report(void)
{
    if (g_vx_n)
        fprintf(stderr, "[disc] overlay: %d virtual file(s); %llu reads of virtual files, %llu bytes\n", g_vx_n,
                g_vx_reads, g_vx_bytes);
}

void disc_overlay_reset(void)
{
    free(g_vx);
    g_vx = NULL;
    g_vx_n = 0;
    g_vx_reads = g_vx_bytes = 0;
}
