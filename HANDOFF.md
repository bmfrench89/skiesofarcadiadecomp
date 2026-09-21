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

The port boots, plays the opening with dialogue, wins the first battle, and
moves around the Valuan ship's hold with menus, a minimap and random
encounters. It renders in a window at the game's 30 fps cap, plays music,
effects and speech, takes keyboard or gamepad input, and reads and writes a
memory card. Headless it runs about ten times real time.

| | |
|---|---|
| Functions recompiled | 7,144, 100% instruction coverage |
| Byte-matching decompiled symbols | 100 across 21 units (83 functions, 17 data) |
| Of those, running in the port | 12 |
| Python tests | 484 |
| Self-test cases | 73 |
| Scenarios | 13 |
| Pinned frame hashes | 23 |

"100 matching" deserves its caveat: 65 are compared in full, and 35 carry words
the checker can only decide by linking, so it reports them separately and does
not count them as matches. Two data symbols have none of their four bytes
compared. Seven of the twenty-one units are fully verified; fourteen are not.
That is the oracle being honest rather than a defect, but do not quote the
round number without it.

## Seven things the history says that are wrong

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

The pattern behind all seven: a count or a description was read instead of the
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

1. **Drive the game past the ship's hold.** This is the visible milestone and
   everything else is easier once scripted play can reach further. `SOA_PAD_RECORD`
   and `SOA_PAD_FILE` exist for exactly this: play it in the window, replay it
   headlessly. Plan item D5.
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
