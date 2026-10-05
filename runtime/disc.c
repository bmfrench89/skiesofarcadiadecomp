/*
 * The disc (disc.h; docs/specs/disc-layer.md I1): the ISO backend, the checks
 * that the image is this port's disc, the drive's reads, and the file table's
 * names for the read log.
 *
 * Every offset, length and count in an image header is the image's to say and
 * is believed only after a bound written as a difference -- as main.c's
 * load_dol does -- so a damaged or crafted image is refused by name instead
 * of reading outside what was allocated.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "disc.h"
#include "plat.h"
#include "sha1.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* What this port was built for. Behind #ifndef, as mod.h's MOD_API is, so
 * tools/citest/disc_driver.c can build this for a synthetic image;
 * tools/tests/test_disc_const.py holds them to config/GEAE8P/config.yml. */
#ifndef DISC_GAME_ID
#define DISC_GAME_ID "GEAE8P"
#endif
#ifndef DISC_DOL_SHA1
#define DISC_DOL_SHA1 "8c0e278126fa3b0173400fdb632038172743cc13"
#endif

#define BOOT_SIZE 0x440u
#define BOOT_MAGIC 0xC2339F3Du
#define DOL_HEADER 0x100u
#define DOL_MAX (16u << 20) /* the real one is 3.0 MB */
#define FST_MAX (16u << 20) /* the real one is 131 KB */
#define FST_ENTRY 12u
#define PATH_MAX_DISC 256u

unsigned gx_frame_count(void); /* gx.c: the frame a logged read belongs to */

/* The build's own copies of the executable, boot.bin and the file table
 * (I3): <--out>/disc_sys.c, which tools/recompile.py writes at every run --
 * little-endian words of the files' bytes, each with its size and SHA-1. A
 * --no-embed build has the same symbols with sizes of zero. */
extern const uint32_t disc_sys_dol[], disc_sys_boot[], disc_sys_fst[];
extern const size_t disc_sys_dol_size, disc_sys_boot_size, disc_sys_fst_size;
extern const char disc_sys_dol_sha1[], disc_sys_boot_sha1[], disc_sys_fst_sha1[];
static int g_builtin; /* 0 not yet asked; 1 built in and sound; 2 none; -1 broken */

typedef struct {
    uint64_t off;
    uint32_t size;
    uint32_t name; /* offset of its full path in g_names */
    uint32_t order; /* its index in the file table, which breaks ties */
} Extent;

static FILE* g_f;
static char g_path[1024];
static DiscInfo g_info;
static int g_open;
static uint8_t g_boot[BOOT_SIZE];
static uint8_t* g_dol;
static size_t g_dol_n;
static uint8_t* g_fst;
static size_t g_fst_n;
static Extent* g_ext;
static uint32_t g_ext_n;
static char* g_names;
static int g_log;
static uint64_t g_past_reads, g_past_bytes;

static uint32_t be32(const uint8_t* p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

/* `n` bytes at `off`, all of them inside the image: the caller has bounded it. */
static int read_at(uint64_t off, void* dst, size_t n)
{
    return plat_fseek64(g_f, (int64_t)off) == 0 && fread(dst, 1, n, g_f) == n;
}

void disc_close(void)
{
    if (g_f) fclose(g_f);
    free(g_dol);
    free(g_fst);
    free(g_ext);
    free(g_names);
    g_f = NULL;
    g_dol = g_fst = NULL;
    g_ext = NULL;
    g_names = NULL;
    g_dol_n = g_fst_n = 0;
    g_ext_n = 0;
    g_open = 0;
    g_past_reads = g_past_bytes = 0;
    memset(&g_info, 0, sizeof g_info);
}

static int refuse(char* why, size_t cap, const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(why, cap, fmt, ap);
    va_end(ap);
    disc_close();
    return 1;
}

static int by_offset(const void* a, const void* b)
{
    const Extent* x = (const Extent*)a;
    const Extent* y = (const Extent*)b;
    if (x->off != y->off) return x->off < y->off ? -1 : 1;
    return x->order < y->order ? -1 : x->order > y->order;
}

/* Every file in the table, by its full path, sorted by where it lies. The
 * table is the image's, so each name and each directory's range is bounded
 * before it is followed. 0 when malformed. */
static int index_fst(void)
{
    uint32_t n = be32(g_fst + 8), strtab, i, depth = 0;
    uint32_t next[32];      /* the first entry past each open directory */
    size_t prefix[33] = {0}; /* the length of the path down to each depth */
    char path[PATH_MAX_DISC];
    size_t used = 0, cap = 1u << 16;
    if (n == 0 || n > (uint32_t)(g_fst_n / FST_ENTRY)) return 0;
    strtab = n * FST_ENTRY;
    g_ext = (Extent*)calloc(n, sizeof *g_ext);
    g_names = (char*)malloc(cap);
    if (!g_ext || !g_names) return 0;
    path[0] = 0;
    for (i = 1; i < n; i++) {
        const uint8_t* e = g_fst + (size_t)i * FST_ENTRY;
        uint32_t noff = (uint32_t)e[1] << 16 | (uint32_t)e[2] << 8 | e[3];
        const char *name, *nul;
        size_t len, at;
        while (depth && i >= next[depth - 1]) depth--; /* directories that closed before this entry */
        if (noff >= g_fst_n - strtab) return 0;
        name = (const char*)g_fst + strtab + noff;
        nul = (const char*)memchr(name, 0, g_fst_n - strtab - noff);
        if (!nul) return 0;
        len = (size_t)(nul - name);
        if (prefix[depth] + len + 1 >= sizeof path) return 0;
        memcpy(path + prefix[depth], name, len);
        at = prefix[depth] + len;
        path[at] = 0;
        if (e[0]) { /* a directory: its entries run to `next` */
            uint32_t end = be32(e + 8);
            if (end <= i || end > n || depth == 32) return 0;
            next[depth] = end;
            path[at] = '/';
            prefix[depth + 1] = at + 1;
            depth++;
            continue;
        }
        if (used + at + 1 > cap) {
            char* more = (char*)realloc(g_names, cap * 2);
            if (!more) return 0;
            g_names = more;
            cap *= 2;
        }
        memcpy(g_names + used, path, at + 1);
        g_ext[g_ext_n].off = be32(e + 4);
        g_ext[g_ext_n].size = be32(e + 8);
        g_ext[g_ext_n].name = (uint32_t)used;
        g_ext[g_ext_n].order = i;
        g_ext_n++;
        used += at + 1;
    }
    qsort(g_ext, g_ext_n, sizeof *g_ext, by_offset);
    return 1;
}

int disc_open(const char* where, char* why, size_t cap)
{
    uint64_t size = 0, dol_off, fst_off, fst_n, dol_n = 0;
    uint8_t head[DOL_HEADER];
    char want[41], got[41], boot_sha[41], fst_sha[41];
    const char* env;
    int kind, i;

    disc_close();
    kind = plat_path_kind(where, &size);
    if (kind == PLAT_PATH_DIR) {
        snprintf(g_path, sizeof g_path, "%s/disc.iso", where);
        kind = plat_path_kind(g_path, &size);
    } else {
        snprintf(g_path, sizeof g_path, "%s", where);
    }
    if (kind != PLAT_PATH_FILE)
        return refuse(why, cap,
                      "no disc image at %s; make one from your own disc with: python tools/extract.py "
                      "<your disc dump> (which writes extracted/disc.iso), or name an .iso or .gcm file",
                      g_path);
    g_f = fopen(g_path, "rb");
    if (!g_f) return refuse(why, cap, "cannot open %s", g_path);
    if (size < BOOT_SIZE || !read_at(0, g_boot, BOOT_SIZE))
        return refuse(why, cap, "%s is %llu bytes, too short to be a GameCube disc image", g_path,
                      (unsigned long long)size);
    if (be32(g_boot + 0x1C) != BOOT_MAGIC) {
        int rvz = memcmp(g_boot, "RVZ\x01", 4) == 0 || memcmp(g_boot, "WIA\x01", 4) == 0;
        return refuse(why, cap, "%s is not a GameCube disc image (boot magic %08X, not %08X)%s", g_path,
                      be32(g_boot + 0x1C), BOOT_MAGIC,
                      rvz ? "; it is Dolphin's RVZ/WIA format, which python tools/extract.py <it> turns into "
                            "the ISO this reads"
                          : "");
    }
    memcpy(g_info.game_id, g_boot, 6);
    for (i = 0; i < 6; i++)
        if (g_info.game_id[i] < 0x20 || g_info.game_id[i] > 0x7E) g_info.game_id[i] = '?';
    g_info.disc_number = g_boot[6];
    g_info.revision = g_boot[7];
    if (strcmp(g_info.game_id, DISC_GAME_ID) != 0)
        return refuse(why, cap,
                      "%s is %s, not %s: this port is the North American GameCube release only (European "
                      "and Japanese discs are not supported)",
                      g_path, g_info.game_id, DISC_GAME_ID);
    if (g_info.revision != 0)
        return refuse(why, cap, "%s is %s revision %u; this port was built for revision 0", g_path,
                      g_info.game_id, g_info.revision);

    /* The executable: its header, then as far as its furthest section. */
    dol_off = be32(g_boot + 0x420);
    if (dol_off > size || size - dol_off < DOL_HEADER || !read_at(dol_off, head, DOL_HEADER))
        return refuse(why, cap, "%s: the executable's header at 0x%llX lies past the image's end (%llu bytes)",
                      g_path, (unsigned long long)dol_off, (unsigned long long)size);
    for (i = 0; i < 18; i++) {
        uint64_t off = be32(head + 4 * i), len = be32(head + 0x90 + 4 * i);
        if (len && off + len > dol_n) dol_n = off + len;
    }
    if (dol_n < DOL_HEADER || dol_n > DOL_MAX)
        return refuse(why, cap, "%s: the executable claims %llu bytes, which no GameCube DOL is", g_path,
                      (unsigned long long)dol_n);
    if (dol_n > size - dol_off)
        return refuse(why, cap,
                      "%s: a section of the executable lies past the image's end (it needs %llu bytes from "
                      "0x%llX, and the image is %llu)",
                      g_path, (unsigned long long)dol_n, (unsigned long long)dol_off, (unsigned long long)size);
    g_dol_n = (size_t)dol_n;
    g_dol = (uint8_t*)malloc(g_dol_n);
    if (!g_dol || !read_at(dol_off, g_dol, g_dol_n)) return refuse(why, cap, "%s: cannot read the executable", g_path);
    /* The translated code is this executable's: any other would run the old
     * code over new data with nothing saying so (§3.3). */
    sha1_hex(g_dol, g_dol_n, got);
    snprintf(want, sizeof want, "%s", DISC_DOL_SHA1);
    if (strcmp(got, want) != 0)
        return refuse(why, cap,
                      "this image's executable is not the one this port was built for: %s has SHA-1 %s, and "
                      "the port was built from %s",
                      g_path, got, want);

    /* The file table. */
    fst_off = be32(g_boot + 0x424);
    fst_n = be32(g_boot + 0x428);
    if (fst_off >= size)
        return refuse(why, cap, "%s: the file table starts at 0x%llX, past the image's end (%llu bytes)", g_path,
                      (unsigned long long)fst_off, (unsigned long long)size);
    if (fst_n < 12 || fst_n > FST_MAX)
        return refuse(why, cap, "%s: the file table claims %llu bytes, which no GameCube disc's is", g_path,
                      (unsigned long long)fst_n);
    if (fst_n > size - fst_off)
        return refuse(why, cap,
                      "%s: the image ends inside the file table (%llu of its %llu bytes are there): a "
                      "truncated dump?",
                      g_path, (unsigned long long)(size - fst_off), (unsigned long long)fst_n);
    g_fst_n = (size_t)fst_n;
    g_fst = (uint8_t*)malloc(g_fst_n);
    if (!g_fst || !read_at(fst_off, g_fst, g_fst_n)) return refuse(why, cap, "%s: cannot read the file table", g_path);
    if (!index_fst()) return refuse(why, cap, "%s: the file table is malformed", g_path);
    sha1_hex(g_boot, BOOT_SIZE, boot_sha);
    sha1_hex(g_fst, g_fst_n, fst_sha);
    /* The stale-disc guard (I3): with the build's own file table built in,
     * an image whose table differs -- a patched or another image -- would
     * boot with offsets pointing at the wrong bytes. */
    if (disc_builtin(why, cap) == 1 &&
        (disc_sys_fst_size != g_fst_n || memcmp(disc_sys_fst, g_fst, g_fst_n) != 0))
        return refuse(why, cap,
                      "this disc image is not the one this build was made from (a patched or different "
                      "image?): %s has file table SHA-1 %s, and the build's is %s; rebuild from it with "
                      "python tools/recompile.py --link, or use the image it was built from",
                      g_path, fst_sha, disc_sys_fst_sha1);

    g_info.image_size = size;
    g_info.covered_end = size;
    g_info.backend = "iso";
    g_info.path = g_path;
    g_open = 1;
    env = getenv("SOA_DISC_LOG");
    g_log = env && *env && strcmp(env, "0") != 0;
    fprintf(stderr, "[disc] %s: %s rev %u disc image, %llu bytes; DOL %s, boot.bin %s, FST %s%s\n", g_path,
            g_info.game_id, g_info.revision, (unsigned long long)size, got, boot_sha, fst_sha,
            g_builtin == 1 ? "; FST matches this build" : "");
    return 0;
}

const DiscInfo* disc_info(void) { return g_open ? &g_info : NULL; }

/* Each built-in part against its own SHA-1, and the executable against the
 * one the port was translated from: a generator or byte-order fault shows
 * here, at boot, not as a game that runs strangely. */
static int hashes_to(const uint32_t* words, size_t n, const char* want, char hex[41])
{
    sha1_hex((const uint8_t*)words, n, hex);
    return strcmp(hex, want) == 0;
}

int disc_builtin(char* why, size_t cap)
{
    static char said[512];
    char hex[41];
    if (g_builtin == 0) {
        g_builtin = -1;
        if (disc_sys_dol_size == 0)
            g_builtin = 2; /* --no-embed: the image's own are read */
        else if (disc_sys_boot_size != BOOT_SIZE || disc_sys_fst_size < 12)
            snprintf(said, sizeof said, "the system files built into this soa.exe are the wrong sizes");
        else if (!hashes_to(disc_sys_dol, disc_sys_dol_size, disc_sys_dol_sha1, hex) || strcmp(hex, DISC_DOL_SHA1) != 0)
            snprintf(said, sizeof said,
                     "the executable built into this soa.exe hashes to %s, not its own %s and the port's %s (a "
                     "generator or byte-order fault); rebuild with python tools/recompile.py --link",
                     hex, disc_sys_dol_sha1, DISC_DOL_SHA1);
        else if (!hashes_to(disc_sys_boot, BOOT_SIZE, disc_sys_boot_sha1, hex))
            snprintf(said, sizeof said, "the boot.bin built into this soa.exe hashes to %s, not its own %s", hex,
                     disc_sys_boot_sha1);
        else if (!hashes_to(disc_sys_fst, disc_sys_fst_size, disc_sys_fst_sha1, hex))
            snprintf(said, sizeof said, "the file table built into this soa.exe hashes to %s, not its own %s", hex,
                     disc_sys_fst_sha1);
        else
            g_builtin = 1;
    }
    if (g_builtin < 0) snprintf(why, cap, "%s", said);
    return g_builtin == 2 ? 0 : g_builtin;
}

int disc_system(const uint8_t** dol, size_t* dol_n, const uint8_t** boot, const uint8_t** fst, size_t* fst_n,
                char* why, size_t cap)
{
    int built = disc_builtin(why, cap);
    if (built < 0) return 1;
    if (built == 1) { /* the build's own copies: the image may not even be open */
        *dol = (const uint8_t*)disc_sys_dol;
        *dol_n = disc_sys_dol_size;
        *boot = (const uint8_t*)disc_sys_boot;
        *fst = (const uint8_t*)disc_sys_fst;
        *fst_n = disc_sys_fst_size;
        return 0;
    }
    if (!g_open) {
        snprintf(why, cap, "no disc image is open");
        return 1;
    }
    *dol = g_dol;
    *dol_n = g_dol_n;
    *boot = g_boot;
    *fst = g_fst;
    *fst_n = g_fst_n;
    return 0;
}

uint32_t disc_peek(uint64_t offset, uint8_t* dst, uint32_t length)
{
    uint32_t got = 0;
    if (g_open && offset < g_info.covered_end) {
        uint64_t room = g_info.covered_end - offset;
        uint32_t want = room < length ? (uint32_t)room : length;
        if (plat_fseek64(g_f, (int64_t)offset) == 0) got = (uint32_t)fread(dst, 1, want, g_f);
    }
    if (got < length) memset(dst + got, 0, length - got);
    return got;
}

const char* disc_name_at(uint64_t offset, uint64_t* start, uint32_t* size)
{
    uint32_t lo = 0, hi = g_ext_n, first;
    /* past the last extent starting at or before offset */
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (g_ext[mid].off <= offset) lo = mid + 1;
        else hi = mid;
    }
    if (lo == 0) return NULL;
    /* of those starting where it does, the first in table order that holds offset */
    for (first = lo - 1; first > 0 && g_ext[first - 1].off == g_ext[lo - 1].off; first--) {}
    for (; first < lo; first++) {
        const Extent* e = &g_ext[first];
        if (offset - e->off < e->size) {
            if (start) *start = e->off;
            if (size) *size = e->size;
            return g_names + e->name;
        }
    }
    return NULL;
}

void disc_serve(uint64_t offset, uint8_t* dst, uint32_t length)
{
    uint32_t got = disc_peek(offset, dst, length);
    if (got < length) {
        /* A truncated image otherwise has no diagnostic at all: the game
         * just gets zeros where an asset should be. Once is enough. */
        if (g_open && !g_past_reads)
            fprintf(stderr, "[disc] a read at %llu reaches past the image's end (+%u bytes of zeros); "
                            "the image looks incomplete\n",
                    (unsigned long long)offset, (unsigned)(length - got));
        g_past_reads++;
        g_past_bytes += length - got;
    }
    if (g_log) {
        uint64_t start = 0;
        uint32_t size = 0;
        const char* name = disc_name_at(offset, &start, &size);
        uint64_t end = start + size, last = offset + length;
        if (name && last > end)
            fprintf(stderr, "[disc] frame %u read 0x%llX +%u %s, %llu past its end\n", gx_frame_count(),
                    (unsigned long long)offset, length, name, (unsigned long long)(last - end));
        else
            fprintf(stderr, "[disc] frame %u read 0x%llX +%u %s\n", gx_frame_count(), (unsigned long long)offset,
                    length, name ? name : "(no file)");
    }
}

const uint8_t* disc_fst(size_t* n)
{
    *n = g_open ? g_fst_n : 0;
    return g_open ? g_fst : NULL;
}

void disc_report(void)
{
    if (!g_open) return;
    fprintf(stderr, "[disc] backend %s; %llu reads past the image's end (%llu bytes of zeros)\n", g_info.backend,
            (unsigned long long)g_past_reads, (unsigned long long)g_past_bytes);
}
