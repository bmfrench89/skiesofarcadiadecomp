<!-- Written 2026-09-25 by the planning session, read-only. First drafted at main 3949028; revised after
two reviews at main b071949, where N2 (3949028, b071949), N3 (1c7b780, 4041dfc) and N4 (c8274db, this
spec's L0) are committed; then checked again at main 012164a in a consistency review across the five
planning documents (its entries close the review log). Since b071949: N5's P6 (24d9235) and its follow-up
P6b (79c9ad8) changed runtime/hle.c, main.c, selftest.c, settings.c and si.c and added runtime/seed.c;
C5a (750cef0) added 125 lines to runtime/gx.c (115 at :53, so gx.c citations past :55 move by 115 to
125); b1199b3 changed mod.c; T0c (012164a) changed tools/guard.py and ci.yml. At 012164a the working tree
held the implementation session's uncommitted P1a. Nothing in the repository was changed and the game was
not run. Compile probes, a libm probe and codegen probes ran in a scratch directory only, on files
exported with `git archive HEAD`; they are not in the repository. [V] = checked in code, a tool run or a
dated page; [I] = inferred. Line numbers are committed b071949's (`git show b071949:<file>`); citations
into the files named above have moved. runtime/gxr.c, gxr.h and gxr_tev.c have not changed since c8274db
(at 012164a too), so their numbers are c8274db's. The order across all plans is ../PLAN-NEXT.md. -->

# Portability groundwork: Windows first, Linux, the Deck, ARM64 and Android kept possible

**Slice ids:** L0-L12, with L2a, L3a/L3b and L4a/L4b. `docs/specs/now.md` N4 ("acquire loads in the render
queue") was this spec's **L0** and has **landed as c8274db**. §6 L0 says what it covered and what moved to L2.

**Sizes** are evenings: hours / a day / several days / week-plus / months. **Rebuild cost** is CLAUDE.md's:
none / `--link` / one retranslation. **Owner** marks where the owner must look, play or decide.

**Every slice keeps the contract.** With the default MSVC build, these do not change:
- the 23 replay hashes (`python tools/scenario.py replay --threads 1,2,3,8`);
- the self test (`$env:SOA_SELFTEST='1'; gen\soa.exe extracted`);
- `python tools/scenario.py run title --check`;
- `python tools/decomp.py`;
- `python -m pytest tools/tests/test_memguard.py tools/tests/test_mods.py`.

Every Done line below names the command that checks it. None compares two live runs (rule 7 of
`docs/PLAN-GAMEPLAY-MODS.md`). Speed is gated on a codegen comparison first. A timing is taken only when the
code moved, as an interleaved A/B against a saved copy of the previous exe, because this machine drifts about
15% within a day.

---

## 1. Purpose and scope

### What you get, in plain words

The port runs today only as a Windows program built by Microsoft's compiler (MSVC). This spec does three
things.

**1. Things worth having on Windows now:**
- **A second compiler, clang-cl,** builds the same program. It must draw the same 23 test frames to the
  last bit. Where it does not, that points at a real bug in our C, which MSVC happens to hide today.
  clang-cl may also be faster; that is measured, not promised. **Today clang cannot build the renderer at
  all** (§2.2); a few hours' fix (L2a) repairs that.
- **The render queue becomes correct on any processor.** The rasterizer threads hand work to each other.
  c8274db (N4) already made every cross-thread read of a work count an "acquire" load, which is what ARM
  processors need. One piece is left. Four reads decide whether a sleeping thread gets woken, and they rely
  on a Microsoft-specific guarantee. They need the strongest kind of load the moment the program is built by
  another compiler. L2 does that, and adds a test so that a plain read cannot creep back in. The x86 machine
  code stays the same.
- **CI catches breakage on every push:** under clang, on Linux, and on ARM processors (GitHub runs ARM
  machines free for public repositories). That includes a class of silent memory corruption that would
  hit the first Linux or Android build (§2.4).
- **An answer to "does it run on a Steam Deck?"** in hours, using Wine on your own PC.

**2. The groundwork for other platforms:**
- one small platform layer for threads, clocks, memory and files (`runtime/plat.h`, `runtime/plat.c`);
- a native Linux build;
- ARM64: Windows-on-ARM laptops, Linux on ARM, and phones.

**3. Decisions left with you.** Each later step is gated on a decision you make (section 7): the order
(Q8), the SDL3 library (Q6), which hardware, and, for Android, the GPU backend and how the game reaches
players.

**Glossary:**
- **Wine** runs Windows programs on Linux. **Proton** is Valve's Wine, which Steam uses on the Deck.
- **clang-cl** is the LLVM compiler dressed up to accept MSVC's options.
- **ARM64** is the processor family in phones, Snapdragon laptops, Apple machines and Raspberry Pis.
- **Atomics and memory ordering** are the rules for how one thread's writes become visible to another.
  x86 is forgiving; ARM is not.
- **Acquire / sequentially consistent (seq_cst) loads** are two strengths of "read this shared number
  safely". Acquire is enough to hand over work. The wake-up handshake needs seq_cst. On today's x86 and
  default ARM64 targets they are the same instruction.

### Not in scope
- **The GPU backend** is `gpu-backend.md` (V0...). This spec only keeps its road open: `plat.h` knows
  nothing about graphics, and the dynamic-library calls here are what a Vulkan loader would use.
- **The disc layer** is `disc-layer.md` (I1...). Two of its files are listed in the churn table (§3.10).
- **Window, pad and audio on other systems** wait for Q6 (SDL3). `window.c` stays Win32 until L10.
- **Speed work on the CPU pixel path** (H15d, H16) is paused for the GPU decision.

---

## 2. Current state

### 2.1 What already holds [V]

- **The translated game code compiles for ARM64, as far as it has been checked.** `gen/chunk_001.c` and
  `gen/dispatch.c` pass an ARM64 `-fsyntax-only` (`docs/research/port-portability.md`, "scope and
  method"). The other 17 chunks come from the same emitter [I]. L2's Done runs the check over all 19
  files.
- **The byte swaps are portable** (`runtime/cpu.h:46-55`).
- **`__forceinline` has fallbacks** (`gxr.c`, `gxr_tev.c`).
- **Guest float semantics are host-independent** as long as contraction is off:
  - `fctiw` and `psq` quantisation clamp explicitly (`cpu.h`);
  - the emitter uses `fma()` for every fused guest op;
  - `gen/*.c` calls only exact libm functions: `fabs` 200 times, `fma` 2,457 and `sqrt` 91 (a grep over
    `gen/*.c`). `cpu.h`, which every chunk includes, adds `nearbyint` in `ppc_fctiw` (`cpu.h:538`, after
    NaN and range are handled at :535-537); it is exact in the default rounding mode. `ldexp` has been gone
    since 042c6b1; `cpu.h:452` names it only in a comment.
- **The SIMD path is guarded and optional, but the guard is MSVC-shaped.** H15d's SSE4.1 blend sits behind
  `#if defined(_MSC_VER) && defined(_M_X64)` (`gxr_tev.c:18-22`). SSE4.1 is detected at run time
  (`simd_decide`, `gxr_tev.c:33-43`). The scalar loop is kept as the reference (`gxr_tev.c:1202-1206`), and
  `SOA_GXR_NOSIMD=1` turns SIMD off with a report line (`gxr_tev.c:913`).
- **`soa.exe` links the C runtime statically.** `dumpbin /dependents gen\soa.exe` lists WINMM,
  api-ms-win-core-synch, dbghelp, USER32, GDI32, XINPUT9_1_0, d3d11, dwmapi and KERNEL32, and no
  ucrtbase, api-ms-win-crt or VCRUNTIME. So `exp2f`, `log2f` and `fma` are inside the exe, and Wine
  runs the same math code Windows does.

### 2.2 What breaks off MSVC/x64 today [V, probes at b071949]

**clang-cl.** The NDK r28c ships clang-cl 19.0.1. With the project's flags and MSVC's headers, compiling each
`runtime/*.c` with `/c` passes 24 of 25. `gxr_tev.c` fails with three errors (:1193 twice, :1196):
> always_inline function '_mm_mullo_epi32' requires target feature 'sse4.1', but would be inlined into
> function 'sample_level' that is compiled without support for 'sse4.1'

A syntax-only pass (`/Zs`) passes all 25, because the error comes at code generation. So any check of this
must compile (`/c`), as `compile_runtime.py` does.

This has been true since b377b1f. clang-cl defines `_MSC_VER`, so the guard lets the SSE4.1 code through,
but clang will not inline SSE4.1 intrinsics into a function built for baseline x86-64. The effect depends on
the compiler:
- **Any clang build that defines `_MSC_VER`** (clang-cl, or `clang --target=*-windows-msvc`) fails to compile
  `gxr_tev.c`.
- **G4's llvm-mingw or zig cc** (`docs/PLAN-GAMEPLAY-MODS.md:1417`) target windows-gnu, which defines neither
  `_MSC_VER` nor `_M_X64`. They compile the file with no error and **silently drop the SIMD path**, losing
  H15d's 7%.
- L2a's `#if PLAT_X86_64` guard fixes both.

**Android ARM64 syntax check** (`clang --target=aarch64-linux-android29 -std=c17 -fsyntax-only`, run over a
`git archive` of b071949): 21 errors in 4 files [V]:
- `gxr.c`, 17 errors:
  - `__declspec(thread)` at :123 and `__declspec(align(64))` at :143;
  - `YieldProcessor` at :199, :1656 and :2081;
  - `LONGLONG` at :1569-1570;
  - `LONG` at :1614 and :2581;
  - `InterlockedIncrement64` at :1619, :2437, :2916 and :3032;
  - `Sleep` at :1656 and :2081;
  - `_ReadWriteBarrier` at :1661;
  - `InterlockedIncrement` at :2664.
- `dvd.c:103`: `_fseeki64`.
- `gx.c:188`: `_exit`.
- `selftest.c:122` and `:344`: `_putenv`. The compiler reports only the first call per function; there are
  four (:122, :123, :124 and :344).

The check does not see the worker pool at all: `fence_wait` (:1697-1746), `worker` (:1748-1815) and
publish's wake (:1620-1622) sit inside `#ifdef _WIN32` and are compiled out. Their Interlocked and
WaitOnAddress calls only reach a non-Windows compiler when L2 brings the pool across.

### 2.3 The render queue's ordering [V code; I on hardware]

The protocol comment is at `gxr.c:1494-1539`. The counters are `volatile LONGLONG g_published` and `g_ran[]`
(:1569-1570), and `volatile LONG` `g_sleepers` (:1614), `g_fence_sleepers` (:1701) and `g_frames_presented`
(:2581).

**c8274db (N4) added `LOAD_ACQUIRE64/32`** (macros at :1584-1589, comment :1572-1583): `ReadAcquire64` /
`ReadAcquire` under `_MSC_VER`, and `__atomic_load_n(p, __ATOMIC_ACQUIRE)` elsewhere. There are no wrapper
types. The three `_ReadWriteBarrier()` calls were kept (:1661, :1744, :1795).

**Writers** are interlocked RMWs, full barriers on every MSVC target:
- `InterlockedIncrement64(&g_published)` at :1619, :2437, :2916 and :3032;
- `InterlockedExchange64(&g_ran[id])` at :1811;
- the sleeper counts at :1732/:1734 (fence) and :1780/:1782 (idle);
- `InterlockedIncrement(&g_frames_presented)` at :2664.

**Cross-thread readers at b071949:**

| Where | What it reads | Load | Then reads |
|---|---|---|---|
| `publish` :1621 | `g_sleepers`, after its RMW (Dekker, waker side) | plain volatile | — |
| `ran_min` :1633 | `g_ran[i]` | acquire (c8274db) | — |
| `wait_ran` :1656 | `g_ran[i]` | acquire | what the command wrote. Compiler barrier at :1661 |
| `fence_wait` :1729 | `g_ran[j]` | acquire | the neighbours' EFB rows and copy images. Compiler barrier at :1744 |
| `fence_wait` :1731 and :1733 | `g_ran[j]` again, around `g_fence_sleepers++` (Dekker, waiter side) | plain volatile | — |
| `worker` :1764 | `g_published` | acquire | the `DrawCmd` slot. Compiler barrier at :1795 |
| `worker` :1781 | `g_published` again, after `g_sleepers++` (Dekker, waiter side) | plain volatile | — |
| `worker` :1812 | `g_fence_sleepers`, after its RMW (Dekker, waker side) | plain volatile | — |
| `drain` :2081 | `g_ran[i]` | acquire | the arena, graveyard and `g_screen` |
| `gxr_presented` :2780, on the UI thread (`window.c:359`) | `g_frames_presented` | acquire | `g_screen` |

The producer's reads of its own `g_published` stay plain (:1630, :1648, :1649, :1672, :1682, :2065, :2996,
:3000). That is c8274db's decision, and it is correct on any machine: the producer is the only writer, and a
thread always sees its own writes.

**Why the whole queue works on x64 today:**
- MSVC defaults to `/volatile:ms` on x86/x64, so volatile loads are acquires at the compiler level.
- x86 is TSO, so the hardware keeps loads in order.
- clang-cl for x64 also passes `-fms-volatile`: `clang-cl -###` shows it [V].

**What is left for ARM64:**
- **Publication and completion are fixed.** The acquire loads are right under MSVC ARM64 (`ReadAcquire`
  is `ldar`) and under gcc and clang.
- **The four Dekker re-checks are not, once the atomics are not Microsoft's.** Each handshake has a waiter
  side and a waker side:
  - The waiter raises a sleeper count, then re-reads the work count, and sleeps only if the count has not
    moved.
  - The waker raises the work count, then reads the sleeper count, and wakes only if someone is asleep.
  - Each side's load must be ordered after its own RMW.
  - Today those loads are plain, and they are correct only because an MSVC Interlocked call is a full
    barrier on x64 (a `lock` prefix) and on ARM64 (a trailing `dmb ish`) [V docs; I codegen on ARM64].
- **Why seq_cst is needed.** L2 maps the RMWs to `__atomic` builtins for gcc and clang, and for clang-cl,
  whose Interlocked builtins are not documented to carry MSVC's trailing barrier on ARM64 [I]. From then on,
  C11 needs seq_cst on both sides:
  - an `__ATOMIC_ACQUIRE` load may compile to `LDAPR` on armv8.3+rcpc targets, and `LDAPR` may be satisfied
    before the RMW's release store is visible;
  - a plain load has no ordering at all.
- **What a lost wakeup costs.** The 50 ms `WaitOnAddress` bound turns it into a stutter, not a hang [I].
- **The flags on other compilers:**
  - MSVC ARM64 defaults to `/volatile:iso` (Microsoft Learn);
  - clang-cl for `aarch64-pc-windows-msvc` passes no `-fms-volatile` [V, `-###`];
  - gcc and clang on Linux treat volatile as ISO.

  So any read left plain and cross-thread would be reorderable there.

### 2.4 The native twins assume a 32-bit `long` [V code; I behaviour]

`include/types.h` defines `u32`/`s32` as `unsigned long`/`signed long` (:14-15). `size_t` is `unsigned long
long` under `_WIN64` and `unsigned long` elsewhere (:5-9), so it is 64-bit on LP64 Linux and Android too.
`u32` and `s32` are the problem.

Six units are built natively (`config/GEAE8P/units.txt`). **Five of them (all but `mem.c`) use `unsigned long`
as the 32-bit machine word:**
- `src/sdk/msl/fillmem.c` fills with `unsigned long* w`, 8 stores a 32-byte block;
- `strcpy.c:9-29` does word copies;
- `strcmp.c`, whose comment at :18 says "assumes a 32-bit unsigned long";
- `strstr.c:15`;
- `string.c:48`.

They are swapped in for `memset` (through `mem.c`'s wrapper into `fillmem.c`), `strcpy`, `strcmp`, `strstr`
and friends (`config/hle.txt:25-36`, twelve bindings).

On Linux and Android, `long` is 64 bits:
- `memset` would write 64 bytes per 32-byte block;
- `strcpy`'s zero-byte test looks at only half of each 8-byte word.

Both corrupt guest memory silently.

**What would catch it.** `tools/citest/dc_check.py`'s guard bands would, but that check has only ever run
under MSVC. It also compares only nine of the twelve routines with host libc (`dc_driver.c:351-361`). `strcpy`,
`strcmp` and `strstr` are compared only by the self test, which runs only on Windows. So a Linux `dc_check`
today would catch `fillmem` (through `memset`) and not `strcpy`. L4b adds the three.

### 2.5 Libm in the renderer [V, probe]

The renderer's only inexact libm calls are `exp2f`, four times in fog (`gxr.c:940-943`), and `log2f` in
the level of detail (`gxr.c:1103`). `sqrtf`, `floorf`, `ceilf` and `sqrt` are exact.

The probe compared UCRT's functions exhaustively with `(float)exp2((double)x)` and `(float)log2((double)x)`,
built with MSVC and with clang-cl, over the domains the renderer feeds them:

| Function, domain | Inputs | Raw outputs that differ | After the renderer's quantisation |
|---|---|---|---|
| `exp2f`, every float in [-8, 0] | 1,090,519,041 | 74,154 | 0 for fog types 4/5 (`1 - e`); **1 input** for types 6/7 (`e`) |
| `log2f`, every positive finite float | 2,139,095,039 | 313,550 | 0 where `(int)(0.5*L + 0.5)` picks the mip |

- **UCRT is not correctly rounded.** A glibc or bionic build would differ on a different set of inputs.
- **The MSVC and clang-cl builds printed identical counts.** They call the same statically linked
  function.
- **The LOD row is a simplified model** (one `log2f` per pixel). The renderer interpolates LOD along a
  span and adds a bias, so it is indicative, not exact.

### 2.6 Float-to-int in the renderer [V code]

Unclamped casts whose out-of-range or NaN result differs by processor:
- **x86** `cvttss2si` gives INT_MIN.
- **ARM64** `fcvtzs` saturates, and gives 0 for NaN.

The sites:
- `gxr.c:946` (fog weight: `f` is clamped to [0, 1] first, but a NaN passes both clamps), :1241 (vertex
  colour, clamped after the cast), :1265, :1271, :1278, :1293 and :1301 (lines and points);
- `gxr_tev.c:1137` (`fast_floor`, which feeds `wrap`), :1171 (bilinear weights) and :1222 (mip level).

Already range-limited before the cast:
- `gxr.c:1142-1145` and :1210-1211;
- `gxr.c:2551` (YUV: a weighted sum of bytes plus 16, so 16-235);
- `gxr_tev.c:1109` (the mip count: `max_lod` is a byte over 16, `gxr_tev.c:1107`, so it lies in [0, 16] and is
  never NaN).

**The two unsigned depth casts,** `gxr.c:926` (fog) and :1011 (the depth test), are the same expression. The
clamp before them passes a NaN. MSVC x64 and clang x64 convert through a 64-bit `cvttss2si` and keep the low
32 bits, so NaN gives 0. ARM64's `fcvtzu` gives 0 too [I, to be confirmed by L6's driver].

### 2.7 Toolchain and CI [V]

- **The toolchain is MSVC only.**
  - `tools/soa/toolchain.py:47` returns no environment off `nt`.
  - `CFLAGS` at :100 is `/std:c17 /O2 /fp:strict /W3 /wd4102 /wd4702 /wd4101`.
- **`tools/recompile.py` hard-codes `cl`:**
  - the `/D` renames (:83);
  - compile (:163-181);
  - the link, which globs `chunk_*.obj` in `--out` (:199; `--out` at :90 defaults to `gen`);
  - the runtime and decompiled compile (:213);
  - the link flags with `/STACK:33554432` (:226-241).
- **19 test modules build C through `toolchain.cl`:**
  - `test_decomp_native` and `test_emit`;
  - the nine `test_gxr_*` modules: alpha, copy_filter, fastpath, lifetimes, overlap, pair, queue, texcache
    and tripwires;
  - `test_memguard`, `test_mods`, `test_padrec`, `test_peek`, `test_profiler`, `test_settings`, `test_tick`
    and `test_uncap`.

  So do `render_check.py`, `dc_check.py` and `compile_runtime.py`.
- **Two CI jobs build C:**
  - `native` (`ci.yml:126`) runs `compile_runtime`, `dc_check` and `render_check`;
  - `test` (`ci.yml:65-84`) runs `pytest tools/tests` on ubuntu-latest and windows-latest. On windows-latest,
    `toolchain.cl_path()` finds MSVC, so all 19 modules build and run C there, including
    `test_gxr_overlap`'s and `test_gxr_queue`'s stall sweeps. On ubuntu-latest they skip.
- **Stale counts.** The runtime had 25 committed C files at b071949; P6's `runtime/seed.c` made 26 at
  24d9235, still 26 at 012164a. "22" is written in six places (b071949's lines, then 012164a's):
  - `ci.yml:97` (:101);
  - `docs/PLAN.md:17` and :81 (unchanged);
  - `docs/TESTING.md:183` (:190);
  - `.claude/skills/check/SKILL.md:164` (:167);
  - `docs/ARCHITECTURE.md:25` (unchanged).
- **The same `ci.yml` comment (:92-125) is stale in two more ways.**
  - It says `units.txt` marks "two units" native (string.c and mem.c); there are six.
  - It says `memset`'s fill `__fill_mem` is one "nobody has decompiled", answered by the host `memset` in
    `runtime/decomp_shims.c`. `fillmem.c` is native now, and `decomp_shims.c:9` says the file is empty.
  - `tools/citest/dc_driver.c:304-311` repeats that note.
- **HANDOFF.md:503** says "four `test_gxr_*` modules" link the renderer alone; there are nine.
- **PLAN.md:17's "the nine MSL twins against libc" is right today:** `dc_check` compares nine routines. It
  becomes twelve with L4b.
- **`windows-latest` (the Windows Server 2025 image)** has LLVM 20.1.8 and the VC ARM64 tools
  (runner-images readme).
- **ARM64 runners** `windows-11-arm` and `ubuntu-24.04-arm` are free for public repositories (GA
  2025-08-07). This repository is public (`gh repo view`).

### 2.8 clang-cl's floating-point flags [V, `-###` and disassembly]

| Option | What clang does with it |
|---|---|
| `/fp:strict` | `-ffp-contract=off -frounding-math -ffp-exception-behavior=strict`: strict FP exceptions, which cost optimisation |
| `/fp:precise` | `-ffp-contract=on` |

`a*b+c` compiled with `-mfma`:
- under `/fp:precise`, one `vfmadd213ss`;
- with `/clang:-ffp-contract=off` added, `vmulss` then `vaddss`.

No runtime or generated code reads the host FP environment: no `fenv` or `_controlfp` anywhere [V grep].
So strict exception semantics buy nothing.

### 2.9 Threads and the guest stack

- **Non-Windows builds exit at the first thread resume.** `threads.c:282-312` puts the same-fiber resume
  (:283-287) inside `#ifdef _WIN32`, and every other platform exits 6 at :308-311.
- **The game has run one guest thread in every log so far,** by the research's 326 logs [V]. Those logs
  cover early-game scenarios only (`docs/research/port-beyond-iso.md:328`), so this is evidence for them, not
  proof for the whole game (§5 risk 18). `OSCreateThread` looks dead-stripped [I].
- **The guest runs on the main thread,** with a 32 MB stack set by the link (`recompile.py:241`). Linux
  defaults to 8 MB.

### 2.10 Who is editing what (`git log`, `git status`, and `docs/specs/now.md`)

| Slice | State |
|---|---|
| N2 (manifest 2, `runtime/mod.c`) | committed at 3949028, follow-up b071949 |
| N3 (T0: `tools/guard.py`, `ci.yml`, the count copies) | committed at 1c7b780, follow-up 4041dfc |
| N4 = L0 (`runtime/gxr.c`) | committed at c8274db |
| N5's P6 (`runtime/settings.c`, `hle.c`, `main.c`, `selftest.c`, a new `runtime/seed.c`, `test_settings.py`, `test_seed.py`) | committed at 24d9235 |
| C5a (`runtime/gx.c`, a log only; gpu-backend.md §6) | committed at 750cef0 |
| P6b (`seed.c`, `main.c`, `si.c`, `settings.c` and tests) | committed at 79c9ad8 |
| Manifest 2's second follow-up (`mod.c`) and T0c (`tools/guard.py`, `ci.yml`) | committed at b1199b3 and 012164a |
| N5's P1 as comfort-pack P1a (`mod.c`, `main.c`, `settings.c`, `recompile.py`, a new `mods/encounter-rate/`) | in flight in the working tree at 012164a |
| N6 (P11, a new `mods/` folder) | after P1a |

The comfort-pack spec has taken over from now.md. Its P5b (the copy-filter switch) and M11a-skip edit
`gxr.c`. The order across all plans is [../PLAN-NEXT.md](../PLAN-NEXT.md). §3.10 has the full churn table.

---

## 3. Design

### 3.1 Principles

1. **One header for the hot primitives, one C file for the cold ones.**
   - `runtime/plat.h` is header-only (`static inline`). It holds everything `gxr*.c` needs: atomics,
     waits, pause and yield, TLS and alignment, clocks, thread start, CPU count, SIMD detection and
     `plat_f2i`. So the renderer still links alone. `render_check.py` and the nine `test_gxr_*` modules build
     `gx.c`, `gxr.c`, `gxr_tev.c` and `png.c` with no `main.c` (HANDOFF.md:502-507, whose "four" is stale),
     and they need no new source.
   - `runtime/plat.c` holds the OS pieces only `main.c` and the device files need: memory reservation
     and the fault guard, the big-stack runner, the executable's folder, dynamic libraries, directory
     listing and process CPU time.
   - Both use the runtime's existing style: `#ifdef _WIN32` sections inside one file.
2. **MSVC x64 is the reference.**
   - Its flags do not change.
   - The x64 machine code of the queue does not change. c8274db compared it in the `/FA` listing, and L2's
     Done compares it the same way.
   - `config/fifo_manifest.tsv` is never re-blessed from any other build.
3. **The determinism target is replays, not live runs.**
   - `--replay` output, the self test and the decompiled twins are to be bit-identical on every platform
     and compiler.
   - Live runs already differ between two runs on one machine (rule 7), so nothing more is promised for
     them.
   - This is why exactness beats a tolerance here: a replay can be exact, and a tolerance check that
     agrees with everything is the trap CLAUDE.md names.
4. **New code in files the comfort pack is editing uses `plat.h` where it offers the call.** Old code in
   those files is converted after the comfort pack and the disc layer have landed (L9), in one pass.

### 3.2 `runtime/plat.h`: the interface

Every name is `plat_*` or `PLAT_*`. Nothing here includes `cpu.h`, and `cpu.h` never includes it, so
editing `plat.h` is a `--link`, never a retranslation. L2a creates the file with the platform tests and the
SIMD section; L2 adds the rest.

**Platform tests:**
```c
PLAT_X86_64    /* _M_X64 && !_M_ARM64EC, or __x86_64__ */
PLAT_ARM64     /* _M_ARM64 or __aarch64__ */
PLAT_MSVC      /* _MSC_VER && !__clang__: MSVC intrinsics */
PLAT_GNU       /* __GNUC__ || __clang__, including clang-cl: __atomic builtins and attributes */
```

**Storage classes:**
```c
PLAT_THREAD_LOCAL  /* __declspec(thread) on _MSC_VER (clang-cl accepts it); _Thread_local otherwise */
PLAT_ALIGN(n)      /* __declspec(align(n)) on _MSC_VER; __attribute__((aligned(n))) otherwise */
```

**Atomics.** The counters stay plain `volatile` integers, as c8274db left them: no wrapper types. What changes
is that every cross-thread access goes through a helper, and a test enforces it (§3.4, rule 4).
```c
typedef volatile int64_t plat_a64;   /* a shared counter: documentation, not a wrapper */
typedef volatile int32_t plat_a32;

int64_t plat_load64(const plat_a64* p);   /* sequentially consistent load */
int32_t plat_load32(const plat_a32* p);
int64_t plat_inc64(plat_a64* p);          /* seq_cst RMW; returns the new value */
int32_t plat_inc32(plat_a32* p);
int32_t plat_dec32(plat_a32* p);
int64_t plat_xchg64(plat_a64* p, int64_t v);
int32_t plat_cas32(plat_a32* p, int32_t expect, int32_t want); /* returns the old value */
void    plat_compiler_barrier(void);      /* _ReadWriteBarrier() / __asm__ __volatile__("" ::: "memory") */
```

How the atomics are implemented:

| Build | Loads | RMWs |
|---|---|---|
| PLAT_MSVC x64 | `ReadAcquire64` / `ReadAcquire`, c8274db's calls. A plain `mov`: after a locked RMW, that is also a seq_cst load | `InterlockedIncrement64` and friends, with a cast to `LONG volatile*` for the 32-bit ones |
| PLAT_MSVC ARM64 | `__ldar64` / `__ldar32` (`ldar`; Microsoft Learn lists them). `ReadAcquire64` compiles to the same | `Interlocked*`, full barriers on ARM64 |
| PLAT_GNU (gcc, clang, clang-cl) | `__atomic_load_n(p, __ATOMIC_SEQ_CST)`: `mov` on x86-64, `ldar` on AArch64 | `__atomic_add_fetch`, `__atomic_exchange_n`, `__atomic_compare_exchange_n`, all seq_cst |

- **One load helper, seq_cst.** At c8274db's acquire sites, seq_cst is the same instruction on x86-64
  (`mov`). It is also the same on AArch64 at both compilers' default targets (`ldar`). It differs only on
  armv8.3+rcpc targets built by gcc or clang, where acquire could be `LDAPR`. The four Dekker re-checks need
  seq_cst (§2.3). One helper for every cross-thread read keeps the rule mechanical: there is no second kind
  of load to choose wrongly. An acquire variant is added only if a profile on such a target ever shows the
  difference (B8).
- **Test switch.** `PLAT_TEST_RELAXED_LOADS`, off by default and test-only, makes the loads relaxed under
  PLAT_GNU. It is L8's mutation.

**Waits** (the H11 pattern: spin, then sleep on a word):
```c
void plat_wait64(plat_a64* p, int64_t seen, unsigned timeout_ms);
void plat_wake_all64(plat_a64* p);
```

| Platform | Implementation |
|---|---|
| Windows | `WaitOnAddress` / `WakeByAddressAll` (`#pragma comment(lib, "Synchronization.lib")` moves here from `gxr.c:20`) |
| Linux and Android | `syscall(SYS_futex, FUTEX_WAIT_PRIVATE / FUTEX_WAKE_PRIVATE)` on the counter's low 32 bits: offset 0 on little-endian, 4 on big-endian |
| Anywhere else | sleep 1 ms and return; the first use prints once "[plat] no futex here; waits poll every 1 ms" |

The low-word trick is safe here. The counters only rise, and a wait lasts at most 50 ms, so a
false-equal needs 2^32 increments inside one wait.

**Spinning and sleeping:**
```c
void plat_relax(void);            /* YieldProcessor / _mm_pause on x86; __yield() or "yield" on ARM64 */
void plat_yield(void);            /* Sleep(0) / sched_yield() */
void plat_sleep_ms(unsigned ms);  /* Sleep / nanosleep */
```

**Clocks.** These sit under `gxr_qpc`, `qpc_hz` and `__rdtsc`/`__cpuid`. `gxr.c`'s calibration logic is kept,
and so are the exported names: `gxr_qpc` and `gxr_clock` (`gxr.h:197-200`) keep their signatures, so the stubs
at `test_memguard.py:57` and `test_profiler.py:58` stay valid.
```c
uint64_t plat_mono_raw(void);        /* QueryPerformanceCounter / clock_gettime(CLOCK_MONOTONIC) ns */
double   plat_mono_hz(void);         /* QPC frequency / 1e9 */
uint64_t plat_mono_ns(void);         /* monotonic nanoseconds, for M19 and the watchdog */
uint64_t plat_cycles(void);          /* __rdtsc on x86-64; CNTVCT_EL0 on ARM64 (_ReadStatusReg / mrs);
                                        otherwise plat_mono_raw() */
int      plat_cycles_invariant(void);/* CPUID 80000007 EDX[8] on x86-64; 1 on ARM64; 0 otherwise */
```

**Threads:**
```c
typedef struct { void* os; } PlatThread;  /* the HANDLE on Windows, kept for SOA_HOSTPROF */
int  plat_thread_start(PlatThread* t, void (*fn)(void*), void* arg, size_t stack_bytes); /* 1 on success */
int  plat_cpu_count(void);                /* GetSystemInfo / sysconf(_SC_NPROCESSORS_ONLN) */
```
- A small heap trampoline carries `{fn, arg}`. It is allocated once per thread, off every hot path.
- `stack_bytes == 0` means the platform default.

**SIMD** (L2a):
```c
PLAT_TARGET_SSE41        /* __attribute__((target("sse4.1"))) under PLAT_GNU; empty under PLAT_MSVC */
int plat_cpu_has_sse41(void); /* 0 off x86-64 */
```
- **Whenever `_MSC_VER` is defined (MSVC and clang-cl):** `__cpuid(r, 1)` from `<intrin.h>`, ECX bit 19, as
  `simd_decide` does today.
  - Not `__builtin_cpu_supports`: under clang-cl linked by `link.exe`, it needs compiler-rt's `__cpu_model`.
    Neither the MSVC libraries nor the NDK's clang-cl supply it, and the link fails with LNK2019 [V, NDK
    clang-cl 19.0.1 probe].
- **Every other x86-64 build** (gcc, clang, llvm-mingw, zig cc): `__get_cpuid(1, ...)` from `<cpuid.h>`, which
  is header-only and needs no runtime library.

**Numerics** (L6):
```c
int32_t plat_f2i(float f);
```
- **Semantics:** x86's `cvttss2si` everywhere. Out of range and NaN give INT32_MIN.
- **On PLAT_X86_64:** `_mm_cvtt_ss2si(_mm_set_ss(f))`. It is the same instruction the cast emits today,
  and the result is defined rather than undefined behaviour.
- **Elsewhere:** `(f >= -2147483648.0f && f < 2147483648.0f) ? (int32_t)f : INT32_MIN`.
- **Test-only switches:**
  - `PLAT_F2I_GENERIC` compiles the "elsewhere" branch on x86, so it can be checked against the instruction;
  - `PLAT_F2I_SATURATE` emulates ARM64's `fcvtzs` (saturate, NaN gives 0) on x86. It is L6's mutation.

**Files and environment** (header-only because they are one-liners):
```c
int plat_fseek64(FILE* f, int64_t off);                 /* _fseeki64 / fseeko */
int plat_setenv(const char* name, const char* value);   /* settings.c's set_env (:54-61) moves here */
```
- **`plat_setenv(name, NULL)` or `plat_setenv(name, "")` unsets the variable:** `unsetenv` on POSIX, and
  `_putenv_s(name, "")` on Windows, which removes it.
- **Why that matters.** `selftest.c:124`'s `_putenv("SOA_SNAP=")` relies on removal. Presence-only switches
  would read an empty value as set: `gxr.c:221` (`getenv("SOA_CULLFLIP") ? 1 : 0`) and `gxr_tev.c:1215`
  (`SOA_GXR_NOTEX`) are two of them.

**Exit:** use C99's `_Exit(code)` from `<stdlib.h>`, not `_exit`. The UCRT has it, and it is the same
immediate exit with no stdio flush. `gx.c:188` changes; `window.c` and `main.c` may keep theirs.

**Directories:** none. `gxr.c`'s `ensure_frames_dir` (:2829-2847) and `exi.c`'s `make_parents` (:98-113) already
have `#ifdef _WIN32 _mkdir #else mkdir(path, 0777)`. If a shared helper is ever wanted, it is `static inline` in
`plat.h`, so the renderer still links alone.

### 3.3 `runtime/plat.c`: the cold half

Each function lands with its first caller, so no code sits on CI compiled but never run.

**L7** (callers in `main.c`, `threads.c`):
```c
void* plat_reserve(size_t bytes);                 /* VirtualAlloc(MEM_RESERVE, NOACCESS) / mmap(PROT_NONE) */
int   plat_commit(void* p, size_t bytes);         /* VirtualAlloc(MEM_COMMIT) / mprotect(RW) */
void  plat_release(void* p, size_t bytes);
typedef int (*PlatFaultFn)(size_t off, int storing, int on_owner_thread); /* 1 = committed, retry */
int   plat_guard_install(void* base, size_t lo, size_t hi, PlatFaultFn fn); /* VEH / sigaction(SIGSEGV) */
unsigned long plat_last_error(void);              /* GetLastError / errno */
int   plat_run_on_big_stack(int (*fn)(void*), void* arg, size_t bytes); /* POSIX: pthread with that stack; Windows: calls fn */
```

**L9** (callers in `settings.c`, `mod.c`, `hle.c`):
```c
int   plat_exe_dir(char* out, size_t cap);        /* GetModuleFileNameA / readlink("/proc/self/exe") */
int   plat_realpath(const char* in, char* out, size_t cap); /* GetFullPathNameA / realpath */
void* plat_dl_open(const char* path, char* err, size_t cap); /* LoadLibraryExA / dlopen(RTLD_NOW|RTLD_LOCAL) */
void* plat_dl_sym(void* lib, const char* name);
void  plat_dl_close(void* lib);
int   plat_list_dirs(const char* dir, void (*fn)(const char* name, void* u), void* u); /* FindFirstFileA / opendir */
double plat_process_cpu(double* user, double* kernel);   /* GetProcessTimes / getrusage */
typedef struct { void* impl; } PlatMutex; void plat_mutex_lock(PlatMutex*); void plat_mutex_unlock(PlatMutex*);
```
`plat_dl_*` land with whichever caller comes first: L9's mod loader, or the GPU backend's Vulkan loader
(gpu-backend.md 3.10 and V5, which create `plat.c` with them if neither L7 nor L9 has landed).

**The POSIX fault guard.** It matches the Windows guard's behaviour (`main.c:541-651`, the MEM1 image, the
handler and `mem_alloc`):
- `sigaction(SIGSEGV, SA_SIGINFO | SA_ONSTACK)` on a `sigaltstack`.
- Offset = `si_addr - base`. Outside [lo, hi), it chains to the previous handler.
- Otherwise it calls `fn`. If `fn` returns 1 (the range is now RW), returning from the handler restarts
  the access.
- `storing`:
  - on x86-64, from `uc_mcontext` (the page-fault error code's bit 1);
  - on AArch64 Linux and Android, from the signal frame's `esr_context` record (`ESR_MAGIC`), ESR bit 6 (WnR),
    when present, and -1 otherwise [I, kernel ABI].
- **One shortcut, stated.** The report that `main.c`'s callback prints uses `fprintf`, which is not
  async-signal-safe. The Windows handler does the same from a vectored handler. It fires once per run,
  on the faulting thread, in generated code, not inside stdio.
- **On Android,** ART's libsigchain routes `sigaction` so the handler chains [I]. The `calloc` fallback
  (`main.c:650`) stays if that fails.

### 3.4 Memory-ordering rules for the queue (c8274db, then L2)

c8274db applied rules 1 and 2 with acquire loads. L2 completes rules 3 and 4, and rewrites the comments at
`gxr.c:1572-1583` and :1786-1794 to state all four.

1. **Publication.**
   - The producer fills the slot with plain stores, then calls `plat_inc64(&g_published)`, whose release
     half publishes them.
   - A worker reads the slot only after `plat_load64(&g_published) > mine`.
2. **Completion.**
   - A worker writes its rows, images and guest memory, then calls `plat_xchg64(&g_ran[id], mine)`.
   - Any thread reads those only after `plat_load64(&g_ran[i]) >= c`.
   - This covers:
     - `wait_ran` → the producer's texture, TLUT and vertex reads;
     - `fence_wait` → the neighbours' EFB rows and copy images;
     - `drain` → the arena, graveyard, hash and PNG;
     - `gxr_presented` → the UI thread's `g_screen`.
3. **Sleepers (Dekker).** One labelling is used everywhere:
   - the **waiter side** is the thread about to sleep: the idle worker (:1780-1781) and the fence waiter
     (:1732-1733);
   - the **waker side** is the thread that raises the count: `publish` (:1619-1621) and a worker finishing a
     command (:1811-1812).

   The rules:
   - Waiter: `plat_inc32(&sleepers)`, then `plat_load64(&count)`, and sleep only if it is unchanged.
   - Waker: `plat_inc64` or `plat_xchg64` on the count, then `plat_load32(&sleepers)`, and wake only if it is
     nonzero.
   - All four operations are seq_cst, so at least one side sees the other's write. The store-buffering
     outcome is forbidden.
   - Today these loads are plain, and correct only because an MSVC Interlocked call is a full barrier. They
     become `plat_load*` **in the same change** that maps the RMWs to `__atomic` for PLAT_GNU. A separate
     fence would also work, but a seq_cst load is one rule, and one instruction on these targets.
   - The 50 ms bound stays as the backstop.
4. **Every cross-thread read goes through `plat_load*`.**
   - The producer's reads of its own `g_published` stay plain, as c8274db decided. Each carries the marker
     comment `/* own count */`.
   - **Enforcement is a grep test, not wrapper types.** `tools/tests/test_gxr_atomics.py` checks every
     occurrence of `g_ran[`, `g_published`, `g_sleepers`, `g_fence_sleepers` and `g_frames_presented` in
     `runtime/gxr.c` outside comments. Each must be:
     - an argument of a `plat_*` call;
     - its declaration; or
     - on a line marked `/* own count */`.
   - The test also asserts that each name appears inside at least one `plat_*` call, so it cannot pass
     vacuously after a rename.
   - Wrapper types would force the producer's own reads through helpers for no change in machine code.

The compiler barriers at :1661, :1744 and :1795 become `plat_compiler_barrier()` and **stay**. They cost
nothing. Deleting them would need its own codegen proof, and would buy nothing. `_ReadWriteBarrier` itself does
not exist for gcc or clang, which is why the NDK check lists :1661.

**What this does not fix:** `g_screen` is one buffer. The UI thread presents it (`window.c:267-280`)
while workers may be writing the next frame's copy into it. That is a pre-existing tear risk on every
platform, not an ordering bug (§7 B1).

### 3.5 SIMD behind an x86-64 guard, scalar kept (L2a)

1. The guard becomes `#if PLAT_X86_64`. clang-cl, `clang --target=*-windows-msvc`, llvm-mingw, zig cc and
   Linux gcc/clang on x86-64 all get the SIMD path.
2. The blend moves out of `sample_level` into its own function:
   `static PLAT_TARGET_SSE41 uint32_t bilinear_sse41(uint32_t q00, uint32_t q10, uint32_t q01, uint32_t q11, int ax, int ay)`.
   It is `__forceinline` under PLAT_MSVC, so MSVC's code is unchanged; L2a's Done compares it.
3. Under clang and gcc, a target-attributed function cannot be inlined into a baseline caller, so each
   bilinear sample is a call. The probe confirmed that pattern compiles on both compilers, with a `callq`
   under clang-cl [V].
   - L3b measures what the call costs.
   - If it matters, the next step is the per-draw span function marked with the target attribute, not a
     global `-msse4.1`. A global flag would let clang use SSE4.1 anywhere in the file and make the
     run-time check meaningless.
4. `simd_decide` uses `plat_cpu_has_sse41()` (`__cpuid` whenever `_MSC_VER` is defined, §3.2).
5. ARM64 takes the scalar loop. NEON is not planned; the scalar loop is the reference.
6. **The differential test.** `test_gxr_fastpath.py`'s test (600,000 random points,
   `test_gxr_fastpath.py:266-272`) asserts zero mismatches.
   - Its "red with one weight pair swapped" mutation was a one-off by hand, recorded in b377b1f's message.
     It is not in the test. L2a re-runs it once, on `bilinear_sse41`, and records it in FINDINGS.
   - L3a makes the module read `SOA_CC`, and L4a runs it in the clang-cl CI leg.

### 3.6 One fma macro (L5)

The emitter writes `SOA_FMA(a, c, b)` where it writes `fma(a, c, b)` today (`emit.py:147-159`,
`:173-180`). `cpu.h` defines it once:
```c
#ifndef SOA_FMA
#if defined(SOA_FMA_UNFUSED)          /* test-only: the mutation that must fail the self-test case */
#define SOA_FMA(a, b, c) ((a) * (b) + (c))
#elif defined(__clang__) || defined(__GNUC__)
#define SOA_FMA(a, b, c) __builtin_fma((a), (b), (c))   /* a libcall, or one instruction on FMA targets */
#else
#define SOA_FMA(a, b, c) fma((a), (b), (c))
#endif
#endif
```
- **Why the switch is a plain name.** MSVC's `/D` cannot define a function-like macro (Microsoft Learn, "/D
  (Preprocessor Definitions)"). So the mutation is `/DSOA_FMA_UNFUSED`, which contains no `=` and can
  therefore also go in the `CL` environment variable.
- **Why a macro:**
  - H13a's "inline fma" becomes one line here (an `_mm_fmadd_sd` path under `__FMA__`/`__AVX2__`),
    with no emitter change;
  - every host gets an exactly rounded fused op;
  - a test can swap in an unfused form to prove the test can fail.
- **Cost:** editing `cpu.h` and the emitter means one full retranslation. Fold it into the next
  retranslation already planned.
- **The self-test case "fma is fused and exact":**
  - `SOA_FMA(1 + 2^-30, 1 - 2^-30, -1) == -2^-60` exactly; unfused gives 0;
  - three more rows where fused and unfused differ, including a double-rounding row for the single forms'
    `(float)` step;
  - the operands are read through `volatile` locals, so the compiler cannot fold the case at compile time
    and skip the path being tested.

### 3.7 32-bit words in the native twins (L4b)

**`include/types.h`:**
- the `__MWERKS__` branch keeps today's typedefs byte for byte, so mwcc objects cannot change;
- the other branch uses `<stdint.h>`/`<stddef.h>`: `typedef uint32_t u32; typedef int32_t s32;`, with
  `size_t` from `<stddef.h>` and `_Static_assert(sizeof(u32) == 4, ...)`.

**The five units that use `long` as a word** replace `unsigned long` with `u32` wherever it means the 32-bit
machine word (`fillmem.c`, `strcpy.c`, `strcmp.c`, `strstr.c`, `string.c:48`), and fix the comment at
`strcmp.c:18`.
- Under mwcc, `u32` is `unsigned long`, so `decomp.py`'s byte match cannot move.
- Non-native units are left alone.

**`tools/citest/dc_driver.c` gains `test_strcpy`, `test_strcmp` and `test_strstr`,** so `dc_check` compares all
twelve swapped-in routines with libc, not nine.

**The test that can fail:** `dc_check.py` on Linux (L4b's CI leg).
- Before the change, `fillmem`'s 8-byte stores run into the driver's guard band (through `memset`), and
  `strcpy`'s word test misses terminators [I].
- After it, the check passes.

### 3.8 Renderer determinism (L6)

**Float-to-int:**
- Every signed site in §2.6 goes through `plat_f2i`.
- The unsigned depth casts at `gxr.c:926` and :1011 keep their form, with a comment and a driver case, since
  every target gives 0 for NaN there [I].
- **Codegen on x86.** The helper is the same `cvttss2si`, but replacing a cast with an intrinsic can change
  what MSVC generates around it. For example, it could stop the vectoriser on the four-channel loops at
  `gxr.c:1238-1243` and :1300. So L6 compares the disassembly and measures only if it moved.

**`exp2f` and `log2f`: own correctly rounded implementations, not a tolerance.**
- **Source:** CORE-MATH's binary32 `exp2f` and `log2f`.
  - MIT licence (core-math.gitlabpages.inria.fr).
  - Correct rounding checked exhaustively by its authors, and tested with and without `fma`.
  - Correct rounding means the same output on every host, whatever the code does inside.
- **Where they go:** `runtime/crmath.c` as `soa_exp2f`/`soa_log2f`, with the MIT header, a NOTICE
  entry, and the GCC builtins (if any) behind macros so MSVC builds them [I, to be checked in the slice].
- **Fallback if the port to MSVC is not clean:** a hand-written double-evaluated version held to the same
  exhaustive check.

**Windows effect.** It changes 74,154 raw `exp2f` and 313,550 raw `log2f` outputs. After quantisation
that is 1 fog input in 1,090,519,041 and 0 LOD roundings (§2.5). Replay decides; if a hash moves, the
frame is opened.

**Check.** `tools/citest/libm_check.py` builds a stdlib-only driver and runs it exhaustively.
- **Domains:** `exp2f` on [-8, 0]; `log2f` on (0, +inf).
- **Speed:** about 45 s on this machine at idle priority for both [V, the probe's timing].
- **Output:** one FNV-1a hash over all outputs.
- **Arbitration:** wherever the double-precision host reference lies within 2^-40 (relative) of a
  rounding boundary, Python's `decimal` at 50 digits decides.
- **Baseline:**
  - The hash is pinned in `config/libm.tsv`, a new baseline.
  - Its commit says how it was inspected: every output agreed with the double reference except the
    arbitrated inputs, all of which `decimal` confirmed, and their count is quoted.
  - Every CI leg prints the same hash.
- **Mutation.** Link UCRT's `exp2f` in place of `soa_exp2f`. The check must then report exactly the 74,154
  known differences (§2.5). The fallback mutation flips a coefficient bit of weight 2^-20 or larger.
  - A last-bit flip is not enough. It moves a double result by about 2^-52, so a float output changes only
    within about 2^-28 of a rounding boundary. That could be no input at all.

### 3.9 Toolchain profiles (L3a, L4b)

**`tools/soa/toolchain.py`** gains a frozen `Profile(name, style, cflags, strict, objext, exeext)`, and
`cc(args, cwd, profile)` generalises `cl()`. `CFLAGS` stays exported, equal to the msvc profile, for every
existing caller.

| Profile | Found by | cflags | Output |
|---|---|---|---|
| `msvc` (default) | vswhere, as today | unchanged: `/std:c17 /O2 /fp:strict /W3 /wd4102 /wd4702 /wd4101` | `gen/` |
| `clang-cl` | `SOA_CLANG_CL`, then `PATH`, `C:\Program Files\LLVM\bin`, then VS's `VC\Tools\Llvm\x64\bin`; the MSVC environment still supplies headers, libs and `link.exe` | `/std:c17 /O2 /fp:precise /clang:-ffp-contract=off /clang:-fno-strict-aliasing /clang:-fwrapv /D_CRT_SECURE_NO_WARNINGS /W3 /wd4102 /wd4702 /wd4101 -Wno-comment` | `gen/clang/` |
| `gcc`, `clang` (style `gnu`) | `PATH` | `-std=c17 -O2 -ffp-contract=off -fno-strict-aliasing -fwrapv -D_GNU_SOURCE -Wall` + link `-pthread -lm` | `gen/linux/` |
| `msvc-arm64` (L8, L11) | vswhere + `vcvarsarm64.bat` / `vcvarsamd64_arm64.bat` | msvc's | `gen/arm64/` |

**Why the non-MSVC flags:**
- `-ffp-contract=off`: §2.8, [V].
- `-fno-strict-aliasing` and `-fwrapv` make clang's semantics MSVC's, which uses no type-based alias
  analysis and wraps in practice. That removes two classes of "clang drew it differently" before they
  cost a bisection.
  - `window.c:207` and `audio_out.c:115` read `uint8_t` buffers through wider types.
- Never `-ffast-math` or `-Ofast`: `cr_fcmp` detects NaN with `a != a` (`cpu.h:298`).

**Strict-warning sets per profile:**
- MSVC's `/we4013 ...` (`compile_runtime.py:50`).
- clang-cl and gnu: `-Werror=implicit-function-declaration`, `-Werror=int-conversion`,
  `-Werror=incompatible-pointer-types`, `-Werror=return-type`.

**`tools/recompile.py --cc <profile>`:**
- A non-msvc profile defaults `--out` to its directory: `--cc clang-cl` means `--out gen/clang`, and
  `--cc gcc` means `--out gen/linux`. The C, the objects, the pdbs and the exe all go there. The emitted C is
  the same C; it is emitted again into that directory.
- `--link` already globs only `--out` (:199). **A clang build can never be linked into `gen/soa.exe`, and
  `gen/` is never touched,** which matters because `--link` never checks what it globs (CLAUDE.md).
- **A non-msvc profile does not build `mods/*/mod.c`.** The shipped mods are MSVC DLLs for `gen/soa.exe`
  (comfort-pack.md P1a makes the msvc `--link` build them); L9 builds `mod.so` on Linux.
  `test_toolchain_profiles.py` asserts that the clang-cl link plan names no path outside `gen/clang`,
  `mods/` included.
- disc-layer.md I3's `build_inputs.txt` (G5's DOL line), written into `--out`, records the profile's name
  too.

**`--cc` also reaches** `compile_runtime.py`, `dc_check.py` and `render_check.py` (L3a for clang-cl; L4b for
gcc and clang), plus a new `queue_check.py` (L8). The gnu profile translates `/D`, `/I`, `/Fo` and `/Fe` into
`-D`, `-I` and `-o`.

**Which tests become profile-aware, and who owns each:**

| Test | Owner | Why |
|---|---|---|
| `test_gxr_fastpath.py` | L3a (reads `SOA_CC`); runs in L4a's clang-cl leg | the SIMD path is the part that differs by compiler |
| `test_gxr_overlap.py`, `test_gxr_queue.py` | L8, through `queue_check.py` | memory ordering is the part that differs by processor |
| `test_memguard.py` | L7 | the fault guard is per platform |
| `test_mods.py`, `test_settings.py` | L9 | the loader and the settings path are per platform |
| the other six `test_gxr_*` (alpha, copy_filter, lifetimes, pair, texcache, tripwires) | none; they stay MSVC-only | They pin renderer semantics that no profile changes. What a profile can change (UB, contraction, SIMD, ordering) is covered per profile by fastpath, `queue_check`, `render_check` and L3b's replay. Making them profile-aware later costs no design |

**One list of runtime support sources.** `toolchain.runtime_support_sources()` returns `[runtime/plat.c]` once
L7 creates it, and `[]` before. Every test that links a runtime file calling `plat.c` adds it, or it fails at
link with LNK2019:
- `test_memguard.py:179-181` and `test_profiler.py:140-142` (they link `main.c`), from L7;
- `test_profiler.py:342` and `test_uncap.py:152` (`hle.c`), `test_mods.py:169` (`mod.c`) and
  `test_settings.py:65` (`settings.c`), from L9.

**`tools/scenario.py replay --bless`** is refused unless `--exe` is the default `gen/soa.exe`. The manifest is
MSVC's. (It already refuses a `--fifo` other than the corpus, `scenario.py:1092`.)

**The `[boot]` line names the compiler:** `_MSC_FULL_VER` or `__clang_version__`/`__VERSION__`. Every
log then says which build wrote it (L3b).

### 3.10 Churn: who edits which file, and when

| File | At 012164a | Later owner | Portability slice | Rule |
|---|---|---|---|---|
| `runtime/gxr.c`, `gxr.h`, `gxr_tev.c`, `gx.c` | N4 landed (c8274db); C5a landed (750cef0, `gx.c`, a log only) | P5b (copy-filter switch) and M11a-skip (comfort pack), C5a/C5b (display lists), H17a (second EFB), V2 (GPU spike) | L2a, L2, L6, L8 (two small race fixes) | One session at a time. **L2 before V2 and before H17a is preferred, not required.** Both add code to the worker loop that L2 converts; if either lands first, L2 converts what it added. ../PLAN-NEXT.md puts L2 after H17a and before V2 (M4a) |
| `runtime/mod.c`, `soa_mod.h` | N2 done (3949028, b071949, b1199b3); P1a in flight (`mod.c`) | M3d, M15, M16, M17 | L9 | After whatever Track M slice is open |
| `.github/workflows/ci.yml`, `tools/guard.py` | N3 done (1c7b780, 4041dfc); T0c done (012164a) | — | L4a, L4b, L7, L8 | Any time; one CI job per slice |
| `runtime/settings.c`, `runtime/hle.c` | P6 and P6b landed (24d9235, 79c9ad8); P1a in flight (`settings.c`) | M19 (clock), M5b | L9 | After P1a, M5b and M19. **M19 should build on `plat_mono_ns()` if L2 has landed**, so its clock is portable when written, not rewritten later |
| `runtime/main.c` | P6 and P6b landed; P1a in flight | I1 (boot from `disc.iso`), M5b | L3b (the `[boot]` line), L7 (memory guard :541-651, watchdog :465-536 and the guest stack only) | One session at a time; L7 stays out of the boot path |
| `runtime/selftest.c`, `tools/citest/render_driver.c` | P6 landed (24d9235, `selftest.c`) | M5b, M18, M19 (self-test cases) | L2 (`plat_setenv`; `render_env()`), L4b (`render_check --threads`), L5 (the fma case) | `render_driver.c` changes in the **same commit** as `selftest.c`'s copied block (`test_citest.py:88-101`) |
| `runtime/dvd.c`, `runtime/aram.c` | — | M5b (`aram_set_data_dir`), I1-I3 (disc layer) | L2 (one line in `dvd.c`); none in `aram.c` (M5b and I1 did it) | disc-layer.md §3.2 uses L2's `plat_fseek64`, or a local wrapper if I1 lands first, which it does under ../PLAN-NEXT.md (M3 before M4a); L2 moves that wrapper into `plat.h` |
| `runtime/window.c` | — | H19a, M18, M5b, M19, CH1, P10a, P5a, M11a | none until L10 | Windows backend; no shim |
| `runtime/audio_out.c` | — | M5b (mute on focus loss) | L9 (the WAV writer out of the `#ifdef`) | After M5b |
| `runtime/si.c` | P6b landed (79c9ad8, buffer sizes) | M5b (`si_set_path_root`), M18, P10a, CH1 | none | — |
| `runtime/cpu.h`, `tools/soa/recomp/emit.py` | — | the next retranslation batch | L5 | Bundle with it |
| `tools/soa/toolchain.py`, `tools/recompile.py`, `tools/citest/*` | — | P1a (`--link` builds the mods), disc I3 (`disc_sys.c`, `build_inputs.txt`), G5 | L3a, L4b, L7, L8 | Whichever of P1a and L3a lands second keeps the mod build to the msvc profile (§3.9); I3 (M3) builds on L3a's per-profile directories |
| `include/types.h`, `src/sdk/msl/*` | — | Track F | L4b | `decomp.py` after |
| `tools/scenario.py` | — | — | L1 (`--wrap`), L3a (bless guard) | `title --check` after each (CLAUDE.md's table) |

### 3.11 clang-cl against MSVC: should the frames match, and how to judge if not

**Expected: bit for bit.** The reasons:
- Both link the same static CRT (§2.1). The libm probe's identical counts for both builds are
  consistent with that [V].
- Both do scalar SSE2 arithmetic with `FLT_EVAL_METHOD` 0.
- Contraction is off in both (MSVC `/fp:strict`; clang `-ffp-contract=off`, proven by L3a's codegen
  test).
- Neither uses fast-math.

What could still differ:
- undefined behaviour in our C (out-of-range casts, overflow, uninitialised reads, aliasing: the last two
  are reduced by the flags above);
- unspecified behaviour (argument evaluation order; `fmaxf(-0, +0)`);
- a builtin one compiler expands inline differently.

Each of those is a latent bug, not a tolerance.

**The check (L3b):**
- the self test, replay 23/23 at 1, 2, 3 and 8 threads, and `title --check`, all on `gen/clang/soa.exe`;
- against the MSVC-blessed manifest;
- with `--bless` refused for that exe.

**If a hash differs:**
1. **Nothing is re-blessed.** Note the capture and the thread counts it differs at.
2. **Check it at `SOA_THREADS=1`.** A difference that depends on thread count is a race, handled as one.
3. **Open both PNGs.** Count the differing pixels and the largest channel difference, and pick one pixel.
4. **Bisect by object file.**
   - COFF objects from both compilers link together with `link.exe` [I, standard].
   - Relink the clang build with MSVC's `gxr.obj`, then `gxr_tev.obj`, then `gx.obj`. The swap that
     restores the hash names the file.
   - The renderer-alone build (`render_check.py`'s link) is the quick bench for this.
5. **Narrate the pixel.** Run `SOA_GXR_PIXEL=x,y` in both builds; the first value that differs names the
   expression.
6. **Classify and fix at the source,** so that both builds give MSVC's hash:
   - contraction: fix the profile, and extend the codegen test;
   - UB: fix the C. It was a bug under MSVC too;
   - unspecified behaviour: make the C explicit;
   - an inline builtin: call the function explicitly.
7. **A FINDINGS entry** names the capture, the pixel, the cause and the fix.

### 3.12 CI legs

| Job | Runner | Steps | Lands in |
|---|---|---|---|
| `native` (exists) | windows-latest | as today; its whole COVERED comment (:92-125) corrected | L4b |
| `test` (exists) | ubuntu-latest, windows-latest | `pytest tools/tests`; on windows-latest the 19 C-building modules run under MSVC | — |
| `clang-cl` | windows-latest (LLVM 20.1.8) | `compile_runtime.py --cc clang-cl`, `dc_check.py --cc clang-cl`, `render_check.py --cc clang-cl`, and `pytest tools/tests/test_toolchain_fp.py tools/tests/test_gxr_fastpath.py` with `SOA_CC=clang-cl` | L4a |
| `linux` | ubuntu-latest, matrix `gcc` and `clang` | `compile_runtime.py --cc $cc`, `dc_check.py --cc $cc` (LP64, twelve routines), `render_check.py --cc $cc --threads 1` and `--threads 4` | L4b |
| `linux` (grows) | ubuntu-latest | `test_memguard.py`, `threads_check.py` | L7 |
| `tsan` | ubuntu-latest | clang `-fsanitize=thread`: `render_check`, `queue_check` | L8 |
| `arm64-linux` | ubuntu-24.04-arm | gcc: `compile_runtime`, `dc_check`, `render_check`, `queue_check` at `SOA_THREADS` 1, 2, 3 and 4 with stalls | L8 |
| `arm64-windows` | windows-11-arm | MSVC ARM64: the same four | L8 (after B4) |

- **`queue_check` repeats drivers** that the `test` job's windows-latest leg already runs under MSVC x64. Its
  value is the other profiles and the ARM hardware, and `ci.yml` says so.
- **No job gets game data.** Everything is synthetic streams and generated inputs, as today.
- **Each job fails loudly when its compiler is missing,** as `compile_runtime.py:76-80` does now.

### 3.13 Wine and Proton (L1)

**Wine can be tested on this PC, headless, with no new hardware.**
- **Where:** a Linux container through the Docker Desktop that is already running (`wsl -l -v` lists
  `docker-desktop`), or a WSL Ubuntu the owner installs.
- **Image:** the distribution, a Python at least CI's 3.14, and the distribution's `wine`. Nothing else, and
  never game data.
- **What the container sees:**
  - The repository checkout, with `gen/soa.exe` and `extracted/`, is **bind-mounted read-only** from the
    host. Nothing of it is copied into an image layer, so no image that could be pushed holds game data.
  - The replay needs `extracted/` too. `main.c` still opens the disc for `--replay`, and `scenario.py`
    refuses to start without it (`scenario.py:1099-1106`). The self test is `soa.exe extracted`, and
    `title --check` boots the disc.
  - **The host's `build/` is not mounted.** A fresh scratch volume is mounted over `build/` inside the
    container. It holds only a copy of the captures and a copy of a card, both writable, so no original can
    be overwritten (`--replay` writes `<base>.png` beside its input) [I: that runs write nothing outside
    `build/` is to be confirmed in the slice].
- **Command prefix:** `tools/scenario.py` gains `--wrap "<prefix>"` for `run` and `replay`, e.g.
  `--wrap wine`.
- **WSL pitfall:** under WSL, running `gen/soa.exe` without `wine` starts a *Windows* process through
  WSL's interop. The prefix is not optional there.

**What it can show:**
- **The math is the same code.** The CRT is inside the exe, so replay 23/23 should hold under Wine.
  A difference would be a Wine defect, or a race another scheduler exposed. Neither is re-blessed.
- **The self test and `title --check`** exercise `WaitOnAddress` (Wine has had it since 3.19, and a
  futex-based one since 4.2), the vectored-exception guard, fibers and the `/STACK` link.

**What it cannot show:**
- DXVK presentation, Steam Input, the Deck's refresh (60 Hz LCD, 90 Hz OLED), or its speed.
- The Deck is 4 Zen 2 cores, so 6 rasterizer workers. Heavy scenes will likely run below 30 fps on the
  CPU renderer [I].
- These are an **Owner** session on a Deck or Linux PC, if there is one.

**Rules:**
- Wine runs are `soa.exe` runs, so CLAUDE.md's one-at-a-time rule applies. Never run one while the
  implementation session is timing.
- Game data stays on the owner's machine and never goes to CI.

### 3.14 Later steps, gated

- **L10, native Linux x86-64.**
  - An SDL3 window, pad and audio behind today's seams:
    - `window_start`, `window_open` and `window_pad` (`window.c:365-461`);
    - `gxr_screen` and `gxr_presented`;
    - `audio_push_block` (`audio_out.c:97`).
  - SDL3 3.4.x is fetched and hash-pinned at build time. It never goes in `vendor/`, which the guard
    refuses.
  - Headless checks run in WSL2 on this PC; WSLg can show a window.
- **L11, ARM64.**
  - **Windows on ARM:** MSVC ARM64 cross-build from this PC.
  - **Linux ARM64:** gnu cross-build.
  - **QEMU user emulation** in Docker (`--platform linux/arm64`) replays at one thread on this PC. It
    covers float, cast and libm semantics, not memory ordering, which L8's CI hardware covers
    synthetically.
  - A real device replays at 1, 2, 3 and 8 threads.
- **L12, Android.**
  - An NDK `.so`, a Gradle shell, lifecycle and surface loss, and M19's pause-aware clock.
  - SAF import into the disc layer's store, a touch overlay feeding `window_pad`, and AAudio or SDL3 at
    48 kHz.
  - **One app data root for every relative path.** Android starts in `/`, so each of these fails there:
    `main.c:105` and :1087, `exi.c:90`, `si.c:294`, `gx.c:143` and `gxr.c`'s `frames_dir`.
  - It is not playable without the GPU backend.

### 3.15 Config keys, logging, failure modes

**Player-facing keys: none new.**

**Build keys:**
- `SOA_CC`: `msvc`, `clang-cl`, `gcc`, `clang` or `msvc-arm64`; the default is `msvc`.
- `SOA_CLANG_CL`: a path.
- `SOA_NDK`: the NDK's root for the local ARM64 syntax check; the default is
  `%LOCALAPPDATA%\Android\Sdk\ndk\28.2.13676358`.
- `recompile.py --cc`, and the citest scripts' `--cc`.
- `render_check.py --threads N` (L4b).
- `scenario.py --wrap` (L1), and `perfbench.py --exe` (L2a).

**New log lines:**
- `[boot] built by <compiler> <version>` (L3b).
- `[plat] no futex here; waits poll every 1 ms`, once, and only where it applies.
- `[gxr] SOA_HOSTPROF is Windows-only here; use perf`, when the switch is set off Windows.

| Failure | What happens |
|---|---|
| Thread start fails | Fewer workers, as `gxr.c:2030` does today |
| No futex | 1 ms polls, stated once |
| Reservation or guard install fails | The `calloc` fallback and today's `[mem]` message, with `plat_last_error()` |
| `dlopen` fails | The mod is refused, naming `dlerror()` |
| The executable's folder is unknown | The working directory, as today off Windows (`settings.c:84-88`) |
| A profile's compiler is missing | The script fails and says so; it never skips |

---

## 4. Alternatives considered

| Alternative | Why not |
|---|---|
| C11 `<stdatomic.h>` everywhere | MSVC's C mode needs `/experimental:c11atomics`, an experimental flag in the reference build. The `__atomic` builtins give the same semantics on clang and gcc, and the MSVC intrinsics keep today's x64 code |
| Keep `volatile` and build ARM64 with `/volatile:ms` | MSVC-only: clang has no ARM64 equivalent (clang-cl passes `-fms-volatile` on x86 only [V]). It also leaves the rule implicit, which is how `drain` ran without machine-level ordering until c8274db |
| Acquire loads only (c8274db as it stands) | Right for publication and completion. Not right for the four Dekker re-checks once the RMWs are `__atomic` (§2.3) |
| Wrapper types for the counters (this spec's first draft) | c8274db kept plain counters and plain own-count reads. A wrapper would force those reads through helpers for no change in machine code. The grep test with marked own-count lines enforces the same rule |
| A mutex and condition variable instead of futex | It changes the wake latency H11 measured, and costs a lock per publish. Futex has `WaitOnAddress`'s semantics exactly |
| SDL3 as the platform layer for threads, atomics and clocks too | Q6 is open, and SPEC.md:463-464 says "no third-party runtime dependency". The renderer-alone builds would then need SDL. SDL3 stays behind window, pad and audio (L10) |
| Separate `plat_win32.c` and `plat_posix.c` | The runtime's style is `#ifdef` sections in one file. The renderer-alone rule needs the hot half header-only anyway |
| A `plat_mkdir_p` in `plat.c` for the frames directory | `gxr.c` would then need `plat.c`, breaking the renderer-alone link that `render_check` and nine test modules rely on. The code is already portable (§3.2) |
| `__builtin_cpu_supports` for SSE4.1 everywhere | Under clang-cl with `link.exe` it does not link (`__cpu_model`) [V] |
| A tolerance oracle for replays on other platforms | It agrees with near-misses by construction; CLAUDE.md's trap. An exact oracle is achievable (§3.8). The GPU backend needs a tolerance oracle and gets one in its own spec |
| Keep UCRT's `exp2f`/`log2f` on Windows and use own ones elsewhere | That splits the replay oracle per platform |
| clang-cl `/fp:strict` | Strict exception semantics disable optimisations for nothing: no `fenv` use [V] |
| Compile `gxr_tev.c` with `-msse4.1` under clang | clang could then use SSE4.1 anywhere in the file, and the run-time check would stop protecting pre-SSE4.1 CPUs. Revisit only with the owner's CPU floor (Q5) |
| Build clang objects into `gen/` | `--link` globs `--out`'s `chunk_*.obj` blindly, so a mixed-compiler exe could be linked silently |
| A Deck for the first Proton test | Wine in a container on this PC answers the binary and math questions in hours with no hardware. The Deck adds only presentation, controls and speed, which an owner session covers |
| A `ucontext` coroutine for threads off Windows | Not in bionic [V, research]. Rejected **while the evidence holds**: every log so far shows one guest thread, so the same-stack `longjmp` is all that is needed, and a second thread keeps the clear `exit(6)`. §5 risk 18 says what a second thread would need |
| A new `gen/`-style interface for a prebuilt Android APK | That is the distribution question (Q3/G4), not portability |

---

## 5. Risks and concerns, stated plainly

1. **The implementation session is editing now.** N2, N3, N4, P6, C5a, P6b and T0c have landed (P6 at
   24d9235, C5a at 750cef0, P6b at 79c9ad8, T0c at 012164a). At 012164a P1a (`mod.c`, `main.c`,
   `settings.c`, `recompile.py`) was in the working tree. Later the comfort pack edits `gxr.c` (P5b,
   M11a-skip). Portability work competes for `gxr.c`, `settings.c`, `hle.c`, `main.c`, `selftest.c`,
   `mod.c` and `ci.yml`. The churn table (§3.10) is the plan. One session edits `gxr*.c` and `gx.c` at a
   time.
2. **clang is broken on the renderer today** (b377b1f, §2.2) [V]. It costs nothing under MSVC.
   - clang-cl, or any clang build that defines `_MSC_VER`, fails to compile `gxr_tev.c`.
   - G4's llvm-mingw or zig cc compile it and silently lose the SIMD path.
   - L2a (hours) fixes both.
3. **The native twins would corrupt guest memory off Windows,** silently (§2.4). `memset` and `strcpy`
   run constantly. This must land before any Linux or Android game run, and it will: L4b's CI leg fails
   until it does. It needs `dc_check` to test `strcpy`, `strcmp` and `strstr`, which it does not today; L4b
   adds them.
4. **ARM64 and the render queue.**
   - c8274db fixed publication and completion with acquire loads.
   - The four Dekker re-checks are still plain loads. They are correct under MSVC only because Interlocked
     calls are full barriers. They must become seq_cst in the same change that moves the RMWs to
     `__atomic` (L2).
   - None of this **can be shown on this PC:** x64 hardware never reorders these loads.
   - The proof is L8's TSAN leg (deterministic), with the ARM runners as corroboration. L8 now follows L4b
     directly. Until it lands, "correct on ARM" is an argument, not a measurement.
5. **The ordering work makes nothing faster.** c8274db's x64 code was unchanged apart from register
   allocation in `fence_wait`. L2's first step should be the same. Do not expect a number.
6. **A clang-cl mismatch could cost days.** If one appears, it is most likely a real UB bug in our C.
   §3.11 bounds the bisection, but a mismatch could be the most expensive thing in this spec.
7. **Own `exp2f`/`log2f` change Windows arithmetic** (74,154 and 313,550 raw outputs). The measured
   pixel-level effect is 1 fog input in about a billion. Replay decides; if a hash moves, the frame is
   opened, never re-blessed to go green.
8. **The CORE-MATH files compiling under MSVC is unverified** [I]. The fallback is hand-written code under
   the same exhaustive check, which is days, not hours.
9. **Wine passing is not the Deck.** It proves the binary and its math, not presentation, controls or
   speed. Heavy scenes on a Deck will likely be under 30 fps with the CPU renderer [I]. That is an
   argument for the GPU backend, not against Linux.
10. **Running Wine, Docker or clang builds on this PC disturbs timing.** It perturbs the implementation
    session's A/Bs (15% drift already) and falls under the one-`soa.exe`-at-a-time rule. Schedule them. The
    local `gen/*.c` syntax check runs at idle priority, and only when nothing is being timed.
11. **The guest's 32 MB stack.** Off Windows the guest must run on its own 32 MB thread
    (`plat_run_on_big_stack`), because the main thread has 8 MB.
    - That changes which thread "is the guest" for the memory guard's thread check. Windows is unaffected.
    - clang's frame sizes also differ from MSVC's: the guest's call depth becomes host depth, and 32 MB has
      been generous so far [I].
12. **Counts rot.**
    - "22 runtime files" is written in six places (§2.7), against 26 committed files at 012164a (P6's
      `seed.c`). Each later slice that adds a file (`picture.c`, `clock.c`, `disc.c`, `sha1.c`, `vfst.c`,
      `delta.c`, `plat.c`, `crmath.c`) moves the count; measure it rather than forecast it.
    - HANDOFF.md:503's "four `test_gxr_*` modules" is nine.
    - L4b fixes every copy, and each later slice that adds a file or a test does the same (CLAUDE.md,
      "Counts in prose rot").
13. **Mods are Windows DLLs.** A mod written against Win32 (P1's plan uses `GetEnvironmentVariableA`)
    will not build as a `.so`. M16's option API is the portable answer. `soa_mod.h` gains
    `SOA_MOD_EXPORT` in L9, additively, with no API bump.
14. **The POSIX fault handler prints with `fprintf`,** which is not async-signal-safe. It is the same
    pragmatism as the Windows handler: once per run, on the faulting thread.
15. **SDL3 (Q6) blocks native Linux and Android input and output.** Until you decide, only the headless
    parts can be checked on Linux.
16. **Android without a GPU backend is slide-show speed.** The research puts it at single digits to the
    mid-teens in heavy scenes on phones [I]. L12 is gated on that decision for a reason.
17. **A higher CPU floor is a real trade.** H13a's "inline fma with `/arch:AVX2`" would require AVX2
    (x86-64-v3). The Deck and the Z1 Extreme have it; older PCs do not. That is Q5, not a detail to slip in
    with L5.
18. **A second guest thread would stop a Linux or Android build.**
    - The one-thread evidence is 326 logs of early-game scenarios (`port-beyond-iso.md:328`).
    - If a later part of the game creates a thread, a non-Windows build exits 6 with "[threads] ...
      Windows-only".
    - The remedy is a hand-written context switch in assembly for x86-64 and AArch64. That is several days,
      and not in this spec.
    - A long Windows playthrough that keeps its log would retire or confirm the risk cheaply (Q9).
19. **TSAN will find old, harmless races first.**
    - `g_notex` (`gxr_tev.c:1158`) is written lazily by every worker inside `sample()` (:1215).
    - `WARN_ONCE`'s `static int said` (`gxr.c:273-280`) is written by any worker that warns.
    - L8 fixes both before its gate can mean anything.
20. **Speed gates below the noise prove nothing.** Interleaved 8-thread blocks spread 64.9-77.2 ns in one
    day (FINDINGS "H15d paused"), so a 2% gate there is noise.
    - Gates here are codegen comparisons first.
    - A timing is taken only if the code moved: at one thread for pixel-path changes, where blocks agreed
      within about 1%, and as wall time for queue changes. `perfbench` measures worker busy time, which leaves
      out the spin and idle time a queue change moves.

---

## 6. Slices

*Superseded for order by [../PLAN-NEXT.md](../PLAN-NEXT.md): M4a = L2, L4a, L4b, L8, L3b, L1 (L2a and L3a
in M1's gaps); M4b = L6, L7, L9 after the GPU gate by default (its D-10); L5 rides the next planned
retranslation (its C7). The order below is this spec's own, kept for its reasoning.*

**Order.** The owner's pivot puts this groundwork third: finish N5 and N6, then the comfort pack, then the
disc layer, then portability, then the GPU decision. This spec follows it.
- **Done:** L0 (c8274db).
- **In any gap, with no renderer edit:** L3a (toolchain profiles, `tools/` only). L1 when the machine is
  free and Q1 is answered. L5 rides the next retranslation.
- **After the comfort pack's `gxr.c` slices (P5b, M11a-skip) and the disc layer:** L2a, L2, L3b, L4a, L4b,
  L8, then L6 and L7, then L9.
- **One preference.** L2 lands before V2 (the GPU spike's `DrawCmd` interface) and before H17a (the second
  EFB), because both add code to the worker loop that L2 converts. If H17a is scheduled straight after the
  comfort pack, that means moving L2a and L2 (a day to several days together) ahead of the disc layer. That
  is a deviation from the pivot, and Q8 asks for it. It is a preference, not a dependency: if H17a lands
  first, L2 converts what H17a added.
- **Gated:** L10-L12.

```
L0   done (c8274db)
L3a  (any gap) ─────────┬──── L3b    (Q2; the machine free)
L2a ────────────────────┤
L2a ── L2 ──────────────┴──── L4a    (clang-cl leg: after L2a and L3a)
       L2 ── L4b ─┬─ L8              (straight after L4b: the ARM proof)
                  ├─ L6              (before any replay off Windows)
                  └─ L7 ── L9        (L9 after the comfort pack and the disc layer)
L1   when the machine is free (Q1)        L5   with the next retranslation
L10 (Q6) ── L11 (hardware, Q4) ── L12 (GPU decision, distribution, Q7)
```

### L0. Acquire loads in the render queue — **done, c8274db** (`docs/specs/now.md` N4)

**What landed.**
- `LOAD_ACQUIRE64/32` (`gxr.c:1584-1589`; comment :1572-1583): `ReadAcquire64` / `ReadAcquire` under
  `_MSC_VER`, and `__atomic_load_n(ACQUIRE)` elsewhere.
- Used at `ran_min` :1633, `wait_ran` :1656, `fence_wait`'s loop :1729, the worker's spin :1764, `drain` :2081
  and `gxr_presented` :2780.
- The producer's own reads of `g_published` stay plain. The three compiler barriers were kept, and the
  comments at :1744 and :1786-1794 rewritten.

**How it was checked, per its commit message:**
- the x64 code compared in the `/FA` listing: the worker loop, `wait_ran`, `ran_min` and `drain` identical,
  and `fence_wait` with the same plain `mov`s and different register allocation;
- replay 23/23 at 1, 2, 3 and 8 threads;
- the self test;
- `test_gxr_overlap`, and 878 tests.

**What it left, now L2's first step:**
- the four Dekker re-checks (:1621, :1731/:1733, :1781, :1812);
- the move into `plat.h`;
- enforcement (§3.4 rule 4);
- a portable spelling of the compiler barriers.

The old B2 (where the helpers go) is answered: at the top of `gxr.c`, for L2 to move.

### L1. Wine smoke test, and optionally Proton on a Deck

*Hours, plus the owner's go-ahead to use Docker Desktop or to install a WSL distro. Rebuild: none.
Prerequisites: none; run it when no other `soa.exe` is running. Files: `tools/scenario.py` (`--wrap` on
`run` and `replay`), `tools/tests/test_scenario.py`, `docs/TESTING.md` (a Wine section, with the container's
mount rules from §3.13), FINDINGS entry "Wine".* **Owner:** the go-ahead; the Proton session only if a Deck or
Linux PC exists.

*Done:*
- `python -m pytest tools/tests/test_scenario.py`: `--wrap "wine"` puts `wine` first in the command for
  both subcommands. A mutation that drops the prefix fails the new cases.
- `python tools/scenario.py run title --check`, natively, because `scenario.py` changed.
- **In the container,** with the checkout and `extracted/` mounted read-only and a scratch volume over
  `build/` (§3.13):
  - `SOA_SELFTEST=1 wine gen/soa.exe extracted` exits 0 with every case passing.
  - `python3 tools/scenario.py replay --wrap wine --fifo build/fifo-copy --threads 1,2,3,8` is 23/23, where
    `build/fifo-copy` is a copy on the scratch volume. It runs against the same manifest, and nothing is
    blessed (`--bless` already refuses a non-corpus `--fifo`).
  - `python3 tools/scenario.py run title --check --wrap wine --env SOA_CARD=build/card-copy.raw` passes, on
    a copied card.
- The FINDINGS entry records the Wine version, all three results, the
  `[gxr] rasterizing on N worker threads` line, and the mount commands used.
- **Owner, optional, and not a gate:**
  - Add `soa.exe` to Steam as a non-Steam game with Proton, with `soa.ini` beside it.
  - Play 10 minutes windowed.
  - Read back the `[window]` refresh and interval line, and confirm the pad and the sound.

### L2a. The SIMD blend behind an x86-64 guard

*Hours. `--link`. Prerequisites: none, but it edits `gxr_tev.c`, so it waits until the session holding the
renderer files says they are free (§6 order). Files:*
- *`runtime/plat.h` (new: the platform tests and the SIMD section only);*
- *`runtime/gxr_tev.c`: the guard, `bilinear_sse41`, and `simd_decide` through `plat_cpu_has_sse41`;*
- *`tools/perfbench.py` (`--exe`, with a case in `tools/tests/test_perfbench.py`), for this slice's fallback
  and later ones;*
- *`docs/ARCHITECTURE.md` (`plat.h`), and a FINDINGS entry.*

*Done:*
- `python tools/citest/compile_runtime.py` compiles every file, and `python tools/recompile.py --link`
  succeeds.
- **MSVC's code is unchanged.** Compile the base and the new `gxr_tev.c` into a scratch directory with
  `toolchain.CFLAGS` plus `/FA`, as c8274db compared `gxr.c`. `sample_level`, `sample` and their inlined
  callers must be identical but for labels.
  - **Only if they are not:**
    1. before relinking, save the base exe as `build\soa-L2abase.exe`;
    2. run `python tools/perfbench.py run --threads 1 --exe build\soa-L2abase.exe`, then the same with
       `--exe gen\soa.exe`, interleaved A B B A;
    3. the slice stops if the new build is more than 3% slower pooled.
- **clang-cl compiles it.** Run `<SOA_CLANG_CL or the NDK's clang-cl.exe> /nologo /c /std:c17 /O2 /fp:precise
  /clang:-ffp-contract=off /W3 /Iruntime runtime\gxr_tev.c /Fo<scratch>\` in the MSVC environment. It must
  report no error. At b071949 it reports three [V]. It must be `/c`: `/Zs` passes today.
- **A non-MSVC x86-64 build keeps the SIMD path.** Compile with
  `"$env:SOA_NDK\toolchains\llvm\prebuilt\windows-x86_64\bin\clang.exe" --target=x86_64-linux-android29
  --sysroot=<same>\sysroot -std=c17 -O2 -c -Iruntime runtime\gxr_tev.c -o <scratch>\t.o`. Then
  `llvm-objdump -d <scratch>\t.o` must show a `bilinear_sse41` containing `pmulld`. With today's guard the
  function does not exist.
- `python -m pytest tools/tests/test_gxr_fastpath.py` passes: 600,000 samples, 0 mismatches. The weight-pair
  swap mutation (b377b1f's, by hand) is re-run once on `bilinear_sse41` and turns it red, recorded in
  FINDINGS.
- **`SOA_GXR_NOSIMD` still reaches the scalar path.** `scenario.py replay` strips every `SOA_` variable
  (`scenario.py:962-966`), so this is a direct run, from the repository root:
  1. Copy one capture's `.fifo`, `.regs` and `.ram` to a scratch folder, because `--replay` overwrites
     `<base>.png` beside its input.
  2. Run `$env:SOA_HASH='1'; $env:SOA_SETTINGS='0'; $env:SOA_THREADS='1'; $env:SOA_GXR_NOSIMD='1';
     gen\soa.exe --replay <scratch base>`.
  3. The log must say "the pixel path ran without SIMD", and the printed hash must equal that capture's
     row in `config/fifo_manifest.tsv`.
  4. Then remove the four variables (`Remove-Item Env:SOA_HASH, Env:SOA_SETTINGS, Env:SOA_THREADS,
     Env:SOA_GXR_NOSIMD`).
- `python tools/scenario.py replay --threads 1,2,3,8` is 23/23; the self test passes.

### L2. `plat.h`: the queue's ordering completed, and the renderer builds and runs anywhere

*A day to several days, in two commits, each checked by the Done lines marked for it. `--link`.
Prerequisites: L2a. Files:*
- *`runtime/plat.h`, `gxr.c` and `gxr.h`;*
- *`gx.c` (`_exit` becomes `_Exit`);*
- *`selftest.c`: its four `_putenv` calls (:122-124, :344) become `plat_setenv`. The render checks' three
  settings move into a `render_env()` defined outside the copied block;*
- *`tools/citest/render_driver.c`, in the same commit: the copied block, and its own `render_env()`;*
- *`dvd.c:103` (`plat_fseek64`, or the disc layer's wrapper moved into `plat.h`);*
- *`tools/tests/test_gxr_atomics.py` (new);*
- *`docs/ARCHITECTURE.md`, a FINDINGS entry, and every copy of the test count.*

**Step 1, the first commit: what c8274db left.**
- `LOAD_ACQUIRE64/32` become `plat_load64/32` (§3.2). The MSVC x64 instruction is the same `ReadAcquire64`.
- The Dekker re-checks at :1621, :1731, :1733, :1781 and :1812 become `plat_load*`.
- The RMWs become `plat_inc*`, `plat_dec32` or `plat_xchg64`: :1619, :1732, :1734, :1780, :1782, :1811,
  :2437, :2664, :2916 and :3032. They stay Interlocked under MSVC, and become `__atomic` seq_cst under
  PLAT_GNU, clang-cl included.
- `WaitOnAddress` and `WakeByAddressAll` (:1621, :1733, :1781, :1812) become `plat_wait64` and
  `plat_wake_all64`, which take the counter itself. The pragma moves from `gxr.c:20` to `plat.h`.
- `_ReadWriteBarrier()` at :1661, :1744 and :1795 becomes `plat_compiler_barrier()`, kept.
- The producer's own-count reads (:1630, :1648, :1649, :1672, :1682, :2065, :2996, :3000) stay plain and get
  the `/* own count */` marker.
- The comments at :1572-1583 and :1786-1794 state §3.4's four rules.

**Step 2, the second commit: the renderer builds off Windows.**
- Spins and sleeps go through `plat_relax` and `plat_yield`: :199, :1656, :1737, :1785 and :2081.
- TLS and alignment: :123 and :143.
- Clocks: `gxr.c:30-55` and :63-95, and `gxr.h:202-222`, sit on `plat_mono_raw` and `plat_cycles`. The names
  `gxr_qpc` and `gxr_clock` are kept, so `test_memguard.py:57`'s and `test_profiler.py:58`'s stubs stay valid.
- **The worker pool gets a POSIX path.**
  - `fence_wait` (:1697-1746), `worker` (:1748-1815) and publish's wake (:1620-1622) leave `#ifdef _WIN32`.
  - `workers_start` (:2005-2039) uses `plat_thread_start` and `plat_cpu_count`, and keeps HANDLEs for
    `SOA_HOSTPROF`.
  - `SOA_HOSTPROF` (:1832-2003) stays Windows-only, and prints its "Windows-only here" line when set
    elsewhere.
- `gx.c:188`, `dvd.c:103`, and the `selftest.c` / `render_driver.c` pair as listed above.
  - `selftest.c`'s `render_env()` still forces `SOA_THREADS=1`, so **the port's self test is unchanged**.
  - `render_driver.c`'s own `render_env()` sets it from its argument (L4b's `--threads`).

*Done:*
- (1)(2) `python tools/citest/compile_runtime.py` compiles every file, and `python tools/recompile.py --link`
  succeeds.
- **(1) The x64 code is compared, as c8274db did.** The base and the new `gxr.c` are compiled into a scratch
  directory with `toolchain.CFLAGS` plus `/FA`. For `worker`, `wait_ran`, `fence_wait`, `drain`, `publish`,
  `ran_min` and `gxr_presented`:
  - no `lock`-prefixed instruction, `xchg`, `mfence` or `sfence` that was not there before;
  - the loads stay plain `mov`s.

  **(2)** The same for `worker` and the inlined `gxr_ticks` sites: `rdtsc` stays inline.
  - **Only if anything moved:** save the base as `build\soa-L2base.exe` before relinking, and time
    `python tools/scenario.py replay --threads 8 --passes 1` for each exe (`--exe`), interleaved A B B A. That
    is wall time, not ns per fragment, which leaves out spin and idle. The slice stops if the new build is
    more than 3% slower pooled.
- (1) `python -m pytest tools/tests/test_gxr_atomics.py` passes (§3.4 rule 4). The mutation, a bare
  `g_ran[1]` read added to `worker()`, turns it red.
- (1)(2) `python -m pytest tools/tests/test_gxr_overlap.py tools/tests/test_gxr_queue.py
  tools/tests/test_gxr_fastpath.py tools/tests/test_citest.py` passes. These are the stall sweeps against the
  one-worker oracle, and the copy rule.
- **(2) The NDK check reports 0 errors.** At b071949 it reports 21 [V]. The command:
  `& "$env:SOA_NDK\toolchains\llvm\prebuilt\windows-x86_64\bin\clang.exe" --target=aarch64-linux-android29
  --sysroot="$env:SOA_NDK\toolchains\llvm\prebuilt\windows-x86_64\sysroot" -std=c17 -fsyntax-only
  -Iruntime runtime\*.c`. The same holds with `--target=x86_64-linux-android29`.
  - It is a local check until L4b's Linux leg replaces it.
- **(2) The generated code, all of it.** The same compiler with `-fsyntax-only -Iruntime -Igen gen\*.c` over
  all 19 files reports 0 errors. It runs at idle priority, and only when no `soa.exe` is being timed.
- (1)(2) `python tools/scenario.py replay --threads 1,2,3,8` is 23/23. The self test and
  `python tools/scenario.py run title --check` pass.

### L3a. Toolchain profiles and `--cc`

*Hours. Rebuild: none. Prerequisites: none. It edits `tools/` only, so it can land in any gap. Files:*
- *`tools/soa/toolchain.py`: `Profile`, `cc()`, clang-cl discovery, and `runtime_support_sources()`
  returning `[]`;*
- *`tools/recompile.py` (`--cc`; `--cc clang-cl` defaults `--out gen/clang`);*
- *`tools/citest/compile_runtime.py`, `dc_check.py` and `render_check.py` (`--cc`);*
- *`tools/scenario.py` (the bless guard);*
- *`tools/tests/test_toolchain_profiles.py` and `test_toolchain_fp.py` (new); the mod build in `recompile.py`
  kept to the msvc profile (§3.9; comfort-pack.md P1a adds the build, and whichever of the two lands
  second keeps the rule);*
- *`tools/tests/test_scenario.py`, and `test_gxr_fastpath.py` (reads `SOA_CC`);*
- *`docs/TESTING.md`.*

*Done:*
- `python -m pytest tools/tests/test_toolchain_profiles.py`:
  - the msvc profile's command lines for `recompile.py --compile/--link` equal a golden copy of today's, and
    a changed flag fails the test;
  - the planned command lines for `--cc clang-cl` name only paths under `gen/clang`, and no `mods/` path:
    a non-msvc profile does not build the mods (§3.9). A mutation that points it at `gen`, or one that
    lets it build `mods/*/mod.c`, fails.
- `python -m pytest tools/tests/test_toolchain_fp.py`: for each clang profile, `a*b+c` built with `-mfma` has no
  `vfmadd` in `llvm-objdump -d`. The mutation, the profile without `-ffp-contract=off`, fails; the probe shows
  `vfmadd213ss` then [V]. The module skips, saying so, where no clang is found. CI's clang-cl leg (L4a) always
  has one.
- `python tools/citest/compile_runtime.py --cc clang-cl`, with `SOA_CLANG_CL` pointing at the NDK's
  clang-cl 19.0.1:
  - **until L2a has landed:** every file compiles but `gxr_tev.c`, which fails with exactly the SSE4.1 inline
    error of §2.2;
  - **after L2a:** every file compiles.
- `python tools/scenario.py replay --bless --exe gen/clang/soa.exe` is refused. A test case covers it, and
  allowing it turns that case red.
- `python tools/scenario.py run title --check` passes, because `scenario.py` changed. Run it when the machine
  is free.
- `python -m pytest`, `ruff check` and `ruff format --check` pass.

### L3b. The clang-cl game build, and the replay under both compilers

*A day to several days; days only if a difference appears. Rebuild: one retranslation into `gen/clang/`; the
MSVC build is untouched. Prerequisites: L2a and L3a; a clang-cl (Q2); the machine free, with the implementation
session not timing. Files: `runtime/main.c` (the `[boot]` compiler line, after P1a lands); README/CONTRIBUTING
(building with clang-cl); `docs/TESTING.md`; FINDINGS entry "clang-cl".*

*Done:*
- `python tools/recompile.py --cc clang-cl --compile --optimize --link` builds `gen\clang\soa.exe`.
  - The SHA-256 of `gen\soa.exe` and of every `gen\*.obj` is the same before and after, listed in FINDINGS.
  - `dumpbin /dependents gen\clang\soa.exe` shows no ucrtbase, api-ms-win-crt or VCRUNTIME: the same
    static CRT.
- `$env:SOA_SELFTEST='1'; gen\clang\soa.exe extracted` passes, and its `[boot]` line names clang.
- `python tools/scenario.py replay --exe gen/clang/soa.exe --threads 1,2,3,8` is 23/23 against the MSVC
  manifest. If it is not, §3.11 runs. The slice closes only at 23/23, with each difference fixed in the
  source so MSVC stays 23/23 too.
- `python tools/scenario.py run title --check --exe gen/clang/soa.exe` passes.
- The contract holds on `gen\soa.exe`, plus `python tools/decomp.py`.
- **Measured, not a gate:**
  - `python tools/perfbench.py run --exe <each>`, all captures, at 1 and 8 threads;
  - the guest ceiling (H3's uncapped `[frametime]` on the Dangral save);
  - MSVC against clang-cl, interleaved A B B A, with the machine's state noted.

  The owner then answers Q3 (§7).

### L4a. CI: the clang-cl leg

*Hours. Rebuild: none. Prerequisites: L2a and L3a. Files: `.github/workflows/ci.yml` (a `clang-cl` job,
§3.12); `docs/TESTING.md`; FINDINGS entry.*

*Done:*
- CI is green on the new leg: `compile_runtime`, `dc_check` and `render_check` with `--cc clang-cl`, and
  `pytest tools/tests/test_toolchain_fp.py tools/tests/test_gxr_fastpath.py` with `SOA_CC=clang-cl`.
- **The mutation is shown red on a branch before the merge,** linked in FINDINGS: with L2a's guard reverted,
  the leg fails on `gxr_tev.c`.
- `python tools/guard.py`, `--history`, ruff check, ruff format --check and pytest pass, as always.

### L4b. CI: the Linux leg, and the 32-bit words it finds

*Several days. `--link` (`src/`, `include/`) and `decomp.py`. Prerequisites: L2 and L3a. Files:*
- *`.github/workflows/ci.yml`: the `linux` job, and the whole COVERED comment at :92-125 rewritten (the file
  count, six native units, `fillmem.c` decompiled, twelve routines);*
- *`include/types.h`; `src/sdk/msl/fillmem.c`, `strcpy.c`, `strcmp.c`, `strstr.c` and `string.c`;*
- *`tools/soa/toolchain.py` (the gnu profiles: `/D`, `/I`, `/Fo`, `/Fe` translated);*
- *`tools/citest/*.py` (`--cc gcc|clang`);*
- *`tools/citest/dc_driver.c`: `test_strcpy`, `test_strcmp` and `test_strstr` added, and the stale `memset`
  note at :304-311 rewritten;*
- *`tools/citest/render_check.py` (`--threads N`, and the assertion below);*
- *the count copies: `ci.yml:97`, `docs/PLAN.md:17` and :81, `docs/TESTING.md:183`,
  `.claude/skills/check/SKILL.md:164`, `docs/ARCHITECTURE.md:25`, `HANDOFF.md:503` ("four" becomes nine), and
  PLAN.md's "nine" routines (:17, :87), which become twelve;*
- *a FINDINGS entry.*

*Done:*
- `python tools/decomp.py`: 83 functions across 21 units still match, because the mwcc branch of
  `types.h` is unchanged.
- `python tools/citest/dc_check.py` (MSVC) reports all twelve routines agreeing, and
  `python tools/recompile.py --link` succeeds.
- The self test passes, including the twin cases.
- `python tools/scenario.py replay --threads 1,2,3,8` is 23/23, and
  `python tools/scenario.py run title --check` passes. `memset`, `strcpy` and `strcmp` are swapped in
  through `hle.txt`, so a run exercises them.
- **CI is green on the `linux` leg** with gcc and clang on ubuntu-latest: `compile_runtime` compiles every file,
  `dc_check` passes 12/12, and `render_check --threads 1` and `--threads 4` pass.
  - `render_check.py --threads N` asserts that the driver printed `[gxr] rasterizing on N worker thread`,
    and fails otherwise. The 4-thread run is the POSIX pool's first run.
  - The mutation for that assertion: `render_driver.c`'s `render_env()` forcing one thread turns the 4-thread
    run red.
- **Mutations shown red on a branch before the merge,** linked in FINDINGS: with `types.h`'s host branch
  reverted, the Linux `dc_check` fails, on `memset` (through `fillmem.c`) and on `strcpy`.
- `python tools/guard.py`, `--history`, ruff check, ruff format --check and pytest pass, as always.

### L5. One fma macro

*Hours. One retranslation; bundle it with the next one already planned (an H13 reopen, or gameplay
milestone 2's retranslation batch A; the comfort pack has none). Prerequisites: none. Files:
`tools/soa/recomp/emit.py`, `runtime/cpu.h`, `runtime/selftest.c`, `tools/tests/test_emit.py`, and the
self-test and test counts in every copy.*

*Done:*
- `python -m pytest tools/tests/test_emit.py`: every fused form emits `SOA_FMA(`, and none emits a bare
  `fma(`.
- `python tools/recompile.py --compile --optimize --link` succeeds.
  - Bare `fma(` occurs 0 times across `gen\chunk_*.c` and `gen\dispatch.c`.
  - `SOA_FMA(` occurs a nonzero number of times, **equal to** the `fma(` count of the same emission with
    `emit.py`'s change stashed. That reference is an emission only (no `--compile`) into a scratch `--out`, so
    `gen/` is not touched. So no fused op was lost. (At b071949's `gen/` the count is 2,457; the next hook
    batch may change it, which is why the reference is re-emitted, not quoted.)
- The self test passes with the new case (§3.6), whose operands are read through `volatile` locals.
- **The mutation:**
  1. `$env:CL='/DSOA_FMA_UNFUSED'; python tools/recompile.py --link`. Only `runtime/` and `src/` recompile, so
     the chunks keep their fused calls, which is fine for this check. The new self-test case must fail.
  2. `Remove-Item Env:CL; python tools/recompile.py --link`, and the self test passes again.

  `toolchain.msvc_env()` passes the parent's `CL` through (`toolchain.py:44-66`). It is run once and recorded
  in FINDINGS.
- `python tools/scenario.py replay --threads 1,2,3,8` is 23/23, and
  `python tools/scenario.py run title --check` passes.

### L6. Renderer determinism: float-to-int and `exp2f`/`log2f`

*A day to several days. `--link`. Prerequisites: L2 and L4b. Needed before the first replay off Windows
(L10, L11), not before. Files:*
- *`runtime/plat.h` (`plat_f2i`, `PLAT_F2I_GENERIC`, `PLAT_F2I_SATURATE`);*
- *`gxr.c` and `gxr_tev.c` (§2.6's sites);*
- *`runtime/crmath.c` (new; CORE-MATH, MIT);*
- *`tools/citest/libm_check.py` and `libm_driver.c`;*
- *`tools/citest/render_check.py` and `render_driver.c`: the `plat_f2i` table, and the synthetic frame with
  its pinned hash;*
- *`config/libm.tsv` (new baseline); NOTICE; the CI legs run `libm_check`; a FINDINGS entry.*

*Done:*
- `python tools/citest/libm_check.py` checks every input (§3.8).
  - The arbitrated inputs all agree with `decimal`, and their count is quoted.
  - The hash matches `config/libm.tsv`, a new baseline whose commit says how it was inspected.
  - The `native`, `clang-cl`, `linux` and (after L8) arm64 legs print the same hash.
  - **Mutation:** UCRT's `exp2f` linked in place of `soa_exp2f` makes the check report exactly the 74,154
    known differences. The fallback is a coefficient bit of weight 2^-20 or larger, flipped (§3.8).
- **`plat_f2i` holds its contract.** `render_check`'s driver, built with `PLAT_F2I_GENERIC`:
  - checks a hard-coded table on every leg: NaN, ±inf, ±2^31, 2^31−128 and −2^31 give INT32_MIN or the exact
    value;
  - on x86 legs, also compares the generic branch with `_mm_cvtt_ss2si` over all 2^32 float bit patterns,
    which takes seconds;
  - covers the unsigned casts at `gxr.c:926` and :1011;
  - goes red with `-DPLAT_F2I_SATURATE`.
- **A synthetic frame with a pinned hash.** It has texture coordinate 1e10 and vertex colour 1e10.
  - Its hash is pinned in `render_driver.c`.
  - The commit says how it was inspected. The pixel values were read back and each was checked by hand
    against x86's arithmetic: the vertex-colour channel is 0, because `cvttss2si` gives INT32_MIN and the
    clamp makes that 0.
  - Every leg prints the same hash, and `-DPLAT_F2I_SATURATE`, the x86 stand-in for ARM's behaviour, turns it
    red.
- **Codegen on x86.** Compile the base and the new `gxr.c` and `gxr_tev.c` with `/FA`, and compare
  `raster_triangle`, `raster_line`, `raster_point`, `fog_apply`, `depth_test`, `sample_level` and `sample`.
  - **Only if the code moved:** run `perfbench run --threads 1`, interleaved A B B A against a saved
    `build\soa-L6base.exe`. The slice stops if the new build is more than 3% slower pooled.
- `python tools/scenario.py replay --threads 1,2,3,8` is 23/23 on `gen\soa.exe`. The probe predicts no
  change (§2.5). If a hash moves, the frame is opened and the difference explained in FINDINGS before
  anything is re-blessed.
- Every `(int)` over a float in `runtime/gxr*.c` is `plat_f2i`, or carries a comment saying why its
  range is bounded. The review list is in FINDINGS.
- The self test passes, and so does `python tools/scenario.py run title --check`.

### L7. POSIX layer, part 1: threads, the guarded tail, the guest stack

*Several days. `--link`. Prerequisites: L2 and L4b. `main.c` is coordinated with P1a, I1 and M5b: L7
edits only the memory guard (:541-651), the watchdog (:465-536) and the start of the guest. Files:*
- *`runtime/plat.c` (new, with the L7 functions of §3.3) and `plat.h`;*
- *`runtime/main.c`: `mem_alloc` and `mem_guard` through `plat_reserve`, `plat_commit` and
  `plat_guard_install`; the watchdog through `plat_thread_start` and `plat_mono_ns`; off Windows the
  guest runs through `plat_run_on_big_stack(32 MB)`; the sampler stays Windows-only;*
- *`runtime/threads.c`: the same-fiber resume at :283-287 moves above the `#ifdef`, and :308-311's message
  says "a second guest thread is Windows-only";*
- *`runtime/irq.c:430-432` (`plat_yield`);*
- *`tools/soa/toolchain.py` (`runtime_support_sources()` returns `[runtime/plat.c]`);*
- *`tools/tests/test_memguard.py` (profile-aware) and `test_profiler.py`, both linking
  `runtime_support_sources()`;*
- *`tools/citest/threads_check.py` with its driver, and `ci.yml` (the Linux leg runs both).*

*Done:*
- **The Windows contract:**
  - `python tools/citest/compile_runtime.py` passes at one more file than before;
  - `python tools/recompile.py --link`;
  - the self test;
  - `python tools/scenario.py replay --threads 1,2,3,8` is 23/23;
  - `python tools/scenario.py run title --check`;
  - `python -m pytest tools/tests/test_memguard.py tools/tests/test_mods.py tools/tests/test_profiler.py`.
- **The guard on Linux:** the leg runs `test_memguard.py` under gcc. `SOA_MEMPOKE=0x81800000` reports
  "[mem] a store … reached 81800000" once and the run carries on. An in-RAM poke says nothing; that is
  the existing mutation.
- **Threads on Linux:** the leg's `threads_check` round-trips a same-stack `OSSaveContext` and
  `OSLoadContext` and exits 0. With `threads.c`'s move reverted on a branch it exits 6: the mutation,
  seen red.
- **The stack on Linux:** the leg's `threads_check` reads the guest thread's stack size back with
  `pthread_attr_getstacksize` and finds at least 32 MB.
- Every copy of the file and test counts is updated.

### L8. CI on ARM64, and ThreadSanitizer

*Several days. `--link` (two small renderer fixes). Prerequisites: L2 and L4b; it does not need L7, because
`queue_check` drives only the renderer. Files:*
- *`ci.yml` (`arm64-windows`, `arm64-linux`, `tsan`);*
- *`tools/soa/toolchain.py` (`msvc-arm64` and `vcvarsarm64`; today it hard-codes `vcvars64.bat`);*
- *`tools/citest/queue_check.py` (new): a standalone, profile-aware runner. It holds the `DRIVER` and `RUNS`
  constants that move out of `test_gxr_overlap.py` (:44-388) and `test_gxr_queue.py`;*
- *`tools/tests/test_gxr_overlap.py` and `test_gxr_queue.py`, which import those constants (one source). Their
  drivers' `_putenv` (`test_gxr_overlap.py:326-327`, `test_gxr_queue.py:153-155`) becomes `plat_setenv`;*
- *`plat.h` (`PLAT_TEST_RELAXED_LOADS`);*
- *`gxr_tev.c`: `g_notex` decided on the producer in `tev_prepare`, beside `simd_decide` (:1086);*
- *`gxr.c`: `WARN_ONCE`'s flag (:273-280) set with `plat_cas32`;*
- *`tools/citest/tsan.supp`, only if needed, one line per entry, each naming a FINDINGS reason;*
- *a FINDINGS entry.*

*Done:*
- **The existing races are fixed first.** `g_notex` and `WARN_ONCE` as above.
  - `python tools/scenario.py replay --threads 1,2,3,8` is 23/23, and
    `python -m pytest tools/tests/test_gxr_overlap.py tools/tests/test_gxr_queue.py` passes with the drivers
    now imported from `queue_check.py`.
  - `g_lines` and `g_points` (`gxr.c:1267`, :1296) need nothing: lines and points are drawn by one thread only
    (`gxr.c:1462`, :1471 and :1480).
- **TSAN:** the leg (clang `-fsanitize=thread`, `render_check` and `queue_check`) reports no race, with at
  most **2** suppressions, each named in FINDINGS. The target is 0.
  - **The mutation:** `-DPLAT_TEST_RELAXED_LOADS=1` makes TSAN report a race on a `DrawCmd` field or a
    neighbour's row. It is seen red on a branch and linked in FINDINGS.
  - Running the same switch on an ARM leg is corroboration only. One run on 4 cores may not show a race;
    TSAN is the oracle that decides.
- **Both ARM64 legs pass:** ubuntu-24.04-arm with gcc, and windows-11-arm with MSVC ARM64 (once B4 is
  answered). Each runs `compile_runtime`, `dc_check`, `render_check` and `queue_check`. `queue_check` covers
  `SOA_THREADS` 1, 2, 3 and 4 with each stall kind, every result matching the one-worker oracle.
- A `libm_check` hash on each ARM leg matches `config/libm.tsv`, once L6 has landed.

### L9. POSIX layer, part 2: the comfort pack's and disc layer's files

*A day to several days. `--link`. Prerequisites: L7; and after M19, M5b and the disc layer's M3 slices (I1,
I3, and I5a if it is agreed) have landed in these files. Files:*
- *`runtime/plat.c`: the L9 functions of §3.3;*
- *`runtime/settings.c`: `settings_path` through `plat_exe_dir`; `set_env` becomes `plat_setenv`;*
- *`runtime/mod.c`: `load_dll` (:725-780) through `plat_dl_*` and `plat_realpath`; the folder listing
  (:975-1000) through `plat_list_dirs`; `mod.so` off Windows;*
- *`runtime/soa_mod.h`: `SOA_MOD_EXPORT`, additive, with no API version bump;*
- *`examples/mods/map-log/mod.c`;*
- *`runtime/hle.c`: the CAS at :189, the lock at :375, `process_cpu_seconds` at :422, and the wall clock
  at :317-351 through `plat_mono_*`. The timebase at :290 is M19's; one line if M19 used QPC;*
- *`runtime/audio_out.c`: the WAV writer, the meter and the report leave `#ifdef _WIN32`, so `SOA_WAV`
  works everywhere; waveOut stays the Windows backend;*
- *tests linking `runtime_support_sources()`: `tools/tests/test_mods.py` and `test_settings.py`
  (profile-aware), `test_uncap.py` and `test_profiler.py`;*
- *`tools/tests/test_portability.py` (new).*

*Done:*
- **The Windows contract,** plus `python -m pytest tools/tests/test_mods.py tools/tests/test_settings.py
  tools/tests/test_memguard.py tools/tests/test_uncap.py tools/tests/test_profiler.py`.
- **Mods on Linux:**
  - The leg builds `examples/mods/map-log` as `mod.so` with gcc and loads it through the real loader.
  - The recording's config line names it `map-log@<version>`.
  - A `mod.so` that exports no `soa_mod_init` is refused, naming `dlerror()`: the mutation.
- **`SOA_WAV` on Linux:** a driver pushes N blocks, and the header's data size equals N × block bytes.
  With the writer back inside `#ifdef _WIN32` on a branch, it fails.
- **Settings on Linux:** `test_settings` shows `soa.ini` is looked for at M5b's root first, then beside the
  executable, never in the working directory.
- **`python -m pytest tools/tests/test_portability.py`.** An `#ifdef _WIN32` or `#if defined(_WIN32)` in
  `runtime/` is allowed only at these sites, listed by file and function:
  - `window.c`;
  - `audio_out.c`'s waveOut backend;
  - `plat.h` and `plat.c`;
  - `threads.c`'s fiber path for a second guest thread;
  - `main.c`'s sampler, with its `profile_start`/`profile_report` stubs;
  - `gxr.c`'s `SOA_HOSTPROF`;
  - the portable `mkdir` pairs in `gxr.c`'s `ensure_frames_dir` and `exi.c`'s `make_parents`.

  The mutation: an `#ifdef _WIN32` added to another function in `exi.c` turns it red.

### L10. Native Linux x86-64 with SDL3 — gated on Q6

*Week-plus. Rebuild: one Linux build; Windows none, unless Q6 also moves Windows to SDL3. Prerequisites:
Q6 answered "SDL3"; L6, L7 and L9. Files: `runtime/window_sdl.c` and `audio_sdl.c` (behind the existing
seams), `tools/fetch_sdl.py` (SDL3 3.4.x, hash-pinned, never in `vendor/`), `tools/recompile.py` (gnu
full build), README/CONTRIBUTING.* **Owner.**

*Done:*
- **Headless, in WSL2 on this PC:**
  - `python3 tools/recompile.py --cc gcc --compile --optimize --link` builds;
  - `SOA_SELFTEST=1 gen/linux/soa extracted` passes;
  - `python3 tools/scenario.py replay --exe gen/linux/soa --threads 1,2,3,8` is 23/23 against the same
    manifest;
  - `python3 tools/scenario.py run title --check --exe gen/linux/soa` passes.
- **Audio rate, in one windowed run:** about 32,000 samples a wall second, taken from `SOA_WAV`'s byte
  count over the run's wall seconds, within a tolerance fixed before the run. A `SOA_SPEED=2` run falls
  outside it (section F's M11 entry of the gameplay plan).
- **Owner:** 15 minutes windowed, under WSLg or on a Linux PC or Deck, covering the pad, sound and the
  present line. The owner's list is filed.
- The Windows contract is unchanged.

### L11. ARM64 on a device — gated on hardware

*Week-plus. Rebuild: one ARM64 build per target. Prerequisites: L6 and L8, plus L10 for Linux ARM64;
Q4's hardware.* **Owner.**
- **Windows on ARM:** `--cc msvc-arm64` cross-build on this PC; run on the device.
- **Linux ARM64:** gnu cross-build.
  - `docker run --platform linux/arm64` (QEMU) replays on this PC at `SOA_THREADS=1`. That covers the
    float, cast and libm semantics, not memory ordering.
  - Then the device.

*Done:*
- On the device: the self test; `replay --threads 1,2,3,8` 23/23 against the same manifest;
  `title --check`.
- Under QEMU: replay 23/23 at 1 thread.
- A FINDINGS entry with fps at the Dangral base, drawn every frame, for the GPU decision.

### L12. Android shell — gated on the GPU decision, distribution (Q3/G4) and Android as a goal

*Several weeks for the shell; the GPU backend is months and is the precondition for playable speed.*
**Owner.**

Contents, as §3.14 lists them:
- the NDK profile (`-fPIC -ffp-contract=off`, a `.so`) and a Gradle shell;
- lifecycle and surface loss, and M19's pause-aware clock;
- SAF import into the disc layer's store;
- a touch overlay into `window_pad`, and AAudio or SDL3 audio at 48 kHz;
- one app data root for every relative path;
- stderr to logcat and a file.

To be specified in full when its gates open. Its Done will be the replay 23/23 at 1-8 threads on the
phone (L6 makes that exact) and an owner session.

---

## 7. Open questions

### For the owner

- **Q1. Wine on this PC.** May the implementation session use Docker Desktop, which is already running,
  or install a WSL Ubuntu, for L1's Wine test? Do you have a Steam Deck or a Linux PC for the optional
  Proton session?
- **Q2. LLVM.** May LLVM be installed for L3b?
  - To match CI's image exactly (LLVM 20.1.8 on runner image 20260922.270.2), the command is
    `winget install LLVM.LLVM --version 20.1.8`. A plain `winget install LLVM.LLVM` takes whatever is newest.
  - A newer local LLVM is also acceptable, as long as L3b records the version, which its `[boot]` line
    prints.
  - The Android NDK's clang-cl 19.0.1 is enough for L3a.
- **Q3. The default compiler.** If clang-cl draws the 23 frames identically and is measurably faster, should
  it become the default? MSVC stays the reference for the pinned hashes until you say otherwise.
- **Q4. ARM hardware.** Which ARM hardware, if any, matters: a Windows-on-ARM laptop, a Linux ARM board, a
  phone? L11 runs only on hardware you have. CI covers the synthetic part either way.
- **Q5. The CPU floor.** Keep today's (x86-64 baseline, with SSE4.1 checked at run time), or require
  x86-64-v3 (AVX2 and FMA)? The Deck and the Z1 Extreme both have v3, and it would let H13a inline
  `fma` and use `/arch:AVX2`.
- **Q6. SDL3** (the gameplay plan's Q6). Reopen "no third-party runtime dependency" (SPEC.md:463-464) for
  SDL3 on Linux, and Android? And should Windows move to SDL3 too, or keep Win32? This gates L10.
- **Q7. Android.** Is Android a firm goal? That, with the GPU decision and distribution (Q3/G4 of the
  gameplay plan), gates L12.
- **Q8. The order.** Your pivot puts this groundwork after the comfort pack and the disc layer, and §6
  follows it. Two things could move earlier, and each would delay something else:
  - **(a) L2a** (hours; `gxr_tev.c` only), in a gap before the comfort pack's `gxr.c` slices. It makes clang
    builds work again, and delays P5b by those hours.
  - **(b) L2a and L2** (a day to several days), ahead of the disc layer. That lands them before H17a if H17a
    comes straight after the comfort pack, and delays the disc layer by that much.
  - **If you do not answer:** [../PLAN-NEXT.md](../PLAN-NEXT.md)'s defaults: L2a in M1's gap (its D-12),
    and L2 in M4a after H17a, converting what H17a added.
- **Q9. A long log.** Next time you play a long stretch on Windows, may the log be kept? Its "guest threads
  seen" count answers whether a later part of the game starts a second guest thread (§5 risk 18), at no cost.

### For the implementation session

- **B1. `g_screen`'s single buffer.** The UI thread reads it while workers may write the next copy
  (§3.4). Is that accepted tearing, or does it deserve a double buffer before TSAN runs with a window?
  H8, H17 and the GPU backend all touch it.
- **B2.** Answered by c8274db: the helpers sit at the top of `gxr.c`, and L2 moves them into `plat.h`.
- **B3. L5's retranslation.** Which retranslation does L5 ride on: an H13 reopen, or gameplay milestone 2's
  retranslation batch A? The comfort pack has none. (../PLAN-NEXT.md proposes the first planned one.)
- **B4. The windows-11-arm image.** Does the image carry Visual Studio with the ARM64-native tools and a
  `vcvarsarm64.bat` that `toolchain.py` can find? That is to be checked at L8's start [I].
- **B5. CORE-MATH or hand-written.** CORE-MATH's `exp2f`/`log2f` against a hand-written pair, once the
  MSVC compile of the former is tried (§3.8).
- **B6. `scenario.py --wrap`.** Is `--wrap` acceptable in `scenario.py`, or should Wine runs go through a
  separate `tools/citest/wine_smoke.py` that shells out to it?
- **B7. Measuring clang-cl's call cost.** In L3b's A/B, is the out-of-line SSE4.1 blend under clang worth
  a span-level target attribute? Measure it before designing it.
- **B8. One seq_cst load, or two kinds.** c8274db chose acquire for publication and completion. This spec
  moves those sites to the same seq_cst `plat_load*` as the Dekker re-checks. It is the same instruction on
  x86-64 and on default ARM64 targets, and there is one rule to follow. Agreed? Or keep an acquire variant
  for c8274db's sites and a seq_cst one for the four re-checks?
- **B9. The self test's thread count.** L2 splits the render checks' environment into a `render_env()` outside
  the copied block, so the port's self test keeps forcing one thread while `render_check` can run at N. The
  alternative is for the self test to follow the caller's `SOA_THREADS` when set. Which do you prefer?

### Cross-spec notes

- `plat_dl_open`/`plat_dl_sym` land with their first caller: L9's mod loader, or the GPU backend's Vulkan
  loader, whichever comes first (§3.3). gpu-backend.md 3.10 and V5 say so too.
- disc-layer.md §3.2 uses L2's `plat_fseek64`, or a local wrapper if I1 lands first, which it does under
  ../PLAN-NEXT.md (M3 before M4a); L2 moves that wrapper into `plat.h` (§3.10).
- `aram.c`'s `__argv` goes with comfort-pack.md M5b (`aram_set_data_dir`) and disc-layer.md I1, both
  before L9, so L9 no longer touches `aram.c`.

---

### Sources consulted (web, 2026-09-25)
- GitHub runner image readme, Windows Server 2025 (LLVM 20.1.8, VC ARM64 tools): https://github.com/actions/runner-images/blob/main/images/windows/Windows2025-Readme.md
- Arm64 hosted runners for public repositories GA (2025-08-07): https://github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available/
- CORE-MATH (MIT; binary32 `exp2f`/`log2f`): https://core-math.gitlabpages.inria.fr/
- Wine 3.19, `RtlWaitOnAddress` and kernelbase's `WaitOnAddress`: https://www.winehq.org/announce/3.19
- Wine 4.2, the futex-based `WaitOnAddress`: https://www.winehq.org/announce/4.2
- MSVC ARM64 intrinsics (`__ldar64`, `__stlr64`): https://learn.microsoft.com/en-us/cpp/intrinsics/arm64-intrinsics
- MSVC `/D` ("doesn't support function-like macro definitions"; `CL` cannot hold `=`): https://learn.microsoft.com/en-us/cpp/build/reference/d-preprocessor-definitions
- SDL 3.4.16 (2026-09-02): https://github.com/libsdl-org/SDL/releases

---

## Review log

Two reviews, 39 issues. Each was checked against the repository before acting: committed HEAD b071949
(`git show HEAD:`), a `git archive` export run through the NDK's ARM64 `-fsyntax-only` and clang-cl `/c`, and
greps.

**Applied (36):**
1. **The tree was out of date; L0 had landed as c8274db, built differently** (header, §2.3, §2.10, §3.4, §6
   L0, §7 B2) [V `git show c8274db`]. Re-baselined to b071949.
   - L0 is marked done, with what it covered and how it was checked.
   - B2 is answered.
   - §2.3's table shows which loads are acquire now.
   - The remainder moved to L2 step 1: the rename to `plat_load*`, seq_cst Dekker loads in the same change as
     the `__atomic` RMWs, enforcement, and the barriers kept as `plat_compiler_barrier()`.
2. **gxr.c line numbers above 1570 off by 20-23.** Every one was re-cited at b071949. The new NDK run gives
   exactly the reviewer's error lines [V]. `:1649` was added as an own-count read.
3. **L7's `plat_mkdir_p` would break the renderer-alone link.** `plat_mkdir_p` was dropped entirely.
   `gxr.c:2829-2847` and `exi.c:98-113` are already portable [V]. The same change removed `exi.c` from L9 and
   added an Alternatives row.
4. **`__builtin_cpu_supports` under clang-cl.** Confirmed by probe (LNK2019 `__cpu_model`). §3.2 now uses
   `__cpuid` whenever `_MSC_VER` is defined, and `<cpuid.h>` elsewhere.
5. **"All 19 gen/ files".** It was two files. Corrected, and L2's Done adds the full 19-file check.
6. **G4's compilers.** llvm-mingw and zig cc drop SIMD silently rather than failing. Reworded in §2.2 and risk 2.
7. **L8 TSAN would trip on `g_notex` and `WARN_ONCE`.** Both fixes were added to L8's files and Done [V
   `gxr_tev.c:1158`, :1215; `gxr.c:273-280`].
8. **CI description and module counts.** 19 modules, nine `test_gxr_*`, and two C-building CI jobs [V]. HANDOFF.md:503
   is fixed in L4b.
9. **The stale-22 list.** Six places, with ARCHITECTURE.md:25 added. TESTING.md's line is :183 at b071949,
   not :182. L4b now rewrites the whole COVERED comment and `dc_driver.c:304-311`. PLAN.md:17's "nine MSL
   twins" was checked and is right for `dc_check`'s nine routines. Found while checking: `dc_check` does not
   test `strcpy`, `strcmp` or `strstr`, so L4b adds them (§2.4, §3.7).
10. **The order contradicted the pivot and now.md.** §6 now follows the pivot, and Q8 asks about the deviations.
11. **The container needs `extracted/`.** Applied, with one change: the host's `build/` is not mounted at all.
    A scratch volume holds the copies, so no original can be overwritten.
12. **L2's NOSIMD line named no command, and claimed a mutation that is not in the test.** The direct command
    is given, and the one-off mutation is re-run by hand in L2a [V `scenario.py:962-966`,
    `test_gxr_fastpath.py:266-272`].
13. **ldexp and nearbyint counts.** Corrected [V grep: 0 and 0; `cpu.h:538`].
14. **§2.4's unit count and `size_t`.** "Five of the six", and `size_t` is 64-bit on LP64 too.
15. **The float-to-int list.** `gxr.c:1011` added, and `gxr_tev.c:1109` moved to range-limited. Also moved, by
    the same reasoning: `gxr.c:2551` (YUV, 16-235).
16. **`plat_setenv` with an empty value.** It now unsets, and all four `selftest.c` sites convert.
17. **Wine and `WaitOnAddress`.** 3.19, with the futex version in 4.2 [V release notes].
18. **The `winget` version.** Pinned, or a newer LLVM recorded.
19. **Minor citations.** `compile_runtime.py:76-80`, `main.c:650` (committed; N5's working tree puts it at
    :653), `gxr_tev.c:1202-1206`, `gxr.c:1494-1539`. One waiter/waker labelling is used everywhere.
20. **The AArch64 `storing` bit.** It comes from `esr_context` WnR, marked [I].
21. **The whole-spec staleness** (a duplicate of 1). For enforcement, the grep test was chosen over wrapper
    types, to match c8274db's plain own-count reads.
22. **`render_check` could not run at 4 threads, and `render_driver.c`'s copy.** Applied with a different
    mechanism: a `render_env()` outside the copied block in both files. The port's self test then keeps
    forcing one thread, instead of following the caller's `SOA_THREADS` (B9). `render_check --threads N`
    asserts the thread line, with a mutation.
23. **(TSAN, partly.)** `g_notex` and `WARN_ONCE` applied, and L8 resized to several days with K = 2. For the
    rejected part, see below.
24. **L8 no longer waits for L7.** The drivers are single-sourced in `queue_check.py`, and the two tests are
    added to its files.
25. **The L5 mutation could not be built.** It is now `SOA_FMA_UNFUSED` through `CL` [V Microsoft Learn].
    The count check re-emits into a scratch `--out`, and the self-test operands are volatile.
26. **Three L6 checks could not fail.** Now `PLAT_F2I_GENERIC` with an exhaustive comparison, a pinned and
    inspected frame hash with the `PLAT_F2I_SATURATE` mutation, and UCRT `exp2f` as the libm mutation.
27. **Speed gates below the noise.** Codegen comparisons first. A timing only if the code moved, with the base
    saved first: at 1 thread, or as wall time for queue changes. `perfbench --exe` moved to L2a.
28. **Tests linking `plat.c`.** `runtime_support_sources()` is added, and each test is listed in L7 or L9.
    For the clock stubs, the design keeps `gxr_qpc`'s and `gxr_clock`'s names, so those stubs stay valid
    rather than being edited.
29. **L3 split.** L3a (plumbing) and L3b (the game build). `--cc clang-cl` defaults `--out gen/clang`. The
    SIMD fix is its own slice, L2a. L4 depends on L3a only.
30. **The order again** (a duplicate of 10).
31. **L0's grep contradiction.** Resolved: there is no wrapper member, `plat_wait64` takes the counter, and the
    grep is over counter names.
32. **L4 undersized.** Split into L4a (the clang-cl leg, hours) and L4b (Linux and the twins, several days),
    with the whole COVERED block and correct line numbers.
33. **Owners for the profile-aware tests.** A table in §3.9, including why six stay MSVC-only. "Four" is
    corrected to nine.
34. **The libm facts** (a duplicate of 13).
35. **The second-guest-thread risk.** Added as §5 risk 18. §4's ucontext row is qualified, and Q9 added.
36. **L9's grep allow-list.** It is now `test_portability.py` by file and function, with a mutation.
37. **The `plat.c` split.** Now by first caller (§3.3), with a cross-spec note for `gpu-backend.md`'s L7
    reference to `plat_dl_*`.
38. **The L2 commands and the NDK path.** Given in full, with `SOA_NDK` defaulting to the known path.
39. **L6 codegen.** A `/FA` comparison of the listed functions, and a timing only if they moved.

**Rejected (1, part of one issue):**
- **Issue 23's `g_lines`/`g_points` claim** ("bumped by every worker … counts multiplied by the worker
  count"). Lines, line strips and points are drawn by one thread only: `if (t_tid > 1) break;` at
  `gxr.c:1462`, :1471 and :1480. So `g_lines++` (:1267) and `g_points++` (:1296) have one writer. The report
  reads them after a drain, whose acquire loads order them. There is no race and no multiplication. L8 says so
  rather than change them.

**Found while revising, not raised by either review:**
- HEAD moved from c8274db to b071949 during the review, and N5 is now in flight in the working tree, with a
  new `runtime/seed.c` that makes the runtime 26 files. §2.7, §2.10, §3.10 and risks 1 and 12 say so.
- `compile_runtime`-style checks of the clang-cl failure must use `/c`: `/Zs` passes all 25 files today [V].

**Consistency review, 2026-09-25, at 012164a.** A check across the five planning documents and against the
repository, with the implementation session's facts from after the drafts:
- **State.** P6 (24d9235), C5a (750cef0), P6b (79c9ad8), b1199b3 and T0c (012164a) have landed, and P1a
  was in the working tree at 012164a (header, §2.7, §2.10, §3.10, risk 1). The runtime count is 26 at
  012164a, the stale-22 copies are re-cited there, and risk 12 no longer forecasts later counts. C5a moved
  `gx.c`'s lines, which the header says.
- **Order.** §6 and Q8's default now defer to ../PLAN-NEXT.md: L2a and L3a in M1, M4a = L2, L4a, L4b, L8,
  L3b, L1, and M4b (L6, L7, L9) after the gate by default. L5 no longer rides "the comfort pack's first
  hook batch", which does not exist; it rides an H13 reopen or gameplay batch A (L5, B3).
- **`aram.c`.** comfort-pack.md M5b and disc-layer.md I1 remove `__argv` before L9, so L9's `aram.c` bullet
  is gone and the churn row says so. The churn row for `exi.c` and `si.c` named P3, which changes only
  tools; it is now `si.c` alone, with M5b, M18, P10a and CH1.
- **The seek wrapper.** The old citation `disc-layer.md:130` pointed at a line that moved; the churn row and
  the cross-spec note now cite disc-layer.md §3.2.
- **Mods under other profiles.** A non-msvc profile does not build `mods/*/mod.c`, and L3a's test asserts
  it (§3.9, L3a).
- **Settings on Linux.** L9's check follows M5b: `soa.ini` at the port root first, then beside the
  executable.
- **`plat_dl_*`.** gpu-backend.md now says they arrive with their first caller, as §3.3 does.
