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
