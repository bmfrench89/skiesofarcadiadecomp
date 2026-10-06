/*
 * The import's portable half (specs/android.md L12d, the settled design's
 * decisions 16-18): what the phone does with a descriptor its file picker
 * handed over -- read it in place, or copy it -- and the copy itself.
 * runtime/android.c holds the flow and the calls into Java; the decisions are
 * here, in C for Linux's kernel, which is Android's, so CI's Linux legs hold
 * them (tools/tests/test_import.py) where no phone is. Off Linux -- on
 * Windows -- the calls that touch files refuse, saying so, and every runtime
 * file still compiles on every system; import_sniff, import_copy_name and
 * import_name_in only look at bytes and are the same everywhere.
 *
 * A picked file reaches the app only as a descriptor N, so these words name
 * it /proc/self/fd/N, and a copy by its .tmp's path. import_name_in puts the
 * name the player picked in place of either before a message is shown.
 */
#ifndef SOA_IMPORT_H
#define SOA_IMPORT_H
#include <stddef.h>
#include <stdint.h>

/* Decision 17's numbers. A copy leaves IMPORT_MARGIN free on its folder's
 * filesystem, so a full device never costs the memory card its next write.
 * A disc's copy may be IMPORT_DISC_LIMIT at most, a library's
 * IMPORT_LIBRARY_LIMIT (the real ones are 1.4 GB and 31 MB). A stream's
 * first IMPORT_DISC_PEEK bytes are checked (disc_identify) before the rest
 * is read, or a library's first IMPORT_LIBRARY_PEEK (its ELF header). */
#define IMPORT_MARGIN ((uint64_t)512 << 20)
#define IMPORT_DISC_LIMIT ((uint64_t)2 << 30)
#define IMPORT_LIBRARY_LIMIT ((uint64_t)256 << 20)
#define IMPORT_DISC_PEEK ((uint64_t)1 << 20)
#define IMPORT_LIBRARY_PEEK ((uint64_t)64)
/* What import_sniff needs to tell every kind apart: the head import_head
 * takes before a copy is named. */
#define IMPORT_HEAD 64

/* import_head's and import_copy's answers. */
enum { IMPORT_OK = 0, IMPORT_REFUSED = 1, IMPORT_CANCELLED = 2 };

/* What a descriptor is: a regular file that seeks, which can be read in
 * place; a stream -- a pipe, a socket, or a file that will not seek -- which
 * can be read only once, in order, so it is copied; or neither (a folder, a
 * device, or no descriptor at all). The kind, and the size in *size: a
 * file's, or -1. */
enum { IMPORT_FILE = 1, IMPORT_STREAM, IMPORT_OTHER };
int import_classify(int fd, int64_t* size);

/* Whether the disc behind fd, picked from the provider `authority`, may be
 * read in place on every launch (decision 16): 1, or 0 with *reason saying
 * why it is copied instead, in the [android] line's words, asked in this
 * order:
 * - "a stream (a pipe or a socket)": anything but a regular file that seeks;
 * - "not this phone's storage": an authority but the phone's own three,
 *   compared whole --
 *     com.android.externalstorage.documents
 *     com.android.providers.downloads.documents
 *     com.android.providers.media.documents
 *   -- since a cloud's provider would otherwise be asked for 1.4 GB on every
 *   launch;
 * - "a proxy (/mnt/appfuse)": a regular descriptor a provider serves on
 *   demand, as a cloud's does, which /proc/self/fd/N shows under /mnt/appfuse;
 * - "the permission could not be kept": kept 0, when the grant could not be
 *   made to outlive this launch. */
int import_in_place(const char* authority, int fd, int kept, const char** reason);

/* Bytes this app may still write on the filesystem holding dir (statvfs), or
 * -1 when it cannot be asked. */
int64_t import_free(const char* dir);

/* What a file is, from its first n bytes: a game library or another ELF, a
 * Windows program or library (PE: "MZ"), a disc store (SOADISC1), a
 * GameCube image (an ISO or GCM: the boot magic at 0x1C), Dolphin's RVZ or
 * WIA, or none of these. */
enum { IMPORT_UNKNOWN, IMPORT_ELF, IMPORT_PE, IMPORT_STORE, IMPORT_ISO, IMPORT_RVZ };
int import_sniff(const uint8_t* b, size_t n);

/* The name a copy of a file of that kind is given: by its content, never by
 * the name its provider reports, which any installed app controls (it could
 * be ../libsoa_game.so). "disc.soadisc" for a store, "libsoa_game.so" for an
 * ELF, and "disc.iso" for anything else: an ISO or GCM, or what
 * disc_identify will refuse once the copy's first bytes are in. */
const char* import_copy_name(int kind);

/* A copy, and what reads a picked descriptor: import_head reads fd, progress
 * and user; import_copy all of it. A disc's copy, as android.c makes one:
 *
 *     ImportCopy c = {.fd = fd, .dir = copy_dir, .expect = size, .limit = IMPORT_DISC_LIMIT,
 *                     .peek_at = IMPORT_DISC_PEEK, .peek = identify, .progress = shown, .user = &ui};
 *     uint8_t head[IMPORT_HEAD];
 *     size_t n;
 *     if (import_head(&c, head, sizeof head, &n, why, sizeof why) != IMPORT_OK) ...
 *     c.head = head;   (a stream's first bytes are gone from it: they come from here)
 *     c.nhead = n;
 *     c.name = import_copy_name(import_sniff(head, n));
 *     if (import_copy(&c, &copied, why, sizeof why) != IMPORT_OK) ...
 *     ...then import_place(<dir>/<name>.tmp, <dir>/<name>, 0, why, sizeof why). */
typedef struct {
    int fd;                /* the picked descriptor, left open */
    const uint8_t* head;   /* bytes import_head took from it, which come first; NULL for none */
    size_t nhead;
    const char* dir;       /* the copy is made as <dir>/<name>.tmp; dir must exist */
    const char* name;      /* import_copy_name's */
    /* The size the provider gave, or -1 when it gave none; 0 counts as none,
     * as some providers say 0 for a size they do not know. */
    int64_t expect;
    uint64_t limit;       /* the most it may be: IMPORT_DISC_LIMIT or IMPORT_LIBRARY_LIMIT */
    uint64_t peek_at;      /* peek is asked once this many bytes are in, or at the end if fewer came */
    /* 0 to go on; nonzero refuses the copy, with why. Given the .tmp's path
     * while it holds exactly `have` bytes, as disc_identify wants a file. */
    int (*peek)(const char* tmp, uint64_t have, void* user, char* why, size_t cap);
    /* 0 to go on; nonzero cancels (the progress dialog's button). Asked at
     * the start, then once a further MiB is in or a quarter second has
     * passed, whichever comes first, silent or not, so Cancel answers at
     * once on a slow provider and on one that has stopped sending. */
    int (*progress)(uint64_t done, int64_t expect, void* user);
    void* user;
} ImportCopy;

/* The first bytes of what c->fd holds, at most n, into b, how many in *got
 * (fewer only at its end), for import_sniff before a copy is named: a file's
 * read where they lie, its offset left alone; a stream's taken from it, so
 * they must go to import_copy as c->head. IMPORT_OK; IMPORT_CANCELLED when
 * c->progress, asked while a stream is silent, says stop; IMPORT_REFUSED with
 * why ("cannot read /proc/self/fd/N: ..."). */
int import_head(const ImportCopy* c, uint8_t* b, size_t n, size_t* got, char* why, size_t cap);

/* c->head, then the rest of c->fd -- a file's from offset c->nhead by pread,
 * wherever a check that read it through a dup left its offset; a stream's
 * from where it stands -- into <dir>/<name>.tmp, replacing any .tmp left from
 * before. Before a byte is written, a size over c->limit is refused, and with
 * a size given the filesystem must have it and IMPORT_MARGIN more free, and
 * the .tmp is allocated whole (fallocate), so a device that is too full says
 * so now rather than at 90%. With none given, the free space is looked at
 * before each MiB is written, and the copy stops where that MiB would leave
 * less than IMPORT_MARGIN free. At the end the count is held to the size
 * given, since a provider that dies mid-stream looks like a clean end once
 * its descriptor is detached: short is "the copy stopped at <n> of <size>
 * bytes". c->peek's refusal is "the copy was stopped after <have> of <size>
 * bytes: <its why>". The .tmp is synced and made 0444, and then waits for
 * import_place.
 * IMPORT_OK with the count in *copied; IMPORT_CANCELLED or IMPORT_REFUSED
 * with why. Either way the .tmp is gone, and nothing else in dir was touched:
 * a refused copy never costs the file it would have replaced. */
int import_copy(const ImportCopy* c, uint64_t* copied, char* why, size_t cap);

/* The finished tmp put in final's place in one rename, then their folder
 * synced, so the rename survives a power cut; the two are in one folder, as
 * a rename cannot cross filesystems. With keep_old, final is first renamed
 * <final>.old (replacing an older one), to be put back if the new one will
 * not load; without, final is simply replaced. A 0444 final is no obstacle:
 * a rename asks only the folder's permission. 0, or nonzero with why and
 * final as it was. */
int import_place(const char* tmp, const char* final, int keep_old, char* why, size_t cap);

/* Every regular file named *.tmp in dir removed: what a process killed
 * mid-copy left. How many; 0 when dir does not exist; -1 when it cannot be
 * read. */
int import_sweep(const char* dir);

/* text written to path through <path>.tmp, synced and put in place, so a
 * reader finds the old text or the new and never part of either: disc.txt
 * and soa.ini, for the app alone (0600). 0, or nonzero with why. */
int import_write_text(const char* path, const char* text, char* why, size_t cap);

/* A check run's line about the descriptor (decision 24): the path it was
 * opened as, its filesystem's f_type, and what opening /proc/self/fd/N by
 * name -- what disc.c did before L12d -- gives:
 * "<path>, f_type 0x<hex>, open by name: ok|<strerror>". */
void import_probe(int fd, char* out, size_t cap);

/* Each whole occurrence of internal in why -- not one inside a longer path,
 * as /proc/self/fd/7 is in /proc/self/fd/71 -- replaced by display, within
 * cap and cut only between characters, so a message names the file the
 * player picked rather than a descriptor or a copy. */
void import_name_in(char* why, size_t cap, const char* internal, const char* display);

#endif
