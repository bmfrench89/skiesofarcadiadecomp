<!-- Written 2026-09-25 by the planning session; revised the same day after two reviews, then checked
again at main 012164a in a consistency review across the five planning documents (section 10, "Review
log"). File:line citations for runtime/ are at main c8274db (L0/N4's acquire loads). 012164a differs from
c8274db in runtime/gx.c (C5a's log, 750cef0: 115 lines at :53 and a few below, so gx.c citations past :55
move by 115 to 125), mod.c, mod.h, hle.c, main.c, selftest.c, settings.c, si.c, a new seed.c,
tools/guard.py and tests. Every gxr.c, gxr.h, gxr_tev.c and window.c line cited here holds at 012164a,
and so does selftest.c:123; main.c's lines past :43 have moved by 4 or more (P6, P6b); tools/guard.py is
cited at b071949 (T0c, 012164a, rewrote much of it). At 012164a the working tree held the implementation
session's uncommitted P1a. The order across all plans is ../PLAN-NEXT.md. Nothing was run except
read-only analysis: tools/fifo.py over the 35 capture files (33 distinct frames) into a scratch
directory, tools/disasm.py and scratch cross-reference scripts over the local DOL, reads of the capture
RAM images, vulkaninfo on the owner's machine, one dxc probe in scratch, and web reads (gpuinfo.org,
Dolphin, Khronos, SDL, Microsoft Learn). No soa.exe, scenario, soak or pytest run. [V] = read in code, a
capture, a tool run or a dated page, with where; [I] = inferred. Record what a slice's run shows in
docs/FINDINGS.md and mark the slice done here the way docs/PLAN.md does. -->

# GPU renderer: a design study, a contained spike, and a decision gate

**For the owner.** Today the port draws every pixel on the CPU (`runtime/gxr.c`). That renderer is
the port's trustworthy reference: 23 captured frames are pinned by hash and replayed on every
renderer change. A GPU renderer is what Android needs, what makes 2× and 3× resolution and real
widescreen possible, and the surest way to 60 images a second in the heavy sky and ship scenes. It is
also 2–3 months of evenings, and it can never match those 23 hashes, so it has to be judged a
different way.

This spec does three things:

1. **Designs the GPU renderer** far enough that its size and risks are known: where it plugs in, how
   the game's graphics features map to a GPU, and the two hard parts (logic ops and copies of the
   picture into game memory).
2. **Defines a spike** of about **three to four weeks of evenings** (V0–V4) that renders the captured
   frames through Vulkan (or Direct3D 11, if you answer Q-V1 "no" first), offline, and measures how
   close they come to the CPU renderer's, with a checker that is built and proven able to fail
   *before* any GPU picture exists.
3. **Ends in a decision for you** (section 8), with the numbers the spike will add.

**What you are asked for:** answers to Q-V1 to Q-V6 (section 7), most importantly whether Android is a
firm goal, because that picks between Vulkan and Direct3D 11, and it should be answered before V3
starts. After the spike, one decision (the gate), and a look at four side-by-side pictures.

**Said plainly, before anything else:**
- **I found that an observation already in FINDINGS (H4) is a defect** (section 2.8). H4 recorded
  that every display-list call in the captures has size 0 and read it as "all draws are direct". The
  chain through the game's `GXBeginDisplayList`/`GXEndDisplayList` says otherwise: the display lists
  the game records while it runs come out empty in the port, and their draws run early, while the
  lists are being recorded. In all 12 distinct frames that use the game's mask effect, the effect's
  caster pass contributes nothing [V]. Dolphin's testers describe that effect's artifacts as
  character shadows, so **character shadows (or something like them) are probably missing in the
  port today, in both renderers** [I]. **8 of the 23 pinned frames have pinned that state since the
  manifest was first blessed.** It needed a run to confirm and is not this spec's to fix; it is
  proposed as PLAN C5 (three small slices). C5a, the confirming run, was the first slice of
  [../PLAN-NEXT.md](../PLAN-NEXT.md)'s M1 and landed as 750cef0: the chain is confirmed (section 6,
  C5a; FINDINGS "Recorded display lists (C5a)"). That the casters are character shadows is still [I].
- **The GPU picture will be judged by a tolerance, not a hash.** The CPU renderer stays, forever, as
  the reference and the fallback. Every future renderer fix is then done twice, or the GPU follows.
- **The 35 captures do not cover what Dolphin found hard in this game** (the start and party menus'
  copy of the screen). V1 captures it before the spike claims anything.
- **Your handheld's GPU supports everything this needs except 24-bit depth**, which costs a small,
  known workaround [V, vulkaninfo, 2026-09-25]. The design needs **no optional Vulkan feature at
  all**, because about 39% of Android devices lack clip distances and 48% lack logic ops (2.5).

Sizes are evenings, as in PLAN.md: **hours**, **a day**, **several days**, **week-plus**, **months**.
Rebuild cost is **none**, **`--link`**, or **one retranslation**; no slice here needs a
retranslation. **Owner** marks where you look or play.

---

## 1. Purpose and scope

**What each outcome gives you.**

| If, after the gate, you choose | You get | It costs |
|---|---|---|
| **A. Vulkan backend** | Android becomes possible (with track L), on devices without clip distances or logic ops too (3.3, V10); 2×/3× resolution; widescreen without squeezing; the ship and sky scenes' 60 fps headroom; probably lower power on the handheld [I, measured only after H20] | V5–V12, about 2–3 months of evenings; a second renderer to keep in step |
| **B. Direct3D 11 backend** | The same on Windows and on the Steam Deck through Proton, no Android | About the same, less the shader-compiler fetch |
| **C. Not now** | The CPU renderer continues: H15d/H16 resume at single-digit gains a step | Nothing new; Android stays out of reach |
| **D. Not ever** | C, and PLAN says so, so nobody reopens it without new facts | The spike's C code is parked; the oracle and the seam stay |

**In scope.** The design (section 3); the pre-gate slices V0–V4; the gate; the post-gate slices
V5–V12 with honest sizes; how the backend meets H17 (interpolation), M9 (textures), M10/M14
(widescreen), X6 (injected draws) and the mod API.

**Out of scope.** The Android shell and the Linux build (portability L10–L12); H17 itself (it works on
draw commands whatever draws them, and is not blocked by this decision); the display-list defect's
fix (proposed PLAN C5a–C5c, section 6); the CPU pixel path's speed work (H15d's rest and H16, deferred
to this decision; H18 follows H17b and is not held by it, ../PLAN-NEXT.md A4).

**The contract, for every slice.** With the GPU off (the default), the 23 replay hashes
(`python tools/scenario.py replay --threads 1,2,3,8`), the self test
(`$env:SOA_SELFTEST='1'; gen\soa.exe extracted`), `python tools/scenario.py run title --check`,
`python tools/decomp.py`, and `python -m pytest tools/tests/test_memguard.py tools/tests/test_mods.py`
are unchanged. No GPU frame hash is ever pinned. (C5c is the one proposed slice that changes the
corpus itself, and it says so.)

---

## 2. Current state

### 2.1 The pipeline as a GPU would see it

- **The front end** (`runtime/gx.c`) parses every gather-pipe store as it happens
  (`gx_pipe_write`, gx.c:428-439), shadows CP/XF/BP registers and calls the renderer for draws and BP
  writes [V].
- **The producer** (the guest thread) turns each draw into a self-contained `DrawCmd` in
  `gxr_draw_inner` (gxr.c:2361) [V]:
  - vertices decoded and transformed on the CPU into clip space, with lit colours and generated texture
    coordinates (`transform`, gxr.c:699; `Vertex`, gxr.h:17-23). The screen position is unset; the
    worker's `to_screen` computes it;
  - `TevSetup` (gxr.h:116-130): up to 16 stages with resolved selectors, konst, swap tables, alpha
    compare, `reg_init`, and eight `TexCfg` (gxr.h:104-114: level pointers and sizes, wrap, filter,
    lod bias and range, scale, `su0`/`sv0`) that point at **CPU-decoded RGBA8 levels** in the texture
    cache (`texture`, gxr_tev.c:777; 1,024 slots, gxr_tev.c:124, evicted within a frame when the
    working set does not fit, gxr_tev.c:742-747);
  - `PixelCfg` (gxr.c:795-811: blend, logic op, masks, depth, fog) and `RasterCfg` (gxr.c:822-826:
    scissor, cull, viewport), snapshotted by `pixel_prepare` / `raster_prepare` (gxr.c:877-918).
  - `DrawCmd` itself is private to gxr.c (gxr.c:828-861), with `kind` 0 draw, 1 copy, 2 clear.
- **The consumers** are the worker pool (`worker`, gxr.c:1749), each owning every Nth row of the single
  EFB, `g_efb[528][640][4]` and `g_efb_z` (gxr.h:151-152) [V].
- **The no-worker path is dead code on Windows** [V]. The producer runs a command on the spot when
  `g_workers == 0` (gxr.c:2428-2438, 2911-2918, 3027-3034), but `workers_start` turns `SOA_THREADS`
  unset or ≤ 0 into three quarters of the logical CPUs (gxr.c:2008, 2016-2025); only the non-Windows
  branch starts none (gxr.c:2035), and `g_workers` is otherwise 0 only if `CreateThread` fails. The
  self test forces `SOA_THREADS=1` (selftest.c:123) and the replay sweep uses 1, 2, 3 and 8. So no
  test, replay or self test has run that path's bookkeeping on Windows (the `g_published` increments,
  the arena reset, the gate drains, `gxr_presented`'s divisor, the hazard waits).
- **Copies** (`enqueue_copy`, gxr.c:2921): a copy to texture writes tiled bytes into guest RAM
  (`copy_to_texture`, gxr.c:2467) and decodes a *copy image* for same-frame samplers
  (`tex_copy_image`, gxr_tev.c:869); a copy to the screen fills `g_screen` only
  (`copy_to_screen`, gxr.c:2612). **The display copy never reaches guest RAM in the port** [V]. The
  vertical deflicker filter is integer, 16/32/16, truncating, clamped to the copy rectangle
  (`filter_sample`, gxr.c:2599; `copy_filter`, gxr.c:2877). A half-scale copy takes a 2×2 box and
  **no** vertical filter, and warns if one is programmed (gxr.c:2522, 2536-2540). An R4 copy writes
  one nibble of a byte by read-modify-write (gxr.c:2566); only texels inside the copy are written
  (loops to `ow`, `oh`). Intensity with a format above 3 is refused, RAM untouched (gxr.c:2490,
  `copy_texfmt` gxr.c:2688-2692).
- **Where a copy's clear runs** [V]. The clear a copy asks for (bit 0x800) runs **inside** the copy
  (`run_copy`, gxr.c:2662) unless the copy is *foreign* — half-scale, filtered, or with rows a worker
  does not own (`copy_is_foreign`, gxr.c:2640) — when it is published as its own kind-2 command
  (`publish_clear`, gxr.c:2903, called at gxr.c:3062). With one thread, an unfiltered full-scale copy
  keeps the fused clear.
- **Synchronisation with the guest**: a producer read of guest memory that a queued copy writes waits
  for that copy (`gxr_ram_hazard`, gxr.c:2740); one drain a frame at the next frame's first command
  (the gate); `GXDrawDone` drains; draw tokens are answered at once (gxr.c:3093-3141) [V].
- **Frames presented**: `g_frames_presented` is static in gxr.c (gxr.c:2581), incremented by
  `run_copy` for a screen copy (gxr.c:2664), and `gxr_presented` divides it by `g_workers`
  (gxr.c:2778-2782) [V].
- **The renderer links alone** (gx.c, gxr.c, gxr_tev.c, png.c and two stubs;
  `tools/citest/render_check.py:32-33`), and `tools/tests/test_gxr_pair.py:268-276` already replays
  captures in such a binary [V]. A spike needs no `gen/`.
- **Output**: `SOA_HASH` is FNV-1a over `g_screen` (`gxr_screen_hash`, gxr.c:2802);
  `config/fifo_manifest.tsv` pins it for the 23 corpus captures; `--replay` writes `<base>.png` beside
  the capture (main.c:1196-1203) [V].
- **A replay starts from end-of-frame RAM** [V]: `load_capture` reads `<base>.ram`, which is all of
  MEM1 as the frame ended (gx.c:56-59), before parsing the stream (gx.c:537-575, `gx_replay`
  gx.c:588); the capturing run flushes first "so its hook and its .ram see every copy it made"
  (gx.c:151-154). **So every copy destination in a capture's RAM already holds what the live run's
  copy wrote**, and a replayed copy that writes nothing, or writes the wrong place, can go unnoticed
  (3.12's poison step is the answer). A pair replay's pass 2 loads B's own RAM (gx.c:656-657).
- **Presentation** is `window.c`'s D3D11/DXGI flip-model swap chain (window.c:24, 161-179), fed by
  converting `g_screen` to BGRA [V].

### 2.2 What this game asks of a GPU: a census of the 35 captures

`tools/fifo.py` over the 23 corpus captures (`build/fifo`) and the 12 benchmark captures
(`build/perfset`), 2026-09-25, into scratch [V]. **35 capture files, 33 distinct frames**:
`build/perfset/corpus/6000` and `corpus/15800` are byte-identical copies of the corpus's (`cmp` on
`.fifo`, `.regs` and `.ram`; FINDINGS H6 says so). Counts below are over the 35 files unless marked.
**They are counts before C5c.** C5c re-captures the corpus, after which `corpus/6000` and `corpus/15800`
are no longer copies of any corpus frame; this section's "33 distinct" and the distinct-frame counts in
V0, V4a, V4b and V10 are re-counted then, by the slice that uses them.
Because every display-list call in them is empty (section 2.8), the top-level stream is every draw
the port renders.

| Feature | What the captures use |
|---|---|
| Draws | 67,160 over the 35 files (61,749 over the 33 distinct frames): 66,428 triangle strips, 678 quads, 54 triangle lists; no fans, lines or points. 4 to 4,440 a frame |
| EFB format | `PE_CONTROL` 000000 or 000040: RGB8/Z24 always; the second sets `ztop` |
| Depth | `LEQUAL` (with and without update) and `ALWAYS`; no `EQUAL` |
| Blend (`PE_CMODE0`) | 15 distinct values. 0054BD (source-alpha blend) in 20,957 writes; additive, reverse, subtract (00093D), multiply (00521D) and dst×(1−src) (00007D) in the rest; none uses a destination-alpha factor |
| Logic ops | **Only in 14 captures (12 distinct frames), only OR and AND, always OR, AND, OR a frame** (`PE_CMODE0` 00713E, 00113E, 00713E) |
| Constant alpha (`PE_CMODE1`) | Never written; zero in the register files |
| Alpha compare | Always-pass (3F0000), alpha > 0 (3C0000), alpha ≥ 128 (368080) |
| Fog | Off, exp (type 4), exp2 (type 5); no linear |
| TEV | At most 5 stages in any GEN_MODE write; 33 distinct combiner setups in the benchmark set by H15c's census (FINDINGS "H15c, first two stages"), counted by shape, not by every register value |
| Copies to texture | **Only in the same 14 captures (12 distinct): exactly two a frame, both R8, 640×480, into the two halves of the current XFB** (0x35D4E0 and 0x3A84E0, or the other buffer 0x4024E0 and 0x44D4E0), the first sampled back as I8 later in the same frame; none carries the clear bit |
| Screen copies | One a frame, filtered (0x53/0x54 = 30A208/00820A: the 8,8,10,12,10,8,8 taps), with the clear bit (e.g. 004803 in capture 6000) |
| Indirect, Z textures, zfreeze, TMEM preload | Unused (the tripwires, gxr.c:298-375, and PLAN.md's "unimplemented GX features") |

Two things follow. **The hard features are narrow**: all logic ops and all texture copies in the
corpus belong to one effect (2.3, 2.8). **The easy features are few**: one EFB format, two depth
functions, a handful of blend modes.

### 2.3 Every copy site in the executable, and what reads the destinations

A scan of every `bl` in the DOL's text sections, over the local DOL [V]:

- **`GXCopyDisp` (`fn_8024F194`)** is called at 0x801DC484 (the frame end in `fn_801DC420`) and
  0x801DC980 (`fn_801DC62C`, setup).
- **`fn_8024F2F0`, `GXCopyTex`** [I by position after `GXCopyDisp` and by its BP writes], is called at
  six sites in four functions:
  - **0x802AB530/0x802AB540 (`fn_802AB460`) and 0x802AB6EC/0x802AB8D4 (`fn_802AB608`): the mask
    effect.** `fn_801D1714`, called from the draw pass `fn_801D0F80`, passes the current XFB
    (the pointer at 0x803476AC) and XFB + 0x4B000 to `fn_802AC160`, which stores them at 0x80347FE8
    and 0x80347FE4 and initialises two texture objects on them (0x803466D8, 0x803466F8, through
    `fn_8024FDD0`, `GXInitTexObj` [I by its arguments]). The copy format argument is 40, `GX_CTF_R8`.
    **Every reference to 0x80347FE4 and 0x80347FE8 (the two copy pointers) is a `GXCopyTex` argument
    (0x802AB528, 0x802AB538, 0x802AB6E4, 0x802AB8CC), the second `GXInitTexObj` (0x802AC244), or the
    store in `fn_802AC160` (0x802AC1A0, 0x802AC1AC); 0x80347FE0 holds the format flag** [V, r13 =
    0x8034E720, an r13-relative scan]. (0x80347FEC is a different variable, walked by
    `fn_802AC31C`.) **No code takes these pointers to read the copies.** A read of the same XFB bytes
    through another pointer is not ruled out by this scan.
  - **0x80226DA4 (`fn_80226D14`): a copy of the screen into a texture object's image** (the pointer
    at +32 of an object reached through 0x80347568). It runs `DCInvalidateRange` over 1 MB, then the
    copy with clear, then `fn_8024E0A0` (`GXPixModeSync` [I]) and `fn_80250850` (`GXInvalidateTexAll`
    [V: two BP 0x66 writes]); no `GXDrawDone`. **Nine call sites in eight functions**:
    `fn_8002FF70`, `fn_800AF780`, `fn_800AF8F8`, `fn_800B0FD0`, `fn_800D81E8`, `fn_80101828` (twice),
    `fn_8011B820`, `fn_8011CE6C`.
  - **0x800AFB9C (`fn_800AF8F8`): a scene rendered into another texture object** (reached through
    0x80303698), followed by `fn_80226D14`.
- **Neither of the last two appears in any of the 35 captures** [V]: every texture copy there is the
  mask effect's R8 pair, and none carries the clear bit (0x800) that `fn_80226D14` asks for. Which
  situations call them is not known; that the menus do is [I] (below).
- **What reads copy destinations at run time [V]:** all 67 saved logs with a `[gxr] waits:` line
  (`grep -rl "\[gxr\] waits:" build --include=*.log`, 2026-09-25) record exactly one `GXDrawDone` a
  run, so the game does not use `GXDrawDone` per frame. A token-synchronised CPU read cannot be
  excluded: tokens arrive twice a frame, 6,602 of them with a copy still running, and "a CPU read of a
  copy after its token cannot be watched" (FINDINGS "H14"); the H14 store watch over both XFB pairs
  saw no CPU store, but it covers stores only.
- **Dolphin** sets three things for this game (`GEA.ini`, checked 2026-09-25) [V]:
  `[Core] CPUThread = False` (single-core: the CPU and GPU are not run in parallel),
  `[Video_Settings] SafeTextureCacheColorSamples = 512`, and `[Video_Hacks] EFBToTextureEnable =
  False` (EFB copies go to RAM). Its forum says "the start and party menus still need EFB Copies set
  to RAM" (Shonumi, 2012-12-29) [V-web]; the wiki's testing notes say "Enable EFB Copy to RAM"
  [V-web], while its problems section reports none. That the menus are `fn_80226D14`'s copy, sampled
  over later frames, is [I]; the port's texture cache already does that right on the CPU, by hashing
  the bytes the copy wrote (gxr_tev.c:777). That the first setting means the game is sensitive to
  CPU/GPU timing is [I]; it bears on V6/V7's asynchronous consumer (section 5).

**Consequence for the design:** the GPU backend must write every copy to texture into guest RAM, as
the CPU renderer does, until a census shows a destination is never read by the CPU (V11). It must
not write the display copy to RAM, because the CPU renderer does not.

### 2.4 The owner's GPU

`vulkaninfo` on this machine, 2026-09-25 [V]: "AMD Radeon Graphics", device 0x15BF, integrated —
**the Ryzen Z1 Extreme's integrated Radeon (Phoenix, RDNA 3; the same GPU as the Radeon 780M)**,
called "the Z1E's GPU" below — AMD proprietary driver 26.10.07.06 (LLPC), Vulkan 1.4.344.
`logicOp`, `depthClamp`, `shaderClipDistance`, `dualSrcBlend`, `independentBlend`,
`fragmentStoresAndAtomics`, `shaderInt16` and `textureCompressionBC` are all true.
`VK_EXT_fragment_shader_interlock` (`fragmentShaderPixelInterlock` true) and
`VK_KHR_dynamic_rendering_local_read` are present; **no rasterization-order attachment access
extension is listed**. **`D24_UNORM_S8_UINT` and `X8_D24_UNORM_PACK32` are unsupported**;
`D32_SFLOAT` is supported. `vulkan-1.dll` is installed with the driver; no Vulkan SDK is installed.

### 2.5 Optional Vulkan features on Android

**Core-feature coverage on Android**, gpuinfo.org's own figures
(`listfeaturescore10.php?platform=android`, fetched 2026-09-25) [V-web]:

| Feature | Android devices reporting it |
|---|---|
| `fragmentStoresAndAtomics` | 100% |
| `depthClamp` | 91.2% |
| `dualSrcBlend` | 65.48% |
| `shaderClipDistance` | **60.78%** |
| `logicOp` | **52.46%** |

**`shaderClipDistance` is a bigger gap than `logicOp`'s fallbacks cover.** SDL issue #12652
(2025-03-26) reports that SDL_GPU making it mandatory kept an application off a Pixel 9 Pro (Mali);
SDL later made it optional [V-web]. This design therefore needs neither clip distances nor depth
clamping (3.3).

**Logic ops by GPU family.** gpuinfo.org's device list, from the page's own data source
(`api/internal/devices.php?platform=android&minversion=true` with `filter.feature=logicOp`, the AJAX
source of `listdevicescoverage.php?feature=logicOp&platform=android`), fetched 2026-09-25, **one row
per device name** as that list gives it: 1,303 devices report `logicOp`, 2,402 do not (35%). The
site's own 52.46% above is computed over a different base, which the site does not state [I]; the
table is a family breakdown, not a market share. Families by GPU name and driver [V, scratch recount]:

| GPU family | reports `logicOp` | does not |
|---|---|---|
| Adreno 7xx (Snapdragon 8 Gen 1–3, 7 Gen x) | 385 | 4 |
| Adreno 8xx (8 Elite family) | 152 | 1 |
| Adreno 6xx | 21 | 834 |
| Adreno 4xx–5xx | 0 | 303 |
| Adreno under Mesa Turnip | 84 | 0 |
| Mali and Immortalis, ARM's driver | 212 (205 of them at driver r46 or later) | 1,179 |
| Huawei Maleoon | 0 | 53 |
| Samsung Xclipse | 38 | 0 |
| PowerVR / IMG | 324 | 0 |
| Everything else (desktop GPUs in Android containers, emulators, software rasterisers, unlabelled rows, rows the split does not place) | 87 | 28 |
| **Total** | **1,303** | **2,402** |

So, by family [I]: Snapdragon phones from the 8 Gen 1 and 7 Gen 1 on, Exynos phones with Xclipse, and
Mali phones on ARM's newest drivers have it; older Snapdragons, most Mali phones and Huawei's do not.
**Android needs a logic-op fallback** (V10). WebGPU and SDL3's GPU API have no logic ops at all
(`SDL_GPUColorTargetBlendState`, SDL_gpu.h:1735-1748, main, 2026-09-25) [V].

### 2.6 Toolchain facts

- The Windows SDK's `dxc.exe` (1.8.2502.11) **cannot emit SPIR-V**: "SPIR-V CodeGen not available"
  (a probe in scratch) [V]. A Vulkan build needs a fetched compiler.
- glslang 16.6.0 (published 2026-09-11) ships `glslang-16.6.0-windows-x86_64-release.zip`, 13.7 MB;
  Vulkan-Headers' newest tag is `vulkan-sdk-1.4.357.0` [V, GitHub API].
- `tools/fetch_toolchain.py` already fetches the Metrowerks compilers into the gitignored `vendor/`
  and records SHA-256s in `vendor/TOOLCHAIN.sha256` [V]; `vendor`, `build` and `gen` are in
  `FORBIDDEN_DIRS` (guard.py:73-96 at b071949, from :74 at 012164a) [V]. That is the pattern for a shader
  compiler.
- SPEC.md:398 and :463-464 say the port has "no shader compiler" and "no third-party runtime
  dependency"; they were settled because there was no GPU path [V]. A fetched build-time compiler
  reopens the first; a driver-supplied `vulkan-1.dll` loaded at run time does not break the second [I].
- Direct3D 11 needs none of this: `D3DCompile` ships with Windows. Its logic ops (D3D11.1) require
  blending off on that target (`D3D11_RENDER_TARGET_BLEND_DESC1`: "If you set LogicOpEnable to TRUE,
  then BlendEnable must be FALSE") and the `OutputMergerLogicOp` option [V-web, Microsoft Learn];
  Dolphin's D3D backend creates an integer (UINT) view of the EFB for them (`DXTexture.cpp`, "Only
  create the integer RTV when logic ops are supported") [V-web].

### 2.7 Where the other plans stand

- H15d is paused and deferred to this decision with H16; H18 follows H17b (../PLAN-NEXT.md A4, D-24).
  At 8 threads the field captures
  meet 61 ns a fragment on a quiet machine; ship and sky are 1.3–1.6× short (FINDINGS "H15d paused",
  574c683:docs/FINDINGS.md:2919) [V].
- H17a is not blocked by this decision and follows gameplay milestone 1 (PLAN-60FPS-MODS.md:371-381,
  cb469d6) [V]. The implementation session asks that H17a be designed at the `DrawCmd` level, with a
  second EFB, whatever draws it. H10's pair key includes the display list a draw came through
  (gxr.c:2100-2106; `pair_key`, gxr.c:2162-2167, via `gx_draw_list`; set at gx.c:361) [V].
- Portability L0 (acquire loads, `docs/specs/now.md` N4) **landed as c8274db** while this was written:
  every cross-thread read in the queue is `LOAD_ACQUIRE64/32` (gxr.c:1585-1589) [V]. L2 (`plat.h`, the
  POSIX worker pool) lands before this spec carves the `DrawCmd` interface (portability.md, "Churn").
- The comfort pack's P5b (deflicker off for the display copy) and a possible M11a-skip both edit
  `enqueue_copy`, which V2 rewires (comfort-pack.md 3.13, 3.14) [V].

### 2.8 A finding: display lists recorded at run time are empty

- **Every `GXCallDisplayList` in the 35 captures has size 0**: 227 calls, no other size [V].
  **This is not new as an observation**: FINDINGS H4 (docs/FINDINGS.md:1686-1687) recorded the zeros
  and read them as "all draws are direct", and H5 (:1688-1700) dropped route (d) on the same reading;
  ARCHITECTURE.md:513-517 documents that display lists are handled inside the parse and that the
  `PI_FIFO_*` registers "are stored and read back but never used to route" (the 0x40 row is
  ARCHITECTURE.md:78). **What is new is the chain below, which shows that reading is wrong.**
- The game records display lists every frame: about a hundred call sites in the render-layer code
  (`fn_801CC6BC` … `fn_801D0DCC`) and the mask effect's list recorder `fn_801D184C` (it records objects
  that `fn_801E4CB0` and `fn_801E676C` register) go through the middleware's `fn_802A8D64` /
  `fn_802A8E50`, which call **`fn_80251D80`**, and `fn_802A8BA4` calls **`fn_80251E48`** [V, scratch
  cross-reference]. By the SDK's layout these are `GXBeginDisplayList` and `GXEndDisplayList` [I].
  Both call `GXSetCPUFifo` (`fn_8024C5FC`, named by dtk), which writes the PI FIFO base, end and write
  pointer through the pointer at r13-27536, and `fn_8024C8A4` reads the write pointer back, which is
  how the list's size is taken [V, disassembly].
- **The port parses every gather-pipe store immediately** (gx.c:428-439; "the CPU FIFO in main memory
  is not modelled", gx.c:14-16) and only stores the PI FIFO registers (gx.c:488-490); the write
  pointer never advances [V]. So a recorded list's commands run **when they are recorded**, during
  the scene update, and the list is empty when the draw pass calls it [I, strongly suggested by the
  chain and the 227 zeros]. H5 found the main loop runs reset, scene update, draw pass in that order
  (FINDINGS "H5") [V].
- **In the port the mask effect's caster pass contributes nothing** [V]:
  - in all 12 distinct mask-effect frames, the only commands between the first OR's full-screen quad
    and the second R8 copy are 1 to 4 display-list calls, all of size 0 (a `fifo.py` walk);
  - the recorder's list header at 0x804EB760 is an `NGDL` block whose 64-byte list body at 0x804EB7A0
    is all zero padding (written by `fn_802A8BA4`'s pad loop), in every mask capture's RAM;
  - the second copy's destination, 0x3A84E0 (0x4B000 bytes), is uniformly 0xFF at end of frame in
    1550, 4500, 4800, 6000 and 6300 and in perfset `field/5000` and `cutscene/4500`: the mask the
    first OR painted, untouched by any caster. (In 15200, 15800, 16300 and the pairs' second frames
    `field/5001` and `cutscene/4501`, both copy destinations hold 0x00 at end of frame; why is not
    known — see section 7.)
- **Likely consequence, stated plainly** [I]: the effect's casters never draw, so whatever they
  produce — character shadows, by Dolphin's testing notes, which report "red/green shadows" and a
  "red box under characters" for this game — is **missing in both renderers today**. More generally,
  layered draws happen in recording order instead of the layer order the draw pass calls them in, so
  any transparency or overlay that depends on that order would be wrong in both renderers, and the
  pinned corpus pins it: **8 of the 23 corpus hashes (1550, 4500, 4800, 6000, 6300, 15200, 15800,
  16300) have pinned a mask effect with no casters since the manifest was first blessed** — CLAUDE.md's
  "first bless" case.
- It is a front-end question (gx.c), independent of the GPU, and belongs to the implementation
  session. Proposed as **PLAN C5a–C5c** in section 6, with checks.

---

## 3. Design

### 3.1 Where the GPU plugs in: after the producer, at the `DrawCmd`

**Decision: the GPU backend consumes `DrawCmd`s, in place of the worker pool.** Everything up to the
queue stays on the CPU and unchanged: the parse, vertex decode, transform and lighting, TEV
resolution, texture decode and the cache (H12's epoch hashing, palette re-hash, M3c's texture
provider, M9's packs), the pair machinery (H10) and the hazard list. The backend receives only what
the workers receive today.

**The interface** (a new header, `runtime/gxr_cmd.h`, holding `Rect`, `PixelCfg`, `RasterCfg`,
`DrawCmd` moved out of gxr.c, and this):

```c
/* A backend draws the queue's commands instead of the worker pool (GPU spec V2).
 * Set before the first command is built; the pool is then never started. */
typedef struct GxrBackend {
    const char* name;
    int  (*draw)(const DrawCmd* D);   /* kind 0 */
    int  (*copy)(const DrawCmd* D);   /* kind 1: to texture (writes guest RAM and its image) or to
                                         screen; never clears (see below) */
    int  (*clear)(const DrawCmd* D);  /* kind 2 */
    void (*reset_efb)(const uint32_t* bp); /* gxr_reset_efb's fill, on the backend's EFB */
    void (*finish)(void);             /* every command so far has run and its RAM writes have landed */
} GxrBackend;
void gxr_set_backend(const GxrBackend* b);          /* NULL: the worker pool, as today */
void gxr_backend_screen(const uint8_t* rgba, int w, int h); /* a screen copy's pixels into g_screen */
/* The CPU renderer's own clipping, for a consumer that clips before upload (3.3). */
int      gxr_vertex_unclipped(const Vertex* v);                   /* vertex_unclipped, gxr.c:1389 */
unsigned gxr_clip_polygon(Vertex* in, unsigned n, Vertex* out);   /* clip_polygon, gxr.c:1394 */
```

- **`DrawCmd` gains `uint8_t efb;`** — 0 the real frame, 1 an in-between image (H17). `claim_slot`
  (gxr.c:1670) sets it from a producer-only `g_target`; H17a adds both, and V2 moves the field into
  `gxr_cmd.h`. **Every
  consumer reads it from the command**, never from global state: the CPU workers through a
  per-command EFB pointer (H17a's work), a GPU backend by choosing its render target (V12). A
  global switch on the backend could not route real and in-between commands interleaved in one queue
  while the consumer runs behind the producer, so there is no `target()` call.
- A `0` return is a failure the backend has logged; the renderer then says so and stops the run
  (V5 decides whether to fall back instead; 3.11).
- `TexCfg` gains `int tex_id; uint32_t tex_gen; uint8_t copy_image;`: the texture-cache slot
  (0–1,023), a generation bumped on every decode, replacement, copy image and eviction of that slot
  (gxr_tev.c), and a flag marking a copy image (which a GPU backend makes itself and never uploads
  from the CPU). They let a backend know when a texture changed without hashing, and cost two stores
  a lookup.
- **A copy's clear, with a backend set, is always its own kind-2 command.** `enqueue_copy` publishes
  the 0x800 clear through `publish_clear` whenever a backend is set, bypassing the foreign test for the
  clear only (the fences keep the foreign test), and `run_copy` does not fuse the clear in that
  case. A backend's `copy()` therefore never clears. Without this, an unfiltered full-scale copy
  (P5b's screen copy, `SOA_DEFLICKER=0`) would carry its clear inside kind 1, and a backend that
  replaced kind 1 would never clear the EFB between frames.
- **Frames presented**: the hook in gxr.c increments `g_frames_presented` after a screen copy's
  `copy()` returns 1 (the counter is static, gxr.c:2581, so a backend cannot).
  `gxr_backend_screen` copies exactly `g_screen_w × g_screen_h` (set by the producer) and asserts that
  `w, h` match.
- **`finish()`**: in V2–V5, `drain()` and `wait_ran()` call `backend->finish()`, a no-op while the
  backend is synchronous. From V6 the consumer thread counts in `g_ran[1]` with `g_workers = 1`
  (3.7), the existing waits cover it, and `finish` is removed.
- **The hook (V2)** is the no-worker path: where gxr.c runs `draw_command(D)` on the producer today
  (gxr.c:2434, 2915, 3031), a set backend is called instead, and `workers_start` starts none. Because
  that path is dead on Windows today (2.1), V2 first makes it reachable and proves it: an explicit
  zero-worker mode (`SOA_GXR_INLINE=1`, and implied whenever a backend is set) and a test-only
  **passthrough backend** (`SOA_GXR_BACKEND=passthrough`) whose `draw`/`copy`/`clear` call the
  existing `draw_command` on the producer, with the clear rule and the presented count above. The
  command numbering, the hazard list and `g_frames_presented` behave as with no workers. Copy images
  are not made (gxr.c:3021 already requires workers), so a same-frame sampler decodes the copy's RAM
  bytes: the synchronous spike writes them before the next command.

**What stays CPU-only** (logged once when the GPU is on): `SOA_THREADS`, `SOA_GXR_DRAIN`,
`SOA_GXR_STALL`, `SOA_GXR_NOSIMD`, `SOA_GXR_PIXEL`'s narration, `SOA_HOSTPROF`'s worker table.
`SOA_GXR_DRAWS` is honoured, which is how a failing frame is bisected to its first bad draw.

### 3.2 Data on the GPU

Chosen for exactness first and portability second; every buffer is an ordinary storage buffer; the
required features are listed in 3.10 (none beyond Vulkan 1.1 core).

- **Vertices**: the frame's `Vertex` records in a storage buffer, read by `gl_VertexIndex` (vertex
  pulling; 156 bytes each, about 1.9 MB for a median frame of 12k vertices [I, from performance.md's
  11.9k]). No vertex input state. Quads draw as 6 indices per 4 vertices from one static index buffer;
  strips as strips; lists as lists; lines and line strips as `LINE_LIST`/`LINE_STRIP` at width 1 and
  points as `POINT_LIST` with `gl_PointSize = 1` (none occur in the corpus; logged once a run when one
  does). A draw with any vertex outside the CPU's clip volume is rebuilt as a triangle list (3.3).
  The vertex ring is bump-allocated per frame and never overwritten before the gate that recycles it
  (below).
- **Three tables for textures and per-draw state:**
  1. **Texture contents**, one entry per pool allocation: `{level offsets[11], lw[11], lh[11],
     nlevels, w, h}` (the content half of `TexCfg`, gxr.h:104-114).
  2. **Per-draw records** in a storage buffer (about 0.5 KB each, indexed by a push constant): the
     TEV shape index; the TEV values (`reg_init`, each stage's konst, `aref0/1`); per texture slot
     `{content index, wrap_s, wrap_t, linear, mip, lod_bias, min_lod, max_lod, scale_s, scale_t, su0,
     sv0}` (36 bytes × 8); fog and pixel parameters; the viewport; `ntex`/`nchan`/`miptex`/
     `texmap_of`. At the corpus's 4,440 draws a frame that is about 2.2 MB.
  3. **TEV shapes**: stage count, selectors, ops, bias/scale/clamp, swap tables, alpha compare
     functions and logic, deduplicated by hash. H15c's census found 33 distinct combiner shapes in
     the benchmark set; per-draw *values* never enter this table (they would multiply it: `reg_init`,
     konst, alpha references and every `TexCfg` field vary per draw, and H10's key already excludes
     TEV colour and konst for the same reason, gxr.c:2105-2106).
- **The texel pool: one storage buffer, bump-allocated, append-only.** Each `(tex_id, tex_gen)` that a
  draw uses gets a **fresh** pool allocation, copied from the CPU cache's decoded levels as RGBA8
  words, and the per-draw record carries that allocation's content index; a slot's allocation is
  never rewritten in place. The pool, the vertex ring and the per-draw buffer reset only at a gate
  after the GPU fence for that frame has signalled, so a draw already recorded but not yet executed
  always samples what it was built with, even when the CPU cache evicts and reuses the slot in the
  same frame. The shader fetches texels by index and filters itself (3.4), so wrap modes,
  non-power-of-two sizes, mirror and the CPU's integer bilinear weights come out the same, and M9's
  replacement images of any size just work. Copy images (V7; `TexCfg.copy_image`) are written into
  the pool by the copy pass and never uploaded from the CPU image buffer, which nothing fills when the
  GPU makes them. Pool cap = min(128 MB, the device's `maxStorageBufferRange`; 128 MB is Vulkan's
  guaranteed minimum). **If the pool runs out mid-frame**: submit, wait for the fence, reset, and
  re-upload what the rest of the frame needs; counted in the end report.
- **The EFB**: an `R8G8B8A8_UNORM` colour attachment, 640×528, keeping alpha exactly as the CPU
  renderer does (it keeps an alpha byte although the console's RGB8 format has none; gxr.c:365-373),
  and a `D32_SFLOAT` depth attachment, since the Z1E's GPU has no 24-bit depth (2.4).
- **Copy outputs**: a storage buffer for the tiled bytes of a copy to texture (seeded from guest RAM,
  3.6), a host-visible buffer to read them back, and a 640×480 RGBA buffer for the screen copy.

### 3.3 The vertex stage

- **Clip space in, the CPU's screen mapping reproduced.** For a vertex (x, y, z, w) the CPU computes
  sx = xorig + x/w·wd, sy = yorig + y/w·ht, depth = (farz + z/w·zrange)/2²⁴ (`to_screen`,
  gxr.c:951). The shader emits
  `gl_Position = (x·wd/320 + (xorig/320 − 1)·w, y·ht/264 + (yorig/264 − 1)·w, 0.5·w, w)`,
  which the GPU's own divide and viewport (the full 640×528 EFB) turn into the same sx and sy.
- **Depth travels as its own `noperspective` varying**, `(farz + z/w·zrange)/2²⁴` computed per vertex
  under `precise`: the CPU interpolates depth linearly in screen space (its plane is built from the
  vertices' screen depths, gxr.c:1164), which is what `noperspective` does. Holding `gl_Position.z`
  at 0.5·w keeps every vertex inside the GPU's own depth clip volume, so **no depth clamping is
  needed** and the GPU never cuts what the CPU keeps.
- **Clipping on the CPU, in the consumer, with the renderer's own functions** — the only clip path,
  chosen for exact parity and because 39% of Android devices lack clip distances (2.5). For each
  draw the consumer tests every vertex with `gxr_vertex_unclipped` (gxr.c:1389: near z + w ≥ 0,
  w > 0, far w·2⁻²³ − z ≥ 0; the three planes of `clip_dist`, gxr.c:1357-1363). A draw whose
  vertices all pass is uploaded as it is. A draw with any failing vertex is rebuilt as a triangle
  list exactly as `emit_triangle` (gxr.c:1402) walks it: inside triangles copied in its vertex order,
  crossing triangles through `gxr_clip_polygon` (gxr.c:1394) and fanned, triangles wholly outside
  dropped. The GPU then gets the CPU's own clipped vertices. x and y are clipped by the scissor, as
  on the CPU.
- **Position invariance is required.** The game draws the same vertices more than once under
  different TEV and blend states and relies on `LEQUAL` ties; different pipelines may compile the
  position arithmetic differently. `raster.vert` declares `invariant gl_Position;` and computes the
  depth varying under `precise`.
- **Culling** maps the CPU's signed-area rule (gxr.c:1128-1135) to a cull mode and front face,
  including mode 3 (`FRONT_AND_BACK`: nothing drawn, gxr.c:1134); V3a's bring-up checks all windings
  under all four modes against the CPU.
- **Scissor** is `RasterCfg.scissor`, inclusive, as a dynamic scissor.

### 3.4 The fragment stage: the TEV as one integer-exact shader

- **One uber-shader**, GLSL compiled offline to SPIR-V, reading its TEV shape and the draw's values.
  It is `tev_pixel` (gxr_tev.c:1272) transcribed: the 32-entry input bank, the lerp
  `(a·(256−c′) + b·c′ + 128) >> 8`, bias, scale, the s11 and 0..255 clamps, the compare modes, swap
  tables, konst, and the two alpha compares with AND, OR, XOR and XNOR. All integer, so a
  transcription can be exact, and V3b proves it exact against the C over setups built by
  `tev_prepare`. The H15c fast shapes are not needed: they give the same numbers.
- **Specialisation later**: V7 turns the **shape** fields (stage count, selectors, ops,
  bias/scale/clamp, swap tables, alpha compare functions and logic) into specialization constants,
  never the values, so the driver folds the uber-shader into small shaders with no run-time GLSL
  compiler and the pipeline count follows the ~33 shapes, not the draws. The spike stays uber.
- **Colours**: interpolated perspective-correct as on the CPU, then `int(c·255 + 0.5)` clamped,
  the CPU's formula (gxr.c:1239-1244).
- **Texture sampling in the shader, on the pool**: `sample` / `sample_level` (gxr_tev.c:1160-1235)
  transcribed: q divide, level-0 factors `su0`/`sv0`, wrap clamp/repeat/mirror including
  non-power-of-two modulo, nearest, and bilinear with the CPU's 8-bit integer weights. The level of
  detail comes from `dFdxFine`/`dFdyFine` of the scaled coordinates with span_lod's formula
  (gxr.c:1083). **The formulas are identical; their inputs are not.** The CPU steps every attribute
  along a span by repeated float adds and divides per pixel (`av[n] += attr[n].a`, gxr.c:1252;
  `w = 1/av[wi]`, gxr.c:1232), the GPU interpolates barycentrically, and Vulkan's division is not
  correctly rounded (2.5 ULP). So **level choice near boundaries (the CPU evaluates it at a span's
  two ends and interpolates), and texel and weight choice where interpolated s, t differ in the last
  bits (gxr_tev.c:1170-1171 truncates to 1/256), are the sampling differences left by design**;
  vertex colours can likewise move by one step. The oracle's near band and blob terms absorb them.
- **Alpha test**: `discard` on the TEV's own `alpha_passes`, then the depth test, which is the CPU's
  late order. The CPU tests depth first only for `ztop` draws and where `TevSetup.alpha_always` says
  the order cannot change a pixel (gxr.c:1030-1056); no draw in the corpus is `ztop` with an alpha
  test that can reject (HANDOFF, wrong statement 2) [V], so the late order gives the CPU's result
  everywhere, and such a draw is a tripwire. If V7 adds early depth as a speed-up, it takes
  `alpha_always` from the CPU and never re-derives it (the XOR-of-always-true trap H15a avoided).
- **Depth quantised as the CPU compares it**: `zq = uint(clamp(depth, 0, 1) · 16777215)` from the
  depth varying (truncating, as `depth_test`, gxr.c:1009), written as `gl_FragDepth = zq · 2⁻²⁴`,
  which D32F holds exactly, so `LEQUAL` compares the same integers. Clears store `zreg · 2⁻²⁴`.
  Writing depth in the shader turns off early-Z; at this game's fragment counts that is affordable
  [I, V4a measures].
- **Fog**: `fog_apply` (gxr.c:922) transcribed on the unquantised depth varying, under `precise` so
  the compiler cannot fuse the multiply-adds. Vulkan bounds `exp2` only within (3 + 2|x|) ULP, and the
  argument reaches −8 (gxr.c:941-944), so up to 19 ULP; `ze`'s division is 2.5 ULP. Either can move
  `fi` by one near a step, which the oracle's near band absorbs. **Exact option** (V7, if the oracle
  shows fog steps): a 256-entry table of the `f` thresholds at which `fi` steps, found on the CPU by
  bisection over `exp2f`, makes `fi` exact given the same `f`.
- **Constant alpha** (PE_CMODE1 bit 8) is never used (2.2). If it appears, the backend logs a
  tripwire and uses dual-source blending (true on the Z1E's GPU; optional, 3.10) to store it.

### 3.5 The pixel engine

- **Blend** maps GX factors to Vulkan: 0 ZERO, 1 ONE, 2 DST_COLOR (source) / SRC_COLOR
  (destination), 3 their inverses, 4 SRC_ALPHA, 5 ONE_MINUS_SRC_ALPHA, 6/7 DST_ALPHA and its inverse;
  subtract is REVERSE_SUBTRACT with ONE, ONE, as the CPU ignores the factors there (gxr.c:988).
  The alpha channel blends ONE, ZERO, because the CPU stores the source alpha unblended
  (gxr.c:1005-1006). Rounding may differ from the CPU's `(x·f + y·g + 127)/255` by one step.
- **Write masks** are `col_upd` and `alpha_upd`.
- **Logic ops, in order of preference:**
  1. **Native `logicOp`** where the device has it (the Z1E's GPU does). Vulkan applies it to all four
     channels, while the CPU applies it to RGB and stores source alpha (gxr.c:991-1006). The alpha
     plane then differs; nothing in the corpus reads it (no destination-alpha factor, no alpha-bearing
     copy) [V, 2.2].
  2. **The blend approximation**, for OR and AND, which is all the game uses: OR as
     `src·(1−dst) + dst`, AND as `src·dst`, alpha ONE, ZERO. It is exact whenever, per channel, one
     operand is 0 or 255. It holds in capture 6000, read draw by draw [V]: the first OR draws the
     vertex colour (255, 0, 0); the AND draws (0, 255, 255); the second OR draws an I8 copy times the
     vertex colour (255, 0, 0), so (I, 0, 0), into a red channel the AND has just cleared. The other 11
     distinct frames run the same `PE_CMODE0` sequence [V]; V4b proves it on all 14 captures with a
     same-replay contrast (native against approximation must give identical images). Note what this
     means for testing: **on these operands even plain saturating addition equals OR** (255 + d
     saturates to 255, 0 + d = d, I + 0 = I), so a mutation of the OR's arithmetic cannot show up in
     this game's frames; V4b's mutations change the operation instead, and V10's synthetic 0x55 | 0xAA
     case is where blend and OR truly differ (blend gives 198, OR 255).
  3. **An EFB snapshot**: copy the EFB to a texture before the draw and compute the bitwise op in the
     shader. Exact for any operands when the draw's triangles do not overlap each other, which every
     logic draw here satisfies (one full-screen quad each). Universal, including WebGPU-class APIs.
  4. **Framebuffer fetch**: `VK_KHR_dynamic_rendering_local_read` for reads of what earlier draws
     wrote (after a barrier); exact for a **self-overlapping** draw only with
     `VK_EXT_rasterization_order_attachment_access` (absent on the Z1E's GPU, 2.4) or fragment-shader
     interlock (present). Not needed for this game unless C5 adds caster draws under a logic op.
- **Dither** is ignored, as on the CPU (RGB8 has none).

### 3.6 Copies and clears

- **Every copy is a compute pass** reading the EFB as a sampled image, after the render pass ends:
  - **full scale**: the vertical filter as `filter_sample` does it (taps clamped to the copy
    rectangle, >> 6 truncating); **half scale (bit 9)**: the 2×2 box and no vertical filter, as
    `copy_to_texture` does (gxr.c:2522, 2536-2540; none in the corpus); then
  - **to texture**: the format conversion and tiling of `copy_to_texture` (gxr.c:2467-2594), formats
    0–6 with intensity and channel selection, one invocation per output word, the intensity formula
    under `precise`. **The copy buffer is first seeded from guest RAM over `[dest, dest +
    copy_bytes)`**, so texels outside the copy's `ow × oh` (padding in partial tiles) and the other
    nibble of an R4 byte keep their old bytes, as on the CPU (gxr.c:2566). It writes (a) the tiled
    bytes, read back and copied into guest RAM at the destination, and (b) the decoded RGBA image into
    the pool allocation for the copy image (V7), which is what `tex_decode_row` would decode from those
    bytes;
  - **to the screen**: the filtered RGBA 640×480 into a buffer read back into `g_screen`
    (through `gxr_backend_screen`); gxr.c's hook then increments `g_frames_presented` once (3.1).
  - **A copy never clears.** With a backend set, the 0x800 clear always arrives as the next kind-2
    command (3.1): colour `(ar & 0xFF, gb >> 8, gb & 0xFF, ar >> 8)` and depth `zreg · 2⁻²⁴`, exactly
    `efb_clear`.
- **When RAM is written.** The rule is parity with the CPU renderer, not with the console: a copy's
  bytes must be in guest RAM no later than the CPU renderer's workers would have finished it. In
  practice: before any producer read the hazard list names (texture, palette, vertex arrays, display
  list, indexed XF, hook), before a `GXDrawDone`, before the frame gate, and before the frame hook of
  a captured frame. The spike does it synchronously at every copy; V6 by readback-before-count; V7
  defers it behind a separate "landed" count, and must keep every copy-wait above exactly (Dolphin
  runs this game single-core, 2.3).
- **The display copy never goes to RAM**, as today. The XFB region's bytes are then the R8 copies',
  exactly as the CPU renderer leaves them.
- **Copy formats the CPU refuses** (`copy_texfmt` → 99: an unknown format, or intensity with a
  format above 3; gxr.c:2688-2692) are refused the same way, guest RAM untouched.

### 3.7 Threads and the queue (post-gate)

- **One consumer instead of a pool.** The GPU backend is the ring's single consumer on its own
  thread (V6), counting in `g_ran[1]` with `g_workers = 1`, so `gxr_presented`'s divisor and every
  existing wait keep their meaning and `finish()` is retired (3.1). Fences are satisfied trivially,
  since one consumer runs in order. It uses L0's acquire loads (`LOAD_ACQUIRE64`, gxr.c:1585-1589)
  and L2's `plat.h` waits, like the workers.
- **Lifetimes stay the queue's.** The consumer copies a command's vertices and any changed textures
  into GPU buffers before it counts the command, so the drain's recycling of the arena and the
  texture graveyard (gxr.c:2057-2094) stays correct unchanged. The GPU-side buffers follow 3.2's
  append-only rule and reset only after the frame's fence.
- **Copies to texture** count only once their bytes are in guest RAM (V6); every existing wait then
  means what it meant.
- **Screen copies** count once `g_screen` holds the frame, so `gxr_presented()` and `SOA_HASH` keep
  their meaning.

### 3.8 Presentation

- **First (V5, V6): read back and present as today.** The screen copy lands in `g_screen`; H8's
  D3D11 presenter, M8's overlay (drawn into the BGRA buffer in `present()`), `SOA_HASH`, `SOA_SNAP`
  and PNGs all work unchanged. At 640×480 a readback is 1.2 MB a frame.
- **Later (V8): present from the GPU**, needed for resolution scaling: a Vulkan swap chain on the
  window, with H8's pacing (hold a frame for two refreshes at 60 Hz, four at 120), and M8's overlay,
  H19a's scaler and P5a's filters as shaders (comfort-pack spec: their CPU functions are the
  reference), for whichever of them have landed.

### 3.9 How existing features behave with the GPU on

| Feature | With `SOA_GPU=vulkan` |
|---|---|
| `SOA_HASH`, `SOA_SNAP`, `--replay` PNG | Describe the GPU's picture (read back into `g_screen`). Never pinned: `scenario.py replay` cannot see the GPU, because `replay_once` strips every `SOA_*` variable and sets `SOA_SETTINGS=0` (scenario.py:964-967); V5 tests that, and the sweep refuses any replay whose output has a `[gxv]` start line |
| The 23 pinned hashes | Unchanged, because they are checked with the GPU off |
| H10 pair replay, `tools/midpoint.py` | Pairing is producer-side and works; midpoint's thread-count check does not apply |
| Copy images, fences, drains | CPU mechanisms; the GPU has its own (3.6, 3.7) |
| M3c projection filter, M10/M14 widescreen | In `transform`, before the `DrawCmd`: unchanged. V9 adds a wider EFB instead of the anamorphic squeeze |
| M3c texture provider, M9 packs, P8 | Through the CPU cache: the replaced image is what is uploaded |
| X6 injected draws | They are `DrawCmd`s (beyond-gamecube.md §7): drawn like the game's |
| H17 interpolation | `DrawCmd.efb` = 1 selects the second target (V12). The in-between pass samples F+1's copy images, which the real pass made first |
| M8 overlay, H8 presenter | Unchanged until V8 moves presentation to the GPU |
| Frame hook, pokes, peeks, mods | Unchanged; a hook's hazard wait also waits for the readback |

### 3.10 API, shader toolchain and build

**Recommendation: Vulkan 1.1 core, written in C, if Android is a goal (Q-V1); Direct3D 11 if it is
not.** Section 4 has the comparison. **If Q-V1 is answered "no" before V3 starts, V3–V4 are built on
Direct3D 11 instead** (V3′/V4′, section 6): HLSL through `D3DCompile`, an `R8G8B8A8_TYPELESS` EFB
with a UNORM view for blending and a UINT view for logic ops (2.6), no `fetch_gpu.py`; the oracle,
the differentials and every Done line stay the same. For Vulkan:

- **The loader at run time**: `LoadLibrary("vulkan-1.dll")` / `dlopen("libvulkan.so.1")` and
  `vkGetInstanceProcAddr`, through portability's `plat_dl_open` / `plat_dl_sym`, which land with their
  first caller (portability.md §3.3): if neither L7 nor L9 has landed, V5 creates `runtime/plat.c` with
  `plat_dl_open/sym/close`, and `toolchain.runtime_support_sources()` returns it (portability.md §3.9).
  No link-time dependency: a machine without Vulkan runs the CPU renderer.
- **Headers and compiler fetched at build time**: `tools/fetch_gpu.py` downloads Vulkan-Headers (a
  pinned tag) and glslang (a pinned release) into `vendor/`, records their SHA-256s in
  `vendor/GPU.sha256`, and `--verify` checks them, as `fetch_toolchain.py` does. Nothing is committed.
- **Shaders**: GLSL sources in the repository (`runtime/gxv/*.glsl`), compiled by glslang to SPIR-V
  at link time into `gen/gxv_spirv.h`, embedded in `soa.exe`.
- **Optional in the build**: without `vendor/` glslang, `--link` builds `soa.exe` without the GPU
  backend, and `SOA_GPU=vulkan` then says "this build has no GPU backend: run
  `python tools/fetch_gpu.py`, then `python tools/recompile.py --link`". The default build is
  unchanged.
- **Baseline**: Vulkan 1.1 with classic render passes (one EFB pass, restarted after each copy).
  **Required features: none beyond core.** `shaderClipDistance` and `depthClamp` are not used (3.3:
  CPU clipping, depth as a varying). **Optional**: `logicOp` (else 3.5's fallbacks), `dualSrcBlend`
  (only for a constant-alpha tripwire). `SOA_GPU_FEATURES=core` makes the backend treat every
  optional feature as absent, which is how the Android capability set is tested on the Z1E's GPU.
  The spike may use nothing past this baseline.

### 3.11 Configuration, logging and failure modes

| Key | Values | Meaning |
|---|---|---|
| `SOA_GPU` / `soa.ini` `gpu` | `off` (default), `vulkan` | The backend |
| `SOA_GPU_DEVICE` | index or name substring | Pick a GPU when there are several |
| `SOA_GPU_LOGICOP` | `native`, `blend`, `snapshot`, `fetch` | Force a logic-op path; how V10's fallbacks are tested on the Z1E's GPU |
| `SOA_GPU_FEATURES` | `all` (default), `core` | Test knob: `core` treats every optional feature as absent |
| `SOA_GPU_VALIDATE` | `1` | Enable the Khronos validation layer when installed; development only |
| `SOA_GPU_SCALE` / `gpu_scale` | `1`, `2`, `3` | Internal resolution (V9) |
| `SOA_GPU_LOADER` | a path | Test knob: the loader to open; a missing file exercises the fallback |
| `SOA_GXR_INLINE` | `1` | Test knob (V2): no worker threads, every command run on the producer; implied by any backend |
| `SOA_GXR_BACKEND` | `passthrough` | Test knob (V2): the passthrough backend, which runs `draw_command` through the seam |

- **Logging**, one line at start: `[gxv] Vulkan 1.4 on AMD Radeon Graphics (AMD proprietary
  26.10.07.06): logicOp yes, dualSrcBlend yes; EFB 640x528 RGBA8 + D32F; logic ops native`. A
  fallback prints one line starting `[gxv] fallback:` and naming the cause. One report line at the
  end: draws, screen copies, texture copies and bytes read back, pipelines created, textures uploaded
  (count and MB), pool resets mid-frame, readback waits, GPU ms a frame (timestamp queries)
  p50/p95/p99, consumer CPU ms a frame p50/p95/p99. The passthrough prints
  `[gxr] backend passthrough: N draws, M copies, K clears`.
- **Failure modes**:
  - loader or device missing: one `[gxv] fallback:` line naming it, and the CPU renderer runs (no
    required feature can be absent, 3.10);
  - a shader failing to compile: the build fails, since it happens at `--link`;
  - pool or memory exhausted mid-frame: submit, wait, reset and re-upload (3.2), counted in the report;
  - device lost: V5 stops the run with a message naming the frame; falling back mid-run is a later
    choice, since the EFB lives on the GPU.

### 3.12 Validation: an oracle for a renderer that cannot match hashes

**Three layers, from exact to judged.**

1. **Exact where exactness is possible**, both in V3b:
   - **The TEV**: a compute shader runs the uber-shader's combiner over setups built by
     `tev_prepare` from random BP words, against `tev_pixel` fed through 1×1 nearest textures (which
     return a chosen texel anywhere). Zero mismatches, with every path's hit count printed and at
     least 100 (V3b); a flipped clamp in the GLSL is the mutation.
   - **The copy encoder**: random EFB contents and random copy commands (every format, intensity,
     half, filter on and off, odd rectangles, random destination bytes) through the compute copy,
     against `copy_to_texture` and `copy_to_screen` on the same EFB in the renderer-only build.
     Byte-identical; a rounding change and a whole-buffer write-back are the mutations.
2. **A tolerance oracle on whole frames** (V0), for what legitimately differs: coverage along edges,
   interpolation rounding and last-bit sampling differences (3.4), blend rounding, level-of-detail
   choice near boundaries, the fog `exp2` bound.
3. **Eyes**: side-by-side PNGs and a difference heat map for every frame that fails, and four for the
   owner at the gate.

**The frame metric** (`tools/imgdiff.py`, stdlib only, CI-runnable), per capture, reference R against
candidate C, both 640×480:
- d = the largest of |R−C| over R, G, B at each pixel;
- **exact** d = 0, **near** 1 ≤ d ≤ 16, **far** d > 16;
- **blob** = far pixels that survive a 3×3 erosion (all eight neighbours far). A missing or wrong
  object leaves blobs; edge disagreements, which are one or two pixels wide, do not;
- **MAE**, the mean absolute error over all pixels and channels, and **bias**, the mean signed error
  per channel.

**Proposed thresholds, to be frozen by V0 before any GPU frame exists**: far ≤ 1% of pixels,
blob pixels ≤ 64, largest blob (8-connected) ≤ 32 pixels, MAE ≤ 1.5, |bias| ≤ 0.75 on each channel.

**Rules that keep it honest:**
- **The reference is a blessed or inspected frame.** For the 23 corpus captures, `imgdiff` recomputes
  FNV-1a over the reference PNG's pixels exactly as `gxr_screen_hash` does and requires the manifest's
  hash. For the benchmark and new captures, whose manifests pin inputs only, the reference is a CPU
  replay **opened once, with the commit saying what each shows** (V0 for the 12 benchmark frames, V1
  for new ones) — otherwise it would be CLAUDE.md's first bless. From V4a on, every reference is
  regenerated by the spike driver's own CPU path in the same session as the GPU frames and must equal
  the V0 reference byte for byte (corpus: the manifest FNV).
- **Every replay the oracle runs is sanitised**: the child's environment has no `SOA_*` variable
  except the ones the tool sets, and `SOA_SETTINGS=0`, as `replay_once` does (scenario.py:964-967).
- **Poison before replaying a frame with copies to texture.** Because a capture's RAM already holds
  the live run's copy output (2.1), the spike driver, after `load_capture`, fills every copy-to-texture
  destination the frame will write with 0xA5 — found by pre-scanning the stream's BP 0x49/0x4A/0x4B/
  0x52 writes with `copy_bytes`' arithmetic (gxr.c:2706) — on the CPU and GPU paths alike. Then a sampler can only
  see what this replay's copy wrote. A frame whose CPU replay moves under poison is reading a
  destination before this frame's copy writes it (a cross-frame read); FINDINGS names the draw, and
  that frame is judged through `chain` instead.
- **Copies used in a later frame are judged by chaining** (`gpuspike.py chain N N+1 …`): replay N and
  keep each copy's bytes; load N+1's RAM; splice the kept bytes over those destinations, except ranges
  N+1 copies into itself; then parse N+1. On the CPU path the spliced bytes must equal N+1's RAM at
  those ranges, which proves no CPU write came between; if they differ, FINDINGS marks the pair
  unusable for chaining.
- **Mutations first.** V0 proves the metric fails on image-level mutations and passes on
  legitimate-noise ones; V4a/V4b prove it fails on mutations of the GPU path itself.
- **A mutation "applies" to a capture** when it changes at least 0.5% of that capture's pixels
  (against the unmutated GPU image of the same replay). Each GPU-path mutation must apply on at least
  5 captures (the count printed) and must fail V0 on **every** capture where it applies. Blind spots
  are counted over distinct frames.
- **Failures are classified.** A capture that fails V0 either has a **by-design** cause — one of the
  differences 3.4/3.5 list (edge coverage, last-bit sampling and level choice, blend rounding, the fog
  `exp2` bound), shown by bisection to its first diverging draw — or it is a **defect**, which is
  fixed within the slice that found it. More than 3 by-design failures in one slice sends the
  threshold question to its own commit.
- **Thresholds are a baseline claim.** Their commit says which mutations fixed them and how. After
  the spike runs, any change to a threshold is its own commit, names the inspected frames that justify
  it, and must still fail every mutation.
- **No GPU output is ever pinned**, and a frame that fails is attributed by bisection
  (`SOA_GXR_DRAWS=N` on both paths) to its first diverging draw before anything else happens.
- **Replays only** (rule 7): the oracle never compares two live runs. A live run with the GPU on is
  judged on its own invariants and its own log (V5, V6b).

### 3.13 H17, widescreen and textures, together

- **H17**: interpolation is producer-side (match draws, lerp positions, build a second stream) and
  identical for both backends; `DrawCmd.efb` routes it. On the GPU the second EFB is just a second
  render target, and the in-between image costs one more pass of a few milliseconds [I]. A CPU H17a
  first measures how many images a second each scene reaches; the GPU then removes the ceiling in the
  sky and ship scenes. **Nothing here blocks H17a.** C5 changes H10's pair key inputs (section 5), so
  H4's match rates are re-measured after C5, before H17a.
- **Widescreen**: M10 squeezes perspective draws into the 640-wide EFB and stretches the picture. With
  the GPU, V9 widens the EFB (854×480 for 16:9) so nothing is squeezed; the R8 copies and the screen
  copy widen with it, and their RAM readbacks are resampled to the game's 640 so the game sees what it
  expects. At scale > 1, copy images stay at their scaled size in the pool and are sampled with
  texcoords normalised by the game's declared size; the native-size RAM readback serves CPU readers
  only — otherwise every mask-effect frame would lose red-channel resolution, since the second OR
  writes the first copy back into red.
- **Textures**: the GPU makes high-resolution packs cheap to sample. Upload is once per change.

---

## 4. Alternatives considered

| Alternative | Why not (now) |
|---|---|
| **Consume the FIFO** (Dolphin's VideoCommon, Aurora's command processor): transform and light on the GPU | Duplicates the XF block in shaders; moves vertex history onto the GPU, which breaks H10's retention design (ARCHITECTURE §12) and X6; saves 2–4 ms of CPU a frame the guest thread can afford (it runs the Dangral base at ~125 images a second alone) |
| **A GX-API layer** (Aurora as a library) | Needs the GX calls and the middleware decompiled or bound; the port's translated code writes the FIFO directly (port-android.md) |
| **Fork Aurora** (MIT, Dawn + SDL3 + C++20) | Fatal on any logic op but CLEAR/COPY/NOOP (`lib/gx/gx.cpp:137-139` at 0812291), keeps copies on the GPU only (`GXCopyDisp` empty), and brings Dawn, SDL3, C++ and CMake against SPEC §10 (port-performance.md §4) |
| **Direct3D 11** | The best Windows-only choice: already in the port (window.c), no fetched compiler (`D3DCompile` ships with Windows), shares H8's device so no readback, Proton covers the Deck. Logic ops through D3D11.1 where the driver offers `OutputMergerLogicOp`, **with blending off on that target and a UINT view of the EFB** (2.6), so the EFB is `R8G8B8A8_TYPELESS` with UNORM and UINT views. No Android. **Chosen if Android is not a goal (Q-V1); then the spike is built on it (V3′/V4′)** |
| **Direct3D 12** | Windows-only like D3D11, with Vulkan's verbosity and none of its reach |
| **SDL3's GPU API** | No logic ops (SDL_gpu.h:1735-1748); needs SDL3 at run time (Q6 open); SPIR-V still needs a compiler, plus shadercross for D3D12; made `shaderClipDistance` mandatory until issue #12652 |
| **WebGPU / Dawn** | No logic ops; a very large C++ dependency |
| **OpenGL / GLES** | Run-time GLSL compile is convenient, but GLES has no logic ops, AMD's Windows GL is the weaker driver, and it is the legacy path |
| **Per-TEV GLSL compiled at run time** | Needs glslang as a run-time library (a third-party runtime dependency); specialization constants give the same result with SPIR-V built once |
| **GPU clip distances** (`gl_ClipDistance`) | Missing on 39% of Android devices (2.5), and they clip in GPU float rather than with the CPU's `clip_against`; CPU clipping in the consumer gives the CPU's exact vertices and needs no feature (3.3) |
| **Texture decode on the GPU** (Dolphin's decoders) | H12 hashing, palette re-hash, copy images, M3c/M9 replacement all live in the CPU cache; decode is 79–93% cheaper since "Palette loads" (FINDINGS) and runs only on change |
| **Hardware texture sampling** | Faster, but its filter weights, wrap for non-power-of-two sizes and mip choice differ; the pool plus manual filtering keeps the sampling formulas identical (their inputs differ in the last bits, 3.4). Revisit in V7 if the GPU is short (it should not be at 640×480) |
| **GPU-only copies, never written to RAM** | Cannot be proven safe (2.3); Dolphin's settings for this game say RAM; the texture copies' readback is 600 KB a frame at most in the corpus |
| **A bit-exact GPU** (the CPU's rasterizer in compute, interlocked pixel engine) | The pixel engine could be made exact with fragment-shader interlock (present on the Z1E's GPU), but coverage and interpolation still follow GPU float rules. Months, for a result the oracle does not need. Kept as the answer if the oracle finds pixel-engine differences that matter |
| **Perceptual metrics** (SSIM, FLIP) | Harder to explain and to prove able to fail; the blob and bias terms catch what matters here. FLIP can be added later |
| **Keep the CPU renderer only** | Option C or D at the gate: honest, cheaper, and closes Android and higher resolution |

---

## 5. Risks and concerns, stated plainly

- **The display-list finding (2.8) undercuts part of the reference.** 8 of the 23 corpus hashes
  (1550, 4500, 4800, 6000, 6300, 15200, 15800, 16300) have pinned a mask effect with no casters since
  the manifest was first blessed. If C5 confirms the chain, the 23 pinned frames pin the port's draw
  order, not the console's, for every layered draw. The GPU spike still means something (it measures
  agreement with the CPU renderer), but the corpus will need re-capturing and re-blessing after C5,
  which is a first bless: every frame opened (C5c). Better to know before V1 captures anything new.
- **C5 moves H10's pair matching, and so H17.** C5 moves caster and layer draws inside display lists,
  whose addresses are part of H10's pair key (gxr.c:2100-2106, 2162-2167). The lists sit in a
  per-frame pool (FINDINGS H5, 0x804E7540; the recorder's at 0x804EB760), so their addresses may shift
  between frames. H4's match rates, and the decision that H7 (draw tags) is not needed, were measured
  while every draw was direct. **They must be re-measured after C5, before H17a** (C5b's Done).
- **A tolerance is a weaker check than a hash.** A bug smaller than the thresholds passes. The
  mutations bound what slips through, and the exact TEV and copy differentials cover the arithmetic,
  but "the picture is right" becomes partly a judgement again.
- **Two renderers forever.** The CPU renderer is the reference and the fallback. Every fix to
  rendering semantics (a new tripwire feature, a filter, C5) lands in the CPU first, then the GPU,
  checked by the oracle.
- **The corpus is narrow where it matters.** All logic ops and all texture copies in the 35 captures
  are one effect, and that effect's casters never draw (2.8). The menu capture Dolphin needed RAM for,
  and the scene-to-texture of `fn_800AF8F8`, are not captured at all. V1 exists for this.
- **Replays can hide a copy that does nothing.** A capture's RAM already holds the live run's copy
  output (2.1), so without 3.12's poison step a GPU copy that wrote nothing would pass. The poison
  and chain steps are what make V4b's copy claims testable.
- **Dolphin runs this game single-core** (`CPUThread = False`, 2.3). That suggests sensitivity to
  CPU/GPU timing [I]. V6 and V7's asynchronous consumer and deferred readback must keep the copy-wait
  semantics of 3.6 exactly; V6b's overlap cases are the check.
- **RAM readbacks cost more on phones.** On a tile GPU a readback stalls the pipeline. The corpus's
  two R8 copies a frame are 600 KB; fine on the Z1E's GPU [I], a measurable cost on a phone. V11 can
  remove readbacks the CPU never reads, once a census proves it.
- **Vulkan on Android is uneven.** 39% of devices lack clip distances and 48% logic ops (2.5); the
  design needs neither (3.3, V10), and `SOA_GPU_FEATURES=core` tests that on the Z1E's GPU. Drivers
  still have bugs Dolphin keeps a list of; the first Android run will find new things.
- **A shader compiler enters the build.** SPEC §10 said there was none. It is fetched and pinned, used
  only at `--link`, and optional, but it is a new moving part (Q-V3).
- **The spike costs about three to four weeks of evenings** (V0 a day, V1 a day, V2 a day to several
  days, V3a and V3b several days each, V4a several days to week-plus, V4b several days) and its C code
  is parked if the answer is C or D. The seam (V2) and the oracle (V0) stay useful either way: V12
  builds on the seam, which carries H17a's `DrawCmd.efb` routing, and the oracle judges clang-cl or
  ARM builds if they ever differ.
- **Timeline.** Post-gate, a live GPU renderer at native resolution with parity is about 4–6 weeks of
  evenings (V5–V7); resolution scaling, widescreen, presentation and the Android fallbacks another
  4–6. Android playable also needs the portability track's L7–L12. "Plays well on a phone" is months.
- **One editor for `runtime/gxr*.c` and `gx.c`.** V2, V5–V7 and V12 touch them; so do L0, L2, C5a/b,
  H17a, P5b and M11a-skip. The implementation session does them, one at a time, in the order
  [../PLAN-NEXT.md](../PLAN-NEXT.md) gives.
- **Energy is unmeasured.** The handheld may well use less power drawing on its GPU than on 12 CPU
  threads [I], but nothing records energy until H20's power line; no claim is made until then.
- **Measurements drift.** This machine drifts about 15% within a day (FINDINGS "H11"): every
  performance number here is taken interleaved, and none is a pass criterion unless it is a budget
  against a fixed limit in one run.

---

## 6. Slices

**Order.** [../PLAN-NEXT.md](../PLAN-NEXT.md) places these slices among the other plans' (C5a in M1,
C5b and C5c in M2, V0–V4b in M5); within them the order is this. C5a first (hours; the first slice of M1,
landed as 750cef0), then C5b, then C5c before V0's references and V1's captures. Pre-gate: V0 after
C5c (or C5a refuted), V1 after V0 and C5b (neither edits the renderer). V2 after L0, L2 and H17a
(../PLAN-NEXT.md M5: H17a adds `DrawCmd.efb` and its `claim_slot` routing; V2 moves them into `gxr_cmd.h`
unchanged); **V2 after P5b and M11a-skip if they are queued, otherwise before them; whichever comes
second rebases on the first** (all three edit `enqueue_copy`). V3a, V3b, then V4a, then V4b (V3′/V4′
on Direct3D 11 if Q-V1 is "no" when V3a starts). The gate. Post-gate: V5, V6a, V6b, V7, then V8–V12 as
the owner's answers allow.

### C5a (proposed for PLAN.md Track C). Confirm the recorded-display-list chain

*Hours. `--link`. Prerequisites: none. Files: `runtime/gx.c` (a log only), FINDINGS entry "Recorded
display lists", with amendment lines on FINDINGS H4 and H5 pointing to it. Not a V-slice: it
changes nothing drawn, and it is the implementation session's.*

- `SOA_GX_DLLOG=1` prints, for each PI FIFO register write (gx.c:488-490), the base, end and write
  pointer, and for each display-list call (gx.c:350) its address and size. Off by default; one
  branch when off.
- The finding holds if, in a run, every recorded list is size 0 and draws are parsed between a PI
  base change and its restore. FINDINGS cites gx.c:14-16 ("the CPU FIFO in main memory is not
  modelled"), H4 (:1686-1687) and ARCHITECTURE.md:513-517.

*Done:*
- One run with `SOA_GX_DLLOG=1` on a copy of the Dangral or `a101b` save, 300 frames drawn: the log
  shows at least one PI base change followed by draws before its restore, and the count of calls
  with size 0 equals the count of calls (both printed, both above zero). If it does not, the finding
  is refuted in FINDINGS and C5b/C5c are dropped.
- With `SOA_GX_DLLOG` unset: the contract (replay 23/23, self test, `title --check`).

*Status: landed as 750cef0,* the first slice of ../PLAN-NEXT.md's M1, because it is cheap and, if the
defect is real, it sits under the replay oracle (8 pinned frames) and under H17 (H10's pair keys). Its
FINDINGS entry "Recorded display lists (C5a): the chain confirmed" reports a run of the opening
scenario to frame 5000: 35,574 moves of the CPU FIFO away from the command processor's, 28.5% of the
run's draws parsed while it was away, and 27,871 display-list calls, every one of size 0; the buffers
are heap blocks 0x80 apart from 0x804EB5A0, called at the addresses they were recorded to [V, 750cef0].
The contract held (replay 23/23 at 1, 2, 3 and 8 threads, the self test, `title --check`). The entry
also names two things C5b must handle (below). C5b and C5c therefore stand.

### C5b (proposed). Record display lists into guest memory

*A day to several days. `--link`, or one retranslation if the bracket needs `hooks.txt` (below).
Prerequisites: C5a confirms (done, 750cef0). Files: `runtime/gx.c`, possibly `config/hooks.txt`,
`tools/tests/test_gx_dlrecord.py` (new), `docs/ARCHITECTURE.md` (:78 and :513-517, corrected),
FINDINGS "Recorded display lists", every copy of the test count.*

- **The rule: record only inside the list functions' bracket.** Between `GXBeginDisplayList`
  (`fn_80251D80`) and `GXEndDisplayList` (`fn_80251E48`), `gx_pipe_write` appends the bytes
  big-endian at the PI write pointer in guest memory and advances it (wrapping at the end, setting
  the overflow bit) instead of parsing. `GXEndDisplayList` then sizes the list, and
  `GXCallDisplayList` parses it at the call (gx.c's display-list case already can). Outside the
  bracket, every byte is parsed at once, as today, **whatever the FIFO bases say**. C5a's run showed
  why the simpler test, "the CPU FIFO's base differs from the GP's", is wrong: at frame 1 the game
  points the CPU FIFO at 0x804024E0, sets the CP there and back to 0x804A74E0, and leaves the CPU FIFO
  at 0x804024E0 until frame 385. The 1,548 draws in that window are never called as a list, and they
  are the developer's logo screen, which the console shows (`build/frames/0200.png`) [V, 750cef0].
- **How the port knows it is inside the bracket** is the first design step, settled with
  `tools/disasm.py` before any code:
  - (a) a hook at each function's entry (`config/hooks.txt`), which is exact and costs one full
    retranslation (CLAUDE.md: `hooks.txt` bakes in like `hle.txt`);
  - (b) a `--link`-only test in the PI register write (gx.c's `PI_FIFO_*` store), keyed on the caller
    `GXSetCPUFifo` (`fn_8024C5FC`) being reached from the two list functions. This holds only if the
    return address seen there is reliably inside them, which the disassembly must show.

  If (b) cannot be shown exact, use (a).
- **Captures must stay replayable**: bytes written into a list are not appended to the capture's
  stream (they would run twice), and a list's bytes are best captured inline at its call, because a
  capture's `.ram` is end-of-frame and a list rebuilt after its call in the same frame would replay
  wrong.
- `gx_report` gains `[gx] display lists: N calls, M nonempty, B bytes`.
- **Recordings outnumber calls** (35,574 against 27,871; the buffer at 0x804EB5A0 was recorded 7,186
  times and called 4,089) [V, 750cef0]. Today every recording is drawn when it is made. After C5b, only
  what a list holds when it is called is drawn. So **some draws the port shows today will disappear,
  and that is correct**: a list recorded again before its call, or never called, was never on the
  console's screen.

*Done:*
- `python -m pytest tools/tests/test_gx_dlrecord.py`, with synthetic streams:
  - inside a Begin/End bracket, record a red quad; then draw a green quad over the same pixels; then
    call the list. With the fix the red lands on top, drawn at the call. The mutation (the fix removed)
    draws the red while recording, and the green covers it;
  - a redirect of the CPU FIFO **outside** any bracket, as at the logo screen: its quad is drawn at
    once. The mutation (the "bases differ" rule) draws nothing;
  - a list recorded twice before one call draws only the second recording, and a list recorded and
    never called draws nothing;
  - a capture of each stream replays to the same picture as the live parse.
- A live run of the opening to frame 1000: `build/frames/0200.png` still shows the logo screen (open it
  and say so in the commit), and the report line's `M nonempty` is above zero, so the check cannot
  pass vacuously.
- Replays of the 23 old captures are unchanged (`python tools/scenario.py replay --threads 1,2,3,8`),
  because a replay parses the captured stream directly.
- **H10 re-measured** on re-captured pairs of the five H4 scenes (captured into `build/perfset-c5/`,
  never `build/fifo`): `python tools/fifopair.py` match rates per scene, with the list-address term's
  contribution reported (matches with and without it), and `python tools/midpoint.py` over the new
  pairs. The 3D-area match must stay at or above 99% in every scene (a limit set here); if it does
  not, H7's dismissal is reopened in FINDINGS before H17a.
- The self test and `python tools/scenario.py run title --check` pass.

### C5c (proposed). Re-capture the corpus and bless it, as a first bless

*A day. Rebuild: none. Prerequisites: C5b. **Owner:** opens every changed frame. Files:
`config/fifo_manifest.tsv`, FINDINGS "Recorded display lists", a note in every spec whose contract
cites the 23 hashes.*

- The corpus's scenes are captured again into a scratch directory (`SOA_FIFO_DIR` set, never
  `build/fifo`), replayed, and each PNG opened beside the old one.

*Done:*
- FINDINGS lists each of the 23 frames as unchanged or changed, and for each changed one says what
  changed and why: casters now drawn, layer order, or **draws removed** because their recording was
  never called (C5b). A removal is expected, not a regression. Each one is traced to a recording with
  no call in that frame's `SOA_GX_DLLOG` output before it is accepted. The owner has looked at each
  changed frame; the commit says so.
- Only then `python tools/scenario.py replay --bless` over the new captures; the old captures are
  kept under `build/fifo-pre-c5/`. The manifest change is announced to every spec's contract.
- `python tools/scenario.py replay --threads 1,2,3,8` is 23/23 against the new manifest.

### V0. The frame oracle, frozen before any GPU frame exists

*A day. Rebuild: none. Prerequisites: C5c, or C5a refuted (../PLAN-NEXT.md M5): the references are
the corpus as it will stay. Files: `tools/imgdiff.py` (new), the PNG reader from
`tools/midpoint.py` moved to `tools/soa/png.py` (S7b's module, if it has not landed),
`tools/tests/test_imgdiff.py` (new), `docs/TESTING.md`, FINDINGS entry "V0", every copy of the test
count.*

- `python tools/imgdiff.py REF CAND [--heat out.png]`: 3.12's metrics and a verdict.
- `python tools/imgdiff.py refs [--set corpus|perfset|gpuset]`: copies each capture to a scratch
  directory, replays it with `gen/soa.exe --replay` (never in `build/fifo`, whose PNGs `--replay`
  overwrites) in a sanitised environment (no inherited `SOA_*`, `SOA_SETTINGS=0`), and keeps the
  reference PNG in `build/gpu-oracle/ref/`. For the corpus it requires the PNG's recomputed FNV-1a to
  equal `config/fifo_manifest.tsv`'s hash.
- `python tools/imgdiff.py mutate`: the mutation suite over the references.

*Done:*
- `python -m pytest tools/tests/test_imgdiff.py` passes, on synthetic PNGs only (CI can run it):
  identity passes; a 24×24 block, a +4 brightness shift and a channel swap fail; 0.3% scattered
  pixels changed by up to 64 and ±1 noise everywhere pass; the FNV check matches a hand-computed value.
  Changing one pixel of a reference makes the FNV check fail. A test asserts `refs`' child
  environment has no `SOA_*` but the tool's own and `SOA_SETTINGS=0` even when the parent sets
  `SOA_GPU=vulkan`; passing `SOA_*` through (the mutation) turns it red.
- `python tools/imgdiff.py refs` produces 23 references whose FNV equals the manifest (a nonzero count,
  23, printed).
- `python tools/imgdiff.py refs --set perfset` produces the 12 benchmark references (12 distinct
  frames once C5c has re-captured the corpus: `corpus/6000` and `corpus/15800` are then pre-C5
  benchmark frames, opened like the rest), and **each is opened once; the commit says what each
  shows**. If C5a was refuted (no C5c), those two are still copies, and their references must equal
  the corpus's byte for byte.
- `python tools/imgdiff.py mutate` over the 23: identity, ±1 noise, 0.3% scattered pixels and a
  1-pixel diagonal line **pass on all 23**. A black 24×24 block placed on the capture's most detailed
  region, +4 brightness, a red-blue swap, a washed-out transform (16 + 0.9c), a one-pixel shift and a
  second 1:2:1 vertical blur **fail on every capture**, except captures FINDINGS lists as that
  mutation's blind spots with the reason (expected: near-uniform frames such as the four-draw boot
  frames 0100 and 0300). More than three blind spots for one mutation stops the slice: the metric
  changes, not the list.
- The thresholds are frozen in `imgdiff.py`, and the commit states which mutations set each one.
- No runtime file changes; the contract holds trivially.

### V1. The captures the corpus lacks

*A day. Rebuild: none (live runs of the current `gen/soa.exe`, one at a time, on card copies).
Prerequisites: V0 for the references; C5b for the mask-effect capture with casters (if C5a was
refuted, there is no such capture). Files:
`tools/fifo.py` (a `--summary` flag: copies with format, destination and size, logic ops,
display-list sizes), `config/gpuset_manifest.tsv` (new: input hashes and labels, no frame hashes),
`tools/tests/test_fifo_summary.py` (new), FINDINGS entry "V1".*

- Capture runs of consecutive frames into `build/gpuset-scan` (`SOA_FIFO_DIR` set, never
  `build/fifo`) around: the save menu opened by the one-word request (HANDOFF), the camp menu opened
  from the pad, the start of a random battle (S3's accelerator), and a map change.
- Keep, in `build/gpuset/`, each frame N whose `--summary` shows a copy to texture other than the mask
  effect's two R8 copies **together with the consecutive frames N+1 … N+k that follow it** (k up to
  the first frame that no longer samples the destination, at most 30), so `gpuspike.py chain` can
  judge a copy sampled in later frames; and (after C5b) a mask-effect frame whose display lists are
  not empty.

*Done:*
- `python -m pytest tools/tests/test_fifo_summary.py`: on a synthetic stream, `--summary` reports one
  R8 copy, one RGB565 copy, a logic OR and a list of size 0x40; removing the copy decode (the mutation)
  fails it.
- For each target: either captures in `build/gpuset/` with their `--summary` lines in FINDINGS and
  their PNGs opened (a first bless of a kind: the commit says what each shows), or "not found" with
  the frames and scenes searched.
- `python tools/imgdiff.py refs --set gpuset` renders every kept capture and verifies its input
  hashes against the manifest.
- The guard passes (`python tools/guard.py`); nothing under `build/` is tracked.

### V2. The seam: `DrawCmd` in a header, a reachable zero-worker path, and a backend hook

*A day to several days. `--link`. Prerequisites: L0 (landed, c8274db) and L2 (portability.md); H17a
(which adds `DrawCmd.efb`); P5b and M11a-skip per the order above; the implementation session holds
`gxr*.c`. Files: `runtime/gxr_cmd.h`
(new), `runtime/gxr.c`, `runtime/gxr.h`, `runtime/gxr_tev.c`, `tools/scenario.py` (`--threads`
accepts `inline`), `tools/tests/test_gxr_backend.py` (new), `docs/ARCHITECTURE.md` (sections 6 and
9), FINDINGS entry "V2", every copy of the test count.*

- 3.1's header and interface: `DrawCmd.efb` as H17a left it, moved into the header; the hook at the three
  no-worker execution points; `SOA_GXR_INLINE=1` (zero workers on every platform; implied by a
  backend); the passthrough backend (`SOA_GXR_BACKEND=passthrough`); a copy's clear as its own kind 2
  whenever a backend is set; `g_frames_presented` incremented by the hook; `finish()` called from
  `drain()`/`wait_ran()`; `TexCfg.tex_id`/`tex_gen`/`copy_image`; `gxr_backend_screen` with its size
  assertion; `gxr_vertex_unclipped`/`gxr_clip_polygon` exported. `SOA_THREADS=0` keeps meaning "the
  default", because it does today (gxr.c:2016) and `soa.ini`'s `threads` key feeds it
  (settings.c:43).

*Done:*
- `python tools/scenario.py replay --threads inline,1,8` is 23/23, which proves the zero-worker path
  before any backend relies on it (`inline` sets `SOA_THREADS=1` and `SOA_GXR_INLINE=1`, and the run's
  `[gxr] rasterizing on 0 worker threads` line is required, so `inline` cannot silently run a pool).
- `python -m pytest tools/tests/test_gxr_backend.py`:
  - a renderer-only driver sets a counting backend and replays a synthetic stream with two draws, a
    filtered copy to texture with the clear bit, an **unfiltered, full-scale copy with the clear bit**,
    a draw, and a screen copy with the clear bit. The backend sees kinds 0, 0, 1, 2, 1, 2, 0, 1, 2 in
    order: a kind 2
    immediately after each copy with the clear bit. `tex_gen` rises when the texture's bytes change
    and not otherwise; `gx_frame_count` and `gxr_presented` agree; every command arrives with
    `efb == 0`, and a test hook that sets `g_target = 1` for one draw makes that command alone arrive
    with `efb == 1`. Mutations, each turning it red: dropping the hook's call for kind 2; keeping the
    clear fused inside the unfiltered copy; not bumping `tex_gen` on a re-decode; `claim_slot`
    ignoring `g_target`;
  - the same driver replays the 23 corpus captures through the passthrough backend and gets the 23
    manifest hashes, with the passthrough's `N draws` line above zero on each. Mutation: the
    passthrough skips every draw with blending on, and the hash of every capture that has such a draw
    moves (the count printed, above zero). (Dropping kind 2 is not a corpus mutation: in a one-frame
    replay the only clears follow the frame's screen copy, so no hash can move; the synthetic stream
    covers it.)
  - The corpus part skips with a printed reason when `build/fifo` is absent (CI); on the owner's
    machine `python -m pytest tools/tests/test_gxr_backend.py -rs` reports 0 skipped.
- `python tools/citest/compile_runtime.py`, `python tools/citest/render_check.py`,
  `python tools/recompile.py --link`.
- `python tools/scenario.py replay --threads 1,2,3,8` is 23/23;
  `python -m pytest tools/tests/test_gxr_overlap.py tools/tests/test_gxr_queue.py tools/tests/test_gxr_pair.py tools/tests/test_gxr_fastpath.py`
  passes.
- Measured, not a gate, reported in FINDINGS: the base exe is saved before relinking; `python
  tools/perfbench.py run --threads 1 --exe <each>` runs interleaved A B B A (portability.md L2a's
  `--exe`), and the 8-thread figure is reported beside it. As in portability.md L2, the `/FA` codegen
  of the worker loop is compared first, and it is timed only if the code moved.
- The self test and `python tools/scenario.py run title --check` pass.

### V3a. A headless Vulkan harness: fetch, build, the EFB pass, the geometry checks

*Several days. Rebuild: none for `soa.exe` (the spike builds its own renderer-only binary; no `gen/`).
Prerequisites: V2; Q-V1 answered "yes" or unanswered (otherwise V3′a, below). Files:
`tools/fetch_gpu.py` (new), `tools/gpuspike.py` (new: `build`, `selftest`), `tools/gpuspike/` (new:
`driver.c`, `gxv.c`, `gxv.h`, `raster.vert`, `raster.frag`), `tools/tests/test_gpuspike.py` (new),
FINDINGS entry "V3", every copy of the test count.*

- `fetch_gpu.py`: Vulkan-Headers `vulkan-sdk-1.4.357.0` and glslang 16.6.0 into `vendor/`, SHA-256s
  in `vendor/GPU.sha256`, `--verify`.
- `gpuspike.py build`: glslang to SPIR-V, embedded as C arrays; `cl` with `toolchain.py`'s flags over
  gx.c, gxr.c, gxr_tev.c, png.c, the driver and `gxv.c`, into `build/gpuspike/`.
- `gxv.c`: instance, device (core features only unless asked), one queue, a bump allocator, the EFB
  pass with 3.3's vertex stage (CPU clipping, depth varying, `invariant`), readback, timestamps;
  loaded through `LoadLibrary`.

*Done:*
- `python tools/fetch_gpu.py --verify` passes; editing one byte of a fetched file makes it fail.
- `python tools/gpuspike.py selftest`:
  - `selftest.c`'s two render recipes (the full-screen quad's 307,200 red pixels, and the second
    check) give the CPU's counts on the GPU;
  - four triangles, both windings, under cull modes 0, 1, 2 and 3, cover the CPU's interiors (edge
    pixels excluded); mode 3 draws 0 pixels beside mode 0's nonzero count;
  - a triangle crossing the near plane and one crossing the far plane: the consumer's clipped
    vertices equal the CPU's `clip_polygon` output byte for byte, and the covered interior matches
    the CPU's (edge pixels excluded); the mutation "upload unclipped" fails it;
  - a line and a point draw cover the CPU's pixels.
- `python -m pytest tools/tests/test_gpuspike.py` runs `--verify` and `selftest`, and **skips with a
  printed reason** when there is no `cl`, no `vendor/` or no Vulkan device, never silently; on the
  owner's machine `python -m pytest tools/tests/test_gpuspike.py -rs` reports **0 skipped**.
- The contract holds (no runtime file changes).

### V3b. The two exact differentials: the TEV and the copy encoder

*Several days. Rebuild: none for `soa.exe`. Prerequisites: V3a. Files: `tools/gpuspike/tev.glsl`,
`tools/gpuspike/copy.comp`, `tools/gpuspike/driver.c`, `tools/gpuspike.py` (`tevdiff`, `copydiff`),
`tools/tests/test_gpuspike.py`, FINDINGS entry "V3".*

*Done:*
- `python tools/gpuspike.py tevdiff --cases 100000`: each case is built by `tev_prepare` from random
  BP words for C0–DF, E0–E7, F3, F6–FD and GEN_MODE, with 1×1 nearest `TexCfg`s, and run twice: as
  prepared, and with `fast_c = fast_a = 0`. Zero mismatches against `tev_pixel`. It prints per-path
  hit counts — each compare mode (`cbias == 3`, `abias == 3`, per op), each `cshift`, `cclamp` 0/1,
  each `alogic` — and **every count is at least 100**. A flipped clamp in `tev.glsl` gives mismatches
  (the mutation, run by the test).
- `python tools/gpuspike.py copydiff`: every copy format 0–6, intensity on and off, half on and off,
  filter on and off, 200 random rectangles each **including odd widths for R4**, with the destination
  filled with random bytes before both paths: byte-identical RAM output over `[dest, dest +
  copy_bytes)`, identical decoded image, identical screen copy. Combinations the CPU refuses
  (intensity with a format above 3) must come out "refused, RAM untouched" on both. Mutations, each
  failing it: a changed rounding in `copy.comp`; writing back the whole buffer without seeding from
  RAM.
- `python -m pytest tools/tests/test_gpuspike.py` runs both; on the owner's machine `-rs` reports 0
  skipped.
- The contract holds.

### V3′a, V3′b, V4′a, V4′b. The same, on Direct3D 11 (only if Q-V1 is "no" when V3a starts)

*Same sizes, prerequisites and Done lines as V3a, V3b, V4a and V4b, with these substitutions: no
`fetch_gpu.py` (and no `--verify` line); HLSL compiled by `D3DCompile` at build time; `gxd.c` in
place of `gxv.c`; an `R8G8B8A8_TYPELESS` EFB with UNORM and UINT views (logic ops on the UINT view
with blending off, where `OutputMergerLogicOp` is true); a `D3D_FEATURE_LEVEL_11_0` device, no swap
chain, through H8's DXGI; `SOA_GPU_FEATURES=core` means "no `OutputMergerLogicOp`".*

### V4a. The spike on captures: draws, textures, depth, fog, blend, the screen copy

*Several days to week-plus, bounded by 3.12's failure rule. Rebuild: none for `soa.exe`.
Prerequisites: V0, V3b. Files: `tools/gpuspike/*`, `tools/gpuspike.py` (`oracle`, `time`),
FINDINGS entry "V4".*

- Vertex pulling, the uber-shader with sampling, fog and alpha test, the pixel engine's blend and
  masks, clears, the screen copy to a PNG. Pipelines keyed by blend, masks, depth, cull, topology,
  created on first use. `SOA_GPU_FEATURES=core` throughout (logic ops are V4b's).

*Done:*
- `python tools/gpuspike.py oracle --set corpus,perfset` over the 21 captures **without** texture
  copies (15 of the corpus, 6 of the benchmark set; all distinct) prints V0's verdict for each. It
  first regenerates every reference with the spike driver's CPU path in the same session: corpus
  references must equal the manifest FNV, benchmark references V0's inspected ones, byte for byte.
  **Every remaining failure has a by-design cause with its bisected first diverging draw; any defect
  found is fixed within the slice; more than 3 by-design failures sends the threshold question to its
  own commit** (3.12). The per-capture table (verdict, cause, draw) goes in FINDINGS.
- Mutations of the GPU path, under 3.12's "applies" rule (≥ 0.5% of pixels changed; each applies on
  at least 5 captures, count printed; each fails V0 on every capture where it applies): skipping the
  frame's largest draw; fog off; the copy filter off in the screen copy; alpha test off;
  level-of-detail bias +1. The FINDINGS table lists each mutation against each capture.
- A synthetic invariance check: one strip drawn twice under two different pipelines (different blend
  and TEV), depth `LEQUAL` with update; the second pass covers every pixel of the first (equal
  counts, above zero). FINDINGS records whether removing `invariant` fails it on the Z1E's GPU.
- `python tools/gpuspike.py time`: GPU milliseconds a frame (timestamps, median of 5) and consumer
  milliseconds, per capture, beside `tools/perfbench.py`'s CPU figures taken interleaved in the same
  session. Reported, not a gate.
- The contract holds.

### V4b. The spike on captures: copies, logic ops, the new captures, and the gate memo

*Several days. Rebuild: none for `soa.exe`. Prerequisites: V4a, V1. Files: `tools/gpuspike/*`,
`tools/gpuspike.py` (`logicop`, `ramdiff`, `chain`, the poison step), this spec's section 8 (the
numbers), FINDINGS entry "V4".* **Owner:** four side-by-sides.

- Copies to texture through the compute copy, synchronously written to guest RAM; logic ops native,
  blend and snapshot (`SOA_GPU_LOGICOP`); 3.12's poison step on every frame with copies to texture,
  and `chain` for copies sampled in later frames.

*Done:*
- **Poison proves the samplers read the copies**: with poison on, the CPU path still gives the
  manifest FNV on all 8 corpus copy captures (1550, 4500, 4800, 6000, 6300, 15200, 15800, 16300) —
  a same-replay contrast — or FINDINGS names the draw that reads a destination before this frame's
  copy writes it, and that frame goes to `chain`.
- `python tools/gpuspike.py oracle --set corpus,perfset,gpuset` over all 35 and V1's captures, poison
  on: verdicts and failure classification as in V4a.
- `python tools/gpuspike.py logicop`: on the 14 mask-effect captures (12 distinct), `native`, `blend`
  and `snapshot` give byte-identical images to each other (a same-replay contrast; count of logic-op
  draws printed, above zero). Mutations that change a mask-operand result, each making `logicop`
  report the paths non-identical with the differing-pixel count printed and above zero, and each
  failing V0 on all 14: (a) the AND drawn as a copy (ONE, ZERO: G and B become 255 full-screen);
  (b) the ORs drawn as copies (source only: G and B become 0); (c) OR drawn as AND (lop 7 and 1
  swapped). (A mutation of the OR's arithmetic, such as saturating addition, cannot differ on this
  game's operands, 3.5.)
- `python tools/gpuspike.py ramdiff`: after each copy to texture, the GPU's bytes in guest RAM against
  the CPU replay's, per copy, both poisoned: bytes written (above zero for every copy), bytes differing
  and the largest difference, with every nonzero difference traced to an EFB difference already
  counted by the oracle.
- Mutations, with poison on, each failing V0 on all 14: logic ops ignored (drawn as copy); copies
  skipped; copy written to dest + 32.
- `python tools/gpuspike.py chain` over each of V1's kept sequences N … N+k: the CPU path's spliced
  bytes equal N+1's RAM at the destinations (or FINDINGS marks the pair unusable), and each chained
  frame's GPU image passes V0 against its CPU chain.
- **Owner**: opens four side-by-sides (field, battle, ship battle, a mask-effect scene; plus the menu if
  V1 caught it) in `build/gpuspike/` and says whether any difference is visible. Recorded, not a pass
  criterion.
- Section 8 of this spec is filled with the measured numbers and committed with the FINDINGS entry.
- The contract holds.

### The gate

The owner decides A, B, C or D (section 8). V5 onward happens only on A or B. If the spike was built
on the other API than the one chosen, V5 ports it (a week-plus more), keeping the oracle, the seam
and the differentials; if Q-V1 was answered before V3a, no port is needed.

### V5. The backend in `soa.exe`, synchronous

*A day to several days. `--link`. Prerequisites: the gate; V4b. Files: `runtime/gxv.c` and
`runtime/gxv/*.glsl` (from the spike), `tools/recompile.py` (the SPIR-V step, optional),
`runtime/settings.c` (`gpu`), `runtime/main.c` (`SOA_GPU`), `runtime/plat.c` and `runtime/plat.h` (the
`plat_dl_*` trio, if not yet there, 3.10), `tools/soa/toolchain.py` (`runtime_support_sources()`),
`tools/scenario.py` (the sweep's `[gxv]` refusal), `tools/citest/compile_runtime.py` (the headers'
include path), `.github/workflows/ci.yml`
(fetch headers, compile `gxv.c`), `tools/tests/test_gxv_live.py` (new: the log checks), README (the
switch), FINDINGS entry "V5".*

*Done:*
- The contract, with `SOA_GPU` unset.
- **Same session, same replays**: the spike binary and `gen/soa.exe --replay`, both with
  `SOA_GPU=vulkan`, replay each of the 35 and V1's captures, and their PNGs are byte-identical; both
  runs log the driver version. Mutation: a changed shader constant in `soa.exe` makes them differ.
  Each image also passes V0 against its CPU reference.
- **Replays cannot see the GPU**: a test asserts `replay_once`'s child environment has no `SOA_GPU`
  and has `SOA_SETTINGS=0` even when the parent sets `SOA_GPU=vulkan` (mutation: pass `SOA_*` through,
  and it turns red); and `sweep()` records a problem for any replay whose output contains a `[gxv]`
  start line — a canned log with that line is refused (mutation: drop the check, and it turns red).
- **Live runs judged on their own logs**: `python tools/scenario.py run title --check --env
  SOA_GPU=vulkan` passes its invariants **and** its log has the `[gxv] Vulkan … on …` start line, no
  `[gxv] fallback:` line, and an end report whose draw count and screen-copy count are both above zero
  and equal to the `[gx]` report's draw and XFB-copy counts (`python -m pytest
  tools/tests/test_gxv_live.py` checks a given log). Mutation: with `SOA_GPU_LOADER=nonexistent.dll`
  this log check fails while plain `title --check` passes on the CPU renderer.
- `python tools/citest/compile_runtime.py` compiles `gxv.c` in CI; a build without `vendor/` glslang
  links `soa.exe` without the backend and `SOA_GPU=vulkan` prints the fetch instruction.

### V6a. The consumer thread: draws

*Several days to week-plus. `--link`. Prerequisites: V5. Files: `runtime/gxr.c` (starting the
consumer instead of the pool, `g_workers = 1`, `finish` retired), `runtime/gxv.c`,
`config/scenarios/partl.scn` (new: H1's Part L run, PLAN-60FPS-MODS.md:157, card by `--env
SOA_CARD=`), `tools/tests/test_gxv_queue.py` (new), FINDINGS.*

- 3.7: the consumer on its own thread, per-frame upload rings with 3.2's append-only rule, textures
  by `(tex_id, tex_gen)`, the screen copy read back into `g_screen`, idle waits as H11's.

*Done:*
- V5's same-session replay contrast still byte-identical.
- `python -m pytest tools/tests/test_gxv_queue.py`: a synthetic stream that frees and reuses a
  texture slot and fills the vertex arena twice in one frame renders identically at every run and
  equal to the synchronous V5 path; a mutation that counts a command before uploading its vertices
  fails it, and so does one that rewrites a slot's pool allocation in place (under
  `SOA_GXR_STALL`-style delays on the consumer). On the owner's machine `-rs` reports 0 skipped.
- **Budget, one live run**: `python tools/scenario.py run partl --frames 3000 --env SOA_CARD=<a copy of
  build/savetest/card-partL.raw> --env SOA_GPU=vulkan`, reading the `[gxv]` end report: consumer CPU
  per frame p99 ≤ 5 ms and GPU per frame p99 ≤ 8 ms at 1× (limits set here, not measured), with the
  log checks of V5.
- Measured, interleaved, not a gate: frames a second and CPU cores used, against the CPU renderer.

### V6b. The consumer thread: copies, hazards and the frame gate

*Several days. `--link`. Prerequisites: V6a. Files: as V6a, plus `tools/tests/test_gxr_overlap.py`
cases run with the GPU.*

*Done:*
- The overlap test's hazard cases (a texture, a palette and indexed vertex colours read from copy
  destinations; a copy written twice; a `GXDrawDone`) pass with the GPU consumer, the one-worker CPU
  run as their oracle; a mutation that counts a copy before its readback lands fails them.
- `python tools/scenario.py run title --check --env SOA_GPU=vulkan` and
  `python tools/scenario.py run battle --check --env SOA_GPU=vulkan` pass their four invariants **and**
  V5's log checks (start line, no fallback, draw and screen-copy counts above zero and equal to the
  `[gx]` report's), via `tools/tests/test_gxv_live.py`.
- **Owner**: fifteen minutes windowed from a part-select save, `SOA_GPU=vulkan`; anything that looks
  wrong is noted with its frame (`SOA_PAD_RECORD` on).

### V7. GPU copy images, deferred readback, specialised pipelines

*Several days to week-plus. `--link`. Prerequisites: V6b. Files: `runtime/gxv.c`,
`runtime/gxv/*.glsl`, `runtime/gxr_tev.c` (the `copy_image` flag honoured), `runtime/gxr.c` (the
"landed" count), `tools/tests/test_gxv_copyimage.py` (new), FINDINGS entry "V7".*

- Copy images in the pool (a same-frame sampler reads the GPU's image, as on the CPU since H14 step 6);
  RAM landing behind its own count, waited for only where 3.6 requires; specialization constants
  keyed on the TEV **shape** only (3.4); a pipeline cache on disk under `build/`.

*Done:*
- V5's same-session replay contrast still byte-identical with specialisation on and off.
- `python -m pytest tools/tests/test_gxv_copyimage.py`: a synthetic copy sampled in the same frame
  reads the GPU image (the count of samplers served by a copy image printed, above zero); a copy
  image uploaded from the CPU buffer (the mutation) gives a different image. On the owner's machine
  `-rs` reports 0 skipped.
- In one `partl` run, the `[gxv]` report's readback waits are fewer than its copies to texture (both
  printed, copies above zero). The mutation that waits for every copy's landing at the copy, as V6
  did, makes them equal. The figure against V6 goes in FINDINGS, interleaved, and is not a gate. The
  count of samplers served by a copy image is above zero on the mask-effect captures.
- The number of pipelines created on `partl` 3000 frames is at most 4 × the number of distinct TEV
  shapes the report prints (a limit set here), which proves values are not keyed.
- **Budget, one live run** crossing at least 20 map loads (a soak from `python tools/soak.py --seed 7
  --warp <map>`, its log's map-load count printed and ≥ 20): the longest single pipeline creation
  ≤ 20 ms (a limit set here, timed around each creation, from the `[gxv]` report), and the number
  created after the first map load reported; a second launch reports pipelines taken from the disk
  cache (above zero).

### V8. Present from the GPU

*Several days to week-plus. `--link`. Prerequisites: V7; H19a landed (the window it presents into);
M8 and P5a, or whichever of them have landed, each with its CPU function as the reference. Files:
`runtime/window.c`, `runtime/gxv.c`, `runtime/gxv/present.glsl`, `runtime/gxv/overlay.glsl` (if M8
landed), `runtime/gxv/filters.glsl` (if P5a landed), `tools/tests/test_gxv_present.py` (new).
**Owner:** a windowed session at 60 or 120 Hz.*

- A Vulkan swap chain on the window with H8's hold-two-refreshes pacing; M8's overlay, H19a's scaler
  and P5a's filters as shaders, their CPU functions the reference; `SOA_PRESENTER` keeps its fallbacks.

*Done:*
- `python -m pytest tools/tests/test_gxv_present.py`: for each shader filter, a synthetic image
  through the shader equals the CPU function within 1 per channel (an invariant; a changed
  coefficient is the mutation).
- H8's present-interval histogram, from one windowed run (`python tools/scenario.py run window --env
  SOA_GPU=vulkan`), meets H8's target.
- A capture taken after presentation with the overlay open is opened; `g_screen` is unchanged by the
  overlay, checked in the same run, with the mutation that draws into it failing.

### V9. Internal resolution and a wide EFB

*Week-plus. `--link`. Prerequisites: V8; M10 landed (the wide mode is M10 on the GPU). Files:
`runtime/gxv.c`, `runtime/gxv/*.glsl`, `runtime/settings.c` (`gpu_scale`), `tools/gpuspike.py`
(`oracle --scale`), `tools/imgdiff.py` (`--sample centre`), FINDINGS entry "V9". **Owner:** judges it.*

- `SOA_GPU_SCALE` 2 and 3: EFB, copies and their filters scaled; RAM readbacks and `g_screen`
  resampled to native size; texel footprints follow the scale; copy images stay scaled in the pool
  and are sampled with texcoords normalised by the game's declared size (3.13). The wide mode: EFB
  854×480 for perspective draws, orthographic HUD placed as M10 places it.

*Done:*
- With scale 1, V5's same-session contrast still byte-identical.
- With scale 3, the oracle takes **the centre sample of each 3×3 block** (co-located with the native
  pixel centre) and it passes V0 against the CPU reference with the same thresholds, under 3.12's
  failure classification — including a mask-effect capture. With scale 2, which has no co-located
  sample, the oracle judges **MAE and bias only** (within V0's limits), and the owner's look decides
  the rest; the Done line says so. The box-downsampled image is for display only.
- The full-size images are opened.
- **Owner** judges 2×, 3× and wide in a window, and names anything wrong.

### V10. Logic ops without `logicOp`

*A day to several days. `--link`. Prerequisites: V5. Files: `runtime/gxv.c`,
`runtime/gxv/logicop.glsl`, `tools/tests/test_gxv_logicop.py` (new), FINDINGS entry "V10".*

- Where the device lacks `logicOp`: `snapshot` for a logic draw that is one quad (every logic draw in
  this game); for a draw that may overlap itself, fragment-shader interlock where present, else
  framebuffer fetch with rasterization-order access where present; otherwise `blend`, with a
  once-a-run line naming the draw, since the approximation is exact only for mask operands.
  `SOA_GPU_LOGICOP` forces any of them for testing.

*Done:*
- On the Z1E's GPU, `SOA_GPU_LOGICOP=blend` and `=snapshot` give images identical to `native` on the 14
  mask-effect captures and V1's (a same-replay contrast).
- `SOA_GPU_FEATURES=core` gives the same V0 verdicts as the default over the 35 and V1's captures (the
  Android capability set, tested on the Z1E's GPU).
- `python -m pytest tools/tests/test_gxv_logicop.py`: a synthetic OR of 0x55 into 0xAA: `snapshot`
  gives 0xFF, and forced `blend` gives 198 (the test demands both, so it proves the modes differ where
  they should). A synthetic self-overlapping strip under a logic op is routed to interlock (present on
  the Z1E's GPU), or logged, never silently to `blend`.

### V11. The copy-read census (optional, for phones)

*Several days. `--link`. Prerequisites: V6b. Files: `runtime/gxv.c`, `runtime/gxr.c` (the page
protection after a copy lands), `runtime/hostprof.c` or wherever `SOA_HOSTPROF` resolves addresses,
`tools/tests/test_copy_census.py` (new), FINDINGS entry "V11".*

- After a copy's bytes land, the destination pages are protected; the first guest read of each is
  logged with the translated function (through dbghelp, as `SOA_HOSTPROF` resolves addresses) and the
  page released. A destination proven unread over a soak may skip its readback.

*Done:*
- `python -m pytest tools/tests/test_copy_census.py`: a synthetic guest read of a copy destination is
  logged with its function (the mutation: the protection off, and the log is empty).
- One accelerated soak (S3) through menus, battles and map changes (`python tools/soak.py --seed 7
  --battle --encounter-every 600`, run with `SOA_GPU=vulkan`): the list of destinations read, and
  which copies may skip readback. FINDINGS says which were never exercised.

### V12. H17 on the GPU

*Several days. `--link`. Prerequisites: H17a (its per-command EFB routing through `DrawCmd.efb`), V7.
Files: `runtime/gxv.c`, `runtime/gxv/*.glsl`, `tools/tests/test_gxv_interp.py` (new), FINDINGS
entry "V12".*

- The GPU backend selects the second render target for commands with `efb == 1`.

*Done:*
- H17a's same-run check (each real frame's `g_screen` equal before and after its in-between pass) holds
  with `SOA_GPU=vulkan`, with its mutation.
- The in-between images of H10's five pairs, rendered on the GPU, pass V0 against the CPU's in-between
  images (`python tools/gpuspike.py oracle --pairs`).
- **Budget, one live run** (`partl`, 3000 frames, `SOA_INTERP=1 SOA_GPU=vulkan`), reading the `[gxv]`
  report: GPU time per in-between image p99 ≤ 4 ms at 1× (a limit set here).

---

## 7. Open questions

**For the owner.**
- **Q-V1. Is Android a firm goal?** Yes: Vulkan (A). No: Direct3D 11 (B) is simpler on Windows and the
  Deck. This is the question everything else waits on; answered before V3a starts, it also picks the
  spike's API, so nothing is built twice.
- **Q-V2. Do you want 2×/3× resolution and unsqueezed widescreen?** They are most of V8–V9.
- **Q-V3. May the build fetch Vulkan-Headers and glslang** (pinned, into `vendor/`, like the Metrowerks
  compilers), reopening SPEC §10's "no shader compiler" for an optional build step?
- **Q-V4. Do you accept a tolerance-judged GPU picture,** with the CPU renderer kept as the pinned
  reference and fallback?
- **Q-V5. May the implementation session spend about three to four weeks of evenings on V0–V4**
  before you decide, after the comfort pack's milestone 1 or interleaved with it?
- **Q-V6. Do you have Dolphin**, and would you compare one scene with the port for C5 — a character
  standing in sunlight (the mask effect's likely shadows), and a menu over a field?

**For the implementation session.**
- **C5a first?** (Answered: C5a ran first, ../PLAN-NEXT.md C1, with `SOA_GX_DLLOG` as specified, and
  landed as 750cef0.) It changes what every future capture holds; V1 and any re-bless should follow it.
- **The zero-worker path.** It is unexercised on Windows today (gxr.c:2016-2025). Besides copy images
  and `gxr_presented`, what else assumes `g_workers > 0`?
- **`gxr_cmd.h`.** Moving `DrawCmd`, `PixelCfg`, `RasterCfg` and `Rect` out of gxr.c, adding
  `DrawCmd.efb` and `tex_id`/`tex_gen`/`copy_image` to `TexCfg`: acceptable after L0 and L2, before
  H17a? (Answered, ../PLAN-NEXT.md D6: after H17a, which adds `DrawCmd.efb`; V2 moves it.)
- **H17a's routing.** Agree now that the in-between image is chosen per command by `DrawCmd.efb`, set
  by `claim_slot` from a producer-only `g_target`, so H17a and V12 build one thing. (Answered,
  ../PLAN-NEXT.md D6: yes, in the H17a spec.)
- **Which frames reach `fn_80226D14` and `fn_800AF8F8`.** V1 searches by capture; do you already know
  a pad recipe for the camp menu and a battle transition?
- **Why are both mask copy destinations 0x00** at end of frame in 15200, 15800, 16300 and the perfset
  pairs' second frames (`field/5001`, `cutscene/4501`), when the same stream in 1550, 4500, 4800,
  6000, 6300 leaves 0xFF at the second? A capture taken with rendering off would explain the three
  corpus ones [I]; it would not explain a pair's second frame. It matters for 3.12's poison step and
  for what those frames' RAM can be trusted to hold.
- **CI.** Fetching Vulkan-Headers in the native job is small; is glslang's 14 MB release zip
  acceptable there too, or should CI compile `gxv.c` against a stub SPIR-V header?

---

## 8. The decision

**What you will be choosing between** (the numbers in brackets are filled by V4b):

- **A. Build the Vulkan backend.** About 4–6 weeks of evenings to a live GPU renderer at native
  resolution with the CPU's picture within tolerance (V5–V7), then 4–6 more for GPU presentation,
  2×/3× resolution, widescreen and the Android fallbacks (V8–V10, V12). Android itself needs the
  portability track's L7–L12 on top. Worth it if Android or higher resolution matters.
- **B. Build a Direct3D 11 backend.** About the same size, fewer moving parts, Windows and the Deck
  only.
- **C. Not now.** The CPU renderer continues. H15d and H16 resume at single-digit gains a step; 60 fps
  through H17 where the CPU keeps up (the field captures meet the budget; ship and sky are 1.3–1.6×
  short). No Android, no higher resolution. The oracle and the seam stay.
- **D. Not ever.** C, and PLAN says so, so nobody reopens it without new facts.

**What the spike adds that you do not have today:**
- whether the GPU's frames agree with the CPU's, capture by capture, under a checker proven able to
  fail [V4a/V4b verdicts];
- that the TEV arithmetic and the copy encoder are exact on the GPU [V3b];
- whether the logic-op fallbacks are exact for this game, which decides the older Android phones
  [V4b's contrast], and whether the Android capability set (`SOA_GPU_FEATURES=core`) gives the same
  verdicts [V4a];
- whether the menu copies Dolphin needed RAM for render right [V4b's `chain` replays of V1's
  consecutive captures];
- GPU milliseconds a frame on your Z1 Extreme's GPU against today's CPU cost [V4a], which bounds
  60 fps, 2× and 3×;
- a list of what the spike found missing from `DrawCmd`, if anything.

**What it cannot tell you:** live frame rate with the game running, presentation and pacing,
long-run stability, device loss, any Android driver's behaviour, or energy use.

**My recommendation.** Answer Q-V1 now. C5a has confirmed the display-list chain (750cef0), so C5b and
C5c come first; then run V0 and V1 (they touch no renderer code) and V2–V4 after the comfort pack's
milestone 1. Decide A, B, C or D on V4b's numbers. [../PLAN-NEXT.md](../PLAN-NEXT.md) orders V0–V4 as
its M5, after M2, M3 and M4a; its D-10 (b) moves M5 to follow M2. If Android is not a goal and higher
resolution is not wanted, C is a respectable answer: the port already runs the heaviest field at the
game's own 30 fps.

---

## 9. Sources

- In the tree: `runtime/gx.c`, `gxr.c`, `gxr.h`, `gxr_tev.c`, `window.c`, `main.c`, `selftest.c`,
  `settings.c` at c8274db (identical at HEAD b071949); `tools/guard.py` and `tools/scenario.py` at
  HEAD; `docs/ARCHITECTURE.md` §6–12 (:78, :513-517); `docs/PLAN.md:954-958`;
  `docs/PLAN-60FPS-MODS.md` (H15d, H16, H17 status lines at cb469d6; :157, :371-381, :567, :591);
  `docs/FINDINGS.md` "H4" (:1686-1687), "H5", "H14", "H15c", "H15d paused", "Palette loads";
  `docs/research/port-performance.md` §4, `android-and-native.md` §4 and §7; `docs/specs/now.md`;
  portability.md and comfort-pack.md (L0, L2, L7; H19a, P5a, P5b, M11a-skip); ../PLAN-NEXT.md for the
  order.
- Scratch analysis (not committed): `tools/fifo.py` decodes and walks of the 35 captures; reads of
  the mask captures' RAM images; call and r13-relative reference scans of the DOL; the gpuinfo JSON.
- Web, 2026-09-25: [Dolphin GEA.ini](https://github.com/dolphin-emu/dolphin/blob/master/Data/Sys/GameSettings/GEA.ini);
  [Dolphin forum, Skies of Arcadia Legends](https://forums.dolphin-emu.org/Thread-gc-skies-of-arcadia-legends--26018?page=4);
  [Dolphin wiki and its testing notes](https://wiki.dolphin-emu.org/index.php?title=Skies_of_Arcadia_Legends);
  [Dolphin RenderState.cpp](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/VideoCommon/RenderState.cpp)
  (its logic-op-by-blending table);
  [Dolphin DXTexture.cpp](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/VideoBackends/D3D/DXTexture.cpp)
  (the integer RTV for logic ops);
  [gpuinfo.org core 1.0 feature coverage, Android](https://vulkan.gpuinfo.org/listfeaturescore10.php?platform=android);
  [gpuinfo.org logicOp devices, Android](https://vulkan.gpuinfo.org/listdevicescoverage.php?feature=logicOp&platform=android);
  [SDL issue #12652](https://github.com/libsdl-org/SDL/issues/12652);
  [SDL_gpu.h](https://github.com/libsdl-org/SDL/blob/main/include/SDL3/SDL_gpu.h);
  [D3D11_RENDER_TARGET_BLEND_DESC1](https://learn.microsoft.com/en-us/windows/win32/api/d3d11_1/ns-d3d11_1-d3d11_render_target_blend_desc1);
  [glslang releases](https://github.com/KhronosGroup/glslang/releases);
  [Vulkan-Headers tags](https://github.com/KhronosGroup/Vulkan-Headers/tags).

---

## 10. Review log

Two reviewers' 45 points, each checked against the tree, the captures, the DOL or the web on
2026-09-25 before acting. Numbered in the order they were received.

**Applied.**
1. *Clip distances and depth clamp required, against 39% of Android lacking them* — confirmed
   (gpuinfo 60.78% / 91.2%; SDL #12652). Applied in a stronger form: CPU clipping in the consumer with
   `vertex_unclipped`/`clip_polygon` is the **only** clip path (exact vertices everywhere), and depth
   travels as a `noperspective` varying with `gl_Position.z = 0.5·w`, so neither feature is used
   (3.3, 3.10). The coverage figures are in 2.5; V10's Done gained the `SOA_GPU_FEATURES=core` line.
   The reviewer's CPU clip alone would still have let the GPU's own 0..w depth clip cut pixels without
   `depthClamp`; the depth varying closes that.
2. and 27. *The logic-op mutation "OR as plain addition" cannot fail* — confirmed (one operand is 0 or
   255 per channel). Replaced by mutations that change the operation (AND as copy, ORs as copies, OR
   as AND), each with a printed nonzero count and a V0 failure on all 14; 3.5 now says why.
3. *The display-list observation is already in FINDINGS H4* — confirmed (FINDINGS.md:1686-1687,
   ARCHITECTURE.md:513-517, H5). 2.8 and "Said plainly" now credit H4 and say what is new; C5a/C5b
   list the documents they amend.
4. *Evidence understated* — partly confirmed, and applied with a correction. The stream walk holds on
   all 12 distinct mask frames (only size-0 calls between the first OR's quad and the second copy);
   the `NGDL` body at 0x804EB7A0 is all zero in every mask capture's RAM; but the second destination is
   uniformly 0xFF in only 7 of the 12 (1550, 4500, 4800, 6000, 6300, `field/5000`, `cutscene/4500`) —
   in 15200, 15800, 16300 and the pairs' second frames both destinations are 0x00, which is now an open
   question (section 7). 2.8 is [V] at the stream level; the shadow consequence stays [I]; the 8
   pinned hashes are in 2.8 and section 5; Q-V6 is a character in sunlight.
5. *C5 changes H10's pair key* — confirmed (gxr.c:2100-2106, 2162-2167; gx.c:361). New risk in
   section 5, a re-measure line in C5b's Done, and a note in 3.13.
6. and 26. *The no-worker hook sits on dead code* — confirmed (gxr.c:2008, 2016-2025, 2035). V2 adds
   `SOA_GXR_INLINE=1` (not `SOA_THREADS=0`, which means "default" today and is fed by `soa.ini`'s
   `threads` key, settings.c:43), `replay --threads inline,…`, and the passthrough backend replaying
   the 23 captures. One change to point 26: its mutation "the passthrough drops kind 2 and a hash
   moves" cannot fail on a one-frame replay (the only clears follow the screen copy), so kind 2 is
   covered by the synthetic stream and the corpus mutation skips blended draws instead.
7. *Sampling is not exact but for level choice* — confirmed (gxr.c:1232, 1252; gxr_tev.c:1170-1171).
   3.4 and section 4 reworded as proposed.
8. *The GXDrawDone inference contradicts H14* — confirmed; 2.3 rewritten. The log count is now 67
   (the reviewer's 66 was one short at re-count time), with the command that counts it.
9. *guard.py citation* — confirmed; now guard.py:73-96 at HEAD (it was :70-87 at c8274db).
10. *Sources said cb469d6* — confirmed; section 9 says c8274db (identical at HEAD) and keeps
    cb469d6 only for the PLAN-60FPS-MODS status lines.
11. *The 15 references overclaim; "nine callers"* — confirmed (0x80347FEC is walked by
    `fn_802AC31C`; 9 sites, `fn_80101828` twice). Reworded with the addresses.
12. *Two captures are copies* — confirmed by `cmp`. "35 files, 33 distinct frames" and "14 (12
    distinct)" throughout; the draw count is also given over distinct frames (61,749).
13. *Framebuffer fetch cannot order a self-overlapping draw on the Z1E's GPU* — confirmed from the
    scratch vulkaninfo; 3.5 item 4 and V10 reroute to interlock.
14. *Fog's `exp2` bound* — confirmed; the (3 + 2|x|)-ULP bound is stated. The optional table is
    specified as a table of `fi`'s step thresholds, which is exact given the same `f`; a table of
    `exp2` values over 257 points would not be exact for arbitrary `f`.
15. *"33 setups" is shapes, not contents* — applied: shapes are a table and the specialisation key;
    values go in the per-draw record (3.2, 3.4, V7 with a pipeline-count limit).
16. *glslang date and size* — confirmed via the GitHub API (2026-09-11, 13.7 MB); applied.
17. *Palette figure* — confirmed ("Decoding falls 79-93%"); applied.
18. *GEA.ini quoted selectively* — confirmed (`CPUThread = False`, `SafeTextureCacheColorSamples =
    512`); all three quoted in 2.3, the single-core risk added to section 5, the wiki's testing notes
    cited in 2.3 and 2.8.
19. *V9's box downsample fails by construction* — applied: centre sample at 3×, MAE and bias only at
    2×, box image for display.
20. *Pool slot reuse within a frame* — confirmed (1,024 slots, in-frame eviction); append-only
    allocation per `(tex_id, tex_gen)`, reset only after the frame's fence (3.2), with a V6a mutation.
21. *"The 780M"* — confirmed (device 0x15BF, the Z1 Extreme); named once in 2.4 and "the Z1E's GPU"
    elsewhere.
22. *The gpuinfo table cannot be checked* — confirmed; the endpoint, the per-device-name rule, the
    totals (1,303 / 2,402) and the site's 52.46% are given, and the left-out families (Adreno 4xx–5xx,
    Huawei, the rest) are now rows, recounted from the fetched JSON.
23. *Replays start from RAM that already holds the copies* — confirmed (gx.c:56-59, 151-154,
    537-575). The poison step and `chain` are in 3.12 and V4b; `chain` excludes ranges N+1 copies into
    itself, which the proposal did not; V1 keeps consecutive frames.
24. *`target()` as a backend state switch* — confirmed as unworkable with an asynchronous consumer;
    replaced by `DrawCmd.efb` set in `claim_slot`, with V2's Done and mutation; section 7 reworded.
25. *A copy's fused clear* — confirmed (gxr.c:2662, 3062, 2640). With a backend set the clear is
    always a kind 2; V2's synthetic stream adds the unfiltered full-scale copy and its mutation.
28. *V5's replay refusal is dead code* — confirmed (scenario.py:964-967); replaced by the environment
    test and the sweep's `[gxv]` refusal, and V0's `refs` sanitises the same way.
29. *GPU live runs pass vacuously on fallback* — applied: every GPU live run also checks its own log
    (start line, no fallback, counts equal to `[gx]`'s), with the loader mutation.
30. *V4a/V9 Done lines can pass vacuously* — applied: by-design versus defect classification, the
    "applies" rule (≥ 0.5% of pixels, ≥ 5 captures), in 3.12, V4a, V4b and V9.
31. *Copy write-back, half scale, refused formats* — confirmed (gxr.c:2522, 2536-2540, 2566,
    2688-2692); seeding from RAM, "box, no filter", "refused, RAM untouched", random destinations, R4
    odd widths and the whole-buffer mutation applied.
32. *64-byte per-draw record; pool rules* — confirmed (TexCfg, gxr.h:104-114); three tables, about
    0.5 KB a draw, the copy-image flag, cap = min(128 MB, `maxStorageBufferRange`), mid-frame run-out
    handled.
33. *Position invariance* — applied (`invariant gl_Position`, `precise` depth; a V4a synthetic check).
34. *V3 too large; spike total* — applied: V3a/V3b, V4a "several days to week-plus", "three to four
    weeks" in sections 1, 5, 7 and 8.
35. *V3–V4 are Vulkan-only while Q-V1 may say no* — applied: V3′/V4′ on D3D11, with the blend-off and
    UINT-view facts confirmed on Microsoft Learn and in Dolphin's DXTexture.cpp.
36. *V7–V12 lack Files lines and budget commands* — applied. There is no scenario for H1's Part L
    run, so V6a adds `config/scenarios/partl.scn` and the budgets name it.
37. *C5 is three commits* — applied: C5a (confirm, with `SOA_GX_DLLOG`), C5b (fix, report line,
    H10 re-measure), C5c (re-capture and first bless, owner).
38. *V5 compared against numbers from weeks earlier* — applied: a same-session byte-identical
    contrast between the spike and `soa.exe`, both logging the driver.
39. *Benchmark references uninspected; not same-session; environment* — applied in V0 (opened once),
    V4a (regenerated by the spike's CPU path, equal byte for byte) and 3.12 (sanitised).
40. *`tevdiff`'s random setups* — confirmed (gxr_tev.c:1342 onward); setups built by `tev_prepare`
    from random BP words, both fast and general paths, per-path counts ≥ 100.
41. *Skips satisfy the Done* — applied: `-rs` reports 0 skipped on the owner's machine, for every GPU
    test module.
42. *V8/V9 prerequisites* — confirmed (M8 and M10 have no done status); applied, with 3.13's scaled
    copy images and V9's mask-capture line.
43. *`finish()` and `g_frames_presented`* — confirmed (gxr.c:2581, 2664, 2778-2782); the rules are in
    3.1 and 3.7.
44. *Lines, points and cull mode 3* — confirmed (gxr.c:1134, 1461-1485); mapped, logged, and in
    V3a's selftest.
45. *Order against P5b/M11a-skip; row D* — applied in section 6's order and section 1's table.

**Rejected.** None outright. Four were applied with a change, each explained above: 1 (stronger
form: no clip distance path at all, plus the depth varying), 4 (the 0xFF evidence holds in 7 of the
12 frames, not all), 14 (a threshold table, since a value table is not exact), and 26 (the kind-2
mutation cannot fail on a one-frame replay, so it lives in the synthetic stream).

**Consistency review, 2026-09-25, at 012164a.** A check across the five planning documents and against the
repository, with the implementation session's facts from after the drafts:
- **V2 comes after H17a.** Section 6, 3.1, V2's prerequisites and What, section 5 and section 7 now agree
  with ../PLAN-NEXT.md (M5, D6): H17a adds `DrawCmd.efb` and its `claim_slot` routing, and V2 moves them
  into `gxr_cmd.h` unchanged. V12, not H17a, is what builds on the seam.
- **H18 is not held by the gate.** Sections 1 and 2.7 no longer defer H18 with H15d and H16; it follows
  H17b (../PLAN-NEXT.md A4, D-24).
- **`plat_dl_*`.** 3.10 no longer says they arrive with L7: they arrive with their first caller, and V5
  creates `runtime/plat.c` with them if neither L7 nor L9 has (V5's files gain it and `toolchain.py`).
- **V0 after C5c.** V0's perfset-copy line could pass only before C5c, while the plan ordered V0 after it.
  V0 now needs C5c or a refuted C5a, and its Done covers both; V1 needs C5b only for the capture with
  casters. 2.2 says its distinct-frame counts are pre-C5c and are re-counted by the slices that use them.
- **Rule 7.** V7's Done compared readback waits between two live runs; it is now a same-run relation with
  a mutation. V2's perfbench figure had a ±2% band inside the noise; it is now reported only, with codegen
  compared first and a saved base exe, as portability.md does.
- **C5a has landed** (750cef0), the first slice of ../PLAN-NEXT.md's M1. Its FINDINGS entry reports the
  chain confirmed and names two things C5b must handle, a redirect that is not a list and recordings
  that outnumber calls; C5b says its rule is restated from that entry before it starts. The header gives
  the shift C5a's log made in `gx.c`'s line numbers.
- **Sizes.** Section 5 gave V2 as "a day or two" against its slice's "a day to several days"; it now says
  the latter. Section 8's recommendation notes ../PLAN-NEXT.md's order and D-10.
