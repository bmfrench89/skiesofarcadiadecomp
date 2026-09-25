<!-- Written 2026-09-25 by a read-only research agent on the portability audit (Linux, ARM64, Android), at HEAD 12e45a8. Nothing in
the repository was changed and the game was not run; compiler probes and syntax checks ran in a scratch
directory only. A second agent then checked this report's key claims; its corrections come first, below,
and supersede the text where they disagree. The summary built from all four reports is
docs/research/android-and-native.md. [V] = checked in code, a tool run or a dated page; [I] = inference. -->

# Porting to Linux, ARM64 and Android, and depending less on the disc

> **Corrections from verification.** A skeptic checked this report's key claims; these did not fully hold.
>
> - **partly:** clang contracts multiply-add expressions into fmadd on aarch64 at -O2 by default and not on x86-64, so every non-MSVC build must pass -ffp-contract=off to both gen/ and runtime/.
>   - **Correction:** The conclusion holds and is if anything stronger; the 'not on x86-64' premise holds only for baseline x86-64. I reproduced with NDK clang 19 -O2. aarch64-linux-android29 and aarch64-pc-windows-msvc emit fmadd, and -ffp-contract=off gives fmul/fmul/fadd/fadd. Baseline x86_64 gives mulss/addss only because it lacks the FMA ISA. With -mfma, -march=x86-64-v3 or -march=znver4 (the owner's Z1 Extreme is Zen 4), x86_64 emits vfmadd231ss too. So an x86 Linux, Steam Deck or clang-cl build tuned for the host also needs -ffp-contract=off. /fp:strict is toolchain.py:100 and applies to both gen and runtime (recompile.py:166, 214, 228). The plane equation is gxr.c:1201 at HEAD 12e45a8 (:1200 was c0d59e2). Note also PLAN-GAMEPLAY-MODS.md:1417 area: the emitter already emits fma() for guest fmadd, which is exact on every host.
> - **partly:** gen/ is 58.9 MB of C in 19 translation units (7,144 functions), and an -O2 ARM64 build of it is about 14 core-minutes, roughly 1.5-3 minutes wall on a 16-thread PC, comparable to MSVC's 103 s.
>   - **Correction:** Sizes verified: 18 chunk_*.c plus dispatch.c = 58,911,696 B and 1,690,463 lines; 7,144 'void X(CpuState* s)' definitions; the largest is fn_801A6BDC at 9,233 lines. ROADMAP.md:126 says 103 s 'on 16 cores'. The time is unmeasured: a linear by-byte extrapolation from one 259 KB slice timed at nice 19 (58.9/0.259 x 3.7 s = 841 s = 14 core-min, arithmetic correct). The wall-time lower bound is set by the largest TU: chunk_005.c, 5,453,989 B, extrapolates to about 78 s alone. The 9,233-line function may compile superlinearly at -O2. So '1.5-3 min' is plausible but unverified. I did not time a full chunk, to avoid perturbing the other session's timing test.
> - **partly:** No prebuilt APK can be distributed, because the executable contains code translated from the DOL; each player builds on a PC and sideloads. Android 10+ still allows dlopen of a user-built .so from app storage (it bans execve), but Google discourages it.
>   - **Correction:** SPEC.md:44-45 (§2 item 2) forbids committing generated code, and PLAN-GAMEPLAY-MODS.md:1417 reads that as 'rules out a prebuilt exe'. Both are verified. But the ban is on any artifact carrying translated code, not on an APK as such. A prebuilt runtime/loader APK with no gen code could be distributed, with only the game .so built by the player, which is exactly the claim's own dlopen route. 'Builds on a PC' is a design choice, not a constraint; an on-device build is possible but slow [I]. The Android 10 wording is verified verbatim ('cannot invoke execve() directly on files within the app's home directory'; 'Apps should load only the binary code that's embedded within an app's APK file'). Missing and version-specific: Android 17 (API 37, stable June 2026; behavior-changes-17 page updated 2026-09-16) extends Safer Dynamic Code Loading to native libraries. Files loaded with System.load() must be read-only or it throws UnsatisfiedLinkError, and Google again recommends avoiding dynamic loading. The .so must also sit in app-internal storage, since shared storage is mounted noexec [I].

**Scope and method.** Checked at HEAD `c0d59e2` (2026-09-25). Another session has uncommitted edits in `runtime/gxr.c`, `gxr.h` and `gxr_tev.c`, so line numbers for those three files are **HEAD's**. Line numbers for every other file are the working tree's, which matches HEAD for them. I did not run the game, `scenario.py`, `soak.py` or pytest, and I touched no repository file. What I did run, all read-only:
- a `-fsyntax-only` compile of all 25 `runtime/*.c` with the locally installed **Android NDK r28c (28.2.13676358, clang 19.0.1)**, targeting `aarch64-linux-android29`;
- the same compile against `x86_64-pc-windows-msvc` with the MSVC headers, which is what clang-cl does;
- a syntax check of `gen/chunk_001.c` and `gen/dispatch.c` for ARM64;
- a timed `-O2` compile of a 259 KB slice of `gen/chunk_001.c` for both architectures, at `nice 19`;
- a dump of bionic's `libc.so` symbol table;
- small codegen probes, and `tools/disasm.py` on one function.

Scratch output is in `C:\Users\bmfre\AppData\Local\Temp\claude\...\scratchpad\android\`. **[V]** means verified in code, data or a tool run. **[I]** means inferred.

---

## 0. The short answer, for the owner

1. **The operating-system layer is the small part.** The runtime already has `#ifdef _WIN32` fallbacks nearly everywhere. For Android ARM64 only **4 of 25 runtime files fail to compile**, with **21 errors** between them, and **the generated game code compiles unchanged** [V].
   - Those fallbacks give you a build that is headless, silent and single-threaded.
   - One fallback is fatal: it exits the first time the game resumes its thread (section 4).
2. **Three things make Android expensive:**
   - **Speed.** The renderer is software. Even a 16-thread desktop draws heavy scenes at about 20–27 fps. A phone would need a GPU renderer (Vulkan or GLES) to be playable, and that is months of work [I].
   - **Distribution.** The executable contains the translated game, so nobody can hand out an APK. Each player builds their own on a PC from their own disc and sideloads it (SPEC.md §2) [V].
   - **App plumbing.** App lifecycle, touch controls, storage permissions and audio.
3. **You will always need your own disc once, but not "always the ISO file".**
   - At run time the port reads only four things from `extracted/`: `sys/main.dol`, `sys/boot.bin`, `sys/fst.bin` and `disc.iso`. The 5,552-file extracted tree (1.42 GB) is never read by the game [V].
   - The three `sys/` files are slices of `disc.iso` itself [V].
   - So the port can boot from one imported image. It can also bake the executable parts into the build and keep only an app-owned asset store of about 1.36–1.46 GB.
   - What it can never do is run with *no* user-supplied data: the assets are Sega's.
4. **Cheapest steps first:**
   - Proton on Linux or Steam Deck: hours, no code.
   - clang-cl on Windows: the runtime already passes a clang syntax check with the MSVC headers.
   - A Windows-on-ARM64 or Linux-ARM64 build to flush out the ARM-specific problems (section 3) before any Android work.

---

## 1. Platform dependencies in `runtime/`

### Compile check off Windows [V]

NDK clang 19, `--target=aarch64-linux-android29 -std=c17`. Only these fail:

| File | Errors | What |
|---|---|---|
| `gxr.c` (HEAD) | 17 | `__declspec(thread)` :123, `__declspec(align(64))` :143, `YieldProcessor` :199/:1613/:2014, `LONGLONG` :1546-1547, `LONG` :1571/:2511, `InterlockedIncrement64` :1576/:2370/:2823/:2922, `Sleep` :1613/:2014, `_ReadWriteBarrier` :1618, `InterlockedIncrement` :2594 |
| `dvd.c` | 1 | `_fseeki64` :103 (unguarded) |
| `gx.c` | 1 | `_exit` :188 (no `<unistd.h>`) |
| `selftest.c` | 2 | `_putenv` :122, :344 |

All 25 files compile with clang against the MSVC headers (`-fms-extensions -fms-compatibility`) [V]. clang-cl itself is not installed: VS Build Tools has only clang-format and clang-tidy under `VC\Tools\Llvm`, so the "C++ Clang tools" component would need adding [V].

### What the fallbacks mean at run time [V]

- no window (`window.c:462-467`, `main.c:1224-1226`);
- no sound (`audio_out.c:145-149`);
- no rasterizer workers, so `workers_start` sets n = 0 (`gxr.c:1967-1969`);
- no clocks for the renderer's timers (`gxr.h:217-222`);
- no watchdog or profiler (`main.c:531-538`);
- no memory tripwire, which falls back to `calloc` (`main.c:651-655`);
- no `mod.dll` (`mod.c:753-762`);
- **fatal: `threads.c:308-311` exits(6) on every `OSLoadContext` that is not an interrupt return.**

### Inventory

Sizes: **S** = hours, **M** = a day to several days, **L** = week-plus, **XL** = months.

| Dependency | Where | Portable replacement | Size |
|---|---|---|---|
| Fibers: `ConvertThreadToFiber`, `GetCurrentFiber`, `CreateFiber`, `SwitchToFiber` | `threads.c:109-111, 144-151, 242-312`; `FIBER_STACK` 4 MB :49 | None needed (section 4). Move the same-stack `longjmp` path at :283-287 out of the `#ifdef` | S |
| Worker threads | `gxr.c:1948-1966` (`GetSystemInfo` :1951, `CreateThread` :1962) | pthreads, `sysconf(_SC_NPROCESSORS_ONLN)`; on Android, keep workers on the big cores | S–M |
| Atomics | `InterlockedIncrement64/Exchange64/Increment/Decrement` at `gxr.c:1576, 1684-1686, 1732-1734, 1761, 2370, 2594, 2823, 2922`; `volatile LONGLONG` counters :1546-1547 | C11 `<stdatomic.h>` or `__atomic` builtins with explicit acquire and release; keep `Interlocked*` under MSVC | M, because of the ordering review (section 3) |
| Waiting and spinning | `WaitOnAddress`/`WakeByAddressAll` `gxr.c:1578, 1685, 1733, 1762` (`Synchronization.lib` :20); `Sleep(0)`/`YieldProcessor` :199, 1613, 1689, 1737, 2014; `_ReadWriteBarrier` :1618, 1696, 1745 | Linux and Android `futex` on the counter's low 32 bits (futex words are 32-bit; `WaitOnAddress` takes 8 bytes), or a mutex and condition variable; `sched_yield`; `pause` on x86, `yield`/`isb` on ARM64 | M |
| Thread-local and aligned storage | `gxr.c:123, 143` | `_Thread_local` / `_Alignas(64)` behind a macro | S |
| Clocks | QPC `gxr.c:30-50`, `hle.c:319-345`, `main.c:255, 274`; `__cpuid` `gxr.c:66-84`; `__rdtsc` `gxr.h:218`; `GetTickCount64` `main.c:469-485` | `clock_gettime(CLOCK_MONOTONIC)`; `cntvct_el0` on ARM64 as the TSC | S |
| Guest timebase | `timespec_get(TIME_UTC)` `hle.c:289` | CLOCK_MONOTONIC, plus time spent paused subtracted; `timespec_get` is bionic API 29+ [V] | S, M with pause handling |
| Guarded MEM1 tail | `VirtualAlloc` reserve and commit, `AddVectoredExceptionHandler` `main.c:562-656`; `cpu.h:36-44` | `mmap(PROT_NONE)` + `mprotect`, and a `sigaction(SIGSEGV, SA_SIGINFO)` handler on a `sigaltstack`. On Android it chains through ART's libsigchain, or keep the `calloc` fallback | S–M |
| Profilers and watchdog | sampler (`CreateWaitableTimerExW`, `_beginthreadex`) `main.c:246-319`; watchdog :463-521; `SOA_HOSTPROF` (`SuspendThread`/`GetThreadContext`/dbghelp) `gxr.c:1782-1936` | pthread + `clock_nanosleep`; `perf` or simpleperf in place of HOSTPROF | S (drop HOSTPROF) |
| Window and present | `window.c:21-37` (7 `#pragma comment(lib)`), DXGI :154-215, GDI `StretchDIBits` :254, UI thread :282-363 | SDL3 on Linux, SDL3 or `ANativeWindow_lock` on Android. The seam is narrow: `window_start`/`window_open`/`window_pad` + `gxr_screen`/`gxr_presented` | M (Linux); M–L (Android lifecycle and surface loss) |
| Input | `GetAsyncKeyState` `window.c:405`, `XInputGetState` :433, `window_pad` :398-461 | SDL3 gamepad; on Android, AGDK Game Controller (Paddleboat) plus a touch overlay | S; M on Android |
| Audio | `waveOut` `audio_out.c:14-140` (drops a block when no header is free, :115) | SDL3 audio stream, or AAudio/Oboe (API 26+) with a ring buffer and resampling from 32 kHz to 48 kHz | S–M |
| File I/O | `_fseeki64` `dvd.c:103`; `__argv` `aram.c:160-172` (not MSVC → `"extracted"`, and it ignores soa.ini's `disc` key) | `pread` on an fd (on Android, from a SAF `ParcelFileDescriptor`); pass main's resolved directory in | S |
| Relative paths | `"extracted"` `main.c:1087`; `build/cards/slotA.raw` `exi.c:90`, `si.c:294`; `build/fifo` `gx.c:143`; `build/frames` `gxr.c:2728`; `config/functions.tsv` `main.c:104`; soa.ini beside the exe via `GetModuleFileNameA` `settings.c:73-87` | One app data root. Android's working directory is `/`, so every relative path fails there [I] | S |
| Mods DLL | `LoadLibraryExA`/`GetProcAddress` `mod.c:708-752` (`opendir` fallback exists :911-923) | `dlopen`/`dlsym` of `mod.so`. Android 10+ forbids `execve` from app data but still allows `dlopen` | S |
| Process details | `_exit` `gx.c:188`; `_putenv` `selftest.c:122, 344`; `GetProcessTimes` `hle.c:418-425`; `SRWLOCK` `hle.c:368-375` (a no-op lock off Windows, so a data race once a UI thread exists) | `unistd.h`, `setenv`, `getrusage`, `pthread_mutex` | S |
| Entry, stack and logs | `main()` `main.c:1085`; `/STACK:33554432` `recompile.py:241` ("guest call depth becomes host call depth"); 68 `getenv` calls; all diagnostics on stderr | Run the guest on a pthread with `pthread_attr_setstacksize(32 MB)` [V: in bionic]; soa.ini → `setenv` before main (`settings.c:55-59` already does this); stderr → logcat or a file on Android | S–M |
| Already portable | byte swaps `cpu.h:46-55` (`__builtin_bswap*`, which is `rev` on ARM64); `__forceinline` fallbacks `gxr.c:913-917`, `gxr_tev.c:316-320`; `mkdir` `exi.c:107-111`; no SIMD intrinsics anywhere [V] | — | none |

---

## 2. The build

### What drives MSVC today [V]

- `toolchain.py:47` returns no environment unless `os.name == "nt"`.
- `CFLAGS` at `toolchain.py:100` is `/std:c17 /O2 /fp:strict /W3 /wd…`.
- `recompile.py` hard-codes MSVC syntax throughout:
  - `/D{n}=dc_{n}` for the decompiled-unit renames (:83);
  - `/Od` or `/O2`, `/c` and `/Fo` (:166-178);
  - a `chunk_*.obj` glob (:199);
  - `/Zi /Fe: /link /DEBUG /OPT:REF /OPT:ICF /STACK:33554432` (:226-241).
- `tools/citest/compile_runtime.py` is MSVC-only.

### What must change

- A small `Toolchain` abstraction with four variants: msvc, clang-cl, clang/gcc (Linux) and NDK. It needs object suffixes, `-D`, `-o`, and link flags (`-Wl,--gc-sections`, lld `--icf=all`).
- On Android: `-shared -fPIC` to produce a `libsoa.so`, plus a Gradle/CMake app shell and APK signing.
- Linux flags: `-std=c17 -O2 -ffp-contract=off`, and **never `-ffast-math` or `-Ofast`**: `cr_fcmp` detects NaN with `a != a` (`cpu.h:298`).
- No strict-aliasing flag is needed: every pun goes through `memcpy`, and the only pointer cast is a qsort comparator (`hle.c:412`) [V].
- For clang-cl, prefer `/fp:precise /clang:-ffp-contract=off` over `/fp:strict`. My understanding is that clang maps strict to a strict floating-point-exception model, which costs optimisation [I].
- The HLE swap is portable. The emitter names the translated body `recomp_fn_X` (`emit.py:244-248`), so there are never duplicate symbols and no linker-precedence trick is involved [V].
- SDL3 cannot live in `vendor/`: `.gitignore:19` ignores it and `guard.py:66` refuses it. Fetch it the way `fetch_toolchain.py` fetches its tools, or use the system package or the SDL3 Android AAR.

### How big `gen/` is [V]

- 18 chunks plus `dispatch.c`: **58,911,696 bytes** of C in 1,690,463 lines. `functions.h` adds 229,914 B.
- **7,144 functions**. The largest is `fn_801A6BDC` at 9,233 lines.
- Chunks range from 1.6 MB to 5.45 MB (`chunk_005`).
- For comparison: MSVC objects total 30.9 MB, `soa.exe` is 21.6 MB, and the MSVC `/O2` compile takes 103 s on 16 cores (`ROADMAP.md:126`).

### How long an `-O2` ARM64 compile would take

- **Measured:** a 259,136-byte slice (the first 60 functions of `chunk_001`) took 3.7 s for aarch64 and 3.9 s for x86-64 on one core at `nice 19` [V].
- **Extrapolated:** about 840 core-seconds, roughly **14 core-minutes**, for all of `gen/` [I].
  - Double that for safety: the slice averages 4.3 KB per function against 8.2 KB overall.
  - On the owner's 16-thread PC that is about 1.5–3 min of wall time, bounded by `chunk_005` alone (about 80 s). `--chunk 100` would parallelise better.
- The build happens on the PC; compiling on the phone is not realistic for players.

---

## 3. Generated-code semantics: ARM64 against x86-64

| Item | What the code does | x86-64 | ARM64 | Verdict |
|---|---|---|---|---|
| `fctiw`/`fctiwz` | `ppc_fctiw` handles NaN and the range explicitly before `(int32_t)` (`cpu.h:508-516`; emitted at `emit.py:631-634`, 2,386 sites) | same | same | **Portable** [V] |
| `psq_st` quantise | `psq_clamp` handles NaN and clamps before converting (`cpu.h:476-482`) | same | same | **Portable** [V] |
| FPSCR rounding mode | `mtfsf`/`mtfsb` only store bits into `s->fpscr` (`emit.py:639-647`); `nearbyint` uses the host's round-to-nearest-even | RNE | RNE | Same on both. Only 2 `mtfsf` sites exist: `PPCMtfpscr` 0x80231A54 and `__OSLoadFPUContext` 0x80233288 [V] |
| Non-IEEE mode | The game calls `PPCSetFpNonIEEEMode` (0x80231AC8, word `0xFFA0004C` = `mtfsb1 29`) from 0x80231CAC. The port never emulates flush-to-zero | IEEE | IEEE | Same on both; a fidelity gap against hardware [V]. **Side bug:** `emit.py:645-647` uses `i.bo`, which the decoder leaves 0 for this form (rd = 29), so the translation sets FPSCR[FX] (`1u<<31`) instead of NI (`1u<<2`). Harmless today, but FX leaks into CR1 on record-form FP ops and into `mffs` [V] |
| Fused multiply-add | `fma()` for every fused op (`emit.py:147-159, 173-180`; 2,457 calls in `gen/`) | correctly rounded (UCRT) | one `fmadd` | Same result [V: both IEEE-exact]; faster on ARM [I] |
| **Implicit contraction** | clang's default for C is `-ffp-contract=on`. `a*x + b*y + c` compiles to `fmadd` on aarch64 at `-O2` and not on the x86-64 baseline [V: NDK clang 19 probe]; GCC defaults to `fast` | no FMA | **fuses** | Pass **`-ffp-contract=off`** to gen *and* runtime. The rasterizer's plane equations (`gxr.c:1200`) would otherwise move pixels |
| **Float to int in the renderer** | Unclamped `(int)f` in `fast_floor` (`gxr_tev.c:985-989`, which feeds `wrap` at :1016/:1020), in colour (`gxr.c:1221`, clamped *after* the cast), and in lines and points (`gxr.c:1242-1278`) | `cvttss2si`: INT_MIN for out-of-range | `fcvtzs`: saturates; NaN → 0 | **Diverges** for values of 2^31 and up: x86 gives texel 0 or colour 0, ARM gives the last texel or 255. NaN mostly converges. Clamp before converting, which also removes C undefined behaviour. Depth (`gxr.c:922, 1007`) and the bounding box (`:1122-1125`) are already clamped |
| libm | Only `exp2f` (fog, `gxr.c:936-939`) and `log2f` (level of detail, `gxr.c:1084`) are not exactly rounded; sqrt/floor/ceil/ldexp/nearbyint are exact [V] | UCRT | bionic/glibc | Can move one ulp, then quantise, so a frame hash may move [I]. Re-baseline by looking at the frames (CLAUDE.md's first-bless rule) or ship own implementations |
| NaN payload | x86 generates `0xFFF8…` (negative); ARM and PowerPC generate `0x7FF8…` | differs | matches PPC | Matters only where the game inspects NaN bits [I] |
| Denormals | Default MXCSR and FPCR.FZ = 0 | IEEE | IEEE | Same |
| Paired singles | Double arithmetic then a `(float)` round (`emit.py:662-666`); `fres`/`frsqrte` computed exactly, not estimated | same | same | Portable; exact rather than hardware estimates on both |
| Unaligned and endian | `memcpy` + bswap (`cpu.h:129-203`) | `mov`+`bswap` | `ldr`+`rev` | Portable |
| **Memory ordering** | Section below | TSO | weak | **Breaks on ARM** |

### Memory ordering in the render queue

- The worker's spin (`gxr.c:1716`) is a plain `volatile` load of `g_published`. The comment at **`gxr.c:1741-1745`** says outright: *"this machine does not reorder two loads, so the command is there. The barrier is against the compiler alone… it emits nothing."*
- ARM64 does reorder loads. A worker could read a stale `DrawCmd` from the slot at `g_queue[mine & QMASK]`.
- The same pattern recurs:
  - `wait_ran` and `drain` read `g_ran` plainly (:1613, :2014) and then read what workers wrote, for example `copy_to_texture` output in guest memory;
  - `fence_wait` reads other workers' rows (:1681-1696);
  - the UI thread reads `g_frames_presented` and the single `g_screen` buffer (`gxr.c:2509-2511, 2686-2689`).
- The writers (`InterlockedIncrement64`, `InterlockedExchange64`) are full barriers on MSVC for both x64 and ARM64, so the gap is the **loads**. They need `memory_order_acquire`, which is `ldar` on ARM64 and a plain `mov` on x86.
- MSVC defaults to `/volatile:iso` on ARM64, so a Windows-on-ARM build breaks the same way [V: Microsoft Learn].
- The sleeper handshake is Dekker-style: a store, then a load of the other side's variable, on both sides (:1576-1578 against :1732-1734). Both sides need sequentially consistent operations. A relaxed port would lose wakeups silently, and the 50 ms `WaitOnAddress` backstop would turn the bug into a stutter rather than a hang [I].
- Validate with the existing `SOA_GXR_STALL` mutations and `replay` at 1, 2, 3 and 8 threads.

---

## 4. Threads and interrupts

**Finding: the game has exactly one guest thread, so host fibers never switch.**

- Every one of **326 logs in `build/`** (2026-09-16 to 09-25, up to 126,000 frames) reports `1 guest threads seen … 0 fiber switches`, and none contains "new guest thread" [V].
- The binary appears to lack the code that makes a second thread:
  - `OSClearContext` (0x802336D4, 36 B) ends exactly where `OSDumpContext` (0x802336F8) starts, leaving no room for `OSInitContext`;
  - `__OSReschedule` ends exactly where `OSCancelThread` starts (0x80237CB4), where `OSYieldThread`, `OSCreateThread` and `OSExitThread` would sit;
  - no translated function materialises `0x9032`, the MSR value `OSInitContext` gives a new thread [V: config/functions.tsv, grep of gen/].
- So the conclusion that `OSCreateThread` was dead-stripped is strong, but still an inference from the layout [I].

What survives is **same-stack `setjmp`/`longjmp`**:
- a thread parks at `setjmp` (`emit.py:564-570`) and is resumed by `longjmp` on its own stack (`threads.c:283-287, 261-270`);
- interrupt returns `longjmp` back to `call_guest_handler` (`irq.c:196, 221-224, 287`), also on the same stack.
- bionic exports `setjmp`, `longjmp`, `_setjmp` and `sigsetjmp` [V]. glibc's fortified `longjmp` check only objects to jumps across stacks, which never happen here [I].

**Required fix (S):** `threads.c:282-312` puts the same-fiber resume inside `#ifdef _WIN32`, so every non-Windows build exits at the first thread resume. There are hundreds to tens of thousands of these per run (for example 55,406 in `boot_field.log`). Move lines 283-287 out of the `#ifdef`.

| Option if a second thread ever appears | Cost | What breaks |
|---|---|---|
| (a) Nothing: keep the `exit(6)` with its message | S | Nothing, today |
| (b) Hand-written switch (about 20 instructions per ABI, saving callee-saved registers d8–d15 and x19–x30 on AArch64), minicoro, or Boost.Context `fcontext` (which has `jump_arm64_aapcs_elf_gas.S`) | M | Nothing semantic; keep the 4 MB stacks |
| (c) One host thread per guest thread, passing a baton through a semaphore | M | Identity checks (`g_mem_tid` in `main.c:589`, `SOA_HOSTPROF`'s guest handle); costs 5–20 µs per switch [I] instead of about 50 ns; still deterministic if exactly one runs at a time |
| (d) `ucontext` | — | **Not in bionic:** NDK r28c API-35 `libc.so` exports no `getcontext`/`makecontext`/`swapcontext`/`setcontext` [V]; the interface is also obsolete in POSIX |

---

## 5. What the running port reads from the disc [V]

| Read | Where | Why |
|---|---|---|
| Directory `extracted` (or argv[1], or soa.ini's `disc`) | `main.c:1087, 1123-1124` | Root |
| `sys/main.dol` | `main.c:1139`; `load_dol` :962-987 copies all 18 sections | Data, rodata and jump tables live in guest RAM; SHA-1 for patch mods (`mod.c:925`) |
| `sys/boot.bin` (0x440 B) | `main.c:1141, 1159-1168` | Game ID into low memory (`setup_low_memory` :993), FST max at 0x42C |
| `sys/fst.bin` (134,426 B) | `main.c:1143-1171` | Parked below `ARENA_HI` 0x81700000 |
| `disc.iso` (1,459,978,240 B) | `main.c:1192-1193` → `dvd.c:79-115`; offset `cmd[1]<<2` :129 | **Every asset read** |
| `sys/fst.bin` + `disc.iso` again | `aram.c:196-217` | Diagnostic census naming ARAM uploads |
| Not read | the 5,552-file tree (1,421,347,731 B); `bi2.bin`; the apploader; any IPL ROM or font (`exi.c:469` "not provided") | — |

The `sys/` files are slices of the image: the header at 0x420 gives the DOL at 0x1EC00 and the FST at 0x323E00 (size 0x20D1A), the same parse as `tools/soa/disc.py:69` [V].

The file data ends at **1,429,436,950 B (1,363.2 MiB)** of 1,459,978,240 B, so the tail is only about **30.5 MB**. `beyond-gamecube.md` §4's "1,363 MB of the 1,460 MB image" mixes MiB with decimal MB [V].

### An "import once into an app-owned store", step by step

1. **Boot from `disc.iso` alone** — S. Read the DOL, the FST and the header through the 0x420 offsets; hand `aram.c` main's handle. `extracted/` shrinks from 2.88 GB to 1.46 GB.
2. **Bake the executable data into the build** — S–M. `recompile.py` already reads `main.dol`. Also emit its 3.1 MB of sections, the boot header fields and the DOL SHA-1 into `gen/`. That is legally the same class as `gen/`, never committed. The run then needs only the asset image.
3. **An importer** — M on PC, M–L on Android.
   - Accept ISO or GCM, and RVZ (`tools/soa/rvz.py` exists).
   - Verify `GEAE8P` and the DOL hash (`tools/soa/dump.py`).
   - Write the store and record its path in soa.ini.
   - On Android: pick the file through the Storage Access Framework, then either copy it into app-specific storage or keep a persisted URI and `pread` through the detached fd with no copy.
4. **Optional virtual disc (E2)** — M–L. A per-file store with an FST overlay (`beyond-gamecube.md:519-540`) makes the store moddable.
   - Trimming the 30.5 MB tail must preserve the "junk past a file's end" behaviour that SPEC R9 closed.
   - A compressed store (zstd, like RVZ) would need a C decoder fetched at build time [I].
5. **Not possible:** a build that needs no user data. SPEC §2.1-2.2 forbid shipping assets or anything translated from the DOL, and the executable *is* the translated DOL.
   - Full decompilation (83 of 7,144 functions today) would change neither the asset dependence nor, per plan-gaps, the copyright exposure.

### Distribution to Android players

- **A personal APK**, built on the player's PC from their own DOL with the NDK and sideloaded with `adb install`.
- Or **a runtime-only APK plus a user-built `libgame.so`** loaded with `dlopen` from app storage. Android 10 banned `execve` from app data, not `dlopen`, though Google says to load only code in the APK. Sideload only, never Play. It also means the gen/runtime boundary becomes a dynamic ABI, with `cpu.h`'s layout versioned — L.
- **Precedent:** Ship of Harkinian's Android forks extract assets from the user's ROM on first launch. Their binary carries no game code; this port's does.
- **Dolphin on Android already runs this game today.**
- **Performance:**
  - A heavy field scene draws at about 20 fps when every frame is rendered (`docs/research/performance.md:6, 124`), and the Dangral base at 27 fps with 12 workers (`gxr.c:1953-1957`).
  - A phone has 2–4 big cores and throttles, so software rendering there would likely run at single digits to mid-teens in heavy scenes [I]. The GPU backend parked in PLAN-60FPS-MODS:13, 64 becomes a prerequisite for Android.
  - Row interleaving (`y % n`) makes a little core gate every draw, so pin workers to big cores [I].
  - Google Play has required 16 KB-page-compatible native code since 2025-11-01 for apps targeting Android 15+; NDK r28 and later align by default. Not relevant to sideloading, but free.

---

## Final table

Sizes: **S** = hours, **M** = a day to several days, **L** = week-plus, **XL** = months.

| Item | Where | Linux x86-64 | Linux ARM64 | Android (ARM64) | Size |
|---|---|---|---|---|---|
| Run `soa.exe` under Proton | — | Works as is [I]; smoke-test the self test | n/a (FEX + Wine only) | n/a (Winlator/Box64 likely too slow [I]) | S |
| Four compile errors, fatal thread stub | `gxr.c` (17), `dvd.c:103`, `gx.c:188`, `selftest.c:122, 344`; `threads.c:282-312` | Fix | Fix | Fix | S |
| Portability header (atomics, futex, yield, TLS, align, clocks) | `gxr.c` HEAD :17-84, 123, 143, 1546-1770, 1948-1969, 1990-2014; `gxr.h:202-222`; `hle.c:188-197, 319-375` | Straight port | + acquire/release review | + big-core affinity | M |
| Contraction off | `toolchain.py:100` | Needed with GCC | **Critical** | **Critical** | S |
| Clamp float-to-int | `gxr_tev.c:985-989`; `gxr.c:1221, 1242-1278` | Not needed | Needed | Needed | S |
| libm ulps / re-baseline hashes | `gxr.c:936-939, 1084`; `config/fifo_manifest.tsv` | Check replay 23/23 | Check | Check | S–M |
| Guarded memory tail | `main.c:562-656` | mmap + SIGSEGV | same | ART sigchain, or drop | S–M |
| Window and present | `window.c:1-461` | SDL3 | SDL3 | GameActivity + `ANativeWindow` or SDL3, lifecycle | M / M / L |
| Input | `window.c:398-461` | SDL3 | SDL3 | Paddleboat or SDL3, touch overlay | S / S / M |
| Audio | `audio_out.c` | SDL3 | SDL3 | AAudio/Oboe, 32→48 kHz | S–M |
| Paths, config, logs, entry, 32 MB stack | `main.c:104, 1085-1087`; `exi.c:90`; `si.c:294`; `settings.c:73-87`; `recompile.py:241` | Small | Small | App dirs, soa.ini, logcat, big-stack thread | S / S / M |
| Mods DLL | `mod.c:708-762` | `dlopen` | `dlopen` | `dlopen` (W^X caveat) | S |
| Build driver | `toolchain.py`, `recompile.py:83, 159-241`, citest | clang/gcc profile | + cross-compile | + `.so`, Gradle, signing | M / M / L |
| Pause-aware timebase | `hle.c:284-297` | Optional | Optional | Required (app suspend) | M |
| Boot from `disc.iso`; bake the DOL | `main.c:1139-1193`; `aram.c:196-217` | Yes | Yes | Yes, + SAF importer | S–M / M–L |
| Renderer speed | `gxr.c`, `gxr_tev.c` | OK on a desktop | OK on laptop class | **GPU backend** | XL |
| Distribution | SPEC §2 | Per-user build | Per-user build | Per-user APK, sideload | L |

**Suggested order:**
1. Proton smoke test.
2. The portability header, the four compile fixes and the `threads.c` fix, plus a clang compile-only CI job.
3. clang-cl on Windows, then replay 23/23. Hashes should match unless contraction or libm differs.
4. Boot from `disc.iso` and bake the DOL.
5. An ARM64 build on Windows-on-ARM or Linux: atomics, clamps, replay at 1/2/3/8 threads.
6. Native Linux with SDL3.
7. Only then the Android shell, and the GPU-backend decision.

Estimates [I]: roughly 2–3 weeks of evenings to a native Linux x86-64 build, a further week for ARM64, then several weeks more for "Android boots and plays slowly". "Plays well on Android" is months, because of the GPU renderer.

### Sources (fetched 2026-09-25)

- Android 10 behavior changes (execve banned, `dlopen` still allowed): https://developer.android.com/about/versions/10/behavior-changes-10
- 16 KB page sizes: https://developer.android.com/guide/practices/page-sizes and https://android-developers.googleblog.com/2025/05/prepare-play-apps-for-devices-with-16kb-page-size.html
- NDK r29, Oct 2025: https://developer.android.com/ndk/downloads/revision_history
- SDL 3.2.0, Jan 2025: https://github.com/libsdl-org/SDL/releases/tag/release-3.2.0
- MSVC `/volatile`: https://learn.microsoft.com/en-us/cpp/build/reference/volatile-volatile-keyword-interpretation?view=msvc-170
- Game Controller library: https://developer.android.com/games/sdk/game-controller
- Storage Access Framework: https://developer.android.com/training/data-storage/shared/documents-files
- cvttss2si: https://www.felixcloutier.com/x86/cvttss2si
- FCVTZS: https://developer.arm.com/documentation/100069/0607/A64-Floating-point-Instructions/FCVTZS--scalar--integer-
- A real x86/ARM conversion divergence: https://github.com/pytorch/pytorch/pull/196646
- Boost.Context: https://www.boost.org/doc/libs/1_61_0/libs/context/doc/html/context/context.html
- Ship of Harkinian Android: https://github.com/Waterdish/Shipwright-Android
- Dolphin compatibility list: https://m.dolphin-emu.org/compat/S/
