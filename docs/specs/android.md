# Android: the shell and the game library (portability L12, distribution R5)

*Written 2026-10-05 at d6d64aa, after L10, and reviewed once against the code the same day (review log).
It specifies portability.md's L12, which was an outline, and distribution.md's R5, which was recorded for it.
The outside facts are in [research/android-shell.md](../research/android-shell.md) (AOSP at
`android-17.0.0_r1`, SDL `release-3.4.18`, RPCSX), and the facts about this tree were measured on this PC the
same day. **[V]** means read in code, on a primary source, or measured; **[I]** means inferred.*

**The route is decided** (G3, PLAN-NEXT §0): a runtime-only APK that holds no game code, and a game library the
player builds on their PC from their own disc. **SDL3 is decided** (G2). **Android is a goal and the GPU is
Vulkan** (D-17, G1). **The owner's answers of 2026-10-05** (§6):
- **the devices:** a Galaxy Z Fold 8 and an AYN Thor;
- **the player's compiler:** llvm-mingw plus this repository's own sysroot;
- **the floor:** Android 13;
- **the app's identity:** still open.

**In one paragraph.**
- **The APK** carries SDL3 and the runtime, as `libsoa_runtime.so`, which also holds `SDL_main`.
- **The player's PC** builds the translated game into `libsoa_game.so`. That library names `libsoa_runtime.so`
  as `DT_NEEDED`, exports one versioned table, and carries its build record in an ELF note.
- **The phone** imports the library and the disc through the system file picker. It checks the library's note
  and imports before loading it, keeps it read-only in its own storage, and `dlopen`s it. It reads the disc in
  place where it can.
- **No phone is needed for the first four slices.** The seam is proved on Linux in a container (L12a), the PC
  build is pinned (L12b), and the shell and the import run on the x86_64 emulator already installed here (L12c,
  L12d).
- **The phones are for** the Done, the touch overlay (L12e) and the GPU (L12f).

---

## 1. What the player gets

| Step | Where | The player | What happens |
|---|---|---|---|
| 1 | PC | Runs `Setup.exe` (R4) with **Android** ticked | Builds `soa.exe` as today, and also `libsoa_game.so` for Android from the same disc (§3.4) |
| 2 | Phone | Installs the APK (adb, or the download with Android's advanced flow; §3.6) | The APK holds SDL3 and the runtime, no game code |
| 3 | Phone | Opens it; it asks for the game library, then the disc image | Both picked in the system file picker; the library is checked and copied (§3.3); the disc is read where it is, or copied (§3.7) |
| 4 | Phone | Plays | With a controller, or the touch overlay (L12e) |

A rebuilt library (a new package version, or a new disc revision) is picked again from the first-run screen,
which the launcher shortcut "Choose the game files again" reopens (a long press on the app's icon): the app asks
for both files again, offering "Keep this one" for each it already has (§3.6). An app update that the library no
longer fits opens that screen by itself, saying why. Saves are the card image, which Dolphin, the PC build and
the phone share (§3.8).

**Out of scope:**
- building on the phone (route C1);
- Google Play, which refuses downloaded code and translated game code (research §6);
- Android before 13;
- the 32-bit ABIs;
- a second guest thread (risk 1);
- mods, until L12g (§3.15).

---

## 2. What exists today [V, measured 2026-10-05 at d6d64aa]

- **The runtime compiles for Android.** All 35 `runtime/*.c` compile with the NDK 28.2 clang for
  `aarch64-linux-android29`, with `SOA_SDL` on and against SDL 3.4.18's headers, with warnings only (a scratch
  probe: the gnu profile's flags plus `-fPIC`).
- **The translated code compiles and links for Android.** The 18 chunks and `dispatch.c` compile the same way,
  the longest unit in 48 s. They link into a 31.4 MB `libsoa_game.so`, every `PT_LOAD` aligned 0x4000 (16 KB),
  `DT_NEEDED` `libm.so`, `libdl.so` and `libc.so`.
- **The seam is small.**
  - The translated code imports 54 symbols (`nm` on the Linux build):
    - the 26 bindings the runtime answers (`config/hle.txt`; 25 until L12c's `__AI_SRC_INIT`);
    - 23 runtime functions and globals: `dec_read`, `dec_write`, `g_watch_addr`, `g_watch_len`,
      `guest_resumed`, `guest_savepoint`, `guest_syscall`, `guest_timebase_hi`, `guest_timebase_lo`,
      `guest_trap`, `gx_pipe_write`, `hook_80237BA8`, `irq_poll`, `mmio_read8`, `mmio_read16`, `mmio_read32`,
      `mmio_read64`, `mmio_write8`, `mmio_write16`, `mmio_write32`, `mmio_write64`, `trace_hit`, `watch_hit`.
      On x86-64 Android a 24th, `soa_fma`, stands in for bionic's `fma` (L12c);
    - five from libc and libm: `_setjmp`, `fma`, `sqrt`, `nearbyint`, `nearbyintf`. On AArch64 the maths become
      instructions: the Android link leaves `setjmp` and crtbegin's `__cxa_atexit`, `__cxa_finalize` and
      `__register_atfork`.
    - `cpu.h`'s inline code touches only listed symbols, and none of it is built only in debug builds.
  - The runtime reaches into the translated code in few places:
    - `dispatch`: `irq.c:285,459`, `mod.c:649`, `selftest.c:59` and `threads.c:255,256,325`;
    - `dispatch_known`: `mod.c:589`;
    - the entry, `fn_80003140`: `main.c:25`;
    - 21 functions the self test compares (`selftest.c:1504-1522`);
    - the nine `disc_sys_*` symbols of the player's system files: `disc.c:65-67` (I3).
  - No function pointer crosses the boundary: `dispatch` is a switch.
  - No `long double` appears anywhere, and the translated objects call no compiler builtin, so the game library
    needs no compiler-rt.
- **The bindings depend on the build mode.** `hle.txt` binds 26 functions. `decomp_swap.c` answers 12 of them
  with decompiled code, and a build with no `src/` (`--no-decomp`, the player's build, distribution §3.1)
  leaves those 12 to translated twins inside the game. 14 then cross the seam, and the self test's 22 twins become
  7 `recomp_fn_` and 15 `fn_` (`selftest.c:1504-1518`).
- **The window, pads and sound** run through SDL3 since L10 (`runtime/window_sdl.c`, `audio_sdl.c`), held on CI
  by `test_window_sdl.py`. `window_sdl.c` already sends `WILL_ENTER_BACKGROUND` and `DID_ENTER_FOREGROUND` to the
  clock, in its pump loop (`window_sdl.c:591-597`). Nothing handles `SDL_EVENT_RENDER_DEVICE_RESET`.
- **The pause holds the guest at the frame end:** `tick_set_hold(clock_pause_requested)` (`main.c:1344`, M19).
- **The guest runs on `plat_run_on_big_stack`,** which starts a thread with a 32 MB stack and joins it
  (`main.c:1444`, `plat.c:220-236`). The window has its own thread (`window_sdl.c:760`).
- **The root and the paths.**
  - `settings_root()` (`settings.c:182-193`) is `SOA_ROOT`, or else the executable's folder from
    `plat_exe_path`, which off Windows is `readlink("/proc/self/exe")` (`plat.c:342-348`). In an Android app that
    is `/system/bin`.
  - `soa.ini`, the card, the mods folder, the GPU's pipeline cache (`main.c:1212`) and the pad recordings
    (`main.c:1269`) all hang from it.
  - The raw defaults are relative to the working directory, which on Android is `/`: `exi.c:90`, `gx.c:312`,
    `gxr.c:3018`, `gxv.c:2325`, `main.c:165` (`config/functions.tsv`, crash names), `main.c:1218`,
    `main.c:1238`, `selftest.c:203` and `si.c:369`.
- **The checks are driven by environment, not flags.** `main.c` takes `--help`, `--check-disc` and `--replay`
  (`main.c:1228-1233`). The self test is `SOA_SELFTEST=1` (`main.c:1389`). A replay wants `SOA_HASH`,
  `SOA_THREADS` and `SOA_SETTINGS=0` (`scenario.py:1085-1089`), and the MEM1 poke `SOA_MEMPOKE` (`main.c:704`).
- **One guest thread off Windows:** a second exits 6 (`threads.c:311-315`; portability risk 18). Every log so
  far has had one.
- **The savepoint is `setjmp`** (`cpu.h:111`), run at every interrupt delivered (`irq.c:285`). On glibc that
  is `_setjmp`, which saves no signal mask.
- **The GPU backend presents through a Win32 surface only** (`gxv.c:3629-3666`). Its loader already looks for
  `libvulkan.so` off Windows (`gxv.c:345-354`).
- **The disc layer opens by path** (`disc.c:404-430`): the ISO, or the I4 store, which checks each 64 KiB block
  at first touch (I5). `main.c:1298` opens it from `argv[1]`.
- **Mods are native libraries** loaded by `plat_dl_open` (`mod.c:746`), from `<root>/mods` by default
  (`settings.c:430`).
- **On this PC:** NDK 28.2.13676358; SDK platforms 34 to 36.1; build-tools 36.0.0 to 37.0.0; the android-34
  x86_64 emulator image, the emulator and adb; JDK 21; Android Studio; and llvm-mingw 20260922 in `vendor/`,
  whose clang links for Android (research §10).

---

## 3. Decisions

### 3.1 Two libraries in the APK, one beside them

| Library | Built by | Holds | Loaded by |
|---|---|---|---|
| `libSDL3.so` | SDL (the pinned AAR, §3.5) | SDL3 | `SDLActivity` |
| `libsoa_runtime.so` | the APK build | `runtime/*.c` with `SOA_SDL` and `SOA_NO_DECOMP`, and `SDL_main` (`runtime/android.c`) | `SDLActivity`, which calls its `SDL_main` (the last of `getLibraries()`, where SDL's own `getMainSharedObject()` looks) |
| `libsoa_game.so` | the player's PC (§3.4) | the translated code and the player's system files | the runtime, by `dlopen` (§3.3) |

- **Which libraries `SDLActivity` loads:** `getLibraries()` returns `{"SDL3", "soa_runtime"}`. There is no
  separate `libmain.so` (research §3).
- **`SOA_NO_DECOMP` always.** The APK holds no decompiled code (distribution §3.1).
- **`runtime/android.c`** is inside `#ifdef __ANDROID__`, since every `runtime/*.c` goes into every desktop
  link (`recompile.py:286, :335`) and `compile_runtime.py`.
- **What the runtime library exports:** the seam (§3.2), plus `SDL_main`. Nothing for the Java glue: it sets the
  environment through SDL's own `nativeSetenv`, and `runtime/android.c` calls it through JNI, by name (§3.6).

### 3.2 The seam: `DT_NEEDED` one way, one table the other

**Game library to runtime, by name.**
- `libsoa_game.so` names `libsoa_runtime.so` as `DT_NEEDED`. Bionic reuses the copy already loaded in the
  namespace and puts it in the game library's local group, so every undefined symbol resolves against it
  (research §2). `RTLD_GLOBAL` would not do this (research §2).
- The calls stay ordinary calls, so the generated C does not change.

**Runtime to game library, one table.** The game library exports one symbol, `soa_game`, a function that
returns `const SoaGame*`:
- `abi`: a version number;
- `entry`, `dispatch` and `dispatch_known`;
- the system files: the DOL, `boot.bin` and the file table, with their sizes and SHA-1s (I3's `disc_sys_*`);
- `twin(name)`: the self test's 21 comparisons, by name, in either mode.

**The record, in an ELF note.** The library carries the build record in a `.note.soa` section, so it can be read
before `dlopen` (§3.3):
- `abi`;
- the decomp mode;
- the DOL's SHA-1;
- the profile;
- the package version;
- the sha256 of everything the translated C bakes in, which is `player_build.BAKED` (`player_build.py:54-67`):
  `cpu.h`, the four binding lists, `functions.tsv`, `decomp_swap.c` and the translator.

The runtime carries the same record for what it was built against, and refuses a library whose record differs.
A different `hooks.txt` or `savepoints.txt` changes what the game does, so it is refused like a different
`cpu.h`.

**How the runtime reaches the table** (as L12a built it, where this spec first had every reference
rewritten):
- **Every build links the table.** `recompile.py` writes `<out>/game_table.c` into every build.
  - A single-file build (`soa.exe`, `gen/linux/soa`) links it and calls the translated code directly.
  - The self test's case "the game's table" holds the one to the other: the entry, `dispatch`, the system
    files, the record's abi and mode, and all 22 twins. So Windows checks the table on every run.
- **A split build** (`--split`) also writes `<out>/runtime_seam.c` into the runtime library. It holds
  forwarders, under the names the runtime calls, through the loaded table: `dispatch`, `dispatch_known`,
  `fn_80003140` and the 22 twins.
  - So `irq.c`, `mod.c`, `threads.c` and `selftest.c` do not change, and neither do the tests' stand-ins.
  - Only `main.c` (its `main` is `soa_main` under `SOA_SPLIT`) and `disc.c` change. A function cannot stand in
    for an array, so `disc.c` reads the system files from the table.
- **No forwarder clashes with the game's own names:** they are hidden in both libraries (§2: no function pointer
  crosses).

**Visibility.**
- The game library is compiled `-fvisibility=hidden`, with `soa_game` alone visible. The 7,144 functions call
  each other directly.
- The runtime library's exports are generated from a checked-in `config/seam.txt` (the 24 runtime symbols) and
  from `hle.txt` with `decomp_swap.c` (the 14 bindings under `--no-decomp`). They are linked with a version script
  that exports nothing else.

### 3.3 Loading the game library

1. **The pick:** SoaActivity's own `ACTION_OPEN_DOCUMENT`, of any type (`*/*`) and opening in the shared Download
   folder (`EXTRA_INITIAL_URI`), returns a `content://` URI. Not SDL's `SDL_ShowOpenFileDialog`, which this text
   first named: nothing cancels an SDL dialog but its result, it cannot open in a chosen folder or ask for local
   files only, and it starts the picker off the UI thread [V].
   - `runtime/android.c` calls `pick` through JNI from SDL's thread, which waits on a lock of the glue's own, never
     on the activity's own monitor, which SDL uses for itself.
   - `onActivityResult` keeps the grant, then writes the pick to `no_backup/pending_library`, and only then wakes
     the waiter: a pick that comes back to a new process, the one that asked having been killed, is still used
     [V L12d].
   - Back in the picker is a cancel, and the prompt comes back. Opened in Download, the picker takes the first
     Back as "up a folder" and closes at the second [V L12d].
2. **Checked, copied, loaded, and only then put in place,** so a pick that will not load never costs the player
   the library they had [V L12d]:
   - before a byte is copied, through its descriptor: a disc picked as the library is refused by its first bytes,
     and a regular file goes through step 3 as `/proc/self/fd/N`;
   - copied by `runtime/import.c` into `noBackupFilesDir/libsoa_game.so.tmp`: at most 256 MiB, with room for it
     and 512 MiB more, made `0444` (research §1) and synced. A stream (a pipe or a socket) cannot be checked whole
     first: its first 64 bytes are held to this device's ELF header before the rest comes (for a Windows file, as
     far as the header that names it), and any other refusal is step 3's, on the whole copy;
   - loaded from the copy (step 4), then renamed over the installed one, its mapping still good;
   - one `dlopen` per process: a library picked once one is loaded (from the disc's "Pick another library") is
     checked as a file, put in place with the old one kept as `.old`, and the run ends asking the player to open
     the app again.
3. **Before any `dlopen`,** from the file's own headers, `runtime/elfcheck.c` checks, as `tools/soa/elfcheck.py`
   does word for word:
   - a Windows file (`MZ`, then `PE`), named as one, with its machine and whether it is a library;
   - the machine, AArch64 (x86_64 on the emulator), before the class, so a 32-bit library is named for what it
     was built for; then 64-bit, little-endian and `ET_DYN`;
   - every `PT_LOAD` aligned to at least 16384;
   - no `DT_TEXTREL`;
   - `DT_NEEDED` including `libsoa_runtime.so`, and nothing outside it, `libc.so`, `libm.so` and `libdl.so`, on
     Android by exactly those names, so a Linux library (`libc.so.6`) is refused as one;
   - the `.note.soa` record against the runtime's (`abi`, `mode`, `baked`), then its `dol=` (step 4);
   - **every undefined dynamic symbol against the runtime's own export list.** Otherwise `dlopen(RTLD_NOW)` would
     fail first, with the linker's words.
   Each failure is refused in the player's words, these among them as the emulator's check runs printed them; a
   box puts the picked file's name and "cannot be used:" before them, with that name in place of any path:
   - "pe-program.so is a Windows program for x86-64, not a game library for this device: pick the libsoa_game.so
     that Setup makes for this device" ("a Windows library" for a DLL);
   - "this library was built for 64-bit ARM (AArch64), not this device (x86-64): rebuild it for this device with
     Setup";
   - "this library was built for Linux (it needs libc.so.6), not Android: rebuild it for this device with Setup";
   - "this library was built for 4096-byte pages, and devices may use 16 KB ones: rebuild it with this package's
     Setup";
   - "this game library and this app come from different releases (its build is 954c63907bf6, the app's
     705f401d4dcd): install the app and run Setup from the same release";
   - "this game library was made from another disc's executable (32e08744cd28, this app plays 8c0e278126fa):
     rebuild it with Setup from your own disc";
   - "this library needs …, which this app's runtime does not have: rebuild it with this package's Setup".
   On the emulator each of `android.py mutants`' ten libraries drew exactly its predicted line [V L12d]. The words
   wait for the owner's look; until then only tests pin them.
4. **`dlopen(path, RTLD_NOW | RTLD_LOCAL)` from native code,** never `System.load`. Android 17's read-only rule
   binds `System.load`, and the file is read-only anyway (research §1). Then `soa_game`'s table is held to the
   runtime's `abi`, and the system files built into it to their SHA-1s ("the system files built into this game
   library are damaged: rebuild it with Setup"). The library is loaded before any disc is opened, and **the two
   are held to each other by a chain:**
   - `elf_check` holds the record's `dol=`, the SHA-1 of the executable the library was translated from, to the
     one this app plays, before `dlopen`; a record with no `dol=` is refused too;
   - `disc_open` holds the disc's executable to the same SHA-1, at the pick and at every launch;
   - with the system files built in, `disc_open` also holds the disc's file table to the library's (I3). That
     refusal offers "Pick another library", since either may be the wrong one.
5. **Precedent:** the RPCSX app does steps 1 and 4 at target SDK 37 today (research §1).

### 3.4 The game library on the player's PC (R5)

*Settled 2026-10-07 in [android-sysroot.md](android-sysroot.md) (D-34 to D-36), which owns R5's slices
from R5-0 on and supersedes this section where they differ: the sysroot is built where it is used, from
pinned bionic sources, by the script every machine runs, not by CI; the stub libraries come from
`config/seam.txt` at each link; its licences ship with their texts. R5a part 1 rewrites this section
from it.*

- **Two profiles,** `android-arm64` and `android-x86_64` (the emulator), in `tools/soa/toolchain.py`:
  - `--target=aarch64-linux-android33` (or `x86_64-...`), `-fPIC`, `-fvisibility=hidden`;
  - the gnu profile's `-ffp-contract=off -fno-strict-aliasing -fwrapv`;
  - `-shared -Wl,-soname,libsoa_game.so -Wl,-z,max-page-size=16384`.
- **The build:** `recompile.py --cc android-arm64 --compile --optimize --link` makes
  `gen/android-arm64/libsoa_game.so`. It is always `--no-decomp`. It links against a stub `libsoa_runtime.so`
  generated from the seam's lists, so the PC needs no runtime built for Android. It is reproducible as
  distribution §3.8 requires.
- **The compiler (Q-A2, answered A):** llvm-mingw, already in the package (R1), plus a small Android sysroot
  this repository's CI builds from pinned AOSP and LLVM sources:
  - the bionic headers the translated C includes (`cpu.h`: `math.h`, `setjmp.h`, `string.h`, `stdlib.h`), BSD;
  - `crtbegin_so.o` and `crtend_so.o`, built from bionic's sources;
  - stub `libc.so`, `libm.so` and `libdl.so`, generated from symbol lists.
  This avoids the SDK licence and a 728 MB download (research §10). It is fetched as `vendor/` is, pinned, and
  recorded.
- **The NDK in the meantime:** until the sysroot exists, L12a to L12d build with the NDK installed here.
- **For the player:** `player_build.py --target android-arm64` (and Setup's checkbox, R4) puts `libsoa_game.so`
  in the install folder beside `soa.exe`, and Setup says how to copy it to the phone.

### 3.5 SDL3 on Android: the pinned AAR

- **The source:** `SDL3-devel-3.4.18-android.zip`, a release asset beside the source archive L10 pins. It is
  fetched by `tools/fetch_sdl.py --android`, with its sha256 pinned and recorded in `vendor/SDL.sha256`.
- **Why the AAR:** it holds `libSDL3.so` for every ABI, already 16 KB-aligned and built for NDK 28, plus
  `SDLActivity` (research §3). It is the same release the Linux build uses.
- **The fallback:** building SDL from the pinned source, but only if SDL ever needs a patch.

### 3.6 The APK

- **Build system:** a Gradle project in `android/`:
  - Gradle 9.6.0 through the wrapper, its distribution's sha256 pinned; AGP 9.4.0; JDK 17 or later (21 here);
  - the AAR by prefab; CMake for `libsoa_runtime.so` (research §5).
- **Why Gradle:** it is the documented path, Android Studio can debug it, and CI's runners carry the SDK. SDL's
  Gradle-free CMake APK is the fallback.
- **SDK levels:**
  - `compileSdk` and `targetSdk` 36, which are installed here;
  - `minSdk` 33, Android 13 (Q-A3, answered);
  - target 37 waits until it is installed. Its rule for audio in the background does not bind a game that pauses
    there (research §8).
- **ABIs:** `arm64-v8a` alone in a release; `x86_64` too in a debug build, for the emulator.
- **The Java glue,** `SoaActivity extends SDLActivity`, as L12d built it. `runtime/android.c` calls it through JNI,
  by name, from SDL's thread, and each call waits there: never on the UI thread, which draws what it waits for, nor
  on the activity's own monitor, which SDL uses for itself:
  - `getLibraries()` (§3.1), and `getArguments()` from the check mode's `args`;
  - `onCreate`: `SOA_NOBACKUP` in every build (§3.8); the check mode's extras in a debuggable one (§3.14); and the
    launcher shortcut "Choose the game files again" (§1; id `reimport`, short label "Game files"), dynamic since
    the package name is still a working one (Q-A4). Its extra, `soa.reimport`, which any build reads, sets
    `SOA_REIMPORT`, so both files are asked for again. Used once the app is running, it brings a toast saying to
    close the app first, since SDL ignores a new intent once `SDL_main` runs;
  - `pick` and `onActivityResult` (§3.3 step 1);
  - `openFd`, a detached descriptor whose open can be cancelled; `describe`: the name (never used as a path), the
    size, the provider and whether the grant is kept; `release`; and `tidyGrants`, which releases every grant that
    neither `disc.txt` nor a pending pick names;
  - `status`: a copy's progress, with a Cancel, since Back reaches no app that targets Android 16, and the screen
    held on while it shows;
  - `messageboxShowMessageBox`, SDL's message box overridden: the message in a ScrollView, so a long refusal
    scrolls and the buttons stay on screen at a large font [V L12d, font scale 1.3]; the system's DeviceDefault
    dialog; a pad's A for the default button and B for Quit [V L12d]; and, once the activity has gone, an answer
    at once, which `android.c` takes as the end of the run;
  - `onDestroy`: every waiter woken before SDL's own teardown, so that `android.c` ends the run inside the second
    SDL waits for it. A pick waiting is [V L12d, through check 13's mutation: `[import] the app was closed during
    the import`, `[exit] 0` and SDL's `onDestroy()` in one millisecond]; a box, a copy's dialog or an open waiting
    is woken the same way, and was not tried.
  The copies are not the glue's: `runtime/import.c` makes them, in C (§3.7). `app/proguard-rules.pro` keeps every
  member `android.c` reaches (minify is off today), and `test_android_jni.py` holds `android.c`'s lookups to the
  Java and to the keep rules, since CI never builds the Java.
- **What the APK holds:** SDL3, the runtime, the glue, the shaders' SPIR-V (L12f) and the licences. No translated
  or decompiled game code, and no game data.
- **The guard over it:** `tools/guard.py --apk <file>` runs `--tree`'s deny scan over the APK's entries. It also
  scans every `.so` for the system files a leak would carry: a DOL header at any 4-byte offset, since a
  `uint32_t` array in `.rodata` is aligned that way, where `dol_inside` steps 32 (`guard.py:492-495`) [I alignment].
- **Built by:** CI's release workflow (distribution R3), as a draft beside the Windows package; the owner
  publishes it.
- **Installed by:** `adb install`, which needs no developer verification, or the advanced flow (research §6).
- **Its identity:** the package name and the release key (Q-A4, open) come before anyone else installs it. Debug
  builds use a working name, which an uninstall replaces.

### 3.7 The disc on the phone: read in place, or copied

- **By default, read in place.**
  - The picked URI's grant is kept by the Java glue, in `onActivityResult`, since SDL never keeps one (research
    §3). Android writes kept grants to `urigrants.xml` 10 s later (AOSP's `UriGrantsManagerService`) [V]: on the
    emulator one outlived a reboot, and a release followed by a reboot within seconds was undone [V L12d].
  - At the pick, and at every launch after it while `no_backup/disc.txt` says the disc is read in place, the glue
    opens a descriptor N, and `android.c` passes it to `main()` as `argv[1] = /proc/self/fd/N` (`main.c:1303`
    unchanged). A grant gone since is said ("GEAE8P.soadisc cannot be read now: the permission to read it is
    gone"), and the disc asked for again [V L12d].
  - **`disc.c` reads that path through N itself** (`plat.h`: `plat_path_kind` `fstat`s N, `plat_fopen_rb` reads a
    `dup` of it; `elfcheck.c` the same), and `[disc]` still names `/proc/self/fd/N`. This text had `fopen` open
    the path again, and on Android 14 that is refused: a check run's probe of the picked store logged
    "/storage/emulated/0/Download/GEAE8P.soadisc, f_type 0xef53, open by name: Permission denied", an ext4
    lower-filesystem descriptor, with `persist.sys.fuse.passthrough.enable` unset [V L12d]. A pipe or a socket is
    refused there as a stream, to be copied first.
  - **Only when all four hold** (`import_in_place`); otherwise it is copied, and the `[android]` line says why:
    - a regular file that seeks (research §7; "a stream (a pipe or a socket)");
    - from the phone's own storage, one of `com.android.externalstorage.documents`,
      `com.android.providers.downloads.documents` and `com.android.providers.media.documents`, compared whole
      ("not this phone's storage"), since a cloud's would be asked for 1.4 GB at every launch;
    - not served from `/mnt/appfuse`, where Android puts a provider's descriptors made on demand ("a proxy
      (/mnt/appfuse)");
    - its grant kept ("the permission could not be kept").
  - **Checked before anything is copied,** through its descriptor, by `disc_open`: the id, the revision, the
    executable (§3.3 step 4), the file table, and every file in it inside the image ("a truncated dump or copy?").
    `disc.txt` is written only once `disc_open` has accepted the disc; when it cannot be written, the run plays all
    the same and the `disc.txt` before stays as it was, which the next launch takes; the log says which disc it
    names. With this disc named, read the same way, the next launch plays it, and with none it asks for the disc
    [V L12d, both].
  - **A read that fails inside the image once it is open stops the run** with `[exit] 9` and
    `[disc] cannot read <path> at 0x<offset> (+<n> bytes[, disc offset 0x<o>]): <why>; was its storage removed?`,
    the why being the system's words, or "it is N bytes now, and was M when it was opened". It is never served as
    zeros. On a phone, before the app closes, a box says why, as it does when a damaged block stops the run
    (below): `disc_stop_words`, a sentence a player reads, with the disc named as it was picked in place of its
    descriptor's path. A damaged disc is forgotten first (`disc.txt`, and the app's copy if it made one), so the
    next launch asks for one [V, the damaged block read in place, L12d's stop box].
- **Otherwise, copied** by `runtime/import.c` into `noBackupFilesDir/copy/`, as `disc.soadisc` or `disc.iso`,
  named by its content, never by its provider's name:
  - it needs its size and 512 MiB more free, kept for the card's next write, and takes the space first
    (`fallocate`); it is capped at 2 GiB, and held to the size its provider gave ("the copy stopped at 65536 of
    2236416 bytes: GTSE01.soadisc ended early; pick it again" [V L12d]);
  - a stream's first MiB is checked (`disc_identify`: the boot magic, RVZ or WIA, the game id, the revision) before
    the rest is read [V L12d];
  - its progress shows with a Cancel, the screen held on; it is synced and made `0444`, checked again as the disc
    the port will read, renamed into place (its folder synced too), and then its grant is released;
  - a refused pick leaves no copy and no grant, and the disc before goes, copy and grant, once a new one is
    accepted.
  The disc's picker offers files on the phone only (`EXTRA_LOCAL_ONLY`), so a player whose disc is in a cloud
  downloads it to the phone first: one 1.4 GB copy rather than two [I]. No cloud provider was tried (L12d).
- **The I4 store is the recommended thing to pick.** It is one file, it says if a copy damaged it (I5's block
  hashes, which stop the run with `[exit] 9` through the descriptor as on the PC [V L12d]), and it is 2% smaller.
  An ISO or GCM works as on the PC. An RVZ is refused, saying how to make an ISO of it on the PC (Dolphin's Convert
  File): no refusal on a phone names `python tools/`, `soa.exe` or `recompile.py` (`disc_set_phone_words`).

### 3.8 One data root, and the logs

- **The root.** `SDL_main` sets `SOA_ROOT` to `filesDir` and `chdir()`s into it, both before `main()`.
  - `SOA_ROOT` moves everything that hangs from `settings_root()`: `soa.ini`, the card, the mods, the pipeline
    cache and the recordings (§2).
  - `chdir` moves the raw relative defaults.
  - `plat_exe_path` is never asked on Android.
  - The first run writes `soa.ini` there, with `render = 1`, once the import is done and only when there is none;
    a check run never writes it. Without it, `SOA_RENDER` is never defaulted (`settings.c:433`), and no window
    opens [V L12d: `[import] wrote …/files/soa.ini: render = 1`, then `[window] open at 2x`].
- **The import's files are in `noBackupFilesDir`,** which SoaActivity passes as `SOA_NOBACKUP` and which neither a
  backup nor a move to a new phone carries: the library (`libsoa_game.so`, 0444), `disc.txt` (`uri=`, `name=`,
  `authority=`, `copy=`), the pending picks (`pending_library`, `pending_disc`) and the disc's copy (`copy/`). A
  library L12c left in `files/` is moved there at the first launch [V L12d], and the `.tmp` files a stopped copy
  left are swept at every launch.
- **The card:** `build/cards/slotA.raw` under the root. Its export and import through the picker, since the format
  is Dolphin's, are not built: they are proposed as their own slice, L12h.
- **The logs:** stderr goes to `soa.log` in the root (the last two runs kept) and to logcat (tag `soa`), through
  a pipe and a thread. The report lines are the PC's, so `scenario.py check` can read a log pulled from the
  phone.

### 3.9 The window, the pads, the touch overlay

- **The window and the pads:** `window_sdl.c` as it is. The phone's built-in pad, and Bluetooth or USB pads,
  come through SDL (research §3).
- **Its thread on Android:** its own, as on the desktop [V L12c]. The window, the renderer, the keyboard, the
  pads and the lifecycle all work from `window_sdl.c`'s thread. SDL's thread runs `SDL_main`, which runs `main()`,
  which joins the guest as it does everywhere, so `main.c` and `plat.c` are unchanged.
- **The background events** are caught in an `SDL_AddEventWatch` filter, on the thread that sends them
  (research §8). In the pump loop they arrived only once the app was back, just before the foreground event: on
  Android SDL's pump blocks whichever thread calls it while the app is away [V L12c].
- **`SDL_EVENT_RENDER_DEVICE_RESET`** remakes the texture. Written, not seen: the emulator's context survived
  every trip to the background.
- **Landscape, and the whole screen.** SDL replaces the manifest's orientation with its own when the window is
  made, which for a resizable window with no hint is any orientation; `android.c` sets the hint to landscape.
  Fullscreen is the default there, so the system bars give way and a 1080-line screen has room for 2x
  (`fullscreen = 0` in `soa.ini` keeps the bars). The theme has no title bar.
- **The touch overlay (L12e)** follows port-android.md §5:
  - a GameCube layout: big A, small B, kidney X and Y;
  - a relative-centre stick;
  - digital L, R, Z, START and a D-pad;
  - the C-stick hidden until the disassembly shows the field reads it;
  - drawn inside `SDL_GetWindowSafeArea()`, hidden at the first physical input.
  It feeds `window_pad`, so pad recordings replay a touch session exactly. The Fold 8's two screens make the
  safe area and a size change mid-session part of its Done.

### 3.10 Sound

SDL picks AAudio (research §3), and `audio_out.c` keeps the 24-block rule L10 gave it. The rate check is L10's,
read from the `[audio]` line of a pulled log.

### 3.11 Lifecycle

- **`WILL_ENTER_BACKGROUND`,** in the event watch (§3.9):
  - `clock_pause(1)`, which holds the guest at the frame start (§2), and in `irq.c` wherever it waits for an
    interrupt, where it used to spin a core for as long as the app was away [V L12c];
  - `si_motor_stop()`;
  - nothing to flush: the card writes each program through (`exi.c`);
  - presenting stops, since SDL's pump holds the window's thread.
- **`DID_ENTER_FOREGROUND`:** the surface is made again, then `clock_pause(0)`.
- **A process killed in the background** loses only what the game had not saved, as on a console with the power
  off.

### 3.12 Pacing, power and the savepoint

- **Pacing:** `ANativeWindow_setFrameRate(window, 30, FRAME_RATE_COMPATIBILITY_DEFAULT)` on every new surface
  (SDL does not call it), and 60 under turbo (research §9).
- **Power:** an `APerformanceHint` session over the guest thread and the render workers, aiming at 33.3 ms. No
  affinity pinning (research §9).
- **The render pool:** the default worker count (`gxr.c:2087`) on Android counts the cores whose `cpu_capacity`
  (`/sys/devices/system/cpu/*/cpu_capacity`) is above the smallest [I].
- **All three wait for the phone** (L12's Done): the emulator's display is fixed at 60 Hz, it offers no
  performance-hint session, and its cores are all alike, so none of them could be measured there.
- **The savepoint stays `setjmp`.** Bionic's `setjmp` saves the signal mask, a system call each time [I]. But
  L12a counted about 47,000 savepoints over `title`'s 71 s on Linux: 2,000 context saves, and every interrupt
  delivered (about 44,800 of all kinds), so about 660 a second. At a microsecond each that is under a
  millisecond a second, so no change is made unless a phone's profile says otherwise.

### 3.13 The GPU on Android (L12f)

- **The surface:** `gxv.c` gains SDL's, through `SDL_Vulkan_GetInstanceExtensions` and `SDL_Vulkan_CreateSurface`
  (`VK_KHR_android_surface`), behind the same `gxv_present_open`. Linux gets the same for free.
- **The shaders:** their SPIR-V is runtime code, built into `libsoa_runtime.so` as on Windows.
- **Its Done:** the corpus drawn on the phone's GPU and judged by V0 against the CPU references (D-19).
- **Why it matters:** this slice is what makes the phone playable; the software renderer is the fallback.

### 3.14 Checking it without a person

- **The check mode.** The debug APK takes the run's environment as an intent extra:
  `--es env "SOA_SELFTEST=1;SOA_SETTINGS=0"`, plus `--es args "..."` and, since L12d, `--es pick "..."`: the
  `content://` URIs, `;` apart, that answer the import's picks in order, without the picker. The glue `setenv`s
  each variable before `SDL_main`, and any of the three sets `SOA_CHECK_RUN=1`. Only a debuggable build reads them
  [V L12c]: the activity is exported, and a release must not let another app choose what the port loads or how it
  runs. A check run without `SOA_IMPORT` is L12c's, but for the library's new home (§3.8), the phone's words
  (`disc_set_phone_words`, §3.7) and L12d's checks of the library (§3.3 step 3).
- **The import's check runs** (L12d):
  - `SOA_IMPORT=1` runs the import as a player's launch does; `library` or `disc` forces that pick; `forget`
    releases the disc's kept grant and keeps `disc.txt`, as a lost permission would leave them. Any other value
    ends the run with 1;
  - no box is shown: each is logged (`[import] box: …`) and answered with its first button. A refusal
    (`[import] refused <name>: <words>`) or a cancel ends the run with `[exit] 1`, and `soa.ini` is never written;
  - an empty `pick` queue is a cancel, unless `SOA_IMPORT_PICKER=1`, which opens the system's picker for
    `android.py` to drive;
  - only a check run logs §3.7's probe of opening `/proc/self/fd/N` by name.
- **The test provider,** in `android/app/src/debug/`, so a release has none: `<package>.testfiles`, not exported, so
  only the app opens it, through the `pick` extra. `content://<package>.testfiles/file/NAME` is a regular
  descriptor on `files/provider/NAME`, as the phone's storage gives one; `.../pipe/NAME` the same bytes through a
  pipe and a writer thread, as a cloud's provider may give them; `?truncate=N` on either stops after N bytes, while
  `query()` still says the whole size.
- **The end of a check run.** It writes `[exit] N` as its last log line and then `_exit(N)`s after flushing,
  whether `main()` returned or the runtime left by `exit`, `_exit` or `_Exit` (linked with `--wrap`, L12c).
  This matters for two reasons:
  - adb cannot see an app's exit status;
  - `SDLActivity` keeps the process alive after `SDL_main` returns, so a second launch would run `main()` over
    the first run's statics.
- **`tools/android.py`** drives it over adb:
  - `install`;
  - `push-game`, `push-corpus` and `push-disc`: a library (into `no_backup/` since L12d), the corpus, and an image
    or a store into `files/extracted/`, where `main.c` looks by default, through `run-as` into the debug app's
    storage;
  - `run`: launch, then wait for `[exit]`. Since L12d it takes `--pick` (a `content://` URI, or `file/NAME` or
    `pipe/NAME` for a file `provide` put there); `--tap TEXT`, `--key KEYCODE` and `--kill-before-tap`, which drive
    the system's picker from uiautomator's dump of the screen and set `SOA_IMPORT_PICKER=1`; and `--font-scale X`.
    `--key KEYCODE_BACK` is pressed until the picker goes, at most 4 times: opened in Download, the picker takes
    the first Back as "up a folder" [V L12d];
  - `selftest`, and `replay`: one launch per capture and thread count, 23 x 4, as `scenario.py replay` runs one
    process each, compared with the manifest by `scenario.py`'s own comparison;
  - `logs`;
  - since L12d: `provide`, a file for the test provider; `stage`, a file into `/sdcard/Download`, where the picker
    opens, once `df` says the shared storage and the app's both have room for it and 512 MiB more; `mutants`, the
    ten libraries the import must refuse, built against the APK's record and the executable it plays, each with
    the line it must draw (`--push` provides them); `player`, the player's own path with no extras, its boxes and
    files tapped by their text and each step's screen captured (`--fresh`, `--reimport`, `--font-scale`, `--out`);
    `reboot`, of the AVD `soa_x86_64` and no other device, its new boot awaited, then unlocked and its screen held
    on; and `grants`, the URI grants the app holds, each kept or not.
- **The emulator:** the installed android-34 x86_64 image, with an x86_64 game library (§3.4), is the first
  target of every slice.
- **The phones:** the AYN Thor first, since its Snapdragon 8 Gen 2 is the target's floor
  (port-android.md §1.3), then the Fold 8.
- **Game data:** the captures and the library go only onto the owner's own devices, never to CI.

### 3.15 Mods: deferred to L12g

- **What they are:** the three shipped mods (`mods/autotext`, `coop`, `encounter-rate`) are runtime-side native
  code, which may be in the APK. They would be built per ABI into it and loaded from `nativeLibraryDir`, with
  their `mod.ini` from the APK's assets.
- **Until L12g:** `SOA_MODS` is unset on Android, and the first-run screen says mods are not there yet.

---

## 4. Order

| Slice | Needs | Proves |
|---|---|---|
| L12a | nothing new | the seam, on Linux in a container |
| L12b | L12a | the PC's game library for Android, checked as a file |
| L12c | L12b | the shell on the emulator: the self test, the replay, the title, the lifecycle |
| L12d | L12c | the import on the emulator: each refusal, read in place, the copy |
| L12's Done | L12d, the Thor | the replay and a session on the phone |
| L12e | L12c, a phone | touch |
| L12f | L12c, a phone | the GPU |
| L12g | L12c | mods |

The sysroot of §3.4 and R5's packaging (Setup's checkbox) follow L12b.

---

## 5. Slices

### L12a. The seam on the desktop

*Built 2026-10-05 (FINDINGS "L12a"), with forwarders where this text first rewrote every reference (§3.2).*

*Files:*
- `tools/recompile.py`: `gen/game_table.c`, the `.note.soa` record, and `--split` for gcc and clang into its own
  directory, `gen/linux-split/`, always `--no-decomp`;
- `config/seam.txt`;
- the references through the table: `runtime/main.c`, `irq.c`, `mod.c`, `threads.c`, `selftest.c` and `disc.c`;
- the test stand-ins of §3.2: `test_memguard.py`, `test_mods.py`, `test_profiler.py`, `tools/citest/threads_driver.c`;
- `tools/tests/test_seam.py`;
- docs.

*What it does:*
- `--split` builds `libsoa_runtime.so`, `libsoa_game.so` and a 20-line launcher, `soa`.
- The launcher links the runtime and `dlopen`s the game library from beside itself, through `elfcheck.c` (§3.3).
  This is Android's arrangement, on a desktop.
- Single-file builds, `gen/linux/soa` among them, call the same table directly.

*Done:*
- **In a Docker container** (TESTING.md section 2's recipe), with `gen/linux-split/soa`:
  - the self test reports 0 failures;
  - `scenario.py replay --exe gen/linux-split/soa --threads 1,2,3,8` matches 23/23 against the same manifest;
  - `title --check` holds 4 of 4;
  - the frame time is within the noise of `gen/linux/soa` (interleaved runs, H11's method), and the savepoints a
    second are counted (§3.12).
- **Windows unchanged:** `soa.exe` through the table, the self test, and replay 23/23.
- **`test_seam.py` on CI** (the gcc and clang legs) builds a synthetic game library of two functions with the
  real `game_table.c` template. The checks:
  - its dynamic symbols are exactly the export, and its imports are a subset of `seam.txt`;
  - a record naming another `cpu.h` is refused by `elfcheck`, naming the rebuild;
  - an import the runtime lacks is refused by `elfcheck`, before `dlopen`;
  - one without `soa_game` is refused.
- **`test_seam.py` against the real build,** in the container: the libraries' dynamic symbols are exactly
  `seam.txt`'s, imports and exports.
- **The mutations:**
  - a runtime symbol added to the synthetic library's imports and not to `seam.txt` fails;
  - `cpu.h`'s hash changed in the note fails.

### L12b. The game library from the PC

*Built 2026-10-05 (FINDINGS "L12b"), but `player_build.py --target`. A player's package carries no NDK, so
that waits for Q-A2's own sysroot and R5's packaging. The C checker and the Python one are held together by
building the same libraries and comparing their verdicts, rather than by a written table.*

*Files:*
- `tools/soa/toolchain.py`: the `android-arm64` and `android-x86_64` profiles, finding the NDK through
  `SOA_ANDROID_NDK`, `ANDROID_NDK_HOME` or `ANDROID_HOME/ndk/*`;
- `tools/recompile.py`: the stub runtime library;
- `tools/soa/elfcheck.py`, §3.3's checks in Python, held to `elfcheck.c` by a shared test table;
- `tools/player_build.py`: `--target`;
- `tools/tests/test_android_build.py`.

*Done:*
- `recompile.py --cc android-arm64 --compile --optimize --link` makes `libsoa_game.so`, and `elfcheck` passes
  it:
  - AArch64 and `ET_DYN`;
  - `PT_LOAD` aligned 0x4000;
  - `DT_NEEDED` `libsoa_runtime.so`;
  - exports `soa_game` alone, and imports `seam.txt`'s;
  - the note's record matches the tree.
- Two builds are byte-identical.
- Without an NDK, the build says where it looked.
- The compile time is measured and written down.
- **The mutations:** `-z max-page-size=4096` fails `elfcheck`; `-fvisibility=default` fails the export check.

### L12c. The shell, on the emulator

*Built 2026-10-06 (FINDINGS "L12c"). Gradle is fetched by `android.py` into `vendor/` against a pinned
sha256, not run through a wrapper whose jar the repository would carry. The window's loop stays on its own
thread (risk 4), so `main.c` and `plat.c` keep their join; `setFrameRate`, the performance hint and the
worker default wait for the phone (§3.12); the savepoint stays `setjmp`. The emulator found five things no
desktop had shown, each fixed here: bionic's x86-64 `fma` (`cpu.h`, `soafma.c`, `soa_fma` in the seam); the
SDK's audio calibration, which never ends where a clock read is slow (`__AI_SRC_INIT` bound in `hle.txt`,
answered in `hle_os.c`, a twin case in the self test); the runtime's own exits, which lost the log's end
(`--wrap` for all three); the background events, which came only once the app was back (§3.9); and a
paused guest spinning a core (§3.11, `irq.c`).*

*Files:*
- `android/`: Gradle with the wrapper pinned, `app/build.gradle.kts`, `CMakeLists.txt`, `SoaActivity.java`;
- `runtime/android.c` (`#ifdef __ANDROID__`): `SDL_main`, the root, logcat, the check mode's end,
  `setFrameRate` and the performance hint;
- `runtime/window_sdl.c`: the event watch, the loop on SDL's thread, `RENDER_DEVICE_RESET`;
- `runtime/main.c` and `plat.c`: the guest started without a join on Android;
- `runtime/gxr.c`: the worker default (§3.12);
- `runtime/cpu.h`, `threads.c` and `irq.c`: `_setjmp` and `_longjmp` on Android, if L12a's measurement says so;
- `tools/fetch_sdl.py --android`;
- `tools/android.py`;
- `tools/guard.py --apk`;
- docs.

*Done, on the android-34 x86_64 emulator, with an x86_64 library pushed by `android.py`:*
- the self test reports 0 failures (`[exit] 0`);
- the replay matches 23/23 at 1, 2, 3 and 8 threads against the same manifest;
- the title screen is reached from the keyboard;
- Home then back resumes: the `[clock]` lines show the pause, and the surface is made again;
- `SOA_MEMPOKE=0x81800000` is survived, with the guard's report, inside the app under ART's `libsigchain`
  (risk 5);
- `guard.py --apk` passes the debug APK, and fails one whose runtime library has `disc_sys.c` compiled in (the
  real leak, at a 4-byte offset).

### L12d. The import

*Built 2026-10-06 (FINDINGS "L12d"). The picks are SoaActivity's own `ACTION_OPEN_DOCUMENT`, not SDL's file
dialog, which nothing cancels but its result, which cannot open in a chosen folder or ask for local files only,
and which starts the picker off the UI thread (§3.3). The disc is read through its descriptor: on Android 14
opening `/proc/self/fd/N` again by name, as this text had `fopen` do, is refused (§3.7). Its design review refuted
"another disc needs no new check": a library made from another disc's executable is now refused by its record's
`dol=`, the first link of a chain that ends at the disc's own executable (§3.3 step 4). The way back to the
first-run screen, which this text left to "a long press", is a launcher shortcut, "Choose the game files again"
(§1). The rules for a picked descriptor and the copy itself are C, in `runtime/import.c`, where CI's Linux legs
test them, since CI never builds the Java (§3.6). Beyond its Done, the emulator ran the player's own path with no
extras, Back in the picker, the process killed with the picker up, a font change mid-pick, and L12c's emulator
checks again; the destroy path came with that font change's mutation (§3.6). Not measured: a whole disc copied and
then played, a Cancel during a copy on the device, the box an app update opens when the library no longer fits,
three of the design's mutations, and any cloud provider (FINDINGS "L12d"). The card's transfer is not built
(§3.8), and the words of the boxes and refusals wait for the owner's look.*

*Files:*
- `runtime/android.c`: the first-run flow, the library before the disc; SDL's message boxes, drawn by
  SoaActivity; the glue's calls through JNI; the pending picks and `disc.txt`; `soa.ini` on the first run; the
  library moved from `files/` to `no_backup/`; the check mode (§3.14);
- `runtime/import.c`, `import.h` (new): what is read in place and what is copied, the copy, the sweep and the
  names (§3.7). Its body is Linux's (`#ifdef __linux__`); elsewhere it compiles to stubs that refuse;
- `runtime/disc.c`, `disc.h` and `plat.h`: a `/proc/self/fd/N` path read through N, and a stream refused; a read
  that fails inside the image stops the run, exit 9; a file table that runs past the image's end refused, and a
  broken set of built-in system files at the open; the phone's words; `disc_identify`, `disc_port_dol_sha1` and
  `disc_refused_by_build`;
- `runtime/elfcheck.c`, `.h` and `tools/soa/elfcheck.py`, word for word alike: `ElfWant`'s `android` and `dol`,
  and what §3.3 step 3 gained;
- `runtime/game.c`, and `runtime/game.h` (new, the runtime's alone): `soa_check_game`, `soa_load_game` (one
  `dlopen` per process) and `soa_game_dlopened`;
- `android/`: `SoaActivity.java` (§3.6); `AndroidManifest.xml`, whose `configChanges` gains density, fontScale,
  fontWeightAdjustment, grammaticalGender, touchscreen and colorMode, since SDL ends the process when its activity
  is made again (without fontScale, a font change mid-pick kept the run from ever ending [V L12d]), and which
  gains `appCategory="game"`, which keeps Android 16 from ignoring landscape on a screen 600 dp wide or more, the
  Fold's inner one; `app/build.gradle.kts` and `app/proguard-rules.pro`, a release type with minify off and the
  members `android.c` reaches kept; `app/src/debug/`, the test provider (§3.14); `CMakeLists.txt`, whose runtime
  glob is asked again at every build, so a file added later, as `import.c` was, is built;
- `tools/android.py` (§3.14), and `tools/soa/gamefixture.py` (new): `android_mutants()`, the ten libraries each
  wrong in one way, with the words each must draw;
- `tools/citest/disc_check.py` and `disc_driver.c`; `tools/tests/test_import.py` (new; CI's Linux legs run it with
  no skips), `test_android_jni.py` (new), `test_android_build.py`, `test_seam.py` and `test_android_tool.py`;
- docs.

*Done, on the emulator:*
- **Each of §3.3's refusals in the player's words:**
  - another ABI;
  - 4 KB alignment;
  - another `cpu.h` in the note;
  - an import the runtime lacks;
  - another disc.
- **The disc:**
  - read in place, with `[disc]` naming `/proc/self/fd/N`;
  - a pipe-backed provider takes the copy path;
  - the grant survives a reboot.
- **The store:** a damaged block stops the run with `[exit] 9`, as on the PC.

### L12's Done: the phone

On the AYN Thor, then the Fold 8:
- the self test reports 0 failures;
- `android.py replay --threads 1,2,3,8` matches 23/23, from a library built on this PC;
- `title`'s invariants hold on the pulled log;
- a FINDINGS entry gives the frame rate at the Dangral base, software-rendered, on each;
- the owner's session: title to the first field with a pad; their list is filed.

### L12e. Touch

*Files:* `runtime/window_sdl.c` (the overlay); `runtime/si.c`, if a touch needs anything of the recording; docs.

*Done:*
- a touch session recorded with `SOA_PAD_RECORD` replays to the same frames;
- the overlay hides at the first pad input and returns at the next touch;
- on the Fold 8, it follows the fold and unfold within the safe area;
- the owner judges it on both devices.

### L12f. The GPU on Android

*Files:* `runtime/gxv.c` (the SDL surface), `runtime/window_sdl.c` (presenting from the GPU, as window.c does),
the CMake that builds the shaders into the runtime library, docs.

*Done:*
- `SOA_GPU=vulkan` on the phone draws the corpus, judged by V0 against the CPU references;
- the frame rate at the Dangral base;
- its review page for the owner's look.

### L12g. Mods

*Files:* `android/` (the mods built per ABI, their `mod.ini` as assets), `runtime/android.c` (`SOA_MODS`).

*Done:* the three shipped mods load on the emulator and switch on, as `test_mod_library.py` does on Linux.

---

## 6. For the owner

- **Q-A1. The devices.** ***Answered 2026-10-05:*** a Samsung Galaxy Z Fold 8 and an AYN Thor. The Thor's
  Snapdragon 8 Gen 2 is the target's floor, so it goes first.
- **Q-A2. The player's compiler for the game library.** ***Answered 2026-10-05: A,*** llvm-mingw plus this
  repository's own Android sysroot from AOSP's BSD sources (§3.4).
- **Q-A3. Android 13 or newer** (`minSdk 33`). ***Answered 2026-10-05: yes.***
- **Q-A4. The app's identity.** *Open: the owner asked for an explanation first.*
  - **The package name** (for example `io.github.bmfrench89.soa`) is the app's permanent ID on every phone.
    Android installs an update only over an app with the same name, and the app's storage (the card, the
    imported library) belongs to that name.
  - **The release key** is a file that signs every APK. An update installs only if it is signed with the same
    key as the copy already there, so a lost key means players must uninstall, and lose the app's storage, to
    update.
  - **Registration (Q-D3)** ties the name and the key to the owner with Google before its global rollout
    (2027).
  - **Nothing needs either** until someone other than the owner installs the APK. Debug builds use a working name
    and the SDK's debug key.

---

## 7. Risks

1. **A second guest thread** would stop the phone as it stops Linux (portability risk 18). Every log so far
   shows one.
2. **Speed.** The software renderer runs the Dangral base at the 30 fps cap on a quiet Z1 Extreme (29.8 fps,
   HANDOFF). Phones throttle, and the Thor's chip is slower per core (port-android.md §1.3). L12f is the answer.
3. **A future SELinux rule.** Mapping app data as code is allowed but audited (`auditallow`, research §1). If it
   is ever blocked, the fallback is `android_dlopen_ext` with a file descriptor.
4. **SDL's thread.** §3.9 assumed video must stay on SDL's main thread. Settled by L12c: it need not, and
   `plat_run_on_big_stack` is unchanged.
5. **The MEM1 guard under ART.** ART's `libsigchain` interposes `sigaction`, so `plat.c`'s SIGSEGV handler is
   chained behind ART's. Settled by L12c: `SOA_MEMPOKE=0x81800000` inside the app is reported once, and the run
   goes on to its frame limit.
6. **Thermal throttling** changes timing, not results. The replay is exact at every thread count, and the frame
   rates say which run they came from.
7. **The process freezer** suspends a cached app 10 s after it goes to the background (research §8). The guest is
   parked by then: asleep, since L12c, where it had been spinning (§3.11). An import's copy (§3.3, §3.7) stops
   with the app and goes on when it is back: L12d gave it no job or foreground service [I, not measured].
8. **The sysroot of §3.4** is new work, and its headers must agree with the bionic each phone runs. The savepoint's
   `jmp_buf` belongs to the runtime (`guest_savepoint`), which the APK builds against the NDK, so the game
   library's view of `setjmp.h` matters only for the declaration [V `cpu.h:111`].

---

## Review log

One review on 2026-10-05, read-only against the code at d6d64aa. What it changed:

1. **The root.** `settings_root()` ignores the working directory: it is `SOA_ROOT` or the executable's folder,
   `/system/bin` in an app. `chdir` alone would have lost `soa.ini`, the card and the window. §3.8 sets
   `SOA_ROOT` too.
2. **The check mode.** There is no `--selftest` flag; the checks are environment. adb cannot see an exit status,
   and SDL keeps the process. §3.14 passes the environment, ends with `[exit] N` and `_exit`.
3. **The record** was two files; distribution §3.8 means all of `player_build.BAKED`, plus the mode. §3.2.
4. **The refusals** came after `dlopen`, which fails first on a missing import. §3.3 reads an ELF note and the
   imports before it.
5. **`SOA_NO_DECOMP`** was unstated for the APK and the split build, and the seam differs by mode (13 or 25
   bindings, 6 or 18 `recomp_fn_` twins). §2, §3.1, §3.2.
6. **`libmain.so`** could not have called the runtime under an exact export list. `SDL_main` moved into the
   runtime library. §3.1.
7. **A file descriptor passed to `disc.c`** would have been closed by `main.c:1298`'s `disc_open`. §3.7 passes
   `/proc/self/fd/N` as the path instead. L12d then found that opening the path again is refused on Android 14, so
   `disc.c` reads it through N (§3.7).
8. **The count** of runtime symbols was 23, not 22.
9. **Mods** were neither covered nor deferred. §3.15, L12g.
10. **L12a's paths and tests:** `--split` had the single-file build's path; the stand-ins in four tests were
    missing; `test_seam.py` needed `gen/` and could not run on CI. L12a now has its own directory and a
    synthetic library.
11. **L12c's files** were missing `window_sdl.c`, `main.c`, `plat.c` and `gxr.c`, and risk 5's poke had no Done
    line. L12e and L12f had no files.
12. **`guard.py --apk`** as an allowlist would have passed trivially; it is a deny scan with a 4-byte step over
    `.so` entries now, and the mutation compiles `disc_sys.c` in.
13. **Staleness:** two raw defaults (`main.c:165`, `:1238`) and the frame rate (29.8 fps since H15c's 27).
14. **The savepoint's cost:** bionic's `setjmp` saves the signal mask; §3.12.
