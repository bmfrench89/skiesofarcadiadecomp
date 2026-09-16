# Disc Analysis — Findings

**Subject:** Skies of Arcadia Legends (USA), GameCube, game ID `GEAE8P`
**Method:** direct decode of an RVZ container; no emulator involved
**Revision:** v2 — figures marked ▲ were corrected after adversarial review

Everything here is structural metadata about the executable — addresses, sizes,
instruction counts, format headers. No game content is reproduced or stored in this
repository.

---

## 1. Container and disc

The source image is an RVZ (Dolphin's compressed disc format), decoded from scratch rather
than converted with an external tool, so the pipeline has no dependency on a Dolphin
install.

| Field | Value |
|---|---|
| Container | RVZ v1, zstd level 19, 128 KiB chunks, 11,139 groups |
| Disc type | 1 (GameCube) — no Wii partition encryption layer |
| Uncompressed size | 1,459,978,240 bytes (1.360 GiB), single layer |
| Compressed size | 1,285,948,056 bytes |
| Game ID | `GEAE8P` — `G`=GameCube, `EA`=Eternal Arcadia, `E`=USA, `8P`=Sega |
| Magic word | `0xC2339F3D` (valid) |
| Apploader | dated 2002-09-05 |

### RVZ format notes

Two details cost real time and are worth recording:

1. **The first 0x80 bytes of the disc live in the RVZ header**, not the group stream. The
   single raw-data entry has `base = 0x80`, but groups tile from
   `align_down(base, chunk_size)` = 0. Treating `base` as the group origin yields garbage.
2. **Junk runs carry a 68-byte seed** (17 × u32 — a lagged Fibonacci generator state), not
   4 bytes. Brute-forcing seed size against "does the chunk decode to exactly 131,072
   bytes" identified it unambiguously.

Junk runs are regenerated (slice 0.5): the seed's 17 words feed a 521-word lagged
Fibonacci generator with lag 32, shifted and byte-swapped once at initialisation and
advanced four times, then forwarded by the run's disc offset modulo the 32 KiB sector.
GameCube games routinely read past a file's declared end, and `disc.iso` now returns
there what the drive returns. Two checks on the real image: every run within one 32 KiB
sector carries the identical seed (68 sectors with several runs, no exceptions), so the
seed is the sector's and the forward-by-offset step is right; and 22 runs span a sector
boundary, so the generator must keep running across one rather than re-seed.

---

## 2. Filesystem

| | |
|---|---|
| FST offset / size | `0x00323E00` / 134,426 bytes |
| Entries | 5,560 (5,552 files, 7 directories) |
| Total file bytes | 1,418,037,369 |
| ▲ Decompressed bytes | **2,126,196,876 (1.98 GiB)** |

Directories: `battle`, `bchara`, `beff`, `ending`, `field`, `sound`, `title`

### ▲ Compression — the finding that invalidated the original method

**3,633 of 5,552 files (65%) are wrapped in a Sega container with magic `AKLZ~?Qd`**,
whose body is Okumura LZSS. v1 did not know this, which means v1's "no `.rel` files on the
disc, therefore no runtime-loaded code" argument was inspecting compressed bytes and could
not have proved anything either way.

`tools/validate_assets.py` now runs an exhaustive gate over every file:

```
AKLZ containers   3,633 of 5,552
decoded bytes     2,126,196,876 (1.98 GiB)
decode failures   0
files w/ PPC code 0
```

Every container decodes to exactly its declared size, and no decompressed payload contains
PowerPC code.

### ▲ Asset formats

v1's table listed `.gvr | 3 files` and treated Sega textures as a footnote. That framing
was badly wrong — three GVR files happen to be *loose*; the disc holds roughly a hundred
thousand of them inside containers.

| Format | Scale |
|---|---|
| `NMLD` (`.mld`) container | 1,791 files, 1,069 MB |
| GVR textures | ≈100,000 (CMPR 62%, INDEX4 22%, RGB5A3 16%, ARGB8888 0.1%) |
| Ninja `NJCM` models / `NJTL` texture lists | ≈23,000 — Dreamcast lineage |
| `AFNT` font | `FontData.US`, 83 KB |
| `.sct` scripts | 258 files — **the engine is script-VM driven** |
| DSPADPCM audio | 620 `.dsp`, 590 `.samp` |
| Nintendo `.tpl` | 2 files |

The `NJCM`/`NJTL`/`GVRT`/`GCIX` magic constants appear in `boot.dol` itself, confirming
the Dreamcast Ninja lineage in the engine rather than just the data.

**None of this is on the critical path** — see [SPEC.md](SPEC.md) §9 for why that is a
decision rather than an oversight.

**No `.rel`, `.map`, or `.elf` files anywhere on the disc.**

---

## 3. Executable

`boot.dol` at disc offset `0x0001EC00`, 3,166,656 bytes, entry `0x80003140`,
BSS `0x80302A00` + 305,860 bytes. Total RAM footprint 3.3 MiB of 24 MiB MEM1.

| Section | File offset | Virtual address | Size | dtk name |
|---|---|---|---:|---|
| `.text0` | `0x000100` | `0x80003100` | 9,472 | init / vectors |
| `.text1` | `0x002600` | `0x80005600` | 2,781,664 | `.text` |
| `.data0` | `0x2A97E0` | `0x802AC7E0` | 32 | `.ctors` |
| `.data1` | `0x2A9800` | `0x802AC800` | 32 | `.dtors` |
| `.data2` | `0x2A9820` | `0x802AC820` | 189,856 | `.rodata` |
| `.data3` | `0x2D7DC0` | `0x802DADC0` | 162,880 | `.data` |
| `.data4` | `0x2FFA00` | `0x80346720` | 864 | `.sdata` |
| `.data5` | `0x2FFD60` | `0x80348000` | 21,600 | `.sdata2` |

▲ **`.text0` is not ordinary code.** It is a ROM image the boot path `memcpy`s into low
memory; its instructions are position-dependent exception vectors interleaved with
embedded strings and zero padding.

▲ **Small-data bases:** `r2 = 0x80350000` (SDA2), `r13 = 0x8034E720` (SDA). mwcc addresses
most globals relative to these, and also through per-translation-unit pooled base
registers — so address analysis needs CFG-aware constant propagation, not peephole
`lis`/`addi` matching.

### Out of scope: the apploader

▲ The disc carries **116,484 bytes of real PowerPC code** in Nintendo's apploader at disc
offset `0x2440`, which is not in the FST and was overlooked in v1. It exists to load the
DOL off a physical disc; a native port replaces it wholesale.

### Toolchain fingerprint

Twelve `<< Dolphin SDK - MODULE release build: ... >>` strings, all stamped
**2002-09-05, version `0x2301`**, plus `Metrowerks Target Resident Kernel for PowerPC`.

**No MusyX.** Audio runs on a custom Sega engine sitting directly on the SDK's `AI`, `AR`
(ARAM) and `DSP` layers.

### ▲ DSP microcode: stock, not custom

This was the open question that could have doubled the project, and it is closed.

Only **three DSP microcode blobs exist in the entire image**, which is provable rather than
merely observed: there are only three code paths that can ever boot a ucode, and all three
hand the DSP a hardcoded `.data` address.

| Address | Size | Identity | Dolphin `HashEctor` |
|---|---:|---|---|
| `0x802FE3A0` | 6,624 | **stock AX audio ucode** | `0x4E8A8B21` |
| `0x802FB400` | 352 | stock CARD ucode | `0x65D6CC6F` |
| `0x802F9600` | 128 | `UCODE_INIT_AUDIO_SYSTEM` | `0x18712672` |

`0x4E8A8B21` is an exact match for Dolphin's stock AX entry — the same build used by
Melee, Super Monkey Ball, Star Fox Adventures and Mario Party 4. The method was validated
end-to-end with a **positive control**: the CARD blob hashes to Dolphin's CARD constant
byte-for-byte.

A structural scan of all 3,166,656 DOL bytes for the GameCube DSP's 8-entry exception
vector table returns only these three, and the same scan across all 5,556 extracted files
plus 164 MB of decompressed assets returns **zero**.

Sega wrote their own **AX driver** (roughly `0x8027C000`–`0x80292000`), not their own
ucode: it assembles AXPB parameter blocks and command lists by hand and mails them to the
stock AX binary. The CPU never mixes — samples are DMA'd into ARAM via `ARQPostRequest`,
the DSP mixes in 5 ms frames (640-byte blocks at 32 kHz, the textbook AX cadence), and AI
resamples to 48 kHz.

Phase 6.3 is therefore a stock-AX mixer reimplementation, not a GameCube DSP interpreter.

> Correction: an earlier draft reported `__DSP_boot_task` referenced five times. That count
> belonged to `__DSP_debug_printf` (7 references), which compiles to an empty stub.
> `__DSP_boot_task` has exactly one caller.

---

## 4. Instruction census

Decoded with `tools/soa/ppc/`, which covers the base 32-bit PowerPC user ISA plus all
three extended-opcode field widths that Gekko packs into primary opcode 4.

| | Words | Valid | Coverage |
|---|---:|---:|---:|
| `.text0` | 2,368 | 730 | 30.83% |
| `.text1` | 695,416 | 695,414 | **99.9997%** |
| **Total** | **697,784** | **696,144** | **99.7650%** |

▲ **Real instruction count is 696,120**, not 697,784 — 1,664 words in `.text0` are data.

`.text1`'s two undecodable words are both `0x00000000` padding at section boundaries.

### ▲ Independent cross-validation

The decoder was diffed against two independent disassemblers — capstone 5.0.7 (LLVM-derived)
and dtk 1.8.4 (`ppc750cl`, written from the 750CL manual for this console) — across all
697,784 words plus a synthetic sweep of the encoding space.

**Field extraction was already correct**: 700,624 operand comparisons, zero real mismatches,
covering every branch target, all 18,890 rotate mask triples, all 12,464 SPR numbers, all
5,007 `psq_*` fields and 28,839 A-form register orderings.

**Naming was not.** Six defects were found and fixed; the worst mislabelled **19,306
instructions (2.77% of the binary)** — every single-precision float carried its
double-precision name, and `fadds` rounds where `fadd` does not. Details in the commit log.

Four apparent disagreements were **capstone gaps where we are correct**, since capstone is a
modern PowerPC decoder rather than a 750CL one: `fcmpo` (3,013 instances), `mcrxr`, every
OE form, and the opcode-4 paired-single compares (which it resolves as AltiVec). dtk
arbitrates in our favour on all four.

The whole-image test now passes: every one of the 697,784 words agrees.

dtk independently found **7,117 functions** and only **three** embedded-data words in the
whole of `.text1`, confirming both figures by a separate method. It also reports **no jump
tables in `.text1`** — they live in `.rodata`.

> **Caveat that remains.** "Decodes as a valid instruction" is weaker than it sounds: a table
> of `0x80xxxxxx` pointers decodes cleanly as PowerPC. Long runs and jump tables are now
> ruled out by dtk's independent code/data map, but short float pools remain possible.

### Gekko-specific usage

| Class | Count |
|---|---:|
| Paired-single arithmetic (opcode 4) | 319 |
| `psq_l` / `psq_lu` / `psq_st` / `psq_stu` / `psq_lx` etc. | 5,007 |
| **Total** | **5,326 = 0.76% of code** |

An engine written natively for GameCube is saturated with these. At 0.76% this binary
barely touches the hardware's distinctive features — exactly what an SH-4 codebase ported
to PowerPC looks like. No locked-cache DMA idioms were observed.

▲ **GQR state is statically determinable**, which matters more than the raw count. The
binary installs six constants and never varies them:

```
GQR0 = 0x00000000    GQR1 = 0x08040804    GQR2 = 0x00040004
GQR3 = 0x00050005    GQR4 = 0x00060006    GQR5 = 0x00070007
GQR6, GQR7 unused
```

**97.3% of quantized load/stores (4,872 of 5,007) use GQR0**, which is `f32`/scale-0 — an
ordinary pair of float loads with no conversion at all. Only ~135 sites need a
scale-and-convert helper. The recompiler needs no runtime GQR dispatch.

### Top opcodes

| Opcode | Mnemonic | Count | Share |
|---:|---|---:|---:|
| 14 | `addi` | 108,213 | 15.51% |
| 31 | X-form ALU | 81,539 | 11.69% |
| 32 | `lwz` | 81,025 | 11.61% |
| 18 | `b` / `bl` | 65,785 | 9.43% |
| 16 | `bc` | 57,600 | 8.25% |
| 36 | `stw` | 52,056 | 7.46% |
| 48 | `lfs` | 33,069 | 4.74% |
| 11 | `cmpi` | 22,649 | 3.25% |
| 59 | single-precision FP | 19,308 | 2.77% |
| 21 | `rlwinm` | 18,408 | 2.64% |

Float usage is substantial (~10%) but **scalar throughout**, consistent with the
paired-single count.

### ▲ Function count

| Signal | Count |
|---|---:|
| Unique `bl` targets | 5,375 |
| `stwu r1` prologues | 5,330 |
| `blr` returns | 8,024 |
| **Estimated entry points** | **~7,100–7,160** |

v1 quoted 5,375 as the working figure. That undercounts by ~25%: **1,781 functions are
never `bl`-called**, reached only through function-pointer tables or virtual dispatch, and
431 are leaf functions with no stack frame at all.

This does *not* rescale Phase 3. Codegen volume scales with **instructions**, and that
number went slightly down. Function count affects symbol tables and the dispatch map.

### ▲ Indirect branches — risk R1 drops from High to Low

| Form | Count |
|---|---:|
| `bctr` | 296 — **all 296 are switch tables** |
| `bctrl` | 248 |
| `blrl` | 121 |
| conditional `blr` | 527 |

320 jump tables totalling 5,721 entries were recovered. Only 24 of 544 sites are
vtable-shaped. The target set is closed within `boot.dol`, so **no interpreter fallback is
needed**. One special case: the single `bla 0x60` at `0x80232278`, which is a
to-be-copied exception-stub template rather than an unresolved branch.

### ▲ Self-modifying code

Only **4 `icbi` instructions** exist in 696,120. PowerPC's instruction cache is not
coherent with stores, so runtime-generated code *must* be `icbi`'d before execution. All
four sit in SDK cache primitives whose call sites target fixed low-memory exception
vectors. Seven runtime-codegen sites exist in total, all confined to the MetroTRK debug
stub, which can be stubbed out.

---

## 5. ▲ Hardware access

The single most consequential finding of the review, because it invalidated the graphics
plan (see [SPEC.md](SPEC.md) §7).

| Measure | Count |
|---|---:|
| Stores to `0xCC008000` (GX write-gather pipe) | **1,508**, across **164 functions** |
| Out-of-line GX entry points called from non-SDK code | **104**, via **1,674 call sites** |
| `GXBegin` (`0x8024E478`) call sites | 96 |
| Non-SDK gather-pipe functions that also call `GXBegin` | **84 of 86**, bracketing 98.2% of their stores |
| Direct MMIO register stores outside the SDK block | **0** |

Per-vertex attribute submission *is* inlined, and aggressively — one function copies the
FIFO base into 24 separate GPRs so an unrolled loop can issue back-to-back `stfs` without
dependency stalls. But the GX **API** is not inlined away: every state-setting call remains
an ordinary out-of-line function, and almost every inlined vertex burst is bracketed by a
real `GXBegin` carrying primitive type, format index and vertex count.

So a gather-pipe assembler and a vertex decoder are needed; a command-processor emulator is
not. See [SPEC.md](SPEC.md) §7.

### ▲ A third code layer

`0x80266778`–`0x802AC7E0` — **807 functions, 286,600 bytes, 10.3% of `.text`** — is a
statically-linked rendering middleware library that no earlier analysis had identified,
distinct from both the Nintendo SDK and the game. It contains **868 of the 1,508 FIFO
writes** and calls up into game code only **2 times out of 3,996 outbound calls**.

That near-zero coupling makes it a clean replacement seam rather than something that must
be recompiled.

▲ **Video mode: 480i only.** Three `GXRenderModeObj` records in `.data3` — NTSC_INT,
MPAL_INT, EURGB60_INT — all 640×480, full-height EFB, no progressive entry. The engine is
paced by `VIWaitForRetrace` at 59.94 Hz, which makes VI the main loop rather than a
late-phase detail.

---

## 6. Comparison to completed GameCube decompilations

| Game | Functions | Decomp status |
|---|---:|---|
| **Skies of Arcadia Legends** | **~7,100–7,160** | **0%** |
| Pikmin | 8,069 | 100% |
| Super Mario Strikers | 8,605 | 100% |
| Mario Party 4 | 10,986 | 100% |
| Metroid Prime | 16,685 | 89% |
| Melee | 19,828 | 100% |
| Animal Crossing | 20,288 | 100% |
| Twilight Princess | 48,107 | 100% |

Even at the corrected count, Skies remains smaller than every GameCube title that has been
fully decompiled.

---

## 7. Assessment

**Favourable:**

- **No runtime-loaded code.** Now proven properly: 4 `icbi` all in OS init, a closed call
  graph, no module-loader symbols, and an exhaustive gate over 1.98 GiB of decompressed
  assets finding zero PowerPC code.
- **0.76% Gekko-specific instructions**, with GQR values static — the recompiler
  specialises every quantized access at translation time.
- **Indirect branches are tractable** — all 296 `bctr` are switch tables (R1: Low).
- **Smallest function count** of any fully decompiled GameCube game.
- **Turn-based JRPG** — tolerant of timing imprecision.
- ▲ **The host toolchain is already installed** — MSVC 14.44, Windows SDK 10.0.26100,
  cmake and ninja. v1 wrongly reported these missing.

- ▲ **Stock DSP microcode**, hash-matched against Dolphin's table with a positive control.
  Audio is a mixer reimplementation, not a DSP interpreter.
- ▲ **The GX API survives interception.** 104 out-of-line entry points, 1,674 call sites,
  and 98.2% of inlined vertex bursts bracketed by a real `GXBegin`.
- ▲ **The decoder is independently validated** against two disassemblers, whole-image.
- ▲ **A 10.3% slice of `.text` is replaceable middleware** with near-zero coupling.

**Unfavourable:**

- ▲ **Per-vertex submission is inlined**, so a write-gather pipe and vertex decoder are
  unavoidable — 1,508 stores across 164 functions. Less bad than the v2 review feared, but
  still the largest single piece of runtime work.
- **No symbol map**, and the SDK is only 7.8% of `.text` — so ~6,170 game functions stay
  anonymous. Phase 2's real job is finding the code to *delete*, not to name.
- ▲ **The exception-vector region is self-modifying in effect** — copied to low memory at
  boot and `ICInvalidateRange`'d — so those 15 bodies need pre-translation or detection.
- **Zero prior decomp work.** The one public repo is a single commit from 2025-05-07 with
  no functions decompiled.

**Conclusion:** every risk that could have ended the project has now been measured rather
than assumed. The DSP question closed favourably, the graphics question closed to a hard
but bounded problem, and the decoder is cross-validated. Proceed.


---

## 8. ▲ Runtime: what it took to reach the game loop

Recorded as each blocker fell, because each one is a rule the runtime now
embodies. Log lines quoted are from `build/boot.log`.

| Blocker | Cause | Rule |
|---|---|---|
| Spin on `0xCC005004` before any mail | The DSP ROM announces itself with `0x8071FEED` at power-on and after reset; `__DSP_boot_task` waits for it before uploading | Outgoing mailbox starts non-empty; CSR `RES` re-arms it; clearing `DSPINIT` boots the ARAM stub (`0x80544348`, then the ROM again) |
| Main thread spinning on a flag with interrupts enabled | Interrupts were only delivered at the scheduler's idle loop | Every backward branch polls (`irq_poll`), then runs `__OSReschedule` as `__OSDispatchInterrupt` would |
| `msr=0x32` forever after the first audio frame | The driver's frame callback does `OSEnableInterrupts … OSDisableInterrupts` inside a handler and relies on `rfi` to restore MSR | Handlers run with EE clear and MSR restored afterwards |
| `sprintf` produced its own format string; random traps | Handlers (and the reschedule) clobbered volatile registers of the interrupted loop | The full register file is saved around every handler and around the reschedule call |
| `DVDOpen(): file '/sound/tone.info' was not found` | The FST was parked *below* arena-hi, so the game's heap overwrote it | Arena-hi = FST start, exactly as the apploader leaves it |

Diagnostics that found them, all kept: `SOA_TRACE=1|2` (tracepoints from
`config/trace.txt`, with backtraces), `SOA_WATCH=addr,len` (store watchpoint
with backtrace), guest `OSReport`/debug-printf HLE (the game's own messages),
the spin detector and watchdog (both with guest backtraces), and
`SOA_SELFTEST=1` (call recompiled library functions directly).

State at the end of this pass: the game boots through `OSInit`, the SDK
banners, `DSPInit`/AX microcode boot, DVD reads of the title assets
(≈11 MB), and runs its main loop at 60 Hz — `VIWaitForRetrace` sleeps and
wakes the main thread each frame, ~4,000 draw commands and ~430 EFB copies
in 15 s, audio frames every 5 ms through the mailbox protocol. Nothing is
displayed yet: the GX front end parses the command stream but does not
rasterize (Phase 5).


## 9. ▲ First frames

Frames captured from the running game and rendered offline by the
software GX (`--replay`) match what the game shows: the "Created by
OVERWORKS" splash (palettised logo textures over a white clear), the
opening narration scroll ("The age of exploration has dawned upon the
world of Arcadia...") with its fade band, and the CMPR cloud layers behind
it. Lessons recorded while getting there:

- The XF shadow must cover 0x1000-0x10FF: viewport, projection and texgen
  registers live there, and a 0x1000-word array silently dropped them.
- TLUT tmem addresses in `LOADTLUT1` and `TX_SETTLUT` are in 512-byte
  units (`<< 9`); a 32-byte unit produced an all-gray screen because the
  text glyphs are C4 textures.
- The EFB persists across frames on the console. A replay must start from
  the previous frame's clear (colour and z from the captured registers),
  or every LEQUAL depth test fails against a zeroed z-buffer.
- Geometry with view-space z > 0 is legitimately behind the camera:
  the title flyover surrounds the camera, so 170 of 187 triangles in one
  frame are clipped away and that is correct.
- Throughput of the first cut is ~8 Mpixel/s (full TEV per pixel with no
  per-draw precomputation), about a tenth of what 60 Hz needs.

- The game copies the whole EFB to four 640x480 one-byte buffers (copy
  format R8) every frame. Encoding an unknown copy format at a guessed
  size overwrote 900 KB past each buffer and stalled the game after ~380
  frames; a copy encoder must write exactly the hardware's tile size or
  nothing.
- The SDK registers the serial interface handler as interrupt 20
  (`__OSUnmaskInterrupts(0x800)`), not 3; the PAD driver's whole bring-up
  waits on that one completion interrupt.

**Title screen (M6):** with a scripted START press the game reaches its
title screen, and the frame is right: logo, the day/sunset/night cloud
flyover, the New Game / Continue menu with its cursor, and the license
line. The game runs at ~29 fps without rendering; the software renderer
adds ~200 ms per rendered frame.

**Into the game:** a scripted START + A on the title menu starts a new
game. The opening cutscene renders through the software GX: the Valuan
warship at night with its searchlight, the ship's deck above the clouds,
the armada's riveted hull -- the game's own 3D models, textures and
matrices, submitted through the exact command stream. Wrong so far: the
character on deck is flat blue (a lighting or material-source detail),
there is no fog (BP 0xEE-0xF2 are set but ignored) and no mipmapping.
Input scripting had to move from retrace numbers to the game's own frame
count: the intro's timing is wall-clock while frames are not.


## 10. ▲ Audio and the rest of the hardware

- The AX microcode this game ships (hash `0x4E8A8B21`) encodes a voice's
  mixer control differently from the later builds the SDK headers
  describe: L and R are always mixed; bit 0 adds aux A, bit 1 aux B, bit 2
  surround, bit 3 enables the ramps. With the later encoding every voice
  mixed into nothing and the game was silent while reporting thousands of
  running voices.
- The buffers the microcode exchanges with the CPU (aux upload and
  download, LRS upload, set-LR, download-and-mix) are 32-bit samples,
  three channels of 160; only the final output to the AI DMA buffer is
  16-bit, right sample first.
- Sega's driver runs its own effects pass on the CPU each frame: the main
  bus is uploaded, and the next frame's list replaces the main bus with
  the processed result (`SET_OPPOSITE_LR`) and adds the rest
  (`MIX_AUXB_NOWRITE`) before output. A mixer that skips those two
  commands still produces sound, but not the game's mix.
- The memory card is reported unlocked from the start, so the SDK never
  runs its DSP unlock microcode; a blank 59-block image is enough for
  the game to offer formatting.

**The opening plays through.** Ten minutes of scripted dialogue advances
run the whole opening: the Valuan bridge (Alfonso, Galcian), the helmsman,
Vyse and Aika boarding the ship -- all rendered by the software GX with the
game's own lighting. It used to end at the transition into the first
battle, where the game opened `/battle/.GVR` and `/battle/.PVR` (an empty
name), reported `memFree Error` twice and ran off through garbage
pointers: the first divergence that was not a missing device.

**The ARAM package cache.** Chasing that divergence exposed a subsystem
worth knowing about. At boot the game stages sixteen battle packages
(`/battle/command.mld`, `pcwindow.mld`, `btlcursor.mld`, the `/bchara/`
models and their `.std` files) into ARAM above the 8 MB mark, one
high-priority ARQ transfer each, and records each slot's ARAM address and
length in a 16-entry table at `0x803165C8` guarded by a byte checksum.
Battle setup pulls a slot back with one ARAM-to-main-memory DMA, trims
the block with the game's `realloc`, and walks its entry table. The
fetched block came back as the stale contents of the freshly allocated
buffer, and the DMA log showed why: the fetch ran as a *store*. The SDK's
`ARStartDMA` writes the direction bit into `AR_DMA_CNT_H`, then reads the
register back to merge in the length's high bits; the runtime answered
that read with zero, so every ARAM-to-main transfer became main-to-ARAM
-- and, worse, overwrote the cached package with the empty buffer. The
stores had all worked, which is why the sound samples and the cache
fills looked fine. One line in the register model (the read returns what
was written) fixed it; the selftest now round-trips a DMA in each
direction so the direction bit cannot silently regress.

**The first battle plays.** With the cache intact the deck battle against
the Valuan soldiers runs end to end: the command wheel, target selection,
Vyse's and Aika's attacks with their camera cuts, the round counter, the
enemy's turn, the win, and the story continuing into the next field
scene (`/field/a201a.mld` loading with new music as the run timed out).
The only thing that had made it look stuck was the scripted controller:
it held sixty-four events and the sixty-fourth was an A press at the
command menu, so the game waited politely for input that never came.
Scripts now repeat (`3600:a@150`) and hold (`sup#120`) instead.

**Into the field.** Past the battle the story runs on into the Valuan
ship's hold, the first area the player controls: Vyse walks where the
scripted stick sends him, the minimap draws in the corner, the room
loads its neighbours (`a201a`, `a200a`, `a101b`) and their music, and a
run of 55,000 frames at three times real time ended only at its
watchdog. The last unresolved indirect branches (four switches whose
bound check is a `bgtlr`) were found the hard way -- the first field
loader dispatches through one -- and are now resolved statically like
the other 292.

**Text.** Dialogue, item names, character names and the battle's action
window were all blank while stat labels, enemy names and damage numbers
drew fine. A captured dialogue frame explained it: the game renders each
glyph from its `AFNT` font into a 24x24 I4 texture in main memory and
draws it as a quad on texture map 7 read through texture coordinate 0.
The renderer took the coordinate scale (`SU_SSIZE`/`TSIZE`) from the
*map's* register pair, which the game never writes, so every glyph was
sampled at its blank corner texel. Those registers are indexed by
coordinate: the SDK writes the dimensions of whatever map a stage samples
into the registers of the coordinate that stage uses. One index change,
and the Alfonso scene reads "We've finally found her...".

- Giving DVD commands and ARAM DMAs realistic completion times (seek plus
  transfer; a short delay) removed the `memFree Error`s: with instant
  completion the SDK's completion callbacks could run at the next loop
  edge, before the requesting code had finished, which never happens on
  the console. The remaining divergence at the battle transition is a
  package entry whose data pointer reads as `0xE0C0C2E7` -- the same value
  in every run, so a data or relocation problem rather than a race.
