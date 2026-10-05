/*
 * Where the game's disc bytes come from (docs/specs/disc-layer.md §3.2): one
 * file owns every byte the game gets from its disc. dvd.c keeps the drive's
 * registers and clock and asks disc_serve for a read; main.c asks
 * disc_system for the executable, boot.bin and the file table; aram.c's
 * census asks for names and 32-byte heads. Every function is safe before
 * disc_open, answering "nothing".
 *
 * I1 is the ISO backend: an .iso or .gcm file, or a directory holding
 * disc.iso. The store (I5), the executable built in (I3) and mods' files
 * (I6-I8) come later, behind these same calls.
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
 * this port was built for, and an executable whose SHA-1 is the one the
 * translated code came from. 0 when open, printing the [disc] line;
 * otherwise nonzero with the reason in `why`, which names the fix. */
int disc_open(const char* where, char* why, size_t cap);
const DiscInfo* disc_info(void); /* NULL until disc_open succeeds */
/* The executable, boot.bin (0x440 bytes) and fst.bin, as the image holds them. */
int disc_system(const uint8_t** dol, size_t* dol_n, const uint8_t** boot, const uint8_t** fst,
                size_t* fst_n, char* why, size_t cap);
/* The drive's read: the image's bytes, zeros past its end. Counted, and with
 * SOA_DISC_LOG=1 one [disc] line each. */
void disc_serve(uint64_t offset, uint8_t* dst, uint32_t length);
/* The same bytes for diagnostics (the census): not counted or logged. The
 * answer is how many came from the image; the rest of dst is zeros. */
uint32_t disc_peek(uint64_t offset, uint8_t* dst, uint32_t length);
/* The file whose extent holds offset, as its full path on the disc; NULL for
 * padding and the system area. */
const char* disc_name_at(uint64_t offset, uint64_t* start, uint32_t* size);
const uint8_t* disc_fst(size_t* n); /* the file table the game sees */
void disc_report(void);             /* end-of-run lines, from dvd_report */
void disc_close(void);              /* back to nothing open (the checks open several) */

#endif
