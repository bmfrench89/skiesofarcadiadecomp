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
such. At R5b, 1516 tests, the guard over the tree and over history, ruff, `decomp.py`,
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
| Python tests | 1981 |
| Self-test cases | 87 |
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

## Where the last session stopped (2026-10-27)

### Start here (for the next session)

**State.** `main` holds the event track's spec, E1 and E2 (2026-10-24 to 25), the two 60 fps defect fixes, H17c's
spec, H17c-a, H17c-b, H17d, H17e, H17f's finding and H17g's first part (2026-10-25), and H17h, H17i's
finding, H17j's first look, H17k, H18a in part, H18d's knob and E3 (2026-10-26), and the night of 2026-10-26
to 27 the 60 fps review's fixes, Setup's example mods kept out of a player's install, WS0's first look, the owner's
D-46 ("Narrow to mods") and D-47 (the CC0 decompilation's 839 names and 17 notes, `docs/research/ogdanimal-decomp/`),
milestone 3's first two mods -- `mods/battle-boosts` (R4) and `mods/difficulty` (R3), to
`docs/specs/battle-mods.md` -- and Setup's two defects from the distribution review, pushed. The full pre-push
suite passes: 1981 tests in 103 files (1940
passed, 41 skipped here; 769 skip with MSVC hidden, so 728 want MSVC). Nothing is
uncommitted but the owner's `.vscode/`. One session committed to this checkout; use the `orient` skill before
choosing work.

**What the night of 2026-10-26 to 27 built, in order** (each with its FINDINGS entry):

| Slice | What it gives | Spec |
|---|---|---|
| E3 | turbo, save now and the debug actions in a recording, applied from a replay | event-track.md |
| the 60 fps review | a GPU race, two pacing defects and a check that could not fail, fixed | interp-display.md |
| Setup's example mods | a player's install carries the shipped mods alone | distribution.md |
| D-46, D-47 | the owner's "Narrow to mods"; the CC0 decompilation's 839 names and 17 notes | (PLAN-NEXT §0) |
| R4, R3 | `mods/battle-boosts` and `mods/difficulty`, shipped, off until set; `tools/battle.py rewards` | battle-mods.md |
| Setup's two defects | another disc image extracts again; a new version keeps the saves and settings | distribution.md |

**What the last session built (2026-10-22 to 24), in order.** Each has a spec under `docs/specs/` and a FINDINGS
entry of the same name:

| Slice | What it gives | Spec |
|---|---|---|
| T9 | the game's addresses by name (`config/gamedata.txt`, 72 names), `soa_gamedata.h` | game-names.md |
| T1/I6 | a mod's `files.txt` replaces, adds and aliases disc files | disc-layer.md §3.8 |
| R0 | the battle harness: `SOA_BATTLE_LOG`, `SOA_BATTLE_FORCE`, `tools/battle.py check`, `on_damage` | battle-harness.md |
| R1 | ten more battle events for mods; a mod crashing in one exits 10, named | battle-events.md |
| X2 | mods keep a chunk in the save file; unloaded mods' chunks ride through; `tools/savext.py show` | save-extension.md |
| T2 | `claim = flag <name>`: flags numbered from 24,576 in `mods.lock`, never reused | content-ids.md |
| K1 | the plan's "8,192 up is free" was wrong: the area maps own flags to 24,255 (`tools/flagmap.py`) | content-ids.md |
| K6 | with `SOA_SEED`, the story's first battle repeats blow for blow | (FINDINGS "K6") |
| K12 | six free battle status bits (`tools/statusbits.py`) | (FINDINGS "K12") |
| M7a | the menu's Save now, anywhere on a quiet field; a Continue lands where it was made | save-now.md |
| M7b | the menu's Debug page: warp, part select, the ending, the fade fix, encounters off | debug-actions.md |

Owner decisions taken: D-43 (the gameplay core), D-44 (gameplay Q2: the honest save promise, no mod-map or gear
fallback until a mod needs one). Milestone 2's core list is done, and M7a/b with it.

**Next, in order.** PLAN-NEXT §0 has the order; since the owner's D-46 (2026-10-27, "Narrow to mods") it is:
1. **Milestone 3, the mod platform.** *R3 and R4 built 2026-10-27* (FINDINGS "Battle mods"): `battle-boosts`
   (EXP, gold and magic EXP x0 to x4, full Spirit, an escape that works, no knock-outs) and `difficulty` (Easy,
   Hard, Nightmare), shipped, each off until set; the owner's Hard through one dungeon is R3's Done left, with
   their say on the preset numbers. Not yet seen in a real battle: a party Run, a Try again, event battle 26 (the
   one the story lets you lose, where no knock-outs stands down), and an enemy's death spell on a party with no
   knock-outs (cancelled as a miss: a state no run has shown the battle survive). Next in milestone
   3: R5 (battle information) and P7, which need a way for mods to draw -- M8's overlay is the likely base (the
   port's menu draws its panel and notices over the picture on both renderers, `runtime/menu.c`), and the game's
   own text queue a second route (`TextPrint` at `0x801E2EE4` among the imported names, through `call_guest` at a
   safe point, with a string in guest memory that no one has found room for yet); then T3 + K8, T5 and R6 (edited
   enemy files: I7, or a patch at load), K2, K7, K11. What follows is the night's brief of 2026-10-26:
   The owner plays the game on another recompilation,
   github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp (GPL-3.0: read its notes, copy none of its code), which
   already ships widescreen, 60 fps and Android and cannot run mods that change the game's code. Here: a spec for
   R3 and R4 first (PLAN-GAMEPLAY-MODS Track R: Easy, Hard and Nightmare; EXP, gold and magic EXP boosts, full
   Spirit, an escape that works, no knock-outs), then R4, then R3. The night's milestone-3 brief (D-46's research)
   found none of milestone 3 specified; R3 and R4 need no research item, their fields confirmed in
   `docs/research/battle-system.md`; R1's events and its `[battle] rewards` line (`runtime/battle.c`) are R4's
   oracle in one `SOA_BATTLE_LOG` run of the battle scenario; R5 and P7 need a way for mods to draw, which no plan
   has yet; T5 and R6 need a route for edited enemy files (I7, or a patch at load). Alongside it, the owner's
   D-47: github.com/ogdanimal/SkiesOfArcadiaLegends-Decomp's CC0 function names and research notes imported, credited.
2. **The play path in maintenance** (D-46): defects fixed with their checks, no new features. 60 fps stays as
   built (`interp` opt-in); the night of 2026-10-26 a review fixed four defects in it (FINDINGS "The 60 fps
   review"), and Setup no longer installs the example mods (FINDINGS "Setup would have installed the example
   mods"). Dropped: session D, H18's classes, Android's 60 Hz request and widescreen, whose first look stays as a
   record (FINDINGS "WS0, first look"). The 60 fps story this item used to tell is FINDINGS "H17a" to "H18d".
3. **The event track's E3: built 2026-10-26** (FINDINGS "E3"): turbo, save now and the debug actions recorded as
   `@turbo`, `@savenow` and `@action` lines and applied from a replay at their frames; the menu's rows take nothing
   during one; a recorded event the replay cannot apply is the replay leaving its recording, exit 11 under
   `SOA_PAD_STRICT`. The event track is done; milestone 2's list is done but for I7 (T1's deltas).

**`build/` was cleaned 2026-10-27, at the owner's word:** 88 GB of screenshots, frame dumps, GPU check renders
and test installs deleted; every log, pad file, card, capture and the protected folders (`fifo`, `fifo-pre-c5`,
`cards`, `savetest`, `gpuset`, `perfset`, `x2`) kept. A FINDINGS reference to a picture from before then no
longer resolves; its log does. It also took `build/gpu-oracle/ref/`, V0's references, which a check reads:
the benchmark set's twelve were re-made the same night and shown to be the same images (FINDINGS "The
cleanup took V0's twelve benchmark references"). Keep that folder in any later cleanup.

**Waiting on the owner at the machine** (none of these can be done by a session; since D-46, only what mods need):
- Hard through one dungeon with `difficulty.preset = hard` in `soa.ini` (R3's Done), and a word on the preset
  numbers (docs/specs/battle-mods.md §4: Easy 0.5 HP and 0.75 attack; Hard 1.5 and 1.25, rewards 1.25; Nightmare
  2, 1.5, defenses and speed 1.25, rewards 1.5);
- a small mod built from `docs/MODDING.md` alone (T10);
- the menu in a window and the Vulkan menu (M8a/b), its Mods page above all, and its Save now and Debug page;
- a save made off a save point (on `a116c`) loaded in Dolphin, which should land at the last save point.
Dropped with the play path's features (D-46): session D's look at 60 fps, the `build/interp-review/` and
`build/ws0/` pages, and the battery run (H20).

**Recipes the last session leaned on** (all in FINDINGS with their runs):
- *Part G's card to the field:* `--card build/savetest/card-partG.raw` and the pad
  `1600:start,1640:a,1800:start,1840:a,2000:start,2040:a,2240:a,2440:a,2640:a`; the field runs on `a116a` by about
  frame 2700.
- *A save from there:* `SOA_SAVE_NOW=3300`, then `3420:a,3490:a,3560:a,3630:b,3700:b,3770:b` (slot A, file 01,
  overwrite); or the lab's `save:3300-5000:a/a/a/b/b/b` at a save point.
- *A warp:* `SOA_ACTION=warp:103a@3300`, or `tools/reach.py run NAME --warp 116c`.
- *Battles:* the `battle` scenario at `SOA_SPEED=3` fights the story's first battle from about frame 9811;
  part G with `--soak-seed 33 --accelerate 600` fights one near 4420; reach U2's crystal and U3's ship battle
  recipes are in FINDINGS "R1, the battle events".
- *A battle mod on that battle* (FINDINGS "Battle mods"): `scenario.py run battle --frames 16000 --env
  SOA_SPEED=3 --env SOA_SEED=4242 --env SOA_BATTLE_LOG=1 --env SOA_SNAP=0 --env SOA_MODS=<a folder with the mod
  alone>`, its options in `SOA_MOD_OPT`; `tools/battle.py rewards <log> --exp K` holds the payout. With K6's seed the
  battle repeats blow for blow, won at frame 11818. `SOA_BOOSTS_TEST=lowhp` brings the party in at 1 HP (never write
  an actor's HP mid-battle: that stalled it); the lab's `peek:F-G:0x80309DF4*+272*+36` reads slot 4's record.
- *The build from before X2* is kept at `build/x2/before/soa.exe` (2ac1b7c): it stands in for the game alone.

**Traps that cost time in that session** (the memory files hold them too):
- **Never write code containing a backslash through a Bash heredoc**, quoted delimiter or not: `\n` and `\\n`
  arrive as real line breaks. Use the Write or Edit tool, or a script file written by Write.
- `Path.write_text` without `encoding="utf-8"` writes the Windows code page, and flips LF to CRLF. Use
  `write_bytes(text.encode("utf-8"))` with the file's own line ending.
- Chain a commit after any script that edits what it commits with `&&`, never `;`: the K12 commit went out with
  stale counts that way.
- Touching `runtime/window_sdl.c` means CLAUDE.md's whole Linux check, `test_window_sdl.py` under Xvfb included
  (its driver stubs every function the window calls; a missing one broke CI once). Docker Desktop works here:
  `python:3.14-slim`, the apt packages CI's `ci.yml` lists, `tools/fetch_sdl.py`, then `xvfb-run`.
- `reach.py run NAME` refuses a folder that already holds a run: give each run a new name.
- A peek address worked out by hand was wrong twice (flag words): compute it, or read it off the mod's own log.
- Counts move with every test added: measure (`pytest --collect-only`, and the MSVC-hidden run with the plugin
  in the memory file `measure-test-count-rows`) and fix every copy in the same commit.

### Earlier notes, newest first

**Latest, 2026-10-24: M7b, the debug actions, built** (FINDINGS "M7b", `docs/specs/debug-actions.md`). The
menu's Debug page (and `SOA_ACTION`) warps to any of 189 field maps, opens part select, plays the ending, turns a
black fade back in and switches random encounters off; each repeated its recipe with frames opened. With M7a
the same day, milestone 2's M7a/b is done. **Next:** the event track (the last of milestone 2), or the owner's
pick; **owner:** the menu's Save now and Debug page in a window.

**Before that, the same day:**

**Latest, 2026-10-24: M7a, save now, built** (FINDINGS "M7a", `docs/specs/save-now.md`). "Save now" on the
menu (and `SOA_SAVE_NOW=F`) opens the game's own save menu wherever the field is quiet; a Continue from it
lands where the save was made, `a116c` included, whose Continue used to stop. Off a save point the save
carries the last save point's map for the game alone, which the pre-X2 build loads. **Next:** M7b (warp by
name, part select and the other debug actions) or the owner's pick; **owner:** Dolphin loading such a save.

**Before that, the same day:**

**Latest, 2026-10-24: T2's core built** (FINDINGS "T2", `docs/specs/content-ids.md`). A mod claims a story
flag by name (`claim = flag <name>`, `api->claim`); the loader numbers it in `mods.lock`, never twice, and
saves carry the table so a mismatched install is named on load. In the game a claimed flag set after
`on_load` came back through the game's own save. **K1 the same day** (FINDINGS "K1"): the plan's "8,192 and up
are free" was wrong, since the area maps' exploration grids own flags up to 24,255 (`tools/flagmap.py` reads
all 71 off the disc and accounts for every high flag in 46 saves), so T2 numbers from 24,576. **K6** (FINDINGS
"K6"): with `SOA_SEED` pinned, two runs of R0's story battle fought the same battle blow for blow; a different
seed fought another. **K12** (FINDINGS "K12", `tools/statusbits.py`): six status bits are free (0x20 and
0x04000000 up but 0x20000000), and the four the plan could not name are in use. Milestone 2's core list
(T9, T1, R0, batch A, T2, K1, K6, K12) is done. **Next:** the owner's pick (PLAN-GAMEPLAY-MODS milestone 2's
rest -- M8, M7a/b, the event track -- or milestone 3).

**Before that, 2026-10-23:**

**Latest, 2026-10-23: X2, the save extension, built; batch A is done** (FINDINGS "X2",
`docs/specs/save-extension.md`). A mod keeps a chunk of its own inside the game's save file (`on_save`,
`on_load`, `on_new_game`), in the block's checksummed gap and the file's tail; the chunks of mods not loaded
ride through every save; loading names the mods a save holds data for that are missing. A save made by the
new build loads in the build before it (`build/x2/before/soa.exe`, 2ac1b7c), and `tools/savext.py show <card>`
reads a card's chunks. Owner's Q2 answer (D-44): the honest promise, so no mod-map or gear fallback yet.
**Next:** milestone 2's remaining core, T2, K1, K6 and K12 (PLAN-GAMEPLAY-MODS), or what the owner picks.

**Before that, the same day:**

**Latest, 2026-10-23: R1, the battle's other ten events, built** (FINDINGS "R1, the battle events",
`docs/specs/battle-events.md`). Heal, enemy spawn, enemy action, turn order, spirit gain, escape, rewards, effect,
round end and ship damage are answered natively (`hle.txt`, 37 entries) and reach mods as `SoaModApi` members;
a mod that faults inside one stops the run, exit 10, naming itself and the event. With mods off every site was
called and none changed, across the story's first battle, part G's crystal battle and reach U3's ship battle;
with a test mod each event's change showed in the game. **Next:** X2, the save extension, with the owner's answer
to gameplay Q2 (D-44, 2026-10-23): the honest wording, so the save-now location fallback and pass-through only.

**Before that, the same day:**

**Latest, 2026-10-23: R0, the battle harness, built** (FINDINGS "R0", `docs/specs/battle-harness.md`). The battle's
damage function is answered natively (`hle.txt`, one retranslation): mods change every blow through `on_damage`, and
`SOA_BATTLE_LOG=1` logs each call with base, original and returned, and what changed each frame. `examples/mods/damage-double`
holds to `min(2 x original, 9999)` on 25 hits of the story's first battle, with every original inside its formula's range;
`SOA_BATTLE_FORCE` starts a battle on demand. **Next:** batch A (R1's other events and X2's save hooks).

**Before that, the same day:**

**Latest, 2026-10-23: T1's core, I6, built** (FINDINGS "I6", `docs/specs/disc-layer.md` §3.8). A mod's `files.txt`
replaces, adds and aliases disc files: the table is rebuilt at boot, the files served past the image's end, and the
game's own lookup finds all 5,552 vanilla paths where they were (self test). `examples/mods/map-alias` sends a warp to
the missing map 045a into 002a's room, pixel-identical to a direct warp there. **Next in the gameplay core:** R0, the
battle harness; I7 (text deltas) when a mod needs one, I8 (per-map swaps) with N2.

**Before that, 2026-10-22:**

**Latest, 2026-10-22: T9 built** (FINDINGS "T9", `docs/specs/game-names.md`; D-43, the gameplay core). The
game's data by name: 68 addresses in `config/gamedata.txt`, each held to the instruction in the DOL that reaches it
(`python tools/gamedata.py check`), a generated header for DLL mods, and names in `patches.txt`
(`once party.gold = 50000`). The owner also asked for a world editor like the Wind Waker port's: planned as
PLAN-GAMEPLAY-MODS N12, after T1, T4, T6 and T8. **Next in the gameplay core:** T1 (the virtual disc), then R0.

**Before that, the same day:**

**Latest, 2026-10-22: V12 built** (FINDINGS "V12", `docs/specs/interp-gpu.md`; D-42). With `gpu = vulkan` and
`interp = 1`, the GPU draws the in-between stream into the lower half of a double-height EFB and its presenter shows
each in-between image for one 60 Hz refresh before its frame. Windowed at the cap the game kept full speed (field
29.2, opening 29.9) with 2773 of 3000 and 3781 of 5000 frames given one; the in-between image costs about 1.35 ms
of GPU time. **Next:** the owner's session D at 60 or 120 Hz judges H17b and V12 together (the display here is 85
Hz); then H18 for whatever that list holds.

**Before that, the same day:**

**Latest, 2026-10-22: H17b built** (FINDINGS "H17b", `docs/specs/interp-live.md`; D-42, "H17b, then V12"). The
window shows each in-between image for one 60 Hz refresh before its frame (`interp = 1` in soa.ini or the menu),
where the display is at 60 or 120 Hz; a screen ring hands it whole frames (closing B1); a cut detector holds the
frame before at camera cuts; and a budget on the game's own frame time stops the in-between work before it slows
the game (opening 25.4 real frames a second on, 24.2 and 26.4 off). On this CPU it stops early in the opening and
the field, so the owner will mostly see repeats until **V12**, next by D-42: the in-between images drawn on the
Vulkan backend. The display here is at 85 Hz, so the pacing waits for session D (D-2).

**Before that, the same day:**

**Latest, 2026-10-22: H17a, interpolation headless, done on this PC** (FINDINGS "H17a", `docs/specs/interp.md`;
the owner chose 60 fps, D-41). `SOA_INTERP=1` builds every draw a second time into a second EFB, the image between
the frame before and this one; `SOA_SNAP` writes it as `NNNN.mid.png`, and `SOA_INTERP=check` proves the real picture
untouched (3000 of 3000 frames in `126a`). The live stream is H10's midpoint byte for byte (`test_gxr_pair.py`), and
off changes nothing (replay 23/23 at 1, 2, 3, 8 threads). Measured: 32 to 43 images a second with it on (field 40.8,
cutscene 32.2, battle 33.2, ship 43.4), the workers short and not the guest. **Next:** H17b, the images in a window
with the cut detector and repeat-when-over-budget, whose Done is the owner's session D at 60 or 120 Hz (PLAN-NEXT M2
row 4); the owner's sitting still holds the menu, Vulkan menu look, battery run and mod-guide checks.

**Before that, 2026-10-21:**

**Latest, 2026-10-21: M16, declared mod options, done on this PC** (FINDINGS "M16",
`docs/specs/mod-options.md`). PC step 2 (reach U4 and U5) was already done, and step 3 needs the owner at the
machine, so the session took the mod framework's next item (PLAN-NEXT §0, D-38). A manifest 2 `mod.ini` declares
`option = NAME TYPE [DOMAIN] DEFAULT`; `SOA_MOD_OPT` and soa.ini's `ID.NAME = VALUE` set them; `patches.txt` reads
`${NAME}`; a DLL calls `option` and `option_int`; the recording names values away from their defaults. In the game,
`encounter-scale.factor=0` zeroed `a116a`'s four live rates where the default halved them, and `map-log.scenes=0`
left out every scene change. A folder `C:\c`, made 2026-10-18 by another program (the owner's to delete; a safety check stops a session), had broken every
gnu-profile compile through `toolchain.gnu_args`; fixed. M17 followed (below);
M16b (`mods/`'s three DLL mods onto declared options) goes with P1's presets.

**Then M17, the same day: the mod list's order and conflicts, done on this PC** (FINDINGS "M17",
`docs/specs/mod-order.md`). `mod_order` (`SOA_MOD_ORDER`) orders mods by id and turns them off with `-ID`; `overrides =`
lets one mod's writes land on another's and loads it after; two mods whose patches can write the same bytes on one
frame are refused with both lines. In the game a twin of `encounters-off` writing 0x10 was refused, then with
`overrides` loaded and its 0x10 was what each frame left. T10 followed (below).

**Then T10, the same day: the mod kit and the guide** (FINDINGS "T10", `docs/specs/mod-kit.md`):
`tools/mod.py` `new`, `build`, `check` (the port's loader against the real DOL, no game), `test` (the fake guest, now
`tools/soa/modkit.py`) and `api` (`docs/MODDING-API.md`, held current by a test); the guide is `docs/MODDING.md`. A
`new` patch mod and a `new --dll` mod built by `build` ran in the game unchanged. **Next:** the mod framework track
(D-38) is done but for T10's owner check, which joins PLAN-NEXT §0 step 3, the owner's sitting. After it, the owner
chooses among mods (M8, M7, R0, R1), 60 fps (H17a) and widescreen (M10); M16b goes with P1's presets.

**Then P1b, the encounter contrast, the same evening** (FINDINGS "P1b"): `mods/encounter-rate`'s test mode and
`tools/encounter_check.py`; the 400,000-frame field run in a116a passed at rate 45 (r 26, 51 and 104 at k 0.5, 1
and 2; no battle in 77 off and 77 hold trials). The sky run waits on map 99's encounter path.

**Then H20, a power line in every run report** (FINDINGS "H20"): `[power] AC, battery 79%, plan Turbo, mode best
performance` on this PC; on battery it adds the mWh the run used and per 1000 frames. A battery run joins the owner's
sitting. **Then M16b** (FINDINGS "M16b"): the shipped mods' settings as options, `encounter-rate.rate` and
`hold_b`, `autotext.wait`, `coop.slots`, the old switches still winning. The owner then chose M8 (D-40).

**Then M8a, the in-game menu** (FINDINGS "M8a", `docs/specs/menu.md`): View+LS or F1 opens it over the picture,
holds the game, withholds the pad before any recording, and writes soa.ini (Mods with their options and on/off,
Settings); fullscreen and turbo apply at once. Checked in a window here and on Linux in a container. **Then M8b** (FINDINGS
"M8b"): the Vulkan presenter blends the menu over its picture. **Next:** the owner's sitting, whose list now
includes the menu in a window; then the owner's next choice (M7a/b's warps and saves from the menu, 60 fps, widescreen). P1b's
sky run is attempted and open (FINDINGS "P1b's sky run, attempted"): map 99's encounter path is read, but
part K's ship sits where no region has a table and did not move under A and the stick.

**Before that, 2026-10-14 to 10-17:**

**The state at the stop (2026-10-14, the PC session after the cloud's R5c and M6):** the cloud branch is merged
(`main` fast-forwarded to 1c1fefd and pushed, CI green), and PLAN-NEXT §0's PC step 1 is done (FINDINGS "R5c and M6
on the PC"):
- **M6 is done.** The contract held here (`--link`, the self test, the replay 23/23, `title` 4 of 4). Part G with the
  accelerator fought 0 battles with `examples/mods/encounter-scale` at × 0 and 5 at × 1, and the eight rate words
  logged at `a116a`'s load agreed with peeks 23,000 frames later. New: in a battle `0x803474BC` still names the
  field's table while its memory holds something else, so pointer patches belong on load triggers. `build\m6\` holds
  the runs (game data).
- **R5c's Done is met but for the capture at 150%**, which goes with the owner's sitting on the Ally X. The real run
  built both targets in about 133 s, the bar's split measured 59/41 (60 stands), and its library equals
  `player_build`'s. The owner's first bless of its words, and §1.3's questions, are on
  `build/setup-review/index.html` (local). `build\r5c\` holds the package and both roots; delete it when its space is
  wanted.
- **TESTING's count table is measured again at 1c1fefd** (1553 tests, five rows). soa-fa's README progress tracker
  (`tools/progress.py`, 13 tests) has since been committed by that session (c0e9d74).

**Then, the same day: PLAN-NEXT §0's PC step 2, the reach runs** (`docs/specs/reach.md`, U0-U5), each with a
FINDINGS entry "Reach U<n>":
- **U0, the tools:** `soak.py check --expect-flag`, the effect-package ledger (`--beff-ledger`, kept at
  `build/reach/beff.json`, 22 of 576 names) and ship battles judged to their results; `examples/mods/lab`
  (`SOA_LAB`): `entry` (the A press at an object, skipping only the walk), `peek` (pointer chains), `objects` (each
  map's hit volumes and where their objects stand), `hold-hp`, `turn` and `sturn` (a battle member's or a ship crew
  member's input played through the pad filter), `dump` and `walk` (below). The run script is
  `labrun.ps1`'s pattern, written into each FINDINGS entry: own card copy, own folders, traced, strict,
  `SOA_SETTINGS=0`, and a lab DLL no older than its source.
- **U1 done:** part G's boss, Vigoro (event 19), started from `M04005`, lost three times into the game's "try
  again", and won with `hold-hp`; the after-scene set flag 304.
- **U2 done:** a Sacri Crystal used in battle by Gilder, consumed and written back to the save.
- **U3 done:** a ship battle won, once its command input was found (`0x80306738`); A presses alone stall at 3 SP,
  which FINDINGS had read as "round 3 of 41" (corrected).
- **U5, nine of ten parts run** (FINDINGS "Reach U5"): every base invariant held; the effect ledger at 44 of 576.
  It found **a port defect: BP_MASK was not applied** (fixed in b80f412: after every game over the
  masked GEN_MODE write changed bits the console keeps; no frame seen drawn differently). U4's part-C runs found
  **a second, a visible one: a destination-alpha blend at RGB8 drew too dim** (the console reads that alpha as 1.0;
  `a107a`'s railcar headlamps were faint wisps instead of bright shafts, 27% of the frame; fixed 2026-10-16). Part L was cut off by the
  host's restart and is to be run again, with `hold-hp` so a soak is not lost to its first game over.
- **U4, part G played to its end** (FINDINGS "Reach U4"): from `a116a`'s cell through the prison, Vigoro, the
  Fortress Gate's ship battle (won with the Moon Stone Cannon) to the Delphinus under way, flags 303 to 315, in one
  195,000-frame run with every base invariant held. Where the story continues by sailing the world map, the entry
  walker stops: that needs a world-map driver, not built.
- **The lab mod drives** the walk (`walk`), A where it belongs (`assist`), battles (`hold-hp`, `turn`), ship battles
  (`sturn`, with alternatives and presses held a frame count: the ship wheel is mapped), saves (`save`), and reads
  (`peek`, `dump`, `objects`); each item's comment in `examples/mods/lab/mod.c` says what it is for and which run
  showed it was needed.

- **U4 with a sense of the story (2026-10-16):** `sct.py --story` indexes every field script's flags set and warps
  (through calls, raw, so message opcodes hide nothing), plus 15 hooks, warps that wait for a flag only the game's
  code sets (the world map's: the ship reaching a spot). The lab's `story:LO-HI` (`reach.py --story 100-149`) aims
  the walker at the next story flag by distance in warps, and sets a hook's flag in place of the sail. Part C now
  runs from Sailors' Island through the Grand Fortress, Antonio, the palace (past Galcian's patrol), the Royal
  Guards and the escape's ship battle (won, the Little Jack held) to Pirate Isle (`build/reach/u4-C13`: flags 100 to
  121 and 124, nothing set by hand; `u4-C11`'s 250,000 frames held every invariant). Walker defects found on the
  way, each fixed with a test: it waits wherever
  the player's A press would do nothing, while a message window is up, and while the map's script runs anything
  but its loop (`*0x8030CEA4`); it aims at the lowest clear flag it can reach (flags are not set in order); its
  back-out never presses B in a ship battle; an entry's tries renew 9,000 frames after its last. The part cards
  start Vyse at level 1, so the lab's `finish` holds a long fight's enemies at 1 HP and the game's own victory
  ends it, and `hold-hp` holds the player's ship in a ship battle, each said in the log. Runs go at
  `SOA_SPEED=4`.
- **Part C done, part D begun (2026-10-16):** `u4-C14` set 122, part C's last; 123 is a later visit's and is
  passed over after 30,000 frames. `build/savetest/card-partC-end.raw` (saved by the lab's `save` at `a002e`)
  starts part D one exit before 122. Three walker defects since, each fixed with a test: a menu B does not leave
  (the Maramba Office) gets the way out; a shopkeeper's choice after a back-out is answered from when it comes
  (the Mystery Merchant's talk was exactly four of assist's beats long); and an entry whose cast is not here is
  not started (a008a's dancer, started from the street, waited 40,000 frames on two people who live in the inn's
  interior MLD, which loads only inside it; RAM captured by `u4-D4`). `sct.py` now lists messages and choices
  with their text. With `--story 150-199` (`u4-D9`): 150 by the world map's hook, 151, and 152 by the dancer's
  night once the walker learned houses: nothing warped to from inside one (flag 1024), doors asked again, and
  the ground an entry is gated on (B[16], which a008a's doors test) stood on first. **Part D done
  (`u4-D12`):** flags 150 to 162 by the game's own scripts, through the inn's two nights, the Temple of Pyrynn
  and two ship battles, Belleza's among them, which end in their own course; its card,
  saved at the temple, is `build/savetest/card-partD-end.raw`.

**Part E done (`u4-E3`, 2026-10-16):** every flag of 200-249 a script sets, through the gates the story index
now knows (the Great Bird's Eyes, a touch's battle). Cards: `card-partE-mid.raw` (`a111d`) and
`card-partE-late.raw` (`a112c`, before part E's last two ship battles).

**Part F through (`u4-F5`, 2026-10-17):** the deserted island by the lab's `wander` (its encounters' meat),
and a chain of requirements the story index now carries (`reqN` lines; the walker aims at what a flag waits
on, field flags too). The story went on into part G; its card, at the prison's save point, is
`card-partF-end.raw`.

**Part G's story done (`u4-G20`, 2026-10-17):** the Fortress Gate by the Moon Stone Cannon, Gilder's choice
answered start by start, the deserted island landed on in place of the sail, the shipwrights paid by the lab's
`gold`, Crescent Isle (the walker steps off a touch entry that keeps starting under the player) and three ship
battles: flags 300 to 327 and 329, by the game's own scripts. Ship battles now end: the crew fire a cannon or
Focus when the SP will not pay (a retry plays the next alternative), and `finish` holds a long one's enemy ship
at 1 HP through the record the fight keeps it in. Cards: `card-partG-sail.raw` (`a103a`),
`card-partG-crescent.raw` (`a018b`) and `card-partG-013d.raw` (`a013d`, after 327). What is left in 330-349
is side errands; 328 belongs to the prison, long behind.

**Part H to 379 and 352 to 364 (`u4-H4` to `u4-H14`, 2026-10-17):** 352 by a hook that carries the flags its block
sets, the Tenkou Spellship sunk by `finish` (the part card's Delphinus has only cannons), Yafutoma, the Ship Parts
Merchant (whose tasks the lab now does when he never takes them up, and whose repeated choice now moves on), Mt.
Kazai (358) and 359 to 364. 380 (the betrayal) waits on 365 clear, which the walker's early trip set. Then the
world map's letter: map 99 loads at B[6]'s, and the index and the lab now say so (`w099@`, `w099i`). Cards:
`card-partH-020a.raw`, `card-partH-019d.raw` (to 377), `card-partH-121a.raw` (Mt. Kazai, with 358). A battle that
stood still once (Muraji, u4-H6) did not recur (FINDINGS).

**Part I's story done (`u4-I3`, 2026-10-17):** 400 to 414 (no script sets 402 or 410), with
the dungeon `a123`'s door puzzle stood in for by `flag:123d:1912` and arrival-only flags now in the index
(`123d via123b s403`). Card `card-partI-004a.raw` (after 412).

**Part J's story done (`u4-J1` to `u4-J4`, 2026-10-17):** every flag of 450-499 a script sets. The
index now marks an arrival sent straight back, a hook's own conditions (and keeps a hook's warp off its loop's
line), and an entry only the game starts (g), which the lab begins by name where it sets the aim (`a127b`'s Fship
and Delocco, a sky map). Cards: `card-partJ-126a.raw`, `card-partJ-109g.raw`, `card-partJ-020a.raw`,
`card-partJ-017h.raw` (after part J, 500 to 504 set).

**Part K's story done (`u4-K1`, 2026-10-17):** 500 to 525 but 508, 513 and 514, which no script sets. Card
`card-partK-028a.raw` (before 515).

**Part L, and the game to its ending credits (`u4-L1`, 2026-10-17):** 550 to 559 and 561 to 571, the last ship
battle and battles, `a298a`'s closing cutscene and the staff credits at frame 275247, the title after. U4's story
is played, every part from C to L, to the end (part I from its part card, J to L each from where the one before
ended). Card `card-partL-130a.raw`.

**Part H's tail done (`u4-H17`, `u4-H18`):** the walker no longer takes a way whose arrival plays a later scene
before its time, so part H ran again from its card with the betrayal (380) in its place, and 381 followed once
`flag:122b:1051` stood in for a flag only the game sets. Card `card-partH-019a-380.raw`.

**U5's second round (2026-10-17):** parts D, E, F, G, I and L with `hold-hp` pass `soak.py check`; H, J and K met
no battle on their maps, but the story runs fought there, and with their logs the effect-package ledger holds 119
of 576 (FINDINGS "Reach U5"). The one renderer question is LINEPTWIDTH (lines asked 2.17 px wide, drawn 1).

**Next:** PLAN-NEXT §0's step 3, the owner's sitting; then the owner's choice among mods, 60 fps and widescreen. Part H's tail (381 on)
needs a run from `card-partH.raw` that leaves `a019d` for the world map only after the betrayal (380): every later
card carries 365, set by that trip made early, which shuts the betrayal out (FINDINGS "u4-H15 and u4-H16"). U5's
parts E, F, I and L with `hold-hp`. The mod framework's
next slices (M16, M17, T10, PLAN-NEXT §0) have not moved since M6 on 2026-10-14: the owner was asked whether a
cloud session or a background agent here takes them. `tools/reach.py run` is how every run here is made (its
`--help`, and each FINDINGS entry's recipe). Step 3, the owner's sitting, also holds R5c's 150% capture and the
review page.

**The state at the stop (2026-10-14, after R5c, built in a cloud session):** a session in Anthropic's cloud,
with the repository and no game data, built R5c (FINDINGS "R5c"), and pushed it to the branch
`ccr-ff7e48fb-uaiw45`, not to `main`. Merging that branch into `main` was the first thing to do on this PC:
**done 2026-10-14** (`main` fast-forwarded to 1c1fefd, CI green; the paragraph above). R5c is Setup's Android box: one run builds `soa.exe` and `libsoa_game.so`, with a two-phase bar,
a status chosen from the run's own lines and the phone's space counted. Its four mutations are caught under Wine,
and CI's `android-route` Windows leg now runs `test_setup.py` under `noskip`. **What waits for this PC** is R5c's
Done (android-sysroot.md §1.3), **all done 2026-10-14 but the 150% capture** (FINDINGS "R5c and M6 on the PC"):
- stage a package (`build\r5c\P`), then `P\Setup.exe --disc <image> --build --android`, ending in the built
  words, its `libsoa_game.so` with the sha256 of `player_build.py --target android-arm64` from the same package
  into `build\r5c\R2`;
- time that two-target first run to settle the bar's 60/40 split (FINDINGS "R5c" derives 59/41 from R5b's
  timings);
- capture the window at 100% and 150% for the review page `build/setup-review/index.html`;
- run `pytest -p noskip tools/tests/test_setup.py` there, and the whole suite's five configurations (now 1566
  tests; TESTING's count table).

The owner's first bless of the words and §1.3's three small questions come after that page. Nothing in R5c
touches `runtime/`, `src/` or anything baked, so `baked=` did not move, and the emulator's APK and library stay
valid. The cloud session did not run `decomp.py`, the self test, the replay or `title`: none of their inputs
changed. Everything the 2026-10-09 paragraph below says this PC holds is as it was left.

**Two sessions from 2026-10-14** (PLAN-NEXT §0, D-37 to D-39, and §E item 10). The owner wants the PC port
"working 100%", with mods and improvements wherever they can go, beside the Android path.
- **A session on this PC leads with making it 100%:**
  - merge the cloud branch and finish R5c's Done here (**done 2026-10-14**: merged at 1c1fefd; R5c's Done but the
    150% capture);
  - scripted runs into what no run has reached (a boss or event battle, Items in battle, a ship battle to its
    end, the story between the jump points, effect packages beyond the 20 of 576 seen), fixing what breaks;
  - one owner sitting at 60 or 120 Hz that confirms what is built but unchecked.
- **The cloud session takes the mod framework,** starting with the mod tests' driver building without MSVC.
  Done (FINDINGS "The mod tests without MSVC"), and M6 built after it (FINDINGS "M6"). M6 changed `runtime/mod.c`,
  so on this PC: `--link`, the self test, the replay and `title --check` (CLAUDE.md's contract; with `SOA_MODS`
  unset none of the new code runs). Then M6's game runs: the eight rate words logged at a real map load with
  `examples/mods/encounter-scale`, a peek agreeing, and part G's rate x0 and x1 (PLAN-60FPS-MODS M6's Done).
- **Decompilation stays targeted.**

What the owner chooses after the sitting (mods, 60 fps or widescreen) is §0's to record.


**The state at the stop (2026-10-09, after R5b):** R5b (1bc44b9, 3c268c4,
and its docs with this section) is pushed; read CI for the last. R5's design
is `docs/specs/android-sysroot.md`; R5-0, R5a and R5b are done, and R5c
(Setup's checkbox and words) is next. **R5b moved `baked=`** (`recompile.py`
is a baked input; 1747c42488ed at 3c268c4), so the emulator's APK was
rebuilt and installed at 3c268c4, and the library on it is the package's
x86-64 one (`package=3c268c4`). `build\r5b\` holds that run's package
(`P`, its sysroot built, and its sources put back on their pins after the
damaged-source check), its roots (`R`: both Android libraries, `soa.exe`
and the extraction; `R2`), and the release draft's zip, extracted
(`ci\Z`) with the root it built (`ci\R`); `build\r5-licences\index.html`
is the owner's licence look (below). All of it is game data or built from
it and stays on this machine; delete `build\r5b` whenever its space is
wanted. The SOA emulator was stopped (TESTING.md's Android recipe starts
it again). Its data
image keeps the debug APK at 3c268c4; in Download the store
(`GEAE8P.soadisc`), `disc.iso` and `libsoa_game-x86_64.so`, the last two
staged by R5b's player run, after which `no_backup/disc.txt` names
`disc.iso`, read in place (a check that reads a disc runs with
`SOA_IMPORT=1`); the x86-64 library in `no_backup/`; the captures in
`files/fifo`; and the debug provider's ten mutants, the real library and
the GTSE01 fixture in `files/provider`. The Docker container `soa-l10`
(python:3.14-slim, gcc, SDL3 built in `/work/vendor`) is kept for the next
Linux check, with R5b's split build in `/work/gen/linux-split`; its layer
holds a copy of the captures, so it stays on this machine, and `docker rm
-f soa-l10` removes it. **R5b's two owner items wait, and neither
blocks:** the licence texts the package now ships
(`build\r5-licences\index.html`, local: each of the 44 files' own words
under its class, and the kernel's two texts), and one line on how the
design read D-34 (PLAN-NEXT's D-34 row): the player's PC builds the
phone's sysroot itself, from bionic's 44 files the package carries, in
under two seconds and offline, the first time it builds for Android, and
nothing built from them is published. **L12d's words wait for the owner's look:**
`build/android-review/index.html` (local) shows the boxes the emulator
drew at font scale 1.0 and 1.3, the refusals its check runs printed,
with what causes each, and every other box and refusal as the code words
it. Until the owner has looked they are a draft (CLAUDE.md's first
bless): tests pin the checker's, the disc layer's and some of the copy's
refusals, and nothing but the code the boxes and `android.c`'s own. Two
of `player`'s three single captures of the game after the import came
out black; captures every second or two after a re-import and a first
run at font scale 1.3, run again, showed the picture each time (FINDINGS
"L12d"). What is next, and why, is item 2 of the list below.

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
   `soa.exe --check-disc` checks a copied store whole. **L9 is done**
   (FINDINGS "L9"): settings.c, mod.c, hle.c and audio_out.c go through
   plat.h; mods load as `mod.so` on Linux, `SOA_WAV` writes there, and
   `tools/tests/test_portability.py` holds `_WIN32` to a written list of
   sites. **L10 is done but the owner's session** (FINDINGS "L10"):
   `python3 tools/fetch_sdl.py` builds SDL 3.4.18 (pinned) into
   `vendor/sdl3`, and `recompile.py --cc gcc --compile --optimize --link`
   makes `gen/linux/soa` with an SDL3 window, pads and sound
   (`runtime/window_sdl.c`, `audio_sdl.c`), and the four mods as `mod.so`
   (the three shipped ones read their switches with `getenv` there). In a
   Docker container here the
   self test, replay 23/23 at 1-8 threads and `title --check` pass, and
   under Xvfb the window shows the game, takes keys and plays sound at
   32,022 samples a wall second. The owner's fifteen minutes need a Linux
   desktop: a WSL distribution, which brings WSLg (`wsl --install -d
   Ubuntu`; this PC has only Docker Desktop's, without it), a Linux PC or
   the Deck. **L12 is specified** (`docs/specs/android.md`, with R5,
   reviewed once against the code): the APK holds SDL3 and the runtime;
   the player's PC builds `libsoa_game.so`, which names the runtime as
   `DT_NEEDED`, exports one versioned table and carries its build record
   in an ELF note, and the phone `dlopen`s it read-only from its own
   storage. The owner's devices are a Galaxy Z Fold 8 and an AYN Thor
   (D-30 to D-33). **L12a is done** (FINDINGS "L12a"):
   `recompile.py --cc gcc --split` builds `libsoa_runtime.so`,
   `libsoa_game.so` and a launcher into `gen/linux-split`; the runtime
   reaches the game only through `soa_game`'s table, `runtime/elfcheck.c`
   refuses a wrong library in words before `dlopen`, and the self test,
   replay 23/23 and `title --check` pass on it in the container.
   **L12b is done** (FINDINGS "L12b"): `recompile.py --cc
   android-arm64` (or `android-x86_64`, for the emulator) builds
   `libsoa_game.so` with the NDK in about a minute and checks it with
   `tools/soa/elfcheck.py`, the phone's checks in Python. **L12c is done**
   (FINDINGS "L12c"): `python tools/android.py build` makes the APK (SDL3
   and the runtime, no game code; `guard.py --apk` holds it to that), and
   on the emulator the self test, the replay 23/23 at 1-8 threads, the
   title from a script and from the keyboard, Home and back, and the MEM1
   guard under ART all pass. The emulator found five things the desktop
   never showed, each fixed: bionic's x86-64 `fma`; `__AI_SRC_INIT`, now
   answered natively (26 bindings), which never ended on its slow clock;
   the runtime's exits losing the log's end; background events arriving
   only after the return; and a paused guest spinning a core. The
   emulator is the AVD `soa_x86_64`, run headless on port 5556
   (docs/TESTING.md has the recipe); `emulator-5554` is another
   project's, never touch it. It runs the game at about 9 frames a second
   because its kernel reads the clock through the PIT: measure no speed
   there. **L12d is done** (FINDINGS "L12d"): the first run asks for the
   game library, then the disc, through the app's own picker, checks each
   before keeping it, and says every refusal in the player's words. The
   disc is read in place through the picked descriptor (Android 14 refuses
   to open the file again by name, so this is necessary), or copied when
   it cannot be, as a pipe is; its grant survives a reboot; and a damaged
   block stops the run with exit 9, saying why on the screen first since
   its stop box (FINDINGS "L12d's stop box"). The activity destroyed
   during a pick came with check 13's mutation: the run ends at once.
   **Next: L12's Done on the AYN Thor,** as specs/android.md §4 orders it
   (the self test, the replay and `title` on the phone, the frame rate at
   the Dangral base, and the owner's session with a pad), which needs the
   owner and the phone. Without them, the owner's answer of 2026-10-06
   (PLAN-NEXT §0) puts R5's own Android sysroot next, so Setup can build
   the phone's library without the NDK. Its design was settled on
   2026-10-07 in `docs/specs/android-sysroot.md`, to the owner's answers
   D-34 to D-36, and its first slice, R5-0 (the package's build had
   stopped at `import fetch_sdl` since L10), is done (FINDINGS "R5-0"),
   and so is R5a, `tools/fetch_android_sysroot.py` and the game library
   built through it by `recompile.py` with no NDK, proven on the emulator
   (FINDINGS "R5a part 1", "R5a part 2"). **R5b is done** (FINDINGS "R5b"):
   `player_build.py --target android-arm64` builds the phone's library
   from a player's package, offline, the sysroot built on the player's PC
   from the 44 files the package carries; the release workflow builds that
   sysroot from its own unzipped package; and a library built from the zip
   it drafted passed the emulator's checks. **R5c is next:** Setup's
   checkbox, its two-phase bar, the status it chooses from what the run
   built, and the words (spec §1.3), which are drafts until the owner's
   first bless, with three small questions for the owner. Where L12g
   (mods on the emulator) and the proposed L12h (card import and export
   through the picker) come after it is still the owner's. D-33 (the
   package name and release key) is still the owner's, and comes before
   anyone else installs it.
   Still open for the owner, and not blocking: whether a
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
