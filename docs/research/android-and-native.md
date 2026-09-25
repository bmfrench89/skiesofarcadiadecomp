<!-- Written 2026-09-25 from four read-only research reports and a skeptic's check of each report's
key claims: docs/research/port-portability.md, port-performance.md, port-android.md and
port-beyond-iso.md. Nothing in the repository was changed and the game was not run. Where a report and
this summary disagree, this summary carries the skeptic's corrections. [V] = checked in code, a tool run or
a dated page; [I] = inference. Record what a run shows in docs/FINDINGS.md. -->

# Android, and life without the ISO

*Read-only research, 2026-09-25, HEAD `12e45a8`. **[V]** means checked in code, a tool run or a dated page. **[I]** means inferred.*

## 1. The short answer

An Android port is feasible, and the operating-system part is small. When built for Android ARM64, only 4 of 25 runtime files fail to compile (21 errors), and the translated game code compiles unchanged [V].

The biggest job is speed. The renderer draws in software on the CPU. The owner's Z1 Extreme manages about 27–28 fps in the heaviest measured scene using 12 threads, and phones are slower. In this game a slow frame rate plays as slow motion, not as skipped frames. A GPU renderer (Vulkan) is the real project, and it takes months [I].

On the disc: the port can stop needing the ISO. Import it once into one file the port owns (about 1.4 GB) and build the executable into the local build. What it cannot have is a version with no game data at all. The art, music and story belong to Sega, and replacing them means a remake.

## 2. What "native" already means

- **The code is native.** `gen/` is the game's 7,144 PowerPC functions translated to C and compiled to machine code. Nothing interprets PowerPC instructions at run time [V].
- **The hardware is modelled.** `runtime/` stands in for the graphics chip, audio DSP, memory card, pads and disc drive [V].
- **Four disc reads at run time:**
  - `sys/main.dol`, copied whole into modelled memory (`main.c:963-988`);
  - `boot.bin` and `fst.bin` (`main.c:1139-1144`);
  - `disc.iso`, which serves every asset by disc offset (`main.c:1192-1193`, `dvd.c:79-115`).
  - The `sys/` files are byte-for-byte slices of `disc.iso` [V].
- **The data is kept twice.** `extracted/` is 2.7 GB: `disc.iso` (1.46 GB) plus 1.42 GB of loose files that only the tools read [V].
- Load times imitate the real drive (`dvd.c:149`), so moving the data will not make loading faster.

## 3. Moving away from the ISO

| Level | What it takes | Size | What it unlocks |
|---|---|---|---|
| 1a. One copy | Stop writing the loose files; read the `sys/` parts through `disc.iso`'s header | hours | 2.7 → 1.46 GB |
| 1b. Build the executable in | Put the DOL, `boot.bin` and the file table into `gen/` (the same legal class as `gen/`) | a day | Only the asset image is needed at run time |
| 1c. Import once | An importer for ISO/GCM/RVZ (`tools/soa/rvz.py` exists) that checks `GEAE8P` and the DOL hash, then writes one store. `dvd.c` reads the store, and a verify mode compares every read with the ISO | several days | Delete the ISO; one file to copy to a Deck or phone; a base for mod overlays (E2) |
| 2. "Native" formats (PNG, Opus, glTF) | The translated code only reads GameCube formats, so this means replacement packs keyed by hash (M9) and caches, not converting files | week-plus each | Mods, smaller installs |
| 3. Full decompilation plus an SDK-level layer (the Dusklight/Aurora route) | 83 of 7,144 functions (0.29% of the code) match today; comparable projects took 1.5–6 years with teams | years | GPU rendering and 60 fps logic from source. Dusklight *still* reads the disc image on every run |
| 4. No game data | Replace 5,552 files and every function; the characters and story stay Sega's | a remake | Nothing new. AM2R, a fan remake, was taken down in 2016 |

**About the store:**
- The files as shipped total 1,418 MB, so dropping the ISO's padding saves only about 39 MB. The real gain is deleting the duplicate [V].
- Undoing the game's own compression and then applying zstd gives about 1.16 GB [I, from a 150-file sample]. That needs a third-party decoder.
- Storing files decompressed would work, because the reader at `0x801C65A4` checks for the AKLZ header. But it means rebuilding the file table, so keep the files as shipped [V].
- Precedents [V]: Zelda64Recomp copies the hash-checked ROM into its own folder once; re:Blue copies the files off its discs.

## 4. Android

### The work list

| Item | Size | Evidence |
|---|---|---|
| Portability layer: atomics, waits, clocks, `mmap` guard pages, paths (Android's working directory is `/`) | several days | NDK clang errors: `gxr.c` (17), `dvd.c:103`, `gx.c:188`, `selftest.c:122,344` [V] |
| clang/NDK build profile, a `.so`, Gradle | several days | `toolchain.py:100` and `recompile.py:226-241` are MSVC-only. NDK r28c, SDK 34–36.1 and adb are already installed [V]. Full compile about 14 core-minutes [I] |
| Silent ARM64 and 64-bit bugs | several days | below |
| Threads | hours | below |
| Touch and controllers feeding `window_pad` (`window.c:398`) | several days | One entry point; pad recordings keep working [V] |
| Audio: AAudio/Oboe or SDL3, 32→48 kHz | a day | `audio_out.c` [V] |
| Import through Android's file picker (SAF) | several days | level 1c |
| App shell: lifecycle, surface loss, a clock that pauses | week-plus | `hle.c:289` uses wall time [V] |
| GPU renderer | months | below |

### Bugs that compile fine and give wrong results [V]

- **Render queue.** It relies on x86 never reordering two loads. The comment at `gxr.c:1742-1746` says so: "this machine does not reorder two loads… it emits nothing". ARM64 does reorder them, so a worker can read a stale draw; Windows on ARM would break the same way. Fix: use acquire loads.
- **Fused multiply-add.** clang fuses `a*b+c` into one operation on ARM64, and also on x86 when tuned for Zen 4. Pass `-ffp-contract=off` to both `gen/` and `runtime/`.
- **Float-to-int casts.** The renderer's casts are unclamped (`gxr_tev.c:1109-1113`, `gxr.c:1222`). Out-of-range values give INT_MIN on x86 but saturate on ARM. Clamp first.
- **64-bit `long`.** On Linux and Android `long` is 64 bits. The native `memset` replacement (`src/sdk/msl/fillmem.c`, bound at `config/hle.txt:26`) would then write 64 bytes per 32-byte block. `strcmp.c:18` makes the same assumption.
- **Math libraries.** `exp2f` and `log2f` can differ by one ulp (the smallest float step) between libraries, so frame hashes may move. Look at the frames before re-blessing.

### Threads

- All 326 logs in `build/` report "1 guest threads seen … 0 fiber switches" [V], and `OSCreateThread` looks dead-stripped from the binary [I].
- The fix is to move the same-stack `longjmp` (`threads.c:283-287`) out of `#ifdef _WIN32`. Today every non-Windows build exits at the first thread resume (`:308-311`) [V].
- Android lacks `swapcontext`. If a second thread ever appeared, it would need a coroutine library or its own host thread.

### GPU renderer

- **Where it plugs in.** The producer already turns the graphics command stream into self-contained draws, so a Vulkan backend can consume them in place of the software workers [V].
- **Logic ops (hard).** The game uses OR and AND in 14 of 35 captures. Vulkan supports logic ops only as an optional feature, and GLES not at all [V].
- **Frame copies (hard).** The game copies the rendered image into its own memory and samples it back. Capture 6000 makes two 640×480 copies into display memory. `PLAN.md:957` calls this "the undesigned part" [V].
- **Aurora is not a drop-in.** It is MIT-licensed and runs on Android, but it aborts on OR/AND, keeps copies on the GPU only, and brings Dawn, SDL3 and C++.
- **Estimate:** 2–4 months of evenings [I]. Keep the software renderer as the reference to compare against.

### Performance

| Measure | Value |
|---|---|
| Z1E, Dangral base, every frame drawn | About 27–28 fps with 12 workers, about 10% spread between runs [V] |
| Z1E game-logic thread per frame | Median about 12 ms; the heaviest run averages about 18 ms, against a 33.3 ms budget [V] |
| Snapdragon 8 Elite vs the Z1E's top-10% Geekbench 6 scores (2026-09-25) | 1.09× single-core, 0.78× multi-core [V] |
| Software renderer, 8 Elite | About 24 fps cool, about 17 when warm [I] |
| Software renderer, Snapdragon 7-series | About 6–14 fps [I] |

- **The phone rows are a crude model.** Part of its throttling input comes from GPU tests, not CPU tests. The renderer also splits rows equally between cores, while phones mix fast and slow cores [I].
- **With a GPU backend,** only the game-logic thread stays on the CPU. That is fine on 2024–26 flagships and borderline on 7-series chips [I].
- **Dolphin reportedly already plays this game on Android** [I]. A native port would add 60 fps interpolation, native mods and better battery life, not the ability to play.

### Distribution

| Route | Translated code handed out? | Trade-off |
|---|---|---|
| Build on the player's PC, install over USB with `adb` | No, the player's copy only | Fits SPEC §2. Google's developer verification leaves adb alone [V]. Each friend builds their own |
| Prebuilt runtime-only APK that loads a player-built `libgame.so` | No | Shareable. `dlopen` from app data is allowed (Android 10 banned only `execve`). Android 17 wants such files read-only. The runtime/game boundary must be versioned. Week-plus [V/I] |
| Compile on the phone | No | A compiler of about 100 MB or more, the Python recompiler rewritten, minutes to tens of minutes at first launch [unverified]. No surveyed port does this |
| Prebuilt full APK, as Zelda64Recomp-Android, UnleashedRecomp-Android and Dusklight do | Yes | The norm on GitHub; conflicts with SPEC §2 rule 2 |

None of these routes fits Google Play: its copyright policy rules out the game code, and it bans downloaded code. Developer verification goes global in 2027. The phase starting 2026-09-30 covers only installs from seven app stores in four countries [V].

## 5. Suggested path

Each step pays off before Android does.

1. **Proton smoke test** on Linux or the Steam Deck: hours.
2. **clang on Windows:** the portability header, the four compile fixes, the `threads.c` fix, `-ffp-contract=off`, a compile-only CI job, and replay 23/23. Several days.
3. **Import once on the PC:** several days. Frees 1.4 GB now.
4. **Native Linux x86-64 with SDL3:** week-plus. It catches the 64-bit `long` bug and covers the Deck.
5. **Linux ARM64 or Windows on ARM:** atomics, clamps, replay at 1/2/3/8 threads. Week-plus.
6. **Android shell,** slow but playable: several weeks.
7. **Vulkan backend:** months. It also gives the PC 60 fps and higher resolutions.

Rough total [I]: 2–3 weeks of evenings to native Linux, a week more for ARM64, and several more weeks to a slow Android build. "Plays well on phones" is months away.

## 6. Decisions for the owner

- **Distribution (Q3, section F's G4):** personal sideloading only, a runtime-only APK, or prebuilt binaries like the other projects.
- **SDL3 (Q6):** it reopens "no third-party runtime dependency" (`SPEC.md:463-464`), but it covers window, pads and audio on Linux, the Deck and Android at once. It would be fetched at build time, because `vendor/` is refused.
- **GPU backend:** a Vulkan backend of the port's own or a fork of Aurora. Either way, GPU frames will not match the 23 pinned hashes bit for bit.
- **Target devices:** 8 Elite-class handhelds only, or mid-range phones too. Mid-range also needs the game-logic thread speed-ups (H13).
- **Store format:** files as shipped or recompressed with zstd. Also, whether a per-file hash list in `config/` counts as metadata (SPEC §2.3).

---

## Load-bearing claims and their evidence

1. **The runtime reads only four things from `extracted/`, and the `sys/` files are slices of `disc.iso`.** [V]
   - `main.c:1087`, `:1139-1144`, `:1192-1193`; `dvd.c:79-115`.
   - `aram.c:196-217` re-reads `fst.bin` and `disc.iso`, but only for a diagnostic count.
   - A grep of every `fopen` in `runtime/` finds no other disc path.
   - Python byte comparisons: `boot.bin` == iso[0:1088]; `main.dol` == iso[0x1EC00 : +3,166,656]; `fst.bin` == iso[0x323E00 : +134,426].
2. **Only 4 of 25 runtime files fail to compile for Android ARM64.** [V]
   - NDK r28c (28.2.13676358, clang 19.0.1), `--target=aarch64-linux-android29 -std=c17 -fsyntax-only`, at HEAD `12e45a8`.
   - 21 errors: `gxr.c` 17, `selftest.c` 2, `dvd.c` 1, `gx.c` 1. All 19 `gen/` files pass with warnings only.
   - This was a syntax check; nothing was linked.
3. **Every non-Windows build exits at the first thread resume.** [V]
   - `threads.c:282` opens `#ifdef _WIN32`; `:283-287` hold the same-fiber `longjmp`; `:308-311` print "fibers are Windows-only for now" and call `exit(6)`.
   - Across the 326 logs, runs resume a thread 432 to 126,524 times.
4. **The game runs one guest thread.**
   - [V] All 326 logs (2026-09-16 to 09-25) say "1 guest threads seen … 0 fiber switches", and none says "new guest thread".
   - [V] `config/functions.tsv:5447-5448`: `OSClearContext` 0x802336D4 plus 36 bytes ends exactly at `OSDumpContext`.
   - [V] `config/functions.tsv:5522-5523`: `__OSReschedule` 0x80237C84 plus 48 bytes ends exactly at `OSCancelThread`.
   - [V] No 0x9032 (the new-thread MSR value) appears in `gen/`.
   - [I] That `OSCreateThread` was dead-stripped is inferred from this layout.
5. **The render queue assumes x86 load ordering.** [V code]
   - HEAD `gxr.c:1742-1746`: the comment plus `_ReadWriteBarrier()`, a compiler-only barrier.
   - `volatile LONGLONG g_published/g_ran` at `:1547-1548`; the spin at `:1717`; the same pattern at `:1619` and `:1697`.
   - Microsoft Learn's `/volatile` page gives `/volatile:iso` as the ARM default.
   - This is a race found by reading the code, not an observed failure.
6. **clang fuses multiply-adds unless told not to.** [V, compiler probe]
   - NDK clang 19 `-O2` emits `fmadd` for `a*x+b*y+c` on aarch64 (Android and Windows targets).
   - It emits `vfmadd231ss` on x86_64 with `-march=znver4`.
   - With `-ffp-contract=off` it emits separate `fmul`/`fadd`.
   - Today's MSVC build uses `/fp:strict` (`toolchain.py:100`).
7. **The native `memset` replacement assumes a 32-bit `long`.** [V code; not executed on a 64-bit-`long` build]
   - `src/sdk/msl/fillmem.c` uses `unsigned long *w`, with a value filled only to 32 bits and 8 stores per 32-byte block.
   - The unit is built natively (`config/GEAE8P/units.txt:11`), and `memset` 0x80005434 is bound to it (`config/hle.txt:26`).
   - `strcmp.c:18` states the same assumption.
8. **The performance figures.**
   - [V] `docs/FINDINGS.md:2579-2592`: 27.2 / 26.8 fps with 12 workers. The "Copy images" entry: pooled 25.9 → 28.3 fps.
   - [V] `docs/research/performance.md:58-59`: per-run averages over 57 logs, power mode not recorded.
   - [V] Slow motion comes from H2 (`FINDINGS.md:1637-1641`).
   - [I] The phone projections come from Geekbench 6 medians scraped 2026-09-25 and `scratchpad/android/model.py`. Part of the throttling input is GPU tests.
9. **The hard parts of a GPU backend.**
   - [V] `tools/fifo.py` decode of all 35 captures: logic mode (`PE_CMODE0` 00713E for OR, 00113E for AND) is in effect in 14.
   - [V] Capture 6000: two 640×480 R8 copies to 0x35D4E0 and 0x3A84E0, sampled as I8, then the display copy (004803) to 0x35D4E0.
   - [V] `PLAN.md:955-958` names the copies as the undesigned part.
   - [V] Aurora at main `0812291`: `lib/gx/gx.cpp:137-139` hits `DEFAULT_FATAL` on any logic op other than CLEAR, COPY or NOOP; `GXFrameBuffer.cpp:206` `GXCopyDisp` is empty.
10. **The store sizes.**
    - [V] Parsing the file table gives 5,552 files and 1,418,037,369 B; `disc.iso` is 1,459,978,240 B.
    - [V] The net saving is about 38.6 MB once the `sys/` files (3,302,170 B) are kept.
    - [I] zstd level 9 on a size-weighted 150-file sample (164.1 MB): 0.819× when decompressed first, 0.939× on the shipped bytes.
    - [V] The AKLZ check is at 0x801C65A4–0x801C660C.
11. **Distribution posture.**
    - [V] `SPEC.md:45-46` (§2 rule 2) forbids committing generated code, and `PLAN-GAMEPLAY-MODS.md:1415-1417` (G4) reads that as ruling out a prebuilt exe.
    - [V] Other projects ship full APKs on GitHub (checked with `gh release view`): Zelda64Recomp-Android 0.6.10 (2026-07-29), UnleashedRecomp-Android v0.5.3 (2026-07-22), Dusklight v2.0.2 (2026-09-25).
12. **Android platform rules.** [V]
    - developer.android.com/developer-verification/guides: "ADB workflow and experience stays the same".
    - The 2026-09-30 phase covers seven participating stores in Brazil, Indonesia, Singapore and Thailand; the global phase is in 2027.
    - Android 10 behavior changes: apps targeting API 29+ cannot `execve()` files in their home directory, but `dlopen` still works.
    - Android 17 behavior changes: files loaded with `System.load()` must be read-only. Direct native `dlopen` is not mentioned.

**Side finding [V]:** `emit.py:645-647` translates `mtfsb1 29` at `0x80231AC8` (the SDK turning on non-IEEE mode in `OSInit`) as setting FPSCR bit FX (`1u<<31`) instead of NI (`1u<<2`). The cause is that `decode.py:284-291` never sets `bo`, which stays 0. The bad code is at `gen/chunk_013.c:28347-28348`. It is harmless today, but FX leaks into CR1 and `mffs`. The implementation session confirmed it the same day and put the fix (the bit number from the `rd` field, with a translator test) into its next full retranslation.

## 7. Recommended ordering (2026-09-25)

Three independent advisors (value to the owner, wasted work, sequencing across the three plans) and a reconciler answered "should the implementation session pivot?". The answer assumes the owner's priorities run: gameplay mods, then not needing the ISO, then Android, then 60 fps. That ordering is the planning session's reading of the conversation, not something the owner stated; if 60 fps matters more, H17 moves up.

**Verdict: don't pivot, reorder.**
- **Finish H13 first.** It is mostly written, it gates turbo (M11), and mid-range phones need it.
- **Then the gameplay comfort pack and ISO step 1a**, rather than the rest of Track H. Milestone 1 needs neither M6 nor M8 (PLAN-GAMEPLAY-MODS.md section E).
- **Decide the GPU backend now, not after H15d.** Android needs a Vulkan backend whatever SIMD spans achieve, and that backend is also the PC's route to 60 fps.

**Next, in order:**
1. H13a/b and the mtfsb fix, in one retranslation.
2. The neighbour-fence change, committed on its own, with replay 23/23 at 1, 2, 3 and 8 threads.
3. Manifest v2: `mod.c` refuses any `api` but "1", so the first API bump would refuse every mod.
4. P1, P6, P11 and T0: hours each.
5. M11 with turbo, now that H13 is in.
6. ISO step 1a: 2.7 GB of disc data becomes 1.46 GB.
7. The rest of milestone 1: H19, M18, the chords, the M5 first-run amendment, M19, P10, P3 and P5.
8. M8 with M7a/b.
9. T9, then T1 with ISO steps 1b/1c as one disc layer, since both rewrite `disc_read`.

**Deferred, and what brings each back:**
- **H15d, the rest of H15c, H16 and H18:** only if the GPU answer is no.
- **H17a/b:** after milestone 1 either way. It works on draw commands, so a GPU backend keeps it.
- **H13c:** if turbo shows the game thread is the limit.
- **H9:** if an owner session shows judder.
- **Vulkan, Linux and Android:** after the owner decides. Until then, only a Proton smoke test and a clang compile-only CI job.

**Hygiene now, in code already being edited:**
- Read `g_published` and `g_ran` in `gxr.c` through acquire loads. The x64 machine code stays the same, and the ARM race goes away.
- Route any fma inlining through one macro, with a plain `fma()` fallback and an exact-rounding test.
- New native code uses `uint32_t`, never `long`.

**Owner decisions this waits on:**
- approve the reorder;
- the GPU backend, and whether Android is a firm goal;
- which handheld, and whether it runs at 60 or 120 Hz;
- the ISO store format, and whether T1 takes deltas.

## Supporting reports

- [port-portability.md](port-portability.md): every Windows-only dependency in `runtime/` and the build, and the ARM64 correctness issues.
- [port-performance.md](port-performance.md): measured speed on the Z1 Extreme, phone projections, and what a GPU backend takes.
- [port-android.md](port-android.md): how other native ports ship on Android, controls, storage, distribution and on-device building.
- [port-beyond-iso.md](port-beyond-iso.md): the levels from "reads the ISO every run" to "fully native", precedents, and the legal line.
