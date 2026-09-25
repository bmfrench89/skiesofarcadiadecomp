<!-- Written 2026-09-25 by a read-only research agent on how native ports ship on Android, and what that implies here, at HEAD 12e45a8. Nothing in
the repository was changed and the game was not run; compiler probes and syntax checks ran in a scratch
directory only. A second agent then checked this report's key claims; its corrections come first, below,
and supersede the text where they disagree. The summary built from all four reports is
docs/research/android-and-native.md. [V] = checked in code, a tool run or a dated page; [I] = inference. -->

# Porting this port to Android, and not needing the disc every time

> **Corrections from verification.** A skeptic checked this report's key claims; these did not fully hold.
>
> - **partly:** The decompiled code's 32-bit types are declared as long, so on Android arm64 (where long is 64 bits) u32 and s32 silently become 64-bit in every native twin built from src/.
>   - **Correction:** include/types.h:14-15 does typedef s32/u32 as long, and Android arm64 is LP64, so those typedefs would widen. But no native twin uses u32 or s32. The six units marked native in config/GEAE8P/units.txt (string.c, mem.c, strcpy.c, strcmp.c, fillmem.c, strstr.c) contain 0 uses. The u32/s32 users (ar.c, arq.c, ppcarch.c, aramcache*.c/h) are built only by mwcc, never natively. The real LP64 problem in the twins is the bare `unsigned long` in their word-at-a-time loops, and it is worse than the claim says. In fillmem.c:15-16,29-47, v fills only 32 bits, but each `*++w = v` stores 8 bytes, so every 32-byte block writes 64 bytes: a guest-memory overrun, with zeroed upper halves. memset (0x80005434, config/hle.txt:26) calls __fill_mem, so this runs in-game. strcmp.c:18-19 already says it 'assumes a 32-bit unsigned long'. Also, the '47 uses' are 47 lines from grep -w (3 in types.h, 2 in comments), not 47 uses.
> - **partly:** Guest threads use Win32 fibers with no non-Windows path, and Android's libc gives no ucontext fallback, so a hand-written ARM64 context switch is needed.
>   - **Correction:** The facts hold. threads.c:110 ConvertThreadToFiber, :301 CreateFiber and :306 SwitchToFiber are all under _WIN32. The #else at :309-311 prints 'fibers are Windows-only for now' and calls exit(6). The NDK r28c sysroot ships ucontext.h and sys/ucontext.h but declares no getcontext, makecontext, setcontext or swapcontext; a grep found none. The conclusion is too strong. A context switch you write yourself is one option. Others are an existing ARM64 coroutine library (Boost.Context fcontext, libco, minicoro) or one pthread per guest thread with a hand-off semaphore, so only one runs at a time. N64Recomp's runtime takes the thread approach.
> - **partly:** The Windows-only surface is concentrated: 37 `#ifdef _WIN32` sites in 10 of the 25 runtime .c files, mostly window.c (467 lines) and audio_out.c (149 lines); the generated C in gen/ uses no compiler-specific keywords.
>   - **Correction:** The counts hold at HEAD: 36 #ifdef _WIN32 plus 1 #ifndef, in 10 of the 25 .c files, with window.c 16-462 and audio_out.c 6-145 under one guard each. A scan of all 19 gen/*.c and functions.h finds no __declspec, intrinsics or pragmas, and cpu.h:46-54 has __builtin_bswap fallbacks. But the _WIN32 lines are not the whole Windows-only surface. Unguarded MSVC/Win32 code at HEAD: gxr.c:122 __declspec(thread); :143 __declspec(align(64)); :1547-1548 and :1572 LONGLONG/LONG; :1577 InterlockedIncrement64; :1614 Sleep(0)/YieldProcessor; :1619 _ReadWriteBarrier. Also dvd.c:103 _fseeki64, and aram.c:160-172 falls back silently off MSVC (__argv). So gxr.c and dvd.c do not compile under the NDK's clang as they stand. Clang for AArch64 also fuses a*b+c into FMA by default (-ffp-contract=on), which changes the translated float results. PLAN-GAMEPLAY-MODS G4 already lists -ffp-contract=off as required.
> - **partly:** Google's developer verification leaves adb installs exempt; it is enforced in Brazil, Indonesia, Singapore and Thailand from 2026-09-30 and globally in 2027; free limited-distribution accounts allow up to 20 devices.
>   - **Correction:** The cited pages (developer.android.com/developer-verification and the 2026-03-19 blog) do not mention adb. The exemption is on developer.android.com/developer-verification/guides: 'ADB workflow and experience stays the same.' The 2026-09-30 phase is narrower than stated. It covers only installs from seven participating stores (Google Play, HONOR App Market, OPPO App Market, Galaxy Store, Palm Store, V-Appstore, GetApps), on certified devices running Android 7+, in those four countries. A GitHub APK sideloaded there is not covered until the global phase, 'In 2027, we'll expand this globally to all apps on certified devices.' The 20-device limit holds: 'up to 20 devices without needing to provide a government-issued ID or pay a registration fee.' The advanced flow for unverified apps is 'a one-time, one-day wait'.
> - **unverifiable:** Compiling the port on the phone at first launch would take roughly 5-30+ minutes on a recent flagship and longer on mid-range devices, and needs about 100 MB or more of bundled compiler, so it is not a realistic first step.
>   - **Correction:** This is an inference. Most inputs check out: 19 units (18 chunks plus dispatch.c); the largest is chunk_005.c at 5,453,989 bytes (5.2 MiB); 103 s for the /O2 compile per TESTING.md:317-318 and ROADMAP.md:126 ('16 cores', meaning 16 logical CPUs). The .c files total 56.18 MiB; '56.4 MiB' only holds with gen/functions.h (0.22 MiB) added. recompile.py:184 compiles through ThreadPoolExecutor(max_workers=os.cpu_count()), and 19 units on 16 workers means the 1,100-1,650 CPU-second bracket is plausible. The largest unit also sets a serial floor of minutes on its own. I could not find the 'RPCSX Thor tuning caps LLVM at 4 compile threads' evidence in RPCSX/rpcsx-ui-android or RPCSX/rpcsx. The 92 MB RPCSX core is 92.3 MiB and includes the emulator, not only LLVM. No surveyed port compiles on the device. Unleashed's 'builds the patched executable itself on first launch' means XEX patching, not recompilation.
> - **partly:** The software renderer is the main obstacle to good Android performance: the Z1 Extreme reaches about 27 fps in the heaviest measured scene with 12 workers, so phones would need a GPU backend to be comfortable. An Aurora-style GX API layer cannot serve this game, because it writes the graphics FIFO directly.
>   - **Correction:** cb904fa did report Dangral at 27.2/26.8 fps with 12 workers. But its '19.2 / 19.0' with 8 workers was 'on the build before H15c', so the two numbers are not a worker-count comparison. HEAD 12e45a8 (copy images) reports the Dangral base at 25.9 -> 28.3 fps pooled over two A/Bs, against the game's own 30 fps cap. The Dangral base is the raster-bound scene. The heaviest guest-side scenes are warp and spoof, at 18.2 ms (performance.md:59, 11.9 ms median, both verified). The phone projection is inferred. 'Cannot serve' is too strong. SPEC.md:270-271 says every state-setting GX call remains 'an ordinary out-of-line function' and only per-vertex submission is inlined. All 1,508 gather-pipe store sites are known at translation time (SPEC.md:275-277). The middleware holding 868 of those writes is called 'a clean seam ... candidate to be reimplemented natively' (SPEC.md:292-300). An API-level layer is therefore possible after HLE or decompilation of the GX calls and the middleware; it is not a drop-in. A GPU backend fed by the FIFO the runtime already parses needs none of that.

*Written 2026-09-25. Read-only: nothing was built, run or changed. Repo line numbers are at HEAD `12e45a8`. **[V]** means I read it in the repo, in your installed Android NDK, or on the cited page (with its date). **[I]** means I inferred it.*

Four terms used below. An **APK** is an Android app package. The **NDK** is Google's C/C++ compiler kit for Android. The **SAF** (Storage Access Framework) is Android's system file picker. **adb** is the USB tool that installs an APK from a PC.

---

## 0. Short answers

**1. Android is feasible, but it is three projects, not one.**
- **An OS layer (days).** The Windows-specific code is in a few places: 37 `#ifdef _WIN32` sites in 10 of the 25 files in `runtime/` [V]. Most of it is in two files: `window.c` (467 lines: the Win32 window, the DXGI/GDI presenter, keyboard and XInput) and `audio_out.c` (149 lines, waveOut) [V]. The generated C in `gen/` uses no compiler-specific keywords [V].
- **ARM64 correctness (a few days).** Three things in the code today would break *without any error* on ARM64 Android: `u32` is declared as `long`, the renderer's work queue relies on x86 keeping loads in order, and Android's C library has no fiber API. Details in §1.2 [V].
- **Speed (the real risk).** On your Z1 Extreme, the software renderer reaches about 27 fps in the heaviest measured scene, using 12 worker threads [V]. An actively cooled Snapdragon 8 Elite handheld might come near that; phones and older chips will not [I]. Every port in the survey that plays well on Android renders on the GPU.

**2. Going "disc-free": no port anywhere removes the need for the player's own game data. The good ones ask for it once.**
- "Full native with no disc" would mean shipping Sega's art, music and code. SPEC.md §2 forbids that, and no well-run port ships assets.
- What you can have: pick the ISO or RVZ once, the app keeps one private copy, and you never think about it again.
- Today the PC setup keeps the data twice:
  - `extracted/disc.iso` (1,392 MiB);
  - the unpacked file tree (1,356 MiB) [V].

**3. The community ships compiled game code in its APKs; this project decided not to.**
- SPEC.md §2 rule 2 says the translated code is never distributed.
- For you personally, the realistic path is:
  - build the APK on your PC with the Android toolchain **you already have installed**: NDK r28.2 (clang 19), SDK platforms 34–36.1, build-tools 36–37 and adb [V, `%LOCALAPPDATA%\Android\Sdk`];
  - install it over USB with adb. adb installs are exempt from Google's new developer verification [V].
- Compiling on the phone, so that someone with only a phone could build it, is technically possible. The cost:
  - roughly 100 MB or more of bundled compiler;
  - an estimated 5–30+ minutes of compiling at first launch;
  - substantial engineering [I, §3].

Android is not mentioned anywhere in the repo's docs or code [V, grep]. SPEC.md:19 promises only that Linux and macOS will not be ruled out. `docs/research/plan-gaps.md:587` parks "an OS layer, ARM64, native Linux and macOS" as XL.

---

## 1. What this port would have to change

### 1.1 What it needs at run time and at build time [V]
- **Run time:**
  - `main.c:1087` defaults to the directory `extracted`;
  - `main.c:1139-1146` loads `sys/main.dol`, `sys/boot.bin` and `sys/fst.bin`, and the DOL's data sections are copied into guest memory;
  - `main.c:1192-1193` opens `<dir>/disc.iso`, and every game file after boot is a DVD read by disc offset (`dvd.c:81`).
- **Build time:** the code itself comes from the DOL.
  - `gen/` holds 18 `chunk_*.c` files plus `dispatch.c`: 56.4 MiB of C (ROADMAP 3.6 says 55.7 MB). The largest is `chunk_005.c` at 5.2 MiB.
  - `gen/soa.exe` is 21.6 MB.
  - Building at `/O2` takes 103 s on 16 threads, and the link about 20 s (`docs/TESTING.md:317-318`, `docs/research/mods.md:47`).

### 1.2 Code that is Windows-only or ARM64-unsafe

| Where | What it does today | What happens on Android / ARM64 | Size of fix |
|---|---|---|---|
| `include/types.h:14-15` | `typedef signed long s32; typedef unsigned long u32;` [V] | Android arm64 makes `long` 64 bits, so every decompiled unit built from `src/` gets a 64-bit `u32`. There are 47 uses of `long` in `src/` and `include/` [V]. Wraparound, shifts and struct sizes change with no error [I]. Windows is unaffected because `long` is 32 bits there. | hours: keep `long` under `__MWERKS__`, use `int` otherwise; add `_Static_assert(sizeof(u32)==4)` |
| `gxr.c:1547-1548, 1717, 1743-1747` (also `:1619`, `:1697`) | The work counters are `volatile LONGLONG`, and workers read them with plain loads. The comment says: *"this machine does not reorder two loads, so the command is there. The barrier is against the compiler alone… it emits nothing."* [V] | ARM64 can reorder two loads. A worker could see the new count and still read old fields of the command → wrong frames now and then, with no error [I; the code is V]. | about a day: C11 atomics, with acquire on reads and release on publish |
| `threads.c:110, 301, 310` | Guest threads run on Win32 fibers. Off Windows it prints "fibers are Windows-only for now" and exits [V]. | Your NDK r28 headers declare no `getcontext`, `makecontext` or `swapcontext` at all [V, grep of the sysroot]. It needs a small ARM64 assembly context switch, of the kind minicoro or libco provide [I]. The `longjmp` in `threads.c` stays on the same fiber, which keeps this simple [V]. | 1–2 days |
| `gxr.c:72` (`__cpuid`), `gxr.c:123` (`__declspec(thread)`), `gxr.h:209` (`__rdtsc`) | MSVC and x86 intrinsics [V] | Compile errors under the NDK's clang. | hours (`_Thread_local`, `clock_gettime`) |
| `tools/soa/toolchain.py:95-100` | `/fp:strict` stops the compiler fusing a*b+c into one operation [V] | ARM64 has a native fused multiply-add, so clang must be given `-ffp-contract=off`. The explicit `fma()` calls in the emitted C (391 in `chunk_004.c` alone) map to an exact `fmadd` [V count; I behaviour]. | minutes, plus a self-test case |
| `main.c:633-636` | `VirtualAlloc` reserve plus a vectored exception handler as the memory tripwire [V] | Use `mmap(PROT_NONE)` plus a `SIGSEGV` handler. The `calloc` fallback (`main.c:626-650`) already runs with no tripwire [V]. | hours |
| `gxr.c:118-120` | Each worker takes every Nth row [V] | This assumes all cores are equally fast. On Snapdragon 8 Gen 2-class chips, three little A510 cores would slow every fence [I]. Use only the big cores, set thread affinity, and give the performance hint (`APerformanceHint`, NDK API 33 [V header]). | hours |
| `window.c`, `audio_out.c` | Win32, DXGI, XInput and waveOut [V] | The NDK already has everything needed [V, headers in your NDK]:<br>- `ANativeWindow_lock` / `unlockAndPost` to put a CPU-drawn frame on screen, which suits a software renderer;<br>- `ANativeWindow_setFrameRate` (API 30) for 30/60 Hz on 120 Hz panels;<br>- AAudio (API 26);<br>- `AInputEvent` gamepad axes;<br>- `android_native_app_glue`.<br>Or use SDL3, which is Q6 in the gameplay-mods plan. | days |
| `mod.c:722` | `LoadLibraryExA` for mod DLLs [V] | Mods become per-ABI `.so` files, the same rule Zelda64Recomp-Android has [V]. Apps targeting Android 17 must mark files loaded with `System.load()` read-only [V]. | days |

**Already portable [V]:**
- `cpu.h:46-55` has byte-swap fallbacks.
- `cpu.h:508-516`: `ppc_fctiw` saturates explicitly, so x86 and ARM give the same result.
- The input seam is one function, `window_pad` (`window.c:398`). It fills the buttons, both sticks and both analog triggers, and `si.c` records and replays it.
- Card images are Dolphin-compatible (SPEC.md definition of done), so saves can move between PC and phone.

### 1.3 Speed [V figures, I projection]
**Measured on your Z1 Extreme [V]:**
- Dangral: 27.2 fps with 12 workers and 19.2 fps with 8 (commit `cb904fa`), against the game's 30 fps cap.
- The guest thread spends a median 11.9 ms per frame, 18.2 ms at worst, at `/O2`, out of a 33.3 ms budget (`docs/research/performance.md`).

**Comparison chips:**
- In Geekbench 6, the Snapdragon 8 Elite beats the Z1 Extreme single-core by 11–30% and is comparable multi-core [V, cpu-monkey]. The Z1 Extreme's scores are 2,534 and 11,358.
- The Snapdragon 8 Gen 2, as in the AYN Thor, is 1× X3, 4× A715/A710 and 3× A510 [V, RPCSX-Thor report].

**Projection [I]:**
- An 8 Elite handheld with a fan might approach Z1 Extreme rates.
- Phones throttle.
- 8 Gen 2 and mid-range devices would fall well short.
- A GPU backend is what makes Android comfortable. PLAN parks it until H15d's numbers are in.

**Aurora is not a drop-in.**
- Aurora advertises Android, but it replaces the GX *API* for decompiled code.
- This game writes the gather pipe directly: 414 stores to `0xCC008000`, and the middleware alone holds 868 of the 1,508 FIFO writes (SPEC.md:73, :292) [V]. An API-level GX layer never sees those writes.
- A GPU backend here has to consume the FIFO, the way Dolphin's VideoCommon does. Dolphin is GPL-licensed, so take ideas, not code [I].

---

## 2. How native ports of console games ship on Android (2025–2026)

| Project | Official Android? | Stack | How game data is supplied | Game code inside the APK? | Distribution | Controls |
|---|---|---|---|---|---|---|
| **Ship of Harkinian** | No. The upstream README lists Windows, Linux, macOS and Switch only [V]. Community forks: Waterdish, linkzenic [V]. | libultraship; "OpenGL ES 3.0+ required" [V] | Pick the ROM in the app; the asset archive is extracted on the device [V] | Yes, decompiled code [V] | GitHub releases [V] | Touch or controller [V] |
| **2Ship2Harkinian** | Community forks (linkzenic, Waterdish) [V] | libultraship | same | decompiled | GitHub | touch + pad |
| **Ghostship** (SM64) | **Yes.** PR #250 "Android on device extraction" merged **2026-09-06**. Release 3.0.0 (**2026-09-07**) ships `Nautilus-Alfa-Android.zip` at 13.4 MB [V] | SDL; NDK 30; arm64-v8a and armeabi-v7a [V] | "take a ROM through the document picker and runs Torch on the device to produce `sm64.o2r`", checked against supported SHA-1s. Tested on a Pixel 10a (Android 16) [V] | decompiled | GitHub | — |
| **Starship** / **SpaghettiKart** | Starship: `starship-v1.0.3.apk` from izzy2lost. Assets are made with Torch, then the folder is selected [V]. SpaghettiKart: no Android build found [V, negative search] | libultraship | Torch extraction | decompiled | direct APK | — |
| **sm64ex / sm64coopdx** | Community. robertkirkman's sm64ex-coop is **built on the phone in Termux** (clang, make, apksigner), with the ROM placed before the build and **no prebuilt APKs** [V]. coopdx v1.0 (2024-07-01) moved ROM asset extraction to run time [V]. ManIsCat2's Android fork Av1.5.1 (**2026-06-01**) is a 148 MB APK; v1.5 "Added a rom picker" [V] | SDL / GLES | ROM picker at run time | decompiled | GitHub | per-button customizable touch controls [V] |
| **Perfect Dark** | izzy2lost fork lists Android arm64-v8a, armeabi-v7a, x86_64 and x86 [V] | SDL | ROM must match a known md5 [V] | decompiled | GitHub | — |
| **Zelda64Recomp** (N64Recomp) | Upstream: Windows, Linux, macOS; "ARM64 builds will work on any ARM64 CPU"; "releases do not contain game assets. The original game is required to build or run" [V]. **Community** linkzenic/Zelda64Recomp-Android 0.6.10 (**2026-07-29**), 35 MB APK [V] | RT64 on Vulkan; SDL input [V] | "provide your own supported ROM when the app asks for it" [V] | **Yes, the recompiled code** [V by construction] | GitHub [V] | ABXY, BAYX and **GC** touch layouts; a "held physical-stick-style touch camera"; gyro [V] |
| **UnleashedRecomp** / MarathonRecomp | Upstream is x86-64 only and requires AVX; its releases contain the recompiled code [V]. Community: an ARM64 Linux fork (fathonix) and Android forks (SansNope and others), 0.5.3 on **2026-07-22**. Their README says it was built "with Anthropic's Fable 5 AI" [V]. MarathonRecomp has an Android test fork [V] | Vulkan 1.3 with Turnip; Oboe audio; SDL [V] | In-app installer via SAF: zip, folder or ISO/packages [V] | **Yes, a prebuilt APK containing recompiled PPC code** [V] | GitHub | drag-to-arrange touch editor; context-aware (D-pad in menus, SKIP in cutscenes) [V] |
| **ReXGlue / re:Blue** | No Android. CI builds for linux-arm64; re:Blue has presets for linux-arm64 and mac-arm64 [V] | — | user's own files | recompiled | GitHub | — |
| **Aurora / Dusklight** | **Yes, official.** Aurora runs on "Windows, Linux, macOS, iOS, tvOS, Android" (MIT) [V]. Dusklight v2.0.2 (**2026-09-25**) ships `Dusklight-v2.0.2-android-arm64.apk`, 55.9 MB [V] | SDL3; WebGPU through Dawn (D3D12, Vulkan, Metal); OpenGL ES is "best-effort" on older Android [V] | SAF picker. The `nod` library reads iso, gcm, ciso, gcz, rvz, wia and others **at run time** [V] | decompiled | GitHub; no Play Store [V] | v1.4 (2026-06-16): customizable touch, touch in menus, native gyro and rumble [V] |
| **Metaforce** | No Android. Alpha, builds unavailable. EctoPad is an iOS/macOS downstream [V] | Aurora | — | — | — | — |
| **OpenGOAL** | Official ARM64 is in progress ("Implement bulk of ARM64 instructions", Q2 2026 report) [V]. Community moukrea fork has an Android APK. Its README sends users to a releases page for both the APK and `jak1_assets.zip` (~1 GB) [V]. **That is distributing game-derived data, a counterexample.** | GLES, optional Vulkan [V] | — | yes | GitHub | touch + Bluetooth [V] |
| **RPCSX** (PS3) | Android UI (GPLv2). APK 10.6 MB (**2026-08-29**), targetSdk 37, minSdk 29 [V] | Compiles PPU code with **LLVM on the device**. It **downloads** a 92 MB core `librpcsx-android-arm64-v8a-<isa>.so` from GitHub at run time and `dlopen()`s it (`native-lib.cpp:72`, `RpcsxUpdater.kt`) [V]. LLVM 20.1.3 android-arm64 build: a 638 MB 7z [V] | File picker for firmware and ISO/PKG/folder [V] | no (emulator) | GitHub only [V] | touch + pad |

**What the survey shows:**
- Every project checked ships through GitHub or a direct APK; none is on Google Play [V].
- Every project needs the player's own data. The good ones ask once, through the SAF picker, and check a hash.
- Every project except robertkirkman's on-device sm64 build ships compiled game code in the APK, whether decompiled or recompiled. Your project is stricter than the community norm on purpose.

---

## 3. Could the phone build the port itself?

**The Android rules [V]:**
- **No running programs from app storage.** An app targeting API 29 or later "cannot invoke `execve()` directly on files within the app's home directory", so a bundled clang cannot run from `filesDir`.
- **Termux's workaround.** Termux ships its executables as `lib*.so` files with `extractNativeLibs=true`, so they land in the read-only, executable `nativeLibraryDir`. RPCSX sets `jniLibs.useLegacyPackaging = true` [V].
- **Termux on Play is at risk.** Its Play build uses `system_linker_exec`, which the Termux team says "violates PlayStore policies".
- **Loading compiled code is allowed, with conditions.**
  - Code you write to storage can be `dlopen`ed, but not mapped executable through a writable file descriptor, and not with text relocations.
  - From Android 17 targets (platform stability 2026-03-26), "All native files loaded using System.load() must be marked as read-only" or it throws `UnsatisfiedLinkError`.
  - RPCSX calls `dlopen` directly on a downloaded library, at targetSdk 37.

**What it would cost:**
- **Compile work.** 56 MiB of C in 19 units: 103 s wall on 16 Zen 4 threads with MSVC `/O2` [V]. That is about 1,100–1,650 CPU-seconds [I: the low figure scales the 5.2 MiB largest chunk ≈ 103 s by size; the high one is 16 × 103].
- **A phone.** RPCSX's Thor tuning caps LLVM at 4 compile threads on an 8 Gen 2 [V]. With 4 threads at 0.5–1.0× Zen 4 per core, and clang taking 1–2× MSVC's time [I]:
  - about **5–30 minutes** on a recent flagship;
  - **30+** on mid-range;
  - worse under thermal throttling.
- **Memory.** Several clang processes on 5 MiB translation units could need gigabytes of RAM, and Android's low-memory killer may end the app [I]. Smaller chunks would cap it.
- **A faster, weaker compiler does not rescue it.** Something like TinyCC compiles quickly but produces roughly unoptimised code. The guest thread already needs 11.9–18.2 ms of its 33.3 ms per frame at `/O2`, so an unoptimised build would probably miss 30 fps [I].
- **Payload.**
  - The APK would need to carry clang, lld and a sysroot, on the order of 100 MB or more [I]. For scale, RPCSX's LLVM-bearing core is 92 MB [V].
  - It would also need the recompiler: `tools/soa/ppc` plus `recomp` is 2,477 lines of Python [V]. That means rewriting it or embedding Python.
  - The player still supplies the disc, because the DOL is the input.

**Verdict:** possible, but not the first step. The alternative that drops C entirely is to translate PowerPC straight to LLVM IR inside the app, as RPCSX does. That is an emulator-sized project [I].

**A zero-code experiment:**
- Run `soa.exe` in Winlator (Wine plus Box64) on an Android handheld. Winlator 11.x is current in 2026 [V].
- By default Box64 does not fully emulate x86 memory ordering (`BOX64_DYNAREC_STRONGMEM`, levels 0–4 [V]). Given `gxr.c:1743`, use a STRONGMEM level of 1 or more, or few renderer threads [I].
- Expect a large speed penalty. It shows how the game feels on the device; it proves nothing about native speed [I].

---

## 4. Google Play and sideloading

**Google Play:**
- **Copyright.** "We don't allow apps that infringe copyright" [V]. An APK containing translated Sega code is not Play material. Dolphin is on Play because "THIS APP DOES NOT COME WITH GAMES" [V].
- **Downloaded code.** Play apps "may not download executable code (such as dex, JAR, .so files) from a source other than Google Play" [V].
- **If it were ever on Play:**
  - new apps and updates must target API 36 from 2026-08-31 [V];
  - native code must support 16 KB pages from 2025-11-01, which NDK r28 does by default [V].

**Developer verification, as of September 2026 [V]:**
- Developer APIs, the power-user "advanced flow" and limited-distribution accounts arrived in August 2026.
- It is enforced from **2026-09-30 in Brazil, Indonesia, Singapore and Thailand**, and globally in **2027**.
- **adb installs are exempt.**
- The advanced flow is a one-time process with a protective waiting period (reported as 24 h).
- **Limited-distribution accounts** are free, need no ID, and allow up to 20 devices.

**What this means for you:** `adb install` of your own build works now and after 2027. Friends would need their own build anyway under SPEC §2.

---

## 5. Controls

**In the repo [V]:**
- Everything goes through `window_pad` (`window.c:398`), and pad recordings capture it.
- The game compares the trigger bytes against 25 and 10 (`FINDINGS.md:1013-1017`), so a digital touch trigger can send 255 plus the L/R button bit.
- Whether the field reads the C-stick is still an open M12 spike (`PLAN-60FPS-MODS.md:615`).

**What good ports do [V]:**
- **Dolphin Android's overlay** offers Edit Layout, Scale, Opacity, Adjust Controls, Reset Overlay, Toggle Controls, Toggle All, Latching Controls and **Relative Stick Center**.
- **Dolphin's input overhaul** (PR #11385, merged 2023-03-11) added profiles, sensors and rumble.
- **Analog touch triggers were never merged** (PR #8590), so digital triggers are the norm.
- **Zelda64Recomp-Android** offers a GC touch layout, a touch camera and gyro.
- **Unleashed-Android** has a drag-to-arrange editor and context-aware buttons.
- **Dusklight** has customizable touch controls, gyro and rumble.
- **sm64coopdx** customizes each button separately.

**Recommendation for Skies of Arcadia:**
- a GameCube layout by default: big A, small B, kidney X/Y;
- a relative-center stick;
- digital L/R, Z, START and a D-pad;
- the C-stick hidden until disassembly (not one run's count) shows the field reads it;
- edit, scale and opacity;
- hide the overlay on the first physical input;
- haptics.

All of it feeds `window_pad`, so recordings stay deterministic.

**Physical controllers:**
- Android handhelds' built-in pads and Bluetooth pads arrive as standard gamepads (`AInputEvent`, or SDL3).
- An official GameCube adapter works over USB OTG in Dolphin [I for other stacks].
- Touch-to-select inside the game's own menus needs knowledge of the game's UI. Dusklight has that from decompiled source; a recompiled binary does not, soon [I].

---

## 6. "Disc-free": what is achievable

| Level | What the player keeps | Work | Posture |
|---|---|---|---|
| 0. Today | `disc.iso` (1,392 MiB) plus the file tree (1,356 MiB), plus a local build [V] | — | fine |
| 1. One copy | Only `disc.iso`, or only the tree, served through E2's virtual disc (`beyond-gamecube.md` §4) | days | fine |
| 2. Import once | The app takes ISO/GCM/RVZ (there is already a reader in `tools/soa/rvz.py` [V]), checks it is `GEAE8P`, stores it privately, and the player never picks it again | days to a week | the same as every surveyed port |
| 3. Compressed store | Little is saved: 65% of the files are already AKLZ-compressed (SPEC.md §3). It would also need a decompressor, and `vendor/` is forbidden | a week | fine |
| 4. No DOL at run time | Bake the data sections into your personal binary | hours to days | personal builds only |
| 5. No game data at all | Impossible without shipping or remaking Sega's content | — | no |

**Why there is no separate asset pipeline to swap:** the translated code finds everything by guest address and disc offset, so the disc image *is* the asset pipeline.

sm64coopdx went from "ROM at build time" to "ROM picked at run time" (v1.0, 2024-07-01), and that is what made prebuilt binaries possible [V]. This port already takes its data at run time. Its blocker is that the *code* comes from the disc at build time, and only distributing the code or translating on the device removes that.

---

## 7. A suggested order
1. **Hours, on Windows; it also helps Linux and the Steam Deck.**
   - Fix LP64 in `types.h`.
   - Use atomics in the renderer's work queue.
   - Guard `__cpuid`, `__rdtsc` and `__declspec(thread)`.
   - Add `-ffp-contract=off`.
   - Add the clang compile-only CI job plan-gaps already proposes.
2. **Days: a thin platform layer.** It covers present, pad, audio sink, fibers, guest-memory reserve and guard, futex/WaitOnAddress, clocks, and reading files through a file descriptor.
3. **Days: an Android shell.**
   - NativeActivity (glue in the NDK) or SDL3.
   - A Kotlin SAF importer.
   - Gradle and CMake building *your* `gen/` with NDK clang.
   - Test the OS side on your installed **x86_64 Android emulator image** (android-34) [V]. It catches lifecycle, storage and input problems, not ARM memory ordering.
4. **A week: ARM64 on a real device.** Worker affinity, NEON when H15d lands, and measured fps.
5. **Large: a GPU backend (Vulkan).** It also serves the PC 60 fps and higher-resolution plans.
6. **Q3: the distribution decision.**

---

## 8. Lessons for this project
1. **Fix `include/types.h:14-15` now.** `u32` must be 32 bits on every native build. Add a `_Static_assert`, with a mutation that proves it fires.
2. **Retire the x86 load-ordering assumption at `gxr.c:1743`.** Use acquire and release atomics. ARM64 and Box64 both need it.
3. **Do not wait for a ucontext API on Android.** Bionic declares none [V]; use a small assembly context switch.
4. **Keep the OS layer thin.** `window_pad`, the audio sink and `present` are already the right seams.
5. **Build on the PC and install with adb.** It is exempt from verification, needs no Play Store, and keeps SPEC §2 intact.
6. **Do not plan on compiling on the device yet.** It means 5–30+ minutes of compiling, more than 100 MB of toolchain and a rewrite of the recompiler [I].
7. **Keep one copy of the disc, not two.** It saves about 1.3 GiB on a phone.
8. **Accept the formats players actually have.** ISO, GCM, RVZ, CISO, GCZ and WIA, as Dusklight's `nod` does, and check the hash at import, as Ghostship and Perfect Dark do.
9. **Do not promise Android playability before the GPU-backend decision.** The software renderer is the bottleneck even on the Z1 Extreme.
10. **Make the worker pool aware of big and little cores.** Row interleaving assumes equal cores.
11. **Use `ANativeWindow_lock` for the software frame and `setFrameRate(30/60)`.** It needs no GPU work to get a first picture.
12. **Build the touch overlay the proven way.** GameCube layout, relative stick, digital triggers, editable, hidden when a controller is used. Analog touch triggers are not worth the effort.
13. **Advertise moving saves between PC and phone.** The card image round-trips with Dolphin; export and import it through SAF.
14. **Native mods become per-ABI `.so` files.** Android 17 wants them read-only, and Play forbids downloaded code.
15. **Do not copy two patterns from the survey.**
    - The moukrea asset-zip pattern of downloading game data from a releases page.
    - The assumption that Aurora's GX API can see this game's direct FIFO writes: it cannot.

---

## Sources
- Android 10 W^X: https://developer.android.com/about/versions/10/behavior-changes-10
- Android 17 Beta 3, native DCL (2026-03): https://android-developers.googleblog.com/2026/03/the-third-beta-of-android-17.html
- Developer verification: https://developer.android.com/developer-verification · https://android-developers.googleblog.com/2026/03/android-developer-verification.html · https://www.androidauthority.com/android-sideloading-changes-timeline-3679204/
- Play Device and Network Abuse: https://support.google.com/googleplay/android-developer/answer/9888379 · Intellectual Property: https://support.google.com/googleplay/android-developer/answer/9888072 · target API: https://support.google.com/googleplay/android-developer/answer/11926878 · 16 KB pages: https://developer.android.com/guide/practices/page-sizes
- Termux and Android 10: https://github.com/termux/termux-packages/wiki/Termux-and-Android-10 · https://github.com/termux/termux-app/discussions/4000
- Ship of Harkinian: https://github.com/HarbourMasters/Shipwright · https://github.com/Waterdish/Shipwright-Android · https://github.com/linkzenic/2ship2harkinian-Android
- Ghostship: https://github.com/HarbourMasters/Ghostship/pull/250 · Starship: https://www.izzy2lost.com/starship
- sm64: https://github.com/robertkirkman/sm64ex-coop/blob/android/README_android.md · https://github.com/ManIsCat2/sm64coopdx/releases · https://github.com/coop-deluxe/sm64coopdx/releases/tag/v1.0
- Perfect Dark: https://github.com/izzy2lost/perfect_dark
- Zelda64Recomp: https://github.com/Zelda64Recomp/Zelda64Recomp · https://github.com/linkzenic/Zelda64Recomp-Android
- UnleashedRecomp: https://github.com/hedge-dev/UnleashedRecomp · https://github.com/raphasilv247/UnleashedRecomp-Android · https://github.com/SansNope/UnleashedRecomp-Android · https://github.com/fathonix/UnleashedRecomp-ARM64-Linux · MarathonRecomp: https://github.com/sonicnext-dev/MarathonRecomp
- ReXGlue: https://github.com/rexglue/rexglue-sdk · re:Blue: https://github.com/volstants/re-bluedragon
- Aurora: https://github.com/encounter/aurora · Dusklight: https://github.com/TwilitRealm/dusklight · https://twilitrealm.dev/posts/2026-06-16-dusklight-v1-4-released/ · https://duskport.com/dusk/install/android/
- Metaforce: https://github.com/AxioDL/metaforce · OpenGOAL: https://opengoal.dev/blog/progress-report-q2-2026/ · https://github.com/moukrea/jak-project
- RPCSX: https://github.com/RPCSX/rpcsx-ui-android · https://github.com/RPCSX/rpcsx-build/releases · https://github.com/noeldvictor/rpcsx-ui-android-thor/blob/master/report/2026-05-10-aps3e-rpcsx-thor-ppu-compile.md
- Dolphin overlay strings: https://github.com/dolphin-emu/dolphin/blob/master/Source/Android/app/src/main/res/values/strings.xml · PR #11385 · PR #8590
- Box64 STRONGMEM: https://github.com/ptitSeb/box64 · Winlator: https://github.com/brunodev85/winlator
- CPU comparison: https://www.cpu-monkey.com/en/compare_cpu-amd_ryzen_z1_extreme-vs-qualcomm_snapdragon_8_elite
