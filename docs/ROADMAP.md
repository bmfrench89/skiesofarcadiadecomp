# Roadmap

Work is sliced so that **every milestone is something you can look at**, not a
percentage. Slices inside a phase are ordered by dependency; where they are
independent it is noted.

**Size key:** `S` = a session · `M` = a few sessions · `L` = weeks · `XL` = months

**Status key:** `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

---

## Milestones

| | Milestone | Gated by | What you can see |
|---|---|---|---|
| **M1** | Function inventory | Phase 1 | Exact function count, call graph, the real shape of the program |
| **M2** | SDK boundary known | Phase 2 | A symbol map we generated ourselves — the platform layer is named |
| **M3** | Whole DOL translates | Phase 3 | 697,784 instructions become C that compiles clean |
| **M4** | CPU verified correct | Phase 4 | Game code executes, matching Dolphin instruction for instruction |
| **M5** | First frame | Phase 5 | Something the game drew, in a window |
| **M6** | Title screen | Phase 5 | The actual title screen, correct |
| **M7** | Audio | Phase 6 | Music and SFX |
| **M8** | Playable | Phase 7 | Field movement, battles, saves |

---

## Phase 0 — Foundation `[~]`

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **0.1** RVZ container decoder | S | Decodes zstd groups + RVZ run packing; exact reads verified against disc header |
| `[x]` | **0.2** DOL parser | S | Sections, entry, BSS parsed; totals match |
| `[ ]` | **0.3** Disc extractor | S | Walks FST, writes all 5,552 files to `extracted/`; sizes match FST exactly |
| `[ ]` | **0.4** Repo scaffold + CI | S | `.gitignore` blocks game data; CI fails if a DOL/ISO/asset is ever committed |
| `[ ]` | **0.5** Junk-run regeneration (lagged Fibonacci) | S | Optional. Only needed for byte-exact whole-disc rebuild; real file data is already exact without it |

**Exit:** the disc is fully unpacked and reproducible from the user's own dump.

---

## Phase 1 — Static analysis `[ ]` → **M1**

The goal is to stop estimating and know exactly what is in the binary.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **1.1** Gekko disassembler | M | Decodes all 697,784 instructions with zero unknowns. Full PPC 750CL: integer, float, branch, SPR, **paired singles**, **`psq_*` quantized load/store** |
| `[ ]` | **1.2** Function boundary detection | M | CFG from entry + `bl` targets + prologue scan. Outputs function list with exact start/end. Resolves the 5,375 vs 8,024 ambiguity |
| `[ ]` | **1.3** Call graph + indirect branches | M | Direct call graph; enumerate every `bctr`/`bctrl` site and classify (jump table, vtable, function pointer). **Feeds R1.** |
| `[ ]` | **1.4** Data classification | M | Partition data sections into: vtables, jump tables, float/double pools, strings, static initializers |
| `[ ]` | **1.5** Symbol database | S | `config/symbols.toml` schema: address, size, name, source (auto/sig/manual), binding. dtk-format compatibility decision made here |

**Exit / M1:** exact function count, complete call graph, every indirect branch site
catalogued. This is the first point where the project's real size is known rather than
estimated.

---

## Phase 2 — SDK identification `[ ]` → **M2**

The highest-leverage phase. See SPEC §5.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **2.1** Harvest reference decomps | S | Clone MP4, Animal Crossing, Pikmin into `vendor/` (gitignored). Locate their SDK object sets |
| `[ ]` | **2.2** Build mwcc toolchain | M | Metrowerks compiler running well enough to build SDK objects from the reference decomps |
| `[ ]` | **2.3** Signature generator | M | Normalize functions (mask relocations + address operands), emit hashes. Self-test: signatures from MP4 must match Animal Crossing's copy of the same SDK function |
| `[ ]` | **2.4** Match against Skies DOL | M | Ranked match report. **Target: 1,000+ identified functions.** |
| `[ ]` | **2.5** Triage and seed symbols | M | Manual confirmation of matches; populate `config/symbols.toml` |

**Exit / M2:** the platform layer is named. We effectively have the symbol map the disc
never shipped.

> **Decision point.** If 2.4 yields under ~300 functions, fall back to manually
> identifying only the ~40 SDK entry points that gate a first frame (`OSInit`,
> `GXInit`, `VIInit`, `DVDRead*`, `PADRead`, the `GXSet*` family). Slower, still viable.

---

## Phase 3 — Recompiler `[ ]` → **M3**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **3.1** CPU state model + codegen skeleton | M | `CpuState` struct, ABI per SPEC §4.3, emitter framework, one hand-picked function translates and compiles |
| `[ ]` | **3.2** Integer, branch, load/store | M | Covers ~85% of the binary by instruction count. Unit-tested per opcode against known vectors |
| `[ ]` | **3.3** Floating point + FPSCR | M | Scalar FP incl. FMA, `fres`/`frsqrte` estimates, rounding modes. ~8% of the binary |
| `[ ]` | **3.4** Paired singles + GQR | S | The 320 `ps_*` and 5,006 `psq_*` instructions. Small but exacting — GQR scale/type decoding must be exact |
| `[ ]` | **3.5** Indirect branch dispatch | M | Address to function table; every `bctr` site from 1.3 resolves or traps loudly |
| `[ ]` | **3.6** Whole-DOL translation | M | All 697,784 instructions emit C. Compiles clean. Measure build time and binary size |

**Exit / M3:** the entire game binary exists as compilable native C.

---

## Phase 4 — Runtime and correctness `[ ]` → **M4**

> **4.2 is scheduled before the HLE work on purpose.** Everything downstream depends on
> trusting the CPU translation, and blind debugging is what kills these projects.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **4.1** Memory map + boot | S | 24 MiB MEM1 at `0x80000000`, stack, entry at `0x80003140`, runs until first unimplemented call |
| `[ ]` | **4.2** Dolphin differential tracer | M | Dolphin trace vs. our trace, auto binary-search to first divergence. **The debugging oracle.** |
| `[ ]` | **4.3** OS HLE | L | Threads (fibers per SPEC §9), alarms, interrupts, arena allocator, `OSReport` to console |
| `[ ]` | **4.4** DVD HLE | M | `DVDOpen`/`DVDReadAsync`/`DVDChangeDir` against `extracted/`. Async completion callbacks fire correctly |
| `[ ]` | **4.5** PAD input | S | SDL3 gamepad to `PADRead` struct |
| `[ ]` | **4.6** CARD saves | M | Memory card emulation to a host file |

**Exit / M4:** real game code executes, verified instruction-for-instruction against
Dolphin. The CPU is no longer a suspect.

---

## Phase 5 — Graphics `[ ]` → **M5**, **M6**

Largest subsystem. Depends on M2 — HLE at the GX API level is only possible once SDK
functions are identified.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **5.1** GX state tracking | L | Intercept the `GXSet*` family, maintain shadow state. Log a full frame of GX calls |
| `[ ]` | **5.2** Texture decode | M | All GX formats (I4/I8/IA4/IA8/RGB565/RGB5A3/RGBA8/CMPR/C4/C8/C14X2) **plus Sega `.gvr`** |
| `[ ]` | **5.3** Vertex pipeline | L | Vertex descriptors, attribute formats, display lists, primitive assembly to Vulkan buffers |
| `[ ]` | **5.4** TEV shader generation | XL | Up to 16 TEV stages + indirect textures to generated SPIR-V. The single biggest piece of work in the project |
| `[ ]` | **5.5** EFB/XFB and copies | L | Framebuffer, copy-to-texture, VI scanout |

**M5** lands mid-5.3 (first geometry on screen). **M6** needs all five.

---

## Phase 6 — Audio `[ ]` → **M7**

Deliberately deferred until the game is visually running. No MusyX, so no reference
implementation exists — this is original reverse engineering.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **6.1** AI/ARAM HLE | M | ARAM as a host buffer, DMA, audio interrupt timing |
| `[ ]` | **6.2** DSPADPCM decode | S | Standard Nintendo ADPCM. Well documented, low risk |
| `[ ]` | **6.3** Sega mixer RE | L | Reverse the custom engine driving `AI`/`AR`/`DSP`. The unknown |
| `[ ]` | **6.4** Streamed BGM | M | Stereo `.dsp` pairs stream and loop correctly |

---

## Phase 7 — Playable `[ ]` → **M8**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **7.1** Title to field | M | New game starts, field scene renders and is navigable |
| `[ ]` | **7.2** Battle system | M | Encounters run start to finish |
| `[ ]` | **7.3** Ship/overworld | M | Airship sections work |
| `[ ]` | **7.4** Playthrough hardening | XL | The long tail. Save/load parity, every scene, every cutscene |
| `[ ]` | **7.5** Enhancements | M | Widescreen, uncapped framerate, higher internal resolution |

---

## Phase 8 — Progressive decompilation `[ ]` *(parallel, ongoing)*

Runs alongside Phases 5-7 once M3 lands. Never blocks the critical path.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **8.1** dtk-compatible splits | M | Split config the wider GC decomp tooling understands |
| `[ ]` | **8.2** mwcc build pipeline | M | Hand-written C compiles to byte-matching objects |
| `[ ]` | **8.3** Function swap-in harness | M | Swap a decompiled function for its recompiled twin; differential test proves equivalence |
| `[ ]` | **8.4** Decomp grind | XL | Function by function, indefinitely |

---

## Critical path

```
0.3 -> 1.1 -> 1.2 -> 1.3 -> [M1]
                      |
                      +-> 2.1..2.5 -> [M2] ------+
                      |                          |
                      +-> 3.1..3.6 -> [M3]       |
                                       |         |
                                 4.1 -> 4.2 -> [M4]
                                                 |
                                       5.1 .. 5.5 -> [M5][M6]
                                                 |
                                       6.x -> [M7] -> 7.x -> [M8]
```

Phases 2 and 3 are **independent** and can proceed in parallel. Phase 2 gates
graphics; Phase 3 gates everything running at all.

---

## Immediate next actions

1. **0.3** — extract the disc (needed by everything)
2. **1.1** — Gekko disassembler (the foundation of all analysis)
3. **1.2** — function boundaries → **M1**

Everything through M1, and most of M2, needs only Python 3.14, git and gh — all
already installed. The C++ toolchain (MSVC/clang, CMake, Ninja, Vulkan SDK) is not
required until Phase 3.
