# Plan

What to do next, in the order it should be done. [ROADMAP.md](ROADMAP.md)
says what is done; this says what to pick up on an evening and how to know
when to put it down. Sizes are evenings: **hours** is one sitting, **a day**
is a long evening or two, then **several days** and **week-plus**. Tracks
are independent; inside a track, order matters.

## Where the port actually is

| | |
|---|---|
| Functions recompiled | 7,144, at 100% instruction coverage |
| Hand-decompiled and byte-matching | 41 across 15 units — 0.18% of `.text` |
| Of those, running in the port | 9 (`config/hle.txt`) |
| Python tests | 229 in 13 files |
| Native code compiled by CI | all 22 `runtime/*.c`, the nine MSL twins against libc, and a renderer-only binary (A1) |
| Frame or audio check CI can run | the renderer's two pixel checks, on a synthetic frame; audio still needs a built binary and a dump |
| Captured frames usable as a corpus | 20 in `build/fifo`; 13 of them have a reference PNG |
| `field/` files any saved run has opened | 21, of 1,862 stems in `extracted/field` — and only with `SOA_TRACE` on |
| Memory card bytes read or written, ever | 0: every log says `card 0 bytes read, 0 written` |
| Saved runs that played a sample | 0 of 27: every `[audio]` line says "(no output device)" |

The port boots, plays the opening, wins the first battle and walks the
Valuan ship's hold with menus and random encounters. Rates: one saved
session was windowed — `build/boot_window.log`, the only `[window]` line in
`build/` — and its 667 screen copies against 1,495 VI retraces are 26.7 game
frames per guest second, against the game's 30 fps cap; `boot_perf.log`
gives 28.5 the same way but is headless. A rate quoted near 60 counts VI
fields, of which the game presents every other one. No saved log records
wall-clock time at all, so every rate here is per *guest* second and equals
wall time only at `SOA_SPEED=1`; the evidence that headless runs hold about
ten times real time is FINDINGS.md's 594 retraces a second at `SOA_SPEED=10`.

What the port could not do, until A1 and D1, was tell you tomorrow that it
still does all that. CI now compiles every line of the runtime and checks two
synthetic frames pixel by pixel, and the scripted runs everything above is
judged by are committed in `config/scenarios/` instead of living in one
person's shell history. What is still unchecked is the game itself: no saved
run's counters, no sample, and no captured frame is compared with anything
until someone runs the A2 sweep.

**Start here:** D1, A1 and A2 were the first three, and are built; what is
left of A2 is a sweep only the owner's machine can run, and what is left of D1
is a README table. So: A3, then A4, which every timing claim below depends on.
After that, any track, cold.

---

## Track A — Ground truth

**A1. Compile the runtime in CI, then the render self-tests** — *built.*
**Built.** The `native` job in `.github/workflows/ci.yml` runs three steps on
windows-latest, each of which fails loudly rather than skipping when there is
no `cl.exe`: `tools/citest/compile_runtime.py` compiles all 22 `runtime/*.c`
with `/c` and the flags in `tools/soa/toolchain.py`, plus nine warnings
promoted to errors (C4013 first: nothing links here, so an implicit
declaration is the only sign a rename left a caller behind);
`tools/citest/dc_check.py` builds `src/sdk/msl/string.c` and `mem.c` with the
`/Ddc_*` renames `recompile.py` derives, links them to
`tools/citest/dc_driver.c` and compares nine routines with host libc over
3,000 generated cases each; and `tools/citest/render_check.py` links `gx.c`,
`gxr.c`, `gxr_tev.c`, `png.c` and `tools/citest/render_driver.c` — two stubs,
`hle_report` and `mmio_read32`, were all the renderer needed — and runs the
two pixel checks from `selftest.c:102-158` with no disc and no `gen/`. The
recipe in the driver is a verbatim copy of `selftest.c`'s, since that one is
static in a file that cannot link outside the port;
`tools/tests/test_citest.py` compares the two texts so the copy cannot drift,
and also holds the `UNCOVERED` escape hatch and the stdlib-only import graph
the no-pip job depends on.
*Left:* `memset`'s fill is not really covered — `mem.c`'s `memset` wraps
`__fill_mem`, which `decomp_shims.c` answers with the host `memset`, so only
the wrapper is checked until F3 decompiles the worker. The renderer binary
prints its frame hash but asserts only the pixel counts: `ceilf`/`floorf` at
a span boundary is where two MSVC versions would differ, and nobody has run
two.

**A2. Frame hashes and a replay corpus check** — *hours, and the sweep is not run.*
**Built.** `SOA_HASH=1` makes `enqueue_copy` (`gxr.c`) print `[gxr] frame N
WxH hash <16 hex>` for every presented frame, FNV-1a over the rows after a
`gxr_flush()`, so the value is the finished frame whether or not a PNG is
being written. `float tex[8][4]` is fixed: all eight slots are seeded with
`(0,0,1,0)` — what `transform()` writes into ungenerated slots — before the
per-pixel loop overwrites the supplied ones, so an unsupplied coordinate no
longer reads stack and no longer depends on the thread count. `python
tools/scenario.py replay --bless` is the sweep: every capture in `build/fifo`
at `SOA_THREADS` 1, 2, 3 and 8, twice over, one hash line demanded per
replay, reference PNGs copied to `build/fifo/ref-before` first because
`--replay` overwrites them, and `config/fifo_manifest.tsv` written with the
capture's name, sha256 over its own `.fifo`/`.regs`/`.ram`, and the frame
hash. The input column is what lets a row mean anything on a machine that
cannot have the capture. Without `--bless` the same sweep checks against the
manifest.
*Left:* nobody has run it. It needs a built `gen/soa.exe`, `extracted/sys/`
(`main.c` wants the disc even for `--replay`) and the captures, so it is the
owner's to run — and until it has been, the manifest does not exist and the
hashes are an emitter with a reader and no data. The sweep pins the row
ownership rule for triangles only: `raster_line` and `raster_point` draw on
every worker with no `my_row` test, and the corpus contains no line or point
draw to catch it with. `hold.scn` now captures three field frames to widen a
corpus that otherwise stops at frame 12100.
*Done:* 20/20 unchanged twice at every thread count, and the right captures
named after a one-line change to blending.

**A3. Tripwires for what the runtime does not model** — *hours.*
Two silent classes. Renderer: indirect and Z textures, fog range, zfreeze,
TMEM preload, non-RGB8 EFB and BP 0xFE (BP_MASK — `080000` in every
frame-start snapshot, never written in a captured stream) are unimplemented;
warn once each from `gxr_bp_written`, with unsupported texture formats
(`gxr_tev.c:295` paints magenta silently), cache evictions, wide lines and
points, and `GX_BL_DSTALPHA` at RGB8. CPU: `mem_ptr` masks 0x01FFFFFF
(`cpu.h:22,95-97`) into a 0x01800000 `calloc` (`main.c:314`), so an EA in
`0x81800000-0x81FFFFFF` reads or writes up to 8 MB of host heap past the
buffer (`mem_zero32` writes 32 bytes of it) while every device model
bounds-checks. Allocate `MEM_MASK + 1`, warn once above `MEM1_SIZE`.
*Done:* a synthetic stream setting each renderer condition warns once each,
all 20 captures warn not at all, and a store to 0x81800000 warns instead of
corrupting the heap.

**A4. Make the profile tell the truth** — *a day.*
Every saved profile measures a different program: all 22 sit under
`[watchdog] still running after Ns`, a message no longer in `runtime/`, and
today's watchdog zeroes its samples on every presented frame
(`main.c:98-99`) then `_exit(5)`s, so a healthy run produces no profile and
the saved ones cover a stall. Nothing has ever sampled a worker: the sampler
reads `g_state->pc`, the main guest thread. No item here cites those
percentages any more. Rebuild it with per-worker busy and idle timers, one
on `parse()`, disjoint buckets (`draw / prepare / decode` print as siblings
though decode is inside prepare is inside draw), samples named through
`config/functions.tsv`, an `s->pc` store in each `decomp_swap.c` adapter so
a native swap stops being invisible, and wall time in the report.
*Done:* busy plus idle within 5% of wall times threads, a named function
table summing to 100%, the same top ten twice, and game frames, guest
seconds and wall seconds reported separately.

---

## Track B — Saves

Roadmap 4.7, `[~]` in Phase 4, and the first of ROADMAP's three immediate
next actions.

**B1. Name the CARD library** — *hours.*
Step zero, and it was missing: `config/functions.tsv` holds no `CARD` symbol
at all and the 54 functions from 0x80247044 to 0x8024B28C are every one of
them `fn_*`, while everything below navigates by SDK name — `EXIGetID` is
`fn_80264A94`, `CARDProbeEx` is `fn_80248708`, the mount is `fn_80248884`.
Recovering those twice out of a disassembly is most of what makes B2 feel
long. Add them to `config/names.txt` with evidence, and wire
`symbols.apply_names_to_dtk` in (F1) so `build/dtk/obj/` gets them too. Land
F1's first half before regenerating the inventory: today that rename breaks
11 of the 41 matches.
*Done:* `python tools/disasm.py CARDMount` prints the mount, and the names
appear in both symbol files.

**B2. The three mount blockers** — *a day.*
One piece of work: each is fatal alone, two confirmed by disassembly.
`EXIGetID` writes a 2-byte command then reads 4 bytes, so the ID lands at
transaction positions 2-5 while `exi.c:89-90` emits it at 5 and 6 — the read
returns zero and the probe returns WRONGDEVICE. The mount then checksums the
12-byte flash ID against SRAM offset 58, which `exi.c:152-172` leaves
zeroed. And erase and program complete by the card's EXI interrupt, which
nothing raises: `exi_irq_pending` (`exi.c:296-302`) reports only `CSR_TCINT`
and `irq.c` maps only the three TC interrupts, so 9/12/15 are unreachable
and every write waits out a 100 ms timeout. Honour command 0x81, set CSR bit
1 after the deselect ending a 0xF1 or 0xF2 transaction, deliver 9/12/15 —
that ordering is the difficulty, since the handler re-selects to read
status.
*Done:* a run past frame 2000 reports a non-zero card read count in `[exi]`,
where every log today says `card 0 bytes read, 0 written`.

**B3. A card selftest, logging, and the plumbing** — *hours.*
The command set is provably closed, so a host-side test shaped like the ARAM
round-trip at `selftest.c:356-382` is cheap, and is what would have caught
B2. Add `SOA_CARD_VERBOSE`: nothing logs EXI per transaction, which is why
no saved log says which frame the game probes on. Fix the SRAM decode —
`exi.c:190` computes `off = c->pos - 4` and ignores the command's offset
field, so every read returns SRAM byte 0, and `exi.c:191` masks with
`0xFFFFFF00`, so `cmd | (offset << 6) | 0x100` matches only offsets 0-3.
Create the card directory (`build/cards/` is empty), accept
`SOA_CARD=<path>`, flush after each page program.
*Done:* the selftest covers ID, status, erase, program, read-back and the
SRAM checksum; reverting any part of B2 fails it; a kill right after a save
keeps the bytes.

**B4. Mount from the title, then round-trip a save** — *several days.*
Three stages, cheapest first, since only the last needs navigation. With
B3's logging you can see which frame the probe lands on and script thirty
seconds around it — `SOA_PAD="1600:start,1700:sdown,1750:a"` is the shape —
exercising probe, mount and read. Then pre-seed a Dolphin-formatted blank so
Continue runs. Only then drive to a save point, which needs D3: nobody knows
how far in the first save point is, and the first real write will probably
expose a fourth defect, the way the first real ARAM fetch did.
*Done:* the image round-trips both ways — Dolphin shows a Skies of Arcadia
Legends file with its banner, and a Dolphin-made save loads from the title.
Whether a blank image draws a format offer is an observation to record, not
a criterion: no mount has ever succeeded, so nobody has seen one.

---

## Track C — The renderer

The feature set matches what this game uses closely: zero indirect stages in
all 10,479 GEN_MODE writes, RGB8/Z24 in all 7,351 PE_CONTROL writes,
trilinear never requested, zero line and point draws.

**C1. Dump vertex attributes, then settle the searchlights** — *a day.*
The one known open rendering defect, and the measurement needs no console.
`fifo.py:216-223` steps over the vertex payload without reading a byte, so
add `--verts <range>` printing normals after the XF normal matrix. The 90
beam draws are additive, one TEV stage computing `clamp(2 * texel * ras)`
lit by light 0 alone with ambient (24,24,63), directional from view-space
~(+0.995,+0.094,+0.015) — so the colour collapses to that ambient exactly
when the normal is perpendicular to it, which is the near-black we see. A
near-zero dot product means the quads are meant to be ambient-lit and some
other term is wrong; a normal facing the light means our vertex data
differs. If it comes to that, capture this one frame in Dolphin; `.dff`
container support waits until a second question needs it.
*Done:* an answer naming the normals and the dot product, or the sprite's
alpha ramp (which decides slab versus beam), or a Dolphin screenshot of the
same draw — and, if the cause is ours, bright beams in `4000.png`.

**C2. Two small defects in the clip and texture paths** — *hours.*
`clip_polygon` (`gxr.c:902-930`) clips the near plane and `w` only, so far
geometry is rasterised with depth clamped to 0xFFFFFF, where LEQUAL passes
against a cleared buffer. And `source_hash` (`gxr_tev.c:86-109`) samples 64
words whatever the texture's size, so a large texture rewritten in place
renders stale. (The third defect that used to sit here, `float tex[8][4]`,
moved into A2, which trips over it.)
*Done:* a quad past the far plane shades nothing, and one rewritten word in
a 128 KB image shows up.

**C3. The EFB copy vertical filter and destination stride** — *a day.*
The game programs a real 7-tap deflicker filter — BP 0x53 = `30A208` and
0x54 = `00820A` in the frame-start snapshot of all 20 captures, weights
8,8,10,12,10,8,8 over 64 — and we apply none of it, so our output is sharper
and more aliased than the console's and no pixel-exact comparison can
converge. No captured stream ever *writes* 0x53, 0x54 or 0x4E; the game sets
them outside the window. BP 0x4D, the destination stride (32 writes against
32 copies across the corpus), is already read into `D->cp_stride` at
`gxr.c:1351` and referenced nowhere else — dead, not missing. Skip the copy
Y-scale: 0x4E is `000100`, the identity, in all 20, so it cannot change a
committed pixel. After A2 and A4, because it multiplies copy read traffic
sevenfold on workers that may already be saturated.
*Done:* a one-pixel white line copied with the game's coefficients leaves
12/64, 10/64 and 8/64 in the neighbouring rows.

**C4. Speed, when it is needed** — *hours, then several days.*
The port is 5-11% short of the 30 fps cap and the items above cover that
several times over; this matters when the heaviest content is reached, and
for slice 7.5. The limiter is the fragment path: 862.5 M fragments in
`boot_window.log` (792,513,505 shaded, 69,749,462 alpha-rejected, 269,041
depth-rejected) over 8 workers reproduces the windowed frame period — and
that is counter arithmetic over `gxr.c:54`, not the profiler, so A4 does not
disturb it. Two free things first: test depth before the TEV where the alpha
test cannot reject the fragment (8% of fragments reaching the TEV in
boot_window, 53% in boot_ship, are discarded after every stage has run; the
trap is that XOR of two always-true comparisons is always false), and
resolve the perspective divide once per texcoord, not twice per stage. The
prize is specialising the fragment body per draw.
*Done:* the cheap pair leaves `failed depth` within 0.1% and all 20 diffs at
zero; the specialisation reaches 1.5x on the heaviest captures, or it lands
on A2 and nowhere else — a wrong body neither crashes nor diffs.

---

## Track D — Reach

Open-loop scripts have hit their ceiling: in `build/boot_field.log` the last
asset load lands just after `[si] frame 14710` and the run then mashed A
until frame 55,360 without loading anything new. A script can advance
dialogue and win a fight; it cannot walk to a door.

**D1. A scenario library and a run checker** — *done, bar one line of README.*
**Built.** `config/scenarios/` holds eleven `.scn` files — title, newgame,
capture, opening, battle, hold, encounter, monkey, audio, speed, window —
each with the pad script, the frame budget, the environment, what it shows, and an
`evidence:` line naming the log in `build/` or the section of FINDINGS it was
recovered from. `tools/scenario.py` lists them, prints the command for one in
three shells, runs one headless, and checks a run or a saved log against the
four invariants that cannot drift (exit code, zero unmodelled MMIO with
`SOA_STRICT` on, zero unknown FIFO bytes, zero bad vertex refs), plus a fifth
look at the input: a script the port did not read as written makes the other
four true about a run that drove nothing. The two counters also fail at zero
with nothing behind them, since a renderer that drew nothing would otherwise
pass. What could not be recovered is labelled: the logs print buttons only,
so the stick events in `hold`, `encounter` and `monkey` are reconstructions
or absent, and `window`'s whole script is one, since the only windowed run
saved was driven by hand. Each file says which.
*Left:* `README.md:75` still describes `SOA_FRAMES` as doing `SOA_SNAP`'s
job, the README table has no row for `SOA_SNAP`, `SOA_STRICT` or `SOA_HASH`,
and neither README nor CONTRIBUTING mentions `config/scenarios/`,
`tools/scenario.py` or `tools/citest/` at all — the library is invisible to
anyone who has not read this file. The map list still waits on D2 and D4.
*Done:* one command runs the title scenario end to end, prints what it
checked, and exits non-zero naming the invariant when one breaks.

**D2. Name every disc read, and add a poke** — *hours.*
"How far did this run get?" is answerable only by `SOA_TRACE` and
hand-reading register dumps — the 21 `field/` files any saved run names come
from `[trace] LoadStart` lines — and tracepoints are compiled in, so moving
one costs a recompile. `main.c:321-335` already reads `sys/fst.bin` into
guest RAM while `dvd.c` holds no FST code and `dvd_init` (`dvd.c:79`) takes
only the ISO path: build the offset-to-path table there, print a
`[progress]` line the first time each file is touched, and end the report
with the ordered map list. Add `SOA_POKE` and `SOA_DUMP` while there —
nothing in `runtime/` can write guest memory.
*Done:* a run with `SOA_TRACE` unset prints the same file list the trace
gives, and a poke changes what the matching dump reports.

**D3. Record live input, replay it headlessly** — *hours.*
The gate on B4's last stage and on D5. `window.c:163-213` reads keyboard and
XInput every poll and stores nothing, and `SOA_PAD` expresses only twelve
buttons and a full-deflection stick (`si.c:66-67,93-97`), which is why the
stick in the saved monkey runs is invisible in their own logs (`si.c:150`
prints buttons only). Add `SOA_PAD_RECORD=<path>` keyed by frame, and
`SOA_PAD_FILE` to replay it.
*Done:* sixty seconds played in the window, replayed headless, enters the
same field maps in the same order per D2 and ends within a few frames.

**D4. A deterministic guest clock** — *several days.*
The guest timebase is the host wall clock scaled by `SOA_SPEED` and every
device completion hangs off it, so the same script does different amounts of
game work on a loaded machine: three runs presented 126,521 / 121,795 /
124,051 frames against near-identical retraces (269,343 / 269,381 /
269,335), a 4% swing, while the pad script is keyed to frames. Advance the
timebase from a deterministic counter, keeping the wall clock as the
default. The size is risk, not code: the AI sample counter, the DMA cadence
and the DVD and ARAM delays all hang off this clock, and giving DVD
realistic delays is what removed the memFree errors. Not before D3.
*Done:* two headless runs of one scenario give byte-identical retrace, DI,
PE, draw, vertex, triangle, pixel and copy counters, under load as well.

**D5. Battles, then the ship and the overworld** — *a day, then week-plus.*
Roadmap 7.2 (`[~]`) and 7.3 (`[ ]`). Battles first, cheap once D3 exists:
one encounter using magic, items and Focus with the A3 warnings,
`SOA_STRICT` and `SOA_WAV` on — `/beff` holds 546 effect packages and three
have ever been loaded. Then the town and overworld, the first content
genuinely likely to break the runtime rather than merely being undriven. Do
not script it from boot: ten hours of game time costs about 3.6 hours even
at ten times real time. Get there once with recorded input, save, and start
later runs from Continue.
*Done:* one battle log using every command with no unmodelled-feature
warning; then five minutes of navigation from a card save.

---

## Track E — Audio

One thing is verified: streamed BGM, at 0.85 for the opening and 0.52 for
battle music under the overlaid mix — two of about 310 stream pairs. Bank
music (590 `.samp`/`.info` pairs), effects and battle voice are unverified,
`runtime/ax.c` has no automated test, and all 27 saved reports say "(no
output device)": no sample has ever left this port through a speaker.

**E1. An AX census: commands, PB fields, voice starts** — *hours, then a day.*
Six opcodes are parsed for length only (`0x00, 0x08, 0x0A, 0x10, 0x12,
0x13`), two more ignored outright (`0x0B, 0x0C`), and ten of the twenty PB
fields named at `ax.c:27-41` appear exactly once each — in their own
definition — so every decision about what to implement is a guess. Count
each opcode at `ax.c:372`, count PBs with non-zero `SRC_TYPE`,
`COEF_SELECT`, ITD, dpop, `is_stream` and ADPCM gain, and record the aux
peaks, which prove whether the CPU effects pass is alive. Then map each
main-to-ARAM DMA to the file most recently opened and count voice starts per
source: nothing shows the SFX, voice and music banks ever starting a voice,
since the long runs average 3.4 to 5.8 voices per 5 ms frame.
*Done:* one run prints a count per opcode, the non-default PB fields, the
aux peaks, and a non-zero start count for `tone.samp`, a music bank and
`STV00.SAMP`. A zero in any of the three locates the defect to the driver.

**E2. Testable audio: a selftest case, then a frame capture** — *a day each.*
458 lines of the most intricate hand-written code in the port have zero
coverage; the only audio test covers the Python ADPCM decoder, which is not
the code that runs. Build one AXPB in guest scratch, known ADPCM frames in
ARAM and a minimal command list, and check the 160 output samples against
hand-computed values, with a hard pan, a ramp and a loop over the end. Then
mirror `SOA_FIFO_DUMP` with `--replay-ax` so a mix defect can be bisected.
*Done:* breaking any Q15 shift, the loop restore at `ax.c:113-117` or the
right-first output order fails a named check; and a replayed frame is
byte-identical to the live run's.

**E3. Measure the waveOut path under a real device** — *hours.*
The only path where an audible defect can appear that no correlation test
would catch, and it has never been run: a block is dropped outright when the
device is behind (`audio_out.c:113`), and `dsp.c:216-219` advances the DMA
clock one period per poll, so a guest stall is made up as a burst delivered
faster than real time, straight into that drop path. Ten minutes windowed
with sound on, a drop-rate and longest-gap line, then a deliberate stall.
*Done:* drops under 0.1% of blocks and the longest gap under 20 ms, in
FINDINGS.

**E4. Verify bank music against a reference recording** — *a day.*
The largest unverified area, and `tools/audio_check.py` structurally cannot
reach it: it correlates against a decoded `.dsp`, and bank music has no
stream to decode. Add a `--ref <wav>` mode — `best_offset()` already takes
arrays — record the same scene in Dolphin under the same D1 scenario, and
correlate. First minute of the evening: the tool imports numpy
(`audio_check.py:20`) while `pyproject.toml:7` lists only pytest, ruff and
capstone, so a fresh checkout cannot run the tool this item extends.
*Done:* a named scene correlates above 0.8 on both channels at a consistent
offset, and the dev extra installs what the tool imports. Below 0.5 is
equally useful: it localises the defect.

---

## Track F — Decompilation

Parallel and never on the critical path, but the oracle underneath it is
unsound, and that comes first.

**F1. Fix the match oracle** — *hours, then hours.*
First half, and urgent. `matchcheck.py:108` resolves each object symbol by
*name* against `config/functions.tsv`, so a unit is checkable only while its
C spells the function the way the inventory does — and `config/names.txt`,
already newer than `functions.tsv`, carries 11 addresses the inventory still
calls `fn_*`: `strcmp`, `memcmp`, `wctomb`, `strtol` and seven ARQ entries.
The next `python tools/inventory.py`, the documented regeneration step,
renames them and `matchcheck.py:115` starts reporting "not in the inventory"
for 11 of the 41 matching functions across 3 units, with no source change.
Resolve by address: parse `fn_([0-9A-Fa-f]{8})` out of the symbol, fall back
to the name — ROADMAP 1.5's own rule. Objdiff has the mirror problem, since
it matches names in `build/dtk/obj/`, generated from
`config/GEAE8P/symbols.txt`, which carries no recovered names at all;
`symbols.apply_names_to_dtk` exists for exactly this and is called from
nowhere, so wire it into `inventory.py` and correct CONTRIBUTING's claim
that both symbol files carry the same names.
Second half: any word carrying a relocation is compared on the six-bit
primary opcode alone (`matchcheck.py:130-137`), so a `bl` to the wrong
function reports MATCH and a register-allocation error in address
materialisation is invisible — in exactly the code where mwcc matching is
hardest. Compare the whole first halfword for 16-bit relocations, opcode
plus AA/LK for REL24, then check the symbol's target; the loop also skips
everything that is not `STT_FUNC`, and a wrong constant is already in the
tree (both decompiled SDK banners read Nov 10 2003 where all twelve in the
executable say Sep 5 2002). Pin the inputs too: `fetch_toolchain.py:20`
downloads a mutable `compilers_latest.zip` with no hash recorded, though
`config.yml:6` pins the DOL's sha1, and `--versions` defaults to 1.3.2 alone
while `units.txt` needs 1.2.5n, so on a fresh checkout `decomp.py:44-48`
`return 2`s at unit 11 and units 13-15 are never checked. Add `--diff
SYMBOL` over `objdiff-cli.exe`, which `fetch_toolchain.py:22,59-60`
downloads and nothing uses.
*Done:* `inventory.py` runs and all 41 still MATCH; one symbol name works in
both `matchcheck` and objdiff; changing a call target or a register reports
`differs`; the data check names `__ARVersion` and `__ARQVersion`;
`--versions` comes from `units.txt` and `decomp.py` reports every unit with
a compiler missing; `vendor/TOOLCHAIN.sha256` records what produced the 41;
and a test asserts every `src/**/*.c` is in `units.txt` with unique object
stems (`decomp.py:49` names them `build/src/<stem>.o`).

**F2. PPCArch, then MTX** — *hours, then a day.*
`sdk/ppc` is 17 functions and 240 bytes of short stubs the real SDK writes
as `asm`, so matching is transcription and a whole library goes 0% to 100%
in a sitting. Then MTX — but the split needs cutting, not deleting:
`splits.txt:23-24` gives `sdk/db/db.c` 0x80238A14-0x80239638, and the first
four functions really are the debugger (`DBInit`,
`__DBExceptionDestination`, `__DBIsExceptionMarked`, `DBPrintf`). The 25
that follow, 2,872 bytes from 0x80238B00, are the matrix library:
0x80238B60 is PSMTXConcat (`psq_l` interleaved with `ps_muls0`, `ps_madds1`,
`ps_madds0` over 4x3 matrices), 0x80238C7C is PSMTXInverse, 22 of the 25 are
leaves. With PPCArch that is 3,112 bytes against the 4,972 that match today,
a 63% increase. That scheduling is why the estimate is a day: these read as
the SDK's `asm` leaves, which transcribe rather than fight the allocator.
*Done:* all 17 PPCArch symbols and all 25 MTX symbols MATCH, and
`splits.txt` cuts `sdk/db/db.c` at 0x80238B00 with an MTX split after it.

**F3. The native path: three defects, then two free units** — *hours.*
`units.txt` sets the bar for `native` at "units free of the game's globals",
which is not the real bar: a twin must also compile under MSVC, be
endian-agnostic, touch no MMIO, and call nothing undecompiled. Three things
fail it today. `recompile.py:34`'s `_FUNC_DEF` regex captures the C keyword
`void` out of `typedef void (*ARCallback)(void);` — verified on `ar.c` and
`arq.c`, harmless only because neither is native — so the first unit with a
function-pointer typedef emits `/Dvoid=dc_void`; reject keywords and fail
loudly. `fillmem.c:9` assigns to a cast, a Metrowerks extension MSVC
rejects, so `__fill_mem` stays in `decomp_shims.c`. And `strcmp.c:59`
returns `(w1 > w2) ? 1 : -1` over words loaded from the strings: right on
PPC, inverted on x86 — guard that one comparison so the mwcc path stays
byte-identical. Free once that guard exists: `strcpy`, `strstr`, `strcmp`.
Same evening, bind the
`DCInvalidateRange` family to native no-ops — its hot loop has an empty body
because `dcbi` emits nothing (`emit.py:74`).
*Done:* `SOA_SELFTEST=1` agrees over 12 pairs instead of 9, `units.txt`
states the four-part bar, and no sampled block falls in that family.

**F4. The next real matching puzzle** — *hours to a day each, after F1.*
`__strtoul` at 0x8025F3A4 is the last hole in the MSL numeric block:
`strtol` and `atoi` both match and both call a function with no body, so
neither unit can go native, and its 222 instructions with twelve
callee-saved registers are purely a register-allocation search.
`aramCacheStage` at 0x8022A854 is the last function of the only game file
taken apart, already named, with six matching siblings (`aramCacheRestore`,
`Save`, `Callback`, `Fetch`, `Find`, `Valid`).
*Done:* whichever you take reports MATCH. Choose `__strtoul` for a puzzle,
`aramCacheStage` for engine knowledge.

---

## Track G — Second-person readiness

None of this moves the port; all of it decides whether anyone else can run
it.

**G1. A LICENSE, and the first-hour traps** — *hours.*
There is no LICENSE, COPYING or NOTICE anywhere in the tree, so nobody can
legally fork or contribute. Then `README.md:48` says `set SOA_RENDER=1`,
which in PowerShell silently creates a variable named `SOA_RENDER=1` and
leaves the environment untouched, so the documented command gives a headless
run the watchdog stops after 20 seconds — `main.c:277` prints the right form
but only under `--help`. And nothing checks the dump is the build `config/`
describes, though `config.yml:6` already records the DOL sha1 for dtk.
*Done:* LICENSE exists and README links it, the run command works in a fresh
PowerShell window, and a mutated DOL is refused with both hashes named.

**G2. The missing pages, the corrections, the boundary** — *a day.*
`docs/TESTING.md`: what the 167 tests cover, which need capstone or MSVC or
a disc, what MATCH means, and the pre-PR list. `docs/ARCHITECTURE.md`: the
path a frame takes, and a table mapping each `runtime/*.c` to the kind of
bug that lands there. Correct SPEC §10, which names `config/symbols.toml`,
`tools/soa/sigs/`, `gfx/`, `audio/`, a C++20 runtime, SDL3 + Vulkan and
CMake + Ninja, none of which exist; say in SPEC §2 where hand-decompiled
source sits, since the rule forbids "generated code derived from the game
binary" while `src/` holds C accepted only when its bytes match; and close
the guard gaps, where CI's history scan is a separate regex omitting the
`.bin` that `guard.py:18-47` includes and the pre-commit hook `guard.py:5`
advertises is not in the tree.
*Done:* both pages exist, every path SPEC §10 names exists or is labelled a
plan not taken, and the suffix lists live in one place.

---

## Not worth doing, or not yet

**A GPU backend.** The only path to 10x and what slice 7.5 needs, but the
port is 5-11% short of a cap C4 covers several times over, and it would
replace the one piece of this port that is a trustworthy reference. The
undesigned part is `copy_to_texture` writing tiled bytes into MEM1 every
frame, which needs readback or guest-write tracking that does not exist.

**The reference interpreter (slice 3.7).** Narrower than this file used to
claim: decode is cross-checked against capstone (19 tests in
`test_crossval_capstone.py`) and two tests in `test_emit.py` compile and run
emitted C, paired singles included. What is missing is the forms nobody
hand-picked, and closing that means a second complete 750CL implementation
plus a comparator. Track A catches more regressions per evening.

**Sega's AX driver, `__ARChecksize`, MetroTRK, MSL printf.** 283 functions
and 22,518 instructions that already run correctly and cause no known audio
uncertainty; `__ARChecksize` is larger than the whole decompilation to date
and runs once; TRK is reachable only through exception vectors.

**Guest-global accessors, and host save states.** 28 of the 41 matching
functions touch guest state or call something undecompiled. Two mechanisms
are missing: byte-order-aware accessors over guest memory, and a
native-to-guest call path — an adapter holds host pointers and no
`CpuState`, though `main.c:49` keeps `g_state` and `threads.c:189-196` shows
there is exactly one, so `dispatch(g_state, addr)` from an adapter is the
mechanism when it is wanted. Do F3 first, then revisit with `ar.c`. Host
save states are worse: guest control state lives in the host C stack and in
fibers, and the game's own card save is the same capability at less risk.

**A second region, and generated bindings.** Seven config files sit at
`config/` top level as bare GEAE8P addresses, `recompile.py:176` hardcodes
`config/GEAE8P/units.txt` against its own `--config`, and six `runtime/*.c`
files define or call C identifiers that are literal addresses. A PAL build
means hand-editing all of them; the fix is a generated `gen/bindings.h` from
the table `emit.py:269-276` already walks. Cheaper now than later, but
nothing needs a second region yet.

**The unimplemented GX features.** Indirect and Z textures, fog range,
zfreeze, TMEM preload, trilinear, line and point width, EFB destination
alpha: all absent, all unused across 38,084 captured tri-strips. A3 is the
right response, since "not used" means "not used in the first hour".

**The AX compressor, ITD, dpop, SETUP ramps, the AI rate bits.** Gate them
on E1's census: measured clipping is 104 samples in 7.5 minutes, and ITD and
dpop have no evidence behind them. The exception on its own merits is the
rate converter, two-tap linear where the hardware is four-tap polyphase.

**The card unlock challenge-response.** Closed, not parked: the runtime has
no DSP interpreter by design, and reporting the card unlocked makes the SDK
skip the challenge — the test is `lbz r0, 20(r1)` then `rlwinm r0, r0, 0,
25, 25` at 0x802489AC inside the mount. Nothing left to do.

**Band decomposition, content-sniffing in the guard, per-file splits for
game and middleware.** The first assumes setup is wastefully duplicated
across workers, and it partly is: rows interleave every Nth (`gxr.c:1156`)
and the average triangle runs 58 to 232 pixels — 8 to 20 rows — so most
workers own rows in most triangles. Bands trade that for load imbalance, so
it waits on A4 showing setup is a measurable share. The second defends
against a case nobody has come close to hitting. The third is several days
for the SDK libraries and a separate week-plus for game and middleware.

---

## Open questions

Not answerable by reading this repository, and each blocks an item.

**Is the game's logic clock the VI retrace or the presented frame?** Retrace
counts track wall time and frame counts do not, which is strong evidence for
the retrace, but nobody has traced the main loop around `VIWaitForRetrace` —
and it decides how much D4 buys.

**Does the card mount once B2 lands, and where is the first save point?**
Each blocker is fatal alone; whether a fourth sits behind them is unknown,
and the existing scripts reach only the hold. Answered by a thirty-second
run once B3 can log the transaction, then by playing (D3).

**Is mwcc 1.2.5n right for the remaining SDK libraries, and what year did
`src/sdk/ar/` come from?** `ar.c` and `arq.c` match with 1.2.5n and all
twelve SDK banners in the executable say Sep 5 2002, while both decompiled
banners say Nov 10 2003 — so those files carry at least one wrong constant,
and no other library has been checked against either compiler.
