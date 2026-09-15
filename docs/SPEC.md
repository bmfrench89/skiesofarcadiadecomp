# Technical Specification

**Project:** Native PC port of Skies of Arcadia Legends (GameCube, `GEAE8P`)
**Status:** Draft v1 — Phase 0
**Last updated:** 2026-09-15

---

## 1. Goal

Produce a native x86-64 Windows executable that plays Skies of Arcadia Legends at
full speed without an emulator, using assets the user supplies from their own disc
dump. Linux/macOS are secondary targets; the design must not preclude them.

### Non-goals (v1)

- Bit-exact hardware emulation. We target *observable behavioral equivalence*, not
  cycle accuracy.
- Supporting other games. The tooling should be reusable, but generality is never a
  reason to slow the critical path.
- Shipping assets, a DOL, or anything derived from the game binary.

### Definition of done

Credits roll on a save-to-finish playthrough with correct graphics and audio, and no
emulator in the process.

---

## 2. Legal posture

Non-negotiable, applies to every commit:

1. **No game data in the repo.** No disc images, no `boot.dol`, no extracted assets,
   no ripped textures. Enforced by `.gitignore` and CI.
2. **No generated code derived from the game binary is committed.** Recompiler output
   is a build artifact, reproduced locally from the user's own dump. `gen/` is ignored.
3. **Analysis metadata is fine.** Function addresses, sizes, symbol names, signature
   hashes and structural offsets are facts about the binary, not copies of it. These
   live in `config/`.
4. The user runs extraction and build against a disc they own. This is the same model
   as Ship of Harkinian, Dusklight, and every other port in the scene.

---

## 3. Evidence base

Full detail in [FINDINGS.md](FINDINGS.md). The decisions below rest on these measured
facts:

| Fact | Value |
|---|---|
| SDK | Nintendo Dolphin SDK `0x2301`, built 2002-09-05 |
| Compiler | Metrowerks CodeWarrior for PowerPC |
| `boot.dol` | 3,166,656 bytes; 2 text + 6 data sections |
| Code | 2,791,136 bytes = **697,784 instructions** |
| REL modules | **0** |
| Symbol map | **absent** |
| Paired-single arithmetic | 320 instructions |
| Quantized load/store (`psq_*`) | 5,006 instructions |
| Gekko-only total | 5,326 = **0.76%** of code |
| Unique `bl` targets | 5,375 |
| Stack-frame prologues | 5,330 |
| `blr` returns | 8,024 |
| RAM footprint | 3.3 MiB of 24 MiB MEM1 |
| Audio middleware | none (no MusyX) — custom Sega mixer on `AI`/`AR`/`DSP` |
| Texture format | `.gvr` (Sega, Dreamcast PVR lineage) |

---

## 4. Architecture: recompile first, decompile progressively

### 4.1 The decision

Two paths exist, and the usual framing treats them as mutually exclusive:

- **Decompilation** yields readable, moddable, portable source. It also costs years.
  Every completed GameCube decomp took a team 18 months to 6 years, and this game has
  *zero* prior work — the one public repo is a single-commit scaffold from May 2025
  with no functions done.
- **Static recompilation** yields a running binary in months, but an opaque one.

**We do both, in that order, in one codebase.** Recompilation gets the game running
and gives us a correctness oracle. Decompilation then replaces recompiled functions
one at a time, without ever breaking the build.

This is viable here specifically because there are no REL modules. Every function has
a fixed address known ahead of time, so every function has a stable identity that both
paths can bind to.

### 4.2 The unified function binding model

This is the core idea the whole project hangs on.

Every function in the DOL is identified by its virtual address, e.g. `0x800A1234`.
For each one, the build selects exactly one implementation:

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
         default          SDK boundary          the long game
```

All three share one calling convention (§4.3), so they are freely interchangeable at
link time.

**Consequences that make this worth it:**

- **The game runs from day one of Phase 4**, long before anything is readable.
- **HLE is opt-in per function.** We replace `GXSetTevOp` with a native implementation
  without touching anything around it.
- **Decomp gets a runtime oracle.** Normally a decompiled function is verified only by
  byte-matching the compiler output. Here we can *also* run the game with the
  recompiled version and the decompiled version and diff observable behavior. Two
  independent correctness checks instead of one.
- **Progress is continuously shippable.** There is no big-bang integration.

### 4.3 Calling convention

Generated and hand-written code share one ABI:

```c
typedef struct CpuState CpuState;
void fn_800A1234(CpuState* s);   /* args/returns per PPC EABI in s->gpr[] */
```

The state struct carries `gpr[32]`, `fpr[32]` (each a paired-single
`{double ps0; double ps1;}`), `cr`, `xer`, `lr`, `ctr`, `fpscr`, and the 8 `gqr[]`
quantization registers. Memory is one flat allocation with `0x80000000` mapped to its
base; loads and stores byte-swap.

An HLE or decompiled function reads its arguments from `s->gpr[3..10]` / `s->fpr[1..8]`
and writes its return to `s->gpr[3]`, exactly as the recompiled version would. Wrapper
macros hide this for readability.

### 4.4 Why the Gekko numbers matter

At **0.76%** Gekko-specific density, the CPU translation is a contained problem. Of
those 5,326 instructions, 5,006 are `psq_l`/`psq_st` — quantized load/store, which are
mechanically a normal load plus a scale-and-convert driven by a `GQR`. Only **320** are
true paired-single SIMD arithmetic. There is no evidence of locked-cache DMA idioms.
This is the payoff of the game being an SH-4 port rather than an engine written
natively for Gekko.

---

## 5. The SDK signature strategy

The missing symbol map is the project's biggest gap, and there is now a way to close
most of it that did not exist two years ago.

**Premise:** every GameCube game statically links the same Nintendo Dolphin SDK. As of
2026, six GameCube titles have 100% byte-matching decompilations. Their repos therefore
contain byte-exact reconstructed source for `OS`, `DVD`, `GX`, `PAD`, `VI`, `AI`, `AR`,
`MTX`, `CARD` and the rest.

Skies was built with SDK `0x2301` (September 2002). Two reference decomps are from the
same year and should be near-identical:

| Reference | Year | Functions | Decomp |
|---|---|---|---|
| Mario Party 4 (`mariopartyrd/marioparty4`) | 2002 | 10,986 | 100% |
| Animal Crossing (`ACreTeam/ac-decomp`) | 2002 | 20,288 | 100% |
| Pikmin (`projectPiki/pikmin`) | 2001 | 8,069 | 100% |
| Melee (`doldecomp/melee`) | 2001 | 19,828 | 100% |
| Twilight Princess (`zeldaret/tp`) | 2006 | 48,107 | 100% |

**Method:** compile the SDK objects from those decomps, normalize each function (mask
relocation operands and address-relative fields so only opcode structure and register
allocation remain), hash it, and match against functions extracted from the Skies DOL.

**Expected yield:** on the order of 1,000–2,000 identified functions — and critically,
they are precisely the functions that must be HLE'd. This converts "no symbol map" into
"no symbol map for the game logic, full symbols for the platform layer," which is the
half that matters for getting a frame on screen.

This is the highest-leverage work in the project and it gates Phase 5. It is scheduled
as early as it can be (Phase 2).

---

## 6. Components

```
tools/soa/           Python analysis + recompiler
  rvz.py             RVZ container decoder                       [done]
  disc.py            FST walk, file extraction
  dol.py             DOL section parsing                         [done]
  ppc/               Gekko disassembler, CFG, call graph
  sigs/              SDK signature build + match
  recomp/            PPC -> C code generator
config/              symbols.toml, hooks.toml, splits  (metadata only)
runtime/             C++ runtime: memory, OS/DVD/PAD/CARD HLE
gfx/                 GX translation, TEV shader generation
audio/               AI/ARAM/DSPADPCM, Sega mixer
gen/                 generated C  (build artifact, never committed)
```

### Technology choices

| Layer | Choice | Rationale |
|---|---|---|
| Analysis & recompiler | Python 3.14 | Already installed; `compression.zstd` built in; iteration speed matters more than throughput |
| Generated code | C | Compiles fast at this volume, no C++ ABI complications |
| Runtime | C++20 | Available everywhere, matches the scene's tooling |
| Graphics | SDL3 + Vulkan | Vulkan for explicit control over TEV translation; SDL3 for windowing/input |
| Build | CMake + Ninja | Standard, and what the reference decomps use |

---

## 7. Correctness strategy

Debugging a recompiled binary blind is the failure mode that kills these projects. The
countermeasure is built early and deliberately (Slice 4.2):

**Differential tracing against Dolphin.** Dolphin can emit a per-instruction register
trace. We emit the same from the recompiled build, then binary-search the first
divergence. Almost every bug becomes "instruction N produced the wrong value in r7,"
which is a five-minute fix instead of a five-day hunt.

This tool is scheduled *before* the OS HLE layer, not after, because everything
downstream depends on trusting the CPU translation.

---

## 8. Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Indirect branches (`bctr`/`blr` through vtables) cannot be resolved statically | High | Address to function dispatch table; C++ vtable analysis in Slice 1.3; interpreter fallback as last resort |
| R2 | SDK signature match yields too few hits (SDK version drift) | High | Three reference decomps spanning 2001-2006; fall back to manual identification of the ~40 functions that actually gate a frame |
| R3 | Custom Sega audio engine has no reference implementation | Medium | Underlying format is standard DSPADPCM; defer all audio to Phase 6, after the game is visually running |
| R4 | GX/TEV translation is the largest single subsystem | Medium | Dolphin's shadergen is a well-documented reference; HLE at the GX API level rather than parsing the FIFO, which M2 makes possible |
| R5 | Self-modifying or runtime-generated code | Low | No RELs; confirm during Phase 1 CFG analysis |
| R6 | Timing assumptions about a 486 MHz CPU | Medium | Turn-based JRPG, far more tolerant than an action title. Defer until observed. |
| R7 | Scope collapse — project stalls in analysis paralysis | **High** | Milestones are demoable, not percentage-based. M1-M4 are all reachable on tooling alone. |

---

## 9. Open decisions

- **Threading model.** `OSThread` to host fibers (deterministic, easier to trace) vs.
  real threads (simpler, but reintroduces nondeterminism into the differ).
  *Leaning fibers.* Decide in Slice 4.3.
- **Graphics API.** Vulkan vs. D3D12 vs. OpenGL 4.6. Vulkan is the current assumption;
  revisit if TEV translation proves simpler on a different target.
- **Whether to adopt dtk's split format** for eventual decomp compatibility. Cheap to
  do early, expensive to retrofit. *Leaning yes.* Decide in Slice 1.5.
