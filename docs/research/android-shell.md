<!-- Written 2026-10-05 by a read-only research agent for portability L12 and distribution R5, at HEAD d6d64aa. It read AOSP at android-17.0.0_r1 (and main), SDL at release-3.4.18 and the RPCSX repository at their sources, and ran two local link tests in a scratch directory; nothing in the repository was changed. [V] = read on a primary source or verified locally; [I] = inference. The spec built from it is docs/specs/android.md. -->

# The Android shell: loading the game library, SDL3, the toolchain

## 1. Loading a native library from app storage

**Yes: an app targeting 29 or later can still `dlopen` a `.so` from its own internal storage.** Android 10
removed `exec()` on files in the app's data, not mapping them as code.

- **SELinux** (AOSP `system/sepolicy`, main):
  - `private/untrusted_app_all.te`, every target SDK: `allow untrusted_app_all app_data_file:file { r_file_perms execute };`
    and `auditallow untrusted_app_all app_data_file:file execute;`, under "Some apps ship with shared libraries and
    binaries that they write out to their sandbox directory and then execute." [V]
  - `execute_no_trans` (`execve`) and `execmod` only in `untrusted_app_27.te` ("25 < targetSdkVersion <= 28"). [V]
  - `private/app_neverallows.te`: execute "cannot be blocked on all of app_data_file without causing backwards
    compatibility issues (see b/237289679)". [V] The `auditallow` logs every such mapping, so a future restriction is
    possible. [I]
- **Android 10** (behavior-changes-10, updated 2026-10-01): no `execve()` on files in the app's home directory; a
  library "cannot have been mapped `PROT_EXEC` through a writable file descriptor", which includes text
  relocations. Open it read-only; never build it with text relocations. [V]
- **Android 14**: "all dynamically-loaded files must be marked as read-only" (DEX and JAR). [V]
- **Android 17, targetSdk 37** (behavior-changes-17): "All native files loaded using `System.load()` must be marked
  as read-only. Otherwise, the system throws `UnsatisfiedLinkError`." [V]
  - In `libcore` `Runtime.java` at `android-17.0.0_r1`, `load0` throws when `!fs.isReadOnly() && file.canWrite()`
    and compat change `THROW_ERROR_FOR_WRITABLE_DCL = 463348571` is on, `@EnabledSince(targetSdkVersion = 37)`. [V]
  - Bionic's `linker.cpp` and `linker_phdr.cpp` at the same tag have no writable-file check: **a direct `dlopen`
    from native code is not covered.** [V]
- **The file:** mode 0444 (`File.setReadOnly()` or `Os.chmod(path, 0444)`) satisfies `System.load` and
  future-proofs `dlopen`. [V check; I advice]
- **Where:** the classloader namespace has `kAlwaysPermittedDirectories = "/data:/mnt/expand"`
  (`art/libnativeloader/library_namespaces.cpp`), and `dlopen` uses the caller's namespace (`get_caller_namespace`),
  so an absolute path under `/data/user/0/<pkg>/` called from the app's own library is permitted. [V] Prefer
  `noBackupFilesDir` (out of Auto Backup), never external `Android/data` (FUSE). [I]
- **RPCSX** (rpcsx-ui-android, pushed 2026-08-29): `targetSdk = 37`, `minSdk = 29`, `ndkVersion = "29.0.13113456"`;
  it writes `librpcsx-android-<abi>-<arch>.so` into `filesDir` (a `.tmp`, then `renameTo`), loads it with
  `::dlopen(path, RTLD_LOCAL | RTLD_NOW)` (`native-lib.cpp:72`) and `dlsym`s `_rpcsx_*` entry points; it never calls
  `setReadOnly`, which works because it bypasses `System.load`. Files from the picker go to native code as file
  descriptors (`openAssetFileDescriptor(uri,"r")`). [V]
- **If ever blocked:** `android_dlopen_ext` with `ANDROID_DLEXT_USE_LIBRARY_FD` (API 21) still needs an executable
  mapping; memfd's SELinux rule was not confirmed. [I]

## 2. Resolving symbols between two native libraries

- Bionic: "the dynamic linker searches the global group followed by the local group". The global group is "the main
  executable, LD_PRELOAD libraries, and any library with the DF_1_GLOBAL flag set (by passing '-z global')"; the local
  group is "the breadth-first transitive closure of the library and its DT_NEEDED libraries"; with `RTLD_LOCAL`,
  "symbols will not be made available to libraries loaded by later calls to dlopen"
  (`android-changes-for-ndk-developers.md`). [V]
- **`RTLD_GLOBAL` does not help.** Relocation uses `get_global_group()`, which collects only `DF_1_GLOBAL` libraries
  (`linker_namespaces.cpp:127`); the flag passed to `dlopen` is read only by `dlsym(RTLD_DEFAULT)` and cross-namespace
  sharing. SDL's `dlopen(libmain, RTLD_GLOBAL)` does not make its symbols visible to a later `dlopen`. [V source; I
  that nothing else rescues it]
- **`DT_NEEDED` works.** `find_library_internal` first calls `find_loaded_library_by_soname(ns, ...)` and reuses the
  copy already loaded in the namespace, which joins the new library's local group. Since API 23 the `DT_NEEDED`
  entry must equal the soname exactly, and a soname is mandatory. [V] libc's symbols then resolve through the
  runtime library's own `DT_NEEDED libc.so`, breadth first. [I]
- The NDK's build systems add `-Wl,--no-undefined`; link the game library against a stub of the runtime library, or
  allow undefined symbols. [I]

## 3. SDL3 3.4.x on Android

- 3.4.18 (2026-10-02) ships `SDL3-devel-3.4.18-android.zip` (16.7 MB): `SDL3-3.4.18.aar` and `INSTALL.md`. [V] The AAR:
  prefab modules `SDL3-shared` (`libSDL3.so` for armeabi-v7a, arm64-v8a, x86, x86_64), `SDL3-Headers`, `SDL3_test`;
  `classes.jar` (`org.libsdl.app`: `SDLActivity`, `SDLControllerManager`, `HIDDeviceManager`, `SDLAudioManager`...);
  `minSdkVersion 21`, `targetSdkVersion 35`; `abi.json` `"api":21,"ndk":28`; the arm64 `libSDL3.so` is aligned
  0x4000. [V, unpacked]
- Use: `buildFeatures { prefab true }`, `implementation files('libs/SDL3-3.4.18.aar')`, `find_package(SDL3 REQUIRED
  CONFIG)`. [V `INSTALL.md`]
- Template `android-project`: AGP 8.7.3, Gradle 8.12, compile and target SDK 35, min 21, `ndkVersion =
  "28.2.13676358"`, `abiFilters 'arm64-v8a'`; ndk-build by default, CMake with `-PBUILD_WITH_CMAKE`. [V] It uses the
  legacy `buildscript` and `applicationVariants.all`, which AGP 9 needs reworked. [I] SDL's CMake can also make a
  debug-signed APK with no Gradle (`README-android.md`). [V]
- **`main`:** `SDLActivity.getLibraries()` returns `{"SDL3","main"}`; `nativeRunMain(getMainSharedObject(),
  "SDL_main", args)` runs on the SDLThread, which `dlopen(library_file, RTLD_GLOBAL)`s and `dlsym`s `SDL_main`
  (`SDL_android.c` ~834-851). `main()`, `getMainSharedObject()` and `getMainFunction()` can be overridden. [V]
- **The picker:** `SDL_ShowOpenFileDialog` uses `ACTION_OPEN_DOCUMENT` + `CATEGORY_OPENABLE` and returns `content://`
  URIs; no folder dialog; SDL never calls `takePersistableUriPermission`. [V] `SDL_IOFromFile("content://...")`
  works: `SDL_iostream.c:899` → `Android_JNI_OpenFileDescriptor` → `openFileDescriptor(uri,"r")` → `detachFd()` →
  `fdopen`. [V]
- **Input:** gamepads through `SDLControllerManager` and HIDAPI (USB host, BLE); touch as `SDL_EVENT_FINGER_*`
  (`SDL_HINT_TOUCH_MOUSE_EVENTS` for synthetic mouse); edge-to-edge since Android 15 — `SDL_GetWindowSafeArea()`. [V]
- **Audio:** AAudio first, then OpenSL ES; `AAUDIO_PERFORMANCE_MODE_LOW_LATENCY`. [V]

## 4. 16 KB pages

- developer.android.com/guide/practices/page-sizes (2026-09-16): NDK r28 and later align 16 KB by default; older
  NDKs need `-Wl,-z,max-page-size=16384`; uncompressed libraries in an APK need AGP 8.5.1 or later; Play refuses
  updates without 16 KB support from 2027-02-01. [V] Pixel 8/8a/9/9a have the developer option; on a 16 KB kernel
  4 KB-aligned apps may run in a back-compatibility mode (`android:pageSizeCompat`). [V] No phone shipping 16 KB
  by default was found. [I]
- A player-built game library on a 16 KB kernel needs every `PT_LOAD` aligned to at least 16384; the importer
  should check before `dlopen`. [I] llvm-mingw's clang 23.1.2 with `-z max-page-size=16384` gave 0x4000. [V]

## 5. Toolchain

- NDK r30 (LTS, `30.0.16248370`) was released 2026-09-08, sysroot to API 37, a 728 MB Windows zip; r29 2025-10-06. [V]
  NDK 28.2.13676358 (clang 19.0.1) is still fine: the current AGP's default, 16 KB by default. [V]
- AGP 9.4.0 (September 2026): Gradle 9.6.0, Build Tools 36.0.0, default NDK 28.2.13676358, JDK 17 minimum, API to 37. [V]
- Command line only works: `gradlew assembleDebug` signs with the SDK's debug key; `adb install`. [V] The first run
  fetches Gradle and AGP. [I]

## 6. Sideloading and developer verification

- "As a developer, you are free to install apps without verification with ADB." [V FAQ]
- 2026-09-30: registration required for seven participating stores in Brazil, Indonesia, Singapore and Thailand;
  "Unregistered apps can be sideloaded with... adb or advanced flow"; global expansion "2027 and beyond". [V blog,
  2026-06-18] The advanced flow: a one-time setup, a one-day wait, then confirmation. [V] A limited-distribution
  account covers up to 20 devices, free; full distribution costs $25. [V]

## 7. Large files from the picker

- A grant lasts "until the user's device restarts" unless `takePersistableUriPermission` keeps it (not across a move
  or delete); `MAX_PERSISTED_URI_GRANTS = 512`. [V]
- `openFileDescriptor(uri, "r")` "could be a pipe or socket pair"; local providers give real files (FUSE, with
  passthrough since Android 12). [V]
- **Reading in place:** persist the grant; on each launch `openFileDescriptor(uri,"r")`, `detachFd()`, pass the fd
  down; `fstat` must say `S_ISREG` and `lseek` must work, then `pread`; otherwise copy into app storage. [I] Check
  free space first (`StorageManager.getAllocatableBytes`). [I]

## 8. Lifecycle

- SDL sends `WILL_ENTER_BACKGROUND` and `DID_ENTER_BACKGROUND` back to back; handle them in an event filter, "because
  the OS may not give you any processing time after". Stop rendering. With `SDL_HINT_ANDROID_BLOCK_ON_PAUSE` (default
  on) the event pump blocks while paused, and AAudio is paused. On `surfaceDestroyed` SDL releases the window;
  watch `SDL_EVENT_RENDER_DEVICE_RESET`. [V]
- SDL blocks only the thread that pumps events; other threads run until the process is cached, and since Android 14
  cached processes are frozen 10 s after, every thread suspended, or killed. [V] Targeting 37, audio in the
  background needs a foreground service. [V]

## 9. Performance hints

- `APerformanceHint` (`performance_hint.h`): sessions and work durations from API 33, `setThreads` 34,
  `setPreferPowerEfficiency` 35, configs and workload notices 36. [V]
- "it's generally best to avoid manually setting CPU affinities". [V]
- `ANativeWindow_setFrameRate` (API 30), with a change strategy (31); `FRAME_RATE_COMPATIBILITY_DEFAULT` for games;
  SDL 3.4.18 never calls it. [V]

## 10. Building the game library without shipping the NDK

- **The licence:** the NDK is under the "Android Software Development Kit License Agreement" (2026-04-28). [V]
  - 3.4: "you may not copy (except for backup purposes), modify, adapt, redistribute... or create derivative works
    of the SDK or any part of the SDK", except as third-party licences require.
  - 3.5: components "licensed under an open source software license are governed solely by the terms of that open
    source software license".
  - 3.2 bars use "to develop applications for other platforms".
  - The NDK carries Apache-2.0, BSD and MIT notices (`NOTICE`, 9,874 lines). Whether 3.5 lets parts be
    redistributed is a legal reading, not verified. [I]
- **Downloading it on the player's PC:** `https://dl.google.com/android/repository/android-ndk-r30-windows.zip`, SHA-1
  published; clause 2.2 ("By clicking to accept and/or using this SDK") means showing the agreement and recording
  acceptance, as `sdkmanager --licenses` does. [V clause; I procedure]
- **What compiling and linking needs:** clang, `ld.lld`, clang's resource headers, and from the sysroot `usr/include`
  (23 MB) plus `usr/lib/aarch64-linux-android/<API>/` (about 1 MB at 29: `crtbegin_so.o`, `crtend_so.o`, stub
  `libc.so`, `libm.so`, `libdl.so`). [V] bionic's sources and headers are BSD; kernel UAPI headers are generated;
  compiler-rt and libunwind Apache-2.0 with the LLVM exception. [V/I] Termux redistributes the NDK r30 sysroot as
  `ndk-sysroot`. [V]
- **A stock LLVM works:** llvm-mingw builds the AArch64 target; its clang 23.1.2 compiled for
  `--target=aarch64-linux-android29` and `ld.lld -shared -soname libsoa_game.so -z max-page-size=16384` linked against a
  stub runtime library: AArch64, `DT_NEEDED libsoa_runtime.so`, 0x4000 alignment. [V; not run on a device] Atomics
  emit `__aarch64_ldadd4_acq_rel` (outline atomics) and `long double` emits `__multf3`, which need compiler-rt
  unless built with `-mno-outline-atomics` and no `long double`. [V] Zig ships no bionic. [V secondary]

## Sources

- AOSP: system/sepolicy (untrusted_app_all.te, untrusted_app_27.te, app_neverallows.te); libcore Runtime.java and
  VMRuntime.java at android-17.0.0_r1; bionic linker.cpp, linker_phdr.cpp, linker_namespaces.cpp,
  android-changes-for-ndk-developers.md; art/libnativeloader/library_namespaces.cpp; UriGrantsManagerService.java;
  ContentResolver.java.
- developer.android.com: about/versions/10, 14 and 17 behaviour changes; guide/practices/page-sizes;
  ndk/downloads; build/releases/gradle-plugin; build/building-cmdline; training/data-storage/shared/documents-files;
  developer-verification (FAQ, guides); agi/sys-trace/threads-scheduling; frame-rate guide; studio/terms.
- android-developers.googleblog.com, 2026-06-18 (verification timeline). source.android.com (FUSE passthrough,
  cached-apps freezer).
- SDL release-3.4.18: android-project, docs/README-android.md, src/core/android/SDL_android.c, src/io/SDL_iostream.c,
  src/events/SDL_androidevents.c; release asset SDL3-devel-3.4.18-android.zip.
- github.com/RPCSX/rpcsx-ui-android; github.com/android/ndk/releases; termux-packages (ndk-sysroot);
  llvm-mingw build-llvm.sh.
