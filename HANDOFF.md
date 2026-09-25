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
  `mods/encounters-off` and `examples/mods/map-log` are the examples; `soa.ini`
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
- **Soaks are judged, not eyeballed (S1-S3):** `tools/soak.py check`, and an
  encounter accelerator that fights only where the story allows.

Nothing found so far would stop a person playing. Two things that looked like
it -- a black field after a battle and a trap on `a116c` -- were both the test
recipe putting the game in a state retail cannot reach, and are written up as
such. 813 tests, the guard over the tree and over history, ruff, `decomp.py`,
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
has no encounter table; see wrong statement 8). It renders in a window -- at 18-22 fps in heavy scenes, below the game's
30 fps cap, when every frame is drawn (FINDINGS, H1) -- plays music,
effects and speech, takes keyboard or gamepad input, and reads and writes a
memory card. Headless it runs about ten times real time.

| | |
|---|---|
| Functions recompiled | 7,144, 100% instruction coverage |
| Byte-matching decompiled symbols | 100 across 21 units (83 functions, 17 data) |
| Of those, running in the port | 12 |
| Python tests | 813 |
| Self-test cases | 75 |
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

## What I would do next

**The plan of record for the next phase is `docs/PLAN-60FPS-MODS.md`** (written
2026-09-24): 60 fps by renderer interpolation, then a native mod framework
(data patches, a safe point, `mod.dll` with a versioned API), targeted
decompilation only where a mod needs it, and a soak programme with checked
invariants. Each slice's line there says whether it is done and where its
evidence is. Done by 2026-09-24: **H1** (drawing every frame runs 18-22 fps),
**S4a** (`SOA_PEEK`), **H2** (the logic is per frame, so 60 fps is
interpolation), **H4/H5** (every 3D draw matches its predecessor), **H6** (a
pinned benchmark set, 85.4 ns a fragment), **S2** (guard suffixes), **S1**
(`soak.py check`), **H3** (`[frametime]`; the guest could run the opening at
50 images a second and a battle at 104, the renderer draws them at 19 and 48,
and 8 workers burn 8.4-8.9 cores at any load), **S3** (the encounter
accelerator fights only where the story allows), **M1** (`SOA_MODS`, data
patches; `mods/encounters-off` stops random battles) and **M2** (`tick.c`: a
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
Next, in the plan's order: H11's other half (the guest idle loop still spins
on one core) and H12 (texture hashing), which are cheap; then H14 (the drains
around every filtered copy), H15 (the pixel path), H13 and H16, which are what
60 images a second at 1x needs before H17a turns interpolation on. M4 (`call_guest`) is done, and M5,
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
  `tools/citest/render_check.py` and four `test_gxr_*` modules build `gx.c`,
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
