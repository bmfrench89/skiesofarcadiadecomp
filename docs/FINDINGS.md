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

**Streamed music, checked.** `SOA_WAV` records everything the game plays;
`tools/audio_check.py` decodes a `.dsp` stream (`tools/soa/dspadpcm.py`,
unit-tested on hand-computed frames), resamples it to 32 kHz and slides an
excerpt over the recording. The opening music (`m01`, 22.05 kHz, 128 s)
correlates at 0.85 on both channels with what the port played; the battle
music at 0.52, under the voices and effects the game mixes over it. So the
ADPCM decode, the sample-rate conversion and the stream refills through
ARAM are right. In 7.5 minutes of recording 104 samples clip.

**The title's black wedges.** The title backdrop is two tall cloud quads;
each lost a diagonal slab. The rasteriser computes each row's span from
the three edge functions, and for a horizontal edge the x coefficient is
not zero but a rounding crumb (-1.2e-10). Dividing by it gave a limit in
the billions, which the int conversion turned into INT_MIN, and the row
was dropped wherever that edge happened to be the binding one. The limits
are now compared in floating point before conversion. `SOA_GXR_PIXEL=x,y`
narrates every fragment that lands on one pixel, which is how the missing
fragments were found.

**The battleship's searchlights: half of this is now solved, and the
other half is a different defect.** This entry used to say the beams
render as near-black slabs with lit rims and needed a reference capture
to settle. **They are not dark any more.** Inside the beams' footprint
the current render averages (84,96,202) against (19,25,90) outside, and
the wedges read as pale blue-white. The darkness went with the texture
use-after-free fixed on 2026-09-17, which was washing whole scenes
green and blue; no lighting change was needed and no console capture was
spent.

Dumping the vertex data settled the lighting question that was supposed
to need hardware. The beam normals are not one population but three: 144
side-wall vertices split exactly evenly at N.L = +/-0.4, +/-0.6 and
+/-0.9915, so half sit at pure ambient and half are lit; 60 end-cap
vertices whose normals have no x component at all, which puts them
within 0.095 of perpendicular to a light that is 99.55% along view-space
x; and 48 with no normal at all. The data is internally consistent, unit
length to within 3e-5, through identity matrices, so nothing supports the
"our vertex data differs" theory. The sprite's alpha ramp is real and the
quads sample it: alpha 255,218,182,145,72,0 across the texels they use.

**The depth theory is also wrong, and was checked to destruction.** The
paragraph here used to say the beams write depth and occlude the sky.
They do not. The game brackets the 54 beam draws with a depth mode that
has the write bit clear, restoring it in the very next command, and our
renderer honours that: narrating a beam pixel shows the depth buffer
unchanged at the sky's value across both beam fragments. The cloud layer
is not occluded either. It is drawn later and it lands: measured over the
sky, it changes 24.9% of the pixels a beam covers against 30.2% of those
it does not, and the cloud fragments that do fail depth fail against the
hull, which is correct.

Two further things were ruled out rather than assumed. Our fragment path
applies the alpha test before the only depth write in the ordinary
late-depth mode, so an alpha-killed fragment cannot touch the depth
buffer. The early-depth mode does write first, which is what the hardware
does and why the API exposes the switch, and a census of all 23 captures
found not one draw among 43,249 that combines early depth with an alpha
test that can reject. The game turns early depth off whenever it turns
the alpha test on.

**What is actually left is a coverage question, not a shading one.**
Inside the beam quads no fragment ever samples a texel alpha below 176,
so the fade end of the sprite's ramp, 145 then 72 then 0, is never
reached: each beam stops at a hard quad boundary with alpha still at 205
one pixel before nothing. The beams' texture coordinates pass through a
post-transform matrix, and the fragments land in a narrow band of the
sprite. That is where to look next, and it is a texture-coordinate
generation question. Whether the transform unit renormalises a vertex
normal is still worth knowing, since capture 3900 submits these normals
at twenty times unit length, but it cannot explain the edges.

A caution for whoever reads this next: the entry above was describing a
render that no longer existed, and the plan item built on it counted 90
draws that turn out to be a different object entirely, octagonal prisms
on the bridge cabins. The beams are 54 draws. Re-look at the frame before
trusting a written description of it.

**Speed.** With every frame rasterised (640x480, eight worker threads) the
port holds 59 retraces a second through the opening with the game thread
about two-thirds idle; the renderer's main-thread share is under a fifth of
a core. Headless, with the write-gather pipe stores going straight to the
GX parser, guest time runs about ten times faster than the wall clock
(`SOA_SPEED=10`: 594 retraces a second), which is what makes scripted
exploration runs practical.

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
  the console. The divergence that remained at the battle transition (a
  package entry whose data pointer read as `0xE0C0C2E7`, the same value in
  every run) was the ARAM DMA direction bit described above.


## 11. ▲ Where scripted play actually gets to, and why it stops

Measured 2026-09-21 from the two saved traced runs and the extracted disc, for
PLAN D5. Everything here is a count from a log or a directory listing.

**The opening moves you between four maps on its own.** Both saved runs load
exactly the same field maps at almost the same frames, and `boot_field.log`
had no stick input at all before frame 15000 — its whole script is START nine
times and A every 150 frames:

| frame (field / monkey) | map |
|---|---|
| 0 / 0 | `a299a` |
| 2250 / 2250 | `a201a` |
| 12910 / 12160 | `a201a` again |
| 13210 / 12460 | `a200a` |
| 14710 / 14010 | `a101b` |

So `a200a` and `a101b` are reached by the story, not by walking, and the room
the player is finally left standing in is **`a101b`** — not `a201a`, which is
what the scenario files' prose calls "the hold". That distinction turns out to
matter.

**The hold cannot produce a random encounter.** Of the five maps any run has
ever loaded, only `a101b` has an encounter table: `extracted/field/` holds
`a101b_ep.enp` and `a101b.ect`, and there is no `.enp` or `.ect` for `a201a`,
`a200a`, `a090a` or `a299a`. `encounter.scn` used to say it would "walk the
ship's hold for twenty minutes of game time until a fight starts" (it names
`a101b` now); if that ever works
it is because the run has already been carried into `a101b`, not because of
the walking. The four random encounters in `boot_monkey.log` (frames 23860,
37650, 45160 and 50860) all happen after `a101b` loads at 14010.

**No saved run has ever walked anywhere.** This is the finding that matters,
and it is easy to get wrong from the logs alone. `boot_monkey.log` does reach
one map nothing else does — `a090a` at frame 52400 — but it is not a place the
player walked to: the monkey scripts press **only START, B, Z, X, Y on five
periods and never touch the stick** (`monkey.scn`'s own event list), the map
loads 1,540 frames after a random encounter starts at 50860, and `a299a` and
`a201a` follow it, which is the game over and restart `monkey.scn` claims. So
`a090a` is the game-over screen. `boot_field.log` is the only run that
scripted the stick at all, and it loaded nothing new after frame 14710: 40,500
further frames, 355 A presses, zero loads.

Every one of the five maps any run has reached was reached by the story or by
losing a fight. The disc holds **264** root field maps (`aNNNx.mld`), 51 `.enp`
and 35 `.ect`. Navigation is not "hard" in this port; it is **unattempted**,
and the first honest attempt at it should expect to fail.

The lesson for D5 is that the ceiling is not the input format — `SOA_PAD`
composes diagonals with `+`, and `SOA_PAD_FILE` takes hand-written analog
lines — it is that nothing tells the script where it is. A run's own trace
already says when it arrives somewhere (`LoadStart "/field/aNNNx.mld"`), which
is enough to score an attempt after the fact, but not to steer one.


**The battle command wheel, read off the screen.** PLAN D5 wants a battle
using every command and did not say what the commands are. They were found by
parking the game on an open menu and rotating it: the menu waits for input
indefinitely, so a script that stops pressing A leaves the wheel up for as
long as you like, and `SOA_SNAP` then photographs each label. All seven names
are confirmed from rendered frames of the first battle (Vyse, Lv 1, Mp 3/3,
round 2 of 8):

**Attack, Magic, Focus, S-move, Guard, Run, Item.**

The d-pad rotates it -- `right` and `left`, not the stick -- and A commits.
Measured transitions, each one a label read from a PNG:

| from | input | to |
|---|---|---|
| Attack | `right` | Magic |
| Magic | `right` | Focus |
| Attack | `left` | Item |
| Item | `left` | Run |
| Run | `right` | Guard |
| Guard | `right` | S-move |

Committing S-move with A put Vyse's S-Move name box on screen, so a
non-default command really does execute from a script.

What is *not* established is the ring's order. Nine further `right` presses
after Focus, and four further `left` presses after Run, changed nothing, which
a simple circular list does not explain -- the wheel may refuse to wrap, or
those presses may have been dropped while the game was busy, and the frames
cannot tell the two apart. Anyone scripting this should drive it by the table
above, one confirmed step at a time, rather than by an assumed ring.


**Warping the field by poke: the load fires, the frame does not come back.**
With `SOA_POKE` (PLAN D2) the field's map identity can be changed mid-run, and
the game really does act on it. Poked at frame 16000 of a run standing in
`a101b`:

```
[poke] frame 16000: 80311AC4 <- 000000C8 (was 00000065)   map number 101 -> 200
[poke] frame 16000: 80311AC8 <- 61000000 (was 62000000)   map letter 'b' -> 'a'
[poke] frame 16000: 80311AEC <- 00000003 (was 00000008)   field state 8 -> 3
```

and the trace then shows a sixth map load, `/field/a200a.mld`, which no run had
ever produced from that point. So the loader does read those two words, and
three words of poke are enough to make this game load an arbitrary one of its
264 field maps.

**It is not a working teleport yet.** Frames 15600-16000 are the room; from
16200 to the end of the run every frame is black. The map loaded and nothing
rendered, which is what forcing state 3 should be expected to do: state 3 is
the *load* step of the 16-state field machine, and whatever the states around
it normally arrange -- where the player stands, the camera, the return to the
steady state 8 -- did not happen. The next thing to try is state **1**, the
warp resolver (`fn_800FFB24`, which checks `/field/meNNNx.sct` and
`/field/aNNNx.mld` for existence before committing), so the game performs its
own warp instead of having the load forced on it. Untried at the time of
writing.

Worth knowing either way: a black frame after a poked load is not evidence
that the map is broken. It is evidence that this route into it is.


**What the warp resolver actually requires, and how many maps pass it.**
`fn_800FFB24` reads exactly the two words the poke writes -- `lwz` for the map
number at 0x80311AC4 and `lbz` plus `extsb` for the *byte* at 0x80311AC8, which
is why the letter has to go in the top byte of that word -- formats two paths
through `fn_8025CB24` with the format strings at 0x802B2364 and 0x802B2374, and
asks `fn_801CC62C` (DVDConvertPathToEntrynum) whether each exists. It returns
success only if **both** `/field/meNNNx.sct` and `/field/aNNNx.mld` are on the
disc, and `fn_80101828`'s state-1 arm advances to state 3 only on that success,
so a warp to a map missing either file leaves the field parked in state 1.

Counted against the extracted disc: 264 `aNNNx.mld`, 254 `meNNNx.sct`, and
**252 maps have both** -- the set a warp can reach. Twelve maps have geometry
and no script (`034j`, `102a`, `102b`, `102c`, `102e`, `102v`, `102z`, `199f`,
`221a`, `300d`, `355a`, `398a`) and two have a script and no geometry (`121e`,
`561a`). Sixty-six of the 252 are numbered 500 and above, which is the
sky/overworld group the resolver special-cases at 0x800FFBE0.

Against five maps ever loaded by any run, 252 is the size of the prize.


**There is a stage select left in the retail executable.** This is the most
useful thing found while chasing the warp, and it is in `fn_800FFB24` -- the
same function the field's state-2 arm calls to resolve a warp. The function has
two halves and a gate between them:

```
800FFB44  lwz   r0, -29092(r13)        the index, r13 = 0x8034E720 -> 0x8034757C
800FFB4C  lwzx  r3, 0x80311A60, r0*4   an object; index is 0 in every capture,
                                       so the object is 0x80311A44
800FFB50  lwz   r0, 8(r3)              its flags word, 0x80311A4C
800FFB54  rlwinm r0, r0, 0, 19, 19     bit 12
800FFB58  bc    12,2 -> 800FFDC8       CLEAR -> the second half
```

Bit 12 set is the normal warp: format `/field/meNNNx.sct` and
`/field/aNNNx.mld`, ask the disc whether both exist, return success. Bit 12
clear is a **stage picker**. From 0x800FFDC8 it reads pad bits out of the
field's own pad snapshot at `0x80311A14 + index*12` and applies them to the map
number at 0x80311AC4: +100, -100, +5, -5, +1, -1, wrapping the number into
0..599 (`+600` if it goes negative, `-599` if it passes 599) and clamping the
letter at 0x80311AC8 into `'a'`..`'z'` with `'a'` as the default. It prints
through the format string **`"Stage No: %03d%c"` at 0x802B2398** -- one hit in
the whole image, in the same string cluster as the two path formats the warp
half uses -- and on commit returns **16** at 0x80100018, which is nonzero, so
the state-2 arm advances to state 3 and the stage loads.

`r13 = 0x8034E720`, from the translated code (`gpr[13] = 0x80340000 | 0xE720`,
`gen/chunk_000.c`). That is worth writing down once: this codebase addresses
most of its globals off r13, and every `-N(r13)` in a disassembly is
`0x8034E720 - N`.

The gate's flags word reads **0** in all three MEM1 captures, so bit 12 is
already clear in the steady field state. The reason normal play never sees the
picker is therefore not the flag -- it is that state 2 is only entered when
something requests a warp, and whatever requests one sets the bit first.

Which makes the route in one line: get the field into state 2 without setting
that bit. `SOA_POKE` can do exactly that.


**The battle menu in the code, and where it disagrees with the screen.** The
character command menu is `fn_8007A890`, an 8-state machine whose state byte is
at task+25 with a jump table at 0x802DF83C, opened by `fn_8007C600(5)` and
registered in the sbss global 0x80347308. Its widget is a 136-byte heap block
at *(task+36): +1 is the command cursor, +2 an availability mask, +3 the row
cursor. `fn_80079F74` builds the mask: bit 0 is code 9, Items, set only when
the party holds an item whose record at `0x802C7C34 + (id-240)*36` has bit 0x02
at byte +17; bit 1 is code 10, Attack, always set; bits 2 and 3 are codes 11
and 12, whose lists live at 0x8030BC88 and 0x8030BDC8. RIGHT (0x0002) and LEFT
(0x0001) come from the auto-repeat-filtered word at 0x8030A6E0 and move the
cursor, wrapping and skipping unavailable entries; A (0x0100) and B (0x0200)
come from the raw edge word at 0x8030A6DC. Target selection is `fn_80079C5C`,
which starts on the actor's *remembered* target at byte +256 of
*(0x80309DE4 + slot*4) -- which is why `battle.scn` wins the first fight with A
presses and no direction presses at all.

**The disagreement, left standing on purpose.** That reading says bits 4 and 5
are never set, so there are exactly four selectable entries. The screen showed
**seven** distinct labels reachable with LEFT and RIGHT in the first battle:
Attack, Magic, Focus, S-move, Guard, Run, Item. Both observations are recorded
because neither has been reconciled: the code may describe a different one of
the two battle menus in the executable, the labels may include entries the
cursor passes through without being able to commit, or the availability mask
may differ from what the static read of `fn_80079F74` suggests. What must not
happen is picking whichever is more convenient. The empirical table above is
what a script should be driven by, because it was measured on the build that
exists; the addresses here are where to look when someone wants to know why.


**The stage select fires, loads any stage, and draws nothing.** Poking the
field to state 2 while bit 12 is clear enters the picker, and START commits it:

```
[poke] frame 15000: 80311AC4 <- 000000C8 (was 00000065)   map number -> 200
[poke] frame 15000: 80311AC8 <- 61000000 (was 62000000)   letter -> 'a'
[poke] frame 15000: 80311AEC <- 00000002 (was 00000008)   field state -> 2
```

and the trace shows `/field/a200a.mld` loading. Three pokes and a START reach
a map the game had no reason to go to.

**The state machine is not the problem.** Reading the state word back at ten
frames across the rest of the run -- every `SOA_POKE` reports the value it
replaced, which makes it a read primitive as well as a write one -- it is
**8 at frame 15200 and at every frame after**. The chain 2 -> select -> 3
(load) -> 4, 5, 6, 7 -> 8 completes in under 200 frames and parks in the
steady rendering state, with the map loaded. That kills the theory that
forcing a state strands the machine in one of the three wait states
(state 4 spins on `fn_80090D78`, state 5 on `fn_80109D74` twice and
`fn_800C7DD4`, state 6 on `fn_800C7DFC`).

**What is actually wrong is that the scene is empty.** Every frame from the
commit onward is *pure* black: min 0, max 0, one distinct colour, zero
non-black pixels out of 307,200, measured on frames 15100, 16000 and 17600.
Not a dark room -- nothing is submitted at all. The map file is read and no
geometry, camera or player exists to draw.

The likely reason is one line in state 7, and it is worth quoting because it
names the developers' own test stage:

```
801019B8  cmpi cr0, r0, 131        ; 0x80311AC0, the COMMITTED map number
801019BC  bc 4,2 -> 801019E8       ; not 131 -> skip
801019C4  cmpi cr0, r0, 101        ; 0x80310008, 'e'
801019C8  bc 4,2 -> 801019E8       ; not 'e' -> skip
801019CC  bl -> 802126C8           scptInitial
```

`scptInitial` -- what starts a map's script, and therefore what places the
camera, the player and the objects -- is called from this path **only for
stage 131e**. Every other stage reaches state 8 with its geometry loaded and
its script never started, which is exactly a black screen. So the picker was
built to be driven to one test map, and 131e is the stage to try first.

Also settled while reading: **0x80311AC0 is the committed map number and
0x80311AC4 the working copy.** The picker copies AC4 into AC0 on entry and
again on commit, and state 7 reads AC0. Earlier experiments here poked only
AC4, which is why the load and the setup could disagree about which map they
were in.


**131e renders, and that is a working teleport.** The prediction from the
state-7 gate held. Warping to stage 131 letter 'e' -- the one map that path
calls `scptInitial` for -- gives a live field:

| | frame 15000 | 15100 | 15200 onward |
|---|---|---|---|
| what is on screen | the old room | one black frame | the new map |
| max channel | 174 | 0 | 161 |
| non-black pixels | 307,200 | 0 | 307,200 |
| distinct colours | 47,899 | 1 | 21,000-26,600 |

`/field/a131e.mld` loads, the machine returns to state 8, and from 15200 the
frames show the player standing in a room with the minimap drawn and the
character animating between snapshots. One black frame is the whole
transition. This is the first time anything in this project has reached a
field map by any means other than the story carrying it there.

The camera sits jammed against the player, which is what a test stage whose
script never places a camera should look like, and is cosmetic.

So the picker is a *working* teleport to one map and a geometry loader for the
other 251. The thing standing between it and all of them is `scptInitial`
being gated on the committed map number, and the gate reads 0x80311AC0 and
0x80311AC8 while the filename was formatted earlier from 0x80311AC4 -- so the
two can be made to disagree on purpose.

One note for anyone reading the disassembly here: `tools/disasm.py` annotates
`lbz r0, 8(r3)` at 0x801019C0 as `@ 0x80310008`, which is wrong. The preceding
`lwzu r0, 6848(r3)` *updates* r3 to 0x80311AC0, so the byte read is
0x80311AC8. The annotator does not track update-form loads. Do the arithmetic
rather than trusting the comment.


**Spoofing the gate did not work, at this timing.** The obvious next move --
load one map's geometry from the working copy and then set the committed words
to 131/'e' so the gate lets `scptInitial` run -- was tried and failed. The
pokes landed (`0x80311AC0 <- 00000083 (was 000000C8)` at frame 15150, so the
picker really had committed 200 and the spoof really did replace it), the
geometry really was `/field/a200a.mld`, and every frame from 15300 on is still
pure black.

The most likely reason is timing rather than the idea: the whole transition in
the 131e run took **one** frame, 15100 black and 15200 already drawing, so
state 7 runs somewhere in 15100-15200 and the first spoof at 15150 may simply
have arrived after it. Narrowing that needs a poke every frame across
15080-15200, which is well inside `SOA_POKE`'s 256-item budget. Not yet tried.

What is *not* established is whether `scptInitial` would even do the right
thing if the gate passed: it may read the map identity itself and try to run
`me131e.sct` against `a200a` geometry. The experiment is still worth running,
because either outcome is informative, but a success should be checked by
looking at the frame rather than by the absence of black.


**Correction, 2026-09-22: `scptInitial` runs for every map, and the 131e test
only decides *when*.** The two entries above read the state-7 gate as "the
script is started only for stage 131e". The instructions after the gate say
otherwise. The field's jump table at 0x802E471C puts state 6 at 0x80101998 and
state 7 at 0x801019AC (state 6 falls through into 7), and r30 is set to 0 at
the function's entry (0x8010183C) and is callee-saved, so every call in the
arm preserves it:

```
801019B8  cmpi  r0, 131              committed number at 0x80311AC0
801019BC  bne   -> 801019E8          not 131: r30 is still 0
801019C4  cmpi  r0, 101              letter at 0x80311AC8
801019C8  bne   -> 801019E8
801019CC  bl    scptInitial          131e only: start the script now ...
801019D4  bl    fn_80212130          ... and run it 200 ticks before the camera
801019DC  ...   (loop 200)               setup below
801019E4  li    r30, 1
801019E8  bl    fn_8012A39C          every map
801019F0  li    r0, 8                state = 8
801019F4  cmpi  r30, 0
801019FC  bne   -> 80101A04
80101A00  bl    scptInitial          every map that is NOT 131e
```

So 200a's script *is* started -- after `fn_8012A39C` and without the 200
pre-run ticks. The gate cannot be why every stage but 131e is black, and the
every-frame spoof of 0x80311AC0 that the entry above proposed would only move
`scptInitial` earlier and pre-run it; it is not worth a run on its own.


**Three more things the stage-select entries above got wrong** (found by an
audit of this section, 2026-09-22, each re-checked against the disassembly):

- **The resolver is state 2, not state 1.** The jump table at 0x802E471C
  gives state 1 = 0x801018B0 and state 2 = 0x80101898, and only the second
  calls `fn_800FFB24`. State 1 goes to 2 when the word at r13-29004
  (0x803475D4) is 0, and straight to 3 -- skipping the resolver -- when it is
  not. A state-1 poke therefore parks the field in the picker, which is why
  `run_warp2` loaded nothing: it never pressed START.
- **The "flags word" at 0x80311A4C is the field's pad snapshot, and bit 12 is
  START.** The picker half tests the same word with 0x200, 0x40, 0x20, 0x8,
  0x4, 0x2 and 0x1 -- B, L, R, up, down, right, left -- beside stick and
  trigger bytes compared against 25 and 10: a PADStatus. So "bit 12 clear is a
  stage picker" means "START not pressed", and every picker run that pressed
  START already ran the file-checking half. It reads 0 in the captures because
  nobody was pressing anything.
- **The picker half never returns 16.** 0x80100018 `li r3, 16` is the
  argument to `fn_80290EA8`; the half ends at 0x801000D8 with `li r3, 0`, and it
  copies the working number to the committed one every frame. The state-2 arm
  advances only on the START half's `return 1` at 0x800FFDB0.
- And "the transition takes one frame" is one *snapshot*: `SOA_SNAP=100`, so
  15100 black and 15200 drawing bounds it at under 200 frames, not one.

Poking 0x1000 into the snapshot to force the START half was tried anyway
(`build/run_normalwarp.log`, frame 15000, with 200/'a' and state 2). The
game's next pad read overwrote it: the state word was never written again in
1,600 frames, and every frame shows the picker's screen -- black, with one
debug string, **なし** ("none").


**How the story's own warps run, from a store watchpoint.** `SOA_WATCH` needs
no recompile (the compare is inlined into every translated store), and on the
state word 0x80311AEC it prints every transition. Every story warp in the
opening takes the same path, and it never enters state 2:

```
15  written by fn_80100178, the warp request           (lr 0x80100210)
 0  written by fn_801DBE6C, the scene change
 1  fn_80101378: the field's init, state 0's arm
 3  state 1 with r13-29004 set: straight to the load, no resolver
 5  fn_801015AC, the load, returns 5
 7  state 5, fn_800C7DD4 != 1
 8  state 7, then scptInitial at 0x80101A00
```

`fn_80100178(name)` is the request: it copies a *script file name* such as
`"ME299A.SCT"` (0x802D9730) to 0x80305CF0, calls `fn_800FF908` and
`fn_801F7B04(number*10 + letter-'a')`, stores state 15 and sets r13-29004 to
1. State 15's arm, `fn_80101494`, is the teardown -- `fn_8022697C`,
`fn_80101158` (which zeroes the script arrays; skipping it is what prints
`scptArrayAlloc: initial two times` after every picker warp), `fn_8012A26C`
-- then re-derives the map from that name with `fn_801004C4`, which parses
`MEnnnX` into the committed number, the working number and the letter, and
calls `fn_801DBE6C(6)` to restart the field at state 0.

So a picker warp differs from a story warp in exactly the part that matters:
it skips the teardown and state 0's init and loads a new map on top of the old
one's objects and scripts. The faithful poke is the name plus state 15:
`0x80305CF0` = `"ME20"`, `0x80305CF4` = `"0A.S"`, `0x80305CF8` = `"CT\0\0"`,
then 15 into 0x80311AEC.


**The name-driven warp works: `a103a`, a map no run had reached, renders with
its own script running.** `build/run_namewarp.log` (the `battle` preamble, then
seven pokes at frame 15000 and seven more at 16000, `SOA_WATCH=0x80311AEC`):

```
15000: 0x80305CF0="ME20" 0x80305CF4="0A.S" 0x80305CF8="CT\0\0"
       0x80311AC0=200 0x80311AC4=200 0x80311AC8=0x61000000 0x80311AEC=15
16000: the same with "ME103A.SCT", 103
```

Both warps took exactly the story's path, 15 -> 0 -> 1 -> 3 -> 5 -> 7 -> 8,
with state 0 written by `fn_801DBE6C` from state 15's arm (lr 0x8010158C), and
both loaded their map: `/player.mld` then `/field/a200a.mld`, and later
`/player.mld` then `/field/a103a.mld`. After `a103a` the trace shows the map's
script at work -- a sub-model `/field/a103aa19.mld`, the music bank
`/sound/m5030000`, the effects bank `/sound/e6a019` -- and the frames agree:

| frame | 15000 | 15100-16000 | 16100 | 16200 | 16400 |
|---|---|---|---|---|---|
| map | `a101b` | `a200a` | `a103a` | `a103a` | `a103a` |
| non-black pixels | 307,200 | 0 | 307,200 | 298,700 | 302,216 |
| distinct colours | 47,899 | 1 | 19,089 | 140,793 | 111,333 |

16200 is Aika on a mossy ledge above turquoise water, facing a stone temple
under a blue sky; by 16400 Vyse has joined her and a dialogue box reads
"Vyse! Over there! Look at the size of that hole!" -- the map's own arrival
scene, played by its own script.

`a200a` is black through the faithful path too, so its black screen is not the
route: that map is the one the story itself visits during the opening, and its
script evidently draws nothing when entered at this point in the story.
Stage-select warps to `a200a` were black for the same reason, not for the
teardown they skip. What the picker's missing teardown costs is still
unmeasured; the name-driven warp makes it moot.

The name's first byte is zeroed after the game reads it (`was 00453230`
at 16000), so the name has to be poked whole for every warp. Seven pokes per
warp and a 256-item `SOA_POKE` give 36 warps per run -- on a binary linked
after commit 1bad9fb; the one used here predated it and allowed 64.


**A census of 36 warps: every map loaded, the runtime survived all of them,
and 27 end on a drawn scene.** `build/run_census.log` and `build/scenario-census.log`,
2026-09-22: the `battle` preamble, then one name-driven warp every 600 frames
from 15000 to 36000 (252 pokes, on a binary relinked that day), `SOA_SNAP=100`,
`SOA_TRACE=1`. Every warp's own map appears in a `LoadStart` line after its
poke. The whole run reports 0 unknown FIFO bytes and no `[mmio!]` line. The
frames 300 and 500 after each warp say:

| outcome | maps |
|---|---|
| a full scene (non-black > 280,000 px, > 13,000 colours) | 002a 005a 008a 010a 013a 018a 020a 028a 034a 035a 098a 099a 103b 106a 107a 109a 111a 112a 115a 116a 121a 123a 126a 130a 202a 213a 260a |
| partial | 019a (31,050 px), 032a (106,083 px: a dusk sky over solid black) |
| black, one colour | 017a 033a 240a |
| the post-battle results screen, frozen | 500a 520a 550a 580a |

`098a`'s row counts among the 27, but what it shows is `099a`: its own
script warped the run onward before frame +300, so a script-driven exit
works through this route too. Frame 24900 (`103b`)
is a waterfall pouring through a ruin toward the sea, which is what a
correctly lit map looks like here.

The 5xx rows are not four overworld frames. From 34300, 100 frames after the
`500a` warp, every frame is the same image: Exp/Gold and Vyse and Aika at Lv 1,
the screen after a battle, waiting for an A this script never presses. The
later three warps still load their maps behind it. The sky group is
special-cased twice -- the resolver prints `/sound/f7000000.mlt` for 500-599,
and state 8's arm sends a map number of 500 or more to state 14 instead of 12
-- so these maps are likely entered through a ship mode this route does not
set up. Unexplained; the next thing to try is a single 5xx warp with
`SOA_WATCH=0x80311AEC` and A presses after it.

The three black maps and the two partial ones are not yet evidence of a
defect: `a200a` was black too and is a map the story visits, so a map drawing
nothing when entered out of story order is expected. Each needs its frame
looked at against the story before anything in the renderer is suspected.


**The 5xx rows explained: a warp to `500a` starts a ship battle.**
`build/run_sky500.log` / `build/scenario-sky500.log`: the same preamble, one
name-driven warp to `ME500A.SCT` at 15000, `SOA_WATCH=0x80311AEC`, and an A
every 150 frames from 15400. The state word goes 15, 0, 1, 3, **4**, 5, 7, 8
-- the first warp seen to pass through state 4, which waits on `fn_80090D78`
-- and the trace loads `/field/sbek000...` before `/field/a500a.mld` and the
status icons after it. Frames 15100 and 15200 are the census's 39,475-colour
Exp/Gold screen, byte for byte the same count; after the first A it is gone.
15500 is the Little Jack under full sail against a blue sky, and 17900 is the
ship-battle interface -- the turn grid, round 2 of 8, Aika's portrait, the
command wheel on Attack, and the enemy named **The Blackbeard** with its hull
bar.

So the census's "frozen results screen" was the first screen of this
sequence, waiting for an A that script never pressed, and the four 5xx
warps were four ship-battle entries. This is the first ship battle anything in
this project has run (ROADMAP 7.3, PLAN D5), reached in 15,400 frames of
scripted input and seven pokes. Whether every 5xx map starts one, and what
the battle does when driven past Attack, is the next run.


**A second census, and 72 maps without a runtime fault.**
`build/scenario-census2.log`, 2026-09-23: the next 36 maps below 500 in
number order (002b to 034d), same method. Every map loaded; 0 unknown FIFO
bytes, no `[mmio!]`, no tripwire. 33 end on a drawn scene; `013f` and `028d`
are black and `019d` partial (17,048 px). With the first census that is 72
maps loaded in two runs, 60 drawn, 5 black, 3 partial, 4 the 5xx artefact
below -- and nothing the runtime refused.


**What four read-only investigations found, and what it corrects.** On
2026-09-23 four agents read the disassembly, the DOL and the decompressed
scripts for the things a playthrough needs that the census cannot show. Their
full reports are in `docs/research/` (`save-load.md`, `encounters.md`,
`ship-worldmap.md`, `story-flags.md`); each claim there is marked verified
or inferred, and none was run when written. The ones this section relied on,
or that correct it:

- **The 5xx "results screen" was made by the pokes, not by the game.** State
  15's teardown calls `fn_8012A26C` *before* `fn_801004C4` parses the new
  name, so it sees whatever map words are there; poking 0x80311AC0/AC4 to 500
  first made it run the ship-battle teardown for a battle that never happened,
  which sets 0x80347280 and sends the next load through state 4, the results
  screen. So the map-word pokes this section called "belt and braces" are
  harmful for a 5xx destination and unnecessary for any other: the name alone
  sets all three words. The 5xx maps are ship-battle stages, one per fight,
  entered in play by script opcode 210 (`fn_80147E2C`), which sets
  0x803472E4 and state 12 rather than 15. The ship battle against The
  Blackbeard at 17900 was real; its first screen was not.
- **255 maps are warpable, not 252.** The disc lookup compares names through a
  lower-case table, so `ME199F.sct`, `ME355A.sct` and `ME398A.sct` count.
- **The executable names its maps.** The stage picker's label table at
  0x802E4780 (158 entries, Shift-JIS) gives Pirate Isle for 002, Valua for
  005, Nasr for 013, Shrine Island for 103, the Sky Map for 099, and an enemy
  ship for each 5xx (500a is Baltor's). Decoded in `ship-worldmap.md`.
- **The world map is map 099 in the field scene**, not a scene of its own; its
  letter is ignored and chosen from byte 0x80310A22. There are ten scenes
  (`fn_801DBE6C(n)`): 3 title, 6 field, 7 battle, 9 ending.
- **Story progress is flags, and the disc carries the developers' part
  select.** Flags 0-27,327 live at 0x80310B3C; each map's script tests them.
  `a200a` is black because its loop does nothing once flag 2 is set -- the map
  and the route were never at fault. `ME355A.SCT` is a menu that jumps to the
  start of story parts B to L with each part's flags, party and destination.
  The word at 0x80310BBC is party membership (flags 1026+ch, 1032+ch), not a
  story flag.
- **The battle wheel is `fn_8007CAB0`, and every scripted press moved two
  slots.** Slots 0-6 are Focus, Magic, S-move, Attack, Guard, Item, Run, with
  no wrap. The game's auto-repeat fires after 6 held frames and `si.c` holds a
  press for 10, so a plain `left` is two steps; all six measured transitions
  above fit that exactly. `fn_8007A890`/`fn_80079F74` are the *Item*
  submenu's tabs, and `fn_80079C5C` cycles a weapon's Moon Stone colour: the
  "four entries" disagreement was two different menus. Use `left#4` for one
  step.
- **A battle can be forced** with six words (the scripted-battle request of
  opcode 112, read first and ungated in `fn_800C1C24`), and **a save can be
  requested** with one (0x803473B4 = 1, which opens the game's own save menu
  in every loaded field). Both recipes are in the reports; runs of them follow.


**A save written from the field loads back through Continue.**
`build/scenario-save.log` then `build/scenario-load.log`, 2026-09-23, both on a
copy of the formatted card in `build/savetest/`. The save run is the `battle`
preamble to the field, then `SOA_POKE=15000:0x803473B0=0,15000:0x803473B4=1`
and A at 15300, 15450, 15600, 15750 and 15900 and X at 16050 and 16200. The
watch on 0x803473C4 reads 0 from lr 0x80123DE4 at the poke -- the save-point
task opening the menu with `fn_801A21F8` -- and 1 from lr 0x8019E310 when it
closes; between them the trace writes pages 0x3A00-0x3F80 and more, and the run
ends `card 204800 bytes read, 147456 written`, which is one save and one
overwrite from the spare A, as the research predicted to the byte. Frame
15900 is the game's own screen: "Now saving. Please do not touch the Memory
Card or the POWER Button.", file #01 "Valuan Battle Ship", Lv 1, 0:07, Vyse's
and Aika's portraits. `cardformat.py show` reads back `SA_LEGENDS.000`, 3
blocks, chain 8 9 10.

The load run boots on that card with the preamble's START/A pairs and A every
200 frames. The title goes through scenes 12, 13, then **16 and 17**, the
Continue arm, which no run had entered; the field starts from its Continue
path (state 0 written from lr 0x80228B24, then 1, 3, 5, 7, 8 -- no 15, no 2),
`/field/a101b.mld` loads, and frame 3000 shows Vyse standing beside the
glowing save point in the hold, minimap drawn. `card 172032 bytes read, 0
written`. PLAN B4 is done.

What it buys: a run that starts from a save reaches a field by frame 2800
instead of 14710, five times less guest time per experiment, and a save made
after any warp, part select or story poke carries that state to every later
run. The card is game-written data, so the images stay in `build/` and are
never committed.


**The developers' part select reaches parts B, H and L.** 2026-09-23, each run
starting from the save above (the field by frame 2800) and warping by name to
`ME355A.SCT` at frame 3300. The map is a corridor with a Valuan officer; his
first question and then 《どうする？》 with 「Bパートへ」「Cパートへ」「へ」
(frame 4260 of `build/scenario-partsel.log`) are the first page of six --
B/C, D/E, F/G, H/I, J/K, L -- each with "next" third.

- **Part B** (`scenario-partsel.log`: A every 60 frames from 3500, so the first
  choice everywhere). The A at 4280 runs routine `a`, and the watch on
  0x80310B3C shows the flag word climb 6, e, 1e, ... 8003fe, 8007fe, a007fe,
  e007fe, ... fffffe -- flags 1-23 set in exactly the order
  `docs/research/story-flags.md` read from the script (9, then 23, 10, 21, 22,
  19, 11, 12, 18, 20, 13...). Then `/field/a002b.mld`: frame 5000 is Vyse on
  the Pirate Isle dock beside a ship, minimap drawn.
- **Part H**, twice, by accident. Each page first shows 《どうする？》 as a
  message box waiting for A (frame 4780, with the ▼), and only then the
  choices; the downs meant for the choices hit the box and were dropped, so
  every page after the first shifted by one and both runs took H:
  `/field/a018a.mld`, Esperanza, frame 6000.
- **Part L** (`scenario-partL3.log`): per page A, `down#4`, `down#4`, A. The
  part routines run, the party is fixed, and the run warps to the world map --
  `/field/sora02.mld`, then `/field/a099o.mld`, the letter 'o' being story
  stage B[6] = 14 as the research said -- from which the story itself warps
  on to `/field/a126a.mld`, the Dangral base: frame 7000 is Vyse on a cavern
  floor facing a metal installation.

Both H and L runs then saved with the one-word request (163,840 bytes written
each); `build/savetest/card-partH.raw` and `card-partL.raw` on the machine
that ran them start a run in the middle and near the end of the story. The
pad for L, as generated:

```python
ev = ["1600:start","1640:a","1800:start","1840:a","2000:start","2040:a","2240:a","2440:a","2640:a"]
ev += [f"{f}:a" for f in range(3500, 4221, 60)]    # the B/C page's choices, up by 4260
ev += ["4270:down#4", "4300:down#4", "4340:a"]      # B/C: "next"
t = 4420
for page in range(4):                                # D/E, F/G, H/I, J/K
    ev += [f"{t}:a", f"{t+60}:down#4", f"{t+90}:down#4", f"{t+130}:a"]
    t += 210
ev += [f"{t}:a", f"{t+80}:a"]                        # the L page: dismiss, take L
```


**The ending plays to "the End" and returns to the title.**
`build/scenario-ending.log`, 2026-09-23: from the save, one word at frame 3300,
`0x80310A68 = 0x4C000000` -- byte variable B[76] set to 'L' (the word was 0).
State 8's arm sends a field with B[76] == 76 to state 15 (0x80101C88), and
state 15's `fn_80101494` clears it and calls `fn_801DBE6C(9)` instead of
restarting the field: the watch on the scene id 0x803475CC reads 9 from lr
0x80101574, the branch the disassembly predicts. Scene 9 is `fn_801C8DF0`,
the ending and staff roll. Frame 5000 is a page of it -- Daigo, "The Redeemed
Prince", an epilogue card beside credits for scripting, technical support and
the manual -- and the pages change through frame 12000; frame 13000 is
"the End" in blue script on black. The ending then leaves by itself (scene 3,
the title, from lr 0x801C9078) and the scripted A presses start a new game.
No `[mmio!]`, 0 unknown FIFO bytes. The ending's streamed music (`m0N_L/R.dsp`)
opens as the credits run.

This is the last scene of the game. Together with the part select, which
reaches the world map at part L, it means the executable's beginning, middle
and end have all been run by this port -- by jumping, not by playing: nothing
yet shows the scenes *between* those points, and the census and the part
select are how to go looking.


**A forced battle is fought, won and returned from correctly; the black field
after it was the recipe's fault.** Written first on 2026-09-23 as "the player
is never re-spawned", which was wrong within the hour -- recorded here because
the way it went wrong is the lesson.

A battle forced on `a101b` with the six-word script-battle request
(`docs/research/encounters.md`: 0x803473C8 = 2, 0x803473CC = 0, 0x803473D0 = 0,
0x803473D8 = -1, 0x80346D28 = 0, 0x803473D4 = 1) runs properly: field states
8, 9, 10, 11, the battle scene, a round against a Valuan "Soldier" (frame 4000
of `build/scenario-forcebattle.log`), the win (`/BEFF/PCWIN.MLK`), and the
results screen -- 5 Gold, Vyse to Lv 2, magic experience per colour. The field
comes back (states 0, 1, 3, 4 -- the results -- 5, 7, 8) and every frame after
it is black, after a New Game as after a Continue.

**What was wrong.** A memory diff and a command-stream capture of a "black
frame" showed the player pointer 0x80347450 at 0 and no world geometry, and
were read as "the player task is gone". That capture was of a frame still in
field state 4, the results screen, where the player does not exist yet and the
world is not drawn (a read-only re-check of the same `.ram` found 0x80311AEC =
4) -- the capture came from a run whose A presses were `#4` holds, which the
results screen did not take. The "state 8" the conclusion needed was never
captured.

**What is right** (`build/scenario-fadetest.log`, 2026-09-23). The same battle,
with a capture at frame 5900 and the fade poked at 6000:

- at 5900, black on screen: field state 8, player pointer 0x80EB7BA0, and the
  stream holds **2,186 world draws** (vertex format 2) -- the room is drawn --
  under the screen fade, whose level at 0x80347510 is 1.0 and direction at
  0x80347518 is 1 (out);
- `0x80347518 <- 0` at 6000, and from frame 6100 the hold is back: Vyse by the
  save point, 95,000 colours, frame 6300 opened and read.

So the port redraws the field after a battle. What leaves it black is the
game: every map load resets the fade to black (`fn_801CBC90` from
`fn_80101264`), and `me101b`'s return-from-battle path (`sys[15] == 10000`)
fades back in only when the ship's alarm is on (flag 2556) or after event a04
(flag 3). This save has neither, and in retail a random encounter cannot happen
here at all -- the encounter check refuses while flag 1025 is set (0x800C1D48
reads bit 0x2 of 0x80310BBC, which is 0x430E here). The forced request made a
battle the game's own rules forbid in that state, and the script, reasonably,
has no path back from it. A fair test sets the alarm first
(`0x80310C78 = 0x10000000`, `0x80310BBC = 0x0000430C` from this save) or
fights where the story allows it.


**A third census: 46 more warps without a fault, then the first trap.**
`build/scenario-census3.log`, 2026-09-23, from the save, four pokes a warp, 64
warps planned. Warps 1-46 (`034e` to `116b`): 27 drawn scenes, 3 black
(`034h`, `101c`, `106b`), 1 partial (`034i`), and 15 warps to `099b`-`099q`,
which all show the same world-map frame -- the letter is ignored for map 99
and chosen from the story stage, as `ship-worldmap.md` said. 0 unknown FIFO
bytes. (Rows after the trap are not counted: the table reads
`build/frames/NNNN.png`, and those were stale files from earlier runs -- a
census table must only read frames its own run wrote.)

**Warp 47, `a116c` from `a116b`, trapped.** The map loaded, the game printed
its own error, `Chgkmap Error 9001` -- the map's script asked (op 235,
`fn_800E2924`) for camera object 9001, which the map does not have -- and then
`fn_800E1A58` followed a garbage pointer: `[mem] a load from block 800E1B2C
reached 81800018`, twenty `[mmio!]` reads of 0xCC0080xx, and a jump to
0x52EC0861, which the port stops as a guest trap (exit 3). Backtrace
800E2940 <- 8020B880 <- 8021137C <- 80212330 <- 80101A38: the script tick.
**It is the warp recipe's, not the port's.** `me116c.sct`'s loop picks its
entrance by `SWITCH (sys[15])` -- the map the party came from -- and asks for
camera 9001 only on `20000`, "arrived by loading a save". A four-poke warp
never updates `sys[15]` (the game's warp request `fn_80100178` does, through
`fn_801F7B04`; the poke bypasses it), so after census 3 started from a
Continue every map it visited believed it had just been loaded from a save.
And `a116c` has no save point -- no op 138 anywhere in its script, where
`me101b` and `me103a` each have one -- so no player can ever Continue into it
and that branch, with its camera, is unreachable in retail. **A warp must also
set `sys[15]`, the word at 0x8030E420**: 0 matches no script's `SWITCH` case
and takes each map's default entrance. Five pokes a warp, 51 a run.


**A fourth census, with `sys[15]` set: 51 warps, no fault, and `a116c` draws.**
`build/scenario-census4.log`, 2026-09-23, from the save, five pokes a warp
(name, `0x8030E420 = 0`, state 15), the 51 maps from `116c` to `238a`. Exit 0,
0 unknown FIFO bytes, no `[mmio!]`. `a116c`, which trapped in census 3, now
takes its default entrance and draws (297,703 px). 46 of the 51 end on a drawn
scene; `205a`, `209a`, `215a` and `232a` are black and `230a` is a letterbox
(86,400 px, 61 colours) -- the 2xx maps are the story's event stages, and like
`a200a` they are expected to draw nothing out of order. Frames were cleared
before the run, so every row read a frame this run wrote.

Four censuses: **169 maps loaded with no runtime fault**, every warpable map
below 500 but 14 of the 2xx event stages.


**The world map sails, and a ship battle enters the game's own way.**
`build/scenario-sky.log`, 2026-09-23, from the save. A warp by name to
`ME099A.SCT` (with `sys[15] = 0`) loads `/field/sora00.mld` and
`/field/a099e.mld` -- the letter from the story stage, as the research said --
and reaches state 8: frame 4200 is the Little Jack over Pirate Isle, its name
on a banner, the altitude gauge on the left and the compass on the right.
Holding the stick moves it: by frame 5300, after `sleft#300` and `sright#300`,
the ship is in open sky with the island behind it and the compass turned. So
the world map takes scripted stick input like the field does.

At frame 7000 the game's own ship-battle entry, opcode 210, was reproduced
without touching the state word: the name `ME500A.SCT` at 0x80305CF0, the
return name `me099a.sct` at 0x802E5E68, and 0x803472E4 = 1. The field did
exactly what `ship-worldmap.md` predicted -- `/sound/m0430.samp` (the preload
only this path makes), states 12, 13, 14, 15, 0, 1, 3, `/field/sbek0000.mld`,
5, `/field/a500a.mld`, 7, 8, and **no state 4**, so no spurious results screen
-- and frame 9000 is the ship-battle interface against The Blackbeard.

The battle then sits on round 2 with the command on Attack through frame 12400
under an A every 150 frames, and its ship panel reads Hp 0. The save is from
part A, before the party has a ship of its own (Drachma joins in part C), so
the likeliest reading is an empty ship record rather than a stuck port; not
established. A fair test is a sky random encounter (the 550-579 stages) from
the part-L save.

The fair test, same day (`build/scenario-sky550.log`): from the part-L save,
the same three opcode-210 words sending the party from `a126a` into `550a`, a
random sky encounter, with its own map as the return point. `sbek0000.mld`,
`a550a.mld`, state 8, no results screen; frame 8000 is **the Delphinus, Hp
36,000, against the Black Pirates**, four crew in the command grid, four
Prototype Cannons on the list, **round 3 of 41** -- the rounds advance under
the scripted A presses. So the round-2 stall above was the part-A save's
empty ship, and ship battles run.


**A battle the story allows: two non-Attack commands, a win, and the field
fades back in by itself.** `build/scenario-fairbattle.log`, 2026-09-23, from
the save: the ship's alarm switched on first (flag 2556 set, 0x80310C78 =
0x10000000; flag 1025 cleared, 0x80310BBC 0x430E -> 0x430C), then the six-word
battle request. A watch on the wheel's words (`SOA_WATCH=0x80346B40,16`) shows
its start slot 3 (Attack), then 2 and 1 for Vyse -- one slot per `right#4`,
which confirms the auto-repeat reading above -- and 3 then 4 for Aika (Guard).
The battle loads effect packages no run had loaded (`/BEFF/D2400600.MLK`,
`/BEFF/E6700017.MLD`), is won (`PCWIN.MLK`), and the field comes back faded in
with no poke: frame 7000 is the hold under red alarm lighting, Vyse by the
save point. The earlier black field was the story's rule, and this is the
same code path with the rule satisfied. (Each third single-step press in a
row was not taken, so Vyse committed Magic rather than Focus and Aika Guard
rather than Item; a press arriving while the wheel animates is dropped.
Space single steps further apart than 60 frames.)


**A fifth census closes the maps below 500: 189 of them, no runtime fault.**
`build/scenario-census5.log`, 2026-09-23: the last 17 -- the 2xx event stages
not yet visited, and the three maps that are warpable only because the disc
lookup ignores case (`199f`, `355a`, `398a`). Every one loaded; exit 0, 0
unknown FIFO bytes, no `[mmio!]`. Ten draw a scene (`292a`'s own script carried
the run on through `220a` and `221a`), six 2xx event stages are black like the
others out of story order, and `398a`, the developers' ship-battle select,
loaded after the last frame the run measured. With the four censuses before
it, **every warpable map numbered below 500 has been loaded by this port --
189 maps, the 186 in the disc's lower-case listing and these three -- and none
has faulted it.** What remains are the 66 ship-battle
stages (5xx), which are entered differently.


**Every ship-battle stage enters the game's own way: all 255 warpable maps have
now loaded.** `build/scenario-ships1.log` and `scenario-ships2.log`,
2026-09-23: from the part-L save (the party has the Delphinus), each of the
66 5xx stages entered as opcode 210 does -- the destination name, the return
name `me126a.sct` at 0x802E5E68 and 0x803472E4 = 1, never the state word --
one every 600 frames with an A every 150. All 66 loaded `sbek0000.mld` and
their own map, every measured frame draws (frame 10200, `518a`'s darkest, is
the opening shot of a Valuan warship's stern and propellers), exit 0 both
times, 0 unknown FIFO bytes, no `[mmio!]`.

With the five field censuses, **every one of the 255 warpable maps on the disc
has been loaded by this port, and none has faulted it** -- the one trap on the
way (`a116c`) was the warp recipe's and does not recur with `sys[15]` set.
That is coverage of the game's *data*: each map loaded, drew and ran its
script for ten to twenty seconds. It is not a playthrough; what happens deep
inside each map, and in the story sequences that join them, is still only
what the censuses happened to show.


**Twenty minutes of pseudo-random play in Esperanza: no fault, and the first
map change made by walking.** `build/scenario-soakH.log`, 2026-09-23: the
part-H save, then 321 generated pad events over 30,000 frames -- the stick held
in one of eight directions for 40-120 frames, A, B, and now and then START
into the menu and B out -- from a fixed seed, so the run repeats. Under
`SOA_STRICT=1`, which stops at the first hardware access the runtime does not
model: exit 0 at the frame limit, no `[mmio!]`, 0 unknown FIFO bytes. And the
random walk took Vyse out of `a018a` into `a018b` at frame 26122 and back at
26560 -- frame 26500 is him running across a rope bridge under a red sky, the
minimap following. **Every earlier map change in this project was the story's,
a lost fight's or a warp's; this is the first a player's input made.** The
exit is a contact volume, as FINDINGS said of the hold's, so walking needed no
position feedback, only time.

The generator is `tools/soak.py` (`--seed 7` reproduces this run exactly): an
LCG choosing, each step, a held direction (60%), A (25%), B (10%) or a menu
visit (5%), advancing 50-220 frames a step.

The same from the part-L save (`build/scenario-soakL.log`, `tools/soak.py
--seed 11`): 30,000 frames of random play in the Dangral base, exit 0, no
`[mmio!]`, 0 unknown FIFO bytes -- and the random walk left `a126a` onto the
world map (`a099o`) and came back in. Field to sky and back, by input alone.


**Saves at ten story points, and the black maps are the story's.** 2026-09-23.
The part select, generalised (page = part / 2, option = part mod 2, each page
dismissed with A before its choice), reached every part from C to K in one
batch and saved at each, each to its own card, no `[mmio!]`: C Sailors'
Island (`004a`), D Pirate Isle (`002e`), E Maramba's port (`008b`), F
Horteka (`010a`), G `230a` then by the story into the Gargantua prison
(`116a`), I Yafutoma (`019b`), J the world map then by the story into the home
base (`017b`/`017c`), K the world map (`099l`) -- exactly the destinations
`story-flags.md` read from `ME355A.SCT`. With H and L, `build/savetest/`
holds a Continue into ten points of the story.

The maps the first three censuses left black or partial were re-warped with
`sys[15] = 0` (`build/scenario-rewarp.log`). Reading each map's loop had
predicted which would change: `me013f`'s fade-ins (op 59) run only when
`sys[15]` is 0 or 131, and census 2 had left it at the story's last value.
**`013f` now draws**, as do `034h` and `034i`; `033a` and `032a` show dim
scenes. `017a`, `240a`, `028d`, `101c` and `106b` stay black, and each loop
tests story state first -- `101c` wants flag 4 clear and the story-step
bytes B[4] = 0, B[5] = 4; `106b` wants to have come from `106a` or a battle.
So of the maps any census left black, every one inspected is gated by the
story or the entrance, and the one prediction made from a script came true.


**Four more soaks, from parts D, G, J and E: no fault.** 2026-09-23,
`build/scenario-soak{D,G,J,E}.log`, `tools/soak.py` seeds 21, 33, 47 and 59,
30,000 frames each under `SOA_STRICT=1`: exit 0 all four, no `[mmio!]`, 0
unknown FIFO bytes. Part D walked off Pirate Isle onto the world map
(`a099h`). Part G fought three random battles in the Gargantua prison, lost
one to the random input, and took the game-over path -- `a090a`, then the
title and its attract demos (`a299a`, `a297a`) -- which is the game doing
what it should. Parts J (home base) and E (Maramba's port) stayed in their
maps. With the H and L soaks that is six story points and about two hours of
random play with no runtime fault.

> Correction, 2026-09-24: this said four battles. `build/scenario-soakG.log`
> loads `/battle/stsicon.mld` six times, twice per battle (`LoadCrew`, then
> `LoadAsset` from inside it), so three battles, at or after pad frames 4723,
> 11980 and 20107, and the game over at frame 20792 after the third.
> `python tools/soak.py check build/scenario-soakG.log` counts them one per
> battle. `docs/research/soak.md` traces the four to a grep that also matched
> the log's one `m0458.info` line.


**Battle soaks: random commands, no fault, and twenty effect packages.**
`tools/soak.py --battle` (single-step d-pad presses among the A presses, so
the wheel commits random commands), from the part-G save, seeds 101 and 202
(`build/scenario-bsoak{101,202}.log`), 30,000 frames each under
`SOA_STRICT=1`: exit 0, no `[mmio!]`, 0 unknown FIFO bytes. Random commands
lose fights -- both runs took the game-over path to the title and on through
the attract demos -- which is the game behaving correctly. They loaded seven
and ten distinct `/BEFF/` effect packages; across every log in `build/` that
is now **20 distinct effect packages**, against the three any run had loaded
before 2026-09-23, of 576 on the disc.

Four more battle-mix soaks the same day, from parts C (Sailors' Island), F
(Horteka), I (Yafutoma) and K (the world map), seeds 303, 404, 505 and 606
(`build/scenario-bsoak{303,404,505,606}.log`): exit 0, no `[mmio!]`, 0
unknown FIFO bytes. They are towns and the sky, so no battle came up; part I
walked from `019b` into `019c`. **Twelve soaks from ten story points, about
four hours of random play, no runtime fault.**


**H1: drawn every frame, the port runs 18-22 fps in heavy scenes, not 30.**
2026-09-24, `build/h1-*.log`, on the Ryzen Z1 Extreme handheld, on AC power,
Windows power plan "Turbo", 16 logical CPUs. Every run drew every frame
(`SOA_RENDER=1`, `SOA_SNAP=0`, headless) and the Part L runs, traced, all
loaded `a126a`. Frames over wall seconds, and the renderer's own counters per
frame:

| run | fps | fields/frame | workers busy | producer wait | fragments | `SelectThread` |
|---|---|---|---|---|---|---|
| opening, `SOA_RENDER=0` | 29.6 | 2.03 | -- | -- | -- | 48.2% |
| opening, drawn | **22.3** | 2.48 | 173.8 ms | 12.0 ms | 1.61 M | 18.7% |
| Part L 3000 frames (boot + title + 126a) | 24.1 | 2.15 | 167.4 ms | 13.7 ms | 1.45 M | 28.1% |
| Part L 9000, 8 threads | **19.4** | 2.29 | 292.9 ms | 27.6 ms | 2.40 M | 13.0% |
| Part L 9000, 4 threads | 14.6 | 2.32 | 241.3 ms | 49.1 ms | 2.40 M | 5.6% |
| Part L 9000, 15 threads | 21.4 | 2.51 | 351.9 ms | 16.4 ms | 2.40 M | 14.6% |
| Part L 9000, `SOA_SPEED=4` | 23.8 (guest 6.0) | 4.89 | 264.7 ms | 25.2 ms | 2.39 M | 1.3% |

The 6,000 frames inside the Dangral base (9000 run minus 3000 run) take 339.6
s: **17.7 fps**. At `SOA_SPEED=4` the port stops waiting for the clock
(`SelectThread` 1.3%) and its throughput there is **23.8 images a second** --
the ceiling on this machine today. Fps rises with the thread count but tails
off: 14.6, 19.4, 21.4 at 4, 8 and 15. The single-thread point was not run:
at about 3 fps the title's 92.267 s wall-clock timeout would fire before the
START at frame 1600.

The verdict on the plan's inference of "about 20 fps" for every-frame play:
**confirmed**, 17.7 to 22.3 in the scenes measured. It matters now, not only
for 60 fps: a window draws every frame, so windowed play in the Dangral base
runs near 18 fps. The fragment path costs about 122 ns a fragment in worker
time (292.9 ms / 2.40 M); 60 images a second of this scene needs about 55
ns with eight workers, 2.2 times faster, inside the plan's 1.4-2.5 times.
The first attempt at these Part L runs used the `battle` scenario's own
`SOA_SNAP=100`, rasterised one frame in a hundred, and measured 29.4 fps and
0.02 M fragments a frame -- a reminder that a scenario's `env:` lines apply
unless overridden.


**H2: the game's logic is per frame, the cap is one constant, and 60 fps has
to be interpolation.** 2026-09-24, `build/h2-base.log` and `build/h2-uncap.log`,
from the part-A save (the field at frame ~2650), snapshot mode, with S4a's
`SOA_PEEK` reading words every frame across the Continue's arrival.

Capped: the frame-start field count (0x8034768C, stored at 0x801DCB88)
steps by **2** on 395 frames of the window, by 3 on three, and by 14 and 17 on
two loading frames -- two fields a frame, 30 fps, the `cmpli r0,1` at
0x801DC4A4. The fade level (0x80347510) shows the load's fade-out, 1/7 a frame
over frames 2700-2706, and then the map's fade-in, **frames 2776 to 2805: 29
frames, 58 fields**, falling 1/29 = 0.0345 a frame.

Uncapped: `SOA_POKE` set 0x8034768C to 0 at the end of every frame from 2700
to 2955, so the frame end's pre-wait passes at once. The same fade-in ran
**frames 2817 to 2846: 29 frames, 37 fields.** Same frames, fewer fields --
the fade counts frames, not time. (It started 41 frames later because the load
is timed by the wall clock, and frames now came faster.) The poke's `was`
values stepped by 1 field on 199 frames, 2 on 51, 3 on two: uncapped, the guest
thread alone sometimes needs more than one field for a frame, as the research's
18.2 ms worst case said it would.

So:
- **PLAN's open question -- is the logic clock the retrace or the presented
  frame? -- is answered: the presented frame.** Every game frame advances the
  logic once; the frame counter at 0x803475C0 equals the port's frame number
  on every frame peeked (2650-3050).
- Uncapping is a 2x-speed mode, not 60 fps; 60 fps is renderer interpolation
  with the logic kept at 30, as `PLAN-60FPS-MODS.md` assumed. That plan stands.
- The kill condition "steps of 2 or more while uncapped" fired on a fifth of the
  frames, so H13 (guest-thread speed) comes before M11 (battle speed-up). It
  does not touch the interpolation route, which keeps the logic at 30.

S4a checked in the same baseline run: at frame 2900 `[peek] ... 8034768C =
0000178C` and `[poke] ... 8034768C <- 00000000 (was 0000178C)` read the same
value, and a watch with `SOA_WATCH_FROM=2700` printed its first line at frame
2700.


**H4: every 3D draw matches the frame before it; interpolation is viable.**
2026-09-24. Five pairs of consecutive frames, captured into
`build/perfset/<scene>/` (never `build/fifo`) and read with `tools/fifopair.py`:

| scene | draws matched | area matched, all | 3D area matched | 2D area matched |
|---|---|---|---|---|
| field, Dangral base (5000/5001) | 1144 / 1147 | 83.0% | **100.0%** of 2.05 M px | 60.8% of 1.57 M px |
| battle, `a101b` alarm on (4000/4001) | 1390 / 1393 | 99.9% | **100.0%** | 99.8% |
| ship battle, `550a` (6000/6001) | 1514 / 1665 | 98.8% | **100.0%** | 97.6% |
| cutscene, the opening (4500/4501) | 4146 / 4280 | 75.7% | **100.0%** of 0.96 M px | 61.4% of 1.64 M px |
| sky, world map `099l` (4000/4001) | 765 / 765 | 100.0% | **100.0%** | 100.0% |

In every scene every perspective draw found its partner, in the same stream
order, with identical position matrices. Read literally, the plan's kill line
(under ~90% of all area) fires for the field and the cutscene -- but the whole
shortfall is in the orthographic 2D layer, where a handful of full-screen
quads (307,200 px each, screen-space effects built from copies to texture)
change key between frames. Those do not move, so an in-between image draws
them from frame N+1 exactly as the plan's unmatched-draw rule already says.
**Judged on what interpolation must move, H4 passes everywhere, and H7 (draws
tagged by the game) is not needed.** The judgement is recorded here so the next
reader can disagree with it.

What the pairs also say:
- **The game transforms most vertices itself.** Most matched draws keep
  identical position matrices and change their *vertex data* (the field: 451
  draws by data, 2 by matrix only). Interpolating XF matrices would move almost
  nothing; the in-between image has to interpolate vertex positions, as
  frame-pacing 3(c) proposed.
- **Displacement is small.** Most matched vertices move under a pixel between
  frames; the tail reaches 8-16 px in battle and 16-32 px in the cutscene --
  the motion interpolation exists to smooth.
- **No draw comes through a display list.** Every display-list call in these
  captures (and in all 23 corpus captures) has size zero; all draws are direct.
  *Amended 2026-09-25:* the sizes are right and the reading is wrong -- the
  game records lists every frame and the port parses them as they are
  recorded; see "Recorded display lists (C5a)" below.

**H5: route (d) is dropped.** A watch on the first layer's list head
(`SOA_WATCH=0x80308CBC`, `SOA_WATCH_FROM=4000`, `build/h5-watch.log`) shows it
rewritten once a frame by `fn_801D129C`, a per-frame reset of ten render layers
in a 16 KB pool (0x804E7540), called from `fn_801D1268` at the top of the main
loop's frame. A watch over that pool for two field frames (`build/h5-pool.log`)
shows 120 stores from the reset, 18 from `fn_801D0BC0` and 3 from inside the
draw pass `fn_801D0F80`, all of the latter on the field's update path
(`801DC35C` -> `801DCCBC`). The main loop runs reset (801DCCB4), scene update
(801DCCB8), draw pass (801DCCC0), in that order. So the lists are recorded
inside the scene's update, as the plan's rule for dropping (d) asks; and since
H4 needs no draw tags, (d) has no role as a fallback either.
*Amended 2026-09-25:* the port parses a recorded list's commands at the
recording, inside that update, not at the draw pass's call -- see "Recorded
display lists (C5a)". (d) stays dropped; the order it was dropped on is
the game's, and C5b makes it the port's too.

Along the way the analyser found that `[gxr] ... texture copies` counts each
copy twice (at enqueue, `gxr.c:2002`, and when it runs, `gxr.c:1737`).


**H6: a pinned benchmark set, and today's nanoseconds per fragment.**
2026-09-24. `build/perfset/` holds the five scene pairs of H4 plus copies of
corpus 6000 and 15800 -- twelve captures, every one rendered and opened before
`config/perfset_manifest.tsv` pinned their SHA-256s: Vyse by the save point in
the Dangral base; Vyse and Aika against a Soldier under the alarm light; the
Delphinus against the Black Pirates; Admiral Alfonso on his bridge ("her ship's
in range of our cannons"); the Delphinus in night cloud on the world map.
`tools/perfbench.py run` replays each five times on a scratch copy and divides
worker busy time by the fragments processed (shaded, alpha- and depth-rejected).
On AC power, Turbo plan, 8 threads, the medians:

| scene | fragments | ns / fragment |
|---|---|---|
| field, Dangral base | 3.62 M | 74.6 |
| cutscene, Alfonso's bridge | 2.61 M | 72.9-76.7 |
| corpus 6000 / 15800 | 3.18 M / 2.31 M | 69.2 / 77.9 |
| ship battle, `550a` | 1.77 M | 102.0-107.6 |
| sky, `099l` | 1.56 M | 108.9 |
| battle, `a101b` | 0.72 M | 111.8-125.7 |
| all replays | | **85.4** |

Against the ~55-61 ns that 60 images a second needs, the field-class scenes
need about 1.3x and the sky, ship and battle scenes nearly 2x -- the battle's
light frames cost the most per fragment. These single-frame replays run cheaper
than H1's live 122 ns (292.9 ms busy over 2.40 M fragments), which carried the
live game's contention; H13-H16 report against this set, so their before and
after compare the same inputs.


**H3: the uncapped ceilings, and eight cores spent at any load.**
2026-09-24, `build/h3-*.log`, same machine and power settings as H1, 8
rasterizer threads unless stated. Every run's report now ends with a
`[frametime]` line (frames a second, wall milliseconds per frame at the 50th,
95th and 99th percentile and worst, and the process's CPU seconds).
`SOA_UNCAP=N` zeroes the frame-start field count from frame N, and
`SOA_FRAMETIME_FROM=N` starts the record at N without uncapping, so each
scene below is measured over the same frames capped and uncapped. Each run was
checked for its scene from its map loads and its snapshots: the opening's
cutscenes in `a201a`; the forced battle on `a101b`, fought from about frame
3300 to 4400 and then its results screen (the window is both); the Delphinus
against the Black Pirates on `a550a`.

Images a second over the window:

| scene, window | capped, snapshot | uncapped, snapshot | uncapped, snapshot, `SOA_SPEED=4` (guest ceiling) | capped, drawn | uncapped, drawn (render ceiling) |
|---|---|---|---|---|---|
| opening, 3600-7500 | 29.7 | 42.8 (p50 19.2 ms) | **50.3** (p50 19.4 ms) | 19.3 | **18.9** |
| battle, 3700-5000 | 29.7 | 58.4 (p50 16.7 ms) | **104.1** (p50 8.8 ms) | 29.8 | **47.8** |
| ship battle, 4000-6100 | 29.9 | 59.1 (p50 16.6 ms) | **80.4** (p50 12.4 ms) | 26.0 | **25.5** |

- **The guest's ceiling** (snapshot mode, which parses every frame and
  rasterises one in a hundred, with the clock at four times real time so no
  field wait bounds it): 50 images a second in the opening, 80 in the ship
  battle, 104 in the battle. The opening's median frame needs 19.4 ms of the
  guest thread alone, more than a field -- so an uncapped opening is guest-bound
  and H13 is what would move it. The two battles have headroom: at real time,
  uncapped, their median frame sits on the one-field floor (16.7 ms).
- **The renderer's ceiling** (every frame drawn, uncapped): 18.9, 47.8 and
  25.5. The opening and the ship battle are no faster uncapped than capped --
  they are render-bound below 30 already -- and the battle, the lightest scene
  (0.72 M fragments a frame, H6), would run a 2x speed-up (M11) at about 1.6x.
- **For interpolated 60 fps** (the logic at 30, 60 images drawn), the renderer
  needs about 3.2x in the opening, 2.4x in the ship battle and 1.3x in the
  battle, in line with H6's per-fragment gap.

H1's Part L every-frame runs, repeated with this build for H11's baseline:

| run | fps, H1 | fps, now | p50 / p95 / p99 ms | CPU seconds | cores |
|---|---|---|---|---|---|
| 3000 frames (boot, title, `126a`) | 24.1 | 24.0 | 38.1 / 57.3 / 63.9 | 1,074 | 8.6 |
| 9000, 8 threads | 19.4 | 19.0 | 55.8 / 64.7 / 77.2 | 3,989 | 8.4 |
| 9000, 4 threads | 14.6 | 14.3 | 76.0 / 90.7 / 99.7 | 2,985 | 4.7 |
| 9000, 15 threads | 21.4 | 24.0 | 37.5 / 59.6 / 64.8 | 5,243 | 14.0 |
| 9000, `SOA_SPEED=4` | 23.8 | 24.3 | 47.3 / 50.1 / 51.6 | 3,290 | 8.9 |

The worst frame of every real-time run is about 1,280 ms: the boot's load, one
frame. About a minute of the 8-thread run overlapped a test build on the same
machine. Four of the five agree with H1 within 3%; the 15-thread run is 12%
faster than H1's, so one run of one configuration is not a figure to quote
closer than about ten per cent.

**The cost that does not show in fps:** every run with 8 workers used 8.4-8.9
cores for its whole length, whatever it drew. A capped snapshot run, which
rasterises one frame in a hundred and leaves the guest idle in `SelectThread`
47% of the time, used 8.9. With 15 workers it is 14.0 cores and with 4 it is
4.7: a worker with nothing to draw spins on `YieldProcessor()` and, every
4000 turns, `Sleep(0)`, which returns at once when no other thread is ready
(`gxr.c:1414`), so the workers cost a core each whether they draw or not. On the
handheld this was measured on, that is the battery and the fan at a title
screen. It is H11's whole case, and these CPU seconds are its baseline.


**S3 and M1: the encounter accelerator fights where the story allows, and a
mod turns encounters off.** 2026-09-24, `build/s3-*.log`, `build/s3/`. Three
jobs on soakG's exact recipe (walk-mix seed 33, 33,500 frames,
`SOA_STRICT=1`, traced), each with its own card copy and its own snapshot
directory (`SOA_FRAMES_DIR`, snapshots every 100 frames), plus the
accelerator -- `soak.py --pokes --encounter-every 600`, 50 pokes of the step
counter 0x80346D28 to 100000 from frame 3200 -- and `--peeks`, the counter
read the frame after each poke. Judged by `soak.py check`:

| job | landing | battles | game over | peeks >= 100000 | verdict |
|---|---|---|---|---|---|
| `card-saved`, accelerated | `a101b` | **0** | -- | 50 of 50 | pass |
| part G, accelerated | `a116a` | **5** (4420, 9801, 12880, 15557, 20107) | 21040 | 49 of 50 | pass |
| part G, accelerated, `SOA_MODS=mods` | `a116a` | **0** | -- | 0 of 50 (all 0 or 1) | pass |
| soakG (2026-09-23, unaccelerated) | `a116a` | 3 | 20792 | -- | pass |

- **The negative control holds, and it is not an accelerator that did
  nothing.** On `card-saved`, where flag 1025 closes `a101b`'s encounters,
  every peek read the counter at 100000 or more and no battle came: the gate
  runs before the counter is read, as `docs/research/soak.md` said it would.
- **Part G fought more**: 5 battles against 3 with the same presses. Fewer
  than 50 pokes might suggest, because a battle fought by random input is
  long -- the first ran from about frame 4420 to the field's return at 9201.
  The one peek under 100000, frame 9801, is the battle itself: the check dates
  the second battle to that very peek line, and a battle resets the counter.
- **Every return to the field shows it.** Four battles came back to `a116a`
  and each return's snapshots include a lit one (single black frames at 9600
  and 12700 are the transition); the fifth ended in the game over. The
  frames were opened: the Gargantua prison's corridor after the battle at
  12880, and a battle with the wheel on Focus at 10500 -- the random wheel
  reaches past Attack.
- **M1's encounters-off mod** (`mods/encounters-off`, one line:
  `every_frame 0x80346d28 = 0 when scene=6`) loaded against the real DOL's
  SHA-1, applied 32,039 times from frame 368, and the same accelerated job
  fought nothing, its peeks at 0 or 1. The peek difference between the two
  part-G jobs is what shows this check could have failed.
- A new question, not a failure: `[gxr] LINEPTWIDTH (BP 22 00060D) asks for
  lines 2.17 pixels wide; lines are drawn one pixel wide` at frame 18380, in a
  battle on `a116a`.

Both slices' criteria are met; the accelerator fights where the story allows
and nowhere else.


**M2: a safe point at the top of the loop, and a tick the port can let go.**
2026-09-24, `build/m2-*.log`. `config/hle.txt` now binds 0x8023F704,
`VIGetRetraceCount` (`lwz r3,-27836(r13); blr`), to `runtime/tick.c`, which
tells its callers apart by `lr`: at 0x801DCB88, the top of the main loop, it
first runs the safe-point callbacks; at 0x801DC49C, the frame end's spin, once
unlocked, it answers the frame's start plus one so the spin leaves after the
one field `fn_801C6248(0)` waits for. Everywhere else it is the original, which
self-test case 74 holds against the recompiled twin over 200 random counts and
four call sites (answering the count plus one at one site fails it at round
2). `SOA_UNCAP=N` now unlocks this tick instead of zeroing 0x8034768C, so the
word the game stored is left as it wrote it.

- **Safe points equal presented frames, less one**: 1,999 over the title
  scenario's 2,000 frames, 1,499 over 1,500, 4,999 over 5,000. The constant
  one is the first frame, presented before the loop's first pass through its
  top; a leak would grow with the run.
- **Unlocked from frame 1, the title runs a frame a field**: peeks of the
  frame counter 0x803475C0 over frames 1000-1255 step one field on 253 of 255
  frames and two on the other 2 -- 59.5 frames a guest second -- and the
  counter equals the port's frame on every one. 1.12 retraces a frame over the
  run, against 2.09 capped.
- **The audio is as it was**: the same AX opcodes, no abandoned lists, and
  output near 30,000 samples a wall second both capped and unlocked. The
  music keeps real time while the frames double.
- **The same ceiling as H3's mechanism**: the uncapped battle in snapshot mode
  (`a101b`, frames 3700-5000) ran 58.7 a second, p50 16.7 ms, against H3's
  58.4, with 1.80 retraces a frame over the whole run in both.
- With the tick locked: the self test's 74 cases, `title --check` 4/4 and the
  replay 23/23 at 1, 2, 3 and 8 threads all pass.


**H11, the workers' half: an idle pool sleeps, and the title costs 1.2 cores
instead of 8.8.** 2026-09-24/25, `build/h11-*.log`, `build/h11ab*-*.log`. A
worker with nothing to draw used to spin on `YieldProcessor()` and `Sleep(0)`,
which returns at once when no other thread is ready (FINDINGS "H3"). Now it
spins 4000 turns for the rest of a burst and then waits on `g_published` with
`WaitOnAddress`; the producer calls `WakeByAddressAll` after a publish only
when a sleeper count says a worker is asleep. Both sides are interlocked, so a
publish between a worker's last look and its wait is either seen or wakes it,
and the wait's 50 ms bound keeps the idle clock charged.

| run | CPU seconds before (H3) | after | cores before | after |
|---|---|---|---|---|
| title scenario, 2000 frames | 620 | **84** | 8.8 | **1.2** |
| capped battle, snapshot mode (`a101b`, 5000 frames) | 1,527 | **207** | 8.9 | **1.2** |
| Part L, every frame drawn, 9000 frames | 3,989 | 3,230 | 8.4 | 6.5 |

Frame rate, measured interleaved because this machine drifts: the same
per-fragment benchmark read 85.4 ns (H6, the morning), 98.0 and then 113.3 to
127.8 over one later batch, on identical code. On H1's 3000-frame Part L run,
drawn every frame, alternating builds:

| build | fps | p99 ms | CPU seconds |
|---|---|---|---|
| spinning | 20.8, 22.2, 23.0 | 104, 87, 74 | 1,098, 1,086, 1,083 |
| sleeping | 23.1, 23.5 (and 14.6) | 72, 71 (and 235) | 728, 721 (and 803) |

The 14.6 run was slow everywhere, not in waiting: the producer's own vertex
setup, which this change does not touch, took 13.3 s against 3.6-4.5 s in the
other five, and decode, prepare and guest code were all about 1.4x slower --
the machine, not the pool. Per fragment, on the H6 set interleaved with the
spinning build, spin windows of 4000, 40,000 and 400,000 turns read 118.2,
116.0 and 110.6 ns against 113.3 and 127.8 for the spinning build before and
after: no difference the drift does not swamp, so the shortest window, which
saves the most, stays. Retraces a frame over the title are 2.09, as before;
`title --check` 4/4 and the replay 23/23 at 1, 2, 3 and 8 threads.

**Measure on this machine interleaved from now on.** A figure from one run an
hour ago is not a baseline: the same code moved 15% within a session.

Not done: the other half of H11, the guest's idle loop, which still spins on
the guest thread -- most of the 1.2 cores the title now costs.


**M3a: native mods load as `mod.dll`, and their callbacks fire where they
say.** 2026-09-25, `build/m3-*.log`. A mod folder may now hold a `mod.dll`
beside, or instead of, its `patches.txt`: once `mod.ini`'s name, API and DOL
SHA-1 check out, the port loads it by full path and calls its exported
`soa_mod_init` with `SoaModApi` (`runtime/soa_mod.h`, version 1: big-endian
guest memory that refuses what a patch line would -- code, the hardware
window, unaligned, outside RAM; the scene, field state, committed map, story
flags and frame; `on_frame_end`, `on_safe_point`, `on_map_loaded`,
`on_scene_change`; a log line under the mod's name). A DLL that exports no
`soa_mod_init`, or whose `soa_mod_init` declines, is refused whole, its
callbacks and patches taken back. The recording names it with a hash that
covers the DLL's bytes. `on_map_loaded` is the field running (state 8) after a
load state (3 or 5), which every warp and every return from a battle passes
through, so a reload of the same map counts.

`examples/mods/map-log` (the template: it logs map entries and scene changes
and changes nothing), built with `cl /LD` and run with
`SOA_MODS=examples/mods`:

| run | safe points (tick) | `on_safe_point` calls | field load lines in the trace | `on_map_loaded` calls |
|---|---|---|---|---|
| title scenario, 2000 frames | 1,999 | 1,999 | 1 (`a299a`) | 1 |
| forced battle on `a101b`, 6500 frames | 6,499 | 6,499 | 3 (`a299a`, `a101b`, `a101b` again after the battle) | 3 |

The scene changes it logged tell the game's shape at a glance: 0 -> 2 -> 3
through the boot, 6 (the field: the title's demo) at frame 369, 3 at the New
Game or Continue, 6 on `a101b`, 7 for the battle from frame 3349 and 6 again
at 5117. With mods unset the self test (74), `title --check` and the replay
are unchanged and no `[mod]` line prints.

Still M3's: `pad_filter` (M3b, in `si.c`) and the renderer's texture and
projection filters (M3c).


**M3b: a mod decides what the game reads from the controller.** 2026-09-25,
`build/m3b-*.log`. `SoaModApi` gains `pad_filter`, appended to the table so a
DLL built before it still loads (it checks `api->size`). `si.c` hands every
read to the filters after the person's input and `SOA_PAD` are merged and
after `SOA_PAD_RECORD` has its copy, and before the game and the `[si]` log
see it: a recording holds the input as given, and a replay made with the same
mod applies the filter again. `SoaPad` mirrors `si.c`'s `PadState` byte for
byte, which a typedef in `si.c` now refuses to compile without. The title
scenario, with `examples/mods/map-log` logging scene changes beside each
filter:

| filter | `title --check` | START read at 1600 | the title's demo left | filtered reads |
|---|---|---|---|---|
| passes everything through | 4/4 | yes | frame 1616 (START) | 4,181 |
| drops START | 4/4 | no | frame 1656 (the A at 1640) | 4,188 |
| drops every button | 4/4 | no | **never** | 4,174 |

The plan's mutation -- "a filter that swallows START keeps the title run on
the title" -- was wrong in its premise: A also leaves the attract demo, so
dropping START only moved the scene change 40 frames and the New Game choice
was never made, and `title --check` has no map to assert. Dropping every
button is the mutation that holds: the game never leaves the demo. A recording
made with the pass-through pair names both, with hashes over each DLL:
`# config ... mods=map-log:132780d5,passthrough:4f07bb15`.


**M3c, the projection: a mod can change the view, and one that does not
changes nothing.** 2026-09-25, `build/m3c-*`. `SoaModApi` gains
`projection_filter`, appended. `gxr.c` hands a mod GXSetProjection's six
parameters and whether it is orthographic once each time the game sets a new
projection, cached against XF 0x1020-0x1026's raw words, never per vertex;
with no filter the transform is the code it was. It runs on the thread that
parses the command stream, the guest's.

**The live title is not a hash oracle.** Two title runs with no mod at all
differ on 22 of their 40 snapshot hashes: loads run on the wall clock, so the
same frame number is a slightly different moment of the same animation. The
oracle is the replay instead -- mods load before `main.c` reaches `--replay`,
so a captured frame renders through the filter, deterministically. (Not
through `scenario.py replay`: it drops every `SOA_*` variable from the
environment it hands the port, on purpose, so each capture ran directly.)

| mod | captures matching `config/fifo_manifest.tsv` |
|---|---|
| a filter that changes nothing | **23 of 23** |
| a wider view (`p[0] *= 0.75` when perspective) | 4 of 23 -- the four boot frames (100-700), text and logos drawn only orthographically |

Capture 6000 was opened wide and as pinned: the wide one shows more of the
room left and right with the figure narrower, which is the change asked for.
What there is to draw in the widened margin is still the game's decision --
it culls against its own frustum -- and a real widescreen mod starts there.

The texture provider, M3c's other half, remains.


**M3c, textures: a mod can replace any texture by its content hash, at any
size.** 2026-09-25, `build/m3c-tex*`. `SoaModApi` gains `texture_provider`,
appended. Each time `gxr_tev.c` decodes a texture it asks the providers, with
the texture's source hash -- its bytes, and its palette for the indexed
formats, the key the cache already uses and the same from run to run -- and
the decoded base level. The first mod to answer with an RGBA8 image of any
size replaces it, copied at once, as one level; an entry marked replaced is
not decoded again for wanting more mip levels, which it would otherwise be on
every draw. The sampler scales by the level's size over the game's
(`gxr_tev.c`, `u = s * scale_s * lw / w`), which is what lets a larger image
sit where the original did.

Through `--replay` over the 23 pinned captures, against unmodded renders:

| provider | hashes matching the manifest | mean difference per pixel, R / G / B (median over captures; worst) |
|---|---|---|
| never answers | **23 of 23** | 0 |
| every texture at twice the size, nearest neighbour | 0 of 23 | 1.41 / 1.32 / 1.33 (worst 3.45 / 3.38 / 3.78) |
| every texture with green and blue halved | 0 of 23 | 0.17 / 23.85 / 39.60 (worst 2.58 / 114.84 / 114.86) |

Capture 6000 was opened through both: at twice the size every texture is in
its place, the circuit lines where they were and a little sharper, since a
doubled image gives the bilinear filter half the blending and the mipmaps
are gone; tinted, every surface is. That is the check a texture pack needs:
right place, right scale, and nothing moves when the provider declines.

With that, M3's criteria are met: `mod.dll` with a versioned API, the safe
point, map loads and scene changes, the pad filter, the projection filter
and the texture provider, each held by tests that build a DLL against
`runtime/soa_mod.h`, and CI's Windows leg builds and loads the example.


**A review of the mod layer found eleven defects, and all are fixed.**
2026-09-25. A workflow of four reviewers (memory, threads, the contract with
everything off, semantics against the plan) read `runtime/mod.c`, `soa_mod.h`,
`tick.c`, the frame hook, the pad, projection and texture hooks and the
frame-time record; each of the sixteen findings went to a skeptic told to
refute it, and none was refuted. Merged, eleven defects:

| defect | severity | fix |
|---|---|---|
| a callback registered after `soa_mod_init` returned 1 and was never called: the dispatchers are wired once, when loading ends | medium | registration is open only inside `soa_mod_init`; later it returns 0 |
| an `on_map_load` patch skipped the reload after a battle, which puts the map's words back as the disc has them, while `on_map_loaded` counted it | medium | a load state (3 or 5) seen since the field last ran is a load, as the safe point already said |
| the `[frametime]` report read the buffer twice across a `malloc` on the UI thread while the guest thread appended and reallocated it (a window closed mid-frame) | low | one lock, and the report works from a copy taken under it |
| mods loaded before the low-memory block was written, so an init's reads saw zeros and its writes were overwritten | low | `mod_load` runs after `setup_low_memory` |
| the recording's mod list kept a half-written entry and dropped later mods past 300 bytes | low | whole entries only, and the rest as `+N more:hash` |
| mod folders with names of 64 characters or more, or past the 64th, were skipped without a word | low | each is named with the reason |
| a `patches.txt` or `mod.ini` line over 511 characters was cut, so `state=18` could read as `state=1` | low | refused with its line |
| a texture over 4096 on a side was dropped silently, and blocked the providers after it | low | refused with a line, and the next provider is asked |
| `SOA_UNCAP` was not in a recording's config line, though it changes frames per second of guest time | low | named there when on; a line without it is unchanged |
| the example refused a port with every member it uses because its table was smaller than the header's | low | `SOA_MOD_HAS(member)`: check the last member used |
| `si.c`'s `PadState` mirrored `SoaPad` by size only | low | `PadState` is `SoaPad` |

Each has a test that fails without its fix, bar the lock (a race of
microseconds) and the load order (the one `main.c` move), which the title run
with `examples/mods/map-log` covers: the same safe points and map load as
before. The self test, `title --check` and the replay are unchanged.


**M5: a settings file, so the port starts without a terminal.** 2026-09-25.
`runtime/settings.c` reads `soa.ini` beside `soa.exe` before any switch is
read: `disc` names the extracted directory, and `render`, `window`, `scale`,
`threads`, `mods`, `card`, `record`, `nosound` and `uncap` each set their
switch where the environment has not -- a variable set in the environment
wins, and the port says so; a key it does not know is named with its line. The
self test never reads it, and `scenario.py`'s runs and replays and
`perfbench.py` run with `SOA_SETTINGS=0`.

Checked by running it: with `gen/soa.ini` naming only the disc and `nosound`,
`soa.exe` started with no arguments from `build/` found the disc through the
file, booted and ran 300 frames. With a `soa.ini` that turned on everything --
`render`, `window`, `scale`, `threads`, `mods`, a card path, a recording path,
`nosound`, `uncap` -- `title --check` still held 4 of 4, and nothing of the
file reached the run: no `[settings]`, `[mod]` or `[uncap]` line, no
recording written. With no file, nothing changes. The owner's own check --
turning an enhancement on and off without a terminal -- is still the owner's to make.


**M4: a mod can call the game's own functions, at the safe point.**
2026-09-25. `SoaModApi` gains `call_guest(addr, ints, n, floats, n, &r3,
&f1)`, appended. It runs the function as `irq.c` runs an interrupt handler --
every register saved, up to eight ints in r3-r10 and eight floats in f1-f8,
the function dispatched, r3 and f1 taken, every register put back -- so the
frame the game is about to run never sees the call; a GQR the callee left
changed is put back and reported. It is allowed only inside an
`on_safe_point`, `on_map_loaded` or `on_scene_change` callback, never in a
handler, and only at the start of a function this program holds: the
recompiler now emits `dispatch_known(addr)` from the same list as `dispatch`,
because dispatching any other address is a trap that ends the run. r2 and r13
must be the game's small-data bases.

- **Self-test case 75** calls `strlen`'s entry through the same code with every
  register set to a pattern first: the length comes back, and r1, r2, r13, the
  non-volatile registers, LR, CTR, CR and the GQRs are as they were. Leaving
  the general registers unrestored fails it.
- **Refusals** (`test_mods.py`): from `soa_mod_init`, from a frame end (inside
  the XFB copy), inside an interrupt handler, at an address inside a function
  rather than at its start, and with r2 and r13 not the game's -- each with a
  line saying which.
- **Old DLLs still load:** `examples/mods/map-log` built against the header
  as it stood before M4 (`git show 3a26618:runtime/soa_mod.h`, no
  `call_guest`) loaded on this port and logged its map load, because it
  checks the table reaches the last member it uses.

With M1-M5 the mod framework the plan asked for is in: data patches, a safe
point and tick, native DLLs on a versioned API with filters for input, the
view and textures, calls into the game, and a settings file.


**H8, the presenter: built and measured here; the owner's display runs at
85 Hz.** 2026-09-25, `build/h8-*.log`. The window now presents through a DXGI
flip-model swap chain: each new frame is scaled by whole pixels on the CPU
(as GDI's COLORONCOLOR did) into the back buffer and presented with a sync
interval chosen from the display's own refresh period -- two refreshes at
60 Hz, four at 120, and the next refresh at a rate that is not a multiple of
30. `SOA_PRESENTER=gdi` keeps the old path (GDI on an 8 ms poll), which is
also the fallback if DXGI cannot start. Both paths record every present's
time; the report gives the histogram in refreshes and the guest's VI rate
against the display's. Nothing touches `g_screen`: the self test,
`title --check` and the replay are unchanged.

The first windowed runs (the `window` scenario, frames 0-2400, then 0-1500)
found what the plan did not assume: **the display is set to 85 Hz** (DWM
measures 11.76 ms; the display mode says 85). A 30-a-second frame is 2.83
refreshes there, so no presenter can hold every frame the same number of
refreshes. Over the opening, which draws at about 25 frames a second here
(H1, H3), both paths show the same shape -- intervals of 3 refreshes 1,341
and 1,363 times, 4 or more 1,012 and 1,015, p50 31.9 ms -- because the game,
not the presenter, sets the pace below 30. And the guest's VI, which should
run at 60 Hz of guest time, ran at **51.3 Hz**: a retrace the guest reaches
late is delivered once and the lost time is not made up (`irq.c`'s
late-retrace rule), which is H9's subject, now with a number.

For the owner: set the display to 60 or 120 Hz (or leave variable refresh on,
if the panel has it) for the presenter to pace 30 frames a second evenly,
then run the `window` scenario for H8's session and say whether it looks
smoother than `SOA_PRESENTER=gdi`. Until then H8's pacing target is unmet
for a reason outside the port.


**H10: the in-between image is right in all five pairs, offline.** 2026-09-25.
`soa.exe --replay F F+1` renders F recording each draw, F+1 as it is, and F+1
again with every matched draw's clip-space positions moved halfway
(ARCHITECTURE section 12). `python tools/midpoint.py` judged the five H4 pairs
in `build/perfset` at 8 threads (and again at 1), on scratch copies checked
against `config/perfset_manifest.tsv`:

| scene | matched | from F+1 | copies skipped | px differing: mid vs F+1 | mid vs F | t=0 vs F |
|---|---|---|---|---|---|---|
| field, Dangral base (5000/5001) | 1144 / 1147 | 3 | 2 | 22,240 | 38,283 | 30,379 |
| battle, `a101b` alarm (4000/4001) | 1390 / 1393 | 3 | 0 | 7,933 | 249,666 | 249,235 |
| ship battle, `550a` (6000/6001) | 1514 / 1665 | 151 | 0 | 583 | 13,646 | 13,264 |
| cutscene, the opening (4500/4501) | 4146 / 4280 | 134 | 2 | 20,332 | 32,262 | 26,162 |
| sky, world map `099l` (4000/4001) | 765 / 765 | 0 | 0 | 9,382 | 9,295 | 468 |

Every check passed in every pair: pass 2 is F+1 exactly as a single replay
draws it; the pairs the renderer wrote are `fifopair.match`'s, the same count
H4 measured; the images are identical at 1 and 8 threads; F paired with itself
gives F and t=1 gives F+1; and a copy of F+1 with one texture address changed
loses the same pair in both implementations. None was demoted (no draw changed
between 2D and 3D) and none exceeded capacity. `tools/midpoint.py` first
exempted the field and the cutscene from the t=1 and (F, F) checks, on the
guess that a draw there samples a copy made later in its frame. Both came out
exact, so the exemption was taken out and the checks are required everywhere.

**How the images were checked.** For each scene F, the in-between image, F+1
and a difference image (magenta where the in-between image differs from F+1)
were opened, and crops of the moving parts were scaled 2-3x side by side:
Vyse's idle animation (field), a crewman's helmet and shoulder (cutscene), the
middle character with its selection ring and swinging blade (battle), and the
ship (sky). In each the 3D sits between its two positions with no cracks, gaps
or stretched triangles. The 2D layer holds still -- the HUDs, the compass, the
dialogue text and the ship battle's menus are unchanged against F+1 -- and
every unmatched draw, in every pair, is 2D (fifopair: 151 in the ship battle
covering 21,888 px, 134 in the cutscene, 3 in the field and in the battle),
drawn from F+1 as the rule says. No midpoint hash is pinned: the eye is the only reference an
in-between image has (CLAUDE.md, "the first bless").

**The large displacements are not motion.** The report's "largest
displacement" (1,324 px in the field, 97.5 px in the cutscene) and its "draws
over 32 px" (10 and 147) come entirely from vertices projected far off
screen -- (35763, 20470) in the field, y near -44,900 in the cutscene -- where
a vertex close to the eye plane swings thousands of pixels for a tiny change in
w. Those draws cover no pixels in either frame. The lerp is in clip space, so
they come to no harm. The largest real motion on screen is about 16 px
(battle).

**What positions-only costs.** The t=0 image has F's positions with F+1's
colours and texture coordinates, so its difference from F is exactly what
interpolating positions alone leaves at 30 Hz. In the battle nearly all of it
is the alarm's lighting pulse, 1-8 levels over 249,000 pixels, which cannot be
seen. In the field it is the save point's scrolling light beams, the
rain/ground sparkle and Vyse's vertex shading (1,363 pixels off by 33 or more).
In the cutscene it is the dialogue line fading in and the lamps' glow (1,831).
Those animations will step at 30 Hz inside a 60 Hz image: visible at most as a
slight texture judder, and not a reason to grow the record before H16. H17a's
headless run, on more scenes, says whether texture coordinates should join the
positions.

What the midpoint also confirmed: the synthetic test
(`tools/tests/test_gxr_pair.py`) captures frames through the real capture path
and shows a triangle moved by 2d landing at d pixel for pixel. It shows the
same under perspective at constant depth. A vertex moving in depth lands at the
view-space midpoint (screen x 368), not the screen-space one (384). Four
deliberate breakages of the lerp and the copy rule (weights swapped, w not
lerped, the clear dropped, copies not skipped) each fail the test written for
them.


**H12: a texture is hashed once an epoch, not on every lookup, and the cache
holds 1,024.** 2026-09-25, `build/h12ab-*.log`, `build/h12ab-speed4-*.log`,
`build/h12-verify-*.log`. Every texture lookup used to hash all of the
texture's source bytes and compare against each of 256 cache slots. Over the
35 captures in `build/fifo` and `build/perfset` that was 16-39 MB hashed a
frame in the heavy scenes, one texture up to thirty times over, where the
distinct textures come to 0.8-2.0 MB. Now each entry remembers the *epoch* its
hash was taken in, and a lookup in the same epoch trusts it. The epoch moves on
everything that can change texture memory under the renderer:

- **BP 0x66**, the texture-cache invalidate that `GXInvalidateTexAll` and
  `GXInvalidateTexRegion` write, which the hardware itself needs before it will
  sample texels the CPU rewrote. The game writes it twice a frame (four times
  when it copies to texture), in every capture;
- **every EFB copy**, to a texture or to the screen, so every frame end too;
- **a replay's RAM load**, which replaces memory with no BP write.

The cache grew from 256 entries to 1,024, found through an open-addressed index
(the old scan of every entry would be 4.5 million compares a frame at 1,024).
The hash function is unchanged, as M9 needs.

**What it saves**, on H1's 3000-frame Part L run drawn every frame, measured
interleaved (new, base, new, base):

| | prepare | decode | fps | p50 | CPU |
|---|---|---|---|---|---|
| base | 3.86 / 3.91 ms | 2.76 / 2.74 ms | 24.7 / 24.7 | 36.3 / 36.1 ms | 657 / 657 s |
| H12 | 0.21 / 0.21 ms | 2.70 / 2.72 ms | 24.3 / 24.3 | 37.5 / 37.6 ms | 615 / 623 s |
| base, `SOA_SPEED=4` | 3.88 / 3.82 ms | 2.49 / 2.45 ms | 35.9 / 36.0 | 27.0 / 27.3 ms | 613 / 622 s |
| H12, `SOA_SPEED=4` | 0.21 / 0.21 ms | 2.59 / 2.53 ms | 37.0 / 37.2 | 23.5 / 23.8 ms | 595 / 591 s |

Prepare falls from 3.9 ms a frame to 0.21, so prepare and decode together fall
from 6.6 ms to 2.9: the plan's "at least halved" is met. Decode is unchanged,
as it should be: the same 82,600 decodes, none of them an eviction, all of them
textures whose bytes did change (copies to texture and the game's own rewrites
between frames).

**Where the saved time goes.** With the clock out (`SOA_SPEED=4`) it is
throughput: 3.2% more frames a second and 3% less CPU. At real speed the paced
run's frame rate *fell* 1.6% in both pairs, 24.7 to 24.3. The producer's wait
for the workers rose by 8.6 s, about what prepare saved, because the run is
raster-bound at the drains around every filtered copy (H14): a faster producer
reaches each drain sooner and waits there longer. And the guest received fewer
retraces: a mean VI period of 19.40 ms against 18.96. Prepare's cost was spread
over hundreds of per-draw slices, and the guest can take a retrace between any
two of them. The drain's wait is one block of host code, and a retrace that
comes due during it is delivered late, the lost time never made up (`irq.c`'s
late-retrace rule). That reading is consistent with the numbers but was not
measured directly. Any producer speedup will show the same until H14 removes
the drains or H9 locks the VI, and paced fps should be re-measured after
either.

**The risk, measured.** The rule cannot see a texture the CPU or a DMA rewrites
*within* an epoch, with no invalidate, copy or frame end between two uses. The
hardware would not see that rewrite either unless the texture had left its
cache, so a game that does it is relying on luck; but it had to be measured,
not assumed. `SOA_TEXVERIFY=1` hashes every lookup as before and counts each
texture whose bytes changed inside an epoch. Over four live scenes, 24,500
frames and 2.57 million lookups, it counted none:

| scene | frames | lookups | changed inside an epoch |
|---|---|---|---|
| `title --check` | 2,000 | 25,873 | 0 |
| Part L, drawn every frame | 3,000 | 2,118,255 | 0 |
| `opening` | 7,500 | 153,484 | 0 |
| `battle` | 12,000 | 274,868 | 0 |

That is evidence about those scenes and not the whole game (CLAUDE.md). The
switch stays in the port for the next scene someone suspects. The `battle` run
filled all 1,024 entries and evicted 88, one or two at a time; the thrash
warning (256 in one frame) did not fire in any run.

**Checks.** Replay is 23/23 with every hash unchanged at 1, 2, 3 and 8 threads.
`tools/midpoint.py` passes all five pairs with the same images. The self test
and `title --check` pass. `tools/tests/test_gxr_texcache.py` includes
`gxr_tev.c` whole: the index stays whole through 30,000 lookups over three
times its keys; LRU order; hashing once an epoch and again after it moves;
`SOA_TEXVERIFY` catching a rewrite; the epoch-moving BP writes; a TLUT load's
dropped decode rebuilt in place. Five deliberate breakages were each caught:
algorithm R off by one, an evicted key left in the index, never hashing again,
BP 0x66 ignored, a TLUT load forgetting the key. An adversarial review found
one defect, now fixed: `tools/soak.py` would have raised the new `[gxr]
textures:` report line as a question in every rendering soak.


**H14: the drains around every copy are gone; the win is pacing, not
throughput.** 2026-09-25, `build/h14-*.log`, `build/h14ab*-*.log`. Every copy
the game makes is filtered (the deflicker reads three rows), so every copy
reads rows other workers own, and until now each was bracketed by two full
drains: the producer -- the guest thread -- stopped until the workers had
drawn the whole frame so far, twice a copy. Step 0 split the producer's wait
by reason (the report's new `[gxr] waits:` line). On H1's 3000-frame Part L
run it was 43.6 s: **copy-first 37.9 s** (the drain before each frame's first
copy, usually the screen copy -- the whole frame), copy-before 3.8 s,
copy-after 1.8 s.

What replaced them (ARCHITECTURE sections 3, 6, 9 and "The renderer is
software"):

- **fences between the workers.** A copy that reads rows other workers own
  carries an entry fence (no worker starts it until every worker has finished
  everything before it); the command after it carries an exit fence (no worker
  starts that until every worker has finished the copy: PLAN C3's race). Every
  screen copy is entry-fenced, so `gxr_presented` still counts whole frames.
  A fence reads only the other workers' `g_ran` counts and is never above its
  own command, so the worker furthest behind always runs;
- **a wait for one copy, not a drain,** wherever the producer reads guest
  memory a queued copy may be writing -- a texture, a palette, vertex arrays, a
  display list, an indexed XF load, a hook's peek, poke or mod access -- found
  in the list of copy destinations, now with exact extents and command
  numbers;
- **the frame gate:** the one full drain a frame, at the next frame's first
  command, which recycles the arena, the copy list and the graveyard and keeps
  one frame in flight while the guest's frame end runs against the workers'
  tail;
- **`SOA_GXR_DRAIN=1`** puts the old drains back in the same binary, as the
  oracle and the fallback.

Every pixel is unchanged: replay 23/23 at 1, 2, 3 and 8 threads, `title
--check` 4/4, `tools/midpoint.py` 5/5 with the same images.

**The token wait, tried and taken out.** A first version made each draw
token (`GXSetDrawSync`, BP 0x47/0x48) wait for the copies before it, so that a
game reading a copy's memory after its token would still see it finished. It
cost the whole gain: the game writes its token at the top of every frame's
stream, *before* the frame's logic, so the wait there held the logic behind
the last frame's drawing. On Part L 3000 the wait simply moved from copy-first
(37 s) to token (38.4 s) and fps did not move (24.6 / 24.4 against the drains'
24.6 / 24.5). Tokens are now answered as they are parsed, as they always were,
and counted: 6,602 in that run arrived with a copy still running, two a frame.
`SOA_GXR_TOKENWAIT=1` puts the wait back. `GXDrawDone`, which is how a game
waits before reading what was drawn, still drains. Store watchpoints over both
screen-copy destination pairs (`SOA_WATCH=0x8035D4E0,0x96000` and
`0x804024E0,0x96000`, frames 2700-3000) saw no CPU store at all; a CPU *read*
of a copy after its token cannot be watched, and the copies land in the XFB
pair, which on the console only the video interface reads.

**Measured, interleaved, one binary (N the fences, D `SOA_GXR_DRAIN=1`),** the
final build, in one session:

| run | fps | p50 | p95 | p99 | producer wait a frame | VI | CPU |
|---|---|---|---|---|---|---|---|
| Part L 3000, D | 24.6 / 24.5 | 36.9 / 36.6 ms | 54.9 / 54.6 | 60.0 / 60.8 | 14.2 / 14.2 ms | 52.1 / 51.9 Hz | 612 / 603 s |
| Part L 3000, N | **27.0 / 27.0** | **33.4 / 33.4 ms** | 53.6 / 53.3 | 57.6 / 57.2 | **2.6 / 2.7 ms** | **57.3 / 57.2 Hz** | 629 / 621 s |
| Dangral window (3000-9000), D | 18.7 | 53.6 ms | 58.5 | 65.7 | 36.9 ms | 44.4 Hz | 2,894 s |
| Dangral window, N | 18.9 | 52.6 ms | 57.1 | 63.4 | 21.9 ms | 45.9 Hz | 3,003 s |
| Part L 3000, `SOA_SPEED=4`, D | 37.9 / 38.4 | 23.5 / 23.2 ms | 47.7 / 48.3 | 50.5 / 51.3 | 14.6 / 14.4 ms | | |
| Part L 3000, `SOA_SPEED=4`, N | 38.0 / 37.5 | 24.0 / 24.1 ms | 48.5 / 49.7 | 51.0 / 52.9 | 12.8 / 13.1 ms | | |

(The `SOA_SPEED=4` rows are from the build before fence parking, below; an
earlier session of the fences gave 27.2 / 26.9 and 19.0 / 18.9 against the
drains' 24.6 / 24.4 and 18.7 / 18.4, so the table is not one lucky pair. The
wait and VI columns divide whole-run figures by the frames counted, so they
compare arms, not scenes.)

Read together:

- **At real speed the port runs 10% faster where it is not raster-bound**
  (Part L 3000: 24.55 → 27.0 fps, the median frame 36.8 → 33.4 ms), and the
  reason is the retrace: the guest no longer sits in long drains, so the
  retraces it waits on arrive on time (VI 52 → 57 Hz). That is H9's late
  retrace, recovered from the other side.
- **With the clock out there is no throughput gain** (`SOA_SPEED=4`: 38.0 /
  37.5 against 37.9 / 38.4): the wait moves from the copies to the gate. H14
  removes serialization the pacing felt, not work.
- **In the Dangral base, which is raster-bound, it is about 1%** (18.7 → 18.9 fps)
  and 2-6 ms off the slow frames. The workers are busy about 85% of every
  frame there, so the producer's saved time turns into waiting: the wait left
  is almost all **hazard, 128 s over 12,670 reads** of the frame's two copied
  textures, which wait for everything drawn before their copy. Copy images
  (the plan's Step 6: the copy decodes its own texture and the sampling draw
  waits at a fence in the pool instead of stalling the guest) would remove
  that wait, but in a raster-bound scene the workers are the critical path, so
  it waits for H15, the pixel path, which is what the Dangral base needs.

**The plan's done line, restated.** H14 asked for producer wait per drawn
frame "down to the level of the copies alone" and predicted ~45 ms falling to
~30. Neither can happen while the scene is raster-bound: a producer with 22 ms
of work a frame and workers with 44 ms must wait the difference somewhere, and
it now waits at the copies' hazard and the gate instead of around every copy.
What H14 can be judged on, and meets: no copy drains (the waits line has no
copy-first, copy-before or copy-after), every hash unchanged over the replay,
the overlap test green with its nine breakages red, and the paced fps up where
the port is not raster-bound.

**CPU.** The first build's fences spun -- `YieldProcessor`, then `Sleep(0)`,
which returns at once when no other thread is ready -- and cost 12-13% more
CPU than the drains (Part L 3000: 679 / 689 s against 598 / 615 s; the 9000
run 3,240 / 3,274 s against 2,868 / 2,907 s), past the plan's 10% line. A
fence now parks in `WaitOnAddress` on the count it waits for after 4,000
spins, as H11's idle workers do, and a worker raising its count wakes parked
waiters only when there are any. The final build's cost is 3-4% (629 / 621 s
against 612 / 603 s, for 10% more frames; 3,003 s against 2,894 s), and its
frame rates are the first build's.

**Tests.** `tools/tests/test_gxr_overlap.py` (20) drives filtered copies, a
full-screen draw over their taps, a texture, a palette and indexed vertex
colours read from copy destinations, a copy written twice to one place, a
screen copy with a clear, draw tokens and a `GXDrawDone`, over frames that
differ, at 1, 2, 3 and 8 threads, with `SOA_GXR_STALL=<worker>:<kind>:<us>`
holding one worker back before its draws, copies or clears so that an
ordering race becomes a certain failure. It demands the one-worker run's
copied memory, screen, EFB, decoded textures and post-`GXDrawDone` CPU reads,
and that the paths were taken (fences, each kind of wait, the gate, no copy
drains). It passed against the old drains, and removing either drain by hand
turned 10-12 of its runs red before any of H14 existed. Nine deliberate
breakages of the new code -- no entry fence, no exit fence, an entry fence one
short, waiting on the oldest overlapping copy rather than the newest, no
palette wait, no source wait, no hazard wait, no token wait under
`SOA_GXR_TOKENWAIT=1`, no gate -- each turn it red. `test_gxr_lifetimes.py`
now runs its driver under both protocols, so the drain inside a draw's setup
(the use-after-free it was written for) keeps its test while the switch
exists. Lines and points are still drawn by one worker across every row, a
race with other workers' triangles that predates H14 and that no capture
reaches (no capture draws a line); making them row-owned is left for later.


**H15a and H15b: three divisions and a test moved; 3-4% off the pixel path,
not a pixel changed.** 2026-09-25, `build/soa-h14.exe` against
`build/soa-h15a.exe`. The plan's two "hours" slices, each an identity by
construction:

- **Depth before the TEV where alpha cannot reject.** A fragment that fails
  depth is discarded whichever test runs first, unless the alpha test could
  have discarded it and saved a depth write. So where the draw's alpha
  compare passes every alpha, depth now runs first and the TEV never sees the
  fragment. "Passes every alpha" is decided once a draw by trying all 256
  through the pixels' own compare function -- not by a table of modes, which
  is how the plan's trap (the XOR of two always-true compares never passes)
  gets in -- and cached on the compare register, which draws share.
- **The perspective divide once a texture coordinate**, not twice a stage:
  stages sharing a coordinate share its s/q and t/q, the same division.
- **The sampler's scale once a draw** at level 0, the same expression as the
  per-sample division it replaces, so the same float; other levels keep the
  division.

The fragment counters -- shaded, failed alpha, failed depth -- are identical
on the field, ship, cutscene, sky and battle captures (C4's "within 0.1%"
met exactly), replay is 23/23 at 1, 2, 3 and 8 threads, and the self test
passes. `tools/tests/test_gxr_alpha.py` checks sixteen compare combinations
worked out by hand, the XOR trap among them, and the cache between draws;
reading XOR as OR, or keying the cache on nothing, turns it red.

Measured with `tools/perfbench.py` (H6's set), interleaved base, new, new,
base. At 8 threads the set read 89.5 / 97.3 ns a fragment against 86.8 /
89.5 -- inside the drift, since busy time is printed to 10 ms and eight
workers contend. At one thread, where a replay's busy time is seconds: 61.1 /
60.1 against **58.8 / 58.4 ns** (-3.5%), most in the sky (80 → 75) and ship
(79 → 75) scenes, least in the Dangral base (56 → 54). One thing the one-thread
figures say that the plan's budget did not: the same fragments cost about
60 ns on one worker and about 90 on eight. What takes that third is not yet
separated: on this handheld eight busy cores clock lower than one under the
power limit, eight workers share SMT siblings with the producer, and they
contend for memory. H15c/d's budget (61 ns at 8 threads) has to be met
against it as well as against the arithmetic.


**H14's review, and a profiler for the workers.** 2026-09-25. A read-only
adversarial review of H14 (three lenses: threads, lifetimes, pixels; each
finding then argued against) confirmed two things and refuted one:

- **A texture read waited for copies into its base level only**, while its
  decode reads every mip level. A copy into mip level 1 in the same frame as
  a minified draw of the texture would have been read unfinished. Before H14
  the drain after every copy hid this; nothing shows this game copies into a
  mip level, so it was latent. The read now covers every level the decode will
  read, and `tools/tests/test_gxr_overlap.py` gained the case: reverting the
  fix turns six of its runs red.
- **ARCHITECTURE still said a draw token waits**, from before the wait became
  opt-in. Corrected, with the one fence case it had left out (a copy writing
  memory an unfinished copy is still writing).
- Refuted: that the store watchpoints in "H14" covered the wrong memory. The
  addresses watched are where the game's texture copies land.

`SOA_HOSTPROF=1` now samples every worker's instruction pointer about once a
millisecond and ends the report with the busy time by function and source
line, through `gen/soa.pdb`, which `--link` now writes (`/Zi`, `/DEBUG`,
`/OPT:REF,ICF`: the code is unchanged, and every hash matched). Over Part L
3000 at 8 workers (570,872 samples), of the workers' busy time `tev_pixel` is
37%, `raster_triangle` (the per-pixel attribute stepping) 16%, `sample_level`
15%, `blend_pixel` 13%, `shade` 7%, and the depth test, the copy filter, fog
and texture wrapping the rest -- no hotspot, the generic path's cost spread
over every stage of every fragment, which is the case H15c's specialising is
for.


**H15c, first two stages: the shapes most pixels use run directly; 17% off
the pixel path.** 2026-09-25, `build/soa-h15a.exe` against
`build/soa-h15c1.exe`. A census of the H6 set by `fifopair`'s estimated screen
area found 33 distinct TEV setups, and the one-stage ones carrying most of the
area: the vertex colour alone (about 35%) and texture times vertex colour,
sometimes doubled (about 45%). The pixel engine is as concentrated: the
source-alpha blend (`GX_BL_SRCALPHA`, `GX_BL_INVSRCALPHA`) with no fog is 57%.
The worker profile (`SOA_HOSTPROF`, "H14's review") put the generic TEV at
37% of the workers' busy time and the blend at 13%, spread over bank set-up,
selector lookups and per-channel branches rather than any one line.

- `tev_prepare` recognises those shapes -- only where every other choice is
  the plain one: identity swaps, colour channel 0, no bias, adding, clamped,
  into the output register -- and `tev_pixel` runs them as the stage formula
  with the constant operands put in, skipping the register bank;
- `pixel_prepare` gives `blend_pixel` a case for "no blend" and one for the
  source-alpha blend, the general formula with the factors fixed.

Every pinned hash is unchanged (replay 23/23 at 1, 2, 3 and 8 threads). Since
a wrong specialised body is exactly what a replay can miss -- it neither
crashes nor diffs when no capture uses it -- `tools/tests/test_gxr_fastpath.py`
compares the two paths directly: 4,000 random register sets through the real
`tev_prepare`, weighted to the recognised shapes but with near misses (a
swap, a bias, a shift, a second stage, the other channel) the recogniser must
refuse, 64 random pixels each through both paths; and 400,000 random blends.
Dropping the doubling, a wrong alpha formula, a recogniser that takes a bias,
or a blend that rounds up each turn it red.

Measured at one thread, interleaved (base, new, new, base), on the H6 set:

| capture | before (ns a fragment) | after |
|---|---|---|
| all twelve | 56.3 / 62.2 | **49.0 / 49.0** |
| field, Dangral base | 52.5 / 53.9 | 45.6 / 44.2 |
| cutscene | 46.0 / 51.8 | 36.5 / 38.4 |
| corpus 6000 (early game) | 45.6 / 48.7 | 36.2 / 34.6 |
| sky | 76.9 / 83.3 | 67.3 / 64.1 |
| ship battle | 73.6 / 79.3 | 65.1 / 65.1 |

About 17% off the whole set, a quarter off the scenes that are mostly vertex
colour and plain texturing.

**The worker count.** H1 measured 15 workers faster than 8 in the Dangral
base; now that idle workers sleep (H11) and fences park (H14), the sweep was
repeated, interleaved, on H1's Part L 9000 run (Dangral window from frame
3000; `build/threads-*.log`):

| workers | fps | p50 | p99 | CPU |
|---|---|---|---|---|
| 8 (the default: half the logical CPUs) | 19.2 / 19.0 | 51.7 / 52.2 ms | 67.9 / 67.0 | 2,937 / 3,011 s |
| 12 | **23.4 / 23.8** | **42.7 / 42.5 ms** | 62.1 / 63.8 | 3,456 / 3,478 s |
| 15 | 19.6 / 19.7 | 50.8 / 50.7 ms | 69.6 / 71.0 | 3,973 / 3,982 s |

Twelve is 24% faster than eight for 17% more CPU (less a frame); fifteen gives
it back, because fifteen workers with the guest, audio and window threads
oversubscribe sixteen logical CPUs and the guest thread -- the critical path
-- loses its core. The default is not changed by this entry: a finer sweep
(10 to 14) and a check that the lighter Part L 3000 run does not lose come
first, and are the next entry.


**H15c, third stage, and the worker count: the Dangral base at 27 fps.**
2026-09-25, `build/soa-h15c1.exe` against `build/soa-h15c3.exe`,
`build/threads-*.log`, `build/threads3000-*.log`. The third stage is two
things the profile named. The pixel loop visited both colour channels and all
eight texture coordinates on every pixel, testing each for use; it now visits
the ones the draw uses, listed once a triangle, with the arithmetic untouched.
And the per-fragment helpers -- `shade`, `depth_test`, `blend_pixel`,
`fog_apply` in `gxr.c`; `sample`, `sample_level`, `wrap`, the alpha compare in
`gxr_tev.c` -- were calls of their own, which `static inline` had not made them
otherwise, so they are `__forceinline`. Replay 23/23 with every hash
unchanged, and the differential test of the fast paths passes. At one thread,
interleaved: 54.2 / 50.5 -> **46.5 / 45.5 ns a fragment** (-12%; the early
game and the cutscene 20-30%, the sky and the field inside this session's
noise). With the first two stages, H15c has taken the set from about 59 ns to
about 46.

The worker-count sweep, finer and on the stage-two build (Dangral window of
H1's Part L 9000 run, interleaved 12, 10, 14, 14, 10, 12):

| workers | fps | p50 | p99 | CPU |
|---|---|---|---|---|
| 10 | 25.6 / 25.2 | 40.4 / 40.6 ms | 49.2 / 57.3 | 2,655 / 2,690 s |
| **12** | **27.2 / 26.8** | **36.9 / 36.0 ms** | 59.0 / 61.6 | 2,816 / 2,881 s |
| 14 | 23.7 / 23.7 | 40.7 / 41.1 ms | 74.8 / 69.0 | 3,264 / 3,260 s |

and the lighter Part L 3000 run does not lose from twelve: 28.4 / 27.7 fps
against 27.9 / 27.3 at eight, for 18% more CPU. **The default is now three
quarters of the logical CPUs** (12 of 16 here; 6 of 8; capped at 16), from
half. It was measured on this one 16-thread handheld only; `SOA_THREADS`
still overrides it, and a machine with fewer cores to spare for the guest
thread may want less. Together with H14 and H15a-c, the Dangral base H1
measured at 17.7 fps drawn every frame now runs at about 27, close to the
game's 30 fps cap.


**Texture decode by tile.** 2026-09-25, `build/soa-h15c3.exe` against
`build/soa-dec.exe`, `build/exeab-3000-*.log`. With H15c done the twelve
workers are idle about half the Dangral window (the `[gxr] workers:` line of
`build/hostprof2-L9000.log`), and of the guest thread's time decoding
textures is the largest piece the renderer owns, 13%. (This entry first said
the guest thread was the critical path. It is not: 30% of its time is the
game's idle loop, `SelectThread` in the same log's profile -- see "Palette
loads" below.) `decode_level` walked the texture in raster order and found
each texel's tile, row and column with four divisions by the format's tile
size, which the compiler cannot know. It now walks tile by tile, and within a
tile row by row, so each texel is read from the same byte and written to the
same place without them, and checks the tile against the end of memory once
instead of once a texel. The pixels are identical by construction and by
test: replay 23/23 at 1, 2, 3 and 8 threads, the texture-cache and fast-path
tests, the self test. H1's Part L 3000 run, interleaved base, new, new, base:

| build | fps | producer decode |
|---|---|---|
| base | 27.3 / 27.0 | 8.56 / 9.54 s |
| tile walk | 28.2 / 27.1 | 7.25 / 8.07 s |

Decode falls about 15% (9.05 -> 7.66 s); fps moves inside the noise. The
divisions were therefore not most of what decoding costs, and the rest --
which formats, how much is the palette lookup, how much is re-decoding the
same copy every frame -- is unmeasured; the copies' own path (H14 step 6,
copy images, which skips decoding a copy entirely) is the larger lever.


**Palette loads: every decode they threw out came back unchanged.**
2026-09-25, `build/envab-3000-*.log`, `build/envab-9000-*.log`. The tile walk
above took 15% off decoding; why there was so much decoding was elsewhere. A
TLUT load (BP 0x65, `tmem_load_tlut`) threw out the decode of every
palettised texture whose palette lay within 32 KB of it, so the next draw to
sample one decoded it again -- and the game loads palettes about 20 times a
frame in the early Part L run and 51 in the Dangral base, over and over into
the same places. The texture's hash already covers its palette (32 bytes for
C4, 512 for C8), so a load now only sends the entries it overlaps to be
hashed again at their next lookup, and a texture is decoded again only if its
palette did change. The report's `textures:` line now says why each decode
happened. Before, in H1's Part L runs:

| run | decodes | made again after a palette load | of those, unchanged |
|---|---|---|---|
| Part L 3000 | 82,545 | 35,667 | 35,667 |
| Part L 9000 | 358,495 | 305,617 | 305,617 |

Every one. Interleaved, the drop (kept behind a temporary switch for the
measurement, now gone) against the re-hash; the Dangral window is frames
3000-9000 of the 9000 run:

| run | build | fps | producer decode | producer wait | guest idle loop | CPU |
|---|---|---|---|---|---|---|
| Part L 3000 | drop | 28.6 / 28.4 | 7.35 / 7.58 s | 0.75 / 0.87 s | | 537 / 536 s |
| | re-hash | 28.4 / 28.6 | 0.55 / 0.53 s | 1.72 / 1.50 s | | 521 / 509 s |
| Dangral | drop | 25.7 / 27.8 | 35.8 / 33.1 s | 28.0 / 21.6 s | 32.6 / 36.4% | 2,562 / 2,492 s |
| | re-hash | 26.5 / 27.2 | 7.6 / 7.0 s | 40.7 / 38.7 s | 39.5 / 40.6% | 2,416 / 2,410 s |

Decoding falls 79-93% and the process 3-5% of its CPU, and **the frame rate
does not move**. Where the Dangral base's saved 3 ms a frame went is in the
same table: the producer's wait at the copies' hazard (25.2 / 20.1 -> 39.8 /
38.1 s, `waits:` line) and the game's own idle loop. So the guest thread was
never the critical path there (the entry above said it was, and is
corrected), and the workers are idle half the time too. What holds the frame
is the order between them: a draw that samples a texture copied earlier in
the frame waits, on the guest thread, for the workers to finish everything
drawn before that copy, and the workers then wait for the draws the guest
builds after it. That is the plan's copy images (H14 step 6): make the copy's
texture in the pool and fence the sampling draw there, so the guest thread
goes on. Whether that raises the frame rate, or only moves the wait into the
workers, is the thing to measure.

Checks: the texture-cache test gains a case -- the same palette loaded again
keeps the decode, a different one in the same place is decoded again, inside
one epoch -- which fails with the mark taken out ("a changed palette was not
decoded again"). The lifetime test's burst of freed textures came from a
palette load, which no longer frees anything; it now comes from
`tex_invalidate_all`, the one mass invalidation left, and the test's note that
700 draws walk a 256-entry cache over (it has held 1,024 since H12) is gone.
Replay 23/23 at 1, 2, 3 and 8 threads with every hash unchanged; the self
test.


**Copy images: the hazard wait is gone, and the frame gate is what is
left.** 2026-09-25, `build/soa-base-img.exe` against `build/soa-img.exe` and
the final `build/soa-img2.exe`, `build/exeab-9000-*.log`.
"Palette loads" above left the frame held by one order: a draw sampling a
texture copied earlier in the frame waited on the guest thread for the
workers to finish everything drawn before that copy, then decoded the copy
from memory. This is the plan's H14 step 6. At the copy, the texture cache's
entry for exactly what the copy makes gets a fresh RGBA image; each worker,
as it writes its rows of the copy, decodes those rows into the image through
the same per-texel decode a decode from memory uses (every texel of a row is
its owner's); and a draw that samples that texture while the copy is the
newest queued write to its bytes takes the image with no wait, hash or
decode, fenced in the pool on the copy instead. Anything that could make
memory differ from the image retires it and the texture is read from memory
as before: a newer copy over its bytes, a drain, a token that finds the
copies finished, a hook's wait. The cache key also drops the palette fields
for formats that have none, and masks the address as memory does -- neither
changes a decode or a hash, and without it the image's key would miss draws
whose TLUT register was left set.

Dangral window, frames 3000-9000 of H1's Part L run, two interleaved A/Bs
(base, new, new, base), the second on the final build -- the review's fixes
below change nothing on this path: the same 19,005 lookups served, none
retired:

| A/B | build | fps | p50 | p99 | producer wait | decode | CPU |
|---|---|---|---|---|---|---|---|
| 1 | base | 25.5 / 24.6 | 36.0 / 38.2 ms | 73.3 / 71.6 | 42.7 / 47.9 s (hazard 41.1 / 46.0) | 9.2 / 10.0 s | 2,535 / 2,583 s |
| 1 | copy images | 29.3 / 28.1 | 33.4 / 33.8 ms | 53.3 / 63.2 | 10.3 / 19.9 s (gate only) | 0.2 / 0.2 s | 2,495 / 2,520 s |
| 2 | base | 27.2 / 26.1 | 35.1 / 36.2 ms | 55.6 / 61.8 | 36.5 / 41.5 s (hazard 35.7 / 40.4) | 8.1 / 9.0 s | 2,421 / 2,482 s |
| 2 | final | 28.4 / 27.2 | 33.8 / 34.4 ms | 61.1 / 69.7 | 19.0 / 32.7 s (gate only) | 0.2 / 0.2 s | 2,497 / 2,634 s |

+14.6% in the first and +4.3% in the second: this machine's drift between
runs is as wide as the effect, so the figure to quote is the pooled one,
**+9% (25.9 -> 28.3 fps)**, with the median frame 36.4 -> 33.9 ms, at or
near the 30 fps cap's two fields in every run. All 19,005 lookups of a
copied texture were served by one of the 12,670 images. The hazard waits are
gone; what the guest thread waits for now is the frame gate, the one drain a
frame (0.7-1.8 s -> 10-33 s), which is the workers finishing the frame
before. So in these frames the pool is the critical path again: a gate that
let the next frame's commands in while the workers finish the last one, or a
faster pixel path (H15d), is where the next frame of time is.

An adversarial review (three reviewers, a skeptic for each finding) found no
concurrency defect and three real gaps, all fixed before this commit: an
image outlived a token that had proved the copy finished, a hook's poke, and
a copy on the no-worker path (the retirements above, and no images with no
workers); it bypassed a mod's texture provider (no images while one is
registered); and no test showed the image path was taken at all. Checks:
replay 23/23 at 1, 2, 3 and 8 threads with every hash unchanged, and the four
copy captures (1550, 4500, 6000, 16300) each serve three lookups from two
images with no hazard wait. `test_gxr_overlap.py` gains an overwritten
image, an unfiltered copy (whose only fence is the draw's), a drain then a
CPU write, a hook's write, and a token between a copy and its draw, with the
drains (`SOA_GXR_DRAIN=1`, no images) as the reference; a new test pins the
producer's image counts per protocol. Seven deliberate breakages each turn
it red: no draw fence, an image used under a newer copy, rows never decoded,
the wrong tile row, a retired image served, a token or a hook that retires
nothing. The lifetime and queue tests sample a texture inside a copy rather
than the copy's own, so their draws still take the wait they are there to
test.


**The frame gate, tried off; neighbour fences.** 2026-09-25,
`build/envab-9000-*.log` (the gate), `build/exeab-9000-*.log` (the fences),
Dangral window of H1's Part L run.

After copy images, the guest thread's wait is the frame gate: at the next
frame's first command it drains, for the workers to finish the frame before.
Turned off (a temporary switch, gone), with the screen copy pruning finished
copies from the pending list instead and the arena, graveyard and copy-list
drains left to recycle when they fill: 28.3 and 22.9 fps against 27.4 and
27.3 with it, the second run's p99 188 ms. The guest ran frames ahead until
the command ring filled -- 41,169 ring waits in the bad run -- and the
workers' time at fences doubled (642 -> 1,323 s): a deeper queue lets the
workers drift further apart, and every filtered copy then waits for the
furthest behind. The gate stays; one frame in flight is the better shape
until the fences are cheaper.

Which is the second thing those logs show: the twelve workers spend 540-730 s
of a run idle at fences, and every copy this game makes fences on all of
them. A filtered copy's output row y reads EFB rows y-1, y and y+1; with
workers owning rows `y % n`, rows y-1 and y+1 belong to the writer's two
neighbours. So a copy that is foreign for its filter alone (full scale, y0 a
multiple of the worker count) now fences on those two only, on the way in
and on the way out (`fence_near`); a screen copy's entry fence, a draw
sampling a copy's image, and a copy over a queued copy's bytes still fence on
every worker. It is deadlock-free for H14's reason: a fence is never above
its own command, so the worker furthest behind never waits. Interleaved:

| with the clock out (`SOA_SPEED=4`) | build | fps | p50 | fence time | guest wait |
|---|---|---|---|---|---|
| first block | every worker | 32.6 / 32.4 | 28.8 / 28.4 ms | 343 / 350 s | 68.8 / 69.4 s |
| | neighbours | 33.0 / 36.1 | 28.6 / 26.8 ms | 281 / 232 s | 60.7 / 59.6 s |
| second block | every worker | 37.2 / 38.8 | 26.1 / 25.4 ms | 194 / 159 s | 59.6 / 56.0 s |
| | neighbours | 38.7 / 38.3 | 25.4 / 25.5 ms | 148 / 158 s | 55.1 / 55.0 s |

Measured with the clock out because at real time both builds now sit on the
30 fps cap on a quiet machine (29.8 fps each in a real-time pair), where no
throughput gain can show; and in blocks, because this machine ran about 15%
faster in the second block than the first, which is the size of the drift
H1 warned about. Within each block: +6% and +1% fps (+3.5% pooled), fence
time -26% and -13%. A small gain, consistently not a loss; the larger effect
is on a contended machine, where one descheduled worker used to hold all
eleven others at every copy (a real-time pair's contended run spent 1,009 s
at fences against 349 s for the neighbour build right after it -- one pair,
so evidence of the shape, not a number to quote).

Checks: replay 23/23 at 1, 2, 3 and 8 threads with every hash unchanged; the
overlap test (its stalls hold worker 2 back, whose rows are the taps of
workers 1 and 3) passes, and four breakages each turn it red -- only the
previous neighbour asked, only the next, no exit fence, no entry fence.


**H13, first steps: the cache calls as no-ops, paired-single loads without
`ldexp`, and an mtfsb that named the wrong bit.** 2026-09-25,
`build/soa-near.exe` against `build/soa-h13.exe`, `build/exeab-9000-*.log`.
One retranslation carries three things.

- **H13b's data-cache calls.** `DCInvalidateRange`, `DCFlushRange`,
  `DCStoreRange` and the two NoSync forms translated to loops that walked
  their range 32 bytes at a time doing nothing but count and poll for
  interrupts (`dcbi`, `dcbf` and `dcbst` emit nothing); `DCInvalidateRange`
  alone was 5.2% of the guest thread in the Dangral window. They are bound in
  `config/hle.txt` to natives in `hle_os.c` that do nothing but keep the
  syscall the two synced forms end in, for a non-empty range as the originals
  do. A self-test case holds all five to their recompiled twins. PSMTXConcat
  stays translated: it is not in the profile's top rows.
- **H13a's paired-single loads and stores** computed their scale with
  `ldexp` on every access, whatever the type, and the f32 type -- almost every
  one in this binary -- ignores the scale. f32 now skips it, and the
  quantized types build the power of two from its bits. A self-test case
  compares every type and scale, paired and single, loads and stores, bit for
  bit against the old formula. `fma` inline is not done.
- **A translation bug**, found by the planning session's portability survey:
  `mtfsb0`/`mtfsb1` name their FPSCR bit in bits 6-10, and the emitter read a
  field the X-form decode never sets, so every one touched bit 0 (FX). The
  binary has one, OSInit's `mtfsb1 29` at 0x80231AC8, which set FX where it
  meant NI (non-IEEE mode). The port acts on neither, so the only change is
  what `mffs` and CR1 report. `test_emit.py` pins the emitted bit.

The guest thread's ceiling in the Dangral window -- H1's Part L run in
snapshot mode, uncapped from frame 3000, the clock at four times real time,
so nothing waits for a field -- interleaved in two blocks:

| build | images a second | p50 | guest idle loop |
|---|---|---|---|
| base | 112.1 / 115.0; 114.7 / 114.7 | 8.4 ms | 27.6-30.2% |
| H13 steps | 127.6 / 121.5; 123.8 / 125.3 | 8.0-8.2 ms | 34.7-35.9% |

**+9% (114.1 -> 124.6), in both blocks.** The guest thread alone runs this
scene at four times the 30 fps cap, so none of this moves the frame rate
at real time; it is headroom, for M11's battle speed-up and for H17a's
second image. (The H13 runs make slightly fewer syscalls, 1.472 M against
1.476 M: uncapped at four times real time, a faster guest spends less guest
time on the same 9,000 frames, and the audio driver flushes its buffers once
an audio frame.) Checks: the full retranslation, the self test with its two
new cases (each turned red by a deliberate breakage: the power of two off by
one in the exponent, the syscall made for an empty range), replay 23/23,
`title --check`, 849 tests.


**H15d's starting point: where the workers' time goes, inlined helpers
apart.** 2026-09-25, `build/hostprof5-L9000-s4.log`, `tools/perfbench.py`.
`SOA_HOSTPROF` now resolves the innermost inlined frame, so the pixel path's
`__forceinline` helpers get rows of their own instead of their callers' line,
and `SOA_REPLAY_REPEAT=N` renders a replay N times so a single capture can be
profiled. At 8 threads the perfset stands at **62.5 ns a fragment** over every
replay: the Dangral field frames at 55 (under the plan's 61 already), the
cutscene 54-58, the early-game corpus frames 47-52, and the ones short of it
the ship battle (79) and the sky (77-83); the battle frames, 0.7 M fragments,
are 98, mostly the fixed cost of a small frame.

Worker time in the Dangral window with the clock out (render-bound, 40
fps, workers 85% busy), by the function inlined at each sample: the
rasterizer's own per-pixel attribute work 18.0%, the TEV 17.5%, texture
sampling 17.2% (`sample_level` 10.7, `sample` 3.3, `fast_floor` 2.1, `wrap`
1.1), `blend_pixel` 8.7%, `shade`'s own body 6.3% -- of which the per-pixel
`g_pixels++`, a thread-local counter, is 3.2% of all worker time -- then
`clamp255` 2.3, `depth_test` 2.1, the copy filter and decode 4.4, fences 3.0.
The hottest single line is the bilinear blend (`gxr_tev.c`, 6.8%). In the sky
capture the busy time is sampling ~27%, the TEV's general path ~25% (the
one-stage fast shapes do not cover it), the rasterizer 15% and fog 7%, a
per-pixel `exp2f` among it.

So the order for H15d: the counters out of thread-local storage; the
bilinear blend four channels at a time in integer SIMD (exact, the same
arithmetic in lanes); the TEV's general path the same way; then the
rasterizer's attribute stepping, which repeats an addition per pixel that a
four-pixel span could not reproduce bit for bit -- that one would move
hashes, and waits until everything that cannot has been done.


**H15d, first step: the counters out of thread-local storage, the bilinear
blend in integer SIMD.** 2026-09-25, `build/soa-h15d0.exe` against
`build/soa-h15d1.exe`, `tools/perfbench.py` through an interleaved A/B. Two
changes that leave every byte as it was:

- `shade` returns what it did with the pixel -- drawn, failed alpha, failed
  depth -- and a triangle counts those in locals and adds them to its
  thread's totals once, where each pixel used to bump a counter found through
  thread-local storage (3% of worker time).
- The bilinear blend runs its four channels at once with SSE4.1: one
  multiply-add of each texel pair by (256 - ax, ax) for the horizontal pass
  (255 * 256 fits a signed 16-bit lane), 32-bit multiplies for the vertical,
  the scalar loop's integers exactly. The CPU is asked once, on the producer,
  in `tev_prepare`; `SOA_GXR_NOSIMD=1` or a CPU without SSE4.1 takes the
  scalar loop, which stays as the reference. A new differential test samples
  600,000 random points (sizes powers of two and not, every wrap mode, exact
  texels and half-texel points) through both and finds no difference; with
  one weight pair swapped it goes red.

At one thread, over the whole perfset, interleaved in two blocks:
43.9 / 43.4 ns a fragment -> **40.6 / 40.7** (**-7%**); the Dangral field
frames 38.7-41.4 -> 35.9-38.7, the sky 57.7 -> 51.3-57.7 (the busy clock's
10 ms grain is coarse on a 1.6 M-fragment frame). Replay 23/23 with every
hash unchanged; the self test.


**H15d, tried and dropped: the rasterizer's per-pixel attributes in SIMD.**
2026-09-25, `build/soa-h15d2.exe` and `build/soa-h15d3.exe` against
`build/soa-h15d1.exe`. The rasterizer's own per-pixel work is the largest
single share of the workers' time (18% in the Dangral window), and most of
it looks vectorisable bit for bit: the vertex colours' multiply, add,
truncating conversion and clamp, the texture coordinates' multiplies, and
the step from one pixel to the next are the same operations in a lane as
alone. Built so (SSE4.1, with a differential test of 320,000 random pixels
-- colours out of range, w zero, NaNs -- that agreed bit for bit and went red
under two breakages), with every hash unchanged: at one thread it was 5%
**slower** (39.5 -> 41.5 ns a fragment, interleaved), and with the padding
the four-float loads need cut to four floats a row, no faster (39.25 against
39.35). What costs in that loop is the division for 1/w and the branches
around it, which a lane does not change, and the triangles are small enough
that anything added per row or per triangle is paid on few pixels. Reverted;
the differential test went with it. What stays from the attempt:
`SOA_GXR_NOSIMD` took any set value, an empty one included, as "off" -- now
only a non-zero one does -- and the report says when the pixel path ran
without SIMD, which is how a run shows the switch reached it (the replay
sweep strips every `SOA_` variable, so a sweep "with" it is the sweep
without it).


**H15d paused: where the pixel path stands.** 2026-09-25, `build/soa-h15d0.exe`
(before H15d) against `build/soa-h15d1.exe` (its first step),
`tools/perfbench.py` at 8 threads, interleaved in two blocks. Recorded
because the owner is weighing a GPU backend before more of H15d.

| build | ns a fragment, all captures | field (Dangral) | ship | sky |
|---|---|---|---|---|
| before H15d | 70.4 / 72.6; 72.1 / 72.8 | 58.0-63.5 | 79.3-102.0 | 89.7-96.1 |
| first step | 70.3 / 64.9; 77.2 / 74.3 | 58.0-69.0 | 85.0-102.0 | 76.9-96.1 |

**No difference at 8 threads** (72.0 against 71.7): the -7% of "H15d, first
step" is at one thread, where the per-fragment work is all there is; at 8
the pool's cost is dominated by what the change does not touch. And the
machine was about 15% slower than when the morning's baseline was taken
(62.5 then, 72.0 now, the same build), so no 8-thread figure from this
session is to be compared with one from another without an interleaved base
beside it. Against the plan's bar of 61 ns at 8 threads: the field captures
meet it on a quiet machine and not on a busy one, and the ship and sky
captures, at 80-100, are 1.3-1.6x short. The TEV's general path, which those
two scenes use most, is the next CPU step if the pixel path stays on the CPU;
the census (`tools/fifopair.py`-weighted) says one-stage shapes carry about
80% of the perfset's area, and the rest is 3-5 stage chains whose operands
are gathered through selector indices, which does not vectorise cheaply as it
stands.


**Manifest 2.** 2026-09-25, `docs/specs/now.md` N2, specified in
`docs/PLAN-GAMEPLAY-MODS.md` section F. `mod.c` refused any `api` but the
literal "1", so the first mod API bump would have refused every mod written
before it. A `mod.ini` may now say `manifest = 2` and carry a stable `id`
(lowercase letters, digits, `.`, `_`, `-`) and a `version`, both required
then, and optional `authors`. The recording's config line names such a mod
`id@version:hash` -- what a later save chunk (X2) and a content-id lock (T2)
will key on -- and a second mod with an id already loaded is refused, naming
the folder that has it. `api` is the least API a mod needs in either
version, so a port that speaks a later one still loads it. A key beginning
`x_` is noted and passed over, kept for later ports; any other unknown key
still refuses the mod, so a misspelling is still caught. A `mod.ini`
without `manifest` is version 1 and loads and records exactly as before,
by folder, so recordings made with mods keep their lines. Both shipped mods
(`mods/encounters-off`, `examples/mods/map-log`) are manifest 2; a real run
with `SOA_MODS=mods` names it `encounters-off@1.0`. Checks:
`test_mods.py` gains nineteen cases -- a manifest 2 mod beside a version 1
one in the recording, fifteen refusals, an `x_` key loaded, a duplicate
id -- and three breakages (duplicate ids allowed, `x_` keys refused, the
recording naming by folder) each turn it red. That `api` below the port's
own loads cannot be shown until the port speaks 2.
*Amended 2026-09-25:* the review of this entry found the recording line's
`+N more:HASH` tail -- the mods that do not fit -- still hashing each mod
by its folder, so renaming the folder of a manifest 2 mod past the line
made a replay claim another configuration while the same rename in the
line's head changed nothing. The tail now hashes each mod by the name the
head would give it; a test renames a tail folder under twelve long ids and
the line holds, and keyed by folder again (the mutation) it moves.


**P11's spike: the message window's state word, read in a run.** 2026-09-25,
`build/p11spike.log`, frames in `build/p11spike/`. The comfort-pack spec's
draft reads the field message window through the task at `0x80346E4C` and
its state, an s16, at `0x80346E64` -- not the plan's `0x80346E60`, which the
draw stores 0 back into -- all from the disassembly. One run checked it
before any mod code: a copy of `card-saved`, the Continue preamble, a warp
by name to `ME355A.SCT` at frame 3000 (HANDOFF's five pokes), no A after the
load, `SOA_PEEK` of both words and the scene id every frame from 2900 to
6600, and one A at 6000.

| frames | task (`0x80346E4C`) | state (upper half of `0x80346E64`) |
|---|---|---|
| 2900-3000 | `80E44A80` | 1, waiting for a message |
| 3001-3002 | 0 | 255 -- the warp's teardown |
| 3003-3075 | `80E44A80` | 1 |
| 3076-3086 | | 2, opening, then 3, revealing |
| **3087-5999** | | **4**: the page complete and waiting for A (frame 5900: 《どうせみないでしょ？》 with the page marker) |
| 6000-6006 | | the A: 5, scrolling, then 3 |
| **6007-6600** | | **6**: a choice (frame 6500: 「みる」「みない」) |

The scene id read 6, the field, throughout. The state rested at 4 with no A
pressed for 2,913 frames, the A moved it on, and the choice box that
followed rested at 6: what the draft predicted, so P11 can build on these
words. The task reads 0 for two frames of a warp, which a mod must treat as
"no window".


**P6: the race seed pinned, and settings that change the game recorded.**
2026-09-25, `build/scenario-p6.log`, `build/scenario-p6-watch.log`,
`build/p6.pad`. The game seeds its random numbers from the timebase through
OSGetTick at three sites -- a field load (the call returns to `0x801012B0`)
and twice at a battle start (`0x8000A1D0`, `0x8000A1D8`) -- each followed at
once by srand, which stores its argument to the seed word `0x803469A8`.
With `SOA_SEED` set, `guest_timebase_lo` hands a read from inside OSGetTick
(the guest's pc `0x8023851C`: the one place the pc decides anything, and a
necessary gate, since the device models read the timebase through the
guest's registers with whatever lr it last set) to `runtime/seed.c`, which
answers the three sites with MurmurHash3's finaliser over the seed, the
site and that site's call count, and every other read with the clock.
`k_settings` now marks the keys that change the game as recorded; `seed` is
the first, and the recording's `# config` line carries every recorded key
that is set -- a run with none keeps the line it had. The report-hook table
grows from four to sixteen and says so when it overflows, where a fifth hook
used to vanish.

The battle scenario with `SOA_SEED=12345`: `field load 2, battle start 1 and
1 pinned; 191132 other OSGetTick reads left alone` -- both field loads before
the deck fight, which starts at frame 9810 and is still going at the
scenario's 12,000 -- and the recording's line ends `seed=12345`. A store
watch on the seed word from frame 9790 shows srand storing `8739D20C` from
lr `0x8000A1D4` and `2A787E8A` from `0x8000A1DC` at frame 9810: the two
battle-start pins for that seed, exactly, then `rand()`'s first store at
9814. Checks: `test_seed.py` holds seed.c built alone to an independent
Python finaliser (36 values), pins exactly the three sites, counts each
site's calls, and refuses a seed that is not 32 bits; a test finds each site
in `gen/` once, followed by srand, so a retranslation that moves one fails;
the self test runs the game's own OSGetTick and srand through the pin at
each site twice, and from `0x8000A1DC` -- the plan's mutation -- gets the
clock; `test_settings.py` has `seed` recorded only when set. Whether one
seed gives one battle is K6's question, and waits on it.


**Recorded display lists (C5a): the chain confirmed.** 2026-09-25,
`build/scenario-c5a.log`. `SOA_GX_DLLOG=1` (`runtime/gx.c`) logs each move
of the CPU FIFO -- the PI FIFO base, which `GXSetCPUFifo` (`fn_8024C5FC`)
writes -- away from the command processor's FIFO base and back, with the
draws and bytes the port parsed while it was away; each display-list call
with its size; each change of the CP's FIFO base; and at the report a table
per buffer. It changes nothing parsed. The opening scenario to frame 5000:

- 35,574 moves away. 1,929,546 of the run's 6,764,969 draws (28.5%) and 512
  MB of its 1.70 GB of pipe bytes were parsed while the CPU FIFO pointed at
  a buffer the command processor was not reading.
- 27,871 display-list calls, **every one of size 0**.
- The buffers are heap blocks 0x80 apart from `0x804EB5A0` up, about 1,900
  of them, and they are the addresses the lists are called at: `0x804EB620`,
  for one, was the CPU FIFO 3,484 times with 552,337 draws parsed there, and
  was called 3,261 times, each time with size 0.

So the redirection the GPU spec's section 2.8 read out of the disassembly
happens in a run: the port parses what the game records at once, during the
scene update (H5's order: reset, update, draw pass), and the list the draw
pass calls is empty. H4's "all draws are direct" and ARCHITECTURE's PI FIFO
registers "stored and read back but never used to route" describe the port,
not the game. C5b -- record into guest memory at the PI write pointer, parse
at the call -- follows, and moves H10's pair keys, so H4's match rates are
re-measured after it.

Two things C5b has to handle that the spec did not name:

- **Not every redirect is a list, and the base test alone would lose the
  logos.** At frame 1 the game points the CPU FIFO at `0x804024E0`, points
  the CP's there too and back to `0x804A74E0` (the only CP base changes in
  the run, frames 0 and 1), and leaves the CPU FIFO at `0x804024E0` until
  frame 385: 1,548 draws, never called as a list -- and they are the
  "Created by Overworks" screen (`build/frames/0200.png`), which the
  console shows. A C5b that stops parsing whenever the two bases differ
  would draw nothing there. Bracketing by the list functions themselves
  (`fn_80251D80` and `fn_80251E48` in the spec) would not. How the console
  reaches those bytes is not known.
- **Recordings outnumber calls**: 35,574 against 27,871 -- `0x804EB5A0` was
  recorded 7,186 times and called 4,089. A list recorded again before its
  call, or never called, is drawn by the port today at every recording;
  with C5b only what the list holds at the call is drawn. (Counted per
  buffer address, and a block the heap reuses for another list counts under
  the same address, so the per-list numbers are an upper bound.)


**P6, followed up: each pin in the log, the reload after a battle, and the
seed in effect recorded.** 2026-09-25, `build/scenario-p6.log`,
`build/p6.pad`. Each pin now prints `[seed] pin: site S (lr X) n N -> 0xV`,
and `python tools/tests/test_seed.py <log> [<recording>]` checks a run by
those lines with the Python finaliser: every value, each site counting from
zero, the report's counts equal to the lines', a field-load pin *after* a
battle start, and the recording's `# config` line ending `seed=<seed>`.
The first P6 run stopped at frame 12,000, mid-battle, so the field-load site
was never seen from a battle's exit path -- the review of 2026-09-25 caught
that the Done asked for it and the entry did not have it. The battle
scenario to frame 13,500 with `SOA_SEED=12345`: `field load 4, battle start
1 and 1 pinned; 214554 other OSGetTick reads left alone`. The field-load
site fired twice before the fight and twice after it -- once between frames
12,800 and 12,900, with the victory pose on screen, and once between 13,060
and 13,100, after the results screen (13,000) and before the deck field is
back (13,400). The check passes on it; with one pin's value edited it names
that pin and fails. The two battle-start pins are the `8739D20C` and
`2A787E8A` the store watch saw srand take.

The same review found that the recording named the text in the environment,
not the seed in effect: `SOA_SEED=12x` was refused and still recorded as
`seed=12x`, and `0x3039` and `12345` -- one seed -- recorded differently, so
a replay with either claimed another configuration. `seed_init` now hands
back the seed it pinned, in decimal, or nothing, and `settings_record_as`
lets a key's owner say what is recorded (`test_settings.py`, with the raw
text as the mutation). The config line has more room: 640 bytes for the
settings and mods (from 320), 1024 for the line, and a line cut short says
`[pad] the config line was cut at N bytes` instead of dropping what did not
fit -- `settings_recorded` used to leave half a value in the buffer when it
overflowed. `test_padrec.py` sends 600 bytes through whole and 800 cut, and
the old 320-byte buffer fails the first.


**P1a: the encounter slider and hold-B, and where the game works out its
multiplier.** 2026-09-25, `build/p1a/`. `mods/encounter-rate` is the first
mod the port ships: a `mod.dll` (built by `--link`, which now builds every
`mods/*/mod.c` and `examples/mods/*/mod.c` and fails if one does not
compile) that writes the game's encounter multiplier, the signed byte at
`0x8030B7AD`, from the frame end while the scene is the field. The game's
byte is -1 (no multiplier) or the effect-84 value of a party accessory;
the mod works out the same base every frame -- 50 with none -- and writes
base/2 at `half`, min(base x 2, 127) at `double`, 0 at `off`, and nothing at
`normal`; B held in the field writes 0, and at `normal` the first frame after
B is let go puts the game's own value back, once. `encounters` and
`encounters_hold_b` are recorded settings, recorded only as values the mod
takes and only when the mod is loaded; without it the port says the key
does nothing. mod.c's report gives each DLL's writes. `mods/encounters-off`
moved to `examples/mods/`, so `mods = ...\mods` no longer turns battles off
for good beside the slider.

Each run from a copy of `card-saved` (a101b), the Continue preamble, the
multiplier's word peeked every frame (the byte is its second):
- nothing poked: the mod logs `base 50 (none)`; `half` reads `19` (25) and
  `double` `64` (100) on every frame from 3000 to 3600; `normal` reads the
  game's `FF` with `0 write(s)`;
- accessory 210 poked onto character 0 at 3000, then a warp to `ME101B.SCT`:
  the mod logs `base 100 (character 0's accessory 210)`, and `half` reads
  `32` (50) and `double` `7F` (127) on every frame from 3300 to 3900;
- `normal` with `3400:b#300`: `FF` to 3400, `00` from 3401 to 3700, `FF` from
  3701 -- to the frame at both edges -- and `301 write(s)`: 300 zeros, one
  restore;
- `SOA_ENCOUNTERS=half` without `SOA_MODS`: "`encounters = half` is set, and
  no mod with id `encounter-rate` is loaded; it does nothing".

**The spec's one expectation that did not hold is about the game, not the
mod.** At `normal` after the accessory poke and the warp, the byte read
`FF`, where the spec expected the game's own `64` and said `FF` would mean
the setup was wrong. It was: a store watch on the byte through the Continue
load, the poke and the warp (`build/p1a/W-watch.log`) shows the game writing
it once, at the Continue load (frame 2648, `fn_801EF7E0` reached from
`0x801A4538`), and never at the warp. `fn_801EF7E0` resets the multiplier
to -1 and runs `fn_801EE5A4` for each of characters 0-5, party or not; its
twenty callers are Continue, the equipment menus (`0x801F0xxx`-`0x801F4xxx`)
and a few others -- a map load is not among them. And the save's party
block lands in the same frame as that call (`W2-watch.log`, both at 2648),
so no poke can get between them. In its place the self test runs the
game's own `fn_801EF7E0` on parties set up in memory: `FF` with no
accessory and with 204 and 201 (no effect 84), `64` with 210 on character
0, and `05` with 211 on character 1 after it or on character 5 alone --
exactly what the mod's reckoning gives on the fake guest for the same
parties. Claiming the first character wins instead (the mutation) fails it:
the game gives `05`.

Checks: `test_mods.py`'s new cases on the fake guest (nothing written unset;
each preset from each base; only in the field; hold-B's zeros and its one
restore of `FF`, or of `64` with 210; hold-B off leaving the controller
alone; `HALF` refused), with the spec's two mutations built from the shipped
source -- halving the byte read back reads 50, 25, 12 where the mod holds
50, and without the restore battles stay off after B; `test_settings.py`'s
"does nothing" line and choices; the self test's new case.


**P11: dialogue that turns its own pages.** 2026-09-25, `build/p11/`.
`mods/autotext` is a `mod.dll` with one controller filter: in the field,
when the message window's state (the s16 at `0x80346E64`, read through the
task at `0x80346E4C` and its context at +36, as P11's spike found) is 4, a
complete page, and neither flag 0x10 nor 0x40 is set on it -- the pages the
game turns on its own countdown -- it waits `SOA_AUTOTEXT` frames (`on` is
45) and presses A, two frames down and two up, once; it arms again only
when the state has left 4. Never in any other state, never over the
person's own A or B. `autotext` is a recorded setting.

Three runs from copies of `card-saved`, each the Continue preamble, a warp
by name to `ME355A.SCT` at 3000, A at 6000, 6900 and 7300, and the state
and the committed map peeked every frame:
- with the mod at 45: four presses (3132, 6472, 6567, 6955), each with the
  state at 4 the frame before; the officer's page complete at 3086 and the
  choice after it up at 3139, 53 frames on (the spike, without the mod,
  rested at 4 for 2,913); the state 6 on every frame from 3139 to 5999, so
  no press in the choice; and `a002b` committed at 7336, after the last A;
- without `SOA_MODS` (the mutation): no press, the choice not up until
  6007, and `a002b` never committed;
- with `SOA_AUTOTEXT_TEST=press-in-choice` (the other mutation): presses
  in the choice boxes too (3185, 3805, 3913 of seven), so the state leaves 6
  at 3185, and the first choice of every box takes the run to `a002b` at
  3949, before the A at 6000.

**Two things the spec had not seen.** The part select has one more menu
than section 3.5 says: after みる come two pages, then 《どうする？》 with
「パートにとびたい」 and two other entries (up at 6574), then one page, and
only then the B/C box (6962); so the run takes a third A (7300), where the
spec's fallback said to move the second. And a choice box's context carries
flag 0x10 -- the choice marker -- so a flags guard applied in every state
kept the test switch from ever pressing in one: the first press-in-choice
run pressed exactly where the plain run did, so the mutation passed. The
guard now applies to state 4 only, the fake guest's choice carries 0x10 as
the game's does, and the rerun above fails as it should. (Play is
unchanged: outside the test switch the mod only ever arms in state 4.)

Checks: `test_mods.py` on the fake guest -- a press 45 frames into a page,
two frames down and two up, not again on the same page, again on the next;
none after a choice (0x10), on an auto-scroll page (0x40), in a choice, in
state 8 or with no window; none over the person's own A; none when off,
`0` or a value it does not take -- and, from the shipped source, the guard
removed presses on a page the game turns itself, and the test switch
presses in a choice.


**M18: rumble.** 2026-09-25. The game drives the pad's motor through
PADControlMotor, which writes `0x00400300 | cmd` to a channel's SI OUTBUF
(1 rumble, 0 stop, 2 stop hard); the port used to store the word and do
nothing. `si.c` now passes a change of channel 0's two command bits to a
sink `window.c` sets -- `XInputSetState` on port 1's pad, both motors -- at
the strength `SOA_RUMBLE` gives (0-100, default 100). The motor turns only
when a person could be holding the pad: a window is open, no `SOA_PAD`
script or `SOA_PAD_FILE` replay drives the input, and the strength is not 0;
every other change sends speed 0. It is stopped on every way out that the
port controls: focus lost (`WM_ACTIVATEAPP`), the window closed, the
report, and `atexit` for the `exit()`s that skip the report. A crash with
the motor on is the one case left: the pad may buzz until XInput's own
timeout or until it is unplugged. The report says how often the game asked
and how often the motor turned. `rumble` is a setting and is not recorded:
it changes nothing the game does.

Checks: the self test's new case drives `si_write` as PADControlMotor
would, with a counting sink: rumble turns the motor at full strength, a
repeated write calls nothing, stop and stop hard send 0, strength 50 half
speed, channels 1-3 nothing, and strength 0, no window or a pad script
never turn it; `si_motor_stop` sends 0 once while on and nothing while off.
The spec's mutation -- a gate that ignores the strength -- cannot fail here,
because the speed is the strength's share of full and is 0 at 0; a gate
that ignores the window (the mutation used, tried) fails the no-window
line. `test_padrec.py` is unchanged: the sink is a setter. Whether the pad
rumbles in a battle with the game's Vibration option on, and not with it
off, is the owner's check (session A).


**CH1: gamepad chords and host buttons.** 2026-09-25, `build/scenario-ch1.log`,
`build/ch1.pad`. The pad's LB, View (Back) and the two stick clicks -- none
of them a GameCube button -- are now host buttons: the port's and the
mods', never the game's (the keyboard's Tab counts as LB). `window.c`
reads them beside the pad; a pad script names them `lb`, `view`, `ls` and
`rs`, in si.c and in scenario.py alike. si.c takes them on the first read of
each frame, so a chord read three times a frame fires once, and holds none
during a replay, which is the whole input. A chord fires on the frame its
last button goes down: View+LB is fullscreen (H19a), View+RS turbo (M11a),
View+LS the menu (M8); main.c's handler has one arm per chord and today
each logs `(not built yet)`. A chord writes `# chord F keys action` into a
recording, which the replay passes over. Mods get `host_buttons` (appended
to `SoaModApi`; a mod built before it still loads). Port 1 now follows the
pad: the first connected XInput slot of the four, kept until it goes, so a
pad Windows puts in slot 1 or 2 plays.

The title scenario with `1700:view+lb,1800:lb,1900:view+rs` added to its
pad passes its four checks; the log has exactly `[chord] frame 1700: view+lb
-> fullscreen (not built yet)` and `[chord] frame 1900: view+rs -> turbo (not
built yet)` -- none at 1800, where LB is alone -- the `[si]` lines show no
button change after 1650, and the recording holds both `# chord` lines. The
spec's mutation, LB mapped to Z as well, shows `buttons 0010` at 1700 and
1800. Checks: `test_padrec.py` (the host bits for exactly the frames held and
no report changing, one chord for ten frames read three times, LB alone not
a chord and View arriving under it one, each name parsed and a misspelling
refused, the chord a comment in the recording and absent from its replay);
`test_scenario.py` (the grammar); `test_mods.py` (`host_buttons` as si.c
gives it; map-log built against the header before it still loads). The
owner's check -- a pad in slot 1 or 2 plays port 1 -- is session A's.


**P11b: hold LB to skip dialogue.** 2026-09-25, `build/p11/skip.log`. With
`mods/autotext` on, holding the host button LB (CH1; the keyboard's Tab)
presses A in states 3 and 4 -- text appearing, and a complete page -- two
frames down and two up for as long as it is held: a press in state 3 shows
the page at once and the next turns it. Never in a choice box, never on a
page the game turns itself, never over the person's own A or B; let go, and
the ordinary auto-advance takes over. Host buttons are not in recordings
yet, so the first skip says once that a replay will not skip.

P11's run with `3000:lb#2400` added: skip presses at 3086 (state 3), 3090
(state 4) and 3096 (state 3); the officer's page, which took 54 frames from
its first 3 to the choice with auto-advance alone, took 10; the choice
still rested at 6 until the A at 6000, and `a002b` came after the A at 7300.
`python tools/tests/test_mods.py p11b <log>` checks those rules: `ok` on it,
and on the same run without the `lb` item (the mutation, `build/p11/on.log`)
it names no skip press in state 3 and a first choice 54 frames after the
first 3. Its pytest feeds it a synthetic log with each rule broken in turn.
On the fake guest: presses at frames 1-2, 5-6 and 9-10 through states 3
and 4, none after LB is let go on a page already pressed, none in a choice,
on a flagged page, in state 8 or 1, and with LB clear only the auto-advance
at its delay.


**H19a: fullscreen and a window that fits.** 2026-09-25,
`build/scenario-h19a.log` (DXGI), `build/scenario-h19a-gdi.log` (GDI). The
window was a fixed 2x with no resizing, and at 150% scaling on a small
screen it was taller than the screen. Now: the process is per-monitor DPI
aware, so the client is physical pixels; the window starts at the largest
whole multiple of 640x480 that fits the monitor's work area (`SOA_SCALE`
still wins); it can be resized and maximised, and the swap chain follows
(`ResizeBuffers`, the last frame shown again at the new size; minimised,
nothing); and the picture goes where `runtime/picture.c`'s `picture_layout`
puts it -- the largest whole multiple (`scaler = integer`, the default) or
the largest 4:3 that fits (`fit`) -- centred with black bars, the same
rectangle in the DXGI and GDI paths. F11, Alt+Enter and the View+LB chord
switch borderless fullscreen (the chord's arm, CH1's, now posts to the UI
thread; headless it says `(no window: logged only)`); Alt+Enter no longer
presses START; Escape in fullscreen leaves it; the cursor hides in
fullscreen and after two seconds still. H8's sync interval moved into
`present_interval`, the rule unchanged, and follows `WM_DISPLAYCHANGE`.

On the owner's 3440x1440 display at 85 Hz, `SOA_WINDOW_TEST=fs@300,win@600,
size:1000x700@900` over the title: fullscreen, client 3440x1440 (the
monitor), image 1920x1440 at +760+0; back in a window, 1280x960 (2x, the
largest whole multiple that fits the work area); at 1000x700, 640x480 at
+180+110; `0 failed present(s), 0 failed resize(s)` -- the same in each of
the two runs, DXGI and GDI, each checked on its own by `python
tools/tests/test_picture.py <log>` (the rectangle is the Python twin's for
its logged client and mode, inside the client, 4:3 within a pixel, centred
within a pixel, the client the monitor's in fullscreen). The `[window]`
lines report the rectangle the presenter computed, so they check the layout
and the window's sizes, not the pixels drawn; the picture itself, the
cursor and Alt+Enter not pressing START are the owner's check (session A).
`test_picture.py` holds picture.c built alone to the spec's cases and to
the twin over a grid of clients, and its two mutations fail: width and
height swapped in the fit fails three cases, a plain `round(hz / 30)` fails
85 and 144 Hz.


**M5b: a first run without a terminal.** 2026-09-25, `build/logs/`. A
double-click starts `gen\soa.exe` in `gen\`, where every relative path the
port uses -- the card, the disc, `soa.ini`'s own -- meant something else,
and its console showed a wall of log. Now:
- **the port root** is the exe's folder, or the parent of the nearest folder
  named `gen` that sits beside `runtime\` (so `gen\clang\soa.exe` finds the
  same one); `SOA_ROOT` overrides it for tests;
- **soa.ini** is `<root>\soa.ini`, then the one beside the exe (the log says
  which when both exist); `SOA_SETTINGS=<path>` names a file;
- **its relative paths** (`disc`, `mods`, `card`, `record`) are the root's;
  the environment keeps its own meaning;
- **when a file was read**, the card defaults to `<root>\build\cards\slotA.raw`,
  the disc to `<root>\extracted`, `mods` to `<root>\mods` when a mod-backed
  key is set, and `render` to 1; with no file nothing changes, and every
  check runs with none;
- **the console goes and the log stays** only when the process owns its
  console and stderr is that console: the log is then
  `<root>\build\logs\soa-YYYYMMDD-HHMMSS.log`, whose first line names it;
- a recording names a card under the root by its path from the root;
  aram.c's census reads the disc main.c settled on, not `argv[1]`; and
  `unfocused = mute` silences the game and ignores the pad while another
  window is in front (the samples handed to the device are zeroed; the WAV
  and the meter still hear the game).

The order of the log redirect was found by measuring, in a small program
started the way Explorer starts one: reopening stderr and stdout on the file
and then freeing the console left the file empty; two opens of one file
kept two offsets, and stderr's next line overwrote stdout's. What works is
the console freed first, then stderr reopened on the file and stdout pointed
at the same descriptor -- every line, in order.

Live: started from `%TEMP%` by `Start-Process` with a test `soa.ini` naming
only `nosound = 1` and `SOA_FRAMES=600`, the run wrote
`build\logs\soa-20260925-185448.log` (first line naming it), its `[exi]
memory card` line names `<root>\build\cards\slotA.raw`, the disc was
`<root>\extracted`, and neither `gen\build\` nor `%TEMP%\build\` appeared.
Started under a new console with stderr a pipe (`CREATE_NEW_CONSOLE`), the
`[run]` report came down the pipe and no log file appeared. Checks:
`test_settings.py` (relative paths under the root, absolute kept, the
environment as given; the defaults only with a file; the root rule for
`gen\soa.exe`, `gen\clang\soa.exe` and an exe elsewhere; the console
decision for (1, char) only), each of the spec's three mutations failing --
resolving against the current directory, dropping the handle-type test,
looking only at the exe's own folder's name; `test_padrec.py` (a card under
the root named relative to it, one elsewhere as given); the self test's new
case (muted, the device gets zeros; unmuted, the block's samples), which a
mute that does not reach the samples (tried) fails. The double-click with
the owner's own `soa.ini`, and `unfocused = mute` on alt-tab, are the owner's
checks (session A).


**M19: a clock that survives sleep.** 2026-09-25, `build/scenario-m19*.log`.
The guest's timebase was wall time since its first read, times
`SOA_SPEED`, from `timespec_get(TIME_UTC)`: a system clock step moved it,
and a machine put to sleep woke to a clock a minute ahead -- the game's play
time jumped and every deadline in the gap fired at once. `runtime/clock.c`
now accumulates speed x the host's monotonic time between reads (QPC), and a
gap between two reads longer than `SOA_CLOCK_GAP_MS` (250) counts as no time
and bumps an epoch. Guest time cannot run backwards; a pause (the system's
own suspend, `WM_POWERBROADCAST`, or `unfocused = pause`) is excluded, with
the guest thread held at tick.c's safe point; a speed change is continuous.
dsp.c starts its audio DMA deadline again from now after an epoch change,
instead of catching up block by block. `[clock] origin at W s` gives the
first read, and the `[run]` line the gaps and the seconds excluded.
`SOA_CLOCK=utc` keeps the old source for one release.

Headless title runs, each checked on its own: with `SOA_STALL=600:10`, one
gap, `frame 601: a gap of 10.0 s wall counted as 0 s of guest time`, and
70.0 guest seconds against 80.0 wall (the origin 0.004 s), four checks
passing; the same with `SOA_CLOCK_GAP_MS=0` (the mutation), no gap line and
79.9 guest against 79.9 wall. Ordinary runs trip nothing: the title (69.8
against 69.8) and the battle scenario's 12,000 frames (405.8 against 405.8)
log 0 gaps, and `speed --check` at `SOA_SPEED=10` passes with 0 gaps. **One
limit, measured:** the first stall run went beside a compiler building the
P3 worker's tests, and logged two more gaps, 0.5 s at frame 1 and 0.8 s at
frame 951 -- the guest thread starved that long without reading the clock
-- which the rule, by its own definition, counts as no time; rerun on a
quiet machine, the same command logged the one gap only. A heavily loaded
host can trip the rule; what it costs is that much guest time not counted.

Checks: `test_clock.py` (clock.c built alone on synthetic host times:
steady steps, a 10 s gap counting 0 and one epoch -- or 10 s with the rule
off -- a backward host step, a continuous speed change, a pause excluded,
and a peek that writes nothing); the self test's new case (above) and its
mutation; `test_profiler.py`'s clock driver now reads the timebase every 10
ms, as a guest does, where it used to read once and sleep 1.2 s -- which is
now, correctly, a gap.


**P3: `.gci` import and export.** 2026-09-25, from a worker in a worktree,
merged as its own commit. `python tools/cardformat.py export CARD --name
NAME` writes a save as Dolphin keeps it -- the 0x40-byte directory entry,
then its blocks along the chain -- and `import CARD IN.gci` puts one onto a
card: a new image by default, or `--in-place` after writing a dated `.bak`
and only while no `soa.exe` has the card open. Blocks are allocated from the
table's last-allocated + 1, as the card library does [I, recalled from the
SDK, not disassembled]; the new directory and table go into the slot the
mount would read as older, with a check code one past the other's, and the
newer slot is left byte for byte as it was -- the card library's own
alternation, which keeps the previous state as the backup. Every refusal the
spec lists holds and writes nothing (another game or maker, a size that
disagrees with the entry, no blocks, too few free blocks, no free entry, a
name already there without `--replace`, a card that does not mount READY),
and what was written is read back from disk and must mount READY, leave the
kept slot unchanged and export back as the file imported.

The tests are synthetic (cards the tool formats, entries over random
blocks): import to READY, export equal to the input but for the start block,
a round trip into a second card, two imports on disjoint chains, the slot
rule under four check-code layouts -- a fresh card, one update on, the two
pairs picking different slots, and codes across 0x7FFF and 0xFFFF -- and
each refusal, "too few blocks" on the 4 Mbit geometry and "no free entry"
on a 16 Mbit card holding 127 files. Writing into the newer slot, and
leaving the check code as it was, each fail all four slot cases. **One
thing it found:** a directory whose check code is 0x7FFF gets 0x8000 as the
rule says, and the mount's signed comparison then reads the new copy as the
older -- the import would be invisible. The command writes it, then exits 1
and says why; the game's own 32,768th save would meet the same. The export
name, `<maker>-<game>-<name>.gci`, follows Dolphin's naming as remembered,
unchecked against its source. Importing a Dolphin save and loading it, and
loading a port save in Dolphin, are the owner's checks (session B).


**P10a: a second pad, for mods.** 2026-09-25. The groundwork for couch
co-op (P10b's mod): port 2 is read, and the game never sees it. `window.c`
takes the next connected XInput pad after port 1's, probed once a second
while there is none; in checks, `SOA_PAD2` is a script in `SOA_PAD`'s
grammar -- si.c's parser now works on a struct, so both scripts use it,
with its refusals. Mods read it with `read_pad(2, &pad)`, appended to
`SoaModApi` (1 when something is there), through setters so si.c and mod.c
still link alone. `g_present` stays `{1,0,0,0}`: a direct SI transfer on
channel 1 still ends in no reply, so the game's controller count does not
change. Pad 2 is not in recordings yet (the event track's). Checks:
`test_padrec.py` (SOA_PAD2's presses, holds and repeats; its refusals, named
as SOA_PAD2's; a press in either script never reaching the other port; and
channel 1 answering nothing with SOA_PAD2 set -- which marking channel 1
present, tried, fails); `test_mods.py` (`read_pad(2)` as si.c gives it,
ports 1 and 3 nothing, and map-log built against the header before the
append still loads).


**P5b: deflicker off.** 2026-09-25, `build/p5b-fifo/`. The game copies
every frame to the screen through its deflicker filter (16/32/16 over three
rows, FINDINGS "C3"), made for an interlaced television; on a progressive
display it only softens. `SOA_DEFLICKER=0` (`deflicker = 0`) collapses the
screen copy's kernel to the identity before the copy decides whether it is
filtered, so it takes the unfiltered path and its fences; copies to
textures -- the game's own effects -- keep its weights. Checks:
`test_gxr_copy_filter.py` has, with the switch set, the display copy under
the game's weights equal the identity copy byte for byte and a texture copy
under the game's weights still differ from the identity; applying the
switch to texture copies (tried) fails the second. `python
tools/scenario.py replay` is 23/23 with the switch unset (the sweep drops
`SOA_*`), and with it set every one of the 23 captures, replayed from a copy
outside `build/fifo`, hashes differently from its manifest line; the
battle's 12000, the cutscene's 4500 and the logo's 0300 were opened: the
battle's text and edges sharper than the deflickered frame beside it, the
others clean.


**M19, followed up: 2 s, the census before the clock, and no DMA resync.**
2026-09-25, `build/m11a/`, `build/scenario-m11a*.log`. M11a's runs, made on
a host loaded by another session's research, showed M19's 250 ms threshold
to be too tight. Two kinds of the port's own work stall the guest thread
past it without its reading the clock:
- **the ARAM census**, which read the head of every one of the disc's 5,552
  files at the first ARAM DMA -- 0.3-1.1 s at frame 1 in all four ceiling
  runs. It is built now before the game's first instruction, where no clock
  runs (`aram_census_prepare`);
- **a snapshot frame**, drawn after 99 undrawn ones with `SOA_SNAP=100`:
  seven gaps of 0.3-1.8 s at frames 4101 to 7501, one frame after a
  hundred, in the turbo battle run -- eight with the census's, 6.4 s in
  all.

The default is 2,000 ms now: past every stall of the port's own measured
here, and still far below a sleep; the stall check's 10 s is caught as
before. The audio DMA also no longer restarts its deadline at an epoch
change: the clock counts no gap, so an epoch brings no backlog of its own,
and the restart only threw away blocks owed from before it.

What that cost is smaller than the first reading said. The turbo battle
logged 116,247 bytes of audio a wall second where 128,000 is right, but its
wall seconds held the 6.4 s the clock excluded; per guest second it was
118,005, and the same run with both changes 119,550. The rest of the gap was
in every run, turbo or not -- the plain battle gave 121,475 -- and had
another cause (the next entry). The self test's epoch case now holds the
owed blocks delivered across an epoch; restarting fails it.


**The AI DMA's pace: a write while the engine runs is not a restart.**
2026-09-25, `build/scenario-aidma*.log`, `build/scenario-aictl.log`. The
audio reached the device 5% slow in every run: the plain battle scenario,
13,500 frames over 457.1 guest seconds, played 86,743 AI DMA blocks of 640
bytes -- 189.8 a second where 200 are due, 121,475 bytes a second where
128,000 are. The blocks were at the right pitch; there were just too few of
them, so a device fed 95% of what it plays spent the rest waiting. M2's
"output near 30,000 samples a wall second" (above) was this, measured and
passed as the audio being as it was: the first reading against the rate
itself was M11a's, which needs it for turbo.

The cause was `dsp_write`'s control register. Every write with the enable
bit set started the deadline again from now. The game makes one such write
each block, from `fn_802416E4`: interrupts off, the start address, then
`0x5036 = (0x5036 & 0x8000) | length >> 5`, keeping bit 15, interrupts back
on -- AIInitDMA's shape. `fn_8024176C`, the next function, sets bit 15 and
is the start. The sound driver's setup, `fn_802851E0`, hands `fn_802850C4`
to `fn_802416A0` (AIRegisterDMACallback's shape) and calls `fn_802416E4`
once with a 640-byte buffer; after that `fn_802850C4`, the DMA callback,
calls it at every AIDINT to queue the next buffer. So each block's clock
began when the callback ran, not when the last block ended: every block a
delivery late. The title scenario now reports it -- `[dsp] AI DMA control
writes: 1 start(s), 13982 while running (the first with LR 80241704), 0
stop(s)` against 13,982 blocks -- one write a block while running, one
start.

A write while running now sets the length for the next block and leaves the
deadline alone; only a write that turns the engine on starts it. The battle
scenario plays 91,716 blocks over 458.6 s, 128,000 bytes a second, and the
title 128,000 too. The self test's pace case holds three owed blocks
through a running write; the old rule plays none of them.

With the device fed as fast as it plays, a stall the clock counts now
overfills its 24-block queue: the battle dropped 77 blocks in 10 runs, the
longest 34 (170 ms) -- 208 in the run before, which did not count runs --
and the title 39 in 3 and, run again, 12 in 4. Runs, not single blocks
spread over the run, which is what a device slower than its rate would give.
The old pace never dropped anything because the queue was always empty. The
report counts the runs now.
