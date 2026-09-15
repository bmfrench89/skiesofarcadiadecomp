# Disc Analysis — Findings

**Subject:** Skies of Arcadia Legends (USA), GameCube, game ID `GEAE8P`
**Method:** direct decode of an RVZ container; no emulator involved
**Date:** 2026-09-15

Everything here is structural metadata about the executable — addresses, sizes,
instruction counts. No game content is reproduced or stored in this repository.

---

## 1. Container and disc

The source image is an RVZ (Dolphin's compressed disc format). It was decoded from
scratch rather than converted with an external tool, so the pipeline has no
dependency on a Dolphin install.

| Field | Value |
|---|---|
| Container | RVZ v1, zstd level 19, 128 KiB chunks, 11,139 groups |
| Disc type | 1 (GameCube) — no Wii partition encryption layer |
| Uncompressed size | 1,459,978,240 bytes (1.360 GiB), single layer |
| Compressed size | 1,285,948,056 bytes |
| Game ID | `GEAE8P` — `G`=GameCube, `EA`=Eternal Arcadia, `E`=USA, `8P`=Sega |
| Magic word | `0xC2339F3D` (valid) |
| Apploader | dated 2002-09-05, 0x1934 bytes |

### RVZ format notes

Two details cost real time and are worth recording:

1. **The first 0x80 bytes of the disc are stored in the RVZ header**, not in the group
   stream. The single raw-data entry has `base = 0x80`, but groups tile from
   `align_down(base, chunk_size)` = 0. Treating `base` as the group origin yields
   garbage.
2. **Junk runs carry a 68-byte seed** (17 × u32 — a lagged Fibonacci generator state),
   not 4 bytes. Brute-forcing seed size against "does the chunk decode to exactly
   131,072 bytes" identified it unambiguously.

Junk runs are currently zero-filled rather than regenerated. This affects inter-file
padding only; the DOL, FST and all real file data are stored as literal runs and decode
exactly. Slice 0.5 covers regeneration if a byte-exact whole-disc rebuild is ever
wanted.

---

## 2. Filesystem

| | |
|---|---|
| FST offset / size | `0x00323E00` / 134,426 bytes |
| Entries | 5,560 (5,552 files, 7 directories) |
| Total file bytes | 1,418,037,369 |

Directories: `battle`, `bchara`, `beff`, `ending`, `field`, `sound`, `title`

### Contents by extension

| Ext | Files | Size | Notes |
|---|---:|---:|---|
| `.mld` | 1,791 | 1,019.7 MB | Field/model data — the bulk of the disc |
| `.samp` | 590 | 121.5 MB | Audio samples |
| `.sml` | 136 | 82.0 MB | |
| `.dsp` | 620 | 74.9 MB | Nintendo DSPADPCM audio |
| `.mlk` | 574 | 34.4 MB | |
| `.info` | 589 | 7.9 MB | |
| `.sct` | 258 | 5.3 MB | |
| `.mll` | 11 | 3.7 MB | |
| `.gvr` | 3 | 1.2 MB | **Sega GameCube Video Resource** — Dreamcast PVR lineage |
| `.std` | 438 | 1.2 MB | |
| `.tpl` | 2 | — | Nintendo standard texture format — only 2 files |
| others | — | — | `.dat`, `.sst`, `.tec`, `.enp`, `.ect`, `.bin`, `.evp`, `.lmt`, `.bnr` |

**No `.rel`, `.map`, or `.elf` files anywhere on the disc.**

The near-total absence of `.tpl` alongside the presence of `.gvr` confirms Sega used
their own asset pipeline rather than Nintendo's — consistent with a Dreamcast port.

---

## 3. Executable

`boot.dol` at disc offset `0x0001EC00`.

| | |
|---|---|
| Size | 3,166,656 bytes |
| Entry point | `0x80003140` |
| BSS | `0x80302A00`, 305,860 bytes |
| Total RAM | 3.3 MiB of 24 MiB MEM1 |

### Sections

| Section | File offset | Virtual address | Size |
|---|---|---|---:|
| `.text0` | `0x000100` | `0x80003100` | 9,472 |
| `.text1` | `0x002600` | `0x80005600` | 2,781,664 |
| `.data0` | `0x2A97E0` | `0x802AC7E0` | 32 |
| `.data1` | `0x2A9800` | `0x802AC800` | 32 |
| `.data2` | `0x2A9820` | `0x802AC820` | 189,856 |
| `.data3` | `0x2D7DC0` | `0x802DADC0` | 162,880 |
| `.data4` | `0x2FFA00` | `0x80346720` | 864 |
| `.data5` | `0x2FFD60` | `0x80348000` | 21,600 |

Code: 2,791,136 bytes = **697,784 instructions**. Data: 375,264 bytes.

### Toolchain fingerprint

Twelve `<< Dolphin SDK - MODULE release build: ... >>` strings, all stamped
**2002-09-05, version `0x2301`**, covering at least `OS`, `DVD`, `VI`, `PAD`, `AI`
and `AR`. Also present: `Metrowerks Target Resident Kernel for PowerPC`.

**No MusyX.** Audio runs on a custom Sega engine sitting directly on the SDK's `AI`,
`AR` (ARAM) and `DSP` layers — `DSPInit()` is referenced directly. There is no
off-the-shelf middleware to lean on here, but the underlying sample format is standard
DSPADPCM.

---

## 4. Instruction census

All 697,784 instructions in both text sections were decoded and counted.

### Gekko-specific usage — the headline result

| Class | Count |
|---|---:|
| Paired-single arithmetic (primary opcode 4) | 320 |
| `psq_l` / `psq_lu` / `psq_st` / `psq_stu` (56/57/60/61) | 5,006 |
| **Total Gekko-only** | **5,326** |
| **As share of all code** | **0.76%** |

For context, an engine written natively for GameCube is saturated with these. At 0.76%
this binary barely uses the hardware's distinctive features — which is exactly what an
SH-4 codebase ported to PowerPC looks like. No locked-cache DMA idioms were observed.

Of the 5,326, the overwhelming majority (5,006) are quantized load/store, which
translate mechanically: a load plus a scale-and-convert driven by a `GQR` register.
Only 320 instructions are genuine paired-single SIMD math.

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
| 52 | `stfs` | 17,791 | 2.55% |
| 15 | `addis` | 17,340 | 2.49% |

Float usage is substantial (`lfs` + `stfs` + FP ops ≈ 10%) but **scalar throughout** —
consistent with the paired-single count.

### Function count

| Signal | Count |
|---|---:|
| Unique `bl` targets | 5,375 |
| `stwu r1` prologues | 5,330 |
| `blr` returns | 8,024 |

The `bl` figure is a **lower bound** — it misses functions reached only through C++
virtual dispatch or function pointers. The `blr` figure over-counts (multiple returns
per function) while missing tail calls. True count is somewhere in **5,400–8,000**;
Slice 1.2 will settle it exactly.

---

## 5. Comparison to completed GameCube decompilations

| Game | Functions | Decomp status |
|---|---:|---|
| **Skies of Arcadia Legends** | **~5,400–8,000** | **0%** |
| Pikmin | 8,069 | 100% |
| Super Mario Strikers | 8,605 | 100% |
| Mario Party 4 | 10,986 | 100% |
| Metroid Prime | 16,685 | 89% |
| Melee | 19,828 | 100% |
| Animal Crossing | 20,288 | 100% |
| Twilight Princess | 48,107 | 100% |

Skies is smaller than every GameCube title that has been fully decompiled.

---

## 6. Assessment

**Favorable:**

- **No REL modules.** All code in one DOL. The single largest static-recompilation
  risk is simply absent — every function has a fixed, statically known address.
- **0.76% Gekko-specific instructions.** CPU translation is a contained problem.
- **Smallest function count** of any GameCube game yet fully decompiled.
- **Small RAM footprint** (3.3 of 24 MiB) — plenty of headroom for instrumentation.
- **Turn-based JRPG.** Tolerant of timing imprecision in a way an action title is not.

**Unfavorable:**

- **No symbol map.** The main gap. Mitigation is the SDK signature strategy (SPEC §5).
- **Custom Sega audio engine.** No MusyX means no reference implementation; this is
  original reverse engineering. Deferred to Phase 6.
- **Zero prior decomp work.** The one public repo
  (`Rainchus/SkiesOfArcadiaLegends`) is a single commit from 2025-05-07 —
  a dtk scaffold that reassembles the DOL with no functions decompiled.

**Conclusion:** the favorable signals are unusually strong and the one serious gap has
a credible mitigation that did not exist before 2026. Proceed.
