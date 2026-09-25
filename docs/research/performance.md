<!-- Written 2026-09-24 by a read-only research agent for docs/PLAN-60FPS-MODS.md; nothing was
run. [V]/V marks what was read from quoted instructions, file:line or logs; [I]/I is inference. -->

# How fast the port runs, where host time goes, and the budget for 60 fps and higher resolution

**Short answer:** the claim that the port is not limited by the software rasterizer is only true when the renderer skips most frames. When every frame is drawn, as in a window, a typical field scene most likely runs at about 20–25 fps. That figure is inferred, because no current log draws every frame. For native-resolution 60 fps, two things are needed:
- stop the full drain around every screen-to-texture copy, so the game thread and the rasterizer run in parallel;
- make the pixel path 1.4–2.5× faster.

2× or 3× internal resolution at 60 fps needs 6–22× more pixel throughput. That points to a GPU backend, not a faster software rasterizer.

## Setup and conventions

**Machine (checked):** AMD Ryzen Z1 Extreme, 8 cores and 16 threads, a handheld chip with a limited power budget. No log records which power mode or whether it was plugged in, and both change every number below.

**Binary (checked):**
- `gen/soa.exe` was linked 2026-09-22 21:30.
- The translated `gen/chunk_*.obj` files date from 2026-09-18 05:37–05:39. They are older than their `.c` files (09-22 21:30).
- They were built at /O2. `dumpbin /disasm gen/chunk_013.obj`, function `fn_80232E38`, shows `cmovne` and values kept in registers, which /Od does not produce.
- The renderer starts 8 worker threads by default, half the logical CPUs (`gxr.c:1454`).

**Terms used below:**
- A **fragment** is a candidate pixel the rasterizer processes. Fragments = pixels shaded + failed alpha test + failed depth test, from the `[gxr]` counter line.
- **Thread-time** is CPU time summed across all worker threads. **Wall** time is elapsed clock time.
- **Snapshot runs** set `SOA_SNAP=n`, which rasterizes only every nth frame.
- **Guest** means the recompiled game code; the **guest thread** is the host thread that runs it.
- A **drain** makes the guest thread wait until the workers have finished every queued draw.
- The **FIFO parse** decodes the graphics command stream the game writes.
- **VI retraces** are the console's 60 Hz display ticks.
- A **texture copy** copies part of the rendered image into a texture in game memory.

Log statistics were computed by two scratch scripts, `fit.py` and `pf.py`, in a session scratchpad, not kept.

## 1. Frame rates today, and what limits each

| Mode | Evidence | Game frames per wall second | What limits it |
|---|---|---|---|
| Headless, snapshot run, `SOA_SPEED=1` | 57 `build/run_*.log` files since 09-21, from their `[run]` lines | 27.4–29.9, median 29.4 (33.5–36.5 ms a frame) | The game's own 30 fps cap. The guest thread sits in `SelectThread` (the guest OS idle loop) 37–49% of the time, plus 0–22% in the main-loop spin |
| Headless, snapshot run, `SOA_SPEED=3` | scenario-monkey, encounter, hold (09-18); run_wheel (09-21) | 79.9 / 70.6 / 63.0 / 41.2, against a 90 cap | Guest-thread CPU. `SelectThread` falls to 31 / 24 / 20 / 11%; the FIFO parse is 11–14% |
| Headless, nothing drawn, `SOA_SPEED=10` | `scenario-speed.log:150` | 77.2 (10,000 frames in 129.5 s, 7.65 retraces a frame) | Guest-thread CPU (`SelectThread` 6.2%) |
| Headless, every frame drawn | No current log. `boot_perf.log` (09-16, before the 09-21 copy filter) has 4,210 frames over 8,848 retraces and no wall clock | Unknown today | Unknown |
| Window | `boot_window.log` only (09-16 07:28) | 26.7 (667 screen copies over 1,495 retraces) | Per PLAN C4, the pixel path |

**The window figure is weak evidence.**
- It is the first 667 frames of a session driven by hand. Every script's first START is at frame 1600, so this is probably just the logos and title flyover (inferred).
- Those frames average 153 triangles but 1.29M fragments each.
- The build predates the A4 profiler rebuild (09-18) and the copy filter (C3, 09-21).
- `HANDOFF.md` says the port "renders in a window at the game's 30 fps cap". No current measurement supports that.

**The 30 fps cap is the game's own frame loop (checked in the disassembly):**
- At the start of each frame, `0x801DCB84` stores the retrace count (read by `fn_8023F704`, which is `lwz r3,-27836(r13)`, the word at `0x80347A64`) into `0x8034768C`.
- `0x801DC490`–`0x801DC4A8` then loops: it calls `fn_801C6248(0)` (the async disc-read poll), and repeats while (current retrace − start) < 1 (`cmpli r0,1` / `blt`).
- It then calls `fn_8023E460` at `0x801DC4D8`. That is VIWaitForRetrace: it sleeps until `0x80347A64` changes.
- So every frame takes at least 2 retraces.
- `-29024(r13)` (`0x803475C0`) is a counter that goes up by one per loop pass, at `0x801DC390`–`0x801DC398`.

**Guest-thread work per frame** (wall × (1 − `SelectThread` − the two spin functions), at speed 1):
- Median 11.9 ms; range 3.4 ms (the ending) to 18.2 ms (the warp and spoof runs: about 2,900 draws and 730 KB of commands per frame).
- That includes the FIFO parse at 0.3–3.2 ms (median 1.8) and 1–7% waiting on the workers.
- The named hot guest functions:
  - the middleware's paired-single vertex loops `fn_802A21C4` and `fn_802A49F4`; the latter stores to the graphics FIFO at `0x802A4BCC`;
  - `PSMTXConcat` (`fn_80238B60`), 2–4.7%;
  - `DCInvalidateRange`, 1.6–3.9%;
  - audio interrupt handlers such as `fn_80285FD8`.

**The "idle" time is still CPU time.**
- The guest idle hook polls continuously (`irq.c:437`).
- Idle workers spin with `YieldProcessor` and `Sleep(0)` (`gxr.c:1414`).
- So about 10 host threads stay busy even when the game is waiting.

**"Ten times real time" counts retraces, not frames.** The speed-10 run managed 590 retraces a second but only 77 frames a second, which is 2.6× real time in frames. Which clock the game's logic follows is still PLAN's open question.

**HANDOFF's "wrong statement 3" rests on a snapshot run (inferred, but the numbers leave little room).**
- A4's run reported 8.8 s of worker busy time over 3,000 frames: 2.9 ms of thread-time a frame.
- At the per-fragment cost measured below, that is 20–34k fragments a frame.
- The first 2,000 frames average 1.60M fragments per drawn frame: `scenario-title.log` has 65.7M fragments over its 41 drawn frames.
- So A4 drew roughly 1 frame in 50.
- Its conclusion ("not rasterizer-bound") holds for snapshot runs and says nothing about windowed play.

## 2. Renderer cost per frame at 640×480

**Counters per drawn frame** (33 runs with `SOA_SNAP` ≤ 100):

| Measure | Median | Range |
|---|---|---|
| Fragments | 2.21M | 1.19–2.98M (max 3.44M across all 57 runs) |
| Depth complexity | about 7× | 3.9–11× the 307,200 visible pixels |
| Pixels actually written | 1.71M | — |
| Triangles | 7.7k | 0.8–12.2k |

**Every frame, drawn or not:**

| Measure | Median | Range |
|---|---|---|
| Draws | 1,900 | 230–3,090 |
| Vertices | 11.9k | — |
| Texture copies | 7.7 | 0.5–13 (up to 16.4 in the soak runs) |

**Worker cost** is roughly linear in these counts. A least-squares fit over 59 runs gives:

| Fit | Per fragment (thread-time) | Per texture copy | Per screen copy | Median error |
|---|---|---|---|---|
| All 59 runs | 111 ns | 0.42 ms | 3.6 ms | 10% |
| 35 runs with `SOA_SNAP` ≤ 100 | 86 ns | 0.43 ms | 4.6 ms | 2.5% |

Runs dominated by fragment work imply 92–100 ns (the Part L runs) up to about 175 ns (sky and ships). **A full frame is therefore about 190–330 ms of thread-time, or 24–41 ms of wall time on 8 workers even if they scale perfectly.**

**Costs on the guest thread per drawn frame:**

| Phase | Cost | Note |
|---|---|---|
| Vertex setup | about 2–4 ms | runs with `SOA_SNAP=20` |
| TEV prepare | median 2.2 ms, up to 12 | hashes the whole texture on every lookup, `gxr_tev.c:190-210` |
| Texture decode | median 5.7 ms | inflated by the cold cache in snapshot runs; the 256-slot cache (`gxr_tev.c:44`) reports thrashing in 54 runs |
| PNG write | 7–10 ms | snapshot runs only |

**The guest thread waits for every frame's rasterization (checked in code):**
- Every copy this game makes is filtered (C3: BP 53/54 = 30A208 / 00820A).
- A filtered copy drains the queue both before and after (`gxr.c:1987` and `gxr.c:2038`).
- In captures 6000 and 15800 the texture copies sit at the end of the command stream (fifo.py output lines 36764 of 37829, and 21323 of 21670). So the guest thread waits for the whole scene before it can start the next frame.
- Measured wait per drawn frame, Part L runs: 17–26 ms. That is the producer `wait` total minus copy-only waits (about 1.15 ms on undrawn frames, derived from the snap-1000 soaks).

**Every-frame rendering in heavy field scenes is inferred to be about 12–17 ms guest + 18–26 ms waiting + 5–12 ms setup, prepare and decode, which is 40–50 ms a frame, or 3 retraces: about 20 fps.** The copy drains were added on 09-21. Before then, the guest and the rasterizer could overlap, which fits `boot_perf.log` holding 2.10 retraces a frame (inferred).

## 3. Can it run faster than real time with every frame drawn?

**What `SOA_SNAP` skips (checked):**
- It skips draws only (`gxr.c:1534`).
- Copies (with their drains), clears, texture copies into game memory and the FIFO parse all still run every frame.
- Opening a window forces every frame to be drawn (`main.c:1057`).
- `SOA_RENDER=1` with no `SOA_SNAP` and `SOA_WINDOW=0` draws every frame headless (`main.c:911`).

**Clocks (checked):**
- Guest time is wall time × speed by construction (`hle.c:288`).
- A late retrace is not caught up (`irq.c:384`, `g_vi_last = now`), so rates derived from retrace counts overstate fps whenever the host stalls. Wall seconds are the reliable clock.

**Answer:**
- Even with almost nothing drawn, the guest thread saturates at 41–80 frames a second: 1.4–2.7× real time.
- No saved run draws every frame at `SOA_SPEED` above 1.
- Projection (inferred): 25–60 ms a frame, so no faster than real time in field scenes. Only light scenes such as the title and menus would exceed it.

## 4. Budget table

Fragments scale with the square of the resolution factor. The workload is 2.2M fragments at 1×, on 8 workers.

- **Overlapped** means the drains are gone and all of the frame time is available for rasterization.
- **Serial** is today's structure: about 12 ms of guest work comes first.
- **Today** the pixel path costs 86–150 ns of thread-time per fragment.

| Target | Frame time | Fragments per frame | Allowed ns per fragment, overlapped | Allowed, serial | Speedup needed, overlapped | Speedup needed, serial |
|---|---|---|---|---|---|---|
| 1× at 30 fps | 33.3 ms | 2.2M | 121 | 77 | 0.7–1.2× | 1.1–1.9× |
| 1× at 60 fps | 16.7 ms | 2.2M | 61 | 17 | 1.4–2.5× | 5–9× |
| 2× at 30 fps | 33.3 ms | 8.8M | 30 | 19 | 2.8–5× | 4.4–7.7× |
| 2× at 60 fps | 16.7 ms | 8.8M | 15 | 4.3 | 5.7–10× | 20–35× |
| 3× at 30 fps | 33.3 ms | 19.8M | 13.5 | 8.6 | 6.4–11× | 10–17× |
| 3× at 60 fps | 16.7 ms | 19.8M | 6.7 | 1.9 | 13–22× | 45–79× |

**Other constraints:**
- **Guest thread at 60 logic updates a second:** the heaviest scenes already take 18.2 ms of guest work a frame against a 16.7 ms budget. Vertex setup and TEV prepare also run on that thread today.
- **Copies scale with resolution too:** the screen copy is 3.6 ms of thread-time at 1×, about 14 ms at 2× and about 32 ms at 3×.
- **Texture copies at higher resolution** must be scaled back down to native size before they are written into game memory.
- **Present path (checked in `window.c`):** the UI thread polls every 8 ms (`window.c:147`). With Windows' default timer resolution that is really about 15.6 ms. The screen buffer is single (`gxr.c:1740`) and read without a lock. At 60 fps this would drop or tear frames (inferred).

## 5. Measurements still missing

Run one `soa.exe` at a time. Always use a card copy, never `build/cards/slotA.raw`.

1. **Every frame drawn, headless, opening (no window needed).**
   - `Copy-Item build\cards\slotA.raw build\savetest\perf.raw`
   - `python tools/scenario.py run window --env SOA_WINDOW=0 --env SOA_CARD=build/savetest/perf.raw --log build/perf-full-opening.log`
   - Run it again with `--env SOA_RENDER=0` as the guest-only baseline.
   - What to read:
     - fps = frames ÷ wall seconds, from `[run] N game frames … W wall seconds`;
     - worker busy ÷ N, from `[gxr] workers: … busy`;
     - producer wait ÷ N, from `[gxr] producer … wait`;
     - fragments ÷ N, from the `[gxr] … pixels shaded (… failed alpha, … failed depth)` line;
     - the `SelectThread` share in the `[profile]` table (headroom).
2. **The same in a heavy field scene.**
   - `Copy-Item build\savetest\card-partL.raw build\savetest\perf-L.raw`
   - Run `window --frames 3000` and then `--frames 9000`, both with `--env SOA_WINDOW=0 --env SOA_CARD=build/savetest/perf-L.raw --env "SOA_PAD=1600:start,1640:a,1800:start,1840:a,2000:start,2040:a,2240:a,2440:a,2640:a"`.
   - Subtract the two runs' counters to isolate frames 3000–9000, which are standing still in the field.
3. **Saturation** (can it beat real time while drawing every frame): repeat item 2 with `--env SOA_SPEED=4`. Check that `SelectThread` is near 0% and that the run actually reached the map. HANDOFF warns that changing the speed can shift what frame-keyed scripts do.
4. **Thread scaling:** item 2 at `SOA_THREADS=1, 4, 8, 15`. If fps rises with threads, the rasterizer is on the critical path.
5. **Rasterizer alone, one frame at a time.**
   - Copy captures into a scratch directory, because `--replay` writes `<base>.png` next to the capture: `New-Item -ItemType Directory -Force build\perfcap; Copy-Item build\fifo\6000.* build\perfcap\`
   - Then `$env:SOA_THREADS='8'; gen\soa.exe --replay build\perfcap\6000`, and read `[gxr] workers … busy` and the fragment count.
   - The corpus is early-game only. New field captures need `SOA_FIFO_DUMP` with `SOA_FIFO_DIR` pointed somewhere other than `build/fifo`.
6. **Windowed rate now:** `python tools/scenario.py run window --env SOA_CARD=build/savetest/perf.raw --log build/perf-window.log` (about 4 minutes, opens a window). Also run item 2 with `--env SOA_WINDOW=1`.
7. **Record the power mode and whether it was plugged in on every run.** Add a per-frame wall-time p50/p95/p99 line to the report; it only prints totals today, so hitches are invisible (a few hours of work).

## 6. Optimisations, in order, with expected payoff

1. **Do the measurements in section 5 first** (hours). They decide whether the rasterizer or the guest thread limits every-frame rendering.
2. **Remove the two full drains around each filtered copy.** Order workers against their neighbours instead, or snapshot the three source rows the filter reads. Frame time would drop from guest + raster to the larger of the two: field scenes from about 45 ms to about 30 ms (inferred). It must hold the replay at 1, 2, 3 and 8 threads over several sweeps, since the C3 defects appeared only on the fourth sweep. Several days.
3. **Pixel path 2–4×.**
   - Test depth before the TEV where the alpha test cannot reject (the C4 cheap pair).
   - One perspective divide per texture coordinate, not two per stage (`gxr_tev.c:787`).
   - Hoist the per-sample float division (`gxr_tev.c:741`).
   - Specialise the fragment function per draw (C4's measured 1.5×), then SIMD spans.
   - Needed for 1× at 60 fps (1.4–2.5× even with the overlap from item 2). Days to weeks.
4. **Move renderer work off the guest thread.**
   - Vertex setup (2–4 ms): do it on the workers.
   - Hash each texture once per frame instead of once per lookup (about 2 ms median, up to 12).
   - Grow the texture cache past 256 slots.
   - (Both done in H12, 2026-09-25: FINDINGS "H12".)
   - Hours to days.
5. **Make the guest thread faster** (needed for 60 logic updates a second).
   - Specialise the paired-single load and store for this binary's six constant GQRs. `cpu.h:441` already notes this; every `psq_l`/`psq_st` currently calls `ldexp` (`cpu.h:467`, `cpu.h:500`). The object code for `fn_802A21C4` makes 24 `ldexp`, 24 `psq_load`, 34 `psq_store1` and 12 `fma` calls.
   - Inline `fma` with `/arch:AVX2` or intrinsics.
   - Run PSMTXConcat natively.
   - Bind `DCInvalidateRange`/`DCFlushRange` as no-ops; `dcbi` already emits nothing (`gen/chunk_013.c:31609`).
   - Move the FIFO parse (0.3–3.2 ms a frame) to its own thread.
   - Estimated 10–30% of guest time (inferred). The `cpu.h` change needs a full retranslation.
6. **Stop spinning when idle:** the guest idle hook and the 8 workers. On a power-limited handheld this frees budget for the guest thread; the payoff is unmeasured.
7. **Present path for 60 fps:** signal the UI thread on each present instead of polling, double-buffer the screen, and use a DXGI flip-model swap chain with vsync. Hours to a day.
8. **Higher internal resolution:** reopen the GPU backend (PLAN lists it under "Not worth doing, or not yet"). Software would need 6–22× for 2×/3× at 60 fps. The undesigned part is the 6–16 texture copies per field frame that land in game memory.
   - The render buffer is a fixed 640×528 array (`gxr.h:9-10`).
   - The Z1 Extreme has an RDNA3 integrated GPU (general knowledge, not measured here).
   - Weeks.
9. **60 fps game logic** is separate from host speed. First trace what advances per pass of the `0x801DC490` loop, to answer PLAN's open question about which clock the logic follows. Lowering the 1-retrace spin threshold probably doubles game speed unless the logic scales by elapsed time (inferred).
10. **Headless soak runs only:** skip texture-copy work on frames that are not drawn. Their source image is stale anyway, and this recovers 0.4–1.5 ms a frame (soakH's wait was 55.6 s, 4.9%). It does not help the window.
