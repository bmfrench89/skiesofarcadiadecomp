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

Clean tree, everything pushed, CI green on all four jobs. Nothing is in
flight, no branch is half-finished, and no workflow is running.

Since 2026-09-21 the renderer applies the EFB copy's deflicker filter (PLAN
C3), `SOA_POKE` can write guest memory mid-run (PLAN D2's half), and the field
can be teleported to the developers' test stage. Five field maps had ever been
loaded by anything here before that, all of them by the story or by losing a
fight; the disc has 264.

The port boots, plays the opening with dialogue, wins the first battle, and
is carried by the story through the Valuan ship's hold into `a101b`, where
it moves around with menus, a minimap and random encounters (the hold itself
has no encounter table; see wrong statement 8). It renders in a window at the game's 30 fps cap, plays music,
effects and speech, takes keyboard or gamepad input, and reads and writes a
memory card. Headless it runs about ten times real time.

| | |
|---|---|
| Functions recompiled | 7,144, 100% instruction coverage |
| Byte-matching decompiled symbols | 100 across 21 units (83 functions, 17 data) |
| Of those, running in the port | 12 |
| Python tests | 497 |
| Self-test cases | 73 |
| Scenarios | 13 |
| Pinned frame hashes | 23 |

"100 matching" deserves its caveat: 65 are compared in full, and 35 carry words
the checker can only decide by linking, so it reports them separately and does
not count them as matches. Two data symbols have none of their four bytes
compared. Seven of the twenty-one units are fully verified; fourteen are not.
That is the oracle being honest rather than a defect, but do not quote the
round number without it.

## Nine things the history says that are wrong

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

The pattern behind all nine: a count or a description was read instead of the
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

**The battle command wheel** has seven labels, every one read off a rendered
frame of the first battle: **Attack, Magic, Focus, S-move, Guard, Run, Item.**
The d-pad rotates it, not the stick, and A commits; committing S-move put
Vyse's S-Move name box on screen, so a non-default command does execute from a
script. Measured transitions: Attack -right-> Magic -right-> Focus; Attack
-left-> Item -left-> Run; Run -right-> Guard -right-> S-move. The ring's order
is **not** established -- further presses past Focus and past Run changed
nothing, and the frames cannot tell a refusal to wrap from a dropped press, so
drive it one confirmed step at a time. `docs/FINDINGS.md` also records the
menu's code (`fn_8007A890`, its mask in `fn_80079F74`, targets in
`fn_80079C5C`), which says *four* selectable entries and so disagrees with the
screen. Both are written down; neither has been reconciled.

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
SOA_POKE=16000:0x80305CF0=0x4D453130,16000:0x80305CF4=0x33412E53,16000:0x80305CF8=0x43540000,16000:0x80311AC0=103,16000:0x80311AC4=103,16000:0x80311AC8=0x61000000,16000:0x80311AEC=15
```

That is `"ME10" "3A.S" "CT\0\0"`, then the committed and working map
numbers and the letter (belt and braces: the name overrides them), then the
state. No button press is needed. It needs a run that has already reached the
field, which the `battle` scenario's preamble plus an A every 150 frames does
by about frame 14710; `build/run_namewarp.log` has the whole command. `a103a`
-- the first dungeon island, never reached by any run before -- draws its
first frame 100 frames after the poke and plays its own arrival scene. The
game zeroes the name's first byte after reading it, so poke all three words
for every warp: seven pokes a warp, 36 warps a run.

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

The plan's cheap, well-specified items are done. What is left is larger and
needs more judgement about what the port is for.

1. **Use the teleport.** It works (see above) and nothing has used it yet.
   The obvious first run is a census: 36 warps a run, one every 600 frames,
   `SOA_SNAP` on, and a table of which of the 252 maps render, which load
   and draw black (like `a200a`, probably story-gated), and which break the
   runtime -- the last being the reason to do it, since every map past the
   opening is code and data this port has never run. Check the first run
   prints `[poke] N poke(s) armed` with the N you asked for: the binary must
   be linked after commit 1bad9fb, and the one on disk before 2026-09-22 was
   not.
   Walking is still unattempted and still needs no position feedback -- the
   hold's exit is a contact volume, event id 6500, and ids 6000-6999 fire on
   contact with no pad read, so a stick script could do it if it knew where to
   walk.
2. **The decompilation grind** (Track F). Two SDK libraries are complete. The
   match oracle is now sound, so a match means what it says.
3. **Speed** (plan C4), read against the profiler rather than against the
   renderer track's assumption — see wrong statement 3 above.

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
- **`tools/disasm.py` does not track update-form loads in its annotations.** At
  0x801019C0 it labels `lbz r0, 8(r3)` as `@ 0x80310008`, but the preceding
  `lwzu` had already moved r3 to 0x80311AC0, so the byte is at 0x80311AC8. Do
  the arithmetic rather than trusting the comment.
