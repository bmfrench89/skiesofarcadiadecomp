# R5: the phone's game library built on the player's PC — the final design

*Committed with R5-0 on 2026-10-07 (FINDINGS "R5-0") as it was settled, but for this note and §1.0's first
line. It owns R5's slices, R5-0 to R5c, and supersedes [android.md](android.md) §3.4 and
[distribution.md](distribution.md) R5 where they differ; R5a part 1 rewrites android.md §3.4 from it (§9).
Its [V] marks that name `r5/…` or the scratchpad are the review's scratch probes, which were not kept: some
read builds made from the owner's disc.*

*Settled 2026-10-07 at HEAD 6d5916c, which committed the gate's work (FINDINGS "R5's gate, and a push held to its
size"). This is the draft of the same day (scratchpad `r5_design.md`, written at 5acabbd) with every fix that four
adversarial reviews asked for and this pass accepted. Each problem was checked again against the code, the scratch
probes or the reviewers' own probes before it was accepted. §11 lists all 66 problems, accepted or not, and why. R5
always means distribution.md's R5. The owner's choices it designs to:*
- *D-31: llvm-mingw plus this repository's own Android sysroot;*
- *D-34: the sysroot is **built where it is used**, from bionic's sources at a pinned commit, each file held to a
  hash this repository holds, **by the script every machine runs**, "rather than built once by CI and published"
  (PLAN-NEXT.md:159-164, :885); the stub libraries come from `config/seam.txt` at each link. This design reads
  "every machine" as every machine that uses the sysroot, **the player's PC included** (§0.1, §11 F13);*
- *D-35: the sysroot's licences ship with their texts in `licenses/`;*
- *D-36: L12's Done on the Thor runs a library built through R5's route.*

*file:line references are at 6d5916c. The gate's commit changed no file R5 edits except `tools/android.py` and its
test (`git diff --stat 5acabbd 6d5916c -- tools runtime .github`), so the draft's references into the other files
still hold.*

**Marks.** **[V]** is measured or read in code, with where. **[I]** is inferred.

---

## 0. The design on one page

**What changes.**
- **First, a fix of its own: R5-0.** Two package defects the reviews found, which R5 would build on:
  - a package staged since L10 cannot import `recompile.py`, because `fetch_sdl.py` is missing from `TOOLS`. The
    owner's pending R4 run on the Ally X fails on it today;
  - the release workflow's checkout on `windows-latest` turns the files git stores with LF into CRLF, and
    `player_build.inputs_record` hashes raw bytes. So a package CI builds bakes a different `baked=` from the
    commit's. From R5 on, a phone would refuse its library as "from a different release".

  R5-0 adds `fetch_sdl.py`, reads CRLF as LF in the digest, stops the release runner converting, and holds every
  release's package to the commit's baked inputs.
- **A new tool, `tools/fetch_android_sysroot.py`,** holds 47 files of bionic at commit
  `06356e41c5ed7b12220b24c05ba4fdb873b126a7` (`android-17.0.0_r1`) to two pins each, their sha256 and their git
  blob id. From the 44 that a build reads it builds `vendor/android-sysroot/`:
  - the 30 headers the game library reads;
  - `crtbegin_so.o` and `crtend_so.o` for arm64 and x86_64, compiled from bionic's source by llvm-mingw's clang
    and held to output pins (the objects the gate's emulator run used);
  - `NOTICE.txt`, every source file's own licence words.

  It records the tree in `vendor/ANDROID-SYSROOT.sha256`. Standard library and `soa.toolchain` only.
- **Built where it is used, the player's PC included (D-34).** The package carries the 44 pinned source files, not
  a built tree. The player's PC builds the tree from them on its first Android build: offline, in seconds, held to
  the same output pins. Nothing built from AOSP is published, and a damaged tree rebuilds itself from the sources.
- **The two Android profiles move to llvm-mingw.**
  - `toolchain.cc()` adds `--sysroot=<vendor>/android-sysroot` to every Android command, and runs it without the
    environment variables clang reads ahead of a sysroot (`CPATH`, `COMPILER_PATH` and the rest).
  - Every Android link is `-nodefaultlibs`, with `-lm -ldl -lc` after the objects.
  - **One llvm-mingw for both profiles.** The Android compiler is the `clang` beside the `x86_64-w64-mingw32-clang`
    that the mingw profile finds (`SOA_MINGW`, a package's `toolchain/bin`, then `vendor/llvm-mingw/bin`). An
    Android build refuses a clang whose `--version` does not name llvm-mingw 20260922's clang 23.1.2 at its commit.
- **The stub C libraries come from `seam.txt` at each link.** `seam.py` writes `libc.so`, `libm.so` and `libdl.so`
  stubs into `<out>/stub/`: bionic's placement of each name, at version `LIBC`, with version scripts named `*.vers`,
  passed to the linker with `-Xlinker` so a folder name with a comma cannot split them. A call outside the seam
  then fails the link on the PC.
- **`recompile.py` has one Android link plan**, which `gamefixture` calls.
  - `build_inputs.txt` records the compiler and its flags for every gnu profile, and for Android the sysroot. A link
    of objects another compiler, other flags or another sysroot made is refused. An Android `gen/` with no record,
    or one that names none of these, is refused too.
  - Android looks up its compiler and sysroot before anything else, and says where it looked.
  - The post-link check is the phone's (`android=True`, `dol=`). FAIL lines carry stderr. The progress lines say
    what each Android step builds. The ELF machine comes from the profile's name.
- **`player_build.py --target android-arm64`** builds `<root>/gen-android-arm64/` and puts `libsoa_game.so` beside
  `soa.exe`.
  - A preflight right after the disc check, before the extraction or any target: the sources, the compiler, the
    space. Then the sysroot, built from the package's sources when it is not there.
  - Its own `[build] android …` lines. Its never-stale record gains the package version, the compiler, the
    compile flags and the sysroot.
- **The package** carries `source/vendor/android-sysroot-src/` (the 44 pinned files), `source/VERSION`, the new
  tool, and three new licence texts. **Setup** gains the Android checkbox and its words.
- **Around it:** `.gitignore` and the guard refuse `gen-*/` folders and `.so` files in the tree; `android.py
  push-game` holds a library to the APK's record before it pushes; a new CI job runs the route on Ubuntu and on
  Windows, where players build.

**What stays.**
- **The NDK** keeps building the APK's `libsoa_runtime.so` (Gradle, `ndkVersion 28.2.13676358`).
- **The NDK also runs the runtime's compile check for the phone,** under new profile names `android-arm64-ndk` and
  `android-x86_64-ndk`. No player ever needs or fetches any of the NDK.

**Order.**
- **R5-0, the package fixed** (one push).
- **R5a, the sysroot and the route,** in two pushes: part 1, the tool; part 2, the route, proved on the emulator
  with a library `recompile.py` built.
- **R5b, the player's build and the package,** proved on the emulator with a library built from the zip the
  release workflow drafted.
- **R5c, Setup's checkbox and words.**
- **Then L12's Done on the Thor** (D-36), the owner's session.

**What the owner does.**
- R5-0: nothing. R4's run on the Ally X can use a package staged after it.
- R5b: look at the licence texts; and read one line saying how this design read D-34.
- R5c: the first bless of Setup's words, and three small questions (§1.3).
- Then: the Thor.

### 0.1 Decisions, each with its reason

| Question | Decision | Why |
|---|---|---|
| Design (map §6) | **Design 2**: a minimal sysroot built from pinned sources wherever it is used; stubs from `seam.txt` at each link | D-34 [V PLAN-NEXT.md:159-164, :885]. |
| Who builds what a player uses | **The player's PC**, from the 44 pinned files the package carries, offline, on its first Android build. Developers, CI and the release runner build it too, from the same files, fetched once into a cache. | D-34's own words: "built where it is used ... by the script every machine runs ... rather than built once by CI and published". The player's PC is where the sysroot is used. The build takes seconds and is held to the same output pins, so it is as checked as a shipped copy [V: a reviewer rebuilt all four crt objects to their pins from a cache holding only the 44 files, in a folder whose name has a space and a comma, with only `clang.exe` and `ld.lld.exe`, both of which the package carries; scratch `r5/review_probe`]. The draft read it otherwise [I]; §11 F13. |
| Bionic commit | `06356e41c5ed7b12220b24c05ba4fdb873b126a7`, which tag `android-17.0.0_r1` (tag object `7eb60ba2…`) peels to | The gate ran it [V FINDINGS:7731-7742]. The peel is from gitiles' refs [V scratch `aosp/bionic_refs.json`]. URLs use the commit, never the tag name. |
| Pins | **sha256 and git blob id**, both checked whenever a file is read | The blob id is upstream's own pin, which gitiles lists; checking both ties the two columns together, so neither can be edited alone (§11 N7). |
| Headers | **30** for both ABIs: 23 common, 3 arm64 `asm/`, 4 x86_64 `asm/` | `clang -M` against bionic at the commit [V A.1]. The map's 32 included `linux/compiler.h` and `linux/compiler_types.h`, which android-17's `linux/stddef.h` no longer reads. |
| crt objects | Built from bionic's source, laid out `usr/lib/<triple>/33/`, held to output pins | What the gate's library ran with [V A.3]. |
| RELR | **clang 23's default** (`--pack-dyn-relocs=android+relr` at API ≥ 28); no flag | The emulator ran RELR [V FINDINGS:7736-7738]. Bionic reads `DT_RELR` from API 30; the floor is 33 [V map §3.5]. |
| `-mno-outline-atomics` | **Not added** | No atomics today [V map §2.5]. A future arm64 atomic fails the link on the PC, naming `__aarch64_…`. |
| `-lm -ldl` | **Kept**: `DT_NEEDED` `libsoa_runtime.so`, `libm.so`, `libdl.so`, `libc.so` | What ran on the emulator [V FINDINGS:7735; A.4]. |
| `libdl.so` stub | **Empty** | `seam.txt` names nothing of libdl's; the game library is byte-identical either way [V A.4]. |
| ABIs in the sysroot | arm64 (players, the Thor) and x86_64 (the emulator, CI's fixture) | x86_64 adds 4 headers and 2 crt objects, 4,812 B [V A.2, A.3]. |
| Where the sources and tree live | Sources: `vendor/android-sysroot-src/` (a checkout's cache), `source/vendor/android-sysroot-src/` (a package's 44). Tree: `<vendor>/android-sysroot/` and `<vendor>/ANDROID-SYSROOT.sha256` | recompile's `VENDOR` and `toolchain` both resolve there in either layout (recompile.py:62, toolchain.py:285). `source/vendor/` is the guard's third-party allowance (guard.py:463), so the sources' `libc/include/` passes `--tree`. |
| The compiler's identity | `clang version 23.1.2` at llvm-project commit `85ac5602…`, required for an Android build | Two profiles that each searched for their own compiler could resolve to two toolchains on one machine (§11 F2). |
| The ARM32 mutant | A 32-bit ARM `.so` from a one-line C file, built `-nostdlib -ffreestanding` | The sysroot has no armv7 piece [V map §3.6]. elfcheck refuses on the machine first (elfcheck.py:221-225). |
| The library's record | Gains `package=`, `cc=` and `sysroot=` after `profile=`, for Android profiles; each value cut at 64 characters; no cap check | distribution §3.8, "the build says what made it". The longest record is 321 bytes, under the 511 the phone reads, and `dol=` comes before the new keys (§5.7). |
| BAKED | **The same list**, read with CRLF as LF | `baked=` must not depend on how a tree was checked out: the APK and the library come from different checkouts by design (§11 F4). |
| Translation per target | **Separate**: `<root>/gen` and `<root>/gen-android-arm64` each translate | Both profiles name their objects `.o`, so one folder cannot hold both, and a shared C folder would need a new recompile option and a joint record. R5b measures what it costs (§11 P18). |

### 0.2 Corrections to the map, found by the draft's probes

1. **The closure is 30 headers at android-17.0.0_r1, not 32** [V A.1]. The "bionic's stubs, no notice" licence class
   (map §4.6) drops out, and the gate's sysroot carried two unread headers.
2. **`bionic_asm.h` does not read `features.h` at this commit.** The crt build reads 14 files beyond the headers
   [V A.1]: six from `libc/arch-common/bionic`, four from `libc/private`, and `asm/unistd.h` and
   `asm/unistd_64.h` for each ABI.
3. **Scratch `up/` is not the pinned commit.** Never take a pin from `up/` [V A.2].
4. **The gate's `libdl.so` stub held `dlopen`, `dlsym`, `dlclose` and `dlerror`,** which are not in `seam.txt`. An
   empty one gives the same game library [V A.4].
5. **AOSP's `external/kernel-headers` NOTICE is GPL-2.0 alone, with no syscall note** [V A.5]. The note comes from
   the kernel's own `LICENSES/` (§2.10).

### 0.3 What the reviews changed, in one list

The largest changes, each with its §11 entry:
- **R5-0 before R5a** (P6, F4/N1/P1): the package's two defects fixed first.
- **The player's PC builds the sysroot** from shipped sources (F13/N11/P15).
- **One llvm-mingw, pinned by identity**; the environment cleaned for Android commands (F2, F8).
- **A preflight in `player_build`** before any work, in player words (P2, N10).
- **The tool repairs, never loops:** a plain run rebuilds a tree that is not as recorded, with no network when the
  cache is whole; the swap is ordered so a stop leaves no record (N4, F9).
- **Fetching:** archives only on a build's path, transport failures retried, one deadline, both pin columns
  checked, `--from` for outages, a cache keyed on the pins and shared across operating systems (N3, N5, N6, N7, N9,
  F5).
- **The record of what built the objects** gains the compile flags; Android refuses a missing record; the
  compiler is looked up before records are compared (P8, F7).
- **Tests and CI:** a CI job on Ubuntu and Windows for the route; call-site tests for FAIL lines and progress; the
  header comparison committed as `--compare`; every new branch with a mutation (T1-T24).
- **`gen-*` folders and `.so` files** refused by `.gitignore` and the guard (N2, P5).
- **Setup's words and status** follow what this run built, and its space check counts the Android build (P3, P4,
  P7).

---

## 1. Slices

Each slice ends with CLAUDE.md's pre-push list, in order, each command's exit code printed (memory "Check chains
need pipefail"):
- `python tools/guard.py`;
- `python tools/guard.py --history`;
- `python -m ruff check tools`;
- `python -m ruff format --check tools`;
- `python -m pytest`;
- then the "You touched" rows its files touch, named in each slice's Done.

**`baked=` moves in R5-0, R5a part 2 and R5b**: R5-0 changes how the digest reads files, and R5a part 2 and R5b
edit `recompile.py`, which is in BAKED (player_build.py:62). Every emulator run therefore starts with
`android.py build` and `install`, or the APK refuses each new library as "another release".

**Folders.** Every root, package and scratch folder a Done line names is under `build\`, which `.gitignore` and the
guard both cover, so nothing a check builds can be staged by `git add`.

### 1.0 R5-0. The package builds again, and carries the commit's bytes (one push)

*Done 2026-10-07 (FINDINGS "R5-0"), with what differed from this text recorded there.*

**Purpose.** Two defects in the package, fixed before R5 builds on it.
- **`TOOLS` lacks `fetch_sdl.py`** (package.py:57) since L10 (d6d64aa), which made `recompile.py` import it at the
  top (recompile.py:51). A staged package's `player_build.py` imports fine, but the `recompile.py` process it starts
  stops at `import fetch_sdl` [V: reviewer's probe `r5/review_pkgtools`, and the draft's A.6]. PLAN-NEXT §0 says the
  owner's R4 run on the Ally X "is to come"; it would fail.
- **The release runner converts line endings.** `release.yml` checks out on `windows-latest` with the runner's Git
  defaults (release.yml:22-26). There is no `.gitattributes`. Git for Windows' system configuration sets
  `core.autocrlf true` [V on this PC: `C:/Program Files/Git/etc/gitconfig`, which this user's `.gitconfig` overrides
  with `false`]. Ten of the files BAKED hashes are stored with LF [V `git ls-files --eol`]: `config/hle.txt`,
  `hooks.txt`, `savepoints.txt`, `tools/recompile.py`, `tools/soa/hle.py`, and five under `tools/soa/ppc` and
  `tools/soa/recomp`. A reviewer read the zip CI drafted at 0223b3a: its `tools/recompile.py` is 25,436 B with 589
  CRLF, where git's is 24,847 B with none [V `r5/review_crlf_probe.py`]. `inputs_record` hashes raw bytes
  (player_build.py:121-132), so that package's `baked=` is not the commit's. Since L12a (75d5ce2, after R3's
  cross-check of 2026-10-04) the digest sits in every `soa.exe`'s record, so R3's "the package CI makes and the tree
  here agree, byte for byte" no longer holds; from R5 on, a phone would refuse such a package's library.

*Files:*
- `tools/package.py`:
  - `TOOLS` gains `fetch_sdl.py`;
  - `stage_source(source)`: the copying of `runtime/`, `config/`, `tools/soa`, `TOOLS`, `TOP` and the mods' text,
    factored out of `stage()` (package.py:155-168), which calls it;
  - `python tools/package.py check <package folder> [--commit REV]` (§6.2): the package's baked inputs against the
    commit's, by `git cat-file`.
- `tools/player_build.py`: `inputs_record()` reads each file with CRLF as LF, and its docstring says why.
- `.github/workflows/release.yml` (§7.3):
  - a first step, `git config --global core.autocrlf false`, then `git config --show-origin --get-all
    core.autocrlf` printed once, before `actions/checkout`;
  - in the guard step: the package's own Python imports every module in `TOOLS`, with `-I`; then
    `python tools/package.py check $pkg`.
- Tests:
  - `test_package.py`: `test_the_staged_tools_import_what_the_build_imports` and
    `test_a_package_s_baked_inputs_are_held_to_the_commit_s` (§8.2);
  - `test_player_build.py`: `test_the_baked_digest_reads_crlf_as_lf`.
- Docs: TESTING (the three rows, R3's recipe gains `package.py check`, the counts), distribution.md's R3 and R4
  notes (both defects, since when), HANDOFF, PLAN-NEXT §0, FINDINGS.

*Done, on this PC:*
- **The tests.** Before the fix, `python -m pytest tools/tests/test_package.py -q` fails
  `test_the_staged_tools_import_what_the_build_imports` with `ModuleNotFoundError: No module named 'fetch_sdl'`
  (shown in FINDINGS). After it, `python -m pytest tools/tests/test_package.py tools/tests/test_player_build.py -q`
  prints the measured `N passed in Ts` with no skip, where `vendor/` holds the embeddable CPython.
- **The package imports.** `python tools/package.py stage build\r5-0\P` prints `staged …\build\r5-0\P`, and
  `build\r5-0\P\python\python.exe -I -c "import sys; sys.path.insert(0, r'build\r5-0\P\source\tools'); import
  recompile, player_build, extract, decomp, fetch_gpu, fetch_sdl"` exits 0.
- **The player's build from it.** R2's recipe, with `PATH` holding only `P\python` (FINDINGS "R2"):
  `P\python\python.exe P\source\tools\player_build.py --disc <the owner's image> --root build\r5-0\R` ends
  `[build] done soa.exe sha256 <hex>`, exit 0. The same command from the checkout's `tools\player_build.py` into
  `build\r5-0\R2` ends with the same hex.
- **The check.** `python tools/package.py check build\r5-0\P` prints
  `baked inputs of build\r5-0\P\source: <12 hex>, and of <commit>: <12 hex>, the same` and exits 0.
- **The CRLF case, by hand.** `P\source\tools\recompile.py` rewritten with CRLF line ends: `package.py check`
  still passes, since the digest reads CRLF as LF. With `inputs_record`'s normalisation taken out, it exits 1 with
  `build\r5-0\P\source: tools/recompile.py is not the commit's (… the checkout converted its line endings?)`.
  The file and the code are put back.
- **On CI.** `gh workflow run release.yml --ref <scratch branch>` drafts a release. Its log shows
  `core.autocrlf` as `false` (`--show-origin` names the global file), the import line passing, and the check's
  line. The draft is deleted after (`gh release delete <tag> --yes`); the branch too.

*Mutations:*
1. **Today's `TOOLS`:** the import test fails, naming `fetch_sdl` (shown before the fix).
2. **`inputs_record` on raw bytes:** `test_the_baked_digest_reads_crlf_as_lf` fails; so does the by-hand case above.
3. **A check that compares nothing:** `test_a_package_s_baked_inputs_are_held_to_the_commit_s`, whose package
   holds one BAKED file a byte off the commit's, fails.

*Emulator:* none. `baked=` moves once (every file stored with CRLF now hashes as LF), so the next emulator run
rebuilds the APK, as every slice's does.

*Owner:* nothing. The R4 run on the Ally X goes ahead with a package staged after this push.

### 1.1 R5a. The sysroot and the route

**Purpose.** The game library for both ABIs is built by llvm-mingw against this repository's own sysroot, on every
machine, through `recompile.py` and `gamefixture` alike. The NDK leaves the game library's path.

#### Part 1: the tool (one push)

*Done 2026-10-07 (FINDINGS "R5a part 1"), with what differed from this text recorded there.*

*Files:*
- `tools/fetch_android_sysroot.py` (new), all of §2:
  - constants `COMMIT`, `TAG`, `BASE`, `API`, `ABIS`, `ARCHIVES`, `TEXT_FILES`, `SOURCES`, `SHIP`, `OUTPUTS`,
    `CRT_FLAGS`, `DEST`, `RECORD`, `CACHE`, `PACE`, `TRIES`, `WAIT_CAP`, `DEADLINE`;
  - functions `fetch()`, `archive_url()`, `text_url()`, `blob_id()`, `held()`, `sources()`, `fill_from()`,
    `cache_problems()`, `mingw_tools()`, `build_crt()`, `notice_text()`, `build()`, `expected_record()`,
    `read_record()`, `write_record()`, `verify()`, `sysroot_digest()`, `ensure()`, `check_upstream()`,
    `cache_key()` and `main()`;
  - its first lines insert its own folder into `sys.path`, as recompile.py:46 does, before `from soa import
    toolchain`: the embeddable CPython's `python314._pth` adds no script folder [V the zip's `._pth` holds
    `python314.zip` and `.`; reviewer's probe `r5/review_probe/emb` got `No module named 'soa'` without it].
- `tools/soa/toolchain.py`, the part the tool needs (§4.2):
  - `MINGW_RELEASE = "20260922"` and `MINGW_CLANG = ("23.1.2", "85ac560262434c9ccfc0c183ec22d4138ed647fb")`;
  - `mingw_clang()` and `mingw_lld()`: the `clang` and `ld.lld` beside `compiler_path(MINGW)`;
  - `clang_id(exe)`, the first line of `<exe> --version`, cached per path;
  - `mingw_identity_problem(exe)`: words when that line does not name `MINGW_CLANG`'s version and commit;
  - `clean_clang_env()`: `os.environ` without the variables clang reads ahead of a sysroot.
- `tools/tests/test_android_sysroot.py` (new): checks 1-10, 13-15 and 17 of §8.1.
- `tools/tests/test_mingw.py`: `test_the_android_clang_is_llvm_mingw_s_own` and
  `test_the_pinned_clang_is_fetch_mingw_s` (§8.2).
- `.github/workflows/ci.yml`: the new `android-route` job on Ubuntu and Windows, with the tool's steps and
  `test_android_sysroot.py` (§7.1).
- Docs:
  - TESTING.md: a recipe under section 2, "The Android sysroot (R5a)"; the new module's row; the CI table's new
    job, and the `mingw` job it already lacks (TESTING.md:1903 says "Nine job runs" where ten run); the counts;
  - CLAUDE.md: the "You touched" row (§9);
  - FINDINGS: an entry, with the first fetch from GitHub's runners (requests, waits, any 429);
  - the check skill: step 5g.

*Done, on this PC*, run from the repository's root:
- **A first build.** `python tools/fetch_android_sysroot.py`, with no `vendor/android-sysroot*`, prints four lines
  `fetching https://android.googlesource.com/platform/bionic/+archive/06356e41c5ed7b12220b24c05ba4fdb873b126a7/<dir>.tar.gz`
  (for `libc/include`, `libc/kernel/uapi`, `libc/arch-common/bionic`, `libc/private`), then exactly:
  ```
  44 of 44 bionic files the build reads, at 06356e41 (android-17.0.0_r1), are as pinned
  built crtbegin_so.o and crtend_so.o for arm64 and x86_64: as pinned
  wrote android-sysroot/NOTICE.txt: as pinned
  recorded 35 file(s) in vendor/ANDROID-SYSROOT.sha256
  ```
- **Again:** `vendor/android-sysroot is there and as recorded (35 file(s) checked)`, and no request.
- **`--verify`:** `35 of 35 recorded Android sysroot file(s) unchanged`, exit 0.
- **A damaged tree repairs itself.** With one byte of `vendor/android-sysroot/usr/include/math.h` changed, the plain
  run prints `vendor/android-sysroot: android-sysroot/usr/include/math.h differs from the record; building it again
  from vendor/android-sysroot-src`, then the four lines above with no `fetching`, and `--verify` passes.
- **Offline.** With `vendor/android-sysroot` deleted, `--offline` prints the same four lines and no `fetching`
  (the cache is held to both pins as it is read, so the 44 line is printed).
- **Any folder.** `--vendor "build\r5\two, again"` (a space and a comma) builds a second tree with the same four
  lines, and `--verify --vendor "build\r5\two, again"` passes.
- **The check lists.** `--lists` prints two `fetching …?format=TEXT` lines, then
  `the 2 check lists (libc/libc.map.txt, libm/libm.map.txt) are as pinned`.
- **Upstream.** `--check-upstream` prints
  `47 of 47 pins are bionic's own blobs at 06356e41 (refs/tags/android-17.0.0_r1 is 06356e41)`.
- **The cache key.** `--cache-key` prints `key=<16 hex>`.
- **The tests.** `$env:PYTHONPATH='tools/citest'; python -m pytest -p noskip tools/tests/test_android_sysroot.py
  tools/tests/test_mingw.py -q`: the measured `N passed in Ts`, none skipped.
- **The arm64 crt objects, looked at** (CLAUDE.md's first bless; the gate ran x86_64 alone). Each own arm64 object
  and NDK r28c's API-33 `crtbegin_so.o` and `crtend_so.o` are compared with `llvm-readelf -S -s -r -n`. They have
  the same sections, symbols, bindings, visibility and relocations, and differ only in `.note.android.ident`'s
  descriptor (4 bytes here, 132 in the NDK's) and `.comment`. The diff goes in the commit message and FINDINGS. The
  x86_64 pins equal the gate's emulator-proven objects [V A.3].
- **On CI.** The `android-route` job is green on `ubuntu-latest` and on `windows-latest`. Both print the same
  `--verify` line, and both built the crt objects to the same pins: Ubuntu's llvm-mingw and Windows' make the same
  bytes (map §7.1 question 2). FINDINGS records the first fetch from each runner.

*Mutations* (each new check shown able to fail):
1. **A served file one byte off its pin** is refused by name, nothing written (check 2). **A blob id one digit off,
   the sha256 right,** is refused too (check 2).
2. **The server's answers** (checks 4-5): a 429 waits its `Retry-After`, in seconds or as an HTTP date, never more
   than 300 s; a 503 then a 200 is retried; a 200 whose gzip is cut short is retried as a transport failure, then
   given up in "broken or non-archive" words, never pin words; a `URLError` is retried, then "cannot reach"; the
   run's deadline gives up; a 404 is not retried.
3. **`--verify`** names a changed byte, a missing file and an unrecorded `usr/include/stdlib.h` (check 7).
4. **A record from another version of the script** is "not this script's" (check 8).
5. **A tree that is not as recorded** is rebuilt by a plain run from the cache, with `get` raising, so no request
   (check 6).
6. **The crt built with `-O0`** (`build_crt(extra=("-O0",))`) is refused, naming `crtbegin_so.o`; **a clang whose
   `--version` is clang 19's** is refused before anything is built (check 9).
7. **A stop inside the swap** (the rename patched to raise) leaves no record, and the next run rebuilds; a rename
   that raises `PermissionError` twice and then succeeds goes through; one that always raises ends in words, not a
   traceback (check 13).
8. **The NOTICE one byte off its pin** is refused by `build()` (check 10).
9. **The tool run with `python -I`** finds `soa.toolchain`; without its `sys.path` line the same run fails (check
   14).
10. **`CPATH` naming a folder whose `asm/unistd.h` holds `#error poisoned`:** the crt objects are still as pinned;
    without `clean_clang_env()` the build stops at the `#error` (check 15).
11. **`SOA_MINGW` naming a folder that holds `clang` but no `x86_64-w64-mingw32-clang`** gives no Android
    compiler, never the next place (test_mingw).
12. **CI on a scratch branch** (`gh workflow run ci.yml --ref <branch>`, built in a scratch worktree): one pin
    changed in the script turns the `android-route` job red at the sysroot step, on both systems, with the pin's
    words. The pin is part of the cache key, so the run restores the older cache by its prefix, finds that file off
    its new pin, and fetches it again.

*Emulator:* nothing new. The x86_64 crt objects equal those of the library the gate ran (FINDINGS:7739-7742).

*Owner:* nothing. The output pins are a first bless, checked as above, and the commit says how. The NOTICE's pin is
a first bless too: it is read whole before it is pinned, and the owner reads it in R5b.

#### Part 2: the route (one push)

*Done 2026-10-07 (FINDINGS "R5a part 2"), with what differed from this text recorded there.*

*Files:*
- `tools/soa/toolchain.py` (§4): the profiles; `ANDROID_NDK` and its two profiles; `is_android()`, `is_ndk()`,
  `android_sysroot()`; `compiler_path()`'s branches; `android_places()`; `compiler_id()`; `gnu_commands()` with the
  sysroot at the head on both of its paths; `cc()` with `clean_clang_env()` for Android.
- `tools/soa/seam.py` (§3): `C_LIBRARIES`, `BIONIC_LIBM`, `c_library_names()`, `stub_library_c()`,
  `stub_version_script()`, `write_android_stubs()`.
- `tools/soa/elfcheck.py`: `ANDROID_MACHINES`; `C_LIBRARIES` becomes `seam.C_LIBRARIES`.
- `tools/recompile.py` (§5):
  - `cc_choices()`, the `--cc` choices without the `-ndk` names;
  - `fetch_android_sysroot` imported inside the Android branch, so a defect in it cannot stop a Windows build;
  - for Android, before anything is read or written: the compiler, its identity and the sysroot, with
    `android_places()` when one is missing;
  - the stubs written at translation;
  - `write_build_inputs`, `check_build_inputs` (compiler, `cflags`, sysroot; strict for Android),
    `build_inputs_note` for a gnu record that names no compiler;
  - `android_link_plan` (the stubs, `-Xlinker`, `p.linker` on the stand-in, `needed`, `stubs=`);
  - `compile_units()`, `run_plan()`, `progress_label()` and `fail_reason()`, the call sites `main()` now uses;
  - `post_link_problems()`.
- `tools/fetch_android_sysroot.py`: `--compare` (§2.8), the header comparison, committed.
- `tools/soa/gamefixture.py`: `build()` through `recompile.android_link_plan`, its `target` keyword gone, the C
  stubs built once per profile and reused (§8.2); `arm32_library()`; `MACHINES = elfcheck.ANDROID_MACHINES`;
  `is_android()` in `android_mutants`; the docstrings.
- `tools/citest/compile_runtime.py`: refuses `android-arm64` and `android-x86_64`, naming the `-ndk` profile;
  compiles SDL with `is_ndk(prof)`; its docstring.
- `tools/android.py`: the docstrings and the `mutants` comment ("the NDK's builder" becomes "llvm-mingw's and the
  sysroot's").
- Tests (§8): `test_android_build.py`, `test_recompile_inputs.py`, `test_toolchain_profiles.py`, `test_citest.py`,
  `test_android_sysroot.py` (checks 11, 12 and 16), and `test_android_tool.py`'s fake gamefixture docstring.
- `.github/workflows/ci.yml` (§7): the `android-route` job also runs `test_android_build.py`; the gcc leg keeps
  only `compile_runtime.py --cc android-arm64-ndk`.
- Docs (§9): specs/android.md §3.4 rewritten and the §1.5-style corrections; TESTING; README; ARCHITECTURE;
  HANDOFF; PLAN-NEXT; CLAUDE.md; the check skill; FINDINGS.

*Done, on this PC* (`vendor/llvm-mingw` and `vendor/android-sysroot` present, the disc extracted):
- **Stale objects refused.** `python tools/recompile.py --cc android-x86_64 --link` over the NDK-built
  `gen/android-x86_64`, whose `build_inputs.txt` holds `dol_sha1` and `profile` alone, exits 1 with
  `gen\android-x86_64: its objects were compiled before build_inputs.txt named their compiler, flags and sysroot;
  run --compile again (stale link)`.
- **The x86_64 build.** `python tools/recompile.py --cc android-x86_64 --compile --optimize --link` prints, among
  its lines:
  ```
  compiled 19/19 units in <t>s
  linked gen\android-x86_64\stub\libc.so (<t>s)
  linked gen\android-x86_64\stub\libm.so (<t>s)
  linked gen\android-x86_64\stub\libdl.so (<t>s)
  linked gen\android-x86_64\stub\libsoa_runtime.so (<t>s)
  linked gen\android-x86_64\libsoa_game.so (<t>s)
  checked gen\android-x86_64\libsoa_game.so: the phone's runtime would load it
  ```
  The 19 units are 18 chunks and `dispatch.c`. `gen\android-x86_64\build_inputs.txt` then has five lines:
  `dol_sha1`, `profile`,
  `compiler = clang version 23.1.2 (https://github.com/llvm/llvm-project.git 85ac560262434c9ccfc0c183ec22d4138ed647fb)`,
  `cflags = <sha256 of the profile's compile flags>` and `sysroot = <sysroot_digest(vendor)>`.
- **The arm64 build** is the same with `--cc android-arm64`. **Two builds are one:** a second arm64 build with
  `--out build\r5\arm64-b` has the same sha256.
- **No compiler or no sysroot, and the build says where it looked, before it reads anything.** With
  `$env:SOA_MINGW='C:\no-such-mingw'`, `python tools/recompile.py --cc android-arm64 --compile` exits 1 within a
  second and prints exactly:
  ```

  android-arm64: no compiler or no sysroot here, so nothing was built
  the game library for Android is built by llvm-mingw's clang against this repository's own sysroot; looked in, in order:
    SOA_MINGW (C:\no-such-mingw): no llvm-mingw there (no x86_64-w64-mingw32-clang.exe)
    C:\Users\bmfre\Documents\Github\SOA\vendor\android-sysroot: there
  ```
  With `SOA_MINGW` unset and `vendor\android-sysroot` renamed away, the looked-in lines are:
  ```
    SOA_MINGW (unset)
    C:\Users\bmfre\Documents\Github\toolchain\bin: no llvm-mingw there (no x86_64-w64-mingw32-clang.exe)
    C:\Users\bmfre\Documents\Github\SOA\vendor\llvm-mingw\bin: llvm-mingw's clang 23.1.2 (85ac5602)
    C:\Users\bmfre\Documents\Github\SOA\vendor\android-sysroot: none (python tools/fetch_android_sysroot.py builds it)
  ```
  The same with `--link` alone, over a `gen/` whose record names a compiler, prints these lines and never the
  stale-link words.
- **The runtime check keeps the NDK.**
  - `python tools/citest/compile_runtime.py --cc android-arm64-ndk --require-gxv --require-sdl` and
    `--cc android-x86_64-ndk` each end with their `compiled N/N runtime translation units` line, N measured.
  - `--cc android-arm64` exits 1 with
    `the runtime is the APK's, compiled by the NDK: --cc android-arm64-ndk; --cc android-arm64 builds the game library (tools/recompile.py)`.
- **The headers change no object.** `python tools/fetch_android_sysroot.py --compare --gen gen/android-x86_64 --cc
  android-x86_64` prints `19 of 19 objects identical against <the NDK's sysroot> (android-x86_64, -O2)`; the same
  for arm64. The reference is NDK r28c's sysroot, which `toolchain.android_ndk()` finds here.
- **The tests.** `$env:SOA_CC='msvc'; $env:PYTHONPATH='tools/citest'; python -m pytest -p noskip
  tools/tests/test_android_build.py tools/tests/test_android_sysroot.py tools/tests/test_toolchain_profiles.py
  tools/tests/test_citest.py tools/tests/test_recompile_inputs.py -q`: the measured `N passed in Ts`, none
  skipped. FINDINGS gives `test_android_build.py`'s time before and after, to show what reusing the stubs saves.
- **The timing.** FINDINGS records the compile time for each ABI on 16 threads, the PC quiet. The gate measured
  38.9 s for 21 units and a 0.3 s link [V FINDINGS:7734]; L12b's NDK build took 50 s for 19 [V map §1.3].
- **The seam row (CLAUDE.md), since `seam.py` changes.** In a Linux container:
  `python tools/recompile.py --cc gcc --split --compile --optimize --link`; on `gen/linux-split/soa` the self test
  (`[selftest] 0 failure(s)`), `python tools/scenario.py replay` 23/23, and `python tools/scenario.py run title
  --check` (4 of 4); then `python -m pytest -p noskip tools/tests/test_seam.py`, its measured count, none skipped.

*Mutations:*
1. **L12b's refusals, through the new route.** `-z max-page-size=4096` and `-fvisibility=default` each draw their
   refusal (test_android_build's MUTANTS).
2. **A call outside the seam fails on the PC.** `strlen` in the fixture fails the link with
   `undefined symbol: strlen`. With a `strlen` stub added, it would link, and the test fails.
3. **A Linux SONAME is refused.** The fixture with `needed=("libc.so.6",)` is refused by `post_link_problems` as
   "built for Linux (it needs libc.so.6)". With `android=False` there, it passes, and the test fails.
4. **Objects from another compiler, other flags or another sysroot** are refused by `--link` (unit tests). So is an
   Android record with none of those fields, and an Android `gen/` with no record. A mingw record that names no
   compiler passes, with `build_inputs_note`'s note naming it; with the note's new branch taken out, its test fails.
5. **The stand-in without `p.linker`:** the plan test fails, and the real link asks for `libclang_rt.builtins.a`.
6. **The machine by identity.** `prof is ANDROID_ARM64`, with a `dataclasses.replace`d arm64 profile, makes the
   post-link check name x86-64, and the test fails.
7. **A FAIL line from stdout alone,** at `compile_units`' call site, carries no reason for clang's error, and its
   test fails. **The old label loop** in `run_plan` labels every stub `decompiled units`, and its test fails.
8. **`gamefixture` with its own copy of the plan:** the spy test fails.
9. **`compile_runtime` accepting `--cc android-arm64`** fails `test_citest`'s case.
10. **The game library's compiler lookup consulting the NDK** (`android_ndk` patched to raise) fails.
11. **The closure.** A test copy of `cpu.h` with `#include <stdlib.h>` fails the closure test, naming `stdlib.h`. A
    `SHIP` entry that no compile reads is named unused.
12. **Bionic's placement.** `seam.BIONIC_LIBM` without `sqrt` fails the placement test, naming `sqrt`; so does a
    seam name bionic does not define (a test copy with `fmaa`).
13. **The version script through `-Wl,`:** the fixture built in a folder whose name holds a comma and a space fails
    to link (`cannot find version script`), and its test fails.
14. **The stubs' environment.** `CPATH` naming a folder whose `math.h` holds `#error poisoned` changes nothing;
    with `cc()`'s clean environment taken out, the build stops at the `#error`.
15. **`--compare` reporting every object identical:** its test, whose second sysroot's `math.h` ends with
    `#define sqrt(x) ((x) * 2.0)`, fails.
16. **CI on a scratch branch.** A `seam.txt` without `__cxa_atexit` turns the `android-route` job red on both
    systems at `test_the_library_is_what_the_phone_loads`, with `undefined symbol: __cxa_atexit`: the job runs the
    route with no skips.

*Emulator* (the AVD `soa_x86_64` on 5556 alone, one `soa` run at a time,
`$env:SOA_ADB_SERIAL='emulator-5556'`). The real route, `recompile.py` itself, which the gate did not run
(FINDINGS:7751-7752):
```
python tools/recompile.py --cc android-x86_64 --compile --optimize --link
python tools/android.py build
python tools/guard.py --apk android/app/build/outputs/apk/debug/app-debug.apk
python tools/android.py install
python tools/android.py push-game
python tools/android.py selftest
python tools/android.py replay --threads 1,2,3,8
python tools/android.py run --timeout 900 --env SOA_IMPORT=1 --env SOA_RENDER=1 --env SOA_FRAMES=2000 --env SOA_SNAP=50 --env SOA_STRICT=1 --env SOA_SETTINGS=0 --env SOA_PAD=1600:start,1640:a > build/android-title.log
python tools/scenario.py check build/android-title.log --name title
python tools/android.py mutants --profile android-x86_64 --push
python tools/android.py stage gen/android-x86_64/libsoa_game.so
python tools/android.py player --timeout 900 --fresh --tap Pick --tap libsoa_game.so --tap Pick --tap GEAE8P.soadisc --out build/android-player/r5a
```

What each must show:
- **The self test:** `[game] …: abi=1 mode=no-decomp baked=<the tree's> dol=<config's> profile=android-x86_64`,
  then `[selftest] 0 failure(s)` and `[exit] 0`.
- **The replay:** `[android] 23 captures match config/fifo_manifest.tsv at SOA_THREADS 1,2,3,8 on emulator-5556`.
- **The title:** `title: 4 of 4 invariants hold`.
- **The mutants:** each of the ten draws its printed line through
  `run --env SOA_IMPORT=library --env SOA_SETTINGS=0 --pick content://io.github.bmfrench89.soa.dev.testfiles/file/<name>.so`,
  `arm32.so`, now made `-nostdlib`, among them:
  `[import] refused arm32.so: this library was built for 32-bit ARM, not this device (x86-64): rebuild it for this device with Setup`.
- **The player's path:** `build/android-player/r5a`'s `soa.log` holds the 34 MB copy and install of
  `libsoa_game.so`, `GEAE8P.soadisc` read in place, `[import] wrote …/files/soa.ini: render = 1`,
  `[settings] … 1 setting(s) applied` and `[window] open at 2x`, as L12d's did (FINDINGS "L12d"); its `[game]`
  line names this build's `baked=`. The capture 30 s after the last step shows the opening's logo, looked at.

**Not on the emulator:** arm64. Its first device is the Thor (§1.4); `push-game` holds that library to the APK's
record before the session (R5b).

*Owner:* nothing.

### 1.2 R5b. The player's build and the package

**Purpose.** A player's package builds the phone's library offline with what it carries:
- `player_build.py --target android-arm64`;
- `--target android-x86_64`, for the emulator.

The package carries bionic's 44 pinned files and the sysroot's licences. The player's PC builds the sysroot from
those files on its first Android build (D-34).

*Files:*
- `tools/player_build.py` (§6.1):
  - `TARGETS`, a repeatable `--target`;
  - `package_version()`, `identity(target)` (package, compiler, cflags, and for Android the sysroot);
  - `android_preflight()`, run right after the disc check: the sources or the tree, the compiler and its
    identity, and the space, each refused in player words with nothing written;
  - the sysroot ensured from the package's sources (`[build] android sysroot`);
  - the per-target gen folder; `build()` gains `target`; `install_android()`;
  - `ANDROID_FREE` and `RELINK_FREE`;
  - the `android ` line prefix; the exit codes; words in a package that are not a developer's.
- `tools/soa/seam.py`: `record()` gains `made_by`.
- `tools/recompile.py`: the record's `package=`, `cc=` and `sysroot=` for Android, each value cut at 64 characters
  (§5.7).
- `tools/fetch_android_sysroot.py`: `stage_sources(cache, dest)` and `longest_written()` (§2.9).
- `tools/package.py` (§6.2):
  - `TOOLS` gains `fetch_android_sysroot.py`;
  - `stage(dest, ver)`, `stage_source(source, ver)` (it writes `source/VERSION`), `stage_vendor()` (it adds the
    44 sources);
  - `licenses()`: `android-sysroot.txt` generated from the sources and held to the NOTICE's pin;
    `linux-gpl-2.0.txt` and `linux-syscall-note.txt` in `LICENSE_URLS`; every fetch through the tool's `fetch()`;
  - `check` also holds `source/VERSION` to the version in the package folder's name;
  - `deepest()`'s floor, `BUILD_DEEPEST`, computed from the build's own outputs (§6.2);
  - `build_zip()` passes `ver`.
- `tools/setup/setup.c`: `PACKAGE` gains `source\vendor\android-sysroot-src\libc\arch-common\bionic\crtbegin_so.c`
  (§6.3).
- `tools/android.py`: `push-game` holds the library to the record and exports the APK was built with, before it
  pushes (§6.6).
- `tools/guard.py`: `forbidden_dir()` refuses a folder named `gen-…` as it refuses `gen` (§6.5).
- `.gitignore`: `gen-*/`, `*.so` and `*.apk`.
- `.github/workflows/release.yml` (§7.3).
- Tests: `test_player_build.py`, `test_package.py`, `test_setup.py`, `test_android_build.py` (the record's fields),
  `test_android_tool.py` (push-game's check), `test_guard.py` (the `gen-` rule), `test_android_sysroot.py` (check
  18, the staging and the paths).
- Docs: distribution.md R5, §3.6-3.8; android.md §3.4's player bullet; TESTING's R2 and R3 recipes and rows;
  README's player section; CLAUDE.md's guard sentence ("49 extensions, 18 directory names") and its copy in
  ci.yml's comment; HANDOFF, PLAN-NEXT (D-34's row gains the reading), FINDINGS.

*Done, on this PC:*
- **The tests.** `python -m pytest -p noskip tools/tests/test_package.py tools/tests/test_player_build.py
  tools/tests/test_setup.py tools/tests/test_android_tool.py tools/tests/test_guard.py -q`: the measured
  `N passed in Ts`, none skipped.
- **The package.** `python tools/package.py stage build\r5b\P` prints `staged …\build\r5b\P`, and in `P`:
  - `source\vendor\android-sysroot-src\` holds exactly the 44 build and ship files, and no `.map.txt`;
  - `source\VERSION` holds `git describe`'s answer;
  - `licenses\` holds `android-sysroot.txt`, `linux-gpl-2.0.txt` and `linux-syscall-note.txt`;
  - `python tools\guard.py --tree build\r5b\P` passes;
  - `python tools\package.py check build\r5b\P` passes.
- **The player's sysroot, built from the package.** With R2's bare `PATH`:
  `P\python\python.exe P\source\tools\fetch_android_sysroot.py --offline` prints the four lines of R5a part 1's
  first build (no `fetching`), and `--verify` passes. FINDINGS records its time.
- **The emulator's library from the package:**
  `P\python\python.exe P\source\tools\player_build.py --disc <the owner's image> --root build\r5b\R --target android-x86_64`
  ends `[build] android done libsoa_game-x86_64.so sha256 <hex>`, exit 0.
- **The phone's library from the package.** The same with `--target android-arm64` ends
  `[build] android done libsoa_game.so sha256 <hex>`.
  - A second root, `build\r5b\R2`, gives the same hex: distribution §3.8's reproducibility, for the library.
  - FINDINGS records the wall time; the translation's time and the C's size, for the cost of separate gen folders
    (§0.1); and the peak drop in free space, from which `ANDROID_FREE` is set.
- **Both targets in one run.** `--target windows --target android-arm64` over `build\r5b\R`:
  - Windows translates, since `R\gen` has no record (`[build] translate: no record of the last translation`), and
    ends `[build] done soa.exe sha256 …`;
  - Android only relinks: no `[build] android translate: …` line, and it ends
    `[build] android done libsoa_game.so sha256 <the same hex>`;
  - the same command with `--rebuild` translates both.
- **The release, downloaded.** `gh workflow run release.yml --ref <branch>` drafts a release whose package passes
  the workflow's new steps (§7.3); its size is printed. Then, as R3's Done did:
  - the draft's zip, downloaded into `build\r5b\ci` (its sha256 the draft's), is extracted to `build\r5b\ci\Z`;
  - `Z\python\python.exe Z\source\tools\player_build.py --disc <the image> --root build\r5b\ci\R --target
    android-x86_64` ends with the same `libsoa_game-x86_64.so` hex as the package staged here from the same
    clean commit, whose `VERSION` is the same;
  - that library passes the emulator's checks below with an APK built here from the same commit.

  The draft is then deleted (`gh release delete <tag> --yes`): the owner publishes only real ones (Q-D4).
- **The seam row (CLAUDE.md), since `seam.record` changes:** the container session of R5a part 2 again, its lines
  the same.

*Mutations:*
1. **`stage_vendor` staging the sources with `copy_tree`:** `libc/include` is dropped (package.py:83, :135), and
   the staging test fails.
2. **`stage_vendor` copying the whole cache:** the two `.map.txt` lists and `linux/version.h` go into the package,
   and the staging test fails; `guard --tree` refuses the lists (guard.py:50).
3. **The record without `package`, `compiler`, `cflags` or `sysroot`:** a change to that one only relinks, and its
   test fails.
4. **One shipped source a byte off, and no tree yet:** `player_build --target android-arm64` prints
   `[build] android failed: this package's Android files are not as it shipped them (libc/include/math.h): extract
   the package again, into a new folder`, exit 1, after `[build] check` and before `[build] extract`; nothing
   under the root. **The tree a byte off, the sources whole:** `[build] android sysroot`, and the build goes on.
5. **Too little space** (`shutil.disk_usage` patched): refused in §6.1's words, exit 1, before `[build] extract`,
   nothing written.
6. **The sources staged outside `source/vendor`** (`source/android-sysroot-src`): `guard --tree` refuses their
   `include/` (guard.py:524-527).
7. **A release branch whose `package.py` stages no sources:** the workflow fails at `Setup.exe --check`
   (`CHECK_INCOMPLETE`, naming the sentinel), before any draft. A scratch branch:
   `gh workflow run release.yml --ref <branch>`.
8. **The 64-character cut taken out:** a 600-character `VERSION` gives a 600-character `package=`, and the
   record-bounds test fails.
9. **`push-game` without its check:** a Windows file named as the library is pushed, and its test fails.
10. **`forbidden_dir` without the `gen-` rule:** `test_guard`'s `gen-android-arm64/chunk_001.c` case fails.

*Emulator:* the package's artifacts, after `android.py build` and `install` (`baked=` moved again):
- `python tools/android.py push-game build\r5b\R\libsoa_game-x86_64.so`, which first prints
  `checked …\libsoa_game-x86_64.so against the app this PC built: ok`;
- the self test, the replay and the title as in R5a, with the same lines; `[game]`'s record now ends
  `package=<version> cc=clang-23.1.2 sysroot=<12 hex>`;
- **the path Setup's words will describe:** `python tools/android.py stage build\r5b\R\libsoa_game-x86_64.so` and
  `stage build\r5b\R\extracted\disc.iso` (when `stage` says the AVD lacks room, the staged `GEAE8P.soadisc` is
  removed from Download first), then
  `python tools/android.py player --timeout 900 --fresh --tap Pick --tap libsoa_game-x86_64.so --tap Pick --tap disc.iso --out build/android-player/r5b`,
  with the same lines as R5a's player run and `disc.iso` read in place;
- the same three checks with the library from the downloaded CI zip (above).

*Owner:*
1. **The licence texts' look.** `licenses/android-sysroot.txt` (the generated NOTICE), `linux-gpl-2.0.txt` and
   `linux-syscall-note.txt`, and the NOTICE's pointer to `licenses/llvm.txt` for the Apache License 2.0. A local
   review page, `build/r5-licences/index.html` (never committed), lists each shipped file, its class (§2.5) and its
   words. D-35 answered that they ship with their texts; this is the first look at what the package carries.
2. **How this design read D-34**, one line: "Your PC builds the phone's sysroot itself, from bionic's 44 files the
   package carries, in a few seconds and offline, the first time it builds for Android. Nothing built from them is
   published. Say if you meant that only developers' and CI's machines build it." Either answer keeps the player
   offline; the other reading is the draft's (ship the built tree), a one-slice change.
3. **The draft release** is deleted, not published.

### 1.3 R5c. Setup's checkbox and words

**Purpose.** A player ticks one box. Setup then builds `soa.exe` and `libsoa_game.so` in one run, with one progress
bar, and says plainly how to put the library and the disc on the phone.

*Files:*
- `tools/setup/setup.c`:
  - `ID_ANDROID`, a checkbox under the disc row (the controls below move down one row, the window grows by it);
    `g_android`;
  - `--android`, which ticks it with no hands;
  - `--show-build`, which prints the command line Build would start and exits 0;
  - `--bar [--android] [--exit N]`, which reads `[build]` lines from stdin, prints the bar's position for each, and
    at the end the status `on_done` would show for exit code N: the test's window onto both;
  - `--assume-free <bytes>`, honoured with `--check` alone: the free space the checks see, for the test;
  - `start_build()` appends `--target windows --target android-arm64` when ticked;
  - `bar_position()`: the two-phase map;
  - `on_line()`, which notes this run's `[build] extract`, `[build] done soa.exe`, `[build] android done` and
    `[build] android failed: <why>`; `on_done()`, which chooses the status from those notes, never from
    `built()`;
  - `ANDROID_FREE`, mirrored from `player_build.py`, and the space rule;
  - the words.
- `tools/tests/test_setup.py`.
- `.github/workflows/release.yml`: `Setup.exe --check --android` beside `--check`.
- Docs: distribution.md R4 and R5 notes (the release gate below), README's player section, TESTING's R4 recipe,
  FINDINGS.

*The behaviour:*
- **The checkbox:** "Also build the game for an Android phone or handheld (64-bit ARM)". Off by default, unless the
  owner says otherwise (question 2).
- **The bar.** When it is ticked, the Windows lines map to 0-60, and the `[build] android …` lines to 60-100, the
  prefix taken off before the same parse (`sysroot` 61, `translate` 64, `n/m` 66-94, `stub …` 95, `link` 96,
  `done` 100). The Windows `done` puts it at 60. The split is set by measurement on the Ally X.
- **Space.** The need is `(built() ? 0 : NEED_FREE) + (ticked && no <root>\libsoa_game.so ? ANDROID_FREE : 0)`.
  It is checked when the window opens, when the box is ticked, when Build or Rebuild is pressed with it ticked, and
  by `--check --android`. `player_build`'s preflight checks again, with the gen folders' sizes counted (§6.1).
- **The status** comes from this run's lines:

  | Exit | This run's lines | Status |
  |---|---|---|
  | 0 | `done soa.exe`, and `android done` when ticked | the built words |
  | 0 | no `done soa.exe` | today's "finished, but soa.exe is not in this folder" (Windows Security) |
  | 2 | — | today's disc refusal |
  | 1 | `android failed: <why>` before `extract` | the Android-cannot-start words, with `<why>` |
  | 1 | `done soa.exe`, then `android failed: <why>` | the Windows-built, Android-not words, with `<why>` |
  | 1 | anything else | today's "The build stopped" words |

- **The words** are drafts, under CLAUDE.md's first-bless rule, and do not say where the app comes from: no release
  carries an APK until D-33.
  - built: "The game is built. Press Play to play here.\r\nFor your Android device: copy libsoa_game.so and
    extracted\disc.iso from this folder to it, then open the SoA port app and pick each when it asks,
    libsoa_game.so first."
  - Windows built, Android not: "soa.exe is built: press Play to play here. The Android build stopped: <why>"
    (with no `<why>`: "its log is below, and saved as <root>\build\setup.log: send that file with any report").
  - Android cannot start: "Nothing was built: <why>\r\nUntick the Android box to build for Windows alone."
  - space: "The game and its Android build need about <n> GB free here, and this drive has <m> GB. Free some
    space, untick the Android box, or move the whole folder to another drive."
- **The release gate.** distribution.md's R5 records that no release whose Setup shows the box is published before
  the release APK exists (D-33); the words then gain where the app comes from. The owner publishes every release
  (Q-D4), so the gate is the owner's, and the look below asks it.

*Done, on this PC:*
- **The command line.** In a package `P` staged after this slice, `P\Setup.exe --show-build --disc <image>
  --android` prints a line ending `--target windows --target android-arm64`; without `--android`, it has no
  `--target`.
- **The bar.** `Get-Content <a recorded two-target log> | P\Setup.exe --bar --android --exit 0` prints positions
  that never go down, pass 60 at the Windows `done` and end at 100, then the built words.
- **The status, from recorded logs** (`test_setup.py`, each exit code of the table).
- **A real run.** `P\Setup.exe --disc <image> --build --android` builds into `P`, and the window ends with the built
  words.
  - `P\libsoa_game.so` has the sha256 of `P\python\python.exe P\source\tools\player_build.py --disc <image>
    --root build\r5c\R2 --target android-arm64` from the same `P`. (Not R5b's: this slice stages a new package,
    whose `VERSION`, and so whose `package=`, differs.)
  - Captures of the window at 100% and at 150% scale, and the log, go on the review page. Where the built words do
    not fit the status box at either scale, the box grows by a line, and the capture is taken again.
- **The tests.** `python -m pytest -p noskip tools/tests/test_setup.py -q`: the measured `N passed in Ts`, none
  skipped.

*Mutations:*
1. **`start_build` ignoring the box:** `--show-build --android` lacks the targets, and the test fails.
2. **`bar_position` without the phase map:** the positions fall back after `done soa.exe`, and the test fails.
3. **`on_done` by `built()`:** a recorded log whose Windows build failed over an existing `soa.exe` shows the built
   words, and the test fails.
4. **The space rule ignoring the box once `soa.exe` is built:** `--check --android --assume-free <1 GB>` in a built
   folder passes where it must be `SPACE`, and the test fails.

*Emulator:* none. Setup builds arm64 only; the Thor runs it (§1.4).

*Owner:*
1. **The first bless of the words.** The checkbox label, the four statuses and the space refusal, on a local review
   page `build/setup-review/index.html` with the captures at both scales. Until then they are drafts, as L12d's are.
2. **Is the box off by default?** The proposal is off: most players have no Android device [I].
3. **The disc's file on the phone, with the phone's own prompt.** Setup's words name `extracted\disc.iso`, which
   every build makes. The phone's `DISC_PROMPT` calls the store `GEAE8P.soadisc` "the better choice", since it can
   tell when a copy is damaged (runtime/android.c:182-185). Either Setup also makes the store (`extract.py
   --store`, about 1.4 GB more), or the prompt names the image Setup made first. The proposal is the second, a
   change to `android.c` in L12's own slices; both are drafts the owner blesses together.
4. **The release gate:** no published release shows the box before the release APK (D-33). The proposal is yes.
5. **The Ally X run:** the owner's R4 run, with the box ticked.

### 1.4 After R5: L12's Done on the Thor (D-36)

- **The library:** either R5c's `libsoa_game.so`, made by Setup with the box ticked on the Ally X, or R5b's, from
  `player_build --target android-arm64` in a staged package. The proposal is Setup's: it is the player's whole
  path, and its sysroot is built on the Ally X from the package's sources.
- **The APK:** `android.py build` from the same commit, then `install --serial <the Thor>`.
- **Before the session:** `python tools/android.py push-game <root>\libsoa_game.so --serial <the Thor>` holds the
  library to the record and exports the APK was built with, for the Thor's machine, and refuses in the phone's words
  when they disagree (R5b). A `baked=` that differs is then found on the PC, not in the session. If wanted, the
  arm64 library can be tried first on the AVD, with the debug APK installed for arm64-v8a under the system image's
  ARM translation [I: Google's x86_64 images from API 30 translate ARM apps]; not a gate.
- **The checks:** android.md's L12 Done lines.
- **What this proves:** the first arm64 library built by llvm-mingw, with RELR, AOSP-built crt objects and seam stubs,
  on a device (§10).

---

## 2. The fetch-and-build tool: `tools/fetch_android_sysroot.py`

The standard library and `soa.toolchain` alone, since `recompile.py`, `player_build.py` and `package.py` import it,
and in a package it runs on the embeddable CPython. Its first lines insert its own folder into `sys.path`, as
recompile.py:46, player_build.py:42 and package.py:41 do: the embeddable CPython's `._pth` file adds no script folder,
so without it a run as a script cannot import `soa` [V: the `._pth` holds `python314.zip` and `.`; the reviewer's
probe `r5/review_probe/emb`]. It never imports `fetch_mingw`, which a package does not carry; the llvm-mingw release
it names is `toolchain.MINGW_RELEASE`.

### 2.1 What it makes, and where

| Path, under `<vendor>` | What | In a package | Recorded |
|---|---|---|---|
| `android-sysroot-src/libc/…`, `libm/…` | **the source cache**: the pinned files in bionic's own layout, each held to both its pins whenever it is read | the 44 build and ship files, staged from the cache and held to their pins (§2.9) | no |
| `android-sysroot/usr/include/…` | the 30 headers, unmodified, in the NDK's layout | built on the player's PC | yes |
| `android-sysroot/usr/lib/aarch64-linux-android/33/crtbegin_so.o`, `crtend_so.o`, and the same for `x86_64-linux-android` | built from the sources | built on the player's PC | yes |
| `android-sysroot/NOTICE.txt` | every source file's own licence words (§2.5) | built on the player's PC; and at staging, as `licenses/android-sysroot.txt` | yes |
| `ANDROID-SYSROOT.sha256` | the record (§2.6) | written on the player's PC | — |

- **Sizes.** The 44 sources are 151,273 B [V design_probe.json]. The tree is 34 files and 115,602 B before
  `NOTICE.txt` [V A.3].
- **The deepest path** a package holds is `source/vendor/android-sysroot-src/libc/kernel/uapi/asm-x86/asm/posix_types_64.h`,
  79 characters. The deepest the tool writes there is the same header under `android-sysroot.new/usr/include/`, 87
  characters; the tree's own is 83. Both are under today's 90 (`SETUP_DEEPEST`, setup.c:56-62), and
  `package.deepest()` now counts them (§6.2).
- **No name holds `.map`,** so guard.py:50's trap is never met in the tree or a package: the stubs' version scripts
  are `*.vers` (§3), and bionic's two `.map.txt` lists stay in a checkout's cache, which is gitignored (`vendor/`) and
  never staged.

### 2.2 The pins

**The commit.** `COMMIT = "06356e41c5ed7b12220b24c05ba4fdb873b126a7"`, `TAG = "android-17.0.0_r1"` (tag object
`7eb60ba263fcba76b9a227530781f74ae84d3515`), `BASE = "https://android.googlesource.com/platform/bionic"`.

**What each pin was checked against.** Every sha256 is from the scratch copy at the commit (`src/bionic`), and every
blob id equals gitiles' own tree listing at `COMMIT`: 47 of 47 [V A.2; `linux/version.h` checked for this design
against `design_upstream.json`'s listing of `libc/kernel/uapi/linux`]. `SHIP` maps each shipped file to its place:
- `libc/include/X` goes to `usr/include/X`;
- `libc/kernel/uapi/{linux,asm-generic}/X` goes to `usr/include/{linux,asm-generic}/X`;
- `libc/kernel/uapi/asm-arm64/asm/X` goes to `usr/include/aarch64-linux-android/asm/X`;
- `libc/kernel/uapi/asm-x86/asm/X` goes to `usr/include/x86_64-linux-android/asm/X`.

**The roles.**
- **ship:** in the tree.
- **build:** read only while building the crt objects.
- **check:** read only by tests: the two symbol lists by check 12, `linux/version.h` by the kernel licence test
  (§8.2). A build never needs them, so a package carries none.

| Path in bionic | Bytes | Role | ABI | sha256 | git blob |
|---|---|---|---|---|---|
| `libc/arch-common/bionic/__dso_handle_so.h` | 1,930 | build | both | `50b6bbb9aaa1692175e45839c0b90810a962449d0b9842960caf8119595bdc32` | `2c0df7bc74cdf364ac7527a4a15322300083502f` |
| `libc/arch-common/bionic/atexit.h` | 1,797 | build | both | `8671df24f92b375fe8ff233e88d5b55f01e91c608ee838045431444101bf70af` | `90aa030eafcfc7c7a47585d40c6f927e5d1d3e73` |
| `libc/arch-common/bionic/crtbegin_so.c` | 2,936 | build | both | `7339e128550f8f90a254fef776c8a23b96a13190e93981cb20a588a2e6342bf3` | `2f3b1189075191332b841e0954f1faa7b140fdfb` |
| `libc/arch-common/bionic/crtbrand.S` | 1,942 | build | both | `27f3d6eda81ba614020871c8cc46fa0e92d9900413f38469fdb2081715cb3bb5` | `26b973fecbbf1bdd0dd1353452e91e1c6a2c3bdb` |
| `libc/arch-common/bionic/crtend_so.S` | 1,668 | build | both | `bb9e63f580f756b7cddb5a36e53c2545df7bcea681a248c647f090ee2c05ef29` | `1e0a3943eba46d49539ab797e1675cfb8dce72fa` |
| `libc/arch-common/bionic/pthread_atfork.h` | 1,327 | build | both | `bdc11ac701a0847a51a7e93760bb0fe12389b8d25b36080f1e0d1fb7ba07e2b1` | `02e383d31f8f41c666be50082494830b95a3b555` |
| `libc/include/android/api-level.h` | 7,953 | ship | both | `31fee93a32b3bfce3a8f2eef90b578a940081c0956cbe66468dc8ff43015f7bc` | `2965bb58005c143411bf0106bd826e190fb404ae` |
| `libc/include/android/versioning.h` | 4,020 | ship | both | `e89f59dda1cb8e1dd37575e24c8f928f697c776b1bfe0e0bb607da4f931e5bbc` | `1cf6e5107ea09e43400b51d0bd562a09b2a696aa` |
| `libc/include/bits/posix_limits.h` | 9,168 | ship | both | `d1c3d19e43a95185144caf7a8b2372cf9a88b67a5b254e3947521e461a19b1d5` | `2cb91ff46df9fde5b3977a723e2fc87aa0503a1a` |
| `libc/include/bits/pthread_types.h` | 2,556 | ship | both | `a383b92a43cef5cd43b36ec965f7b33dbd14bab51b447ce4d3783cda8e2a6de7` | `f0ab2a6fae53142c0f094a6d48b89165a0d7f4b7` |
| `libc/include/bits/strcasecmp.h` | 2,911 | ship | both | `43e9619daee9abcd034362846e5522acfad8df388f70e20d6cd802d74b00c001` | `c5bdae16405f16c808634e2c498278bfdcd63838` |
| `libc/include/bits/wchar_limits.h` | 1,856 | ship | both | `8b0309028526bde5d40be47ef28d40aa4463b79322340e0a1ebd83a094eeff8f` | `eb2271382479c3cd6019177e177cea10fed4ae4b` |
| `libc/include/limits.h` | 5,100 | ship | both | `ea2234585f42e2b0f0cba2babb72eb0077139d8ab38f464b5659a45b127e04d2` | `a8ff2cbc53fbc367a67e76f275d85fd49408f0e9` |
| `libc/include/math.h` | 13,179 | ship | both | `e50651fab9321e622d899d48dc3c30113f3d11f65a97775253c543afec8aaa10` | `0d0394026354e1b4491403b1ecce1ad51795853b` |
| `libc/include/setjmp.h` | 4,950 | ship | both | `fe68fb9043c92ef91acb174d2f3b71d41fc4814b3434d75df3b589eb190345f9` | `0236fe6e821483cb802992590c081de9c8659b3f` |
| `libc/include/stdint.h` | 7,439 | ship | both | `c37028b9bf6b76e9ebe4d2c6ca2cd3bc280b57d9d2593da3bbf2888d9966c3f4` | `1e228fa559110459c537aa19504a36e7653a0087` |
| `libc/include/string.h` | 15,340 | ship | both | `a8fad67dad381339e4f47a711f962f2d9e97a9d7d5878dd2637f0319ad9451a3` | `06793c34e8b431f273476736f963655073de88e6` |
| `libc/include/strings.h` | 3,747 | ship | both | `3fd37db73727cabb576562e9bfa2cdbd59a7659a832619dac8e5f43137ad8668` | `7543edca533675c3837bad031ae6a9663675b051` |
| `libc/include/sys/cdefs.h` | 14,297 | ship | both | `e5c5aad8f5a5d28ec6d8741e7672ba091977c9f281fddce6e4310960ad8c15cd` | `bd57ef035128cda273c1e0bdbf8a351fa5ad04d0` |
| `libc/include/sys/types.h` | 4,980 | ship | both | `dbf62d44925a1b5265be69234de54e6022d58e5fde835a7573bf1964bde9b235` | `dcb0e58589c887d46c520c18da01e1f21ddc0579` |
| `libc/include/xlocale.h` | 1,987 | ship | both | `0ca127f21e39067cb1c5f272adeea80a4c0110158023f6a321600f8c85292ec0` | `aa1cefd5c1d33749926ed70ba3365c9c62548bc1` |
| `libc/kernel/uapi/asm-arm64/asm/bitsperlong.h` | 300 | ship | arm64 | `e17e530bc6dc93aa7fe66ec8c176e86487b8eb14e80255531c04cc9808513053` | `312224c20ff2a38a5c989b08b5952651c6477c2b` |
| `libc/kernel/uapi/asm-arm64/asm/posix_types.h` | 405 | ship | arm64 | `54c9c13ed0a1894336d70abb439bcd182a19c04396a05e379f217f0ff5eb132f` | `00df90d44aeb7f09a7b5e0e90b89bbee8f1de0ac` |
| `libc/kernel/uapi/asm-arm64/asm/types.h` | 204 | ship | arm64 | `4b8d02254d1d5ee1b7eb6ee962a63a935330799c14eaf07f93698c2cf8e59e2a` | `a030be86d321b3e51c78cb0f18085d2145682427` |
| `libc/kernel/uapi/asm-arm64/asm/unistd.h` | 200 | build | arm64 | `4da7ddf17f9f2c986e2aeffba0c3247ac7984dd96ef1120996db176b78f88d23` | `178578fdf907905542639789661c76cc7c68e9dc` |
| `libc/kernel/uapi/asm-arm64/asm/unistd_64.h` | 9,086 | build | arm64 | `7e830959a08125428f0b1b870dc9bb39a04f74ef7c2ef89c55dfb8c0e4857b37` | `41b77d7d8dd38467c3ef80fbde334890f068d8a5` |
| `libc/kernel/uapi/asm-generic/bitsperlong.h` | 512 | ship | both | `363e0abd35c267c94d736d8bb04af196fa4f8e5959d26fe1be9b041adb3f154b` | `11dcc1a11f197028d168fcc9fb907975f4a8a873` |
| `libc/kernel/uapi/asm-generic/int-ll64.h` | 686 | ship | both | `a34ebb4aa0604ff54f78922f50bb7dc82d9587cfc426aa4f0c1ef0c74b051dbe` | `505efc646249c3171792063dba986923b7838b3a` |
| `libc/kernel/uapi/asm-generic/posix_types.h` | 2,039 | ship | both | `fd5996951df10efc97bd123c91fa6d3dcf877251ed0ccb32761d4083a1bf293b` | `4792662e4f9443f40bffd5f344bce5efbf342cd4` |
| `libc/kernel/uapi/asm-generic/types.h` | 282 | ship | both | `f676ab1191fcad85565228eb0e4cf53edc98e5fb0b4dba9ae3ebf1855e9ada96` | `d3e6944626023dae8909c4a3ecc5d2aa38324ceb` |
| `libc/kernel/uapi/asm-x86/asm/bitsperlong.h` | 395 | ship | x86_64 | `e343383ddabdc6ebd93054b2d758efc6247daf8ec5e1e0769f0dfa9f9e63be84` | `e5df11c2766a98aa7e62e79fcae121409bb3a0d6` |
| `libc/kernel/uapi/asm-x86/asm/posix_types.h` | 324 | ship | x86_64 | `1248ea8b090d92a712b85cb0e4a71464404b100e7c85e90b4edb19a66198c30a` | `c57f1e06465d4d4860a0078eed06b9fdfe172a3a` |
| `libc/kernel/uapi/asm-x86/asm/posix_types_64.h` | 505 | ship | x86_64 | `daba3320e459d498913ce51af77fc820f1edcfcb64e551170259c82a2ac99e1b` | `26db149e54994c1d9317e1699ed35ddb17d21a8b` |
| `libc/kernel/uapi/asm-x86/asm/types.h` | 204 | ship | x86_64 | `4b8d02254d1d5ee1b7eb6ee962a63a935330799c14eaf07f93698c2cf8e59e2a` | `a030be86d321b3e51c78cb0f18085d2145682427` |
| `libc/kernel/uapi/asm-x86/asm/unistd.h` | 415 | build | x86_64 | `5f2173b31c189b51c081277e4ad876e822fcc6050ed35686aad9ff4551d6ab7f` | `fc9d18d2d8d1a58f5473417f8d4eef2b8922bfd8` |
| `libc/kernel/uapi/asm-x86/asm/unistd_64.h` | 10,553 | build | x86_64 | `f5932f5da1d4bbec377207d7694a1918d6362174a840a271efa346977128b8d6` | `47976abdcda2ca485eb85d203351b6ebc199edca` |
| `libc/kernel/uapi/linux/limits.h` | 544 | ship | both | `b67c7dc51627702441cc1761f20dc7f358e0e9cbfc1d8e690cf16890d3e1a2e7` | `e2d5103c3f12355bb51268e843666a182af2754f` |
| `libc/kernel/uapi/linux/posix_types.h` | 537 | ship | both | `b4dfa3505ea263b2867e7305c6ca1274415cde7236496cf524556ce0ce59099d` | `b21f63fcc0a0b382263bff27e2dd6e4ab14c77ca` |
| `libc/kernel/uapi/linux/stddef.h` | 918 | ship | both | `23f0b9bcbe8652a75f05fea737d5312ac240101d59397af33bc041f19f80f082` | `5c9e2570bd4a1cfc0fe85689071703493355e30a` |
| `libc/kernel/uapi/linux/types.h` | 1,048 | ship | both | `841ed4d21f88467caf5d01af9e551f25e5e7167bb2bd25139712cf9b1f81bf1d` | `f33febd72d49730db3340b9a12d9d6e15d07caa1` |
| `libc/kernel/uapi/linux/version.h` | 389 | check | — | `48fdd11cab86262fa1c5215ce695966732d3e699cccd4eae645195bbd04fd94b` | `8b12181eefdb93cdccc9fe572fa449d3240d4bd2` |
| `libc/private/bionic_asm.h` | 4,344 | build | both | `6291935944e995c5111f913a34446fadb529b5dabf0c3d099eaffca6a550c819` | `05af4abc03894f51f2934375c357b61a9dce9893` |
| `libc/private/bionic_asm_arm64.h` | 3,097 | build | arm64 | `b6f66c98e064969b75e2af97481517ac5ce7fa0d89fa0052ea021fd30f1d8104` | `d245967373a74cbbe48fd5541fd63bb32c0986df` |
| `libc/private/bionic_asm_note.h` | 1,548 | build | both | `57e505697ec2ab18ceda59187db33b7a9c829a9180a8721fea3afa24958b8cf1` | `9a533c0000837777ff3beee4ab24f1f144b1ddb5` |
| `libc/private/bionic_asm_x86_64.h` | 2,044 | build | x86_64 | `0e4299fd7fe15b4bba4f3d79849e558a5fdc63e64e239a14f7519644420745af` | `b8e38071734097acbecc3eeccd758bb4a98d2f07` |
| `libc/libc.map.txt` | 38,678 | check | — | `5831b40390f17a34536513c79735bc632aa3d3f4d81fc4ed5f5ea8ff6ed5107c` | `b0633eb32feabe48f2e1575184a69e423626913f` |
| `libm/libm.map.txt` | 4,751 | check | — | `addb0e674222bb262646809f768328e27325266e122f569e80282216cf5c84c0` | `b9a0db23a6d93dd5e457602647a7f3a73241773a` |

Notes on the table:
- **47 rows:** 30 ship, 14 build, 3 check. `linux/version.h` is new in this version of the design: it holds
  `LINUX_VERSION_CODE 398080` (6.19.0), from which the kernel licence texts' tag is derived (§2.10). It comes in the
  `libc/kernel/uapi` archive, so it costs no request.
- **Two shipped files share bytes.** `asm-arm64/asm/types.h` and `asm-x86/asm/types.h` are identical (`4b8d0225…`).
  The table keys on the path, so this is harmless.
- **Both columns are checked on every read** (`held(path, data)`): the sha256, and the git blob id,
  `sha1(b"blob %d\0" % len(data) + data)`. So `--check-upstream`'s "bionic's own blobs" vouches for the sha256 too,
  and a hand edit of either column alone fails the next read.
- **The output pins, `OUTPUTS`**, relative to `android-sysroot/` [V A.3]:

  | Output | Bytes | sha256 |
  |---|---|---|
  | `usr/lib/aarch64-linux-android/33/crtbegin_so.o` | 3,096 | `5781a58d6c1f273ec5a642548f6fc37a22b8916febaf4fb8ccb12966431d2520` |
  | `usr/lib/aarch64-linux-android/33/crtend_so.o` | 736 | `8703453e41637538b26a57ce0461f0ad5f2abfbcdf9303166b82b47131a3d4be` |
  | `usr/lib/x86_64-linux-android/33/crtbegin_so.o` | 2,816 | `ecf36375989bce14e04491cecc765f874aa0104736e5b083900110341f515906` |
  | `usr/lib/x86_64-linux-android/33/crtend_so.o` | 568 | `022ba53c856b6a2c5028b4fbb11be638b102e100606b594b111c3ea4012834b6` |
  | `NOTICE.txt` | — | set when §2.5's text is first generated, after reading it whole |

  The x86_64 objects equal `sysroot_full_own`'s, the gate's, byte for byte; the arm64 ones are held to NDK r28c's by
  structure before they are pinned (R5a part 1's Done).

### 2.3 Fetching

**Archives on a build's path, single files only on request.** A build needs the 44 build and ship files, which come
in four `+archive` requests, always at `COMMIT`: `{BASE}/+archive/{COMMIT}/{dir}.tar.gz` for `libc/include`,
`libc/kernel/uapi`, `libc/arch-common/bionic` and `libc/private`. The two symbol lists come only with `--lists`
(`{BASE}/+/{COMMIT}/{path}?format=TEXT`, base64), the endpoint that met HTTP 429 in the research [V map §4.5]; CI
asks for them, a build never does.

**Never pin an archive.** gitiles makes a new archive on each request, so the same tree came back with three digests
[V map §4.5].
- Each archive is opened in memory (`tarfile`, `r:gz`). Its members are named relative to the directory, with no
  leading `./` [V reviewer's `r5/review_archive_probe.py` over the scratch archives].
- Only the members `SOURCES` names are taken, as `<dir>/<member>`, and only regular files.
- Each is held to both pins before it is written to the cache. Nothing else touches the disk, which also avoids
  `libc/kernel/uapi`'s eight pairs of names that differ only in case [V map §4.1].

**`fetch(url, *, decode=None, get=None, sleep=time.sleep, clock=time.monotonic)`.** One helper for every request
the tool and `package.py` make.
- `get` is an injected opener, as `fetch_sdl.source(get=)` has (fetch_sdl.py:191-202), so no test touches the
  network. `sleep` and `clock` are what the tests patch.
- `decode` turns a 200's body into what the caller needs (here, an open `tarfile`, or base64 decoded). A failure
  there counts as a transport failure, as below.
- **Pacing:** `PACE = 2.0` s between any two requests; ten requests paced this way met no 429 [V A.2, A.5].
- **What is tried again,** up to `TRIES = 6` tries a request:
  - HTTP 429 and 5xx;
  - a timeout, a reset, a refused connection, a name that does not resolve (`URLError`, `TimeoutError`,
    `ConnectionError`, `ssl.SSLError`);
  - a body that fails while it is read or decoded: `http.client.IncompleteRead` and the rest of `HTTPException`, an
    `OSError` while reading, `EOFError`, `tarfile.ReadError`, `zlib.error`, `gzip.BadGzipFile`, `binascii.Error`.
    That covers a cut-short gzip and a proxy's HTML page.
- **Each wait** is `Retry-After` when given, in seconds or as an HTTP date (`email.utils.parsedate_to_datetime`),
  never more than `WAIT_CAP = 300` s; else 10, 20, 40, 80, then 120 s. Each wait prints
  `android.googlesource.com asked this machine to wait (HTTP 429); trying again in <n> s (<k> of 6)`, or, for a
  transport failure, `android.googlesource.com sent a broken or non-archive response for <url> (<reason>); trying
  again in <n> s (<k> of 6)`. The host in the words is the URL's, so `package.py`'s fetches say theirs.
- **One deadline for the whole run,** `DEADLINE = 600` s from the first request. A wait that would pass it is not
  taken.
- **A 404** is never tried again: `error: <url>: not found (HTTP 404): the pinned commit or path is not on
  android.googlesource.com`. Any other 4xx: `error: android.googlesource.com refused <url> (HTTP <code>)`.
- **Giving up** prints `error: android.googlesource.com would not serve <url> after <k> tries (<last reason>): try
  again later; or fill vendor/android-sysroot-src from a checkout of bionic at 06356e41 (--from <folder>); or copy
  it from a machine that has it and pass --offline`. A run that never connected says `error: cannot reach
  android.googlesource.com (<reason>): connect and run this again, …` with the same two ways out.
- None of these words speak of pins. Only a body that decoded and holds a file whose bytes are not its pin's does
  (below).

**The source cache, `<vendor>/android-sysroot-src/`.**
- A file there that matches both pins is used. One that does not is deleted and fetched again, or, offline,
  named.
- A fetched file that does not match is refused:
  `error: <path> from <url>: sha256 <got>, pinned <want>; nothing was written` (or `git blob <got>, pinned <want>`).
  The cache keeps what it had, and no tree is touched.
- An archive that decoded but lacks a pinned member is refused:
  `error: <url> holds no <path>: the pinned commit or path is not what android.googlesource.com serves; nothing was
  written`.
- With every file it needs in the cache, a run makes no request.

**`--from <folder>`** fills the cache from any folder laid out as bionic: a checkout of the tag from any AOSP mirror,
the scratch `src/bionic`, or another machine's cache. Each file is held to both pins as it is copied, so where it
came from does not matter. It prints `<n> of 44 bionic files the build reads, from <folder>, are as pinned` and names
each one it lacks or that differs. It is the way out when googlesource is down, and TESTING's recipe names it.

**Offline (`--offline`).** No request. A file the build needs that the cache lacks, or holds off its pins:
`error: --offline, and vendor/android-sysroot-src has no <path> as pinned (missing | sha256 differs | git blob
differs)`, exit 1.

**`--cache-key`** prints `key=<the first 16 hex of the sha256 of COMMIT and every SOURCES row>`. It depends on the
pins alone, never on the script's bytes or line ends, and CI keys its cache on it (§7.1).

### 2.4 Building the crt objects

**The compiler.** `mingw_tools()` returns `(clang, ld.lld)` from `toolchain.mingw_clang()` and `mingw_lld()`: the
ones beside the `x86_64-w64-mingw32-clang` the mingw profile finds, so the crt objects, the game library and
`soa.exe` come from one llvm-mingw (§4.2).
- None there: `error: no llvm-mingw (python tools/fetch_mingw.py fetches it): the crt objects are built with its
  clang`, exit 1, before any request.
- A clang whose `--version` does not name 23.1.2 at `85ac5602…` (`toolchain.mingw_identity_problem`): `error: <path>
  is "<its first line>", and the crt objects are built by llvm-mingw 20260922's clang 23.1.2 (85ac5602): python
  tools/fetch_mingw.py fetches it`, exit 1, before anything is built.
- Every command runs with `toolchain.clean_clang_env()`: `os.environ` without `COMPILER_PATH`, `CPATH`,
  `C_INCLUDE_PATH`, `CPLUS_INCLUDE_PATH`, `OBJC_INCLUDE_PATH`, `OBJCPLUS_INCLUDE_PATH`, `LIBRARY_PATH` and
  `CCC_OVERRIDE_OPTIONS`. clang reads each ahead of a sysroot: header folders searched first, a crt object or linker
  found first, an edited command line.

**A build sysroot in a temporary folder.** `tempfile.TemporaryDirectory(prefix="soa-sysroot-")` holds, for the
build alone:
- the 30 shipped headers at their `SHIP` places, and, for each ABI, `asm/unistd.h` and `asm/unistd_64.h` under
  `usr/include/<triple>/asm/`: the layout the proven recipe used [V A.3; the reviewer's probe rebuilt the pins from
  the same layout in another folder];
- each compile's and link's own output, which clang and lld first write under a temporary name beside it
  [I: LLVM's output buffers add `-%%%%%%%%` and `.tmp%%%%%%%`]. Kept here, those longer names never reach the
  vendor folder.

The temporary folder is removed afterwards. Its path does not enter the objects (below).

**The recipe, per ABI,** the one that reproduced the gate's bytes [V A.3]. `CRT_FLAGS` is
`("-fPIC", "-O2", "-Wall", "-Werror", "-Wno-gcc-compat")`, `<triple>` is `aarch64-linux-android` or
`x86_64-linux-android`, and `<cache>/libc` gives `private/…` its path:
```
clang --target=<triple>33 --sysroot=<build sysroot> <CRT_FLAGS> -I<cache>/libc -c <cache>/libc/arch-common/bionic/crtbegin_so.c -o <tmp>/<abi>/crtbegin_so_c.o
clang --target=<triple>33 --sysroot=<build sysroot> <CRT_FLAGS> -I<cache>/libc -DPLATFORM_SDK_VERSION=33 -c <cache>/libc/arch-common/bionic/crtbrand.S -o <tmp>/<abi>/crtbrand.o
ld.lld -r <tmp>/<abi>/crtbegin_so_c.o <tmp>/<abi>/crtbrand.o -o <tmp>/<abi>/crtbegin_so.o
clang --target=<triple>33 --sysroot=<build sysroot> <CRT_FLAGS> -I<cache>/libc -c <cache>/libc/arch-common/bionic/crtend_so.S -o <tmp>/<abi>/crtend_so.o
```

**What does not move the bytes, and what does** [V A.3]: no path enters the objects (`STT_FILE` is `crtbegin_so.c`,
the driver's `-main-file-name`); the `.comment` names clang 23.1.2 and nothing of the host; a different clang
changes the bytes, which the output pins then refuse.

**Each output is held to `OUTPUTS`.** A mismatch prints `error: crtbegin_so.o for arm64 built here has sha256 <got>,
pinned <want>: the clang is not llvm-mingw 20260922's 23.1.2, or the recipe changed; nothing was written`.
`build_crt(…, extra=())` takes extra flags for the mutation test only.

**Putting it in place: `build(vendor, cache)`.** A stop at any step leaves no record, which the next run treats as
"build again":
1. Delete `<vendor>/ANDROID-SYSROOT.sha256`, then any `android-sysroot.new/` or `android-sysroot.old/` an earlier
   stop left.
2. Copy the 30 headers into `android-sysroot.new/usr/include/…`, the four built crt objects into
   `android-sysroot.new/usr/lib/<triple>/33/`, and write `android-sysroot.new/NOTICE.txt`. Hold every one to its pin.
3. Rename `android-sysroot/` to `android-sysroot.old/` when it exists; rename `android-sysroot.new/` to
   `android-sysroot/`.
4. Write the record.
5. Remove `android-sysroot.old/`.

On Windows, Defender or the indexer can hold a file the tool has just written, so each rename and removal is tried
up to five times, 0.2, 0.4, 0.8, 1.6 and 3.2 s apart. A rename that still fails ends in words: `error: Windows would
not let this replace <vendor>\android-sysroot (<the OSError>): close anything using that folder, such as an Explorer
window, and run this again; nothing is recorded, so the next run builds it again`, exit 1. An `.old` that will not go
is left, named in a note, and removed by the next run's step 1. No `OSError` reaches the user as a traceback.

### 2.5 `NOTICE.txt`

`notice_text(cache) -> str` is deterministic, written as UTF-8 with LF line ends. In order, it holds:
1. **A preface.** It says what the sysroot is; that every file is bionic's at `COMMIT` (android-17.0.0_r1),
   unmodified, or built from it by llvm-mingw `MINGW_RELEASE`'s clang; and where the texts the notices name but do
   not hold are:
   - the Apache License 2.0 is the first part of `licenses/llvm.txt`, LLVM's licence, which is that text followed
     by LLVM's exceptions. No line numbers: a new llvm-mingw could move them, while this text's pin held;
   - the GNU GPL version 2 and the Linux-syscall-note, which the Linux user-space headers under `usr/include/linux`,
     `asm-generic` and `<triple>/asm` are under, are `licenses/linux-gpl-2.0.txt` and
     `licenses/linux-syscall-note.txt`.
2. **One section per file,** `== <place in the sysroot> (bionic <path>)`, then the file's leading comments verbatim:
   every `/* … */` block before its first line of code. That rule takes the `$NetBSD$` and `$OpenBSD$` tag comments
   with the licence under them. A file's first comment alone is not its licence in five of them: `setjmp.h`,
   `strings.h`, `sys/cdefs.h` and both `bionic_asm_<arch>.h` [V A.5]. The sections come in three groups, in path
   order:
   - **the 30 shipped headers;**
   - **"compiled into crtbegin_so.o or crtend_so.o":** the six `arch-common` files and the four `private` ones;
   - **"read while building the crt objects; nothing of it is compiled in":** the four `unistd` headers.

The classes the text holds [V A.5]:

| Class | Shipped headers | Compiled into the crt objects |
|---|---|---|
| BSD-2-Clause, the Android Open Source Project | `android/api-level.h`, `bits/{posix_limits,pthread_types,strcasecmp,wchar_limits}.h`, `stdint.h`, `string.h`, `sys/types.h`, `xlocale.h` (9) | `__dso_handle_so.h`, `atexit.h`, `crtbegin_so.c`, `crtbrand.S`, `crtend_so.S`, `bionic_asm.h`, `bionic_asm_note.h` (7) |
| BSD-3-Clause, the University of California | `limits.h`, `setjmp.h`, `sys/cdefs.h` (3) | `bionic_asm_arm64.h`, `bionic_asm_x86_64.h` (2) |
| The NetBSD Foundation's 4-clause text, its advertising clause still in it | `strings.h` (1) | — |
| Sun's fdlibm notice | `math.h` (1) | — |
| Apache-2.0, AOSP | `android/versioning.h` (1) | `pthread_atfork.h` (1) |
| Linux user-space API, generated: "This file is auto-generated", no licence text; the kernel marks them GPL-2.0 WITH Linux-syscall-note | 15: `linux/` 4, `asm-generic/` 4, arm64 `asm/` 3, x86_64 `asm/` 4 | — (the four `unistd` headers are read, not compiled in) |

### 2.6 The record, `--verify`, and the sysroot's digest

**`ANDROID-SYSROOT.sha256`** is sha256sum's format, with LF line ends, written with `newline="\n"` as
fetch_mingw.py:124 does. Three comment lines come first, all from constants, so the record is the same bytes on
every machine that builds the same tree:
```
# R5's Android sysroot (tools/fetch_android_sysroot.py, specs/android.md 3.4): bionic's headers and crt objects, built here.
# bionic: https://android.googlesource.com/platform/bionic at 06356e41c5ed7b12220b24c05ba4fdb873b126a7 (android-17.0.0_r1): each file held to its pinned sha256 and git blob
# built with llvm-mingw 20260922's clang 23.1.2 (toolchain.MINGW_RELEASE); the crt objects and NOTICE.txt held to their pins
```
Then 35 lines, `<sha256>  android-sysroot/<path>`, sorted.

**`expected_record()`** is the same 35 entries computed from `SOURCES` (via `SHIP`) and `OUTPUTS` alone.

**`verify(vendor) -> list[str]`** returns facts, never advice, in order:
- `no <vendor>/ANDROID-SYSROOT.sha256` when there is none;
- `the record is not this script's (<path>: recorded <x>, this script pins <y>)`: a tree from an older pin table,
  or from another llvm-mingw, is never taken;
- for each recorded file, `android-sysroot/<path>: recorded but missing` or `…: differs from the record`;
- for each file under `android-sysroot/` the record does not name, `android-sysroot/<path>: not in the record`. An
  extra `usr/include/stdlib.h` would otherwise be compiled against silently; that is what gives the closure its
  meaning.

Each caller adds its own way out: the command line and `recompile.py` add `run python tools/fetch_android_sysroot.py`
(which rebuilds from the cache); `player_build` uses its own words (§6.1). An `OSError` while reading is returned as
a fact, never raised.

**`--verify` prints** the facts on stderr, then `<n - bad> of <n> recorded Android sysroot file(s) unchanged`, and
exits 1 when there are any. `--vendor` names another vendor folder, a package's `source/vendor` among them.

**`sysroot_digest(vendor) -> str`** is the sha256 of the record's `android-sysroot/usr/` lines alone: the headers and
crt objects, which is all that a compile or a link reads. `build_inputs.txt`, `player_build`'s identity and the
library's `sysroot=` use it. A change to `NOTICE.txt` or a comment line therefore never makes a `gen/` stale.

### 2.7 `--check-upstream`

For the developer who changes a pin, or reviews the first bless. With network, through `fetch()`:
- `{BASE}/+/refs/tags/{TAG}?format=JSON` must name `COMMIT`;
- then one request per directory holding a pinned file, `{BASE}/+/{COMMIT}/{dir}?format=JSON`, paced: ten under
  `libc/`, then `libc` and `libm` for the two lists. Each pinned file's blob id must be the listing's.

It prints `47 of 47 pins are bionic's own blobs at 06356e41 (refs/tags/android-17.0.0_r1 is 06356e41)`, or each
that is not, and the tag's commit when it is not `COMMIT`. `check_upstream(get=None)` takes the injected opener, so
its test needs no network (check 17). CI does not run it.

### 2.8 `--compare`: the headers change no object (part 2)

`python tools/fetch_android_sysroot.py --compare [<reference sysroot>] [--gen DIR] [--cc PROFILE]` compiles every
translation unit in `DIR` (default `gen/<profile>`: `dispatch.c` and each `chunk_*.c`) twice, with the profile's
`--optimize` compile command from `recompile.compile_command` (imported inside this mode), once against the
reference and once against `<vendor>/android-sysroot`, into a temporary folder. It prints
`<k> of <n> objects identical against <reference> (<profile>, -O2)`, and names each unit that differs, exit 1 when
any does. The reference defaults to the NDK's own sysroot, where `toolchain.android_ndk()` finds one; this PC's is
NDK r28c's.

It is the map's "run the object comparison again whenever the closure changes" (map §6.0), committed so it can be
run again, and the bump instructions in the docstring name it. It needs the translated C, which only a machine with
the disc has, so CI does not run it; check 16 holds it to a small unit that needs no disc.

### 2.9 Command line, `ensure()`, and what the package uses

```
python tools/fetch_android_sysroot.py [--vendor DIR] [--offline] [--from DIR] [--lists]
python tools/fetch_android_sysroot.py --verify [--vendor DIR]
python tools/fetch_android_sysroot.py --check-upstream
python tools/fetch_android_sysroot.py --cache-key
python tools/fetch_android_sysroot.py --compare [<reference sysroot>] [--gen DIR] [--cc PROFILE]
```

**`ensure(vendor, *, offline=False, get=None) -> str`** is the plain run, and what `player_build` calls:
1. When `verify(vendor)` finds nothing and the record equals `expected_record()`: `vendor/android-sysroot is there
   and as recorded (35 file(s) checked)`. Nothing is fetched or built.
2. Otherwise it names the first fact (`vendor/android-sysroot: <fact>; building it again from
   vendor/android-sysroot-src`), fills the cache (§2.3, no request when the cache is whole), and runs `build()`.

So a run never says "there" over a tree that `recompile.py` would refuse; the draft's loop between the two is gone.

**What `package.py` uses** (R5b):
- `stage_sources(cache, dest)` copies exactly the 44 build and ship files into `dest`, in bionic's layout, each held
  to both pins. Never the check files, never anything else in the cache.
- `longest_written() -> int` is the longest path the tool writes under a vendor folder:
  `android-sysroot.new/usr/include/x86_64-linux-android/asm/posix_types_64.h`, from `SHIP`.
- `notice_text(cache)`, for `licenses/android-sysroot.txt`.

**Exit codes:** 0 when the tree is there and as pinned (or the mode's check passed); 1 otherwise. That covers a pin,
the network, no llvm-mingw, an identity, a swap, and verify's facts.

**The module docstring** follows fetch_mingw.py's (fetch_mingw.py:1-24). It adds:
- why each file is there;
- that **a new llvm-mingw release fails the output pins by design**: whoever bumps `fetch_mingw.RELEASE` bumps
  `toolchain.MINGW_RELEASE` and `MINGW_CLANG` with it (a test holds the two releases equal), derives the new pins,
  and runs R5a's emulator checks again;
- that **a new `#include` in `cpu.h` or `soa_game.h` fails the closure test**: whoever adds it pins the new headers
  (`--check-upstream` checks them), runs `--compare`, then the emulator;
- the grep that finds every copy of a count this tool's output prints:
  `grep -rn "<the old number>" --include="*.md" .`.

### 2.10 What `licenses/` gains (R5b)

- `android-sysroot.txt`: `notice_text()` of the staged sources, held to `OUTPUTS["NOTICE.txt"]`, written by
  `package.licenses()`. It is the same text as the tree's `NOTICE.txt` on every machine.
- `linux-gpl-2.0.txt`: `https://raw.githubusercontent.com/torvalds/linux/v6.19/LICENSES/preferred/GPL-2.0`,
  18,600 B, sha256 `8780e78a1a737e127f25a65f6d95269bffd36158dc261114de7859b490bfc5aa` [V A.5].
- `linux-syscall-note.txt`: `…/v6.19/LICENSES/exceptions/Linux-syscall-note`, 1,258 B, sha256
  `8e378ab93586eb55135d3bc119cce787f7324f48394777d00c34fa3d0be3303f` [V A.5].
  - `v6.19` is the kernel these headers were generated from: bionic's pinned `linux/version.h` holds
    `LINUX_VERSION_CODE 398080`, 6.19.0. A test derives the tag from that file and holds both URLs to it, so a new
    `COMMIT` with newer kernel headers fails it.
  - Both go in `LICENSE_URLS`, fetched once into `vendor/licenses/` through `fetch_android_sysroot.fetch()` and held
    to their pins (package.py:186-196). The host is the one llvm-mingw's and glslang's texts come from, which
    test_package.py:31-35 requires.
- **Apache-2.0:** no new file. `licenses/llvm.txt` holds the full text; a test holds that its first part is it (§8.2).
- **Not shipped:** bionic's whole `libc/NOTICE` (228,429 B, 14 advertising clauses, map §4.6), and AOSP
  `external/kernel-headers`' NOTICE (GPL-2.0 alone, blob `d159169d…` at `68a96878`) [V A.5]. The owner may ask for
  either at the look.

---

## 3. The stub libraries from `seam.txt` (`tools/soa/seam.py`)

**New in `seam.py`:**
- `C_LIBRARIES = ("libc.so", "libm.so", "libdl.so")`. elfcheck.py:38's tuple becomes `C_LIBRARIES =
  seam.C_LIBRARIES`: one list of the names the phone takes.
- `BIONIC_LIBM = frozenset({"fma", "nearbyint", "nearbyintf", "sqrt"})`: the `seam.txt` names bionic's `libm.so`
  defines at version `LIBC`. Every other `libc` name is `libc.so`'s, and `libdl.so` gets none. This is bionic's own
  placement: all 13 names are in the `LIBC` block of the list holding them, and `__register_atfork` has
  `introduced=23` [V A.5]. Check 12 holds this constant and `seam.txt` to bionic's two lists.
- `c_library_names(seam) -> dict[str, tuple[str, ...]]`, in `seam.txt`'s order:
  - `libc.so`: `_setjmp`, `setjmp`, `memcpy`, `memmove`, `memset`, `__stack_chk_fail`, `__cxa_finalize`,
    `__cxa_atexit`, `__register_atfork`;
  - `libm.so`: `fma`, `sqrt`, `nearbyint`, `nearbyintf`;
  - `libdl.so`: none.
- `stub_library_c(soname, names) -> str`: a header comment saying it is linked against and never run
  (`config/seam.txt`, specs/android.md 3.4), then `void <name>(void) {}` for each name. No names gives the comment
  alone.
- `stub_version_script(names) -> str`: with names, `LIBC {\n  global:\n    <name>;\n  …\n  local: *;\n};\n`; with
  none, `LIBC {\n  local: *;\n};\n`, which lld takes [V A.4].
- `write_android_stubs(stub_dir, seam, bound)`: writes `stub_runtime.c` (today's text, seam.py:201-215), `libc.c`,
  `libc.vers`, `libm.c`, `libm.vers`, `libdl.c` and `libdl.vers`. It is the one writer: recompile calls it at each
  run that translates, which every `--link` run does (recompile.py:689-708), and gamefixture at each fixture build.

**Built where:** `<out>/stub/`, beside today's stand-in.

**Built how:** by `android_link_plan`'s first three commands (`android_stub_commands(p, stub)`), at each link (§5.4):
```
<p.cflags' --target> -fPIC -fvisibility=default -fno-builtin -w -shared -nostdlib /Fe<stub>/libc.so <stub>/libc.c -Wl,-soname,libc.so -Xlinker --version-script=<stub>/libc.vers
```
And the same for `libm` and `libdl`. Not `p.cflags` whole, whose `-fvisibility=hidden` would hide every stub.

**`-Xlinker`, not `-Wl,`, for the one argument that carries a path.** clang splits a `-Wl,` argument at every comma,
and Setup takes a folder whose name holds one (setup.c:142-148 refuses only characters outside 0x20-0x7E). The
reviewer's probe, in a folder named "Skies, the game (probe)": `-Wl,--version-script=<path>` exited 1 with `ld.lld:
error: cannot find version script C:\…\review_probe\Skies`, and `-Xlinker --version-script=<path>` exited 0 [V
`r5/review_probe/probe.py`]. No other Android `-Wl,` argument carries a path (`-soname`, `-z`, `--no-undefined`,
`--no-as-needed`). The Linux split build's and the APK's own `-Wl,--version-script=` take a developer's checkout path;
they are left as they are, and FINDINGS notes that a checkout path with a comma breaks them.

**The SONAMEs are exactly `libc.so`, `libm.so` and `libdl.so`.** The phone's checker takes the C libraries by those
names alone, on Android (elfcheck.py:183-191, :249-261).

**What it gives** [V map §3.6, A.4]:
- **The output.** The game library has the gate's `DT_NEEDED`, imports and `VERNEED` (`libc.so: LIBC`).
- **The allowlist at link time.** A call to anything outside `seam.txt` fails the link on the PC with
  `undefined symbol: <name>`, where the NDK's full stubs linked it and only elfcheck refused it later.
- **No rebuild for a seam change.** A change to `seam.txt` reaches the stubs at the next link, and the APK's allowlist
  only with an APK rebuild, as today.

---

## 4. Profiles, the compiler lookup, and what keeps the NDK (`tools/soa/toolchain.py`)

### 4.1 The profiles (part 2)

```python
_ANDROID = ("-fPIC", "-fvisibility=hidden")
# Every Android link names its C libraries itself, after the objects, in the NDK's order: llvm-mingw
# carries no Android compiler-rt or libunwind, which the driver's defaults ask for (map 3.3), and
# nothing in the game library uses either (map 2.5).
_ANDROID_LINK = ("-nodefaultlibs", "-lm", "-ldl", "-lc")
ANDROID_ARM64 = Profile("android-arm64", "gnu", ("--target=aarch64-linux-android33", *_GNU_FLAGS, *_ANDROID),
                        _CLANG_STRICT, ".o", "", "gen/android-arm64", _ANDROID_LINK)
ANDROID_X86_64 = Profile("android-x86_64", "gnu", ("--target=x86_64-linux-android33", *_GNU_FLAGS, *_ANDROID),
                         _CLANG_STRICT, ".o", "", "gen/android-x86_64", _ANDROID_LINK)
ANDROID = (ANDROID_ARM64, ANDROID_X86_64)
# The NDK, for what the sysroot cannot serve: the APK's runtime reads 49 system headers (jni.h,
# android/log.h, pthread.h, SDL's, Vulkan's; map 2.7). compile_runtime.py's check of every runtime
# file for the phone uses these; recompile.py refuses them.
ANDROID_ARM64_NDK = Profile("android-arm64-ndk", "gnu", ANDROID_ARM64.cflags, _CLANG_STRICT, ".o", "",
                            "gen/android-arm64-ndk", ("-lm",))
ANDROID_X86_64_NDK = Profile("android-x86_64-ndk", "gnu", ANDROID_X86_64.cflags, _CLANG_STRICT, ".o", "",
                             "gen/android-x86_64-ndk", ("-lm",))
ANDROID_NDK = (ANDROID_ARM64_NDK, ANDROID_X86_64_NDK)
PROFILES = {p.name: p for p in (MSVC, CLANG_CL, GCC, CLANG, MINGW, *ANDROID, *ANDROID_NDK)}
```

- `is_android(p)` is `p.name in {"android-arm64", "android-x86_64"}`; `is_ndk(p)` the same for the `-ndk` pair. Both
  go by name, so a `dataclasses.replace`d profile is still known; identity and tuple membership are not used.
- **The compile flags are unchanged**, so the objects are what L12b, L12c and the gate built [V map §3.5].

### 4.2 Finding the compiler and the sysroot

**Part 1 (the tool needs these):**
- `MINGW_RELEASE = "20260922"`; `MINGW_CLANG = ("23.1.2", "85ac560262434c9ccfc0c183ec22d4138ed647fb")`. A test holds
  `MINGW_RELEASE == fetch_mingw.RELEASE` (test_mingw.py), so a bump of one without the other fails.
- `mingw_clang() -> str | None` is the `clang` (`clang.exe` on Windows) in the folder where
  `compiler_path(MINGW)` found `x86_64-w64-mingw32-clang`; `mingw_lld()` is the `ld.lld` there. So the two profiles
  cannot resolve to two toolchains: a generic `clang` in `<checkout>/../toolchain/bin` that belongs to another
  project, or an NDK's `bin` named by `SOA_MINGW`, has no `x86_64-w64-mingw32-clang` beside it and is never taken
  (toolchain.py:281-287, :364-369). Windows' `clang.exe` is llvm-mingw's wrapper, and a later `--target=` wins
  [V map §3.1]; Linux's `bin/clang` is kept by fetch_mingw's pruning [V fetch_mingw.py:64-92].
- `clang_id(exe) -> str`: the first non-empty line of `<exe> --version`, cached per path; `""` when it cannot run.
  For llvm-mingw it is `clang version 23.1.2 (https://github.com/llvm/llvm-project.git 85ac560262434c9ccfc0c183ec22d4138ed647fb)`
  [V A.3].
- `mingw_identity_problem(exe) -> str | None`: `None` when `clang_id(exe)` names `MINGW_CLANG`'s version and commit;
  else words naming both (§2.4). Ubuntu's build of the same release is expected to print the same line [I]; R5a
  part 1's CI run shows it.
- `clean_clang_env() -> dict[str, str]`: §2.4's list taken out of `os.environ`.

**Part 2:**
- `android_sysroot() -> Path | None`: `<source root>/vendor/android-sysroot` when it holds `usr/include/stdint.h`.
  That is `vendor/` in a checkout and `source/vendor/` in a package, the folder recompile's `VENDOR` is
  (recompile.py:62). No environment variable: tests monkeypatch it. It does not verify; recompile and `player_build`
  do (§5.2, §6.1).
- `compiler_path(p)`:
  - `is_android(p)`: `mingw_clang()` when it and `android_sysroot()` are both there, else `None`. Every caller's
    existing `None` check then covers the sysroot too: recompile, gamefixture's `toolchain.cc`, the tests' markers.
  - `is_ndk(p)`: today's NDK clang (toolchain.py:370-372).
  - **The game library never looks for an NDK.**
- `compiler_id(p) -> str`: `clang_id(compiler_path(p))` for gnu-style profiles; `""` for msvc-style ones and when
  there is no compiler.
- `android_places() -> list[str]`, for "the build says where it looked", one line each:
  - `SOA_MINGW (<value> | unset)`, and when set, `: <llvm-mingw's clang 23.1.2 (85ac5602) | no llvm-mingw there
    (no x86_64-w64-mingw32-clang[.exe])>`;
  - when it is unset, `<root>\..\toolchain\bin: …` and `<root>\vendor\llvm-mingw\bin: …`, with the same answers;
  - `<root>\vendor\android-sysroot: there | none (python tools/fetch_android_sysroot.py builds it)`.

  The exact lines are R5a part 2's Done.

### 4.3 `--sysroot` and a clean environment on every Android command, in one place (part 2)

- `gnu_commands(args, exe, p)` (toolchain.py:420-438) builds each command as `[exe, *head, …]`, where
  `head = [f"--sysroot={android_sysroot()}"]` for `is_android(p)` and `[]` otherwise, **on both of its paths**: the
  single command, and the per-source commands of a compile into a folder.
- `cc()` (toolchain.py:441-467) raises `no <name> compiler here` as today when `compiler_path` is None, and runs an
  Android profile's commands with `env=clean_clang_env()`.
- Every compile and link of the game library goes through `cc()`: recompile's units, stubs, stand-in and game, and
  gamefixture's `_cc`. The one exception is the tool's crt build, which runs clang itself against its own build
  sysroot, with the same clean environment (§2.4).
- **No game-library command can miss the sysroot.** Without `--sysroot`, clang looks at the root of the current
  drive [I map §3.2].

### 4.4 What keeps the NDK

- **The APK's runtime:** `android/app/build.gradle.kts`'s `ndkVersion` and CMake. `android.py build` and
  `android.py sdk()` (android.py:157-167) are unchanged.
- **`compile_runtime.py --cc android-arm64-ndk` and `--cc android-x86_64-ndk`:** SDL is compiled when `is_ndk(prof)`
  (compile_runtime.py:221); `--cc android-arm64` and `--cc android-x86_64` exit 1 with `the runtime is the APK's,
  compiled by the NDK: --cc <name>-ndk; --cc <name> builds the game library (tools/recompile.py)`; the usage line
  lists the profiles.
- **CI's line ci.yml:431** becomes `python tools/citest/compile_runtime.py --cc android-arm64-ndk --require-gxv
  --require-sdl`. No doc names `--cc android-arm64` for the runtime check today [V grep]. FINDINGS' past entries stay
  as written.
- **`recompile.py --cc` refuses the `-ndk` names** (§5.1).

---

## 5. `tools/recompile.py`

### 5.1 Choices and imports

- `cc_choices() -> list[str]`: `[n for n, p in toolchain.PROFILES.items() if not toolchain.is_ndk(p)]`, `--cc`'s
  `choices`. `--cc android-arm64-ndk` is then argparse's `invalid choice`.
- `android = toolchain.is_android(prof)` (recompile.py:616).
- `fetch_android_sysroot` is imported inside the Android branch, not at the top beside `fetch_gpu` and `fetch_sdl`
  (recompile.py:50-51): a defect in it can then never stop a Windows build. `test_citest.py`'s probes import it by
  name, since a lazy import is not in `sys.modules` after `import recompile` (§8.2).

### 5.2 Android: the compiler, its identity and the sysroot, before anything

For `android`, right after the arguments are read and before the DOL is read or anything is written, for `--compile`
and `--link` alike:
1. **The compiler and the sysroot.** `toolchain.compiler_path(prof)` is None: the lines of R5a part 2's Done
   (`android-arm64: no compiler or no sysroot here, so nothing was built`, then `the game library for Android is
   built by llvm-mingw's clang against this repository's own sysroot; looked in, in order:` and `android_places()`),
   exit 1.
2. **Its identity.** `toolchain.mingw_identity_problem(...)`, refused in its words, exit 1.
3. **The sysroot as recorded.** `android_sysroot_problem(VENDOR)`, a helper over `fetch_android_sysroot.verify`:
   `vendor/android-sysroot is not as recorded (<first fact>): run python tools/fetch_android_sysroot.py`, exit 1.
   This mirrors the GPU's refusal (recompile.py:824-830).
4. **Then** the stale-link check of §5.3, which can now compare against a real compiler line.

Today's Android lookup ran after the translation (recompile.py:749-756), so a missing NDK cost the whole
translation first; this costs nothing.

### 5.3 `build_inputs.txt`: the compiler, its flags and the sysroot

**`write_build_inputs(out, dol_sha1, profile, *, compiler="", cflags="", sysroot="")`** writes `dol_sha1` and
`profile` as today; then, for any gnu profile, `compiler = <compiler_id(prof)>` and `cflags = <sha256 of the
compile's profile flags, as declared>`; then, for Android, `sysroot = <sysroot_digest(VENDOR)>`. An msvc record keeps
exactly its two keys (test_recompile_inputs.py:24-30 asserts that, and stays).
- **`cflags`** is the sha256 of `" ".join(cprof.cflags)`: the flags the compile's profile declares, `-O2` included
  as declared, and the split build's added `-fPIC -fvisibility=hidden` with them. The level `--compile` picks is not
  in it: CLAUDE.md says the level comes from the last `--compile`, and a `--link` alone must not refuse for it. What
  it catches is an edit to a profile's flags between a compile and a link, `-mno-outline-atomics` (§10, risk 14) among
  them.

**`check_build_inputs(out, dol_sha1, *, compiler="", cflags="", sysroot="", strict=False)`** checks in this order:
1. **No record:** `None` when not `strict` (`build_inputs_note` says so, as today); under `strict`:
   `{out}: it has no build_inputs.txt, so nothing says how its objects were compiled; run --compile again (stale
   link)`.
2. **The DOL:** today's words.
3. **Under `strict`, a record without `compiler`, `cflags` or `sysroot`:** `{out}: its objects were compiled before
   build_inputs.txt named their compiler, flags and sysroot; run --compile again (stale link)`.
4. **A `compiler` that differs**, where both are known: `{out}: its objects were compiled by "{rec}", and this link
   uses "{now}"; run --compile again (stale link)`.
5. **A `cflags` that differs:** `{out}: its objects were compiled with other flags than {profile}'s now are; run
   --compile again (stale link)`.
6. **A `sysroot` that differs:** `{out}: its objects were compiled against the Android sysroot recorded as
   {rec[:12]}, and vendor/android-sysroot is now {now[:12]}; run --compile again (stale link)`.

`strict` is `android`. **`build_inputs_note(out, profile)`** gains a second case: a gnu record that names no
`compiler`, which a `gen/mingw` or `gen/linux` from before R5 has: `note: {out}'s build_inputs.txt does not name the
compiler or flags its objects were compiled with, so this link cannot check them; the next --compile writes them`.
It passes, as the record-less note does.

**Why:** one profile name, `android-*`, was built by the NDK until now. Its `gen/` holds clang 19's objects, which
`--link` would relink with lld 23 without a word: CLAUDE.md's stale-link trap (map §3.8). The flags are the same
trap's other half (§11 P8).

### 5.4 `android_link_plan`: one plan

```python
def android_link_plan(p, out, *, units=None, flags=(), page=16384, undefined=False, needed=(), stubs=True):
```
- `units`: the objects (default: the chunks and `dispatch`, as today), or a fixture's sources.
- `needed`: extra empty libraries by SONAME, for a mutant.
- `stubs`: `False` leaves out the three C-stub commands, for a caller that has put their `.so` files in
  `<out>/stub` already (gamefixture's reuse, §8.2). recompile always passes `True`.
- No `target` keyword: the ARM32 mutant is made apart (§8.2).

**The commands, in order, each with cwd `Path(".")`:**
1. **The three stubs,** `android_stub_commands(p, stub)`, §3's command each.
2. **The stand-in `libsoa_runtime.so`:** `[*p.cflags, "-fvisibility=default", "-shared",
   f"/Fe{stub/RUNTIME_SONAME}", str(stub/"stub_runtime.c"), f"-Wl,-soname,{RUNTIME_SONAME}", f"-L{stub}",
   *p.linker]`. It now gets `p.linker`, which today it never does (recompile.py:433-440).
3. **For each name in `needed`:** `[<--target>, "-shared", "-nostdlib", f"/Fe{stub/name}", str(stub/"empty.c"),
   f"-Wl,-soname,{name}"]`. gamefixture writes `empty.c` first.
4. **The game:** today's line (recompile.py:441-456), with `*flags` after `p.cflags`; `page`; `--no-undefined`
   unless `undefined`; `-Wl,--no-as-needed <the needed libraries>` before `-L`; `*p.linker` last. That gives
   `DT_NEEDED` `libsoa_runtime.so`, `libm.so`, `libdl.so`, `libc.so` [V A.4].

### 5.5 The post-link check is the phone's

`post_link_problems(prof, lib, the_seam, hle, baked, dol_sha1) -> list[str]`, factored out of
recompile.py:910-928:
```python
return elfcheck.problems(elfcheck.read(lib), machine=elfcheck.ANDROID_MACHINES[prof.name],
                         exports=seam.runtime_exports(the_seam, hle), libc=the_seam.libc,
                         record=seam.record(True, baked), dol=dol_sha1, android=True, path=str(lib))
```
- `elfcheck.ANDROID_MACHINES = {"android-arm64": EM_AARCH64, "android-x86_64": EM_X86_64}`; gamefixture's `MACHINES`
  (gamefixture.py:35-38) becomes it.
- What it catches that today's check passes: a `libc.so.6` in `DT_NEEDED` (`android=True`), and a library whose
  `dol=` is not the one built in (`dol=`).

### 5.6 The call sites: compiling, linking, FAIL lines and progress

`main()`'s two loops become functions that `main()` calls, so tests reach the very lines a build prints:
- **`compile_units(prof, cprof, out, units, optimize, progress) -> collections.Counter`** is today's
  recompile.py:769-784, with its FAIL line from `fail_reason(proc)`.
- **`run_plan(plan, prof, out, exe, progress) -> int`** is today's recompile.py:868-907, with each `[build]` line
  from `progress_label()` and each mod's FAIL line from `fail_reason()`.
- **`fail_reason(proc) -> str`:**
  ```python
  text = (proc.stdout or "") + (proc.stderr or "")
  errs = [ln for ln in text.splitlines() if "error" in ln.lower()]
  return errs[0] if errs else text[-300:]
  ```
  The compile's FAIL line read stdout alone (recompile.py:781-782), where clang writes nothing; so every gnu
  profile's compile failure, the players' mingw build included, gave no reason.
- **`progress_label(cmd, cwd, out, exe) -> str`:** `link` for the command whose `/Fe` is the exe or
  `<out>/libsoa_game.so`; `mod <folder>` for a mod's; `stub <name>` for one whose `/Fe` is under `<out>/stub`;
  `decompiled units` otherwise. Today both Android links print `decompiled units` (recompile.py:868-874), a line
  Setup's bar ignores.

### 5.7 The record says what made it (R5b)

`seam.record(no_decomp, baked, dol_sha1="", profile="", made_by=None)`. `made_by` is an optional mapping, appended in
this order after `profile=`:
- `package=<player_build.package_version()>`;
- `cc=clang-<X.Y.Z>`, parsed from `compiler_id` by `clang version (\S+)`, else `cc=<the line's sha256[:12]>`;
- `sysroot=<sysroot_digest(VENDOR)[:12]>`.

**Values:** each has its spaces made `_` and is cut at 64 characters. **Only Android builds pass `made_by`.** The
APK's own record, `seam.record(True, baked)` from android.py:126, is unchanged.

**No cap check, and why it is not needed.** The phone reads a record's first 511 bytes (`RECORD_CAP`,
elfcheck.py:40-42), and `abi`, `mode`, `baked` and `dol` must be inside them. They come before every new key, and the
cut bounds the rest: `abi=1` (5), ` mode=no-decomp` (15), ` baked=` and 64 (71), ` dol=` and 40 (45),
` profile=android-x86_64` (23) make 159 bytes, the arm64 one 158; ` package=` (73), ` cc=` (68) and ` sysroot=`
(21) at most bring it to 321. The draft's cap could never fire (§11 F6). The test holds the bound, with the cut
taken out as its mutation (§8.2).

---

## 6. The player's build, the package, Setup's check, the guard, `push-game`

### 6.1 `tools/player_build.py` (R5b)

```
python tools/player_build.py --disc <image> --root <folder> [--rebuild] [--target windows] [--target android-arm64] [--target android-x86_64]
```

**Targets and order.**
- `TARGETS = ("windows", "android-arm64", "android-x86_64")`; `--target` is `action="append"`. None given means
  `["windows"]`: today's behaviour, unchanged.
- One run goes: the disc check; **the Android preflight** (when an Android target is asked for); the sysroot, built
  when it is not there; the extraction; then each target once, in the order given.
- `android-x86_64` is the emulator's target, for the owner and tests. Setup never passes it.

**The preflight, `android_preflight(root, targets) -> str | None`.** Read-only, right after `[build] check`, so a
refusal comes in seconds, before the extraction and before the Windows target, with nothing written:
1. **The sysroot or its sources.** When `fetch_android_sysroot.verify(SOURCE / "vendor")` finds nothing and the record
   is `expected_record()`, the tree is there. Otherwise the 44 build and ship files in
   `SOURCE/vendor/android-sysroot-src` must be whole and on their pins (`cache_problems`).
2. **The compiler.** `toolchain.mingw_clang()` is there, and `mingw_identity_problem()` finds nothing. (Not
   `compiler_path(profile)`, which needs the tree this run may be about to build.)
3. **The space.** `shutil.disk_usage` of the nearest folder of `root` that exists, since `root` may not yet. The need
   is the sum, over the Android targets asked for, of `max(ANDROID_FREE - <the size of root/gen-<target> now>,
   RELINK_FREE)`: a translation frees its old folder first, and a relink needs only the link's temporary output and
   the stubs. `ANDROID_FREE` is planned at 384 MiB (the map's 146 MB `gen/` and the 34 MB library, about twice over)
   and set in R5b from the measured peak drop in free space; `RELINK_FREE` is 64 MiB. Windows' space stays Setup's
   (`NEED_FREE`), as today.
4. An `OSError` on the way is a refusal in words, never a traceback.

A refusal prints `[build] android failed: <words>` and exits 1, and **stops every target, Windows too**: the player
asked for both, and Setup can then say within seconds why, and that unticking the box builds Windows alone (§1.3).

**The words.** In a package (`package_version() != "checkout"`), the player's, with no developer command in them:
- the sources: `this package's Android files are not as it shipped them (<path>): extract the package again, into a
  new folder`;
- the compiler missing: `this package's compiler is missing (toolchain\bin\clang.exe): extract the package again,
  into a new folder; if Windows Security removed it, Virus & threat protection > Protection history shows it`;
- the compiler's identity: `this package's compiler is not the one it shipped with (<its line>): extract the package
  again, into a new folder`;
- the space: `the Android build needs about <n> MB free in <root>, and there are <m> MB: free some space and build
  again`.

In a checkout, the developer's: the tool's own facts with `python tools/fetch_android_sysroot.py` (or
`python tools/fetch_mingw.py`) after them.

**The sysroot, built when it is not there.** `[build] android sysroot`, then `python
<SOURCE>/tools/fetch_android_sysroot.py --offline` as a process, its lines relayed indented as recompile's are
(player_build.py:173-178). It reads only the package's own sources and runs the package's own clang. A failure prints
`[build] android failed: the Android files could not be built here (<its first error line>): extract the package
again, into a new folder, and send build\setup.log with any report`, exit 1; in a checkout, the tool's error line and
`python tools/fetch_android_sysroot.py` instead. In a package it happens once, on the first Android build;
afterwards the preflight finds the tree. A tree that was damaged since is rebuilt the same way.

**Per Android target:**
- **Its gen folder:** `<root>/gen-<target>`.
- **Never stale.** The record is `<gen>/build-inputs.txt`, today's format (player_build.py:135-152): `inputs_record()`
  (BAKED, read with CRLF as LF since R5-0) merged with `identity(target)`, whose entries are named `package`,
  `compiler`, `cflags` and, for Android, `sysroot`:
  - `package`: sha256 of `package_version()`;
  - `compiler`: sha256 of `toolchain.compiler_id(<the target's profile>)`;
  - `cflags`: sha256 of the target profile's declared compile flags, as `build_inputs.txt` has them (§5.3);
  - `sysroot`: `fetch_android_sysroot.sysroot_digest(SOURCE / "vendor")`.

  A change to any is a moved input, named in `[build] android translate: package, compiler`. The Windows target
  gains `package`, `compiler` and `cflags` too, as distribution §3.8 asks, so the first build of an R5b package over
  an older folder translates once more. That is §3.8's rule, not a regression.
- **`package_version(source=None)`:** the stripped text of `SOURCE/VERSION`, which `package.py` writes; `checkout`
  in a clone.
- **`build(root, gen, retranslate, target)`:** today's command (player_build.py:157-168) with `--cc <the target's
  profile>`. `--reproducible` stays mingw's. Every `[build] …` line recompile prints is relayed as
  `[build] android …`.
- **`install_android(root, gen, target) -> str`:** copies `gen/libsoa_game.so` to `<root>/libsoa_game.so` for
  `android-arm64`, or `<root>/libsoa_game-x86_64.so` for `android-x86_64`, and returns the copy's sha256. recompile
  has already run the phone's check (§5.5).
- **The end:** `[build] android done <file> sha256 <hex>`; a failure, `[build] android failed: <why>` (for a compile,
  `the compile of <unit> failed; the lines above say why`).

**The lines** of a package's first two-target run:
```
[build] check
[build] android sysroot
  44 of 44 bionic files the build reads, at 06356e41 (android-17.0.0_r1), are as pinned
  …
[build] extract
[build] translate: <why>
[build] 1/19 dispatch.c
… [build] link, [build] mod …
[build] done soa.exe sha256 <hex>
[build] android translate: <why>
[build] android translate
[build] android 1/19 dispatch.c
…
[build] android stub libc.so
…
[build] android link
[build] android done libsoa_game.so sha256 <hex>
```
`[build] android translate: <why>` appears only when the record moved; the bare `[build] android translate` is
recompile's own.

**Exit codes:** 0, every target asked for was built; 1, a step failed, and the log names the target (a failed
preflight stops all of them before any work); 2, the disc was refused. The module docstring says this
(player_build.py:26-29).

### 6.2 `tools/package.py`

- **`TOOLS`:** `("player_build.py", "recompile.py", "extract.py", "decomp.py", "fetch_gpu.py", "fetch_sdl.py",
  "fetch_android_sysroot.py")`: `fetch_sdl.py` in R5-0, `fetch_android_sysroot.py` in R5b.
- **`stage_source(source, ver=None)`** (R5-0): the copying of `runtime/`, `config/`, `tools/soa`, `TOOLS`, `TOP` and
  the mods' text, out of `stage()`, which calls it. In R5b it also writes `source/VERSION`: `ver` and LF, no suffix,
  under no forbidden folder. The import test calls this very function (§8.2).
- **`stage(dest, ver=None)`.** `ver` is `version()` when None (package.py:199-211).
  - Before anything (package.py:149-151): `fetch_mingw.verify(VENDOR) + fetch_gpu.verify(VENDOR) +
    fetch_android_sysroot.cache_problems(VENDOR / "android-sysroot-src", roles=("ship", "build"))`.
  - Then `stage_source`, `stage_vendor`, `licenses`, and Setup last, as today.
- **`stage_vendor(vendor, dest)`.** The GPU folders and record as today (package.py:169-171), then
  `fetch_android_sysroot.stage_sources(vendor / "android-sysroot-src", dest / "android-sysroot-src")`: exactly the 44
  build and ship files, each held to both pins, never `copy_tree` (which drops every path through a folder named
  `include`, package.py:83, :135), never the check files.
- **`licenses(dest)`.** `LICENSE_COPIES` as today. `android-sysroot.txt` is `notice_text()` of the staged sources,
  held to `OUTPUTS["NOTICE.txt"]`. `LICENSE_URLS` gains `linux-gpl-2.0.txt` and `linux-syscall-note.txt` (§2.10).
  Every fetch, the CPython zip's included (package.py:86-98), goes through `fetch_android_sysroot.fetch()`, with its
  retries and its words.
- **`python tools/package.py check <package folder> [--commit REV]`** (R5-0, extended in R5b):
  - the package's baked inputs, `player_build.inputs_record(<folder>/source)`, against the commit's, read with
    `git ls-tree -r --name-only REV -- <BAKED>` and `git cat-file blob REV:<path>`, both read with CRLF as LF.
    Equal: `baked inputs of <folder>\source: <12 hex>, and of <rev>: <12 hex>, the same`. Not: the first path that
    differs, with `(… the checkout converted its line endings?)` when the two differ only in CR, exit 1;
  - R5b: when the folder's name is `soa-<ver>-windows-x64`, `source/VERSION` must hold `<ver>`.
- **`deepest(folder)`** returns `max(<the longest path under folder>, BUILD_DEEPEST)`. `BUILD_DEEPEST` covers what a
  build writes, each under the longest name its tool writes it:
  - `gen-android-x86_64/stub/libsoa_runtime.so`, 41 characters, and lld's 11-character temporary suffix: 52
    [I: LLVM's output buffer];
  - `source/vendor/` and `fetch_android_sysroot.longest_written()`: 14 + 73 = 87.

  So 87 [V count]. The docstring says so, and `test_setup.py`'s expectation follows (§8.2). Today the toolchain's
  libc++ header, at 90, is deeper still; the floor holds if that ever goes.
- **`build_zip(out, ver)`** passes `ver` to `stage`.
- **Unchanged:** `MINGW.sha256` is still not staged (map §5.2): out of R5. The module docstring's list gains the
  sources and the three texts.

### 6.3 Setup's check

- **`setup.c`'s `PACKAGE`** (setup.c:65-66) gains
  `L"source\\vendor\\android-sysroot-src\\libc\\arch-common\\bionic\\crtbegin_so.c"`. test_setup.py's mirror
  (test_setup.py:43-48) gains it too, which `test_the_lists_here_are_setup_cs` holds. A package without the sources is
  then `CHECK_INCOMPLETE`, and the release workflow's `Setup.exe --check` refuses it before any draft.
- **`SETUP_DEEPEST`** stays measured by `package.deepest()`, never below 87 now.
- **`NEED_FREE`** stays 2 GB for Windows. R5c adds `ANDROID_FREE` and the space rule (§1.3).

### 6.4 `release.yml`

§7.3.

### 6.5 `.gitignore` and the guard (R5b)

- **The gap.** `gen/` in `.gitignore` and `gen` in `FORBIDDEN_DIRS` match only a folder named exactly `gen`
  (guard.py:201-208); `.so` is refused by the guard but not ignored. A `--root` inside a checkout and outside `build/`
  would leave `gen-android-arm64/` with translated chunks of 1.6 to 2.0 MB, under `MAX_TRACKED_BYTES` (guard.py:162),
  which `git add -A` stages and no rule refuses; `disc_sys.c` alone is caught, by its marker [V `git check-ignore`;
  the reviewers' sizes: `chunk_001.c` 1,632,132 B, `chunk_014.c` 1,979,255 B]. Once pushed, history keeps it for good
  (CLAUDE.md).
- **`.gitignore`** gains, under "# build": `gen-*/`, `*.so` and `*.apk`.
- **`guard.py`:** `FORBIDDEN_DIR_PREFIXES = ("gen-",)`; `forbidden_dir()` refuses a component that is a forbidden
  name or starts with one of these, in any case. No path any commit has touched has such a component [V `git log
  --all --name-only`, at 6d5916c], so `--history` stays clean.
- **CLAUDE.md's** "refuses 49 extensions, 18 directory names" and ci.yml's "the eighteen directory names guard.py
  refuses" gain "and any `gen-…` folder".

### 6.6 `android.py push-game` holds the library to the APK (R5b)

- After choosing the library and before `put()`, `cmd_push_game` (android.py:264) runs
  `elfcheck.verdict(lib, machine=<the device's ABI's>, exports=apk_exports(), libc=apk_libc(), record=apk_record(),
  dol=apk_dol(), android=True)`.
  - `ok`: it prints `checked <lib> against the app this PC built: ok` and pushes.
  - Anything else: `<lib>: the app this PC built would refuse it: <the words>`, exit 1, nothing pushed.
- `apk_exports()` and `apk_libc()` read `generated/runtime_seam.c`'s `soa_runtime_exports[]` and
  `soa_runtime_libc[]`, as `apk_record()` reads its record (android.py:392-404): what the APK was built with, not
  this tree's.
- Why: before the Thor session (D-36) nothing on the PC held the library to the APK; a `baked=` that differed would
  first show on the phone (§11 P14).

---

## 7. CI

### 7.1 A job of its own for the route, on Ubuntu and on Windows (R5a)

Players build on Windows, where `clang.exe` is llvm-mingw's wrapper, the sysroot's path is `C:\…` and
`runtime/elfcheck.c`'s driver is built with MSVC. Until now `test_android_build.py` ran in both Tests jobs wherever
the runner's NDK was found [V ci.yml:69-90; ubuntu-latest sets `ANDROID_NDK_HOME`; windows-latest too, I]. With the
`route` marker those tests skip in the Tests jobs, which have no llvm-mingw and no sysroot, so they move here, on both
systems. A job of its own also keeps a googlesource outage from turning the `mingw` job's runtime compile red.

```yaml
  # R5 (specs/android.md 3.4): the game library for Android as a player's PC builds it -- llvm-mingw's
  # clang and this repository's own sysroot, built from bionic's pinned sources, the stub C libraries from
  # config/seam.txt -- a game of two functions, checked by tools/soa/elfcheck.py and by runtime/elfcheck.c
  # (gcc on Ubuntu, MSVC on Windows, which players build on), which must agree. A skip is a failure here.
  android-route:
    name: The Android game library through R5's route (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    steps:
      # the files as git stores them: the runner's Git turns LF into CRLF on Windows (R5-0)
      - name: No line-ending conversion
        run: git config --global core.autocrlf false
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"

      - name: Install
        run: python -m pip install --upgrade pip pytest

      - name: llvm-mingw, pinned and verified
        run: |
          python tools/fetch_mingw.py
          python tools/fetch_mingw.py --verify

      - name: The compilers the checks use
        shell: bash
        run: |
          python -c "import sys; sys.path.insert(0, 'tools'); from soa import toolchain; c = toolchain.mingw_clang(); print(c, toolchain.clang_id(c) if c else 'none')"
          if [ "$RUNNER_OS" = Linux ]; then gcc --version; fi

      # bionic's pinned files, cached on the pins alone (not the script's bytes or line ends), shared across
      # systems, restored by prefix when the pins move: every file is held to its pins when it is read
      - name: The sysroot's cache key
        id: key
        shell: bash
        run: python tools/fetch_android_sysroot.py --cache-key >> "$GITHUB_OUTPUT"
      - uses: actions/cache/restore@v4
        id: restore
        with:
          path: vendor/android-sysroot-src
          key: android-sysroot-src-${{ steps.key.outputs.key }}
          restore-keys: android-sysroot-src-
          enableCrossOsArchive: true

      - name: R5's Android sysroot, built from bionic's pinned sources, and verified
        timeout-minutes: 15
        run: |
          python tools/fetch_android_sysroot.py --lists
          python tools/fetch_android_sysroot.py --verify

      # saved as soon as the fetch has passed, whatever the tests after it do
      - uses: actions/cache/save@v4
        if: steps.restore.outputs.cache-hit != 'true'
        with:
          path: vendor/android-sysroot-src
          key: android-sysroot-src-${{ steps.key.outputs.key }}
          enableCrossOsArchive: true

      - name: The sysroot and the route, no skips
        if: ${{ !cancelled() }}
        env:
          SOA_CC: ${{ runner.os == 'Linux' && 'gcc' || 'msvc' }}
          PYTHONPATH: tools/citest
        run: python -m pytest -p noskip tools/tests/test_android_sysroot.py tools/tests/test_android_build.py -v
```
- **Part 1** adds the job with `test_android_sysroot.py` alone in its last step; **part 2** adds
  `test_android_build.py`.
- **The cache.** `actions/cache` saves only when a whole job succeeds, so a red run would fetch again next time; the
  split `restore` and `save` steps keep a good fetch. A cache saved on Ubuntu is restored on Windows only with
  `enableCrossOsArchive` [I: actions/cache's documentation]. A release run on a tag restores the default branch's
  caches, never another tag's [I: GitHub's documentation], so the release finds main's here.
- **The cache is not publication** [I]: Actions caches are visible to this repository's workflows alone, and evicted
  after seven days unused. D-34's "not published" holds.
- **What this settles** [I until run]: Ubuntu's llvm-mingw builds Android code (map §7.1 question 2), and its crt
  bytes equal Windows', by the output pins.
- The `mingw` job is unchanged: it compiles every runtime file for Windows.

### 7.2 The gcc leg (R5a part 2)

The step at ci.yml:418-431 becomes "The runtime compiled for the phone (the NDK), no skips". It runs only
`python tools/citest/compile_runtime.py --cc android-arm64-ndk --require-gxv --require-sdl`, with the runner's
`ANDROID_NDK_HOME`, NDK 27.3 there (map §5.3). `test_android_build.py` moves to `android-route`. Its comment loses
"the game library … built with the NDK".

### 7.3 `release.yml` (R5-0, R5b, R5c)

**R5-0.** A first step, before `actions/checkout`, `git config --global core.autocrlf false` and
`git config --show-origin --get-all core.autocrlf`, with a comment saying why. In "The guard, over the package
unzipped, and Setup's checks there", after `Setup.exe --check`:
```powershell
& "$pkg\python\python.exe" -I -c "import sys; sys.path.insert(0, r'$pkg\source\tools'); import recompile, player_build, extract, decomp, fetch_gpu, fetch_sdl"
if ($LASTEXITCODE -ne 0) { exit 1 }
python tools/package.py check $pkg
if ($LASTEXITCODE -ne 0) { exit 1 }
```
The first line is the import the package's own Python makes, the one that fails today; the second holds the
package's baked inputs to the commit's.

**R5b.** After "The GPU build files", before "Every runtime file under llvm-mingw": the cache key, `restore` (with
`enableCrossOsArchive: true` and the same prefix, no `save`: a tag's cache serves no later run), the sysroot step with
`--lists`, `timeout-minutes: 15`, and:
```yaml
      # The first step's run skipped these, having no llvm-mingw or sysroot yet; here a skip is a failure.
      - name: The Android game library through R5's route
        env:
          PYTHONPATH: tools/citest
        run: python -m pytest -p noskip tools/tests/test_android_sysroot.py tools/tests/test_android_build.py -q
```
The import line gains `fetch_android_sysroot`. Then, after `package.py check` (which now holds `source\VERSION` to the
zip's name too):
```powershell
& "$pkg\python\python.exe" "$pkg\source\tools\fetch_android_sysroot.py" --offline
if ($LASTEXITCODE -ne 0) { exit 1 }
& "$pkg\python\python.exe" "$pkg\source\tools\fetch_android_sysroot.py" --verify
if ($LASTEXITCODE -ne 0) { exit 1 }
```
That is the player's own path on GitHub's Windows machine: the package's Python and clang build the sysroot from the
package's sources, offline, held to the pins. It writes into the unzipped check folder, after the guard has run, and
never into the zip.

**R5c.** `& "$pkg\Setup.exe" --check --android`, beside `--check`.

---

## 8. Tests

Counts move. **Measure, never derive** (§8.6).

### 8.1 `tools/tests/test_android_sysroot.py` (new)

Each check, with the mutation that shows it can fail:

| # | Test | Holds | Mutation that fails it | Needs |
|---|---|---|---|---|
| 1 | `test_the_pins_are_bionic_s_files_at_one_commit` | 47 `SOURCES` (30 ship, 14 build, 3 check); 40-hex `COMMIT` and blobs, 64-hex sha256; `SHIP`'s places all under `usr/include/`, 23 common + 3 arm64 + 4 x86_64; no shipped place, nor the record's or `NOTICE.txt`'s name, has a forbidden suffix (`guard.forbidden_suffix`); the check files are neither shipped nor built; `cache_key()` moves with a pin and with nothing else | a `SHIP` place renamed `…/x.map.h`; a pin with 63 hex digits; a key over the script's bytes | nothing |
| 2 | `test_a_file_that_is_not_its_pin_is_refused_and_nothing_written` | `sources()` with an injected `get` serving a tar.gz whose one member is a byte off (`SOURCES` patched to a test table) raises with the path and both digests; with the bytes right and the blob pin a digit off, raises with both blob ids; the cache lacks that file, `android-sysroot/` does not exist | the sha256 check removed; the blob check removed | nothing |
| 3 | `test_a_pinned_file_missing_from_its_archive_is_named` | the refusal names the URL and the path, in words that are not a pin's | the missing-member check removed | nothing |
| 4 | `test_the_server_s_answers_are_waited_on_retried_or_given_up` | two 429s with `Retry-After: 7`, then 200: waits 7 and 7, plus the pace; `Retry-After` an HTTP date 30 s ahead: waits 30; 86400: waits 300; a 503 then a 200; a 200 whose gzip is cut short, then a good one: the "broken or non-archive" words, never pin words; six 429s: the give-up words naming `--from` and `--offline`; a `URLError` twice then a 200; a `URLError` always: "cannot reach"; a clock past `DEADLINE`: gives up without the wait | no retry; `Retry-After` ignored; the date form unread; no cap; a decode failure not retried; no deadline | nothing |
| 5 | `test_a_404_is_not_tried_again` | one request, the 404 words | a 404 retried | nothing |
| 6 | `test_a_whole_cache_makes_no_request_and_a_bad_tree_is_rebuilt_from_it` | `sources()` over a complete test cache with a `get` that raises returns it; one file removed and `offline=True`: the words name it; one file a byte off, online: fetched again; `ensure()` over a tree not as recorded calls `build()` (patched) with `get` raising; over a verified tree, calls neither | `offline` ignored; the cache's own pin check removed; `ensure()` taking any record as "there" | nothing |
| 7 | `test_verify_names_a_changed_byte_a_missing_file_and_an_unrecorded_one` | the three facts, in that order, with no advice in them; the summary's count | the unrecorded-file walk removed | nothing |
| 8 | `test_a_record_from_another_script_is_not_this_one_s` | a record whose crt line differs from `expected_record()` is named | the record-to-pins comparison removed | nothing |
| 9 | `test_the_crt_objects_are_the_pinned_ones_in_any_folder` | `build_crt` from the cache into a folder whose name holds a space and a comma: each output equals `OUTPUTS`; `extra=("-O0",)` is refused, naming `crtbegin_so.o`; `clang_id` patched to clang 19's line: refused before anything is built | the output pins removed; the identity check removed | llvm-mingw, the cache |
| 10 | `test_the_notice_holds_each_file_s_own_words` | for each shipped and crt file, its section heads with its place and holds its leading comments verbatim; `strings.h`'s holds "advertising materials"; the preface names `licenses/llvm.txt`, `linux-gpl-2.0.txt` and `linux-syscall-note.txt`, and no line numbers; two runs give the same bytes; `build()` refuses a notice one byte off its pin | first-comment-only extraction; the NOTICE's pin check removed | the cache |
| 11 | `test_the_sysroot_is_the_closure_of_what_the_game_includes` (part 2) | for each Android profile, `clang -fsyntax-only -H` (one header a line on stderr, each path whole, spaces kept) of a unit including `cpu.h`, `soa_game.h`, `<stddef.h>` and `<stdint.h>`, with its flags, against `android_sysroot()`, reads exactly that ABI's headers, and the two together are `SHIP`'s 30; a copy of `runtime/` whose `cpu.h` adds `#include <stdlib.h>` fails, naming `stdlib.h`; a `SHIP` entry no compile reads is named unused. The `-H` parser is held on its own to a path with a space in it | either half removed; the parser splitting on spaces | llvm-mingw, the sysroot |
| 12 | `test_the_seam_s_c_library_names_are_bionic_s` (part 2) | each `seam.txt` `libc` name is in the `LIBC` block of the list `seam.BIONIC_LIBM` places it in (`libc.map.txt` or `libm.map.txt`), with `introduced=` at most 33 | `BIONIC_LIBM` without `sqrt`; a seam copy naming `fmaa` | the check lists (`--lists`) |
| 13 | `test_a_stop_inside_the_swap_leaves_no_record` | the rename patched to raise after step 3's first rename: no record, and the next `ensure()` rebuilds; `PermissionError` twice then success: done; always: the words, exit 1, no traceback | the record deleted last instead of first; no retries | nothing |
| 14 | `test_the_tool_runs_as_a_package_runs_it` | `python -I tools/fetch_android_sysroot.py --verify --vendor <tmp>`, from `tmp_path`, imports `soa.toolchain` and prints its summary line; a copy of the script without its `sys.path` line fails with `No module named 'soa'` | the `sys.path` line removed | nothing |
| 15 | `test_the_environment_cannot_reach_the_crt_build` | `CPATH` naming a folder whose `asm/unistd.h` holds `#error poisoned`: the crt objects are still as pinned | `clean_clang_env()` not passed | llvm-mingw, the cache |
| 16 | `test_compare_names_an_object_that_differs` (part 2) | `--compare`'s function on a unit holding `#include "cpu.h"` and `double g(double x) { return sqrt(x); }`, against the sysroot and a copy of it: `1 of 1 objects identical`; against a copy whose `math.h` ends with `#define sqrt(x) ((x) * 2.0)`: the unit named, exit 1 | a comparison that always says identical | llvm-mingw, the sysroot |
| 17 | `test_upstream_s_listing_is_held_to_the_pins` | `check_upstream(get=…)` over an injected tag and listings: all equal, the 47 line; one blob changed, named; a tag that peels to another commit, named | the comparison removed | nothing |
| 18 | `test_a_package_gets_the_44_sources_and_nothing_else` (R5b) | `stage_sources` from a test cache holding the 44, the two lists, `linux/version.h` and a stray `.build/x`: exactly the 44 are copied, `libc/include/` among them; one a byte off is refused; `longest_written()` equals the longest `android-sysroot.new/` place in `SHIP` | copying the whole cache; `copy_tree` | nothing |

Checks 9, 10, 11, 12, 15 and 16 skip, saying which thing is missing; they run with no skips in CI's `android-route`
job and in the release workflow.

### 8.2 Changed modules

**`test_android_build.py`** (part 2):
- **Its docstring and marker.** The docstring says the route. The `ndk` marker becomes `route`:
  `compiler_path(ANDROID_ARM64) is None`, with the reason "no llvm-mingw or no Android sysroot (python
  tools/fetch_mingw.py, then python tools/fetch_android_sysroot.py)".
- **Kept:** `test_a_mistyped_ndk_is_no_ndk_and_the_places_are_named`, with `ANDROID_ARM64_NDK`: the NDK lookup stays
  for the runtime's check and `android.py sdk()`.
- **New, needing no compiler:**
  - `test_without_llvm_mingw_or_the_sysroot_the_build_says_where_it_looked`: `android_sysroot` patched to None,
    `SOA_MINGW` to a missing folder; `compiler_path` is None, and `android_places()`'s lines name each place. Its
    mutation: one place left out.
  - `test_an_android_build_with_no_compiler_says_so_before_it_reads_anything`: `recompile.main()` with
    `--cc android-x86_64 --link --dol <a tmp file> --no-embed --out <tmp>`, a `build_inputs.txt` there naming another
    compiler, and `SOA_MINGW` an empty folder: exit 1, the looked-in lines, never the stale-link words. Its mutation:
    the lookup after the record comparison.
  - `test_the_game_library_never_looks_for_an_ndk`: `android_ndk` patched to raise; a fake llvm-mingw bin and
    sysroot in `tmp_path`.
  - `test_every_android_link_names_its_c_libraries_after_its_objects`: in `android_link_plan`, the stub commands
    carry `-nostdlib` and `-Xlinker --version-script=…*.vers`, never `-Wl,--version-script`; the stand-in and the
    game end with `-nodefaultlibs -lm -ldl -lc` after every object and `-l:libsoa_runtime.so`; every SONAME is
    exact; `stubs=False` leaves out exactly the three stub commands. Its mutation: the stand-in without `p.linker`.
  - `test_the_stubs_are_seam_txt_s_in_bionic_s_places`: `c_library_names`, the `.vers` text with the empty `libdl`,
    and the C text.
  - `test_the_post_link_check_is_the_phone_s`: `elfcheck.problems` captured: `android=True`, `dol=`, and AArch64's
    machine for a `dataclasses.replace`d arm64 profile.
  - `test_a_failed_compile_says_why_from_stderr`: `compile_units` with `toolchain.cc` patched to return a
    `CompletedProcess` whose stderr alone holds `x.c:1:1: error: boom`; the printed line is
    `  FAIL chunk_000.c: x.c:1:1: error: boom`. Its mutation: the call site reading stdout alone.
  - `test_the_android_link_steps_say_what_they_build`: `run_plan` over `android_link_plan`'s plan with `toolchain.cc`
    patched: `[build] stub libc.so`, `[build] stub libm.so`, `[build] stub libdl.so`,
    `[build] stub libsoa_runtime.so`, `[build] link`, in order. Its mutation: the old label loop.
  - `test_an_android_command_runs_without_clang_s_search_variables`: `cc()` with `compiler_path` and
    `subprocess.run` patched, `CPATH` and the rest set: the environment it passes holds none of them. Its mutation:
    `env` not passed.
- **New, building fixtures:**
  - `test_the_stubs_export_seam_txt_s_names_and_no_other`: through the whole plan; `elfcheck.read` of
    `stub/libc.so`, `libm.so` and `libdl.so`: the SONAME and the exports.
  - `test_a_call_outside_the_seam_fails_the_link`: `extra` calling `strlen` raises with `undefined symbol: strlen`.
  - `test_the_post_link_check_refuses_a_linux_library`: the fixture with `needed=("libc.so.6",)` gets "built for Linux
    (it needs libc.so.6)" from `post_link_problems`. Its mutation: `android=False` there.
  - `test_the_fixture_is_built_by_recompile_s_own_plan`: a spy on `recompile.android_link_plan`, called once, with
    `units=[<d>/game.c]`; the first build of a key runs the stub commands and a second does not.
  - `test_a_folder_with_a_comma_and_a_space_builds`: the fixture in `tmp_path / "Skies, the game"` passes the phone's
    check. Its mutation: `-Wl,--version-script=` back in the stub command.
  - `test_the_environment_cannot_reach_the_game_s_compile`: `CPATH` naming a folder whose `math.h` holds
    `#error poisoned`; the fixture builds. Its mutation: `cc()`'s clean environment taken out.
- **MUTANTS:** "built for 32-bit ARM" becomes `{"arm32": True}`, made by `gamefixture.arm32_library(d)`.
- **The settings:** `POST_LINK` becomes `NO_DOL = {**PHONE, "dol": None}`. So the NULL-`dol` branch of both checkers
  (elfcheck.py:212, the C driver's `-`) stays held to each other, which TESTING.md:92's claim needs. "The settings
  differ where they should" (test_android_build.py:362-367) compares phone and desktop (`{a Linux library}`) and phone
  and no-dol (`{another disc's executable, no executable named, a record past 511 bytes}`).
- **R5b adds** `test_the_record_says_what_made_the_library`: the order `profile= package= cc= sysroot=`; a
  600-character `VERSION` gives a 64-character `package=` and a record of at most 321 bytes whose `dol=` is inside
  `RECORD_CAP`; and `elfcheck.verdict` unchanged by the new keys, in both checkers (a fixture library carrying them
  joins the C-and-Python agreement test). Its mutation: the cut taken out.

**`gamefixture.py`** (part 2):
- `build()` writes the stubs with `seam.write_android_stubs`, writes `empty.c` when `needed`, and runs
  `recompile.android_link_plan(p, d, units=[d/"game.c"], …)` through `_cc`. `recompile` is imported in the function, as
  `player_build` is (gamefixture.py:184).
- **The C stubs are built once a session per profile.** `_BUILT_STUBS` maps (the profile's name, the sha256 of the
  three stub sources and scripts) to the first build's `stub/` folder. That build runs the whole plan; later ones
  copy its three `.so` files into their own `stub/` and run the plan with `stubs=False`. A reviewer measured 0.44 s a
  stub link on this PC; at three a build and some 30 builds a session, that saves 30-40 s of a full run. A seam
  change makes a new key.
- `arm32_library(d) -> Path` writes `arm32.c` (`int soa_arm32(void) { return 32; }`) and runs `toolchain.cc` with
  `[ARM32, "-shared", "-nostdlib", "-ffreestanding", f"/Fe{d/GAME_SONAME}", "arm32.c"]` under `ANDROID_ARM64`.
- `android_mutants`' `arm32` recipe uses it; its profile check is `toolchain.is_android(p)`.

**`test_recompile_inputs.py`** (part 2), needing no compiler:
- `test_a_link_of_objects_another_compiler_flags_or_sysroot_made_is_refused`: the same everything passes; another
  compiler, other `cflags`, another sysroot are each refused in their words; a strict record without the fields, and
  a strict folder with no record, are refused; a non-strict record without `compiler` passes, and
  `build_inputs_note` names it. An msvc record keeps exactly its two keys.
- `test_compiler_id_is_the_first_line_and_write_build_inputs_writes_it`: `compiler_path` patched to a fake path and
  `subprocess.run` to `clang version 9.9.9 (x)\nTarget: …`: the first non-empty line, cached per path; msvc's is
  `""`; `write_build_inputs` writes the `compiler` and `cflags` lines, and the `sysroot` line for Android; and
  `check_build_inputs` takes that record. Its mutation: `compiler_id` returning `""`.
- `test_the_sysroot_not_as_recorded_is_refused_before_the_build`: `android_sysroot_problem` on a tmp vendor: one byte
  changed is refused in the record's words; a record whose tree is absent names it. Its mutation: the check removed.

**`test_toolchain_profiles.py`** (part 2), two new tests:
- `test_the_android_profiles_are_the_spec_s`: the flags, copied, not imported; the linker
  `("-nodefaultlibs", "-lm", "-ldl", "-lc")`; the directories; the `-ndk` pair's names, flags, `("-lm",)` and
  directories; `recompile.cc_choices()` without the `-ndk` names.
- `test_an_android_command_carries_the_sysroot_and_an_ndk_one_does_not`: `gnu_commands`, the sysroot patched, on both
  paths (one command; a compile of two sources into a folder). Its mutation: the head dropped from one path.

**`test_mingw.py`** (part 1):
- `test_the_android_clang_is_llvm_mingw_s_own`: `SOA_MINGW` naming a folder that holds only `clang(.exe)`: no
  Android clang, never the next place; one holding both: that folder's; unset: a package's `toolchain/bin` before
  `vendor/`.
- `test_the_pinned_clang_is_fetch_mingw_s`: `toolchain.MINGW_RELEASE == fetch_mingw.RELEASE`;
  `mingw_identity_problem` with `clang_id` patched: the pinned line gives None, clang 19's gives words naming both;
  with `vendor/llvm-mingw` here, the real clang passes (skipped otherwise).

**`test_citest.py`** (part 2):
- `test_the_runtime_is_checked_for_the_phone_with_the_ndk`: `compile_runtime.main()` with `sys.argv` set to
  `--cc android-arm64` returns 1, its words naming `android-arm64-ndk`, before any compiler is looked for.
- The import-graph probes (test_citest.py:69-103) import `fetch_android_sysroot` by name beside `recompile`, since
  `recompile` now imports it lazily.

**`test_player_build.py`:**
- **R5-0:** `test_the_baked_digest_reads_crlf_as_lf`: two tmp trees, one with every file's line ends CRLF, give one
  digest. Its mutation: raw bytes.
- **R5b**, with run_main-style stand-ins and no compiler:
  - **`run_main` changes:** its `build` stand-in takes `target` and records it, and it patches
    `player_build.identity` to a constant mapping, so no unit test starts a compiler. Both tests that use it,
    `test_a_changed_input_retranslates_and_an_unchanged_one_relinks` (test_player_build.py:138-155, which keeps its
    `stale()` mutation) and `test_setups_rebuild_translates_again_when_nothing_moved` (:157-166), change with it.
  - `test_an_android_target_builds_into_its_own_folder_and_says_so`: `--cc android-arm64`,
    `--out <root>/gen-android-arm64`, the `android ` prefix, `<root>/libsoa_game.so`, the done line.
  - `test_the_targets_run_in_order_after_one_check_and_one_preflight`.
  - `test_a_new_package_compiler_flags_or_sysroot_translates_again`: each key moved in turn. Its mutation: `identity`
    returning `{}`.
  - `test_a_damaged_source_is_refused_before_the_extraction`: `[build] android failed: …` after `[build] check` and
    before `[build] extract`, exit 1, nothing under the root.
  - `test_a_damaged_tree_is_rebuilt_from_the_sources`: the sysroot step runs, and the build goes on.
  - `test_too_little_space_for_the_android_build_is_refused`: `shutil.disk_usage` patched; a root that does not exist
    yet is measured at its nearest parent; a folder with its gen already there needs less.
  - `test_a_package_says_extract_again_and_a_checkout_names_the_tool`.
  - `test_the_package_version_is_the_staged_one`.

**`test_package.py`:**
- **R5-0:** `test_the_staged_tools_import_what_the_build_imports`: `stage_source(tmp_path / "source")`, the real
  copying with `NEVER`; then `[python, "-I", "-c", <probe>]` with `cwd=tmp_path`, where `python` is the embeddable
  CPython unpacked from `vendor/` when it is there (else `sys.executable`). The probe imports every module in `TOOLS`,
  `extract` and `decomp` among them, and the test asserts each loaded module's file is under `tmp_path` or the
  interpreter's own folder. It fails on today's `TOOLS`.
- **R5-0:** `test_a_package_s_baked_inputs_are_held_to_the_commit_s`: a package source written from
  `git show HEAD:<path>` for BAKED: `check` passes; one file a byte off: refused, named; one file written with CRLF:
  passes. Skips without git.
- **R5b:** `test_the_sources_are_staged_whole_and_alone`: `stage_vendor` on a fixture vendor whose cache holds the 44,
  the two lists, `linux/version.h` and a stray `.build/x`: only the 44 under `source/vendor/android-sysroot-src`,
  `libc/include` kept; `guard.tree_problems(dest)` is empty; the same files under `source/android-sysroot-src` are
  refused for `include/`.
- **R5b:** `test_the_kernel_s_licence_texts_are_at_the_headers_version`: the tag derived from the cache's
  `linux/version.h` (`LINUX_VERSION_CODE` 398080 is v6.19) is both URLs'; 64-hex pins. Skips without the cache; runs
  in CI.
- **R5b:** `test_the_apache_text_the_notice_names_is_in_llvm_txt`: `vendor/llvm-mingw/LICENSE.TXT`'s first part is
  the Apache License 2.0 ("Apache License", "Version 2.0, January 2004", then "END OF TERMS AND CONDITIONS", before
  LLVM's exceptions). Skips without `vendor/llvm-mingw`.
- **R5b:** `test_the_package_says_its_version`: `stage_source` writes `source/VERSION`, the version and LF.
- **R5b:** `test_a_stage_refuses_sources_off_their_pins_before_writing`: `stage()` with `fetch_mingw.verify` and
  `fetch_gpu.verify` patched to `[]`, and a cache whose one file is a byte off: `SystemExit` naming it, and the
  destination still empty. Its mutation: the cache check taken out of `stage()`.
- **R5b:** `test_the_deepest_floor_covers_the_build_s_own_outputs`: `BUILD_DEEPEST` is at least 52 and at least
  14 + `longest_written()`.

**`test_setup.py`:**
- **R5b:** `PACKAGE` gains the sentinel; `test_package_leaves_room_for_the_deepest_file` expects
  `package.BUILD_DEEPEST` (87) where it expected 40 (test_setup.py:64).
- **R5c:**
  - `test_the_android_box_adds_both_targets` (`--show-build`, with and without `--android`);
  - `test_the_bar_never_goes_back_with_android` (`--bar --android` over a recorded line set: never down, 60 at the
    Windows `done`, 100 at the end). Its mutation: no phase map;
  - `test_the_status_says_what_this_run_built`: one recorded log per row of §1.3's table, through `--bar --android
    --exit N`. Its mutation: `on_done` by `built()`;
  - `test_a_built_folder_with_the_box_ticked_checks_the_android_space`: `--check --android --assume-free <bytes>` in
    a folder holding `soa.exe`. Its mutation: the rule ignoring the box once built;
  - `test_the_lists_here_are_setup_cs` also holds `ANDROID_FREE` to `player_build.ANDROID_FREE`.

**`test_android_tool.py`:**
- **R5a part 2:** the fake gamefixture's docstring ("which needs llvm-mingw and the sysroot").
- **R5b:** `test_push_game_refuses_a_library_the_app_would_refuse`: a Windows file (`gamefixture.windows_file()`)
  named as the library, against a fake `generated/runtime_seam.c`: refused in the phone's words, nothing pushed. Its
  mutation: the check removed. The existing push test (test_android_tool.py:267) patches the check to `ok`.

**`test_guard.py`** (R5b): `test_a_gen_dash_folder_is_refused`: `gen-android-arm64/chunk_001.c`, in any case, by
`forbidden_dir`. Its mutation: the prefix rule removed.

### 8.3 What stays untouched

`test_seam.py` (R5a part 2's and R5b's container sessions run it), and `test_mingw.py`'s existing tests.

### 8.4 The C side

No runtime C changes in R5. R5c changes `tools/setup/setup.c` alone, which is not under `runtime/`, so CLAUDE.md's
`runtime/` rows do not apply. `elfcheck.c` is unchanged: the record's new keys are ones it ignores (elfcheck.c:86,
:285-298). The rows that do apply are named in each Done: `seam.py`'s container session (R5a part 2, R5b) and
`android.py`'s APK rows (each emulator run).

### 8.5 The emulator is the test of what CI cannot run

§1.1 and §1.2 list it: the self test, the replay at 1, 2, 3 and 8 threads, the title, the ten mutants, and the
player's path, with libraries from `recompile.py` (R5a), from a package staged here and from the zip CI drafted
(R5b).

### 8.6 Counts that will move

**Measure them after each slice, on this PC, five ways:** everything (MSVC, capstone, llvm-mingw, the sysroot and its
cache present); no capstone; no MSVC; neither; and no llvm-mingw (`SOA_MINGW` naming an empty folder), which is what a
fresh clone and CI's Tests jobs see. Use the pytest plugin that hides MSVC or capstone (memory "Measure test-count
rows"). Never derive them. `grep -rn "<old number>" --include="*.md" .` finds every copy; fix every copy in the same
change.

**Where they live** [V grep at 6d5916c]:
- `docs/PLAN.md:16`;
- `docs/TESTING.md`:
  - :37 (the transcript) and :40-50, which also say "the counts below include those 41 skips", "this machine has the
    Android NDK that `test_android_build.py` wants" and "CI's Linux legs run … the Android build";
  - the install rows at :150-156, and :163 ("The 409 compiler-gated tests");
  - footnote ² at :1895;
  - the module rows: `test_android_build.py`'s at :92 ("Skips without an NDK", "`recompile.py`'s post-link check"),
    `test_recompile_inputs.py`'s at :98, `test_toolchain_profiles.py`'s at :124 ("every profile's flags … are 3.9's
    table", true only once the Android test lands), and each new or changed module's;
  - "What CI can and cannot run" at :1903, which says "Nine job runs" where ten run today, and whose table lacks the
    `mingw` job: it gains that and `android-route`;
- `HANDOFF.md:141` and `:174`;
- `README.md:376`;
- `docs/ARCHITECTURE.md:679`;
- `.claude/skills/check/SKILL.md:32` ("785 s", "nothing (409 tests want MSVC)") and `:342-357` (the count, the skips
  by module, "The 409 compiler-gated tests").

**The skips now depend on three more things** (`vendor/llvm-mingw`, `vendor/android-sysroot` and its cache): TESTING
and the skill say so, beside the fifth row.

**Counts in prose** (CLAUDE.md, "Counts in prose rot"). The tool's counts (30 headers, 35 recorded files, 44 and 47
pinned files) live in its own output and in TESTING's transcript of it. Specs, README, ARCHITECTURE and HANDOFF say
"the closure" and "bionic's pinned files" instead, and the docstring's bump instructions carry the grep.

---

## 9. Docs

### specs/android.md

**§3.4, rewritten for design 2:**
- **The profiles:** llvm-mingw's clang (the `clang` beside the mingw profile's compiler, pinned by identity),
  `--sysroot` and a clean environment added by `cc()`, and every link `-nodefaultlibs -lm -ldl -lc`.
- **The sysroot (D-31, D-34):** built where it is used, the player's PC included, by
  `tools/fetch_android_sysroot.py`, from bionic at `06356e41`/android-17.0.0_r1, each file held to its sha256 and git
  blob; the headers the game reads (named by what `cpu.h` and `soa_game.h` include: `math.h`, `setjmp.h`, `stdint.h`,
  `string.h` and what they read; `stdlib.h` only under `_MSC_VER`, cpu.h:58-59); `crtbegin_so.o` and `crtend_so.o`
  built from bionic's source and held to pins; `NOTICE.txt`; no LLVM sources, since nothing references compiler-rt or
  libunwind (§2); nothing built is published.
- **The stubs:** `libc.so`, `libm.so`, `libdl.so` from `seam.txt` at each link, version `LIBC`, bionic's placement.
- **The NDK:** the APK's runtime, and the `-ndk` compile checks.
- **The licences (D-35):** the classes of §2.5, not "BSD".
- **The player's build,** its preflight, and Setup's checkbox.

**Elsewhere in android.md:**
- **§1.5-style corrections:** `stdint.h`, not `stdlib.h`; "BSD" becomes the classes; no LLVM sources; the record's
  package version is real now (§5.7, §6.1); §3.6's "arm64-v8a alone in a release" notes that `build.gradle.kts`
  lists both ABIs until the release APK (D-33); risk 8's `cpu.h:111` becomes `:116`; research §10's direct `ld.lld`
  becomes the driver with `-nodefaultlibs`.
- **§4:** R5-0 to R5c rows. **§5:** the slices, with their Files, Done and mutations from §1 here. **§6:** D-34 to
  D-36, D-34's with its reading. **L12b:** an "as built since R5a" note on its NDK lines (android.md:601-611).
  **L12's Done:** "built through R5's route (D-36)". **The review log:** this design's findings (§0.2) and its
  reviews (§11).

### specs/distribution.md

- **R3:** a note that a package's baked inputs are held to the commit's (R5-0), and why: the release runner converted
  line endings, and since L12a the digest is in `soa.exe`.
- **R4:** a note that `TOOLS` lacked `fetch_sdl.py` from L10 to R5-0.
- **R5's header and second bullet** (distribution.md:348-357): "settled: llvm-mingw and this repository's own
  sysroot, built where it is used, the player's PC included (D-31, D-34)"; the "L12's to settle" text goes. And the
  release gate: no published release shows Setup's Android box before the release APK exists (D-33).
- **§3.6:** a `source/vendor/android-sysroot-src` row (the 44 pinned files), `source/VERSION`, and the licences row's
  three texts.
- **§3.7:** `gen-android-arm64/` and `libsoa_game.so` when Android is ticked; the sysroot built under
  `source/vendor/` on the first Android build; the space.
- **§3.8:** never stale: package, compiler, flags, sysroot; the baked inputs read with CRLF as LF; the build says what
  made it: the library's `package= cc= sysroot=`.
- **§6:** pointers to D-34 to D-36.

### TESTING.md

- **§1:** the rows of §8.2 and the new module's; the counts (§8.6).
- **§2:**
  - "The Android sysroot (R5a)": the tool's commands and lines from §1.1, `--from` for when googlesource is down,
    `--compare` for a header change;
  - the L12c recipe gains `python tools/fetch_mingw.py` and `python tools/fetch_android_sysroot.py` before
    `recompile.py --cc android-x86_64` (TESTING.md:649), with the measured times;
  - R2's player-build recipe gains `--target`; R3's gains `package.py check` and the downloaded zip's Android build.
- **§7's table:** a row for `fetch_android_sysroot.py`; `android.py` rows say "llvm-mingw and the sysroot for the
  library; the NDK for the APK"; `android.py mutants`' CI column becomes "the `android-route` job"; `push-game`
  checks the library first.
- **"What CI can and cannot run":** the job count, the `mingw` job's row and the `android-route` job's.

### Other files

- **ARCHITECTURE.md:652-660:** "`android-arm64` and `android-x86_64` (llvm-mingw's clang against this repository's own
  Android sysroot, `tools/fetch_android_sysroot.py`; the NDK builds only the APK's runtime and the `-ndk` compile
  checks)". The "fetched into `vendor/`" sentence gains bionic's sources. The count is at :679.
- **README.md:99-110:** building the game library needs `fetch_mingw.py` and `fetch_android_sysroot.py`, no NDK; the
  APK still needs Android Studio's SDK and NDK; the player section names Setup's box (R5c); the count is at :376.
- **HANDOFF.md:** the Android paragraph gains R5's state, and "next" becomes L12's Done on the Thor. The counts are at
  :141 and :174.
- **PLAN-NEXT.md:** §0 records R5-0 to R5c as they land, then "next: L12's Done on the Thor (D-36); L12g and L12h, the
  owner's order"; D-34's row gains "read as every machine that uses it, the player's PC included: the package carries
  bionic's 44 pinned files, and the player's PC builds the sysroot from them (R5b)"; C4's L12 bullet
  (PLAN-NEXT.md:663-680).
- **docs/PLAN.md:16:** the count; the "Native code compiled by CI" row says the phone's runtime is compiled with the
  NDK and the game library's route runs on a fixture under llvm-mingw, on Ubuntu and Windows.
- **CLAUDE.md:**
  - "Relink, or retranslate": `--link` still never rebuilds translated code, but `build_inputs.txt` now refuses a link
    of objects from another executable, and, for gnu profiles, another compiler or other flags, and for Android
    another sysroot or no record at all; which corrects "nothing … warns about staleness" for those.
  - The guard sentence gains "and any `gen-…` folder" (§6.5).
  - A "You touched" row:

    | You touched | Also run | Why |
    |---|---|---|
    | `tools/fetch_android_sysroot.py`, the Android profiles, `cc()` or the llvm-mingw lookup in `tools/soa/toolchain.py`, `seam.py`'s stubs, `android_link_plan`, or an `#include` in `runtime/cpu.h` or `soa_game.h` | `python tools/fetch_android_sysroot.py --verify`, then `$env:PYTHONPATH='tools/citest'; python -m pytest -p noskip tools/tests/test_android_sysroot.py tools/tests/test_android_build.py`; for a header change, `--compare`; when a library's bytes can move, the emulator: `recompile.py --cc android-x86_64 --compile --optimize --link`, `android.py build`, `install`, `push-game`, `selftest`, `replay --threads 1,2,3,8` | the sysroot holds exactly the headers the game reads, so a new `#include` fails only here and in CI's `android-route` job; only the emulator runs a library built this way |
- **The check skill:** step 5g, `fetch_android_sysroot.py --verify` and the no-skip pytest of the two modules, with
  what it needs and its time, measured; the counts and the skips.
- **FINDINGS:** one entry per slice, giving what was measured, what was found, what was not measured, and the counts.

---

## 10. Risks, and what is not measured

| # | Risk | Where it fails, if it does | Answer |
|---|---|---|---|
| 1 | An arm64 library from llvm-mingw has never run on a device: clang 23's code, RELR, AOSP-built crt objects, `LIBC`-versioned seam stubs, the 4-byte ident note [V map §3.7] | the Thor, at L12's Done | D-36 makes that session the proof; `push-game` checks the library against the APK first. x86_64 has run on the emulator (the gate). The arm64 crt objects are compared with NDK r28c's by structure before they are pinned. If RELR fails, `-Wl,--pack-dyn-relocs=none` in `_ANDROID_LINK`, one line, then both proofs again [I low risk]. |
| 2 | Ubuntu's llvm-mingw gives other crt bytes than Windows' [I identical: same release and commit, no host in the objects] | CI's first `android-route` run, at the output pins | Measured in R5a part 1, on both systems. If they differ, pins per host (as fetch_sdl's per-host record), and FINDINGS says why. |
| 3 | googlesource rate-limits or is down; no fetch from GitHub's runners has been measured (developers and CI, never players) | the sysroot step | Four requests on a build's path, paced 2 s apart; retries for every transport failure, `Retry-After` honoured, one deadline; a cache keyed on the pins, shared across systems and restored by prefix; `--from` a bionic checkout; `--offline` from a copied cache. A CI run red from an outage is re-run, never skipped. |
| 4 | A new `#include` in `cpu.h` or `soa_game.h` | the PC's compile (`'stdlib.h' file not found`), check 11, CI | By design: pin the new headers (`--check-upstream`), `--compare`, then the emulator again. |
| 5 | A new C-library call in translated code or `cpu.h` | the PC's link (`undefined symbol`) | Add it to `seam.txt` in bionic's place (check 12), rebuild the APK (its allowlist), re-prove. |
| 6 | A new llvm-mingw release | the identity check and the crt output pins, on every machine | By design: bump `fetch_mingw.RELEASE` and `toolchain.MINGW_RELEASE`/`MINGW_CLANG` together (a test holds them), derive the new pins, re-run R5a's emulator checks. |
| 7 | The licence texts are a legal reading [I] | the owner's look (R5b) | D-35 accepted the classes. The NOTICE is each file's own words, verbatim, plus the texts they name. |
| 8 | A package built since L10 cannot import `recompile.py` [V] | any player's build from such a package | Fixed first, in R5-0, with a test that runs under the package's own Python and a release step. Every draft since L10 has had it; none was published [I: the owner publishes]. |
| 9 | A package built by CI bakes the runner's line endings [V] | a phone refusing a CI package's library as another release | Fixed in R5-0: the digest reads CRLF as LF, the release runner does not convert, and every release is held to the commit's baked inputs; R5b builds from a downloaded CI zip and runs it on the emulator. |
| 10 | The player's PC builds the sysroot (new work on the player's PC): a quarantined `clang.exe` or a damaged source | the preflight, or the sysroot step, in seconds | Refused in player words before any work; the Windows build is untouched when the box is unticked. The tree is held to the same output pins as anywhere. |
| 11 | The Android `gen/` and library need more space than planned | the preflight, Setup's check | R5b measures the peak drop; `ANDROID_FREE` comes from it, mirrored in Setup. |
| 12 | The x86_64 emulator reads the clock through the PIT (about 9 fps) | speed only | No speed is measured there (TESTING.md:677-683). |
| 13 | `.note.android.ident` is 4 bytes, where the NDK's is 132 | crash tooling such as debuggerd's tombstones [I] | Bionic's loader at the commit reads only `NT_ANDROID_TYPE_PAD_SEGMENT` [V map §2.4]. Tombstones are not tried. |
| 14 | A future atomic on arm64 | the PC's link, naming `__aarch64_…` | Add `-mno-outline-atomics` then (the `cflags` record makes every `gen/` retranslate), and re-prove. |
| 15 | `baked=` moves with every edit to `recompile.py` | every emulator run after a slice | Each slice's emulator run starts with `android.py build` and `install` (§1). |
| 16 | A folder name with a comma, a space or a long path | the stub link, the crt build, Setup's depth check | `-Xlinker` for the one path-carrying linker argument; tests in folders with a comma and a space; `BUILD_DEEPEST` counts the build's own outputs and temporary names. |

**Not measured, and not claimed:**
- an arm64 library built this way on any device (the Thor, D-36);
- Ubuntu's and Windows' runners building Android code, and their crt bytes (R5a part 1's CI run);
- a fetch from googlesource on GitHub's runners (R5a part 1's CI run records it);
- the sysroot built on the Ally X (R5c's owner run);
- Setup with the box ticked on a Steam Deck under Proton [I: it works as the Windows build does];
- debuggerd reading the ident note;
- an llvm-mingw bump;
- the release APK, which waits for D-33.

---

## 11. Review decisions

Four reviews read the draft adversarially: **feasibility (F1-F13)**, **network (N1-N11)**, **player (P1-P18)** and
**tests (T1-T24)**, 66 problems in all. Each was checked again for this version against the code at 6d5916c, the
scratch probes, or the reviewer's own probe, before it was accepted. Several reviews found the same problem; those
rows point at the first. **Nothing was rejected outright.** Eight fixes were taken in another form than the one
proposed, or in part, each saying why: F4's `.gitattributes`, F12's parameter, N2's `git check-ignore`, P7's hidden
box, P8's `VERSION` digest, P16's Apache file, P18's shared C, and T5's whole-`main()` test.

### 11.1 Feasibility

| ID | Problem | Decision | Why, as checked | Where |
|---|---|---|---|---|
| F1 | A folder name with a comma breaks the stub link: clang splits `-Wl,--version-script=<path>` at the comma | **Accepted** | clang's `-Wl,` is documented as comma-separated; setup.c:142-148 refuses only characters outside 0x20-0x7E; the reviewer's probe in "Skies, the game (probe)" failed with `-Wl,` and passed with `-Xlinker`. No other Android `-Wl,` argument carries a path. The split build's and the APK's own `-Wl,--version-script=` take a developer's checkout path, so they stay, with a FINDINGS note | §3, §5.4; R5a part 2 mutation 13; `test_a_folder_with_a_comma_and_a_space_builds` |
| F2 | The Android compiler is whichever generic `clang` turns up first; the two profiles can resolve to two toolchains, the NDK's clang included | **Accepted** | toolchain.py:281-287 puts `<checkout>/../toolchain/bin` before `vendor/`; :364-369 requires `x86_64-w64-mingw32-clang` for mingw alone. The Android clang is now the one beside that compiler, and an Android build refuses a clang whose `--version` is not 23.1.2 at `85ac5602…`, a constant held to `fetch_mingw.RELEASE` by a test | §4.2, §5.2, §6.1; `test_mingw.py`'s two tests; check 9 |
| F3 | Run as a script under the embeddable CPython, the tool cannot import `soa.toolchain` | **Accepted** | The package's `python314._pth` holds `python314.zip` and `.` alone [V the zip]; recompile.py:46, player_build.py:42 and package.py:41 insert their own folder for this; the reviewer's probe got `No module named 'soa'` | §2; check 14 |
| F4 | A package built by the release workflow on `windows-latest` gets CRLF where git has LF, so its `baked=` is not the commit's | **Accepted**, with N1 and P1, as **R5-0** | No `.gitattributes`; Git for Windows' system configuration sets `core.autocrlf true` [V this PC's `C:/Program Files/Git/etc/gitconfig`]; 10 of BAKED's files are stored LF [V `git ls-files --eol`]; the reviewer read draft-0223b3a's zip (recompile.py 25,436 B with 589 CRLF, against 24,847 B). R3's same-bytes check (2026-10-04) predates L12a (75d5ce2), which put the digest in `soa.exe`, so it could not have seen this. Fixed three ways: the digest reads CRLF as LF, so no checkout moves it; the release runner does not convert; and `package.py check` holds every release to the commit. **Not taken:** a `.gitattributes` with `* -text`, which changes every clone's behaviour to fix one runner, where the digest's reading alone makes `baked=` independent of any checkout | §1.0, §6.2, §7.3; R5b's downloaded-zip Done |
| F5 | The release job can never restore the source cache: Linux caches do not restore on Windows by default, tags do not share caches, and `hashFiles` over a CRLF script gives another key | **Accepted**, with N3 and P17 | The cache is keyed on `--cache-key` (the pins alone), restored by prefix, with `enableCrossOsArchive` on both sides, so a release on a tag restores main's [I: GitHub's cache documentation]. The first fetch from each runner is recorded | §2.3, §7.1, §7.3 |
| F6 | R5b's mutation 8 can never fail: with each value cut at 64 characters the record is at most about 321 bytes, so the 511-byte cap is dead code | **Accepted**, with P10 and T2 | Counted: 159 (x86_64's base) + 73 + 68 + 21 = 321. `abi`, `mode`, `baked` and `dol` come before every new key, so the cap protects nothing the cut does not. The cut stays, the cap goes, and the test holds the bound with the cut taken out as its mutation | §5.7; R5b mutation 8; `test_the_record_says_what_made_the_library` |
| F7 | Three stale-link behaviours the draft relied on do not exist: no note for a record without `compiler`; a missing Android record passes; the check runs before the compiler lookup | **Accepted**, with T22 | recompile.py:89-100 returns None for no record; :103-110 notes only when there is none; :641-645 checks before the lookup at :790. Now `build_inputs_note` names a gnu record without `compiler`; `strict` refuses a missing record; Android looks up its compiler, identity and sysroot before any record is compared | §5.2, §5.3; `test_an_android_build_with_no_compiler_says_so_before_it_reads_anything`; test_recompile_inputs' cases |
| F8 | `COMPILER_PATH`, `CPATH`, `C_INCLUDE_PATH`, `CCC_OVERRIDE_OPTIONS` and the like reach clang ahead of the sysroot | **Accepted** | toolchain.py:458-461 runs gnu commands with the inherited environment. `clean_clang_env()` takes eight such variables out of every Android command and the crt build. The mingw profile is not changed: out of R5 | §2.4, §4.3; check 15; `test_the_environment_cannot_reach_the_game_s_compile`; `test_an_android_command_runs_without_clang_s_search_variables` |
| F9 | The in-place swap leaves the old record with no tree, or with the new one; Windows file locks raise tracebacks | **Accepted** | The draft removed the old tree and renamed the new one before writing the record, never deleting the old one first. Now: the record goes first; stale `.new` and `.old` go; the old tree is renamed aside; renames and removals are tried five times; failures end in words | §2.4; check 13 |
| F10 | The closure test's parser splits `clang -M` output on spaces, which breaks in a folder with a space | **Accepted** | design_probe.py:28 splits on whitespace. Check 11 reads `-H`, one header a line with the path whole, and the parser has its own test with a space | §8.1 check 11 |
| F11 | The design did not say where the new steps go; the sysroot step needs llvm-mingw first | **Accepted**, with N8 and T24 | The route has a job of its own, its order written out (llvm-mingw, then the sysroot), its test step `!cancelled()` | §7.1 |
| F12 | Three stub links per fixture build slow `test_android_build.py` by 30-40 s | **Accepted, in another form** | A reviewer measured 0.44 s a stub link on this PC. Rather than a stubs-folder argument every caller passes, `gamefixture` builds the C stubs once per profile per session and reuses them through the plan's `stubs=False`; the first build, and two tests, still run the plan whole. Measured before and after in R5a part 2 | §5.4, §8.2 |
| F13 | The draft read D-34 as excluding the player's PC, shipping CI-built crt objects; building on the player's PC is feasible offline | **Accepted**, with N11 and P15: **the literal reading** | D-34's own words: "built where it is used", "by the script every machine runs", "rather than built once by CI and published" (PLAN-NEXT.md:159-164, :885). The player's PC is where it is used. The reviewer rebuilt all four crt objects to their pins from a cache of the 44 files alone, in a folder with a space and a comma, using only the two programs a package carries. The cost is 151,273 B of sources and seconds of building; a damaged tree then repairs itself. The owner reads the reading at R5b's look, rather than being asked a question D-34 already answered | §0.1, §2.1, §2.9, §6.1, §6.2, §7.3; R5b's Owner item 2 |

### 11.2 Network

| ID | Problem | Decision | Why, as checked | Where |
|---|---|---|---|---|
| N1 | The drafted package's library will not load beside an APK built here, through CRLF; R5b's Done stages locally, so nothing would see it | **Accepted** (as F4), with its part (d) | R3's Done built from the downloaded CI zip, and R5b's now does too: the zip's Android library, built in a new folder, equals the local package's and runs on the emulator with an APK built here | §1.0, §1.2 |
| N2 | `gen-android-arm64/` and `libsoa_game.so` are neither ignored nor refused, so translated chunks under 2 MB could be committed | **Accepted**, with P5 | `.gitignore`'s `gen/` and `FORBIDDEN_DIRS`' `gen` match a whole folder name (guard.py:201-208); `.so` is not ignored; the chunks are under `MAX_TRACKED_BYTES`. No path in history has a `gen-` folder [V `git log --all --name-only`], so the new rule is safe for `--history`. **Not taken:** `player_build` refusing a root that `git check-ignore` does not ignore, since a package has no git and the two rules cover it | §6.5; R5b mutation 10; Done roots under `build\` |
| N3 | The cache step protects neither failed runs nor releases; any script edit misses; no restore-keys | **Accepted** (with F5) | `actions/cache` saves only on success [I its `post-if`]; split `restore`/`save` steps keep a good fetch; the key is the pins'; `restore-keys` takes the newest by prefix, which is safe because each file is held to its pins on reading | §7.1 |
| N4 | A tree with a changed file is "there", so the tool and recompile loop; the swap is misdescribed | **Accepted** | The draft's plain run built only when the tree was missing or "not this script's", printing "there … --verify checks it" over a damaged tree (as fetch_mingw.py:205-207 does), while recompile refused it and named the tool. Now `ensure()` counts a tree as there only when `verify()` finds nothing and the record is expected, and rebuilds otherwise, from the cache with no request | §2.9; check 6; R5a part 1's "repairs itself" Done line |
| N5 | Retries covered status codes only; body failures surfaced as tracebacks or pin words; no `Retry-After` date; no deadline; the release's other fetches have no retries | **Accepted** | `fetch()` treats a read or decode failure of a 200 as transport, retries a name that does not resolve, reads both `Retry-After` forms, caps a wait at 300 s, gives the run one 600 s deadline, and never speaks of pins for a transport failure. `package.py`'s licence and CPython fetches go through it, and the CI steps that fetch have `timeout-minutes: 15` | §2.3, §6.2, §7; check 4 |
| N6 | The two symbol lists, read only by a test, were on every build's path, through the endpoint that met 429 | **Accepted** | A build needs the 44 files (four archives); `--lists` fetches the two lists for check 12 and `--check-upstream`, and CI asks for it. A package carries neither list | §2.3; check 12 |
| N7 | The blob ids were never checked against the files, so a hand edit of one column passed every check | **Accepted** | `held()` checks the sha256 and the git blob id on every read, so `--check-upstream`'s blob comparison vouches for the sha256 too | §2.2; check 2 |
| N8 | Where the steps go, and `!cancelled()` | **Accepted** (as F11) | | §7.1 |
| N9 | Every new machine depends on googlesource alone | **Accepted** | With both pins checked on every file, the source does not matter to trust. `--from <folder>` fills the cache from any bionic checkout or copied cache, and the give-up words and TESTING's recipe name it | §2.3 |
| N10 | `player_build`'s refusal would quote verify's developer advice to a player | **Accepted** | `verify()` returns facts; the command line and recompile add the developer's way out; `player_build` has its own words, different in a package and a checkout | §2.6, §5.2, §6.1 |
| N11 | The D-34 reading | **Accepted** (as F13) | | §0.1 |

### 11.3 Player

| ID | Problem | Decision | Why, as checked | Where |
|---|---|---|---|---|
| P1 | A CI package's library gets a `baked=` no APK built here accepts | **Accepted** (as F4) | The reviewer's copy of the 18 inputs with the LF ones converted gives `baked` f05af62beb91 against 705f401d4dcd here [V `r5/review_crlf`] | §1.0 |
| P2 | The Android checks ran only when that target started, after the extraction and the whole Windows build; mutations promised "before any work" | **Accepted** | A preflight right after the disc check, read-only, before the extraction or any target, catching `OSError`, in player words in a package; a failed preflight stops every target, so Setup can say why in seconds. The mutations now say "before `[build] extract`" | §6.1; R5b mutations 4-5; test_player_build's preflight tests |
| P3 | Setup checks space only while `soa.exe` is absent, and only when the window opens | **Accepted** | setup.c:185's `!built()` guard, and `folder_problem` at :484 and :556 only. The need now counts the Android build when the box is ticked and no library is built, and is checked again when the box is ticked and on Build or Rebuild; `--assume-free` lets a test hold it | §1.3; R5c mutation 4 |
| P4 | Setup's "Windows built, Android not" words had no rule; `built()` would claim a build after a failed Rebuild; the Android reason never reached the status | **Accepted** | setup.c:403-419 decides by the exit code and `built()`; a failed Rebuild keeps the old `soa.exe`, since `install` runs only on success (player_build.py:233-241). The status now comes from this run's lines, by §1.3's table; `--bar --exit` shows it to a test | §1.3; R5c mutation 3 |
| P5 | `gen-*` and `.so` not ignored or refused | **Accepted** (as N2) | | §6.5 |
| P6 | The one-line `TOOLS` fix for a live defect waited behind two pushes, while R5a added a second top-level import | **Accepted** | The reviewer's probe staged `TOOLS` and `tools/soa` and got `ModuleNotFoundError: fetch_sdl` from `import recompile` [V `r5/review_pkgtools`]; PLAN-NEXT §0 has the owner's R4 run "to come". R5-0 lands first, and recompile imports the new tool lazily, so it can never stop a Windows build | §1.0, §5.1 |
| P7 | Setup's built words send players to an app with no source until D-33, disagree with the phone's prompt about the disc, and describe a path never run | **Accepted, in part** | The words name no app source, and distribution R5 records the gate: no published release shows the box before D-33's release APK, put to the owner. The disc's file goes to the owner together with `DISC_PROMPT`. The words' path (`disc.iso` picked from Download) is followed on the emulator in R5b, and on the Thor. Captures at 100% and 150% go on the review page. **Not taken:** a mechanism in Setup that hides the box, since the owner alone publishes (Q-D4) and the gate is a publishing rule | §1.2, §1.3, §1.4 |
| P8 | The never-stale record left out the compile flags, so a flag edit relinks old objects without a word | **Accepted, in its first form** | `cflags` joins `build_inputs.txt` (refused when it differs, for every gnu profile; missing refused under strict) and `identity()`. **Not taken:** a digest of the staged trees appended to `VERSION`: with the flags recorded, everything that changes the objects is recorded (BAKED, compiler, flags, sysroot), and a `VERSION` that is not `git describe`'s would break the release's name check | §5.3, §6.1 |
| P9 | R5c's Done compared Setup's library with R5b's, which cannot match: a new package means a new `VERSION`, so a new `package=` | **Accepted** | `package=` is compiled into the record (§5.7), and R5c stages a new package for its new `Setup.exe`. R5c compares with `player_build` from the same package into a second root | §1.3 |
| P10 | The cap and the cut contradict | **Accepted** (as F6) | | §5.7 |
| P11 | The sysroot's identity covered `NOTICE.txt` and the comment lines, so a licence edit retranslates every root | **Accepted** | `sysroot_digest()` is over the record's `usr/` lines alone, all that compiles and links read; `NOTICE.txt` stays recorded for `--verify` | §2.6 |
| P12 | The package import test could pass while the package fails, and a `fetch_mingw.RELEASE` import would break the package | **Accepted**, with T11 | The test calls `stage_source`, the real copying; runs with `-I` from a temporary folder under the embeddable CPython when `vendor/` holds it; imports every `TOOLS` module; and asserts where each came from. The tool names `toolchain.MINGW_RELEASE`, held to `fetch_mingw.RELEASE` by a test | §6.2, §8.2 |
| P13 | `deepest()`'s floor no longer covers the build's own outputs | **Accepted**, extended | lld writes each output under a name 11 characters longer [I]; `gen-android-x86_64/stub/libsoa_runtime.so` is 41. And now the player's PC writes the sysroot under `source/vendor/`, at most 87 characters. `BUILD_DEEPEST` is computed from both | §6.2; `test_setup.py`'s expectation |
| P14 | Nothing on the PC checks before the Thor session that the arm64 library and the APK agree | **Accepted** | `push-game` holds the library to the record, exports and C libraries the APK was built with (read from `generated/runtime_seam.c`), for the device's machine, before it pushes. The arm64 library under the AVD's ARM translation is left as an optional try in §1.4, not a step [I] | §6.6, §1.4 |
| P15 | The D-34 reading | **Accepted** (as F13) | | §0.1 |
| P16 | The Apache text was cited by line numbers of a file a bump can change; the kernel texts' v6.19 came from an unpinned header | **Accepted, in part** | The NOTICE names `licenses/llvm.txt`'s first part with no line numbers, and a test holds that part to the Apache License 2.0. `linux/version.h` is pinned as a check file, in an archive already fetched, and a test derives the kernel tag from it. **Not taken:** a separate `licenses/apache-2.0.txt`: `llvm.txt` already carries the text whole, so a new host and pin would add nothing D-35 asks | §2.2, §2.5, §2.10, §8.2 |
| P17 | The release job fetches from googlesource every run | **Accepted** (as F5) | | §7.1, §7.3 |
| P18 | Whether the Android target can share the Windows target's translated C was left unanswered | **Accepted, in part** | R5b's Done measures the translation's time and the C's size per target, and §0.1 gives the reason. **Not taken:** compiling the Android objects from `<root>/gen`'s C: both profiles name their objects `.o` in their own `--out`, so sharing needs a C-folder option in recompile and a record of two targets, for minutes paid once per release per player | §0.1, §1.2 |

### 11.4 Tests

| ID | Problem | Decision | Why, as checked | Where |
|---|---|---|---|---|
| T1 | Part 1's crt build calls `toolchain.mingw_clang()`, which the draft added only in part 2 | **Accepted** | Part 1's Files now hold the lookup, the identity and the clean environment, with test_mingw's two tests | §1.1 part 1 |
| T2 | The cap can never fire | **Accepted** (as F6) | | §5.7 |
| T3 | `compiler_id()` and `write_build_inputs`' new lines had no test | **Accepted** | A test with `compiler_path` and `subprocess.run` patched, whose mutation is `compiler_id` returning `""` | §8.2 test_recompile_inputs |
| T4 | recompile's sysroot refusal and `stage()`'s new check had no test | **Accepted** | `android_sysroot_problem()` has its test; `stage()` refuses a cache off its pins before writing, tested with the other verifies patched | §5.2, §8.2 |
| T5 | The FAIL-line and label tests checked helpers, not `main()`'s call sites | **Accepted, in another form** | `main()`'s loops become `compile_units()` and `run_plan()`, the very lines a build prints, tested with `toolchain.cc` patched. **Not taken:** a whole `main()` run, which needs the game's DOL that no test has; `main()` itself is reached where its lines come before the DOL is parsed (the Android lookup test) | §5.6, §8.2 |
| T6 | No per-push CI job ran the route on Windows, where players build | **Accepted** | ci.yml:69-90's Tests jobs ran `test_android_build.py` wherever an NDK was found; with the `route` marker they skip there. `android-route` runs on `ubuntu-latest` and `windows-latest`, MSVC building `elfcheck.c` on the latter | §7.1 |
| T7 | Two existing `test_player_build.py` tests break, and one would start a real compiler | **Accepted** | `run_main`'s stand-in (test_player_build.py:129) takes `target`, and `run_main` patches `identity`; both tests that use it are listed | §8.2 |
| T8 | The header comparison was a scratch script, yet the docstring and risk 4 told people to run it again | **Accepted** | `--compare` commits it, with exact output, a test (check 16), TESTING's recipe and the docstring's bump steps; "19 units" is 18 chunks and `dispatch.c` | §2.8, §1.1 part 2 |
| T9 | §8.6 missed copies of the counts, and one paragraph was stale | **Accepted** | Grepped at 6d5916c: SKILL.md:32 and :357, TESTING.md:40-50, :92, :163, :1903; the gate's commit already holds 1436, so the paragraph about uncommitted counts goes. A fifth row, without llvm-mingw | §8.6 |
| T10 | `test_recompile_inputs.py`, which owns the record's tests, was not named; the profiles test was new, not changed | **Accepted** | test_recompile_inputs.py:24-30 asserts the msvc record's two keys, kept; test_toolchain_profiles.py has no Android test today [V grep] | §8.2 |
| T11 | The import test could pass on today's `TOOLS` | **Accepted** (as P12) | | §8.2 |
| T12 | Nothing kept a later `package.py` from dropping `source/VERSION` | **Accepted** | `package.py check` holds `VERSION` to the zip folder's name in the release; `stage_source` writes it, and its test holds that | §6.2, §8.2 |
| T13 | `--check-upstream` had no test, and blob ids were never checked offline | **Accepted** | Check 17 injects listings; check 2 holds both pins on every read (N7) | §2.7, §8.1 |
| T14 | The arm64 crt pins are a first bless of objects that have never run | **Accepted** | The gate ran x86_64 alone (FINDINGS:7731-7752). Before pinning, each arm64 object is compared with NDK r28c's by `llvm-readelf -S -s -r -n`, the differences named in the commit and FINDINGS | §1.1 part 1 |
| T15 | The reproducibility Done line could not fail | **Accepted** | Two records of trees held to one pin table are the same bytes by construction. The line becomes a build in a folder with a space and a comma, verified; reproducibility is said to be held by the output pins | §1.1 part 1 |
| T16 | The kernel licence test compared literals | **Accepted** (as P16) | | §8.2 |
| T17 | The staging test could not catch the source cache being shipped | **Accepted**, for the literal reading | A package now carries the 44 sources, and nothing else of the cache: check 18 and the staging test give it the lists, `version.h` and a stray file, and expect only the 44, with the guard clean | §8.1 check 18, §8.2 |
| T18 | Removing `POST_LINK` left the `dol=NULL` branch of both checkers untested | **Accepted** | `NO_DOL = {**PHONE, "dol": None}` keeps the C and Python branches held together, as TESTING.md:92 claims | §8.2 |
| T19 | Two slices edit `seam.py`, which CLAUDE.md binds to a Linux-container check | **Accepted** | CLAUDE.md:50's row. R5a part 2's and R5b's Dones run the container session, with its lines | §1.1, §1.2 |
| T20 | Several Done lines were inexact or contradicted each other | **Accepted** | Each is now a command and its exact output: the offline run's 44 line; counts as the measured `N passed in Ts` under `-p noskip`; one spelling of the looked-in lines, written out; the `soa.log` lines and the capture that prove the player's path; check 6 needing nothing; "before `[build] extract`" | §1 |
| T21 | New branches had no test: retries, the cap, the cache's repair, "there", the per-source sysroot flag, Setup's Android space, the NOTICE pin | **Accepted** | Checks 4, 6, 10 and 13; `gnu_commands`' two paths; Setup's `--assume-free` | §8 |
| T22 | No note is printed for a mingw record without `compiler`; the stale check runs before the lookup | **Accepted** (as F7) | | §5.2, §5.3 |
| T23 | R5 adds counts in prose that will rot | **Accepted** | The tool's counts live in its output and TESTING's transcript; elsewhere "the closure"; the docstring carries the grep | §8.6, §2.9 |
| T24 | The YAML's place and `!cancelled()` | **Accepted** (as F11) | | §7.1 |

---

## Appendix A. Probes run for the draft

Each is in the scratch folder `…/scratchpad/r5/`. They read the repository and wrote only there.

1. **`design_probe.py`: the closure.** `clang -M` with llvm-mingw's clang 23.1.2 and the profile's flags, at -O0 and
   -O2, for both ABIs, over `probe_includes.c` (`cpu.h`, `soa_game.h`, `<stddef.h>`, `<stdint.h>`) and over the crt
   sources, against the whole android-17 tree (`ours`), mapped back to bionic's paths. **The result:** 30 headers for
   the game (23 common, 3 and 4 `asm/`), 14 more for the crt, 44 in all; `design_probe.json` holds sizes, sha256 and
   blob ids. android-17's `linux/stddef.h` has no `#include <linux/compiler_types.h>`; NDK r28c's has.
2. **`design_upstream.py`: the pins against upstream.** Ten gitiles `?format=JSON` listings at `06356e41`, 2 s apart,
   no 429: 44 of 44 blob ids match; then the two lists: 46. The tag's peel is from `aosp/bionic_refs.json`.
3. **`design_recipe.py`: the recipe.** Exactly the 30 headers; the crt objects by §2.4's recipe into `design_out` and
   `design out2 (spaces)`, all four byte-identical in both and to `sysroot_full_own`'s (the gate's); the game's
   includes compiled against the 30 alone, both ABIs; the tree 34 files, 115,602 B; `llvm-readelf -s -n` on arm64's
   `crtbegin_so.o`: `STT_FILE crtbegin_so.c`, `__dso_handle` hidden, the three imports, the ident note `21 00 00 00`.
4. **`design_stub/`: the stubs.** lld linked an empty `libdl.so` with `LIBC { local: *; };`; a small x86_64 game
   library linked against §3's stubs was byte-identical with the empty `libdl.so` and with the gate's (`920d5ac1…`):
   `DT_NEEDED` `libsoa_runtime.so`, `libm.so`, `libdl.so`, `libc.so`; imports `__cxa_finalize@LIBC`,
   `__cxa_atexit@LIBC`, `__register_atfork@LIBC`, `setjmp@LIBC`; `DT_RELR` and `FINI_ARRAY` present.
5. **Licences: `design_notice.py` and the fetches.** Each file's leading comment, classed (§2.5); the kernel's
   `Linux-syscall-note` and `GPL-2.0` at `v6.19`; `LINUX_VERSION_CODE` 398080; AOSP `external/kernel-headers`' NOTICE
   is GPL-2.0 with no note; `vendor/llvm-mingw/LICENSE.TXT` holds the Apache License 2.0 whole at its start (lines
   4-206, before "LLVM Exceptions" at 208, re-read for this version); the 13 seam names
   all in `LIBC`, 9 in libc's list, 4 in libm's.
6. **The package's tools.** `package.TOOLS` and `tools/soa/**/*.py` in a scratch `tools/`: `import recompile` exited
   1 with `ModuleNotFoundError: No module named 'fetch_sdl'`.

## Appendix B. What the reviews ran, and what this pass checked

**The reviewers' probes**, each under `…/scratchpad/r5/`:
- **`review_probe/probe.py`:** the crt recipe against a cache holding only the 44 pinned files, in
  `Skies, the game (probe)`: all four outputs as pinned. The stub link there: `-Wl,--version-script=<path>` exit 1
  (`cannot find version script …\Skies`), `-Xlinker --version-script=<path>` exit 0.
- **`review_probe/emb`:** the embeddable CPython 3.14.8 unpacked; a script in `source/tools` without a `sys.path`
  line got `No module named 'soa'`.
- **`review_crlf_probe.py`:** draft-0223b3a's zip, read by range requests, against `git show 0223b3a:<path>`:
  `tools/recompile.py` 25,436 B with 589 CRLF against 24,847 B with none; `config/hle.txt` 2,216 against 2,179;
  `tools/soa/hle.py` 2,529 against 2,468; `config/hooks.txt` 219 against 215. Files stored CRLF were the same bytes.
- **`review_crlf/`:** the 18 inputs with the 10 LF ones converted: `baked` f05af62beb91, against 705f401d4dcd here.
- **`review_pkgtools/`:** `TOOLS` and `tools/soa` staged as `stage()` stages them; `python -I -c 'import recompile'`
  gave `ModuleNotFoundError: No module named 'fetch_sdl'`.
- **`review_archive_probe.py`:** the scratch archives at android-17.0.0_r1: member names relative, with no leading
  `./`; files and folders only; eight case-colliding pairs in `libc/kernel/uapi`; every pinned file present with its
  pinned bytes.

**Checked again for this version** [V, at 6d5916c, reading only]:
- `git ls-files --eol` over BAKED: the 10 LF files, `config/trace.txt` mixed, the rest CRLF; no `.gitattributes`;
  `git config --show-origin --get-all core.autocrlf` gives `true` from Git's system file and `false` from this user's.
- The commit order: R3 (ff0926d) and R4 (0223b3a) before L12a (75d5ce2).
- `git log --all --name-only` and `git ls-files`: no path with a `gen-…` folder, no tracked `.so` or `.apk`.
- `linux/version.h` from the scratch copy: 389 B, sha256 `48fdd11c…`, blob `8b12181e…`, the same blob as gitiles'
  listing at `COMMIT` in `design_upstream.json`; it holds `LINUX_VERSION_CODE 398080`.
- `review_archive_probe.py` re-run (offline): 15, 19 and 6 pinned files in the three scratch archives, all as pinned.
- The 44 sources: 151,273 B; the deepest in a package 79 characters; the deepest the tool writes there 87.
- The embeddable CPython's `python314._pth`: `python314.zip` and `.`.
- `tools/setup/setup.c`, `player_build.py`, `package.py`, `recompile.py`, `toolchain.py`, `guard.py`, `elfcheck.py`,
  `gamefixture.py`, the tests and both workflows, read whole where §11 cites them.

**Game-derived scratch** from the research is still there and is to be deleted when this workflow ends (map
appendix): `ours-*`, `probe-arm64`, `ours-link*`, `work/`, `stub/`. Neither the design's probes nor the reviews' built
game code.
