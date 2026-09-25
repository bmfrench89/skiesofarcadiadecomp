<!-- Written 2026-09-25 by the planning session, read-only, at main 3949028. Revised the same day after
two reviews at main b071949 (T0 as 1c7b780 and 4041dfc, N4's acquire loads as c8274db, manifest 2's
follow-up as b071949), then checked again at main 012164a in a consistency review across the five
planning documents (its entries close the review log). Line numbers are b071949's. Since then P6
(24d9235) and its follow-up P6b (79c9ad8) added 4 lines at runtime/main.c:43 and 14 in the recording
block (:1177-1187), so main.c's citations move by 4 from :43 and by 18 past :1187; they also changed
hle.c, selftest.c, settings.c and si.c and added seed.c. C5a (750cef0) moved gx.c's lines past :55 by 115
to 125. T0c (012164a) rewrote much of tools/guard.py, so §2's guard line numbers are b071949's too. At
012164a the working tree held the implementation session's uncommitted P1a. Nothing in the repository was
changed and the game was not run. Read-only work done for it: the code reads cited below, tools/disasm.py
on the SDK's DVD code and the akFio reader, Python passes over extracted/sys/*.bin and extracted/disc.iso
(layout, gaps, hashes, past-the-end reads under the reader's own length rounding; a scratch script plus
inline re-runs), MSVC compile probes of a 3.3 MB array in a scratch directory (re-run interleaved), a
SHA-1 speed probe of mod.c's own code built with toolchain.CFLAGS (a scratch benchmark), and web checks
of the BPS format's licence, xdelta's licence and Redump's hash for this disc. None of the scratch files
is in the repository. The order across all plans is ../PLAN-NEXT.md. [V] = checked in code, the
disassembly, a measurement or a dated page; [I] = inference. Sizes are evenings: hours / a day / several
days / week-plus / months. Rebuild cost: none / --link / one retranslation. Slices use I1, I2, ...; T1 of
PLAN-GAMEPLAY-MODS.md is delivered as I6-I8. The review log at the end says what the reviews changed. -->

# The disc layer: off the ISO, and a virtual disc for mods

## 1. Purpose and scope

**What you get, in plain terms.** Sizes are decimal (1 GB = 10⁹ bytes).

| After | You have | Disk | Size of the work |
|---|---|---|---|
| today | `extracted/` = `disc.iso` (1.46 GB) + 5,552 loose files (1.42 GB) + `sys/` (3.3 MB); the port reads only `sys/` and `disc.iso` | **2.88 GB** (plus your original dump) | — |
| **I2** (step 1a) | The loose files are no longer written, and a command deletes yours after checking each one against the image. Every tool reads through the image. Nothing in the port changes | **1.46 GB** | hours to a day, no rebuild |
| **I1** (the seam) | The port reads everything through one file, `runtime/disc.c`, and runs straight from your own ISO. An image whose executable is not the one this port was built for is refused by name. No space saved: this is the base I3, I5 and T1 build on | same | a day to several days |
| **I3** (step 1b) | `soa.exe` carries the executable, `boot.bin` and the file table. Replays and the self test need no disc. A disc that is not the one the build was made from is refused by name | same | a day |
| **I5a + I4 + I5** (step 1c; I5a only if agreed, §3.4) | One verified file, `GEAE8P.soadisc` (1.43 GB), that the port reads instead of `disc.iso`. Corruption is caught and named at first use. A verify mode proves, read by read, that it serves exactly what the ISO served. After that the ISO can go | **1.43 GB** (only ~28 MB less — see §5) | hours + several days × 2 |
| **I6 + I7 (+ I8)** (T1) | Mods replace, add and alias disc files, edit a file with a small text delta against *your own* copy, and (I8, later) swap a file per map. Two mods naming the same file are stopped by name. Everything a mod places is in the recording | same | several days, a day to several days, a day |

**The single most useful fact for deciding the order:** almost all of the space comes back with **I2 alone** — a tools-only slice of hours to a day, with no rebuild and nothing changed in the port. The port never reads the loose files. Step 1c buys integrity checking and one clean file to copy to a Deck or phone, not space.

**In scope:** `runtime/main.c`'s boot use of the disc, `runtime/dvd.c`'s `disc_read` and its deadline (I5a), `runtime/aram.c`'s census reads, `tools/extract.py` and the tools that read the extracted tree, the store format and importer, the virtual FST (T1), deltas, per-map swaps, the guard, and the tests for all of it without game data.

**Out of scope:** faster loads (the drive model at `dvd.c:149` is kept exactly; see §3.4), recompressing the disc (a codec byte is reserved; §4), an on-device importer for Android (a later slice of the Android track; §7), BPS deltas for shareable packages (with T13; §3.8.6), and NKit/GCZ/WIA/CISO input (G3 names them).

---

## 2. Current state (main b071949)

**Boot** (`runtime/main.c`):
- `:1087` the data directory is `argv[1]` or `extracted`; `:1122-1125` `soa.ini`'s `disc =` replaces it when there is no argument, never for the self test (`settings.c:119-120`, `:143`).
- `:1128-1136` `mem_poke`, `poke_parse`, `peek_parse`, `uncap_parse` and `watch_init` run **before** the disc is read, so their diagnostics print even when there is no disc. `test_memguard`, `test_peek`, `test_poke` and `test_uncap` stop there on purpose ("finds no sys/main.dol and gives up", `test_memguard.py:192-194`).
- `:1139-1149` slurps three files: `<dir>/sys/main.dol` (3,166,656 B), `sys/boot.bin` (1,088 B), `sys/fst.bin` (134,426 B), and refuses if any is missing (exit 1).
- `:1151` `load_dol` (`:963-988`) copies all 18 section slots into MEM1 with difference-form bounds.
- `:1159-1167` bounds `boot.bin` (≥ 0x430) and the FST (under `ARENA_HI` 0x81700000, `:927`). `:1168` `fst_max = be32(boot+0x42C)`; `:1169` `fst_addr = (ARENA_HI - size) & ~31` (0x816DF2E0 today); `:1170` the copy; `:1171` `setup_low_memory` (`:993-1009`) writes 0x80000034/38/3C and the boot magic 0x0D15EA5E at 0x80000020 (`:996`).
- `:1178` `mod_note_dol`; `:1179-1185` `mod_load` (kept after the low-memory block by 2754cba, comment `:1173-1177`). P6 (24d9235) rebuilt this block to compose the recording's extra from `settings_recorded()` and `mod_describe()`, and P6b (79c9ad8) edited it again.
- `:1192-1193` `dvd_init("<dir>/disc.iso")`. `:1195` the self test; `:1196-1204` `--replay`, which overwrites all of MEM1 from the capture's `.ram` (`gx.c:553-556`) — the DOL loaded above is never used by a replay [V]. A replay's `dir` is always `extracted` (`:1087`: `argv[1]` is the switch).

**Tests that compile the boot path** [V]: `test_memguard.py:172-185` builds `main.c`, `mod.c`, `tick.c` and stubs (stubbing `dvd_init`), and `test_peek`, `test_poke` and `test_uncap` reuse that build. `test_profiler.py:132-157` builds the same list and boots it against a fake `disc/sys/` of three zero files (0x100, 0x440, 0x40 B) so the boot path reaches its stubbed guest. `test_mods.py:155-180` compiles `mod.c`, `tick.c` and a driver — never `main.c` — and its `:288-296` checks that `hashlib` agrees with `mod.c`'s own SHA-1.

**The drive** (`runtime/dvd.c`):
- `:79-89` `dvd_init` opens `disc.iso`; a missing image only warns, and every read then returns zeros (`:104-112`, `:209-216`).
- `:91-115` `disc_read`: MEM1 bound written as a difference (`:99`), `_fseeki64` + `fread` (`:103`, the one NDK compile error in `dvd.c`), zero-fill on a short read.
- `:117-153` `execute`: command 0xA8 (read, and read disk ID) at `g_cmd[1] << 2` (`:129`; the drive's offset is in words). **Timing:** `:149` charges 6 ms plus `g_len` at 3 MB/s of guest time; `:151` sets `g_due = tb_now(s) + ticks` *after* the read.
- **The read stops the game while it runs.** `execute` is called inside the guest's own DI register write (`di_write`, `:192`), and guest time is the wall clock times `SOA_SPEED` (`hle.c:294-304`). So the host's read time already passes as guest time with the guest thread frozen, and `:151` then counts it a second time by adding it to the deadline. `:46-50` records why completion cannot be instant.
- Load completion is therefore already timed by the wall clock: it moves in frames with host speed today [V, code]. Scenarios and pad scripts are frame-based and tolerate that; what they must not see is the disc layer adding time of its own.

**The census** (`runtime/aram.c:55-250`): builds a name index from `sys/fst.bin` and a 32-byte read of every file in `disc.iso` (`:196`, `:216`). It finds the directory through MSVC's `__argv` (`:160-172`), so it ignores `soa.ini`'s `disc =` [V, code], and it seeks with `(long)` below 0x7FFF0000. Two files whose first 32 bytes agree are marked ambiguous (−2, `:118-121`) and named by neither.

**The SDK never reads the FST or the disc ID from the disc here** [V]. `DVDInit` (0x8023ACE8) calls `__fstLoad` only when 0x80000020 holds 0xE5207C22 (`0x8023AD60-0x8023AD88`); `main.c:996` writes 0x0D15EA5E. The only two `DVDReadDiskID` calls are inside `__fstLoad` and its callback (`gen/chunk_014.c:6867`, `:6935`).

**The game's path lookup** `DVDConvertPathToEntrynum` (0x8023A4B0) is a linear walk of each directory's range, comparing names case-insensitively through `fn_8025BD6C` and skipping sub-directories by their next index (`0x8023A678-0x8023A768`) [V]. With `__DVDLongFileNameFlag` (r13−27948) clear it takes an 8.3-name branch that reports (`0x8023A578-0x8023A624`); OSInit sets it (content-systems.md §8). Nothing caches entry numbers; openers copy offset and length into their `DVDFileInfo` at open (content-systems.md §8).

**The game's file reader** (akFio's `fn_801C64DC`) [V]: opens by path (`0x801C6528`), reads the first 32 bytes (`0x801C6560`, `addi r5,r0,32`), and tests them for AKLZ — the magic at +0 and `~?Qd` at +4 (`0x801C65A4-0x801C65E8`) and the float 0.1f (0x3DCCCCCD) at +8 (`0x801C65F4-0x801C6600`); a file failing any of the three takes the raw path. For a raw file it rounds the `DVDFileInfo` length up to 32 (`0x801C6628-0x801C662C`), so the read ends at *file start + roundup32(length)*; an AKLZ file is read through a staging buffer of min(length, 0x20000) (`0x801C6648-0x801C66B4`), whose last read is assumed to round the same way [I]. Other code calls `DVDReadAsync` directly (0x80007E2C, 0x80097814, 0x801E36F4, 0x80215D68, 0x80216844, 0x80219790 among others; port-beyond-iso.md:14), and nobody has shown those paths read only raw files [I]. Some reads have a fixed size: `FontData.US` is read as exactly 0x13020 bytes (`0x801E36E8`), its length on the disc (beyond-gamecube.md §4).

**Extraction** (`tools/extract.py`): decodes RVZ (`tools/soa/rvz.py`, junk runs regenerated in `_unpack` at `:129-144`, `junk_bytes` at `:139`, the generator at `:16-75`) or reads ISO/GCM; always writes the 5,552 loose files plus `sys/{boot,bi2,main.dol,fst}.bin` (`tools/soa/disc.py:144-167`); writes `disc.iso` only with `--iso` (`extract.py:76-80`, `:127-139`); checks the DOL SHA-1 against `config/GEAE8P/config.yml:6` (`extract.py:36-58`, `tools/soa/dump.py`). That is the only check of the DOL today: the runtime never hashes it.

**Who reads what in `extracted/`** [V, grep of `tools/` and `runtime/`]:

| Reader | Reads | After I2 / I1 |
|---|---|---|
| `runtime/main.c`, `aram.c` | `sys/` ×3, `disc.iso` | I1: `disc.iso` (or the store) only, through `runtime/disc.c` |
| `recompile.py`, `inventory.py`, `matchcheck.py` (via `decomp.py`), `disasm.py`, `checkdump.py`/`soa/dump.py`, `sct.py` (opcode names), `test_crossval_capstone.py`, dtk (`config.yml` `object:`) | `sys/main.dol` | unchanged: `sys/` (3.3 MB) is still written |
| `scenario.py` (`NEEDED_FILES`, `:128`; `missing_inputs`, `:419-436`) | checks all four | I1: checks the image only |
| `sct.py:219`, `validate_assets.py:85`, `audio_check.py` (and the `.scn` notes that quote it) | loose files | I2: read through the image when the loose file is absent |

**The disc's layout** [V, measured read-only 2026-09-25]:
- FST: 5,560 entries (5,552 files, 7 directories), 134,426 B, `fst_max == fst_size`. No zero-length files, no two files sharing or overlapping an extent, no names differing only in case, longest path 23 characters.
- First file at 0x348000 (the 3,440,640 B before it hold boot.bin, bi2, the apploader, the DOL at 0x1EC00 and the FST at 0x323E00). Last file ends at 0x55337A16 (1,429,436,950); the image is 0x57058000 (1,459,978,240), so 30,541,290 B of tail padding.
- Between files: 2,336 files abut the next; 2,970 gaps are 1–31 bytes and are all zeros; 245 are 12,184–32,621 bytes and hold junk after a short zero run (the first non-zero byte at +28: 76 gaps, +29: 53, +30: 57, +31: 58, +32: 1); 7,958,941 B in all.
- Offsets: 247 files start on a 32 KiB boundary, 9 on 2 KiB, 529 on 32 B, 4,767 on 4 B only.
- Sizes: the largest files are 4,284,399 B and 4,284,330 B (`.dsp` streams); 15 exceed 3 MB, 96 exceed 2 MB, 393 exceed 1 MiB.
- **Reads past a file's end reach real bytes.** FINDINGS §1: "GameCube games routinely read past a file's declared end". 4,610 files have a length that is not a multiple of 32. A read of the file rounded up to 32 bytes from its start (the reader rounds the length, `0x801C6628-0x801C662C`) ends in padding for 600 of them, in the *next file's first bytes* for 4,009, and in the tail for the last file (43,270 B, `ts000899.gvr`). This is what rules out a files-only store (§4).
- Hashes: `disc.iso` SHA-1 `46105320553c858f25fafc5fd357566b505a4940`, CRC32 `23e347b6` — the values Redump's verification thread gives for this disc [V for the local image; the Redump thread `forum.redump.org/post/129269` was quoted by two search summaries and refused a direct fetch; they agreed on the SHA-1 and CRC32 and disagreed on one MD5 digit, so confirm on redump.org before pinning]. `main.dol` SHA-1 `8c0e278126fa3b0173400fdb632038172743cc13` (= `config.yml:6`); `boot.bin` `d7b9c3f09b2e2ad8fcc4ecdfbb2181b4a91b115e`; `fst.bin` `8d8757eb2bc312b279665a634eb5d4dc7b039eab`; the files hash (defined in §3.7.3) `7f185565fdb2f4180d3ed893319f6e1482dc50a3`.

**The recording** (`runtime/si.c:282-304`, the extra set through `si_set_config_extra`, `:287`): the `# config` line carries the `mods=...` string built in `mod_load` (`mod.c:1008-1030`) and returned by `mod_describe` (`:1081`): a manifest 2 mod as `id@version:hash`, a version 1 mod as `folder:hash`. Each mod's hash is FNV-1a over `mod.ini`, `patches.txt` and `mod.dll` (`mod.c:940`). Replay string-compares the line and warns on a difference (`si.c:572-576`). P6 (24d9235) prefixes the recorded settings to the same extra.

**The mod loader's refusals that T1 meets** [V]: a second mod whose `id` is already loaded is refused whole and the run continues (`mod.c:907-908`); a folder with neither `patches.txt` nor `mod.dll` is refused as one that "would do nothing" (`mod.c:932-936`). `MOD_API` is overridable by a test build behind `#ifndef` (`mod.h`, b071949) — the pattern this spec reuses for disc.c's constants.

**The guard** (`tools/guard.py` at b071949, after T0's 1c7b780 and 4041dfc; T0c, 012164a, has since added the card-directory test for a binary file of any length, the GCS and SAV save signatures, every suffix in a name counting, and a content check of history, with the counts unchanged at 43 and 18): 43 suffixes (`:18-70`) and 18 directory names (`:73-96`), the 2 MB size cap (`:122`), CI's regex copy at `ci.yml:34` (a test holds the two equal); a signature check refusing any binary file (a NUL in its first 8 KB) that begins as game data begins — AKLZ, GVR, `GEAE8P` at offset 0, PNG, DDS, Ogg, FLAC, MP3, WAV — whatever it is named (`:109-119`, `:195-205`); and, in a folder holding a `mod.ini`, any file that is not UTF-8 text (`:208-235`). It does not refuse `.exe`, `.obj`, `.pdb` or `.so`; `.gitignore` covers `*.exe`/`*.obj`/`*.pdb`, which is not enforcement.

---

## 3. Design

### 3.1 The shape

```
  DI registers (dvd.c: execute, timing)          main.c boot            aram.c census
                 |                                    |                       |
                 v                                    v                       v
        +------------------------------ runtime/disc.c ------------------------------+
        |  disc_serve(offset,len)    disc_system(dol,boot,fst)    disc_peek / names   |
        |                                                                             |
        |  overlay (I6-I8, vfst.c): virtual extents >= 0x57060000, deltas, swaps      |
        |          |                                                                  |
        |  base backend: ISO / GCM file (I1)   or   GEAE8P.soadisc store (I5)         |
        |  system files: built into gen/ (I3), else read through the base's header    |
        +-----------------------------------------------------------------------------+
```

One C file owns every byte the game gets from its disc. `dvd.c` keeps the registers and the clock; `main.c` asks for the system files; `aram.c` asks for names and 32-byte heads. The overlay sits above whichever base backend is open, so T1 does not wait for the store and the store does not wait for T1. None of it touches `gx.c` or `gxr*.c`: this track can run beside the renderer and GPU work.

### 3.2 `runtime/disc.h` (and the overlay's types)

```c
/* Where the game's disc bytes come from. Every function is safe to call before
 * disc_open (it answers "nothing"). Only disc_overlay_on_map writes guest memory. */

/* What this port was built for. Behind #ifndef, as mod.h's MOD_API is (b071949),
 * so disc_driver.c can build disc.c for a fixture; tools/tests/test_disc_const.py
 * holds DISC_DOL_SHA1 equal to config/GEAE8P/config.yml's hash. */
#ifndef DISC_GAME_ID
#define DISC_GAME_ID "GEAE8P"
#endif
#ifndef DISC_DOL_SHA1
#define DISC_DOL_SHA1 "8c0e278126fa3b0173400fdb632038172743cc13"
#endif

typedef struct {
    char game_id[7];          /* "GEAE8P" */
    uint8_t disc_number, revision;
    uint64_t image_size;      /* the pressed disc's size: 0x57058000 */
    uint64_t covered_end;     /* offsets below this come from the base; = image_size for an ISO */
    const char* backend;      /* "iso" or "store" */
    const char* path;
} DiscInfo;

int  disc_open(const char* where, char* why, size_t cap); /* a directory, an .iso/.gcm, or a .soadisc */
const DiscInfo* disc_info(void);
/* The DOL, boot.bin (0x440) and fst.bin: built-in copies first (I3), else the base's header. */
int  disc_system(const uint8_t** dol, size_t* dol_n, const uint8_t** boot, const uint8_t** fst,
                 size_t* fst_n, char* why, size_t cap);
/* The drive's read: base, overlay, zeros elsewhere. Counts, verifies and logs. */
void disc_serve(uint64_t offset, uint8_t* dst, uint32_t length);
/* The same bytes for diagnostics (the census): not counted, verified or logged. */
int  disc_peek(uint64_t offset, uint8_t* dst, uint32_t length);
/* The first file entry, in FST order, whose extent holds offset; NULL for padding. */
const char* disc_name_at(uint64_t offset, uint64_t* start, uint32_t* size);
const uint8_t* disc_fst(size_t* n);       /* the FST the game will see (after I6's overlay) */
void disc_report(void);                    /* end-of-run lines, from dvd_report */

/* I6: one parsed files.txt line (mod.h), handed from mod.c's pre-pass to the overlay. */
typedef struct {
    uint8_t verb;             /* DISC_OP_REPLACE, _ADD, _ALIAS, _DELTA (I7), _SWAP (I8) */
    char path[256];           /* the path on the disc, as written */
    char src[512];            /* a file in the mod folder, or (alias) a disc path */
    int mod;                  /* index in load order */
    unsigned line;            /* files.txt line, for messages */
    uint32_t map_number;      /* swap only (mod.c's parse_map) */
    uint8_t map_letter;
} DiscFileOp;
int  mod_scan_files(const char* mods_dir, const DiscFileOp** ops, size_t* n);          /* mod.c */
int  disc_overlay_build(const DiscFileOp* ops, size_t n, const uint8_t* base_fst, size_t base_n,
                        uint8_t** fst, size_t* fst_n, char* why, size_t cap);          /* vfst.c */
/* I8 */ void disc_overlay_park(uint32_t fst_addr);   /* main.c, once the FST is parked */
/* I8 */ void disc_overlay_on_map(CpuState* s);       /* tick_on_safe_point's type, tick.c:70 */
```

- Portable C17: `uint32_t`/`uint64_t`, never `long` (the L-track hygiene rule). One 64-bit seek: L2's `plat_fseek64` (`runtime/plat.h`, portability.md L2) if L2 lands first; else a local wrapper (`_fseeki64` under MSVC, `fseeko` with `_FILE_OFFSET_BITS 64` elsewhere) that L2 moves into `plat.h`. Under [../PLAN-NEXT.md](../PLAN-NEXT.md), I1 (M3) lands before L2 (M4a), so the local wrapper is the one written. This removes the `dvd.c:103` NDK error.
- Store header fields are read byte by byte as little-endian; FST fields byte by byte as big-endian. Nothing depends on host byte order except I3's embedded words (§3.6).
- SHA-1 lives in `runtime/sha1.c`/`sha1.h` from I1, moved out of `mod.c` (`:117-151`), used by `disc.c` and `mod.c`.

### 3.3 System files: where they come from

1. **Built in** (I3): `<--out>/disc_sys.c` (`gen/disc_sys.c` by default) defines the DOL, `boot.bin` and `fst.bin` of the disc the build was made from.
2. **Else the base's header** (I1): parse the boot header at 0x420–0x42F (DOL offset, FST offset, FST size, FST max); the DOL's length is the largest `offset + size` over its 18 section slots, bounded to 16 MiB; each slice bounded against the image by differences, as `load_dol` does.

**From I1**, `disc_open` refuses (exit 1) an image whose boot magic is not 0xC2339F3D, whose game id is not `DISC_GAME_ID`, or whose DOL does not hash to `DISC_DOL_SHA1`: "this image's executable is not the one this port was built for", with both hashes. The translated code in `gen/` is the DOL's; a patched or other-revision executable would run the old code over new data with nothing saying so. A patched ISO that keeps the DOL and changes files boots with its own, self-consistent FST; that is what patching an ISO means.

**From I3**, when built-in parts exist, the base's FST must also equal the built-in one byte for byte (the built-in DOL already equals `DISC_DOL_SHA1`, since `recompile.py` refuses any other), or boot stops (exit 1) with "this disc image is not the one this build was made from (a patched or different image?)" and both hashes. That is the stale-disc guard: with a built-in FST, a patched ISO that moves files (T7's case) would otherwise boot with a file table pointing at the wrong bytes.

`sys/` is no longer read by the runtime after I1. `extract.py` keeps writing it for the tools (§3.5).

### 3.4 The drive's timing

- **Kept exactly:** the modelled duration of a command (`dvd.c:149`): 6 ms + `g_len` at 3 MB/s for 0xA8, 1 ms otherwise. Completion is still raised by `di_poll` at the deadline (`:72-75`).
- **What cannot be kept, and never could:** the host's read time passes as guest time with the guest thread stopped. `execute` runs inside the guest's DI register write (`dvd.c:192`), and guest time is the wall clock (`hle.c:294-304`). Every host millisecond the disc layer spends in a read is a millisecond the game is frozen — today an `fread` from the file cache, well under a millisecond. The store's first-touch hash (§3.7.4) and verify mode's second read add to that stall by their full cost.
- **Changed, deliberately, in I5a (not I1), and only once agreed:** the deadline counts from the command's start. `execute` reads `t0 = tb_now(s)` before `disc_serve` and sets `g_due = t0 + ticks`. Today `:151` adds the host's read time to the deadline a second time. The change removes only that second count: a backend that finishes inside the modelled time no longer moves completion; one that overruns completes at the first `di_poll` after the read returns, as today.
- **I5a is off the default path.** It is a behaviour change to every run's disc timing. The implementation session has asked that DI completion timing stay identical, because scenarios and pad scripts are frame-based (2026-09-25). So I2, I1 and I3 keep it exactly, and I5a is not built until that session agrees to it (implementation question 1). If agreed, it lands alone, after I1's refactor, where a regression can be told apart from the seam. If declined, the deadline keeps today's double count, and I5 is re-specified around it before it starts.
- **I5a also measures overruns:** for each 0xA8 command, the guest ticks from `t0` to `disc_serve`'s return are compared with the modelled ticks. Guest ticks, not host time, so the comparison holds under `SOA_SPEED`. The end report prints `[dvd] N reads outlasted their modelled time (worst X ms)`, always, N = 0 included.
- Consequence for T1: a replaced or delta'd file with a different length takes a different modelled time, exactly as a real drive would. A delta'd AKLZ file is served re-wrapped (§3.8.6), 9/8 of its decompressed size, so it loads later than the shipped container.

### 3.5 Step 1a (I2, tools) and the seam (I1, runtime)

**`tools/extract.py` (I2, which lands first and alone recovers the space):**
- `extract.py <dump>` writes `disc.iso` and `sys/` (four files, 3.3 MB) and checks the build. `--iso` is accepted and says it is now the default.
- `--files` also writes the 5,552 loose files, for anyone who wants to browse them.
- `--prune-loose [--dry-run]` deletes a loose file under `--out` only after comparing its bytes with the image's slice; a file that differs is kept and named; emptied directories are removed; `sys/` is never touched. This is how the owner gets 1.42 GB back without trusting a blind `rm`.
- `soa.disc.open_data(root) -> Disc` returns a `Disc` over the store (after I4), else `disc.iso`, else a loose-tree reader; `Disc.read_path("field/me101b.sct")` reads one file. `sct.py`, `validate_assets.py` (walks the FST instead of the tree) and `audio_check.py` (a path under the data directory that does not exist is looked up in the image by its relative path, so the commands quoted in `audio.scn` and `voice.scn` keep working) use it.
- `tools/soa/discfixture.py` (the synthetic-image builder, §3.12) arrives here, because I2's tests need it first.

**Runtime (I1):** `disc_open` accepts a directory (looks for `GEAE8P.soadisc` once I5 exists, then `disc.iso`) or a file (an `.iso`/`.gcm` or a store), and refuses what §3.3 says. So `gen\soa.exe "D:\dumps\Skies.iso"` runs straight from a player's own ISO with no copy at all, and a patched or other-revision ISO is refused from the first slice. With no image the port stops at boot (exit 1) naming `python tools/extract.py <your dump>` — today it boots and reads zeros, which only ever wasted a run. `disc_open` is called where `main.c` slurps today (`:1139-1149`), after `mem_poke`, `poke_parse`, `peek_parse`, `uncap_parse` and `watch_init` (`:1128-1136`), so the switch diagnostics the no-disc tests read still print before a missing image stops boot. The self test and `--replay` still need the image for the DOL until I3.

### 3.6 Step 1b: the executable built in (I3)

- `recompile.py` gains `--disc` (default `extracted`), opened through `soa.disc.open_data`. At every emission (it re-emits on every run, `recompile.py:126-146`) it writes `<--out>/disc_sys.c`: the DOL, `boot.bin` (0x440) and `fst.bin`, each as a `uint32_t` array whose little-endian bytes are the file's bytes, with their sizes and SHA-1 strings. It refuses (without `--force`) a DOL whose SHA-1 is not `config.yml`'s, and a `--dol` that differs from the disc's DOL.
  - Words, not bytes: interleaved compile probes of 3.3 MB of random bytes (`/std:c17 /O2 /c`) compiled as 32-bit words in 0.5–1.0 s warm and as bytes in 1.7–5.5 s warm, the first compile of either about 6 s cold; words are about 3× faster or more (a scratch probe, re-run interleaved for the review; the evidence appendix has the figures) [V].
  - **Where it goes:** `<--out>/disc_sys.c`, which is `gen/disc_sys.c` by default and `gen/clang/disc_sys.c` under portability.md L3a's `--cc clang-cl` (L3a lands first, in ../PLAN-NEXT.md's M1). Every path below written as `gen/` means `--out`.
  - **The link:** `--link` compiles `runtime/*.c` and links only the `chunk_*.obj` and `dispatch.obj` that already exist (`recompile.py:199`, `:226-244`); nothing else in `--out` reaches it. I3 adds `<--out>/disc_sys.c` to the link's source list (`:235`, beside `RUNTIME.glob`), so it is compiled at `/O2` on every `--link` (under a second warm); no chunk is recompiled. Without that line the file would be written and silently left out. L3a's golden copy of the `--link` command line (`test_toolchain_profiles.py`) gains the file in the same commit.
  - **`--no-embed`** emits `<--out>/disc_sys.c` with zero sizes, no marker and `""` SHA-1 strings, so both modes link the same symbols. The runtime then uses the image-header path and says so at boot: `[boot] system files from the image (built without them)`. A build that embedded them says `[boot] system files built in (DOL sha1 <40 hex>)`. One of the two lines is always printed, so a missing embed can never pass silently.
  - First line of an embedding `disc_sys.c`: a marker comment the guard refuses in any tracked file. The literal must never appear in `tools/` source: both the emitter and the guard build it by concatenation, or the guard refuses itself.
- **Stale-link guard (the DOL line of G5):** two pure functions in `recompile.py`, called before any DOL parsing: `write_build_inputs(out_dir, dol_sha1)` (a successful `--compile` writes `<--out>/build_inputs.txt`, recording the DOL's SHA-1 and the toolchain profile's name, portability.md 3.9) and `check_build_inputs(out_dir, dol_sha1) -> str | None` (`--link` refuses when the DOL it is about to embed differs; a `gen/` built before this has no file, so `--link` says so once and the guard arms at the next `--compile`). Being pure, they are testable without MSVC, without a DOL, and without touching the real `gen/`.
- `main.c`: built-in parts are used when present; at boot `disc.c` hashes the built-in DOL (3 MB, about 6 ms) and compares it with the built-in SHA-1 string, which catches a generator or byte-order bug. `--replay` and the self test no longer open a disc.
- The runtime keeps the image-header path (§3.3 item 2) alive for `--no-embed`. A future distribution route that ships a runtime without the game's bytes (G4, the Android runtime-only APK) needs exactly that path.

**What 1b means for SPEC §2.** Rule 1 (no game data in the repository) is unchanged: `gen/` is gitignored and a forbidden directory. Rule 2 names "generated code"; `gen/` now also holds verbatim copies of the player's system files. Proposed wording for SPEC §2.2: *"Recompiler output — the translated C and the copies of the player's executable, disc header and file table built into it — is a build artifact reproduced locally from the user's own dump. `gen/` is ignored."* The practical change is in `soa.exe`: today it holds a *translation* of the code but not the executable's data; after I3 it holds **the whole executable verbatim**, code and data. Neither was ever shareable (`SPEC.md:26`), but a shared `soa.exe` would now be a complete copy of Sega's and Nintendo's executable. README gains one sentence: *"`gen\soa.exe` contains your copy of the game's executable. Never share it."* The guard gains `.exe`, `.obj`, `.pdb`, `.so` and `.apk` (43 suffixes to 48 at b071949's count; CI's regex copy and every document that counts the suffixes change with it).

### 3.7 Step 1c: the store (I4 format and importer, I5 runtime)

#### 3.7.1 What is stored, and why

**Default: every byte of the disc from offset 0 to one mebibyte past the last file's end, exactly as shipped, in disc order** — system area, files, and the padding between them. Only the tail after that is dropped.

- As shipped, not decompressed: the game's own reader handles AKLZ; the FST, file sizes, the reader's path and the modelled load times all stay exactly as today. Decompressing the 3,633 AKLZ files would make them 1.62× longer to load under `dvd.c:149` (1,847,887,181 B against 1,139,727,674 B).
- With the padding: a read rounded up to 32 bytes from a file's start ends in the next file's first bytes for 4,009 files and in padding for 600 (§2), so a store that kept only files would hand the game different bytes on most past-the-end reads, and a verify mode could never be byte-exact.
- Not recompressed: zstd needs a third-party decoder (`SPEC.md:463-464`; `vendor/` is refused) for 6% on shipped bytes, or 18% after decompressing AKLZ with all the costs above (port-beyond-iso.md's corrections). A `codec` byte per extent is reserved so the question can be reopened without a format change.
- Result: payload 0x55438000 = 1,430,487,040 B plus about 1 MB of tables: a 1,431,490,560 B file, about 28.5 MB (2.0%) smaller than `disc.iso`. **The store is not a space saving; §5.**

#### 3.7.2 File format, version 1

All integers little-endian. The payload is the disc's own bytes, verbatim.

**Header, 4,096 bytes:**

| Offset | Size | Field |
|---|---|---|
| 0x000 | 8 | magic `SOADISC1` |
| 0x008 | 4 | `format_version` = 1 (a reader refuses any other value) |
| 0x00C | 4 | `header_size` = 4096 |
| 0x010 | 4 | `extent_size` = 64 |
| 0x014 | 4 | `extent_count` |
| 0x018 | 8 | `extent_table_offset` = 4096 |
| 0x020 | 8 | `payload_offset` (after both tables, 4096-aligned) |
| 0x028 | 8 | `payload_size` |
| 0x030 | 8 | `image_size` (decoded source image: 1,459,978,240) |
| 0x038 | 8 | `covered_end` = align_up(last file end + 1 MiB, 32 KiB), at most `image_size` |
| 0x040 | 6+1+1 | `game_id`, `disc_number`, `revision` (from the boot header) |
| 0x048 | 20 | `dol_sha1` |
| 0x05C | 20 | `fst_sha1` |
| 0x070 | 20 | `files_sha1` (§3.7.3) |
| 0x084 | 20 | `image_sha1` of the decoded source (zeros if not computed) |
| 0x098 | 4 | `source_kind`: 1 ISO/GCM, 2 RVZ |
| 0x09C | 4 | `flags`: bit 0 image SHA-1 matched the pinned value; bit 1 files SHA-1 matched |
| 0x0A0 | 64 | importer name and version, NUL-padded ASCII |
| 0x0E0 | 4 | `block_size` = 65536 |
| 0x0E4 | 4 | `block_count` = ceil(`payload_size` / `block_size`) |
| 0x0E8 | 8 | `block_table_offset` = `extent_table_offset` + `extent_count` × 64 |
| 0x0F0 | … | zeros |
| 0xFEC | 20 | `header_sha1`: SHA-1 of header bytes 0x000–0xFEB, then the whole extent table, then the whole block table |

**Extent, 64 bytes**, sorted by `disc_offset`, contiguous, non-overlapping, covering exactly [0, `covered_end`):

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | `disc_offset` |
| 8 | 8 | `length` |
| 16 | 8 | `data_offset`, relative to `payload_offset` (equal to `disc_offset` in version 1) |
| 24 | 4 | `fst_index` of a file, else 0xFFFFFFFF |
| 28 | 1 | `kind`: 0 system area [0, first file), 1 file, 2 padding, 3 tail |
| 29 | 1 | `codec`: 0 = stored (the only value in version 1) |
| 30 | 2 | zero |
| 32 | 20 | SHA-1 of the extent's bytes |
| 52 | 12 | zero |

**Block digest, 20 bytes:** block *k*'s SHA-1 over payload bytes [*k* × 65536, min((*k*+1) × 65536, `payload_size`)). The extent SHA-1s serve `--check`, `--check-disc` and naming; the block digests bound what the runtime must hash before serving a read (§3.7.4).

For this disc: 1 system + 5,552 files + 3,215 padding + 1 tail = 8,769 extents (561,216 B), and 21,828 blocks (436,560 B; the last is 32 KiB); the payload starts at 0xF5000.

**Atomicity:** the importer writes `<name>.soadisc.part`, re-reads it and checks every hash, then renames. A reader never opens a `.part`; the importer deletes a stale `.part` it finds, naming it.

**Location:** `extracted/GEAE8P.soadisc` by default (inside a gitignored, guard-forbidden directory), `--out` elsewhere. `soa.ini`'s `disc =` and `argv[1]` may name the file or its directory.

#### 3.7.3 The importer and its checks (Python, I4)

`python tools/extract.py <dump> --store` (the default once I5 is done; `--iso` then also writes `disc.iso`):

1. Opens RVZ through `tools/soa/rvz.py` or ISO/GCM raw. Names NKit, GCZ, WIA, CISO and WBFS as unsupported, with "convert to ISO or RVZ with Dolphin" (G3).
2. Boot magic 0xC2339F3D; game id `GEAE8P`, disc 0, revision 0. A European or Japanese disc is named as unsupported rather than offered `--force`, since `--force` also waives the DOL check (G3).
3. DOL SHA-1 equals `config/GEAE8P/config.yml`'s (`soa.dump.verify`).
4. FST parses; every file lies inside the image; none overlap.
5. **Pinned whole-disc hashes** in a new `config/GEAE8P/disc.yml`, read by `dump.py`'s narrow `key: value` parser:
   - `image_size`, `image_sha1` (Redump's), `fst_sha1`, and `files_sha1` = SHA-1 over the concatenated 20-byte SHA-1 digests of every file entry's bytes, in FST entry order.
   - All match: a verified dump; flags bits 0 and 1.
   - `files_sha1` matches and `image_sha1` does not: the files are the game's but the padding differs (a scrubbed or trimmed image). Accepted with a plain warning that past-the-end reads will not match a real drive.
   - `files_sha1` differs: a bad or patched dump; refused unless `--force`. Which file differs cannot be named without a per-file list (owner question 4).
   - These are four hashes and a size, the same class as `config.yml`'s DOL hash (SPEC §2.3). No file names, no per-file list.
6. Writes (both tables and the payload), re-reads, verifies, renames. Prints the extent and block counts, `covered_end`, the hashes and the verdict.

`--check <store>` re-hashes every extent, every block and the header; `--compare <store> <iso>` reads both over [0, `covered_end`) in 8 MiB blocks and reports differing bytes (`--flip OFFSET` corrupts one byte of the store side in memory, as the mutation); `--sys-only <store>` regenerates `sys/` from a store, for a player who deleted `extracted/` but keeps the store.

`tools/soa/store.py` gives `Store(path)` the same `read(offset, length)` interface `RawImage` and `RVZ` have, so `Disc(Store(...))` works for every tool.

#### 3.7.4 The runtime backend (I5)

- `disc_open` checks, in order: magic, `format_version`, header sizes, `header_sha1`, file size ≥ `payload_offset + payload_size`, game id and revision, `dol_sha1` against `DISC_DOL_SHA1`, and (with I3) `fst_sha1` against the built-in FST. Any failure stops boot with exit 1 and the reason. It loads both tables (about 1 MB).
- Reads: seek to `payload_offset + data_offset` and `fread`, the same I/O `dvd.c` does today. Below `covered_end` the bytes are the disc's; above it, zeros, counted, the first one logged with its offset.
- **Verification, `SOA_DISC_VERIFY`:**
  - unset, store backend: **`hash`**. The first read touching a 64 KiB block hashes that whole block (one bit per block, 21,828 bits); a mismatch stops the run with **exit 9**, naming the file or files whose extents overlap the block and "re-import with tools/extract.py". **The cost is a stall of the game** (§3.4): mod.c's SHA-1 built with `toolchain.CFLAGS` runs at about 500 MB/s (4,284,399 B in 7.7–9.4 ms over several runs, a scratch benchmark; the evidence appendix has the figures) [V], so a block costs about 0.13 ms. A read of L bytes touches at most L/64 KiB + 2 blocks, so its hashing costs at most about (L + 128 KiB)/500 MB/s — always well under its modelled 6 ms + L/3 MB/s. Hashing whole extents instead would stall 8–9 ms on the largest file's 32-byte header read, modelled at 6 ms (§4). The end report gives blocks hashed, bytes and host milliseconds.
  - `0`: no per-read checks.
  - `iso` or `iso:<path>` (default `<dir>/disc.iso`): every base read is also read from the ISO and compared — a second read that stalls the game by its full cost; each difference is logged with offset, length, file and **the disc offset of the first differing byte**; the run continues; the report gives reads compared, bytes compared, reads that differ and reads past `covered_end`. Needs the store backend and an ISO, or boot stops naming the missing one: a check that silently does not run is worse than none.
  - `all`: `hash` and `iso` together.
- **`SOA_DISC_FLIP=<path>|<0xoffset>`** (test knob): XORs 0x01 into one byte *as read from the store*, before hashing, comparing or serving — the first byte of the named file's extent, or the offset. It simulates on-disk corruption, so both `hash` and `iso` must catch it. If the run never reads that byte the report says "flip armed at X, never read", which fails any Done that relies on it.
- `soa.exe --check-disc [path]`: hashes every block, every extent and the header, checks the pinned-hash flags, prints one line and exits 0 or 9. For a store just copied to a Deck or a phone.

### 3.8 T1: the virtual disc (I6 core, I7 deltas, I8 per-map swaps)

#### 3.8.1 What a mod writes: `files.txt`

A mod folder (beside `mod.ini`) may hold `files.txt`:

```
# verb     path on the disc (as the FST names it)   source, relative to this folder
replace    title/warning.mld                         build/warning.mld
add        field/me045a.sct                          build/me045a.sct
alias      field/a045a.mld                           field/a002a.mld
delta      field/me101b.sct                          deltas/me101b.sct.delta     # I7
swap       battle/ecinit004.dat                      build/ec004_x.dat  when map=101b   # I8
```

- **Explicit verbs**, so a misspelled path is a refusal, not a silent `add` that nothing opens.
- **Paths:** forward slashes, no leading slash, no `.` or `..` components, printable ASCII, at most 255 characters; matched case-insensitively (the game's lookup is).
- `replace`: the path must be on the disc; its entry is re-pointed at a virtual extent.
- `add`: the path must not exist, and its directory must (no new directories in version 1; nothing in the game would open one).
- `alias`: a new name for an existing extent; its third column is a path on the disc, not a file in the folder. The name must not exist; the target must be on the disc or added by a mod; an alias of an alias is refused.
- `delta` (I7): a text delta against the player's own file (§3.8.6); the path must be on the disc.
- `swap … when map=NNNx` (I8): the path must be on the disc; its entry points at the source only while the committed map is `NNNx` (mod.c's `parse_map` syntax, `mod.c:250-259`).
- **Sources are read into host memory at boot**, when they are hashed for the recording (§3.8.8), and served from there — as deltas already are. A source over 16 MiB is refused; over 3.75 MB warns that heap 4's largest free block was measured at about that (beyond-gamecube.md §4). All mods' sources and delta results together are capped at 256 MiB; a mod that would pass the cap is refused whole, named, with the total asked for.
- **Fixed-size reads:** a few reads have a baked size — `FontData.US` is read as exactly 0x13020 bytes (`0x801E36E8`) — so a replacement or delta of a different length is read at the old size there. The loader warns when a `replace`, `delta` or `swap` changes the length of a path on a short list of known fixed-size reads (`FontData.US`, for now).
- **Rule 3 still holds:** a replacement `.mld` or `.sct` is a game-format binary built on the player's machine (T4, T5, T7, or a copy of the player's own file); the guard refuses those suffixes in the repository and any non-text file in a mod folder, so a repository mod can only carry aliases and text deltas.

#### 3.8.2 Where it runs, and mod refusals

- **A pass of its own in `main.c`**, after the system files are read and before the FST bound (`main.c:1163`): if `SOA_MODS` is set, `mod_scan_files()` in `mod.c` reads each folder's `mod.ini` (name, api, id with manifest v2, `dol_sha1`) and `files.txt`, in the same order and with the same refusal rules and messages as today — a duplicate `id` (`mod.c:907-908`) included, so a second copy of a mod is refused before its `files.txt` is read (a faulty mod is refused whole, file and line named, the run continues). It returns the accepted mods' `DiscFileOp` list. No mod code runs. `disc_overlay_build` then rebuilds the FST from that list.
- `mod_load` later skips the folders `mod_scan_files` refused (their reasons were printed once).
- **A `files.txt` counts as content** (I6): `load_one`'s refusal (`mod.c:932-936`) becomes "no patches.txt, no mod.dll and no files.txt beside it, so it would do nothing". A mod of `mod.ini` + `files.txt` alone loads, and appears in the recording.
- The rebuilt size goes through the existing bound (`:1163-1167`); `fst_addr` (`:1169`), arena hi and 0x80000038 follow it; `fst_max` (0x8000003C) is set to the new size (nothing in the game reads it; content-systems.md §8).
- `mod_load` stays after `setup_low_memory` (`main.c:1171`, `:1181`).
- **A mod refused after its files were placed** — its `patches.txt` fails later in `mod_load`, or its `mod.dll` declines — **stops the run (exit 9)**, naming the mod: "refused after its files were placed on the disc; fix it or remove it". The rule "never half a mod" (`mod.c:32-33`) cannot otherwise be kept once the FST is parked. Only a mod with both `files.txt` and a later fault can hit it.
- With no `files.txt` in any mod, the rebuild does not run and the FST is the base's, byte for byte.

#### 3.8.3 Rebuilding the FST

1. Parse the base FST (built-in or the base's) into entries.
2. Phase 1, all mods in load order: `replace` rewrites the entry's offset and length words; `add` appends a file entry at the end of its directory's range (the lookup is linear, §2, so position within a directory does not matter).
3. Phase 2: each `alias` becomes a file entry with its target's offset and length **as they stand after phase 1**. An alias of a file another mod replaced therefore reads the replacement, and the boot log says so ("mod B's alias field/a045a.mld reads mod A's replacement of field/a002a.mld").
4. Serialise: entries in the base's order with new entries inserted at the end of their directory's range; every directory's parent and next index and the root's count recomputed. **The base's string table is kept verbatim** and new names are appended, so an empty overlay reproduces the base byte for byte and a replace changes exactly two words.
5. Check the result before parking it: re-parse, confirm every base path not replaced still resolves (by a C twin of the SDK's linear walk) to its old offset and length, every replaced path to its extent, every added or aliased path to its target, and the entry count is base + added. A failure is a bug, and stops boot with exit 9.

Each added file costs 12 B plus its name and a NUL out of heap 4's arena.

#### 3.8.4 Serving virtual offsets

- Virtual extents start at 0x57060000 (the image's end plus a 32 KiB guard), each 32 KiB-aligned with at least 32 KiB between them, in mod load order then line order, so the same mod set always gets the same layout. **They must end below 2 GiB (0x80000000)**, which leaves 0x28FA0000 = 687,472,640 B (655 MiB); a set that does not fit is refused. FST offsets are u32 and the drive command carries the offset in words (`dvd.c:129`), but the SDK's read calls usually take the offset as an `s32` [I, not checked in this DOL], and an offset at or above 2 GiB risks a sign bug nothing here would catch.
- `disc_serve` splits a request into pieces: below `covered_end` from the base; inside a virtual extent from its source in host memory; anywhere else zeros. A read that runs off a virtual file's end gets zeros, where the ISO would give padding or the next file's bytes; the game reads by the FST's length, so this is harmless [I].
- The original extent of a replaced file stays readable at its old offset, so a neighbour's past-the-end read still gets the bytes the ISO holds there.

#### 3.8.5 Precedence and collisions

- **No silent winner.** The same path named by two mods (replace, add, delta, or an alias name) stops boot (exit 9), naming both mods' folders, both `files.txt` lines and the path. M17's `overrides =` declaration is the planned way to allow one to win; until then the fix is to remove one mod.
- Two `swap`s of one path for one map are a collision; for different maps they are not.
- Case-only differences are the same path.

#### 3.8.6 Deltas (I7)

**Recommendation: yes to deltas, in a text format of the project's own, applied at boot against the player's own file, decompressed, and served in the form the file ships in.**

- **Why deltas:** the after-T4 fallback (a script the assembler cannot round-trip is edited as a delta, PLAN-GAMEPLAY-MODS.md §E) and T13 (packages that never carry the game's bytes) both need them, and a delta is the only form of "edit this binary file" that carries only the edit.
- **Why text, now:** rule 3 says mods in the repository are text. A text delta is reviewable in a diff and carries only offsets and the modder's new bytes:

```
soa-delta 1
source  field/me101b.sct  size=45678  sha1=<40 hex: the decompressed vanilla content>
target  size=45690  sha1=<40 hex>                    # checked after applying
# offsets are in the source; hunks in increasing order, non-overlapping
0x00001234 = 4F 6B 21                                # overwrite 3 bytes
0x00002000 + 48 65 6C 6C 6F 20                       # insert before this offset
0x00003000 - 16                                      # delete 16 bytes
```

- **Against the decompressed content.** Most files are AKLZ; a byte edit inside LZSS output changes everything after it. The runtime decompresses the vanilla file (a C LZSS decoder mirroring `tools/soa/aklz.py`), checks the source SHA-1, applies the hunks and checks the target SHA-1.
- **Served re-wrapped, not raw.** An AKLZ file's result is served as a **literal-only AKLZ container**: the magic `AKLZ~?Qd`, the float 0.1f (0x3DCCCCCD) at +8 — which the reader compares at `0x801C65F4-0x801C6600` and without which it takes the raw path — the target size at +12 (big-endian), then for each 8 bytes a 0xFF flag byte and the 8 bytes (the last group short). A raw file's result is served raw. So every reader keeps the path it takes today. Serving an AKLZ file raw would move it onto the reader's raw path, which the akFio readers accept (`0x801C65A4-0x801C6610`), but `DVDReadAsync` has callers outside akFio (§2) that nobody has shown read only raw files [I]; a file one of those reads would break with nothing to catch it but one live check.
- **Cost:** the container is 16 B + the target + one byte per 8, so 9/8 of the decompressed size. A 30 KB container that decompresses to 90 KB is served as 101,266 B and loads about 24 ms later under `dvd.c:149`. The reader's AKLZ staging buffer (min(length, 0x20000) + 4,096 B) is used as today.
- **Refused:** a source SHA-1 that does not match (another revision, or the player's file is not vanilla), hunks out of order or overlapping, an offset past the end, more than 64 KiB of literal bytes in one delta (larger edits belong in a locally built `replace`), and a `delta` and a `replace` of the same path. A length change on a known fixed-size read warns (§3.8.1).
- Applied once at boot into host memory; the recording's hash covers the delta text.
- `tools/soa/delta.py` (parse, apply, make from two files, and the literal-only wrap) and `tools/delta.py` (the command) are the Python twins the tests compare against; `make` is how a modder writes one.
- **BPS later, for packages** (a slice with T13, not specified here): BPS is a compact binary delta format whose specification is public domain ("by byuu. Public domain.", `github.com/blakesmith/rombp/blob/master/docs/bps_spec.md`, fetched 2026-09-25), carries CRC32s of source and target, and is familiar from ROM hacking. The project would write its own decoder from the specification (about 120 lines); nothing is vendored. It is refused in the repository (binary), and T13's packer checks it against the player's files locally.

#### 3.8.7 Per-map swaps (I8)

- Each `swap` source gets a virtual extent at boot; the base entry is remembered.
- `main.c` calls `disc_overlay_park(fst_addr)` once the FST is parked and registers `disc_overlay_on_map` with `tick_on_safe_point` (`tick.c:70`, which takes `void (*)(CpuState*)`). The callback reads the committed map (0x80311AC0 and the byte at 0x80311AC8, as `mod.c:78-79` does) and, when it changes, rewrites each swapped entry's offset and length words in the parked FST in guest memory: the swap's extent for its map, the base entry otherwise.
- **Limitation, stated in MODDING:** only files the game opens *after* the map is committed follow the swap — battle files (`ebinit`/`ecinit`, beyond-gamecube.md §2.3), not the map's own `.mld`/`.sct`, which are per-map names anyway, and not the battle packages staged into ARAM at boot (`battle.scn:13-15`). A file opened in the same frame as the commit, before the next safe point, sees the previous mapping. Files already open keep what their `DVDFileInfo` copied at open.

#### 3.8.8 The recording, the census and the guard

- **Recording:** each mod's hash (`mod.c:940`) also covers `files.txt` and every source's bytes (deltas included), so the `# config` line's `mods=` entry changes when anything a mod places changes (rule 6). The base backend (ISO or store) is not recorded: it serves the same bytes, which I5's verify runs show.
- **Census:** `aram.c` names uploads from `disc_fst()` and `disc_peek()`, so overlay audio is named rather than "unidentified", and `__argv` and the `(long)` seek go. It indexes each extent once: an FST file whose (offset, length) equals an already-indexed file's is recorded as an alias name of that file, not hashed again — otherwise the shared first 32 bytes would mark both ambiguous (`aram.c:118-121`) and name neither. An upload from that extent is named `a002a.mld (= a045a.mld)`. The census line keeps its format with no aliases (`N disc files indexed`) and adds `, M aliases` otherwise.
- **Guard** (with CI's regex copy, `test_guard`, and every document that counts suffixes, in the same change as each addition; b071949's counts are 43 suffixes and 18 directories):
  - I3: `.exe`, `.obj`, `.pdb`, `.so`, `.apk`; the built-in-bytes marker line as a content check on text files (the signature check judges only binary files).
  - I4: `.soadisc`; one `SIGNATURES` row for `SOADISC1` (a store's header holds NULs, so the existing binary signature check refuses it under any name).
  - I7: `.bps`; `.delta` files over 256 KiB refused.
  - Mod source folders need no new directory names: T0's content check already refuses any non-text file in a folder holding a `mod.ini`, and the sources a mod builds locally sit in its `build/` subfolder, a forbidden directory. `files.txt` and `.delta` files are ASCII text and pass.

### 3.9 Switches and settings

| Name | Where | Meaning | Slice |
|---|---|---|---|
| `argv[1]`, `soa.ini disc =` | existing | a directory, an `.iso`/`.gcm`, or a `.soadisc` | I1, I5 |
| `SOA_DISC_LOG=1` | env | one `[disc]` line per drive read: frame, offset, length, file, bytes past its end | I1 |
| `SOA_DISC_VERIFY=hash\|iso[:path]\|all\|0` | env | §3.7.4 | I5 |
| `SOA_DISC_FLIP=<path>\|<0xoffset>` | env, test only | §3.7.4 | I5 |
| `soa.exe --check-disc [path]` | CLI | verify a store and exit | I5 |
| `recompile.py --disc DIR`, `--no-embed` | tools | §3.6 | I3 |
| `extract.py --files`, `--prune-loose`, `--dry-run` | tools | §3.5 | I2 |
| `extract.py --store`, `--check`, `--compare`, `--flip`, `--sys-only` | tools | §3.7.3 | I4 |
| `disc_check.py --log LOG --data DIR`, `--real DIR` | tools | check a run's disc log against the FST; the AKLZ decoder over a real disc | I1, I7 |
| `files.txt` in a mod folder | mods | §3.8.1 | I6-I8 |

`scenario.py` strips inherited `SOA_*` variables, so live checks pass these with `--env NAME=VALUE`, and `--data` may name a store file after I5. A direct `gen\soa.exe` run in a Done line sets `$env:SOA_SETTINGS='0'`, as scenario.py does (`:862`, `:967`), so a player's `soa.ini` cannot change it.

### 3.10 Logging

- Boot, one line when an image is opened, with the full 40-hex digests: `[disc] extracted/disc.iso: GEAE8P rev 0 disc image, 1459978240 bytes; DOL 8c0e2781…, boot.bin d7b9c3f0…, FST 8d8757eb…` (I1), or `[disc] extracted/GEAE8P.soadisc: GEAE8P rev 0 store v1, image to 0x55438000 of 0x57058000, 8769 extents, 21828 blocks, verified dump; DOL …, boot.bin …, FST …` (I5). After I3, `; FST matches this build` is appended.
- `[boot] DOL 3166656 bytes, FST 134426 bytes at 816DF2E0; entering fn_80003140` keeps its exact bytes (`test_scenario.py:63` and `test_soak.py:111` quote it). From I3 it is preceded by `[boot] system files built in (DOL sha1 …)` or `[boot] system files from the image (built without them)`. scenario.py parses only `[boot] N frames done` (`:453`), so the new line is harmless to it.
- Overlay, one line at boot: mods, files replaced/added/aliased/delta'd/swapped, FST size before and after, arena hi before and after, overlay memory used; one line per alias that reads another mod's replacement; one line per delta naming the path, its served size and whether it was re-wrapped.
- End of run (from `dvd_report`): the existing `[dvd] N reads, M bytes` line unchanged; then (I5a) `[dvd] N reads outlasted their modelled time (worst X ms)`; `[disc] backend …; X reads past the stored image`; `[disc] hashed N blocks (M MB) in T ms`; `[disc] verify: N reads compared with disc.iso, B bytes, D differ, P past the stored image`; `[disc] overlay: N reads of virtual files`.

### 3.11 Failure modes

| Condition | Behaviour | Exit | Says |
|---|---|---|---|
| No image where pointed (game run) | stop at boot | 1 | where it looked, and `python tools/extract.py <your dump>` |
| No image, self test or `--replay`, after I3 | runs | — | nothing |
| Boot magic wrong, game id not GEAE8P, revision not 0 | stop | 1 | both ids; European/Japanese discs are unsupported |
| Image's DOL is not `DISC_DOL_SHA1` (I1) | stop | 1 | "this image's executable is not the one this port was built for" and both hashes |
| Image's FST differs from the built-in (I3) | stop | 1 | "not the image this build was made from (patched or different?)" and both hashes |
| Store: bad magic, unknown version, header hash, truncated | stop | 1 | which, and "re-import" |
| Store: a block fails its hash at first read | stop | 9 | the file(s), and "re-import" |
| A read past `covered_end` | zeros, counted | — | first offset at the time; count in the report |
| A read outlasting its modelled time (I5a) | completes at the next `di_poll`, as today | — | counted, worst in ms |
| A stale `.part` | never opened | — | the importer names and deletes it |
| Store and `disc.iso` both present | store used | — | the ISO is unused; `--check` then delete it if you like |
| `SOA_DISC_VERIFY=iso` without an ISO or on the ISO backend | stop | 1 | what is missing |
| Importer: files hash differs | refused without `--force` | 1 | bad or patched dump |
| Importer: only the image hash differs | accepted | 0 | scrubbed or trimmed image; past-the-end reads will differ from a drive |
| `files.txt` fault (syntax, missing path on replace/delta/swap, existing path on add, missing directory, alias of alias, missing source, source over 16 MiB) | that mod refused whole; run continues | — | file and line |
| Overlay memory over 256 MiB | that mod refused whole; run continues | — | the mod and the total asked for |
| A second mod with an id already loaded | refused whole (as today); run continues | — | both folders |
| Two mods name one path | stop | 9 | both mods' folders, both lines, the path |
| A mod refused after its files were placed | stop | 9 | the mod |
| Virtual space past 2 GiB, or arena exhausted | stop | 9 | how much was asked for |
| Delta source SHA-1 mismatch | that mod refused whole | — | both hashes |
| A length change on a known fixed-size read | warns; loads | — | the path and both sizes |

Exit 9 is new: "the disc layer stopped the run (runtime/disc.c)". `scenario.py`'s `EXIT_MEANINGS` (`:137-147`, which stops at 8 and calls anything else "an exit code the runtime does not document", `:609`) and README's exit-code list gain it in whichever of I5 and I6 lands first; both slices carry it "if not already there".

### 3.12 Tests without game data

- **`tools/soa/discfixture.py`** (I2; I4 adds the RVZ writer) builds small synthetic GameCube images (about 2 MB): a boot header with a test game id (never `GEAE8P`: the fixture is written at test time into a temporary directory, and the guard's signature check refuses a binary file beginning `GEAE8P` anywhere in the tree), a fake DOL with a valid header and random sections, an FST with nested directories, files of random bytes (some wrapped as AKLZ with literal-only LZSS and 0.1f at +8), files that abut, zero padding, junk gaps, lengths not multiple of 32, and a tail. I4 adds RVZ with stored groups and one junk run (compressed tables through `compression.zstd`). The expected game id and hashes are parameters, so tests never need the real values.
- **pytest** (both CI legs): the fixture itself, the importer, `Store`, `--check`, `--compare`, `--prune-loose`, `--sys-only`, `open_data`, the tools' image fallback, the text-delta twin, the guard's new refusals, `scenario.py`'s missing inputs and exit 9, `recompile.py`'s build-input functions, and `test_disc_const.py` (disc.c's constants against `config/`).
- **`tools/citest/disc_check.py` + `disc_driver.c`** (CI's MSVC job, like `render_check.py`): builds `runtime/disc.c`, `sha1.c`, `dvd.c` and the overlay code standalone with a fake clock, a stub `mem_ptr`, and `/DDISC_GAME_ID=... /DDISC_DOL_SHA1=...` naming the fixture's, and runs them on the fixtures: system-file slicing and refusals, store reads, block-hash stops, FST rebuild and refusals, virtual serving including straddling reads, the AKLZ decoder, literal-only encoder and delta applier against the Python twins, and the drive deadline and overrun count under a delayed stub backend. `--log LOG --data DIR` checks a live run's `[disc]` read lines against the FST as `tools/soa/disc.py` parses it (an independent parser, not `disc_name_at`). `--real <image>` runs the AKLZ comparison over a real disc on the owner's machine.
- **Self test** (owner's machine): cases that need the real game code — the FST rebuild checked by the SDK's own `__DVDFSInit` (0x8023A478) and `DVDConvertPathToEntrynum` (0x8023A4B0), with the long-name flag set as OSInit sets it.
- **Live checks** follow rule 7: one run against fixed expectations (5,552 files; 0 differences; the pinned hashes; a budget), same-run contrasts and invariants, and mutations each in their own run against a fixed expectation. Never two live runs compared.

### 3.13 The contract

With no mods and the default backend, after every slice: `python tools/scenario.py replay` 23/23 with no hash moved; `$env:SOA_SELFTEST='1'; gen\soa.exe extracted` passes; `python tools/scenario.py run title --check` passes; `python tools/decomp.py` unchanged; `python -m pytest` passes. Three test builds compile runtime files this track changes, and each gains what it needs in the slice that adds it, with its assertions unchanged except the no-disc wording (I1):
- `test_memguard` (whose build `test_peek`, `test_poke` and `test_uncap` reuse) compiles `main.c`: it gains `runtime/disc.c` and `runtime/sha1.c` (I1), the built-in parts (I3: a stub, or implementation question 3's default), `runtime/vfst.c` (I6) and `runtime/delta.c` (I7).
- `test_profiler` compiles `main.c` and boots it: it gains `runtime/sha1.c` (I1) and stubs for the disc functions `main.c` calls — `disc_open` succeeding and `disc_system` handing back its three zero buffers, as it already stubs `dvd_init` — extended at I3, I6 and I8.
- `test_mods` compiles `mod.c`: it gains `runtime/sha1.c` (I1), and `delta.c` at I7 only if `mod.c` reads delta sources through it.

The `[boot]` line is byte-identical to `test_scenario.py:63`. No frame hash, capture or manifest row is created or re-blessed by this track; the one new baseline is `config/GEAE8P/disc.yml` (I4), inspected as I4 says.

---

## 4. Alternatives considered

| Alternative | Why not |
|---|---|
| **Stop after I3: `disc.iso` is the one file** (optionally with a sidecar index of hashes beside it) | The cheapest real option, and the right one if Android and the Deck are not coming soon (§7, owner question 1): I1 and I3 already refuse a mismatched image. Rejected as the design for 1c because a sidecar and its image can disagree (one left over from another extraction), there is no atomic "import finished" marker, and nothing can carry a codec later. |
| **Files only, padding dropped** | A read rounded up to 32 bytes from a file's start ends in the next file's first bytes for 4,009 files and in padding for 600 (§2): the game would get different bytes on most past-the-end reads, and verify mode could never be exact. Saves 8 MB. |
| **Keep the tail too** (the whole image) | Exact for any read at +29.5 MB. Rejected narrowly: no file lies there; reads beyond the stored region are counted and reported, and verify mode fails on any. Revisit if one ever appears. |
| **Store decompressed** (1.98 GiB) or **recompressed with zstd** (0.94× shipped; 0.82× after decompressing) | Bigger, or a third-party decoder (`SPEC.md:463-464`); decompressing changes FST sizes, lengthens modelled loads 1.62× on AKLZ files and moves the reader off its AKLZ path. The `codec` byte keeps the door open. |
| **Hash whole extents on first touch** (no block table) | The first read of a file is its 32-byte header (`0x801C6560`), modelled at 6 ms; hashing the largest file (4,284,399 B) then stalls the game 7.7–9.4 ms, and 96 files exceed 2 MB. 64 KiB block digests cost 437 KB of table and bound each stall to about 0.13 ms. |
| **Memory-map the store** | Fine, and Android may want it; not needed to match today's `fread` behaviour. An optimisation for later. |
| **Embed with C23 `#embed`, a `.rc` resource or a COFF writer** | `#embed` support in the pinned MSVC is not established here; `.rc` is Windows-only; a COFF writer is more code than a words array that compiles in under a second warm [V probe]. |
| **Only the DOL's data sections built in** | Nobody has shown the game never reads its own code as data (port-beyond-iso.md §2); the whole DOL is 3 MB. |
| **Serve a delta'd AKLZ file raw** | Simpler (no encoder) and a little shorter to load. Rejected: it moves the file onto the reader's raw path, and `DVDReadAsync` callers outside akFio are not shown to read only raw files [I]. The literal-only re-wrap keeps every reader on today's path for 1/8 more bytes. |
| **Deltas as VCDIFF (RFC 3284)** | Open standard, but a larger decoder, and xdelta3 (Apache-2.0 since 3.x; the GPL line lives on as `jmacd/xdelta-gpl`, README fetched 2026-09-25) would be a third-party runtime dependency (`SPEC.md:463-464`; `vendor/` is refused). |
| **bsdiff** | Needs bzip2 (third-party). |
| **IPS** | 16 MB limit and no source check. |
| **BPS now** | Binary, so not allowed in the repository (rule 3); worth it only for T13's packages. Kept as the later format. |
| **Deltas applied by a tool into a local cache** | A second step for players and a cache that goes stale; at boot costs milliseconds. |
| **Mod sources opened per read** | A same-size edit mid-run would be served without being recorded, and it needs a failure mode of its own. Read once at boot, when hashed, instead. |
| **Implicit replace/add from a folder tree** | A typo becomes a silent add. |
| **Last mod wins** | A silent winner changes the game without saying so. M17 adds declared overrides. |
| **Per-map redirect in `disc_serve` instead of re-pointing FST entries** | The game takes a file's length from the FST at open, so a different-length swap needs the FST anyway. |
| **Hash with XXH3 or CRC32** | XXH3 is third-party; CRC32 is weak for corruption naming. SHA-1 is already in `mod.c` and in `config.yml`, and Python's `hashlib` is fast. |
| **The deadline change inside I1** | I1 is a refactor that should change nothing; bundling a change to every run's timing would leave a `title --check` regression unattributable. It lands alone as I5a. |

---

## 5. Risks and concerns, plainly

1. **The store does not save space.** I2 takes you from 2.88 GB to 1.46 GB. The store is then 1.43 GB against `disc.iso`'s 1.46 GB — about 28.5 MB, 2%. Its value is integrity checking, a clean import, and one file for another device. If you are not planning Android or the Deck soon, stopping after I3 loses little.
2. **After I3, `soa.exe` contains the whole game executable, verbatim.** It already could not be shared (it holds a translation of the code); now it is a complete copy of Sega's and Nintendo's executable. Never share it, and do not attach it to an issue.
3. **Nothing here changes the legal position.** The store is still Sega's data and stays on your machine. Mods share only edits (aliases, text deltas); T13's packer checks that on the player's machine.
4. **I1 changes the boot path for every run.** It is not behind a switch. From I1 the port also refuses any image whose executable is not the one it was built for, which is new: today only `extract.py` checks. The checks prove the DOL, `boot.bin` and FST are the same bytes (fixed hashes) and that the 23 hashes, the self test and the title scenario are unchanged.
5. **The game is frozen while the disc layer works.** A read runs inside the game's own register write, and the game's clock is the wall clock, so every host millisecond spent reading is a millisecond the game stands still. Today that is an `fread` from the file cache, well under a millisecond. The store's first-touch hash and verify mode's second read add their full cost; that is why the runtime hashes 64 KiB blocks (about 0.13 ms each) rather than whole files (8–9 ms for the largest). I5a's deadline change removes only the *second* count of that time. It is also a behaviour change nobody asked for, and the implementation session has asked that DI completion timing stay identical, because scenarios and pad scripts are frame-based. So I5a is off the default path: it is built only if that session agrees (implementation question 1), and then it lands alone, with an overrun count that names any read the backend made late.
6. **Delta'd files load a little slower** (served as a literal-only container, 9/8 of the decompressed size), on the same path through the game's reader as the shipped file.
7. **A few reads have a fixed size.** `FontData.US` is read as exactly 0x13020 bytes; a replacement of a different length is read at the old size there. The loader warns for the reads known so far; others may exist [I].
8. **The file table grows into the heap.** Each added file costs about 12 bytes plus its name out of heap 4; the slack is unknown [I]. Large files may not fit heap 4's largest free block (≥ 3.75 MB measured); the loader warns.
9. **A mod collision or a late refusal stops the game at boot.** That is safer than a silent winner, but a player will meet it as "the game will not start". M17's mod list and a friendly message in M8's overlay are the real fix.
10. **Per-map swaps have a timing edge** (§3.8.7). They are for battle files; the check exercises exactly that case.
11. **Verify mode needs the ISO.** Once it is deleted, only the store's own hashes and the pinned hashes remain, which are enough to catch corruption but not a bug in the reader. Run both of I5's verify runs (the title, and the longer hold) before deleting.
12. **A scrubbed or trimmed dump** is accepted with a warning; the game's past-the-end reads then see zeros where a drive gives padding. Nothing is known to depend on it [I].
13. **The Redump hash came through search summaries** (the forum refused a direct fetch). Your `disc.iso` matches the summaries' SHA-1 and CRC32 exactly, which is very strong evidence, but confirm on redump.org before pinning it.
14. **The guard's marker can trap its own author:** the literal marker in `tools/` source would be refused. Build it by concatenation.
15. **Counts rot.** New tests, new runtime files (`disc.c`, `sha1.c`, `vfst.c`, `delta.c`; `PLAN.md`'s "all 22 `runtime/*.c`" at `:17` and `:81` is already stale: there are 26 at 012164a, with P6's `seed.c`) and new guard suffixes (43 and 18 directories at b071949) change numbers quoted in `PLAN.md`, `TESTING.md` (four places), `HANDOFF.md`, `README.md`, `ARCHITECTURE.md`, `CLAUDE.md` and `.claude/skills/check/SKILL.md`. Each slice fixes every copy (`grep -rn "<the old number>" --include="*.md" .`).
16. **Coordination.** `main.c`/`settings.c` path handling is also touched by comfort-pack.md's M5b (relative paths against the port root; `aram_set_data_dir` in place of `__argv`), which lands first ([../PLAN-NEXT.md](../PLAN-NEXT.md) M1): I1 opens the disc path settings.c resolved and reads through M5b's `aram_set_data_dir`. `main.c`'s recording block (`:1173-1185`) was rebuilt by P6 (24d9235) and edited again by P6b (79c9ad8), and `mod.c` by manifest v2 (3949028, b071949) and later M17; I6 rebases on all of them. T0 has landed (1c7b780, 4041dfc); I3, I4 and I7 add to its lists. portability.md's L2 (`dvd.c:103`, `plat_fseek64`) touches the same line as I1; I1 lands first under ../PLAN-NEXT.md (M3 before M4a), so L2 moves I1's wrapper into `plat.h`. Portability no longer touches `aram.c`: M5b and I1 remove `__argv`. Nothing here touches `gx.c` or `gxr*.c`.
17. **Android:** importing an RVZ on the phone needs a zstd decoder (third-party). A plain ISO can be imported on the device, or the store made on the PC and copied.

---

## 6. Slices

Order: **I2, then I1, then I3.** [../PLAN-NEXT.md](../PLAN-NEXT.md) places I2 as a gap filler in M1 and I1 and I3 in M3. I2 alone gives the space back; I1 is the seam the rest builds on. **I5a is off the default path:** it changes every run's disc timing, so it is built only if the implementation session agrees (implementation question 1), and then alone (§3.4). **I4, I5** when gate G5 says to build the store (Android or the Deck firm, or you want integrity checks); I5 needs I5a, or a re-specification that keeps today's double count. **I6, I7** in milestone 2, after T9 (PLAN-GAMEPLAY-MODS.md §E); manifest v2, which T1 needs, is already in (3949028, b071949). **I8** when N2 needs it. One commit per slice.

---

**I2. One copy on disk: the loose files go, the tools read the image** — *hours to a day, none. Landed as 12077d1 but for the owner's prune (session A). On the owner's data, the dry run found 5,552 deletable files and 0 kept (1,418,037,369 bytes), leaving 1,463,288,602 B. `validate_assets` through `disc.iso` matches FINDINGS §2 (3,633 AKLZ containers, 2,126,196,876 decoded bytes, 0 failures). Where it differs from the text below: `open_data` returns `Disc | LooseTree`; `--prune-loose` refuses a dump argument and exits 1 when anything is kept; the fixture is 1.2 MB.*
- *Prerequisites:* none. Lands first; touches no runtime file.
- *Files:* `tools/extract.py`, `tools/soa/disc.py` (`open_data`, `read_path`, a loose-tree reader), `tools/soa/discfixture.py` (new: the ISO writer of §3.12), `tools/sct.py`, `tools/validate_assets.py`, `tools/audio_check.py`; `tools/tests/test_extract.py` (new); `README.md`, `CONTRIBUTING.md`, `docs/TESTING.md`, `.claude/skills/check/SKILL.md` (test counts).
- *What:* §3.5's tools half: `disc.iso` + `sys/` by default, `--files`, `--prune-loose [--dry-run]`, `--iso` accepted; the three tools read through the image when a loose file is absent; the fixture builder.
- *Done:*
  - `python -m pytest tools/tests/test_extract.py`: the fixture parses (`soa.disc.parse_fst` finds every file it placed, and `aklz.decompress` returns each wrapped file's bytes); on it, `extract.py` writes `disc.iso` and the four `sys/` files, each equal to its slice, and no loose file; `--files` writes every file equal to its slice; `--prune-loose` deletes exactly the loose files equal to the image and keeps, and names, one the test altered (the mutation); `sct.py`, `validate_assets.py` and `audio_check.py` each read a file present only in the image.
  - **Owner:** `python tools/extract.py --prune-loose --dry-run`, then without `--dry-run`: 5,552 deleted, 0 kept; `extracted/` is `disc.iso` + `sys/`, 1,463,288,602 B.
  - Owner's machine, after the prune (no loose tree): `python tools/validate_assets.py` reports 3,633 AKLZ containers of 5,552, 2,126,196,876 decoded bytes, 0 failures (FINDINGS §2's fixed figures).
  - `python tools/guard.py`, the ruff pair, `python -m pytest`.

**I1. One seam for the disc, and the system files from the image** — *a day to several days, `--link`.*
- *Prerequisites:* I2 (for `tools/soa/discfixture.py`); comfort-pack.md's M5b, for its `aram_set_data_dir` and the disc path settings.c resolves (it lands first, in ../PLAN-NEXT.md's M1). Touches neither `gx.c` nor `gxr*.c`.
- *Files:* `runtime/disc.c`, `runtime/disc.h`, `runtime/sha1.c`, `runtime/sha1.h` (new); `runtime/main.c`, `runtime/dvd.c`, `runtime/aram.c`, `runtime/mod.c` (SHA-1 moves out; its callers unchanged); `tools/citest/disc_check.py`, `tools/citest/disc_driver.c` (new); `.github/workflows/ci.yml` (one step); `tools/scenario.py` (`NEEDED_FILES` → the image only); `tools/tests/test_scenario.py` (`:485-496`), `tools/tests/test_memguard.py` (build list gains `disc.c` and `sha1.c`; its no-disc boot asserts exit 1 and `extract.py` named), `tools/tests/test_profiler.py` (build list gains `sha1.c`; stubs for the disc functions `main.c` calls), `tools/tests/test_mods.py` (build list gains `sha1.c`), `tools/tests/test_peek.py`, `test_poke.py`, `test_uncap.py` (docstrings: "finds no disc image"), `tools/tests/test_disc_const.py` (new); `README.md` (`SOA_DISC_LOG`; running from an ISO; the no-image stop), `docs/TESTING.md`, `docs/ARCHITECTURE.md`, `docs/PLAN.md` counts.
- *What:*
  - `disc.c` with the ISO backend and §3.3's refusals, `DISC_GAME_ID` and `DISC_DOL_SHA1` behind `#ifndef`;
  - `main.c` calls `disc_open` where it slurps today (`:1139-1149`), after the switch parsing (`:1128-1136`), takes the DOL, `boot.bin` and FST from `disc_system`, and stops with no image (exit 1);
  - `dvd.c` reads through `disc_serve`; **the deadline is unchanged** (I5a changes it);
  - `aram.c`'s census reads through `disc.c`, from the directory M5b's `aram_set_data_dir` passes, dropping the `(long)` seek;
  - SHA-1 moves from `mod.c` (`:117-151`) into `sha1.c`, used by both;
  - `SOA_DISC_LOG`, and `disc_check.py --log`;
  - the `[disc]` open line with the three SHA-1s (§3.10); the `[boot]` line is unchanged.
  - The offset-to-file table this builds is what D2's disc-read list needs; D2's remainder becomes hours afterwards.
- *Done:*
  - `python tools/citest/disc_check.py` (new, in CI): on fixtures, the DOL, `boot.bin` and FST `disc.c` returns are the exact slices the fixture placed; six broken images are each refused with their own message: bad magic, wrong game id, FST past the image, DOL section past the image, image truncated inside the FST, and a DOL with one byte changed (the `DISC_DOL_SHA1` refusal). Mutation: moving the fixture's FST offset by 4 makes the returned FST differ and the check fail. Its `--log` mode refuses a fixture log with one line naming the neighbouring file.
  - `python -m pytest tools/tests/test_disc_const.py`: `DISC_DOL_SHA1` in `runtime/disc.c` equals `config/GEAE8P/config.yml`'s `hash`, and `DISC_GAME_ID` equals the config directory's name; the same checker, fed a copy of the text with one hex digit changed, refuses it.
  - `$env:SOA_SETTINGS='0'; $env:SOA_FRAMES='300'; gen\soa.exe extracted`: the `[disc]` line names DOL `8c0e278126fa3b0173400fdb632038172743cc13`, boot.bin `d7b9c3f09b2e2ad8fcc4ecdfbb2181b4a91b115e` and FST `8d8757eb2bc312b279665a634eb5d4dc7b039eab`; the `[boot]` line is byte-identical to `test_scenario.py:63`'s.
  - The same run with `$env:SOA_DISC_LOG='1'`, then `python tools/citest/disc_check.py --log <that log> --data extracted`: at least one `[disc]` read line; every read's named file is the one `tools/soa/disc.py`'s FST parse places at that offset (FST offset ≤ read offset < FST offset + size); reads naming no file: 0.
  - `$env:SOA_SETTINGS='0'; gen\soa.exe build\citest\no-disc` (an empty directory) exits 1 and stderr names `python tools/extract.py`; `test_memguard`'s no-disc boot asserts the same.
  - In the contract's `python tools/scenario.py run title --check` run, the `[aram] census sources` line reports 5,552 disc files indexed (the FST's file count; all 305 saved logs in `build/` with a census line show that figure, so a wrong walk of the FST through `disc.c` shows here).
  - `python -m pytest tools/tests/test_mods.py`: passes, with its `hashlib` agreement check (`:288-296`) now running against `sha1.c`.
  - The contract (§3.13).

**I3. The executable built in** — *a day, `--link` (the stale-link guard arms at the next `--compile`).*
- *Prerequisites:* I1.
- *Files:* `tools/recompile.py` (`--disc`, `--no-embed`, `write_build_inputs`/`check_build_inputs`, `<--out>/disc_sys.c` in the link's source list at `:235`), `tools/soa/embed.py` (new emitter); `runtime/disc.c`, `runtime/main.c`; `tools/guard.py`, `.github/workflows/ci.yml` (regex); `tools/tests/test_guard.py`, `tools/tests/test_recompile_inputs.py` (new), `tools/tests/test_toolchain_profiles.py` (portability.md L3a's golden `--link` line gains `disc_sys.c`; the clang-cl line names it under `gen/clang`), `tools/tests/test_memguard.py` and `tools/tests/test_profiler.py` (the built-in symbols); `tools/citest/disc_driver.c`, `disc_check.py`; `tools/scenario.py` (the replay sweep reports a replay whose output holds a `[disc] ` open line), `tools/tests/test_scenario.py`; `docs/SPEC.md` §2, `README.md`, `docs/ARCHITECTURE.md`, and every copy of the suffix count (`CLAUDE.md`, `TESTING.md`, check skill, `HANDOFF.md`, `PLAN.md`: 43 → 48).
- *What:* §3.6: `<--out>/disc_sys.c` as words with its marker, compiled on every `--link`; `--disc`, `--no-embed`; `<--out>/build_inputs.txt` with the DOL's SHA-1 and the profile's name; built-in parts preferred, the image's FST checked against them; `--replay` and the self test open no disc; the guard's new suffixes and marker check; SPEC §2's wording.
- *Done:*
  - `python tools/recompile.py --link`, then `$env:SOA_SETTINGS='0'; $env:SOA_FRAMES='300'; gen\soa.exe extracted`: `[boot] system files built in (DOL sha1 8c0e278126fa3b0173400fdb632038172743cc13)` is present, and the `[boot]` DOL line is unchanged.
  - `python tools/scenario.py replay`: 23/23, no hash moved, and the sweep reports no replay whose output holds a `[disc] ` open line. Mutation, once, recorded in the commit: calling `disc_open` on the replay path makes the sweep report all 23.
  - `$env:SOA_SELFTEST='1'; gen\soa.exe build\citest\no-disc` (an empty directory): passes, and prints no `[disc] ` open line.
  - `python tools/citest/disc_check.py`: with the driver's built-in copies, an image whose FST differs by one byte is refused with "not the image this build was made from"; with an empty built-in stub (the `--no-embed` form), the image path is used and `[boot] system files from the image (built without them)` is printed.
  - `python -m pytest tools/tests/test_recompile_inputs.py` (no MSVC, no DOL): `write_build_inputs` then `check_build_inputs` on `tmp_path` with two 40-hex strings differing in one digit refuses; with the same string passes; with no file gives the one-time note. It never runs `main()` or touches `gen/`.
  - `python -m pytest tools/tests/test_guard.py`: a tracked file holding the marker (built at test time) is refused; so are `.exe`, `.obj`, `.pdb`, `.so`, `.apk`; the guard's own source passes. `python tools/guard.py --history` stays clean.
  - The contract.
- **Owner:** agree to §5 item 2 before this lands.

**I5a. The drive's deadline from the command's start, and overruns counted** — *hours, `--link`. A deliberate change to every run's disc timing, so it is off the default path: built only once the implementation session agrees, and then as a commit of its own.*
- *Prerequisites:* I1; implementation question 1 answered "accept". Until then nothing here is built, and I2, I1 and I3 keep DI completion timing exactly as today.
- *Files:* `runtime/dvd.c`; `tools/citest/disc_driver.c`, `disc_check.py`; `README.md` (the new `[dvd]` line), `docs/TESTING.md`.
- *What:* §3.4: `g_due = t0 + ticks` with `t0` read before `disc_serve`; the overrun count in guest ticks and its end-of-run line.
- *Done:*
  - `python tools/citest/disc_check.py`: `dvd.c` linked in `disc_driver.c` against a stub `disc_serve` that advances the fake clock by 50 ms: a read's deadline is exactly its start plus 6 ms plus length at 3 MB/s, and the overrun count is 1; with a stub that advances nothing, the count is 0. Mutation, once, recorded in the commit: computing the deadline after the read fails the first.
  - In the contract's `python tools/scenario.py run title --check` run: `[dvd] 0 reads outlasted their modelled time`. (The ISO backend is an `fread` from the file cache; a nonzero count here is the finding this line exists to surface.)
  - The contract.

**I4. The store: format, importer and checker** — *several days, none.*
- *Prerequisites:* I2.
- *Files:* `tools/soa/store.py` (new), `tools/soa/disc.py` (`open_data` prefers a store), `tools/extract.py` (`--store`, `--check`, `--compare`, `--flip`, `--sys-only`; unsupported formats named), `tools/soa/dump.py` (reads `disc.yml`), `config/GEAE8P/disc.yml` (new), `tools/soa/discfixture.py` (RVZ writer), `tools/tests/test_store.py` (new); `tools/guard.py` (`.soadisc`; a `SIGNATURES` row for `SOADISC1`), `.github/workflows/ci.yml` (regex), `.gitignore`, `tools/tests/test_guard.py`; every copy of the suffix count.
- *What:* §3.7.1–§3.7.3, with the block table.
- *Done:*
  - `python -m pytest tools/tests/test_store.py`: ISO and RVZ fixtures import; `Store.read` equals the image at every offset below `covered_end` (exhaustive on the fixture) and gives zeros above; every block digest equals `hashlib` over its payload slice; each mutation is caught and named: one payload byte flipped (`--check` names the file, and exactly one block and one extent fail), a truncated store, an unfinished `.part`, a wrong game id, a DOL hash that is not the expected one, a files hash that differs (refused), and a padding-only difference (a fixture with its junk zeroed: accepted, with the warning); `--sys-only` on a fixture store writes four `sys/` files, each equal to the fixture's slice.
  - Owner's machine: `python tools/extract.py "<the owner's .rvz>" --store` writes `extracted/GEAE8P.soadisc` and reports the image SHA-1 `46105320…4940`, FST `8d8757eb…`, files `7f185565…`, each equal to `disc.yml`, 8,769 extents and 21,828 blocks; `python tools/extract.py --check extracted/GEAE8P.soadisc` passes; `python tools/extract.py --compare extracted/GEAE8P.soadisc extracted/disc.iso` reports 0 differing bytes over [0, 0x55438000); the same with `--flip 0x348000` reports exactly 1.
  - **Baseline:** `config/GEAE8P/disc.yml` is a first bless. How it is inspected, in the commit: the image SHA-1 is Redump's (confirmed on redump.org, an independent source) and equals the owner's image; the FST and files hashes were computed twice, independently (this spec's scratch pass and the importer), and agree.
  - `python -m pytest tools/tests/test_guard.py`: a tracked `.soadisc`, and a tracked binary file beginning `SOADISC1` under another name, are refused.

**I5. The port reads the store, and proves it against the ISO** — *several days, `--link`.*
- *Prerequisites:* I1, I4, I5a (I3 recommended, for the built-in FST check). If I5a is declined, this slice is re-specified with today's deadline kept before it starts (implementation question 1).
- *Files:* `runtime/disc.c`, `runtime/main.c` (`--check-disc`); `tools/citest/disc_driver.c`, `disc_check.py`; `tools/scenario.py` (`--data` may be a file; `EXIT_MEANINGS` gains 9 if not already there), `tools/tests/test_scenario.py`; `tools/extract.py` (the store becomes the default output); `README.md` (exit 9 if not already there), `docs/TESTING.md`.
- *What:* §3.7.4.
- *Done:*
  - `python tools/citest/disc_check.py`: the C store reader equals the Python reader at every offset of the fixture; a flipped byte stops `hash` mode at first touch of its block, naming the file; a header-hash mismatch, a truncated payload and `format_version` 2 are each refused at open.
  - `python -m pytest tools/tests/test_scenario.py`: exit 9 maps to "the disc layer stopped the run (runtime/disc.c)".
  - Owner's machine, verify run 1: `python tools/scenario.py run title --check --data extracted/GEAE8P.soadisc --env SOA_DISC_VERIFY=all` passes; its report says `[disc] verify: N reads compared with disc.iso, …, 0 differ, 0 past the stored image` with N equal to the same log's `[dvd] N reads` (with no mods every read starts below `covered_end`, so each is compared), and `[dvd] 0 reads outlasted their modelled time`.
  - Verify run 2, longer: `python tools/scenario.py run hold --check --data extracted/GEAE8P.soadisc --env SOA_DISC_VERIFY=all` passes with the same invariant, 0 differ and 0 past. (hold runs at `SOA_SPEED=3`, where a modelled time is a third as long in wall time; its overrun count is reported and a nonzero one is written up, not a failure.)
  - Mutation, its own run: title with `--env SOA_DISC_VERIFY=iso --env SOA_DISC_FLIP=<X, a file an I1 SOA_DISC_LOG of title shows read>` reports at least one differing read; every differing read's first differing byte is at X's start offset (the reads may belong to X or to the file before it, whose rounded read reaches X's first bytes), and no other offset differs. A further run with `SOA_DISC_VERIFY=hash` and the same flip stops with exit 9 naming X.
  - Budget: in verify run 1, the `[disc] hashed …` line's host milliseconds are under 1% of the run's wall seconds (a fixed limit).
  - `gen\soa.exe --check-disc extracted/GEAE8P.soadisc` exits 0; with `$env:SOA_DISC_FLIP='0x348000'` (the first file's first byte) it exits 9 naming that file.
  - The contract on the store backend, and on the ISO backend (`--data extracted/disc.iso`).
- **Owner:** decide whether to delete `disc.iso` (and the original dump) once both verify runs pass.

**I6. The virtual FST: replace, add, alias (T1's core)** — *several days, `--link`.*
- *Prerequisites:* I1; manifest v2 (done, 3949028 and b071949: ids for the collision messages and the recording); T0 (done, 1c7b780 and 4041dfc: the content check); I3 recommended (a built-in base FST). Rebases on P6's recording block in `main.c`.
- *Files:* `runtime/vfst.c` (new: the rebuild and the overlay extents), `runtime/disc.c`, `runtime/disc.h`, `runtime/main.c` (the pass before parking), `runtime/mod.c` and `runtime/mod.h` (`mod_scan_files`, `DiscFileOp`, the hash over `files.txt` and sources, `load_one`'s refusal wording, `mod_load` skipping the pre-pass's refusals, the exit-9 rule), `runtime/aram.c` (one index entry per extent, alias names), `runtime/selftest.c`; `tools/citest/disc_driver.c`, `disc_check.py`; `tools/scenario.py` (`EXIT_MEANINGS` gains 9 if not already there), `tools/tests/test_scenario.py`; `examples/mods/map-alias/` (`mod.ini`, manifest 2, `id = map-alias`; `files.txt` with two aliases); `tools/tests/test_mods.py`, `tools/tests/test_memguard.py` (build list gains `vfst.c`), `tools/tests/test_profiler.py` (stub for `disc_overlay_build`); `README.md` (exit 9 if not already there), `docs/TESTING.md`.
- *What:* §3.8.1–§3.8.5 and §3.8.8, without deltas or swaps. In `mod.c`'s `load_one`, a `files.txt` counts as content: the refusal at `:932-936` becomes "no patches.txt, no mod.dll and no files.txt beside it, so it would do nothing".
- *Done:*
  - `python tools/citest/disc_check.py`: on fixtures, an empty overlay rebuilds the FST byte for byte; a replace changes exactly two words; after an add and an alias, every other path still resolves (through the C twin of the SDK's walk) to its old offset and length; each refusal fires with its message: replace of a missing path, add of an existing one, add into a missing directory, alias onto a missing path, alias of an alias, a case-only duplicate, a set ending at or past 0x80000000, overlay memory past 256 MiB, and a collision between two mods with different ids (exit 9, both folders, both lines, the path); two mods with the same id: the second is refused as a duplicate and no collision is reported. Reads straddling two virtual extents and running off a virtual file's end give the expected bytes and zeros.
  - `python -m pytest tools/tests/test_mods.py`: (a) a folder with only `mod.ini` and `files.txt` loads, and its `mods=` entry appears in `mod_describe`; (b) a folder with only `mod.ini` is still refused, with the new wording; (c) the recorded `mods=` hash changes when one byte of `files.txt` or of a source changes; (d) `examples/mods/map-alias` is manifest 2 with its folder's id (`test_the_shipped_mods_are_manifest_2` gains it). Mutation, once, recorded in the commit: restoring the old condition makes (a) fail.
  - `$env:SOA_SELFTEST='1'; gen\soa.exe extracted`: a new case rebuilds the real FST with an empty overlay (identical bytes) and with a built-in test overlay of one add and one alias, parks it in scratch memory, sets the long-name flag as OSInit does, calls the game's own `__DVDFSInit` (0x8023A478) and `DVDConvertPathToEntrynum` (0x8023A4B0), and gets: the added path at its virtual offset, the alias at its target's offset and length, all 5,552 vanilla paths at their old offset and length, and −1 for a missing path. Mutation, once, recorded: skipping the directory renumbering fails the vanilla-path lookups after the insertion point.
  - No mods: the `[boot]` line still reads `FST 134426 bytes at 816DF2E0`, and the contract.
  - Live, a virtual extent read by the game's own SDK: pick a file an I1 `SOA_DISC_LOG` of title shows read and whose length is a multiple of 32 (so no rounded read overreaches it and every byte served is the ISO's). In a scratch folder `build\citest\mods-replace\probe\` write a `mod.ini` (manifest 2, `id = replace-probe`, the DOL's `dol_sha1`), a `files.txt` line `replace <path> build/<name>`, and a byte-identical copy of the file (`python -c` over `soa.disc.open_data('extracted').read_path('<path>')`). `python tools/scenario.py run title --check --env SOA_MODS=build\citest\mods-replace --env SOA_DISC_LOG=1`: the log shows that path read at 0x57060000 plus an in-file offset, the end report's `[disc] overlay: N reads of virtual files` has N > 0, and `--check` passes.
  - Live, the alias: a scratch `build\citest\mods-alias\` holding a copy of `examples\mods\map-alias`. From a Continue (HANDOFF, "Start a run from a save": `SOA_CARD` naming a copy of a save card, never `build/cards/slotA.raw`), with `$env:SOA_SETTINGS='0'`, `SOA_MODS='build\citest\mods-alias'`, `SOA_DISC_LOG='1'`, `SOA_TRACE='1'`, `SOA_RENDER='1'`, `SOA_SNAP='100'`, `$env:SOA_PAD=(python tools/soak.py --warp 045a --last 3800)`, `$env:SOA_POKE=(python tools/soak.py --pokes --warp 045a)`, `SOA_PEEK='0x80311AC0@3700,0x80311AC8@3700'` and `SOA_FRAMES='3800'`, then `gen\soa.exe extracted`: `python tools/soak.py check <log> --expect-reach 045a` passes; the peeks read 0x0000002D and a word whose top byte is 0x61 (`WARP_FRAME` 3300 + `WARP_SETTLE` 400, `soak.py:209-210`); after frame 3300 the disc log shows reads inside `field/a002a.mld`'s extent; the census line reads `5552 disc files indexed, 2 aliases`. **Owner:** open the snapshot after frame 3700 and see `a002a`'s room.
  - Live, the collision: a scratch `build\citest\mods-collide\` holding the example and a copy whose `mod.ini` changes `id =` and `name =`. `$env:SOA_SETTINGS='0'; $env:SOA_MODS='build\citest\mods-collide'; $env:SOA_FRAMES='1'; gen\soa.exe extracted`: exit 9, with both folder names, both `files.txt` line numbers and `field/a045a.mld` on stderr. In its own run, two copies with unchanged ids: the second is refused as a duplicate id, the run reaches frame 1, exit 0.

**I7. Deltas against the player's own files** — *a day to several days, `--link`.*
- *Prerequisites:* I6; the owner's answer on deltas (question 3).
- *Files:* `runtime/delta.c` (new: the AKLZ decoder, the literal-only encoder, the hunk applier), `runtime/vfst.c`; `tools/soa/delta.py`, `tools/delta.py` (new); `tools/tests/test_delta.py` (new), `tools/tests/test_memguard.py` (build list gains `delta.c`), `tools/tests/test_mods.py` (only if `mod.c` reads delta sources through `delta.c`); `tools/citest/disc_driver.c`, `disc_check.py`; `examples/mods/delta-demo/` (manifest 2, `id = delta-demo`); `tools/guard.py`, `.github/workflows/ci.yml` (regex), `tools/tests/test_guard.py` (`.bps`; `.delta` cap); every copy of the suffix count; `docs/`.
- *What:* §3.8.6's text deltas, served re-wrapped for AKLZ files and raw for raw files.
- *Done:*
  - `python tools/citest/disc_check.py`: the C AKLZ decoder equals `aklz.py` on fixture containers; the C literal-only encoder's output, decoded by `aklz.py`, equals its input, carries 0x3DCCCCCD at +8 and the size at +12; the C applier equals `delta.py` on overwrite, insert and delete; each refusal fires: wrong source SHA-1, hunks out of order, overlapping hunks, an offset past the end, 64 KiB + 1 of literals, a wrong target SHA-1; a length change on `FontData.US` warns.
  - Owner's machine: `python tools/citest/disc_check.py --real extracted` — the C AKLZ decoder agrees with `aklz.py` on all 3,633 AKLZ files.
  - `python -m pytest tools/tests/test_delta.py`: `delta.py make` then `apply` round-trips random edits; its output parses in the C driver.
  - Live: a scratch `build\citest\mods-delta\` holding a copy of `examples\mods\delta-demo` (one hunk changing one word of a message in `field/me101b.sct`). `python tools/scenario.py run encounter --check --env SOA_MODS=build\citest\mods-delta --env SOA_DISC_LOG=1` (encounter reaches `a101b` by frame 14710 with no stick input, `encounter.scn:45-46`): the log shows `field/me101b.sct` served from its virtual extent with the length the boot line names for the re-wrapped target; the boot line names the delta; `--check` passes.
  - `python -m pytest tools/tests/test_guard.py`: `.bps` refused; a `.delta` over 256 KiB refused.
- **Owner:** talk to that character in a live run and see the changed line.

**I8. Per-map swaps** — *a day, `--link`. Build when N2 needs it.*
- *Prerequisites:* I6.
- *Files:* `runtime/vfst.c`, `runtime/disc.h`, `runtime/main.c` (`disc_overlay_park`, the safe-point registration); `tools/tests/test_profiler.py` (stub for `disc_overlay_park`); `tools/citest/disc_driver.c`, `disc_check.py`; `docs/`.
- *What:* §3.8.7.
- *Done:*
  - `python tools/citest/disc_check.py`: with a fake committed-map word, a swapped entry holds the swap's offset and length on its map and the base's on any other; two swaps of one path for one map are refused.
  - Before building, run `battle.scn` once with I1's `SOA_DISC_LOG`, pick a battle file whose first read comes after the committed map changes (not one of the packages staged into ARAM at boot), and write its path, that map and its FST offset into this Done in the commit. Then two runs, each against fixed values: (1) `python tools/scenario.py run battle --check --env SOA_MODS=<scratch> --env SOA_DISC_LOG=1` with `swap <path> <a byte-identical copy> when map=<that map>`: the file is read at 0x57060000 or above, and `--check` passes; (2) the same with `when map=<any other map>`: it is read at its FST offset.

---

## 7. Open questions

**For the owner**
1. **Order.** Do I2 now (hours to a day, tools only: 1.42 GB back), then I1 and I3 (a day to several days plus a day, about a week of evenings at most: the seam, running straight from an ISO, replays without the disc, a mismatched disc refused), and the store (I4, I5, about two weeks of evenings, with I5a if the implementation session agrees to it) only when Android or the Deck becomes firm or you want integrity checking? Or build the whole disc layer now? ([../PLAN-NEXT.md](../PLAN-NEXT.md) takes the first answer by default: gate G5.)
2. **Store contents:** exactly as shipped (recommended), or recompressed? Recompressing saves 6–18% but needs a third-party decoder, which reopens "no third-party runtime dependency" (the same decision as SDL3).
3. **Deltas:** yes, as project-own text deltas now (recommended), with BPS later for shareable packages? Or no deltas, so scripts the assembler cannot round-trip stay closed to mods?
4. **Pinned hashes:** four whole-disc hashes in `config/` (recommended: metadata, like the DOL's hash), or also a per-file list of 5,552 hashes so the importer can name which file of a bad dump is wrong? The list names every file on the disc.
5. **`soa.exe` holding the executable (I3).** Agree, given it was never shareable?
6. **Deleting your files:** the loose tree after I2 (`--prune-loose`), and later `disc.iso` and your original dump after I5. Your disk, your call; the commands check before deleting.
7. **Scrubbed or trimmed dumps:** accept with a warning (recommended), or refuse?

**For the implementation session**
1. The drive deadline from the command's start (§3.4, I5a's prerequisite): accept the change to every run, or keep today's order and let backend time count twice? The implementation session asked on 2026-09-25 that DI completion timing stay identical, because scenarios and pad scripts are frame-based. So the default is "keep": I5a is not built, and I1 and I3 change no timing. I5a lands, alone, only if that session agrees to it as a deliberate behaviour change; if not, I5 is re-specified with the double count kept.
2. A mod refused after its files are placed: stop (exit 9, proposed), or rebuild and re-park the FST without it before the game starts?
3. `test_memguard` and `test_profiler` compile `main.c` without `gen/`, so from I3 they need the built-in symbols: a stub file in their build lists, or a default in the runtime (MSVC `/alternatename`, weak symbols elsewhere) so they stay untouched? Either way `soa.exe` always links `gen/disc_sys.c` and prints which mode it is in (§3.6).
4. Hash on first touch on by default for the store. Measured: `mod.c`'s SHA-1 built with `toolchain.CFLAGS` runs at about 500 MB/s (4,284,399 B in 7.7–9.4 ms), which is why §3.7.4 hashes 64 KiB blocks (about 0.13 ms each, always inside a read's modelled time). Agree with block digests, the 1% budget and I5a's overrun count as the guards, or default off?
5. Should I1 also finish D2's `[progress]` disc-read list from the same table, or leave it separate?
6. Whether `SOA_DISC_LOG` stays an environment switch or becomes the D2 default output.
7. The M5 first-run amendment and I1 both resolve the disc path: which lands first? (Answered, ../PLAN-NEXT.md D6: M5b first, in M1; I1 in M3 reuses its `aram_set_data_dir`.)
8. The on-device ISO importer for Android: which track owns it (the Android plan, after the L slices)?

---

## Evidence appendix

- Layout and gap census: a scratch script over `extracted/sys/fst.bin` and `extracted/disc.iso`, 2026-09-25, and an inline re-run for this revision. Output: 5,552 files, 7 directories, 5,560 entries; alignment {32 KiB: 247, 2 KiB: 9, 32 B: 529, 4 B: 4,767}; no shared or overlapping extents; gaps {0: 2,336, 1–31 B: 2,970 (all zero bytes), 12,184–32,621 B: 245 (each starts with a zero byte; first non-zero at +28: 76, +29: 53, +30: 57, +31: 58, +32: 1)}, 7,958,941 B; first file 0x348000; last file end 0x55337A16 (`ts000899.gvr`, 43,270 B); image 1,459,978,240 B; loose files 1,418,037,369 B; `extracted/` 2,881,325,971 B.
- Past-the-end reads: 4,610 lengths not a multiple of 32. **Model used:** a read from the file's start with the length rounded up to 32, as the reader does (`fn_801C64DC`, `addi r4,r4,31; rlwinm r4,r4,0,0,26` at 0x801C6628-0x801C662C on the `DVDFileInfo` length). Under it: 600 end in padding, 4,009 in the next file's first bytes, 1 in the tail. (The first draft rounded each file's absolute end to a 32-byte disc boundary instead, which gives 742 and 3,867; that is not how the game reads.)
- Hashes, read-only on the owner's machine: `disc.iso` SHA-1 `46105320553c858f25fafc5fd357566b505a4940`, CRC32 `23e347b6` (1.8 s); `main.dol` SHA-1 `8c0e278126fa3b0173400fdb632038172743cc13`, 3,166,656 B (equals `config.yml:6`); `boot.bin` `d7b9c3f09b2e2ad8fcc4ecdfbb2181b4a91b115e`, 1,088 B; `fst.bin` `8d8757eb2bc312b279665a634eb5d4dc7b039eab`, 134,426 B; files hash (SHA-1 of the concatenated per-file SHA-1s in FST entry order) `7f185565fdb2f4180d3ed893319f6e1482dc50a3`.
- Redump: search results for "redump Skies of Arcadia Legends USA" (2026-09-25) quoting `forum.redump.org/post/129269` and `viewtopic.php?pid=129269`: size 1,459,978,240, CRC32 23e347b6, SHA-1 46105320…4940; the two summaries differed in one MD5 digit; a direct fetch was refused (ECONNREFUSED).
- Compile probe: 3,301,000 random bytes as `uint8_t` hex (16,917,750 B of C) and as `uint32_t` hex words (9,284,184 B of C), MSVC `/std:c17 /O2 /c`, a scratch probe. First draft, one sample each: bytes 7.9 s, words 0.8 s. Interleaved re-runs for the review: words 5.8 (cold), 0.7, 0.6, 0.6 s and bytes 2.4, 5.5, 1.7 s; then bytes 6.25 (cold), 2.01, 1.84 s and words 0.98, 0.57, 0.54 s.
- SHA-1 speed: `mod.c:117-151`'s code, built with `toolchain.CFLAGS` in a scratch benchmark, hashes 4,284,399 B in 8.0–9.4 ms over 5 runs (the review) and 7.67–7.96 ms over 7 runs (this revision): about 500 MB/s.
- Disassembly: `DVDInit` 0x8023ACE8 (the magic test at 0x8023AD60–0x8023AD9C); `__fstLoad` 0x8023D8F0 (writes 0x80000038/3C at 0x8023D974/0x8023D980); `DVDConvertPathToEntrynum` 0x8023A4B0 (linear walk 0x8023A678–0x8023A768; long-name flag test 0x8023A578); akFio's `fn_801C64DC` (the 32-byte header read at 0x801C6560, the AKLZ test at 0x801C65A4–0x801C6610 including 0.1f at 0x801C65F4–0x801C6600, the raw length rounding at 0x801C6628–0x801C662C).
- BPS licence: "BPS File Format Specification _by byuu. Public domain._", `raw.githubusercontent.com/blakesmith/rombp/master/docs/bps_spec.md`, fetched 2026-09-25.
- xdelta licence: `github.com/jmacd/xdelta` README, fetched 2026-09-25: "The `main` branch and the 3.2.x series (`release3_2_apl`) continue under the same Apache 2.0 license"; "The original GPL licensed Xdelta lives at github.com/jmacd/xdelta-gpl".

---

## Review log

Two reviewers reported 34 issues. Each was checked against the tree at b071949 before acting. **All 34 were applied; none was rejected.** Nine were applied with a change, because the tree had moved on or the check turned up something the reviewer had missed. Those nine are marked *(changed)*.

1. **Past-the-end counts used absolute-end rounding** — applied. Confirmed at 0x801C6628-0x801C662C and re-measured: 600 / 4,009 / 1 under the length model; 742 / 3,867 reproduce only under the absolute-end one. *(changed)* The larger gaps are 12,184–32,621 B, not "2–32 KB", and the text now says so.
2. **"Invisible to the game" overstated; first-touch hashing does not fit the modelled time** — applied. `execute` runs from `di_write` (`dvd.c:192`), and guest time is the wall clock (`hle.c:294-304`). The bench re-ran at 7.7–7.9 ms. *(changed)* I chose the reviewer's option (a): 64 KiB block digests in the store format (§3.7.2), with the extent SHA-1s kept for `--check`. The stall is stated in §3.4, §3.7.4 and §5 item 5, and implementation question 4 stays open with the measurement.
3. **Stale current state** — applied. *(changed)* The tree had moved past the reviewer's fix: HEAD is b071949, and 4041dfc took the guard to 43 suffixes and 18 directories, added a signature check and dropped the 64-row rule. The text uses today's counts, and I3 goes from 43 to 48.
4. **test_profiler missed; the wrong test named for I1; the switch diagnostics** — applied. Confirmed at `test_profiler.py:132-157` and `test_memguard.py:172-194`. *(changed)* I found `test_uncap` also reuses test_memguard's build, and it is added. For test_profiler I chose stubbing the disc API over a fixture image. That test is about the sampler, it already stubs `dvd_init`, and a fixture would need the game-id and DOL checks overridden in its build.
5. **`--link` never compiles `gen/`** — applied (`recompile.py:199`, `:235`). The boot line that names which system files are in use is now printed in both modes, so a missing embed cannot pass silently.
6. **`[boot]` line contradiction** — applied, together with 30. The `[boot]` line stays byte-identical, and the hashes move to the `[disc]` line.
7. **GB versus GiB** — applied, in decimal (2,881,325,971 B measured).
8. **`ecinit005.dat` is not on the disc** — applied. The example uses `ecinit004.dat`, and `swap` now requires the path to be on the disc.
9. **Missing caveats: non-akFio callers and fixed-size reads** — applied. Fixed-size reads are in §3.8.1 and §5, with a loader warning. The raw-serving caveat is settled by 26's re-wrap.
10. **I5 mutation check ambiguous** — applied. The check is keyed on the first differing byte's disc offset, which verify mode now logs.
11. **xdelta licence stale** — applied. The README was fetched on 2026-09-25.
12. **Compile timing from one sample** — applied. *(changed)* This revision re-ran the probe interleaved (bytes 6.25 cold / 2.01 / 1.84 s; words 0.98 / 0.57 / 0.54 s), and both re-runs are in the appendix. The decision is kept.
13. **Wrong citations** — applied (`rvz.py:129-144`/`:16-75`, `mod.c:1008-1030`/`:1081`, `mod.c:250-259`).
14. **A `mod.ini` + `files.txt` mod is refused today** (high) — applied. Confirmed at `mod.c:932-936`. The new wording, the test_mods cases and the mutation are in I6.
15. **The collision Done could never fire because of the duplicate-id refusal** (high) — applied. Confirmed at `mod.c:907-908`. The Done now has a scratch fixture with a changed id, a named command, and a separate same-id case. The same checks run on the host in `disc_check`. `SOA_SETTINGS=0` was added to direct runs.
16. **SHA-1 needed before it moved** — applied. `sha1.c` moves in I1, and test_mods, test_memguard and test_profiler gain it there.
17. **No DOL check between I1 and I3** — applied. I1 refuses on `DISC_DOL_SHA1`, uses the `#ifndef` pattern from b071949's `MOD_API`, and adds `test_disc_const.py` with an in-test mutation and a sixth fixture refusal. *(changed)* The game id is checked against the config directory's name, because `config.yml` has no id field.
18. **I2 alone returns the space; the fixture belongs in I2** — applied. The order is now I2 → I1 → I3, `discfixture.py` moves to I2, and §1 and owner question 1 are reworded.
19. **The deadline change bundled into I1** — applied. It is now its own slice, I5a (hours, `--link`), and I1 is resized to "a day to several days".
20. **No check reads a virtual extent; the 4 GiB limit** — applied. The cap is now 0x80000000. *(changed)* The reviewer said "about 655 MB"; the room is 687,472,640 B (655 MiB). I also required the probe file's length to be a multiple of 32, so every byte served is the ISO's and `--check` can stay exact.
21. **Live checks named no command** — applied. I6's alias check has full commands. *(changed)* `SOA_TRACE=1` was added, because `soak.py check --expect-reach` reads `[trace]` lines (`soak.py:607`). Scratch mod folders replace `examples\mods`, so map-log's DLL does not load alongside. I7 has a named command and an **Owner** line.
22. **Build lists at I6 and I7** — applied: test_memguard gains `vfst.c` and `delta.c`, test_profiler gains stubs, and `test_delta.py` is listed.
23. **`test_recompile_inputs` cannot drive `main()`; `--no-embed` undefined** — applied: two pure functions, and `--no-embed` defined as zero-size symbols.
24. **Checks that rename `extracted/`** — applied. The self test runs on an empty directory, and the replay sweep reports any `[disc] ` open line, with a recorded mutation.
25. **Verify "N > 0" too weak; no per-read overrun count** — applied. The check is now the invariant "reads compared = `[dvd] N reads`", plus a hold run. *(changed)* The overrun counter lives in I5a's `dvd.c` and is measured in guest ticks, so it holds under hold's `SOA_SPEED=3`. It must be 0 in title and is reported in hold.
26. **Deltas served raw change the reader's path** — applied, with option (a): a literal-only AKLZ re-wrap. *(changed)* The disassembly adds a requirement the reviewer did not name: the reader compares the float at +8 with 0.1f (0x801C65F4-0x801C6600), so the re-wrap must write 0x3DCCCCCD there or the reader takes the raw path.
27. **`EXIT_MEANINGS` gap when I6 lands first** — applied, in whichever of I5 and I6 lands first, with a test_scenario check.
28. **I8 Done under-specified** — applied: the file is picked from a battle log before building, then two runs checked against fixed values.
29. **Interface gaps** — applied: `DiscFileOp`, `mod_scan_files`, the `disc_overlay_build` signature, `disc_overlay_park`, `on_map(CpuState*)`, and the corrected header comment.
30. **`[boot]` line and a self-test case that passes vacuously** — applied. Fixed hashes (boot.bin's measured as `d7b9c3f0…`) go on the `[disc]` line, and the self-test comparison case is dropped from I1.
31. **Stale statements; L2 not L0; L9** — applied (portability spec L2 `plat_fseek64`, L9 `aram.c:160-172`). I also added P6's in-flight edit of `main.c`'s recording block to §5 item 16.
32. **Features with no Done line** — applied. The `SOA_DISC_LOG` check runs `disc_check --log` against `tools/soa/disc.py`'s independent FST parse. The reviewer's "+32" tolerance was dropped, because a read's start always lies inside its file. The no-image stop and `--sys-only` each have a check.
33. **Aliases would make the census name nothing** — applied. Confirmed at `aram.c:118-121`: each extent is indexed once, and the census line keeps its format and adds ", M aliases".
34. **Sources re-opened per read** — applied. Sources are read into memory at boot under a 256 MiB cap, and the "changed size mid-run" failure row is dropped.

**Consistency review, 2026-09-25, at 012164a.** A check across the five planning documents and against the repository, with the implementation session's facts from after the drafts:
- **I5a is off the default path.** The implementation session asked that DI completion timing stay identical, because scenarios and pad scripts are frame-based. §3.4, §5 item 5, §6, the I5a and I5 slices and implementation question 1 now say that I5a is a deliberate behaviour change, built only on that session's agreement, and then alone; I1 and I3 change no timing.
- **M5b lands first and I1 reuses it.** §5 item 16 described the M5 amendment's rejected design (paths against `soa.ini`'s folder). It now names comfort-pack.md's M5b (the port root, `aram_set_data_dir`), which lands in ../PLAN-NEXT.md's M1; I1 reads through `aram_set_data_dir` and is no longer the slice that drops `__argv`. Implementation question 7 is marked answered.
- **I3 writes into `--out`.** `disc_sys.c` and `build_inputs.txt` go to `<--out>` (`gen/clang` under portability.md L3a's `--cc clang-cl`, which lands first); `build_inputs.txt` records the toolchain profile too; L3a's golden `--link` line gains the file (`test_toolchain_profiles.py` in I3's files).
- **The 64-bit seek.** I1 lands before L2 under ../PLAN-NEXT.md, so the local wrapper is the one written, and L2 moves it (§3.2).
- **Sizes.** Owner question 1 gave I1 and I3 as "about three evenings", below their own slice sizes; it now says a day to several days plus a day, about a week at most.
- **State.** P6 (24d9235) and P6b (79c9ad8) are recorded as landed, and T0c's guard changes (012164a) in §2; the runtime count is 26 at 012164a; the header gives main.c's measured shift. Scratch paths in the header, §3.6, §3.7.4 and the evidence appendix are reworded: the scripts and benchmarks are not in the repository.
