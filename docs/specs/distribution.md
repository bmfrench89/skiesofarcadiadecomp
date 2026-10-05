<!-- Written 2026-10-04 by the implementation session at main 019e593, read-only for this file: gate G3's
route (PLAN-NEXT §0: "specified after V7 and built before L12") turned into slices. Inputs: the research
in ../research/distribution.md (2026-10-03), a read-only survey of the build at 019e593, and two outside
checks made the same day: llvm-mingw's latest release page (20260922, LLVM 23.1.2) and this machine's
CPython 3.14.0, whose `compression.zstd` is the extension module `DLLs\_zstd.pyd`. Then one review, the
same day, against the code; its thirteen findings are folded in and listed at the end. Nothing was built
or run for it. [V] = checked in code, a doc or a dated page; [I] = inference. Sizes are evenings: hours /
a day / several days / week-plus. -->

# Distribution: the game built on the player's machine

## 1. What the player gets

**The route, as decided at G3** ([PLAN-NEXT.md](../PLAN-NEXT.md) §0;
[research/distribution.md](../research/distribution.md) route B). Players download a runtime package
that holds no translated or decompiled game code (§0's words). They run it, point it at their own disc
image, wait a few minutes once, and play. SPEC §2 rule 5 says what the package may hold.

| Step | The player | What happens |
|---|---|---|
| 1 | Downloads `soa-<version>-windows-x64.zip` (about 150-250 MB [I]) and extracts it to a folder of their own | — |
| 2 | Runs `Setup.exe` | A window asks for the disc image (ISO, GCM or RVZ) |
| 3 | Picks their image | The image is checked; a disc that is not `GEAE8P` with the expected executable is refused by name |
| 4 | Waits: about 2 minutes on a 16-thread PC, 5-15 on a Steam Deck [I] | The game is translated and compiled with the bundled compiler; a progress bar counts the steps |
| 5 | Presses Play | `soa.exe` starts, from then on without `Setup.exe` |

**The Steam Deck** runs the same package under Proton, set up in Desktop Mode where the file picker
works (research §5). **Android** gets a runtime-only APK that loads a game library built by the same
package on a PC (route C2, R5), with L12.

**In scope:** a Windows build of `soa.exe` with no Microsoft compiler; the build with no decompiled code
present; the recompiler run with no installed Python; one command from disc image to install folder; the
package, the guard over it, and the workflow that makes it with no game data present; the setup window;
and what R5 asks of L12.

**Out of scope:** building on the phone (route C1); a native Linux package (after L10); an auto-updater;
signing and Android registration, which are the owner's (§6); NKit, GCZ, WIA and CISO images
(PLAN-GAMEPLAY-MODS G3; the setup window names Dolphin's converter).

---

## 2. What the build needs today (main 019e593)

- **Four steps from a checkout** (README.md:52-66) [V]: `pip install -e ".[dev]"`; `tools/extract.py
  <dump>`, which writes `extracted/disc.iso` (1.46 GB) and `extracted/sys/` (3.3 MB), refuses a game ID
  other than `GEAE8P` (extract.py:36, 132-137) and a DOL whose SHA-1 is not `config/GEAE8P/config.yml:6`'s
  (extract.py:40-62), but only warns and goes on when it cannot check (extract.py:51-56); `tools/checkdump.py`,
  which checks again on request; `tools/recompile.py --compile --link` (`--optimize` for `/O2`).
- **No later step refuses a different executable** [V]: recompile.py does not check it, and the boot reads
  `extracted/sys/main.dol` (main.c:1298-1306) and only notes its hash for mods (`mod_note_dol`,
  main.c:1337). Disc-layer I3, which builds the DOL into `soa.exe`, is specified only.
- **Decompiled code enters the build twice** [V]: `config/GEAE8P/units.txt` marks 8 units of `src/`
  `native`, compiled as twins into `soa.exe`, and `config/hle.txt` binds 12 MSL functions (strlen to
  strstr, memcpy, memset) to `src/sdk/msl/*.c`. The self test's case 73 checks that swap (CLAUDE.md).
- **The translation** [V]: 7,144 functions in 18 `chunk_*.c` files plus `dispatch.c`, about 56 MB of C
  (TESTING.md:397-413). `/O2` takes 103 s on 16 threads (TESTING.md:425-428); clang-cl compiled the 19
  units in 57.7 s and linked in 10.2 s (FINDINGS "L3b").
- **What the chunks bake in** [V]: `runtime/cpu.h`, `config/hle.txt`, `hooks.txt`, `savepoints.txt` and
  `trace.txt` are compiled into every chunk, and `--link` never retranslates (CLAUDE.md, "Relink, or
  retranslate"). G5's build-inputs guard (PLAN-GAMEPLAY-MODS) is not implemented.
- **The compilers** (tools/soa/toolchain.py) [V]: `msvc` (vswhere, then vcvars64.bat's environment
  captured, :15-68) and `clang-cl` (which still needs MSVC's headers, libraries and `link.exe`:
  `compiler_path` returns None without `msvc_env`, :229-239). `gcc` and `clang` are Linux profiles (:188-201)
  on baseline x86-64, with no FMA instruction; `--link` refuses any profile not MSVC-style
  (recompile.py:357-363). **No `x86_64-w64-mingw32` profile exists**, and only the msvc profile builds a
  mod's `mod.dll` (`cl /LD`, recompile.py:53-65, 162-167).
- **What a GNU-style Windows link must supply** [V]: the libraries, which come only from `#pragma
  comment(lib)` (window.c:34-40: user32, gdi32, xinput9_1_0, d3d11, dxgi, dxguid, dwmapi; audio_out.c:15
  winmm; gxr.c:1900 dbghelp; plat.h:94 Synchronization, behind `_MSC_VER`); and the 32 MB stack of
  `/STACK:33554432` (recompile.py:158), which guest call depth needs.
- **The CRT is static under MSVC** (FINDINGS.md:4462-4464), which is why L1 found Wine runs the same math
  code Windows does (portability.md:111-114) [V].
- **The runtime is already mostly compiler-neutral** [V]: every `_MSC_VER` branch has a GNU fallback
  (plat.h :65-71, :131-179, :299-330); there is no SEH `__try`; `_fseeki64`, `_beginthreadex`, fibers,
  the vectored handler and D3D11 through `COBJMACROS` all exist in mingw-w64.
- **Python** [V]: `requires-python >= 3.14` (pyproject.toml:4), for `compression.zstd`, which the RVZ
  reader uses (soa/rvz.py:14). `tools/tests/test_citest.py:69-85` holds `import recompile` to the
  standard library. tools/ is about 1.9 MB.
- **The GPU backend's build** [V]: `--link` compiles the shaders only when `vendor/` holds glslang and
  `fetch_gpu.verify` passes (recompile.py:383-398, shaders.py:50-52); otherwise `soa.exe` is built
  without it and says so.
- **Paths at run time** [V]: the root is `SOA_ROOT`, an ancestor named `gen` with a `runtime\` beside it,
  or the exe's folder (settings.c:160-212), found through ANSI calls (`GetModuleFileNameA`, `fopen`;
  settings.c:204, :237); `soa.ini` under it (:222-245); cards, mods and the disc under it when a
  `soa.ini` was read (:441-456; exi.c:90), logs under it (:266-284); `SOA_MODS` defaults to
  `<root>\mods` (:450-454). **Two defaults are relative to the working directory:** V7's pipeline cache
  (`build/gxv-pipelines.bin`, gxv.c:2057) and the cards when no `soa.ini` was read (exi.c:90).
- **The guard** reads only `git ls-files` (guard.py:159, :433-470), refuses a directory named `vendor`
  (:74-80) and any file over 2 MB (:141) [V].
- **CI** has no release workflow and never links `soa.exe` (ci.yml:123-131, 199-200) [V].

---

## 3. Decisions

### 3.1 No decompiled code in the package: the player's build runs the translated twins

`src/` and `include/` (the decompiled game code and its headers) stay out of the package (§0, rule 5).
The player's build therefore switches off what uses them: the 8 `native` units (their translated
functions run instead, as they did before each was decompiled) and the 12 `hle.txt` bindings to
`src/sdk/msl` (the guest's own MSL runs, translated). The self test's case 73 says it is skipped, by
name, in such a build. **The cost** (MSL's string and memory functions translated rather than native)
is R2's to measure. If it shows, the runtime gains plain-C equivalents written for it, under MIT, held
to the translated twins by the same case 73; they would be this repository's own code, which a package
may carry.

### 3.2 The compiler: llvm-mingw, fetched and pinned

| | llvm-mingw | zig cc | clang-cl + Microsoft's SDK |
|---|---|---|---|
| Download | about 190 MB [V, research §6] | about 100 MB [V, research §6] | clang, plus an SDK fetched on the player's machine |
| Licence | ISC and Apache-2.0 [V, research §6] | MIT and LLVM's [I] | Microsoft's SDK and CRT terms; not ours to ship |
| Windows headers for D3D11, DXGI, XInput | mingw-w64's | mingw-w64's | the real ones |
| Proven here | no | no | builds the whole game, with MSVC's environment (FINDINGS "L3b") |

**llvm-mingw** (`x86_64-w64-mingw32`, UCRT) at a pinned release (20260922, LLVM 23.1.2 when written),
fetched by a new `tools/fetch_mingw.py` with a SHA-256 for its archive. For developers it lands in
`vendor/llvm-mingw/`, never committed. In the package it is `toolchain/`, and the `mingw` profile's
`compiler_path` looks for `SOA_MINGW`, then `<root>\toolchain\bin`, then `vendor\llvm-mingw\bin`. zig cc is
the fallback if R1 finds llvm-mingw cannot build the game. **The owner is asked before R1 starts** (§6,
Q-D1): on 2026-10-02 they declined installing LLVM for L3b (portability Q2). This is a fetched toolchain,
not an installed one, but it is still a new third-party dependency.

### 3.3 The math stays inside the exe

mingw-w64 has no static UCRT [I]: an llvm-mingw `soa.exe` imports `ucrtbase.dll`, and under Proton that
is Wine's. The guest's 2,457 emitted `fma()` calls (portability.md:103) and the libm functions L6 pinned
(`config/libm.tsv`) must then not come from it, or the Deck runs other math than Windows does. R1
provides them inside the exe (mingw-w64's own where they are exact, otherwise a vendored exact `fma`,
as L6 vendored CORE-MATH's `exp2f` and `log2f`), and checks the import table.

### 3.4 Floating point: what can and cannot fail

- **The renderer's float math** runs in `replay`, but on baseline x86-64 clang has no FMA instruction to
  contract into, so removing `-ffp-contract=off` alone changes nothing. The mutation that can show the
  flag matters is `-mfma` without it.
- **The guest's `fma`** never runs in `replay`, which renders with no game running (scenario.py:88;
  main.c:1392-1404), and `title --check` compares no hashes. So R1 adds a self-test case: guest
  `fmadd`/`ps_madd` inputs whose double-rounded result differs from the fused one, through the emitted
  path. Its mutation links a naive `fma(a, b, c) { return a * b + c; }`, which must fail it.

### 3.5 Python: the embeddable CPython

The recompiler needs only the standard library, so the package carries CPython's Windows embeddable
distribution (`python-3.14.x-embed-amd64.zip`, about 10 MB, PSF licence) [I], pinned and hashed, and runs
`tools/` from source with it. R2 checks it carries `_zstd.pyd`; this machine's full install has it as an
extension module (`DLLs\_zstd.pyd`) [V]. `test_citest.py`'s stdlib check is extended to `player_build.py`.

### 3.6 What the package holds

| In the package | Contents | From |
|---|---|---|
| `Setup.exe` | the setup window (R4) | `tools/setup/`, built in CI by the bundled compiler |
| `python/` | the embeddable CPython | python.org, pinned and hashed |
| `toolchain/` | llvm-mingw, pruned to the x86_64 host and target | `fetch_mingw.py` |
| `source/` | `runtime/`, `config/`, the `tools/` the build runs, `README`, `LICENSE` | the tagged commit |
| `source/vendor/` | Vulkan-Headers and glslang, as `fetch_gpu.py` fetches them, so `--link` builds the GPU backend unchanged | `fetch_gpu.py` (glslang is the build-time shader compiler the owner allowed, 2026-09-30) |
| `mods/` | each shipped mod's `mod.c` and `mod.ini` (their addresses are rule-3 metadata), built into `mod.dll` at the root by R1's GNU mod build | the tagged commit |
| `licenses/` | the texts for CPython, LLVM, llvm-mingw, mingw-w64, Vulkan-Headers and glslang | each project |

**Never in it:** `src/`, `include/`, anything from `gen/`, `extracted/` or `build/`, a DOL or anything
built from one. R3's guard holds the zip to that.

### 3.7 The install folder

`Setup.exe` builds into the folder it was extracted to and puts `soa.exe` and `mods\` at its top. In the
package `runtime\` sits under `source\`, so settings.c's last rule makes the install folder the root
(settings.c:160-212) [V]. The folder then holds `extracted/` (until disc-layer I1 lets the game run from
the image), `gen/` (kept, for rebuilds), `soa.exe`, `soa.ini`, `mods/`, `build/`. About 1.6 GB beside the
package [I]; with I1 landed the image is read where it lies and its copy goes.

- **Both working-directory defaults move under the root** (R2): gxv.c's pipeline cache through
  `settings_root()`, and `Setup.exe` starts `soa.exe` with the root as its working directory.
- **ANSI paths:** until settings.c uses the wide calls, `Setup.exe` refuses a folder path that is not
  plain ASCII, saying why, rather than let the root be lost silently.
- **Where it may not write:** `Setup.exe` checks write access and free space (about 2 GB) before it
  starts, and refuses Program Files with a message.

### 3.8 Identity, reproducibility, and a stale `gen/`

- **The disc is checked before any work:** the game ID and the DOL's SHA-1, refused by name ("this is
  not the North American GameCube release, GEAE8P"; "this disc's executable is not the one this package
  was made for"). `player_build` treats extract.py's "cannot check" as a refusal.
- **The build says what made it:** `soa.exe`'s `[boot]` line gains the package version, the compiler's
  version (L3b already prints it) and the DOL's SHA-1.
- **Never a stale `gen/`:** `player_build` records the package version and a hash of every input the
  chunks bake in (G5's build inputs), and retranslates from scratch when any differs. A new package
  over an old folder, and the setup window's Rebuild, take that path.
- **Two builds from the same package and disc give the same `soa.exe`, byte for byte:** no timestamps
  (`-Wl,--no-insert-timestamp`), `-ffile-prefix-map` for the absolute paths `__FILE__` writes (gxv.c:286
  is one, and would put the player's user name in the exe), sorted inputs, no PDB. This is what lets a
  player's bug report be reproduced.

---

## 4. Order

R1 to R4 come after the GPU build (V8 onward, D-27) and before L12, as G3's answer put it; **R1 may go
earlier as a gap filler**, since it touches only the toolchain and is worth having for the Deck
regardless. R5 is built with L12.

---

## 5. Slices

### R1. `soa.exe` with no Microsoft compiler

*Landed 2026-10-04 (FINDINGS "R1"): every Done line below holds. Added while building:
`runtime/soafma.c` (the instruction where the CPU has FMA3, musl's exact `fma` otherwise), named by
`cpu.h` in a MinGW build only; and the GNU mod build writes `gen/mingw/mods`, never beside the msvc
build's `mod.dll`.*

*Week-plus. Rebuild: one retranslation with the new profile. Prerequisites: Q-D1. Files:
`tools/fetch_mingw.py` (new); `tools/soa/toolchain.py` (a `mingw` profile:
`--target=x86_64-w64-mingw32 -O2 -ffp-contract=off -fno-strict-aliasing -fwrapv`, the libraries of §2 as
`-l`, `-Wl,--stack,33554432`); `tools/recompile.py` (a GNU-style `--link`, which L10 then reuses on Linux,
and a GNU `mod.dll` build); `runtime/selftest.c` (§3.4's fused case); the math of §3.3; `tools/gpuspike.py`
(an `--exe` for `contrast`); runtime fixes the build finds; `.github/workflows/ci.yml` (a job compiling
every runtime file with the pinned llvm-mingw).*

*Done:*
- `python tools/fetch_mingw.py --verify` checks every fetched file against its recorded hash; one changed
  byte fails it.
- `python tools/recompile.py --cc mingw --compile --optimize --link` builds `gen/mingw/soa.exe` on this PC
  with no MSVC environment captured (a test makes `msvc_env` raise for the run).
- With that exe:
  - `SOA_SELFTEST=1` passes, the fused case among them;
  - `python tools/scenario.py replay --exe gen/mingw/soa.exe --threads 1,2,3,8` is 23/23 against the
    manifest;
  - `title --check` passes;
  - `SOA_GPU=vulkan` starts the GPU backend, and `gpuspike.py contrast --exe gen/mingw/soa.exe` gives the
    spike's pixels;
  - a shipped mod built by the GNU mod build loads and applies.
- `llvm-readobj --coff-imports gen/mingw/soa.exe` lists no `fma` and none of `config/libm.tsv`'s functions
  from a CRT DLL.
- **The mutations:**
  - a naive `fma` linked in fails the self test's fused case;
  - `-mfma` without `-ffp-contract=off` is built and replayed, and FINDINGS records whether a hash moved
    (if none does, the renderer's math has no contraction to lose on these frames, and FINDINGS says so);
  - an `__try`/`__except` added on a scratch branch turns CI's new job red (the CI-mutation-on-a-branch
    practice).
- FINDINGS records the MinGW build's time against MSVC's and clang-cl's, interleaved.

### R2. One command from a disc image to an install folder

*Landed 2026-10-04 (FINDINGS "R2"), every Done line holding. As built: `tools/package.py stage`
is R3's staging; `discfixture.write_rvz` makes the synthetic RVZ; the never-stale check is
`test_player_build.py` on the build's decision, and the staged package's run with `cpu.h` changed
is in FINDINGS.*

*Several days. Rebuild: none for the port. Prerequisites: R1. Files: `tools/player_build.py` (new),
`tools/extract.py` (callable as a function), `tools/recompile.py` (a build with no `src/`: no native units,
no MSL bindings), `runtime/gxv.c` (the pipeline cache under the root), `runtime/selftest.c` (case 73
skipped, by name, with no bindings), `tools/package.py` (R3's staging, used here to test),
`tools/tests/test_citest.py`.*

- `python tools/player_build.py --disc <image> --root <folder>` checks the image (§3.8), extracts what the
  game reads, translates, compiles with the bundled compiler on every core, links, builds the mods and
  writes `soa.ini`. It prints one machine-readable line per step and translation unit (`[build] 7/19
  chunk_006.c`), which R4's window reads, and ends with the exe's SHA-256.
- It runs from the package's own `python/` and `toolchain/`, and a test runs it with `PATH` holding nothing
  else, so an installed Python, MSVC or LLVM cannot be picked up by accident.

*Done:*
- On this PC, from a package staged by `tools/package.py` into an empty folder and run with that bare
  `PATH`, the owner's disc builds. The build prints `GPU backend: built in`, and the result passes the self
  test (case 73 named as skipped), `replay` 23/23 and `title --check`.
- FINDINGS gets the wall time, and the cost of the translated MSL (§3.1) on `partl`, interleaved against
  the native build.
- **Reproducible:** a second build in a second folder, with another folder name, gives a byte-identical
  `soa.exe`. Its mutation drops `--no-insert-timestamp`, and the two must then differ.
- **Never stale:** a staged package with one byte of `runtime/cpu.h` changed, built over a finished
  folder, retranslates (its log says why). With the check removed it would only relink, and the test
  fails.
- **Run from elsewhere:** `soa.exe` started with another working directory puts its pipeline cache under
  the root (its `[gxv] pipelines:` line names the path).
- **Refusals,** each by name, each a test with no game data: a game ID other than `GEAE8P`, a synthetic DOL
  whose SHA-1 differs, an image that is not a disc, and the "cannot check" case.
- **The RVZ path under the embedded Python:** a standard-library script builds a small synthetic RVZ and
  reads it back under `python\python.exe`. The same script with `_zstd.pyd` removed fails.

### R3. The package, its guard, and the workflow that makes it

*As built, 2026-10-04: `tools/package.py --out` stages, adds `licenses/` (eight texts: those the
package carries, and llvm-mingw's and glslang's fetched at their tags, pinned), zips and hashes;
`guard.py --tree` also allows `python/`, the embeddable CPython, whose DLLs pass the size limit;
its DOL check reads offset 0 of every file and every 32-byte step of the package's own files.*

*A day to several days. Rebuild: none. Prerequisites: R2. Files: `tools/package.py` (new), `tools/guard.py`
(`--tree <dir>`), `.github/workflows/release.yml` (new).*

- `tools/package.py --out <dir>` assembles §3.6 from a clean checkout and the pinned downloads, and zips it.
- `guard.py --tree <dir>` scans a folder, not git, with the package's rules: `toolchain/` and
  `source/vendor/` allowed, no size limit there, and every other rule kept. It adds a DOL found by
  content (its header's section table, wherever the bytes sit) and refuses `src/` and `include/` by name.
- `release.yml` runs on a version tag and on `workflow_dispatch`. In order: the tests, R1's job, the
  package, `guard.py --tree` over the unzipped package, then a **draft** release with the zip and its
  SHA-256. The owner publishes.

*Done:*
- The workflow, run by `gh workflow run release.yml --ref <branch>`, produces a draft whose package
  passes `guard.py --tree`, with its size printed.
- **The mutations:** a branch that plants a synthetic DOL into the staging folder fails the workflow before
  any release is drafted, and so does one that copies a file of `src/` in.
- That zip, downloaded to this PC into a new folder, passes R2's Done from there.

### R4. The setup window

*Several days. Rebuild: none for the port. Prerequisites: R2 (R3 to ship it). Files: `tools/setup/setup.c`
(new, Win32: the file dialog, a progress bar fed by R2's lines, a log pane, Play), its build in
`package.py`.*

- One window: pick the disc; §3.8's checks in words a player understands; the progress bar; on failure,
  the log and where it is saved; then Play, which starts `soa.exe` with the root as its working
  directory and closes the window.
- `python.exe` and the compiler are console programs: Setup starts them with `CREATE_NO_WINDOW`, so no
  console appears.
- §3.7's checks before anything is written: ASCII path, write access, free space, not Program Files.
- **Smart App Control:** where it is on, Windows blocks unsigned programs outright (research §5). That
  covers the bundled `clang.exe` and `ld.lld.exe` and the `soa.exe` built on the player's machine, which no
  signature can cover. Setup reads its state [I: `HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy`,
  `VerifiedAndReputablePolicyState`] and, where it is on, says plainly that the build cannot run and why.
- Unrecognised image formats name Dolphin's converter. A second run in a built folder offers Play and
  Rebuild.

*Done:*
- On this PC, from R3's zip: extract, run `Setup.exe`, pick the disc, reach the title screen with no
  console window opened.
- **Owner:** the same on the Ally X, and on a Steam Deck under Proton if one is available (portability's
  Proton question is still open). The owner's notes are filed.

### R5. Android: a runtime-only APK and a game library from the PC

*Specified with L12; recorded here so L12 does not miss what route C2 needs. Prerequisites: L12, R2.*

- **A seam between the runtime and the game.** Today `soa.exe` links everything. C2 needs the translated
  code built as a shared library (`libsoa_game.so`), which the APK's runtime loads with `dlopen` from the
  app's own storage and calls through a small versioned table. **The library records §3.8's build inputs**
  and the table's version. The runtime refuses a library made from other inputs, naming the rebuild the
  player needs, rather than run a stale one.
- **The PC build gains `--target android-arm64`:** clang cross-compiling with Android's headers and
  libraries. Whether the NDK's sysroot may be shipped in the package, or must be fetched on the player's PC,
  is L12's to settle (its licence terms are not this spec's to read [I]).
- **The phone:** the APK asks for the library and the disc image through the system file picker (SAF) and
  copies them into its storage (L12's "SAF import").
- **Done** belongs to L12: replay 23/23 at 1-8 threads on the phone from a library built on this PC.

---

## 6. For the owner

- **Q-D1. The bundled compiler** (before R1). llvm-mingw, about 190 MB, fetched at a pinned release and
  never installed, as glslang is. ***Answered 2026-10-04: yes, fetch it*** (PLAN-NEXT §0).
- **Q-D2. Signing** (before the first public release). SignPath Foundation signs open-source releases free,
  if the binary is built by CI from this repository's source (research §5). The package fits that: it holds
  no game code, and `Setup.exe` is built from `tools/setup/`. Signing cannot cover the `soa.exe` built on the
  player's machine, nor the third-party toolchain. Unsigned, SmartScreen warns once ("More info", "Run
  anyway"), and Smart App Control blocks it (R4).
- **Q-D3. Android registration** (before the first APK): register under your ID ($25, government ID), or
  have players use Android's 24-hour advanced flow (research §4).
- **Q-D4. Who presses publish.** R3 drafts releases; this spec assumes you publish each one.

---

## 7. Risks

1. **Math under Proton** (§3.3) and **floating point under MinGW** (§3.4) are the ones that change results
   silently. R1's import check, its fused self-test case and its mutations are there for them.
2. **Smart App Control** blocks the build itself where it is on, and nothing in this design can sign
   what the player's machine builds. R4 detects it and says so. The owner should know that some players
   cannot use this route without turning it off.
3. **setjmp and longjmp across fibers** under MinGW are unproven; the self test's savepoint cases and
   `title --check` exercise them.
4. **The translated MSL's cost** (§3.1) is unmeasured until R2.
5. **The Deck's build time** is an estimate (5-15 minutes); R4's owner session measures it if a Deck is
   available.
6. **The package's size** (150-250 MB [I]) is mostly the compiler. Pruning llvm-mingw to one host and one
   target is R3's to measure.
7. **Antivirus** may flag a freshly built, unsigned `soa.exe` written by a script. R4's window says what to
   do if Windows Defender quarantines it.

---

## Review log

One review on 2026-10-04, read-only against the code at 019e593. What it changed:

1. **`src/` was in the package.** §0 says the download holds no decompiled game code; §3.1 now builds
   without it.
2. **The floating-point check could not fail.** Baseline x86-64 has no FMA to contract into, `replay` runs
   no guest code, and the self test had no fused case. Now §3.4 and R1's mutations.
3. **The static CRT does not carry over to MinGW.** Now §3.3 and R1's import check.
4. **A kept `gen/` could go stale.** Now §3.8's build inputs, with R2's mutation, and R5's refusal.
5. **The package would have had no GPU backend.** glslang now ships in `source/vendor/`.
6. **Mods would not load.** R1 now has a GNU mod build, and `mods/` sits at the root.
7. **Two working-directory defaults.** Now §3.7, and R2's run-from-elsewhere check.
8. **The guard could not scan a package.** Now `guard.py --tree`.
9. **Done lines that could not run or fail.** Fixed:
   - `contrast --exe`;
   - the RVZ script, in place of a test that does not exist;
   - a named MSVC-only construct for the CI mutation;
   - a mutation for reproducibility, and `-ffile-prefix-map`;
   - a synthetic DOL.
10. **Smart App Control, and console windows.** Now R4 and risk 2.
11. **ANSI paths, write access, free space, licence texts, llvm-mingw's licence.** Now §3.7, §3.6 and §3.2.
12. **Five citations corrected:** the log lines, the link time, the claim that nothing checks the DOL after
    extraction, emit.py's path, and the stdlib test.
13. **Where the toolchain lives.** `vendor/` for developers, `toolchain/` in the package, found in that
    order. Now §3.2.
