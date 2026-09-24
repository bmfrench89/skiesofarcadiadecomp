<!-- Written 2026-09-24 by a read-only research agent for docs/PLAN-60FPS-MODS.md; nothing was
run. [V]/V marks what was read from quoted instructions, file:line or logs; [I]/I is inference. -->

# Running Skies of Arcadia at 60 fps: what the code shows

The game caps itself at 30 fps with an immediate constant in its frame-end function. All game logic advances once per game frame, and no delta-time or fields-per-frame variable exists. Removing the cap would therefore run the whole game at double speed.

The feasible route is to interpolate in the renderer: the game keeps running at 30, and the port generates an in-between image from two consecutive frames' draws. It is feasible because the port already holds every draw's transformed vertices, and because nothing the game itself does has to change.

Addresses below use r13 = 0x8034E720. **V** means verified (the instruction, file:line or log line is quoted). **I** means inferred.

## 1. How the game caps itself (V)

`main` is at 0x801DCB28, and its loop runs from 0x801DCB84 to 0x801DCD74:
- `801DCB84 bl fn_8023F704` is VIGetRetraceCount (`lwz r3,-27836(r13)` = retraceCount at 0x80347A64). `801DCB88 stw r3,-28820(r13)` stores the frame-start field count at **0x8034768C**.
- The loop calls the scene dispatcher fn_801DC288 once (`801DCCB8`). It uses a jump table at 0x802F6660, indexed by the scene id at 0x803475CC; scene 6 is the field. It then calls the draw pass fn_801D0F80(1) (`801DCCC0`), and last the frame end `801DCD68 bl fn_801DC420`.
- fn_801DC420, the frame end:
  - `801DC484 bl fn_8024F194`: GXCopyDisp(xfb at 0x803476AC, clear=1). It builds `oris 0x4B00` and `ori 0x4000`/`oris 0x5200`, which is the BP 0x52 copy to the XFB.
  - `801DC488 bl fn_801D22CC`: draw sync on token 0xB00B. If 2 or more fields pass while it waits, the game treats the GPU as hung and resets the FIFO. The field counter at 0x80347600 is bumped by the pre-retrace callback fn_801D1DE0.
  - The cap itself:
    ```
    801DC490 addi r3,r0,0 ; bl fn_801C6248   (services async file reads)
    801DC498 bl fn_8023F704                   (VIGetRetraceCount)
    801DC49C lwz r0,-28820(r13)
    801DC4A0 subf r0,r0,r3
    801DC4A4 cmpli cr0,r0,1
    801DC4A8 bc 12,0 -> 801DC490              (spin until 1 field since frame start)
    ```
  - Then `801DC4CC` VISetNextFrameBuffer (fn_8023F614), `801DC4D0` VIFlush (fn_8023F4E4), and `801DC4D8` VIWaitForRetrace. VIWaitForRetrace (fn_8023E460) calls OSSleepThread on queue 0x80347A6C until retraceCount changes. The XFB then flips (`801DC4DC-801DC4F0`).
- **What this gives:** the frame needs at least one field since it started, and then waits for the next field. That is 2 fields, or 30 fps, for any work up to 2 fields; work past 2 fields costs 3 fields (20 fps). **The "N" is the immediate 1 at 0x801DC4A4, not a variable.**
- The disc-error loop fn_801D150C (`801D1560`) and the reset path fn_801DC504 use the same frame end.
- Measured: every saved `run_*.log` shows 2.01 to 2.10 retraces per frame at SOA_SPEED=1. For example, run_bsoak101 has "33500 game frames, 67570 VI retraces (2.02 per frame)" and run_ships1 has 2.10.

## 2. Game logic runs once per game frame (V, by listing every clock read in game code)

**No catch-up and no delta.**
- The dispatcher is called exactly once per loop iteration.
- 0x8034768C has two references: the store at 801DCB88 and the load at 801DC49C.
- retraceCount is read only inside the VI library. VIGetRetraceCount is called only at 801DCB84, 801DC498, in OS reset code (0x802344AC to 0x80234B00) and once at init (80297150).
- The only `mftb` instructions are in OS Reset, OSGetTime/OSGetTick and TRK; there is none inline in game code.

**Every game read of a clock, by use:**
- **Random seeds:** OSGetTick into fn_8025ECBC (srand) at 8000A1CC, 8000A1D4 and 801012AC.
- **Memory-card operation timeout:** 801D6D48 and 801D709C (0x80311C40).
- **Title attract timeout:** 80228FB4 and nearby compare elapsed milliseconds with `0x0001686B` (92,267 ms).
- **Debug meters nothing reads:** 0x803475B8 is stored at 801DC478; 0x80347F04 and 0x80347F08 are stored at 80296F6C and 80296F48.
- **Save timestamp:** OSGetTime at 800073D4, into calendar time.
- **Play time:** a 1 Hz periodic OSAlarm (set at 802289FC). Its handler fn_80228948 increments play time at 0x803474A0 in scenes 6 and 7.

**Per-frame steps, sampled:**
- **Fade task** fn_801CBA98, registered at 801CBCD0. The level at 0x80347510 moves by 1.0/(duration−1) per call (`fdivs`, then `fadds`/`fsubs`). The duration at 0x80347514 is in frames, and the default is 30.0 (r2−17180 = 0x41F00000). The setters fn_801CBB9C and fn_801CBBAC take the duration in frames.
- **Script WAIT** (opcode 16, handler fn_801F570C): the target is at 0x803477A8, and the counter at 0x803477AC steps by `addi r3,r3,1` per tick.
- **Frame counter** at 0x803475C0 advances by 1 per dispatcher call (801DC390).

**Movement, animation, camera and battle (I):** I did not trace these individually. None of them can be time-scaled, because the list above is every clock the game code reads.

**Consequence:** presenting more than one frame per two fields makes all game logic run faster in proportion. Music would not speed up (I), because it is paced by the AI DMA, which runs off the timebase.

## 3. The four approaches

**(a) Unlock the cap.** One word does it: set 0x8034768C to 0 before 801DC49C, and the pre-wait is skipped, so a frame takes one field.
- The existing `SOA_POKE` can do this with no rebuild. The copy at 801DC484 raises BP 0x52 synchronously: every gather-pipe store parses immediately (`gx.c:411-424`), and gx.c:274 calls `frame_end`, which calls the poke hook at gx.c:148. That all happens before the check.
- As a play mode it is wrong: everything runs at 2x. Its value is as an experiment that measures throughput.

**(b) A delta variable set to half.** It does not exist (section 2). Building one means patching every per-frame integrator in code and in data (script WAITs, fade durations, motion data), with no semantics recovered. Not feasible.

**(c) Interpolation in the renderer. Rank 1.**
- What the renderer already holds:
  - `gxr_draw_inner` (gxr.c:1517-1603) decodes and transforms on the producer thread into a DrawCmd holding clip-space `x,y,z,w` per vertex (gxr.h:17-24). The DrawCmd also carries fully resolved TEV, texture, pixel and raster state (gxr.c:738-763).
  - `to_screen` projects inside the worker (gxr.c:842-848).
  - So an in-between image is frame N+1's DrawCmds re-issued with each matched vertex's `x,y,z,w` interpolated linearly from frame N.
- Keys for matching draws: the display-list address (known at gx.c:347), CP array bases, texture addresses, primitive, count, and a hash of the TEV setup.
- What would have to change:
  - Keep a copy of each frame's vertices. The arena is recycled on every drain (`g_arena_used = 0` at gxr.c:1506, 1601, 2011 and 2053).
  - Pin textures for two frames. They are currently freed through the graveyard.
  - Use a second EFB, or save and restore it. `g_efb` and `g_efb_z` are single globals (gxr.h:120-121).
  - In the in-between pass, skip copies to texture, because they write guest MEM1. Also skip `g_frames_presented`, the frame counter and the hash.
  - Add a paced presenter (section 4).
- Latency: one extra field (about 16.7 ms), not a whole frame (I). The in-between image goes up at field k+1 and the real N+1 at k+2.
- The guest is untouched, so the pinned hashes, the scenarios and the recordings all stay valid.
- Cost: an MVP is 1 to 2 weeks (I), followed by a long tail of scene problems: particles, reordered alpha, UI, camera cuts.
- Rasterizing twice is cheap on average (the A4 profile: workers busy 8.8 s of 830 s, PLAN.md:221-223). But PLAN C4 (PLAN.md:502-512) says the opening in `boot_window.log`, at 862.5M fragments, is bound by fragments, so heavy scenes are at risk.
- A robustness upgrade: add `hooks.txt` hooks at the game's object-draw routine to tag each draw with its object pointer. This is the same idea as Zelda64Recomp tagging matrices for RT64, which I know from outside this repo.

**(d) Logic at 30, camera at 60, by patching the game. Rank 2, and far behind.**
- fn_801D0F80 only replays per-layer "NGDL" display lists. It checks the magic 0x4E47444C (802A8AFC-802A8B04), reads the list heads at 0x80308CB8 to 0x80308CDC, calls fn_80251F1C (I read it as GXCallDisplayList) and zeroes each list at 801D0FF0.
- The geometry is therefore recorded earlier in the frame, and I infer the matrices are baked into it (not verified). Moving only the camera would mean re-running whatever records the lists, which means decompiling the game's scene and task system.
- That is weeks, and depends on Track F. It also smooths only the camera, not animation.

**Final ranking:** (c), then (d), then (a) as an experiment only; (b) is not possible.

## 4. What paces frames in the runtime today (V)

- **Guest time** is the host wall clock (`timespec_get`) multiplied by `SOA_SPEED` (hle.c:269-283). SOA_SPEED is a throughput knob: it scales logic, audio and the device models together, so it never produces 60 fps.
- **The VI retrace** is delivered once 1/60 s of guest time has passed (irq.c:80 and 381-389). Missed periods are dropped rather than queued (`g_vi_last = now`, irq.c:384). Delivery happens only at the SelectThread idle hook (irq.c:437, `hooks.txt` 0x80237BA8) or on every 16th backward branch while interrupts are enabled (irq.c:448-453).
- **Nothing sleeps while waiting:** `SOA_PACE` only does `Sleep(0)` (irq.c:431). The run_bsoak101 profile is 48.6% SelectThread, 24.6% fn_8023F704 and 10.6% fn_801C6248, so 83.8% of wall time is spent spinning in the game's two waits. That run skipped rasterizing most frames (SOA_SNAP=1000).
  - The old `boot_perf.log` rendered every frame and was about 73% waiting. That implies about 9.5 ms of busy time per frame on the guest thread (I).
- **Presentation:** `run_copy` bumps `g_frames_presented` when the screen copy is rasterized (gxr.c:1825), which is at copy time, not at the retrace. `window.c` polls every 8 ms or less (`MsgWaitForMultipleObjects(...,8,...)`, window.c:145-147) and draws with GDI `StretchDIBits` (window.c:75). There is no vsync, and nothing ties presentation to either the guest's retrace or the monitor. The only recorded windowed rate is 26.7 fps (PLAN.md:34, `boot_window.log`).
- **What would have to change:**
  - For (c): a vsync'd flip-model presenter that shows each real frame for exactly two refreshes and slots the in-between image into the first one. Optionally, drive the guest's retrace from the host's vblank so the two 60 Hz clocks do not drift against each other; that interacts with D4.
  - Also for (c): an idle-sleep until the next device deadline, so the spinning guest thread stops competing with the extra rasterizing.
  - For (a): nothing in the runtime.

## 5. First experiments

All of these launch the game, so none was run here. Play on a copy of a save.

1. **Baseline, no rebuild.** Run with `SOA_WATCH=0x8034768C` in a field. Consecutive stored values should step by 2, occasionally 3. If they do not, the anchor is wrong.
2. **Prove or kill (a), and show logic is per frame. No rebuild.**
   - Set `SOA_POKE` to 256 items of `F+i:0x8034768C=0` (the cap is 256 items, one-shot each, main.c:708 and 774-775). Start a fade (30-frame default) or a scripted WAIT inside that window.
   - Prediction: the value each poke reports replacing steps by 1, the `[run]` retrace total drops by about 256, and the fade finishes in half the fields.
   - If the steps stay at 2 or more, the guest cannot finish a frame in one field, and throughput is the limit.
   - For a sustained measurement: a `--link`-only switch that makes `poke_at_frame` write 0 every frame (`SOA_UNCAP`). Run it rendering every frame (no SOA_SNAP), windowed, in the opening, a battle and a ship battle. It gives the ceiling for 60 images a second.
3. **Can draws be matched for (c)? Offline.**
   - Capture consecutive pairs with `SOA_FIFO_DUMP=F,F+1` and `SOA_FIFO_DIR=build/fifo-pairs`. It must never be `build/fifo`.
   - Take pairs in a field, a battle, a ship battle and a cutscene.
   - Report: share of draws matched, weighted by pixels; share with equal vertex counts; a histogram of displacement; draws whose order changed.
   - Kill criterion: under about 90% of pixels coming from matched draws means game-side tags (hooks) are needed first.
4. **Does a midpoint look right for (c)?** Extend `--replay` to render the midpoint of a captured pair to a PNG. Unmatched draws come from F+1, and copies to texture are skipped. Open the PNG, per CLAUDE.md. The pinned hashes must not move.
5. **Presenter (needed by (c)).** Build a vsync'd presenter showing each real frame for exactly two refreshes, and compare the spread of frame times with today's 8 ms poll. On its own this makes 30 fps look smoother.
6. **Scope (d).** Run with `SOA_WATCH=0x80308CBC` (the first layer's list head) and read the storing lr and backtraces to see who records the lists. Add a gx.c counter of draws inside versus outside display lists. If the lists are recorded inside the scene's update tasks, drop (d).
