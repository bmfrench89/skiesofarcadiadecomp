/*
 * The disc (disc.h; docs/specs/disc-layer.md I1, I3, I5): the two backends --
 * an ISO, or the checked store tools/extract.py --store writes -- the checks
 * that the image is this port's disc, the drive's reads, and the file table's
 * names for the read log.
 *
 * Every offset, length and count in an image or store header is the file's to
 * say and is believed only after a bound written as a difference -- as
 * main.c's load_dol does -- so a damaged or crafted image is refused by name
 * instead of reading outside what was allocated.
 *
 * The store (I5) is read like the ISO, from its payload, with each 64 KiB
 * block checked against its SHA-1 the first time a drive read touches it
 * (SOA_DISC_VERIFY=hash, its default): a corrupt copy stops the run, exit 9,
 * naming the file, before the game sees a byte of it. The drive's timing is
 * dvd.c's and unchanged: the hashing stalls the game as a read does, and that
 * time counts toward the read's completion as a read's does (the
 * implementation session's "keep", 2026-10-05; I5a not built).
 *
 * On a phone (specs/android.md L12d) the disc is often read in place through
 * the descriptor the file picker gave, from storage that can go away under
 * the run: a read that fails inside the image once it is open stops the run,
 * exit 9, saying so, never handing the game zeros. The refusals there are in
 * a phone's words (disc_set_phone_words), which name no PC command.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "disc.h"
#include "plat.h"
#include "sha1.h"
#include <errno.h>
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

/* The store, tools/soa/store.py's format version 1 (spec section 3.7.2). */
#define STORE_MAGIC "SOADISC1"
#define STORE_HEADER 4096u
#define STORE_EXTENT 64u
#define STORE_BLOCK 65536u
#define STORE_DIGEST 20u
#define STORE_SHA1_AT 0xFECu
#define STORE_MAX_EXTENTS (1u << 20)
#define STORE_MAX_BLOCKS (1u << 22)

enum { VERIFY_HASH = 1, VERIFY_ISO = 2 };

unsigned gx_frame_count(void); /* gx.c: the frame a logged read belongs to */

/* The build's own copies of the executable, boot.bin and the file table
 * (I3): <--out>/disc_sys.c, which tools/recompile.py writes at every run --
 * little-endian words of the files' bytes, each with its size and SHA-1. A
 * --no-embed build has the same symbols with sizes of zero. */
#ifdef SOA_SPLIT
/* A split build has them from the game library's table (specs/android.md 3.2). */
#include "soa_game.h"
#define disc_sys_dol (soa_game_table->dol)
#define disc_sys_boot (soa_game_table->boot)
#define disc_sys_fst (soa_game_table->fst)
#define disc_sys_dol_size (*soa_game_table->dol_size)
#define disc_sys_boot_size (*soa_game_table->boot_size)
#define disc_sys_fst_size (*soa_game_table->fst_size)
#define disc_sys_dol_sha1 (soa_game_table->dol_sha1)
#define disc_sys_boot_sha1 (soa_game_table->boot_sha1)
#define disc_sys_fst_sha1 (soa_game_table->fst_sha1)
#else
extern const uint32_t disc_sys_dol[], disc_sys_boot[], disc_sys_fst[];
extern const size_t disc_sys_dol_size, disc_sys_boot_size, disc_sys_fst_size;
extern const char disc_sys_dol_sha1[], disc_sys_boot_sha1[], disc_sys_fst_sha1[];
#endif
static int g_builtin; /* 0 not yet asked; 1 built in and sound; 2 none; -1 broken */
static int g_builtin_bad; /* when broken, which part: 1 the sizes, 2 the executable, 3 boot.bin, 4 the file table */
static char g_builtin_hex[41]; /* what that part hashed to */

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

/* The backend: where image offset 0 sits in the file, and how far it goes. */
static int g_store;
static uint64_t g_payload, g_covered;
static uint8_t* g_store_ext; /* the store's extent table, as stored */
static uint32_t g_store_ext_n;
static uint8_t* g_blocks; /* the store's block digests */
static uint32_t g_block_n;
static uint32_t g_flags;
static int g_verify;
static uint8_t* g_seen; /* one bit per block hashed */
static FILE* g_iso;
static char g_iso_path[1024];
static uint64_t g_flip = UINT64_MAX;
static char g_flip_said[300];
static int g_flip_read;
static uint64_t g_hashed, g_hash_ns;
static uint64_t g_vreads, g_vbytes, g_vdiffer, g_vpast;
static void (*g_stop_hook)(void);
static uint64_t g_file_size; /* the file's size when it was opened */
static int g_read_errno;     /* why the last raw_read failed: an errno, or 0 when the file ended first */
static uint64_t g_read_at;   /* and where in the file it began, */
static size_t g_read_n;      /* for how many bytes */
static int g_phone;          /* disc_set_phone_words */
static int g_by_build;       /* the last disc_open refused by the I3 guard */
static char g_stop_words[1000]; /* disc_stop_words: why the run was stopped, for a player, */
static int g_stop_kind;         /* and which kind of stop it was */

/* The remedies refusals end with: the PC's commands, or a phone's, which has
 * no Python, no soa.exe and no recompile.py -- its player has Setup on a PC
 * and the copy they made there (specs/android.md L12d). */
#define PC_REIMPORT "re-import with python tools/extract.py <your disc dump> --store"
#define PHONE_RECOPY "copy it to this phone again, or make it again on your PC"
#define PHONE_REBUILD "make the game library again with Setup on your PC"

/* What carries the built-in system files, as the player knows it: a phone's
 * runtime has them from the game library, as a split build does. */
static const char* build_noun(void)
{
#ifdef SOA_SPLIT
    return "this game library";
#else
    return g_phone ? "this game library" : "this soa.exe";
#endif
}

void disc_set_phone_words(int on) { g_phone = on != 0; }
const char* disc_port_dol_sha1(void) { return DISC_DOL_SHA1; }
int disc_refused_by_build(void) { return g_by_build; }

int disc_stop_words(char* out, size_t cap)
{
    if (!g_stop_kind) return DISC_STOP_NONE;
    snprintf(out, cap, "%s", g_stop_words);
    return g_stop_kind;
}

/* A stop's words for a player, and its kind, said before stop() exits. */
static void stop_said(int kind, const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_stop_words, sizeof g_stop_words, fmt, ap);
    va_end(ap);
    g_stop_kind = kind;
}

static uint32_t be32(const uint8_t* p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static uint32_t le32(const uint8_t* p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint64_t le64(const uint8_t* p) { return (uint64_t)le32(p) | (uint64_t)le32(p + 4) << 32; }

/* `n` bytes of the file at file offset `at`. When they cannot be had,
 * g_read_errno says why: an errno, or 0 when the file ended first; and
 * g_read_at and g_read_n say which read it was. */
static int raw_read(uint64_t at, void* dst, size_t n)
{
    if (plat_fseek64(g_f, (int64_t)at) != 0) {
        g_read_errno = errno ? errno : EIO;
    } else if (fread(dst, 1, n, g_f) == n) {
        return 1;
    } else {
        g_read_errno = ferror(g_f) ? (errno ? errno : EIO) : 0;
        clearerr(g_f);
    }
    g_read_at = at;
    g_read_n = n;
    return 0;
}

/* Why a read of the file at `path`, `was` bytes when it was opened, came up
 * short: the system's words for `err`, or, when the file simply ended, how
 * long it is now. */
static const char* why_short(int err, const char* path, uint64_t was, char* out, size_t cap)
{
    uint64_t now = 0;
    if (err)
        snprintf(out, cap, "%s", strerror(err));
    else if (plat_path_kind(path, &now) == PLAT_PATH_FILE && now < was)
        snprintf(out, cap, "it is %llu bytes now, and was %llu when it was opened", (unsigned long long)now,
                 (unsigned long long)was);
    else
        snprintf(out, cap, "it ends sooner than it did when it was opened");
    return out;
}

/* The words for a read that failed: `n` bytes at file offset `at` of `path`,
 * which was `was` bytes when it was opened, failing with `err`. The offset
 * and the length are the file's, as its sizes are, so the line agrees with
 * itself. A store's payload starts further in, so a read there also gives
 * its offset on the disc, which the other [disc] lines use (`disc`;
 * UINT64_MAX for none, as for a read of a header). */
static void read_words(char* out, size_t cap, const char* path, uint64_t at, size_t n, uint64_t disc, int err,
                       uint64_t was)
{
    char reason[200], also[48] = "";
    if (disc != UINT64_MAX) snprintf(also, sizeof also, ", disc offset 0x%llX", (unsigned long long)disc);
    snprintf(out, cap, "cannot read %s at 0x%llX (+%llu bytes%s): %s; was its storage removed?", path,
             (unsigned long long)at, (unsigned long long)n, also, why_short(err, path, was, reason, sizeof reason));
}

/* `n` bytes of the image at `off`, all of them below g_covered: the caller has
 * bounded it. The store's flip knob is applied here, as a corruption on the
 * disk would be: before anything hashes, compares or serves the bytes. */
static int read_at(uint64_t off, void* dst, size_t n)
{
    if (!raw_read(g_payload + off, dst, n)) return 0;
    if (g_store && g_flip >= off && g_flip - off < n) {
        ((uint8_t*)dst)[g_flip - off] ^= 1;
        g_flip_read = 1;
    }
    return 1;
}

void disc_set_stop_hook(void (*fn)(void)) { g_stop_hook = fn; }

void disc_close(void)
{
    if (g_f) fclose(g_f);
    if (g_iso) fclose(g_iso);
    free(g_dol);
    free(g_fst);
    free(g_ext);
    free(g_names);
    free(g_store_ext);
    free(g_blocks);
    free(g_seen);
    g_f = g_iso = NULL;
    g_dol = g_fst = g_store_ext = g_blocks = g_seen = NULL;
    g_ext = NULL;
    g_names = NULL;
    g_dol_n = g_fst_n = 0;
    g_ext_n = g_store_ext_n = g_block_n = 0;
    g_open = g_store = g_verify = g_flip_read = 0;
    g_payload = g_covered = g_file_size = 0;
    g_flags = 0;
    g_flip = UINT64_MAX;
    g_past_reads = g_past_bytes = g_hashed = g_hash_ns = 0;
    g_vreads = g_vbytes = g_vdiffer = g_vpast = 0;
    memset(&g_info, 0, sizeof g_info);
}

/* A refusal's words, into why: 1. say() only says it, for disc_identify,
 * which has nothing of its own open to close; refuse() also closes. */
static int say(char* why, size_t cap, const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(why, cap, fmt, ap);
    va_end(ap);
    return 1;
}

static int refused(void)
{
    disc_close();
    return 1;
}

static int refuse(char* why, size_t cap, const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(why, cap, fmt, ap);
    va_end(ap);
    return refused();
}

/* The words for the last raw_read that failed, of the open file. Once
 * open_store has set the backend every read is of the payload, so a store's
 * also say where on the disc the read was. */
static void failed_read(char* out, size_t cap)
{
    read_words(out, cap, g_path, g_read_at, g_read_n,
               g_store && g_read_at >= g_payload ? g_read_at - g_payload : UINT64_MAX, g_read_errno, g_file_size);
}

/* A read at the open that failed, refused in the words a stop would use. */
static int refuse_read(char* why, size_t cap)
{
    failed_read(why, cap);
    return refused();
}

/* A stop the disc layer makes mid-run: say it, give the report, exit 9. */
static void stop(const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[disc] ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
    if (g_stop_hook) g_stop_hook();
    fflush(stderr);
    exit(9);
}

/* `n` bytes of the image at `off`, below g_covered, once it is open. The
 * image's size was measured at the open, so a read there that fails is the
 * storage failing -- a card pulled out, a provider gone, the file cut short
 * under its descriptor -- and never a short image: the run stops in words of
 * its own, rather than the game being handed zeros or a sound block being
 * called damaged. */
static void read_or_stop(uint64_t off, void* dst, size_t n)
{
    char said[1400], reason[200];
    if (read_at(off, dst, n)) return;
    failed_read(said, sizeof said);
    stop_said(DISC_STOP_READ, "%s could not be read: %s. Was its storage removed?", g_path,
              why_short(g_read_errno, g_path, g_file_size, reason, sizeof reason));
    stop("%s", said);
}

/* The refusals disc_open and disc_identify share, each a function so the two
 * say the same thing of the same file. What a path names, when it is not a
 * file disc.c can read anywhere in. */
static int say_kind(const char* path, int kind, char* why, size_t cap)
{
    if (kind == PLAT_PATH_STREAM)
        return say(why, cap,
                   "%s is a stream (a pipe or a socket), which can be read only from start to end, and a disc "
                   "is read anywhere in it: copy it to a file first",
                   path);
    if (g_phone)
        return say(why, cap, "no disc image at %s: pick an .iso, .gcm or .soadisc file made from your own disc",
                   path);
    return say(why, cap,
               "no disc image at %s; make one from your own disc with: python tools/extract.py "
               "<your disc dump> (which writes extracted/disc.iso), or name an .iso, .gcm or .soadisc file",
               path);
}

/* The game id at `p` (six bytes), printable, into id[7]. */
static void game_id(const uint8_t* p, char id[7])
{
    int i;
    memcpy(id, p, 6);
    id[6] = 0;
    for (i = 0; i < 6; i++)
        if (id[i] < 0x20 || id[i] > 0x7E) id[i] = '?';
}

/* This game id and this revision, from boot.bin or a store's header. */
static int say_id(const char* path, const uint8_t* id6, unsigned revision, char* why, size_t cap)
{
    char id[7];
    game_id(id6, id);
    if (strcmp(id, DISC_GAME_ID) != 0)
        return say(why, cap, "%s is %s, not %s: %s the North American GameCube release only (European and Japanese "
                   "discs are not supported)", path, id, DISC_GAME_ID, g_phone ? "this app plays" : "this port is");
    if (revision != 0)
        return say(why, cap, "%s is %s revision %u; %s revision 0", path, id, revision,
                   g_phone ? "this app plays" : "this port was built for");
    return 0;
}

/* boot.bin, the first 0x440 bytes of an image: GameCube's magic, then
 * this game id and revision. Dolphin's own formats are named. */
static int say_boot(const char* path, const uint8_t* boot, char* why, size_t cap)
{
    if (be32(boot + 0x1C) != BOOT_MAGIC) {
        int rvz = memcmp(boot, "RVZ\x01", 4) == 0 || memcmp(boot, "WIA\x01", 4) == 0;
        return say(why, cap, "%s is not a GameCube disc image (boot magic %08X, not %08X)%s", path,
                   be32(boot + 0x1C), BOOT_MAGIC,
                   !rvz      ? ""
                   : g_phone ? "; it is Dolphin's RVZ/WIA format, which this app does not read: make an ISO of it on "
                               "your PC (Dolphin's Convert File does) and pick that"
                             : "; it is Dolphin's RVZ/WIA format, which python tools/extract.py <it> turns into the "
                               "ISO this reads");
    }
    return say_id(path, boot, boot[7], why, cap);
}

/* A store's header on its own: format 1, its sizes and its tables where
 * format 1 puts them (spec section 3.7.2). The file's size and the header's
 * SHA-1 are open_store's, since a copy in progress has neither yet. */
static int say_store(const char* path, const uint8_t* h, char* why, size_t cap)
{
    uint32_t version = le32(h + 0x08), header_n = le32(h + 0x0C), extent_n = le32(h + 0x10), n = le32(h + 0x14);
    uint64_t ext_at = le64(h + 0x18), pay_at = le64(h + 0x20), pay_n = le64(h + 0x28);
    uint64_t image_n = le64(h + 0x30), covered = le64(h + 0x38), block_at = le64(h + 0xE8);
    uint32_t block_size = le32(h + 0xE0), blocks = le32(h + 0xE4);
    if (version != 1)
        return say(why, cap, "%s: store format %u, and %s 1; %s", path, version,
                   g_phone ? "this app reads" : "this port reads",
                   g_phone ? "make it again on your PC, with the release this app comes from" : PC_REIMPORT);
    if (header_n != STORE_HEADER || extent_n != STORE_EXTENT || block_size != STORE_BLOCK || n == 0 ||
        n > STORE_MAX_EXTENTS || blocks > STORE_MAX_BLOCKS || pay_n != covered || covered > image_n ||
        blocks != (pay_n + STORE_BLOCK - 1) / STORE_BLOCK || ext_at != STORE_HEADER ||
        block_at != ext_at + (uint64_t)n * STORE_EXTENT || pay_at < block_at + (uint64_t)blocks * STORE_DIGEST)
        return say(why, cap, "%s: its header does not describe a version 1 store", path);
    return 0;
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
    uint32_t next[32];       /* the first entry past each open directory */
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

/* The store's header and tables (spec section 3.7.2), each size and offset
 * bounded, then held to the header's own SHA-1. Sets the backend. */
static int open_store(uint64_t file_size, char* why, size_t cap)
{
    uint8_t h[STORE_HEADER], *all;
    uint64_t ext_at, pay_at, pay_n, image_n, covered, tables;
    uint32_t n, blocks;
    char got[41], want[41];
    if (file_size < STORE_HEADER) return refuse(why, cap, "%s: too short to be a disc store", g_path);
    if (!raw_read(0, h, STORE_HEADER)) return refuse_read(why, cap);
    if (say_store(g_path, h, why, cap)) return refused();
    n = le32(h + 0x14);
    ext_at = le64(h + 0x18);
    pay_at = le64(h + 0x20);
    pay_n = le64(h + 0x28);
    image_n = le64(h + 0x30);
    covered = le64(h + 0x38);
    blocks = le32(h + 0xE4);
    if (file_size < pay_at || file_size - pay_at < pay_n)
        return refuse(why, cap, "%s: truncated (%llu bytes, and its payload needs %llu); %s", g_path,
                      (unsigned long long)file_size, (unsigned long long)(pay_at + pay_n),
                      g_phone ? "copy it to this phone again" : PC_REIMPORT);
    /* the header's own SHA-1: over its bytes before it, then both tables */
    tables = (uint64_t)n * STORE_EXTENT + (uint64_t)blocks * STORE_DIGEST;
    all = (uint8_t*)malloc((size_t)(STORE_SHA1_AT + tables));
    if (!all) return refuse(why, cap, "%s: no memory for its tables", g_path);
    memcpy(all, h, STORE_SHA1_AT);
    if (!raw_read(ext_at, all + STORE_SHA1_AT, (size_t)tables)) {
        free(all);
        return refuse_read(why, cap);
    }
    sha1_hex(all, (size_t)(STORE_SHA1_AT + tables), got);
    {
        int i;
        for (i = 0; i < 20; i++) snprintf(want + 2 * i, 3, "%02x", h[STORE_SHA1_AT + i]);
    }
    if (strcmp(got, want) != 0) {
        free(all);
        return refuse(why, cap, "%s: its header and tables do not match their SHA-1; %s", g_path,
                      g_phone ? "the store is damaged: " PHONE_RECOPY : PC_REIMPORT);
    }
    g_store_ext = (uint8_t*)malloc((size_t)n * STORE_EXTENT);
    g_blocks = (uint8_t*)malloc((size_t)blocks * STORE_DIGEST + 1);
    g_seen = (uint8_t*)calloc(blocks / 8 + 1, 1);
    if (!g_store_ext || !g_blocks || !g_seen) {
        free(all);
        return refuse(why, cap, "%s: no memory for its tables", g_path);
    }
    memcpy(g_store_ext, all + STORE_SHA1_AT, (size_t)n * STORE_EXTENT);
    memcpy(g_blocks, all + STORE_SHA1_AT + (size_t)n * STORE_EXTENT, (size_t)blocks * STORE_DIGEST);
    free(all);
    g_store = 1;
    g_store_ext_n = n;
    g_block_n = blocks;
    g_payload = pay_at;
    g_covered = covered;
    g_flags = le32(h + 0x9C);
    g_info.image_size = image_n;
    return 0;
}

/* The files whose extents overlap [lo, hi), for a message. */
static int files_in(uint64_t lo, uint64_t hi, char* out, size_t cap)
{
    uint32_t i;
    size_t used = 0;
    out[0] = 0;
    for (i = 0; i < g_ext_n && used + 1 < cap; i++) {
        const Extent* e = &g_ext[i];
        if (e->off < hi && e->off + e->size > lo) {
            int k = snprintf(out + used, cap - used, "%s%s", used ? ", " : "", g_names + e->name);
            if (k < 0) break;
            used += (size_t)k < cap - used ? (size_t)k : cap - used - 1;
        }
    }
    if (out[0]) return 1;
    snprintf(out, cap, "padding, no file");
    return 0;
}

/* SOA_DISC_VERIFY and SOA_DISC_FLIP, once the image is open and indexed. */
static int arm_checks(const char* where, char* why, size_t cap)
{
    const char* v = getenv("SOA_DISC_VERIFY");
    const char* flip = getenv("SOA_DISC_FLIP");
    const char* iso = NULL;
    if (!v || !*v) g_verify = g_store ? VERIFY_HASH : 0;
    else if (!strcmp(v, "0")) g_verify = 0;
    else if (!strcmp(v, "hash")) g_verify = VERIFY_HASH;
    else if (!strncmp(v, "iso", 3) && (!v[3] || v[3] == ':')) g_verify = VERIFY_ISO, iso = v[3] ? v + 4 : NULL;
    else if (!strncmp(v, "all", 3) && (!v[3] || v[3] == ':')) g_verify = VERIFY_HASH | VERIFY_ISO, iso = v[3] ? v + 4 : NULL;
    else return refuse(why, cap, "SOA_DISC_VERIFY=%s: it is hash, iso[:path], all[:path] or 0", v);
    /* a check that silently does not run is worse than none */
    if (g_verify && !g_store)
        return refuse(why, cap, "SOA_DISC_VERIFY=%s checks a store against its hashes or an ISO, and %s is an ISO "
                      "(%s)", v, g_path,
                      g_phone ? "a store of it is made on a PC"
                              : "python tools/extract.py <your disc dump> --store makes one");
    if (g_verify & VERIFY_ISO) {
        uint64_t size = 0;
        if (iso && *iso) {
            snprintf(g_iso_path, sizeof g_iso_path, "%s", iso);
        } else if (plat_fd_path(g_path) >= 0) {
            /* a descriptor has no folder to look beside, and a disc.iso made
             * up from its path would only be refused as missing */
            return refuse(why, cap, "SOA_DISC_VERIFY=%s compares the store with an ISO, and %s is a descriptor, "
                          "with no folder beside it to find one in: name the ISO, as SOA_DISC_VERIFY=%.3s:<path>",
                          v, g_path, v);
        } else if (plat_path_kind(where, NULL) == PLAT_PATH_DIR) {
            snprintf(g_iso_path, sizeof g_iso_path, "%s/disc.iso", where);
        } else {
            const char* slash = strrchr(g_path, '/');
            const char* back = strrchr(g_path, '\\');
            size_t dir = slash || back ? (size_t)((back > slash ? back : slash) - g_path) : 0;
            snprintf(g_iso_path, sizeof g_iso_path, "%.*s%sdisc.iso", (int)dir, g_path, dir ? "/" : "");
        }
        if (plat_path_kind(g_iso_path, &size) != PLAT_PATH_FILE || !(g_iso = fopen(g_iso_path, "rb")))
            return refuse(why, cap, "SOA_DISC_VERIFY=%s compares the store with an ISO, and there is none at %s", v,
                          g_iso_path);
    }
    if (flip && *flip) {
        if (!g_store) return refuse(why, cap, "SOA_DISC_FLIP corrupts a store as it is read, and %s is an ISO", g_path);
        if (flip[0] == '0' && (flip[1] == 'x' || flip[1] == 'X')) {
            g_flip = strtoull(flip, NULL, 16);
        } else {
            uint32_t i;
            for (i = 0; i < g_ext_n; i++)
                if (!strcmp(g_names + g_ext[i].name, flip)) break;
            if (i == g_ext_n) return refuse(why, cap, "SOA_DISC_FLIP=%s names no file on the disc", flip);
            g_flip = g_ext[i].off;
        }
        if (g_flip >= g_covered)
            return refuse(why, cap, "SOA_DISC_FLIP=%s lies past the stored image (0x%llX)", flip,
                          (unsigned long long)g_covered);
        snprintf(g_flip_said, sizeof g_flip_said, "%s", flip);
        fprintf(stderr, "[disc] flip armed: one byte of the store at 0x%llX (%s) reads with its low bit inverted\n",
                (unsigned long long)g_flip, flip);
    }
    return 0;
}

int disc_open(const char* where, char* why, size_t cap)
{
    uint64_t size = 0, dol_off, fst_off, fst_n, dol_n = 0;
    uint8_t head[DOL_HEADER], magic[8];
    char want[41], got[41], boot_sha[41], fst_sha[41], said[600];
    const char* env;
    int kind, built, i;
    uint32_t k;

    disc_close();
    g_by_build = 0;
    /* A build whose own system files are broken plays no disc: refused here
     * as well as at main.c's boot, since a phone checks the disc it is
     * handed with this call alone (specs/android.md L12d). */
    built = disc_builtin(said, sizeof said);
    if (built < 0) return refuse(why, cap, "%s", said);
    kind = plat_path_kind(where, &size);
    if (kind == PLAT_PATH_DIR) {
        /* the checked store first (I5), then the ISO */
        snprintf(g_path, sizeof g_path, "%s/%s.soadisc", where, DISC_GAME_ID);
        kind = plat_path_kind(g_path, &size);
        if (kind != PLAT_PATH_FILE) {
            snprintf(g_path, sizeof g_path, "%s/disc.iso", where);
            kind = plat_path_kind(g_path, &size);
        }
    } else {
        snprintf(g_path, sizeof g_path, "%s", where);
    }
    if (kind != PLAT_PATH_FILE) {
        say_kind(g_path, kind, why, cap);
        return refused();
    }
    g_f = plat_fopen_rb(g_path); /* a /proc/self/fd/N path is read through N itself (plat.h) */
    if (!g_f) return refuse(why, cap, "cannot open %s: %s", g_path, strerror(errno));
    g_file_size = g_info.image_size = size;
    if (size >= sizeof magic && !raw_read(0, magic, sizeof magic)) return refuse_read(why, cap);
    if (size >= sizeof magic && !memcmp(magic, STORE_MAGIC, 8)) {
        if (open_store(size, why, cap)) return 1;
        size = g_info.image_size;
    } else {
        g_covered = size;
    }
    if (g_covered < BOOT_SIZE)
        return refuse(why, cap, "%s is %llu bytes, too short to be a GameCube disc image", g_path,
                      (unsigned long long)g_covered);
    if (!read_at(0, g_boot, BOOT_SIZE)) return refuse_read(why, cap);
    if (say_boot(g_path, g_boot, why, cap)) return refused();
    game_id(g_boot, g_info.game_id);
    g_info.disc_number = g_boot[6];
    g_info.revision = g_boot[7];

    /* The executable: its header, then as far as its furthest section. */
    dol_off = be32(g_boot + 0x420);
    if (dol_off > g_covered || g_covered - dol_off < DOL_HEADER)
        return refuse(why, cap, "%s: the executable's header at 0x%llX lies past the image's end (%llu bytes)",
                      g_path, (unsigned long long)dol_off, (unsigned long long)g_covered);
    if (!read_at(dol_off, head, DOL_HEADER)) return refuse_read(why, cap);
    for (i = 0; i < 18; i++) {
        uint64_t off = be32(head + 4 * i), len = be32(head + 0x90 + 4 * i);
        if (len && off + len > dol_n) dol_n = off + len;
    }
    if (dol_n < DOL_HEADER || dol_n > DOL_MAX)
        return refuse(why, cap, "%s: the executable claims %llu bytes, which no GameCube DOL is", g_path,
                      (unsigned long long)dol_n);
    if (dol_n > g_covered - dol_off)
        return refuse(why, cap,
                      "%s: a section of the executable lies past the image's end (it needs %llu bytes from "
                      "0x%llX, and the image is %llu)",
                      g_path, (unsigned long long)dol_n, (unsigned long long)dol_off, (unsigned long long)g_covered);
    g_dol_n = (size_t)dol_n;
    g_dol = (uint8_t*)malloc(g_dol_n);
    if (!g_dol) return refuse(why, cap, "%s: no memory for the executable", g_path);
    if (!read_at(dol_off, g_dol, g_dol_n)) return refuse_read(why, cap);
    /* The translated code is this executable's: any other would run the old
     * code over new data with nothing saying so (section 3.3). */
    sha1_hex(g_dol, g_dol_n, got);
    snprintf(want, sizeof want, "%s", DISC_DOL_SHA1);
    if (strcmp(got, want) != 0 && g_phone)
        return refuse(why, cap,
                      "this image's executable is not the one this app plays (a patched image, or a damaged "
                      "copy?): %s has SHA-1 %s, and this app's is %s",
                      g_path, got, want);
    if (strcmp(got, want) != 0)
        return refuse(why, cap,
                      "this image's executable is not the one this port was built for: %s has SHA-1 %s, and "
                      "the port was built from %s",
                      g_path, got, want);

    /* The file table. */
    fst_off = be32(g_boot + 0x424);
    fst_n = be32(g_boot + 0x428);
    if (fst_off >= g_covered)
        return refuse(why, cap, "%s: the file table starts at 0x%llX, past the image's end (%llu bytes)", g_path,
                      (unsigned long long)fst_off, (unsigned long long)g_covered);
    if (fst_n < 12 || fst_n > FST_MAX)
        return refuse(why, cap, "%s: the file table claims %llu bytes, which no GameCube disc's is", g_path,
                      (unsigned long long)fst_n);
    if (fst_n > g_covered - fst_off)
        return refuse(why, cap,
                      "%s: the image ends inside the file table (%llu of its %llu bytes are there): a "
                      "truncated dump?",
                      g_path, (unsigned long long)(g_covered - fst_off), (unsigned long long)fst_n);
    g_fst_n = (size_t)fst_n;
    g_fst = (uint8_t*)malloc(g_fst_n);
    if (!g_fst) return refuse(why, cap, "%s: no memory for the file table", g_path);
    if (!read_at(fst_off, g_fst, g_fst_n)) return refuse_read(why, cap);
    if (!index_fst()) return refuse(why, cap, "%s: the file table is malformed", g_path);
    /* Every file inside the image: one cut short after its file table, a
     * dump or a copy that stopped early, would otherwise open, and the game
     * read zeros where its files should be. The extents are sorted, so the
     * first past the end is where the cut is. (A store is bounded when it is
     * written, tools/soa/store.py.) */
    for (k = 0; k < g_ext_n; k++)
        if (g_ext[k].size && g_ext[k].off + g_ext[k].size > g_covered)
            return refuse(why, cap,
                          "%s: its file table puts %s at 0x%llX (+%u bytes), and the %s ends at 0x%llX: a "
                          "truncated dump or copy?",
                          g_path, g_names + g_ext[k].name, (unsigned long long)g_ext[k].off, g_ext[k].size,
                          g_store ? "stored image" : "image", (unsigned long long)g_covered);
    sha1_hex(g_boot, BOOT_SIZE, boot_sha);
    sha1_hex(g_fst, g_fst_n, fst_sha);
    /* The stale-disc guard (I3): with the build's own file table built in,
     * an image whose table differs -- a patched or another image -- would
     * boot with offsets pointing at the wrong bytes. On a phone the remedy
     * may be the other half: a library made from another image. */
    if (built == 1 && (disc_sys_fst_size != g_fst_n || memcmp(disc_sys_fst, g_fst, g_fst_n) != 0)) {
        g_by_build = 1;
        if (g_phone)
            return refuse(why, cap,
                          "this disc image is not the one this game library was made from (a patched or "
                          "different image?): %s has file table SHA-1 %s, and the library's is %s: pick the "
                          "image the library was made from, or make the game library again from this one with "
                          "Setup on your PC",
                          g_path, fst_sha, disc_sys_fst_sha1);
        return refuse(why, cap,
                      "this disc image is not the one this build was made from (a patched or different "
                      "image?): %s has file table SHA-1 %s, and the build's is %s; rebuild from it with "
                      "python tools/recompile.py --link, or use the image it was built from",
                      g_path, fst_sha, disc_sys_fst_sha1);
    }
    if (arm_checks(where, why, cap)) return 1;

    g_info.covered_end = g_covered;
    g_info.backend = g_store ? "store" : "iso";
    g_info.path = g_path;
    g_open = 1;
    env = getenv("SOA_DISC_LOG");
    g_log = env && *env && strcmp(env, "0") != 0;
    if (g_store)
        fprintf(stderr, "[disc] %s: %s rev %u store v1, image to 0x%llX of 0x%llX, %u extents, %u blocks, %s; "
                        "DOL %s, boot.bin %s, FST %s%s\n",
                g_path, g_info.game_id, g_info.revision, (unsigned long long)g_covered, (unsigned long long)size,
                g_store_ext_n, g_block_n,
                (g_flags & 3) == 3 ? "verified dump" : (g_flags & 2) ? "the files verified, the padding not"
                                                                      : "not checked against pinned hashes",
                got, boot_sha, fst_sha, g_builtin == 1 ? "; FST matches this build" : "");
    else
        fprintf(stderr, "[disc] %s: %s rev %u disc image, %llu bytes; DOL %s, boot.bin %s, FST %s%s\n", g_path,
                g_info.game_id, g_info.revision, (unsigned long long)size, got, boot_sha, fst_sha,
                g_builtin == 1 ? "; FST matches this build" : "");
    return 0;
}

/* The checks disc_open makes first, on as much of the file as there is: a
 * store says its game id and revision in its header, so its first 4 KiB do,
 * and an ISO's are in its first 0x440 bytes. Its own FILE, so a disc that is
 * open stays open, and the same words, so a player hears one thing of one
 * file. */
int disc_identify(const char* path, char* why, size_t cap)
{
    uint8_t h[STORE_HEADER];
    uint64_t size = 0;
    size_t want, n = 0;
    int kind = plat_path_kind(path, &size), err = 0;
    FILE* f;
    if (kind != PLAT_PATH_FILE) return say_kind(path, kind, why, cap);
    f = plat_fopen_rb(path);
    if (!f) return say(why, cap, "cannot open %s: %s", path, strerror(errno));
    want = size < sizeof h ? (size_t)size : sizeof h;
    if (plat_fseek64(f, 0) != 0) /* a descriptor's offset is shared: from the start, always */
        err = errno ? errno : EIO;
    else if ((n = fread(h, 1, want, f)) < want && ferror(f))
        err = errno ? errno : EIO;
    fclose(f);
    if (n < want) {
        read_words(why, cap, path, 0, want, UINT64_MAX, err, size);
        return 1;
    }
    if (n >= 8 && !memcmp(h, STORE_MAGIC, 8)) {
        if (n < STORE_HEADER) return say(why, cap, "%s: too short to be a disc store", path);
        if (say_store(path, h, why, cap)) return 1;
        return say_id(path, h + 0x40, h[0x47], why, cap);
    }
    if (n < BOOT_SIZE)
        return say(why, cap, "%s is %llu bytes, too short to be a GameCube disc image", path, (unsigned long long)size);
    return say_boot(path, h, why, cap);
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

/* The broken built-in part, said in the words of the moment it is asked:
 * disc_set_phone_words may come after the first ask. */
static void builtin_words(char* why, size_t cap)
{
    const char* fix = g_phone ? ": " PHONE_REBUILD : "";
    if (g_builtin_bad == 1)
        snprintf(why, cap, "the system files built into %s are the wrong sizes%s", build_noun(), fix);
    else if (g_builtin_bad == 2 && g_phone)
        snprintf(why, cap, "the executable built into %s hashes to %s, not its own %s and this app's %s%s",
                 build_noun(), g_builtin_hex, disc_sys_dol_sha1, DISC_DOL_SHA1, fix);
    else if (g_builtin_bad == 2)
        snprintf(why, cap,
                 "the executable built into %s hashes to %s, not its own %s and the port's %s (a generator or "
                 "byte-order fault); rebuild with python tools/recompile.py --link",
                 build_noun(), g_builtin_hex, disc_sys_dol_sha1, DISC_DOL_SHA1);
    else
        snprintf(why, cap, "the %s built into %s hashes to %s, not its own %s%s",
                 g_builtin_bad == 3 ? "boot.bin" : "file table", build_noun(), g_builtin_hex,
                 g_builtin_bad == 3 ? disc_sys_boot_sha1 : disc_sys_fst_sha1, fix);
}

int disc_builtin(char* why, size_t cap)
{
#ifdef SOA_SPLIT
    /* the library comes before the disc (specs/android.md L12d): without it
     * there is nothing to ask, and nothing is remembered */
    if (!soa_game_table) {
        snprintf(why, cap, "no game library is loaded yet, and a disc is checked against the one it was made from");
        return -1;
    }
#endif
    if (g_builtin == 0) {
        g_builtin = -1;
        if (disc_sys_dol_size == 0)
            g_builtin = 2; /* --no-embed: the image's own are read */
        else if (disc_sys_boot_size != BOOT_SIZE || disc_sys_fst_size < 12)
            g_builtin_bad = 1;
        else if (!hashes_to(disc_sys_dol, disc_sys_dol_size, disc_sys_dol_sha1, g_builtin_hex) ||
                 strcmp(g_builtin_hex, DISC_DOL_SHA1) != 0)
            g_builtin_bad = 2;
        else if (!hashes_to(disc_sys_boot, BOOT_SIZE, disc_sys_boot_sha1, g_builtin_hex))
            g_builtin_bad = 3;
        else if (!hashes_to(disc_sys_fst, disc_sys_fst_size, disc_sys_fst_sha1, g_builtin_hex))
            g_builtin_bad = 4;
        else
            g_builtin = 1;
    }
    if (g_builtin < 0) builtin_words(why, cap);
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
    if (g_open && offset < g_covered) {
        uint64_t room = g_covered - offset;
        got = room < length ? (uint32_t)room : length;
        read_or_stop(offset, dst, got); /* zeros only past the image's end, never for a read that failed */
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

/* Block k against its digest: 1 when it matches. A block that cannot be
 * read stops the run as what it is: it was never shown to differ. */
static int block_ok(uint32_t k, uint8_t* buf)
{
    uint64_t lo = (uint64_t)k * STORE_BLOCK;
    uint32_t n = g_covered - lo < STORE_BLOCK ? (uint32_t)(g_covered - lo) : STORE_BLOCK;
    uint8_t digest[20];
    read_or_stop(lo, buf, n);
    sha1(buf, n, digest);
    return memcmp(digest, g_blocks + (size_t)k * STORE_DIGEST, STORE_DIGEST) == 0;
}

/* Every block a drive read touches, hashed the first time (I5): the game is
 * stopped before it sees a byte of a block that is not what was imported. */
static void verify_blocks(uint64_t offset, uint32_t length)
{
    static uint8_t* buf;
    uint64_t end = offset + length < g_covered ? offset + length : g_covered;
    uint32_t k;
    if (offset >= end) return;
    if (!buf && !(buf = (uint8_t*)malloc(STORE_BLOCK))) {
        stop_said(DISC_STOP_MEMORY, "There was no memory left to check %s: close other apps and start the game "
                  "again.", g_path);
        stop("no memory to hash the store's blocks");
    }
    for (k = (uint32_t)(offset / STORE_BLOCK); (uint64_t)k * STORE_BLOCK < end; k++) {
        uint64_t t0;
        if (g_seen[k / 8] & (1u << (k % 8))) continue;
        t0 = plat_mono_ns();
        if (!block_ok(k, buf)) {
            char names[600];
            const char* fix = g_phone ? PHONE_RECOPY : PC_REIMPORT;
            if (files_in((uint64_t)k * STORE_BLOCK, (uint64_t)(k + 1) * STORE_BLOCK, names, sizeof names))
                stop_said(DISC_STOP_DAMAGED,
                          "%s is damaged: the part of it holding %s is not what was stored there; %s.", g_path,
                          names, fix);
            else
                stop_said(DISC_STOP_DAMAGED, "%s is damaged: a part of it is not what was stored there; %s.", g_path,
                          fix);
            stop("block %u of %s (0x%llX) does not match its SHA-1: %s; the store is damaged%s", k, g_path,
                 (unsigned long long)k * STORE_BLOCK, names, g_phone ? ": " PHONE_RECOPY : " -- " PC_REIMPORT);
        }
        g_hash_ns += plat_mono_ns() - t0;
        g_hashed++;
        g_seen[k / 8] |= (uint8_t)(1u << (k % 8));
    }
}

/* The read again from the ISO, compared byte for byte (SOA_DISC_VERIFY=iso). */
static void verify_iso(uint64_t offset, const uint8_t* got, uint32_t length)
{
    static uint8_t* buf;
    static uint32_t cap;
    uint32_t n = 0, i;
    if (offset + length > g_covered) g_vpast++;
    if (length > cap) {
        free(buf);
        buf = (uint8_t*)malloc(length);
        cap = buf ? length : 0;
    }
    if (!buf) {
        stop_said(DISC_STOP_MEMORY, "There was no memory left to check %s: close other apps and start the game "
                  "again.", g_path);
        stop("no memory to compare a read with %s", g_iso_path);
    }
    if (plat_fseek64(g_iso, (int64_t)offset) == 0) n = (uint32_t)fread(buf, 1, length, g_iso);
    if (n < length) memset(buf + n, 0, length - n);
    g_vreads++;
    g_vbytes += length;
    for (i = 0; i < length && got[i] == buf[i]; i++) {}
    if (i < length) {
        const char* name = disc_name_at(offset, NULL, NULL);
        g_vdiffer++;
        fprintf(stderr, "[disc] verify: the read at 0x%llX +%u (%s) differs from %s, first at disc offset 0x%llX\n",
                (unsigned long long)offset, length, name ? name : "no file", g_iso_path,
                (unsigned long long)(offset + i));
    }
}

void disc_serve(uint64_t offset, uint8_t* dst, uint32_t length)
{
    uint32_t got;
    if (g_verify & VERIFY_HASH) verify_blocks(offset, length);
    got = disc_peek(offset, dst, length);
    if (got < length) {
        /* A truncated image otherwise has no diagnostic at all: the game
         * just gets zeros where an asset should be. Once is enough. */
        if (g_open && !g_past_reads)
            fprintf(stderr, "[disc] a read at %llu reaches past the %s's end (+%u bytes of zeros)%s\n",
                    (unsigned long long)offset, g_store ? "stored image" : "image", (unsigned)(length - got),
                    g_store ? "" : "; the image looks incomplete");
        g_past_reads++;
        g_past_bytes += length - got;
    }
    if (g_verify & VERIFY_ISO) verify_iso(offset, dst, length);
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

int disc_check_store(const char* where)
{
    char why[1024], names[600];
    uint8_t* buf;
    uint32_t k, bad_blocks = 0, bad_extents = 0;
    uint64_t t0 = plat_mono_ns();
    if (disc_open(where, why, sizeof why) != 0) {
        fprintf(stderr, "[disc] check: %s\n", why);
        return 9;
    }
    if (!g_store) {
        fprintf(stderr, "[disc] check: %s is an ISO, which holds no hashes to check; --check-disc is for a store\n",
                g_path);
        return 9;
    }
    buf = (uint8_t*)malloc(STORE_BLOCK);
    if (!buf) return 9;
    for (k = 0; k < g_block_n; k++)
        if (!block_ok(k, buf)) {
            files_in((uint64_t)k * STORE_BLOCK, (uint64_t)(k + 1) * STORE_BLOCK, names, sizeof names);
            if (bad_blocks++ < 8)
                fprintf(stderr, "[disc] check: block %u (0x%llX) does not match its SHA-1: %s\n", k,
                        (unsigned long long)k * STORE_BLOCK, names);
        }
    free(buf);
    for (k = 0; k < g_store_ext_n; k++) {
        const uint8_t* row = g_store_ext + (size_t)k * STORE_EXTENT;
        uint64_t off = le64(row), len = le64(row + 8);
        uint8_t* data, digest[20];
        if (off > g_covered || len > g_covered - off || len > (64u << 20)) {
            bad_extents++;
            continue;
        }
        data = (uint8_t*)malloc(len ? (size_t)len : 1);
        if (!data) {
            bad_extents++;
            continue;
        }
        read_or_stop(off, data, (size_t)len);
        sha1(data, (size_t)len, digest);
        free(data);
        if (memcmp(digest, row + 32, 20) != 0) {
            files_in(off, off + len, names, sizeof names);
            if (bad_extents++ < 8)
                fprintf(stderr, "[disc] check: the extent at 0x%llX (+%llu) does not match its SHA-1: %s\n",
                        (unsigned long long)off, (unsigned long long)len, names);
        }
    }
    fprintf(stderr, "[disc] check: %s: %u blocks and %u extents hashed in %.1f s, %u and %u differ; %s\n", g_path,
            g_block_n, g_store_ext_n, (double)(plat_mono_ns() - t0) / 1e9, bad_blocks, bad_extents,
            bad_blocks || bad_extents ? "the store is damaged: re-import it"
            : (g_flags & 3) == 3     ? "a verified dump"
            : (g_flags & 2)          ? "the files are the pinned ones, the padding not"
                                     : "it was not checked against pinned hashes at import");
    if (g_flip != UINT64_MAX && !g_flip_read)
        fprintf(stderr, "[disc] flip armed at 0x%llX (%s), never read\n", (unsigned long long)g_flip, g_flip_said);
    return bad_blocks || bad_extents ? 9 : 0;
}

void disc_report(void)
{
    if (!g_open) return;
    fprintf(stderr, "[disc] backend %s; %llu reads past the %s's end (%llu bytes of zeros)\n", g_info.backend,
            (unsigned long long)g_past_reads, g_store ? "stored image" : "image",
            (unsigned long long)g_past_bytes);
    if (g_verify & VERIFY_HASH)
        fprintf(stderr, "[disc] hashed %llu blocks (%.1f MB) in %.1f ms\n", (unsigned long long)g_hashed,
                (double)g_hashed * STORE_BLOCK / 1048576.0, (double)g_hash_ns / 1e6);
    if (g_verify & VERIFY_ISO)
        fprintf(stderr, "[disc] verify: %llu reads compared with %s, %llu bytes, %llu differ, %llu past the stored "
                        "image\n",
                (unsigned long long)g_vreads, g_iso_path, (unsigned long long)g_vbytes,
                (unsigned long long)g_vdiffer, (unsigned long long)g_vpast);
    if (g_flip != UINT64_MAX && !g_flip_read)
        fprintf(stderr, "[disc] flip armed at 0x%llX (%s), never read\n", (unsigned long long)g_flip, g_flip_said);
}
