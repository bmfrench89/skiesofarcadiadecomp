<!-- Written 2026-09-25 by a read-only research agent on whether the port would run well on a phone, and the GPU backend, at HEAD 12e45a8. Nothing in
the repository was changed and the game was not run; compiler probes and syntax checks ran in a scratch
directory only. A second agent then checked this report's key claims; its corrections come first, below,
and supersede the text where they disagree. The summary built from all four reports is
docs/research/android-and-native.md. [V] = checked in code, a tool run or a dated page; [I] = inference. -->

# Android, part 1: would the port run well on a phone, and what would it take?

> **Corrections from verification.** A skeptic checked this report's key claims; these did not fully hold.
>
> - **partly:** The game thread needs a median 11.9 ms and at most 18.2 ms a frame on the Z1E. Its uncapped ceilings are 50.3 fps (opening), 104.1 (battle) and 80.4 (ship battle).
>   - **Correction:** The ceilings hold: FINDINGS.md:1752-1754 gives 50.3 (p50 19.4 ms), 104.1 (p50 8.8) and 80.4 (p50 12.4). They were measured in snapshot mode at SOA_SPEED=4 with 8 raster threads on the 2026-09-24 build. The 11.9 / 18.2 figures come from performance.md:58-59. They are per-run averages (wall x (1 - SelectThread - spins)) over 57 snapshot logs from the 09-21/22 builds, and performance.md:18 says no log recorded the power mode. So 18.2 ms is the heaviest run's average, not a per-frame maximum, and 'at most 18.2 ms a frame' is wrong. H3 (FINDINGS.md:1757-1760) measured the opening's median frame at 19.4 ms of guest-thread time alone. H2 (:1632-1635) found uncapped frames that stepped 2-3 fields. Correct wording: median about 12 ms and the heaviest run averaging about 18 ms. Individual frames and the opening's median exceed 18.2 ms.
> - **partly:** The pixel path costs about 46 ns a fragment on one thread after H15c, and about 90 ns at 8 threads under the handheld's power limit. A drawn frame has 0.72M-3.62M fragments.
>   - **Correction:** 46 ns on one thread holds: FINDINGS.md:2571-2572 gives 54.2/50.5 -> 46.5/45.5 ns. The 'about 90 on eight' figure (:2463-2464) was measured on the H15a build, when one thread cost about 59-60 ns. No 8-thread ns/fragment figure has been published since H15c, so pairing 46 with 90 mixes two builds. Blaming the power limit also goes beyond the source. :2464-2468 says the cause 'is not yet separated' and lists the power limit, SMT siblings shared with the producer, and memory contention. The 0.72M-3.62M range comes from the seven scenes of the H6 benchmark set (:1716-1723: battle a101b 0.72M, Dangral field 3.62M), not from a survey of the game. The live H1 runs averaged 1.45-2.40M a frame (:1588-1591).
> - **partly:** Scaling the Z1E's Dangral frame (about 18 ms producer + 19 ms raster) by those ratios gives the software renderer about 24.5 fps fresh / 17 warm on an 8 Elite, 30 / 21 on an 8 Elite Gen 5, and 6-14 fps on 7-series chips. Because the logic is per frame, that is slow motion.
>   - **Correction:** The arithmetic reproduces: model.py prints 8 Elite 24.5/17.3, 8EG5 30.0/21.3 and 7-series 6.4-14.2. The inputs are weaker than the claim suggests. (1) The throttling sources are misattributed. Only Beebom's 73% is a 15-minute CPU test on the 8 Elite. Android Authority's 58% (2025-09-24) is a 3DMark Wild Life GPU stress test on an 8 Elite Gen 5 reference phone. AndroidHeadlines' 'under 30%' (2025-11-06) is a GPU stress test on a realme GT8 Pro (8 Elite Gen 5). So the 0.65 multi-core sustained factor rests on GPU tests of a different chip. (2) The 18+19 ms split is inferred, and the model adds the two serially. At HEAD the workers are idle about half the Dangral window, the guest thread spends 30-40% in SelectThread, and the frame is held by ordering and the frame gate (FINDINGS 'Palette loads' and 'Copy images'), not a serial sum. The Dangral figure is now 28.3 fps pooled. (3) The model divides by the Z1E's p90 but the phones' medians, and it assumes GB6 multi-core scales linearly to a 12-worker row split. (4) On Android today, runtime/gxr.c does not compile (Win32 atomics, Sleep, YieldProcessor, __declspec), and its non-Windows branch starts zero workers, so the multi-core term is hypothetical. The slow-motion point holds when every frame is drawn, since H2 (FINDINGS.md:1637-1641) shows the logic advances once per presented frame. Skipping frames, as snapshot mode does at about 29.4 game fps, would keep full speed at the cost of smoothness [I].
> - **partly:** The game uses GX logic ops other than COPY/CLEAR/NOOP (OR, AND, NOR, EQUIV) in 16 of 35 captures. Aurora hits a fatal error on any logic op other than CLEAR, COPY and NOOP.
>   - **Correction:** The count and the op list are wrong. The Aurora half holds. I decoded all 35 captures (23 in build/fifo plus 12 in build/perfset) with tools/fifo.py and classified every PE_CMODE0 write, with 0 BP_MASK writes found. Logic mode is effective (logic bit set, blend and subtract clear) in 14 of 35, using only OR (0x00713E) and AND (0x00113E), always as 2 ORs and 1 AND. The 14 are corpus 1550, 4500, 4800, 6000, 6300, 15200, 15800 and 16300, perfset corpus 6000 and 15800 (copies), and the cutscene 4500/4501 and field 5000/5001 pairs. That is 8 distinct corpus scenes, not independent samples. NOR, EQUIV and the other ops appear only in a raw byte scan for 0x61 0x41. My reproduction of that scan gets 17 hits, including false positives in 4200, battle/4000 and battle/4001, where the bytes fall inside non-BP data. The Aurora half holds at encounter/aurora main 0812291 (2026-09-25). lib/gx/gx.cpp:137-139 has `case GX_BM_LOGIC: switch(op){ DEFAULT_FATAL("unsupported logic op {}")` with only CLEAR, COPY and NOOP handled. regs.cpp decodes BP 0x41 into GX_BM_LOGIC, so OR and AND would reach the fatal.

*Read-only research, 2026-09-25. Nothing was run except `python tools/fifo.py` on one capture and a byte scan of the `.fifo` captures, both written to the scratch folder. **[V]** means I read it in a file at a given line, a log figure, a scraped page or source code. **[I]** means it is inferred. Scratch files, including the benchmark scrape, the model and the downloaded Aurora and WiiCompiled sources, are in `C:\Users\bmfre\AppData\Local\Temp\claude\c--Users-bmfre-Documents-Github-SOA\9c0b5de4-3d3f-44f9-a448-811014adcd50\scratchpad\android\`.*

## Short answer, for the owner

- **The software renderer is not viable on phones.**
  - On your Z1 Extreme the heaviest measured field scene (the Dangral base) now runs at about 27 fps with every frame drawn. It keeps 5–7 CPU cores busy.
  - The same arithmetic puts a 2025 flagship phone at about 24 fps at first and about 17 once it heats up. The newest chip (Snapdragon 8 Elite Gen 5) reaches 30 at first and about 21 when warm. Mid-range Snapdragon 7-series phones land at 6–14 fps. [I]
  - This game counts time in frames, so a slow frame rate plays the whole game in slow motion rather than dropping frames (FINDINGS H2 [V]).
- **A GPU backend is the prerequisite for Android.** With the drawing on the phone's GPU, only the recompiled game thread is left on the CPU.
  - 2024–2026 flagships (8 Gen 3, 8 Elite, 8 Elite Gen 5) have room to spare.
  - Upper mid-range (7+ Gen 3) is borderline in heavy scenes.
  - Plain 7-series chips (7 Gen 3/4, 7s Gen 3) need the planned speed-ups to the game thread (H13) first. [I]
- **Dolphin already plays this game on Android.** What a native port would add is mainly true 60 fps by building in-between frames, native mods, and no emulator setup. A GPU backend is also what would eventually make it lighter on battery. It does not add raw playability on today's flagships.
- **Size:** a GPU backend written in C against Vulkan is roughly 2–4 months of evenings for someone who knows Vulkan [I].
  - The hard part is the one PLAN.md:954-958 already names: copies of the rendered image that the game writes back into its own memory.
  - Aurora (a GameCube graphics library) fits better than expected, because it now decodes the raw command stream. But it cannot run this game's graphics as it stands (details in §4).

---

## 1. What the repository measured on the Ryzen Z1 Extreme

**Machine:** Ryzen Z1 Extreme, 8 cores and 16 threads. H1, H3 and H6 were measured "on AC power, Windows power plan Turbo" (FINDINGS.md:1580, :1714) [V].

| Measure | Value | Source |
|---|---|---|
| Game-thread time a frame, headless runs with most frames skipped, speed 1 | median **11.9 ms**, range 3.4–**18.2 ms** (warp and spoof runs). Includes the command-stream parse (0.3–3.2 ms) and 1–7% waiting | performance.md §1 [V] |
| Game-thread ceiling, uncapped, clock at 4× | opening **50.3 fps** (p50 19.4 ms), battle **104.1** (8.8 ms), ship battle **80.4** (12.4 ms) | FINDINGS.md:1749-1753 (H3) [V] |
| Fragments a drawn frame, 640×480 | median 2.21M (1.19–2.98M, max 3.44M); the Dangral base 2.40M live; per perfset capture: field 3.62M, battle 0.72M | performance.md §2; FINDINGS.md:1591, :1716-1723 [V] |
| ns a fragment, 8 threads | 122 live (H1); **85.4** on single-frame replays (H6); 89.5–97.3 after H15a/b | FINDINGS.md:1607, :1724, :2457 [V] |
| ns a fragment, 1 thread | 58.8 (H15a/b) → 49.0 (H15c, stages 1–2) → **~46** (H15c stage 3) | FINDINGS.md:2460, :2531, :2571-2574 [V] |
| 1 thread against 8 | "about 60 ns on one worker and about 90 on eight", put down to power-limited clocks, SMT siblings and memory contention | FINDINGS.md:2462-2467 [V] |
| Frame rate, every frame drawn | the Dangral base went from **17.7 fps (H1)** to about **27 fps** (27.2 / 26.8 fps with 12 workers, p50 about 36.5 ms) | FINDINGS.md:1596-1597, :2582, :2590-2592 [V] |
| Cores used | 8 workers spinning: 8.4–8.9 cores at any load (H3); after H11, the title costs 1.2 cores and a drawn Part L run 6.5; now about **4.9** (Part L 3000) and **7.3** (Part L 9000) | FINDINGS.md:1786-1792, :1884-1886 [V]; the last two derived from CPU seconds and fps at :2647-2650 [I] |

**What each step of H11–H15 improved** [V]:
- **H11:** idle workers sleep. The title costs 1.2 cores instead of 8.8.
- **H12:** a texture is hashed once per epoch. Prepare fell from 3.9 ms to 0.21 ms a frame, and the frame rate barely moved.
- **H14:** the copy drains are gone. Part L 3000 went from 24.55 to 27.0 fps, the Dangral base only 18.7 to 18.9 fps. The gain was in pacing, not throughput.
- **H15a/b:** −3.5% on the pixel path.
- **H15c:** about 59 → 46 ns a fragment at one thread, and 12 workers by default, which lifted the Dangral base to about 27 fps.
- **Palette loads:** decode fell 79–93% with no change in fps (FINDINGS.md:2641-2664). That entry also shows where the Dangral frame is now held. The game thread is about 40% idle and the workers are idle about half the time. What holds the frame is the ordering between them: a draw that samples an earlier copy of the image waits for the workers to finish.

**Power caveats** [V]:
- The same benchmark drifted 85.4 → 98.0 → 113–128 ns on identical code within a day. FINDINGS.md:1908 says "Measure on this machine interleaved from now on".
- No run records energy. H20 proposes a power line "that feeds the GPU-backend decision" (PLAN-GAMEPLAY-MODS.md:1401).

## 2. Estimating the same on 2025–2026 phones

**Benchmarks.** These are Geekbench 6 medians of the latest roughly 75–100 uploads per chip, scraped from browser.geekbench.com on 2026-09-25 [V]:

| Chip | GB6 single-core | GB6 multi-core | Single vs Z1E | Multi vs Z1E |
|---|---|---|---|---|
| Ryzen Z1 Extreme (all runs; **p90 used as the Turbo, AC-power reference**) | 2,237 (p90 2,560) | 8,932 (p90 11,119) | 1.00 | 1.00 |
| Snapdragon 8 Elite Gen 5 (SM8850) | 3,543 | 10,563 | 1.38 | 0.95 |
| Snapdragon 8 Elite (SM8750) | 2,802 | 8,689 | 1.09 | 0.78 |
| Snapdragon 8 Gen 3 (SM8650) | 2,110 | 6,398 | 0.82 | 0.58 |
| Snapdragon 7+ Gen 3 (SM7675) | 1,807 | 4,709 | 0.71 | 0.42 |
| Snapdragon 7 Gen 4 (SM7750) | 1,316 | 4,038 | 0.51 | 0.36 |
| Snapdragon 7s Gen 3 (SM7635) | 1,208 | 3,242 | 0.47 | 0.29 |
| Snapdragon 7 Gen 3 (SM7550) | 1,130 | 3,055 | 0.44 | 0.27 |

**Cross-check:** Geekbench's own charts are now Geekbench 7. There the Z1E scores 1,972 / 10,821 and a Galaxy S25 Ultra (8 Elite) 2,475 / 8,888, which gives 1.26 / 0.82 [V]. Against the Z1E's *median* rather than its p90, GB6 gives 1.25 / 0.97. The ratios therefore carry about ±15% depending on which Z1E power mode is the reference [I].

**Sustained performance on phones:**
- Snapdragon 8 Elite, 15-minute CPU throttling test: 73% of peak (Beebom) [V].
- 8 Elite Gen 5 reference device: fell to 58% of peak in a graphics stress test (Android Authority, 2025-09-24) [V].
- realme GT8 Pro: dropped below 30% (AndroidHeadlines, 2025-11-06) [V].
- I use 0.80 for the single thread and 0.65 for all cores once warm [I].

**Model** [I]. On the Z1E the Dangral frame (about 37 ms) behaves almost serially because of the copy-hazard ordering above. I split it into about 18 ms of producer work (game thread, parse, vertex setup and decode) and about 19 ms of raster wall time:
- frame time on a phone ≈ 18/ST + 19/MT;
- for the battle, 11/ST + 10/MT, which reproduces H3's 47.8 fps render ceiling on the Z1E;
- ST and MT are the single- and multi-core ratios from the table, times the sustained factor when warm;
- frame rates are capped at the game's 30.

| Chip | Software renderer, Dangral base: fresh / warm fps | Software renderer, battle: fresh / warm | GPU backend: heaviest game-thread frame (18.2 ms on Z1E), fresh / warm |
|---|---|---|---|
| 8 Elite Gen 5 | 30 / **21** | 30 / 30 | 13.2 / 16.4 ms |
| 8 Elite | 24.5 / **17** | 30 / 30 | 16.6 / 20.8 ms |
| 8 Gen 3 | 18 / 13 | 30 / 23 | 22.1 / 27.6 ms |
| 7+ Gen 3 | 14 / 10 | 25.5 / 18 | 25.8 / **32.2 ms** (budget 33.3) |
| 7 Gen 4 | 11.5 / 8 | 20 / 14.5 | 35.4 / **44.3 ms** |
| 7 Gen 3 | 9 / 6.4 | 16 / 11.5 | 41.2 / 51.5 ms |

**Why the software-renderer column is optimistic** [I unless marked]:
- **Row ownership assumes equal cores.** Worker *i* owns rows `y % nthreads == i-1` (ARCHITECTURE.md "Workers rasterize it") [V], so a frame waits for its slowest worker.
  - Phones mix core sizes. Going by vendor specifications as I remember them: 8 Gen 3 is 1+5+2, 7+ Gen 3 is 1+4+3, 7 Gen 3 is 1+3+4, and the smallest cores are Cortex-A520/A510 at roughly a third of the speed.
  - The 3/4-of-CPUs default (gxr.c:1958) would put workers on those small cores.
  - Only the 8 Elite family, which is all Oryon cores, avoids this.
- **A non-Windows build has no workers at all today.** `workers_start` compiles `#else n = 0` (gxr.c:1968-1970) [V], so it rasterizes on the game thread alone. H1 notes the single-thread case at about 3 fps before H15.
- **The game thread's idle loop still spins.** This is H11's unfinished half (FINDINGS.md:1911) [V]. On a phone it costs a core and battery.

## 3. Verdict on the software renderer

Not viable as the Android renderer:
- On the best 2025 phone it matches the Z1E only until the phone heats up.
- Warm, a heavy field scene plays at about 55–70% of real speed on flagships and about 20–45% on 7-series chips.
- H15d (SIMD spans) behind a NEON path might be worth 1.5–2× [I], which is still not enough warm, on mid-range phones, or with any 60 fps interpolation.

It stays valuable as the reference to compare a GPU backend against, and as a fallback. PLAN.md:954-956 already warns that a GPU backend "would replace the one piece of this port that is a trustworthy reference", so keep both.

## 4. What a GPU backend takes in *this* architecture

**Where to cut** [I, built on V]:
- The producer already turns the raw command stream into self-contained `DrawCmd`s (ARCHITECTURE.md §6) [V]. Each one holds:
  - clip-space vertices, already transformed and lit on the CPU (`transform`, `light_channel`, §5);
  - a `TevSetup` snapshot, plus pixel and raster state snapshots;
  - decoded textures from the 1,024-entry cache.
- A GPU backend can be a *second consumer of that queue* in place of the worker pool. That keeps all of this unchanged:
  - the parse (gx.c) and the capture/replay harness;
  - H12's epoch hashing and palette re-hash;
  - H10's clip-space in-between image. Interpolated 60 fps then costs the GPU almost nothing.
  - mods' injected draws (beyond-gamecube.md §7).

**Component by component:**
- **Vertex decode and transform.** Keep them on the CPU.
  - Median 11.9k vertices and 1,900 draws a frame (230–3,090) [V, performance.md §2].
  - Vertex setup costs 2–4 ms on the Z1E. H16 moves it off the game thread, and on a 7-series phone that matters (4–8 ms) [I].
  - Draw submission needs batching. About 3,000 draws a frame through a mobile driver is a real CPU cost on its own thread [I].
- **The TEV combiner as generated shaders.**
  - The H6 set has only **33 distinct TEV setups**. One-stage setups cover about 80% of the screen area, and the source-alpha blend with no fog 57% (FINDINGS.md:2501-2505) [V].
  - Suggested design [I]:
    - one SPIR-V "ubershader" built offline;
    - Vulkan specialization constants per setup, so there is no runtime shader compiler (SPEC's no-runtime-dependency rule, SPEC.md:463);
    - integer-exact TEV arithmetic (bias, scale, clamp, swap tables, konst) and alpha compare with `discard`.
  - About a week-plus.
- **The pixel engine.**
  - **Logic ops are a real requirement.** A scan of all 35 captures for BP 0x41 writes with logic enabled found OR, AND, NOR, EQUIV, CLEAR and COPY in **16 of 35**. The scan is a byte pattern, but the decoded stream confirms it: in capture 6000, `PE_CMODE0 = 00713E` (logic OR) and `00113E` (logic AND) sit around the copies in the full-screen passes [V].
  - Logic ops are an optional Vulkan feature, and GLES and WebGPU have none, so some GPUs need emulation (framebuffer fetch or ping-pong) [I].
  - Also needed: 24-bit depth and early depth (`ztop`), fog by the port's own formula, RGBA6 and dither, colour and alpha update masks.
  - Several days to a week-plus.
- **Texture decode and cache.** Upload the CPU-decoded RGBA8 cache entries. The port already hashes every byte once an epoch, which is stricter than Dolphin's per-game "Medium" (512-sample) setting. Several days.
- **Copies of the rendered image.** This is the hard part.
  - FINDINGS.md:460 [V]: "The game copies the whole EFB to four 640x480 one-byte buffers (copy format R8) every frame."
  - In capture 6000 [V]:
    - two R8 copies (`PE_COPY_EXECUTE = 01000B`, 640×480) land at 0x0035D4E0 and 0x003A84E0;
    - both lie **inside the display buffer at 0x8035D4E0**;
    - they are sampled as I8 textures (`TX_IMAGE0 = 177E7F`, `TX_IMAGE3 = 01D427 / 01AEA7`) by full-screen quads;
    - the frame's display copy (`004803`) is then written to the same address, 0x35D4E0.
  - A GPU backend must therefore:
    - keep copies on the GPU, keyed by guest address and format;
    - retire them when a later copy overlaps them;
    - apply C3's three-row 16/32/16 filter and half-scale;
    - write bytes back into guest RAM wherever something reads them as memory.
  - Dolphin's settings for this game (`GEA.ini`: `EFBToTextureEnable = False`, `SafeTextureCacheColorSamples = 512`, `CPUThread = False`) say that GPU-only copies break it [V].
  - The port already knows every *renderer-side* read of a copy's destination (`gxr_texture_hazard`, `gxr_source_hazard`, `gxr_hook_hazard`, ARCHITECTURE.md §9) [V].
  - What does not exist is tracking of the game's own CPU reads. H14 notes "a CPU *read* of a copy after its token cannot be watched" (FINDINGS.md:2346-2348) [V]. That tracking is page protection or proof it is not needed.
  - On a phone's tile-based GPU a readback stalls the pipeline, so readbacks must be deferred and batched (Dolphin's "Defer EFB Copies to RAM") [I].
  - Two or more week-plus slices, and the highest risk.
- **Depth.** GX depth is 24-bit integer. Depth copies and Z textures are unused ("all absent, all unused across 38,084 captured tri-strips", PLAN.md:993-996) [V], which keeps this simple.
- **Verification.** GPU rasterization rules differ, so the 23 pinned hashes cannot match exactly. The check has to be each capture replayed through both backends, compared with a tolerance [I]. Several days, then ongoing.

**Overall size** [I]: roughly 8–12 slices of "week-plus" size (sizes as PLAN.md uses them), about 2–4 months of evenings. Vulkan runs on both Windows and Android, so one backend serves both.

**Risks** [I]:
- The RAM path for copies.
- Logic-op emulation.
- Mobile driver bugs: Dolphin keeps a list in `VideoCommon/DriverDetails.cpp`.
- Shader-compile stutter.
- Losing bit-exact regression checks.

**Dolphin's VideoCommon, for comparison** (reference only: its README says GPLv2+, and this repo's LICENSE is MIT) [V]:
- The command stream is decoded in `OpcodeDecoding.cpp` and `BPStructs.cpp` (54 KB).
- Vertex loaders are JIT-compiled (`VertexLoaderARM64.cpp`), and transform and lighting run on the GPU (`VertexShaderGen.cpp`).
- The TEV becomes per-setup shaders (`PixelShaderGen.cpp`, 83 KB), with an `UberShaderPixel.cpp` (58 KB) to hide compile stutter.
- Copies go through `TextureCacheBase.cpp` (128 KB), `FramebufferManager.cpp` and `TextureConversionShader.cpp` (GPU encoding into GX formats for RAM).

It is general-purpose for every game. This port needs only what this game uses.

**Aurora** (encounter/aurora: MIT, pushed 2026-09-25, 530 stars) [V]:
- **Better fit than its description suggests.** `lib/gx/command_processor.cpp` decodes raw BP, CP and XF writes and draws 0x80–0xBF, and `lib/gx/regs.cpp` has `bp_gen_mode` and the rest.
- **Addresses are the obstacle.** Arrays, textures, palettes and copies travel as `GX_AURORA` sub-commands carrying host pointers plus an explicit version (`LOAD_ARRAYBASE`, `LOAD_TEXOBJ`, `LOAD_COPY_DST`). The port would synthesize those from guest addresses and its epochs.
- **Blocking gaps for this game** [V]:
  - `to_blend_state` handles only CLEAR, COPY and NOOP logic ops, and any other hits `DEFAULT_FATAL("unsupported logic op")` (`lib/gx/gx.cpp:137-160`). WebGPU has no logic ops at all. This game uses OR, AND, NOR and EQUIV.
  - Copies stay on the GPU in `copyTextureCache`, keyed by host pointer, and `GXCopyDisp` is a no-op (`lib/dolphin/gx/GXFrameBuffer.cpp:36-65`, `:206`). There is no RAM path, which Dolphin says this game needs.
- **It brings Dawn, SDL3, C++20 and CMake**, against SPEC.md:463 ("no third-party runtime dependency") and the MSVC-direct build.
- **What it offers:** a mature shader generator (`lib/gx/shader.cpp`, 79 KB), a pipeline cache, Dolphin-compatible texture packs, resolution scaling, and Android through SDL3. Dusklight, which uses it, describes itself as "PC and mobile".
- **A precedent:** WiiCompiled (GPL-3.0) is a static recompilation, like this port, that bridges to Aurora. Its bridge is 23 files and 315 KB of C++ (`runtime/src/hle/gx/`), and it keeps copies "GPU-only until an explicit/lazy readback" (`gx_copy.cpp:14`).
- **Verdict** [I]: Aurora is feasible only if logic-op emulation and a RAM path for copies are added upstream or in a fork. That is the same hard work as the own-backend route, plus a large dependency.

## 5. Dolphin on Android today, and what a native port adds

**Dolphin** [V]:
- `GEA.ini` forces single-core mode (`CPUThread = False`). The change replaced `SyncGPU = True` in commit 869edd5 (2021), "particularly on Android, where SyncGPU had poor performance and stability".
- It also sets EFB copies to RAM and Medium texture-cache accuracy.

**Reports of play** (thin evidence):
- A 2017 Snapdragon 835 phone: "pretty constant 30 fps", with red and black texture glitches (Dolphin forums).
- A 2026 handheld guide rates it "Tier A-B": full speed on a Snapdragon 865 Retroid Pocket 5, up to Snapdragon 8 Gen 2-class devices (heldgames.com, 2026-04-13).
- The Dolphin wiki lists "no reported problems" and one Android test entry.

In short, flagship Android users can already play it [I].

**What a native port adds:**
1. **True 60 fps by interpolation**, with the game logic still at 30 (H10 done offline, H17 planned). Dolphin cannot do this, because the 30 fps cap is game logic (H2) [V].
2. **Native mods**, with `mod.dll` becoming a `.so` (M3a), and the gameplay-mods plan.
3. **The copy behaviour designed in**, rather than per-game settings that cost performance [I].
4. **Lower CPU and battery use** once there is a GPU backend, the guest idle fix (H11b) and H13, since a phone's CPU would run one game thread and a submit thread [I]. Before those, the port would be *worse* than Dolphin on a phone.

**The cost is setup friction:**
- A user must build the translated game code as a library on a PC from their own disc, because `gen/` is never shipped (SPEC §2) [V].
- Android 14 and later require any dynamically loaded library to be read-only before it is loaded (search result summarising Android's dynamic-code-loading rule) [V-web].

## 6. Other Android prerequisites, briefly, and the ISO

**Windows-only pieces to replace** (other reports cover these in depth) [V]:
- guest threads on fibers (threads.c:110, :289, :301). Android's C library lacks `makecontext`/`swapcontext`, so this needs a small assembly context switch [V-web];
- `VirtualAlloc` for the memory guard (main.c:595, :633);
- `WaitOnAddress`/`WakeByAddressAll` (gxr.c:20, :1579), becoming futexes;
- `waveOut` (audio_out.c:39), becoming AAudio;
- DXGI and Win32 (window.c).

**Easy and hard points** [V]:
- cpu.h:47-54 already has a non-MSVC byte-swap path.
- Any non-MSVC build must turn off fused multiply-adds (plan-gaps.md:587). Clang contracts `a*b+c` by default, and `/fp:strict` is what MSVC is given today (toolchain.py:100).
- H15d's SIMD must sit behind an x64 guard with a scalar path (PLAN-GAMEPLAY-MODS.md:1402).

**The ISO** [V]:
- The disc is needed once at build time, because the DOL is translated into `gen/`.
- Today it is also needed at run time, since `dvd.c` serves reads from `extracted/disc.iso` (ARCHITECTURE "dvd.c").
- Serving the game's files from an extracted folder or pack instead is renderer-independent and relink-only (beyond-gamecube.md §4, the virtual disc).
- Nothing in this report changes that. Running with no copy of the game at all is excluded by SPEC §2.

Sources: [Geekbench browser](https://browser.geekbench.com/processors/amd-ryzen-z1-extreme), [Geekbench Android chart](https://browser.geekbench.com/android-benchmarks), [Android Authority 8 Elite Gen 5](https://www.androidauthority.com/snapdragon-8-elite-gen-5-benchmarks-3600242/), [AndroidHeadlines throttling](https://www.androidheadlines.com/2025/11/qualcomm-snapdragon-8-elite-gen-5-thermal-throttling-heat-hot-tests.html), [AndroidHeadlines 8 Elite Gen 6](https://www.androidheadlines.com/2026/09/we-benchmarked-the-snapdragon-8-elite-gen-6-and-the-year-over-year-gains-are-real.html), [Beebom 8 Elite](https://gadgets.beebom.com/guides/snapdragon-8-elite-benchmark-specs), [Dolphin GEA.ini](https://github.com/dolphin-emu/dolphin/blob/master/Data/Sys/GameSettings/GEA.ini), [Dolphin commit 869edd5](https://github.com/dolphin-emu/dolphin/commit/869edd5), [Dolphin wiki](https://wiki.dolphin-emu.org/index.php?title=Skies_of_Arcadia_Legends), [Dolphin forum thread](https://forums.dolphin-emu.org/Thread-skies-of-arcadia-legends-via-dolphin-emulator-android), [heldgames](https://heldgames.com/guides/best-gamecube-games-handheld), [Aurora](https://github.com/encounter/aurora), [WiiCompiled](https://github.com/patchzyy/Wiicompiled), [Dusklight](https://github.com/TwilitRealm/dusklight), [Intune SDK issue on Android dynamic code loading](https://github.com/microsoftconnect/ms-intune-app-sdk-android/issues/343), [NDK ucontext thread](https://groups.google.com/g/android-ndk/c/rbrQGZxuUSM).
