# Handoff

For whoever picks this up next, human or agent. `CLAUDE.md` has the rules and
`docs/PLAN.md` has the work; this page is the part that is otherwise only in
someone's head: what the state actually is, what has already been tried, and
which confident-sounding statements in the history are now known to be wrong.

Read in this order: `CLAUDE.md`, then this, then `docs/PLAN.md`. Reach for
`docs/TESTING.md` when you want to check something and `docs/ARCHITECTURE.md`
when you want to know where a thing lives.

**To get from a clean machine to a running binary, start at `README.md` and
`CONTRIBUTING.md`** — the prerequisites, the disc extraction, the dump check
and the build command are only there, and none of the pages above will get you
a `gen/` directory. `README.md` is also where every environment switch is
documented; the port's own `--help` lists nine of them and points here for the
rest.

## State

`main` is pushed and CI is green. On 2026-09-22/23 the port went from the
opening to reaching the whole game by jumping, and every step is in
`docs/FINDINGS.md` section 11 with the frames that were opened to check it:

- **Warp by name to any of the 255 warpable maps** (the game's own warp, five
  pokes). Seven censuses loaded all 255 warpable maps -- 189 field maps and 66 ship-battle stages -- with no runtime fault.
- **Save and load** (PLAN B4, done): one word opens the game's save menu from
  any field; Continue reads it back. A run that loads a save reaches the field
  by frame 2800 instead of 14710.
- **The developers' part select** (`ME355A.SCT`) jumps to story parts B-L
  with the game's own flags and party; saves made at parts H and L start a run
  mid-story and near the end.
- **The ending** plays to "the End" with one poke and returns to the title.
- **A battle** can be forced, is fought and won, and returns -- faded in only
  where the story allows a battle, which is the game's rule, not a defect.
- `tools/sct.py` disassembles the field scripts that decide all of the above;
  `docs/research/` holds four read-only investigations it grew out of.

On 2026-09-24/25 the plan of record became `docs/PLAN-60FPS-MODS.md`, and
these of its slices are done, each with a FINDINGS entry of the same name:

- **The mod framework is in (M1-M5).** `SOA_MODS=<dir>` loads data-patch mods
  (`patches.txt`) and native `mod.dll` mods on a versioned API
  (`runtime/soa_mod.h`): guest memory with refusals, a safe point at the top of
  the main loop, map and scene callbacks, filters for the controller, the
  projection and textures, and `call_guest` into the game's own functions.
  `examples/mods/encounters-off` and `examples/mods/map-log` are the examples; `soa.ini`
  beside the exe starts the port without a terminal. An adversarial review
  found eleven defects in the layer, all fixed.
- **What speed costs, measured (H1-H6, H3, H11).** Drawn every frame the port
  runs 18-26 fps in heavy scenes; the logic is per frame, so 60 fps has to be
  interpolation (H2); every 3D draw matches the frame before it (H4); the
  guest could run the opening at 50 images a second and a battle at 104, the
  renderer draws them at 19 and 48 (H3). Idle render workers now sleep: the
  title costs 1.2 cores instead of 8.8 (H11).
- **A paced presenter (H8)** is built; the owner's display runs at 85 Hz, where
  30 fps cannot be paced evenly.
- **The in-between image works, offline (H10).** `--replay F F+1` renders the
  frame halfway between two captures. All five H4 pairs pass
  `tools/midpoint.py`'s seven checks and were judged by eye with no artifacts;
  the vertex history the live path must use is ARCHITECTURE section 12.
- **Textures are hashed once an epoch (H12)**, not on every lookup: prepare
  falls from 3.9 ms a frame to 0.21, and the cache holds 1,024. The saved
  time is throughput only with the clock out (+3.2%); at real speed the run
  waits at the drains instead, which is H14's to remove.
- **The drains around every copy are gone (H14).** The workers fence each
  other instead, the producer waits only for the one copy it reads, and one
  drain a frame recycles. Paced play is 10% faster where the port is not
  raster-bound (Part L 3000: 27 fps), because retraces now arrive on time; the
  Dangral base is raster-bound and gains 1%, which is H15's to change.
  `SOA_GXR_DRAIN=1` is the fallback if a scene draws wrong.
- **The pixel path is a quarter faster, and the pool bigger (H15a-c).** The
  TEV shapes and the blend most pixels use run directly, the helpers inline,
  about 59 -> 46 ns a fragment; the default worker count is three quarters of
  the CPUs. The Dangral base, 17.7 fps drawn every frame in H1, runs at ~27.
- **The heaviest field now runs at the 30 fps cap (2026-09-25).** Texture
  decoding is 80-90% smaller: decode walks tiles instead of dividing per texel,
  and a palette load re-hashes the textures it touches instead of throwing
  their decodes out (every one of 305,617 came back unchanged). **Copy
  images** (H14 step 6): a draw sampling a texture copied earlier in the frame
  takes an image the workers decoded as they copied, instead of waiting for the
  copy on the guest thread (+9% pooled). A filtered copy fences on its two
  neighbouring workers only. On a quiet machine the Dangral base runs at 29.8
  fps drawn every frame. FINDINGS "Palette loads", "Copy images", "Neighbour
  fences".
- **The guest thread has room, and a translator bug is fixed (H13 first
  steps).** The data-cache range calls are no-ops, paired-single loads skip
  `ldexp`, and `mtfsb` names the bit it should: the guest alone runs the
  Dangral base at about 125 images a second (+9%). FINDINGS "H13, first
  steps".
- **H15d has begun**: per-pixel counters out of thread-local storage and the
  bilinear blend in SSE4.1, -7% ns a fragment, every hash unchanged; the
  rasterizer's attributes in SIMD was tried and was no faster (FINDINGS). The
  host profiler now names inlined helpers and samples the guest thread.
- **Soaks are judged, not eyeballed (S1-S3):** `tools/soak.py check`, and an
  encounter accelerator that fights only where the story allows.
- **Most of the comfort pack is in (2026-09-25; `docs/PLAN-GAMEPLAY-MODS.md`
  milestone 1, specified in `docs/specs/comfort-pack.md`, ordered by
  `docs/PLAN-NEXT.md`).** Each slice has a FINDINGS entry of its name:
  manifest 2 for mods; the guard's T0 and T0c (card images and saves under
  any name, history read for content); the race seed (P6: `SOA_SEED`, and
  settings that change the game written into a recording); three shipped mods,
  `mods/encounter-rate` (P1a: `SOA_ENCOUNTERS=off|half|normal|double`, hold B
  for none), `mods/autotext` (P11 and P11b: `SOA_AUTOTEXT=on`, hold LB to
  skip) and `mods/coop` (P10b: `SOA_COOP=1`, a second pad chooses party
  slot 1's commands in battle), all built by `--link`; rumble (M18); host buttons and pad chords
  (CH1: View+LB fullscreen, and port 1 follows the pad to any slot);
  fullscreen, DPI, a resizable letterboxed window (H19a); a first run by
  double-click, with `soa.ini` at the repository root, relative paths and
  defaults under it, and the log in `build\logs\` (M5b); and the tools reading
  the disc image, so the 1.42 GB of loose files can go (I2:
  `extract.py --prune-loose`); a clock that survives sleep, with `unfocused =
  pause` (M19); `.gci` import and export (P3); a second pad for mods (P10a);
  the deflicker off for the display copy (P5b: `SOA_DEFLICKER=0`); and turbo
  up to 2x in battles and the sky (M11a: `SOA_TURBO`, View+RS), which reaches
  2x in a window only with M11a-skip, since drawn every frame a battle at
  turbo makes about 43 images a second here; and the picture's filters
  (P5a: gamma, colour-blind correction or simulation, a flash limiter;
  the `sharp` and `crt` scalers wait on `docs/specs/display.md`). `examples/mods/encounters-off` moved out of
  `mods/` for the slider. **Waiting on the owner (sessions A and B in
  PLAN-NEXT):** the pad rumbling in a battle; a pad in slot 1 or 2 playing;
  F11, Alt+Enter, the chord, resizing and the cursor in a window; a
  double-click with a real `soa.ini`; `unfocused = mute` on alt-tab; the
  prune itself; a Dolphin save imported and one exported back; turbo's
  feel; two pads through one battle with `SOA_COOP=1`; and whether the flash
  limiter should damp the opening's flight through cloud.
- **The audio plays at its rate (2026-09-25).** Until then every run fed the
  device 5% slow -- 189.8 blocks of 5 ms a second where 200 are due -- because
  the port took the game's once-a-block DMA length write as a restart. Fed at
  its rate, the device's 120 ms queue now drops a burst after a host stall
  instead of starving all the time (FINDINGS "The AI DMA's pace").
- **Recorded display lists run at recording (C5a).** The game records lists
  every frame and the port parses them as they are recorded, so every list
  called is empty; 28.5% of the opening's draws happen that way. C5b is the
  fix, bracketed by the list functions -- the logo screen draws through a
  redirected FIFO that is not a list (FINDINGS "Recorded display lists").

Nothing found so far would stop a person playing. Two things that looked like
it -- a black field after a battle and a trap on `a116c` -- were both the test
recipe putting the game in a state retail cannot reach, and are written up as
such. 1321 tests, the guard over the tree and over history, ruff, `decomp.py`,
the self test, `title --check` and the replay all passed before the last push.

**History holds 24 reviewed blobs under `scratch/`, on purpose.** An audit
found that commits of 2026-09-15/16 added files under a directory the guard
forbids (deleted since, still in published history). Each was read: analysis
scripts, a table of function addresses, an opcode census, and one frame's GX
command stream decoded to register writes and draw summaries, with no asset
bytes. Rewriting public history would have changed every hash the documents
cite, so they are exempt in `HISTORY_EXEMPT` in `tools/guard.py`, keyed by blob
as well as path, and CI now runs `guard.py --history` over every path any
commit ever held. Two stale git worktrees are left on the owner's machine
(`git worktree list`); removing one was refused by a permission prompt.

Since 2026-09-21 the renderer applies the EFB copy's deflicker filter (PLAN
C3) and `SOA_POKE` can write guest memory mid-run (PLAN D2's half). Before
2026-09-22 five field maps had ever been loaded by anything here, all of them by
the story or by losing a fight.

The port boots, plays the opening with dialogue, wins the first battle, and
is carried by the story through the Valuan ship's hold into `a101b`, where
it moves around with menus, a minimap and random encounters (the hold itself
has no encounter table; see wrong statement 8). It renders in a window -- at
about 30 fps in the heaviest field scene measured, the game's cap, when every
frame is drawn (FINDINGS "Copy images"; 18-22 in H1) -- plays music,
effects and speech, takes keyboard or gamepad input, and reads and writes a
memory card. Headless it runs about ten times real time.

| | |
|---|---|
| Functions recompiled | 7,144, 100% instruction coverage |
| Byte-matching decompiled symbols | 100 across 21 units (83 functions, 17 data) |
| Of those, running in the port | 12 |
| Python tests | 1321 |
| Self-test cases | 83 |
| Scenarios | 13 |
| Pinned frame hashes | 23 |

"100 matching" deserves its caveat: 65 are compared in full, and 35 carry words
the checker can only decide by linking, so it reports them separately and does
not count them as matches. Two data symbols have none of their four bytes
compared. Seven of the twenty-one units are fully verified; fourteen are not.
That is the oracle being honest rather than a defect, but do not quote the
round number without it.

## Ten things the history says that are wrong

Commit messages and older doc revisions are a record of what was believed at
the time. These were each corrected later, and re-deriving any of them would
cost you a day.

1. **"The searchlight beams render as near-black slabs and need a reference
   capture from real hardware."** They are bright, and have been since the
   texture use-after-free was fixed. No capture was ever needed. What remains
   is a texture-coordinate coverage question: no beam fragment samples a texel
   alpha below 176, so the sprite's fade never appears. `docs/FINDINGS.md` has
   the current reading.
2. **"The beams write depth and occlude the sky."** They do not. The game
   clears the depth-write bit across those 54 draws and the renderer honours
   it; narrating a beam pixel shows the depth buffer unchanged, and the cloud
   layer lands. Separately, a census of all 43,249 draws in the corpus found
   none that combines early depth testing with an alpha test that can reject,
   which rules out the other way this could have happened. No code changed.
3. **"The port is rasterizer-bound."** It is not. 47% of a run is spent in the
   *guest's* operating system idle loop, the console's own scheduler with
   nothing runnable, and the eight rasterizer threads are busy 8.8 seconds out
   of 830 seconds of available thread time. The renderer track in the plan was
   written on the opposite assumption; re-read any performance item against
   the profiler's numbers first.
4. **"The mixer silently discards the reverb."** No. The command in question
   is implemented now, and it is dead code in this title anyway: every
   reachable producer passes zero, so no run can reach it.
   The reverb is on the other auxiliary bus and works. That claim was invented
   and retired inside a day.
5. **"The voice bank never reaches audio memory"** and **"the zero voice-start
   count is a driver defect."** Both wrong. The bank uploads 262,464 bytes and
   the opening simply has no spoken line; the game does speak, later, and
   `config/scenarios/voice.scn` reaches one.
6. **"41 functions match byte for byte."** That number was true under an
   oracle that compared relocated instructions on six bits, so a call to the
   wrong function passed. The oracle is fixed; like for like the figure is now
   83 functions. The headline 100 adds 17 data symbols, which the old oracle
   never compared at all.
7. **"The EFB copy filter's seven taps are seven rows, so a white line leaves
   12/64 in its own row and 10/64 and 8/64 spreading three rows either side."**
   That was `docs/PLAN.md`'s acceptance criterion for C3 and it is wrong. The
   taps are vertical sub-samples — two for the row above, three for the row
   itself, two for the row below — so the game's weights are 16/32/16 across
   three rows and nothing lands further out. Note where the derivation has to
   come from: the SDK's filter-off set {0,0,21,22,21,0,0} kills the seven-row
   reading but is equally an identity under a *five*-row grouping that would
   give 8/8/32/8/8, and nothing in this tree separates them, because no caller
   ever reaches that arm. Patent US6999100B1 does. Re-deriving this from the
   register layout alone lands you back on seven rows, which is how it was
   written the first time.

8. **"A scripted run left the ship's hold and found a new map."** Nothing in
   this project has ever walked anywhere. Both traced runs follow the same
   story-driven chain `a299a` -> `a201a` -> `a200a` -> `a101b`, and
   `boot_field.log` had no stick input at all at those frames. The one map
   nothing else reaches, `a090a`, loads 1,540 frames after a random encounter
   and is followed by the title and a restart: it is the game-over screen, and
   the monkey scripts that reached it press only START, B, Z, X and Y and never
   touch the stick. Related: `encounter.scn` used to promise a random encounter
   from walking the hold, which is the one room of the five with no encounter
   table -- only `a101b` has a `.enp` and an `.ect`.

9. **"`scptInitial` is called only for stage 131e, so every other stage is
   black because its script never starts."** Written 2026-09-22 and wrong the
   same day. The state-7 arm calls it for *every* map: 131e gets it before
   `fn_8012A39C` plus 200 pre-run script ticks, and every other map gets it at
   0x80101A00, after state 8 is stored (r30 is still 0 there). The quoted
   disassembly stopped five instructions short of the second call. Whatever
   makes a picker warp black, it is not that gate.

10. **"A won battle leaves the field black because the player is never
   re-spawned."** Written 2026-09-23 and wrong within the hour. The capture it
   rested on was of a frame still on the results screen (field state 4), where
   there is no player yet; at state 8 the room is fully drawn under a screen
   fade that the map's script, in a story state where retail allows no battle,
   never lifts. A fade poke brought the room back. The port was never at fault.

The pattern behind all ten: a count or a description was read instead of the
thing itself. Every correction came from disassembling, tracing, or rendering
the frame and looking at it.

## What has already been tried and did not work

- Reaching the memory card format through a save point. Unnecessary: it is
  four button presses from a cold boot, through the title screen's card
  dialog. `config/scenarios/cardwrite.scn` does it.
- Scripting a START press before the title screen exists. The scene before it
  consumes that press to snap the logo flyover, which is what puts the title
  on screen, so the press always arrives one scene early. Repeat it.
- Waiting longer at the title for a menu. It times out after 92.267 seconds of
  *host wall clock* and drops into the attract demo, so more frames do not
  help and a faster machine gets further.
- Fixing a crash by changing the memory allocation. It hid it. For a
  layout-sensitive bug a run completing proves nothing.
- Forcing the field's state machine to a state you want. **The field only
  renders in state 8.** Poking the state word to 3 loads the map on top of the
  old one and every frame after is pure black; poking it to 1 parks it in
  state 2, the stage picker, which waits for a START nobody pressed. The one
  state worth poking is 15, and only with a warp name -- see the teleport
  below.
- Blaming that black screen on the state machine being stranded. It is not:
  the state word reads 8 again within 200 frames of a forced warp and stays
  there. The scene is simply empty -- max channel 0, one distinct colour, zero
  non-black pixels of 307,200. Measure the frame before theorising about the
  machine. And do not blame the route either: `a200a`, the map every stage
  select experiment warped to, is black through the game's own warp path too.
  Test a warp on a map the story has not already used.
- Hijacking the story's own warp by overwriting the destination before its
  frame-14710 load. Tried twice, at 50-frame and at 1-frame spacing over
  different windows. The map name is formatted before any window a frame-end
  poke can reach.
- Spoofing the script gate by setting the committed map words to 131/'e' after
  another map's geometry had loaded. There is no gate to spoof: `scptInitial`
  runs for every map, and 131e only gets it earlier (wrong statement 9). Do
  not run the every-frame version the previous handoff recommended.
- Poking START (0x1000) into `0x80311A4C` to force the resolver's file-check
  half. That word is the field's pad snapshot, not a flag, and the next pad
  read overwrites it; the field sat in state 2 for 1,600 frames showing the
  picker's one debug string, なし.

## How to drive the game, which is most of what was missing

`SOA_PAD` scripts are frame-keyed (`frame:buttons[@repeat][#hold]`, `+` for
chords, so all eight stick directions are expressible). Two things about them
cost this session runs, and both are cheap to know:

- **A menu waits for input forever.** Stop pressing A and the battle command
  wheel stays open indefinitely, which turns a blind script into an
  experiment: park it there, press one direction, photograph the label with
  `SOA_SNAP`, repeat. That is how the seven commands below were read.
- **Do not change `SOA_SPEED` and reuse a frame-keyed script** -- and do not
  blame it for a failure without isolating it either. A probe that stalled here
  was fully explained by its A presses running out mid-dialogue, with speed a
  confound that never got tested.

**The battle command wheel** is `fn_8007CAB0`, seven slots with no wrap:
0 Focus, 1 Magic, 2 S-move, 3 Attack (where it opens), 4 Guard, 5 Item, 6
Run. **A plain scripted `left` moves two slots**: `si.c` holds a press for
10 frames and the game's auto-repeat fires after 6, so every press measured
here moved twice -- which is exactly why the transitions in FINDINGS looked
like a ring that refused to wrap. Use `left#4` / `right#4` for one step.
`fn_8007A890` is the *Item* submenu, not the wheel; the "four entries versus
seven labels" disagreement was two different menus
(`docs/research/encounters.md`).

**Start a run from a save, not from New Game.** A save loads to the field by
frame ~2800 instead of ~14710. Make one once (on a *copy* of the card --
never `build/cards/slotA.raw`):

```
mkdir build/savetest; cp build/cards/slotA.raw build/savetest/card.raw
python tools/scenario.py run battle --frames 16600 --log build/scenario-save.log \
  --env SOA_CARD=build/savetest/card.raw \
  --env SOA_POKE=15000:0x803473B0=0,15000:0x803473B4=1 \
  --env SOA_PAD=<the battle preamble to 14850>,15300:a,15450:a,15600:a,15750:a,15900:a,16050:x,16200:x
```

`0x803473B4 = 1` is the request a save point makes; it opens the game's own
save menu in any loaded field. Then every later run copies that card and
boots with `1600:start,1640:a,1800:start,1840:a,2000:start,2040:a,2240:a,2440:a,2640:a`
-- the last three walk the load menu -- and is standing in the saved map by
2800. **Do not press A after the load**: the save point is right there and A
opens it. `build/savetest/card-saved.raw` on the machine that wrote this is
such a card (a101b, part A).

**The developers' part select is on the disc.** Warp by name to `ME355A.SCT`
(`0x4D453335 0x35412E53 0x43540000`, then 15) and an officer asks what you
want; pressing only A reaches 《どうする？》「Bパートへ」「Cパートへ」「へ」,
the first of six pages (B/C, D/E, F/G, H/I, J/K, L), each with "next" as its
third choice. A choice runs the game's own routines for every earlier part --
the watch shows flags 1-23 set in story order -- fixes the party with JOIN and
LEAVE, and warps: B to Pirate Isle (`002b`), H to Esperanza (`018a`), L to the
world map (`a099o`, from which the story carries the run into the Dangral base,
`126a`). **Each page is two steps**: 《どうする？》 first appears as a message box
waiting for A, and only then do the choices come up -- downs sent to the box
are ignored, which is how two attempts at L landed on H. So per page: A, then
`down#4`, `down#4`, then A (the B/C page's box is already dismissed by the
A presses that reach it). The generator for L's pad is in FINDINGS;
`build/savetest/card-part{C..L}.raw` hold saves made right after arriving at
ten points of the story (FINDINGS has the generalised pad). `docs/research/story-flags.md` has what each part sets.

**`SOA_POKE` is a read primitive as well as a write one.** Every poke prints
the value it replaced, so poking a word with its own value traces it across a
run. That is how the field state was shown to return to 8, and it needs no
tracepoint and no recompile -- which matters, because tracepoints are compiled
in and cost a full retranslation. **`SOA_WATCH=addr` is better for a word
that changes**: the compare is inlined into every translated store, so it too
needs no rebuild, and it prints every store with the storing code's lr and a
guest backtrace (the first 201). On the field state `0x80311AEC` it prints
every transition of every warp, which is how the teleport below was found.

**The teleport works** (2026-09-22). It is the game's own warp, driven by
name: write the destination's script file name into `0x80305CF0` and put the
field in state 15. State 15 tears the old map down, parses the name into the
map words and restarts the field, which then takes exactly the path every story
warp takes (15, 0, 1, 3, 5, 7, 8). To `a103a`, with the letter in the **top
byte** of `0x80311AC8`:

```
SOA_POKE=16000:0x80305CF0=0x4D453130,16000:0x80305CF4=0x33412E53,16000:0x80305CF8=0x43540000,16000:0x80311AEC=15
```

That is `"ME10" "3A.S" "CT\0\0"`, then the state. **Also poke
`0x8030E420=0` with it**: that is `sys[15]`, "the map the party came from",
which the game's own warp request sets and a poke does not, and maps choose
their entrance by it -- left at 20000 after a Continue, it sends a map down its
"loaded from a save" branch, which crashed `a116c`. 0 takes the default
entrance. **Do not also poke
the map words** (0x80311AC0/AC4/AC8), as the census runs of 2026-09-22 did:
the teardown reads them before the name is parsed, and for a 5xx destination
that runs a ship-battle teardown for a battle that never happened and puts a
spurious Exp/Gold screen up. The name sets all three. No button press is needed. It needs a run that has already reached the
field, which the `battle` scenario's preamble plus an A every 150 frames does
by about frame 14710; `build/run_namewarp.log` has the whole command. `a103a`
-- the first dungeon island, never reached by any run before -- draws its
first frame 100 frames after the poke and plays its own arrival scene. The
game zeroes the name's first byte after reading it, so poke all three words
for every warp: five pokes a warp, 51 warps a run.

The older stage-select route (`0x80311AEC=2` and a START) is the resolver's
debug path; it skips the teardown and state 0's init. Do not use it.
`r13 = 0x8034E720`, so every `-N(r13)` in a disassembly is `0x8034E720 - N`.

## If you change the renderer

Run `python tools/scenario.py replay --threads 1,2,3,8` afterwards. It takes
about 17 seconds and it is the only thing that will tell you a pixel moved.

A moved hash is a question, not a failure — but re-blessing is something you
do after opening the frame and deciding the new pixel is right, never to make
a check go green. That mistake cost a day: the manifest was first created from
a render nobody had looked at, so eight of twenty-three frames pinned
washed-out colour and a correct fix would have failed the suite.

## Where the last session stopped (2026-10-04)

Everything below this section is older and still true. Landed in the last
stretch, newest first, each with a FINDINGS entry of its name: **L6**
("L6": `plat_f2i`, the bilinear weights, CORE-MATH's `exp2f`/`log2f`; every
leg draws the same pixels and the same libm bits); **L7**
("L7": `plat.c`'s cold half; the MEM1 guard and the guest's 32 MB stack
off Windows, run by CI's three Linux legs); **L1**
("Wine": the port under Wine 10.0, all three checks); **L3b**
("clang-cl": the game under a second compiler, 23/23); **L8** (the
queue on ARM64 and under TSAN; three races fixed); **L4b** (CI's
Linux leg under gcc and clang; the native units' 32-bit words); **L2** (two
commits: the queue's seq_cst helpers and the grep test, then the renderer
building for Android); **C5c** (the corpus re-captured, matched to its old
moments and blessed after the owner's look); **C5b**; **L4a**
(CI's fifth job, `clang-cl`: the three citest scripts and the two
clang-sensitive pytest modules under LLVM's clang-cl, where a skip fails the
run; L2a's guard reverted turns it red); **L2a**
(`runtime/plat.h`, the SIMD blend in every x86-64 build, `perfbench --exe`;
clang-cl now compiles every runtime file); **L3a's review** (cee8a5b,
seventeen findings fixed); **L3a**
(toolchain profiles, `--cc clang-cl` into `gen/clang`); **P10b** (couch
co-op, `mods/coop`, f740207); **P5a** (gamma, colour blindness, the flash
limiter, 5237e2e, with f8ec2c1 fixing its red CI); **M11a** (turbo, 79bec43);
**the AI DMA's pace and M19 followed up** (2169a6f: the audio had played 5%
slow in every run).

**The state at the stop (2026-10-02, after L6):** C5c (9ccef87), L2
(dd87a59, b736cb0), L4b (a2c7c21), L8 (8a0188a), L3b (5783358), L1
(56ecb9a), L7 (664a524) and L6 (with this section) are pushed; read CI
for the last. `build/soa-L6base.exe` is the build before L6, kept for
perfbench comparisons. The owner plays
`gen/clang/soa.exe` (D-15); MSVC stays the tools' default and the build that
pins the hashes. Docker Desktop is stopped; the `soa-wine:l1` image, with no
game data, is kept for the next Wine run; L7's local gcc runs used
throwaway `python:3.14-slim` containers and kept nothing. `gen/soa.exe` (MSVC) and
`gen/clang/soa.exe` (the NDK's clang-cl) are both linked at L6 and both draw
the 23 frames identically. The branches
`l4b-linux`, `l4b-mutation`, `l8-tsan-arm`, `l8-mutation`, `l7-posix`,
`l7-mutation`, `l6-determinism` and `l6-mutation` stay on origin,
as L4a's do, because FINDINGS links their runs. Nothing is running.
`build/fifo` is the **new** corpus, 23 captures with `PROVENANCE.tsv` (the
run and frame each came from); the old one is `build/fifo-pre-c5/`, intact,
and is as irreplaceable as `build/fifo` was. C5c's scratch captures are
deleted; its scripts (`build/c5c-*.sh`, `build/c5c-*.py`) are kept, and
FINDINGS "C5c" holds the recipe. `build/perfset-c5/`
holds H4's five pairs re-captured after C5b, and `build/midpoint-c5/` their
images. The working tree is clean but for `.claude/worktrees/`, an old
agent's worktree that is not this session's.

**The owner set the goal and the order on 2026-09-30** (PLAN-NEXT §0, which
overrides the older order): play on any Windows or Android device, meaning
x86-64 PCs and handhelds (this machine is a ROG Ally X), the Steam Deck, and
Android flagships and handhelds (Snapdragon 8 Gen 2 or newer). Vulkan, SDL3
and a build-time shader compiler are allowed. The order: the picture fix,
then the Android path, then 60 fps and the disc layer. The picture fix (C5b,
C5c) is now done.

**Pick up here, in order:**
1. ~~C5b~~, ~~C5c~~ -- done (FINDINGS "C5b", "The shadows were drawn out of
   order", "C5c"). The green blob and teal bands were the characters'
   shadow volumes run when recorded; they are shadows now. The searchlights
   are beams. Nothing was removed. The owner looked at all 16 changed frames
   and the corpus is re-blessed. Two things learned that the next capture
   needs:
   - **A frame number no longer names a moment.** The guest clock follows
     host time, so a faster renderer reaches each moment at another frame.
     To re-capture a frame, capture a window of consecutive frames and keep
     the one closest to the old render (`build/c5c-match.py` is the
     pattern); a battle may take another course entirely.
   - **`SOA_GX_DLLOG` stops after 400 lines** (`DLLOG_LINES`), a line a
     call, and the opening makes 2,746 calls by frame 1000, so it cannot
     speak for a late frame.
2. **The Android path,** in PLAN-NEXT §0's order: M4a (~~L2~~, L4b, L8, L3b,
   L1), M4b (L7, L9, L6), then M5 (the GPU spike and the gate), then V5+ and
   the Android shell. **L2, L4b and L8 are done** (FINDINGS "L2, step 1",
   "L2, step 2", "L4b", "L8"): `plat.h` holds the atomics, waits, clocks and
   threads; `runtime/*.c` and all of `gen/*.c` compile for Android with 0
   errors; CI runs the citest checks under gcc and clang, on ARM64, and the
   queue under ThreadSanitizer with no race and no suppression; and the
   four-worker frame hash is the same on Windows, x86-64 Linux and ARM64.
   **L3b is done too** (FINDINGS "clang-cl"): the whole game builds with the
   NDK's clang-cl in about 90 s and draws the 23 frames exactly as MSVC does;
   its renderer is 10-13% faster a fragment and its guest ceiling 14% higher
   pooled. **L1 is done** (FINDINGS "Wine"): under Wine 10.0 in a container
   the self test, replay 23/23 and `title --check` pass, run from a copy of
   the exe because Wine faults on it straight off the Windows share. That
   ends M4a. **L7 is done** (FINDINGS "L7"): `runtime/plat.c` holds the
   cold half. Off Windows the MEM1 guard is a SIGSEGV handler and the
   guest runs on a 32 MB thread, and CI's gcc, clang and ARM64 legs run
   `test_memguard.py` and `tools/citest/threads_check.py` on every push.
   **L6 is done too** (FINDINGS "L6"): `plat_f2i`, the bilinear weights'
   fix the spec missed, and CORE-MATH in `runtime/crmath.h`. MSVC,
   clang-cl, gcc, clang, ARM64 and TSAN all draw the pinned out-of-range
   frame and print the pinned libm hashes. **Next is M5,** by the owner's
   answers (PLAN-NEXT section 0); L9 waits until I1 and I3 have landed in
   its files. The owner answered M5's questions on 2026-10-02: D-19 yes
   (a tolerance-judged GPU picture, the CPU renderer the reference) and
   D-20 yes (three to four weeks of evenings); D-17 and D-18 were
   settled by section 0. **V0 is done** (FINDINGS "V0"): `tools/imgdiff.py`,
   its thresholds frozen by mutations, with a filter test added because
   3.12's metric passed a one-pixel shift and a second vertical blur.
   The references are in `build/gpu-oracle/ref/` (corpus and perfset).
   **V1 is done** (FINDINGS "V1"): `build/gpuset` holds a random battle's
   start, whose screen-to-texture copy also showed the renderer ignored a
   copy's destination stride, fixed in 2d48bbe (FINDINGS "The battle
   transition"); and a mask-effect frame. Captures with copies must be
   made with `SOA_RENDER=1`. **V2 is done** (FINDINGS "V2"):
   `runtime/gxr_cmd.h`, the backend hook at the three points the producer
   runs a command itself, `SOA_GXR_INLINE`, the passthrough backend,
   copy clears as their own commands, `tex_id`/`tex_gen`, and H17a's
   `DrawCmd.efb`. **V3a is done** (FINDINGS "V3"): `tools/fetch_gpu.py`
   fills `vendor/` (pinned, gitignored) and `tools/gpuspike.py selftest`
   draws 15 scenes through `gxv.c` (now `runtime/gxv.c`) on this machine's GPU and
   on the CPU. Away from edges the coverage is exact, and colours are
   within one step where they are interpolated. Thirteen mutations turn it
   red; hardware colour rounding is the one difference nothing here can see.
   `vendor/` (27 MB) can be fetched again at any time; `build/gpuspike/<compiler>/`
   holds the spike and its last scene images, CPU and GPU, to open.
   **V3b is done** (FINDINGS "V3"): `tev.glsl` (now in `runtime/gxv/`) and
   `copy.comp` give `tev_pixel`'s and `copy_to_texture`'s bytes exactly --
   `gpuspike.py tevdiff`, 100,000 random setups, and `copydiff`, 25,600
   random copies, both with 0 mismatches and each Done mutation red -- and
   gxv now makes every EFB copy with `copy.comp`. **V4a is done** (FINDINGS
   "V4"): the GPU draws the game's frames -- `tev.glsl` and the sampler in
   the fragment stage, fog, the alpha test, blending -- and all 21 captures
   without a copy to a texture pass V0 against the CPU on the first run
   (`gpuspike.py oracle`). Two results are for the owner and the gate: the
   LOD +1 mutation passes V0 on the sky pair though the ship is visibly
   blurrier (a V0 blind spot, listed), and the alpha mutation applies on 3
   captures, not five. **V4b is done** (FINDINGS "V4"): all 67 captures on
   the GPU, the copy captures poisoned; 65 pass V0 and the Dangral base
   pair fails by design (the CPU's span-stepped depth drifts, and the GPU
   is the one that agrees with exact arithmetic); logic ops are exact three
   ways; every copy's RAM difference traces to the EFB; the battle
   transition chains. The spec's section 8 holds the numbers. LOD +1 is
   V0's one blind spot, three distinct frames. **The gate answered A,
   Vulkan,** on 2026-10-03, after the owner judged the five side-by-sides
   right (PLAN-NEXT §0, with D-26 and D-27). **V5's `loddiff` is done**
   (FINDINGS "V5, first"): the exact level-of-detail check the owner chose
   for V0's blind spot, 0 mismatches, each mutation red; its first run
   found the GPU's division one ULP out and lod.glsl now divides exactly.
   **The backend is in the runtime** (FINDINGS "V5, second"):
   `runtime/gxv.c` and `runtime/gxv/`, which `--link` builds in when
   `vendor/` is filled, a stub otherwise, with every image the spike
   writes unchanged by the move. **V5 is done** (FINDINGS "V5"):
   `SOA_GPU=vulkan` draws the game on the GPU in `soa.exe` itself, the
   same pixels as the spike on all 67 captures (`gpuspike.py contrast`),
   and `title --check --env SOA_GPU=vulkan` holds five invariants, the
   fifth that the GPU drew everything the renderer sent it. The 3.4
   tripwire that fired in the title is answered (FINDINGS "V5, after"):
   the fade quad at alpha 1.0, every frame 1290-1400 passing V0. Compare a
   running game with `gpuspike.py live <scenario> --range A-B`, never
   unseeded and never by snapshots of an undrawn stretch: guest time
   follows the host, and the opening's clouds differ CPU against CPU
   without `SOA_SEED`. **V6a is done** (FINDINGS "V6a"): the GPU draws on
   a thread of its own, every picture unchanged, and on Part L takes 1.1
   CPU cores where the CPU renderer takes 4.8, both at 28.9 fps; the
   budget run is `partl` (a copy of `card-partL.raw` by `--env SOA_CARD=`).
   **V6b is done but for the owner's session** (FINDINGS "V6b"): the copy
   hazards hold with the GPU as consumer (`gpuspike.py overlap`, its
   oracle the GPU's own synchronous run), and `title` and `battle` hold
   5 of 5 with `SOA_GPU=vulkan`. The owner's fifteen windowed minutes from
   a part-select save are open (the owner chose later, 2026-10-03).
   **V7 is under way**: the pipeline cache on disk landed first (FINDINGS
   "V7, first"), then pipelines specialised by TEV shape, made on a
   compiler thread while the interpreter draws (FINDINGS "V7, second":
   the GPU's time on Part L down 3.6 times at the median), then copy
   images in the GPU's pool and copies landing behind gxr's `g_landed`
   (FINDINGS "V7, third": Part L's 670 copies take 281-286 waits, not
   670). **V7 is done but for one line** (FINDINGS "V7, fourth"): the
   soak's second launch meets the 20 ms budget; the first stalls 26-30 ms
   four times, on interpreter pipelines the driver had never compiled.
   Pipeline libraries, the usual cure, made this AMD driver draw nothing
   once enabled and were backed out; a validation layer is what would say
   why. `gpuspike.py specdiff` checks that specialised and interpreted
   draw the same bytes, `copyimage` a copy sampled in its frame;
   `overlap` is the one to run after touching the landing. The
   distribution route is specified (specs/distribution.md, R1-R5; its
   Q-D1, the bundled compiler, waits for the owner before R1). **V8 is under
   way:** the GPU presents to the window through a Vulkan swap chain
   (FINDINGS "V8, first"; `gpuspike.py present` holds the shader to
   `picture_scale`). **V10 is done** (FINDINGS "V10"): without
   `logicOp` each logic draw is routed -- a snapshot for a quad, the
   interlock where it may overlap itself -- and `SOA_GPU_FEATURES=core`
   gives the oracle's verdicts unchanged. V7's first-launch stalls in play
   fell from five to one with cull, topology and depth as dynamic state
   (FINDINGS "V7, fifth"). **The owner answered four questions on 2026-10-04**
   (PLAN-NEXT §0): llvm-mingw may be fetched (R1 may start), V9 is split
   (2x/3x now as V9a, the wide EFB after M10), the Vulkan SDK is installed
   (`SOA_GPU_VALIDATE=1` now prints the layer's messages; the whole GPU path
   is clean, FINDINGS "The validation layer, installed"), and the owner
   will set 60 or 120 Hz for the windowed sessions. **V9a is done but for
   the owner's look** (FINDINGS "V9a"): `SOA_GPU_SCALE=2|3` draws into an
   EFB two or three times the console's, each copy run once per sample
   phase, so at 3x every native pixel's centre sample is held to V0
   (`gpuspike.py oracle --scale 3`, 65 of 67 with the by-design pair the
   same) and must equal `g_screen` exactly; `copydiff`, `copyimage` and
   `present` take `--scale` too. A copy sampled after its own submission is
   still the native image. **V8b is done** (FINDINGS "V8b"): P5a's filters
   are a GPU pass at the size the GPU drew, byte for byte `picture.c`'s
   (`gpuspike.py present --filters`), the flash limiter deciding its blend
   on the CPU. The owner's windowed session (V6b's fifteen minutes, V8's
   presenter, V9a's 2x and 3x) was set up on 2026-10-04 and put off by the
   owner; it wants the display at 60 or 120 Hz (it is still at 85), and
   View+LS marks a frame. The GPU build is done but for what waits on
   others (that session, M8's overlay, V9b after M10, V12 after H17).
   **R1 is done** (FINDINGS "R1"): `python tools/fetch_mingw.py`, then
   `recompile.py --cc mingw --compile --optimize --link` builds
   `gen/mingw/soa.exe` with nothing of Microsoft's, its guest `fma` inside
   the exe (`runtime/soafma.c`), and it passes the self test, the replay,
   `title --check` and the GPU contrast; CI compiles every runtime file with
   the pinned llvm-mingw. **R2 is done** (FINDINGS "R2"):
   `tools/player_build.py --disc <image> --root <folder>` builds a folder
   that plays with nothing of Microsoft's, from `tools/package.py stage`'s
   package too, with `PATH` bare; the exe is the same byte for byte in any
   folder, and a changed `cpu.h` retranslates. **R3 is done** (FINDINGS
   "R3"): `tools/package.py --out` zips the package (129 MB),
   `guard.py --tree` holds it to the package's rules, and
   `.github/workflows/release.yml` (`gh workflow run release.yml --ref
   main`) tests, packages, guards and leaves a draft release for the owner
   to publish; its zip, downloaded, builds the game here byte for byte.
   **R4 is built** (FINDINGS "R4"): `Setup.exe` at the package's top
   checks the folder, builds from the chosen disc with no console window
   (a progress bar, a log pane, `build\setup.log`), and Play starts the
   game. From this tree's zip it reached the title screen with no console
   window opening, and a watcher saw both of the mutation's consoles. The
   owner's run on the Ally X (the dialog, a real player's folder) is R4's
   second Done line and joins the windowed session. **I1 is done**
   (FINDINGS "I1"): `runtime/disc.c` owns the disc, `gen\soa.exe <your
   .iso>` runs with no copy, an image that is not this port's (game id,
   revision, the executable's SHA-1) is refused by name, no image stops
   the run naming `extract.py`, and `tools/citest/disc_check.py` holds
   disc.c to a synthetic image in CI. **I3 is done** (FINDINGS "I3", after
   the owner's D-5 yes on 2026-10-05): `soa.exe` carries the player's
   executable, boot.bin and file table (`gen/disc_sys.c`; never share
   the exe), the self test and replays open no disc, an image whose
   table is not the build's is refused, and `--link` refuses chunks
   compiled from another executable. **I4 is done** (FINDINGS "I4"):
   `extract.py <dump> --store` writes `GEAE8P.soadisc`, checked block by
   block and judged against `config/GEAE8P/disc.yml` (pinned 2026-10-05,
   Redump's image hash, the owner approving); the owner's disc is "a
   verified dump". **I5 is done** (FINDINGS "I5", without I5a: the
   implementation session kept today's disc timing): the port reads the
   store, preferred in a folder, each 64 KiB block hashed at first touch
   (a damaged one stops the run, exit 9, naming the file);
   `SOA_DISC_VERIFY=iso` proved it against the ISO over title and hold;
   `soa.exe --check-disc` checks a copied store whole. **Next:** L12,
   the Android shell, to be specified in full (portability.md's L12 is
   an outline), with R5 beside it. Still open for the owner, and not blocking: whether a
   Steam Deck or Linux PC exists for the optional Proton session. `tools/citest/queue_check.py` (16 s) is worth a run
   after any change to `gxr.c`'s queue. Two
   habits from L2: compare `gxr.c`'s queue in the `/FA` listing against the
   base, after taking the base listing before any edit; and read a whole
   compile's output, not its tail (L2's first commit shipped two C4273
   warnings that way). The clang-cl here is the NDK's: `$env:SOA_CLANG_CL =
   'C:\Users\bmfre\AppData\Local\Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin\clang-cl.exe'`,
   and for the pytest modules put that `bin` on `PATH` too (the second FMA
   probe looks for `clang` there). CI's is LLVM's 20.1.8, and its clang-cl
   job now runs on every push, so a change that breaks clang shows there.
3. **Gap fillers, as each unblocks:** **H20** once the planning session
   (soa-b4) sends its Done; **M11a-skip** once its spec lands (turbo is
   about 1.4x in a window until then); `docs/specs/display.md`, which now
   owns P5a's presenter budget -- p99 10.08 ms fullscreen at 3440x1440
   before any filter, against 6 ms; and P1b, once a card in a rate-20 zone
   exists.

**Done in this stretch, for the record:** L3a's review (seventeen findings,
none in what MSVC builds; most were tests a wrong plan passed); L2a (MSVC's
pixel path measured unchanged; Android's x86-64 target has SSE4.1 on, so one
Done line needed a second compile); L4a (green on the branch `l4a-clang-cl`,
red on `l4a-mutation` with L2a's guard reverted, both before the merge; the
two branches stay on origin because FINDINGS "L4a" links their runs).
`ci.yml` runs on push only for `main`, so a branch is checked with
`gh workflow run ci.yml --ref <branch>`, built in a scratch worktree rather
than by switching this shared checkout.

**Traps met in this stretch, each now in the author's memory too:** a check
chain piped through `tail` hides a failing step -- run it under
`set -o pipefail` and read CI after each push; `sed -i` in Git Bash turns a
CRLF file in `runtime/` into LF; a Bash heredoc mangles `\n` inside embedded
Python; never `git commit --amend` here, another session commits to main.

## What I would do next

**What is next, in order, is `docs/PLAN-NEXT.md`** (2026-09-25).
PLAN-60FPS-MODS.md and PLAN-GAMEPLAY-MODS.md keep the slices.
`docs/PLAN-60FPS-MODS.md` (written 2026-09-24) holds 60 fps by renderer
interpolation, then a native mod framework (data patches, a safe point,
`mod.dll` with a versioned API), targeted decompilation only where a mod
needs it, and a soak programme with checked invariants. Each slice's line
there says whether it is done and where its evidence is. Done by
2026-09-24: **H1** (drawing every frame runs 18-22 fps),
**S4a** (`SOA_PEEK`), **H2** (the logic is per frame, so 60 fps is
interpolation), **H4/H5** (every 3D draw matches its predecessor), **H6** (a
pinned benchmark set, 85.4 ns a fragment), **S2** (guard suffixes), **S1**
(`soak.py check`), **H3** (`[frametime]`; the guest could run the opening at
50 images a second and a battle at 104, the renderer draws them at 19 and 48,
and 8 workers burn 8.4-8.9 cores at any load), **S3** (the encounter
accelerator fights only where the story allows), **M1** (`SOA_MODS`, data
patches; `examples/mods/encounters-off` stops random battles) and **M2** (`tick.c`: a
safe point at the top of the main loop, and `SOA_UNCAP=N` lets the frame end's
spin go after one field), **H11**'s workers' half (idle rasterizer workers
sleep: the title costs 1.2 cores instead of 8.8, at the same fps measured
interleaved) and **M3a** (native `mod.dll` mods on `runtime/soa_mod.h`;
`examples/mods/map-log` is the template), **M3b** (`pad_filter`: a mod decides
what the game reads) and **M3c**'s projection filter (a wider view, checked on
the 23 pinned captures under `--replay`, which loads mods) and its texture
provider (any texture replaced by content hash, at any size), and **H10** (the
offline midpoint: right in all five pairs, by `tools/midpoint.py` and by eye;
positions only, so colour and texture animation steps at 30 Hz, slightly).
**H12**, **H14** and **H15a-c** are done too (texture hashing once an epoch;
fences instead of drains around copies; the pixel path a quarter faster; 12
workers by default; FINDINGS "H12", "H14", "H15c"), and the Dangral base runs
at about 27 fps drawn every frame. Texture decoding is 80-90% smaller since
(palette loads no longer throw decodes out; FINDINGS "Palette loads"), and
the frame rate did not move: what held the frame was a draw sampling a
texture copied earlier in the frame, waiting on the guest thread for the
workers to finish everything before that copy. **Copy images** (the plan's
H14 step 6) took that wait away -- the copy's texture is decoded by the
workers as they copy, the sampling draw fenced in the pool -- and the Dangral
base went from about 26 to about 28 fps (+9% pooled over two interleaved
A/Bs; the median frame 36.4 -> 33.9 ms; FINDINGS "Copy images"). A filtered
copy now fences on the two neighbouring workers only (+3.5% with the clock
out; FINDINGS "Neighbour fences"), and turning the one-drain-a-frame gate off
was tried and was worse (the guest ran frames ahead into the ring). On a
quiet machine the Dangral base now runs at the cap, 29.8 fps. So 30 fps at 1x
is there in the heaviest field; what 60 needs is the render ceiling, since
H17a draws twice as many images: H15d (SIMD spans) for the workers -- its
first step, the per-pixel counters out of thread-local storage and the
bilinear blend in SSE4.1, is -7% ns a fragment with every hash unchanged;
the TEV's general path is next, for the sky and ship scenes -- then
H16 and H11's other half (the guest idle loop still spins on one core). The
guest thread has room: alone it runs the Dangral base at about 125 images a
second, +9% since H13's first steps (the cache calls as no-ops, paired-single
loads without `ldexp`, and an `mtfsb` translation fix; FINDINGS "H13, first
steps"). M4 (`call_guest`) is done, and M5,
`soa.ini` beside the exe, is done but for the owner's check. **H8**'s presenter is built (DXGI flip model);
the owner's display runs at 85 Hz, where 30 fps cannot be paced evenly -- set 60 or 120 Hz first. It needs the owner at a window for
fifteen minutes whenever convenient. **Measure speed interleaved**: this
machine drifts 15% within a session on identical code (FINDINGS "H11"). The
live title is no frame-hash oracle -- two unmodded runs differ on 22 of 40
snapshots -- so visual checks go through `--replay` (FINDINGS "M3c").
`docs/PLAN-GAMEPLAY-MODS.md` (2026-09-24, from a planning session) plans the
gameplay mods and content that build on this API. The list below still stands
beside it.

The question this project was stuck on for a week -- can anything reach the
rest of the game -- is answered: every warpable map has loaded, the story's
parts, the world map, ship battles and the ending all run, saves round-trip,
and twelve twenty-minute soaks of random play from ten story points (C to L)
ran clean, walked through exits, fought and lost into the game-over screen,
and loaded 20 of the disc's battle-effect packages (3 before). Nothing found so far would stop a person
playing. What is left is depth, and a person playing is now the best test.

1. **Play it.** Windowed, with a pad (`README.md`), from a part-select save.
   Every defect this project has found in two days was found by looking at
   what the game did; a human session covers more of it in an hour than a
   script does in a day. Keep `SOA_PAD_RECORD` on, so anything that breaks
   can be replayed headless.
2. **Soak where the fights are.** `tools/soak.py --battle` turns the wheel to
   random commands; soak saves in dungeons with encounter tables (FINDINGS
   lists the 35 maps that have one) rather than towns, under `SOA_STRICT=1`.
   A fault it finds replays from its seed.
3. **Battles past Attack.** Items, Focus and S-moves in a story state that
   allows the fight (set the alarm first on `a101b`, or use the H/L saves);
   single-step presses more than 60 frames apart.
4. **Speed** (plan C4, now H in `docs/PLAN-60FPS-MODS.md`). H1 measured
   17.7-22.3 fps drawing every frame in heavy scenes; an older windowed run
   measured 26.7 game frames a second
   against the game's 30; read the profiler first (wrong statement 3).
5. **The decompilation grind** (Track F). Two SDK libraries are complete; the
   match oracle is sound.

The deflicker filter, which this list used to name as the largest understood
fidelity gap, landed on 2026-09-21 and is no longer one. Do not take that as a
claim that the port is now pixel-exact with a console: it removes the one
mismatch that was *fully* understood, and the untested ones are simply
untested. Its entry in `docs/PLAN.md` is worth reading before any other
renderer work, because both defects it turned up were in the queue protocol
rather than in the arithmetic, and the second one appeared only on the fourth
consecutive sweep.

I would not spend more time on the searchlights. They have had four rounds,
each overturning the last, and what is left is cosmetic and well documented.

## Things that will bite you

- `ruff format --check` is a separate command from `ruff check`. 23 commits in
  this project's history were pushed red for exactly that.
- A change to `runtime/cpu.h`, `config/trace.txt` or `config/hle.txt` needs a
  full retranslation, not a relink. Tracepoints in particular are compiled in,
  so adding one and running without rebuilding shows nothing and looks like
  the tracepoint is wrong.
- `build/fifo` is a precious, gitignored corpus that cannot be regenerated
  cheaply. A capturing run must set `SOA_FIFO_DIR` elsewhere. Three streams
  were lost to this once.
- The game's own decompiled code lives in `src/soa/`, never `src/game/`: both
  the ignore rules and the guard treat any path segment named `game` as game
  data, and several units silently went uncommitted because of it.
- **Most tracked files here are CRLF and `sed -i` rewrites them to LF.** There
  is no `.gitattributes` and `core.autocrlf` is false, so git stores the
  change: a six-hunk edit to `docs/PLAN.md` committed as 896 insertions and 896
  deletions, which destroys the diff and `git blame`. Check
  `git diff --numstat` after any bulk documentation edit -- if the line count
  equals the file length, that is what happened. `tools/guard.py` is one of the
  few LF files, so do not assume either way.
- **The renderer links on its own, and that is load-bearing.**
  `tools/citest/render_check.py` and nine `test_gxr_*` modules build `gx.c`,
  `gxr.c`, `gxr_tev.c` and `png.c` with two stubs and no `main.c`. A call added
  from `gx.c` into `main.c` compiles cleanly and breaks 29 tests at the link
  step, which the compile-only CI job cannot see. Hang new per-frame work off
  `gx_set_frame_hook` instead.
- **`gen/soa.exe` can be older than `runtime/`, and nothing says so.** The
  binary every experiment of 2026-09-21/22 ran on was linked before commit
  1bad9fb raised `SOA_POKE`'s limit from 64 to 256, so the "256-item budget"
  in the docs was false on this machine for a day. After pulling runtime
  changes, `python tools/recompile.py --link` (20 s) before trusting a run,
  and read the `[poke] N poke(s) armed` line.
- **A `run_*.log` has no trace lines in it.** `scenario.py run` echoes a
  summary to stdout and writes the whole log, `[trace]` and `[watch]`
  included, to `build/scenario-<name>.log` -- which the next run of the same
  scenario overwrites. Pass `--log build/scenario-<experiment>.log` so the
  evidence survives; the 131e load trace was lost that way.
- **Probing line endings with `grep $'\r'` in Git Bash is unreliable** -- it
  called three CRLF files LF on 2026-09-22. Ask Python:
  `open(f,'rb').read().count(b'\r\n')`. Appending with a heredoc to a CRLF
  file adds LF lines, which `ruff format --check` then flags.
- **`tools/disasm.py` does not track update-form loads in its annotations.** At
  0x801019C0 it labels `lbz r0, 8(r3)` as `@ 0x80310008`, but the preceding
  `lwzu` had already moved r3 to 0x80311AC0, so the byte is at 0x80311AC8. Do
  the arithmetic rather than trusting the comment.
