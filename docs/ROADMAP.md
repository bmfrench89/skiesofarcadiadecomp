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
| **M7** | Audio | Phase 6 | Music and SFX |
| **M8** | Playable | Phase 7 | Field movement, battles, saves that round-trip |

---

## Phase 0 — Foundation `[~]`

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **0.1** RVZ container decoder | S | Decodes zstd groups + RVZ run packing. Verified against disc header |
| `[x]` | **0.2** DOL parser | S | Sections, entry, BSS. Totals match |
| `[x]` | **0.3** Disc extractor | S | **Done:** 5,552/5,552 files, byte-exact, DOL sha256 matches image |
| `[x]` | **0.4** Repo scaffold + CI | S | **Done:** guard blocks game data in tree *and* full history; tests run without a disc |
| `[x]` | **0.6** AKLZ container decoder | S | **Done:** exhaustive gate — 3,633 containers, 1.98 GiB, 0 failures, 0 PPC code |
| `[ ]` | **0.5** Junk-run regeneration (lagged Fibonacci) | M | **No longer optional — see R9.** RVZ junk runs are zero-filled. GameCube games routinely over-read past a file's declared end; `extracted/` would return zeros where the disc returns junk. Correctness dependency of slice 4.4 |
| `[x]` | **0.7** DSP microcode probe | S | **Done: STOCK.** Audio ucode hashes to `0x4E8A8B21` = Dolphin's stock AX. Positive control validated the method. R3 → Low; slice 6.3 stays L |
| `[ ]` | **0.8** Clean-machine reproduction | S | `pyproject.toml` `[project]` table, pinned deps, `CONTRIBUTING.md`, scripted fetch of `dtk` and the mwcc archive. A second contributor gets from `git clone` to a working tree |

**Exit:** the disc is fully unpacked, reproducible, and every container is accounted for.

---

## Phase 1 — Static analysis `[~]` → **M1**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[x]` | **1.1** Gekko disassembler | M | **Done:** 696,144/697,784 words decode. `.text1` at 99.9997%; `.text0` at 30.8% (it is a ROM image of exception vectors with embedded strings and padding). Full paired-single and `psq_*` coverage across all three opcode-4 field widths |
| `[x]` | **1.1b** Decoder cross-validation | S | **Done.** Diffed vs capstone + dtk over all 697,784 words. Six defects fixed, worst mislabelled 19,306 float instructions. Whole-image test now passes |
| `[ ]` | **1.2** Function boundary detection | M | CFG from entry + `bl` targets + prologue scan + function-pointer tables. Must reconcile ~7,117 (dtk heuristic) vs ~7,156 (independent derivation) and account for the 1,781 functions never `bl`-called and the 431 leaf functions with no prologue |
| `[ ]` | **1.3** Call graph + indirect branches | M | Classify all 296 `bctr` + 248 `bctrl` + 121 `blrl` + 527 conditional `blr`. Recover the 320 jump tables / 5,721 entries. Special case: the sole `bla 0x60` at `0x80232278` |
| `[ ]` | **1.4** Data classification | M | Partition `.data0..5` **and `.text0`** into vtables, jump tables, float pools, strings, static initialisers. Reconcile the disagreement over whether jump tables live only in `.data3` or also `.data4` |
| `[ ]` | **1.5** Symbol database | S | `config/symbols.toml`: address, size, name, source (auto/dtk/sig/string/manual), binding (direct-only / indirect-only / both). dtk-compatible split format |
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
| `[ ]` | **2.1** Run `dtk dol split` | S | ~260 SDK names, 12-section split, zero dependencies |
| `[ ]` | **2.2** Harvest self-naming strings | S | ~87 names from diagnostic strings. Yields ~8 *SDK* names — useful, but v1 badly over-estimated this vector |
| `[ ]` | **2.3** Build one donor SDK | M | `mariopartyrd/marioparty4` — the only confirmed `0x2301` banner match. ~+89 names. **Do not budget for building all four repos**; a second donor adds ~8 |
| `[ ]` | **2.4** Signature match + triage | M | Ranked report, manual confirmation, false-positive check (size agreement is not verification). Populate `config/symbols.toml` |
| `[ ]` | **2.5** Delimit the replacement set | S | The contiguous SDK block `0x802319E0`–`0x80266770` marked as HLE candidates |

**Exit / M2:** we know which code to throw away.

---

## Phase 3 — Recompiler + reference interpreter `[ ]` → **M3**, **M4**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **3.0** Byte-swap strategy decision | S | **Irreversible once 696k instructions of C exist (R10).** Measure swap-on-access vs byte-swapped backing image on a representative function. Decide with numbers |
| `[ ]` | **3.1** CpuState + codegen skeleton | M | ABI per SPEC §4.3 **including `hid2`, `wpar`, gather-pipe accumulator**. One hand-picked function translates and compiles |
| `[ ]` | **3.2** Integer, branch, load/store | M | ~85% of the binary. Per-opcode vectors sourced from 3.7 plus one-time Dolphin fixtures |
| `[ ]` | **3.3** Floating point + FPSCR | M | Scalar FP incl. FMA, `fres`/`frsqrte` estimates, rounding modes |
| `[ ]` | **3.4** Paired singles + GQR | S | 319 `ps_*` + 5,007 `psq_*`. **Specialise at translation time** — GQR values are static constants and 97.3% use GQR0 (plain f32). No runtime GQR dispatch. Only ~135 sites need a convert helper |
| `[ ]` | **3.5** Indirect branch dispatch | M | Address→function table from 1.3. R1 is Low: the target set is closed, no interpreter fallback needed |
| `[ ]` | **3.6** Whole-DOL translation | M | All 696,120 instructions emit C and compile. Measure build time and binary size |
| `[ ]` | **3.7** Reference interpreter + lockstep differ | M | **The oracle. Replaces v1's Dolphin tracer, which does not exist.** C interpreter over the same `CpuState`, sharing the runtime's memory and HLE. Compares per basic block, then per instruction on failure. No trace files, O(1) storage. **Must land alongside 3.2, not later** — 3.2's test vectors have no other source |

**Exit / M3:** the game binary exists as compilable native C.
**Exit / M4:** it executes correctly, verified in lockstep.

> **R8.** The differ is circular if both sides share a bug. Share *field extraction* only,
> never semantics: write interpreter semantics from the 750CL manual independently of the
> C emission templates, and anchor with Dolphin save-state fixtures.

---

## Phase 4 — Runtime `[ ]`

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **4.1** Memory map + MMIO dispatch | M | MEM1 **plus the `0xC0000000` uncached alias over one backing store**, OS low-memory globals, and trap-and-dispatch for `0xCC00xxxx`. See SPEC §5 — "one flat allocation" was wrong |
| `[ ]` | **4.1b** Write-gather pipe | M | **Moved ahead of graphics.** `HID2[WPE]`, `WPAR`, 32-byte granularity, the SDK's dummy-write flush idiom. 414 stores depend on it |
| `[ ]` | **4.2** Boot path lockstep | S | Point the 3.7 differ at the boot path. Runs to first unimplemented HLE call |
| `[ ]` | **4.2b** Dolphin calibration fixtures | S | Save-state checkpoints, BranchWatch export. Dolphin demoted from daily loop to one-time fixture source |
| `[ ]` | **4.3** OS HLE | L | Arena allocator, alarms, interrupts, `OSReport` |
| `[ ]` | **4.3b** Guest→host context-switch bridge | M | **The hard part of "fibers," and it had no slice.** How a guest `OSThread` switch — guest SP swap, guest LR restore, the `lmw` GQR0-7 + HID2 + DMAU/DMAL restore at `0x802597D8` — bridges to a host fiber whose C stack is mid-`fn_800A1234` |
| `[ ]` | **4.4** DVD HLE | M | `DVDOpen`/`DVDReadAsync`/`DVDChangeDir` against `extracted/`. **Depends on 0.5** — see R9 |
| `[ ]` | **4.5** VI + retrace | M | **New slice. This is the game loop.** 480i only (NTSC/MPAL/EURGB60), 59.94 Hz, `VIWaitForRetrace` drives everything. v1 buried this in three words inside 5.5 |
| `[ ]` | **4.6** PAD input | S | SDL3 gamepad → `PADRead`. Rumble (`rdt_vibrate`) exists in the binary |
| `[ ]` | **4.7** CARD saves | M | Memory-card emulation. **Acceptance includes importing a save from a real card or Dolphin** — users judge the port on this |

---

## Phase 5 — Graphics `[ ]` → **M5**, **M6**

Gated on **4.1b (the gather pipe)**, not on M2. See SPEC §7.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **5.0** FIFO-log replay harness | M | **The rendering oracle.** Record a Dolphin `.dff` at the title screen, replay it through our backend offline, diff against Dolphin. Frame-level ground truth *before the game runs*, and a permanent regression corpus |
| `[ ]` | **5.1** GX state HLE + vertex decoder | L | HLE the 104 out-of-line GX entry points (1,674 call sites); decode vertices from `GXSetVtxDesc`/`GXSetVtxAttrFmt`/`GXSetArray` state. A full opcode parser is needed for display-list buffers only — 1 function, 2 call sites |
| `[ ]` | **5.2** Texture decode | M | GX formats (I4/I8/IA4/IA8/RGB565/RGB5A3/RGBA8/CMPR/C4/C8/C14X2). **Not GVR** — at the GX boundary we see GX enums and tiled data, never a GVR header |
| `[ ]` | **5.3** Vertex pipeline | L | Vertex descriptors, attribute formats, display lists → Vulkan buffers |
| `[ ]` | **5.4** TEV shader generation | XL | Up to 16 TEV stages + indirect textures → SPIR-V. The single largest piece of work |
| `[ ]` | **5.5** EFB/XFB and copies | L | Framebuffer, copy-to-texture, scanout |
| `[ ]` | **5.7** Evaluate replacing the middleware library | M | `0x80266778`-`0x802AC7E0`: 807 functions, 10.3% of `.text`, holds 868 of 1,508 FIFO writes, calls into game code 2 times out of 3,996. Reimplementing rather than recompiling it would delete most of the vertex problem |
| `[ ]` | **5.6** Graphics dependency vendoring | S | **Undeclared install burden.** Vulkan SDK, `glslang`/`shaderc`, SDL3 — vcpkg vs FetchContent vs prebuilt. Decide before 5.4 |

---

## Phase 6 — Audio `[ ]` → **M7**

Deferred until the game is visually running. **Size depends on slice 0.7.**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **6.1** AI/ARAM HLE | M | ARAM as a host buffer, DMA, audio interrupt timing |
| `[ ]` | **6.2** DSPADPCM decode | S | Standard Nintendo ADPCM, well documented |
| `[ ]` | **6.3** Sega mixer | **L** | Stock AX ucode confirmed, so this is a mixer reimplementation. Dolphin's AX HLE handles this exact CRC and its semantics are publicly documented |
| `[ ]` | **6.4** Streamed BGM | M | Stereo `.dsp` pairs stream and loop |

---

## Phase 7 — Playable `[ ]` → **M8**

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **7.1** Title to field | M | New game starts, field renders and is navigable |
| `[ ]` | **7.2** Battle system | M | Encounters run start to finish |
| `[ ]` | **7.3** Ship/overworld | M | Airship sections |
| `[ ]` | **7.4** Playthrough hardening | XL | The long tail. Save/load parity, every scene |
| `[ ]` | **7.5** Enhancements | **L, not M** | Widescreen, higher internal resolution. **Uncapped framerate is a re-architecture**, not a tweak: the engine is 480i-locked and retrace-driven |

---

## Phase 8 — Progressive decompilation `[ ]` *(parallel, ongoing)*

Runs alongside Phases 5–7 once M3 lands. Never blocks the critical path.

| | Slice | Size | Acceptance |
|---|---|---|---|
| `[ ]` | **8.1** dtk-compatible splits | M | Split config the wider GC decomp tooling understands |
| `[ ]` | **8.2** mwcc build pipeline | M | Hand-written C compiles to byte-matching objects |
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
