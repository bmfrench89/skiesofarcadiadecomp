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

*Amended 2026-09-30:* C5b has landed; see "C5b" at the end of this file.


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


**M11a: turbo up to 2x, in battles and the sky.** 2026-09-25,
`build/m11a/*.log`, `build/scenario-m11a*.log`. `SOA_TURBO=battle|sky|both`
(`turbo`, recorded) lets the frame end's spin go after one field while the
game is in a battle -- scene 7, or scene 6 on a map of 500 or more, the ship
battles -- or in the sky, the sky-mode word `0x80347464` at 1. tick.c decides
at the loop's safe point and keeps the answer for the frame; View+RS flips it
from the next one. The window follows it: `present_interval(hz, 60)` while
on, `(hz, 30)` off, the rule H19a gave the normal case in both (60 Hz: 1
against 2; 85 Hz: 1 and 1; 120 Hz: 2 against 4; 144 Hz: 1 and 1).

**The first step, the ceilings (comfort-pack 3.14).** Uncapped, headless, at
`SOA_SPEED=4` so the pacing is not the limit:

| | guest alone (snapshot mode) | drawn every frame |
|---|---|---|
| battle, frames 9950-11898 | 104.9 a second, p95 14.3 ms | 35.0 a second, p95 48.2 ms |
| sky, frames 3100-4998 (the world map, from `card-partK`) | 110.9, p95 12.1 ms | 37.6, p95 43.9 ms |

The guest makes more than 60 at p95 in both, so H13 stays closed. Drawn
every frame neither comes near 60: the renderer is the limit. Those four
runs shared the host with another session's research. A windowed run on a
quieter host drew more and still fell well short: the battle at turbo, in a
window at 85 Hz, made 42.9 images a second (p95 35.0 ms), and the game's
frame counter advanced 0.717 a retrace where 1 is 2x. So turbo in a window
is about 1.4x today. Only snapshot runs, which draw one frame in a hundred, reach 2x. The full
2x in a window is M11a-skip, which 3.14 left to this measurement.

**The check** (`tools/tests/test_turbo.py <log>`) holds a turbo battle to a
same-run contrast: the counter at one a retrace over the battle and one per
two over the field before it, each within 5%; the battle over inside the run;
and the audio at 128,000 bytes a wall second within 3%, because turbo must not
speed the music. The battle scenario at `SOA_TURBO=battle` passes it: 0.974
over frames 9810-11878, 2,069 frames at turbo, 0.499 over the field, 128,000
bytes a second, no clock gaps. The same run without turbo fails it (0.495 in
the battle), and so does `SOA_SPEED=2`, whose audio doubles. The check's
audio rule is what found the AI DMA's pace (the entry above): before that
fix every run, turbo or not, failed it at 121,475.

The chord: a run pressing View+RS at frame 1900 logs `[chord] frame 1900:
view+rs -> turbo on`, then `[turbo] frame 1900: on`. In a window the
presenter logs `[window] frame 9812: turbo on, each frame held 1 refresh(es)`. This display runs at 85 Hz, where the interval is
1 either way, so the switch changes nothing here that can be seen; the 60 Hz
and 120 Hz rows are held by `test_picture.py`, whose plain-round mutation
fails at 144 Hz alone.


**P5a, the filters: gamma, colour blindness, and a flash limiter.**
2026-09-25, `build/scenario-p5a-*.log`, `build/frames/0880.png`-`0940.png`.
The native half of the spec's 3.13. `runtime/picture.c` filters the frame at
its own 640x480 before the scaler, in window.c's present and in `--replay`:
the colour-blind model in linear light, then gamma, then the flash limiter on
what the two made. `sharp` and `crt` wait on `docs/specs/display.md`, as the
planning session asked. The nearest-neighbour scaler moved into picture.c
unchanged (`picture_scale`), so the replay's picture and the window's are
one code.

- **Colour blindness** is Machado, Oliveira and Fernandes (2009) at severity
  1 in linear light; correction is daltonize's `rgb + C (rgb - sim)`, folded
  into one matrix per kind. `test_picture.py` holds the three matrices to
  3.13's own text to six places, in picture.c and in its Python twin, so one
  typo in both cannot pass; all six kind-and-mode pairs to the twin over 91
  colours within a step a channel; grey to grey. Gamma 1.0 changes no byte
  and 2.2 takes mid-grey 128 to 186. A bad value in one key is refused by
  name and leaves the others on -- in the first cut a typo in gamma switched
  the flash limiter off.
- **The flash limiter** counts WCAG's general flash for each pixel. A pixel
  keeps the luminance it last turned at (before its first turn, the lowest
  and highest it has shown); a move of 0.1 or more from there, the other way,
  with the darker below 0.8, is half a flash, and the opposite half inside a
  second ends one. A pixel that ends a fourth flash inside a second is over
  the limit for a second after. When the pixels over it, with those that
  would end a fourth now, would cover a quarter of the frame, the frame is
  blended toward the one shown before by the most that keeps them under a
  quarter; the search looks only at the pixels at risk, and the frame it
  picks is checked whole. The report gives the largest share of the picture
  that was ever over the limit.
- **The tests feed whole frames and count every pixel independently.** The
  spec's 5 Hz, black and white in turn at 30 and 60 a second, a flash built
  of steps of 0.075, two halves swapping, the spec's 5 Hz over a gradient, a
  white overlay pulsing over a busy picture, a flash sweeping down in bands,
  and a flash of 0.12 about a pixel's first light: each flashes over more
  than a quarter of the picture as given and under a quarter as shown. Two
  flashes a second, a fifth of the frame, a step under 0.1 and a change
  among bright values are shown untouched. Eight mutations each fail: the
  colour model in sRGB, gamma inverted, a limiter that never acts (the 5 Hz
  gets through) and one that always acts (the 2 Hz is touched), a fourth
  flash let through, a fifth of the frame counted as enough, flashes measured
  frame to frame, the quarter judged a frame at a time, and a pixel that
  forgets its first extremes.
- **It took three designs; two were wrong.** The first judged each frame
  against the one before -- half a flash was a quarter of the pixels moving
  0.1 the same way. In a window over the title it held 8 frames of the
  opening's cloud whiteout at 980-998, opened from captures: cloud moving
  past makes a quarter of the pixels lighter and another quarter darker in
  the same frame. It also missed a flash spread over several frames and two
  halves that swap. The second counted each pixel from its last turn but
  judged the quarter one frame at a time. An adversarial review -- three
  reviewers, each finding put to a skeptic: 14 findings, all confirmed --
  showed it let just under a quarter of the pixels end a fourth flash on
  every frame, different pixels each time: the spec's 5 Hz over a gradient
  left 72% of the picture flashing six times a second, a white overlay over a
  busy picture 100%, and a flash sweeping down in bands was never held. The
  tests had missed it because every flashing pixel in them was the same.
- **What it does to the game.** In a window over the title scenario the
  third design holds 114 frames from frame 909, during the opening's flight
  through cloud, most of them shown 1% of the way. That is the rule as
  written: the frames 880-940, snapshotted unfiltered (`SOA_SNAP=1@880-940`,
  a range new here) and measured the same way by the test module's own code,
  have up to 66% of the picture flashing more than three times a second --
  50% over cells of 40 pixels, 25% over twelve cells of 160. The frame's
  mean luminance moves only between 0.29 and 0.48, so the flashing is
  regional, cloud and blue sky passing fast. Whether a limiter should damp
  that is the owner's call in session B; it is off unless set.
- **Also from the review:** a resize no longer shows the limiter the same
  frame twice; the replay writes the picture whenever a key is set, at any
  value, and not after a replay that failed; `SOA_PICTURE_SIZE` with anything
  after WxH is refused and a bad `SOA_SCALER` is named; the report reads the
  present's timings under a lock; the GDI path's paint is inside its time.
- **The replay** (3.13's Done): on copies of the title (0300), a field (4500)
  and a battle (11900) outside `build/fifo`, every key at its identity value
  with `SOA_PICTURE_SIZE=640x480` gives a `.picture.png` with the same pixels
  as the `.png` by `python tools/tests/test_picture.py --same`, and
  `gamma = 1.01` makes them differ. Opened: the battle simulated for
  deuteranopia (the red damage figure and green bar to yellow, the green
  enemy to grey-olive) and for tritanopia (the blues to teal, the deck to
  pink); the field corrected for deuteranopia (a 2x picture centred in
  1920x1080) and for protanopia (the crest's maroon to purple, the crystals
  to green); the title at gamma 1.8, which barely moves on a card of white,
  black and red.
- **The cost, and the budget not met.** The present's own work, the frame to
  the back buffer, at 2x over the title: p50 2.89 ms and p99 4.40 with no
  filter; p50 5.82 and p99 12.80 with gamma 1.2, deutan correction and the
  flash limit. Fullscreen at the display's 3440x1440: p50 6.85, p99 10.08
  with none; p50 10.26, p99 17.65 with all three. 3.13's budget is p99 under
  6 ms at the device's resolution, and the present misses it before any
  filter: the scaler writes the whole back buffer on the CPU and uploads it
  every frame. That is the presenter's to fix, with display.md's `sharp` and
  a scaler on the GPU; the filters' own 3 ms at p50 can go to SIMD or a
  worker then.

Also here: README's list of `soa.ini` keys had not named M11a's `turbo`,
and nothing noticed; `test_settings.py` now holds that list to every key
`settings.c` reads.


**P10b's spike: the battle's command wheel, read.** 2026-09-25,
`build/scenario-p10spike1.log`-`5.log`, snapshots `build/frames/10230.png`-
`10520.png`. The battle scenario (the deck fight: Vyse party slot 0, Aika
slot 1; port 1's script A every 150 frames from 3600) with `SOA_PEEK` of the
phase word `0x8034733C`, the member choosing `0x80347330` (a word, loaded
`lwz r13-29680` at `0x8007C7D0`) and the four command words `0x80309174 +
32 * m`, every frame from 9780, and extra presses on Aika's wheel:
- **Phase 0 -> 1 at frame 9946 sets every command word to -1**; Vyse's reads
  3 (Attack) the frame after, before any press: the wheel opens on Attack.
- **Each member takes two A presses for Attack**, the command and the
  target; the member word goes 0 -> 1 on Vyse's target A (10200 -> 10201),
  and phase 1 -> 2 on Aika's (10501). At that edge both words are 3. Aika's
  word stays -1 until her command A: it is written on the choice, not as the
  cursor moves.
- **The wheel, from Attack:** one left is Item (5) and one right Magic (1);
  two or more rights stop at Focus (0), and five or seven lefts at Run. It
  does not wrap. Item's and Magic's menus take A without moving on in this
  battle, so a check whose presses land there stalls; Focus needs no target.
- **B on Aika's wheel gives the turn back to Vyse** (member 1 -> 0 at
  10421); B on his does nothing; the wheel opens on Attack again after.
- Round 2 repeats round 1 from phase 1 at 10944.


**P10b: couch co-op in battle.** 2026-09-30, `build/scenario-p10.log`,
`build/p10.pad`, `build/scenario-p10-mut.log`. `mods/coop` (manifest 2, id
`coop`) is one `pad_filter`: with `SOA_COOP=1` (or `1,3`: party slots 0-3),
while a battle takes the party's commands and the member choosing is one of
those slots, the game's port 1 reads pad 2 (P10a's `read_pad`) in place of
player 1's. When the turn passes between the pads the incoming pad is read
as let go -- buttons, sticks and triggers -- until it has no button down.
Pad 2 absent, port 1 plays everyone, said once. The mod logs each handover,
each press forwarded from pad 2, and at each phase 1 -> 2 edge every
member's command type.

- **The live run:** the battle scenario with `SOA_MODS=mods SOA_COOP=1
  SOA_PAD2=10225:right,10245:right,10270:a,10420:a@150
  SOA_PAD_RECORD=build/p10.pad`. Pad 2 took Aika's turns at frames 10202,
  11102 and 12002. On the first its two rights and A chose Focus -- logged
  `frame 10272 commands: 0=3 1=0 2=-1 3=-1`, and snapshots show her wheel on
  Focus at 10260 and the Focus banner at 10300 -- where port 1's script
  chooses Attack (3), as spike run 1 did with the same script; on the next
  two its A presses chose Attack. `python tools/tests/test_mods.py p10b
  build/scenario-p10.log build/p10.pad` passes: on pad 2's turns the game
  read only presses forwarded from pad 2, never port 1's A-every-150;
  outside them only port 1's recorded presses; Aika's first command was
  Focus; a direction was forwarded; and the recording still holds port 1's
  A presses on her turns, taken before the filter. The same run with
  `SOA_COOP=` (the Done's mutation) fails it: pad 2 never had a turn.
- **The fake guest** (`test_mods.py`) holds the rest: the filter follows the
  member and phase words and only in scene 7; a handover passes neutral while
  the incoming pad holds A until every button is up, and only the next A
  confirms (without the rule the held A confirms at once); sticks and
  triggers are neutral in the hold and pad 2's are forwarded whole; pad 2
  absent leaves port 1 playing; one commands line per 1 -> 2 edge and one
  line per press; off and refused values filter nothing. Each rule has a
  mutation that fails it.
- **An adversarial review** (three reviewers, each finding put to a
  skeptic; 10 confirmed, 3 refuted) found what those first tests missed,
  now fixed. Pad 2 was read under `unfocused = mute`, so co-op passed its
  presses to the game from behind another window; it now reads as let go,
  still connected. Pad 2's sticks had no dead zone and its triggers passed
  raw; one mapping (`map_xinput`) now serves both ports. No test looked at
  sticks or triggers, the scene gate, or how many times a line was logged.
  A `coop` value the mod refuses was still recorded, and `coop = 1, 3`
  split the config line at its space: the recorder now applies the mod's
  own test (`test_settings.py`). README's key list lacked `coop`, which
  test_settings.py's new key-list test caught first.
- **Pad 2 is not in recordings yet** (the event track's), so a co-op
  session does not replay: port 1's recorded presses would take pad 2's
  turns. The mod says so at its first forward.


**L3a: toolchain profiles and `--cc`.** 2026-09-30. `tools/soa/toolchain.py`
has a `Profile` for msvc, clang-cl, gcc and clang (portability.md 3.9), and
`recompile.py --cc clang-cl` writes everything -- the C, the objects, the
exe -- under `gen/clang`, never `gen`, and builds no mod. The msvc profile's
command lines are the ones recompile.py ran before, held to a golden copy by
`test_toolchain_profiles.py`; they are now pure functions (`compile_command`,
`link_command`, `link_plan`), and `--link` runs the plan. One change in
behaviour: the decompiled units' objects are named from the units, not
globbed, so a stale object in `gen/decomp` is no longer linked.
- **The clang-cl found here** is the Android NDK's 19.0.1 (`SOA_CLANG_CL=
  C:\Users\bmfre\AppData\Local\Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin\clang-cl.exe`). It defaults to `lld-link`, which the NDK does not ship, so its
  links failed with "program not executable"; the profile carries
  `-fuse-ld=link`, MSVC's linker, on lines that link (`Profile.linker`, a
  field the spec's table did not have). `/D_CRT_SECURE_NO_WARNINGS=` is
  defined empty, as the files that define it themselves do, which quiets a
  redefinition warning in each of them (17 of the 28 runtime files).
- **Measured:** `compile_runtime.py --cc clang-cl` compiles 27 of 28;
  `gxr_tev.c` fails with the SSE4.1 always_inline error of portability.md
  2.2, L2a's to fix. `dc_check.py --cc clang-cl` passes, all nine routines;
  `render_check.py --cc clang-cl` stops at the same `gxr_tev.c` error.
- **No FMA:** `test_toolchain_fp.py` builds `a*b+c` with `-mfma` under the
  clang-cl profile -- `vmulss` then `vaddss` -- and without
  `-ffp-contract=off`, the mutation, `vfmadd213ss`. It skips where no clang
  and llvm-objdump are found, as in a default run here. CI's Windows
  runner ships LLVM, so its Tests job runs both ("L3a's review", below).
- `scenario.py replay --bless --exe gen/clang/soa.exe` is refused: the
  manifest pins the MSVC build. Removing the guard turns its test red.
  `title --check` passes (4 of 4), since scenario.py changed.
- An adversarial review was started and stopped at the owner's request
  before any finding came back; it was run again the same day ("L3a's
  review", below).

**L3a's review.** 2026-09-30, on 8bd7c79. The adversarial review that was
stopped was run again in three lenses -- does msvc build as before, can the
tests pass a wrong plan, does it do what 3.9 says -- and each finding was
checked against the code and against CI before it was fixed. **What MSVC
builds did not change**: a script rebuilt the parent's `--link` sequence
against the real `gen/`, `units.txt` and `mods/` and compared it with
`link_plan`, and all six commands and their working directories were equal.
Seventeen findings, none of them in what MSVC builds:
- **The tests could pass a wrong plan.** Twenty-two mutations of
  `toolchain.py` and `recompile.py` were each run against the tests in a
  copy of the tree, and each had left them green: `--out` defaulting to `gen`
  in `main()` (the test built its plan from `CLANG_CL.out` itself), clang-cl's
  lines taking `CFLAGS` instead of its own (equal for msvc, so the golden
  copy could not tell), the link dropping `-fuse-ld=link`, the plan dropping
  the decompiled units' objects or globbing `gen` for its chunks, a compile
  writing `../chunk_000.obj`, a pdb sent elsewhere through the linker's
  `/PDB:`, `/fp:fast`, a strict warning removed (the strict-set test compared
  `compile_runtime.STRICT` with the list it is defined from). The module now
  holds 3.9's table as literal copies, the whole msvc `--link` plan as a
  golden copy, and every path of a clang-cl plan from its own working
  directory, inputs included; all twenty-two fail it.
- **`test_gxr_fastpath.py` linked without `Profile.linker`**, so under the
  NDK's clang-cl, which has no lld-link, it would have failed at link the day
  L2a let `gxr_tev.c` compile. It carries it now.
- **`--cc clang-cl --out gen` was accepted**, and would have linked a clang-cl
  runtime with MSVC's chunks into `gen/soa.exe`, which `replay --bless` trusts
  by its path. `recompile.out_dir` refuses it in any spelling and is where
  `main()` takes its default from.
- **A `SOA_CLANG_CL` naming no file** fell through to whatever clang-cl was on
  `PATH`; it now finds none, so a typo cannot test another clang's version.
- **The gnu profiles, first used by L4b:** `--compile` swapped only `/O2`, so
  gcc validated at `-O2` while printing `/Od` (now `-O0`); the profiles lacked
  3.9's `-pthread -lm`, and every link put the linker flags before the
  objects, where GNU ld ignores `-lm` (now after them); `gnu_args` read a
  POSIX path such as `/Data/soa/gx.c` as a `-D` (an existing absolute path now
  passes through). Left for L4b: `/Fo` naming a directory, which every citest
  driver uses, has no gcc spelling with several sources.
- **`link_command` added `runtime_support_sources()` to a glob of every
  runtime file**, so `plat.c` would have been linked twice once L7 made it;
  that list is for the tests that link a few runtime files.
- **Wording:** `--compile` and `--link` printed "msvc" where TESTING.md quotes
  "MSVC"; the msvc profile prints MSVC's lines again, and others add their
  directory. `ARCHITECTURE.md` still said recompile.py drives MSVC directly.
- **Counts.** CI's Windows runner ships LLVM, so its Tests job runs both FMA
  probes: 1077 passed, 4 skipped at 8bd7c79 against 1067 and 4 at f740207,
  ten more passing and no more skipped. TESTING.md said they skip on CI, and
  its table of counts had been worked out from older rows rather than
  measured. The rows are measured now, MSVC or capstone hidden by a
  three-line pytest plugin (`-p`) that makes `toolchain.msvc_env` answer None
  or makes `import capstone` fail as a missing module.

**L2a: the SIMD blend behind an x86-64 guard.** 2026-09-30.
`runtime/plat.h` is new, with portability.md 3.2's platform tests
(`PLAT_X86_64`, `PLAT_ARM64`, `PLAT_MSVC`, `PLAT_GNU`, each 0 or 1) and its
SIMD section: `PLAT_TARGET_SSE41`, the target attribute under gcc and every
clang, and `plat_cpu_has_sse41`, `__cpuid` wherever `_MSC_VER` is defined and
`<cpuid.h>` elsewhere. `gxr_tev.c`'s guard is `#if PLAT_X86_64` instead of
`_MSC_VER && _M_X64`, and the bilinear blend is its own function,
`bilinear_sse41`: target-attributed under gcc and clang, forced inline under
MSVC. `perfbench.py run --exe` benchmarks a saved build.
- **clang-cl compiles it.** The Done's command (the NDK's clang-cl 19.0.1,
  `/c /std:c17 /O2 /fp:precise /clang:-ffp-contract=off /W3`) reports no
  error, where the base reports the three of portability.md 2.2 (two at
  :1193, one at :1196). Under `--cc clang-cl`, `compile_runtime.py` compiles
  28 of 28 and `render_check.py` passes; its unasserted second-frame hash,
  63a57c77609efd77, is MSVC's.
- **A non-MSVC x86-64 build keeps the SIMD path, and the Done's check needed
  a second compile to show it.** Android's x86-64 target turns SSE4.1 and 4.2
  on by default (its ABI requires them; `-march=x86-64` does not turn them
  off), so under the Done's command clang inlines `bilinear_sse41` into
  `sample` and no function of that name exists: two `pmulld` sit in `sample`
  instead, where the base has none. With `-mno-sse4.2 -mno-sse4.1`, a
  baseline x86-64 build, `bilinear_sse41` is its own function holding the
  SSE4.1 instructions (`pmulld` twice, `packusdw`) and `sample` calls it
  once: the target attribute doing its job. The base has no SIMD in either
  build.
- **MSVC's code: the blend's own function moved registers in `tev_pixel`.**
  Compiled with `toolchain.CFLAGS` and `/FA`, 55 of 56 functions are
  identical but for labels, `sample_level`, `sample` and `simd_decide` among
  them. `tev_pixel`, which inlines the sampler, allocates registers
  differently around the inlined wrap arithmetic: the same instructions over
  r11, r14, r15 and ecx permuted, three lines longer. The split is the cause:
  the guard and the include alone leave all 56 identical, and four spellings
  of the split (unsigned or signed words, the texel loads inside the
  function or out, a separate result) each moved `tev_pixel` the same way.
  So the Done's fallback ran: the base relinked from 8bd7c79's runtime and
  saved as `build\soa-L2abase.exe`, then `perfbench.py run --threads 1`,
  interleaved A B B A twice:

  | | ns a fragment, whole perfset, 1 thread | mean |
  |---|---|---|
  | base (A) | 40.2, 38.3, 39.6, 39.0 | 39.3 |
  | L2a (B) | 39.4, 38.7, 39.4, 39.2 | 39.2 |

  No difference: -0.3%, inside the noise and far inside the slice's 3%.
- **The blend is still exact.** `test_gxr_fastpath.py` passes, 600,000
  samples and 0 mismatches, under MSVC and, now that its link carries
  `-fuse-ld=link` (L3a's review), under the NDK's clang-cl with the SIMD path
  live. b377b1f's mutation, run once on `bilinear_sse41` -- the first weight
  pair of `_mm_set_epi16` swapped, which is channel 3's -- turns it red under
  both compilers: "MISMATCH 32x16 wrap 1/0 at -21.56,-97.65: 155,116,49,220
  vs 155,116,49,183", the alpha byte alone.
- **`SOA_GXR_NOSIMD` still reaches the scalar path.** A direct `--replay` of
  a scratch copy of capture 15800 with `SOA_HASH=1`, `SOA_SETTINGS=0`,
  `SOA_THREADS=1` and `SOA_GXR_NOSIMD=1` prints "the pixel path ran without
  SIMD" and a91622f21a14d5bb, the manifest's hash; without the switch the
  line is absent and the hash the same. Replay 23/23 at 1, 2, 3 and 8
  threads; the self test passes.

**L4a: CI's clang-cl leg.** 2026-09-30. `ci.yml` has a fifth job, `clang-cl`
("Runtime compiles (clang-cl)", portability.md 3.12): `compile_runtime.py`,
`dc_check.py` and `render_check.py` with `--cc clang-cl`, then
`test_toolchain_fp.py` and `test_gxr_fastpath.py` with `SOA_CC=clang-cl`. The
runner's clang-cl is LLVM's 20.1.8, in `C:\Program Files\LLVM\bin`, found on
`PATH`; the job's first step prints which and its version, and fails if there
is none.
- **Green before the merge:**
  [run 36766285607](https://github.com/bmfrench89/skiesofarcadiadecomp/actions/runs/36766285607)
  on the branch `l4a-clang-cl`. 28 of 28 runtime files, all nine routines,
  both render checks (the unasserted second-frame hash 63a57c77609efd77, the
  same as MSVC's and the NDK clang-cl's), and 5 passed with none skipped.
- **The mutation, red:**
  [run 36766296154](https://github.com/bmfrench89/skiesofarcadiadecomp/actions/runs/36766296154)
  on the branch `l4a-mutation`, which is that commit with `gxr_tev.c` as it
  was at 5af18b3^, L2a's guard reverted. The leg fails on `gxr_tev.c` with
  portability.md 2.2's three errors (two at :1193, one at :1196):
  `compile_runtime` 27 of 28, `render_check` stops compiling the renderer,
  and all three fastpath tests fail to build. `dc_check` stays green, since
  it builds no renderer, and the MSVC job on the same commit is green. The
  fastpath step failing is what shows `SOA_CC` reached it: built with MSVC,
  the reverted file compiles and the same three tests pass (run locally).
- **A skip would have been a green tick.** Both modules skip where no
  clang-cl, `llvm-objdump` or SSE4.1 is found, and pytest exits 0 on a skip.
  `tools/citest/noskip.py` is a pytest plugin (`-p noskip`) under which each
  skip is named and fails the run. In a default local run, with no clang,
  the FMA module's two skips exit 1 under it and 0 without.
- **Every check step runs after a failure** (`if: ${{ !cancelled() }}`), so
  the mutation run shows all four verdicts instead of stopping at the first.
- **LLVM 20.1.8's warnings, none of them an error.** Every clang-cl call warns
  that `-ffp-contract=off` overrides `/fp:precise`'s `-ffp-model=precise` (41
  times in the job; the NDK's 19.0.1 does not say it). The override is the
  profile's intent, and the FMA probe passing shows it holds. `strcpy.c`
  casts a pointer to a 32-bit `unsigned long` three times, the words L4b is
  for. `gxr.c:2942`'s unused `x0` warns as it does under the NDK.

**C5b: display lists recorded into guest memory, and drawn at their call.**
2026-09-30, `build/scenario-c5b-opening.log`, `build/c5-cap-*.log`. Until
now the port parsed every gather-pipe byte at once, so each list the game
recorded was drawn during the scene update that recorded it, and the draw
pass then called it empty (C5a). `runtime/gx.c` now records while the CPU
FIFO is the SDK's `DisplayListFifo`. The bytes go into guest memory at the PI
write pointer, and the list is parsed when the game calls it.
- **How the port knows it is inside the bracket.** The spec offered (a) hooks
  at the two functions, which needs a retranslation, or (b) the caller's
  return address at the PI write. The disassembly gave a third option,
  `--link` only and keyed on the SDK's own state:
  - `GXSetCPUFifo` (`fn_8024C5FC`) stores the FIFO object's address at
    `r13-27520` (`0x8024C620`) before it writes the PI base, top and write
    pointer.
  - `GXBeginDisplayList` (`fn_80251D80`) passes it `DisplayListFifo`,
    `0x80318B18`, after setting `inDispList`.
  - `GXEndDisplayList` (`fn_80251E48`) reads the write pointer's wrap bit,
    bit 26, as overflow. It then sizes the list through `fn_8024C8A4`, which
    first runs GXFlush (`fn_8024DE18`: 32 zero bytes, then `sc`). Only after
    that does it restore the old FIFO and clear `inDispList`.

  So at each PI base write the port records exactly when that global holds
  `0x80318B18`. The logo screen's redirect to `0x804024E0` uses another
  object, so it is still parsed at once. A list that outgrows its buffer
  wraps to its base and sets bit 26, and the game's call then has size 0.
- **Captures keep the list as it was called.** A capture's RAM is the frame's
  end, so a live call is captured as a `0x41` record: address, size, then the
  list's bytes inline. Only a replay reads it, and `tools/fifo.py` follows it,
  so `fifopair` and `midpoint` read new captures as the C replay does.
  Recorded bytes are not captured where they were written, so nothing in a
  replay is drawn twice. Old captures hold no `0x41` and replay as before.
- **Tests:** `test_gx_dlrecord.py`, 13 of them, on the renderer built alone.
  The SDK's Begin/End/Call sequence is played by hand. Five mutations, each
  run in a scratch worktree, turn it red:

  | Mutation | Tests that fail |
  |---|---|
  | recording removed | 7 |
  | the "bases differ" rule | 8, the logo test among them |
  | the call not captured inline | the `rerecord` replay and the inline test |
  | `fifo.py` ignoring `0x41` | the `fifopair` test |
  | no wrap at the buffer's end | the overflow test |
- **Live:** the opening to frame 1000 logs `[gx] display lists: 2746 calls,
  2746 nonempty, 6786431 bytes; 3311 recorded`. Before C5b, every call had
  size 0. `build/frames/0200.png` was opened and still shows the "Created by
  OVERWORKS" logo screen. The self test reports 0 failures, `title --check`
  4 of 4 (0 unknown FIFO bytes of 355 MB), and `replay --threads 1,2,3,8`
  23/23 with no hash moved.
- **H10 re-measured.** H4's five pairs were captured again into
  `build/perfset-c5/` (never `build/fifo`), because nothing had recorded how
  they were first made. Each card was found from its map loads and copied to
  a scratch card for the run:

  | scene | card | pad | pokes |
  |---|---|---|---|
  | field | `card-partL` | the Continue preamble | -- |
  | sky | `card-partK` | the Continue preamble | -- |
  | battle | `card-saved` | the Continue preamble, then A every 150 frames | `cap-battle`'s pokes |
  | ship | `card-partL` | the Continue preamble, then A every 150 frames | `cap-ship`'s pokes |
  | cutscene | `build/cards/fresh.raw` | `opening.scn`'s | -- |

  The cutscene needs the fresh card because `card-saved` Continues into
  `a101b`. The whole recipe, pokes included, is `build/c5-capture.sh`, beside
  the original runs' `build/run_cap-*.log`, whose first lines hold the same
  environment. Every run loaded its scene's map and logged 0
  unknown bytes. By `fifopair`:

  | scene | draws matched, before | draws matched, after | 3D area matched | draws through a list now |
  |---|---|---|---|---|
  | field | 1144 / 1147 | 1144 / 1147 | 100.00% of 2.05 M px | 334 (0.42 M px) |
  | battle | 1390 / 1393 | 1795 / 1798 | 100.00% of 0.41 M px | 842 |
  | ship | 1514 / 1665 | 1514 / 1665 | 100.00% of 0.86 M px | 142 |
  | cutscene | 4146 / 4280 | 4146 / 4280 | 100.00% of 0.96 M px | 1238 |
  | sky | 765 / 765 | 765 / 765 | 100.00% of 0.59 M px | 26 |

  The 3D area is at or above the 99% limit everywhere, and matching without
  the list-address term gives the same pairs in every scene, so that term
  costs nothing and adds nothing. `midpoint`'s verdicts all hold over the
  new pairs, including "the pairs are fifopair's", which means C and Python
  agree on the `0x41` format. The one exception is battle's "as many as H4
  counted". Its frames were opened: they show the same battle (`a101b`, the
  Soldier, 2/8 on the gauge) at a later moment, with the camera turned to
  show the machinery on the left. The guest clock follows host time, so two
  runs of one script need not reach one moment.
- **What the pictures show.** The field and cutscene pairs show the same
  moments as H4's, so they compare directly:
  - the field's dark band across the cavern and over the ground on the left
    is gone, and so is the green-teal ellipse under Vyse's feet. No shadow
    is visible under him;
  - the cutscene's translucent teal band down the middle of the bridge,
    which hid Alfonso's legs, is gone, and his feet show.

  These are draws the game recorded and never showed. Whether the console
  draws a shadow under Vyse is for C5c, where the owner looks at every
  changed corpus frame, with D-29's Dolphin comparison if wanted.

  *Corrected 2026-10-01 (next entry): nothing was removed, and the shadow is
  drawn. The band and the ellipse were the characters' shadow volumes, run
  when they were recorded instead of at their call.*

**The shadows were drawn out of order, not drawn too often (C5c).**
2026-10-01. The entry above called the field's green-teal ellipse and the
cutscene's teal band draws "the game recorded and never showed", and found no
shadow under Vyse. Both were judged by eye; the captures say otherwise.

- **C5b removed no draw from any pair it can be compared on.** Walking each
  capture with `fifo.walk(..., follow_lists=True)`, the draws before C5b
  (`build/perfset/`) and after (`build/perfset-c5/`) are field 1147 and 1147,
  sky 765 and 765, ship 1665 and 1665, cutscene 4280 and 4280, behind the same
  list calls; after C5b 334, 26, 142 and 1238 of them come through a call.
  Battle (1393, 1798) is another moment of the fight, as above. C5b moved
  recorded draws from where they were recorded to where they are called.
- **The game's shadow pass, from the field capture after C5b** (draw numbers
  count list draws in stream order):
  1. a full-screen EFB copy in R8, no clear, saves the scene's red channel
     (destination `0x35D4E0`);
  2. a full-screen quad with logic OR (`PE_CMODE0 00713E`) sets red to 255
     (draw 805);
  3. list `805048A0` draws a shadow volume twice, depth LEQUAL without update
     (`PE_ZMODE 07`), material red 51: one face set subtracting
     (`PE_CMODE0 00093D`, `GEN_MODE 8010`, draw 806) and the other adding
     (`00013D`, `4010`, draw 807). Only ground inside the volume ends at 204;
  4. a second R8 copy takes red as the mask (`0x3A84E0`);
  5. a quad with logic AND (`00113E`, colour `00FFFF`) clears red (808), and
     the saved copy is ORed back (809);
  6. two draws (810, 811) sample the mask and blend
     `dst * (1 - src)` (`PE_CMODE0 00007D`) with src 51: 20% darker.

  The characters' own lists follow. The cutscene runs step 3 four times, one
  list per character (`80503EA0`, `8050DD20`, `80517BA0`, `8051FF60`). Before
  C5b, step 3 ran when the lists were recorded, earlier in the frame, against
  the visible scene's red channel and that moment's depth state, which is
  consistent with an ellipse short of red over Vyse's feet and a teal band
  over Alfonso's legs.
- **The shadow is drawn, and is faint on that ground.** The field frame
  rendered with `SOA_GXR_DRAWS=809` and `=811`: 5,493 pixels in x 283-397,
  y 346-426 change, to a median 0.80 of their value, and all 5,493 keep that
  value in the finished frame. Mean luminance 25.5 inside, 34.1 a dozen pixels
  outside. Vyse's lower boots, drawn before the pass and inside the volume,
  are darkened with the ground; that is the game's depth test, as before C5b,
  when his toe showed through the ellipse. `build/c5b-compare/
  field-shadow-where.png` shows the 5,493 in magenta.
- **The red channel's round trip is not lossless, and is not meant to be.**
  The frame after draw 809 differs from the one after 804 on 187,153 pixels,
  by up to 9 steps at edges. The copy filter at frame start is the
  deflicker's (8, 8, 10, 12, 10, 8, 8; BP `53` `30A208`, `54` `00820A`) and
  nothing in the frame changes it, so both texture copies are filtered
  vertically, as the registers ask. The TEV multiply in the restore is exact
  (`gxr_tev.c` `c + (c >> 7)`).
- **D-29 answered:** with the shadow found, the owner chose no Dolphin
  comparison before C5c's bless (2026-10-01).

**C5c: the corpus re-captured, matched to its old moments, and blessed.**
2026-10-01. The 23 captures in `build/fifo` are new, taken with C5b's
recording; the old ones are in `build/fifo-pre-c5/`, untouched. The owner
looked at every changed frame and found them all right before the bless.

- **The runs.** Four scenarios, each on a card path that did not exist (a
  new blank card, as every original log shows) and `SOA_FIFO_DIR` set to a
  scratch directory. Which original run each frame came from was read from
  the old logs' pad events: `boot_ship.log` has the opening's 19 events, so
  8000 comes from the opening run, and `boot_field.log` has hold's 21, so
  11900-12100 come from the hold run. The frames before 1600 come from the
  title run, which presses nothing before then.

  | run | scenario | frames | `--frames` |
  |---|---|---|---|
  | title | `title.scn` | 0100-0700, 1500, 1550, 2000-2100 | 2150 |
  | capture | `capture.scn` | 3600, 3900, 4200 | 4250 |
  | opening | `opening.scn` | 4500, 4800, 6000, 6300, 8000 | 8050 |
  | hold | `hold.scn` | 11900-12100, 15200, 15800, 16300 | 16350 |

  Every run reported 0 unknown bytes.
- **Most frame numbers no longer reach the same moment.** The guest clock
  follows host time, and today's renderer is faster: by frame 12000 the
  September hold run had counted 32,327 VI retraces and today's 28,161, 69
  s less guest time. Loads end at other frame numbers, and the text fade at
  0500, the opening flight at 1500 and the battle all landed elsewhere. So
  every drifted frame was captured again in a window of consecutive frames
  (2,325 captures in four more runs, into scratch directories), each was
  replayed, and the one whose render is closest to the old capture's (mean
  absolute RGB difference over every 7th pixel) was kept under the old
  name. `build/fifo/PROVENANCE.tsv` records the run and frame of each:

  | name | frame kept | distance | name | frame kept | distance |
  |---|---|---|---|---|---|
  | 0500 | 521 | 0.00 | 4800 | 4796 | 0.80 |
  | 0700 | 721 | 0.00 | 6000 | 6000 | 0.19 |
  | 1500 | 1488 | 1.97 | 6300 | 6300 | 0.90 |
  | 1550 | 1538 | 1.40 | 8000 | 7991 | 8.19 |
  | 3600 | 3600 | 0.02 | 15200 | 15200 | 0.59 |
  | 3900 | 3900 | 1.30 | 15800 | 15800 | 0.55 |
  | 4200 | 4200 | 2.71 | 16300 | 16300 | 0.37 |
  | 4500 | 4496 | 0.83 | | | |

  8000's 8.19 is clouds and ships drifting; 15200 and 15800 tie with frames 41 apart, Vyse's run
  cycle against a wall, and keep their own numbers. **The battle has no
  match:** the best of 451 candidates was 16 to 26 away, the fight having
  taken a different course in each of three runs (one had reached the
  results screen by 12100). 11900-12100 keep the first hold run's own frames, a fight in
  progress, and were judged as new scenes.
- **Before any change, the old captures replayed to their 23 manifest
  hashes**, so the comparison ran on the renderer that had pinned them.
- **Each frame, against the old one** (`build/c5c-compare/`: old | new | the
  changed pixels; the draws compared as a multiset of primitive, count and
  vertex bytes):

  | frames | result | what changed, and why |
  |---|---|---|
  | 0100, 0300, 0500, 0700, 2000, 2050, 2100 | unchanged | pixel for pixel |
  | 3600, 6300, 1500, 1550, 15200, 15800, 16300 | the same draws, reordered | recorded lists now draw at their call |
  | 15200, 15800, 16300 | shadows | the teal blob under Vyse is a faint shadow, as in the field (entry above) |
  | 4500, 4800, 6300 | shadows | the teal bands over Alfonso and the Vice Captain are gone and their feet show; 4500 and 4800 also differ by idle animation |
  | 1500, 1550, 3900 | layer order | 404 draws in seven lists (1500) and 474 in nine (1550) now draw at the end of the frame instead of mid-frame, where they were recorded; the sky is lighter and hazier; 1550 also re-layers rigging behind the sails; 3900's cloud patches likewise |
  | 4200, 3600 | layer order | the dark blotches inside the searchlight beams are gone, the bridge windows are lit warm yellow instead of white, and the mast shows through the central beam (not traced); 3600, 203 pixels at the beams' edge |
  | 8000 | searchlights | the warship's searchlights were three opaque black fans and are translucent beams |
  | 6000 | timing only | a hair ribbon moved, and a flickering sprite drawn outside any list (texture `041302`, present at frames 5998, 5999, 6000 and 6002 of today's run, not 6001) is drawn once instead of twice |
  | 11900, 12000, 12100 | new moments | no old frame to compare |
- **C5b removed no draw from any frame that could be compared**, so the
  Done's removal tracing has nothing to trace. Where a frame differs by a
  few draws (3900, 4200, 6000), every draw only the new frame has is drawn
  outside any list, small 4-vertex strips with as many on the old side
  give or take one. 4500, 4800 and 8000 have more draws now, not fewer.
  `SOA_GX_DLLOG` could not have shown it for most frames anyway: it prints
  its first 400 lines and stops (`DLLOG_LINES`, `gx.c`), and the opening
  makes 2,746 list calls by frame 1000 (entry C5b), a line each.
- **The look and the bless.** The owner opened `build/c5c-compare/
  index.html`, the 16 changed frames with a note each, and answered that
  all look right. `python tools/scenario.py replay --bless` then pinned the
  23, `replay --threads 1,2,3,8` is 23/23, and the pinned frame hashes are
  the ones the owner looked at, all 23.

**L2, step 1: the queue's ordering completed.** 2026-10-02. Every
cross-thread access to the render queue's counters in `gxr.c` now goes
through `plat.h`: `plat_load64/32`, `plat_inc64/32`, `plat_dec32`,
`plat_xchg64` and `plat_compiler_barrier`, all seq_cst, and on Windows
`plat_wait64` and `plat_wake_all64`. The `LOAD_ACQUIRE` macros, the
Interlocked calls, `WaitOnAddress`, `WakeByAddressAll` and `_ReadWriteBarrier`
are gone from `gxr.c`, and the `Synchronization.lib` pragma moved to
`plat.h`. Base: 9ccef87.

- **What it fixes.** The four Dekker re-checks of portability.md 3.4 rule 3
  (`publish` and a finishing worker reading the sleeper counts, the idle
  worker and the fence waiter reading the count again), and the fence
  waiter's first read of `seen`, were plain volatile reads, correct only
  because an MSVC Interlocked call is a full barrier. They are `plat_load*`
  now, in the same change that makes the RMWs `__atomic` seq_cst under
  PLAT_GNU (clang-cl and the NDK), so on ARM64 neither side can miss the
  other's write.
- **No `<windows.h>` in `plat.h`.** The MSVC helpers are `<intrin.h>`'s
  `_Interlocked*` intrinsics, which are what `<windows.h>`'s Interlocked names
  expand to on x64, and the x64 load is a plain volatile read, which is what
  the SDK's `ReadAcquire64` is there (10.0.26100's AMD64 section: `Value =
  *Source;`). The two waits are declared as `synchapi.h` declares them, so
  `gxr.c`, which includes both, compiles and links. *Corrected in step 2:
  not with no warning. `synchapi.h` does not declare these two dllimport
  (they come from the `Synchronization.lib` API set), so this commit's
  `__declspec(dllimport)` drew MSVC's C4273, "inconsistent dll linkage",
  twice in every file that also includes `<windows.h>`; only the tail of
  that compile was read. Step 2 matches the SDK.* The
  reason is `hle.c`: it includes a lean `<windows.h>` because `mmsystem.h`'s
  `MMIO_READ` collides with its own names, and a `plat.h` that pulled in the
  full header would break it once step 2 has `gxr.h` include `plat.h`.
  `plat_cas32` (3.2) is not added: nothing calls it.
- **The x64 code** (the Done's comparison). Compiled with `toolchain.CFLAGS`
  and `/FA`, against 9ccef87's `gxr.c`, labels normalised:

  | function | against the base |
  |---|---|
  | `wait_ran`, `drain`, `publish`, `ran_min`, `gxr_presented` | identical, line for line |
  | `worker` | the same multiset of instructions, blocks and registers placed differently |
  | `fence_wait` | one push/pop pair fewer (one fewer saved register), one `mov` traded for a `movsxd` |

  In all seven the `lock`, `xchg` and fence lines are the same set, and
  every shared-counter load is a plain `mov`. The comparison can fail:
  with `plat_load64` made a locked compare-exchange, `worker`, `wait_ran`
  and `ran_min` turned red and `publish`, which loads only the 32-bit
  count, stayed identical. Nothing moved, so the Done's timing run was not
  needed.
- **`test_gxr_atomics.py` (5 tests)** enforces rule 4 by reading `gxr.c`:
  comments and strings blanked, each use of a shared counter must sit
  directly inside a `plat_*` call, be its declaration, or be the producer's
  plain read of its own `g_published` on a line marked `own count`. 9ccef87's
  `gxr.c` fails it 38 times, all five re-checks among them. Its cases hold the
  spec's mutation (a bare `g_ran[1]` read added to `worker()`), a worker's
  count wrongly marked `own count`, and a read inside a cast or an `if`.
- **`test_gxr_queue.py`'s rewind test** named `InterlockedIncrement64` and
  `InterlockedExchange64` and failed on the rename. It names `plat_inc64` and
  `plat_xchg64` now, and also refuses an exchange or a decrement on
  `g_published`, or a decrement on `g_ran`: through a helper, those rewind
  the numbering as surely as the assignment it already refused.
- **Checks:** `compile_runtime.py` 28/28 under MSVC and under the NDK's
  clang-cl; `render_check.py` under clang-cl, the first time the `__atomic`
  helpers ran the worker pool; `dc_check.py`; the no-skip clang modules;
  `test_gxr_overlap`, `_queue`, `_fastpath` and `test_citest`; `replay
  --threads 1,2,3,8` 23/23; the self test 0 failures; `title --check` 4 of 4.

**L2, step 2: the renderer builds off Windows.** 2026-10-02. The worker
pool, its waits, its clocks and the files the self test and the disc reader
use now go through `plat.h`, and `runtime/*.c` compiles for Android. Base:
dd87a59.

- **`plat.h` gains** the storage classes (`PLAT_THREAD_LOCAL`,
  `PLAT_ALIGN`); `plat_relax`, `plat_yield` and `plat_sleep_ms`; the waits
  on Linux and Android (a private futex on the counter's low 32 bits) and a
  1 ms poll anywhere else, said once; clocks (`plat_mono_raw` and
  `plat_mono_hz`, which are QueryPerformanceCounter or `CLOCK_MONOTONIC`;
  `plat_cycles`, the TSC or `CNTVCT_EL0`; `plat_cycles_invariant`); threads
  (`plat_thread_start` through `_beginthreadex` or `pthread_create`, a heap
  block carrying the function and its argument; `plat_cpu_count`); and
  `plat_fseek64` and `plat_setenv`.
- **Six Win32 calls are declared, not included,** each exactly as the SDK
  declares it: `WaitOnAddress` and `WakeByAddressAll` without dllimport,
  `Sleep`, the two performance-counter calls and `GetActiveProcessorCount`
  with it. `union _LARGE_INTEGER` is declared at file scope first, so it is
  the SDK's tag whichever header comes first. `gxr.h` now includes `plat.h`,
  which reaches `main.c`, `window.c` and `selftest.c`, and none of them gains
  `<windows.h>`'s macros by it.
- **`gxr.c`:** `fence_wait`, `worker` and `publish`'s wake leave `#ifdef
  _WIN32`; `workers_start` starts the pool with `plat_thread_start` and keeps
  each HANDLE for `SOA_HOSTPROF`, which stays Windows-only and says so when
  set elsewhere. `gxr.h`'s `gxr_ticks` reads `plat_cycles` or `gxr_qpc`
  everywhere; off Windows it used to return 0, so a run there had no
  timings at all.
- **The CPU count:** `GetSystemInfo`'s `dwNumberOfProcessors` counted the
  current processor group, and `GetActiveProcessorCount(ALL_PROCESSOR_GROUPS)`
  counts all of them. The two differ only past 64 logical processors, where
  Windows 11 spreads a process's threads over every group anyway. This
  machine still gets 12 workers by default, and `SOA_HOSTPROF=1` still
  samples all 12 and the guest thread.
- **`gx.c`** leaves with `_Exit`, **`dvd.c`** seeks with `plat_fseek64`, and
  the self test's three render settings move into a `render_env()` outside
  the block `tools/citest/render_driver.c` copies, each file with its own.
  `test_gxr_queue.py` found the worker by its Windows signature; it finds
  `static void worker(void* arg)` now.
- **The x64 code** against dd87a59, compiled with `toolchain.CFLAGS` and
  `/FA`: `worker`, `wait_ran`, `fence_wait`, `drain`, `publish`, `ran_min`
  and `gxr_presented` are identical once the listing's names for stack slots
  and compiler temporaries are set aside (`c$1` is `v$1`, `tv366` is
  `tv398`). Every `rdtsc` is still inline; the listing gains one more, in an
  out-of-line copy of `plat_cycles` that nothing calls. `stall`,
  `gxr_timing_init` and `workers_start` changed, all cold. Nothing moved, so
  no timing run.
- **The NDK check:** the NDK's clang 19.0.1, `-fsyntax-only` over
  `runtime/*.c` with `--target=aarch64-linux-android29` and with
  `x86_64-linux-android29`, reports 0 errors (11 at dd87a59, 21 at b071949).
  Over all 19 `gen/*.c`, at idle priority: 0 errors; 19 `-Wcomment`
  warnings, one per file from `cpu.h`, and 3 `-Wparentheses-equality`.
- **What it does not show:** nothing links or runs off Windows yet. The
  futex wait, the POSIX thread start and `CLOCK_MONOTONIC` have compiled for
  Android and never run; L4b's Linux leg is the first thing that will run
  them.
- **Checks:** `compile_runtime.py` 28/28 under MSVC (no C4273 now) and
  clang-cl, whose one warning, an unused `x0` in `gxr.c`'s copy code, is
  older; `render_check.py` under both, the same hash, `63a57c77609efd77`;
  `dc_check.py`; the no-skip clang modules; `test_gxr_overlap`, `_queue`,
  `_fastpath`, `_atomics`, `test_citest`, `test_memguard` and
  `test_profiler`; `replay --threads 1,2,3,8` 23/23; the self test 0
  failures; `title --check` 4 of 4.

**L4b: CI's Linux leg, and the 32-bit words it found.** 2026-10-02. A
`linux` job runs the citest checks under gcc and clang on ubuntu-latest, and
the six native MSL units no longer assume `long` is 32 bits.

- **The words.** `include/types.h` gave `s32` and `u32` as `long`, and
  `fillmem.c`, `strcpy.c`, `strcmp.c`, `strstr.c` and `string.c` spelled
  their words `unsigned long`: 32 bits under mwcc and MSVC, 64 on Linux and
  Android. `types.h` now has two branches. Under `__MWERKS__` it keeps the
  exact typedefs the units were matched with. Every host gets `int32_t`
  and `uint32_t` and `<stddef.h>`'s `size_t`. The units say `u32`, and cast
  pointers through `size_t` as `strcmp.c` already did; that also silences
  MSVC's C4311 (pointer truncation) on `strcpy.c:14`. `tools/decomp.py`'s
  whole report is byte-identical before and after each step, so nothing the
  game's build compiles moved.
- **Twelve routines.** `dc_driver.c` adds `strcpy`, `strcmp` (as
  `fn_8025EF88`, the name its unit defines and the rename keeps:
  `test_citest.py` requires the table and the declarations to agree) and
  `strstr`. `strcpy` and `strcmp` take their word loops only when both
  pointers share an alignment, so half the cases are forced to.
  `strcmp`'s cases mostly share a long prefix, where the word compare
  answers, and `strstr`'s run over a three-letter alphabet, where partial
  matches are common. The `memset` note was stale: `fillmem.c` landed, so
  the fill itself has been checked since, not the host's.
- **The toolchain.** cl's `/Fo<dir>/` over several sources has no gcc
  spelling, so `toolchain.gnu_commands` makes it one command per source,
  each object named for its source (a test in `test_toolchain_profiles.py`).
  The three citest scripts take every profile in `--cc` and name objects and
  executables from it. `render_check.py --threads N` runs the driver with
  `N` workers through its own `render_env()`, and fails unless the renderer
  printed `[gxr] rasterizing on N worker thread`.
- **Green on a branch before the merge**
  ([run 37036199554](https://github.com/bmfrench89/skiesofarcadiadecomp/actions/runs/37036199554),
  branch `l4b-linux`, all seven jobs). Under gcc 13.3.0 and Ubuntu clang
  18.1.3: `compile_runtime.py` 28/28, `dc_check.py` 12/12, and
  `render_check.py` at one worker and at four. The four-worker run is the
  first run anywhere of `plat.h`'s POSIX half: `pthread_create`, the futex
  wait and `CLOCK_MONOTONIC`. Its frame hash is `63a57c77609efd77` under
  both compilers, the hash MSVC and clang-cl give on Windows, so the
  renderer draws this frame bit for bit alike on two operating systems and
  four compilers.
- **Red on a branch, as the Done asks**
  ([run 37036562506](https://github.com/bmfrench89/skiesofarcadiadecomp/actions/runs/37036562506),
  branch `l4b-mutation`, never merged), under both Linux compilers. With
  `types.h`'s host branch reverted to `long`, `dc_check` fails on exactly
  `memset` (2,503 of 3,000 cases, its word loop writing eight bytes a word
  through `fillmem.c`) and `strcpy` (3 cases, a word written past the
  terminator); `strcmp` stays right, since its word loop never reads past a
  zero. With the driver's `render_env()` forcing one thread, the four-worker
  step fails with `asked for 4 worker thread(s), and the renderer never said
  ...`. The Windows jobs stay green there, as they should: `long` is 32 bits
  on Windows. The same `types.h` mutation, simulated here with `u32` as
  `uint64_t`, gives the same 2,503 and 3: the driver's inputs are a fixed
  xorshift sequence.
- **Warnings the Linux leg shows, none promoted:** `cpu.h`'s `/*` inside a
  comment (every file), the unused `x0` in `gxr.c`'s copy code, `hle.c`'s
  `done`, `mod.c`'s `g_api`, `threads.c`'s fiber helpers that only Windows
  calls, and gcc's truncation warnings in `aram.c` and `si.c`. All older
  than this slice.
- **Checks:** `decomp.py` unchanged; `dc_check.py` 12/12 under MSVC;
  `render_check.py --threads 1` and `4` under MSVC; `--link`; the self test 0
  failures, its twin cases (`strcpy`, `strcmp`, `memset`) among them; `replay
  --threads 1,2,3,8` 23/23; `title --check` 4 of 4.

**L8: the queue on ARM64 and under ThreadSanitizer.** 2026-10-02. Two CI
jobs, `tsan` and `arm64-linux`, and a third race fixed because TSAN found
it. Base: a2c7c21.

- **The two known races.** `g_notex` (`SOA_GXR_NOTEX`) was decided inside
  `sample()` on the workers, so several could race to write it; it is
  decided on the producer in `tev_prepare` now, beside `simd_decide`, before
  any sampling draw is published, and `sample()` only reads it.
  `WARN_ONCE`'s flag was a plain `int`, which two workers at one tripwire
  could both see unset; it is taken with `plat_cas32`, its first caller, so
  exactly one prints. `SOA_GXR_NOTEX=1` still greys every texel: a replay of
  4500 hashes `02be8f2d42c8cefa` with it and its manifest hash without.
- **`tools/citest/queue_check.py`** holds the two queue drivers and their
  run table, moved verbatim from `test_gxr_overlap.py` and
  `test_gxr_queue.py` (one copy; the tests import them, and their drivers'
  `_putenv` is `plat_setenv` now). It builds them under any profile, with
  `--cflag` for a sanitizer, and holds every thread count, unstalled and
  with each stall kind, to the one-worker run. Under MSVC here: 18 runs, all
  matching, in 16 s. With the worker's fence wait disabled, every
  multi-worker overlap run fails and the one-worker runs pass, so the check
  can see the bug it is for. `render_check.py` takes `--cflag` too.
- **TSAN found a third race,** on its first run: `gxr_report` reads each
  worker's idle timer while a parked worker is still charging it, in
  `charge()` on every wake of its wait loop, with nothing to order the two.
  A statistic, not a pixel, but a race, and rule 4's territory. The owner's
  write is now `plat_store64_relaxed`, a helper 3.2 did not list (a plain
  `mov` on x64 and ARM64), and the report reads both timers with
  `plat_load64`. The workers line still adds up: `title --check`'s run reads
  busy 15.38 s + idle 827.09 s = 842.47 s, 0.0% unaccounted. The same first
  run also showed `queue_check` printing `ok` for a thread count whose run
  had failed, judging by the frame hashes alone; it now prints `FAIL` for
  any failed run. And `halt_on_error=1` had hidden any race after the first
  in each run; the job reports every race now and fails at the end.
- **Clean:** ([run 37040632648](https://github.com/bmfrench89/skiesofarcadiadecomp/actions/runs/37040632648),
  branch `l8-tsan-arm`, all nine jobs). TSAN under Ubuntu clang 18.1.3:
  `render_check --threads 4` and `queue_check --threads 1,2,3,4` (18 runs)
  with no race reported and `tsan.supp` empty of entries, the spec's target.
  ARM64 (`ubuntu-24.04-arm`, `aarch64`, gcc 13.3.0): `compile_runtime`
  28/28, `dc_check` 12/12, `render_check --threads 4`, and `queue_check`
  with every run matching the one-worker run. The four-worker frame hash on
  ARM64 is `63a57c77609efd77`, the same as on x86-64 Linux and Windows.
- **Red, as the Done asks** ([run 37041203392](https://github.com/bmfrench89/skiesofarcadiadecomp/actions/runs/37041203392),
  branch `l8-mutation`, never merged): with `-DPLAT_TEST_RELAXED_LOADS=1`
  TSAN reported 64 races, on the worker's reads of the command's `seq`,
  `fence` and `fence_near` (`gxr.c:1800`, :1804), in `draw_command`,
  `emit_triangle`, `clip_dist` and `raster_triangle` reading the command's
  vertices, and in `run_copy` and `copy_to_screen` reading a copy's fields
  and the rows. The render step failed; the queue step was still reporting
  races 40 minutes in, and the run was cancelled to read the log.
- **Dropped from the spec:** the `arm64-windows` leg, `msvc-arm64` and B4.
  Windows on ARM is outside the owner's targets (PLAN-NEXT section 0), and
  no target runs MSVC's ARM64 code. `libm_check` on the ARM leg waits for
  L6.
- **Checks:** `compile_runtime.py` 28/28 under MSVC and clang-cl; `--link`;
  `replay --threads 1,2,3,8` 23/23; the self test 0 failures; `title
  --check` 4 of 4; `test_gxr_overlap`, `_queue` and `_atomics` with the
  drivers imported from `queue_check.py`; pytest 1128 passed, 2 skipped.

**clang-cl: the whole game under a second compiler (L3b).** 2026-10-02. The
Android NDK's clang-cl 19.0.1 (the owner's answer to Q2: no LLVM install)
builds the game, and it draws the 23 reference frames exactly as MSVC does.

- **The build.** `python tools/recompile.py --cc clang-cl --compile
  --optimize --link`: the translation into `gen/clang`, 19 units compiled
  in 57.7 s and linked in 10.2 s, about 90 s in all, with no warning in the
  log. Before and after, the SHA-256 of `gen/soa.exe` and of all 47
  `gen/*.obj` are identical: the MSVC build was not touched. `dumpbin
  /dependents` lists the same nine DLLs for both exes, no ucrtbase,
  api-ms-win-crt or VCRUNTIME among them: the same static CRT.
- **Every check, the first time.** `gen/clang/soa.exe`'s self test: 0
  failures. `replay --exe gen/clang/soa.exe --threads 1,2,3,8`: 23/23
  against the MSVC manifest, so 3.11's procedure for a difference never
  ran. `title --check --exe gen/clang/soa.exe`: 4 of 4. The MSVC build,
  relinked for the line below, keeps the contract (23/23, the self test,
  `title --check`) and `decomp.py`'s report is byte-identical.
- **`[boot] built with ...`** after the DOL line names the compiler, so a
  log says which build made it: `clang 19.0.1 (https://android.googlesource
  .com/toolchain/llvm-project 97a699bf...)`, or `MSVC 194435221`.
- **Measured, not a gate,** interleaved, on AC power in the Turbo scheme,
  with 13-16% background load from other sessions. MSVC's translated code
  was confirmed `/O2`: compiling its smallest chunk again gives 943,526
  bytes at `/O2` against the existing object's 943,430, and 1,095,716 at
  `/Od`, so both builds were optimised.

  | | MSVC | clang-cl | |
  |---|---|---|---|
  | `perfbench`, ns a fragment, 1 thread (A B B A) | 42.2, 44.2 | 39.2, 38.6 | clang-cl 10% less |
  | `perfbench`, ns a fragment, 8 threads (A B B A) | 68.6, 62.1 | 59.2, 54.9 | clang-cl 13% less |
  | guest ceiling, images a second (A B B A, then B A A B) | 135.5, 158.6, 140.2, 148.2 | 172.0, 176.7, 139.6, 176.3 | pooled 145.6 against 166.2, +14% |

  The ceiling is H1's Part L uncapped from frame 3000 at `SOA_SPEED=4`, in
  snapshot mode, 9,000 frames, every run checked to have reached `126a`.
  It is bimodal: three clang-cl runs sit at 172-177 with a 4.7-4.8 ms
  median frame, and the fourth at 139.6 with 7.7 ms, MSVC's level; MSVC's
  medians run 6.0-7.8 ms. Why one run fell is not known, and nothing here
  tests it. Each figure is one invocation (perfbench's with `--runs 5`), so a
  drift of this machine's size could move any single one.
- **Q3 is the owner's:** whether clang-cl becomes the default build. MSVC
  stays the reference for the pinned hashes, and `replay --bless` still
  refuses any exe but `gen/soa.exe`.

**Wine: the port under Wine 10.0, headless (L1).** 2026-10-02. What the
Steam Deck's Proton runs, smoke-tested in a Linux container through Docker
Desktop (D-13, the owner's answer), and it passes all three checks.

- **Setup.** The image is `python:3.14-slim` and Debian's `wine` and
  `wine64`: Wine 10.0 (Debian 10.0~repack-6), Python 3.14.7, 16 CPUs
  visible. The checkout, `extracted/` with it, mounted read-only; a fresh
  named volume over `build/`; the captures and `build/cards/slotA.raw`
  mounted read-only elsewhere and copied onto the volume. The commands are
  in TESTING.md. The volume was deleted afterwards and Docker Desktop
  stopped; the image, with no game data in it, is kept.
- **The first run crashed at the entry point:** a write to address 0 at
  `mainCRTStartup`, whose instruction disassembled as `addb %al, (%rax)`,
  two zero bytes. Started from the Docker Desktop share from Windows, the
  exe's code page reads as zeros to Wine's image mapping, though Python's
  `mmap` of the same file reads it correctly and `cmp` finds a copy
  identical. Run from a copy in the container's `/tmp`, everything below
  passes. A property of the mount, not of the port, and the reason the
  TESTING.md recipe copies the exe.
- **All three checks, on `gen/soa.exe` (MSVC, SHA-256 `d71af51e...`):**
  - `SOA_SELFTEST=1 wine soa.exe extracted`: exit 0, 0 failures, `[boot]
    built with MSVC 194435221`.
  - `scenario.py replay --wrap wine --fifo build/fifo-copy --threads
    1,2,3,8`: 23/23 against the manifest. Wine draws every reference frame
    bit for bit, at every thread count, so the pool's `WaitOnAddress`
    under Wine's futex-based one orders the queue as Windows does.
  - `scenario.py run title --check --wrap wine` on the copied card: 4 of 4;
    2,000 frames, `[gxr] rasterizing on 12 worker threads`, 72.0 guest
    seconds in 72.9 wall, so real time.
- **Nothing outside `build/` was written:** the checkout was read-only, and
  every run passed. Two `.git` entries newer than the run were the host's
  own fetch at 14:52:32, during it.
- **`scenario.py --wrap "<prefix>"`** on `run` and `replay`, split into
  words; a wrapped replay may not `--bless`. Three tests in
  `test_scenario.py`; dropping the prefix in `wrap_prefix` fails the run
  test and the bless test, and the replay test checks `replay_once`'s
  command itself.
- **What it does not show:** DXVK presentation, a window, sound, Steam Input,
  the Deck's refresh rate or its speed. That is the owner's optional Proton
  session, which needs a Deck or a Linux PC (portability Q1's second half,
  still open).

**L7: the POSIX layer's first part: the guard, the guest's stack, a thread's
resume.** 2026-10-02. Off Windows the MEM1 tripwire now reports and survives
a store past the RAM, the guest runs on a 32 MB stack, and a guest thread that
loads its own context resumes rather than ending the run. CI's three Linux
legs run all three on every push.

- **What moved.** `runtime/plat.c` is new: the cold half of 3.3.
  - `plat_reserve`, `plat_commit`, `plat_release` and `plat_last_error` wrap
    VirtualAlloc, or `mmap(PROT_NONE)` and `mprotect`.
  - `plat_guard_install` is a vectored handler on Windows. Elsewhere it is
    `sigaction(SIGSEGV, SA_SIGINFO | SA_ONSTACK)` on a `sigaltstack`, chaining
    to the previous handler for any fault outside the range.
  - `plat_run_on_big_stack` calls `fn` on Windows. Elsewhere it runs `fn` on a
    pthread with that stack and joins it.
- **`main.c`.**
  - The guard's report is a callback, `mem_fault`, with the same text.
  - The watchdog runs on `plat_thread_start` and `plat_mono_ns` on every
    platform and ends with `_Exit(5)`.
  - Block naming leaves the Windows block, because both reports use it. The
    sampler stays Windows-only, with its stubs.
  - The guest starts through `plat_run_on_big_stack(32 MB)`. Off Windows that
    makes it a new thread, which then claims the guard (`plat_guard_owner`,
    added to 3.3's list for this).
- **Elsewhere.** `threads.c`'s same-fiber resume moved above its `#ifdef`, and
  a second guest thread off Windows still exits 6, now saying "a second guest
  thread is Windows-only". `irq.c` yields through `plat_yield` and no longer
  includes `<windows.h>`. By the orient skill's measure, the runtime files
  outside the platform layer that touch Win32 go from 16 to 15.
- **On Linux** (branch `l7-posix`, run 37056700247, every job green):
  - The gcc, clang and ARM64 legs each pass `test_memguard.py` (4 passed,
    with `noskip`) and `threads_check.py`.
  - `threads_check.py` reads the guest's stack back as 33554432 bytes on each
    leg.
  - On ARM64, "a store" can come only from the ESR record in the signal
    frame: without the record the report says "an access" and the test
    fails. This was that path's first run.
- **The mutations, seen red.** On `l7-mutation` (run 37056702939), threads.c's
  move was reverted. `threads_check` failed on all three Linux legs with
  "[threads] OSLoadContext(80300000): a second guest thread is Windows-only"
  and exit 6; every other step was green. Locally, under gcc 14.2 in a
  throwaway container, each of these failed its check, and the unmutated tree
  passed both:
  - a guard that never calls back failed `test_memguard`;
  - `fault_storing` returning -1 failed it, because the report says "an
    access";
  - the default stack failed `threads_check` (8388608 bytes).
- **Checks on Windows, both builds** (`gen/soa.exe` and `gen/clang/soa.exe`):
  - `compile_runtime.py`: 29/29 under MSVC and the NDK's clang-cl, with no new
    diagnostic.
  - `--link` without a warning; the self test, 0 failures; `replay --threads
    1,2,3,8`, 23/23; `title --check`, 4 of 4.
  - The watchdog, fired by `SOA_STALL=60:5` with `SOA_WATCHDOG=2`, exits 5 at
    6-7 s.
  - `SOA_MEMPOKE=0x81800000 gen\soa.exe nodisc` prints TESTING.md's text
    unchanged.
  - pytest: 246 passed over `test_memguard` and the nine modules that import
    it, and 1131 passed, 2 skipped over everything.
- **Fixed before the commit:** `plat_mono_ns` cached its tick ratio in a
  static set on first use. That is a race the day a second thread calls it,
  so it now divides every call; the watchdog check and the self test were run
  again on both builds.
- **What it does not show:**
  - the port itself running off Windows, which needs L9, L10 and a window;
  - a second guest thread off Windows: every log so far has one (risk 18,
    Q9).

**L6: the renderer's arithmetic, the same on every platform.** 2026-10-02.
Every leg CI runs now draws the same pixels from out-of-range conversions and
gets the same bits from `exp2f` and `log2f`. Those legs are MSVC, clang-cl,
gcc, clang, gcc on ARM64, and clang under ThreadSanitizer. One defect turned
up that the spec had not foreseen.

- **`plat_f2i`** (`plat.h`) is x86's `cvttss2si` everywhere: the intrinsic on
  x86-64, a range test elsewhere.
  - **The sites:** ten in `gxr.c` and `gxr_tev.c`. Fog's weight, the
    triangle's vertex colour, the line's step count, position and colour, the
    point's position and colour, `fast_floor`, the bilinear weights and the
    mip level.
  - **How they were found:** by the compiler, not by reading. They are every
    `cvtt*` instruction in MSVC's `/FAs` listings, by source line. That gave
    §2.6's sites, moved 4-9 lines, and none in `gx.c`.
  - **The bounded casts,** each now commented:
    - the triangle's bounding box (`fminf` and `fmaxf` drop a NaN);
    - the span limits (a NaN fails the compare);
    - YUV (at most 235.7);
    - the mip count (a byte over 16);
    - the two unsigned depth casts. A NaN gives 0 on every target; the driver
      checks it.
  - **Checked in `render_check`'s driver:** a 14-case table on every leg, and
    the range test against the instruction over all 4,294,967,296 floats on
    x86. Both pass on every leg. `PLAT_F2I_SATURATE` fails 5 cases and
    830,472,191 floats.
- **The bilinear weights: the defect.** Past int range, `fast_floor` and the
  weight are both INT32_MIN.
  - **How the paths disagreed:** the SSE4.1 path (16-bit lanes, a logical
    shift, saturating packs) and the scalar path (int products) wrap that
    differently. Where an odd weight in one direction met INT32_MIN in the
    other, over texels whose 2x2 sum is odd, the SIMD path gave 0 and the
    scalar path the texel.
  - **Why it mattered:** ARM64 has only the scalar path, so `plat_f2i` alone
    would not have made it draw as x86 does.
  - **The fix:** such a weight is now 0. Along s that is what the SIMD path
    already computed; along t it replaces a value that depended on parity.
  - **The proof:** with the clamp removed, the synthetic frame's block B
    comes out 0 under SIMD and 85 under scalar. Replay stays 23/23.
- **The synthetic frame** (`render_driver.c`) is six blocks of constant
  texture coordinates over an 8x4 I8 texture from an LCG, bilinear and
  repeating. Each block is one value worked out by hand, in the driver's
  comment, and the driver checks every pixel.
  - **On x86:** A 60, B 85, C 218, D 220, E 108, F 220. The MSVC SIMD path,
    the scalar path, and the range test with the scalar path (ARM's
    arithmetic) all draw it with hash aa535458106bed0e.
  - **Pinned** after the owner looked at the frame.
  - **The saturating mutation** gives B 19, C 108 and D 70, as worked out.
  - **One worked value was wrong the first time:** F, whose s is NaN, was
    worked as 218 and draws 220. The identity texture matrix makes t
    0 x NaN + t, so t is NaN too and the block samples texel (0, 0). The
    renderer was right.
  - **No vertex colour of 1e10,** as the spec asked: none can reach the
    conversions through GX, because `read_color` decodes bytes and
    `light_channel` clamps.
  - **Two earlier designs could not fail.** The first, interpolated
    coordinates, could not be modelled exactly. The second, texels whose 2x2
    parities always cancelled, drew the same under SIMD and scalar even
    without the fix.
- **`exp2f` and `log2f`** are CORE-MATH's (commit 8ea8ea35, MIT, in
  NOTICE), as `soa_exp2f` and `soa_log2f`.
  - **Where:** `runtime/crmath.h`, not the spec's `crmath.c`, so the renderer
    still links alone (3.1).
  - **How:** generated from upstream by exact, asserted substitutions, listed
    in the header. MSVC and clang-cl compile it with no diagnostic.
  - **The check:** `libm_check.py` runs every input. 1,090,519,041 for
    `exp2f` and 2,139,095,039 for `log2f` are all correctly rounded. Of
    those, 6,996 and 49,987 lie within 2^-40 of a rounding boundary, and
    decimal at 50 digits agrees with every one.
  - **Pinned** in `config/libm.tsv` (d26a9f42e670180c, 68eb594274ef7407) by
    the owner's answer. The pin was inspected by that comparison: every
    output agreed with the double reference, and every arbitrated one with
    decimal.
- **The C libraries' own functions,** the mutation.
  - **The counts:** 74,153 `exp2f` and 313,550 `log2f` outputs are not
    correctly rounded.
  - **Not 74,154:** §2.5's probe said 74,154 for `exp2f`. At
    x = -0.029743773862719536 (BCF3A937) the double-precision reference
    rounds the wrong way and UCRT is right; CORE-MATH handles that input by
    name. `test_libm_check.py` pins it.
  - **The same bits everywhere:** UCRT, glibc on x86-64 and glibc on ARM64
    give the same outputs (hashes 3a3a2f6c6fd6caab and 946e2e76f2851206 on
    all five legs). So §2.5's "a glibc build would differ" does not hold.
    Android's bionic is not measured. The renderer's answer is now its own
    either way.
- **Codegen and speed.**
  - **`/FA`:** fog lost a register swap. `fast_floor` converts once instead
    of twice, and one `cmov` became a branch. `soa_exp2f` stays a call, as
    `exp2f` was.
  - **perfbench,** at one thread, three interleaved rounds against
    `build\soa-L6base.exe`, in ns a fragment, new against base:
    - after `plat_f2i`: 35.6 against 36.9;
    - with the weight fix: 34.6 against 35.75;
    - final: 35.25 against 35.5.

    Not slower.
- **Checks:**
  - `compile_runtime` 29/29 under MSVC and clang-cl;
  - both builds relinked, with the self test, `replay --threads 1,2,3,8`
    23/23 (unchanged at every step, as §2.5's probe predicted) and `title
    --check` 4 of 4;
  - `render_check` under MSVC (1 and 4 workers) and clang-cl;
  - `libm_check` under MSVC and clang-cl;
  - pytest 1138 passed, 2 skipped (`test_libm_check.py` is new, with 7
    tests).
- **CI.**
  - **`l6-determinism`** (run 37066691655): every job green. Every leg prints
    the frame's and the libm's pinned hashes. `libm_check` takes 14-39 s on
    the runners.
  - **`l6-mutation`** (run 37066694789): `plat_f2i` saturating in `plat.h`
    and the host's libm in the driver. Every renderer and libm step on every
    leg is red, and nothing else.

**V0: the frame oracle, frozen before any GPU frame.** 2026-10-02.
`tools/imgdiff.py` judges a candidate frame against a reference by 3.12's
metric. Its thresholds are frozen by mutations, and one rule had to be added
before they failed what a GPU path is likeliest to get wrong.

- **The references.** `refs` replays each capture from a scratch copy, with no
  `SOA_*` in the environment but `SOA_SETTINGS=0`, `SOA_HASH=1` and
  `SOA_THREADS=4`, into `build/gpu-oracle/ref/<set>/`.
  - **The corpus:** all 23 frames hash to `config/fifo_manifest.tsv`. The
    hash is FNV-1a over the PNG, as `gxr_screen_hash` computes it, and is
    also checked against the hash the replay printed.
  - **The 12 benchmark frames** were rendered after each capture was checked
    against `config/perfset_manifest.tsv`, and each was opened once:
    - **battle 4000 and 4001:** Vyse, a party member and a Soldier on a red
      grid floor, the turn gauge at 2/8. In the second frame the floor's tint
      has pulsed and the target rings moved.
    - **corpus 15800:** a pre-C5 capture of Vyse from behind in a riveted
      room of the a101b ship, the minimap lower right. The teal patch under
      him is the shadow volume as the pre-C5b stream draws it.
    - **corpus 6000:** a pre-C5 close-up of Fina's hood beside a
      gold-framed panel on a circuit-patterned wall.
    - **cutscene 4500 and 4501:** Alfonso and a guard behind a railing on his
      bridge, two green crystal lamps, crew in the foreground, the Vice
      Captain's line in the dialogue box.
    - **field 5000 and 5001:** Vyse from behind at Dangral base, the blue
      anchor save point to the left and the minimap lower right. These
      predate C5b too, and the dark green patch under him is its shadow
      volume.
    - **ship 6000 and 6001:** the Delphinus against the Black Pirates, the
      command grid and the Prototype Cannon menu.
    - **sky 4000 and 4001:** the ship from behind over night clouds, with
      the compass and the altitude gauge.
- **3.12's metric failed two of V0's own mutations.**
  - **The one-pixel shift** passed on 3 frames: 1500, 3900 and 6000, with
    far at most 0.97% and MAE at most 1.46.
  - **The second 1:2:1 vertical blur** passed on 22 of 23, with MAE
    0.06-1.19 and far at most 0.8%.
  - **The rule:** more than three blind spots stops the slice, so the metric
    changed, not the list.
- **The filter test.** Per axis, S is the least-squares coefficient of the
  error on the reference's backward difference, and L on its second
  difference.
  - **Measured over the 23:**
    - the shift: S along x is -1.00 on every frame;
    - the blur: L along y is 0.23-0.25;
    - identity, +-1 noise, 0.3% scattered and the diagonal line: within
      +-0.02;
    - the black block: up to 0.19 on S and 0.13 on L.
  - **The thresholds** are |S| at most 0.25, which a half-pixel offset at
    about 0.5 also fails, and |L| at most 0.10.
  - **The alternative measured first:** a detail ratio, sum |dC| over sum
    |dR|. It gave the blur 0.78-0.96, too near 1 for a margin.
- **The thresholds, frozen, and what set each:**
  - **3.12's five proposals stand;** no mutation needed one moved.
  - **Blob at most 64 and largest at most 32:** the black block fails them
    on every frame (22 x 22 = 484 blob pixels).
  - **MAE at most 1.5 and |bias| at most 0.75:** +-1 noise passes them (MAE
    1.0); +4 brightness and the washed-out transform fail them.
  - **Far at most 1%:** the shift and the blur pass it, which is why the
    filter test exists.
- **The result over the 23** (3 min 10 s):
  - the four noise-like mutations pass everywhere;
  - the block, washed out, shift and blur fail everywhere;
  - +4 brightness is blind on 0100 and 0300, nearly white boot frames where
    the clamp leaves 89% and 93% of pixels exact;
  - the red-blue swap is blind on 0500 and 0700, grey frames where red
    equals blue at every pixel.

  These four are `BLIND_SPOTS` in `imgdiff.py`, with these reasons. An
  unlisted one fails the run.
- **What it does not show:** how a real GPU's legitimate differences score. A
  consistent edge-rule difference correlates with the gradient at edge pixels.
  It should score far below a whole-frame shift, and 3.12's by-design rule
  decides it once V4a has frames.
- **Also:**
  - `tools/soa/png.py` holds midpoint.py's PNG reader and writer, moved, plus
    `screen_hash`.
  - `test_imgdiff.py` has 13 tests, on synthetic frames, so CI runs them.
  - pytest: 1151 passed, 2 skipped.

**The battle transition: an EFB copy's destination stride.** 2026-10-02.
Every random battle in the port began with streaks over unrelated artwork
where the game shatters the screen into squares. V1's capture of a battle's
start found it: part G's card on `a116a`, S3's seed-33 walk and accelerator,
the battle beginning at frame 4421.

- **What the game does.** It copies the 640x480 screen to an RGB5A3 texture
  at 0x667540 with BP 0x4D = 0x100, 8,192 bytes from one row of tiles to the
  next. It then samples that texture as 1024x512, with 1,536 texture binds a
  frame for at least 31 frames, while the image breaks apart.
- **What the renderer did.** It stored BP 0x4D (`cp_stride`) and never used
  it, packing the rows 5,120 bytes apart. The copy's 614,400 bytes filled the
  texture's first 300 rows as streaks (614,400 / (1,024 x 2) = 300). The rest
  showed whatever was already there: the battle-results screen's artwork.
- **The fix.**
  - `copy_to_texture` puts the rows of tiles at the stride.
  - `copy_bytes` returns the span the copy covers, which the fences and the
    texture hazard use.
  - A strided copy makes no copy image. That image describes a texture of the
    copy's own size, laid out packed, so a strided copy's texture is decoded
    from memory once its fence has passed.
  - A stride narrower than the copy's own rows still packs them. Its rows
    would overlap: the console orders the writes, but the pool writes rows in
    parallel and cannot. No game sets one.
- **What surfaced on the way.** The synthetic streams in `tools/citest` set
  0x28 there for every copy, a value from the screen copy. That made their
  128-wide RGBA8 copies overlap, and a 3-worker overlap run differed from the
  1-worker one, until the narrow-stride rule went in. The drivers now set each
  copy's natural stride.
- **Checks.**
  - **Regression:** `render_check`'s driver copies a 16x8 block with its rows
    512 bytes apart, then checks both rows and the untouched gap. With the
    fix reverted it fails, the second row landing at byte 128.
  - **The live run:** at 4421, 4436 and 4451 it shows the clean field, then
    the field in squares, then the squares scattering. The owner was sent
    before and after.
  - **Unchanged:** replay 23/23, because no corpus copy uses a stride other
    than its own (the mask effect's R8 copies set 0x50, their natural 2,560
    bytes).
  - **Also passing:** the self test; `title --check`; `compile_runtime` and
    `render_check` under MSVC and clang-cl; `queue_check` 18 of 18; and the
    renderer's test modules, 94 passed.

**V1: the captures the corpus lacks.** 2026-10-02. One live run a target,
one `soa.exe` at a time, each on a fresh copy of a save card. Consecutive
frames were captured into a scratch scan directory, never `build/fifo`, then
read with the new `tools/fifo.py --summary`.

- **The save menu** (a101b, `card-saved`, the one-word request poked at 3200):
  not found. The field gives way to a black frame at 3204, and the menu builds
  over ten frames to 741 draws, with no copy but the screen's. Frames
  3200-3359 searched.
- **The camp menu:** not found.
  - START at 3200 does nothing here; `docs/research/save-load.md` lists the
    conditions it needs.
  - Y switches to the first-person view.
  - X opens the camp menu on the party's status page (Vyse and Aika at level
    1, 10 gold). It cuts in at 3200 with no copy to a texture.
  - Frames 3195-3359 searched, once for each button.
- **A map change** (the game's own warp to `116c`, poked at 3300): not
  found. The screen is black from 3301 to 3361 and the new map draws from
  3364, with no copy. Frames 3295-3554 searched.
- **The start of a random battle:** found.
  - **The route:** a101b cannot fight (story flag 1025, S3's negative
    control). Part G's card on `a116a` with S3's exact recipe, the seed-33
    walk and the accelerator every 600 frames, starts a battle at 4421, the
    step counter falling to 0 between 4420 and 4424. All six runs with that
    input started it there.
  - **The summary at 4421:** `copy 3: to texture RGB5A3 at 00667540,
    640x480 from (0,0) clear`, beside the mask effect's two R8 copies.
  - **After it:** every frame from 4422 binds that texture 1,536 times
    (`SETIMAGE3` naming 0x333AA) as the field breaks into squares, well past
    V1's limit of 30. Kept: 4421 and 4422-4451.
  - **The defect:** this capture showed the renderer ignored a copy's
    destination stride, fixed first (FINDINGS "The battle transition").
- **A mask-effect frame with non-empty display lists:** a101b 3200: 2,279
  draws, the two R8 copies, logic AND (1 draw) and OR (2), and 11 display
  lists, none empty.
- **Captures with copies must be rendered.** The first battle captures ran
  without `SOA_RENDER`, and their replays from 4422 showed the battle UI's
  texture atlas where the field's pieces belong.
  - **Why:** decoded from the captured RAM, the copy's destination held that
    atlas in every frame, because with the renderer off no EFB copy writes
    memory.
  - **Proof the shards read there:** filling the destination with 0xA5 turned
    every shard that colour.
  - **Consequence:** 3.12 assumes "a capture's RAM already holds the live
    run's copy output", which holds only for a rendered run. Every kept
    capture was made again with `SOA_RENDER=1`, the battle after the stride
    fix.
- **`build/gpuset`:** 32 captures, 784 MB, pinned by input in
  `config/gpuset_manifest.tsv` (no frame hashes). `imgdiff refs --set gpuset`
  renders all 32 and checks every input.
  - **Opened, as a contact sheet and singly:** 4421 is Vyse in the corridor
    before a steel door. Through 4451 that picture breaks into squares that
    scatter and darken. The mask frame is Vyse at the a101b save point under
    its spotlight.
  - **The live run** at 4421, 4436 and 4451, rendered with the fix, matches
    the replays.
- **Also:** `test_fifo_summary.py` has 5 tests. The scan directory (21 GB,
  this session's) is deleted.

**V2: the renderer's backend seam.** 2026-10-03. A GPU backend now has
something to plug into, proved with the CPU renderer standing in for one. The
change introduces no new picture.

- **The header.** `runtime/gxr_cmd.h` holds `DrawCmd` with its `PixelCfg`,
  `RasterCfg` and `Rect`, moved out of gxr.c, and 3.1's interface:
  `GxrBackend`, `gxr_set_backend`, `gxr_backend_screen`, the exported clip
  helpers and `gxr_set_target`.
  - `DrawCmd` gains `efb`, the EFB it was built for. `claim_slot` stamps it
    from the producer's `g_target`, which H17a would have added; V2 adds it.
  - `TexCfg` gains `tex_id`, `tex_gen` and `copy_image`. The generation moves
    on every decode, replacement, copy image and eviction.
- **One run point.** The three places the producer runs a command itself
  (`gxr_draw`, `publish_clear`, `enqueue_copy`) now share `run_here`. It
  calls the backend when one is set and `draw_command` otherwise, and it
  counts a backend's screen copy in `g_frames_presented`, which the backend
  cannot reach.
  - **No workers:** `SOA_GXR_INLINE=1`, or any backend, starts none.
  - **The passthrough:** `SOA_GXR_BACKEND=passthrough` is the test-only
    backend that calls the CPU path's own code through the hook.
  - **Clears:** with a backend set, a copy's clear is always its own kind-2
    command.
  - **Waits:** `drain` and `wait_ran` call the backend's `finish`.
- **The zero-worker path, unreachable on Windows until now, works.**
  `scenario.py replay --threads inline,1,8` is 23/23. `inline` sets
  `SOA_THREADS=1` and `SOA_GXR_INLINE=1`, and fails a run that never says
  `rasterizing on 0 worker threads`.
- **`test_gxr_backend.py`** (5 tests) builds the renderer alone with a
  counting backend.
  - **The copy sequence:** two draws, a filtered copy to texture, an
    unfiltered full-scale copy and a screen copy, each copy with its clear
    bit, arrive as `0 0 1 2 1 2 0 1 2`.
  - **Generations:** across four draws of one texture they read A A A B: the
    same through an invalidate that changed nothing, then higher once its
    bytes changed.
  - **Counts and routing:** the frame and presented counts agree at 1, and a
    target of 1 set for one draw reaches that command alone.
  - **The corpus:** all 23 captures, replayed through the passthrough, keep
    their manifest hashes. Frame 6000 runs 3,593 draws, 3 copies and 1
    separate clear.
  - **The mutations,** each red:
    - the hook dropping kind 2;
    - the clear left fused in the unfiltered copy;
    - a re-decode keeping its generation;
    - `claim_slot` ignoring the target;
    - the passthrough skipping blended draws, which moves 23 of 23 hashes.
- **Codegen:** the worker loop's `/FA` code is identical to the base, and so
  is `raster_triangle`'s. Only `draw_command`'s copy branch moved, now a
  call to `run_copy` (a few times a frame), so nothing was timed.
- **Checks:**
  - `compile_runtime` under MSVC and clang-cl;
  - `--link`;
  - `render_check`;
  - replay 23/23 at 1,2,3,8 and at inline,1,8;
  - `test_gxr_overlap`, `_queue`, `_pair` and `_fastpath`, 45 passed;
  - the self test and `title --check`;
  - `test_scenario` with two new tests for `inline`;
  - pytest 1163 passed, 2 skipped.

**V3: the GPU spike (V3a, the harness and the geometry).** 2026-10-03. The
renderer draws through Vulkan for the first time: headless, outside the
port, on this machine's GPU (AMD Radeon Graphics, the Z1 Extreme's; Vulkan
1.4.344). Away from triangle edges, every scene covers exactly the pixels
the CPU covers. Colours match exactly too, except where they are
interpolated, which is within one step.

- **What it is.**
  - `tools/fetch_gpu.py` puts Vulkan-Headers `vulkan-sdk-1.4.357.0` and
    glslang 16.6.0 into `vendor/` (gitignored), with every kept file's
    sha256 in `vendor/GPU.sha256`. glslang's release archive is pinned by
    hash. GitHub builds the headers' tag archive on demand, so that hash is
    recorded but not enforced. `--verify` reports any file that is missing
    or changed.
  - `tools/gpuspike.py build` compiles the two shaders to SPIR-V as C
    arrays. It then builds `gx.c`, `gxr.c`, `gxr_tev.c`, `png.c`, the
    driver and `tools/gpuspike/gxv.c` into `build/gpuspike/<compiler>/`.
    It rebuilds only when an input is newer than the binary.
  - `gxv.c` is the backend:
    - Vulkan comes from `vulkan-1.dll` (or `libvulkan.so.1`) through one
      list of entry points;
    - one queue, a bump allocator per memory type, and an EFB of
      `R8G8B8A8_UNORM` with `D32_SFLOAT` depth;
    - vertex pulling of the `Vertex` records as they are, 156 bytes each;
    - pipelines keyed by topology, cull, depth state and write mask, with a
      dynamic scissor;
    - clears through `vkCmdClearAttachments`;
    - a screen copy by reading the EFB back, assembled as `copy_to_screen`
      does;
    - timestamps.
  - **Refused, with a message that stops the run:** a TEV shape other than
    the vertex colour, an alpha test that can reject, blending, logic ops,
    fog, a constant alpha, and a copy to a texture. These are V3b's and
    V4a's.
  - **Clipping is the consumer's.** A draw whose vertices all pass
    `gxr_vertex_unclipped` is uploaded as it is, with its own topology
    (quads through a static index buffer, `(0,1,2)(0,2,3)`). Any other draw
    is rebuilt as a list in `draw_command`'s order:
    - triangles go through `gxr_clip_polygon` and are fanned;
    - lines and points with w <= 0 are dropped, as the CPU skips them.
- **`python tools/gpuspike.py selftest`.** It runs the driver with
  `--backend cpu` and `--backend gpu` and compares 15 scenes.
  - **An edge pixel** is one whose 3x3 neighbourhood in the CPU's image is
    not all one colour, for the flat-coloured scenes, or not all covered
    or all uncovered, for the gradients. Vulkan's top-left fill rule and
    the CPU's inclusive one may disagree there.
  - **The two render recipes** from `runtime/selftest.c`, copied verbatim
    and held to it by a test, pass on the GPU: `307200 of 307200 red` and
    `complete, 53301 px`, as on the CPU.

  | Scene | Pixels, CPU / GPU | Away from edges | At edges | Colour |
  |---|---|---|---|---|
  | `cull0`: four shapes in both windings, a strip, a fan, two quads | 91,332 / 91,332 | 0 differ | 0 | exact |
  | `cull1` | 37,840 / 37,840 | 0 | 0 | exact |
  | `cull2` | 53,492 / 53,492 | 0 | 0 | exact |
  | `cull3` | 0 / 0 | -- | -- | -- |
  | `clip_near_ortho` | 45,710 / 45,710 | 0 | 20 | 51 px one step off |
  | `clip_far_ortho` | 45,710 / 45,710 | 0 | 20 | 49 px one step off |
  | `clip_near_persp` | 49,597 / 49,597 | 0 | 0 | 66 px one step off |
  | `clip_far_persp` | 35,812 / 35,813 | 0 | 3 | 73 px one step off |
  | `depth`: EQUAL redraw, LESS against the clear | 132,774 / 132,774 | 0 | 0 | exact |
  | `depth_persp`: two planes crossing in perspective | 152,061 / 152,053 | 0 | 22 | exact |
  | `scissor`: two per-draw scissors | 179,791 / 179,791 | 0 | 0 | exact |
  | `quad_gradient`: four corner colours | 157,820 / 157,820 | 0 | 0 | 193 px one step off |
  | `clear`: a copy's clear, (0x30, 0x60, 0x90) at depth 0x400000 | 264,000 / 264,000 | 0 | 0 | exact |
  | `lines`: six segments, a strip, and two in perspective | 2,400 / 2,391 | all within one pixel | -- | -- |
  | `points`: 64 | 64 / 64 | exact | -- | exact |

  - **The clip scenes' uploads.** In each, the vertices uploaded equal the
    driver's own walk of the draw through `clip_polygon`, field by field:
    9 vertices for each orthographic scene and 12 for each perspective one,
    where the draw had 6.
  - **Opened:** `depth`, `depth_persp` and `clear` show what their comments
    say. Red is wholly replaced by blue under EQUAL; green is in front
    only where z > 50; the cleared rectangle is (0x30, 0x60, 0x90) with
    orange around it and white over both.
- **Mutations, each run against the real source.** Thirteen turned it red:

  | Mutation | Scenes that failed |
  |---|---|
  | upload unclipped (`--mutate unclipped`, run by the test) | the four clip scenes and their upload check, and `lines` (the segment behind the eye) |
  | cull front and back swapped | `cull1`, `cull2` |
  | front face clockwise | `cull1`, `cull2` |
  | a strip drawn as a list | `cull0` to `cull2` |
  | a fan drawn as a strip | `cull0` to `cull2` |
  | quads split `(0,1,3)(1,2,3)` | `quad_gradient` |
  | depth unquantised | `depth` |
  | EQUAL compared as LESS | `depth` |
  | the fragment input's depth perspective-correct | `depth_persp` (the crossing moves from row 240 to 193; 6,492 px change colour) |
  | the clear's red and blue swapped | `clear` |
  | the clear's depth ignored | `clear` |
  | the scissor ignored | `scissor` |
  | lines with w <= 0 kept in the rebuild | `lines` |

  Four of these were green against the first scenes, and each exposed a
  gap that a scene now fills:
  - flat rectangles look the same whichever diagonal splits them;
  - the first perspective depth scene leaned both planes: with the
    fragment input perspective-correct both shifted alike and the crossing
    stayed on row 240, as putting that scene back afterwards confirmed. One
    plane now faces the eye;
  - every scene used the full-screen scissor;
  - no line went behind the eye.
- **Two results that are not checks, recorded as such.**
  - **The interpolation decoration that counts is the fragment input's.**
    Removing `noperspective` from the vertex output alone changes nothing,
    and the selftest stays green.
  - **Hardware colour rounding.** Writing the interpolated colour straight
    to the UNORM target, instead of quantising as the CPU does, gives the
    same bytes on this GPU in every scene. The shader quantises anyway,
    because Vulkan leaves the float-to-UNORM rounding to the
    implementation. Nothing here can tell the two apart on this GPU.
- **Points and lines** (none occur in the corpus, 3.2):
  - **Points:** a point exactly on a pixel edge (x = 554.0) lit 554 on the
    CPU and 553 on the GPU, where Vulkan leaves the choice to the
    implementation. The scene keeps its points 0.2 to 0.8 of a pixel from
    the edges.
  - **Lines:** the CPU steps a line in `ceil(length)` floored samples, and
    Vulkan rasterizes by diamond exit. 95 and 86 pixels differ, all within
    one pixel, so lines are judged on that and no closer.
- **Compilers.** The NDK's clang-cl (`--cc clang-cl` with `SOA_CLANG_CL`)
  builds the spike with no warning of its own, and its selftest gives the
  same numbers as MSVC's.
- **Time.** The GPU's timestamps total about 2.4 ms for the 42 draws and 18
  screen copies, each copy waiting for a fence. That is not a performance
  figure; V4a measures one. The selftest takes about 5 s. The test module
  takes 15 s, the two GPU runs most of it.
- **`test_gpuspike.py`** has 11 tests, 0 skipped here.
  - **Seven run anywhere:** the judge's own cases (an edge pixel moved
    passes, a hole or a one-step colour fails; colour edges; `cull3`;
    lines and points), the recipe copy, and every scene being judged.
  - **Four need `vendor/` and skip, printing why, without it:** the record
    verifying; a copy of `vendor/` with one header byte changed and
    `LICENSE.md` deleted failing it; the selftest; and the unclipped
    mutation failing.
  - **The two GPU tests also skip without MSVC** or a Vulkan device (the
    driver's exit code 3).
  - **CI:** its runners have no `vendor/` and no GPU, so CI runs the
    seven.
- **No runtime file changed.**

**V3: the GPU spike (V3b, the two exact differentials).** 2026-10-03. The
TEV and the EFB copy, the two pieces of the renderer that are all integers,
now run on the GPU and give the CPU's bytes exactly, over random inputs.

- **What it is.**
  - `tools/gpuspike/tev.glsl` is `tev_pixel`'s general path, transcribed:
    the 32-entry input bank, the lerp, bias, shifts, both clamps, the four
    colour compare modes, swaps, konst, and the two alpha compares with
    their logic. It reads a setup packed by `gxv_pack_tev` from a
    `TevSetup`, and asks its includer for texels. `tevdiff.comp` runs it a
    case an invocation.
  - `tools/gpuspike/copy.comp` is `copy_to_texture` and `copy_to_screen`:
    the filter, the half-scale box, intensity and channel choice, formats 0
    to 6, tiling at any stride, one invocation per 32-bit word of the copy,
    with the buffer seeded from guest RAM first. It also works out each
    texel's decoded RGBA, what `tex_decode_row` gives from those bytes.
  - `gxv` now makes every EFB copy with it, to a texture (into guest RAM) or
    to the screen. Draws are still the vertex colour only, which V4a ends.
- **`python tools/gpuspike.py tevdiff`: 100,000 cases, 0 mismatches.** The
  same held for seeds 1, 2 and 3.
  - **Each case:** `tev_prepare` turns random registers into a setup, with
    every map a 1x1 nearest texture of a random texel and random raster
    colours. `tev_pixel` runs it twice, as prepared and with `fast_c` and
    `fast_a` turned off, and `tev.glsl` runs it once.
  - **The registers:** the spec's C0-DF, E0-E7, F3, F6-FD and GEN_MODE,
    and also the texture orders 0x28-0x2F. Without those every stage would
    sample map 0 with texturing off.
  - **The fast shapes:** one case in eight is built as an H15c fast shape,
    which random words almost never make. So the fast path is held to the
    general one, and both to the GPU, over 6,367 and 6,338 cases of
    `fast_c` 1 and 2 and 3,158, 6,334 and 3,213 of `fast_a` 1 to 3.
  - **Every path counted at least 100 times.** The smallest count is those
    3,158. Each colour and alpha compare mode is near 23,000; each shift,
    clamp, bias, op, alpha logic and alpha compare function runs from
    12,342 to 383,994 times.
  - **Found on the way:** the first version seeded `xorshift32` with the
    case number almost as it was. Xorshift is linear, so neighbouring cases
    came out correlated, and the alpha logic's four values each took
    exactly 25,000 of 100,000 cases. Seeding is now splitmix64, and the
    counts vary as random ones do (24,753 to 25,255).
- **`python tools/gpuspike.py copydiff`: 25,600 copies, 0 differences.**
  - **The combinations:** every copy command format (BP 0x52's four bits,
    0 to 15), intensity on and off, half scale on and off, filter on and
    off, 128 in all. Each has 200 random rectangles and a random EFB.
  - **The rectangles:** 60% are up to 64x64, 30% up to the EFB's size and
    10% up to 1024x1024, past its edge. Odd widths come up throughout.
  - **Strides and filters:** a quarter of the copies use a wider stride.
    Filters are mostly weights summing near 64, and a quarter are anything
    at all, which clamps.
  - **What is compared:** the CPU renderer and gxv make the same copies in
    two processes at once, from one seed, with random bytes around each
    destination. They must leave the same bytes over the copy's span and
    64 either side, the same decoded image and the same screen copy of the
    rectangle. All three are equal in every case.
  - **Refusals:** 12,000 are copies the CPU refuses (intensity with a
    format above 3, and the three unknown formats). On both sides they
    leave RAM exactly as seeded.
- **Mutations, all red.**
  - **The four the Done names,** each in exactly the combinations it should:

    | Mutation | What failed |
    |---|---|
    | the clamp flipped in `tev.glsl` (`--mutate clamp`) | tevdiff |
    | the copy filter rounding instead of truncating (`rounding`) | RAM, image and screen, filtered copies only |
    | intensity rounding instead of truncating (`intensity`) | RAM and image, intensity copies only |
    | the buffer written back without seeding from RAM (`unseeded`) | RAM only |

  - **Twenty-six more,** each applied to the shader source and reverted,
    every one red.
    - 16 in the TEV: the lerp's rounding constant; c' without `c >> 7`;
      bias -128 as -127; shift 3 as a division; operand a unmasked; d
      masked; GR16 comparing one channel; the RGB8 compare using channel
      0; the alpha compare's `>` as `>=`; the raster swap ignored; the
      texture swap ignored; channel 1 reading channel 0; XOR as XNOR;
      LEQUAL as LESS; the alpha destination ignored; the texel dropped
      between stages.
    - 10 in the copy: R4's nibbles swapped; RGBA8's two halves swapped;
      the box rounding; filter taps clamped to the EFB rather than the
      rectangle; RGB5A3's threshold at 223; RGB565 green at 5 bits; IA4's
      alpha unmasked; the stride ignored; screen alpha copied; the
      decoded RGB5A3 alpha scaled by 36.
    - **The weakest:** LEQUAL as LESS mismatched 15 of 20,000 cases, and
      GR16 25; the run takes 100,000.
- **Differences from 3.6, both chosen for exactness by construction.**
  - **The EFB is read through a buffer,** copied from the image, rather
    than as a sampled image: every byte is exact, with no
    unorm-to-float-and-back conversion to trust.
  - **The decoded image is worked out from each texel's value** rather than
    read back out of the bytes. So a mistake in an encoding shows in RAM,
    and one in a decoding shows in the image.
- **Speed.**
  - **Cached memory for what the host reads back:** at first copydiff's
    GPU side took 14.5 s for 10 rectangles a combination against the CPU's
    0.8 s, reading results out of write-combined memory. Those buffers are
    now host-cached, and the same run takes 1.5 s.
  - **copydiff:** 22 s at 200 rectangles, both sides at once. The 25,600
    copies to texture and 25,600 to the screen cost 2.3 s of GPU time,
    each copy waited for.
  - **tevdiff:** under a second.
  - **A built binary needs no compiler:** `build` now looks for one only
    when something is stale, which saved 2 s a command.
- **Compilers.** Built by the NDK's clang-cl, tevdiff, copydiff and the
  scenes all pass with the same numbers.
- **`test_gpuspike.py`** has 19 tests, 0 skipped here, in 32 s.
  - **New, needing a GPU:** tevdiff and copydiff at the Done's sizes, the
    clamp mutation, and the three copy mutations, each held to the
    differences it must cause.
  - **New, running anywhere:** two tests of copydiff's comparison. One
    checks each kind of difference is counted. The other checks a refused
    copy that wrote is caught, as are two runs whose cases differ, a run
    cut short, and an empty run.
  - **CI** runs the nine that need no GPU.
- **No runtime file changed.**

**V4: the GPU spike on captures (V4a, draws, textures, depth, fog and blend).**
2026-10-03. The GPU draws the game's captured frames, and all 21 frames
without a copy to a texture pass V0's oracle against the CPU's, on the first
run. They are 15 of the corpus and 6 of the benchmark set; nothing needed
fixing, and no frame needed bisecting.

- **What it is.**
  - **The fragment stage, `raster.frag`:**
    - `tev.glsl`, the TEV, which V3b's tevdiff holds exact;
    - `sample` and `sample_level`, transcribed: wrap modes, the
      non-power-of-two remainder (rebuilt from the division, since GLSL
      leaves `%` of a negative number undefined), nearest, and bilinear
      with the CPU's 8-bit weights;
    - each texcoord's level of detail, from `dFdxFine` and `dFdyFine` with
      `span_lod`'s formula;
    - the alpha test as a `discard`, fog as `fog_apply` does it, and depth
      quantised as before.
  - **What it reads:** a record a draw (TEV, texture slots, fog) in a
    storage buffer, and the texel pool. Each texture is uploaded once a
    submission per cache slot and generation, as 3.2 has it.
  - **Blending, write masks and depth** are the pipeline's, by 3.5's table.
    Pipelines are keyed by topology, cull, depth, masks and blend, and made
    on first use: 8000 made 9.
  - **Refused, and stopping the run:** logic ops (V4b's) and a constant
    alpha. Neither occurs in these 21.
  - **`gpuspike.py oracle`** replays each capture on the CPU and on the GPU
    through `gx_replay`, the port's own replay, and prints V0's verdict.
  - **`gpuspike.py time`** reports the GPU's and the consumer's
    milliseconds beside perfbench.
- **The references.**
  - **They are the spike's own CPU replays,** made in the same session.
  - **All 15 corpus frames** hash to the manifest's FNV.
  - **All 6 benchmark frames** are V0's inspected references, byte for
    byte.
  - **The NDK's clang-cl build** reproduces both, and its GPU frames pass
    too.
- **The 21 captures**, every one passing V0 (`python tools/gpuspike.py
  oracle`):

  | Capture | Exact | Near | Far | Blob | MAE |
  |---|---|---|---|---|---|
  | 0100 | 306,296 | 904 | 0 | 0 | 0.001 |
  | 0300 | 304,834 | 2,366 | 0 | 0 | 0.005 |
  | 0500 | 306,747 | 453 | 0 | 0 | 0.001 |
  | 0700 | 305,662 | 1,538 | 0 | 0 | 0.005 |
  | 11900 | 294,140 | 13,023 | 37 | 0 | 0.038 |
  | 12000 | 293,359 | 13,808 | 33 | 0 | 0.039 |
  | 12100 | 297,567 | 9,537 | 96 | 0 | 0.030 |
  | 1500 | 255,461 | 51,735 | 4 | 0 | 0.063 |
  | 2000 | 293,273 | 13,927 | 0 | 0 | 0.017 |
  | 2050 | 293,426 | 13,774 | 0 | 0 | 0.017 |
  | 2100 | 293,295 | 13,905 | 0 | 0 | 0.017 |
  | 3600 | 300,484 | 6,711 | 5 | 0 | 0.010 |
  | 3900 | 292,740 | 14,373 | 87 | 0 | 0.033 |
  | 4200 | 292,160 | 15,013 | 27 | 0 | 0.023 |
  | 8000 | 291,987 | 15,145 | 68 | 1 | 0.028 |
  | battle_4000 | 293,344 | 13,732 | 124 | 0 | 0.035 |
  | battle_4001 | 293,304 | 13,758 | 138 | 0 | 0.036 |
  | ship_6000 | 252,131 | 54,957 | 112 | 9 | 0.097 |
  | ship_6001 | 251,841 | 55,247 | 112 | 9 | 0.098 |
  | sky_4000 | 299,788 | 7,412 | 0 | 0 | 0.011 |
  | sky_4001 | 299,833 | 7,367 | 0 | 0 | 0.011 |

  - **The largest far count is 0.045% of a frame,** against V0's 1%. The
    largest blob is 6 pixels, against 32.
  - **Opened:** 8000's GPU frame is the battleship and the Little Jack, as
    the CPU draws them. Its heat map shows one-step differences across the
    textured clouds and along edges, nothing missing.
  - **Ship_6000's far pixels, magnified:** a row of isolated pixels inside
    the hull's texture (y 319), each one texel over, and one pixel on a
    mountain's edge. These are 3.4's last-bit sampling and edge classes.
  - **The GPU drew every draw:** 8000's replay ran 4,387 draws on the GPU,
    1,801 of them rebuilt by clipping, while the CPU rasterizer shaded 0
    pixels.
- **Mutations** (`oracle --mutations`). A mutation applies where it
  changes at least 0.5% of the unmutated GPU frame's pixels (3.12).

  | Mutation | Applies on | Fails V0 on | Blind spots |
  |---|---|---|---|
  | skip the frame's most visible large draw | 21 | 21 | 0 |
  | fog off | 7 (3900, 4200, 8000, ship, sky) | 7 | 0 |
  | the copy filter off in the screen copy | 21 | 21 | 0 |
  | the alpha test off | 3 (8000, the ship pair) | 3 | 0 |
  | level-of-detail bias +1 | 16 | 14 | 2 (the sky pair) |

  - **"The largest draw" needed defining.** By samples passed (an
    occlusion query around each draw), the largest is often a full-screen
    fill that later draws cover entirely. Skipping 8000's (307,200
    samples) changed nothing. The mutation now takes the five largest by
    samples and skips the one whose absence changes the most pixels.
  - **The alpha test off applies on only 3 captures,** two distinct frames,
    short of 3.12's five. Only those frames have alpha-tested pixels that
    show once drawn (0.9% and 3.8%); sky's come to 0.49% and 12100's to
    0.23%. It fails V0 on all 3. `SHORT_OF_FIVE` in `gpuspike.py` names it
    with that reason, and V4b counts it again over 35 captures and V1's.
  - **The LOD bias +1 passes V0 on the sky pair,** one distinct frame. 12%
    of the pixels move, most by one or two steps (22,178 by 1, 6,622 by 2,
    the largest 32), and 137 are far.
    - **Where:** only on the player's ship and the cloud band at the
      horizon. Magnified, the ship is visibly a level blurrier: the blue
      band and hull lose detail.
    - **Why V0 passes it:** its whole-frame blur and MAE are diluted by the
      empty sky.
    - **This is a real blind spot.** It is listed in `GPU_BLIND_SPOTS` with
      that reason. The thresholds are not changed here: that is its own
      commit with its own inspected frames (3.12). The gate should weigh it.
- **Invariance.** A strip in perspective is drawn twice with depth LEQUAL
  and update.
  - **The two passes:** first red through the vertex colour, then a konst
    blue added to it (blend ONE, ONE). The second pass is a different TEV
    and a different pipeline.
  - **The result:** 87,120 pixels red after the first pass, 87,120 magenta
    after the second, none left red, on the CPU and the GPU alike.
  - **Without `invariant gl_Position`** (`--mutate noinvariant`) the result
    is the same on this GPU: the driver evidently places the vertices alike
    without being told to. The qualifier stays, as 3.3 requires.
  - **The check can fail:** pushing only the second pass's depth one 24-bit
    step deeper, by hand, gives 0 magenta and 87,120 left red.
- **Time** (`gpuspike.py time`, median of 5). Reported, not a gate.
  - **GPU:** 1.3 to 4.7 ms a frame.
  - **The consumer:** 2.7 to 18.9 ms a frame; the battle frames take about
    16 ms and 11900 19 ms. Every submission is waited for and every texture
    copied in on the CPU, which V7's pipelining is for.
  - **perfbench, 8 workers on the CPU,** before and after in the same
    session: 57.1 and 58.1 ns a fragment over the benchmark set. Ship_6000,
    for instance, is 1.77 M fragments at 73.6 ns, about 130 ms of worker
    time or 16 ms across eight. On the GPU it is 3.9 ms, and 7.8 ms of
    consumer.
- **Device features:** core only, but for `occlusionQueryPrecise`, enabled
  where the device has it (this one does) so that `measure` counts samples
  exactly. Nothing that draws depends on it.
- **`test_gpuspike.py`** has 22 tests, 0 skipped here, in 50 s.
  - **New:** the 21-capture oracle (it skips, saying why, without
    `build/fifo` or `build/perfset`), the replay's environment, and the
    mutation threshold.
  - **The scenes' test** now also holds the invariance strip.
  - **Not run by pytest:** the mutations, about two minutes, run by
    `oracle --mutations`.
- **No runtime file changed.**

**V4: the GPU spike on captures (V4b: copies, logic ops, the new captures).**
2026-10-03. All 67 captures replay on the GPU:
- the corpus's 23, the benchmark set's 12 and V1's 32;
- the 16 that copy to a texture poisoned, as 3.12 asks, and copied by the
  GPU's own compute pass.

65 pass V0. The two that fail, the Dangral base field pair, fail by design,
and the mechanism is one the CPU reference gets wrong.

- **What it adds.**
  - **Logic ops three ways, `--logicop`:**
    - native, Vulkan's `logicOp`, whose 16 numbers are GX's;
    - blend, OR as `src(1 - dst) + dst` and AND as `src dst`;
    - snapshot, the EFB copied out before the draw and the CPU's bitwise op
      done in the shader, with the source alpha kept.
  - **The poison step:** each copy-to-texture destination is found by
    pre-scanning the stream with `copy_bytes`' arithmetic, and filled with
    0xA5 in a scratch copy of the capture. Only the rows of tiles a copy
    writes are filled, not the gaps a wide stride leaves.
  - **New commands:** `logicop`, `ramdiff` and `chain`.
  - **A selftest scene for logic ops,** and `GXV_DRAW=N` and
    `--dump-depth` for classifying a failure.
- **A defect, found and fixed in the slice.** With native or snapshot logic
  ops the mask-effect frames came out white or black.
  - **Bisected** to the AND draw: draw 2347 of 6000.
  - **The cause:** the pipeline's blend block tested the key's blend field,
    which also carries a logic op's number. So every logic pipeline was given
    a blend with factors ZERO, ZERO besides its logic op. The blend mode
    overwrote the factors, which is why it alone was right.
  - **The guard:** the new selftest scene (a quad, then OR, AND, OR as the
    mask effect draws them) caught it, and holds all three modes to the CPU.
- **Poison.** All 8 corpus copy captures, poisoned, still hash to the
  manifest on the CPU, so every sampler reads this replay's own copies
  (the same-replay contrast). All 16 copy captures' poisoned CPU references
  equal V0's inspected ones or the manifest.
- **The oracle**, `python tools/gpuspike.py oracle --set
  corpus,perfset,gpuset`: 65 of 67 pass V0. Field_5000 and field_5001, one
  moment, fail on blobs (172 blob pixels, the largest 59).
  - **Bisected:** their five clusters go to draws 374, 393, 653, 656 and
    76. All are by design.
  - **Three are coplanar decals whose depth the CPU gets wrong.** The CPU
    steps depth along a span by float additions (`av[n] += attr[n].a`), and
    over long spans it drifts.

    | Pixel | Draw that set the depth | Its exact depth | GPU stored | CPU stored | The decal, exact | The decal on the CPU |
    |---|---|---|---|---|---|---|
    | (600, 179) | 346 | 16,712,140.0 | 16,712,140 | 16,712,197 | 374: 16,712,156.9 | passes |
    | (227, 345) | 355 | 16,454,135.9 | 16,454,137 | 16,454,163 | 393: 16,454,154.6 | passes |
    | (273, 172) | -- | -- | 16,702,776 | 16,702,765 | 653: 16,702,806.9 | 16,702,756, passes |

    - **Exact arithmetic** puts each decal behind the surface, and the GPU,
      within 2 steps of exact, leaves it out.
    - **The CPU draws it** only because its stored depth drifted 27 to 57
      steps deep, or its decal's depth 51 shallow.
    - **Where:** these are pixels 142 to 227 along their spans.
  - **The fourth, draw 656,** ties exactly: its exact depth is 16,710,535.5,
    which truncates to the 16,710,535 stored. LEQUAL passes it on the GPU,
    and the CPU's last bit fails it.
  - **The fifth, draw 76,** agrees in depth. The CPU narrates its level of
    detail as 3.50, on the boundary of two mip levels this texture makes
    very different (dark blue and light grey): 3.4's level choice near a
    boundary, over five pixels.
  - **The method.** Each depth was read from both paths after draw N
    (`SOA_GXR_DRAWS=N`, the frame's last screen copy cut off so nothing
    clears it). The exact values were worked in double precision from the
    draw's clip-space vertices, printed to nine digits. A first pass with
    three decimals was off by about 40 steps, which is the size of the
    effect, so it decided nothing.
  - **The verdict:** two by-design failures in one distinct scene, under
    3.12's three. `BY_DESIGN` in `gpuspike.py` names them.
- **Logic ops, `logicop`.** On the 14 mask-effect captures (12 distinct),
  native, blend and snapshot give byte-identical frames, 3 logic draws
  each.
  - **The Done's three mutations,** applied to the native path only, each
    part the paths by 226,000 to 307,000 pixels and fail V0 on all 14: the
    AND as a copy, the ORs as copies, OR and AND swapped.
- **`ramdiff`**, 33 copies to a texture, both paths poisoned.
  - **Every copy writes:** each of the 32 R8 copies writes 306,600 to
    307,200 of its 307,200 bytes (a byte can be 0xA5 by chance), and the
    RGB5A3 copy 602,218 of the 614,400 its rows of tiles hold.
  - **Differences:** 0 to 22,811 bytes differ per copy, the largest
    difference 224, in the RGB5A3 copy's packed bytes.
  - **Every differing byte is traced to the EFB.** The tool cuts the
    stream just before the copy, appends an unfiltered screen copy, and
    replays it on both paths. A differing byte must sit over a pixel, among
    the ones its filter reads, that differs there, the encoders being equal
    (V3b). 0 untraced.
  - **The trace can fail:** with the GPU's copies written 32 bytes on,
    most of the differences are untraced (259,675 of 288,221 in one copy).
- **`chain`**, V1's battle start, 4421 to 4451, 31 frames.
  - **What is carried:** 4421's three copies (the two R8 masks and the
    screen into a 1,024-wide RGB5A3 texture), kept from each path and
    spliced into each later frame's RAM.
  - **On the CPU** the 1,228,800 spliced bytes equal what those frames'
    RAM already holds, so nothing wrote them between frames.
  - **On the GPU** every chained frame, sampling the GPU's own copy,
    passes V0.
  - **A fix on the way:** the first version spliced and poisoned the
    RGB5A3 copy's whole span, gaps included, and so failed the equality.
    Now only the rows of tiles are carried.
- **Mutations**, `oracle --set corpus,perfset,gpuset --mutations`, poisoned.
  A frame failing V0 by design is left out.

  | Mutation | Applies on | Fails V0 on | Blind spots (distinct) |
  |---|---|---|---|
  | skip the most visible of the five largest draws | 35 | 35 | 0 |
  | fog off | 14 | 14 | 0 |
  | the screen copy unfiltered | 65 | 65 | 0 |
  | the alpha test off | 5 | 5 | 0 |
  | LOD bias +1 | 28 | 23 | 5 (3) |
  | logic ops drawn as copies | 14 | 14 | 0 |
  | copies to a texture skipped | 14 | 14 | 0 |
  | copies written 32 bytes on | 14 | 14 | 0 |

  - **The alpha test now applies on five** with V1's captures included,
    which meets 3.12's rule.
  - **LOD +1 adds the ship's hold to V4a's sky pair:** 15200, 15800 and
    the benchmark set's copy of 15800.
    - **What it does there:** a level blurrier fades the floor's rivets
      almost away, 12% of pixels moving and about 1,012 far.
    - **What V0 sees:** its vertical blur measure reads 0.089 against its
      0.10.
    - **The count:** three distinct frames, at the limit. **V0 does not
      reliably catch a one-level blur of texture detail.** The thresholds
      stay as they are here; changing one is its own commit (3.12), and
      the gate should weigh this.
- **The owner's look:** `build/gpuspike/review/index.html` has five rows,
  each CPU | GPU | heat map:
  - the field (field_5000, the by-design pair, captions naming its
    clusters);
  - a battle;
  - a ship battle;
  - the mask effect (mask_3200);
  - the battle transition, chained.

  The owner looked on 2026-10-03 and judged them right; the gate answered
  A, Vulkan (PLAN-NEXT §0).
- **Compilers.** The NDK's clang-cl build gives the same oracle verdicts.
- **`test_gpuspike.py`:** the oracle test now covers the 35 captures with
  copies (33 pass and 2 by design). It adds `logicop` and four GPU-free
  tests: `copy_texfmt` against gxr.c's table, a copy's runs and texels
  across a stride gap, poison touching only what a copy writes, and
  `efb_at`'s cut. `ramdiff`, `chain` and the mutations are commands, about
  20 s, 30 s and 16 min.
- **No runtime file changed.**

**V5, first: `loddiff`, the level of detail held exactly.** 2026-10-03. This
is the owner's answer at the gate for V0's blind spot. LOD +1 passes V0 on
three distinct frames ("V4"), so the GPU's choice of mip level is now held
to the CPU's directly, as `tevdiff` holds the TEV.

- **What it compares.** `python tools/gpuspike.py loddiff` runs two kinds of
  case, 100,000 of each, in one process.
  - **The level:** a random level of detail, bias, clamps, level count,
    texture size, scale and coordinate. They go through the sampler's own
    level choice (`tex_level`, a wrapper of gxr_tev.c's `SAMPLE_AT`) and
    through lod.glsl's `gx_level` and `gx_level_uv`. These must agree bit for
    bit, in the level and in u and v scaled to it.
    - The registers' own ranges are used.
    - One case in four lands within four ULPs of a rounding boundary.
    - One in 64 is a NaN, which `span_lod` returns for a degenerate
      triangle.
    - Nine paths are counted, and each must be taken 100 times. The smallest
      count is 1,615 (NaN).
  - **The formula:** random planes of 1/w, s/w, t/w and q/w and a pixel.
    They go through `span_lod` (`gxr_span_lod`) and through `gx_lod`, given
    the derivatives worked in double from the same planes.
    - The derivatives themselves differ by design (3.4) and stay V0's.
    - The tolerance, fixed before the first run: within 1/1024 of a level.
    - 67 cases are left out, where the CPU's float subtraction cancels
      (condition over 1,000) or the footprint sits by `span_lod`'s floor.
- **The first run failed, on the coordinates, not the level.**
  - **The count:** 5,256 of 100,000 cases had u or v one ULP away. All 5,256
    were levels above 0 of a texture whose side is not a power of two. The
    level matched in every case.
  - **The cause:** `scale * lw / w` is a division, and Vulkan allows a GPU's
    division to be 2.5 ULP out. This GPU is exact only when dividing by a
    power of two, which no rule promises.
  - **The fix:** lod.glsl now divides by a side exactly. A power of two is an
    `ldexp`; any other side is divided out of the 24-bit significand in
    integers, a bit at a time, and rounded to nearest even, as C's division
    rounds.
  - **The result:** 0 mismatches.
- **What it shows now** [V, seed 1]:
  - level: 0 mismatches in 100,000;
  - formula: 99,933 cases, none over 1/1024, the largest 0.00044 of a level.
- **The mutations fail.**
  - `--mutate lod`, the same bias +1 the oracle runs, gives 12,096 level
    mismatches. It cannot show where the clamps already hold the level.
  - `--mutate lodmin`, the footprint's smaller axis for its larger, puts
    99,877 formula cases over the tolerance.
- **The fragment stage reads the same code.** raster.frag now takes its level
  of detail from lod.glsl.
  - **One comparison covers both changes:** the move into lod.glsl and the
    exact division. Afterwards, all 67 captures' GPU frames were
    byte-identical to a run taken just before the move, and V0's verdicts are
    unchanged (65, two by design). The self test passes.
  - **What that says:** the division changed nothing these frames sample. A
    captured frame either reads no mipmapped texture with a side that is not
    a power of two above level 0, or its one-ULP change moved no pixel.
- **The runtime is unchanged in what it runs.**
  - **Why that needed checking:** the level choice became gxr_tev.c's
    `SAMPLE_AT`, which `sample()` and the new `tex_level` share, and gxr.c
    gained `gxr_span_lod`.
  - **A macro, not an inline function:** a forced-inline function moved
    `tev_pixel`'s register allocation. With the macro, every function that
    existed compiles to the same instructions as before in MSVC's `/O2`
    listing (labels normalised); only the two wrappers are new.
  - **The checks:** the 23 pinned frames match at 1, 2, 3 and 8 threads; the
    runtime compiles under MSVC and clang-cl; and the self test reports 0
    failures.
- **Still a GPU division.** Two remain in the fragment stage: `s/q` for a
  projective texture coordinate, and `gx_lod`'s `/q`. Neither is held
  exactly; V0 judges what they do. For q = 1, an ST texture coordinate,
  both are exact.
- `test_gpuspike.py` gains three tests: the pass, and each mutation failing
  its own half.

**V5, second: the backend moves into the runtime.** 2026-10-03. `gxv.c`,
`gxv.h` and the seven shaders are now `runtime/gxv.c`, `runtime/gxv.h` and
`runtime/gxv/`, so the spike and `soa.exe` build one source. The spike's
driver stays in `tools/gpuspike/`. `soa.exe` links the backend but does not
call it yet: `SOA_GPU` is the next commit.

- **Built two ways.**
  - **With `SOA_GXV=1`:** the backend, compiled against Vulkan-Headers and
    the SPIR-V that `tools/soa/shaders.py` makes from `runtime/gxv/`.
    `tools/gpuspike.py` always builds it so. `recompile.py --link` does when
    `vendor/` holds glslang and the headers, as recorded.
  - **Without it:** a stub whose `gxv_built()` says the build has none.
  - **Failures:** a shader that does not compile fails the link, and a
    `vendor/` that differs from its record stops it.
  - **Both links run** [V]: `GPU backend: built in`, then `not built in` with
    glslang set aside; each `soa.exe` passes the self test with 0 failures.
- **The loader.** Vulkan is opened through `plat_dl_open` and `plat_dl_sym`,
  portability.md 3.3's `plat_dl_*`, which land here in `plat.c`: on Windows
  `LoadLibraryExA`, elsewhere `dlopen(RTLD_NOW | RTLD_LOCAL)`.
  `SOA_GPU_LOADER` names another loader (3.11).
- **Debug variables renamed.** `GXV_DRAW`, `GXV_DEVICE` and `GXV_VALIDATE`
  are now `SOA_GPU_DRAW`, `SOA_GPU_DEVICE` and `SOA_GPU_VALIDATE`, so a
  replay, which strips every `SOA_*` variable (3.12), cannot inherit one.
- **The C is checked everywhere.** `compile_runtime.py` compiles `gxv.c`
  twice: as every runtime file is (the stub), and as the backend, with
  one-word stand-ins for the SPIR-V, so no glslang is needed.
  - **The headers:** `fetch_gpu.py --headers` fetches Vulkan-Headers alone.
  - **CI:** every compile job (MSVC, clang-cl, Linux gcc and clang, ARM64
    gcc) fetches the headers and passes `--require-gxv`, which turns missing
    headers into a failure.
  - **Here** [V]: MSVC and clang-cl compile both builds with no warning from
    `gxv.c`. The NDK's clang, targeting aarch64 Android, compiles `gxv.c` and
    `plat.c`, the `dlopen` side included.
- **The move changed nothing the spike draws** [V].
  - **The images:** each one written for the same command is byte-identical
    to the build before the move: the self test's 17 scenes, plain and with
    `--mutate unclipped`, and the oracle's 67 captures (65 pass V0, two by
    design, as before).
  - **The differentials:** `tevdiff`, `copydiff` and `loddiff` pass.
  - **One false alarm, explained:** the first comparison flagged five
    self-test images, four clip scenes and the lines. The baseline had been
    written by the test suite's last self test, the one with `--mutate
    unclipped`, and the new build's mutated run reproduces all 17 exactly.
- **Tests:** four new.
  - The shader list is exactly what `gxv.c` includes, and each stub declares
    its array.
  - `--headers` records only the headers and asks for no glslang, where a
    full fetch on a host without a release refuses.
  - The backend compiles against `vendor/`, fails against an empty
    `vulkan_core.h`, and is not attempted without headers.
  - `--link` adds `SOA_GXV=1` and the two include paths only when asked,
    the rest being the golden copy.

**V5: the GPU draws the game in `soa.exe`.** 2026-10-03. `SOA_GPU=vulkan`
(`gpu = vulkan` in `soa.ini`) makes gxv the renderer's backend in the port
itself. Every command is drawn on the GPU as the producer builds it, and the
screen copy read back is the picture. Every frame waits for the GPU; V6
moves that to a thread.

- **What it says.**
  - **When it starts:** one line, `[gxv] Vulkan 1.4.344 on AMD Radeon
    Graphics (driver 0x800184): logicOp yes; EFB 640x528 RGBA8 + D32F;
    logic ops native; timestamps on`.
  - **When it cannot:** one `[gxv] fallback: <why>; the CPU draws` line.
    The causes are a build without the backend (which names `fetch_gpu.py`
    and `--link`), no loader, no device, or a value of `SOA_GPU` other than
    `off` or `vulkan`.
  - **At the end:** its report, after `[gxr]`'s.
  - **What the renderer sent:** `[gxr]` now prints `<name> backend: N
    draws, M copies, K clears` for any backend, not only the passthrough,
    so the two reports can be held to each other.
  - **Knobs:** `SOA_GPU_LOGICOP` picks the logic-op path,
    `SOA_GPU_LOADER` another loader, and `SOA_GPU_MUTATE` one of gxv's
    mutations (a check's knob).
- **The same pictures as the spike** [V]. `python tools/gpuspike.py
  contrast --set corpus,perfset,gpuset` replays all 67 captures through the
  spike and through `gen/soa.exe --replay`, both on the GPU, from one scratch
  copy of each.
  - **The result:** 67 of 67 have the same pixels, and both binaries print
    the one start line, driver version included.
  - **So V0's verdicts carry over:** each picture is the spike's, which the
    oracle judged (65 pass, two by design).
  - **The mutation:** `--mutate fog` (soa.exe's shader without fog) makes 14
    differ, the 14 V4b found fog applies to, and fails the contrast.
- **A live run, judged on its own log** [V]. `python tools/scenario.py run
  title --check --env SOA_GPU=vulkan` passes five invariants in the usual 71
  s, the four as before and "the GPU drew the run".
  - **What was drawn:** 26,336 draws, 2,000 screen copies and 152 copies to
    a texture, exactly what the renderer handed the backend (26,336 draws,
    2,152 copies, 2,000 clears) and what `[gxr]` counted copying.
  - **The mutation:** with `--env SOA_GPU_LOADER=nonexistent.dll` the run
    falls back, the four invariants still pass on the CPU, and the fifth
    fails, naming the fallback.
  - **`test_gxv_live.py`** holds the check to canned logs, each wrong one
    way. `scenario.py check <log>` applies it to any log with a `[gxv]`
    line: the passing run's log gives 5 of 5, the fallback's fails, and a
    CPU run's gives 4 of 4.
- **The spec's comparison had to change.** V5's Done line held the GPU's
  counts to `[gx]`'s draw count. That cannot hold in a headless run with
  `SOA_SNAP`: the renderer draws only the frames it snapshots, so `[gx]`
  parsed 1,261,709 draws where 26,336 were drawn. The check compares what the
  renderer sent the backend instead, and screen copies to `[gxr]`'s count
  (2,000, which `SOA_SNAP` does not thin).
- **Replays cannot see the GPU** [V].
  - **The sweep:** `scenario.py`'s sweep records a problem for a replay
    whose output has the start line, since the 23 pinned hashes are the CPU
    renderer's.
  - **The environment:** a test shows `replay_once` hands the port none of
    the caller's `SOA_GPU*` and `SOA_SETTINGS=0`.
  - **The mutations:** dropping the check, and passing `SOA_*` through, each
    turn their test red.
- **A build without the backend says so** [V]. With glslang set aside,
  `--link` prints `GPU backend: not built in`, and `SOA_GPU=vulkan` gives
  `[gxv] fallback: this build has no GPU backend: run python
  tools/fetch_gpu.py, then python tools/recompile.py --link; the CPU draws`.
- **The contract holds with `SOA_GPU` unset** [V]:
  - `replay` 23/23 at 1, 2, 3 and 8 threads;
  - the self test, 0 failures;
  - `title --check`, 4 of 4, with no `[gxv]` line;
  - `decomp.py`;
  - `test_memguard.py` and `test_mods.py`. Its boot-path build now links
    `gxv.c` as the stub and stubs `gxr_enabled`, which `main.c` asks before
    starting the GPU. `test_profiler.py` builds `main.c` the same way and
    needed the same; the full suite, not the contract's list, caught it
    (nine tests, all MSVC-gated).
- **A tripwire fired in the title, open.**
  - **What fired:** `[gxv] draw 6425 is ztop with an alpha test that can
    reject: the GPU tests depth after the TEV, the CPU before`.
  - **What it means:** spec 3.4 relies on no `ztop` draw with a rejecting
    alpha test existing, and none does in the 67 captures. The game makes
    one in the title, outside them, where the GPU's order can keep depth
    the CPU's would write.
  - **What is not known yet:** whether any pixel differs. The next step is a
    capture of that frame, into a scratch directory, replayed both ways.
    The line now names the draw, and `SOA_GPU_DRAW=6425` describes it.
- **Less noise.** The per-copy `copy to texture at ...` line stops after
  eight; the report counts the rest. A live run made 152.
- **Tests:** `test_gxv_live.py` (10); `test_scenario.py`,
  two more (the sweep refuses a GPU replay, and a replay cannot see
  `SOA_GPU`).

**V5, after: the ztop tripwire, and comparing a running game.** 2026-10-03.

- **The tripwire is answered: no pixel moves.**
  - **Where it fires:** the line now gives the screen copies before it,
    which is the frame. It is frame 1300 of the title run, and every drawn
    frame from 1290.
  - **The draw** (`SOA_GPU_DRAW=6425`) is a full-screen strip of 4 vertices
    at depth 0.99999: black, vertex alpha 1.0, no texture, blended source
    over destination, depth LEQUAL with writes on.
  - **Why it can't differ here:** its alpha test can reject only because
    its alpha comes from the vertex colour. At alpha 1.0 it passes
    everywhere, so the order of the depth test makes no difference.
  - **The evidence** [V]: every frame from 1290 to 1400 drawn on both
    renderers, seeded, passes V0 CPU against GPU, 111 of 111.
  - **What stays:** the tripwire, since a fade at partial alpha elsewhere
    would be the case it guards.
- **A running game is not reproducible, and that nearly made a false
  defect.**
  - **The first comparison:** the title run on each renderer, snapshots every
    50 frames, gave 7 of 40 frames failing V0, three of them wholesale.
  - **What they showed:** frames 900-1050, the opening's flight through
    cloud, had the clouds somewhere else entirely.
  - **The CPU against itself:** two CPU runs of frames 880-960, every frame
    drawn, differed in all 81, failing V0 too. The game reseeds from the
    clock.
  - **With the seed pinned** (`SOA_SEED=12345`): two CPU runs are identical
    in all 81 frames, and the GPU's 81 all pass V0 against them.
  - **Still not enough:** with snapshots every 50 frames even two seeded CPU
    runs differ. Frame 450 is off by 7 in every pixel, a fade caught at
    another moment.
  - **The cause:** guest time is the host's monotonic time (M19). Much of
    the game is timed by it (34,261 `OSGetTick` reads in one run), and an
    undrawn frame runs at whatever pace the host manages. Of 40 snapshots,
    18 come out alike in two CPU runs; with every frame drawn, 81 of 81 did.
- **`gpuspike.py live <scenario> [--range A-B]`.** It runs the scenario
  three times through `scenario.py`: on the CPU twice and with
  `SOA_GPU=vulkan` once, all with `SOA_SEED`. It then holds each GPU
  snapshot to the CPU's by V0, judging only the frames the two CPU runs make
  byte for byte alike and counting the rest as not judged.
  - **Results** [V]:

    | Run | Reproduced on the CPU | GPU frames passing V0 |
    |---|---|---|
    | `live title` | 18 of 40 | 18 |
    | `live title --range 1290-1330` (before the guard) | -- | 41 of 41 |
    | the 880-960 and 1290-1400 runs above, every frame drawn | all | all 81 and all 111 |

  - **The mutation:** `--mutate nofilter`, soa.exe's screen copy
    unfiltered, fails all 11 frames of 1290-1300.
  - **Which mode to use:** `--range`, every frame drawn, is the mode that
    reproduces. A frame-locked guest clock would make every frame
    judgeable, but it touches every device that reads guest time (DVD, DSP,
    ARAM, the VI fields, audio), and it is not this slice's to build.
- **Tests:** one, GPU-free. Identical snapshots pass, a frame painted over
  fails, only the reproduced frames are judged, and a missing frame or an
  empty folder is a problem.

**V6a: the GPU on a thread of its own.** 2026-10-03. With `SOA_GPU=vulkan`
the backend is now the render queue's one consumer, on its own thread (3.7):
`[gxr] the vulkan backend draws every command, on a thread of its own`. The
producer, which is the game's thread, publishes each command and goes on.

- **How it is built.**
  - **The flag:** `GxrBackend` gains `own_thread`, which gxv sets.
  - **One worker:** `workers_start` starts a single worker for such a
    backend, and its loop calls the backend where a CPU worker calls
    `draw_command`. That is `run_backend`, shared with the inline path; it
    counts what the backend was sent and the frames it presented.
  - **The queue's machinery is unchanged:** `g_ran[1]`, `drain`,
    `wait_ran`, the H11 sleep and `SOA_GXR_STALL` all keep their meaning.
  - **`finish` is the producer's only** for an inline backend. gxv's copies
    finish before the consumer counts them, which is 3.7's rule.
  - **`reset_efb`** follows a drain, so the consumer is idle when the
    producer calls it.
  - **V5's path stays:** `SOA_GXR_INLINE=1` keeps the backend on the
    producer. The passthrough and test backends leave the flag 0 and stay
    inline.
- **Nothing drawn changed** [V].
  - **The spike's checks:** every one passes on the thread, with the
    oracle's 67 GPU images byte-identical to V5's.
  - **The contrast:** spike against `soa.exe`, 67 of 67 the same pixels.
  - **The contract:** `replay` 23/23 at 1, 2, 3 and 8 threads, and the self
    test.
  - **One effect checked rather than assumed:** with a worker present, the
    producer now gives copies to a texture CPU copy images, which inline V5
    never did, and gxv fills them. The unchanged images cover it.
- **The live run.** `title --check --env SOA_GPU=vulkan` passes 5 of 5 in
  70 s. Submissions fell from 4,156 to 2,153, the producer no longer
  submitting at every drain.
- **The budget, `partl`** (new: H1's Part L run, a copy of
  `card-partL.raw` by `--env SOA_CARD=`). The `[gxv]` report now gives each
  frame's consumer and GPU milliseconds, p50, p95 and p99, each screen copy
  ending a frame.
  - **The first runs:** the consumer's p99 was 7.8 ms against its 5 ms
    limit.
  - **The profile** (`SOA_HOSTPROF`): the consumer thread idle 78% of the
    time and waiting for the GPU 10%. Of its own work, `gxv_pack_tev` came
    first, 3.6% of samples.
  - **The cause:** `draw_record` built each record in mapped, uncached device
    memory, where every `|=` is a read across the bus. Built locally and
    copied out once, it gives the same bytes: the oracle's images are
    unchanged.
  - **Since the fix**, six runs of 3,000 frames:

    | | p99, each run (ms) | The limit | Met |
    |---|---|---|---|
    | consumer | 3.69, 3.76, 4.36, 3.51, 3.31, 3.46 | 5 | every run |
    | GPU | 6.93, 6.82, 9.79, 7.02, 6.74, 6.72 | 8 | five of six |

    - **The one GPU run over** had a lower median (2.25 ms against 2.7 to
      2.8), which looks like the GPU's own clocks. The median p99 is 6.9 ms.
- **Against the CPU renderer**, measured interleaved, not a gate. Part L,
  3,000 frames, every frame drawn, two runs each:

  | Renderer | Frames a second | Process CPU | Cores |
  |---|---|---|---|
  | CPU | 28.9 | 487-507 s | 4.7-4.9 |
  | GPU | 28.9 | 114-117 s | 1.1 |

  - **Every run loaded `a126a`.** Both renderers hold the game's 30 fps
    cap; the GPU takes 4.3 times less CPU, the figure that matters on a
    handheld's battery and a Deck's four cores.
- **`gpuspike.py queue` and `test_gxv_queue.py`.**
  - **The frame:** the spike driver's `--queue 1` draws one synthetic frame
    through the real parser and producer. It has 64 quads, each drawn after
    the one texture's bytes were rewritten and invalidated: one cache slot,
    a new generation each, all in one GPU submission. Then 656,000
    vertices, in draws kept under the parser's 64 KB pipe buffer, fill the
    producer's 48 MB arena twice.
  - **The result** [V]: on the GPU, three times on the thread, once inline
    and once stalled 2 ms before every draw, the frame is the CPU's to the
    hash (`dd8b42488c9a0d3c`), all 64 quads right and the arena drained
    twice.
  - **pool-in-place** (gxv rewriting a slot's allocation under recorded
    draws) leaves 1 quad of 64 right.
  - **count-early** is a variant build, `GXR_MUTATE_COUNT_EARLY`: the
    consumer counts a command before running it. Stalled, it crashes. The
    producer drains, frees the textures and ends the frame while the
    consumer still needs them, which is the hazard 3.7's rule exists for.
  - **Both fail the test**; the three tests skip nothing here.

**V6b: the copy hazards with the GPU as the consumer.** 2026-10-03.

- **`gpuspike.py overlap`** runs `tools/citest/queue_check.py`'s overlap
  stream with the GPU backend as the queue's consumer. The stream has
  textures, a palette and indexed vertex colours read from copy
  destinations, a copy written twice, tokens, GXDrawDone and a hook's poke.
  - **The build:** the same driver, built with `OVERLAP_GPU`, `gxv.c` and
    `plat.c`. CI's builds of it never define that.
  - **The runs:** unstalled; the consumer stalled before its draws (300
    µs), copies or clears (20 ms); and `SOA_GXR_TOKENWAIT=1`, with and
    without a stall.
- **The oracle is the GPU's own synchronous run, not the CPU's.**
  - **The spec named the CPU:** V6b's Done holds the GPU runs to the
    one-worker CPU run.
  - **What the first run showed** [V]: three of the seven final hashes
    differ from the CPU's, the drawdone reads, the screen and the texture
    decodes. They differ identically on the GPU's thread, inline (V5's
    path) and under every stall.
  - **The size:** dumping the copy destinations, 16 to 365 bytes a copy
    differ, at isolated pixels, by up to 227. The pixels sit where
    textured quads drawn at half their texture's size put pixel centres on
    texel boundaries. There a coordinate's last bit picks the texel: 3.4's
    sampling difference, by design.
  - **So the oracle is** `SOA_GXR_INLINE=1`, where no command can overlap
    another. The three copies no textured draw touches are held to the CPU's
    byte for byte, and are equal.
- **Results** [V]:
  - **Pass:** all six GPU runs give all seven hashes of the synchronous
    run.
  - **The mutation:** `--mutate late-readback` makes gxv put a copy's bytes
    in guest RAM only at the next command, after the consumer has counted
    it. The drawdone reads, the screen and the decodes then differ.
  - **The tests:** `test_gxr_overlap.py` gains both.
- **Live, on the GPU's thread:**
  `title --check` and `battle --check` with `--env SOA_GPU=vulkan` each
  hold 5 of 5 [V]. The battle drew 272,415 draws, 12,000 screen copies and
  9,113 copies to a texture, every one as the renderer sent it, at 29.6
  frames a second (its snapshot frames: consumer p99 1.8 ms, GPU p99
  0.9 ms). As in V5, the check holds the GPU's counts to what the
  renderer sent, not to the `[gx]` report's, which V6b's Done still
  names.
- **The owner's look**, fifteen minutes windowed from a part-select save, is
  this slice's last Done line, and waits for the owner.

**V7, first: the pipeline cache on disk.** 2026-10-03.

- **What it does.** Every pipeline gxv makes, graphics and compute, goes
  through one `VkPipelineCache`.
  - **Loaded at start** from `SOA_GPU_PIPELINES`, by default
    `build/gxv-pipelines.bin`; `off` turns it off.
  - **Written back** by the consumer thread at the end of a frame that made
    new pipelines, at most once a second, and at shutdown. It is written
    beside the old file and renamed over it, so a killed run leaves the old
    file intact.
  - **Another device's data:** the driver checks the file's header and
    ignores data from another device.
- **What the report says now.** `[gxv] pipelines:` gives how many were made,
  how many the cache already had, the longest creation, the total, and the
  frame each of the first 48 was made in.
  - **How it knows a hit:** with `VK_EXT_pipeline_creation_feedback`,
    enabled where the device has it, each creation says whether the cache
    supplied it. gxv asks for Vulkan 1.1, so the extension is used, not the
    structure that is core in 1.3.
- **Measured** [V]:

  | Run | Pipelines | From the cache | Longest | All |
  |---|---|---|---|---|
  | capture 6000, first | 20 | 1 | 0.35 ms | 2.6 ms |
  | capture 6000, second | 20 | 20 | 0.35 ms | 2.3 ms (464,220 bytes loaded) |
  | `partl`, first | 32 | 1 | 1.03 ms | 6.5 ms |
  | `partl`, second | 32 | 32 | 0.41 ms | 4.7 ms |

  - **Where they are made:** across the run, frames 1 to 2,738, as each new
    state is first drawn.
  - **Why it is fast even uncached:** AMD's driver keeps a shader cache of
    its own, so creation is short here either way. The file is for drivers
    that do not, phones and the Deck among them.
- **The test** (`test_gxv_queue.py`): the queue frame run twice against one
  cache file. The second run finds every pipeline the first made. A file of
  junk gives back none, so the count is not one the driver always reports.
- **Unchanged pictures:** the self test passes, and the contrast gives 23 of
  23 the same pixels.
- **A noise fix:** the spike's `--replay` no longer prints gxv's report
  twice. `gx_replay`'s own report has printed it, through the backend's
  hook, since V5.

**V7, second: pipelines specialised on the TEV's shape.** 2026-10-04.

- **What it does.** A draw's pipeline is specialised on its TEV's *shape*
  (spec 3.4), passed to the shader as Vulkan specialization constants. The
  driver then folds the interpreter loop into a shader for that one shape.
  - **The shape:** the stage count; the alpha compares and their logic; and
    each stage's words 0 to 3 from `gxv_pack_tev`. Those words hold the
    colour and alpha inputs, the texture map, coordinate and channel, bias,
    operation, clamp, shift and destination, and the swaps.
  - **The values stay in the draw's record:** the registers, the alpha
    references, and each stage's konst word.
  - **`tev.glsl`:** 67 constants (`SC_ON`, `SC_STAGES`, `SC_ACMP` and 64
    stage words). A stage's word is read through a switch, because glslang
    builds no array from specialization constants.
  - **`SC_ON` 0, the default, keeps the interpreter as it was:** the shader
    reads everything from the record. tevdiff runs that way.
  - **The pipeline's key:** the fixed-function state, as before, plus the
    shape. The shape is compared whole, never by a hash.
- **Made off the draw path.** A cold specialised pipeline took up to 144 ms
  to make here (the first run after the shader changed: 62 pipelines, 3.36 s
  in all). On the draw path that is a stall at every new shape.
  - **By default (`SOA_GPU_SPECIALIZE=1`)** the draw path queues each new
    pair of state and shape for a compiler thread, and draws with the
    interpreter's pipeline for that state meanwhile. The two give the same
    pixels, so the switch cannot be seen.
  - **Publishing:** the thread writes the pipeline, then sets the slot's
    `ready` with a compare-exchange. The draw path loads `ready` before it
    reads the pipeline.
  - **The other modes:** `SOA_GPU_SPECIALIZE=wait` makes them on the draw
    path, so every draw is drawn specialised (the checks' way to see them);
    `0` uses the interpreter alone.
  - **The thread:**
    - its queue is a ring of 256 jobs, one producer and one consumer;
    - it sleeps in `plat_wait64`;
    - at shutdown it finishes the pipeline it is making and stops;
    - a creation that fails leaves that state on the interpreter.
    - not yet seen by Vulkan's validation layer, which is not installed
      here (`SOA_GPU_VALIDATE=1` says so). The pipeline cache is the
      driver's to synchronise, and the thread touches only its own
      slots' `pipe` and `ready`.
  - **`say`** now formats its line and writes it in one call, because the
    thread writes too.
- **The report** has three lines:
  - `pipelines: 32 made on the draw path, ...`: the stalls that count;
  - `pipelines specialised on the TEV's shape: 62 for 17 distinct shapes,
    3.6 a shape; made on the compiler thread`;
  - `the compiler thread: 62 made, ...; 0 failed, 0 still to make; 380
    draws drawn by the interpreter while theirs was made`.
- **The same pixels** [V]:
  - **`gpuspike.py specdiff` (new):** each of the 67 captures (corpus,
    perfset and gpuset) is replayed twice, every draw specialised (`wait`)
    and the interpreter alone (`0`). All 67 are byte-identical, with 808
    specialised pipelines for 399 shapes summed over the captures.
  - **Its mutation:** `--mutate spec-stages` cuts a stage from the
    specialised shape. It fails 8 captures, perfset's battle, field, ship
    and sky pairs. The corpus's 23 have no draw of two stages for it to
    cut.
  - **The oracle under `wait`, `0` and `1`:** 65 of 67 pass V0 (2 by
    design), and the 67 GPU images are byte-identical to V6a's in all three.
  - **The contrast (the V7 Done line):** 67 of 67 the same pixels, spike and
    `soa.exe`, under all three modes. Under `wait`, `--mutate spec-stages`
    fails perfset's 8.
  - **Also unchanged:**
    - the self test and tevdiff pass;
    - the queue frame hashes to the CPU's;
    - with background specialisation, `live title --range 1290-1400` passes
      111 of 111 and `880-960` 81 of 81.
- **The draw path does not wait** [V]. A test knob,
  `SOA_GPU_COMPILE_STALL=200`, makes the thread sleep 200 ms before each
  pipeline, as on a driver with no shader cache of its own.
  - **With it:** the queue frame's 228 draws are all drawn by the
    interpreter, its hash is unchanged, and the consumer's frame takes
    11.8 ms.
  - **Its mutation:** `--mutate compile-wait` makes the draw path wait for
    the thread. That takes the consumer above 200 ms and fails the test.
- **Measured on `partl`, interleaved** [V]:

  | Run | Consumer ms, p50 / p99 | GPU ms, p50 / p99 |
  |---|---|---|
  | interpreted | 0.92 / 3.64 | 2.76 / 6.84 |
  | specialised in the background | 0.94 / 3.51 | 0.77 / 2.56 |
  | interpreted | 0.92 / 3.43 | 2.75 / 6.78 |
  | specialised in the background | 0.96 / 3.73 | 0.77 / 2.53 |

  - **GPU time:** 3.6 times less at the median, 2.7 times less at p99.
    Specialised on the draw path (`wait`), warm, it was p50 0.77 and p99
    2.26, so drawing the first frames of each shape with the interpreter
    costs almost nothing.
  - **The consumer:** about 3% more at the median, for the shape built and
    looked up at each draw. Its p99 is within the spread of the runs.
    - A first version packed the TEV twice a draw, once for the record and
      once for the shape, and cost about 4%. The shape is now taken from
      the record's words.
  - **The pipelines:** 62 specialised for 17 shapes, 3.6 a shape. That is
    under V7's limit of four a shape, so values are not keyed.
    - The interpreter's 32, one for each fixed-function state, come on top:
      94 in all, 5.5 a shape.
    - The limit is read as the specialised count, which is what it was set
      to test. This reading is recorded in the spec.
- **A first launch can still stall** [V]. In the first background run, the
  interpreter's new SPIR-V had been compiled for none of `partl`'s states.
  - **The draw path's longest creation was 37.50 ms,** and 163.8 ms over
    32. That is the interpreter's pipelines compiling with AMD's own shader
    cache cold. Repeated, the longest was 0.34 ms.
  - **The specialised pipelines in that run** were already in AMD's cache
    from earlier runs: the longest on the thread was 1.22 ms.
  - **Why no thread can fix it:** something has to draw while a pipeline
    is made, and the interpreter's pipeline is that something.
  - **Not new:** this was true before V7 and is measured here for the first
    time.
  - **What it means for the soak:** its 20 ms limit will see this on a first
    launch. Two ways to meet it go with the soak:
    - fewer interpreter pipelines, through dynamic state (cull, depth and
      topology are core in Vulkan 1.3);
    - making them at start, from the states of the last run.
- **The live check in snapshot mode** [V]. One `live title` run with
  background specialisation failed 16 of 40 frames by shift and blur: a
  fade caught at another moment.
  - **The repeats:** its rerun passed (18 of 18), and interpreted and
    `wait` passed 40 of 40.
  - **Why:** the guard judges only frames that two CPU runs agree on, but
    nothing holds the GPU run to the same moment. This is V5's finding that
    `--range` is the mode that reproduces.
  - **The every-frame ranges pass** with background specialisation (above).
    No test runs snapshot mode.
- **Tests:**
  - `test_gxv_queue.py` gains two (4 to 6). The compiler thread accounts
    for every specialised pipeline; a frame with every compile stalled is
    unchanged and its consumer stays under the stall; `compile-wait` fails
    that; `wait` and `0` report as they should.
  - `test_gpuspike.py` gains two (34 to 36): specdiff over the 35 captures
    of the corpus and benchmark set, and its `spec-stages` mutation.

**V7, third: copy images on the GPU, and copies landing late.** 2026-10-04.

- **What changed.** Until now gxv waited for the GPU at every copy to a
  texture. It read the copy back, put it in guest RAM, filled the
  producer's copy image, and only then counted the copy (V6's protocol).
  Now a copy is counted as soon as it is recorded, and lands later.
- **The copy, in gxv:**
  - **Recorded into regions of its own:** its bytes in the copy buffer,
    seeded from guest RAM as before, and its decoded image in the image
    buffer and in the texel pool. `copy.comp` takes the regions' offsets
    and, with flag 8, writes the image into the pool too.
  - **Lands when its submission is done** (`land_all`, at the end of every
    submission): its bytes go into guest RAM, its image into the producer's
    copy image, and gxr is told.
  - **Lands early in two cases:** when a copy still to land overlaps its
    bytes, whose seed must hold what that copy wrote, or when the regions
    are full.
- **The draw that samples it.** A draw later in the same submission that
  samples the copy's image samples the pool's.
  - `upload_texture` finds it by the producer's image pointer, which the
    draw's `TexCfg` carries with `copy_image` set.
  - From an earlier submission the producer's image has landed, and it is
    uploaded as any texture is.
  - So the CPU's copy images (H14 step 6) now have their GPU half. The spec
    named `gxr_tev.c` for this; it needed no change.
- **The landed count, in gxr.**
  - **Two new backend fields:** `lands_late`, and an `idle` hook, which the
    consumer calls before it sleeps.
  - **The count:** `g_landed`, raised by `gxr_backend_landed`.
  - **Rule 5 of the queue's ordering (portability 3.4):** the backend writes
    guest memory, then `plat_xchg64(&g_landed)`. The producer reads that
    memory only after `plat_load64(&g_landed)` is past the copy.
    `test_gxr_atomics.py` now checks `g_landed` too.
  - **Every wait for what a copy wrote also waits for its landing:**
    - the hazards: texture, palette, vertex sources and a hook;
    - a token, and whether the token may forget the pending copies;
    - every drain: the frame gate, `GXDrawDone` and a flush.
  - **The report:** time waited for a landing goes to its own reason,
    `landed`.
  - **What answers such a wait:** the consumer lands what it holds when it
    runs out of commands, which a waiting producer guarantees.
- **The report** gains a line: `copies to a texture: N, landed with the
  submissions they were in but for M readback waits of their own; K
  samplers served by a copy image from the pool`.
- **Measured on `partl`, interleaved,** against V6's protocol kept as a
  mutation (`land-at-copy`, a wait at every copy) [V]:

  | Run | Copies | Readback waits | Served from the pool | Consumer ms p50 / p99 | GPU ms p50 / p99 |
  |---|---|---|---|---|---|
  | landing late | 670 | 286 | 919 | 0.96 / 3.63 | 0.83 / 2.53 |
  | at the copy (V6) | 670 | 670 | 0 | 0.97 / 3.72 | 0.76 / 2.56 |
  | landing late | 670 | 281 | 951 | 0.95 / 3.39 | 0.76 / 2.38 |
  | at the copy (V6) | 670 | 670 | 0 | 0.95 / 3.37 | 0.77 / 2.45 |

  - **The waits that remain** are the consumer landing when it runs out of
    commands. That happens at a frame's end, when the frame's last copies
    come after its screen copy.
  - **The producer never waited for a landing:** there is no `landed` in
    `[gxr] waits`.
  - **The times do not move at this load.** At 30 fps the GPU is idle most
    of each frame, and a wait at a copy costs about the copy's own GPU time.
    What V7 removes is the round trip at each copy. On this machine that is
    too short to show, and the spec does not make it a gate.
- **The mask effect's 14 captures** each make two copies and serve three
  samplers from the pool, 42 in all [V].
- **Checks** [V]:
  - **`gpuspike.py copyimage` (new):** a frame draws sixteen cells, copies
    them to an RGBA8 texture, and samples the copy in the same frame. The
    CPU's and the GPU's frames are the same hash, all 16 cells are right,
    one sampler is served from the pool, and no readback wait is made.
    - The frame was looked at: the pattern at the top left, and its copy at
      (128, 128), cell for cell.
    - `--mutate cimg-cpu` (the producer's image sampled before it has
      landed) gives 0 of 16 and another hash.
    - `--mutate land-at-copy` gives one wait for one copy and nothing served.
  - **V6b's copy hazards with the GPU as consumer still hold:** `overlap`,
    6 runs of 7 hashes. `late-readback`, now telling gxr a copy has landed
    before its bytes reach RAM, still fails it.
  - **The pictures:** the oracle's 67 GPU images are byte-identical to
    V6a's, and the contrast gives 67 of 67.
  - **The other spike checks pass:** ramdiff, logicop, chain, copydiff,
    queue, selftest, tevdiff and loddiff.
  - **The CPU renderer:** `replay` 23/23 at 1, 2, 3 and 8 threads, and
    `queue_check.py`.
  - **Live runs:** `title` and `battle` 5 of 5 with `SOA_GPU=vulkan`, and
    `live title --range 1290-1400` 111 of 111.
- **Tests:** `test_gxv_copyimage.py` (new, 3): the frame, and each mutation
  red.
- **V6a's `count-early` had stopped failing, and is fixed.** It counts a
  command before running it. The queue frame's last drain now also waits
  for the screen copy's landing, which gxv reports only after it has run
  the copy, so the stalled frame came out right: 3 runs of 3. The
  mutation now reports the landing early too, which is what counting a
  command before it runs means once copies land late. It fails again: 0
  of 64 quads, 3 runs of 3. The full test run caught it.

**V7, fourth: the soak, and a first launch that still stalls.** 2026-10-04.

- **How it was run.** The spec asks for a soak from `soak.py --seed 7
  --warp <map>` crossing at least 20 map loads. Random play crosses about
  two a battle; part G's accelerated soak fought five in 33,500 frames. So
  this run takes the censuses' route instead:
  - **The run:** `partl` with `--frames 18400`, `SOA_GPU=vulkan`, a fresh
    pipeline-cache file, and an `SOA_POKE` of 25 warps by name, one every
    600 frames from 3300.
  - **The maps:** those the first census found drawing a full scene.
  - **It took** 10 min 25 s.
  - **The second launch:** the same run against the same cache file.
- **New, to judge it.** gxv logs a line for each pipeline it makes:
  `pipeline made on the draw path at frame F in X ms`, or `... on the
  compiler thread ...`. `soak.py check` counts them against the field map
  loads around them, and prints each side's count, longest, and how many
  came after the landing map loaded, then the map loads. Its test is
  `test_soak.py`'s new one.
- **Measured** [V]:

  | Launch | Field map loads | Draw path: made, longest, after landing | Compiler thread: made, longest, after landing | From the cache | Consumer ms p99 |
  |---|---|---|---|---|---|
  | first | 27 | 42, **30.10 ms**, 12 | 123, 161.64 ms, 74 | 1 of 42 | 5.93 |
  | second | 27 | 42, 0.26 ms, 12 | 123, 0.29 ms, 74 | 42 of 42 and 123 of 123 | 5.60 |

- **The verdict on V7's budget:** met on the second launch, not on the
  first.
  - **Four creations broke the 20 ms limit on the first launch:** 30.10 ms
    at frame 3367 (the first warp), then 27.36, 26.93 and 26.12 ms at
    frames 17751-17779 (`a260a`).
  - **What they were:** each is the interpreter's pipeline for a
    fixed-function state the driver had not compiled since the interpreter's
    SPIR-V changed. The other 38 took about 0.3 ms, from AMD's own shader
    cache.
  - **Why the thread cannot take them:** the specialised pipelines' cost is
    already off the draw path (161 ms at the most), but something has to
    draw while a pipeline is made.
- **Values are still not keyed,** but the ratio grows with the maps: 123
  specialised pipelines for 25 shapes across 27 maps is 4.9 a shape. The
  spec's limit of four was set for `partl` alone, where it is 3.6. The
  states a shape is drawn with multiply with the maps.
- **Tried and backed out: pipeline libraries**
  (`VK_EXT_graphics_pipeline_library`, which this device has, with fast
  linking).
  - **The design:** the interpreter's parts made once on the compiler thread
    at the first draw (vertex input by topology, the vertex stage by cull,
    the fragment stage by depth state: 27 libraries). Each new state then
    costs a fragment output and a fast link, and compiles nothing.
  - **What happened on driver 0x800184:** enabling the extension makes
    ordinary pipelines draw nothing or lose the device. The self test's
    first full-screen quad drew 0 of 307,200 red. This happens even with
    the feature left off and no library used, while
    `VK_KHR_pipeline_library` alone is fine, as is everything with
    `SOA_GPU_GPL=0`.
  - **Not explained:** this machine has no validation layer to say whether
    the fault is this code or the driver.
  - **The ways on:**
    - the validation layer (the Vulkan SDK), to find which;
    - dynamic state (`VK_EXT_extended_dynamic_state`), for fewer
      interpreter pipelines;
    - making the last run's states at start, which helps only the launches
      the disk cache already serves.

**V8, first: the GPU presents to the window.** 2026-10-04.

- **What it does.** With `SOA_GPU=vulkan` and a window, the picture no
  longer goes through the CPU on its way to the screen.
  - The window's thread presents the newest screen copy from the GPU through
    a Vulkan swap chain on the window, in place of DXGI.
  - `present.frag` is `picture_scale` as a shader: the rectangle
    `picture_layout` chose, nearest neighbour by the same integer arithmetic,
    black outside it.
  - Each frame is presented `g_interval` times in FIFO order, a refresh each.
    That is what DXGI's sync interval did (H8).
  - `SOA_PRESENTER=dxgi` or `gdi` keeps the CPU presenter. So do P5a's
    picture filters, until V8b makes them shaders, and the window says so.
- **How the two threads share it:**
  - **The screen buffer** now holds three slots and a scratch region. The
    consumer writes one slot and publishes it. The presenter takes the newest
    by swapping its own slot in, so neither thread writes or reads a slot the
    other holds. The presenter keeps a slot until its own fence says the GPU
    has read it.
  - **The one Vulkan queue** is shared under a new `plat_lock`, a spinning
    lock held only around a submit or a present.
  - **The readback into `g_screen` is unchanged,** so `SOA_HASH`,
    snapshots, PNGs and the frame hook see what they saw.
- **A fix the first windowed run found:** `main.c` started the window before
  the GPU, so the window's thread saw no GPU and opened DXGI, without saying
  so. The GPU now starts first.
- **The check** [V]: `gpuspike.py present` (new). Two synthetic screen
  copies, 640x480 and 640x448, every pixel its own colour, go through the
  presenter's own pass into an offscreen image.
  - **Eight targets at both layouts:** 1x to 4x, 16:9, 21:9, odd sizes, and
    one smaller than the picture.
  - **The result:** 32 of 32 equal `picture_scale`'s picture in every pixel's
    colour.
  - **The mutation** (`present`, one column over) leaves 0 of 32.
- **The window** [V], `scenario.py run window --env SOA_GPU=vulkan`, on this
  machine's 85 Hz display:

  | Presenter | Frames | 1 / 2 / 3 / 4+ refreshes | Interval p50 / p99 | A present's own work p50 / p99 |
  |---|---|---|---|---|
  | DXGI (the CPU's copy) | 7,491 | 62 / 373 / 6,034 / 1,022 | 31.7 / 48.6 ms | 2.91 / 3.88 ms |
  | Vulkan (the GPU's) | 7,493 | 55 / 343 / 6,125 / 970 | 31.6 / 48.4 ms | 0.74 / 1.49 ms |

  - **The same pacing:** at 85 Hz no presenter can hold a 30-a-second frame
    evenly, which H8 found.
  - **A quarter of the work,** since the CPU no longer converts and scales
    each frame.
  - **No failed present** in any run.
  - **Window changes:** with `SOA_WINDOW_TEST=fs@300,win@600,size:1000x700@900`,
    fullscreen on the 3440x1440 monitor, back to the window and a
    1000x700 client each remade the swap chain (5 in all), with no failed
    present. The longest present then was 48 ms, the remake's wait for the
    queue.
  - **Looked at:** a screenshot of the window, mid-run, shows the opening's
    narration at 2x, crisp and placed as the CPU presenter places it.
- **Unchanged:** contrast 67/67, `replay` 23/23, `title` 5/5 on the GPU,
  the self tests, and the copy checks: `copydiff`, `queue`, `overlap`,
  `copyimage`.
- **What V8 still owes:**
  - **V8b:** P5a's filters as shaders, each held to its CPU function within
    1 a channel.
  - **M8's overlay,** when M8 lands.
  - **The pacing target and the owner's windowed session** at 60 or 120 Hz.
    The display here is set to 85.

**V10: logic ops without `logicOp`.** 2026-10-04.

- **What it does.** Where the device lacks `logicOp`, as many phone GPUs
  do, each logic draw is now routed on its own (`logic_route`):
  - **a snapshot** for a draw of one quad, which cannot overlap itself;
    every logic draw in this game is one (3.5);
  - **the interlock** for a draw that may overlap itself and tests no
    depth, where the device has `VK_EXT_fragment_shader_interlock`;
  - **otherwise** blend for OR and AND, a snapshot for the rest, each said
    once by draw, since neither is exact where the draw overlaps itself.
    Never a blend for an op the blend cannot draw: that is refused, as
    before.
  - **`SOA_GPU_LOGICOP`** forces any route for testing, `interlock` among
    them.
- **The interlock route:**
  - **the shader:** `raster.frag` built with `GXV_LOGIC_INTERLOCK` reads
    and writes the EFB pixel as a storage image inside
    `beginInvocationInterlockARB`, applying the write masks itself;
  - **the pass:** the EFB goes into GENERAL for one draw, in a pass of no
    attachments, and back;
  - **what the device must allow:** the EFB image has storage usage, and
    `fragmentStoresAndAtomics` and pixel interlock are enabled where the
    device has them.
  - **No depth:** the route is taken only with the depth test off, because
    the shader writes depth, so the hardware tests it after the store.
- **`SOA_GPU_FEATURES`** (3.10), now implemented:
  - `core` treats every optional feature as absent: `logicOp`, the
    interlock, the creation feedback;
  - `nologicop` drops `logicOp` alone, which is how the routing to the
    interlock is tried on this GPU, which has both.
  - **The start line now names** the interlock and the mode, and the
    report counts each route.
- **Measured** [V]:
  - **`gpuspike.py logicop`** now covers 16 captures, the mask effect's 14
    and V1's two that draw logic ops (`battle_4421`, `mask_3200`). Native,
    blend, snapshot and the forced interlock give byte-identical frames on
    all 16, and `--mutate or-and` makes every capture's paths differ.
  - **`gpuspike.py oracle --set corpus,perfset,gpuset --features core`:**
    the same verdicts as the default (65 of 67, 2 by design), and the 67
    GPU images byte-identical to the base. Its logic draws went through
    the snapshot (`3 from a snapshot`).
  - **`gpuspike.py logictest` (new),** depth off throughout:

    | Scene | CPU | native | snapshot | blend | interlock | `nologicop` | `core` |
    |---|---|---|---|---|---|---|---|
    | 0x55 ORed into 0xAA, one quad | 255 | 255 | 255 | **198** | 255 | 255 (snapshot) | 255 (snapshot) |
    | two triangles XORed, the overlap | 0 | 0 | **240** | refused | 0 | 0 (interlock) | **240** (snapshot, named) |

    - **The interlock's frame** is native's, hash for hash. The CPU's
      differs at triangle edges, which is by design between the two
      renderers.
    - **What the forced snapshot shows:** its 240 is what a route that
      reads the EFB from before the draw gives an overlapping draw. So the
      check would fail on a wrong route.
- **Unchanged:**
  - the oracle's 67 images, the contrast 67/67 and `replay` 23/23;
  - `title` 5/5 on the GPU and the self tests;
  - the spike's checks: `queue`, `overlap`, `copyimage`, `present`.
- **Tests:**
  - `test_gxv_logicop.py` (new, 1): the two scenes through every route.
  - `test_gpuspike.py`'s logic-op test now holds the 16 captures to every
    path.
- **What V10 does not do:** framebuffer fetch with rasterization-order
  access, the spec's next choice after the interlock. This GPU has no such
  extension to try it on, so a device with neither interlock nor
  `logicOp` takes the snapshot, with its line.

**V7, fifth: cull, topology and depth as dynamic state.** 2026-10-04.

- **What the cold soak showed** [V].
  - **The run:** V10 changed `raster.frag`, so AMD's own cache was cold
    again for the interpreter's pipelines: a first launch. The soak of "V7,
    fourth", with the state key on each draw-path creation's line, made 42
    pipelines on the draw path; 7 took 27-40 ms.
  - **What the 7 were:** none brought a write mask or blend not already
    made. Each differed from a pipeline already made only in topology, cull
    or depth state, which the driver compiles a pipeline for.
- **What changed.** Where the device has `VK_EXT_extended_dynamic_state`
  (core in Vulkan 1.3; the Deck's and flagship phones' drivers have it):
  - **Set by draw:** the cull mode, the topology within its class and the
    depth test, write and compare, with the last values kept so a repeat is
    not set again.
  - **The pipeline's key** keeps the topology's class, the write mask and
    the blend.
  - **Off switches:** `SOA_GPU_EDS=0`, or `SOA_GPU_FEATURES=core`, builds
    the state into the pipeline as before.
  - **The interlock route** sets depth off for its draw.
  - **The start line** says `dynamic state`.
- **The same soak again, cold for the new pipelines** [V]:

  | Soak | Draw path: made, stalls over 20 ms after landing | Compiler thread: made, a shape |
  |---|---|---|
  | state built in (`V7, fourth`'s method, cold) | 42, 5 (27-40 ms) | 123, 4.9 |
  | dynamic state, cold | 10, **1** (30.3 ms) | 38, 1.5 |

  - **Where the first launch's creations fall now:** 9 of the 10 are before
    the landing, at the first frames and the title (26-34 ms each, every one
    new to the driver).
  - **The one in play** is a blend not seen before, at frame 11,757.
  - **So the 20 ms limit still does not hold on a first launch,** by that
    one and the boot's. A second launch takes them from the disk cache, as
    "V7, fourth" showed.
  - **What would remove the last:** making the blend dynamic too
    (`VK_EXT_extended_dynamic_state3`), which phones have less often.
- **`partl`, interleaved, dynamic state on, off, on, off** [V]:

  | Run | Consumer ms p50 / p99 | GPU ms p50 / p99 | Pipelines on the draw path | Specialised |
  |---|---|---|---|---|
  | on | 0.96 / 3.62 | 0.85 / 2.85 | 9 | 24 for 17 shapes |
  | off | 0.97 / 3.28 | 0.81 / 2.46 | 32 | 62 for 17 shapes |
  | on | 0.93 / 3.12 | 0.76 / 2.34 | 9 | 24 for 17 shapes |
  | off | 0.93 / 3.25 | 0.77 / 2.32 | 32 | 62 for 17 shapes |

  - **The cost:** the calls that set the state cost nothing measurable.
  - **The pipelines:** a quarter as many on the draw path, and the
    specialised ones from 3.6 a shape to 1.4.
- **Unchanged:**
  - the oracle's 67 GPU images (and its verdicts), the contrast 67/67, and
    specdiff 67/67, now with 488 specialised pipelines summed over the
    captures, against 808;
  - logicop's 16 captures, logictest, queue, overlap, copyimage, present,
    tevdiff, loddiff, copydiff and the self tests;
  - `replay` 23/23, `title` 5/5 on the GPU, and `live title --range
    1290-1400`.

**V8b, first step: P5a's filters presented by the GPU.** 2026-10-04.

- **What it does.** With a picture filter set (`SOA_GAMMA`,
  `SOA_COLORBLIND`, `SOA_FLASH_LIMIT`), the window no longer falls back to
  DXGI.
  - It runs `picture_filter` on the CPU's copy of the frame, as it always
    has.
  - The GPU presents the result (`gxv_present_image`): a fifth slot in the
    screen buffer, written by the window's thread through `upload_bgra`
    once the presenter's last read of it is done, then the same present
    pass.
  - So the filters are their own reference, byte for byte.
- **Why not shaders yet.** The spec's V8 asks for the filters as shaders.
  - **Gamma and colour-blind** are per-pixel tables and would port
    directly.
  - **The flash limiter** keeps per-pixel history across frames, and its
    whole-frame search for how far to blend has no cheap exact GPU form.
  - **When it matters:** only once V9 renders above native size, where the
    CPU's copy is native and the picture is not. They wait for V9.
- **Checked** [V]:
  - **`gpuspike.py present`** now feeds the check through `upload_bgra`,
    so the BGRA-to-RGBA swizzle is checked too: 32 of 32 layouts, and the
    mutation 0 of 32.
  - **A windowed run** with `SOA_GAMMA=1.2` and `SOA_GPU=vulkan`: the
    window presents from the GPU, `picture_filter` ran on 1,494 frames,
    1,494 presents and none failed.
  - **The report** now counts the window's own images apart from the
    screen copies taken.
  - **Unchanged:** `title` 5/5 on the GPU, the spike's self test, `queue`
    and `copyimage`.

**The validation layer, installed: the GPU path is clean, and the pipeline-library failure is
the driver's.** 2026-10-04.

- **The owner's answers this day** (PLAN-NEXT §0):
  - the Vulkan SDK may be installed (`winget install KhronosGroup.VulkanSDK`, 1.4.363.0);
  - llvm-mingw may be fetched (distribution Q-D1);
  - V9 is split: 2x and 3x now, the wide EFB after M10;
  - the owner will set 60 or 120 Hz for the windowed sessions.
- **`SOA_GPU_VALIDATE=1` now prints the layer's messages.** It had
  switched the layer on, but with no debug messenger nothing it found
  reached the log.
  - gxv now enables `VK_EXT_debug_utils` with the layer, and each warning
    or error is a `[gxv] validation warning:` or `validation error:` line:
    the first 200, then a count, and a total at shutdown.
  - **Shown to work:** the layer's best-practice checks
    (`VK_KHRONOS_VALIDATION_ENABLES=VK_VALIDATION_FEATURE_ENABLE_BEST_PRACTICES_EXT`)
    put 8 warnings into a queue frame's log.
- **What it found in this code** [V], both fixed:
  - **A needless write:** the interlock variant of `raster.frag` (V10)
    wrote `o_color` in a pass with no colour attachment. It no longer
    declares it.
  - **A buffer never freed:** the presenter's check (V8) made its readback
    buffer and never destroyed it, so the device was destroyed with an
    object alive. The buffer is now freed with the presenter.
- **Then nothing** [V]. Every one of these ran with no validation message:
  - the 67 captures, poisoned where they copy;
  - the spike's self test, queue frame, copy image, presenter check and
    both logic scenes, the interlock forced;
  - `title` on the GPU, on its own thread;
  - a windowed run through the swap chain, with fullscreen, back to the
    window and a resize (5 swap chains).
- **The pipeline-library failure** ("V7, fourth"), repeated under the
  layer: `VK_EXT_graphics_pipeline_library` and its feature enabled on the
  device, never used.
  - **The result:** the self test's full-screen quad draws 0 of 307,200
    red, and the layer reports nothing.
  - **So the fault is the AMD driver's** (0x800184), not this code's
    use. The route stays closed on this driver.
  - **The last first-launch stall** in play ("V7, fifth") has other ways
    out: the blend as dynamic state (`VK_EXT_extended_dynamic_state3`), or
    the next driver.

**V9a: the EFB at two and three times the console's size.** 2026-10-04.

- **What it does.** `SOA_GPU_SCALE=2|3` (soa.ini `gpu_scale`) draws on the GPU into an EFB of
  S·640 × S·528 samples. The window shows that picture, sharper.
  - The scissors, clears, viewport and framebuffers are scaled; `raster.vert` is not changed.
  - Lines are S samples wide and points S samples square, through `wideLines` and `largePoints`.
- **The copies, one phase at a time.** A copy is the native copy run once per phase: native pixel
  (x, y) reads sample (S·x + jx, S·y + jy). So the filter's taps are S samples apart, and every
  native formula is unchanged.
  - **The native picture is one phase:** the centre at S = 3, the mean of four at S = 2. That
    covers the RAM bytes, the producer's copy image and `g_screen`.
  - **The pool's image holds every phase,** sampled by `raster.frag` with the game's texel
    coordinates times S. So the mask effect's copies are drawn at 3x too.
  - **The presenter's slot holds the screen at scale,** and the window averages each pixel's
    footprint where the picture shrinks (`picture_scale_area` is its C twin).
- **Mip levels follow the scale** (derivatives in the scaled pixel). `SOA_GPU_SCALE_LOD=native`
  picks native's levels instead, for the oracle.
- **Found while building** [V]: at one sample, lines and points vanish from the centre samples.
  - The 3x self test's lines missed 1,108 of the CPU's 2,400 pixels, and 13 of its 64 points
    were drawn.
  - At S samples across, every scene passes at 3x as it does at 1x.
- **Checked** [V]:
  - **Scale 1 is unchanged.**
    - The oracle's 67 GPU frames are byte for byte the ones drawn before V9a.
    - V5's contrast gives 67 of 67 captures the same pixels from the spike and `soa.exe`.
    - The oracle's verdict is as before (65 pass, the field pair by design), and the self test,
      `scenario.py replay` and `SOA_SELFTEST` pass.
  - **`copydiff --scale 3` and `--scale 2`,** on an EFB whose samples are alike within each pixel:
    - 25,600 copies, with ram 0, image 0 and screen 0 differences from the CPU;
    - the pool's image is the native one replicated in 13,458 of 13,458 copies, and the full screen
      `g_screen` replicated in 25,600 of 25,600.
    - **`--mutate taps`** (the filter's taps one sample apart): ram 3,708, image 3,708 and screen
      12,009 differences; the pool's image replicated in 9,750 of 13,458 copies.
  - **`copyimage --scale 2` and `--scale 3`:** 16 of 16 cells and the CPU's frame hash.
    `--mutate copy-scale` (the scaled image sampled as if native) gives 1 of 16.
  - **`present --scale 2` and `--scale 3`:** 32 of 32 layouts exact against
    `picture_scale_area`, and `--mutate present` gives 0 of 32. The C twin is held to its
    definition by exact fractions in `test_picture.py`, and two mutations fail that.
  - **`oracle --scale 3`,** all 67 captures, each frame's centre samples, native mip levels:
    - 65 pass V0, the mask capture `mask_3200` among them;
    - `field_5000` and `field_5001` fail as at scale 1, the by-design pair: blob 156 against 1x's
      172, largest 58 against 59. `field_5000`'s 3x frame against the GPU's own 1x frame passes V0.
    - The centre samples equal `g_screen` exactly on all 67.
    - **`--mutate phase`** (`g_screen` taken from the first sample, not the centre) fails that on
      23 of 23 corpus captures, by 22 to 255, while V0 alone passes all 23.
  - **With mip levels for the scale,** as a player sees it: MAE 0.001 to 5.16 against the CPU's
    frame, largest on `battle_4000` and `battle_4001`, whose floor resolves a finer level.
  - **`oracle --scale 2`,** all 67, the box of each 2x2, native mip levels: MAE 0.027 to 1.652,
    bias within 0.651.
    - 64 pass V0's MAE and bias, and the oracle passes with the other three listed by design
      (`BY_DESIGN_SCALE2`, with the evidence below).
    - `4800` (MAE 1.652) and the ship pair (1.549) exceed V0's MAE limit of 1.5, and are listed by
      design. Averaging four samples is supersampling: it blends the text edges and fine texture
      that the CPU's single sample keeps, and lowers these frames' level (bias -0.62 on `4800`).
    - **Why that is the averaging, not the 2x path:** the 3x frame's box lowers it by the same
      (-0.57) and is within MAE 0.527 of the 2x box, while the 3x centre samples hold the CPU's
      level to 0.005.
    - The box is `g_screen` within one step on all 67.
    - Mip levels for the scale: MAE up to 4.417.
  - **Looked at:** the full-size 3x frames of `battle_4000`, `mask_3200` (the beam and Vyse) and
    `sky_4000`, and 2x's `4800`, each beside the CPU's 1x frame.
    - All are sharper, with smooth edges. The beam has no seam, and the minimap is right.
    - The dialogue text is a little softer at 2x: the font is a low-resolution texture, now filtered
      at finer positions.
  - **The game, live:** `gpuspike.py live title --range 1290-1400 --scale 3` passes. All 111
    reproducible frames pass V0 against the CPU's, and the GPU run holds 5 of 5 invariants at
    1920x1584 (GPU p50 1.71 ms, p99 5.88 ms).
  - **The cost** on this machine's GPU (the Ally X's Z1 Extreme), for one frame of each of the
    benchmark set's 12 captures (median of five, interleaved):
    - **Every pipeline specialised** (`SOA_GPU_SPECIALIZE=wait`, as a live run settles): 1x 1.48 to
      3.04 ms, 2x 5.61 to 9.88, 3x 10.87 to 17.34 (`field_5000`).
    - **So** 3x fits a 30 fps frame with half of it spare, and 2x fits even 60 fps.
    - **Cold**, with the interpreter drawing, 3x reached 37.40 ms on `field_5000`. A new scene's
      first moments at 3x may drop frames until its pipelines are made.
- **What it does not do yet:**
  - **A copy sampled after its own submission** reads the producer's native image. A copy made
    in one frame and drawn in the next is native-sharp, not scaled.
  - **P5a's filters** run on the native picture, so with one set the window shows the native
    picture, said once. Their shaders (V8b) are next.
  - **The 2x self test** fails on edges by design: the mean blends them (cull0-2, points).
  - **The presenter reads its slot from host-visible memory,** 12 MB a frame at 3x. That is shared
    memory on the Ally X, but would cross the bus on a discrete GPU.
- **Owner:** to judge 2x and 3x in a window (the Done's last line), at 60 or 120 Hz.

**V8b: P5a's filters drawn by the GPU, at the size it draws.** 2026-10-04.

- **What it does.** Gamma, colour-blind correction or simulation, and the flash limiter now apply to
  the picture the GPU drew: at 2x and 3x too, where V8b's first step showed the native picture.
  - **The pass.** `filters.comp` runs when the presenter takes a new screen copy. It reads the slot at
  the copy's own scale and writes `SCREEN_SHOWN`, which the present pass reads; a present of the same
  frame again (the interval, a resize) filters nothing.
  - **The arithmetic is the CPU's.** Colour-blind and gamma use `picture.c`'s own tables (`lin`, the
  65,536-step `enc`, `gam`) and matrix, unfused, so the GPU's bytes are `picture_filter`'s.
  - **The flash limiter's decision stays on the CPU.** Its history is a whole frame, and its search
  for how far to blend has no cheap exact GPU form. `window.c` runs `picture_filter` on the native
  picture only when `flash_limit` is set, for the blend it returns, and the pass blends the frame
  shown before toward the new one by those 256ths, rounded as `picture.c`'s `blend`.
  - **What went:** `gxv_present_image` and `SCREEN_HOST`, V8b's first step. Where the pass cannot be
  made, DXGI presents and the CPU filters, so the window never loses its filters.
- **Checked** [V]:
  - **`gpuspike.py present --filters`,** at scale 1 and at 3: 24 of 24 cases exact, every byte.
    - The cases: eight filter sets (two gammas, the three models corrected and simulated, with and
      without gamma), each into the picture's own size and into 1920x1080 fit; and two of them
      blended twice, half and a quarter of the way.
    - The reference: `picture_filter`, `picture_blend`, then `picture_scale` or
      `picture_scale_area`, on the CPU.
    - **`--mutate filter`** (one colour coefficient times 1.01) gives 12 of 24: every colour-blind
      set fails and the gamma-only sets pass.
  - **Live, windowed at 3x** with gamma 1.2, deutan corrected and the flash limiter, 1,500 frames:
    - 1,489 screen copies taken, and 1,489 frames through the GPU's filters;
    - 90 blended by the flash limiter, the 90 its CPU half held back in the opening's flashes
      (frames 902-942).
  - **Live at 2x** with protan corrected and gamma 0.8: 594 of 594 frames through the GPU's filters,
    0 blended, and the CPU filtering nothing.
  - **What a present costs the window's thread:** p50 0.62 ms without the flash limiter, and 4.14 ms
    with it, the CPU's decision costing what the first step's whole filtering did.
  - **Unchanged:**
    - `present` at scale 1, 2 and 3 (32 of 32);
    - V5's contrast (67 of 67 captures the same pixels from the spike and `soa.exe`);
    - `compile_runtime`, `dc_check` and `render_check` under MSVC and clang-cl.
- **V8's remainder:** M8's overlay, when M8 lands; H8's pacing, from a windowed run at 60 or 120 Hz;
  and the owner's session.

**R1: soa.exe built with no Microsoft compiler.** 2026-10-04.

- **What it does.** `python tools/fetch_mingw.py` fetches llvm-mingw 20260922 (LLVM 23.1.2) into
  `vendor/llvm-mingw`, from the release asset whose sha256 is pinned (GitHub records the same
  digest beside it).
  - It keeps the x86-64 Windows target alone: 5,300 files, 425 MB of the archive's 750.
  - It records each one in `vendor/MINGW.sha256`, which `--verify` checks.
  - `python tools/recompile.py --cc mingw --compile --optimize --link` then builds
    `gen/mingw/soa.exe`, and each shipped mod's `mod.dll` under `gen/mingw/mods`, beside a copy of
    its `mod.ini`, never over the msvc build's.
- **What the runtime needed:**
  - **One change in `gxr.c`:** the host profiler's inline-frame symbols, which mingw-w64's
    `dbghelp.h` does not declare. There a sample is charged to the line that calls the inline.
  - **The guest's `fma` inside the exe** (3.3):
    - The mingw link imported `fma` from the UCRT DLL, which under Proton is Wine's.
    - `runtime/soafma.c` now gives it the instruction where the CPU has FMA3, and otherwise musl's
      exact software `fma` (vendored, MIT, named in NOTICE).
    - `cpu.h` names it in a MinGW build only. MSVC's static CRT keeps its own, already inside the
      exe.
    - `exp2f` and `log2f` were already CORE-MATH's, inside the exe (L6).
- **Checked** [V]:
  - **`--verify`:** 5,300 of 5,300 files unchanged; one byte flipped in `include/stdio.h` gives
    5,299 and exit 1.
  - **The build with nothing of Microsoft's:** `test_mingw.py` runs the whole build with
    `msvc_env` made to raise. Every runtime file also compiles under `compile_runtime.py --cc mingw`
    (31 of 31, `gxv.c` as the backend too).
  - **The import table** (`llvm-readobj --coff-imports`) lists no `fma`, `exp2f` or `log2f`.
    Before `soafma.c` it listed `fma`. What it still takes from the UCRT:
    - `floor`, `floorf`, `ceilf` and `sqrt`, which have exactly one correct answer, so every
      library agrees;
    - `pow`, which only `picture.c`'s filter tables call, never the game's arithmetic.
  - **With `gen/mingw/soa.exe`:**
    - `SOA_SELFTEST=1` gives 0 failures. Its new case calls the translated vector lerp at 80120A50
      with t = 1 + 2^-30, a.z = -(1 + 2^-23) and b.z = 0, and gets 0x30800001, the once-rounded
      float. `soa_fma_soft` agrees with the build's own `fma` on 200,000 triples where one rounding
      decides.
    - `scenario.py replay --exe gen/mingw/soa.exe --threads 1,2,3,8` matches all 23 captures
      against the manifest.
    - `title --check` holds 4 of 4 invariants.
    - `SOA_GPU=vulkan` starts the backend, and `gpuspike.py contrast --exe gen/mingw/soa.exe` gives
      the spike's pixels on 67 of 67 captures.
    - The four mods built by the GNU build load. The co-op mod's live check
      (`test_mods.py p10b`, battle scenario, pad 2 scripted) passes.
  - **The mutations:**
    - **A naive `fma`** (`a * b + c`) linked in fails the case: 0x30800000, and 165,071 of 200,000
      triples differ.
    - **One sticky bit dropped** from the software `fma`'s normalisation gives 6 of 200,000 that
      differ: the comparison sees a rounding-edge error, not only a gross one.
    - **`-mfma` without `-ffp-contract=off`** moves all 23 replay hashes. So the renderer's float
      maths does contract wherever an FMA instruction exists, the flag is what keeps it the
      console's, and the replay catches its loss.
  - **CI:** a new job, `Runtime compiles (llvm-mingw)`, fetches and verifies the release's
    Ubuntu-hosted build and compiles every runtime file for Windows with it. Its mutation, an `__try` added to
    `clock.c` on a scratch branch (run 37231179534, `gh workflow run --ref`; the branch deleted
    after), turns it red: 30 of 31 compiled, "use of undeclared identifier '__try'".
    - The Linux gcc and clang jobs fail it too, and the clang-cl and MSVC jobs pass it.
    - What only this job compiles is the Windows half of the runtime under mingw-w64's headers.
      The `dbghelp` inline-frame calls R1 had to guard were such a case: every other job compiled
      them.
    - Its verify recorded 5,208 files from the Linux archive.
  - **Build times**, full `--compile --optimize --link` from the same translation, interleaved twice
    on this machine (16 threads): compile, link and the whole command (translation
    included), in seconds:

    | | compile | link | whole |
    |---|---|---|---|
    | MSVC | 150.4, 148.5 | 9.3, 10.4 | 187, 182 |
    | clang-cl (the NDK's) | 54.2, 60.2 | 18.1, 14.2 | 93, 97 |
    | llvm-mingw | 44.0, 41.4 | 11.6, 13.2 | 77, 75 |

    llvm-mingw builds the game in about two fifths of MSVC's time, on this machine.
- **Not yet:**
  - the player's build without `src/` and `include/` (3.1), and one command from disc to folder
    (R2);
  - reproducible bytes: no timestamps, no absolute paths, which R2 asks.

**R2: one command from a disc image to a folder that plays.** 2026-10-04.

- **What it does.** `python tools/player_build.py --disc <image> --root <folder>` builds the game into a
  folder with nothing of Microsoft's:
  - it checks the disc;
  - it extracts what the game reads;
  - it translates, compiles and links with llvm-mingw (`--no-decomp`, `--reproducible`, every core);
  - it puts `soa.exe` and the mods at the folder's top and writes `soa.ini` (`gpu = vulkan`, the mods
    on);
  - it prints a `[build]` line per step and translation unit, for R4's window, and ends with the exe's
    SHA-256.
- **The package.** `python tools/package.py stage <folder>` lays out what a release holds:
  - `python/`, CPython 3.14.8's embeddable distribution (pinned and hashed), 24 MB;
  - `toolchain/`, llvm-mingw, 425 MB;
  - `source/`, 31 MB: `runtime/`, `config/`, the tools the build runs, the mods' text and
    `vendor/`'s GPU build files.
  - Never `src/`, `include/`, `gen/`, `extracted/` or `build/`.
- **The build without `src/`** (3.1). `recompile.py --no-decomp`:
  - leaves out the 12 bindings `decomp_swap.c` answers with decompiled code (a test holds them to the
    ones `hle.txt` notes as decompiled), so the game's own MSL runs translated;
  - links with `SOA_NO_DECOMP`, which empties `decomp_swap.c` and has the self test name its
    comparison skipped.
- **The pipeline cache under the root:** `main.c` hands `settings_root()` to `gxv_set_root`, and the
  cache is `<root>/build/gxv-pipelines.bin` (`plat_mkdir` makes the folder) whatever the working
  directory. The spike, which links no `settings.c`, keeps the relative path.
- **Checked** [V]:
  - **From the staged package,** with `PATH` holding only its `python/`, the owner's disc builds into an
    empty folder:
    - in 137 s the first time, and 85 s when it rebuilt;
    - `GPU backend: built in`;
    - the same `soa.exe`, byte for byte, as the builds from the repository (sha256 8e5d246f...).
  - **The installed exe:** `SOA_SELFTEST=1` gives 0 failures with case 73 named as skipped; `replay
    --exe` matches 23 of 23 at 1, 2, 3 and 8 threads; `title --check` holds 4 of 4.
  - **Reproducible:** `build/player1`, `build/second player` (a space in its name) and the staged
    package's build give the same `soa.exe`. Without `--no-insert-timestamp`, the two folders' links
    differ.
  - **Never stale:** one byte of the staged package's `runtime/cpu.h` changed, and the build over the
    finished folder logged `[build] translate: runtime/cpu.h` and compiled all 19 units again.
    `test_player_build.py` holds the decision, with the mutation that only relinks.
  - **Run from elsewhere:** started from another working directory, the exe's `[gxv] pipelines:`
    line names `<root>/build/gxv-pipelines.bin`, and no `build/` appears where it was started.
  - **Refusals,** four tests with a synthetic disc, each exit 2 and a `[build] refused:` line:
    - another game id, named (GTSE01);
    - an executable whose SHA-1 differs;
    - an image that is not a disc;
    - a config that cannot be read, never a warning.
  - **RVZ under the embedded Python:** `discfixture.write_rvz` (new) makes a synthetic RVZ, which reads
    back under `python.exe`. With `_zstd.pyd` taken out, the same run fails.
  - **What the translated MSL costs** on `partl` (3,000 frames at `SOA_SPEED=20`, the mingw build with
    `src/` against the one without, interleaved three times):
    - native 34.8, 41.8 and 43.7 s; translated 43.9, 39.3 and 34.9 s;
    - medians 41.8 and 39.3, so no cost shows above the noise, and 3.1's plain-C equivalents are not
      needed.
- **Not yet:** R3 (the zip, the guard over it, the release workflow) and R4 (the setup window).

**R3: the package, its guard, and the release workflow.** 2026-10-04.

- **What it does:**
  - **`tools/package.py --out <dir>`** stages the player's package and adds `licenses/`. That folder
    holds eight texts: those for what the package carries (CPython, LLVM, mingw-w64, winpthreads,
    Vulkan-Headers), and llvm-mingw's and glslang's, fetched at their tags and pinned. It then zips
    the package and writes the zip's SHA-256.
  - **`guard.py --tree <dir>`** scans a folder by the package's rules:
    - the third-party folders (`toolchain/`, `python/`, `source/vendor/`) may pass the size limit
      and the folder names;
    - every other rule holds everywhere;
    - `src/` and `include/` are refused by name;
    - a DOL is found by its header, at offset 0 of any file and on any 32-byte step of the package's
      own files.
  - **`.github/workflows/release.yml`** runs, in order: the tests, R1's llvm-mingw compile, the
    package, and the guard over the package unzipped. Only then does it draft a release, for the owner
    to publish.
- **Checked** [V]:
  - **The first run** (37256223377, `gh workflow run release.yml --ref main`, 6 min) passed every
    step and drafted `soa-ff0926d-windows-x64`:
    - 128,712,356 bytes, 488,165,904 unpacked;
    - the guard passed 5,518 files.
  - **The mutations**, each on a scratch branch (deleted after), failed at the guard and drafted
    nothing:
    - a synthetic DOL planted as `source/config/notes.txt` ("holds a DOL's header at offset 0x0");
    - `src/sdk/msl/string.c` copied in ("under 'src/', the decompiled code a package never holds").
  - **That draft's zip, downloaded to this PC** into a new folder (its SHA-256 the draft's):
    - built the owner's disc with `PATH` holding only its `python/`, in 78 s;
    - made the same `soa.exe` as every build here, byte for byte (8e5d246f...), so the package CI
      makes on GitHub's machine and the tree here agree;
    - and passed R2's checks: the self test (case 73 named as skipped), `replay` 23 of 23 at 1, 2, 3
      and 8 threads, and `title --check`.
  - **The guard by tests:** a clean package passes; a DOL is found under an innocent name, inside a
    file, and in a third party's folder; random bytes and text hold none.
- **Found by that download:** the `.sha256` file was written with CRLF on Windows, which
  `sha256sum -c` reads as part of the file name. It is now written with LF on every host.
- **Q-D4 stays the owner's:** each release is a draft until the owner publishes it.

**R4: the setup window.** 2026-10-04.

- **What it is:** `tools/setup/setup.c` builds `Setup.exe`, which sits at the top of the package.
  `tools/package.py` compiles it last, with the package's own llvm-mingw, and `windres` adds
  `setup.manifest`: common controls 6, the system's DPI, `asInvoker`. The result is 97,792 bytes.
- **Before anything is written,** it checks the folder it sits in (§3.7):
  - a plain ASCII path;
  - a path short enough for the package's deepest file. `package.py` measures that file when it
    builds Setup: 90 characters, a libc++ header under `toolchain/`, so roots of 169 characters or
    more are refused;
  - not inside Program Files, asked of the shell (`SHGetKnownFolderPath`);
  - the whole package: its python, the build script and the compiler. Opening Setup.exe from inside
    the zip, where Explorer extracts it alone to a temporary folder, is refused, with Extract All named;
  - write access, by a probe file deleted on close;
  - 2 GB free, until a build is there;
  - Smart App Control, read from `VerifiedAndReputablePolicyState` (1 is on). This PC reads 0.
  Each refusal says why and what to do. Any image format but ISO, GCM or RVZ names Dolphin's Convert
  File.
- **Build** runs `python\python.exe -X utf8 source\tools\player_build.py` with `CREATE_NO_WINDOW`:
  - its output goes through a pipe to the log pane and to `build\setup.log`, and the `[build]` lines
    drive the progress bar;
  - exit 2 shows the refusal in words, and any other failure says where the log is saved;
  - its processes run in a job object, so closing Setup mid-build asks first and then ends them all.
- **Play** starts `soa.exe` with `CREATE_NO_WINDOW` and the root as its working directory, then closes
  Setup. The game's console is hidden, so M5b's rule sends its log to `build\logs`.
- **A built folder** offers Play and Rebuild. Rebuild runs `player_build.py --rebuild` (new), which
  translates again from scratch, as §3.8 says.
- **When `soa.exe` has gone** at Play or after a build (risk 7), the window names Windows Security's
  Protection history and its Restore.
- **For checks with no hands:** `--disc <image> --build --play`, and `--check [--root <folder>]`,
  which exits with what the checks found and opens no window.
- **In the release workflow:** `test_setup.py` runs once llvm-mingw is fetched, and there a skip fails
  the step. Then `Setup.exe --check` must pass in the package as unzipped, beside the guard.
- **Checked** [V]:
  - **The Done line, on this PC, with the final Setup.exe:**
    - `package.py --out` made the zip from this tree, and it was extracted into a fresh folder.
      `guard.py --tree` passed its 5,519 files, and `Setup.exe --check` passed there.
    - `Setup.exe --disc extracted\disc.iso --build --play` opened the game 54 s after Setup's window
      appeared. Its `soa.exe` is 8e5d246f..., the same as every build.
    - The game reached the title screen, seen in a capture of its window 40 s after it opened.
    - A watcher listed every new visible top-level window for the whole run. It saw two: Setup's
      (`SoaSetup`) and the game's (`SoaWindow`). There was no console window, and the game's log says
      "started without a terminal". An earlier build of Setup gave the same result.
  - **The mutation:** Setup built with `SETUP_MUTATE_CONSOLE`, which passes 0 for the flag. The watcher
    saw a Windows Terminal window for python at 0.5 s, a `PseudoConsoleWindow`, and a second Terminal
    window for `soa.exe` at 26 s.
  - **Closing mid-build:** at 15 s, 2 python and 32 compiler processes were running from the folder.
    After Setup's question was answered Yes, none were left. `setup.log` stops at
    `[build] 1/19 dispatch.c`.
  - **A folder whose path holds a space** (`...\sp ace\soa-...`, 161 characters) built the same
    `soa.exe` through Setup in 58 s.
  - **`test_setup.py` (11):**
    - `--check` passes a whole package in a plain folder, and leaves nothing behind;
    - it refuses, each in words: Setup.exe alone in Explorer's kind of temporary folder, and each of
      the three package files missing in turn; a path holding `ï`; a root one character too long, while
      one character shorter passes that check; both Program Files folders (`C:\PROGRA~1` too, but not
      `C:\Program Files2`); a folder denied writes by `icacls` (the same folder passes again once
      allowed); and `.wbfs`, `.ciso`, `.gcz` and a file with no extension, naming Convert File;
    - two builds of one source are one file, which holds the manifest;
    - `package.deepest` measures a tree.
    Six mutations of `setup.c` were each built and run against it, and each failed its own test: the
    ASCII check removed, the length check removed, Program Files matched by prefix alone, the package
    check removed, the write probe removed, and `.wbfs` accepted.
  - **`test_player_build.py`:** `--rebuild` translates again when the record matches.
- **Found:**
  - **The ProgramFiles variable cannot test the Program Files check.** Windows sets it afresh in each
    64-bit process it starts, whatever the parent's environment says. A test that set it saw the
    check pass. The check now asks the shell, and the tests name the real folders through `--root`.
  - **Windows' 260-character limit applies to the whole package.** Extracting it under a 178-character
    root failed on a libc++ header at 262 characters, before Setup could run. A player's
    `Downloads\<zip name>\<zip name>` is about 70 characters, well inside the limit. Pruning
    `toolchain/include/c++`, which a C build never reads, would give 7 more characters and some
    megabytes. That is for R1's fetch to weigh.
  - **A screen copy of the game's window is plain grey.** The GPU presents through a flip-model swap
    chain, which `BitBlt` and `ImageGrab` do not see. `PrintWindow` with `PW_RENDERFULLCONTENT` does.
    Any later grab of the live window needs it.
- **Not checked:**
  - the free-space refusal (no drive here is that full);
  - Smart App Control turned on;
  - the file dialog in the player's hands (the disc was given with `--disc`).
  These are for the owner's run on the Ally X, R4's second Done line, which is still to come. A Steam
  Deck run follows if one exists.

**I1: one seam for the disc, and the system files from the image.** 2026-10-05.

- **What it is:** `runtime/disc.c` now owns every byte the game gets from its disc.
  - **Opening:** `disc_open` takes a folder holding `disc.iso`, or an `.iso`/`.gcm` file itself, so
    `gen\soa.exe "D:\...\Skies.iso"` runs from the player's own image with no copy.
  - **Refusals:** before anything is believed, it refuses bad boot magic, a game id other than
    `GEAE8P`, a revision other than 0, an executable whose SHA-1 is not the one the code was
    translated from, and a file table or executable section past the image's end. Each refusal is a
    sentence that names the fix. An RVZ is named as Dolphin's format, with `extract.py` as the way to
    convert it.
  - **What it hands out:** `main.c` gets the executable, boot.bin and the file table; `dvd.c`'s
    reads go through `disc_serve` (zeros past the end, counted); the census gets names and 32-byte
    heads.
  - **No image:** the run stops at boot, exit 1, naming `python tools/extract.py`. It used to boot
    and read zeros.
  - **Other changes:**
    - SHA-1 moved from `mod.c` to `runtime/sha1.c`, unchanged.
    - `plat.h` gained `plat_path_kind`, a 64-bit `stat`.
    - `aram.c` lost MSVC's `__argv` and its `(long)` seek.
    - `dvd_init`, `aram_set_data_dir` and `main.c`'s `slurp` are gone.
    - The drive's timing is unchanged: I5a is still not built.
- **New:**
  - `SOA_DISC_LOG=1` writes a `[disc] frame F read 0xOFFSET +LEN file[, N past its end]` line per
    read.
  - The `[disc]` open line gives the image's size and three SHA-1s.
  - At the end of a run: `[disc] backend iso; N reads past the image's end`.
- **Checked** [V]:
  - **The open line:** `$env:SOA_SETTINGS='0'; $env:SOA_FRAMES='300'; gen\soa.exe extracted` names
    DOL `8c0e2781...`, boot.bin `d7b9c3f0...` and FST `8d8757eb...`, the spec's three hashes. The
    `[boot]` line is byte for byte `test_scenario.py`'s. The ISO named directly boots the same.
  - **`tools/citest/disc_check.py`, 81 of 81** under MSVC, clang-cl and llvm-mingw (2.8 s):
    - the three system files are the synthetic image's exact slices, from the folder and from the
      file;
    - every file read as the game reads it (rounded up to 32) is the image's bytes, and a read past
      the end is the last bytes then zeros, counted and said once;
    - every file is named at its first and last byte, and padding, junk gaps, the system area and
      the tail by none;
    - ten images are refused, each in different words. That is the spec's six, plus another
      revision, a malformed file table, an RVZ and no image.
    The mutation `--mutate fst-offset` fails it.
  - **The live read log:** `SOA_DISC_LOG=1` then `disc_check.py --log` gave 68 reads in 300 frames
    and 226 over `title`. Each named the file `tools/soa/disc.py`'s own parse puts at its offset,
    with the right count past its end, and none named no file. `test_disc_check.py` refuses a line
    naming the neighbouring file, a read naming no file, a wrong overrun, and a log with no reads.
  - **No disc:** `gen\soa.exe build\citest\no-disc` exits 1 naming `python tools/extract.py`.
    `test_memguard` now asserts that on every one of its boots, under gcc in CI too.
  - **The census:** `title --check` passes, and its `[aram] census sources` line still says 5,552
    disc files indexed.
  - **The constants:** `test_disc_const.py` holds `DISC_DOL_SHA1` to `config.yml`'s hash and
    `DISC_GAME_ID` to the folder's name, and refuses one hex digit changed.
  - **The contract:**
    - `scenario.py replay` matched 23 of 23 at 1, 2, 3 and 8 threads;
    - the self test reported 0 failures;
    - `title --check` held 4 of 4;
    - `decomp.py` is untouched;
    - `test_mods.py`, whose hashlib agreement check now runs on `sha1.c`, passes;
    - the boot-path builds (`test_memguard`, `test_peek`, `test_poke`, `test_uncap`,
      `test_profiler`) pass with `disc.c`, `sha1.c` or the disc stubs added.
- **CI:** `disc_check.py` runs in the MSVC and clang-cl jobs and on the three Linux legs, which are
  `disc.c`'s first runs through `stat` and `fseeko`.
- **What follows:**
  - **I3** waits for D-5, the owner's yes or no on `soa.exe` holding their executable.
  - **The store** (I4, I5) is next in M3, since §0's G5 default now applies.
  - **The player's package** could now read an ISO where it lies, not copy it (distribution §3.7).
    `player_build.py` still copies it, because Setup's Rebuild reads `extracted\disc.iso`.

**I3: the executable built in.** 2026-10-05, after the owner's D-5 yes.

- **What it is:** `tools/recompile.py` builds the disc's executable, boot.bin and file table into
  `soa.exe`.
  - **Where they come from:** `--disc`, `extracted` by default. `tools/soa/embed.py` writes them
    into `<--out>/disc_sys.c` at every run, as little-endian 32-bit words with each part's size and
    SHA-1. Both links compile that file beside `runtime/`. The file's first line is a marker the
    guard refuses in any file.
  - **Refusals, unless `--force`:** a disc whose executable is not `config.yml`'s, and one that is
    not `--dol`'s.
  - **`--no-embed`** writes the same symbols empty.
- **At boot:**
  - **The built-in parts are checked first:** `runtime/disc.c`'s `disc_builtin` holds each to its
    own SHA-1, and the executable to the port's. A part that fails stops the boot naming a generator
    fault.
  - **No disc for the self test or a replay:** neither opens one. A game run still opens the image,
    and an image whose file table is not the build's is refused: "not the one this build was made
    from (a patched or different image?)", with both hashes. Otherwise the `[disc]` line ends
    "FST matches this build".
  - **One boot line always says which:** `[boot] system files built in (DOL sha1 ...)`, or
    `[boot] system files from the image (built without them)`.
- **The stale-link guard:** a `--compile` that succeeds writes `<--out>/build_inputs.txt`, the
  executable's SHA-1 and the profile. `--link` refuses chunks compiled from another executable
  before it parses anything. A `gen/` from before says so once.
- **The guard:**
  - `.exe`, `.obj`, `.pdb`, `.so` and `.apk` are refused, so 48 suffixes, CI's history grep with
    them.
  - So is the marker, in any file's first 24 KB.
  - `--tree` keeps the package's python, compiler and `Setup.exe`.
  - All of history passes both forms.
- **Other changes:**
  - `player_build.py` passes its own `--disc`, because recompile.py runs from the package's
    `source/`.
  - SPEC §2.2 names the copies.
  - README says plainly that `gen\soa.exe` holds your executable and is never shared.
- **Checked** [V]:
  - **A game run:** `$env:SOA_SETTINGS='0'; $env:SOA_FRAMES='300'; gen\soa.exe extracted` prints
    `[boot] system files built in (DOL sha1 8c0e278126fa...)`. The `[boot]` DOL line is unchanged
    and the open line says the table matches.
  - **The self test with no disc:** `$env:SOA_SELFTEST='1'; gen\soa.exe build\citest\no-disc`
    reports 0 failures and prints no `[disc]` line. With `extracted` it opens none either.
  - **Replay:** `scenario.py replay` matched 23 of 23 at 1, 2, 3 and 8 threads. Its sweep now
    reports a replay that opened a disc from a build that says it needs none. The mutation, once:
    `main.c` built to open the image on every path made the sweep report all 184 runs (23 captures,
    four thread counts, two passes). Restored and relinked, 23 of 23.
  - **`--no-embed`:** a link without them prints `[boot] system files from the image (built
    without them)` and boots from the image. With no image it stops, as I1 does.
  - **The stale-link guard, live:** a `gen/build_inputs.txt` one digit off stopped `--link`
    ("stale link") before translating anything. With the right digit it linked.
  - **The player's path:** `player_build.py` into a fresh folder (llvm-mingw, `--compile`) wrote
    `build_inputs.txt` (`profile = mingw`) and a `disc_sys.c`. Its `soa.exe` booted with the system
    files built in and the table matching. Two fresh folders made the same `soa.exe`
    (8207e14d...), so the build is still reproducible. That is a new hash, since the executable is
    now inside. Cold, the build took 72 s; an earlier run took 122 s, with the machine busy.
  - **`disc_check.py`, 92 of 92** under MSVC, clang-cl and llvm-mingw, adding to I1's:
    - built without system files, it has none to give;
    - built with the fixture's, it hands them back with no image open, opens their image saying
      the table matches, and refuses one whose table differs by one letter;
    - built with a table that misses its own SHA-1, it refuses before handing anything out.
    `--mutate fst-offset` still fails it.
  - **The new tests:**
    - `test_recompile_inputs.py` (6): the record; embed's words read back to the fixture's bytes;
      `--no-embed`'s empty symbols; the refusals; both links.
    - `test_guard.py` (+2): built binaries outside the third-party folders, and the marker under
      any name.
    - `test_scenario.py` (+1): the sweep's new check.
  - **The contract:** the self test reported 0 failures, `title --check` held 4 of 4, and
    `decomp.py` is unchanged.
- **What follows:** M3 is done: I1 and I3. The store (I4, I5) is G5's to start. Its default, "build
  it when Android or the Deck is firm", now holds. I5 needs I5a (the deadline change, off the
  default path until agreed) or a re-specification, so I4, the importer, comes first.

**I4: the store, its importer and its checks.** 2026-10-05.

- **What it is:**
  - **`tools/soa/store.py`** writes and reads `GEAE8P.soadisc`, in §3.7.2's format. It holds every
    byte of the disc to a mebibyte past its last file, rounded to 32 KiB, in disc order. A table
    names each extent: the system area, each file, each padding gap, and the tail. A SHA-1 of every
    64 KiB block follows, and a header SHA-1 covers both tables.
  - **One pass:** the writer hashes the whole image while it writes the covered part, to a `.part`
    that is read back, re-hashed and only then renamed. `Store` reads like the other image readers,
    so `Disc(Store(...))` serves every tool, and `open_data` prefers a store to `disc.iso`.
  - **`tools/extract.py <dump> --store`** checks the dump first: the game id, disc and revision; the
    executable against `config.yml` (`--force` waives that); and that its files lie inside the image
    and none overlap.
  - **The verdict** comes from `config/GEAE8P/disc.yml`. All four pins equal is a verified dump.
    Files equal but image not is a scrubbed or trimmed dump, accepted with a warning. Files that
    differ are refused unless forced, and the store is deleted.
  - **Other formats:** NKit, GCZ, WIA, CISO and WBFS are named, with Dolphin's converter.
  - **Commands:** `--check`, `--compare` (`--flip` is its mutation) and `--sys-only`.
  - **The guard** refuses `.soadisc` (49 suffixes, in CI's grep too) and any binary beginning
    `SOADISC1`.
- **The baseline,** `config/GEAE8P/disc.yml`, a first bless the owner approved:
  - **image_size and image_sha1** are Redump's for "Skies of Arcadia - Legends (USA)". They were
    read from libretro-database's mirror of the Redump GameCube list, because redump.org refused the
    connection and GameTDB returned 403. The owner's image also matches that entry's CRC32
    (23E347B6) and MD5 (3E7FA503...ECD), which settles the one-digit MD5 doubt the spec recorded.
  - **fst_sha1 and files_sha1** were computed twice, independently: the spec's read-only pass of
    2026-09-25, and the importer. They agree.
- **Checked** [V]:
  - **The owner's disc:** `extract.py extracted/disc.iso --store` wrote 1,431,490,560 bytes in
    5 s. It has 8,769 extents and 21,828 blocks, covers to 0x55438000 of 0x57058000, and the hashes
    are image `46105320...`, FST `8d8757eb...`, files `7f185565...`. Each is the spec's figure, and
    against `disc.yml` the verdict is "a verified dump", flags 3.
  - **The checks on it:** `--check` re-hashed it all with 0 differing. `--compare` against
    `disc.iso` found 0 bytes differing over [0, 0x55438000), and exactly 1, at 0x348000, with
    `--flip 0x348000`.
  - **`test_store.py` (17):**
    - an ISO and an RVZ import, and each read back is exhaustive;
    - the mutations: a flipped payload byte fails exactly one block and one extent and is named by
      its file;
    - refused: a truncated store, an unfinished `.part`, a changed header, another game, another
      executable, and files that differ;
    - accepted with a warning: a padding-only difference;
    - `--compare`'s 0 and 1, `--sys-only`, the five unsupported formats, overlapping and
      out-of-image tables, the pins' form, and a store preferred in a folder.
  - **`test_guard.py`** (+1): the name and the magic.
- **Not done here:** the owner's image is an ISO, so the RVZ import is checked only on the
  fixture's RVZ.
- **What follows:** I5, which makes the port read the store. It needs I5a (the deadline counted
  from a command's start, which changes every run's disc timing) or a re-specification that keeps
  today's double count. The implementation session's "accept" for I5a is the question before it.

**I5: the port reads the store, and proves it against the ISO.** 2026-10-05, without I5a.

- **The decision first:** the implementation session's question 1 asked whether to count the
  drive's deadline from a command's start (I5a), which would change every run's disc timing. The
  answer is "keep", the recorded default, so I5 was re-specified around today's timing. A block's
  hashing stalls the game, as a read's host time always has, and counts toward the read's
  completion. The 1% hashing budget bounds it, and I5a's overrun line is dropped.
- **What it is:**
  - **`runtime/disc.c` reads the store.** It takes `GEAE8P.soadisc`, preferred in a folder holding
    both, or the file named directly.
  - **The checks at open:** its header and tables (the version, every size and offset bounded, the
    header's SHA-1 over both tables, a truncated payload), then the same disc checks as an ISO. The
    `[disc]` line says "store v1" and whether the dump was verified at import.
  - **`SOA_DISC_VERIFY`:**
    - `hash`, the store's default, hashes each 64 KiB block the first time a drive read touches it.
      A block that differs stops the run with exit 9, naming the files in it, before the game sees
      a byte;
    - `iso[:path]` reads every read again from the ISO and names each read that differs, with its
      first differing byte;
    - `all` does both; `0` neither;
    - asking it of an ISO is refused: a check that silently does not run is worse than none.
  - **`SOA_DISC_FLIP`** inverts one bit of the store as it is read: a file's first byte, or an
    offset.
  - **`soa.exe --check-disc [store]`** hashes every block and extent: exit 0, or 9 naming what
    differs.
  - **Exit 9** is the disc layer's stop. scenario.py knows it and takes a store or an image as
    `--data`.
- **Checked** [V], on the owner's disc through a store made by `--store`:
  - **Verify run 1:** `scenario.py run title --check --data <store> --env SOA_DISC_VERIFY=all:<iso>`
    held 4 of 4. It compared 226 reads with the ISO, the same as `[dvd]`'s 226, with 0 differing and
    0 past the stored image. It hashed 227 blocks in 35.8 ms of 69.9 s, 0.05% against the 1% budget.
  - **Verify run 2:** `hold` the same way (16,500 frames at `SOA_SPEED=3`) held 4 of 4. It compared
    449 reads, equal to `[dvd]`'s 449, with 0 differing and 0 past, and hashed 437 blocks in
    79.4 ms of 210 s.
  - **The mutation, ISO comparison:** title with `SOA_DISC_VERIFY=iso` and
    `SOA_DISC_FLIP=sound/tone.info` (its first read). Exactly one read differed, the first at
    0x5502E8E8, that file's first byte, and no other offset. The game, which iso mode serves, then
    hung on the corrupt sound header; the watchdog stopped it, exit 5, after 6 reads. That is why
    `hash` is the default.
  - **The mutation, hash check:** the same flip under the default check stopped the run at first
    touch, exit 9. The message named block 21762 and the two files in it, `sound/stv73.samp` and
    `sound/tone.info`, before the game had a read (`[dvd] 0 reads`).
  - **`--check-disc`:** the clean store passed, exit 0, in 7.0 s, "a verified dump". With
    `SOA_DISC_FLIP=0x348000` it exited 9, naming `battle/btlcursor.mld` with exactly one block and
    one extent differing.
  - **`disc_check.py`, 108 of 108** under MSVC, clang-cl and llvm-mingw, adding the store's half on
    a long-tailed fixture. A mutation that removes the block check fails it (the driver exited 0
    where 9 was due).
  - **The contract on both backends:**
    - the store: title above, and hold;
    - the ISO: `title --check` 4 of 4, replay 23 of 23 at 1, 2, 3 and 8 threads, and the self test
      0 failures, the last two opening no disc (I3);
    - `decomp.py` is unchanged.
- **Not changed:** `extract.py` still writes `disc.iso` by default, and the store is `--store`.
  The player's build and Setup's Rebuild read `extracted/disc.iso`; moving them to the store is the
  player package's change to make.
- **What follows:** M3 and the store are done, I1 to I5. Next on §0's Android path is L12, the
  Android shell, which is to be specified in full when its gates open, and they now have; it
  specifies R5 with it.

**L9: the POSIX layer, part 2.** 2026-10-05.

- **What it is:** what settings.c, mod.c, hle.c and audio_out.c asked of Windows now goes through
  `runtime/plat.h` and `plat.c`. So do clock.c, tick.c, selftest.c and main.c's watchdog.
  - **New in plat.h:** `plat_exe_path`, `plat_realpath`, `plat_dl_why` (the loader's own words),
    `plat_list_dirs`, `plat_process_cpu`, `plat_thread_detach`, `PLAT_SEP` and `PLAT_DL_SUFFIX`.
  - **Mods:** a native mod is `mod.dll` on Windows and `mod.so` elsewhere. It is loaded by its full
    path; on Windows that keeps `LOAD_WITH_ALTERED_SEARCH_PATH`. `soa_mod.h` gained
    `SOA_MOD_EXPORT` (additive, no API change), and the four mods use it.
  - **Audio:** the meter, the arrival rate, `SOA_WAV`, the mute and the report are every platform's.
    waveOut is the Windows backend.
- **Three fixes off Windows, found by the move** [V, code]:
  - **The report's once-only guard** was a plain flag. A stop on the guest thread and a window's close
    could both run it. It is now plat.h's compare-and-swap, as on Windows.
  - **The frame-time lock** was a no-op off Windows. That is the race the 2026-09-25 review named. It
    is now V8's `PlatLock`.
  - **The wall clock** read `TIME_UTC`, so a clock change could move a run's seconds. It is now the
    monotonic one. CPU time reads `getrusage`; it read `clock()`.
- **`tools/tests/test_portability.py`** names every `_WIN32` conditional in `runtime/` by its function
  and holds the set to a written list, each entry with its reason. The list adds the sites that came
  after the spec: gxv.c's Vulkan loader name and Win32 surface, settings.c's Windows console, and
  soa_mod.h's export macro. The renderer-only build's two mkdir pairs stay, because it links no
  plat.c.
- **Checked** [V]:
  - **Windows:**
    - `test_mods`, `test_settings`, `test_memguard`, `test_uncap`, `test_profiler`, `test_clock`
      and `test_tick` pass (203);
    - the self test reports 0 failures;
    - replay matches 23 of 23;
    - `title --check` holds 4 of 4, its audio still 128,000 bytes a second with 0 dropped and the
      frame-time line naming CPU seconds;
    - the three real mods load as `mod.dll`.
  - **llvm-mingw:** `test_mod_library`, `test_memguard`, `test_audio_wav` and the settings test pass.
  - **Linux, gcc 14 in a Docker container on this PC:**
    - `test_mod_library`: map-log built as `mod.so` loads through the real loader, and the recording
      names it `map-log@1.0`. A library exporting no `soa_mod_init` is refused with dlerror's words.
    - `test_audio_wav`: seven blocks give a header of 4,480 bytes, the samples in order.
    - `test_memguard`, `test_portability`, and the settings test: `soa.ini` is found at the root,
      then beside the executable, never in the working directory.
    - **The mutations:** the WAV writer put back inside `#ifdef _WIN32` fails `test_audio_wav` on
      Linux. An `#ifdef _WIN32` added to another function of exi.c fails `test_portability`.
    - Every runtime file compiles under gcc and clang. One new unused-function warning was fixed,
      and a buffer was enlarged.
  - **CI:** the gcc, clang and ARM64 legs run the three Linux checks with skips refused.
- **What follows:** L10, native Linux with SDL3, whose prerequisites (L6, L7, L9) are now all done.
  After it, L12.

**L10: native Linux with SDL3.** 2026-10-05.

- **What it is:** the port builds and runs on Linux, its window, pads and sound through SDL3. Windows
  keeps its Win32 window and waveOut (D2).
  - **`tools/fetch_sdl.py`** fetches SDL 3.4.18's source, its sha256 pinned (another archive is
    refused), and builds a static library with CMake into the gitignored `vendor/sdl3/<system>-<machine>`.
    `vendor/SDL.sha256` records every installed file and the drivers built. SDL loads X11 or Wayland,
    and PipeWire, PulseAudio or ALSA, at run time, so `gen/linux/soa` needs no `libSDL3.so`. Without a
    window system's headers SDL's configure stops, and the script names Debian's packages. `--headers`
    unpacks the source alone, for compiling against it on any host.
  - **`runtime/window_sdl.c`** is window.c on SDL3, behind the same seams (`window_start`,
    `window_open`, `window_pad`, `window_pad2`, `window_host`, `window_toggle_fullscreen`):
    - its own thread, every SDL call on it, the pads reaching the guest thread as a snapshot under a
      lock;
    - `picture_scale` on the CPU into a client-sized texture, shown 1:1 and held by the renderer's
      vsync, as the DXGI presenter scales;
    - the keyboard by the layout in use, as Win32's virtual keys are; any gamepad SDL knows for ports 1
      and 2, with XInput's dead zones and trigger threshold, and rumble on port 1;
    - fullscreen, the cursor, focus and `unfocused`, P5a's filters, `SOA_WINDOW_TEST` and the
      [present] report, in window.c's words.
  - **`runtime/audio_sdl.c`** is an SDL audio stream. audio_out.c's new `SOA_SDL` branch keeps the
    meter, the WAV, the mute, the report and waveOut's rule: a block is dropped when the device is 24
    blocks behind.
  - **`tools/recompile.py`** links on Linux at last (`--cc gcc` or `clang`, the mods as `mod.so` under
    `gen/linux/mods`), and builds the window and sound in whenever `vendor/sdl3` holds this host's
    build. Without it the build is headless, as before.
  - **The three shipped mods build off Windows.** Each read its switch with `GetEnvironmentVariableA`
    and included `windows.h` for it, so none compiled as `mod.so`. L9's test built only the example.
    `env()` keeps that call on Windows and reads `getenv` elsewhere, which settings.c's `setenv`
    writes.
- **Checked** [V]:
  - **The headless Done, in a Docker container on this PC** (python:3.14-slim, gcc 14.2, 16 cores, the
    owner's disc mounted read-only). The final run, from the tree as committed, every exit status 0:
    - `recompile.py --cc gcc --compile --optimize --link` builds in 232 s, the 19 units in 199 s at
      -O2, with SDL3 and all four mods;
    - the self test: 0 failures;
    - replay: 23 of 23 against the same manifest at 1, 2, 3 and 8 threads, in 26 s;
    - `title --check`: 4 of 4, at 27.8 fps, the audio 128,000 bytes a second (SDL found no sound
      device in the container and said so, as waveOut does when it fails).
    - The same three passed before SDL was linked, and after (175 s, 23/23, 4 of 4).
  - **All four mods load on Linux**, each reading its switch: autotext's 45 frames, coop's pad 2, and
    encounter-rate's half. On Windows they build with MSVC and load as before.
  - **The window, under Xvfb** (X11; SDL3's OpenGL renderer on Mesa's software rasterizer):
    - the intro's logo at 2x, whole pixels, in a screenshot;
    - with openbox: fullscreen `fit` at 1440x1080 from +240+0 (a screenshot too), then windowed, then a
      900x600 client with the picture at 800x600 from +50+0, each in the [window] line window.c prints;
    - keys typed by xdotool reached the game: X as A over frames 116-147 of a pad recording, and Left
      as the stick at 0 over frames 162-184;
    - 0 failed presents.
  - **The audio rate.** The tolerance was fixed before the run: 32,000 samples a wall second, plus or
    minus 2%, counting the WAV's samples over the wall seconds between the first block and the last.
    The runs went through SDL's disk device, which takes samples in real time.
    - `SOA_SPEED=1`: 32,022, inside.
    - `SOA_SPEED=2`: 63,961, outside. The device took 9,009 of 18,229 blocks and the rest were
      dropped.
  - **Drops track the container's load, not the backend.** Over 1,200 frames:
    - 0 with nothing drawn;
    - 14, in 6 runs, drawing with no window;
    - 242, in 95 runs, drawing into Xvfb through software OpenGL, with the guest itself behind real time
      (52.1 s in 57.5).
  - **`tools/tests/test_window_sdl.py`** runs the window and sound for real on an X display, with a
    driver standing in for the renderer. It checks the frame read back off the X screen, a key through
    `window_pad`, a resize's line, the presents, and 200 blocks of sound at once keeping 24.
    - Each of four mutations fails it: red and blue swapped, the X key sent as B, the queue a hundred
      times deeper, and the resize not asked.
    - It failed once in an ordinary run, unread. In a fully loaded 16-core container it then failed in
      two ways:
      - 3 of 12 runs showed fewer presents than it asked for (41 to 44 of 50), so the bar is now 20;
      - after that, 1 of 12 exited before the X server had finished the resize, so the driver now
        waits two seconds more.
      Then 20 of 20 under the same load.
  - **`tools/tests/test_fetch_sdl.py`** (8 tests): the pin, the record, the drivers, sdl3.pc, and the
    link line with and without SDL.
  - **`tools/tests/test_mod_library.py`**, 4 new tests: each shipped mod builds as this system's
    library, loads, and reads its switch, and every shipped mod must be listed. On Linux, autotext as
    it was fails to build, and with its `getenv` finding nothing it fails its switch. CI's Linux legs
    run it with skips refused.
  - **Windows unchanged:** MSVC, clang-cl and llvm-mingw compile all 35 runtime files, the two SDL files
    to nothing. `soa.exe` links with the GPU backend and the four mods, and the self test reports 0
    failures.
  - **CI:** every Linux leg compiles the SDL files with `SOA_SDL` (`--require-sdl`). The gcc leg builds
    SDL and runs `test_window_sdl.py` under Xvfb, with skips refused. Before main, a scratch branch
    ran the new steps (run 37369073677): SDL built on the runner with X11, Wayland, PipeWire, PulseAudio
    and ALSA, and the window test and the shipped mods passed. GitHub left some jobs unacquired by any
    runner twice before they ran.
  - **The test count** is 1342 in 84 files, measured: 1338 passed and 4 skipped here (the fourth is
    `test_window_sdl.py`, with no X display on Windows), 931 and 411 without MSVC.
- **Fixed on the way** [V, code]: the guest thread could read port 1 before the window thread's first
  snapshot, and get the stick hard left and down for one poll. The window now reads the input once
  before it says it is open.
- **A filtered log hid a failure** [V]. The first builds' logs dropped lines that start with two
  spaces, which is how `recompile.py` names a mod that failed, and a pipe hid its exit 1. `soa` linked
  each time, so the build looked whole. The final run above prints every exit status.
- **Not checked:** a person playing. That means a real gamepad (SDL's mapping and rumble), Wayland, and
  a real display's vsync: Xvfb has none, and SDL's OpenGL renderer there would hold each present for
  one refresh, not two, leaving the rest of the pacing to the loop. These are the owner's fifteen
  windowed minutes, which need a Linux desktop: a WSL distribution, which brings WSLg (`wsl --install -d
  Ubuntu`; this PC has only Docker Desktop's, without it), a Linux PC or the Deck.
- **What follows:** L12, the Android shell, to be specified in full, with R5.

**L12a: the seam on the desktop.** 2026-10-05.

- **What it is:** Android's arrangement, built on Linux. `tools/recompile.py --cc gcc --split` builds three
  files into `gen/linux-split`:
  - `libsoa_runtime.so`: every runtime file with `SOA_SPLIT` and `SOA_NO_DECOMP`, plus the generated
    `runtime_seam.c`;
  - `libsoa_game.so`: the translated objects, `disc_sys.c` and `game_table.c`, every function hidden but
    `soa_game`;
  - `soa`, a launcher that needs the runtime.
  - **The runtime reaches the game only through one table** (specs/android.md 3.2). `game_table.c` is written
    into every build from `config/seam.txt` by `tools/soa/seam.py`. A single-file build links it and calls
    directly, and the self test's new case holds the table to those calls. In a split build, `runtime_seam.c`
    gives the runtime forwarders under the names it already calls, so only `main.c` (renamed `soa_main`) and
    `disc.c` (the system files, which are arrays) change. This differs from the spec's first text, which
    rewrote every reference.
  - **The game library carries its build record** in an ELF note: the table's abi, the decomp mode, and one
    digest of `player_build.BAKED`.
  - **`runtime/elfcheck.c`** reads the library's own headers before `dlopen`:
    - the machine, a shared object, 16 KB pages, no text relocations;
    - the libraries it needs;
    - the record;
    - every symbol it imports, against the runtime's export list;
    - its one export.
    Each failure is refused in the player's words. `runtime/game.c` then `dlopen`s the library, checks the
    table's abi, and runs `main`.
- **Checked** [V], in the Docker container on this PC unless named:
  - **The split build** links, exit 0, in 219 s (the 19 units at -O2 with `-fPIC`, 187 s):
    - `libsoa_game.so` is 25.7 MB and exports `soa_game` alone;
    - it imports the 23 runtime symbols, the 13 bindings of a build with no `src/`, five C library functions
      and weak ones;
    - it needs `libsoa_runtime.so` by name, every `PT_LOAD` is aligned 0x4000, and its `.note.soa` holds the
      record;
    - `libsoa_runtime.so` exports exactly 37 names: 23, 13 and `soa_run`.
  - **On `gen/linux-split/soa`:**
    - the self test reports 0 failures, the table loaded;
    - replay matches 23/23 at 1, 2, 3 and 8 threads against the same manifest;
    - `title --check` holds 4 of 4.
  - **No cost.** Interleaved `title` runs, single-file then split, twice: 93.8 and 95.0 CPU seconds against
    96.4 and 94.9, at 28.1 and 28.0 fps against 27.9 and 28.0. The single-file runs differ from each other by as
    much.
  - **The savepoint:** about 47,000 `setjmp`s over `title`'s 71 s (2,000 context saves, about 44,800 interrupts
    delivered), about 660 a second. A system call each on Android costs under a millisecond a second, so it
    stays `setjmp` (android.md 3.12).
  - **`tools/tests/test_seam.py`** (9 tests) passes under gcc and clang:
    - a game of two functions loads through the real loader and checks, and its entry calls the runtime;
    - it exports the table alone;
    - six libraries with one thing wrong are each refused before `dlopen`, in words;
    - the real split build crosses only `seam.txt`.
    - **The mutations:** with `elfcheck.c`'s import check removed, or its record compared on nothing, the
      matching cases fail.
  - **The self test's new case** ("the game's table": entry, dispatch, files, record, 21 twins) passes in
    `soa.exe` on Windows and in `gen/linux/soa`. MSVC, clang-cl and llvm-mingw compile all 37 runtime files.
- **The self test counted 85 cases before this, not the 83 the docs said:** R1's two fused multiply-add cases
  were never added to them. It is 86 now, and every copy says so. The tests are 1351 in 85 files, measured four
  ways: 1338 passed and 13 skipped here (`test_seam.py`'s nine want an ELF system).
- **CI:** the gcc, clang and ARM64 legs run `test_seam.py` with skips refused. They leave out the real-build
  case, which needs the disc.
- **What follows:** L12b, the game library built on the PC for Android, with the NDK here until Q-A2's own
  sysroot exists.

**L12b: the game library from the PC.** 2026-10-05.

- **What it is:** the phone's game library, built where the player builds `soa.exe`.
  - `tools/soa/toolchain.py` gains the `android-arm64` and `android-x86_64` profiles: the NDK's clang at API
    33 (Q-A3), the gnu flags, `-fPIC -fvisibility=hidden`.
  - It finds the NDK through `SOA_ANDROID_NDK`, `ANDROID_NDK_HOME`/`_ROOT`, or the newest in an SDK's `ndk/`.
    A mistyped `SOA_ANDROID_NDK` is no NDK, and the build names every place it looked.
  - `recompile.py --cc android-arm64 --compile --optimize --link` (always `--no-decomp`) writes a stand-in
    `libsoa_runtime.so` from the seam (`seam.stub_runtime_c`). It links `libsoa_game.so` against it with
    `--no-undefined`, so a call outside the seam fails at link time.
  - **`tools/soa/elfcheck.py`**, `runtime/elfcheck.c`'s checks in Python and in the same words, then says
    whether the phone's runtime would load it.
- **Checked** [V], on this PC with NDK 28.2:
  - `--cc android-arm64`: 19 units compiled in 50 s, 66 s in all, giving a 34.0 MB library. `elfcheck.py`
    passes it.
  - **Reproducible:** a second full build gives the same bytes (sha256 `77ae5a24…`).
  - `--cc android-x86_64`, for the emulator: 47 s to compile, 34.4 MB, passed.
  - **The runtime compiles for both targets:** `compile_runtime.py --cc android-arm64` compiles all 37 files, and
    the SDL window and sound with `SOA_SDL`.
  - **`tools/tests/test_android_build.py`** (9 tests) passes. A game of two functions, built as the real one
    is, passes `elfcheck.py` and is the same bytes twice.
    - Five libraries with one thing wrong each draw their refusal: 4 KB pages, functions not hidden, an import
      the runtime lacks, another record, and one built for x86-64.
    - `runtime/elfcheck.c`, built for this PC with MSVC, gives every one the same verdict in the same words.
  - **The mutations:** `elfcheck.py`'s page limit at 4 KB fails two tests. `elfcheck.c`'s wording changed fails
    the agreement.
- **Not built:** `player_build.py --target`. A player's package carries no NDK, so it waits for Q-A2's own
  sysroot and R5's packaging.
- **CI:** the gcc leg runs `test_android_build.py` with skips refused, using the NDK the runner image carries,
  and compiles the runtime for Android.
- **The tests** are 1360 in 86 files, measured four ways: 1347 passed and 13 skipped here.
- **What follows:** L12c, the APK shell, on the android-34 x86_64 emulator installed here.

**L12c: the shell, on the emulator.** 2026-10-06.

- **What it is:** the APK, with a game library pushed beside it, on the android-34 x86_64 emulator here (the AVD
  `soa_x86_64`, headless on port 5556; the other project's emulator is never touched).
  - **`android/`:** Gradle 9.6.0 and AGP 9.4.0; SDL3 3.4.18's own AAR by prefab; CMake building
    `libsoa_runtime.so` from every `runtime/*.c` with `SOA_SDL`, `SOA_SPLIT` and `SOA_NO_DECOMP`; and
    `SoaActivity`, which is SDL's activity, taking the run's environment and arguments from the intent in a
    debuggable build only. Gradle is fetched by `android.py` against a pinned sha256, with no wrapper jar.
  - **`runtime/android.c`:** the app's storage as the data root; stdout and stderr to logcat and `soa.log`
    through a pipe and a thread; the window held landscape; the game library from that storage; and every
    way out ending with `[exit] N` once the log is drained.
  - **`tools/android.py`:** `build`, `install`, `push-game`, `push-disc`, `push-corpus`, `selftest`,
    `replay`, `run` and `logs`. A device is always named, never taken as the only one attached.
  - **Also new:** `tools/guard.py --apk` and `tools/fetch_sdl.py --android`.
- **Checked on the emulator** [V], with the x86_64 library built here:
  - **the self test:** 87 cases, 0 failures, `[exit] 0`;
  - **the replay:** 23/23 at 1, 2, 3 and 8 threads, against the PC's manifest;
  - **`title` from its script:** 4 of 4 invariants;
  - **`title` from the keyboard:** in a window, `pad.rec` shows START at frame 1603 and A at 1696; START
    skipped the opening, frame 2250 is the title screen with PRESS START, and the four invariants hold;
  - **Home, then back:**
    - 15.7 s are excluded from guest time, and the frame count held at 300 while away;
    - 4% CPU while away, and no audio block dropped;
    - the game's picture is drawn again at 2x after the return (screenshots);
  - **`SOA_MEMPOKE=0x81800000,0x81900000,0x80001000`** under ART's `libsigchain`: reported once, the in-range
    word read back, and the run carried on to `[exit] 0` at its frame limit;
  - **`guard.py --apk`** passes the 8.5 MiB debug APK. A mutant with the real `disc_sys.c` in its runtime
    library is refused at 0x11860 (arm64) and 0x12040 (x86_64).
- **What the emulator found, each fixed:**
  1. **Bionic's x86-64 `fma` rounds a negative result that underflows to +0, not −0:** 80 of the self test's
     200,000 cases. Judged exactly with Python's `Fraction`, bionic was right on none of them and musl's soft
     version on all 80.
     - `cpu.h` now sends `fma` to `soa_fma` on x86-64 Android, as on MinGW: FMA3 where CPUID has it, else
       the soft version. `soa_fma` joins the seam.
     - ARM64's `fma` is the instruction.
  2. **`__AI_SRC_INIT` never ended,** so the game stopped at AIInit with 1 frame in 20 s, 22.7 of its 22.9 CPU
     seconds in the kernel.
     - **What it does:** the SDK times one tick of the 48 kHz sample counter with the timebase, and retries
       until the gap is under 28.5 µs (or between 34.5 and 39 µs).
     - **Why it never ended:** the gap spans at least seven timebase reads. The emulator boots its kernel
       with `clocksource=pit`, so one clock read is a system call of 8 µs (17 µs just after boot), and the
       window was out of reach.
     - **The fix:** `hle.txt` binds it and `hle_os.c` answers it with one round's read-modify-writes of AICR,
       without the spins. That makes 26 bindings, 14 of them crossing under `--no-decomp`.
     - **The self test** (case 76) holds it to its twin, with the five bounds AIInit computes set as AIInit
       sets them. Where a counter read costs 2 µs or more, the twin is not run. Dropping the restart or the
       stop fails it.
  3. **The emulator runs the game at about 9 frames a second,** almost all of it in the kernel reading that
     clock. `title` took 248.9 CPU seconds, 238.6 of them in the kernel, for 2,000 frames in 219 s.
     - **That is the emulator,** not the port. A phone reads its clock through the vDSO in under a microsecond.
       [I] The kernel seconds over the measured read cost give about 136,000 reads a second at 9 frames a
       second. At the phone's 30, and 60 ns a read, that would be about 3% of one core.
     - **A TSC clock is no way out:** booting with `-qemu -append "clocksource=tsc tsc=reliable"` makes the reads
       cheap, but under WHPX every clock then moves in 24-48 ms steps.
     - **The renderer's per-phase timers** disagree with the clock there ("−118% unaccounted").
  4. **The runtime's own exits lost the log's end.**
     - **How it leaves:** the frame limit and the watchdog leave through `_Exit`, a window's close through
       `_exit`, a trap through `exit`. None of them ran `android.c`'s drain.
     - **What was lost:** the report's last lines and the `[exit]` line.
     - **The fix:** the APK links `--wrap` for all three. `test_android_tool.py` fails when a runtime file calls
       an exit the link does not wrap.
  5. **The background events came too late.**
     - **Why:** SDL's pump blocks whichever thread calls it while the app is away. So the loop heard
       `WILL_ENTER_BACKGROUND` only once the app was back, just before the foreground event.
     - **The effect:** the game ran on unseen, with 0 s excluded and 2,946 audio blocks dropped.
     - **The fix:** an `SDL_AddEventWatch` filter now pauses on the thread that sends the event.
  6. **A paused guest spun a core.**
     - **Why:** a guest waiting for an interrupt, in the idle loop or on a flag, read a frozen clock at full
       speed: 100% of one core for as long as the app was away.
     - **The fix:** `irq.c` sleeps while a pause is requested, and the core goes to 4%. `unfocused = pause` on
       the desktop spun the same way.
     - **Also:** the pause request is now one of L2's atomics, since a third thread writes it.
  7. **The window:**
     - **Landscape:** SDL replaced the manifest's landscape with "any" for a resizable window, so
       `android.c` now sets SDL's orientation hint.
     - **The title bar:** the default theme showed one, so the theme is now one without it.
     - **Fullscreen** is the default on Android. Without it the system bars leave 954 lines, and a 2x picture
       needs 960.
  8. **Driving it:**
     - **Keys:** the emulator console's `event send` never reaches the app on a headless emulator, and a plain
       `input keyevent` ends between two reads of the pad. `input keyevent --longpress` holds a key for about
       four frames.
     - **The screen:** one that times out locks, and a locked device sends keys nowhere.
  9. **A replay's log was read before its run ended,** with neither its hash nor its `[exit]` line in it.
     - **The evidence:** logcat shows that run finishing normally, 46 ms before the process died.
     - **Why:** one empty `pidof` answer had ended the wait.
     - **The fix:** `launch` now waits for two empty answers in a row; with one, two tests fail. The second sweep
       ran clean.
- **Settled:**
  - **SDL's thread (risk 4):** video, input and the lifecycle work from `window_sdl.c`'s own thread, so
    `main.c` and `plat.c` are unchanged.
  - **The MEM1 guard under `libsigchain` (risk 5)** works.
- **Left for the phone:**
  - **`setFrameRate`, the performance hint, and the render pool's default by `cpu_capacity`** (§3.12). The
    emulator's display is fixed at 60 Hz, it gives no hint session, and its cores are alike.
  - **`RENDER_DEVICE_RESET`** remakes the texture. That is written, but never seen: the context survived every
    trip away.
- **A correction to what this session told the owner:** the 8.5 MiB APK had not "carried something of the
  mutant's".
  - An ordinary incremental build is 8.5 MiB too, against a clean build's 8.1 MiB. The difference is the
    archive's layout.
  - Both pass the guard.
- **Elsewhere:**
  - **Windows,** retranslated for the binding: the self test 87 with 0 failures; `title` 4 of 4; the audio
    unchanged (13,945 blocks, none dropped).
  - **The Linux split build** in the container: the self test runs the new twin through the game table's
    forwarder; `title` 4 of 4; replay 23/23 at 1 and 8 threads; `test_seam.py` 9 of 9.
- **The tests** are 1370 in 87 files, measured four ways: 1357 passed and 13 skipped here; 1338 and 14
  without capstone; 949 and 421 without MSVC; 930 and 422 without either. `test_guard.py` has 84 (the
  `--apk` case), and `test_android_tool.py` is new, with 9.
- **What follows:** L12d, the import on the emulator; then L12's Done on the AYN Thor. D-33 (the package name
  and the release key) is the owner's, before anyone else installs it.

**L12d: the import.** 2026-10-06.

- **What it is:** the phone's first run, on L12c's emulator. It asks for the game library, then the disc,
  through SoaActivity's own picker opening in Download; checks each before keeping it; and says each refusal
  in the player's words, none naming `python tools/`, `soa.exe` or `recompile.py` (specs/android.md L12d).
  - **The disc** is read through the picked descriptor when it is a regular file on this phone's own storage
    whose grant was kept, and copied into `no_backup/copy/` otherwise. Since 6e39f13 a `/proc/self/fd/N` path
    is read through N, and a pipe or a socket is refused as a stream. A read that fails inside the image after
    the open stops the run with exit 9 ("cannot read <p> at 0x..: <the reason>; was its storage removed?"),
    never served as zeros, and a file table that runs past the image's end is refused ("a truncated dump or
    copy?").
  - **The library** is checked through its descriptor before it is copied, and loaded from the copy before it
    replaces the one installed. The checker, `runtime/elfcheck.c` and `tools/soa/elfcheck.py` word for word,
    now names a Windows program or DLL as one; on Android accepts only bionic's C library names, so a library
    needing `libc.so.6` is "built for Linux"; checks the machine before the class, so the 32-bit names print;
    calls another record "different releases"; and holds the record's `dol=` to the executable the app plays.
  - **`runtime/import.c`** (new; Linux only, refusing stubs elsewhere) is the portable half: the copy (checked
    from its first bytes, held to its size, 512 MiB kept free, cancellable, then `fsync`, 0444, `rename` and
    the folder's `fsync`), the rule for reading in place, and the sweep of unfinished copies.
    `runtime/android.c` is the flow and the calls into SoaActivity.
  - **SoaActivity** draws the boxes (`SDL_ShowMessageBox`, overridden: a ScrollView, the DeviceDefault theme,
    a pad's buttons); takes the persistable grant in `onActivityResult` before it writes
    `no_backup/pending_<kind>`, so a pick outlives its process; shows a copy's progress with Cancel; and
    publishes the launcher shortcut "Choose the game files again". `configChanges` gains density, fontScale,
    fontWeightAdjustment, grammaticalGender, touchscreen and colorMode, and the app is a game
    (`appCategory`). The first run writes `soa.ini` with `render = 1`; the library moves from `files/` to
    `no_backup/`.
  - **For checking it:** `SOA_IMPORT=1|library|disc|forget` and `SOA_IMPORT_PICKER`, from extras only a
    debuggable build reads, each box then answered in C; a debug-only provider (`<pkg>.testfiles`: `file/`,
    `pipe/`, `?truncate=N`), absent from a release APK; `tools/soa/gamefixture.py`'s ten libraries, each
    wrong in one way, with the words predicted for each; and `android.py`'s `provide`, `stage`, `mutants`,
    `player`, `reboot` (the port's AVD only) and `grants`, with `run --pick`, `--tap`, `--key`,
    `--kill-before-tap` and `--font-scale`.
- **Checked on the PC and in the container** [V]:
  - **The PC:** `dc_check` and `render_check` pass; the self test 87 cases, 0 failures; replay 23/23 at 1, 2,
    3 and 8 threads; `title` 4 of 4.
  - **`disc_check.py`:** 156 passed under MSVC, clang-cl and llvm-mingw; 169 under gcc in the container as an
    ordinary user, and 168 as root, which reads a file made unreadable, so the by-name refusal is left out.
  - **`compile_runtime.py`:** 39 of 39 under MSVC, clang-cl, llvm-mingw, android-x86_64 and android-arm64;
    `import.c` is the 39th. MSVC's C4996 on `plat_fopen_rb` is silenced in `plat.h` itself.
  - **The Linux split build:** `recompile.py --cc gcc --split --link`; the self test 0 failures, its `[game]`
    record carrying `dol=8c0e278126fa3b0173400fdb632038172743cc13 profile=gcc`; replay 23/23 at 1 and 8
    threads; `title` 4 of 4; `test_seam.py` 17 passed, the real-build case included; `test_import.py` 20
    passed (`-p noskip`, as an ordinary user). CI's gcc, clang and ARM64 legs run `test_import.py` with skips
    refused.
  - **CI, before the push:** the code ran green on the scratch branch `l12d-ci` (run 37521297619):
    `test_import.py` 20 of 20 and the disc check 169 on the gcc, clang and ARM64 legs, 156 under MSVC and
    clang-cl, and 39 of 39 compiled on every leg. Only Android builds compile the two later changes to
    `android.c`'s message (below).
- **Checked on the emulator** [V], the AVD `soa_x86_64` (Android 14, `UE1A.230829.050`, userdebug, port 5556):
  - **The ten wrong libraries through `file/`:** each drew exactly its predicted line,
    `[import] refused <name>: <words>`, and `[exit] 1`; the installed library's sha256 was unchanged
    (`c0046416…`), and no `.tmp` was left. They are the spec's refusals: another ABI (arm64, arm32, two
    Windows files, a library needing `libc.so.6`), 4 KB pages, another `cpu.h` (another build's record), an
    import the runtime lacks, and another disc (another `dol=`, or none). The mutation: the real library,
    picked as `file/real.so`, was copied (34,428,504 bytes), loaded from the `.tmp` and installed.
  - **The same ten through `pipe/`:** all refused: arm32 and arm64 with "the copy was stopped after 64 of N
    bytes: <the same words>", the two Windows files "after 152 of 512 bytes: …"; the rest were copied whole
    and refused in the same words as through `file/`.
  - **Another game's store through `file/`:** "GTSE01.soadisc is GTSE01, not GEAE8P: this app plays the North
    American GameCube release only (European and Japanese discs are not supported)", `[exit] 1`, no copy.
  - **The same store through `pipe/`:** "a stream (a pipe or a socket): copying to
    …/no_backup/copy/disc.soadisc.tmp", then "the copy was stopped after 1048576 of 2236416 bytes:
    GTSE01.soadisc is GTSE01, not GEAE8P: …", `[exit] 1`, `copy/` empty. The mutation: `?truncate=65536`
    gives "the copy stopped at 65536 of 2236416 bytes: GTSE01.soadisc ended early; pick it again".
  - **The real picker, read in place:** DocumentsUI driven by uiautomator, the store staged in
    `/sdcard/Download`. "[android] disc GEAE8P.soadisc:
    content://com.android.externalstorage.documents/document/primary%3ADownload%2FGEAE8P.soadisc,
    grant kept, read in place as /proc/self/fd/104";
    `[disc] /proc/self/fd/104: GEAE8P rev 0 store v1 … verified dump`; 137 blocks hashed (8.6 MB) in 87.7 ms;
    `[exit] 0`; one grant, kept. Its mutation is the re-open probe (found, 1): the open by name that a build
    without 6e39f13 would make is refused there. On Linux, `disc_check.py`'s unreadable-file case is the same
    test, and 6e39f13 showed it refusing a build that opens the path again.
  - **A damaged block:** `SOA_DISC_FLIP=sound/tone.info` gives exactly one "flip armed … 0x5502E8E8
    (sound/tone.info)" line, then "[disc] block 21762 of /proc/self/fd/97 (0x55020000) does not match its
    SHA-1: sound/stv73.samp, sound/tone.info; the store is damaged: copy it to this phone again, or make it
    again on your PC" and `[exit] 9`. The mutation: with `SOA_DISC_VERIFY=0` there is no block line, and the
    game hangs until the watchdog's exit 5.
  - **The grant survives a reboot:** `android.py reboot` takes 39 s; the grant is still kept, and the next run
    reads in place (fd 102) and ends `[exit] 0`. The mutation, with 20 s between `forget` and the reboot
    (found, 3): 0 grants after it, then "GEAE8P.soadisc cannot be read now: the permission to read it is
    gone", `[import] cancelled (disc)` and `[exit] 1`. A pick restored the grant.
  - **Back in the picker:** two Backs (found, 2), then `[import] cancelled (disc)`, `[exit] 1`, `disc.txt`
    unchanged.
  - **The process killed with the picker up:** `--kill-before-tap` killed it, the file was tapped, and the app
    came back as a new process: "[import] pending disc pick from an earlier process: <uri>", read in place,
    `[exit] 0`, one grant.
  - **A configuration change:** `font_scale` 1.15 while the picker was up and 1.3 during the run: 600 frames,
    `[exit] 0`. The mutation: with `fontScale` taken out of `configChanges`, the activity was recreated
    during the pick; the next process, whose `soa.log` the run pulled, never read in place or reached `[exit]`,
    and was stopped at the 600 s limit with the picker showing again. In a re-run (found, 4), logcat
    showed the first process end `[exit] 0`.
  - **The player's path, with no extras:** Pick; Back (twice); Pick; `libsoa_game.so` (34 MB copied,
    installed); Pick; `GEAE8P.soadisc` (read in place). Then `[import] wrote …/files/soa.ini: render = 1`,
    `[settings] … 1 setting(s) applied` and `[window] open at 2x`. The screen captures, at font scale 1.0 and
    1.3, are in `build/android-player/`: at 1.3 the text scrolls and the buttons stay on screen. The
    re-import, `am start --ez soa.reimport true` then "Keep this one" twice, starts the game.
  - **The game after the import** [V, looked at for this entry]: the capture 30 s after the last step shows
    the opening's Overworks logo at 2x at font scale 1.0, and is black at 1.3 and after the re-import. Captured
    again after the last step, every 0.3-1.1 s for 100 s after a first run at font scale 1.3 and every 0.4-4.6 s
    after a re-import, the picture came after both: black while the game boots, then "Presented by SEGA", a
    fade, "Created by Overworks", 22 to 25 s of black while it loads, and the opening's narration ("The age of
    exploration has dawned upon the …"). After a launch with nothing to ask, every 0.5-8.7 s for 120 s from the
    launch, SEGA came at 36.0 s and Overworks was fading at the end. The first logo came 6.7 s after the first
    run's last step with the PC quiet, 7.0 s after the re-import's with the test suite running beside it, and
    36.0 s after the plain launch, also with the suite running. In both stepped series a capture at 30 s would
    have shown Overworks, so the two black captures were not reproduced. [I] They fell in the opening's own
    black, whose timing varies from run to run.
  - **L12c unchanged:** the first launch logs "[android] library moved from
    /data/data/<pkg>/files/libsoa_game.so to /data/user/0/<pkg>/no_backup/libsoa_game.so"; the self test 0
    failures; replay 23/23 at 1, 2, 3 and 8; `title` 4 of 4; `SOA_MEMPOKE=0x81800000` reported once,
    `[exit] 0`; Home and back with the frames held at 300 while away, 16.3 s excluded, 7.6% CPU away,
    `[exit] 0`.
  - **Also:** `cmd shortcut` shows the shortcut, id `reimport`. With `no_backup/disc.txt.tmp` made a folder, the
    run still plays in place and ends `[exit] 0`, the grant kept (its message, see below). Pad B on a box answers
    Quit, `[exit] 0`. A name with an accented letter and a character outside the Basic Multilingual Plane
    (`pagés-` and U+1F600) reached the refusal line without a CheckJNI abort; `android.py provide` refuses names
    that are not plain, so that file itself was not served.
  - **The final APK, after the fact checks.** That run logged "cannot create …/disc.txt.tmp: Is a directory; the
    next launch asks for the disc again", but the `disc.txt` before still named the same disc, so the next launch
    would play it without asking; no next launch had been run. What the next launch finds depends on the
    `disc.txt` left and the permission and copy let go, so `android.c` now says what stays rather than what
    comes: "disc.txt is as it was, naming this disc"; "disc.txt is as it was, naming <name> as copied before"
    or "… as read in place before", for another disc or this one read another way; and, with none, "with no
    disc.txt, the next launch asks for the disc again". On the APK built with it (`4f8cb81f…`): the self test
    0 failures; the unwritable `disc.txt` with this disc named before, `[exit] 0`, and the next launch read in
    place with no box, `[exit] 0`; the same with no `disc.txt` before, `[exit] 0`, and the next launch asking for
    the disc (`[import] box: Now the disc: …`, which a check run answers and cancels, `[exit] 1`); a real pick
    putting `disc.txt` back as it was, with one grant; and pad A on the re-import's box answered "Pick a new
    one", its default, then two Backs and pad B answered Quit, `[exit] 0`. Every other emulator check ran on the
    APK before these two changes to that message.
- **What the emulator found:**
  1. **Android 14 refuses to open the picked file again by name.** The probe:
     "/storage/emulated/0/Download/GEAE8P.soadisc, f_type 0xef53, open by name: Permission denied", an ext4
     descriptor from the lower filesystem, with `persist.sys.fuse.passthrough.enable` unset. The spec's first
     plan, that `disc.c` would open `/proc/self/fd/N` again, fails there, so reading through the descriptor
     (6e39f13) is necessary. The design review had predicted EACCES from AOSP's source; this is the
     measurement.
  2. **DocumentsUI takes two Backs to close.** Opened in Download, it takes the first Back as "up a folder"
     (Download to the device's root), and only the second closes it (by hand, twice).
     `android.py run --key KEYCODE_BACK` now presses Back until the picker goes, at most 4 times
     (`BACK_TRIES`).
  3. **A reboot can beat the write of a grant.** `forget` followed by a reboot within seconds brought the
     grant back, and with 20 s between them the release held: a release, like a take, reaches
     `urigrants.xml` only after a delay, about 10 s by the design's P3 (AOSP's source, for a take). [I] So a
     phone restarted within about 10 s of a disc pick asks for the disc again.
  4. **The destroy path is reached by check 13's mutation.** Without `fontScale` in `configChanges`, the font
     change makes Android remake the activity when the pick comes back, which destroys the one waiting in it.
     The run's pulled `soa.log` is the next process's, so the first time nobody saw it. Run again with logcat
     cleared first, logcat shows `[import] the app was closed during the import`, `[exit] 0` and SDL's
     `onDestroy()`, all at 16:49:39.037, and the process gone 21 ms later. So `onDestroy` wakes a waiting pick,
     and `android.c` ends the run well inside the second SDL gives its thread; a box, a copy's dialog or an open
     left waiting is woken the same way, and was not tried. The first attempt, `settings put global
     always_finish_activities 1` before a run, saw the activity stopped behind DocumentsUI and never destroyed
     in 5 minutes; but ActivityManager reads that setting at boot or from the Developer Options switch [I,
     AOSP's ActivityManagerService], and the run did neither, so it showed nothing.
- **What the design review found,** before any of it was built [V, code]:
  - **SDL's own file dialog does not fit** (SDL 3.4.18, `vendor/sdl3`, re-read for this entry). It runs one
    dialog at a time and cannot cancel it (`SDL_android.c:3347, 3418`); its intent has no start folder and
    no local-only flag (`SDLActivity.java:2092-2105`); a new process drops its result, because the dialog's
    state is a static set when it opened (`:229, 747`); `SDLActivity.java` never takes a persistable grant,
    so no pick would outlive a reboot; and it starts the picker from SDL's thread (`:2108`). So SoaActivity
    has its own.
  - **"Another disc needs no new check" was refuted.** `disc_open` holds the disc's executable to the app's
    (`DISC_DOL_SHA1`), and `disc_builtin` the copy built into the library, but nothing held the executable
    the library's code was translated from: `--no-embed` builds no copy in, and `--force` builds in a
    disc's whatever `--dol` was. The record's `dol=` is that executable's SHA-1 (`recompile.py:638, 700`),
    and the checker now holds it to the app's before `dlopen`: "this game library was made from another
    disc's executable (32e08744cd28, this app plays 8c0e278126fa): rebuild it with Setup from your own
    disc".
- **Not measured:**
  - **An installed library refused after an app update,** shown in the first box; and three of the design's
    mutations: an APK that writes no `soa.ini`, an `onActivityResult` that only notifies, and the library
    left unmoved.
  - **The real store copied through a pipe, and a Cancel during a copy,** on the emulator. `test_import.py`
    cancels a copy at a byte on CI's Linux legs.
  - **A cloud provider's file:** none was picked here.
  - **A phone.** L12's Done is on the AYN Thor, then the Fold 8.
- **Not built:** card import and export through the picker (proposed as slice L12h), a CI build of the APK, and
  a box for a run stopped mid-play. A damaged block or a disc whose storage went (exit 9) closes the app, and
  the reason is in the log alone (`finish()` in `android.c` shows nothing), in lines that name the disc by its
  descriptor's path: a box would need words of its own. (Built next: "L12d's stop box".)
- **The words are not blessed.** Tests pin the checker's and the disc layer's refusals (`test_android_build.py`,
  `test_seam.py`, `disc_check.py`) and some of the copy's (`test_import.py`); nothing but the code pins the
  boxes or the refusals `android.c` words itself. The owner has looked at none of them, so under CLAUDE.md's
  first-bless rule they are a draft. `build/android-review/index.html` (local) shows the boxes as the emulator
  drew them at font scale 1.0 and 1.3 (the re-import's at 1.0), the refusals its check runs printed with what
  causes each, and every other box and refusal as the code words it.
- **The modules:** `test_android_build.py` has 17 tests (was 9), `test_seam.py` 17 (was 9),
  `test_android_tool.py` 34 (was 9) and `test_guard.py` 84 (unchanged). New: `test_import.py` (20), and
  `test_android_jni.py` (4), which holds `android.c`'s JNI lookups to `SoaActivity.java` and
  `proguard-rules.pro`.
- **The tests** are 1435 in 89 files, measured four ways: 1394 passed and 41 skipped here; 1375 and 42
  without capstone; 985 and 450 without MSVC, 409 of them the tests that need MSVC, counted by their skip
  reasons; 966 and 451 without either. The full run took 755.08 s.
- **What follows:** L12's Done on the AYN Thor, which needs the owner and the phone. Without them, two slices
  need neither: R5's own Android sysroot, so Setup builds the phone's library without the NDK, and L12g, mods
  on the emulator. Which comes first is the owner's (PLAN-NEXT §0). D-33 (the package name and the release
  key) is still the owner's, before anyone else installs it.

**L12d's stop box.** 2026-10-06.

- **What it is:** a run disc.c stops mid-play (exit 9: a read that fails, a damaged block) now says why on the
  screen before the app closes, where L12d had left the reason in the log alone (found by reading `finish()`). The
  owner chose it first, before R5's sysroot (PLAN-NEXT §0). `disc.c` keeps the stop's reason as a sentence a
  player reads, with its kind (`disc_stop_words`, `DISC_STOP_READ`, `_DAMAGED` or `_MEMORY`): "<disc> could not be
  read: <why>. Was its storage removed?", "<disc> is damaged: the part of it holding <files> is not what was
  stored there; <remedy>." ("a part of it" when the block holds no file), or "There was no memory left to check
  <disc>: close other apps and start the game again." On exit 9, `android.c`'s `finish()` puts the disc's name, as
  the player picked it, in place of its path, and shows "The game stopped." with those words and a Close button. A
  damaged disc is forgotten first, its `disc.txt` and the app's own copy if the import copied it, so the next
  launch asks for a disc rather than stopping at the same place again, and the box ends "When you open the app
  again, it asks for the disc." The box is SoaActivity's `messageboxShowMessageBox`, called through JNI from the
  thread that stopped, not SDL's, which would work SDL's input state from a thread other than the window's;
  SoaActivity now lets the screen sleep while any box waits. A check run logs the box (`[android] box: …`), shows
  nothing and forgets nothing.
- **What the review found,** before it was pushed [V, code]: the first version named the picked file and advised a
  new copy even when the damaged thing was the app's own copy, which the next launch reused without asking
  (`disc_open` hashes no payload block), so every launch stopped at the same place; called `SDL_ShowMessageBox`
  off SDL's main thread; kept the screen on (SDL's video holds it once it starts); capitalised the picked name's
  first letter; left one stop (the ISO comparison's out-of-memory) without words; and called a block with no file
  in it "padding, no file". Each is fixed above.
- **Checked on the PC and in the container** [V]: `disc_check.py`'s driver prints the words from disc.c's stop
  hook, and the check holds them for the damaged store, in the PC's words and a phone's, and for an ISO cut while
  open, through two readers and, on Linux, under its descriptor. 160 passed under MSVC, clang-cl and llvm-mingw,
  174 on Linux as an ordinary user and 173 as root (156, 169 and 168 before). On Windows, with the damaged-block
  words taken out and the read's words changed, 4 fail. `compile_runtime.py` 39 of 39 under MSVC, clang-cl,
  llvm-mingw, android-x86_64 and android-arm64; `soa.exe` relinked, the self test 0 failures and `title` 4 of 4;
  `test_android_jni.py` holds the new lookup of the box.
- **Checked on the emulator** [V], on the APK built with it (`fbaa0f3d…`):
  - **The self test:** 0 failures.
  - **A check run** with `SOA_DISC_FLIP=sound/tone.info` logs the block line, then `[android] box: The game
    stopped. / GEAE8P.soadisc is damaged: the part of it holding sound/stv73.samp, sound/tone.info is not what was
    stored there; copy it to this phone again, or make it again on your PC.` and `[exit] 9`, and `disc.txt` stays.
  - **A player's launch** (no extras) with one byte of the staged store in Download really damaged, the low bit at
    file offset 1427257576 (0x551238E8: the payload's 0xF5000 plus disc offset 0x5502E8E8, in `sound/tone.info`),
    stopped at the game's first frame and showed the box on a black screen, in those words and "When you open the
    app again, it asks for the disc." (captured as `build/android-review/stopped-box.png`, local); `dumpsys
    window` showed no window holding the screen on while it waited. Close ended the run `[exit] 9`, and
    `no_backup/` held the library alone. The byte was put back and the store's SHA-256 matched the PC's; the next
    launch asked for the disc (a check run answers Pick, finds no pick and cancels, `[exit] 1`); and a real pick
    read it in place, `disc.txt` back, one grant held.
  - **The mutation,** on the first version: an APK whose `finish()` never calls the box logs the block line and
    `[exit] 9`, and no box.
- **Not measured:** a damaged copy the app made, and its removal (the emulator has no room for a second 1.4 GB
  store); the read-failure box on the device (no storage was pulled; the disc check holds the words for an ISO cut
  while open, not for a cut store); the out-of-memory stops; and the screen held on with the first version, which
  this measurement has nothing to compare with.
- **The words wait for the owner's look**, with the import's, on `build/android-review/index.html`.
- **The tests** are unchanged in number: 1435 in 89 files.

**R5's gate, and a push held to its size.** 2026-10-07.

- **What it is:** before designing R5's own Android sysroot (D-31), the one question every design rested on: does
  Android's loader run a game library built by llvm-mingw's clang instead of the NDK's? Five readers mapped the
  specs, the toolchain, what the library needs, what llvm-mingw does with a foreign sysroot, and the upstream
  sources (scratchpad `r5_map.md`). The library needs 32 of bionic's headers, the four C-library names of
  `config/seam.txt` it calls (`setjmp`, and `crtbegin_so.o`'s `__cxa_atexit`, `__cxa_finalize` and
  `__register_atfork`), and no compiler runtime; llvm-mingw, which carries no Android compiler-rt, links it once
  `-nodefaultlibs` is given with `-lm -ldl -lc` after the objects.
- **The library** [V]: from `gen/android-x86_64`'s C with its real `disc_sys.c`, compiled by llvm-mingw 20260922
  (clang 23.1.2) against a sysroot made only from bionic's sources at `android-17.0.0_r1`: the 32 headers,
  `crtbegin_so.o` and `crtend_so.o` built from bionic's source by the same clang, and stubs of `seam.txt`'s names
  with the version `LIBC`. 21 units in 38.9 s on 16 threads, linked in 0.3 s, 33,996,192 bytes. `elfcheck.py` with
  the phone's settings passes it, as it does the NDK's; the same `DT_NEEDED` and the same 42 imports, 4 from the C
  library at `LIBC`. It differs from the NDK's build in its relocations, packed (`DT_RELR` and `DT_ANDROID_RELA`,
  clang 23's default from API 28) where the NDK's are plain `RELA`, and in a 4-byte ident note (the API level)
  where the NDK's is 132.
- **On the emulator** [V], pushed over the NDK's library with `push-game`: its `[game]` record line, the self test
  0 failures, `android.py replay --threads 1,2,3,8` 23 of 23, and `title` 4 of 4 over 2000 frames, reading the
  imported store in place (`SOA_IMPORT=1`). The NDK's library was put back after (`c0046416…`). So the route the
  owner chose (D-34 to D-36, PLAN-NEXT §0) is the one measured.
- **What it found:** the first title run stopped at boot: `[boot] extracted/disc.iso: its file table puts
  sound/b7022300_R.dsp at 0x491FACA4 (+48050 bytes), and the image ends at 0x49206000: a truncated dump or copy?`.
  L12d's new check was right. The ISO `push-disc` had put back at the end of L12d's session was 1,226,858,496 of
  1,459,978,240 bytes, with no error then, and HANDOFF had recorded it as restored. A push needs the file's size
  free twice, in `/data/local/tmp` and then in the app's storage, and the store staged in Download left too
  little. `tools/android.py`'s `put()` now holds every push to its size (`stat -c %s`), refusing with both sizes;
  `test_android_tool.py` has the case, and with the check taken out it fails. The short ISO was removed (2.4 GB
  free); a check on the emulator that reads a disc runs with `SOA_IMPORT=1`.
- **Not measured:** an arm64 library built this way (the Thor's, D-36), and a library built by `recompile.py`
  itself, which R5 makes take this route.
- **The tests** are 1436 in 89 files, measured four ways: 1395 passed and 41 skipped here; 1376 and 42
  without capstone; 986 and 450 without MSVC; 967 and 451 without either. The full run took 784.73 s.

**R5-0: the package builds again, and carries the commit's bytes.** 2026-10-07.

- **What it is:** the first slice of R5's design, settled the same day after four adversarial reviews and committed
  with this entry as `docs/specs/android-sysroot.md`, which owns R5's slices from now on (PLAN-NEXT §0). It fixes
  two defects in the player's package that those reviews found, before R5 builds on the package.
- **A package's build stopped at an import** [V]: `recompile.py` has imported `fetch_sdl` at its top since L10
  (d6d64aa), and `package.TOOLS` never gained it, so the `recompile.py` a package's `player_build.py` starts stopped
  at that line. R4's commit (0223b3a) came before L10, so its Done held; every package staged after L10 and before
  this entry could not build. `TOOLS` now holds `fetch_sdl.py`. `test_the_staged_tools_import_what_the_build_imports`
  stages `source/` through `package.stage_source`, now factored out of `stage()`, then imports what the build runs
  (`player_build`, `recompile`, `extract`) and every module `TOOLS` stages from it, with `-I -S` from the test's own
  folder, under the package's own python where `vendor/` has its zip and else under this one; any module loaded from
  outside the stage but the interpreter's own library fails it. With `fetch_sdl.py` taken out of `TOOLS` it fails,
  `ModuleNotFoundError: No module named 'fetch_sdl'`, under the embeddable CPython and under this PC's python alike.
- **A package CI made did not carry the commit's `baked=`** [V]: GitHub's Windows runner checks out with
  `core.autocrlf true`, which Git for Windows sets system-wide (its log: `file:C:/Program Files/Git/etc/gitconfig
  true`; this PC's own `.gitconfig` overrides it), the repository has no `.gitattributes`, and `inputs_record`
  hashed raw bytes. The zip CI drafted at 0223b3a, which a review found and this entry measured again: its
  `tools/recompile.py` is 25,436 bytes with 589 CRLF, git's 24,847 with none, and 10 of its 18 baked files differ
  from the commit's, so its digest would be dc23fd1df793 where the commit's is 862f5c24caf4. Since L12a (75d5ce2),
  after that zip, every build's record carries the digest (recompile.py writes `game_table.c` "in every build"),
  and from R5 a phone refuses a library whose `baked=` is not its APK's. Now:
  - `player_build.inputs_record` reads each file with CRLF as LF. `test_the_baked_digest_reads_crlf_as_lf`: two
    trees, one LF and one CRLF, give one record, and a changed line still moves it; with the raw read put back it
    fails.
  - `release.yml` sets `core.autocrlf false` before checking out, and prints where each setting comes from.
  - `python tools/package.py check <package folder> [--commit REV]` holds a package's baked inputs to the commit's,
    read by `git ls-tree` and `git cat-file` with CRLF as LF. `release.yml` runs it over the unzipped package, after
    the package's own python imports `recompile, player_build, extract, decomp, fetch_gpu, fetch_sdl`.
    `test_a_package_s_baked_inputs_are_held_to_the_commit_s` writes a source from `git archive HEAD` of the baked
    inputs (`core.autocrlf false`): it passes, and so it does with every line ending CRLF; a doubled CR (named, with
    "(the checkout converted its line endings?)"), a changed byte, a file missing and one the commit lacks are each
    refused by name. With a check that compares nothing it fails at the doubled CR; with the commit's side read raw,
    at the commit's own files.
- **`baked=` moved on this PC too** [V]: git stores eight of the 18 baked files with CRLF (`config/functions.tsv`,
  `runtime/cpu.h`, `runtime/decomp_swap.c`, `tools/soa/dol.py`, `ppc/cfg.py`, `ppc/isa.py`, `recomp/emit.py`) or
  mixed (`config/trace.txt`), so the digest here went from 705f401d4dcd to 57f744e5121c. The emulator's APK and
  library are now another release's: its next run starts with `android.py build` and `install`, and the library
  rebuilt and pushed.
- **On this PC** [V]: `python tools/package.py stage build\r5-0\P` staged a package in 58 s. Its own CPython 3.14.8
  (`P\python\python.exe -I -c "…import recompile, player_build, extract, decomp, fetch_gpu, fetch_sdl"`)
  imported the build, and `package.py check` printed `baked inputs of …\P\source: 57f744e5121c, and of HEAD:
  57f744e5121c, the same`. With `P\source\tools\recompile.py` rewritten with CRLF ends (39,009 bytes to 39,942)
  it still passed; with `inputs_record`'s normalisation taken out it exited 1, `…\P\source: config/functions.tsv
  is not the commit's (the checkout converted its line endings?)`; with both put back it passed. R2's recipe from
  the package, with `PATH` holding only `P\python`, built the owner's disc into `build\r5-0\R` in 87 s, every
  unit translated again and the GPU backend built in, ending `[build] done soa.exe sha256 6d0c88f9…`; the
  checkout's `tools\player_build.py` built it into `build\r5-0\R2` in 97 s, with the same hash. `build\r5-0` was
  deleted after.
- **On CI** [V]: `release.yml` on a scratch branch at the same tree (run 37661533080, 094a5e6), every step green:
  the settings printed as `file:C:/Program Files/Git/etc/gitconfig true` and `file:C:/Users/runneradmin/.gitconfig
  false`; the tests 1327 passed and 94 skipped in 337.44 s; the package 128,879,786 bytes; `guard.py --tree` over
  its 5541 files; `the build imports`; and `baked inputs of …\soa-094a5e6-windows-x64\source: 57f744e5121c, and of
  HEAD: 57f744e5121c, the same`, the digest this PC's tree gives. Downloaded, the zip's 18 baked files are the
  commit's byte for byte, its `tools/recompile.py` 39,009 bytes with no CRLF. The draft and the branch were deleted
  after; the drafts of c7ca5a2 and 0223b3a are earlier sessions' and stay.
- **What differed from the design's text:** the import test also imports the build's three entry points by name,
  so one dropped from `TOOLS` is still imported, and runs with `-S`, since a package's python has no
  site-packages; the commit-side test writes its source with `git archive` rather than `git show`, and adds the
  doubled-CR, missing and extra cases; and the by-hand CRLF refusal named `config/functions.tsv`, not
  `tools/recompile.py`: stored with CRLF, it sorts first and differs too once the digest reads raw bytes.
- **The tests** are 1439 in 89 files, measured four ways: 1398 passed and 41 skipped here; 1379 and 42
  without capstone; 989 and 450 without MSVC; 970 and 451 without either. The full run took 792.94 s.

**The SDL window test on CI: five reads of the screen, and its log when none shows the frame.** 2026-10-07.

- **What happened** [V]: `test_window_sdl.py` failed in CI's `Runtime compiles (Linux, gcc)` job on R5-0's push
  (run 37666958607) and again on its rerun: `no green on the X screen: the frame was not shown`. R5-0 changed
  nothing the test builds or runs. The same job on 6d5916c, green that morning, passed when run again; the two
  failures ran on runner images 20261004.327.1 and 20260927.320.1, and the test has passed on both. In the
  `soa-l10` container it passed 20 times of 20, and 15 of 15 with every one of its 16 cores kept busy. So it is
  intermittent on GitHub's runners and was not reproduced here.
- **Why it could not be read:** the driver read the X screen once, 30 frames (about a second) after the window
  opened, and the failing assertion printed nothing else, so a present that came late and a frame never shown
  looked the same.
- **The change:** the driver reads the screen five times, at frames 30, 32, 34, 36 and 38, all before
  `SOA_WINDOW_TEST`'s resize at 40, and the test checks the first read that holds the frame's green corner. When
  none does, the failure carries the window's whole log: its renderer, and the `[present]` report of how many
  presents there were and how many failed. In the container it passed 10 times of 10; with the driver's frame
  drawn without its green square, it fails, printing `[window] open at 1x, presenting with SDL3's opengl renderer
  (video x11)` and `[present] … 119 intervals between presents`, `0 failed present(s)`.
- **Not settled:** whether CI's failures were a present later than a second or a frame not shown at all. If it
  fails again, its log says which.

**R5a part 1: R5's Android sysroot, built from bionic's pinned files.** 2026-10-07.

- **What it is:** `tools/fetch_android_sysroot.py` (docs/specs/android-sysroot.md §2), the first half of R5a.
  It builds the phone's C headers and crt objects on every machine that uses them (D-34): 44 files of bionic at
  06356e41 (android-17.0.0_r1), each held to a sha256 and a git blob id, fetched as four directory archives into
  `vendor/android-sysroot-src`; the 30 headers the translated C reads, unmodified, under
  `vendor/android-sysroot/usr/include`; `crtbegin_so.o` and `crtend_so.o` for arm64 and x86_64 built from bionic's
  own source by llvm-mingw's clang, each held to a pinned sha256; and `NOTICE.txt`, each file's own licence words,
  pinned too. `vendor/ANDROID-SYSROOT.sha256` records the 35 files. `tools/soa/toolchain.py` gains llvm-mingw's
  release and clang (`MINGW_RELEASE`, `MINGW_CLANG`), the clang and ld.lld beside the mingw profile's compiler, a
  clang's identity line, and the environment clang reads ahead of a sysroot taken out. Nothing builds the game
  library through it yet: that is part 2.
- **On this PC** [V], with no `vendor/android-sysroot*`: the first run printed the four `fetching
  .../+archive/06356e41.../<dir>.tar.gz` lines and then, exactly, `44 of 44 bionic files the build reads, at
  06356e41 (android-17.0.0_r1), are as pinned`, `built crtbegin_so.o and crtend_so.o for arm64 and x86_64: as
  pinned`, `wrote android-sysroot/NOTICE.txt: as pinned`, `recorded 35 file(s) in vendor/ANDROID-SYSROOT.sha256`,
  in 10.4 s with no 429. Again: `vendor/android-sysroot is there and as recorded (35 file(s) checked)` and no
  request; `--verify`: `35 of 35 recorded Android sysroot file(s) unchanged`. With a byte of `math.h` changed the
  plain run named it and built the tree again from the cache, no request; with the tree deleted, `--offline` did
  the same. A second vendor folder, `build\r5\two, again`, built and verified (it found a bug, below). `--lists`
  fetched the two symbol lists as pinned; `--check-upstream` printed `47 of 47 pins are bionic's own blobs at
  06356e41 (refs/tags/android-17.0.0_r1 is 06356e41)`; `--cache-key` printed `key=b080f95ed440cef5`. The tests,
  `python -m pytest -p noskip tools/tests/test_android_sysroot.py`: 20 passed, none skipped.
- **The first bless, and how each pin was checked** [V]:
  - **The 47 source pins** are the design's table, generated from it rather than retyped and held to the scratch
    copy of bionic at the commit by size, sha256 and blob id (47 of 47), and to bionic's own tree listing by
    `--check-upstream` (47 of 47).
  - **The x86_64 crt objects** are the bytes of the gate's, which ran the game on the emulator (FINDINGS "R5's
    gate").
  - **The arm64 crt objects** were compared with NDK r28c's API-33 ones by `llvm-readelf -S -s -r -n`, as the
    design asked, and differ in more than it predicted. Its expected differences are there: the Android ident note
    (4 bytes of descriptor, the API level, against the NDK's 132, which add the NDK's version) and the `.comment`.
    So are clang 23's unsuffixed mapping symbols (`$x`, `$d` for `$x.1`, `$d.2`) and `crtend_so.o`'s section
    order. The one that is not cosmetic: the NDK's `crtbegin_so.o` carries a `.note.gnu.property` marking it BTI
    and PAC, its functions longer by the branch-protection instructions, and ours neither. It changes nothing in a
    library: a shared object is marked BTI only when every object in it is, neither the NDK's clang nor llvm-mingw's
    marks ordinary code (a one-line function compiled by each for `aarch64-linux-android33` carries no such note),
    and the arm64 game library the NDK built in L12b carries no GNU property at all.
  - **`NOTICE.txt`** (43,194 bytes, 965 lines) was read whole before it was pinned: every shipped and compiled file's
    leading comments under its place, `setjmp.h`'s, `strings.h`'s, `sys/cdefs.h`'s and both `bionic_asm_<arch>.h`'s
    tag lines and licence blocks, `strings.h`'s advertising clause, `math.h`'s Sun notice. One sentence of the
    preface was reworded before pinning. The owner reads it in R5b.
- **A review**, four lenses (the design, correctness, Linux and Windows, the tests' strength), each finding then
  argued against by another reader: 23 confirmed, 2 refuted, all 23 fixed. Among them: the test module failed
  `ruff format --check` after a last edit (CI's Tests job would have gone red on both systems); on GitHub's Windows
  runner a step's exit status is its last command's, so a failed `--lists` hid behind the `--verify` after it (the
  step runs under bash now); a leftover folder another program held, an unreadable record, a `--version` line the
  code page cannot decode and a JSON answer with no `{` each reached the user as a traceback; a connection reset
  mid-body said "cannot reach"; `--verify` said "35 of 35 unchanged" over a record not this script's; and nine
  tests that would have agreed with a broken tool (no pace, `Retry-After` ignored on a 503, files written one
  archive at a time, a check list off its pin, `--from` unchecked, the key over the script's bytes, `ensure()`
  taking a stale record, the identity check untested without llvm-mingw, `--check-upstream` skipping a directory).
  Separately, a relative `--vendor` failed to build: clang runs in the build sysroot's folder, so the cache's path
  is now resolved first.
- **Mutations** [V]: 39, each a defect a check is there for, each failing its check, the files put back byte for
  byte after: the design's list (a pin a digit short, the sha256 or blob check removed, a missing member unnamed,
  no retry, `Retry-After` ignored or its date form unread, no cap, a decode failure not retried, no deadline, a 404
  retried, `--offline` ignored, the cache's own pin check removed, any record taken as there, the unrecorded-file
  walk and the record-to-pins comparison removed, the output pins and the identity check removed, the first
  comment only, the NOTICE's pin check removed, the record deleted last, no retries in the swap, the clean
  environment not passed, the upstream comparison removed, any clang taken as llvm-mingw's) and the review's.
- **On CI** [V]: `ci.yml` on a scratch branch at this tree (run 37712785770): all 12 jobs green. On both
  `android-route` legs, Ubuntu's llvm-mingw and Windows' each printed `clang version 23.1.2 (... 85ac5602...)`,
  fetched the four archives and the two lists with no 429 and no wait, built the crt objects `as pinned` -- so
  the two systems make the same bytes -- verified 35 of 35 and passed the 20 tests with no skip. Ubuntu saved
  the source cache under `android-sysroot-src-b080f95ed440cef5`; Windows' save of the same key failed, with a
  warning only, the key being taken. With `math.h`'s pin one digit off on a second branch (run 37712813356),
  both legs failed at the sysroot step, `error: libc/include/math.h from .../libc/include.tar.gz: sha256
  e50651fa..., pinned f50651fa...`, and at the tests after it, whose three skips `noskip` failed. Not yet seen:
  a run restoring an older cache by its prefix when a pin moves, which needs main's cache, saved by this push's run.
  Both branches were deleted after.
- **What differed from the design's text:** the rebuild line is `vendor/android-sysroot is not as recorded
  (<fact>); building it again from vendor/android-sysroot-src`; the notice heads a file compiled into the crt
  objects `== bionic <path>`, since it has no place in the tree; `check_upstream` also returns how many pins it
  compared, which the 47 line prints; a folder `build()` cannot clear is refused in words like the swap's; and
  `test_mingw.py`'s archive test still skips on this PC (no symbolic links without developer mode), so the Done
  line's "none skipped" holds for `test_android_sysroot.py`.
- **The tests** are 1461 in 90 files, measured four ways: 1420 passed and 41 skipped here; 1401 and 42 without
  capstone; 1011 and 450 without MSVC; 992 and 451 without either. The full run took 1186.10 s, against 792.94 s
  this morning: the new tests take about 10 s of it, and the rest is this PC's load that hour.
