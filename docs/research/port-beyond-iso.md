<!-- Written 2026-09-25 by a read-only research agent on moving from the ISO to fully native, and the legal line, at HEAD 12e45a8. Nothing in
the repository was changed and the game was not run; compiler probes and syntax checks ran in a scratch
directory only. A second agent then checked this report's key claims; its corrections come first, below,
and supersede the text where they disagree. The summary built from all four reports is
docs/research/android-and-native.md. [V] = checked in code, a tool run or a dated page; [I] = inference. -->

# Getting off the ISO: what "fully native" means for this port on PC and Android, and where the legal line sits

> **Corrections from verification.** A skeptic checked this report's key claims; these did not fully hold.
>
> - **partly:** The disc holds 1,418,037,369 B in 5,552 files; 3,633 AKLZ (1,139,727,674 B shipped, 1,847,887,181 B decompressed), 1,919 raw (278,309,695 B); the last file ends at 1,429,436,950 of 1,459,978,240, so a pack store saves about 42 MB (2.9%) over disc.iso.
>   - **Correction:** All counts and sizes reproduce exactly with an independent FST parser [V]. The 42 MB does not follow from the last-file end. Trimming after the last file saves only 30,541,290 B (2.09%). The 41,940,871 B (2.87%) is disc.iso minus the file bytes: 3,440,640 B of system area before the first file, plus 7,958,941 B of inter-file gaps, plus the 30.5 MB tail. A store must still carry main.dol, fst.bin and boot.bin (3,302,170 B), so the net saving is about 38.6 MB (2.6%). Also, FINDINGS.md's totals are at lines 56-57, not 57-58, and FINDINGS gives the combined decompressed figure 2,126,196,876 = 1,847,887,181 + 278,309,695.
> - **partly:** The game's file reader decompresses only on AKLZ magic + '~?Qd' + a float check, so an importer could store files decompressed; doing so changes FST sizes and possibly heap use (36 files decompress past 3.75 MB, largest 5,178,944 B).
>   - **Correction:** The check is verified [V]: 801C65A4-801C65B0 does addis -32319/cmpli 20836 (the word 0x7E3F5164 '~?Qd' at +4), then bytes 65/75/76/90 at +0, then fcmpu of the float at +8. Every AKLZ file carries 0x3DCCCCCD (0.1f) there. The same check is emitted only twice (gen/chunk_010.c:14129 and :14573, the async and sync akFio readers), and the LZSS ring constant 0xFEE appears only in chunk_010's reader callbacks. The heap hedge points the wrong way. The destination size is the decompressed size either way: 84(r31) is set from the header's size at 801C6648-801C6660, or from the DVDFileInfo length at 801C661C-801C6630 for a raw file. Only the AKLZ path allocates extra: a min(file length, 0x20000) staging buffer plus 4,096 B (801C6654-801C66B4). Storing decompressed would therefore reduce transient heap, not add to it, and the 36-file count says nothing about heap. That count is right only for decimal MB (3.75e6 gives 36; 3.75 MiB gives 27); the largest is 5,178,944 B [V]. Caveat [I]: DVDReadAsync has callers outside akFio (0x80007E2C, 0x80097814, 0x801E36F4, 0x80215D68, 0x80216844, 0x80219790 among others), so an importer should confirm those paths read only raw files.
> - **partly:** Recompressing the store with zstd after AKLZ decompression gives about 0.80x the shipped size (about 1.13 GB); zstd on files as shipped gives only 0.896x.
>   - **Correction:** The direction holds and the magnitude is slightly optimistic, because the original sample was weighted by file count and over-represents small files. My size-weighted re-samples with Python 3.14's compression.zstd at level 9 [V]: 30 files (31.4 MB) gave 0.929x as shipped and 0.812x decompressed; 150 files (164.1 MB, 11.6% of the store, seed 11) gave 0.939x as shipped and 0.819x decompressed. The better estimate is about 0.82x, roughly 1.16 GB, and only about 6% saved by zstd on shipped bytes, not 10%. Higher zstd levels or long mode were not tested.
> - **partly:** Off Windows the runtime compiles but cannot run the game: fibers exit, the rasterizer has zero workers, window/audio are stubs, gxr.c uses unguarded MSVC __declspec; the generated C has no compiler-specific tokens beyond #pragma once and fma().
>   - **Correction:** 'Compiles' is false [V]. A syntax check of every runtime/*.c with NDK 28.2.13676358 clang --target=aarch64-linux-android29 gives 21 errors in 4 of 25 files. gxr.c has 17: __declspec at :123/:143, LONG/LONGLONG, InterlockedIncrement(64), Sleep, YieldProcessor, _ReadWriteBarrier. selftest.c has 2 (_putenv at :122). dvd.c has 1 (_fseeki64 at :103, unguarded). gx.c has 1 (_exit at :188, no unistd.h). The reporter's own scratch log android_syntax2.txt shows the same. The rest holds: threads.c:310 exits; gxr.c 'n = 0' is at :1969 in HEAD (:1977 in the modified working tree), leaving only participant 0 to rasterize; window.c:464-467 and audio_out.c:145-149 are stubs. The generated-C part holds across all 18 chunks, dispatch.c and functions.h: only #pragma once, fma (C99) and setjmp. The compiler-specific byte swaps come in through runtime/cpu.h:46-55, which already has a __builtin fallback.
> - **partly:** Peer static-recompilation ports distribute binaries containing translated code (UnleashedRecomp, Zelda64Recomp, UnleashedRecomp-Android APK released 2026-07-09); this repo's SPEC rules that out (SPEC.md:26, PLAN-GAMEPLAY-MODS.md:1416).
>   - **Correction:** The substance holds [V]. UnleashedRecomp's docs/BUILDING.md requires default.xex, default.xexp and shader.ar in UnleashedRecompLib/private/, its releases are prebuilt, and main.cpp calls LdrLoadModule(modulePath) to load and decompress the xex at run time. Zelda64Recomp's README reads 'This repository and its releases do not contain game assets. The original game is required to build or run this project.' The date is wrong: the GitHub API for SansNope/UnleashedRecomp-Android (not a fork) shows the first APK v0.0.1 published 2026-07-04T09:47Z, then v0.0.3 07-05, v0.0.4 and v0.1.4 07-08 (18:09Z), and v0.2.1 07-11; nothing on 2026-07-09 UTC. The latest is v0.5.3 (2026-07-22, 67,035,734 B APK). Its README keeps UnleashedRecompLib/ppc/ (the recompiler output) local and builds it into the APK. The 'builds the patched executable on first launch' line means patching the xex with the title update, not on-device recompilation [I]. On the repo side, SPEC.md:26 sits under 'Non-goals (v1)', and SPEC §2 item 2 is the standing rule; PLAN-GAMEPLAY-MODS.md:1416 is correct.
> - **partly:** Takedowns have targeted distributed executables (SM64 PC port), a reimplementation (re3/reVC), circumvention (Yuzu) and a fan remake (AM2R); nobody in the peer set distributes assets.
>   - **Correction:** The dates check out [V]. VGC 2020-05-08 quotes 'The reported file contains an unauthorized derivative work' (Wildwood Law Group, aimed at hosts and Google, not the developers). re3: DMCA Feb 2021, suit filed 2021-09-02 (TorrentFreak 2021-09-03), settlement in principle 2023-02-06 and dismissal with prejudice (TorrentFreak 2023-04-05). Yuzu: filed 2024-02-26, settled 2024-03-04 for $2.4M with the 'primarily designed' admission. AM2R: released 2016-08-06 and DMCA'd within days. The correction: the SM64 PC-port executables had Nintendo's assets baked in. The sm64ex EXTERNAL_DATA build option defaults to 0 ('If 1, load textures and soundbanks from external files'), so by default textures and soundbanks are compiled into the exe, and the May 2020 builds predate that option [I, strong]. That case is therefore not evidence that an asset-free recompiled binary gets taken down, and it should not be paired with 'peers distribute no assets' as though it were.
> - **partly:** An Aurora-style source port would have to decompile the game code (5,362 functions, about 2.28 MB, 81.6% of .text) and the middleware (807 functions, 286,600 B, 10.3%); Aurora supplies GX, PAD, CARD, DVD, VI, SI and OS but has no AX/AI/DSP audio layer.
>   - **Correction:** The numbers are verified from config/symbols.txt [V]: 5,362 functions summing exactly 2,278,368 B in 0x80005600-0x802319E0 (81.6% of 2,791,136), and 807 functions / 286,600 B in 0x80266778-0x802AC7E0. The SDK block holds 961 functions (217,444 B) by symbols.txt, against SPEC §6's 936. SPEC §7.1 frames the middleware as a candidate to reimplement, not necessarily decompile. Aurora's OS support is overstated. The live tree (GitHub API, pushed 2026-09-25) has lib/dolphin/os with only OSAddress, Alloc, Arena, BootInfo, Cache, Init, Memory, Report and Time: no OSThread, OSMutex, OSMessage or OSAlarm implementation, which SoA's threaded engine needs. Also present are ms/mouse.cpp, thp (with THPAudio.cpp), mtx, gd, AR.cpp (no ARQ lib, although include/dolphin/arq.h exists and SoA's aramCache uses ARQ), and lib/card plus dolphin/card.cpp. 'No AX/AI/DSP' holds: include/dolphin/ai.h and dsp.h are headers only, with no lib implementation.

*Read-only research, 2026-09-25. I did not run `soa.exe`, scenarios, soak or pytest. I did run three read-only things: Python over `extracted/sys/fst.bin` plus the 16-byte header of each file in `extracted/disc.iso`, a zstd test on 120 random files, and `tools/disasm.py`. The scratch scripts are `C:\Users\bmfre\AppData\Local\Temp\claude\c--Users-bmfre-Documents-Github-SOA\9c0b5de4-3d3f-44f9-a448-811014adcd50\scratchpad\android\store_sizes.py` and `zsample.py`.*

*Tags: **[V]** means checked in the tree, the disassembly, a measurement or the cited page. **[I]** means inferred.*

*Line numbers are from today's working tree. `runtime/gxr.c` has uncommitted edits from another session, so its line numbers may shift.*

*The legal questions are the owner's to decide. This report gives facts and precedents, not legal advice.*

---

## 0. Summary

1. **What every run needs today.** The port needs a 1.46 GB flat copy of the disc (`extracted/disc.iso`) and three system files [V]. It does **not** need the player's original `.rvz`/`.iso` after `tools/extract.py --iso` has run. It also does not need the 1.42 GB of loose extracted files, which only the tools read [V].
2. **"Import once" (Level 1) is a small change.** It means one app-owned data store, verified by hash, with the executable (the DOL) embedded in the build. The store is about 1.42 GB kept as shipped, or about 1.13 GB recompressed [I]. The work is several days. After it, the ISO can be deleted. The player still has to supply the disc once.
3. **Converting assets to PNG, Opus or glTF (Level 2) gains almost nothing here.** The game's own translated code parses GameCube formats. In this architecture, "native assets" means packs of replacements keyed by content hash, plus caches built at run time.
4. **A full decompilation with an SDK-level platform layer (Level 3) is the Dusklight/Aurora route, and it takes years.**
   - Community decomps took about 1.5 to 6 years, with teams.
   - This repo is at 0.29% [V].
   - Android does **not** need Level 3. Two recompilation ports (Zelda64Recomp and UnleashedRecomp) reached Android without it, using translated code plus a Vulkan renderer.
5. **"No ISO at all" is a remake.** It means replacing every piece of Sega code and every asset. Fan remakes of a publisher's IP have been taken down (AM2R, 2016). The realistic end state is "the player supplies the game once."
6. **For Android, the legal question is the binary, not the ISO.** An APK built here would contain code translated from Sega's and Nintendo's executable. `SPEC.md:26` and G4 rule out distributing that. Peer recompilation projects distribute it anyway. This is the owner's decision (Q3).

---

## 1. Level 0: what the port reads today [V]

**At build time.** `tools/recompile.py:100` reads `extracted/sys/main.dol`. It writes `gen/`: 59,141,610 bytes of C in 18 chunks, plus `dispatch.c` and `functions.h`. The resulting `gen/soa.exe` is 21,625,344 bytes.

**At run time** (`runtime/main.c`):
- **Lines 1139-1144** read three files:
  - `sys/main.dol`, 3,166,656 B;
  - `sys/boot.bin`, 1,088 B;
  - `sys/fst.bin`, 134,426 B.
- **Lines 963-988 and 1151:** `load_dol` copies **all eight sections** into guest memory. That is 2,791,136 B of code (`.text0` 9,472 plus `.text1` 2,781,664) and 375,264 B of data (six sections).
  - So the whole DOL is a run-time input, not just its data sections. The translated C reproduces what the code does, but the bytes still have to sit in guest memory.
  - `.text0` is a ROM image that the boot code copies onto the exception vectors (SPEC §5).
- **Lines 1168-1171** place the file table (FST) just below `ARENA_HI`.
- **Line 1178:** `mod_note_dol`. Data mods check themselves against the DOL's SHA-1.
- **Lines 1192-1193** open `<dir>/disc.iso`. `runtime/dvd.c:91-115` then serves every drive read by its offset on the disc.

**The census reads the disc a second time.** `runtime/aram.c:160-217` reopens `sys/fst.bin` and `disc.iso` for its ARAM census. It finds the directory through MSVC's `__argv`, which is the G4 portability note in PLAN-GAMEPLAY-MODS.

**Nothing else opens the extracted tree.** No other `fopen` in `runtime/` touches `extracted/`. The 5,552 loose files exist only for `tools/`.

**Disk use.** `extracted/` is 2.7 GB:
- `disc.iso`, 1,459,978,240 B;
- the loose tree, 1,418,037,369 B;
- `sys/`.

**Load times are modelled on the real drive.** `dvd.c:149` charges each read 6 ms plus its length at 3 MB/s, in guest time. The largest file, 4,284,399 B, therefore takes about 1.43 s.

**Why loads can't simply be instant.** `dvd.c:46-50` records that completing reads instantly let the SDK's callbacks run before the code that asked for the read had finished.

**Consequence:** faster loads are a separate change in `dvd.c` with its own risk. They do not come from changing where the data is stored.

---

## 2. Level 1: import once

### What is on the disc

Measured read-only from the file table and each file's header [V]:

| | Files | Bytes |
|---|---|---|
| All files | 5,552 | 1,418,037,369 |
| AKLZ-compressed, as shipped | 3,633 | 1,139,727,674 |
| AKLZ, once decompressed | 3,633 | 1,847,887,181 |
| Stored raw | 1,919 | 278,309,695 |
| Whole store decompressed | 5,552 | 2,126,196,876 |
| `disc.iso` | – | 1,459,978,240 |
| End of the last file | – | 1,429,436,950 |

**Where the space goes:**
- `.mld` model/texture containers: 1,791 files, about 1,069 MB.
- `.samp`: 127.4 MB. `.dsp`: 78.6 MB.
- By directory: `field/` 1,030 MB, `sound/` 214 MB.

**What a pack saves over the ISO.** It drops the header, the gaps between files and the tail padding, 41,940,871 B (2.9%) in all.

**Recompression, from a 120-file random sample** (24.7 MB, zstd level 9):
- zstd on the files as shipped: 0.896×.
- Decompress AKLZ first, then zstd: 0.797× of the shipped size.
- **Estimate:** about 1.13 GB for the whole store [I]. This is one sample, weighted by file count.

### The game already accepts uncompressed files [V]

The file reader at `fn_801C64DC` checks four things (disassembled at 0x801C65A8–0x801C660C):
- the bytes `'A','K','L','Z'`;
- the next word, `~?Qd`;
- a float in the header;
- and it decompresses only when all of them match.

`docs/research/content-systems.md:46` records the same thing, including a second reader at 0x801C6870.

**What that means:** an importer may store files decompressed. But three things change [I, to measure]:
- **The FST has to be rebuilt.** File sizes change, so this needs beyond-gamecube's E2 machinery.
- **Heap use may change.**
  - 36 files decompress to more than 3.75 MB; the largest is 5,178,944 B.
  - Heap 4's largest free block was measured at ≥3.75 MB (`beyond-gamecube.md` §4).
  - Whether reading raw files lowers or raises the peak depends on how the reader stages its buffers.
- **Loads get slower.** Bigger files take longer at the modelled 3 MB/s.

**Recommendation:** keep files exactly as shipped by default.

### What changes in this repo

1. **Importer.** Extend `tools/extract.py`, which already decodes RVZ through Python's `compression.zstd` (`tools/soa/rvz.py:14`) and checks the DOL's SHA-1 against `config/GEAE8P/config.yml:6`.
   - It writes one store: an index mapping each FST entry to an offset, length and hash, then the file blobs.
   - A flag skips the loose tree for players.
   - A per-file hash manifest in `config/` is arguably "analysis metadata" under SPEC §2.3. That is the owner's call.
2. **`runtime/dvd.c`.** `disc_read` reads through a store backend that maps disc offsets to files with a sorted extent table. `aram.c`'s `src_build` already walks the FST this way.
   - **Reads outside any file need a defined answer.** Today `disc.iso` returns the drive's regenerated junk there (SPEC R9); a store would return zeros.
   - **Prove it with a verify mode.** It reads both the ISO and the store and compares every read across the scenarios. As a mutation, flipping one byte in the store must make it fail (CLAUDE.md: a new check has to be shown able to fail).
3. **`runtime/main.c`.** It takes the DOL, `boot.bin` and the FST either from the store or from an array that `recompile.py` writes into `gen/`.
   - That array is the same kind of artifact as `gen/`: derived from the DOL, which the build already reads.
   - Embed the whole DOL, not only its data. Nobody has checked that the game never reads its own code as data [I].
   - `mod_note_dol` then hashes the embedded bytes.
4. **`runtime/aram.c`.** The census reads through the same API, which also removes its `__argv` dependency.
5. **Settings.** The `disc =` key read by `runtime/settings.c` points at the store.

**Size:**
- Stop writing the loose tree, and document that the dump can be deleted: hours.
- Embed the DOL, `boot.bin` and FST: a day. This adds one generated file to compile and needs no retranslation of the chunks.
- Store, backend, verify mode, and tests on a synthetic disc: several days.

**What it unlocks:**
- The ISO can be deleted.
- Disk use drops from 2.7 GB to about 1.42 GB (−47%), or about 1.13 GB recompressed [I].
- One file to copy to a Steam Deck or Android device.
- E2's mod overlay plugs into the same lookup.
- Each file is checked against its hash.

**What it does not unlock:** faster loads (that is `dvd.c:149`), mods by itself, or other platforms by itself.

**The legal status does not change.** The store is still Sega's assets, and `gen/` is still translated code, and both stay on the player's machine (SPEC §2).

**On Android.** Importing an RVZ on the device needs a zstd decoder written in C. That is third-party code, which the repo avoids: `SPEC.md:464` says "no third-party runtime dependency," and `vendor/` is forbidden per `beyond-gamecube.md` §4. There are two ways around it:
- Import a plain ISO on the device, which is simple C.
- Import on the PC and copy the store over.

**Precedents** for this pattern:
- **Zelda64Recomp.** Its runtime copies the verified ROM into its config folder: `write_file(config_path / game_entry.stored_filename(), rom_data)`, after an XXH3 check [V, N64ModernRuntime `librecomp/src/recomp.cpp`].
- **re:Blue** "copies the game files out of the discs" into `game\` [V README].
- **OpenGOAL** keeps an `iso_data` folder [V Q2 2026 report].

---

## 3. Level 2: native asset formats, and why they rarely pay here

**The consumer of every asset is the translated game code** [V, SPEC §9]. It parses `.mld`, walks the model data (Ninja's NJCM format), and passes pixel data, already in the GameCube's tiled layout, to `GXInitTexObj`. A PNG, an Opus file or a glTF model gives that code nothing it can read.

In this architecture, Level 2 is three things:

- **Replacement packs keyed by hash.**
  - Textures are M9. They are decoded through WIC today (`beyond-gamecube.md` §4), which is Windows-only, so Android would need a PNG decoder.
  - Music replacement goes through a host mixer (`beyond-gamecube.md` E3, row 12).
- **Caches built at run time, keyed by content hash.** Decoded textures could be persisted. With a mobile GPU backend, CMPR textures could be transcoded to ASTC or ETC2, formats mobile GPUs support natively.
  - Converting textures at import time instead would need a map from each GPU upload back to the file it came from. That map only exists once the loading code is understood [I].
- **Making the install smaller.** For example, the 206 MB of ADPCM audio as Opus [I]. That needs a host decoder and a host mixer path.

**Converting models to glTF** needs either a native model path (Level 3) or the injected-draw API in `beyond-gamecube.md` E3.

---

## 4. Level 3: full decompilation plus an SDK-level platform

It helps to think in **two independent directions**:
- **Code:** from translated to decompiled.
- **Platform model:** from a console modelled at the hardware level (today's `runtime/`) to an SDK-level layer like Aurora.

Today the port is translated code on a hardware-level model. Android can be reached **without moving along either direction**; see §8.

**What a source port like Dusklight must decompile** (SPEC §6 and §7.1; ROADMAP 8.1):
- **Game code:** 5,362 functions, 0x80005600–0x802319E0 = 2,278,368 B, 81.6% of `.text`.
- **Middleware:** 807 functions, 286,600 B, 10.3%.
  - It issues 868 of the 1,508 writes to the graphics FIFO.
  - It contains the Sega sound driver at 0x8027C000–0x80292000 (`beyond-gamecube.md`, row 12).
- **The SDK** (936 functions, 216,464 B, 7.8%) would mostly be *replaced* by the platform layer, not decompiled.
- **Progress:** 83 functions, 8,084 B, 0.29% of `.text` (`docs/PLAN.md:15`). Most are SDK or C-library routines. The first `src/` commit was 2026-09-16.

**Matching is not the same as a port.** After 100%, the Melee team wrote: "Even at 100%, the decomp is pretty unusable in its current state… cleanup… portability bugs… a system to use data files on different platforms" (EventHubs, 2026-09-19). For this game that work includes [I]:
- data files that are big-endian;
- data files that store 32-bit offsets and fix them up into pointers, which become 64-bit on a modern host;
- replacing the guest memory model;
- an audio layer.

**Aurora**, `github.com/encounter/aurora` [V, fetched 2026-09-25]:
- MIT licence.
- Graphics (GX) on WebGPU through Dawn, reaching D3D12, Vulkan and Metal.
- Runs on Windows, Linux, macOS, iOS, tvOS and Android.
- Uses SDL3, and `nod` for disc images.
- `lib/dolphin` holds `dvd, gd, gx, mtx, os, pad, si, thp, vi, AR.cpp, card.cpp`. There is **no ai, ax or dsp** directory.
- `lib/dolphin/dvd/dvd.cpp` opens the disc image with `nod_disc_open_stream` and answers `DVDRead` from it **at run time**.

**So the flagship decomp ports still read the player's disc image every run** [I for Dusklight specifically]. Level 3 does not remove the disc.

**What Level 3 unlocks:**
- GPU rendering at any resolution.
- Game logic at 60 fps.
- The "Track F or never" limits in `beyond-gamecube.md` §10: 80 items per category, 255 enemies, 7 saves.
- Readable code for deep mods.
- Better battery life on phones [I].

**Size:** years (§6).

---

## 5. How other projects handle game data

| Project | Game code in the distributed binary? | How game data arrives | Stated posture | Action against it |
|---|---|---|---|---|
| sm64 decomp and PC port | Decompiled source on GitHub. The build extracts assets from the player's ROM into the output [V README] | ROM at build time; binaries need no ROM | "A prior copy of the game is required to extract the assets" | Nintendo targeted the PC-port **executables** in May 2020: "an unauthorized derivative work" (VGC, 2020-05-08). The source repo `n64decomp/sm64` is still up [V] |
| Ship of Harkinian (OoT) | Yes, binaries of reconstructed code | `.otr`/`.o2r` archive generated at launch from the player's ROM, stored beside the exe or in App Support [V README] | "Does not include any copyrighted assets"; "not distributing any Nintendo owned IP" | None reported (Wikipedia, read 2026-09-25) |
| OpenGOAL (Jak) | Decompiled game source is public; releases are shipped [I] | Extractor turns the ISO into `iso_data` [V] | "Do not use… without… your own legally purchased copy"; "no plans to ever make a mobile release" [V README]. ARM64 compiler work in Q2 2026 [V] | None known |
| Zelda64Recomp (MM) | Yes. Prebuilt releases, and building needs the ROM, so the releases carry translated code [V/I] | ROM picked on first run, checked by XXH3, **copied** into the config folder [V code] | "Releases do not contain game assets. The original game is required to build or run" | None known. An Android fork exists (`linkzenic/Zelda64Recomp-Android`), Vulkan/RT64 with a Turnip driver recommended [V] |
| UnleashedRecomp (Sonic) | Yes. Building needs `default.xex`, `default.xexp` and `shader.ar` [V BUILDING.md], and releases are prebuilt | Installer checks the player's dump. `LdrLoadModule` loads the xex **into guest memory at run time** [V `main.cpp`], the same thing as `load_dol` here | "Does not include any game assets" | None found in my searches [I]. Android fork: prebuilt APK containing the recompiled code, released 2026-07-09, Android 9–11+, bundles a Turnip Vulkan driver [V] |
| re:Blue (Blue Dragon) | Released 2026-08-28 [V thread title] | Installer copies the files off all three discs into `game\` [V README] | "Contains NO ASSETS" | None known |
| Dusklight (Twilight Princess) | Yes. Decomp plus Aurora, on Windows, Linux, macOS, iOS and Android [V site] | Player's disc image, which Aurora/nod read at run time [I] | "Does not provide any copyrighted assets" | None known. v1.0 in May 2026; v2.0.2 dated September 25 on the releases page |
| re3/reVC (GTA) | Reimplementation source and binaries | Needed the PC game | "No code owned by Take-Two" | DMCA in Feb 2021; restored after a counter-notice; sued in Sept 2021; settled and dismissed in 2023. The project never returned [V] |
| Yuzu (a different kind of case) | An emulator | Needed Switch keys and games | – | Nintendo sued 2024-02-26; settled 2024-03-04 for $2.4M. The settlement admits Yuzu was "primarily designed" to circumvent Nintendo's protections [V]. This port decrypts nothing [I] |
| AM2R (fan remake) | Entirely new game | None needed | – | DMCA the day after its 2016-08-06 release [V] |

**The pattern [I].**
- Nobody distributes assets.
- Recompilation projects routinely distribute translated code.
- Takedowns have hit executables (SM64 in 2020), a reimplementation (re3 in 2021), circumvention (Yuzu) and a remake (AM2R).
- Source repositories of *matching* decomps have stayed up.

**Sega-specific:**
- Sega renewed its Skies of Arcadia trademarks in Japan, filed 2025-01-16 (Shacknews and others).
- No remaster has been announced that I found.
- I found no public Sega action against UnleashedRecomp or its Android fork. That is an absence of evidence, nothing more.

---

## 6. How long full decompilations took, and whether this game's is realistic

| Project | Code size on decomp.dev (as displayed; may include overlay modules or several regions) | Timeline | Port |
|---|---|---|---|
| SM64 | – | About 2 years, done 2019 | PC port 2020 |
| OoT | – | 21 months, to Nov 2021 | Ship of Harkinian, Mar 2022 |
| Mario Party 4 | 5.94 MB | 2023-11-19 to May 2025, about 18 months | Partyboard, work in progress |
| Animal Crossing | 3.62 MB | About 2.5 years, to June 2025 | Community port |
| Twilight Princess | 11.49 MB | Aug 2020 to Dec 2025 (GameCube versions matching) | Dusklight, May 2026 |
| Pikmin | 2.21 MB | 100% by Jul 2026 (Android Authority, 2026-07-23) | – |
| Melee | 3.88 MB | About 2020 to Sept 2026, "over six years" | "Still far away" |
| **This game** | `.text` 2.79 MB [V] | 83 functions, 0.29%, since 2026-09-16 | Recompiled port |

**Is a full decompilation realistic here? [I]** For one person working evenings, it is a multi-year project at minimum:
- The comparable projects had teams, reusable SDK source and tooling that already existed.
- This binary has no symbol map (SPEC §3) and no prior community work (SPEC §4.1).
- The SDK part could borrow from Mario Party 4, which has the same SDK 0x2301 banner (SPEC §6), but its licence needs checking.
- The game's own 2.28 MB is where the time goes.

**The incremental path:**

1. **Keep recompilation as the shipping path** (SPEC §4, "recompile first, decompile progressively").
2. **Targeted decompilation for mods** (PLAN-60FPS-MODS F4–F7).
   - A guest-C dialect whose macros compile to plain pointer accesses under mwcc and to `mem_r*`/`mem_w*` under MSVC.
   - The targets total about 8 KB.
   - The decompiled code stays on guest memory, so it mixes freely with translated code.
3. **A GPU backend fed by `gx.c`'s parsed command stream.**
   - This is how the port gets Android performance and high resolution without decompiling anything [I]. The analogues are Dolphin's video backends and the recomps' RT64 path.
   - The part nobody has designed yet is `copy_to_texture` writing tiled bytes back into MEM1 (PLAN.md, "Not worth doing, or not yet").
4. **Reimplementing the middleware natively** (SPEC §7.1 and §12, still open).
   - It is 807 functions, and makes 2 calls into game code out of 3,996 outbound calls.
   - It is the first big block to take on if a native renderer is ever wanted.
5. **HLE of the SDK** (SPEC §7's hybrid, not built; see ARCHITECTURE "Where this differs"). Native replacements of SDK libraries matter only once the code calling them is native.
   - The device models `dsp.c`/`ax.c`, `exi.c`, `si.c` and `dvd.c` are already portable C.
   - An API-level GX layer cannot avoid the pipe anyway: per-vertex data is 1,508 inline stores across 164 functions (SPEC §7).
   - So HLE is not what enables Android.

---

## 7. "No ISO at all"

**What it would take:**
- Replacing all 7,144 functions and the 375 KB of data.
- Replacing all 5,552 files: 1,069 MB of models and textures, 206 MB of ADPCM audio, 258 scripts (the dialogue and the story), and the font.
- The characters, the story and the name are still Sega's IP.

**That is a fan remake**, and the precedent is AM2R's DMCA in 2016.

**The realistic target is "supply once":**
- Level 1 locally.
- Mods distributed as edits and new entries only. `PLAN-GAMEPLAY-MODS.md:805` already has `mod.py pack` refuse any file that matches the player's own files after decompressing.

---

## 8. What this means for Android specifically

**The platform layer.** Off Windows, the runtime compiles but does not run the game [V]:
- `threads.c:310` prints "fibers are Windows-only for now" and exits at the first guest thread.
- `gxr.c:1949-1970` starts rasterizer workers only under `_WIN32`; elsewhere the count is `n = 0`.
- `window.c:462-467` and `audio_out.c:145-149` are stubs.
- `gxr.c:123` and `:143` use `__declspec` with no guard, which MSVC accepts and Android's clang does not.
- `main.c:630-650` falls back to `calloc` without the guard-page tripwire.
- `recompile.py:241` gives the process a 32 MB stack ("guest call depth becomes host call depth"). On Android the guest would need its own thread with a stack at least that big [I].

**The generated C is portable.** It uses no compiler-specific tokens beyond `#pragma once` and calls to `fma()` [V, grep]. An Android build needs `-ffp-contract=off`, so the compiler does not fuse floating-point operations the game computes separately (G4).

**Guest threads.** All 326 saved logs in `build/` say "1 guest threads seen… 0 fiber switches" [V]. Those logs cover early-game scenarios only, so a POSIX context switch is still required [I].

**Rendering speed.** On the Z1 Extreme, the Dangral base needs 12 rasterizer workers to reach 27 fps (commit cb904fa) [V]. Phones have fewer big cores and are throttled by heat, so expect a Vulkan or GLES backend to be necessary [I]. Both Android recomp forks use Vulkan with a Turnip driver [V].

**Android can already play the game.** Dolphin on Android reportedly holds a near-constant 30 fps on a Snapdragon 835 (a Dolphin forum anecdote, undated). What a native port adds is mods, 60 fps and battery life, not the ability to play.

**Distribution:**
- **Sideloading.**
  - ADB installs stay allowed: "Developers and power users can still use ADB…" [V, Google support page].
  - Developer verification is enforced from 2026-09-30 in Brazil, Indonesia, Singapore and Thailand, and globally in 2027.
  - Unverified apps get an "advanced flow" with a 24-hour lock.
  - "Limited distribution" accounts reach up to 20 devices without ID.
- **Loading code at run time.** Apps targeting API 29+ can `dlopen()` a library from the app's data directory, but cannot `exec()` files there [V]. Android 14's read-only rule applies to DEX/JAR/APK files [V].
- **Three routes to a phone:**
  - **(a)** Build the APK on a PC and install it over adb, for personal use.
  - **(b)** Ship a runtime-only APK, and have the player load their own `libgame.so` built on their PC [I, a design].
  - **(c)** Ship a prebuilt APK, as the peers do. That conflicts with SPEC §2.

---

## 9. Where the legal line sits: facts only

**Who owns what in the binary:**
- Sega: the game code, the assets and the trademarks.
- Nintendo: the SDK, 7.8% of `.text`.
- Metrowerks: the MSL C library.

**What the repository publishes:**
- `config/`: addresses and hashes. SPEC §2.3 counts these as facts, not copies.
- `runtime/`: original code.
- `src/`: byte-matching reconstructions of Nintendo, Metrowerks and Sega code.
  - `PLAN-GAMEPLAY-MODS.md:1442`: "copyright in `src/` is the larger" exposure.

**What never leaves the player's machine:** `gen/`, `soa.exe`, `extracted/`, the store, and `build/`. That is SPEC §2 rules 1–2 and `SPEC.md:26`.

**Decisions only the owner can make:**
- **Q3, distribution:** stay source-only; build a one-step build on the player's machine (G4); or ship prebuilt binaries like Zelda64Recomp, UnleashedRecomp and re:Blue.
- **Q8, the name.**
- **Whether a per-file hash manifest counts as metadata.**
- **For Android:** personal sideloading only, or a public APK.
