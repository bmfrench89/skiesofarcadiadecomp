# Roadmap

**v3** — restructured after two rounds of adversarial review. See [SPEC.md](SPEC.md) §7–§8
for the findings that moved work around: per-vertex submission is inlined and needs a
write-gather pipe (though the GX *API* survives interception, so no GPU emulator), and the
Dolphin instruction tracer the v1 critical path depended on does not exist.

Work is sliced so **every milestone is something you can look at**, not a percentage.

**Size:** `S` = a session · `M` = a few sessions · `L` = weeks · `XL` = months
**Status:** `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

---

## Milestones

| | Milestone | Gated by | What you can see |
|---|---|---|---|
| **M1** | Function inventory | Phase 1 | Exact function count, call graph, indirect-branch map |
| **M2** | HLE boundary known | Phase 2 | The 7.8% of code we delete instead of port, named |
| **M3** | Whole DOL translates | Phase 3 | 696,120 instructions become C that compiles |
| **M4** | CPU verified correct | Phase 3+4 | Recompiled code matches the reference interpreter, lockstep |
| **M5** | First frame | Phase 5 | Something the game drew, in a window |
| **M6** | Title screen | Phase 5 | The actual title screen, correct |
| **M7** | Audio | Phase 6 | Music and SFX. **Reached in first form:** the AX mixer runs the driver's command lists and the AI DMA plays through waveOut |
| **M8** | Playable | Phase 7 | Field movement, battles, saves that round-trip. **Progress:** New Game, the opening cutscenes, the first battle (won) and free movement in the first field (the Valuan ship's hold, with the minimap) all run; saves not yet |

---

## Phase 0 — Foundation `[~]`

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **0.1** RVZ container decoder | S | Decodes zstd groups + RVZ run packing. Verified against disc header |
| `[x]` | **0.2** DOL parser | S | Sections, entry, BSS. Totals match |
| `[x]` | **0.3** Disc extractor | S | **Done:** 5,552/5,552 files, byte-exact, DOL sha256 matches image |
| `[x]` | **0.4** Repo scaffold + CI | S | **Done:** guard blocks game data in tree *and* full history; tests run without a disc |
| `[x]` | **0.6** AKLZ container decoder | S | **Done:** exhaustive gate — 3,633 containers, 1.98 GiB, 0 failures, 0 PPC code |
| `[x]` | **0.5** Junk-run regeneration (lagged Fibonacci) | M | **Done:** the RVZ reader regenerates every junk run from its 17-word seed with the disc's lagged Fibonacci generator (521/32, forwarded by the run's offset in its 32 KiB sector), so `disc.iso` holds what the drive returns past a file's end. Unit-tested against the generator's invariants; no disc needed |
| `[x]` | **0.7** DSP microcode probe | S | **Done: STOCK.** Audio ucode hashes to `0x4E8A8B21` = Dolphin's stock AX. Positive control validated the method. R3 → Low; slice 6.3 stays L |
| `[x]` | **0.8** Clean-machine reproduction | S | **Done:** `pyproject.toml` `[project]` table with the dev extras, `CONTRIBUTING.md` walking a second contributor from `git clone` to a running game and the tests; `dtk` is optional (names only) and documented rather than fetched |

**Exit:** the disc is fully unpacked, reproducible, and every container is accounted for.

---

## Phase 1 — Static analysis `[~]` → **M1**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **1.1** Gekko disassembler | M | **Done:** 696,144/697,784 words decode. `.text1` at 99.9997%; `.text0` at 30.8% (it is a ROM image of exception vectors with embedded strings and padding). Full paired-single and `psq_*` coverage across all three opcode-4 field widths |
| `[x]` | **1.1b** Decoder cross-validation | S | **Done.** Diffed vs capstone + dtk over all 697,784 words. Six defects fixed, worst mislabelled 19,306 float instructions. Whole-image test now passes |
| `[x]` | **1.2** Function boundary detection | M | **Done.** 7,166 functions recovered; cross-checked against dtk's 7,117 with **99.77% size agreement** and 99.70% `.text` coverage. 62 ours-only / 13 dtk-only, the latter almost entirely the MetroTRK debug stub reached only via `rfi`/vectors. Handles the 1,781 never-`bl`-called functions (data-pointer + gap seeding) and frameless leaves |
| `[x]` | **1.3** Jump tables + indirect branches | M | **Done (jump tables).** 296/296 `bctr` resolved as switch tables by backward def-chain tracking of the mwcc idiom, including the four whose bound check is a conditional return (`bgtlr`); targets become intra-function successors, not entries. Full `bctrl`/`blrl` classification and the `bla 0x60` special case remain |
| `[ ]` | **1.4** Data classification | M | Partition `.data0..5` **and `.text0`** into vtables, jump tables, float pools, strings, static initialisers. Reconcile the disagreement over whether jump tables live only in `.data3` or also `.data4` |
| `[x]` | **1.5** Symbol database | S | **Done.** `config/symbols.txt` (dtk format, 16,531 symbols) and `config/functions.tsv` (per-function metadata). 249 functions carry real names from dtk's SDK signature database; the rest are `fn_XXXXXXXX`. C identifiers are always `fn_`; pretty names are display-only so `exit`/`__start` never collide |
| `[ ]` | **1.6** Constant-propagation engine | M | **Correctness requirement, not an optimisation.** mwcc materialises addresses through per-TU pooled base registers and the `r2`/`r13` SDA bases. Peephole `lis`/`addi` matching misses most references. Needed by 1.3, 1.4, and all of Phase 3 |

**Exit / M1:** exact function count, complete call graph, every indirect branch classified.

> **On dtk's numbers.** `dtk dol split` produces ~7,117 boundaries in 0.45s and is worth
> running immediately. It is a **seed, not an authority** — it is a fast heuristic and its
> output contains artifacts such as 4-byte "functions." M1 says *exact*; dtk is not.

---

## Phase 2 — HLE boundary `[ ]` → **M2**

Reframed in v2. This phase is not about naming game functions — 92% of `.text` is game
code and out of reach. It is about identifying the **936 SDK functions (7.8%) we delete
and replace**. That is the whole point; see [SPEC.md](SPEC.md) §6.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **2.1** Run `dtk dol split` | S | **Done** with slice 8.1: 254 SDK names, the 11-section split, `config/GEAE8P/` |
| `[x]` | **2.2** Harvest self-naming strings | S | **Done:** 61 functions named from diagnostic strings that name their own routine (`config/names.txt`, merged by `tools/inventory.py`): the script VM's handlers (`scpt*`), the async loader (`akFioReadASync`), effects, `DVDReadAsync` |
| `[ ]` | **2.3** Build one donor SDK | M | `mariopartyrd/marioparty4` — the only confirmed `0x2301` banner match. ~+89 names. **Do not budget for building all four repos**; a second donor adds ~8 |
| `[ ]` | **2.4** Signature match + triage | M | Ranked report, manual confirmation, false-positive check (size agreement is not verification). Populate `config/symbols.toml` |
| `[x]` | **2.5** Delimit the replacement set | S | **Done:** the SDK block `0x802319E0`–`0x80266854` is split per library in `config/GEAE8P/splits.txt` (`sdk/*`), the middleware library `0x80266854`–`0x802AC7DC` as `lib/middleware.c`; the HLE bindings in `config/hle.txt` name what the runtime replaces |

**Exit / M2:** we know which code to throw away.

---

## Phase 3 — Recompiler + reference interpreter `[ ]` → **M3**, **M4**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **3.0** Byte-swap strategy decision | S | **Decided: swap on access over a console-order image.** The alternative needs per-word types a whole-program recompile does not have. See SPEC §12 |
| `[x]` | **3.1** CpuState + codegen skeleton | M | **Done.** `runtime/cpu.h` (state, memory windows + MMIO trap, CR/XER/carry/shift/divide helpers, `fctiw`), `soa.recomp.Emitter`. **End-to-end test passes: a translated function compiles under MSVC, runs natively, and produces the right registers and byte-swapped memory** |
| `[x]` | **3.2** Integer, branch, load/store | M | **Done.** Direct branches → `goto`, calls → C calls with LR set, conditional returns, CTR-decrement forms, switch tables → `switch`, indirect calls → `dispatch`, `rfi`, `dcbz` |
| `[x]` | **3.3** Floating point + FPSCR | M | **Done.** Single ops fill both halves and round via `(float)`; fused forms use `fma()` under `/fp:strict`; `fctiw[z]`, `fcmp[uo]`, `fsel`, FPSCR bit ops. **Semantics unverified until 3.7** |
| `[x]` | **3.4** Paired singles + GQR | S | **Done.** Emitter covers all 25 `ps_*` ops and every `psq_*` form, verified end to end (a quantised u8 store scales and saturates natively); `psq_load`/`psq_store` decode GQR type/scale at runtime with truncating, saturating quantisation. Generic on purpose until the differ confirms semantics; specialising on the six static GQRs is a later optimisation |
| `[x]` | **3.5** Indirect branch dispatch | M | **Done:** `dispatch()` generated as a switch over all 7,144 entries; all 296 switch tables inline (the last four had a `bgtlr` bound check) |
| `[x]` | **3.6** Whole-DOL translation | M | **Done: 7,166 functions → 18 files, 52.7 MB of C, 99.999% instruction coverage (696,047 of 696,052); all 19 translation units compile under MSVC** (3 s at `/Od`, parallel). Remaining: the 5 unresolved `bctr` |
| `[ ]` | **3.7** Reference interpreter + lockstep differ | M | **The oracle. Replaces v1's Dolphin tracer, which does not exist.** C interpreter over the same `CpuState`, sharing the runtime's memory and HLE. Compares per basic block, then per instruction on failure. No trace files, O(1) storage. **Must land alongside 3.2, not later** — 3.2's test vectors have no other source |

**Exit / M3:** the game binary exists as compilable native C. **Reached.**
**Exit / M4:** it executes correctly, verified in lockstep.

> **R8.** The differ is circular if both sides share a bug. Share *field extraction* only,
> never semantics: write interpreter semantics from the 750CL manual independently of the
> C emission templates, and anchor with Dolphin save-state fixtures.

---

## Phase 4 — Runtime `[~]`

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **4.1** Memory map + MMIO dispatch | M | **Done** (`runtime/cpu.h`, `hle.c`, `irq.c`).  MEM1 **plus the `0xC0000000` uncached alias over one backing store**, OS low-memory globals, and trap-and-dispatch for `0xCC00xxxx`. See SPEC §5 — "one flat allocation" was wrong |
| `[x]` | **4.1b** Write-gather pipe | M | **Done** (`runtime/gx.c`: byte stream parsed as CP commands; BP/XF/CP loads, display lists, draws counted).  **Moved ahead of graphics.** `HID2[WPE]`, `WPAR`, 32-byte granularity, the SDK's dummy-write flush idiom. 414 stores depend on it |
| `[x]` | **4.2** Boot path | S | **Reached without the differ**: the boot runs `__start` → `main` → the game loop on diagnostics alone (`SOA_TRACE`, `SOA_WATCH`, guest printf, spin/watchdog backtraces). 3.7 stays valuable for the long tail.  Point the 3.7 differ at the boot path. Runs to first unimplemented HLE call |
| `[ ]` | **4.2b** Dolphin calibration fixtures | S | Save-state checkpoints, BranchWatch export. Dolphin demoted from daily loop to one-time fixture source |
| `[~]` | **4.3** OS HLE | L | **Mostly recompiled, not HLE'd**: allocator, alarms, interrupts and threads run as translated; only `OSSave/LoadContext`, `__OSInitAudioSystem` and `OSReport` are native. Interrupts arrive at loop back-edges (`irq_poll`) and the idle loop, with the full register file saved around every handler.  Arena allocator, alarms, interrupts, `OSReport` |
| `[x]` | **4.3b** Guest→host context-switch bridge | M | **Done** (`runtime/threads.c`: setjmp at the single `OSSaveContext` call site, fibers per thread).  **The hard part of "fibers," and it had no slice.** How a guest `OSThread` switch — guest SP swap, guest LR restore, the `lmw` GQR0-7 + HID2 + DMAU/DMAL restore at `0x802597D8` — bridges to a host fiber whose C stack is mid-`fn_800A1234` |
| `[x]` | **4.4** DVD | M | **Done at the DI register level** (`runtime/dvd.c` reads `extracted/disc.iso`); the SDK's DVD stack runs recompiled. Arena-hi must sit at the FST, as the apploader leaves it.  `DVDOpen`/`DVDReadAsync`/`DVDChangeDir` against `extracted/`. **Depends on 0.5** — see R9 |
| `[x]` | **4.5** VI + retrace | M | **Done**: DI0 status bit, 60 Hz of guest timebase, `VIWaitForRetrace` sleeps and wakes the main thread every frame.  **New slice. This is the game loop.** 480i only (NTSC/MPAL/EURGB60), 59.94 Hz, `VIWaitForRetrace` drives everything. v1 buried this in three words inside 5.5 |
| `[x]` | **4.6** PAD input | S | **Done**: SI model (`runtime/si.c`), keyboard and XInput gamepad through the window (`runtime/window.c`), and a scripted controller (`SOA_PAD=frame:buttons,...`) for headless runs.  SDL3 gamepad → `PADRead`. Rumble (`rdt_vibrate`) exists in the binary |
| `[~]` | **4.7** CARD saves | M | **EXI bus and a slot-A memory card modelled** (`runtime/exi.c`: a 59-block image at `build/cards/slotA.raw` the game formats itself, reported unlocked so the DSP unlock microcode is never needed; RTC and a valid SRAM too). Not yet exercised by a save. Importing a save from a real card or Dolphin is still the acceptance test |

---

## Phase 5 — Graphics `[~]` → **M5 reached**, **M6 reached**

A release build of the translated code (`recompile.py --compile --optimize`) takes 103 s on 16 cores; the validation build 3 s. The software renderer runs on worker threads behind a deferred command queue and keeps up with the game's own 30 fps cap with every frame rendered (`runtime/gxr.c`). A GPU backend is now an optimisation, not a prerequisite.

Gated on **4.1b (the gather pipe)**, not on M2. See SPEC §7.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **5.0** FIFO-log replay harness | M | **Done, from our own captures instead of Dolphin's**: `SOA_FIFO_DUMP` writes a frame's registers, command bytes and RAM; `soa.exe --replay` renders it to PNG; `tools/fifo.py` decodes it.  **The rendering oracle.** Record a Dolphin `.dff` at the title screen, replay it through our backend offline, diff against Dolphin. Frame-level ground truth *before the game runs*, and a permanent regression corpus |
| `[x]` | **5.1** GX command stream + vertex decoder | L | **Done at the hardware level, not the API level**: the write-gather byte stream is parsed as the command processor would (gx.c), so no GX entry point needs HLE.  HLE the 104 out-of-line GX entry points (1,674 call sites); decode vertices from `GXSetVtxDesc`/`GXSetVtxAttrFmt`/`GXSetArray` state. A full opcode parser is needed for display-list buffers only — 1 function, 2 call sites |
| `[x]` | **5.2** Texture decode | M | **Done** (`gxr_tev.c`): every format including CMPR and C4/C8/C14X2 through TLUTs in a TMEM model.  GX formats (I4/I8/IA4/IA8/RGB565/RGB5A3/RGBA8/CMPR/C4/C8/C14X2). **Not GVR** — at the GX boundary we see GX enums and tiled data, never a GVR header |
| `[x]` | **5.3** Vertex pipeline | L | **Done in software** (`gxr.c`): matrices, lighting, texgen, clipping, rasterization. No Vulkan yet -- the software renderer is the reference.  Vertex descriptors, attribute formats, display lists → Vulkan buffers |
| `[~]` | **5.4** TEV | XL | **Software TEV done** (all 16 stages, konst, swap tables, compare modes, alpha test, blend, logic ops); indirect texturing and fog not yet. Shader generation for a GPU backend is the remaining work, and is now a translation of working code.  Up to 16 TEV stages + indirect textures → SPIR-V. The single largest piece of work |
| `[x]` | **5.5** EFB/XFB and copies | L | **Done**: EFB, clears, copies to texture (tiled encode) and to the screen; the window presents each copied frame (`runtime/window.c`), or a PNG is written headlessly.  Framebuffer, copy-to-texture, scanout |
| `[ ]` | **5.7** Evaluate replacing the middleware library | M | `0x80266778`-`0x802AC7E0`: 807 functions, 10.3% of `.text`, holds 868 of 1,508 FIFO writes, calls into game code 2 times out of 3,996. Reimplementing rather than recompiling it would delete most of the vertex problem |
| `[ ]` | **5.6** Graphics dependency vendoring | S | **Undeclared install burden.** Vulkan SDK, `glslang`/`shaderc`, SDL3 — vcpkg vs FetchContent vs prebuilt. Decide before 5.4 |

---

## Phase 6 — Audio `[~]` → **M7 reached**

Deferred until the game is visually running. **Size depends on slice 0.7.**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **6.1** AI/ARAM/DSP mail | M | **Done** (`runtime/aram.c`, `dsp.c`): ARAM as a host buffer, DMA, DSP mailbox protocol for the stock AX boot and command lists, AI DMA clock raising AIDINT every 5 ms. No mixing yet.  ARAM as a host buffer, DMA, audio interrupt timing |
| `[x]` | **6.2** DSPADPCM decode | S | **Done** in `runtime/ax.c` (with PCM16/PCM8, loops, per-voice rate conversion) |
| `[~]` | **6.3** AX mixer | **L** | **Working** (`runtime/ax.c`): voices, envelopes, per-ms updates, main/aux buses, 32-bit CPU exchange buffers, this build's mixer-control encoding (L/R always; bits for aux A/B, surround, ramps). Not yet: SETUP ramps, compressor, initial-time-delay |
| `[x]` | **6.4** Streamed BGM | M | **Verified:** `tools/audio_check.py` decodes a `.dsp` stream and cross-correlates it with a `SOA_WAV` recording; the opening music matches at 0.85 (both channels) and the battle music at 0.52 under the voices and effects mixed over it; clipping 0.0004% |

---

## Phase 7 — Playable `[ ]` → **M8**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **7.1** Title to field | M | **Done:** New Game, the opening, the deck battle and the Valuan ship's hold as the first navigable field, with dialogue, menus and the minimap rendering |
| `[~]` | **7.2** Battle system | M | **The tutorial battle and random encounters in the hold run start to finish** (command wheel, targeting, attacks, damage, turns, victory); magic, items, Focus and boss fights not yet exercised |
| `[ ]` | **7.3** Ship/overworld | M | Airship sections |
| `[ ]` | **7.4** Playthrough hardening | XL | The long tail. Save/load parity, every scene |
| `[ ]` | **7.5** Enhancements | **L, not M** | Widescreen, higher internal resolution. **Uncapped framerate is a re-architecture**, not a tweak: the engine is 480i-locked and retrace-driven |

---

## Phase 8 — Progressive decompilation `[ ]` *(parallel, ongoing)*

Runs alongside Phases 5–7 once M3 lands. Never blocks the critical path.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **8.1** dtk-compatible splits | M | **Done:** `config/GEAE8P/` (config.yml, splits.txt, symbols.txt) drives `dtk dol split` on the user's own DOL: 23 objects, the SDK split per library (os, dvd, vi, gx, exi, si, MetroTRK, MSL, ...), the middleware library (807 functions) and the game (5,362) as units of their own, ready to be subdivided as decompilation names files |
| `[x]` | **8.2** mwcc build pipeline | M | **Done:** `tools/fetch_toolchain.py` fetches the Metrowerks compilers into `vendor/`; `tools/decomp.py` builds every unit in `config/GEAE8P/units.txt` with the compiler and flags it names and `tools/matchcheck.py` compares each function with the executable word for word. First unit: MSL `strlen` and `strchr`, byte-matching with mwcc 1.3.2 `-O4,p` |
| `[ ]` | **8.3** Function swap-in harness | M | Differential test proves a decompiled function equivalent to its recompiled twin |
| `[ ]` | **8.4** Decomp grind | XL | Function by function, indefinitely |

---

## Critical path

v1's graph routed everything through `4.1 → 4.2 → [M4] → 5.x` on the strength of a Dolphin
tracer that does not exist. Redrawn:

```
  0.3 ─┬─ 1.1 ─ 1.1b ─ 1.6 ─ 1.2 ─ 1.3 ──────────────────► [M1]
       │                                │
  0.6 ─┘                                ├─ 2.1..2.5 ─────► [M2]
                                        │
  0.7 (DSP probe) ──► sizes 6.3         └─ 3.0 ─ 3.1 ─┬─ 3.2 ─ 3.3 ─ 3.4 ─ 3.5 ─ 3.6 ─► [M3]
                                                      └─ 3.7 (oracle) ──┬──────────────► [M4]
                                                                        │
  0.5 (junk) ──► 4.4                    4.1 ─ 4.1b ─ 4.2 ─ 4.3 ─ 4.3b ─┤
                                                      │                 │
                                                      └─ 4.5 (VI) ──────┤
                                                                        ▼
                                              5.0 (FIFO oracle) ─ 5.1 ─ 5.2 ─ 5.3 ─► [M5]
                                                                        └─ 5.4 ─ 5.5 ─► [M6]
                                                                                  │
                                                            6.x ─► [M7] ─ 7.x ─► [M8]
```

Key changes from v1:

- **3.7 (reference interpreter) is on the critical path**, paired with 3.2. It is the
  oracle; nothing downstream can be trusted without it.
- **4.1b (gather pipe) gates graphics**, replacing M2 as the Phase 5 gate.
- **5.0 (FIFO replay) comes before 5.1** — validate the backend before the game drives it.
- **0.7 (DSP probe) is off the critical path** but sizes Phase 6, so it runs now.

Phases 2 and 3 remain independent and can proceed in parallel.

---

## Immediate next actions

1. **0.7** — DSP microcode probe *(in flight)*
2. **1.1b** — decoder cross-validation *(in flight)*
3. **1.6** — constant-propagation engine, then **1.2** → **1.3** → **M1**

> **Correction to v1:** the C++ toolchain is **already installed** — MSVC 14.44.35207,
> Windows SDK 10.0.26100, and `cmake`/`ninja` under VS BuildTools. `cl.exe` simply is not
> on `PATH` without `vcvars64.bat`. v1 told contributors to expect a blocker that is not
> there. Phase 3 needs no new installs; the real install burden is Phase 5's (slice 5.6)
> and Dolphin-from-source for FIFO capture.
