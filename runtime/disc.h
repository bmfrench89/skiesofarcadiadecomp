/*
 * Where the game's disc bytes come from (docs/specs/disc-layer.md §3.2): one
 * file owns every byte the game gets from its disc. dvd.c keeps the drive's
 * registers and clock and asks disc_serve for a read; main.c asks
 * disc_system for the executable, boot.bin and the file table; aram.c's
 * census asks for names and 32-byte heads. Every function is safe before
 * disc_open, answering "nothing".
 *
 * I1 is the ISO backend: an .iso or .gcm file, or a directory holding
 * disc.iso. I3 builds the executable, boot.bin and the file table into
 * soa.exe. I5 is the store backend: GEAE8P.soadisc, preferred in a
 * directory, each 64 KiB block checked against its SHA-1 at first touch
 * (SOA_DISC_VERIFY). Mods' files (I6-I8) come later, behind these same
 * calls.
 */
#ifndef SOA_DISC_H
#define SOA_DISC_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    char game_id[7];      /* "GEAE8P" */
    uint8_t disc_number, revision;
    uint64_t image_size;  /* the image's size: 0x57058000 for a full dump */
    uint64_t covered_end; /* offsets below this come from the image; = image_size for an ISO */
    const char* backend;  /* "iso" */
    const char* path;
} DiscInfo;

/* Open a directory holding disc.iso, or an .iso/.gcm file, and check it is
 * this port's disc (§3.3): GameCube boot magic, the game id and revision
 * this port was built for, an executable whose SHA-1 is the one the
 * translated code came from, and every file in its table inside the image.
 * 0 when open, printing the [disc] line; otherwise nonzero with the reason in
 * `why`, which names the fix. A build whose own system files are broken
 * (disc_builtin < 0) refuses every disc. */
int disc_open(const char* where, char* why, size_t cap);
const DiscInfo* disc_info(void); /* NULL until disc_open succeeds */
/* The system files built into this soa.exe (I3, <--out>/disc_sys.c): 1 when
 * there and each matches its SHA-1, 0 for a --no-embed build, -1 when they do
 * not match (the reason in `why`), and in a split build -1 until a game
 * library is loaded. With them, disc_open refuses an image whose file table
 * is not the build's, and nothing needs an image open to have the
 * executable: the self test and --replay open none. */
int disc_builtin(char* why, size_t cap);
/* The executable, boot.bin (0x440 bytes) and fst.bin: the build's own when
 * built in, else the open image's. */
int disc_system(const uint8_t** dol, size_t* dol_n, const uint8_t** boot, const uint8_t** fst,
                size_t* fst_n, char* why, size_t cap);
/* The drive's read: the image's bytes, zeros past its end. Counted, and with
 * SOA_DISC_LOG=1 one [disc] line each. A read that fails inside the image --
 * its storage gone, the file shorter than it was at the open -- stops the
 * run, exit 9, saying why; it is never served as zeros. */
void disc_serve(uint64_t offset, uint8_t* dst, uint32_t length);
/* The same bytes for diagnostics (the census): not counted or logged. The
 * answer is how many came from the image; the rest of dst is zeros. A failed
 * read stops the run as disc_serve's does. */
uint32_t disc_peek(uint64_t offset, uint8_t* dst, uint32_t length);
/* The file whose extent holds offset, as its full path on the disc; NULL for
 * padding and the system area. */
const char* disc_name_at(uint64_t offset, uint64_t* start, uint32_t* size);
const uint8_t* disc_fst(size_t* n); /* the file table the game sees */
void disc_report(void);             /* end-of-run lines, from dvd_report */
void disc_close(void);              /* back to nothing open (the checks open several) */
/* I5. What runs before exit 9 when the disc layer stops a run (main.c gives
 * hle_report, so the report still prints). */
void disc_set_stop_hook(void (*fn)(void));
/* soa.exe --check-disc: every block and extent of the store at `where` (a
 * folder holding one, or the file) hashed, one line said; 0, or 9 when any
 * differs or it is not a store. */
int disc_check_store(const char* where);

/* ---- T1, the virtual disc (I6, docs/specs/disc-layer.md §3.8; vfst.c) ---- */
#define DISC_OVERLAY_BASE 0x57060000ull /* the image's end plus 32 KiB */
#define DISC_OVERLAY_END 0x80000000ull  /* the game's reads may take an offset as signed */
enum { DISC_REPLACE, DISC_ADD, DISC_ALIAS };
/* One files.txt line of an accepted-so-far mod, in load order then line order.
 * The build fills offset, and refused for every line of a mod it refuses. */
typedef struct {
    int verb;
    char path[256];      /* on the disc, as the FST names it (matched case-insensitively) */
    char target[256];    /* alias: the path it names */
    const uint8_t* data; /* replace, add: the source's bytes, kept by the caller for the run */
    uint32_t size;
    const char* mod;     /* the mod's folder, for messages */
    unsigned line;       /* the files.txt line */
    int mod_index;       /* lines of one mod share it, and stand together */
    int refused, warned;
    uint32_t offset;     /* where it lies on the disc */
} DiscFileOp;
/* The base table rebuilt with ops: 1 with *out (malloc'd) and the virtual
 * extents set for disc_serve; a mod with a fault is refused whole, said, and
 * left out. -1 when two mods place one path (said; the caller stops, exit 9);
 * 0 on an error in `why`, which is a bug. */
int disc_overlay_build(const uint8_t* fst, size_t fst_n, DiscFileOp* ops, int nops, uint8_t** out, size_t* out_n,
                       char* why, size_t cap);
/* The rebuilt table against the base, through a twin of the SDK's walk: every
 * base file where it was or where its replacement is, every added or aliased
 * path where the ops put it, the count base + added. 1, or 0 with why. */
int disc_overlay_check(const uint8_t* base, size_t base_n, const uint8_t* fst, size_t n, const DiscFileOp* ops,
                       int nops, char* why, size_t cap);
uint32_t disc_overlay_read(uint64_t offset, uint8_t* dst, uint32_t length); /* virtual bytes; zeros between */
const char* disc_overlay_name(uint64_t offset, uint64_t* start, uint32_t* size);
int disc_overlay_extents(void);
void disc_overlay_count(uint32_t bytes);
void disc_overlay_report(void);
void disc_overlay_reset(void);
/* The rebuilt table as the one the game sees: disc_fst and disc_name_at answer
 * from it from now on. The bytes are the caller's, kept for the run. */
int disc_overlay_install(const uint8_t* fst, size_t n);

/* ---- L12d: the disc picked on a phone (specs/android.md L12d) ---- */
/* Refusals in a phone's words from now on: none names `python tools/...`,
 * `soa.exe` or `recompile.py`, and a split build says "this game library"
 * where the PC says "this soa.exe". runtime/android.c sets it once, before
 * anything is opened; every other build keeps the PC's words. */
void disc_set_phone_words(int on);
/* Whether the first bytes of the file at `path` -- however many it holds, as
 * a copy in progress does -- could be this port's disc: an ISO, a GCM or a
 * store, with GameCube boot magic, this game id and this revision; RVZ and WIA
 * refused by name. 0, or nonzero and why in disc_open's own words. Needs no
 * game library (a split build's disc_open does) and keeps nothing open. */
int disc_identify(const char* path, char* why, size_t cap);
/* The SHA-1, 40 lowercase hex digits, of the executable this build plays:
 * what disc_open holds a disc's DOL to, and elf_check a game library's
 * record (`dol=`) to. */
const char* disc_port_dol_sha1(void);
/* 1 when the last disc_open was refused because the image's file table is not
 * the one built into the game library (I3): a disc another library could
 * play; 0 otherwise. */
int disc_refused_by_build(void);
/* Why disc.c stopped the run mid-play (exit 9), in a sentence a player can
 * read, the disc named by the path it was opened by: its kind, with the words,
 * from the stop hook on; DISC_STOP_NONE before any stop. runtime/android.c says
 * it on the screen before the app closes, and forgets a damaged disc. */
enum { DISC_STOP_NONE, DISC_STOP_READ, DISC_STOP_DAMAGED, DISC_STOP_MEMORY };
int disc_stop_words(char* out, size_t cap);

#endif
