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
which a long press reopens. Saves are the card image, which Dolphin, the PC build and the phone share (§3.8).

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
  - The translated code imports 53 symbols (`nm` on the Linux build):
    - the 25 bindings the runtime answers (`config/hle.txt`);
    - 23 runtime functions and globals: `dec_read`, `dec_write`, `g_watch_addr`, `g_watch_len`,
      `guest_resumed`, `guest_savepoint`, `guest_syscall`, `guest_timebase_hi`, `guest_timebase_lo`,
      `guest_trap`, `gx_pipe_write`, `hook_80237BA8`, `irq_poll`, `mmio_read8`, `mmio_read16`, `mmio_read32`,
      `mmio_read64`, `mmio_write8`, `mmio_write16`, `mmio_write32`, `mmio_write64`, `trace_hit`, `watch_hit`;
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
- **The bindings depend on the build mode.** `hle.txt` binds 25 functions. `decomp_swap.c` answers 12 of them
  with decompiled code, and a build with no `src/` (`--no-decomp`, the player's build, distribution §3.1)
  leaves those 12 to translated twins inside the game. 13 then cross the seam, and the self test's twins become
  6 `recomp_fn_` and 15 `fn_` (`selftest.c:1504-1518`).
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
| `libsoa_runtime.so` | the APK build | `runtime/*.c` with `SOA_SDL` and `SOA_NO_DECOMP`, and `SDL_main` (`runtime/android.c`) | `SDLActivity`, which calls its `SDL_main` (`getMainSharedObject()` overridden) |
| `libsoa_game.so` | the player's PC (§3.4) | the translated code and the player's system files | the runtime, by `dlopen` (§3.3) |

- **Which libraries `SDLActivity` loads:** `getLibraries()` returns `{"SDL3", "soa_runtime"}`. There is no
  separate `libmain.so` (research §3).
- **`SOA_NO_DECOMP` always.** The APK holds no decompiled code (distribution §3.1).
- **`runtime/android.c`** is inside `#ifdef __ANDROID__`, since every `runtime/*.c` goes into every desktop
  link (`recompile.py:286, :335`) and `compile_runtime.py`.
- **What the runtime library exports:** the seam (§3.2), plus `SDL_main` and the JNI entry points its Java glue
  calls (§3.6).

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
    files, the record's abi and mode, and all 21 twins. So Windows checks the table on every run.
- **A split build** (`--split`) also writes `<out>/runtime_seam.c` into the runtime library. It holds
  forwarders, under the names the runtime calls, through the loaded table: `dispatch`, `dispatch_known`,
  `fn_80003140` and the 21 twins.
  - So `irq.c`, `mod.c`, `threads.c` and `selftest.c` do not change, and neither do the tests' stand-ins.
  - Only `main.c` (its `main` is `soa_main` under `SOA_SPLIT`) and `disc.c` change. A function cannot stand in
    for an array, so `disc.c` reads the system files from the table.
- **No forwarder clashes with the game's own names:** they are hidden in both libraries (§2: no function pointer
  crosses).

**Visibility.**
- The game library is compiled `-fvisibility=hidden`, with `soa_game` alone visible. The 7,144 functions call
  each other directly.
- The runtime library's exports are generated from a checked-in `config/seam.txt` (the 23 runtime symbols) and
  from `hle.txt` with `decomp_swap.c` (the 13 bindings under `--no-decomp`). They are linked with a version script
  that exports nothing else.

### 3.3 Loading the game library

1. **The pick:** `SDL_ShowOpenFileDialog` returns a `content://` URI (research §3).
2. **The copy:** streamed into `noBackupFilesDir/libsoa_game.so.tmp`, renamed into place, then `chmod 0444`
   (research §1).
3. **Before any `dlopen`,** from the file's own headers, `runtime/elfcheck.c` checks:
   - AArch64 (x86_64 on the emulator) and `ET_DYN`;
   - every `PT_LOAD` aligned to at least 16384;
   - no `DT_TEXTREL`;
   - `DT_NEEDED` including `libsoa_runtime.so`, and nothing outside it, `libc.so`, `libm.so` and `libdl.so`;
   - the `.note.soa` record against the runtime's;
   - **every undefined dynamic symbol against the runtime's own export list.** Otherwise `dlopen(RTLD_NOW)` would
     fail first, with the linker's words.
   Each failure is refused in the player's words:
   - "this library was built for x86-64 Windows, not this phone";
   - "this library was built for 4 KB pages; rebuild it with this package";
   - "this library was built by package 1.2 and this app is 1.3: rebuild it with Setup".
4. **`dlopen(path, RTLD_NOW | RTLD_LOCAL)` from native code,** never `System.load`. Android 17's read-only rule
   binds `System.load`, and the file is read-only anyway (research §1). Then `soa_game` is checked for its `abi`,
   and the disc's DOL SHA-1 against the record.
5. **Precedent:** the RPCSX app does steps 1 and 4 at target SDK 37 today (research §1).

### 3.4 The game library on the player's PC (R5)

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
- **The Java glue,** `SoaActivity extends SDLActivity`:
  - `getLibraries()` and `getMainSharedObject()` (§3.1);
  - persisting the picker's grants;
  - the streamed copies;
  - the check mode's extras (§3.14).
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
  - The picked URI's grant is persisted, by the Java glue, since SDL never does it (research §3).
  - On each launch the glue opens a file descriptor. It must be a regular file that seeks (research §7).
  - The glue passes it to `main()` as `argv[1] = /proc/self/fd/N`, which `fopen` and `plat_path_kind` read as
    the file. So `disc.c` and `main.c:1298` need no change.
- **Otherwise, copied** into `noBackupFilesDir`: a cloud provider, a pipe, or a grant that is gone. Free space is
  checked first, and the copy says how big it is.
- **The I4 store is the recommended thing to pick.** It is one file, it says if a copy damaged it (I5's block
  hashes), and it is 2% smaller. An ISO or GCM works as on the PC. An RVZ is refused, naming the PC command that
  converts it.

### 3.8 One data root, and the logs

- **The root.** `SDL_main` sets `SOA_ROOT` to `filesDir` and `chdir()`s into it, both before `main()`.
  - `SOA_ROOT` moves everything that hangs from `settings_root()`: `soa.ini`, the card, the mods, the pipeline
    cache and the recordings (§2).
  - `chdir` moves the raw relative defaults.
  - `plat_exe_path` is never asked on Android.
  - The first-run screen writes `soa.ini` there, with `render = 1`. Without it, `SOA_RENDER` is never defaulted
    (`settings.c:432`), and no window opens.
- **The card:** `build/cards/slotA.raw` under the root. It is exported and imported through the picker, since
  the format is Dolphin's.
- **The logs:** stderr goes to `soa.log` in the root (the last two runs kept) and to logcat (tag `soa`), through
  a pipe and a thread. The report lines are the PC's, so `scenario.py check` can read a log pulled from the
  phone.

### 3.9 The window, the pads, the touch overlay

- **The window and the pads:** `window_sdl.c` as it is. The phone's built-in pad, and Bluetooth or USB pads,
  come through SDL (research §3).
- **Its thread on Android:** SDL's main thread. SDL's event pump belongs to the thread that started video
  [I; L12c settles it].
  - So `main()` there starts the guest on the big-stack thread without waiting for it, and runs the window's loop
    on its own thread until the run ends.
  - This changes `main.c` and `plat.c`'s `plat_run_on_big_stack`, which joins today.
- **The background events** move from the pump loop into an `SDL_AddEventWatch` filter, so they run before
  Android stops the app (research §8).
- **`SDL_EVENT_RENDER_DEVICE_RESET`** remakes the texture.
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
  - `clock_pause(1)`, which holds the guest at the frame end (§2);
  - `si_motor_stop()`;
  - the card flushed;
  - presenting stops.
- **`DID_ENTER_FOREGROUND`:** the surface is made again, then `clock_pause(0)`.
- **A process killed in the background** loses only what the game had not saved, as on a console with the power
  off.

### 3.12 Pacing, power and the savepoint

- **Pacing:** `ANativeWindow_setFrameRate(window, 30, FRAME_RATE_COMPATIBILITY_DEFAULT)` on every new surface
  (SDL does not call it), and 60 under turbo (research §9).
- **Power:** an `APerformanceHint` session over the guest thread and the render workers, aiming at 33.3 ms. No
  affinity pinning (research §9).
- **The render pool:** the default worker count (`gxr.c:2087`) on Android counts the cores whose `cpu_capacity`
  (`/sys/devices/system/cpu/*/cpu_capacity`) is above the smallest [I; L12c measures it].
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
  `--es env "SOA_SELFTEST=1;SOA_SETTINGS=0"`, plus `--es args "..."`. The glue `setenv`s each variable before
  `SDL_main`.
- **The end of a check run.** It writes `[exit] N` as its last log line and then `_exit(N)`s after flushing.
  This matters for two reasons:
  - adb cannot see an app's exit status;
  - `SDLActivity` keeps the process alive after `SDL_main` returns, so a second launch would run `main()` over
    the first run's statics.
- **`tools/android.py`** drives it over adb:
  - `install`;
  - `push`: the corpus and a library, through `run-as` into the debug app's storage;
  - `run NAME`: launch, then wait for `[exit]`;
  - `replay`: one launch per capture and thread count, 23 x 4, as `scenario.py replay` runs one process each,
    compared with the manifest by `scenario.py`'s own comparison;
  - `logs`.
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

*Files:*
- `runtime/android.c`: the first-run screen, with SDL's message boxes and pickers;
- `runtime/elfcheck.c`;
- `SoaActivity.java`: the persisted grants, the copies, the descriptor passed as `/proc/self/fd/N`;
- tests.

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
4. **SDL's thread.** §3.9 assumes video must stay on SDL's main thread. L12c finds out first, and the change to
   `plat_run_on_big_stack` follows from what it finds.
5. **The MEM1 guard under ART.** ART's `libsigchain` interposes `sigaction`, so `plat.c`'s SIGSEGV handler is
   chained behind ART's [I]. L12c's Done pokes it inside the app.
6. **Thermal throttling** changes timing, not results. The replay is exact at every thread count, and the frame
   rates say which run they came from.
7. **The process freezer** suspends a cached app 10 s after it goes to the background (research §8). The guest is
   already parked by then.
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
   `/proc/self/fd/N` as the path instead.
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
