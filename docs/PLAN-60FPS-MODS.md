<!-- Written 2026-09-24 from four read-only research reports (docs/research/frame-pacing.md,
performance.md, mods.md, soak.md) and an independent critique of a first draft, whose every
correction is folded in. Nothing here was run when it was written; the 30 fps cap at
0x801DC4A4 was re-checked in the disassembly. Record what a slice's run shows in
docs/FINDINGS.md, and move a slice here to done the way docs/PLAN.md does. -->

# Next phase: 60 fps, then native mods

**For the owner.** This phase has two goals. The first is a game that shows 60 images a second at its normal speed. The second is native PC mods: declarative data patches and compiled mod DLLs that load at run time, are off by default, and move no pinned hash while off. The most important finding is that the 30 fps cap is a constant. It is the immediate `cmpli r0,1` at 0x801DC4A4, re-checked in the disassembly. Every piece of game logic we can see advances once per frame: fades, script WAITs and the frame counter. The game reads no clock that could scale it. Removing the cap therefore does not give 60 fps; it runs the whole game at double speed. So 60 fps has to come from the renderer: the logic stays at 30, and the port builds an in-between image from two consecutive frames' draws. Uncapping is still useful as a 2× mode, and a battle speed-up (M11) is the obvious use. You are needed for five things:
- a handful of windowed sessions: the paced presenter (H8), vblank locking on your monitor (H9), live interpolation (H17b), the settings file (M5), the overlay (M8) and widescreen (M10, M14). The first is about 15 minutes.
- setting up Task Scheduler and lending two nights to the overnight runner (S6);
- noting the handheld's power mode, and whether it was plugged in, on every measured run;
- one decision: whether to reopen the GPU backend once the pixel-path work (H15d) reports how far it lands from 61 ns per fragment;
- one headless card rebuild on your machine (S7a).

Sizes are in evenings, as in PLAN.md: **hours**, **a day**, **several days**, **week-plus**. **Owner** marks a slice that needs a window on the owner's screen or a person playing. **[V]** means the research quotes the instruction, file:line or log line. **[I]** means it is inferred. *Checked here* means the source was re-read while writing this plan. The new tracks are **H** (speed and frame pacing), **M** (mods), **F4–F7** (Track F continued) and **S** (soak and regression).

---

## A. The goal, and what must be true first

**The goal has two parts.**
1. The game shows 60 distinct images a second and still runs at its normal speed.
2. PC mods and enhancements, both data patches and native mod DLLs, load at run time and are off by default. When they are off, no pinned hash moves.

**One fact shapes both [V, disassembly, re-checked by the lead].**
- **Frame start:** `801DCB84 bl VIGetRetraceCount; 801DCB88 stw r3,-28820(r13)` stores the retrace count at 0x8034768C.
- **Frame end,** in `fn_801DC420`:
  - `801DC498 bl VIGetRetraceCount; 801DC49C lwz r0,-28820(r13); subf; 801DC4A4 cmpli r0,1; 801DC4A8 blt → 801DC490` spins until one field has passed since the frame started.
  - Then come `VISetNextFrameBuffer`, `VIFlush` and `VIWaitForRetrace`, at 801DC4CC–801DC4D8.
- **What that gives:** every frame takes at least two fields. That is 30 fps for work up to two fields and 20 fps past that. The cap is the immediate 1, not a variable.
- **The scene dispatcher runs once per loop.** The frame counter at 0x803475C0 goes up by 1 per call (801DC390).
- **The research lists every clock game code reads.** They are the RNG seeds, the card timeout, the title's 92,267 ms attract timeout, the save timestamp and a 1 Hz play-time alarm. None of them is a per-frame delta.
- **Fades and script WAITs count frames.** The fade level at 0x80347510 moves by 1/(duration−1) per call; the duration at 0x80347514 is in frames and defaults to 30. The WAIT counter at 0x803477AC steps by 1 per tick.
- **So removing the cap runs the whole game at double speed.** That is a battle speed-up mod (M11), not 60 fps.
- **60 fps therefore means:** the logic stays at 30, and the renderer builds the in-between image from two consecutive frames' draws.
- **PLAN's open question is answered.** The logic clock is the presented frame, paced by VI. The disassembly gives the answer, and H2 confirms it with a run by timing a fade in fields.

**The path to 60 fps, in order:**
1. **Measure what drawing every frame costs today (H1).** No current log draws every frame.
2. **Confirm with a run that the logic advances once per frame (S4a, then H2).** H2 needs a frame-tagged read, which S4a's `SOA_PEEK` provides.
3. **Show that consecutive frames' draws can be matched (H4), and scope route (d) alongside it (H5).** If under about 90% of pixels come from matched draws, draws must be tagged by the game first (H7).
4. **Fix the capture set that all speed work is measured on (H6).**
5. **Build a presenter that holds each frame for exactly two refreshes (H8), then lock the guest's VI to vblank (H9).** The presenter is worth having at 30 fps on its own.
6. **Get a midpoint image that looks right offline (H10)** before any speed work that only 60 fps needs. H10 also fixes the design for keeping vertices.
7. **Make the renderer able to produce 60 images a second at 1× (H11–H16).**
   - The copy drains must go.
   - The pixel path must get 1.4–2.5× faster in field scenes and about 2.9× faster in sky and ship scenes [I, budget table].
   - The guest thread must fit a heavy frame in one field wherever the tick is unlocked.
8. **Go live (H17a headless, then H17b in a window), then work the tail one artifact class at a time (H18a–e).**
9. **Before the renderer changes (H11 onward),** S1, S4a/b and H6 must be in place. A regression then fails a check instead of relying on someone to grep. For a renderer change, the check is `title --check` plus replay 23/23, at 1, 2, 3 and 8 threads when the workers change.

**The path to mods, in order:**
1. **The contract.** With mods off, the 23 frame hashes, the self test, `title --check` and `decomp.py` are all unchanged. This is part of every M *Done:*.
2. **A run-time loader for data patches, with a chained frame hook (M1, relink only).**
3. **A safe point between frames, and tick control (M2, one retranslation).**
4. **Native mod code (M3):** a `mod.dll` loaded with `LoadLibrary`, a versioned `SoaModApi`, and callbacks. Then calls from mod code into guest code (M4). This is the core of "native PC mods".
5. **A settings file (M5),** before any enhancement is usable by a player rather than through environment variables.
6. **Enhancements that need only addresses (M6–M11).**
7. **Research, and hook sites compiled in (M12–M14).**
8. **Only for a mod that must change logic inside a function:** the guest-C dialect and a link-level check (F4, F5), then that function (F6, F7).

**Not in this phase:**
- **Higher internal resolution.** 2× or 3× at 60 fps needs 6–22× today's pixel throughput. That means a GPU backend, which PLAN parks under "Not worth doing, or not yet". Reopen it on H15's numbers.
- **Logic at 60 ticks.** Every per-tick constant in the game would have to be halved.
- **Gecko or Action Replay codes that patch instructions.** Writing into `.text` does nothing to translated code. Data-write codes still work.
- **Host save states.**
- **Running soaks in parallel.** Two `soa.exe` at once have died silently three times.

## Where the reports disagree, and how this plan resolves it

1. **"Rasterizing twice is cheap."**
   - The frame-pacing report bases this on A4's 8.8 s of busy workers over 830 s. The performance report shows that A4's run drew about 1 frame in 50, so that figure says nothing about the cost of drawing every frame.
   - This plan uses the performance report's cost: 2.2M fragments at 86–150 ns in field scenes, and about 175 ns in sky and ship scenes. That is 24–41 ms of wall time on 8 workers [I, a fit over 59 runs].
2. **"Windowed play runs at the 30 fps cap."** HANDOFF says so, and C4 says the port is 5–11% short. No current measurement supports either.
   - The only windowed log, 26.7 fps, covers the first 667 frames of a session driven by hand, probably the logos and title [I]. It predates A4 and C3.
   - Since C3, every copy drains the queue before and after (`gxr.c:1987`, `gxr.c:2038`, checked here).
   - Every-frame field play is inferred at about 20 fps. H1 settles it.
3. **The mods report's first acceptance test would pass on its own.** It checks "encounters off" on `a101b`. On `card-saved`, flag 1025 already blocks `a101b`'s encounters, so the check agrees with everything. This plan uses part G on `116a` with the step-counter accelerator instead.
4. **What to interpolate is unsettled.** The frame-pacing report interpolates the clip-space vertices of matched draws; the mods report interpolates XF matrices. H4 measures what each approach needs.
5. **A time step in the middleware is still possible.** The clock listing rules out a delta derived from a clock. It does not rule out a constant step passed to the middleware. The question stays open (M12) but is not on the critical path.
6. **`fn_801DC420` does not need decompiling for a mod.** The mods report lists it first, but M2 changes the tick without touching it. It stays first in Track F only as the pilot for the dialect, and F6 must keep M2 working.
7. **The counts of maps with a save point measure different things.** "54 scripts with op 138" covers all scripts; "15 of the 35 encounter maps" covers the encounter maps only. They do not conflict.
8. **FINDINGS.md:1544's "four random battles" for part G is three.** S1 corrects it.
9. **"The part-G soaks are the only ones that had battles" is wrong.** `build/scenario-soakD.log:1192-1193` loads `/battle/stsicon.mld` at about frame 28.3k, with no BP_MASK line.
   - Counting lines, checked here: soakD 2, soakG 6, bsoak101 2, bsoak202 4, all others 0. Each battle logs `stsicon.mld` twice (LoadCrew and LoadAsset), so the battles are 1, 3, 1 and 2.
   - BP_MASK is therefore not a battle signature. It is a question S1 raises.
10. **Two research checks based on watches cannot work.**
    - `watch_hit` prints only the first 201 hits (`trace.c`: `if (hits++ > 200) return;`) with no frame number (checked here).
    - A poke's own `mem_w32` is itself a hit (`main.c:783`, `cpu.h:150`).
    - So a watch on 0x8034768C covers only the logos, and a watch on 0x80346D28 is spent within seconds by any job that writes it.
    - This plan uses S4a's `SOA_PEEK`, the frame counter at 0x803475C0, and battle counts instead.

**Checked here, so the current exe can be measured without retranslating:**
- The translated objects (built 09-18 05:38) contain the three newest `hle.txt` bindings (strcpy, strcmp and strstr, in `gen/chunk_015.obj`).
- No change to a binding, `trace.txt`, `hooks.txt`, `savepoints.txt`, `cpu.h` or the emitter has been committed since then.
- `SOA_FIFO_DUMP` takes a comma list, and its directory must already exist (`gx.c:93-105,159`).
- `poke_at_frame` fires on the first frame at or after its target, once. It prints `[poke] frame F: ADDR <- NEW (was OLD)` (`main.c:769-786`), so a poke is also a read tagged with a frame. `frame_end` calls the hook before any capture (`gx.c:146-148`).
- The watch compare is inlined by `cpu.h`'s `WATCH` macro, but the printing is in `trace.c`'s `watch_hit`. A frame number or a start frame on `[watch]` lines is therefore a relink, not a retranslation.
- The `window` scenario sets `SOA_RENDER=1` and `SOA_WINDOW=1`, runs 7,500 frames, and takes New Game at frame 1640 (`config/scenarios/window.scn`).
- `gxr_draw_every_frame()` already exists (`gxr.c:357`, `main.c:1057`).

---

## B. Tracks

### Track H — Speed and frame pacing

**Goal.** 60 images a second with the logic at 30, on this machine. It is a Ryzen Z1 Extreme handheld. No log records its power mode or whether it was plugged in, though both change every number.

**What the research established.**
- **[V] Retraces per frame.** Every saved run holds 2.01–2.10 retraces per frame at `SOA_SPEED=1`.
- **[V] Headless snapshot runs.**
  - They make 27.4–29.9 fps (median 29.4).
  - The guest thread spends 37–49% of its time in `SelectThread`. In bsoak101, 83.8% of wall time is spent spinning in the game's two waits.
  - Guest work is a median of 11.9 ms a frame, and 18.2 ms at most, against a 16.7 ms field.
- **[V] Guest hot spots.**
  - The middleware's paired-single vertex loops. The object code for `fn_802A21C4` makes 24 `ldexp`, 24 `psq_load`, 34 `psq_store1` and 12 `fma` calls. Every `psq_l`/`psq_st` calls `ldexp` (`cpu.h:467`, `cpu.h:500`).
  - `PSMTXConcat` (`fn_80238B60`), 2–4.7%.
  - `DCInvalidateRange`, 1.6–3.9%.
  - The FIFO parse, 0.3–3.2 ms a frame.
- **[V] Serial copies.** Every copy this game makes is filtered, and every filtered copy drains the queue. The texture copies sit at the end of the command stream, so the guest thread waits for the whole scene: 17–26 ms per drawn frame in the Part L runs.
- **[V] Synchronous frame end.** Every gather-pipe store parses immediately (`gx.c:411-424`). The XFB copy at 0x801DC484 therefore reaches `frame_end` and the frame hook before the spin at 0x801DC490. `SOA_POKE` and any uncap depend on this.
- **[V] Presentation.**
  - `g_frames_presented` is bumped at copy time.
  - `window.c` polls every 8 ms (`window.c:147`, checked here) and draws through GDI.
  - The screen buffer is single and is read without a lock.
  - There is no vsync.
  - The guest VI fires once 1/60 s of guest time has passed (guest time is wall time × `SOA_SPEED`), and a late retrace is dropped (`irq.c:384`).
- **[V] What the renderer already holds.** Each DrawCmd holds clip-space vertices and fully resolved state. The vertex arena is recycled on every drain, and there is a single EFB.
- **[I] The budget.** 60 images a second at 1× allows at most 61 ns per fragment when guest and raster overlap.
  - That is 1.4–2.5× faster than today's 86–150 ns in field scenes, and about 2.9× faster than about 175 ns in sky and ship scenes.
  - Serially it allows 17 ns, or 5–9× in field scenes. Removing the drains is therefore close to a prerequisite.

**Approach: route (c), interpolation in the renderer.**
- The guest is untouched, so the hashes, the scenarios and the pad recordings all stay valid.
- Order of work:
  1. Measure, and run the kill experiments.
  2. Fix the capture set.
  3. Build the presenter, which pays off at 30.
  4. Render the midpoint offline.
  5. Improve throughput, each step measured on the fixed set.
  6. Go live.

**Risks and open questions.**
- **Throughput.** Software rendering may not reach 60 images a second in heavy scenes on a power-limited handheld. The fallback is to interpolate only when the previous pair finished in budget, and otherwise repeat the frame.
- **Matching.** How well draws match is unknown until H4. The known failure classes are particles, reordered alpha, UI and camera cuts, so a cut detector is needed.
- **Texture copies.** The in-between image skips copies to texture, so its draws sample frame N+1's copies [I].
- **Latency.** Interpolation adds one field of latency [I].
- **Two clocks.** The guest's VI runs off the wall clock; the monitor has its own vblank. H9 locks them, and it must stay inert headless and under D4.
- **The C3 race.** Removing the drains reopens C3's race, which showed up only on the fourth sweep.
- **A parse thread breaks the synchronous frame end.** H13c must drain the parser at the XFB copy, or the frame hook fires after the spin.

**H1. Every-frame cost, headless** — *done 2026-09-24: 17.7-22.3 fps drawing every frame in heavy scenes; FINDINGS "H1".*
Runs on copies of the cards, one `soa.exe` at a time.
- **Opening:** `scenario.py run window --env SOA_WINDOW=0 --env SOA_CARD=build/savetest/perf.raw --log build/perf-full-opening.log`. Then run the same with `SOA_RENDER=0` as the guest-only baseline; its log also gives the opening's map sequence.
- **Part L:** `--frames 3000` and `--frames 9000` on a copy of `card-partL.raw` with the Continue pad, subtracted from each other.
- **Variations:** Part L at `SOA_THREADS` 1, 4, 8 and 15, and at `SOA_SPEED=4`. At `SOA_SPEED=4`, check that `SelectThread` is near 0%.
- **Assert every run reached its map.** Part L must load `126a`. The opening must load the same first field maps as its `SOA_RENDER=0` baseline. No run may load the attract-demo maps `a299a`/`a297a`.
- **Watch for the attract timeout.** The title drops into the attract demo after 92.267 s of wall clock.
  - At `SOA_THREADS=1` a drawn frame costs 190–330 ms of worker time, about 3–5 fps, so the timeout probably fires before START at frame 1600. `SOA_SPEED=4` shortens it in wall time as well [I].
  - A run that lands in the attract demo gives no figure; record it as such. The single-thread point then comes from `--replay` of captures at `SOA_THREADS=1`.
- **Every run:** note the power mode and whether it was plugged in.

*Done:*
- A FINDINGS table gives, for each run: frames ÷ wall seconds, worker busy per frame, producer wait per frame, fragments per frame, the `SelectThread` share, and the map reached.
- The entry gives a verdict on the ~20 fps inference and says whether fps rises with the thread count.
- PLAN's status table, C4 and HANDOFF's "30 fps cap" line are corrected to the measured figure, in every copy.

**H2. Prove the cap and the per-frame logic, by poke and peek** — *done 2026-09-24: per frame (29 frames, 58 fields capped, 37 uncapped); one uncapped frame in five needed 2 fields, so H13 before M11. FINDINGS "H2".*
Run headless in snapshot mode, so the guest thread is measured rather than the rasterizer, on a copy of a Continue card.
- **Baseline, capped:**
  - `SOA_PEEK` of 0x8034768C across a stretch of field frames.
  - `SOA_PEEK` of the fade level 0x80347510, and of the WAIT counter 0x803477AC, across the frames around the Continue's arrival in the field. Every soak reached its field at frame 2650 [V]; that a fade happens there is [I].
  - This run finds the fade or WAIT and its frames.
- **Uncapped:**
  - 256 `SOA_POKE` items of the form `F+i:0x8034768C=0`, starting just before the fade or WAIT that the baseline found.
  - The same peeks, plus 0x803475C0.
  - Each peek line carries the retrace count, so fields can be counted without a watch.

*Done:*
- The baseline's 0x8034768C values step by 2, occasionally 3.
- The `[poke] … (was …)` values step by 1 across the window.
- The run's retrace total is about 256 lower than the baseline's.
- **The per-frame proof:** the fade or WAIT takes the same number of frames in both runs, and about half as many fields when uncapped.
- The FINDINGS entry closes PLAN's open question about the logic clock, citing both runs.
- **Kill conditions:**
  - If the baseline does not step by 2, the anchor is wrong and nothing in H stands.
  - Steps of 2 or more while uncapped mean the guest thread alone cannot finish a frame in one field. H13 then comes before M11.
  - If the fade takes the same number of *fields* in both runs, the logic is not per frame. Uncapping would then be the 60 fps route, and this plan is redone.

**H3. Frame-time percentiles and a sustained uncap** — *done 2026-09-24: `[frametime]`, `SOA_UNCAP=N` (a start frame, not `=1`: disc loads run on the wall clock, so a frame-keyed pad script needs the scene reached first) and `SOA_FRAMETIME_FROM=N`. Guest ceilings 50/104/80 and render ceilings 19/48/26 in the opening, a battle and a ship battle; 8.4-8.9 cores at any load with 8 workers. FINDINGS "H3".*
- Add per-frame wall time (p50, p95, p99 and max) and the process's CPU seconds to the `[run]` report. Today it prints totals only, so hitches are invisible.
- Add `SOA_UNCAP=1`: the frame hook writes 0 to 0x8034768C every frame. It is for measurement only; M2 replaces it for play.

*Done:*
- Both have tests in the style of `test_poke`.
- With neither set, `title --check` and replay 23/23 are unchanged. That is this slice's net; S1 checks soak logs and does not cover it.
- FINDINGS records the uncapped images-per-second ceiling in the opening, a battle and a ship battle, both in snapshot mode (the guest ceiling) and drawing every frame (the render ceiling).
- H1's Part L every-frame runs are repeated with this build, so that H11 has CPU seconds to compare against.

**H4. Can consecutive frames' draws be matched? Offline** — *done 2026-09-24: 100% of 3D draw area matched in all five scenes; the literal all-area line fires only on unmoving full-screen 2D quads, so H7 is not needed. FINDINGS "H4".*
- **Capture pairs** into `build/fifo-pairs`: create the directory, set `SOA_FIFO_DIR` to it (never `build/fifo`) and set `SOA_FIFO_DUMP=F,F+1`. Take pairs in a field, a battle, a ship battle and a cutscene.
- **Write a pair analyser** on top of `fifo.py`'s parser. It keys draws by display-list address, CP array bases, texture addresses, primitive, vertex count and a hash of the TEV setup. It reports:
  - the share of pixels that come from matched draws;
  - the share of draws with equal vertex counts;
  - the share whose XF position-matrix loads match;
  - a histogram of displacement;
  - draws whose order changed;
  - draws reached through a display-list call against direct draws, for H5.

*Done:*
- FINDINGS has the figures for each scene.
- A synthetic test gives a mutated pair (one draw's texture changed) and requires a lower match share.
- **Kill condition:** under about 90% of pixels matched in any scene means H7, draws tagged by the game, comes before H10.

**H5. Route (d) spike, alongside H4** — *done 2026-09-24: dropped; the layer lists are reset per frame and recorded inside the scene update. FINDINGS "H5".*
- Run with `SOA_WATCH=0x80308CBC`, the first layer's display-list head, and with S4a's `SOA_WATCH_FROM` set to a field frame. The head is zeroed every frame (801D0FF0), so an unstarted watch would spend its 201 hits on the logos.
- Read the storing lr and backtraces to find what records the lists.
- Take the inside-versus-outside display-list counts from H4's analyser.

*Done:* a FINDINGS verdict on route (d), in hand at the week-1 decision. Drop (d) if the lists are recorded inside the scene's update tasks. Otherwise name the recorder as the fallback in case H4 and H7 both fail.

**H6. The performance capture set** — *done 2026-09-24: 12 captures pinned in `config/perfset_manifest.tsv`, `tools/perfbench.py`, 85.4 ns/fragment overall. FINDINGS "H6".*
- A named set in `build/perfset/`, captured with `SOA_FIFO_DIR` pointed there and never at `build/fifo`. It holds:
  - H4's four pairs;
  - a heavy Part L field frame;
  - a sky scene and a ship battle, the ~175 ns class, reached from part K's card or the census's ship-stage pokes;
  - copies of the early-game captures 6000 and 15800.
- A manifest of hashes and scene labels is committed. The captures are game data and stay on the one machine.
- A benchmark command copies each capture to a scratch directory before `--replay`, because `--replay` writes `<base>.png` beside it. It runs at 8 threads and reports ns per fragment (worker busy ÷ fragments) per capture, over repeated runs, with the spread.

*Done:*
- Every capture's PNG is opened before the manifest is committed. This is a first bless of a kind: a broken render would benchmark the wrong work. The commit says how each was checked.
- Today's ns per fragment for each capture is in FINDINGS, with the power mode.
- H13–H16 report against this set and no other.

**H7. Tag draws by the game (only if H4 < 90%)** — *not needed: H4 matched every 3D draw (2026-09-24).*
- **Research:** find the object-draw routine. No address is known; H5's recorder backtrace is the starting point.
- **Tag each draw with its object pointer.**
  - Pass the tag through a renderer setter into each DrawCmd, so the renderer still links alone.
  - A `hooks.txt` pre-hook at the routine's entry is acceptable only if the routine has no loop that waits on an interrupt, because the hook strips `irq_poll` from all of its back-edges. Otherwise it waits for M13's wrapper sites.

*Done:*
- H4's analyser, keyed on tags, reaches at least 90% of pixels matched in every scene. If it does not, FINDINGS says so and route (c) is re-decided against H5's verdict.
- With tags off, 23/23 and `title --check`.

**H8. A paced presenter** — *a day. **Owner:** one windowed session.*
- A DXGI flip-model swap chain with vsync, presented on an event instead of the 8 ms poll.
- A double-buffered screen.
- Each real frame is held for exactly two refreshes.
- The same session records today's windowed rate: the `window` scenario, about 4 minutes, on a card copy, and H1's Part L with `SOA_WINDOW=1`.

*Done:*
- A histogram of present intervals, from the presenter's own timestamps, for the old path and the new one.
- The drift between guest retraces and host vblanks over the session is recorded, as H9's input.
- With the new path, at least 99% of the frames the game finishes in time are held for exactly two refreshes, or the misses are attributed to drift for H9. That target is set here, not measured.
- 23/23 unchanged, because the presenter sits after `g_screen`.
- The owner's verdict on whether it looks smoother.

**H9. Lock the guest's VI to vblank, and handle monitors that are not 60 Hz** — *several days, `--link`. **Owner:** one windowed session.*
- In a window at `SOA_SPEED=1`, deliver the guest retrace from the presenter's vblank instead of the wall clock.
- Headless runs, `SOA_SPEED` other than 1, and D4's deterministic clock keep today's path, so no scenario, soak or hash can change.
- **At a refresh rate that is a whole multiple of 60:** hold each image for proportionally more refreshes.
- **At any other rate:** keep the wall-clock VI, let the presenter take the nearest refresh, and log that it is doing so.
- The late-retrace rule stays (`irq.c:384`).

*Done:*
- In the owner's session at 60 Hz, the lock meets H8's 99% target; the drift without it is recorded.
- The peek lines show 0x803475C0 advancing 30 per wall second with the lock on. The audio report is unchanged.
- Headless: `title --check`, replay 23/23 and `SOA_HASH` lines are unchanged.
- FINDINGS states how the lock interacts with D4, and what happened at another refresh rate if the display offers one.

**H10. A midpoint image, offline, and the vertex-retention design** — *several days.*
- `--replay` of a pair renders the midpoint to a PNG: matched vertices are interpolated, unmatched draws come from F+1, and copies to texture are skipped.
- The vertex retention it builds, meaning what is kept across the drain and on which thread, is written into ARCHITECTURE.md. It is the layout H16 and H17a must use.

*Done:*
- The four scenes' midpoints are opened and judged, and FINDINGS lists their artifacts.
- A synthetic test shows that a triangle moved by 2d between frames lands at d in the midpoint.
- `scenario.py replay` is 23/23 unchanged.

**H11. Stop spinning when idle** — *hours to a day, `--link`.*
About ten host threads stay busy while the game waits. The guest idle hook should sleep until the next device deadline. The workers should block on an event instead of calling `YieldProcessor` and `Sleep(0)`.

*Done:*
- Against H3's re-run of H1's Part L every-frame run, CPU seconds fall and fps does not.
- Retraces per frame stay at 2.0–2.1.
- `title --check` and replay 23/23 are unchanged.

**H12. Texture hashing and the cache** — *a day, `--link`.*
- Hash each texture once per frame, not on every lookup: that costs a median of 2.2 ms a frame, up to 12 ms.
- Grow the texture cache past 256 slots; 54 runs report it thrashing.
- **Risk:** a texture rewritten within a frame, by a copy to texture or by the CPU between draws, must still be re-hashed [I].
- The hash function stays the same, because M9 freezes it as the pack key.

*Done:*
- In H1's Part L every-frame run, TEV prepare and texture decode per drawn frame are at least halved.
- Replay is 23/23 at 1, 2, 3 and 8 threads.

**H13. Guest-thread speed** — *three slices, each measured.* M2's "about 60 a second" in heavy scenes needs these, and so does M11. They also free producer-thread time for route (c). Each reports guest ms per frame, meaning wall × (1 − `SelectThread` − the two spins), in snapshot runs of Part L and a battle, and H3's uncapped ceiling. The target is the heaviest scene's 18.2 ms brought under 16.7 ms; the research estimates 10–30% from all three together [I].

**H13a. Paired singles and fma** — *a day, plus a full retranslation (`cpu.h`).*
- Specialise `psq_l`/`psq_st` for this binary's six constant GQRs, with no `ldexp` (`cpu.h:441`, `:467`, `:500`). Fall back to the generic path when a GQR differs.
- Inline `fma` with `/arch:AVX2` or intrinsics.

*Done:*
- A self-test case compares the specialised and generic paths for each of the six GQR settings.
- The full self test, replay 23/23 and `title --check` pass.
- Guest ms per frame is measured before and after.

**H13b. PSMTXConcat native; DC range calls as no-ops** — *hours, plus a full retranslation (`hle.txt`).*
- Bind `fn_80238B60` (`PSMTXConcat`) natively, with a twin case.
- Bind `DCInvalidateRange` and `DCFlushRange` as no-ops. `dcbi` already emits nothing (`gen/chunk_013.c:31609`); check that `dcbf` does too before binding `DCFlushRange`.
- Use lowercase `0x` and eight hex digits, or the line is dropped silently.

*Done:*
- `--compile --optimize --link`, then the self test, including case 73 and the new twin.
- Replay 23/23 and `title --check`.
- Guest ms per frame before and after.

**H13c. The FIFO parse on its own thread** — *several days, `--link`.*
- Move the parse, 0.3–3.2 ms a frame, off the guest thread.
- Drain the parser at the XFB copy (BP 0x52, from 0x801DC484) and at draw sync (token 0xB00B, 801DC488). `frame_end` and the frame hook must still run before the spin.

*Done:*
- H2's uncapped window still steps by 1, which proves the hook still fires in time.
- Replay 23/23 at 1, 2, 3 and 8 threads, and `title --check`.
- `SOA_FIFO_DUMP` captures are byte-identical to those from the synchronous parser.
- Guest ms per frame falls by about the parse share.

**H14. Remove the two full drains around each filtered copy** — *several days, `--link`.*
Either order the workers against their neighbours' rows, or snapshot the three source rows the filter reads.

*Done:*
- Replay 23/23 at 1, 2, 3 and 8 threads over at least four sweeps.
- In H1's Part L run, producer wait per drawn frame falls from 17–26 ms to the level of the copies alone.
- The every-frame fps is reported. The prediction is about 45 ms a frame falling to about 30 [I].
- H6's set is re-measured.

**H15. The pixel path down to 61 ns per fragment** — *four slices, each measured on H6's set. Absorbs C4. After H10.*

**H15a. C4's cheap pair** — *hours.*
- Test depth before the TEV where the alpha test cannot reject, minding the trap that XOR of two always-true comparisons is always false.
- Resolve the perspective divide once per texture coordinate, not twice per stage (`gxr_tev.c:787`).

*Done:* C4's criterion (`failed depth` within 0.1%, all 23 diffs at zero), plus ns per fragment for each capture before and after.

**H15b. Hoist the per-sample division** — *hours.* The division is at `gxr_tev.c:741`.

*Done:* replay 23/23, and ns per fragment before and after.

**H15c. Specialise the fragment function per draw** — *several days.*

*Done:* C4's criterion of 1.5× on the heaviest captures, replay 23/23, and ns per fragment.

**H15d. SIMD spans** — *several days to week-plus.*

*Done:*
- At most 61 ns per fragment at 8 threads on the field captures, and on the sky and ship captures, which need about 2.9×.
- If either falls short, write down the gap. That number is the owner's GPU-backend decision.

**H16. Vertex setup onto the workers** — *a day to several days, `--link`. After H10.*
Move vertex setup (2–4 ms per drawn frame) off the guest thread, keeping H10's retention layout.

*Done:*
- Guest-thread vertex setup per drawn frame falls in H1's Part L run.
- Replay 23/23 at 1, 2, 3 and 8 threads.
- H10's synthetic midpoint test still passes.

**H17a. Interpolation, headless, off by default** — *several days, `--link`.*
`SOA_INTERP=1` does the following:
- keeps frame N's vertices across the drain, in H10's layout;
- pins textures for two frames;
- uses a second EFB, or saves and restores it;
- has the in-between pass skip copies to texture, `g_frames_presented`, the frame counter and the hash;
- headless, writes the in-between PNGs.

*Done:*
- **Off:** 23/23, `title --check`, and `SOA_HASH` lines identical to before.
- **On, headless:** the real frames' `SOA_HASH` lines are still identical, which proves the in-between pass does not touch them. The in-between PNGs from a field, a battle, a ship battle and a cutscene are opened.

**H17b. Interpolation, live** — *several days, `--link`. **Owner:** judges it in a window.*
- H8's presenter shows the in-between image at the first refresh.
- A cut detector repeats the frame when the match share falls below H4's threshold.
- Interpolate only when the previous pair finished in budget; otherwise repeat the frame.
- The switch goes into M5's settings file, off by default.

*Done:*
- A synthetic cut pair (two unrelated captures) makes the detector repeat the frame.
- A windowed opening, a field walk and a battle show 60 images a second, with the p99 present interval within one refresh of 16.7 ms (a target set here).
- Off: 23/23 and `title --check`.
- The owner's list of visible artifacts is filed as H18's input.

**H18. The tail, one artifact class per slice** — *a day to several days each.*
Classes known today, to be confirmed by H17b's list: **H18a** particles, **H18b** reordered alpha, **H18c** UI and HUD, **H18d** camera cuts the detector misses, and **H18e** texture copies that the in-between image samples from N+1.

*Done, for each:* a fix or a documented fallback to repeating the frame for that class, with before-and-after in-between PNGs opened. Off: 23/23.

---

### Track M — Mod framework and enhancements

**Goal.**
- Mods load at run time from `SOA_MODS=<dir>` or the settings file. They are off by default and keep the contract.
- A mod is a folder holding a declarative patch list, a native `mod.dll`, or both.
- The first enhancements are the ones that need only addresses.

**What the research established.**
- **[V] How native code takes over.**
  - `hle.txt`, `hooks.txt` and `trace.txt` are baked into the translated C. Each change costs a full retranslation of about 2 minutes: 103 s of /O2 compile and about 20 s of link.
  - `SOA_POKE` and `SOA_WATCH` work at run time.
  - Nothing loads a DLL or keeps a list of callbacks.
- **[V] The frame hook.** It has one slot, which `SOA_POKE` already uses. It fires inside the GXCopyDisp gather-pipe store (0x801DC484), so only memory writes are safe there.
- **[V, checked here] The watch.** It prints only 201 hits and no frame number, and a poke's write is a hit. Acceptance checks therefore use `SOA_PEEK` (S4a) and battle counts instead.
- **[V, checked here] Hooks and interrupts.** A `hooks.txt` entry removes `irq_poll` from every back-edge of its function (`emit.py:240,309`). A hook in a loop that spins waiting for an interrupt would therefore hang.
- **[V, checked here] Telling call sites apart.** Every translated call sets `s->lr` first (`emit.py:297-298`). A native `VIGetRetraceCount` can therefore tell 0x801DCB88 (the top of the loop) from 0x801DC49C (the spin).
- **[V] The native-to-guest call pattern exists.** It is `irq.c:276-291` (`call_guest_handler`), reachable today only from inside `irq.c`.
- **[V, by runs in FINDINGS] Existing recipes.**
  - Warp by name: the name at 0x80305CF0 (three words), 0x8030E420 = 0, then 0x80311AEC = 15.
  - Part select: warp to `ME355A.SCT`.
  - The ending: 0x80310A68 = 0x4C000000.
  - A forced battle: six words at 0x803473D4.
  - The fade fix: 0x80347518 = 0.
  - The save menu: 0x803473B0 = 0, 0x803473B4 = 1; the result is at 0x803473C4.
- **[V] Texture replacement.** The texture cache hashes every source byte plus the palette. The sampler scales by `lw/w`, so a higher-resolution replacement samples correctly with no other change.
- **Encounter step counter.** `fn_800C1C24` and the counter at 0x80346D28 come from quoted instructions, not from a run. The soak research checked in the disassembly that every gate runs before the counter is read.
- **[V] Encounter rate.** The rate is a u16 in the loaded table, at `table + 2 + z*132` for zones 0–7. The table pointer is at 0x803474BC. Map 99 uses a separate sub-table (`fn_800C1A50`).
- **[I] Widescreen.** Every perspective matrix comes from `fn_80239270` (`C_MTXFrustum`), which has five call sites, all in the middleware. Where the CPU culls against the camera is unknown.
- **Save-anywhere trap.** A load sets `sys[15]=20000`, and maps with no save point can break on that branch (`a116c` asked for camera 9001 and trapped).

**Approach.**
- Build in layers:
  1. the loader for data patches;
  2. the safe point and tick;
  3. native mod DLLs on a versioned API;
  4. `call_guest`;
  5. settings;
  6. features that need only addresses;
  7. hook sites compiled in.
- Declarative patch lists (`addr = value` with conditions) cover the first mods without any code.
- `SoaModApi` holds plain data only. It is versioned by size and number, and members are only ever appended.

**Risks and open questions.**
- **Save format.** Anything a mod writes into the saved regions persists into the card, so mods must not change the save format.
- **Game data.** Texture dumps and packs are game-derived, and the guard does not refuse `.png` today.
- **Recordings.** The active mods, DLLs included, must be written into the pad config header, or a recording of a modded session cannot be replayed.
- **Native code.** A `mod.dll` runs with the port's full rights. It is loaded only from the named directory, only when enabled, and only after its version and DOL SHA-1 check. There is no sandbox.
- **Threads.** Callbacks run on the guest CPU thread. Mods must never touch `CpuState` from the UI, raster or watchdog threads.
- **Post-hooks.** A post-hook is skipped when an interrupt return `longjmp`s through it.
- **A guard on every function.** Its overhead is unmeasured; measure it before adopting it.
- **Rendering at 60 ticks.** When the tick is unlocked, rendering must either keep up with every frame (Track H) or skip every other frame.

**M1. The mod runtime, data patches only** — *done 2026-09-24: `runtime/mod.c`, `SOA_MODS`, `mods/encounters-off`, 42 parser tests; accelerated part G fought 5 without the mod and 0 with it, peeks 100000+ against 0-1. FINDINGS "S3 and M1". The map condition reads the committed map 0x80311AC0, not 0x80311AC4, the picker's working copy (FINDINGS "131e renders").*
- `runtime/mod.c` with `SOA_MODS`.
- A `mod.ini` per mod: name, API version, and the required DOL SHA-1.
- A patch-list format: `addr = value`, with a `when` condition on scene, map or state, and a trigger of `every_frame`, `on_map_load` or `once`.
- **Refusals:** MMIO addresses, writes into `.text`, anything outside MEM1, and badly spelled addresses (the `hle.py` rule, but refused loudly rather than dropped).
- **A chained frame hook:** S4a's peeks first, so they read what the game wrote, then the pokes, then each mod. `gx.c` does not change.
- **Recording:** the active mods are written into the `pad_config` header.

*Done:*
- Two jobs on part G's card at `116a`, both with S3's accelerator and the same seed:
  - Without the mod, the job fights at least one battle (`stsicon.mld` loads), and a peek of 0x80346D28 on the frame after each accelerator poke reads 100000 or more.
  - With an "encounters off" patch (0x80346D28 = 0 every frame in scene 6), the job fights none, and the same peeks read at most 1.
  - The peek difference between the two jobs is what shows the check can fail.
- Both jobs assert they reached `116a` and not the attract demo.
- With mods unset, the contract holds.
- Parser tests cover each refusal, with no disc needed.

**M2. A safe point and tick control** — *done 2026-09-24: `runtime/tick.c` answers `VIGetRetraceCount`; `SOA_UNCAP=N` now unlocks the tick instead of zeroing 0x8034768C. Safe points = presented frames less the one frame shown before the loop starts; unlocked, 253 of 255 title frames took one field (59.5 a guest second). Self-test case 74. FINDINGS "M2".*
- Bind 0x8023F704 (`VIGetRetraceCount`) natively. It returns the word at 0x80347A64, as the original does.
- When `lr` is 0x801DCB88, it first runs the safe-point callbacks.
- When `lr` is 0x801DC49C and the unlock is on, it returns the word at 0x8034768C plus 1, so the spin exits.
- Add a twin case to the self test.

*Done:*
- Safe-point callbacks equal presented frames over the title scenario.
- With the unlock on, headless in snapshot mode, peeks of 0x803475C0 show one frame per field, about 60 per guest second, in the title. In heavy scenes this waits on H13. The audio report is unchanged.
- With it off, 23/23, `title --check` and the full self test pass, including case 73.
- It replaces H3's `SOA_UNCAP`.

**M3. Native mod code: `mod.dll` and `SoaModApi`** — *several days, `--link`.*
The core of native PC mods, right after the loader and the safe point.
- **Loading:** an optional `mod.dll` in a mod's folder, loaded with `LoadLibrary`, exporting `int soa_mod_init(const SoaModApi*, uint32_t ver)`.
- **`SoaModApi` v1 provides:**
  - big-endian guest-memory accessors (u8, u16, u32, f32 and bulk), with M1's refusals;
  - state helpers: scene 0x803475CC, map 0x80311AC4 and byte 0x80311AC8, field state 0x80311AEC, story flags 0x80310B3C.
- **Callbacks:**
  - `on_frame_end`, for memory writes only; guest calls and GX are refused;
  - `on_safe_point`;
  - `on_map_loaded` and `on_scene_change`, derived at the safe point from the words above;
  - `pad_filter`, in `si.c`'s `pad_sample` after live and scripted input are merged;
  - renderer filters registered through setters (`gxr_set_texture_provider`, `gxr_set_projection_filter`), so the renderer still links alone.
- **An example mod's source** in the repository, built by CI's MSVC job. Check its directory name against `FORBIDDEN_DIRS` and `.gitignore` first: a bare `game/` is ignored at any depth.

*Done:*
- With the example DLL loaded:
  - `on_safe_point` fires once per presented frame over the title scenario;
  - `on_map_loaded` fires once per field load line in the log;
  - a `pad_filter` that swallows START keeps the title run on the title, so its map assertion fails (this is the mutation);
  - a pass-through filter passes `title --check`;
  - an identity projection filter leaves every `SOA_HASH` line of a title run identical, and a filter that changes the projection moves them.
- A wrong API version, a wrong DOL SHA-1, or a missing export is refused with a message, not a crash.
- A guest call or GX write from `on_frame_end` is refused.
- The DLL mods and their versions are recorded in the `pad_config` header.
- With mods unset, the contract holds.

**M4. Calling guest code from a mod** — *a day, `--link`.*
Add `call_guest(addr, ints, floats)` to the API, allowed at the safe point only, following the `irq.c:276-291` pattern.
- It asserts r2 = 0x80350000 and r13 = 0x8034E720, and that the GQRs are unchanged.
- It refuses to run inside an interrupt handler.
- The callee may sleep the thread, which is legal between frames and documented.

*Done:*
- A self-test case calls a leaf's recompiled twin, and r1, r2, r13, the non-volatile registers, LR and the GQRs all come back intact.
- A call made from the frame end or from a handler is refused with a message.
- A DLL built against M3's API still loads.

**M5. User-facing settings** — *a day, `--link`. **Owner:** checks it without a terminal.*
- A settings file beside the exe holds every switch a player would use: mods, the presenter, `SOA_INTERP`, widescreen, the texture pack, and the battle speed-up. It is edited by hand or from M8's settings page; a separate launcher is built only if the owner wants one.
- Environment variables override the file.
- Scenario runs, the self test and `nightly.py` ignore the file, so a player's settings can never move a check.
- Unknown or misspelled keys are reported, never silently dropped.

*Done:*
- With no file, behaviour is identical: the contract holds.
- Parser tests cover each key, the override, and a misspelled key.
- A scenario run with a file present that turns everything on still passes `title --check`.
- The owner turns an enhancement on and off without a terminal.
- Every later enhancement's *Done* includes "its switch is in the settings file, off by default".

**M6. Patches relative to a pointer, and read-modify-write** — *a day, `--link`.*
- Extend M1's format with widths (u8, u16, u32) and with addresses relative to a pointer (`[0x803474BC] + 2 + z*132`, for z in 0–7).
- Add a read-modify-write operator (`*= k`, clamped to the width).
- The trigger is `on_map_load`, keyed on the map word, and each load is applied once. A repeated trigger must never compound.
- Map 99 is refused until its sub-table (`fn_800C1A50`) has its own layout work.
- First use: the encounter rate × k.

*Done:*
- The loader logs each of the eight rate words as `addr: was → now` once per map load, and a peek later in the map agrees.
- A unit test pins that a second trigger on the same load does not compound.
- On part G at `116a` with S3's accelerator, rate × 0 fights 0 battles and rate × 1 fights at least one.
- The contract holds.

**M7a. Save now, with the `sys[15]=20000` trap** — *several days, `--link`; the trap is the work.*
- Allowed only in scene 6, state 8, with no event running. The script tick freezes while the request is 1 (0x8021214C).
- On maps whose script contains op 138, the one-word request (0x803473B0 = 0, 0x803473B4 = 1) is used directly.
- On other maps, a Continue takes the `sys[15]=20000` branch. The proposed fix is to write 0x8030E420 = 0 before the map's script runs [I]; the timing of that write, and where the player then lands, are part of the work.

*Done:*
- A save-now on an op-138 map, then a Continue run on that card copy, lands on that map, and `cardformat.py verify` reports READY.
- At `a116c`, the known trap, a save-now and Continue with the fix lands without the camera-9001 trap, with frames opened. Without the fix, a save-now there is refused with a message.
- The contract holds.

**M7b. The other debug actions, headless** — *a day to several days, `--link`.*
Actions are queued to the safe point, and an environment variable drives them for tests.
- **Warp by name** from the table at 0x802E4780: 158 entries in Shift-JIS, decoded with `MultiByteToWideChar(932)`. Never use the old stage-select route (state 2), which skips the teardown.
- **Part select.**
- **Forced battle:** the six-word request. It is for debugging only and must never be used in a soak, because it skips every gate.
- **Fade fix, encounter toggle, the ending, and the tick unlock.**

*Done:*
- Each action reproduces its FINDINGS recipe in a headless run, and its frames are opened.
- The contract holds.

**M8. Overlay and hotkeys** — *a day to several days, `--link`. **Owner:** one windowed session.*
- The overlay is drawn in `window.c`'s `present()` after the RGBA to BGRA conversion, and never into `g_screen`.
- The UI thread only posts requests to a queue, which is drained at the safe point.
- While the menu is open, the keyboard stops reaching the pad.
- A settings page edits M5's file.

*Done:*
- The owner opens the menu, warps, saves, and loads the save back through Continue.
- 23/23 unchanged, and `SOA_HASH` lines are identical with the overlay open.

**M9. Texture dump and replace** — *several days, `--link`.*
- **Dump:** on first decode, write a PNG named from width, height, format and the source hash.
- **Replace:** load a hash-to-file index at startup, keep replacements in their own cache, and add log2(scale) to the LOD.
- **Reading PNGs:** use WIC, since `vendor/` is forbidden.
- **The hash:** freeze and version it, because it becomes the pack key. H12 changes when it is computed, not what it computes.
- **The guard:** add the pack and dump directory names to `FORBIDDEN_DIRS`.

*Done:*
- An opening texture is dumped, edited visibly at 2×, and the replacement shows in that frame's snapshot, which is opened.
- With the pack off, 23/23.
- `test_guard` refuses a pack directory.
- A test pins the hash key.
- The switch is in the settings file, off by default.

**M10. Widescreen, stage 1 (anamorphic)** — *several days, `--link`. **Owner:** judges it in a window.*
- Perspective draws (XF 0x1026 bit 0 clear) get p0 × 3/4.
- The image is presented at 16:9.
- Orthographic HUD draws are pillarboxed, except full-screen quads.

*Done:*
- PNGs from a field, a battle, a ship battle and a menu are opened and judged.
- The problems at the screen edges are listed; pop-in from the game's CPU culling is expected, and M14 addresses it.
- With it off, 23/23. The switch is in the settings file.

**M11. Battle speed-up** — *hours, `--link`. After M2 and H13.*
The tick unlock applies only while 0x803475CC is 7 (battle). Rendering either draws every frame, or skips the draw and the present on alternate frames, reusing the skip at `gxr.c:1534`.

*Done:*
- Peeks of 0x803475C0, which carry the retrace count, show one frame per field in battle and one per two fields outside it: about 60 and 30 per second. If the guest cannot finish a battle frame in one field, FINDINGS gives the shortfall.
- The battle returns to the field normally.
- The audio report is unchanged.
- The contract holds. The switch is in the settings file.

**M12. Research spikes** — *hours each, no rebuild after S4a.*
- **Text speed:** first find the 24×24 I4 glyph textures' address from a FIFO capture taken while a message is shown [I]. Then watch writes to it, with `SOA_WATCH_FROM` set to a frame when the message is on screen, to find the message task.
- **Camera:**
  - Read the pointer at 0x80347EB4 (used by `fn_8029C9B0`) with `SOA_PEEK` in a field.
  - Then `SOA_WATCH` the matrix it points to, starting at a field frame, to find its writer. Watching the pointer's own word would catch only changes to the pointer.
  - Find whether the field reads the C-stick.
- **Widescreen culling:** find who culls against the 0x80345850 block. `fn_80288C68` and `fn_802AB460`–`fn_802AC160` are the candidates [I].
- **Middleware time step:** does the middleware take a constant step argument?

*Done:* a FINDINGS entry for each, with [V] and [I] marks and function addresses. These feed M14 and F7.

**M13. Hook sites by address (`config/modsites.txt`)** — *several days, plus an emitter change and one retranslation.*
Emit `body_fn_X` plus a wrapper `fn_X`, without setting `_hooked`, so back-edges keep their interrupt polls. Attaching and detaching happen at run time; adding a site costs a retranslation.

*Done:*
- A test attaches and detaches pre, post and replace handlers at run time on a listed site.
- `test_emit` asserts that the back-edges keep `irq_poll`.
- `tools/profile.py` reports the overhead with sites listed and nothing attached.

**M14. Widescreen, stage 2 (culling and clean edges)** — *several days, plus one retranslation. After M12 and M13. **Owner:** judges it in a window.*
- A pre-hook on `fn_80239270`, at an M13 site, multiplies l and r (f3, f4) by 4/3, only for camera callers selected by lr. The five call sites are `fn_802970A0`, `fn_80299188`, `fn_80299238`, `fn_802992F8` and `fn_802993C8`; which of them are cameras comes from M12.
- Widen the CPU cull that M12 found.

*Done:*
- Field, battle, ship-battle and menu PNGs are opened. The edge pop-in listed under M10 is gone, or each case that remains is listed.
- Off: 23/23. The switch is in the settings file.

---

### Track F (continued) — Targeted decompilation, for the mods

**Goal.** A decompiled game function can run in the port, and the only functions decompiled are the ones a mod must change on the inside. The broad library grind stays parked, because finishing SDK libraries gives mods little beyond names.

**What the research established.**
- **[V] Why the native path cannot run game code yet.**
  - It has no big-endian accessors over guest memory and no way for native code to call guest code; PLAN names both.
  - `aramcache*.c` matches but declares host structs with `void*` fields.
  - `C_MTXFrustum` writes host-order floats.
- **[V] Words only a link can decide.** 35 of the 100 matched symbols carry words that only a link can decide. Game-code targets land in that group, because of every `bl` and every r13 global.
- **[V] Bindings keyed on lr.** M2's native `VIGetRetraceCount` tells its callers apart by `s->lr`, which only translated calls set.
- **[I] The size of the targets.** They total about 8 KB, roughly the whole decompilation so far (8,084 B):
  - `fn_800C1C24` 1,960 B, `fn_80101828` 1,596 B and `fn_800FFB24` 1,484 B;
  - `main` 664 B, `fn_80123CBC` 464 B and `fn_801DC420` 228 B;
  - plus the text and camera functions once M12 finds them.

**Approach.**
- **The guest-C dialect.**
  - `GPTR(T)`, and `LD32`/`ST32`/`LDF`/`STF` accessors. Under mwcc they compile to plain dereferences (the same bytes); under MSVC they compile to `mem_r*`/`mem_w*`.
  - Calls to undecompiled functions go through `dispatch(g_state, addr)`.
  - The dialect's call path sets `s->lr` to the original return address, so bindings keyed on lr keep working.
- **Mod changes stay outside matched units.** A mod's change lands as a separate, reviewed commit outside the matched unit.

**Risks and open questions.**
- The macros may disturb mwcc's code generation, and a unit must still match.
- Twins test 200 random rounds; they are not a proof.
- F5's design is not scoped, so its size is a guess.

**F4. The guest-C dialect** — *several days: `--link`, plus one retranslation for the new `hle.txt` lines.*

*Done:*
- `aramcache*.c` and `mtx.c` run natively.
- `decomp.py` still matches every unit.
- The twin comparison passes for each newly swapped function.
- A test shows that a native call through the dialect presents the original return address in `s->lr`.
- 23/23 and `title --check` are unchanged.
- An accessor deliberately left in host byte order makes a twin fail, which proves the oracle can fail.

**F5. A link-level check for relocated words** — *several days (an estimate).*

*Done:*
- `decomp.py` reports the 35 words as match or differ, instead of "not counted".
- A wrong `bl` target or r13 offset reports "differs".

**F6. Pilot: `fn_801DC420`, the frame end** — *a day to several days.*
It is small and fully understood, calls undecompiled SDK functions, and reads r13 globals. It also calls `VIGetRetraceCount` from the spin, which is exactly what M2 detects by lr.

*Done:*
- It matches, including its relocations under F5.
- The twin passes.
- Once bound natively:
  - `title --check` passes;
  - retraces per frame stay at 2.0–2.1;
  - 23/23;
  - **M2's unlock test passes unchanged:** with the unlock on, 0x803475C0 advances one frame per field in the title. Without F4's lr handling this would silently stop working.

**F7. Targets, as mods need them** — *a day to week-plus each.*
- First, whatever M12 finds for text and the camera.
- Then `fn_800C1C24`, but only if a mod needs a different encounter formula. Scaling the rate is M6's patch relative to a pointer, not decompilation. Map 99's sub-table needs its own layout work either way.

*Done, for each function:* it matches, the twin passes, it is bound, and the mod's change is a separate commit.

---

### Track S — Soak and regression

**Goal.**
- Turn "the run finished" into checked invariants before H and M touch the renderer and the runtime.
- Give the runtime the frame-tagged reads that H2 and M1 need.
- Soak dungeons that really fight the game's own encounters (this is option 3).

**What the research established.**
- **[V] How the soaks were judged.** `soak.py` only generates pads. None of the 12 soaks used `--check`; each verdict was a grep.
  - Each 33,500-frame run took 1,121.6–1,128.1 s.
  - All exited 0, with no `[mmio!]` lines, no unknown FIFO bytes and no bad vertex refs.
  - All 12 ran as `scenario.py run battle`, and each copied its card into the one `build/savetest/work.raw`.
- **[V] Renderer coverage.** Each soak rasterized 34 of its 33,500 frames (`SOA_SNAP=1000`).
- **[V, checked here] Battles.** Four soaks fought battles: soakD 1, soakG 3, bsoak101 1 and bsoak202 2. Each battle logs `stsicon.mld` twice. The other eight fought none: soakE, soakH, soakJ, soakL, bsoak303, bsoak404, bsoak505 and bsoak606.
- **[V] What the write-ups missed.**
  - `[gxr] BP_MASK 080000 was in force…` appears in the three part-G logs, and not in soakD's battle.
  - Game over wasted 38–50% of each part-G soak.
  - The random A presses saved to the card over and over: 1,933,312 bytes in bsoak404.
- **[V] What replays from a seed.** The RNG is reseeded from `OSGetTick` on every map load, so a soak replays its input, not its encounters.
- **[V] The accelerator.**
  - The step counter 0x80346D28 is read after every gate: flag 1025, the zone and the movement tests.
  - Poking it to 100000 therefore only shortens the wait. That the zone rate still applies is inferred [I].
  - **Never use the six-word request at 0x803473D4 in a soak.** It skips every gate.
- **[V, checked here] Runtime reads.** A poke reports the value it replaced and its frame. The watch reports 201 hits and no frame. Nothing reads a word at a chosen frame without writing it.
- **[I, a lower bound] Which save for which dungeon.** The table comes from `sct.py` flag tests, and the linear disassembly lost sync in 1–36 entries per map.
- **[V] The guard.** `.raw`, `.fifo`, `.regs`, `.ram`, `.wav` and `.png` are not refused. TESTING.md:948-949 gives stale CI counts.

**Approach.**
- First the frame-tagged read (S4a), because H2 and M1 need it.
- Then the checker, run back over the 12 existing logs, then the accelerator, the other runtime aids and the runner.
- CI runs the Python against fixture logs. Never use a self-hosted runner, because the repository is public.
- Interpolation leaves frame-keyed scripts valid. A tick change (M2, M11) does not, so generators should hold durations in game-seconds and take `--fps`.

**Risks and open questions.**
- Until D4 gives a deterministic clock, compare invariants and coarse outcomes, not exact sequences.
- Two `soa.exe` at once have caused three silent deaths, so runs stay serial.
- The title drops into the attract demo after 92.267 s of wall clock. A slow run can miss Continue and "pass" while soaking the attract demo, so every run must assert its setup.

**S4a. `SOA_PEEK`, and a watch you can aim** — *done 2026-09-24 (commit ae74c35); both run-level criteria checked in H2's baseline.*
- **`SOA_PEEK=addr@N[-M][,…]`** reads a word at frame N, or at every frame from N to M. It has its own list, not a share of `SOA_POKE`'s 256.
  - Each line is `[peek] frame F: ADDR = VALUE (retrace R)`, where R is the word at 0x80347A64.
  - Peeks run before pokes in the frame hook, so they read what the game wrote.
- **`[watch]` lines gain the game's frame counter** (the word at 0x803475C0).
- **`SOA_WATCH_FROM=N`** ignores hits before that counter reaches N, without spending the 201.
- All of this lives in `main.c` and `trace.c`; `cpu.h` does not change.

*Done:*
- Tests in the style of `test_poke`.
- A peek and a poke of the same word at the same frame print the old value.
- A watch started at a field frame prints only hits from that frame on.
- With none set: `compile_runtime.py`, `--link`, the self test, `title --check` and replay 23/23 all pass.

**S4b. The other runtime aids** — *hours each, `--link`.*
- `SOA_UNTIL=addr=value`: a clean stop, for example at game over.
- `SOA_RASTER_ALL`: rasterize every frame while still snapshotting every N. It is a switch onto the existing `gxr_draw_every_frame()`.
- `SOA_FRAMES_DIR`: where snapshot PNGs go.

*Done:*
- Each has tests in the style of `test_poke`.
- `SOA_UNTIL` exits 0 and prints the full report.
- The fps cost of `SOA_RASTER_ALL` is recorded.

**S1. `soak.py check`** — *done 2026-09-24: `python tools/soak.py check LOG...`; all 12 logs pass the failure invariants, battle counts as below. Two criteria were wrong and the checker follows the logs: only **four** logs "did not test what it says" (bsoak303/404/505/606, the battle mix with no battle) -- soakE/H/J/L were walk soaks that ran under `scenario.py run battle` for its environment and never claimed a battle; and soakD's battle is at frame ~30,670, not ~28.3k. BP_MASK follows the game over (GXInit again on the reset to the title), not battles.*
It adds the new invariants (tripwire lines and setup assertions) and writes `summary.json`. It counts battles by `stsicon.mld` loads, one per battle, not one per matching line.

*Done:*
- All 12 existing logs pass the invariants that decide failure: exit 0, no `[mmio!]`, 0 unknown bytes, 0 bad vertex refs, no stop lines, and the pad count.
- **Battle counts:** soakG 3 with game over at frame 20792, bsoak101 1, bsoak202 2, and soakD 1.
- **The other eight** (soakE, soakH, soakJ, soakL and bsoak303, 404, 505, 606) are reported "did not test what it says", not "pass".
- The BP_MASK line is raised as a question in the three part-G logs, noting that soakD's battle does not show it.
- The card check reports "not available" for these 12, which shared one `work.raw`.
- Each injected mutation fails: an `[mmio!]` line, 5 unknown bytes, a `[mem]` line, a missing `[gx]` line, and a wrong landing map.
- FINDINGS.md:1544 is corrected to three battles.

**S2. Guard suffixes and the stale TESTING lines** — *done 2026-09-24 (commit 468b3c2): six suffixes (`.raw .fifo .regs .ram .wav .png`), CI's regex matches, counts updated.*

*Done:*
- `guard.py` and `--history` pass.
- `test_guard` covers the new suffixes and the CI regex.
- Every copy of the test count is updated.

**S3. Dungeon soaks with the accelerator** — *done 2026-09-24: `soak.py --warp/--encounter-every/--pokes/--peeks`, `check --expect-reach/--frames`, `SOA_FRAMES_DIR`. `card-saved` accelerated fought 0 with every peek at 100000+; part G fought 5 against soakG's 3; every return to the field was lit. FINDINGS "S3 and M1".*
- Add `--warp NNNx` and `--encounter-every K`, which re-pokes 0x80346D28=100000 every K frames. At K=600 that is 50 pokes per 30k frames.
- A test asserts that 0x803473D4 appears nowhere in the generated pokes.
- Every job is judged by S1's checker, setup assertions included.

*Done:*
- `card-saved` at `a101b` with the accelerator fights 0 battles. This is a negative control: it shows the accelerator respects the story gates (flag 1025). It does not prove the check can fail, because an accelerator that did nothing would also give 0.
- Part G at `116a` fights more battles than the same seed without the accelerator. This is the run that shows the battle count can move.
- Every snapshot after a battle is non-black, or is raised as a question.

**S5. Dungeon reach matrix** — *a day plus a night.*
All 35 encounter maps at 3,000 frames each (about 70 minutes), then 30-minute accelerated soaks on the maps that reach. Every job asserts its setup.

*Done:*
- Every map has a row (reached, drew, encounter, fault) with its frame opened.
- The save-to-dungeon table is corrected from what actually ran.

**S6. An overnight runner** — *two days. **Owner:** sets up Task Scheduler and lends two nights.*
`tools/nightly.py`:
- runs one `soa.exe` at a time, with a lock and a refusal if one is already live;
- runs each job on its own card copy, with its own `SOA_FRAMES_DIR`;
- can resume;
- refuses a stale binary;
- records the exe SHA-256 and HEAD, and whether the machine was on mains;
- writes a report and a TSV with fps for each job and a diff against the previous night.

*Done:*
- A CI dry run against a fake port passes.
- A 3-job real run survives a kill and resumes.
- Over two consecutive nights, the second night's report shows only its diff from the first.

**S7a. `tools/partsel.py`** — *a day or less.*
- `pad <B..L>`, plus the `ME355A` warp pokes and the save request at frame 10000.
- `make-card` runs it from `card-saved.raw`, checks the landing map in the log, then runs `cardformat.py verify`.

*Done:*
- Pinned pads for C–L parse, stay at or under 1024 events, and match the ones that made the cards (`padL.txt` for L).
- On the owner's machine, rebuilding G lands `a230a` then `a116a`, and the card verifies READY.

**S7b. `tools/census.py` poke and table, and `tools/soa/png.py`** — *a day to several days.*

*Done:*
- The generated pokes are byte-identical to census 4's.
- Tests show the map words are never poked, ship mode never pokes the state word, and 257 pokes are refused.
- `table` over `census4.log` gets all 51 warp loads right from the log alone. Pixel statistics are tested on synthetic PNGs, because census 4's PNGs have been overwritten.

**S7c. `census.py maps`** — *a day.*

*Done:*
- `config/maps.tsv` holds ids and booleans only: 255 warpable maps, 66 of them 5xx, and 35 with encounter tables, matching `encounters.md` §4.
- The disc test skips in CI.

**S8. Census baseline** — *a day plus two hours of runs.*
Use the fixed recipe: from `card-saved`, with `sys[15]=0` and a 600-frame gap. Re-run the census-1–3 maps, which used older recipes.

*Done:* `config/census_baseline.tsv` exists, and its commit says how each outcome was checked. Every frame is opened, because this is a first bless.

**S9. `SOA_SPEED=3` equivalence** — *hours plus an hour of runs.*

*Done:* the same seeds at speeds 1 and 3 give the same map sequence, battles and invariants. If they do not, speed 3 is not adopted; if they do, it gives about 2.3× the throughput.

---

## C. Recommended sequence

**Ordering rules this sequence keeps.**
- S4a comes before H2 (a read tagged with a frame) and before M1 (the peek check).
- H5, the route (d) spike, runs alongside H4, so the week-1 decision knows whether (d) is a fallback.
- H6 fixes the capture set before H13–H16 measure anything.
- H10, the offline midpoint, comes before H15. H15's 61 ns target matters only for 60 fps, and H10 is the kill test for whether a midpoint looks right. H14, the drains, may come earlier if H1 shows play near 20 fps.
- H10's retention design comes before H16 moves vertex setup.
- H3 is protected by `title --check` plus replay, not by S1. H11 compares against H3's re-run of H1, because CPU seconds first appear in H3.
- M3, native DLLs, comes right after M1 and M2. M5, settings, comes before any enhancement is called player-usable.
- F6 carries M2's unlock test.
- If the guest thread is too slow, the answer is H13, not H12.

**After the first two weeks, in order.**
1. **Mods core:** M2 (one retranslation), then M3, M4 and M5.
2. **Renderer, offline first:**
   - H7, if H4 said so;
   - H10;
   - H11 and H12, which are cheap;
   - H14, if it has not already run;
   - H15a–d, each measured on H6;
   - H13a–c, before M11 or wherever H2 or H3 asks for them;
   - H16, after H10.
3. **Pacing and live interpolation:** H9 (**Owner**), H17a, H17b (**Owner**), then H18a–e.
4. **Enhancements:**
   - M6, M7a, M7b, M8 (**Owner**), M9, M10 (**Owner**);
   - M11, after H13;
   - M12's spikes whenever an evening is short;
   - M13, then M14 (**Owner**).
5. **Soak programme, runs at night:** S5, S6 (**Owner**), S7a–c, S8 and S9.
6. **Track F, only when a mod needs a function changed inside:** F4, F5, F6, F7.

**The first two weeks of evenings.**

| Evening | Slice | Why now |
|---|---|---|
| 1 | **H1** | No build. It turns every speed claim from inference into measurement, and each run proves it reached its map. |
| 2 | **S4a** | The first `--link`. H2 and M1 both need a read tied to a frame. Its checks are the self test, `title --check` and replay 23/23. |
| 3 | **H2** | No build after S4a. It proves the logic is per frame by timing a fade in fields, and rules out simply uncapping. |
| 4–5 | **H4**, **H5** | H4 is the kill experiment for interpolation. H5 (route d) runs alongside so the decision below knows the fallback. |
| 6 | **H6**, **S2** | H6's set is captured in the same runs as H4's pairs. S2 is hours. |
| 7 | **S1** | Python only. It is what judges S3's soaks. |
| 8 | **H3** | Percentiles and CPU seconds. H1's Part L is re-run for H11's baseline. Checks: `title --check` and replay. |
| 9–10 | **S3** | Option 3: accelerated dungeon soaks, run overnight. M1's *Done* reuses the accelerator. |
| 11–13 | **M1** | The loader for data patches. Its *Done* uses S3's accelerator and S4a's peek. |
| 14 | **H8** (**Owner**) | The one windowed session: today's rate, the old presenter against the new, and the VI drift H9 needs. |

**Decision points, once H1, H2, H4 and H5 are in (end of week 1):**
- **H4 under about 90%:** H7 comes before H10. If H7 might fail too, H5's verdict says whether route (d) is a real fallback.
- **H1 shows every-frame field play at 30 already:** H14 and H15 move behind H10.
- **H1 shows it near 20 fps:** H14, the drains, opens week 3, measured on H6's set.
- **H2's steps stay at 2 or more when uncapped in snapshot mode:** the guest thread alone cannot finish a frame in one field. H13 comes before M11, and M2's "about 60 a second" is checked in light scenes only until H13 lands. H12 would not help, because it speeds drawn frames only.
- **H2's fade takes as many fields uncapped as capped:** the logic is not per frame. Uncapping becomes the 60 fps route, and this plan is redone.

**The first three slices to do next: H1, S4a, H2.**
- H1 needs no build.
- S4a is a few hours of `--link` work.
- H2 then needs no build.

Together they answer two questions before anything larger is built: what drawing every frame costs on this machine, and whether the game's logic really is per frame, which decides whether interpolated 60 fps is the right route at all. The owner is needed once in the first two weeks, for a windowed session of about 15 minutes (H8), which can be combined with a playtest from a save.
