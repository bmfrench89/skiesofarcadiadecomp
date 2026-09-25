<!-- Written 2026-09-25 by the planning session, read-only, at main 24d9235, and reviewed the same day at
main 012164a: a consistency check across this file and the four specs and against the repository, whose
fixes the specs' review logs list. Between the two, C5a (750cef0), P6b (79c9ad8), manifest 2's second
follow-up (b1199b3) and T0c (012164a) landed. Committed as dc0cc98; then updated at 1a09d4a after P1a
(090eea6) and the A5/B3 edits (1a09d4a) landed. Path in the repository: docs/PLAN-NEXT.md, the name docs/specs/now.md gives
it. It sequences four reviewed specs -- specs/comfort-pack.md, specs/disc-layer.md, specs/portability.md
and specs/gpu-backend.md, each revised after two reviews -- with the slices the committed plans already
hold, and with the implementation session's input of 2026-09-25 (it stopped at 574c683) and its facts
from later that day. Nothing here was run. [V] = read at a commit, file:line or in a FINDINGS entry named
here; [I] = inferred. Sizes are evenings: hours / a day / several days / week-plus / months. Rebuild
cost: none / --link / one retranslation. Owner marks a place where the owner must look, play or decide.
Record what a slice's run shows in docs/FINDINGS.md, and mark it done in the document that specifies it
and in this file's tables, in the same commit. -->

# What is next: the order after the pivot

**For the owner.** This page is the one place that says what happens next and in what order. The
other plans keep the details of each piece; this one only sequences them. On 2026-09-25 you asked for
a pivot and told the implementation session to go with the planning session's best recommendation. This
is that recommendation: finish the renderer step then in progress, then the comfort mods, then running
from your own disc, then groundwork for other platforms, then a decision on a GPU renderer, with 60 fps
interpolation after the comfort mods. D-1 asks you to confirm it. That renderer step is finished: at 574c683 the heaviest field
scene measured runs at the game's own 30 fps with every frame drawn, on a quiet machine [V, HANDOFF,
FINDINGS "Copy images", "Neighbour fences"]. The rest of the CPU renderer's speed work waits for the GPU
decision; 60 fps does not.

In order, with honest sizes [I, sums of the specs' own slice sizes]:

1. **The comfort pack** (about 4 weeks of evenings: 3.5 for the comfort slices,
   [specs/comfort-pack.md](specs/comfort-pack.md) §5, plus the gap fillers): fewer or no random
   battles, dialogue that advances itself, rumble, fullscreen, gamepad shortcuts, a clock that survives
   sleep, a double-click start, Dolphin saves, couch co-op, picture options, battle turbo.
2. **The picture right, then 60 fps** (3 to 4 weeks): fix a missing effect, probably character
   shadows, that the port has never drawn (C5). Its first check, C5a, ran at the start of step 1 and
   confirmed the cause (750cef0): the port draws the game's recorded draw lists at the wrong moment.
   Then 60 images a second by interpolation, first headless, then in a window.
3. **Your own disc, one copy** (about 1 week, plus the first 1.42 GB back during step 1): run straight
   from your own ISO, with a wrong disc refused by name.
4. **Portability groundwork** (2 to 3 weeks): a second compiler, CI on Linux and ARM, the render queue
   proved correct on any processor, and a Wine answer for the Steam Deck. The part that only matters
   once the port leaves Windows (M4b) waits until after the GPU decision.
5. **The GPU experiment and your decision** (3 to 4 weeks): an offline GPU renderer judged against
   the CPU one by a checker that is proven able to fail, and then your choice.

That is **about three to four months of evenings to the GPU decision**. If that answer matters sooner,
the experiment can follow step 2 directly (D-10 below).

**You are needed for these, batched into as few sittings as possible (section C8):**
- **One decision sitting now,** about 30 to 45 minutes of reading and answering. The main questions:
  which handheld you have and what refresh rate you play at, whether Android is a real goal, and whether
  `soa.exe` may hold your copy of the game's executable. Every other question has a default that
  applies if you say nothing (section D6).
- **Two play sessions on the handheld during step 1,** each about an hour. Several things already built
  are waiting for these checks (H8's presenter, M5's settings file).
- **In step 2,** a 20-minute look at re-captured frames, and a 30-minute windowed session at 60 fps.
- **The gate:** four side-by-side pictures and one decision.

**Two things to know before you start.** Your owner sessions use the same machine the implementation
session runs the game on, so nothing automated runs while you play. And the implementation session
cannot measure speed while you use the machine for anything heavy.

---

## A. The stopping point, recorded

### A1. Where the renderer stopped, and what has landed since

**Stopping point: 574c683** ("FINDINGS: H15d paused, with the 8-thread figures"). Nothing was in flight
[V, the implementation session's input of 2026-09-25]. What stood there:

- **30 fps reached.** The Dangral base runs at 29.8 fps drawn every frame on a quiet machine
  (HANDOFF, "State").
- **The guest has room.** The guest thread alone runs that scene at about 125 images a second, four
  times the cap (FINDINGS "H13, first steps").
- **The pixel path.** Field captures meet the 61 ns per fragment budget at 8 threads on a quiet
  machine; ship and sky scenes are 1.3 to 1.6 times short (FINDINGS "H15d paused").

**Landed since, in order** [V, `git log`]:

| Commit | What | Plan id |
|---|---|---|
| cb469d6 | The pivot: `docs/specs/now.md`; PLAN-60FPS-MODS status lines for H13, H15d, H16, H17a | now.md N1 |
| 3949028, b071949 | Manifest 2: a mod's id and version, `api` as a minimum, one API constant | N2 = MV2 |
| 1c7b780, 4041dfc | T0: 43 suffixes, 18 directories, the signature check over the whole tree; the 64-row table rule dropped, the mod-folder UTF-8 rule kept | N3 = T0 |
| c8274db | Acquire loads at every cross-thread read in the render queue | N4 = portability L0 |
| b911380 | P11's spike: the message window's state word, read in a run | N6's spike |
| 24d9235 | P6: the race seed pinned, and game-changing settings recorded | N5's P6 half |
| 750cef0 | C5a: recorded display lists confirmed; the port runs them at recording | gpu-backend C5a (PLAN C5a) |
| 79c9ad8 | P6 follow-up: each pin logged, the reload after a battle, the seed in effect | comfort P6b |
| b1199b3 | Manifest 2 follow-up: mods past the recording line keyed by id, not folder | MV2 |
| 012164a | T0c: card images and saves under any name, and history read for content | comfort T0c |

**P6 landed without the comfort spec's three additions** [V, `git show 24d9235`]. These were:
- no `[seed] pin:` line;
- `main.c`'s `extra[320]` unchanged;
- no log check in `test_seed.py`.

They became **P6b** ([specs/comfort-pack.md](specs/comfort-pack.md) 3.3 and its P6b slice), which
landed as 79c9ad8. Its run went to frame 13,500 and found the field loads after the battle that P6's
run, stopped at 12,000, could not see (FINDINGS "P6, followed up").

**The implementation session's order was C5a, then P6b, then P1a** (C1 says why C5a went first). C5a
and P6b have landed, and so have T0c and a manifest 2 follow-up, taken in between.

**Landed after dc0cc98:** **P1a** (090eea6), with its accessory case as a self-test case
(specs/comfort-pack.md P1a), and the A5 and B3 edits (1a09d4a). **In flight at 1a09d4a:** P11 in its
live checks, M18 written, and I2 being built in a separate worktree. Since then P11 (664f005), M18
(3d08479, but for the owner's check) and I2 (12077d1, but for the owner's prune) have landed, then
CH1 (d1000af), P11b (4c698f5) and H19a (63661a0), then M5b (9642613) and M19 (fe7e48f). CH1, H19a,
M5b and M19 wait only for the owner's checks, so **owner session A is ready** (C8). P3 is being built in a
worktree; P10a, then P5a, P5b and M11a, are next.

### A2. H13 is closed as "done enough"

**Done.** Two first steps landed in 042c6b1 and together took the Dangral guest ceiling from 114 to 125
images a second (FINDINGS "H13, first steps"):
- **H13a:** `psq` loads and stores without `ldexp`;
- **H13b:** the data-cache range calls bound as no-ops.

**Not done:**
- `fma` inline;
- `PSMTXConcat` native: it is not in the profile's top rows;
- **H13c,** the FIFO parse on its own thread. It is about 5% of the guest thread and breaks the
  synchronous frame end unless drained at the XFB copy.

**What reopens them.** Only a measured shortfall of the guest thread, in either of these cases:
- **(a) Turbo.** M11a's first step (specs/comfort-pack.md 3.14) measures the battle and world-map guest
  ceilings: H3's uncapped `[frametime]` in snapshot mode. It reopens H13 if either is under 60 images
  a second at p95.
- **(b) Interpolation.** H17a or H17b finds a scene where the guest thread, not the workers, misses
  the in-between budget. The guest thread's time per real frame, as H13 defines it (wall × (1 −
  `SelectThread` − the two spins)), plus building the in-between stream, is above 33.3 ms at p95,
  while worker busy time per real frame is below it.

**The rules once reopened:**
- Either measurement is taken interleaved against a saved base exe.
- The profile names which of the three pays before any is built: the `fma` rows, `PSMTXConcat`'s
  share, or the parse's 0.3 to 3.2 ms.
- `fma` inline then goes through portability L5's single `SOA_FMA` macro.
- `/arch:AVX2` needs decision D-21 (the CPU floor).

### A3. H15d and H16 wait for the GPU gate

**The state they stop in:**
- **H15d** is paused after its first step: per-pixel counters out of TLS, and the bilinear blend in
  SSE4.1. It is 7% faster at one thread and no faster at 8 (b377b1f, ff3a2c1; FINDINGS "H15d
  paused"). The next step would be the TEV's general path for the sky and ship scenes.
- **H16** (vertex setup onto the workers) never started. The producer is not the bottleneck today
  (FINDINGS "Copy images").

**Both return only on one of these, decided at gate G1 (section D1):**
- **The gate answers C or D** (no GPU backend, now or ever). H15d resumes at the TEV's general path,
  then H16. The gap FINDINGS recorded (ship and sky 1.3 to 1.6 times short) is re-measured first,
  because the corpus will have changed at C5c.
- **The gate answers A or B, but the CPU renderer, kept as reference and fallback, is too slow on a
  target you name at the gate** (for example the Z1 Extreme on battery, or a Deck under Proton).
  Proposed here, fixed at the gate:
  - the Dangral base drawn every frame under 30 fps at p50 on that target; or
  - H17b repeating more than a quarter of its in-between images in field scenes.
- **H16 alone** also returns if H17a's measurement finds the guest thread short (A2 (b)) and vertex
  setup is its largest share.

### A4. H17 is not blocked; H18 follows it

Interpolation happens on the guest thread, before any drawing:
1. match the draws of two frames;
2. interpolate their positions;
3. build a second command stream.

So it works whatever draws the commands. Both specs and the implementation session agree
(specs/gpu-backend.md 3.13; now.md). The order is:

- **H17a after the comfort pack,** and after C5b, since C5a confirmed the display-list finding (750cef0).
  C5 moves draws into display lists whose addresses are part of H10's pair key, so the match rates are
  re-measured first (C5b's Done).
- **Design H17a at the level of `DrawCmd`.** Its real work is a second EFB: `g_efb` and `g_efb_z` are
  globals that every pixel function indexes. H17a adopts specs/gpu-backend.md 3.1's routing now:
  - `uint8_t efb` in `DrawCmd`, set by `claim_slot` from a `g_target` that only the guest thread sets;
  - the CPU workers take a per-command EFB pointer.

  V2 later moves the struct into `gxr_cmd.h` without redoing it, and V12 draws the same commands on
  a GPU. H10's pair machinery (`pair_claim`, `pair_positions`, the rotation) is the core it reuses.
- **Then H17b** (live, with you at the window).
- **Then H18,** one artifact class at a time, only for the classes on your H17b list.

**One reading to confirm.** cb469d6's status lines put H18 with the deferred speed work ("deferred ...
with H16 and H18"). This plan follows the implementation session's reading: H18 follows H17b wherever
H17 goes. Its fixes (particles, reordered alpha, HUD, cuts, texture copies) are matching and fallback
rules on the guest thread, so the GPU decision does not change them. The status edits below make the
two lines agree. If you meant otherwise, say so at the first sitting (D-24).

### A5. The status edits `docs/PLAN-60FPS-MODS.md` needed

**Done, 1a09d4a.** cb469d6 made the H13, H15d, H16 and H17a edits, and 1a09d4a made the rest, listed
here as they were proposed. Each was a one-line change. Line numbers are at 012164a (this file has not
changed since 24d9235).

| Line | Today | Change to |
|---|---|---|
| after :9 | (nothing) | "**Order:** `docs/PLAN-NEXT.md` says what is next across all plans; this file keeps the H, M, F4+ and S slices." |
| :13 | "one decision: whether to reopen the GPU backend once the pixel-path work (H15d) reports how far it lands from 61 ns per fragment;" | "one decision: the GPU backend, taken at PLAN-NEXT's gate G1 after a three-to-four-week spike (`docs/specs/gpu-backend.md`);" |
| :64 | "... which PLAN parks under 'Not worth doing, or not yet'. Reopen it on H15's numbers." | "... reopened 2026-09-25 as a spike with a decision gate (`docs/specs/gpu-backend.md`; PLAN-NEXT M5, G1)." |
| :248 (H8) | "**Owner:** set 60 or 120 Hz, then the windowed session and the verdict." | append: "Batched into PLAN-NEXT's owner session A; the display's rate is decision G4." |
| :261 (H9) | "*several days, `--link`. **Owner:** one windowed session.*" | append: "*Deferred 2026-09-25: reopens if owner session A or D shows judder at 60 or 120 Hz. Its :270-271 Done lines are to be restated first (PLAN-GAMEPLAY-MODS F).*" |
| :283 (H11) | "The guest idle loop's half remains." | "The guest idle loop's half remains, unscheduled: it reopens when H20's power line shows its cost on battery, or with M19, which rewrites the clock that loop would sleep against." |
| :322 (H13c) | "*several days, `--link`.*" | "*several days, `--link`. Not started; closed with H13 as done enough, and reopened only under H13's condition (PLAN-NEXT A2).*" |
| :353 (H15c) | "... The sampler is next. FINDINGS "H15c"." | "... Done 2026-09-25: the sampler stage was subsumed (FINDINGS to say by what). FINDINGS "H15c"." |
| :357 (H15d) | "... deferred to that decision with H16 and H18." | "... deferred to the GPU gate (PLAN-NEXT G1) with H16; it returns under PLAN-NEXT A3's condition." |
| :363 (H16) | "... with H15d's rest and H18: ..." | "... with H15d's rest (H18 follows H17b instead): ... It returns under PLAN-NEXT A3's condition." |
| :371 (H17a) | "Ordered after milestone 1 of `docs/PLAN-GAMEPLAY-MODS.md` ... Its Done lines are to be restated ..." | "Ordered after the comfort pack and C5b (PLAN-NEXT M2). Commands reach their EFB through `DrawCmd.efb`, set in `claim_slot` (specs/gpu-backend.md 3.1). Its Done is restated per PLAN-GAMEPLAY-MODS F before it starts." |
| :380-381 (H17a Done) | "`SOA_HASH` lines identical to before"; "the real frames' `SOA_HASH` lines are still identical" | PLAN-GAMEPLAY-MODS.md:1405-1407's wording: **off**, replay and `title --check`; **on**, a same-run contrast of each real frame's `g_screen` hash before and after its in-between pass, with the mutation |
| :383 (H17b) | "**Owner:** judges it in a window." | append: "Owner session D (PLAN-NEXT); needs the display at 60 or 120 Hz (G4)." |
| :395 (H18) | "*a day to several days each.*" | "*a day to several days each. Follows H17b wherever H17 goes: its fixes are on the guest thread, so the GPU gate does not hold it. Only the classes on the owner's H17b list are built (PLAN-NEXT M2).*" |
| :520 (M5) | "**Owner:** turn one on and off without a terminal." | append: "Batched into owner session A (PLAN-NEXT)." |
| :567 (M8) | "*a day to several days, `--link`. **Owner:** ...*" | append: "*Scheduled with M7a/b as the first slices after the GPU gate (PLAN-NEXT, after M5), per PLAN-GAMEPLAY-MODS F.*" |
| :601 (M11) | "*hours, `--link`. After M2 and H13.*" | "*Split 2026-09-25: M11a (turbo up to 2×) is in the comfort pack (`docs/specs/comfort-pack.md`); M11b (past 2×) waits for M19 and S9.*" |
| :602 | "reusing the skip at `gxr.c:1534`" | "a skip in `gxr_draw_inner`; copies are not skipped, so it is specified only if M11a's measurement asks for it (comfort-pack 3.14)" |
| :607 | "The audio report is unchanged." | the one-run audio-rate check (PLAN-GAMEPLAY-MODS F, M11 entry). :270 (H9) needs the same change before H9 starts; :479 (M2) is done and stays as history |
| :721 | "The RNG is reseeded from `OSGetTick` on every map load" | "... on every map load and twice at every battle start (0x8000A1D0, 0x8000A1D8; P6, 24d9235)" |
| :847 (§C) | "## C. Recommended sequence" | add a first line: "*Superseded for order on 2026-09-25 by `docs/PLAN-NEXT.md`. The ordering rules below still hold.*" |

---

## B. The plan of record

### B1. One place says what is next

**This file owns the order.** It says:
- which slice comes next;
- which milestone each slice belongs to;
- where the owner is needed;
- which decisions gate what.

**It does not restate designs.** A slice's text lives in exactly one of the documents below.

| Document | What it owns now | Status |
|---|---|---|
| `docs/PLAN.md` | Ground truth (the status table at its top) and tracks A to G, including the proposed C5a-C5c and G3-G7 | Current; its "next phase" pointer moves here (B3) |
| `docs/PLAN-60FPS-MODS.md` | Tracks H (speed and pacing), M (mod framework), F4+ and S | Current; its §C order is superseded by this file |
| `docs/PLAN-GAMEPLAY-MODS.md` | Tracks P, K, T, R, N and X, rules 1 to 8, section F's proposals, questions Q1-Q11 | Current; milestone 1 is now specified by specs/comfort-pack.md, and T1 by specs/disc-layer.md |
| [specs/comfort-pack.md](specs/comfort-pack.md) | Implementation-ready milestone 1: P1a/b, P3, P5a/b, P6b, P10a/b, P11, P11b, M18, M19, M5b, CH1, H19a, M11a, T0c | Reviewed twice, then checked with this file |
| [specs/disc-layer.md](specs/disc-layer.md) | I1 to I8; T1 is I6-I8 | Reviewed twice, then checked with this file |
| [specs/portability.md](specs/portability.md) | L0 (done) to L12 | Reviewed twice, then checked with this file |
| [specs/gpu-backend.md](specs/gpu-backend.md) | C5a-C5c (proposed for PLAN.md Track C), V0 to V12, and the gate | Reviewed twice, then checked with this file |
| [specs/now.md](specs/now.md) | The first rows after the pivot | **Superseded**: every row has landed or is replaced (B3) |
| `docs/ROADMAP.md`, `HANDOFF.md`, `docs/FINDINGS.md` | What is done, what is known, what was tried | Unchanged in role |

### B2. When documents disagree

- **About what the code does:** the code wins, and the document is fixed in the commit that finds the
  difference.
- **About a slice's design:** the reviewed spec wins over the older plan text. The specs were
  re-verified against b071949 and corrected the plans in several places:
  - P11's address;
  - M11's frame skip;
  - M5's path rule;
  - T0's table limit.
- **About the order:** this file wins.
- **When a slice lands,** its commit marks it done in the document that specifies it and in this
  file's milestone table, and fixes every copy of any count it moved (CLAUDE.md, "Counts in prose
  rot").

### B3. Pointer edits the other documents needed

**Done, 1a09d4a** (and dc0cc98 for PLAN-GAMEPLAY-MODS's own lines). Listed here as they were proposed. Line numbers are at 012164a.

**Landing the specs.** One docs-only commit adds:
- `docs/specs/comfort-pack.md`, `docs/specs/disc-layer.md`, `docs/specs/portability.md` and
  `docs/specs/gpu-backend.md`;
- this file as `docs/PLAN-NEXT.md`.

**`docs/specs/now.md`**, a line under its title:
> *Superseded 2026-09-25 by `docs/PLAN-NEXT.md`. N1-N4 landed (cb469d6; 3949028, b071949; 1c7b780,
> 4041dfc; c8274db). N5's P6 landed as 24d9235 and its remainder, comfort-pack P6b, as 79c9ad8; its P1 is
> comfort-pack P1a/P1b. N6 is comfort-pack P11 (spike b911380), with hold-to-skip as P11b.*

**`docs/PLAN.md`:**

| Line | Change |
|---|---|
| :54-60 | "The next phase has its own plan: PLAN-60FPS-MODS.md ..." becomes: "**What is next, in order: [PLAN-NEXT.md](PLAN-NEXT.md).** The slices' text lives in PLAN-60FPS-MODS.md (H, M, F4+, S), PLAN-GAMEPLAY-MODS.md (P, K, T, R, N, X) and `docs/specs/`." |
| after :535 (end of C4) | Add "**C5a-C5c. Recorded display lists** -- *proposed 2026-09-25 in `docs/specs/gpu-backend.md` §6, re-reading FINDINGS H4's zero-size calls; scheduled in PLAN-NEXT M1 (C5a) and M2 (C5b, C5c).*" |
| after :896 (Track G intro) | Add "G3-G7 are proposed in PLAN-GAMEPLAY-MODS.md section F. G5's DOL line is disc-layer I3's stale-link guard, and G4's compiler half is portability L3a/L3b." |
| :954-958 | "A GPU backend ..." gains: "*Reopened 2026-09-25 as a three-to-four-week spike ending in the owner's decision: `docs/specs/gpu-backend.md`, PLAN-NEXT M5 and gate G1.*" |
| :17, :81 | "all 22 `runtime/*.c`": the runtime has 26 C files with `seed.c` [V, specs/portability.md 2.7]. Measure and fix every copy (`ci.yml:101`, PLAN.md :17 and :81, TESTING.md:190, SKILL.md:167, ARCHITECTURE.md:25) in the next commit that adds a runtime file, or now |

**`docs/PLAN-GAMEPLAY-MODS.md`:**

| Line | Change |
|---|---|
| after :13 | "**Order:** `docs/PLAN-NEXT.md`. Milestone 1 is specified in `docs/specs/comfort-pack.md`, and T1 in `docs/specs/disc-layer.md` (I6-I8)." |
| :66 | "H15c is under way" becomes "the renderer paused at 574c683; see PLAN-NEXT A" |
| :289 | "It is parked until H15d's numbers, and then it is your decision" becomes "It has a spike and a decision gate (`docs/specs/gpu-backend.md`; PLAN-NEXT M5, G1)" |
| :304 (P1) | append "*Specified as comfort-pack P1a (the mod) and P1b (the contrast); 'normal' writes nothing.*" |
| :342, :364, :441 (P3, P5, P10) | append "*Specified in `docs/specs/comfort-pack.md` as P3, P5a/P5b and P10a/P10b.*" |
| :377 (P6) | append "*Done 2026-09-25 (24d9235, and its follow-up 79c9ad8: the pin line, the config buffers and the log check; FINDINGS "P6: the race seed pinned ..." and "P6, followed up").*" |
| :463 (P11) | append "*Spike done (b911380): read the window through 0x80346E4C, then +36, with the state at 0x80346E64, not 0x80346E60, which the draw zeroes each frame. Built as comfort-pack P11; hold-to-skip is P11b, after CH1.*" |
| :629 (T0) | append "*Done 2026-09-25 (1c7b780, 4041dfc): 43 suffixes, 18 directories, the signature check; T0c (012164a) added card images and saves under any name and read history for content. The enemy-table check is T5's (012164a moved it there).*" |
| :637 (T1) | append "*Specified as disc-layer I6 (replace, add, alias), I7 (deltas) and I8 (per-map swaps), on I1's seam.*" |
| :1252 (milestone 1) | append "(specified in `docs/specs/comfort-pack.md`, which adds P6b, CH1, M5b, P10a, P11b, T0c and M11a)" |
| :1263 | "Go to 2, or to M9/M10 first" becomes "PLAN-NEXT's order follows milestone 1 (C5, H17, the disc layer, portability, the GPU spike); milestone 2 follows the gate" |
| :1268-1271 | "The first three slices" gains "*P6 and T0 are done; P1 and P11 are comfort-pack P1a and P11.*" |
| :1284 (Manifest v2) | append "*Done 2026-09-25 (3949028, b071949, b1199b3; FINDINGS "Manifest 2").*" |
| :1322, :1333, :1339, :1348, :1398 | append, in order: "*Specified as comfort-pack M18*", "*... M19*", "*... M5b*", "*... CH1*", "*... H19a*" |
| :1403 (H20) | append "*A gap filler in PLAN-NEXT M1; its Done is written first.*" |
| :1476 | "PLAN.md parks the GPU backend until H15d's numbers" becomes "a spike and gate in `docs/specs/gpu-backend.md` (PLAN-NEXT M5)" |

**`HANDOFF.md`:**
- **:382:** "The plan of record for the next phase is `docs/PLAN-60FPS-MODS.md`" becomes "What is
  next, in order, is `docs/PLAN-NEXT.md` (2026-09-25). PLAN-60FPS-MODS.md and PLAN-GAMEPLAY-MODS.md keep
  the slices."
- **:503:** "four `test_gxr_*` modules" becomes nine (portability L4b also fixes this).

**`README.md:26`:** add "and [docs/PLAN-NEXT.md](docs/PLAN-NEXT.md), the order".

**`CLAUDE.md:5-6`** (your call, since it is the project's instruction file): "Plan of record
docs/PLAN.md" could become "Plan of record docs/PLAN.md; what is next, in order, docs/PLAN-NEXT.md".

---

## C. Milestones, in order

### C0. At a glance

| Milestone | Slices | Size | What you get | You are needed |
|---|---|---|---|---|
| **M1. Comfort pack** | C5a first (done, 750cef0), then P6b (done, 79c9ad8), P1a (done, 090eea6), P11, P1b, M18, CH1, P11b, H19a, M5b, M19, P3, P10a, P10b, P5a, P5b, M11a; gap fillers T0c (done, 012164a), I2, L3a, L2a, H20 | about 4 weeks | The comfort features; 1.42 GB of disk back; the display-list question answered | Sessions A and B |
| **M2. The picture right, then 60 fps** | C5b, C5c, H17a, H17b, (H9), H18 by class | 3 to 4 weeks | Effects drawn as the console layers them (C5a confirmed the cause); 60 images a second where the CPU keeps up, the frame repeated where it cannot | Look C, session D |
| **M3. Your own disc, one copy** | I1, I3 (I5a only if the implementation session agrees to it, C3) | about 1 week (+2 if you want the store) | Runs from your ISO; wrong disc refused; replays need no disc | One yes/no (D-5) |
| **M4. Portability groundwork** | M4a: L2, L4a, L4b, L8, L3b, L1. M4b (L6, L7, L9) after the gate by default (D-10). L5 rides the next planned retranslation (C7) | 2 to 3 weeks (M4a); about 1.5 more for M4b | clang-cl building the same frames, CI on Linux, ARM and ThreadSanitizer, the Deck question answered by Wine | Two yes/no answers (D-13, D-14) |
| **M5. The GPU spike, then the gate** | V0, V1, V2, V3a, V3b, V4a, V4b, then gate G1 | 3 to 4 weeks | Your GPU decision, with measured numbers and four pictures | The gate sitting |
| After the gate | Branch on G1: the GPU build (V5+), or H15d/H16 resume; M4b if G1 or G2 points off Windows; then gameplay milestone 2 | — | — | A choice of which first |

**The contract, at every slice.** With the slice's feature off, these must hold, whatever the
specs call them:
- `python tools/scenario.py replay --threads 1,2,3,8` matches `config/fifo_manifest.tsv`;
- `$env:SOA_SELFTEST='1'; gen\soa.exe extracted` passes;
- `python tools/scenario.py run title --check` passes;
- `python tools/decomp.py` is unchanged;
- `python -m pytest tools/tests/test_memguard.py tools/tests/test_mods.py` passes.

After C5c the manifest's hashes are the re-blessed ones (M2), so this contract names the manifest, not
"the 23 hashes".

**The exit check for every milestone.** A milestone is done when:
- each of its slices landed as its own commit, with its spec's Done lines run and named in the
  commit;
- the contract and CLAUDE.md's pre-push list pass on HEAD;
- each owner session of the milestone has a FINDINGS entry saying what was seen;
- the tables here mark each slice done with its commit.

A check that compares two live runs never counts (PLAN-GAMEPLAY-MODS rule 7).

### C1. M1: the comfort pack (gameplay milestone 1)

**What you get.** Every item is off until you switch it on in `soa.ini`:
- encounters off, half, normal or double, and "hold B to avoid";
- a pinned random seed;
- dialogue that advances itself, and holding LB to skip;
- rumble;
- borderless fullscreen and a resizable window;
- port shortcuts on the pad's spare buttons;
- a double-click start that finds your saves;
- a clock that ignores sleep;
- Dolphin saves in and out;
- a second pad for co-op battles;
- gamma, colour-blind, flash-limiter, sharp and CRT options, and deflicker off;
- battle turbo up to 2×.

From the gap fillers you also get 1.42 GB of disk back, and clang builds working again.

**Order and slices.** [specs/comfort-pack.md](specs/comfort-pack.md) §6 has each slice's files and Done
lines. The order is the spec's, with C5a first (below says why) and the gap fillers placed where they
cost least.

| # | Slice | Size | Rebuild | Needs first | Owner |
|---|---|---|---|---|---|
| 1 | **C5a** confirm the recorded-display-list chain, `SOA_GX_DLLOG` ([specs/gpu-backend.md](specs/gpu-backend.md) §6). **Done, 750cef0:** the chain is confirmed (FINDINGS "Recorded display lists (C5a)") | hours | `--link` (gx.c, a log only) | — | — |
| 2 | **P6b** P6's three additions: the `[seed] pin:` line, 640- and 1024-byte config buffers with a "cut at" line, `test_seed.py`'s log check (comfort 3.3 and its P6b slice). **Done, 79c9ad8** (FINDINGS "P6, followed up") | hours | `--link` | P6 (24d9235) | — |
| 3 | **P1a** encounter slider and hold-B with restore; per-mod write counts; `--link` builds `mods/*/mod.c`; `encounters-off` moved to `examples/`. **Done, 090eea6** | a day | none for the DLL, `--link` for the rest | P6b | — |
| 4 | **P11** dialogue auto-advance. **Done, 664f005** | hours | none, `--link` for its key | P1a | — |
| 5 | **T0c** (gap) card images under any name. **Done, 012164a**, wider than specified: saves under any name too, every suffix in a name, and history read for content | hours | none | — | — |
| 6 | **I2** (gap) one copy on disk: the tools read the image; `--prune-loose`. **Done, 12077d1**, but for the owner's prune | hours to a day | none | — | **Owner** runs the prune in session A |
| 7 | **P1b** the encounter contrast (long runs at `SOA_SPEED=3`) | a day to several days | `--link` | P1a; a card and walk in a rate-20 zone where the step counter counts (Q-I5: `card-saved`'s a101b spot is zone 0, and the counter stayed 0) | — |
| 8 | **M18** rumble. **Done, 3d08479**, but for the owner's check | hours | `--link` | P6 | **Owner** (A) |
| 9 | **CH1** chords and host buttons (the chord arms log "not built yet"). **Done, d1000af**, but for the owner's check | a day | `--link` | — | **Owner** (A) |
| 10 | **P11b** hold-to-skip. **Done, 4c698f5** (only while autotext is on) | hours | none | P11, CH1 | — |
| 11 | **H19a** fullscreen, DPI, resize, letterbox, `present_interval` in `picture.c`. **Done, 63661a0**, but for the owner's check | a day to several days | `--link` | D-2 (defaults otherwise) | **Owner** (A) |
| 12 | **M5b** a first run without a terminal. **Done, 9642613**, but for the owner's check | a day | `--link` | D-3 | **Owner** (A) |
| 13 | **M19** a clock that survives sleep. **Done, fe7e48f**, but for the owner's check | several days | `--link` | — | **Owner** (A) |
| — | **Owner session A** (C8) | — | — | 8, 9, 11, 12, 13 landed | **Owner** |
| 14 | **P3** `.gci` import and export | a day | none | — | **Owner** (B) |
| 15 | **P10a** pad 2 in the runtime | a day | `--link` | — | — |
| 16 | **P10b** couch co-op (its one-hour spike first) | hours to a day | none, `--link` for its key | P10a, P1a | **Owner** (B) |
| 17 | **P5a** picture options | a day | `--link` | H19a for `sharp`/`crt` | — |
| 18 | **P5b** deflicker off for the display copy | hours | `--link` (gxr.c) | gxr.c free, which it is | — |
| 19 | **M11a** turbo up to 2×: measure first; M11a-skip is specified only if the battle drawn every frame misses 60 at p95 | a day | `--link` | P6b; CH1 (the chord arm); H19a (`present_interval`) | **Owner** (B) |
| — | **Owner session B** (C8) | — | — | 14, 16, 19 landed | **Owner** |
| gap | **L3a** toolchain profiles and `--cc` (`tools/` only; clang output goes to `gen/clang`) | hours | none | — | — |
| gap | **L2a** the SIMD blend behind an x86-64 guard, with `perfbench --exe` | hours | `--link` (gxr_tev.c) | D-12 "yes" (recommended) | — |
| gap | **H20** a power line in every run report | hours | `--link` | its Done written first (planning session) | — |

**Why C5a went first, before P6b and P1a.** It is cheap: hours, and a log that changes nothing drawn.
And if the defect is real, it sits under two things everything after it relies on:
- **the replay oracle:** 8 of the 23 pinned frames have pinned a mask effect with no casters since the
  manifest was first blessed ([specs/gpu-backend.md](specs/gpu-backend.md) 2.8), and every renderer
  check since has defended that picture;
- **H17:** H10's pair matching keys on display-list addresses, so the match rates H17a builds on move
  once the lists are recorded.

So its answer decides what M2 captures, blesses and measures, and it should not wait behind the comfort
pack. The implementation session's order put it first: C5a, then P6b, then P1a. It landed as 750cef0:
the chain is confirmed, and its FINDINGS entry names two things C5b must handle (C2).

**Why the gap fillers sit here:**
- **I2** is tools only and gives the disk space back at once.
- **L2a** fixes a breakage live since b377b1f: clang cannot compile `gxr_tev.c`, and G4's candidate
  compilers silently drop the SIMD path. It also brings `perfbench --exe`, which H17a's and later
  renderer A/Bs want.
- **H20** automates the power-mode note every measured run is supposed to carry.

**Written by the planning session during M1:**
- the H17a spec (C2);
- C5b's bracket mechanism, (a) a hook or (b) a `--link`-only test, settled with `tools/disasm.py` (specs/gpu-backend.md C5b);
- H20's Done;
- M11a-skip's spec, if M11a's measurement asks for it.

Each is reviewed before its slice starts.

**Answered by this order** (comfort Q-I4): gxr.c is free now. P5b is late in M1, and M11a-skip is
built only if measured.

### C2. M2: the picture right, then 60 fps

**What you get:**
- **As C5a confirmed** (750cef0), the game's layered effects drawn in the order the console draws them
  (probably character shadows that neither renderer draws today), and a corpus of reference frames
  re-captured and looked at.
- **60 images a second** where the CPU renderer keeps up: the field scenes meet the budget, and the
  ship and sky scenes do not yet. Elsewhere the port repeats the frame, as H17b's design says.
- **A list of what interpolation gets wrong,** fixed one class at a time.

| # | Slice | Size | Rebuild | Needs first | Owner | Spec |
|---|---|---|---|---|---|---|
| 1 | **C5b** record display lists into guest memory; `[gx] display lists` report; H10's pair matching re-measured on re-captured pairs, with 99% of 3D area the limit | a day to several days | `--link` (gx.c) | C5a confirmed | — | gpu-backend §6 |
| 2 | **C5c** re-capture the corpus, open every changed frame, bless: **a first bless** | a day | none | C5b | **Owner** look C | gpu-backend §6 |
| 3 | **H17a** interpolation, headless, off by default. A second EFB routed per command by `DrawCmd.efb`, from `g_target` in `claim_slot`. It measures the images a second each scene reaches, the input to A2 (b) and A3 | several days | `--link` | C5b's re-measure (or C5a refuted); the H17a spec reviewed | — | PLAN-60FPS-MODS H17a + the H17a spec |
| 4 | **H17b** interpolation, live: H8's presenter, cut detector, repeat when over budget, a `soa.ini` key off by default | several days | `--link` | H17a; D-2 (display at 60 or 120 Hz) | **Owner** session D | PLAN-60FPS-MODS H17b |
| 5 | **H9** VI locked to vblank, **only** if session A or D shows judder | several days | `--link` | its Done restated (PLAN-GAMEPLAY-MODS F) | **Owner** | PLAN-60FPS-MODS H9 |
| 6 | **H18a-e**, only the classes on your session D list, most visible first | a day to several days each | `--link` | H17b | — | PLAN-60FPS-MODS H18 |

**The H17a spec** (the planning session's, written in M1) has to fix four things:
- **the Done, restated as same-run checks.** Off: the contract. On: in one `SOA_INTERP=1` run, each
  real frame's `g_screen` hash is equal before and after its in-between pass, and the mutation that
  lets the pass write `g_screen` makes them differ. The in-between PNGs of a field, a battle, a ship
  battle and a cutscene are opened;
- **the `DrawCmd.efb` routing,** exactly as specs/gpu-backend.md 3.1 words it, so V2 and V12 build on it;
- **how the worker loop's changes are left** for portability L2 to convert (portability §3.10: L2
  converts what H17a added);
- **the measurement** that A2 (b) and A3 read: per scene, the images a second reachable, and whether
  the guest thread or the workers limit it.

**C5a's run bears on C5b's design** (FINDINGS "Recorded display lists (C5a)", 750cef0). Not every
redirect of the CPU FIFO is a list: from frame 1 to 385 the game draws its logo screen from a buffer it
never calls as a list, so a C5b that records whenever the two FIFO bases differ would draw nothing there.
C5b therefore records only between `GXBeginDisplayList` and `GXEndDisplayList` (`fn_80251D80`,
`fn_80251E48`), as the implementation session proposed. And lists are recorded more often than they are
called (35,574 against 27,871), so after C5b some draws the port shows today disappear, correctly. Look C
expects removals as well as additions (specs/gpu-backend.md C5b, C5c). Whether the bracket costs a
retranslation (a hook) or only `--link` is C5b's first step.

**C5a confirmed the finding** (750cef0), so C5b and C5c stand. (Had it refuted it, C5b and C5c would have
been dropped and H17a would have followed M1 directly; the V0 and V1 rows in C5 keep that branch.)

**If C5b's re-measure falls under 99%,** H7 (draw tags from the game) is reopened in FINDINGS before
H17a, as C5b's Done says.

### C3. M3: your own disc, one copy (disc layer step 1)

**What you get:**
- `gen\soa.exe "D:\wherever\Skies.iso"` runs from your own image, with no copy;
- an image whose executable is not the one the port was built for is refused by name;
- replays and the self test need no disc;
- I2 already gave the 1.42 GB back in M1.

| # | Slice | Size | Rebuild | Needs first | Owner |
|---|---|---|---|---|---|
| 1 | **I1** one seam for the disc (`runtime/disc.c`, `sha1.c`); system files from the image; the DOL-hash refusal; `SOA_DISC_LOG`. The drive's deadline is unchanged | a day to several days | `--link` | I2; M5b (its `aram_set_data_dir`) | — |
| 2 | **I3** the executable built in (`disc_sys.c` in `--out`); `--no-embed`; the stale-link guard; guard suffixes 43 to 48 | a day | `--link` (the guard arms at the next `--compile`) | I1; **D-5** | **Owner** agrees first |
| — | **I5a**, off the default path: the deadline from the command's start, with overruns counted in guest ticks. A deliberate change to every run's disc timing; built only if agreed, then alone | hours | `--link` | I1; **the implementation session agrees** to the change (disc impl Q1). Not before | — |

**Later:**
- **The store,** only if gate G5 says to build it: **I4** (several days, none) and **I5** (several
  days, `--link`), about 2 weeks. It adds integrity checks and one file to copy to a Deck or phone. It
  saves about 28 MB, not space.
- **I6 and I7** (T1: mods that replace, add, alias and delta disc files) land in gameplay milestone 2,
  after T9.
- **I8** lands when N2 needs it.

**M2 and M3 may interleave.** M2 edits `gx.c` and `gxr*.c`; M3 edits `disc.c`, `dvd.c`, `aram.c`,
`main.c` and the tools. Runs stay one at a time.

**I5a is a deliberate behaviour change, and off the default path.** The implementation session asked
that the disc layer keep DI completion timing identical, because scenarios and pad scripts are
frame-based. I1 and I3 do: they change no timing. I5a would change it on purpose, for every run: today
the host's read time is counted twice (specs/disc-layer.md §3.4), and I5a removes the second count.
So:
- it needs its own agreement, from the implementation session (disc implementation question 1);
- until then it is not built, and M3 is I1 and I3 alone;
- if agreed, it lands alone, as its own commit, so a timing change cannot hide inside another slice.

I5 depends on I5a, so if the implementation session declines I5a, I5 is re-specified with the double
count kept before it starts.

### C4. M4: portability groundwork

**What you get:**
- a clang-cl build that must draw the same frames as MSVC's, bit for bit;
- CI that catches breakage under clang, on Linux and on ARM processors;
- the render queue proved correct on any processor (ThreadSanitizer);
- the native string routines' silent 64-bit-`long` bug found and fixed;
- an answer to "does it run on a Steam Deck?" from Wine on this PC.

**M4a pays on Windows whatever the gate decides:**

| # | Slice | Size | Rebuild | Needs first | Owner |
|---|---|---|---|---|---|
| — | **L3a** and **L2a**, if they did not land in M1 | hours each | none / `--link` | — | — |
| 1 | **L2** `plat.h`: the queue's ordering completed (seq_cst on the four Dekker re-checks, the grep test), then the renderer builds anywhere (the POSIX pool) | a day to several days, two commits | `--link` | L2a | — |
| 2 | **L4a** CI: the clang-cl leg, with the reverted-guard mutation shown red | hours | none | L2a, L3a | — |
| 3 | **L4b** CI: the Linux leg; `types.h` and the five native units fixed for LP64; `dc_check` to twelve routines; `render_check --threads N` | several days | `--link`, `decomp.py` | L2, L3a | — |
| 4 | **L8** CI on ARM64 and ThreadSanitizer, after fixing the `g_notex` and `WARN_ONCE` races | several days | `--link` | L2, L4b | — |
| 5 | **L3b** the clang-cl game build: self test, replay and `title --check` against the MSVC manifest; speed measured | a day to several days | one retranslation into `gen/clang` (MSVC's build untouched) | L2a, L3a; **D-14** (LLVM); the machine free | — |
| 6 | **L1** Wine smoke test in a container (checkout and `extracted/` mounted read-only, a scratch volume over `build/`) | hours | none | **D-13**; the machine free | optional Proton session on a Deck |

**M4b pays only once a non-Windows build is a goal:**
- **L6:** renderer determinism, `plat_f2i`, and CORE-MATH `exp2f`/`log2f`. It changes Windows
  arithmetic too.
- **L7:** the POSIX layer's first part.
- **L9:** its second part, after M1's and M3's files have settled.

The portability spec orders them straight after M4a, and does not tie them to the GPU decision. **This
plan runs them after the gate by default** (D-10), for two reasons:
- **L6 is a risk with no payoff yet.** It changes the Windows renderer's arithmetic for a benefit that
  exists only once a replay runs off Windows.
- **L7 and L9 are only exercised by the Linux CI leg** until L10 exists, and L10 waits for G2.

Run after the gate, they land when G1 and G2 say whether Linux or Android is coming, and the gate comes
about 1.5 weeks sooner. If you would rather follow the portability spec's order exactly, answer D-10
"M4b before M5".

**Gated, not scheduled:**
- **L10**, native Linux: gate G2 (SDL3).
- **L11**, ARM64 on a device: hardware you name.
- **L12**, Android: gate G1 answering A, gate G3, and Android as a goal.

**The order question the portability spec asked (its Q8).**
- **(a) L2a in M1:** recommended here (D-12).
- **(b) L2 before H17a:** not recommended by default. It would put portability work ahead of the disc
  layer and delay 60 fps by 2 to 5 evenings. It is a preference, not a dependency: L2 converts what
  H17a added.

### C5. M5: the GPU spike, then the gate

**What you get:** a decision taken on measurements. For each captured frame:
- whether a GPU renderer's picture agrees with the CPU one's, under a checker frozen and proven able to
  fail before any GPU picture exists;
- whether the game's hard features (logic ops, copies of the picture into game memory) are exact on
  the GPU;
- GPU milliseconds a frame on your Z1 Extreme's GPU;
- four side-by-side pictures for you.

**Before it starts, four answers** (section D1):
- whether Android is a firm goal (D-17): that picks Vulkan or Direct3D 11;
- whether the build may fetch Vulkan's headers and a shader compiler (D-18);
- whether a GPU picture judged by a tolerance is acceptable (D-19);
- whether three to four weeks of evenings may go to it (D-20).

| # | Slice | Size | Rebuild | Needs first | Owner |
|---|---|---|---|---|---|
| 1 | **V0** the frame oracle (`tools/imgdiff.py`), thresholds frozen by mutations; the benchmark references opened | a day | none | C5c, or C5a refuted (the references are the corpus as it will stay) | — |
| 2 | **V1** the captures the corpus lacks: menus, scene-to-texture, a mask effect with casters, kept as consecutive frames | a day | none (live runs, one at a time) | V0; C5b, or C5a refuted (then no mask capture with casters) | — |
| 3 | **V2** the seam: `gxr_cmd.h`, a reachable zero-worker path (`SOA_GXR_INLINE`), the passthrough backend, copy clears as their own commands, `tex_gen` | a day to several days | `--link` | L2; H17a (which added `DrawCmd.efb`; V2 moves it into the header and does not redo it) | — |
| 4 | **V3a** headless Vulkan harness: fetch, build, the EFB pass with CPU clipping, geometry self test | several days | none | V2; D-17 "yes" or unanswered | — |
| 5 | **V3b** the exact differentials: `tevdiff`, `copydiff` | several days | none | V3a | — |
| 6 | **V4a** the spike on the 21 captures with no texture copies: draws, textures, depth, fog, blend, screen copy | several days to week-plus | none | V0, V3b | — |
| 7 | **V4b** copies and logic ops, with poison and chain; V1's captures; the gate memo | several days | none | V4a, V1 | **Owner**: four side-by-sides |
| — | **Gate G1** | — | — | V4b | **Owner** |

If D-17 is "no" before V3a starts, V3-V4 are built on Direct3D 11 (V3′/V4′), with the same Done
lines.

**The time box is three to four weeks of evenings.** If V4a has run past week-plus, stop, and take the
gate with V4a's numbers and a list of what V4b would have added.

**This order differs from the GPU spec's own recommendation.** specs/gpu-backend.md §8 proposed V2-V4 right
after the comfort pack. The pivot puts M2, M3 and M4a first, so the gate lands about 6 to 8 weeks later
than that spec suggested. D-10 offers moving M5 up: it needs only L2a, L2 and H17a first.

### C6. After the gate

| G1's answer | Next |
|---|---|
| **A. Vulkan** | V5, V6a, V6b, V7: about 4 to 6 weeks to a live GPU renderer at native resolution. Then V8 (present from the GPU), V9 (2×/3×, widescreen), V10 (logic ops without `logicOp`) and V12 (H17 on the GPU), about 4 to 6 more, as D-26 allows. L10-L12 per G2, G3 and Android |
| **B. Direct3D 11** | The same on D3D11 (porting the spike first, week-plus, if it was built on Vulkan); no Android |
| **C. Not now** | H15d resumes at its next step, then H16 (A3). The oracle and the seam stay |
| **D. Not ever** | As C, and PLAN.md says so |

**M4b (L6, L7, L9) runs after the gate** when G1 or G2 points off Windows: Android, native Linux or
ARM. If neither does, it stays parked with L10-L12.

**Whatever the answer, a second choice follows:** the GPU build first, or gameplay milestone 2 first
(PLAN-GAMEPLAY-MODS §E). Gameplay milestone 2 opens with M8 and M7a/b (the overlay and the in-game
actions, which many later slices need), then T9, T1 (disc-layer I6/I7) and R0, then retranslation batch
A.

### C7. The parking lot: planned elsewhere, not scheduled here

These stay in their plans with their text intact. Naming them here means nobody takes silence for
cancellation. Each returns on the condition shown.

| Item | Returns when |
|---|---|
| H9 | owner session A or D shows judder |
| H11's guest half | H20 shows its battery cost, or with M19 (A5) |
| H13's rest, H13c | A2's condition |
| H15d, H16 | A3's condition |
| M6, M7a/b, M8, M9, M10, M12-M17, M3d | gameplay milestone 2 onward, M8 and M7a/b first |
| F4-F7 | a mod needs a function changed inside |
| S4b, S5-S9 | nights are free for soaks; S6 needs you for Task Scheduler |
| Gameplay milestones 2 to 7; K3, K5, K10, P8, P13, P14, T7, T12, R7, R9, X9 | after the gate (C6) |
| PLAN.md tracks B, D, E, F; G3-G7 | G3's answer for G4; otherwise as before |
| Disc I4/I5 | G5; I6-I8 with gameplay milestone 2 |
| Portability M4b (L6, L7, L9) and L10-L12 | after the gate, when G1 or G2 points off Windows (D-10, C6) |
| L5 (one `SOA_FMA` macro) | the next planned retranslation (an H13 reopen, or gameplay batch A). No slice in M1-M5 is planned to retranslate `gen/` (L3b's retranslation is into `gen/clang`); if C5b's restated rule needs a hook, L5 can ride that |
| GPU V5-V12, V11 | G1 |

### C8. Owner time, batched

| Sitting | When | About | What happens |
|---|---|---|---|
| **Decision sitting 1** | Now, early in M1 (C5a, P6b and P1a need no answer) | 30 to 45 min, no play | Eight questions, most of them yes or no: **D-1** (approve this order) and **D-10** (or take the GPU answer sooner); **D-2** (the handheld and its refresh rate; then set the display to 60 or 120 Hz); **D-5** (`soa.exe` holding your executable); **D-12** (L2a early); **D-13** (Docker or WSL for Wine); **D-14** (install LLVM); **D-17** (is Android a firm goal?). Everything else defaults (D6), and you can overrule a default at any later sitting |
| **Session A** | Mid-M1, after M18, CH1, H19a, M5b and M19 | 60 to 90 min on the handheld | **H8**: 15 minutes windowed, and your verdict. **M5**: a setting on and off without a terminal. **M5b**: double-click start; `unfocused = mute`. **H19a**: F11, Alt+Enter and the chord; resize; Escape in fullscreen. **CH1**: the pad in slot 1 or 2. **M18**: rumble in a battle with the game's Vibration on and off. **M19**: sleep a minute in the field. **I2**: run `extract.py --prune-loose --dry-run`, then for real (D-28). Optionally play with P1 and P11 on, and keep the log (D-25) |
| **Session B** | End of M1 | about 60 min, with Dolphin at hand | **P10b**: two pads, one battle (Parsec optional). **M11a**: turbo feel and music pitch. **P3**: import a Dolphin save, and export one back to Dolphin. **C5 (optional)**: the same scene in Dolphin and the port, a character in sunlight and a menu over a field (D-29), which feeds C5b/C5c. P5a at a glance |
| **Look C** | M2, after C5b | about 20 min, no play | **C5c**: open each changed frame beside the old one; the bless commit says you did |
| **Session D** | M2, after H17b | about 30 min windowed, at 60 or 120 Hz | **H17b**: does 60 look right? A list of anything wrong, which is H18's input. Judder here reopens H9 |
| **Gate sitting** | After V4b | about 30 min | Four side-by-sides; **G1**; then D-26 (2×/3×) and, if the answer is A with Android or Linux, G2 and G3 |

**Optional, not a gate:** the Proton session on a Deck, if you have one (L1).

**While you use the machine** for any of these, the implementation session runs nothing.

---

## D. Decision gates

### D1. G1: the GPU backend

| | |
|---|---|
| **When** | After V4b (end of M5). Four questions come first: D-17 before V3a (it picks the API); D-18, D-19 and D-20 before M5 starts |
| **You see** | V0's per-capture verdicts, with each failure classified as by-design or defect. V3b's exactness counts. Whether the logic-op fallbacks match native. GPU and CPU milliseconds a frame, interleaved in one session. Energy per drawn frame, if H20 has landed. Four side-by-sides |
| **Choices** | **A** Vulkan; **B** Direct3D 11; **C** not now; **D** not ever (specs/gpu-backend.md §8) |
| **It decides** | V5+; whether H15d and H16 return (A3); whether L12 can ever be playable; V8/V9 (2×, 3×, unsqueezed widescreen) |
| **If unanswered** | C: nothing new is built, the oracle and the seam stay, and H15d/H16 stay deferred until you answer |

### D2. G2: SDL3 (gameplay Q6 = portability Q6)

| | |
|---|---|
| **When** | Before L10. Nothing in M1-M5 needs it |
| **Choices** | SDL3 (fetched and hash-pinned at build time, never in `vendor/`) behind the existing window, pad and audio seams for Linux and Android, and possibly Windows; or Windows.Gaming.Input or Steam Input for non-XInput pads; or no |
| **It decides** | L10 (native Linux), L12's input and audio, and non-XInput pads on Windows |
| **If unanswered** | No SDL3. Linux stays headless in CI, and Windows stays Win32 |

### D3. G3: distribution (gameplay Q3, PLAN G4)

| | |
|---|---|
| **When** | Before anyone else gets a build, and before L12 |
| **Choices** | Source only, built on each player's machine (today); a runtime-only APK that loads a player-built game library (android-and-native.md §4); prebuilt binaries, which conflict with SPEC §2 rule 2 |
| **It bears on** | I3 (after it, `soa.exe` holds your copy of the executable verbatim, so never share it); portability Q3 (the default compiler); L12 |
| **If unanswered** | Source only |

### D4. G4: the handheld and its refresh rate (gameplay Q1 = comfort Q-O4)

| | |
|---|---|
| **When** | Now, at sitting 1 |
| **Why now** | H8 found your display running at **85 Hz**, where 30 fps cannot be paced evenly (FINDINGS "H8"). H19a's run (63661a0) found it is a **3440×1440 ultrawide**, so the question is also whether you play on that monitor, on the handheld's own screen, or on both. H8's verdict, H17b's pacing target and M11a's presenter all assume 60 or 120 Hz, and H19a's default window size depends on the screen. A ROG Ally or Ally X (7 inch, 1920×1080, 120 Hz) and a Legion Go (8.8 inch, 2560×1600, 144 Hz) need different defaults, and at 144 Hz the game paces unevenly until H9 |
| **It decides** | H19a's defaults, the display for sessions A and D, whether H9 is needed, and M11a's presenter table |
| **If unanswered** | H19a picks the largest whole multiple of 640×480 that fits, and the sessions run at 60 Hz, which you set before session A |

### D5. G5: the disc store format (disc Q1, Q2, Q4, Q7)

| | |
|---|---|
| **When** | After M3 |
| **Choices** | Stop after I3: `disc.iso` stays and a mismatch is refused. Or build the store as shipped: I4 and I5, about 2 weeks, giving integrity checks and one file to copy to another device, and saving about 28 MB, not space. Or build it recompressed, which needs a third-party decoder: the same kind of question as SDL3. Also: a per-file hash list in `config/` or not, and whether scrubbed dumps are accepted |
| **If unanswered** | Stop after I3. Build the store when Android or the Deck is firm |

### D6. The decision register: every open owner question, merged

The specs ask about forty questions between them, and several are the same question under two
numbers. **Only the questions in bold are asked at sitting 1;** every other row's default applies
until you say otherwise.

| Id | Question | Source ids | Needed by | Default if unanswered |
|---|---|---|---|---|
| **D-1** | Approve this order | pivot; android §7 | now | this order |
| **D-2** | Which handheld; which refresh rate you play at | gameplay Q1, comfort Q-O4 | H8's check, H19a, H17b | D4's default |
| D-3 | Relative paths and the default card mean "inside the SOA folder" | comfort Q-O1 | M5b | yes |
| D-4 | Escape in fullscreen leaves fullscreen; should quitting need confirming? | comfort Q-O3 | H19a | leaves fullscreen; no confirmation |
| **D-5** | `soa.exe` may hold your copy of the executable (never shared) | disc Q5 | I3 | **none: I3 waits** |
| D-6 | Chord layout: View+LB fullscreen, View+RS turbo, LB to skip text | comfort Q-O5 | CH1 | as proposed |
| D-7 | Rumble on by default, at strength 100? | comfort Q-O2 | M18 | 100, with the game's option deciding |
| D-8 | Auto-advance delay | comfort Q-O6 | P11 | 1.5 s |
| D-9 | Turbo: battles only or sailing too; from the settings file or the chord only | comfort Q-O7 | M11a | battles; both switches |
| **D-10** | Where M5 goes. (a) After M4a, with M4b after the gate. (b) Sooner: right after M2 (only L2a and L2 first), with M3 and M4 after the gate. (c) The portability spec's order exactly: M4b before M5 | GPU §8 and portability §6 against the pivot | M2's end | (a), recommended (C4) |
| D-11 | Picture options: which matter; co-op's default slot | comfort Q-O8, Q-O9 | P5a, P10b | flash limiter and sharp first; slot 1 (the second party member) |
| **D-12** | L2a (hours) in M1 | portability Q8(a) | M1 gap | yes (recommended here) |
| **D-13** | Docker Desktop or a WSL distro for the Wine test | portability Q1 | L1 | L1 waits |
| **D-14** | Install LLVM for the clang-cl build | portability Q2 | L3b | L3b waits; L3a uses the NDK's clang-cl |
| D-15 | clang-cl as the default compiler, if it is exact and faster | portability Q3 | after L3b | MSVC stays |
| D-16 | ARM hardware that matters | portability Q4 | L11 | none |
| **D-17** | Is Android a firm goal? | portability Q7 = GPU Q-V1 | V3a (the API); L12 | Vulkan for the spike (gpu-backend V3a's rule); L12 stays gated |
| D-18 | The build may fetch Vulkan headers and glslang into `vendor/` | GPU Q-V3 | V3a | ask before M5; D3D11 needs neither |
| D-19 | Accept a GPU picture judged by a tolerance, with the CPU renderer as reference | GPU Q-V4 | V0 | ask before M5 |
| D-20 | Three to four weeks of evenings for the spike | GPU Q-V5 | M5 | ask before M5 |
| D-21 | CPU floor: keep x86-64 with SSE4.1 checked at run time, or require AVX2 | portability Q5 | an H13 reopen, L5 | keep today's floor |
| D-22 | Store format, per-file hashes, scrubbed dumps | disc Q1, Q2, Q4, Q7 | G5 | D5's default |
| D-23 | Text deltas for disc files | disc Q3 | I7 (gameplay milestone 2) | yes, as specified |
| D-24 | H18 follows H17b and is not held by the GPU gate (A4) | this plan | M2 | yes |
| D-25 | Keep a long play log, to count guest threads | portability Q9 | any time | yes, please |
| D-26 | 2×/3× resolution and unsqueezed widescreen wanted | GPU Q-V2 | V8/V9 | ask at the gate |
| D-27 | GPU build or gameplay milestone 2 first, after the gate | this plan | C6 | ask at the gate |
| D-28 | Delete the loose tree (I2), and later `disc.iso` and your original dump (I5) | disc Q6 | session A; I5 | nothing is deleted without you; the commands check first |
| D-29 | A Dolphin comparison for C5 | GPU Q-V6 | session B | optional; C5c proceeds on the port's frames |
| — | Gameplay Q2, Q4, Q5, Q7-Q11 (save promise, licences, game-data boundaries, bounty, name, NG+, companion, "Encore") | gameplay G | gameplay milestone 2 onward | ask when that milestone starts |

**Questions for the implementation session,** collected so they are answered once:

| Question | Where it is asked | This plan's proposed answer |
|---|---|---|
| Q-I5: a card and walk for P1b | comfort | partly answered by the implementation session: `card-saved`'s a101b spot is zone 0 (the u16 at `0x8034740E`), and the step counter `0x80346D28` stayed 0 over 1,700 frames of scripted walking though Vyse walked. P1b needs another card and route in a rate-20 zone, for example the part-G card at 116a, where M1 fought. P1a's live Done peeks only the byte and does not depend on it |
| Q-I6: P10b's spike | comfort | first thing in P10b |
| Accept I5a's timing change? | disc impl 1 | open; until answered, "no": I5a stays off the default path and is not built (C3) |
| A mod refused after its files are placed | disc impl 2 | open |
| The built-in symbols in `test_memguard` and `test_profiler` | disc impl 3 | open |
| Block digests | disc impl 4 | open |
| I1 also finishes D2's disc-read list? | disc impl 5 | open |
| `SOA_DISC_LOG` as D2's default output? | disc impl 6 | open |
| Which of M5b and I1 lands first | disc impl 7 | M5b, in M1; I1 in M3 reuses its `aram_set_data_dir` |
| Who owns the on-device ISO importer | disc impl 8 | open |
| B1: `g_screen`'s single buffer | portability | before L8's windowed TSAN, or with H17b |
| B3: which retranslation L5 rides | portability | the first planned one |
| B4: the windows-11-arm image | portability | checked at L8's start |
| B5: CORE-MATH or hand-written | portability | open |
| B6: `scenario.py --wrap` or a separate script | portability | open |
| B7: measuring clang-cl's call cost | portability | in L3b |
| B8: one seq_cst load | portability | open |
| B9: the self test's thread count | portability | open |
| Is C5a's log the cheapest confirmation? | GPU | answered: C5a as specified, first in M1, landed as 750cef0 |
| What else assumes `g_workers > 0` | GPU | answered in V2 |
| `gxr_cmd.h` acceptable before H17a? | GPU | no: after H17a, as here |
| H17a's routing through `DrawCmd.efb` | GPU | yes, in the H17a spec |
| Pad recipes for the camp menu and a battle transition | GPU | answered in V1 |
| Why the mask copies read 0x00 in some captures | GPU | answered at C5b |
| CI and glslang's 14 MB | GPU | open |

---

## E. Coordination between the two sessions

1. **Who does what.**
   - **The planning session** writes documents only: `docs/PLAN-NEXT.md`, `docs/specs/*.md` and
     their review logs. It never runs `gen\soa.exe`, `tools/scenario.py`, `tools/soak.py` or pytest. Its
     compile and web probes run in a scratch directory at idle priority, and never while the
     implementation session is timing.
   - **The implementation session** does all code, every run, every push, every status line in the
     plans, and FINDINGS.
2. **One `soa.exe` at a time on this machine** (CLAUDE.md). That includes:
   - Wine and Docker runs (L1);
   - clang builds' runs (L3b);
   - your play sessions, because the build machine is your handheld.
3. **One editor for `runtime/gxr*.c` and `runtime/gx.c`:** the implementation session. The planning
   session proposes through a spec and never edits them.
4. **Specs reviewed before work starts.**
   - Each slice starts from a reviewed spec. The four specs had two reviews each, then a consistency
     check with this file. New ones are written
     by the planning session and reviewed before the slice begins: the H17a spec, H20's Done, and
     M11a-skip's if it is needed.
   - At a slice's start, the implementation session re-reads its spec against HEAD. Drift (moved
     lines, landed prerequisites, a design the code overtook) becomes a one-line entry in that spec's
     review log, in the slice's commit.
5. **Git, on one shared working tree.**
   - `git pull --rebase` before every commit.
   - Commit only your own paths (`git add <path> ...`, never `git add -A`): the other session's
     in-flight edits sit in the same tree.
   - After any documentation edit, `git diff --numstat` (the CRLF trap, HANDOFF).
   - The planning session's commits are documentation only and are not pushed unless the owner asks.
     The implementation session pushes after CLAUDE.md's full pre-push list.
6. **Status in the same commit.** A slice's commit marks it done in the document that specifies it
   and in this file's tables, and fixes every copy of any count it moved.
7. **Hand-over notes.** At the end of a sitting each session names its commits to the other. The
   planning session re-bases its specs on the named commits before the next slice they describe
   starts.
8. **The spec conventions the implementation session asked for**, which every slice keeps:
   - every Done line names the command that checks it;
   - a performance claim comes from an interleaved A/B against a saved base exe, because the machine
     drifts about 15% within a day;
   - any new baseline says in its commit how it was inspected;
   - one commit per slice, with its tests;
   - no completion check compares two live runs (rule 7).
9. **Deviations are allowed and written down.** The implementation session may depart from a spec
   when the code says otherwise. The commit and FINDINGS say why, and the planning session folds it
   back into the spec.

---

## F. Concerns, stated plainly

**Your time is the scarcest thing in this plan.**
- **What is already waiting on you.** Two pieces of work are built and waiting for your check: H8's
  presenter, which also needs the display off 85 Hz, and M5's settings file. The comfort pack adds
  eight more checks that only you can do: M18, CH1, H19a, M5b, M19, P3, P10b and M11a (the device,
  two pads, a Dolphin save, a sleep, turbo feel).
- **The questions pile up.** The four specs and the gameplay plan ask about forty questions between
  them, some twice under different numbers.
- **What this plan does about it.** It asks eight questions now and gives every other one a default
  (D6). It batches your checks into two play sessions, one short look, one windowed session and the
  gate (C8).
- **If a session slips,** the slices it checks stay "done but for the owner's check", the way M5 is.
  The next milestone does not wait for it, except H17b (it needs the display rate) and I3 (it needs
  D-5).

**Plan sprawl.**
- **The count.** There are now nine planning documents, with over 8,000 lines of specs and plans
  between them.
- **Ids collide.**
  - "Q3" is distribution in the gameplay plan and the default compiler in the portability spec.
  - "Q1" is the handheld in one and Wine in the other.
  - The same slice goes by several names: M5b is PLAN-GAMEPLAY-MODS's "M5 amendment", T1 is I6-I8,
    and L0 is N4.
- **The mitigation.** This file is the only place that orders things. D6 gives every owner question
  one id, B1 says which document owns which slice, and B3's pointer edits close the old "what next"
  lines.
- **The risk that remains is drift.** A slice can land without its status line: P6 landed without
  the spec's three additions, a live example (they followed as P6b, 79c9ad8). Hence E6's same-commit rule.

**Baselines drift across compilers, and one baseline is about to move on purpose.**
- **The pinned hashes are MSVC's.** The 23 pinned hashes are MSVC `/fp:strict /O2` output of the CPU
  renderer. clang-cl (L3b), Wine (L1), Linux and ARM (L10, L11) must reproduce them bit for bit and
  may never bless them. L3a makes `--bless` refuse any exe but `gen/soa.exe`.
- **L6 changes Windows arithmetic.** Its own `exp2f`/`log2f` change 74,154 and 313,550 raw outputs,
  predicted to move no hash; a moved hash is opened, not re-blessed.
- **Every bless commit records the compiler version,** which L3b's `[boot]` line provides from then
  on. A Visual Studio update that moves a hash is a question to answer, not a new baseline.
- **C5c re-blesses the corpus itself, as a first bless.** Every spec's contract then means the new
  manifest. Done lines that name specific captures must be re-read after C5c: V0's perfset-copy line and
  the distinct-frame counts in gpu-backend 2.2, V4a, V4b and V10, and V4b's list of 8 mask-effect
  captures. (P5b's "all 23 move" runs in M1, before C5c.)
- **The GPU frames are never pinned.** V0 freezes its thresholds before any GPU frame exists.
- **More new baselines,** each a first bless whose commit must say how it was inspected:
  `config/libm.tsv` and the synthetic frame hash in `render_driver.c` (L6); `config/GEAE8P/disc.yml`
  (I4); V0's frozen thresholds and opened benchmark references; V1's gpuset references.
- **Speed figures are per compiler and per day.** MSVC's figures in FINDINGS and clang-cl's are
  comparable only when taken interleaved in one session.

**Two sessions editing the same files.** Only the implementation session edits code, so the conflict is
between its own slices and the specs that describe them, as those slices move lines under the specs.
The hot files in M1-M5:

| File | Touched by |
|---|---|
| `runtime/main.c` | P6b, P1a, M18, CH1, H19a, M5b, M19, P5a, M11a, I1, I3, L3b, L7, V5 |
| `runtime/settings.c` | nearly every comfort slice (a key each), M5b, L9 |
| `runtime/si.c` | P6b, CH1, M18, M5b, P10a |
| `runtime/window.c` | H19a, M18, M5b, M19, CH1, P10a, P5a, M11a, then V8 |
| `runtime/mod.c`, `soa_mod.h` | P1a, CH1, P10a, I1 (the SHA-1 move), I6, L9 |
| `runtime/gxr.c`, `gxr_tev.c`, `gx.c` | C5a, P5b, (M11a-skip), L2a, C5b, H17a, L2, L6, L8, V2 |
| `runtime/dvd.c`, `aram.c` | M5b, I1, I5a (only if agreed), L2 |
| `tools/guard.py`, `ci.yml` | T0c, I3, I4, I7, L4a, L4b, L8 |
| the count copies in README, TESTING, HANDOFF, PLAN, ARCHITECTURE and SKILL | almost every slice |

Specs cite line numbers at b071949 or c8274db, and the first `gxr.c` edit moves them. Specs also cite
functions by name, and E4's re-read at slice start is the check.

**Deferred work goes stale.**
- **What is deferred.** H15d stopped mid-way, H16 never started, H13's rest, H9, H11's guest half,
  M8, gameplay milestones 2 to 7, the disc store, L9-L12 and V5-V12 all wait months.
- **Why that is a hazard.** Their numbers age in the meantime:
  - the corpus changes at C5c;
  - H17 changes the guest thread's load;
  - the machine drifts 15% a day.
- **The rule this plan adds.** A deferred slice reopens only on its named condition (C7, A2, A3).
  When it does, its FINDINGS figures are re-measured first, interleaved, and its spec is re-read
  against HEAD before any code.
- **A risk to close cheaply now.** H15d's SIMD guard is the kind of thing that rots silently: clang
  has been unable to build `gxr_tev.c` since b377b1f, and nothing noticed, because no CI leg uses
  clang. L2a and L4a close that.

**Scope creep.**
- **The pack has already grown.** The comfort pack grew from the gameplay plan's twelve milestone-1
  items to seventeen slices (P6b now standing for P6's remainder):
  - four items split in two: P1, P5, P10, and P11 with hold-to-skip;
  - M11a and T0c added.

  It is now about 4 weeks instead of 3. The disc layer has nine slices, and portability sixteen.
- **The rules that hold the line:**
  - each milestone's slice list is fixed here, and a new idea goes to the parking lot (C7), not into
    the milestone;
  - the GPU spike has a time box (C5);
  - H18 builds only the classes you list;
  - a slice that outgrows its size is split, not stretched;
  - the optional parts (the store, M4b, H9) are built only when their gate says so.
- **What to cut first if time is short:** M4b, H18 beyond its first class, P5a's CRT and
  colour-blind modes, and P1b's sky run.

**Other things you should know:**
- **The GPU decision is three to four months out** under the order you asked for. Android and 2×/3×
  resolution wait for it. D-10 is the way to have it sooner.
- **60 fps moves back by the comfort pack's length,** about 4 weeks, plus C5b and C5c if C5a
  confirms. If 60 fps matters more to you than the comfort pack, H17a can go first: nothing in M1
  blocks it.
- **C5 may show a visible defect the port has always had.** 8 of the 23 pinned frames would then
  have pinned it since the manifest was first blessed (specs/gpu-backend.md 2.8). That is exactly the
  "first bless" trap CLAUDE.md warns about, and it is why C5a runs first and C5c needs your eyes.
- **After I3, `soa.exe` contains the game's whole executable, verbatim.** It was never shareable,
  since it holds a translation of the code, but now it is a complete copy. Never attach it to an
  issue or send it to anyone.
- **The store (G5) is not a space saving.** I2 alone, in M1, gives the 1.42 GB back.

---

## G. Open questions about this plan itself

- **For the owner:** D-1, D-10 and D-24 are about this plan's own choices: the order, taking the GPU
  answer sooner, and H18's placement. The rest of D6 is the specs' questions, merged.
- **For the implementation session:**
  - Does A2's reopen condition (b) measure what it needs? The guest thread's time per real frame,
    plus the in-between build, against worker busy time.
  - Are A3's proposed thresholds reasonable for "too slow on a named target"?
  - Is H18's reading in A4 agreed?
  - The table in D6 lists the specs' own questions for you. The ones this order answers are marked
    there.

*Review: a consistency review across this file and the four specs was applied on 2026-09-25 at 012164a;
the specs' review logs list its changes. This file is also reviewed by the implementation session before
it lands as `docs/PLAN-NEXT.md`. Disagreements go in a review log at its end, not into silent edits.*
