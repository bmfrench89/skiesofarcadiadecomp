# Technical Specification

**Project:** Native PC port of Skies of Arcadia Legends (GameCube, `GEAE8P`)
**Status:** v2 — revised after adversarial review of v1
**Last updated:** 2026-09-15

> **v2 changelog.** v1 was reviewed by six parallel probes and a completeness critic.
> Four of its load-bearing claims were wrong and are corrected here: the graphics
> mitigation (§7), the memory model (§5), the correctness oracle (§8), and the claim that
> no C++ toolchain was installed. Two claims survived with better evidence: the
> no-runtime-loaded-code premise (§3) and the recompile-first architecture (§4).

---

## 1. Goal

A native x86-64 Windows executable that plays Skies of Arcadia Legends at full speed
without an emulator, using assets the user supplies from their own disc dump.
Linux/macOS are secondary; the design must not preclude them.

### Non-goals (v1)

- Bit-exact hardware emulation. We target *observable behavioural equivalence*.
- Supporting other games. Reusable tooling is welcome; generality is never a reason to
  slow the critical path.
- Shipping assets, a DOL, or anything derived from the game binary.
- **The apploader.** The disc carries 116,484 bytes of PowerPC code in Nintendo's
  apploader at disc offset `0x2440`, outside the FST. It exists to load the DOL off a
  physical disc. A native port replaces it wholesale. Explicitly out of scope.

### Definition of done

Credits roll on a save-to-finish playthrough with correct graphics and audio, no emulator
in the process, and a save file that round-trips with a real memory card or Dolphin.

---

## 2. Legal posture

Non-negotiable, applies to every commit:

1. **No game data in the repo.** No disc images, no `boot.dol`, no extracted assets.
   Enforced by `tools/guard.py` in CI, over the full git history, not just the tree.
2. **No generated code derived from the game binary is committed.** Recompiler output is
   a build artifact reproduced locally from the user's own dump. `gen/` is ignored.
3. **Analysis metadata is fine.** Addresses, sizes, symbol names, signature hashes and
   structural offsets are facts about the binary, not copies of it. These live in `config/`.
4. The user runs extraction and build against a disc they own.

---

## 3. Evidence base

Full detail in [FINDINGS.md](FINDINGS.md). Figures marked ▲ were corrected in v2.

| Fact | Value |
|---|---|
| SDK | Nintendo Dolphin SDK `0x2301`, built 2002-09-05 |
| Compiler | Metrowerks CodeWarrior for PowerPC |
| `boot.dol` | 3,166,656 bytes; 2 text + 6 data sections |
| Instruction words in `.text` | 697,784 |
| ▲ Real instructions | **696,120** (1,664 words in `.text0` are data) |
| ▲ Function entry points | **~7,100–7,160** (1,781 never `bl`-called) |
| REL modules | **0** — see §3.1 |
| Symbol map | absent |
| Paired-single arithmetic | 319 |
| Quantized load/store (`psq_*`) | 5,007 |
| ▲ Gekko-only total | 5,326 = **0.76%** of code |
| ▲ GQR values | **static constants**; 97.3% of `psq_*` use GQR0 |
| SDA bases | `r2 = 0x80350000`, `r13 = 0x8034E720` |
| ▲ SDK/runtime block | `0x802319E0`–`0x80266770`, 936 functions, 7.8% of `.text` |
| ▲ Indirect branches | 296 `bctr` (**all** switch tables), 248 `bctrl`, 121 `blrl` |
| ▲ Gather-pipe stores | **414** to `0xCC008000` — see §7 |
| ▲ AKLZ-compressed files | **3,633 of 5,552 (65%)** |
| Audio middleware | none (no MusyX) — custom Sega mixer on `AI`/`AR`/`DSP` |
| ▲ Video mode | **480i only** (NTSC/MPAL/EURGB60), no progressive mode |
| ▲ Host toolchain | **MSVC 14.44, Windows SDK 10.0.26100, cmake, ninja all present** |

### 3.1 Why we believe no code loads at runtime

v1 justified this with "there are no `.rel` files on the disc." That argument was not
sound: 65% of the disc is AKLZ-compressed, so no raw byte scan could see inside it. The
conclusion survived on better evidence:

- **4 `icbi` instructions** in 696,120. PowerPC's instruction cache is not coherent with
  stores, so any runtime-generated code *must* be `icbi`'d before execution. All four sit
  in SDK cache primitives (`ICInvalidateRange`, `DCFlushRange` and friends), and every
  call site targets fixed low-memory exception vectors — never a heap or file-derived
  address.
- **The direct call graph is closed.** Exactly one `bl`/`b` target lands outside mapped
  `.text`, and it is a `bla 0x60` inside an exception-stub *template* that gets copied
  into the vector area — data to be copied, not an unresolved import.
- **No module-loader symbols.** `OSLink`, `OSModule`, `__OSModuleInfo`, `OSUnlink` all
  appear zero times, while assert-retained strings like `DVDOpen` *do* survive — so the
  absence is meaningful, not stripping.
- **~350 MB of decompressed assets contain no PowerPC code.** `tools/validate_assets.py`
  runs this as an exhaustive gate over every container.

One honest caveat: that last test is calibrated on PowerPC code density. It would not see
DSP microcode, a precompiled display list, or SH-4 remnants. The claim is "no PowerPC
code in assets," not "no code."

---

## 4. Architecture: recompile first, decompile progressively

*(This section survived review unchanged in substance.)*

### 4.1 The decision

**Decompilation** yields readable, portable source and costs years — every completed
GameCube decomp took a team 18 months to 6 years, and this game has zero prior work.
**Static recompilation** yields a running binary in months, but an opaque one.

**We do both, in that order, in one codebase.** Recompilation gets the game running.
Decompilation then replaces recompiled functions one at a time without breaking the build.

This works because there are no REL modules: every function has a fixed address known
ahead of time, so every function has a stable identity both paths can bind to.

### 4.2 The unified function binding model

Every function is identified by its virtual address. For each, the build selects exactly
one implementation:

```
                    +-------------------------+
  0x800A1234  --->  |   binding table         |
                    |   (config/symbols.toml) |
                    +-----------+-------------+
                                |  exactly one of:
            +-------------------+-------------------+
            v                   v                   v
    +--------------+   +-----------------+   +--------------+
    | RECOMPILED   |   | HLE             |   | DECOMPILED   |
    | generated C  |   | hand-written    |   | hand-written |
    | from PPC asm |   | native impl of  |   | C/C++ that   |
    |              |   | an SDK function |   | matches mwcc |
    +--------------+   +-----------------+   +--------------+
         default          the 7.8% (§6)         the long game
```

Consequences: the game runs from day one of Phase 4; HLE is opt-in per function; and a
decompiled function can be differentially tested against its recompiled twin at runtime,
giving a second correctness check beyond byte-matching.

### 4.3 Calling convention

```c
typedef struct CpuState CpuState;
void fn_800A1234(CpuState* s);   /* args/returns per PPC EABI in s->gpr[] */
```

`CpuState` carries `gpr[32]`, `fpr[32]` (each a paired single `{double ps0, ps1;}`),
`cr`, `xer`, `lr`, `ctr`, `fpscr`, `gqr[8]`, and — added in v2 — **`hid2`, `wpar`, and
the 32-byte write-gather accumulator** (§7). Omitting those would have made the graphics
path unimplementable.

### 4.4 Why the Gekko numbers matter

At 0.76% Gekko-specific density the CPU translation is contained. Better still, **GQR
state is statically determinable**: the binary installs six constants and never varies
them, and 97.3% of quantized load/stores use GQR0, which is plain `f32`/scale-0 — i.e.
an ordinary pair of float loads with *no* conversion. Only ~135 sites need a
scale-and-convert helper.

**The recompiler therefore needs no runtime GQR dispatch and no GQR shadow register in
the hot path.** Every `psq_*` site specialises at translation time. Building general
dynamic-GQR machinery would be wasted work.

---

## 5. Guest machine model

> v1 said "memory is one flat allocation with `0x80000000` mapped to its base." That is
> wrong and would silently corrupt every DMA buffer and FIFO setup.

The guest address space has four distinct kinds of region:

| Region | Contents | Implementation |
|---|---|---|
| `0x80000000`–`0x817FFFFF` | MEM1, 24 MB cached window | backing store |
| `0xC0000000`–`0xC17FFFFF` | **uncached alias of the same DRAM** | *same* backing store, different view |
| `0x80000000`–`0x800030FF` | OS low memory globals (`__OSCurrentThread` at `0x800000E4`, memory size, console type, exception vectors) | backing store, some fields synthesised at boot |
| `0xCC000000`–`0xCC00FFFF` | hardware MMIO | **trap and dispatch to device models** |

Two rules fall out, both absent from v1:

1. **The cached and uncached windows must alias one allocation.** The game does pointer
   arithmetic in the `0xC0000000` space for DMA buffers and display lists. If they are
   separate arrays, writes vanish.
2. **MMIO must trap, not store.** 428 sites materialise `0xCC00xxxx`/`0xCC01xxxx`
   addresses. A flat array would turn device programming into silent no-ops.

Peripherals to model: CP `0xCC000000`, PE `0xCC001000`, VI `0xCC002000`, PI `0xCC003000`,
MI `0xCC004000`, DSP `0xCC005000`, DI `0xCC006000`, SI `0xCC006400`, EXI `0xCC006800`,
AI `0xCC006C00`, and the write-gather pipe at `0xCC008000` (§7).

`.text0` is **not ordinary code**. It is a ROM image the boot path `memcpy`s into low
memory; its 706 real instructions are position-dependent exception vectors and need
separate handling from `.text1` functions.

---

## 6. The HLE boundary

Phase 2's job is **not** to name game functions. It is to find the code we *delete and
replace* rather than port: the SDK. That block is `0x802319E0`–`0x80266770` — 936
functions, 7.8% of `.text`. Seven point eight percent being deletable is the point, not a
disappointment.

**Method, cheapest first:**

1. **`dtk dol split`** (prebuilt binary, no dependencies) yields ~7,117 function
   boundaries and a correct 12-section split in under a second, plus ~260 SDK names.
   Treat this as a **seed, not an authority** — it is a fast heuristic and its output
   contains artifacts such as 4-byte "functions."
2. **Compile one donor SDK** — `mariopartyrd/marioparty4` is the only confirmed `0x2301`
   banner match — for roughly +89 names. A second donor adds ~8; not worth it.
3. **Harvest self-naming diagnostic strings** for ~87 more. Note this vector was
   over-estimated in v1: it yields 8 SDK names, not the 100+ hoped for.

**Address analysis requires CFG-aware constant propagation.** mwcc materialises addresses
through per-translation-unit pooled base registers and the `r2`/`r13` small-data bases.
Peephole `lis`/`addi` matching misses most references. This is a correctness requirement
for Phases 1 and 3, not an optimisation.

---

## 7. Graphics: the write-gather pipe is unavoidable

> v1's mitigation — "HLE at the GX API level rather than parsing the FIFO" — is **false**,
> and this was the single most dangerous error in the document.

`GXBegin`, `GXPosition3f32`, `GXColor1u32`, `GXTexCoord2f32` and the rest of the
vertex-submission family are SDK **inline** functions. They compile *into the caller* and
store directly to the write-gather pipe. **You cannot intercept a function that was
inlined away.**

The evidence: **414 stores whose effective address is `0xCC008000`** (`stw` 241, `stb`
180, `stfs` 50, `sth` 31), and of 256 sites materialising a `0xCC01xxxx` base, **103 are
outside the SDK block** — in engine code that `dtk` leaves as `fn_XXXXXXXX`.

So the runtime must implement:

- **A real write-gather pipe.** `HID2[WPE]` enables it; `WPAR` holds the target address;
  it accumulates in 32-byte granules and the SDK flushes with dummy-write padding. A
  naive "store to MMIO calls a handler" model loses partial gathers and mis-orders bytes.
- **A GX command-stream decoder** over the gathered output: CP/XF/BP register writes plus
  primitive vertex data.

A hybrid remains viable and is the working plan: HLE the non-inline `GXSet*` state calls,
and parse only the vertex stream coming through the pipe. Phase 5 is gated on this, not
on symbol recovery.

**Rendering ground truth** comes from Dolphin FIFO logs (`.dff`): a recorded GX command
stream plus the memory it references, replayable offline against our backend and
diffable against Dolphin's output. This gives frame-level validation *before the game
runs at all*, and a permanent regression corpus.

---

## 8. Correctness strategy

> v1 declared "Dolphin can emit a per-instruction register trace" and built the whole
> debugging plan on it. It cannot, in the form v1 assumed.

**Primary oracle: an in-process lockstep differ against our own reference interpreter.**
A C interpreter over the same `CpuState` and the same decode tables as the recompiler,
sharing the runtime's memory and HLE. Both run from one entry state; compare `CpuState`
per basic block, then re-run a failing block instruction by instruction. No trace files,
O(1) storage, failures reported as "fn `0x800A1234`, insn 17, r7 = X expected Y."

This is circular on its own — two of our components agreeing proves nothing about real
hardware — so it is anchored by three external sources:

- **Dolphin save states**: a complete CPU + MEM1 + ARAM snapshot at an arbitrary point,
  as a checkpoint fixture.
- **Dolphin FIFO logs**: GPU-side ground truth (§7).
- **Dolphin BranchWatch**: a supported export of observed indirect-branch targets.

Determinism is a precondition: identical initial state, identical inputs, identical event
schedule. That forces the threading decision (§12).

---

## 9. Asset formats, and why they are off the critical path

The disc is ~70% asset data in undocumented Sega formats:

| Format | Scale |
|---|---|
| AKLZ container | 3,633 of 5,552 files |
| `NMLD` (`.mld`) | 1,791 files, 1,069 MB |
| GVR textures | ≈100,000 disc-wide (CMPR 62%, INDEX4 22%, RGB5A3 16%) |
| Ninja `NJCM` models / `NJTL` texture lists | ≈23,000 — Dreamcast lineage |
| `AFNT` font | `FontData.US`, 83 KB |
| `.sct` scripts | 258 files — **the engine is script-VM driven** |

**None of it is on the critical path, and that is a decision, not an oversight.** In
static recompilation the game's own recompiled code parses `.mld`, walks `NJCM`, and
hands already-GC-tiled pixel data to `GXInitTexObj`. We never need to understand these
formats to render them. We would only need them to *modify* content.

The one exception is **AKLZ, which we implement now** — not for rendering but for
*observability*. Without it we cannot tell whether the bytes we served a read are the
bytes the game expected, and we cannot write a single content-level test.

Corollary: delete "plus Sega `.gvr`" from the texture-decode slice. If we sit at the GX
boundary we see GX format enums and tiled data, never a GVR header.

---

## 10. Components

```
tools/soa/           Python analysis + recompiler
  rvz.py             RVZ container decoder                       [done]
  dol.py             DOL section parsing                         [done]
  disc.py            FST walk, file extraction                   [done]
  aklz.py            AKLZ LZSS container                         [done]
  ppc/               Gekko disassembler, CFG, call graph         [decoder done]
  sigs/              SDK signature build + match
  recomp/            PPC -> C code generator
config/              symbols.toml, hooks.toml, splits  (metadata only)
runtime/             C++ runtime: memory map, MMIO, OS/DVD/PAD/CARD HLE
gfx/                 write-gather pipe, GX command decoder, TEV shader gen
audio/               AI/ARAM/DSPADPCM, Sega mixer
gen/                 generated C  (build artifact, never committed)
```

| Layer | Choice | Rationale |
|---|---|---|
| Analysis & recompiler | Python 3.14 | installed; `compression.zstd` built in |
| Generated code | C | compiles fast at this volume |
| Runtime | C++20 | MSVC 14.44 already present |
| Graphics | SDL3 + Vulkan | explicit control over TEV translation |
| Build | CMake + Ninja | both already present under VS BuildTools |

**Install burden is misallocated, not underestimated.** Phase 3 needs nothing new.
Phase 5 carries the real burden and it is undeclared: Vulkan SDK, plus a shader compiler
in the build (`glslang`/`shaderc`) and SDL3 — a vendoring decision no document has made.
Dolphin-from-source (Qt + full CMake tree) is needed for FIFO capture and is unbudgeted.

---

## 11. Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Indirect branches unresolvable statically | ~~High~~ **Low** | Measured: 296/296 `bctr` are switch tables; 320 tables / 5,721 entries recovered; only 24 of 544 sites vtable-shaped; target set closed within `boot.dol`. No interpreter fallback needed. |
| R2 | SDK identification yields too little | ~~High~~ **Medium** | `dtk` gives ~260 names free; one donor SDK adds ~89. Reframed: the goal is the 7.8% HLE boundary, not naming game code. |
| R3 | Custom Sega audio engine | **Medium → TBD** | **Open.** If Sega ships custom DSP microcode, Phase 6 becomes "write a GameCube DSP interpreter" and this goes High. Probe in flight. |
| R4 | GX translation | ~~Medium~~ **High** | Vertex submission is inlined into game code and cannot be HLE'd (§7). Requires write-gather pipe + command-stream decoder. Validated against Dolphin FIFO logs. |
| R5 | Self-modifying code | **Low** | 7 runtime-codegen sites exist, all confined to the MetroTRK debug stub; stub it out. |
| R6 | Timing assumptions | **Medium** | Game is 480i-only and retrace-driven at 59.94 Hz. Pacing is the main loop, not an afterthought. |
| R7 | Analysis paralysis | **High** | Milestones are demoable, not percentage-based. |
| R8 | **New:** correlated bug between recompiler and reference interpreter | **Medium** | Share field extraction only, never semantics. Write interpreter semantics from the 750CL manual independently of the C emission templates. Anchor with Dolphin fixtures. |
| R9 | **New:** `extracted/` is not a faithful DVD | **Medium** | RVZ junk runs are zero-filled. Games routinely over-read past a file's declared end. Slice 0.5 is a correctness dependency of DVD HLE, not optional. |
| R10 | **New:** byte-swap strategy is irreversible | **Medium** | Swap-on-access vs byte-swapped backing image must be decided *and measured* before 696,120 instructions of C exist. |

---

## 12. Decisions

**Settled in v2:**

- **Threading: fibers.** The lockstep differ is worthless against a nondeterministic
  build, and only fibers give an identical event schedule. This was "leaning" in v1; the
  correctness strategy forces it.
- **Graphics is gated on the FIFO model, not on symbol recovery.**
- **Adopt dtk's split format** for decomp compatibility — cheap now, expensive to retrofit.

**Still open:**

- **DSP microcode: stock or custom?** Probe in flight. Changes R3 and the shape of Phase 6.
- **Byte-swap strategy.** Needs a measurement, not an opinion (R10).
- **The guest-to-host context-switch bridge.** "Fibers" names the host mechanism but not
  how a guest `OSThread` switch — guest stack pointer swap, guest LR restore, and the
  `lmw` GQR0-7 + HID2 + DMAU/DMAL restore at `0x802597D8` — bridges to a host fiber whose
  C stack is mid-`fn_800A1234`. That bridge is the hard part and it needs its own slice.
- **Graphics API.** Vulkan assumed; revisit if TEV translation is simpler elsewhere.
- **Shader-compiler and SDL3 vendoring** (§10).
