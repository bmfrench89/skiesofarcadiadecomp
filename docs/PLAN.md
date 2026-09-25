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
| Hand-decompiled and byte-matching | 100 symbols across 21 units — 83 functions (8,084 bytes, 0.29% of `.text`) and 17 data |
| Of those, running in the port | 12, of the 25 bindings in `config/hle.txt` |
| Python tests | 1017 in 54 files (327 need MSVC and skip without it) |
| Native code compiled by CI | all 27 `runtime/*.c`, the nine MSL twins against libc, and a renderer-only binary (A1) |
| Frame or audio check CI can run | the renderer's two pixel checks, on a synthetic frame; audio still needs a built binary and a dump |
| Captured frames usable as a corpus | 23 in `build/fifo`, all pinned in `config/fifo_manifest.tsv` |
| `field/` files any saved run has opened | 347 of 1,862 stems in `extracted/field`, 242 of them root maps (every warpable map was warped to; the 15 world-map warps share the files of the story stage the game picks) -- 21 and 5 before 2026-09-22; only with `SOA_TRACE` on |
| Memory card bytes the game has written | 40,960 — it formats a card (2026-09-18) |
| Saved runs that played a sample | 0 of 27: every `[audio]` line says "(no output device)" |

Do not quote that 100 without its caveat: 65 of them are compared in full and
35 carry words only a link can decide, which `tools/decomp.py` reports
separately and does not count as matches. Seven of the twenty-one units are
fully verified. That is the oracle being honest, not a defect — and the figure
was 41 until F1 fixed an oracle that compared relocated words on six bits.

The port boots, plays the opening, wins the first battle and is carried by
the story through the Valuan ship's hold into `a101b`, which has menus and
random encounters (the hold has no encounter table; FINDINGS section 11). Rates: one saved
session was windowed — `build/boot_window.log`, the only `[window]` line in
`build/` — and its 667 screen copies against 1,495 VI retraces are 26.7 game
frames per guest second, against the game's 30 fps cap; `boot_perf.log`
gives 28.5 the same way but is headless. A rate quoted near 60 counts VI
fields, of which the game presents every other one. No saved log records
wall-clock time at all, so every rate here is per *guest* second and equals
wall time only at `SOA_SPEED=1`; the evidence that headless runs hold about
ten times real time is FINDINGS.md's 594 retraces a second at `SOA_SPEED=10`.
**Measured 2026-09-24 (H1), drawing every frame:** 22.3 fps in the opening and
17.7 in the Dangral base, against the game's 30 -- windowed play draws every
frame, so these are the rates a player sees in heavy scenes. The 26.7 above
was the logos and title.

What the port could not do, until A1 and D1, was tell you tomorrow that it
still does all that. CI now compiles every line of the runtime and checks two
synthetic frames pixel by pixel, and the scripted runs everything above is
judged by are committed in `config/scenarios/` instead of living in one
person's shell history. What is still unchecked is the game itself: no saved
run's counters, no sample, and no captured frame is compared with anything
until someone runs the A2 sweep.

**What is next, in order: [PLAN-NEXT.md](PLAN-NEXT.md).** The slices' text
lives in [PLAN-60FPS-MODS.md](PLAN-60FPS-MODS.md) (H, M, F4+, S),
[PLAN-GAMEPLAY-MODS.md](PLAN-GAMEPLAY-MODS.md) (P, K, T, R, N, X) and
`docs/specs/`.

**Start here:** the cheap, well-specified items are gone. Done and run: A1,
A2, A3, A4, B2, B3, B4, C0, C2, C3, D1, D3, E1, F1, F2, F3, G1 and G2. Half-done
and named in place: B1 (one step needs the disc), C1 (the instrument is built and the defect was not what the
entry said), E2 (the selftest half).

What is left is larger and needs judgement about what the port is for: **D5**
is the visible milestone and the one a person would notice, and since
2026-09-22 a seven-word poke reaches field maps no run had seen; **C4** and
**D4** are multi-day, and Track F is a grind that is now worth doing because F1 made
a match mean what it says. Read `HANDOFF.md` before picking any of them — nine
confident statements in the history are wrong and it lists them.

---

## Track A — Ground truth

**A1. Compile the runtime in CI, then the render self-tests** — *built.*
**Built.** The `native` job in `.github/workflows/ci.yml` runs three steps on
windows-latest, each of which fails loudly rather than skipping when there is
no `cl.exe`: `tools/citest/compile_runtime.py` compiles all 27 `runtime/*.c`
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
*Run, and it earned itself.* The manifest exists and all 23 captures match at
1, 2, 3 and 8 threads. It has already caught two real things: the suite
overwriting its own corpus, and the texture use-after-free of 2026-09-17,
whose fix moved 8 of the 23 frames — the old ones washed green and blue, so
the manifest had been pinning broken output until those were re-blessed. The sweep pins the row
ownership rule for triangles only: `raster_line` and `raster_point` draw on
every worker with no `my_row` test, and the corpus contains no line or point
draw to catch it with. `hold.scn` now captures three field frames to widen a
corpus that otherwise stops at frame 12100.
*Done:* 23/23 unchanged twice at every thread count, and the right captures
named after a one-line change to blending.

**A3. Tripwires for what the runtime does not model** — *built.*
Two silent classes. Renderer: indirect and Z textures, fog range, zfreeze,
TMEM preload, non-RGB8 EFB, BP_MASK, unsupported texture formats, cache
evictions, wide lines and points and `GX_BL_DSTALPHA` at RGB8 are all
unimplemented and drew something plausible instead. CPU: `mem_ptr` masks
0x01FFFFFF into an image that was 0x01800000 long, so an EA in
`0x81800000-0x81FFFFFF` read or wrote up to 8 MB of host heap past the buffer
while every device model bounds-checks.
**Built.** The CPU half is not the `MEM_MASK + 1` allocation this entry asked
for, and the difference matters: the image is the mask's whole range plus the
widest access that can start at its last byte (`cpu.h`'s `MEM_IMAGE_SIZE`),
but only the first `MEM1_SIZE` of it is *committed* — the 8 MB above the RAM
is reserved `PAGE_NOACCESS`, and a vectored exception handler (`mem_guard`,
`main.c`) catches the access violation, commits the range, names the guest
block and the address in one `[mem]` line with a backtrace, and continues. So
the common load and store pay nothing at all: `mem_ptr` is still a mask and
an add, and the detection is done by the page tables, which were walking that
access anyway. It cannot flood, by construction rather than by discipline —
the first fault commits the whole tail, so there is no uncommitted page left
to fault on and the run carries on against zeroed scratch. The message
therefore means *detected* once, not *happened* once.
`SOA_MEMPOKE=addr[,addr...]` fires it on purpose before the disc is read (it
refuses an address in the hardware window, which at that point is not set up
yet). Off Windows, or if the reservation or the handler will not take, the
whole range is ordinary zeroed memory: nothing reaches the host heap either
way, there is just nothing to say that it tried. While the invariant was
being written down, three unbounded writes into the image beside it were
fixed: `load_dol`'s bound wrapped (every term is 32-bit and two come out of
the file, so all of them are differences now), the FST `memcpy` had no bound
at all and its destination underflowed for a file bigger than the arena, and
`slurp` believed a negative length. The store path also lost a branch —
`is_gather_pipe` implies `is_mmio`, so the pipe test is now nested inside the
MMIO test and an ordinary store costs one compare instead of three.
The renderer half warns once per condition from `bp_tripwire`,
`draw_tripwire`, `decode_level` and the texture cache, each naming the
register and value it was asked with and what we do instead. Two of them were
built wrong the first time and are worth recording: the EFB copy filter was
not a tripwire, because the game programs the filter before the first frame
of every run and leaves it there, so the line would have been in every log and
the channel would stop meaning "something unmodelled was asked for" —
`gxr_report` stated it at the end of the run instead, and C3 has now removed
both. The reasoning is kept because the next always-on unmodelled feature
poses the same question. And
the cache-eviction tripwire counted a session total, which ten evictions a
frame reaches in under a second of ordinary play; it counts per frame now and
speaks at a quarter of the cache in one frame, six times the heaviest frame
in the corpus. BP_MASK fires on the *write* that the mask really does change
bits outside of, not on the mask itself, because GXSetCoPlanar writes the
mask and then the whole shadowed GEN_MODE and changes nothing outside it; the
line-width threshold is two pixels, not "anything but exactly one", because
the game programs 1.17 px in three captures.
`tools/tests/test_gxr_tripwires.py` builds the renderer on its own the way
`render_check.py` does and feeds it a synthetic stream: twelve conditions
asked for twice, each saying exactly one line, and beside each one the value
the game really does program, which has to stay silent.
`tools/tests/test_memguard.py` does the CPU half, arithmetic over the
constants plus a real build-and-run of the boot path with stubs.
*Left:* the corpus half of the criterion has not been re-run here — the
tripwires are silent on the census a reviewer decoded from all 23 captures,
but `python tools/scenario.py replay` and the eleven scenarios are the
owner's to run, and `scenario.py --check` counts only positives, so a stray
`[gxr]` or `[mem]` line has to be read out of the log rather than failing an
exit status. Two conditions have no synthetic coverage: an unsupported
texture format and a cache eviction both need a real texture, which the
stream above does not build. The warn-once flags are process-global with no
reset entry point, which is invisible today because `main.c` replays one
capture per process and `scenario.py` spawns a process per replay — but the
obvious optimisation of several captures per process would let the first
capture silence every one after it, and the fix (a `gxr_tripwires_reset()`
called from `gx_replay`) needs `gx.c`. The BP tripwires fire on writes and
the draw and copy ones on state, so a capture that merely *inherits* zfreeze,
ZTEX2 or a non-RGB8 EFB renders wrong and says nothing: a silent corpus is
evidence that nothing was asked for in those windows, not that nothing was in
force. Three unbounded writes outside this entry's files are still open and
guest-reachable: `dvd.c:95` (the length is a guest-written DMA register and
the bound wraps, so a 4 GB `fread` into the image is two MMIO stores away),
`gx.c:324` (the same wrap, with the length coming out of a display list) and
the `decomp_swap.c` adapters, which mask once and then index as far as a
guest-supplied length says. `tools/citest/render_driver.c` still allocates
`MEM1_SIZE`, which is the thing `cpu.h` now documents as the bug.
`threads.c:73` can read three bytes past the end of the RAM while walking a
back chain, so the runtime's own crash reporter can trip the wire and blame
the guest. The guard is Windows-only.
*Done:* a synthetic stream setting each renderer condition warns once each,
all 23 captures warn not at all, and a store to 0x81800000 warns instead of
corrupting the heap.

**A4. Make the profile tell the truth** — *done, and it changed what we think this port is.*
The old profile could only ever describe a stall, sampled the guest thread
alone at a rate that silently depended on whether sound was open, and
accounted for under 4% of a windowed run. It is rebuilt: per-worker busy and
idle timers, seven disjoint producer phases that telescope to the span by
shape rather than arithmetic, a sampler weighted by the interval each sample
covers, names resolved through `config/functions.tsv`, a program counter
stored in each `decomp_swap.c` adapter so natively-swapped functions stop
being charged to their callers, and game frames, guest seconds and wall
seconds printed separately. It also cross-checks itself: the report prints
the widest disagreement between the sampler and the independent timers, which
on a 3,000-frame run is 0.0% of the run.

*Measured, 3,000 frames rendered:* 103.8 wall seconds for 3,000 game frames,
6,193 VI retraces, 2.06 retraces per frame against the 2.00 the game's 30 fps
cap wants. **47.4% of the run is `SelectThread`, the OS idle loop**, and the
eight rasterizer workers are busy 8.8 seconds out of 830 seconds of thread
time. Two runs agree on the top ten.

*What that means, and it is not what Track C assumed.* This port is not
rasterizer-bound and not obviously compute-bound at all: it is running at the
game's own frame cap and idling roughly half the time. Any item below that
justifies itself by rasterizer cost needs re-reading against these numbers
first, and the honest headline rate is 28.9 game frames per second of wall
clock against a 30 fps cap.
*Done:* busy plus idle within 5% of wall times threads (0.0% unaccounted), a
named table (98% named), the same top ten twice, and frames, guest seconds
and wall seconds reported separately. **Met.**

---

## Track B — Saves

Roadmap 4.7, `[~]` in Phase 4, and the first of ROADMAP's three immediate
next actions.

**B1. Name the CARD library** — *built, with one step left that needs the disc.*
**Built.** `config/names.txt` carries 86 CARD and EXI entries with evidence,
from `CARDDoMount` (0x80248884) and `EXIGetID` (0x80264A94) down to the
callbacks the mount's state machine re-enters through. F1's first half is
wired: `python tools/soa/symbols.py` applies them to
`config/GEAE8P/symbols.txt`, and `tools/matchcheck.py` now resolves an
object's `fn_XXXXXXXX` symbol by the address it spells before by name, so
regenerating the inventory no longer unmatches a source nobody touched: the
11 matches that rename used to cost are 0, checked by regenerating into a
scratch directory and re-matching every unit, which still gives 41 of 41. `tools/tests/test_card.py` holds
the file to its shape: three tab fields, evidence on every line, an address
that is a function start, and a name that resolves to itself.
*Left:* the names are in `names.txt` alone. The committed
`config/functions.tsv` and both symbol files still spell the mount
`fn_80248884`, because `tools/inventory.py` is what merges them and it reads
the DOL. Until the owner runs it, `python tools/disasm.py CARDDoMount` says
"unknown function" and every CARD name is reachable only by address.
(`CARDMount` itself is not linked into this build — the game calls
`CARDMountAsync` — so it cannot be the acceptance test.)
*Done:* `python tools/inventory.py --dtk build/dtk-symbols.txt` (the flag is
not optional: `--dtk` defaults to nothing, and without it the names dtk's
signature database supplies drop out of `functions.tsv`, which is most of the
425 it names with the flag) and `python tools/soa/symbols.py`, then `python
tools/disasm.py CARDDoMount` prints the mount and `CARDDoMount` is in
`config/symbols.txt` and `config/GEAE8P/symbols.txt`. Re-run `python
tools/decomp.py` after: it stays at 41 of 41, which is the point of B1's
ordering note.

**B2. The three mount blockers** — *done.*
All three are fixed in `runtime/exi.c` and `runtime/irq.c`, and the game has
now been seen using them. On 2026-09-17 a 9,000-frame run driven to the title
probed slot A at frame 3418 for the first time in this project: device ID
`00000004`, clear status, read status `41`, enable interrupt, then 320 reads
of 512 bytes covering card addresses 0 to 0x9E00 — the whole five-block
system area — and the same again at frame 4292. `[exi]` reports 81,920 bytes
read where every previous log in the repository said `card 0 bytes read`.
Writes and the interrupt path remain unexercised by the game itself: with a
blank image there is nothing to write yet, so both are covered only by the
selftest. That is B4's job.

- *The device ID.* `EXIGetID` writes a 2-byte command and then reads 4, so the
  ID belongs at transaction positions 2–5, where `card_byte`'s command-0x00
  case now puts it — masked `& 3`, so every immediate split the SDK might use
  (4, 2+2, 1+1+1+1) lands the same four bytes. The value is `0x00000004`, which
  `CARDIsCard` reads as 4 Mbit, sector-size index 0 (the 0x2000 the erase uses)
  and latency index 0 (the four dummy bytes `__CARDReadSegment` sends), so the
  ID and the geometry the rest of the model implements are one decision.
- *The SRAM checksum.* `sram_init` recovers the flash ID from the image's own
  ID block, descrambling it exactly as `CARDVerifyID` does, and stores the
  complement of its byte sum at SRAM offset 58 — where `CARDDoMount` recomputes
  it, `__OSLockSramEx` returning SRAM+20 and the store being `stb r0, 38(r3)`.
  Deriving rather than inventing it is what makes an image formatted elsewhere
  verify: the flash ID presented is the one that image was made with.
- *The card's interrupt.* `card_byte` honours command 0x81, and
  `card_deselected` latches `CSR_EXIINT` on the deselect that ends a 0xF1, 0xF2
  or 0xF4. Latched, not re-derived: `__CARDExiHandler` clears the CSR bit first
  and only then reads status, so a level-sensitive bit would still be set when
  it returned and the handler would re-enter for ever. `exi_exi_irq_pending`
  reports it gated by `CSR_EXIINTMSK`, which is the bit `EXILock` drives through
  `SetExiInterruptMask`. `irq.c` delivers 9/12/15 ahead of the
  transfer-complete 10/13/16 and re-reads both after *every* handler, not once
  per pass — the deselect inside `__CARDTxHandler` is itself what raises the
  next device interrupt, and one visit per pass would spend a delivery of the
  100 ms alarm's margin on every page. The rounds are bounded, so a handler
  that never clears its own bit costs a pass, not the run.

*Done:* a run past frame 2000 reports a non-zero card read count in `[exi]`,
where every log today says `card 0 bytes read, 0 written`. **Not met: no run.**

**B3. A card selftest, logging, and the plumbing** — *built.*
**Built.** `SOA_SELFTEST=1` runs 26 card checks before anything else, against
an image of its own (`build/cards/selftest.raw`, removed and rebuilt each run,
its format time stamped from the clock so last run's bytes cannot pass for this
run's): device ID, status, set-interrupt, clear-status, sector erase, page
program, read array, the read latency on the DMA path, SRAM both ways by
immediate and by DMA, the two SRAM checksums, four consecutive programs each
with its own interrupt, the flush to disk, a reload from disk, and the byte
counters `[exi]` prints. Reverting any one of B2's three fixes fails a check
that names it — measured, one revert at a time, in a host harness — and so does
deleting irq.c's EXI delivery block or renumbering it: the interrupt checks
install `EXIIntrruptHandler` in the slot `deliver_pending` reads and count what
arrives there, rather than reading back the predicate under test.

The plumbing: `SOA_CARD=<path>` and `SOA_CARD_VERBOSE=1` (a `[card]` line per
transaction; both now in README's switch table), `build/cards/` created on the
first flush, and every framed erase or program written through to disk as it
completes, so a kill mid-save keeps what landed. The SRAM decode honours the
command's offset field and is byte-granular, which is what `__OSUnlockSramEx`
committing from offset 20 needs.

*Left:* none of it runs in CI. `main.c` bails out before `selftest()` without
`sys/main.dol`, and `tools/citest/` links the renderer only, so the card checks
run on the owner's machine or nowhere. What CI does hold is
`tools/tests/test_card.py`, which pins the agreement between `exi.c`,
`selftest.c`, `irq.c`, `names.txt` and the README — not the behaviour. A
`tools/citest/card_check.py` in the shape of `render_check.py` would fix that:
`exi.c`'s outside surface is `mem_r8`, `mem_w8`, `MEM_MASK`, `MEM1_SIZE` and
`irq_retrace_count`, so it links against a handful of stubs.
*Done:* the selftest covers ID, status, erase, program, read-back and the SRAM
checksum; reverting any part of B2 fails it; a kill right after a save keeps the
bytes. **First two met. The third needs a save, so it waits on B4.**

**B4. Mount from the title, then round-trip a save** — *done: a save written from the field loads back through Continue (2026-09-23).*
**The game has written to a memory card.** On 2026-09-18 a blank card in slot
A produced the title screen's "Proceed with formatting?" prompt, Yes was
confirmed, and `CARDFormatAsync` ran to completion: five sector erases, 960
page programs, **40,960 bytes written** where every log this repository has
ever kept said 0, and 325 completion interrupts, which are the ones B2 had to
start raising. `config/scenarios/cardwrite.scn` reproduces it from a cold
boot. The image the game left behind verifies as one the mount would accept,
and carries the game's own serial and format timestamp rather than ours.

It took three attempts, and the two failures were worth more than the
success. The format is reachable four presses from boot rather than at a save
point, because `CARDFormatAsync` is called from exactly one instruction in
the executable and its caller is the title's card dialog. But the title
consumed every scripted START: scene 10 reads the same edge to snap the logo
flyover, and snapping it is what puts the title on screen, so the press that
arrives always arrives one scene early. And the value 119 that routed the run
away from the card screen is not a menu id at all, it is the attract-mode
sentinel written when the title times out after 92.267 seconds of *host wall
clock*. Scene 12 had never once been entered in this port's history.

*Next:* the other half of the round trip. Reaching a save point still needs
D3's recorded input, and a save written by the game should then load from the
title (scene 16, the Continue arm, which has also never been entered). The
repair path is a second, cheaper write worth exercising once on purpose: a
card damaged with `tools/cardformat.py --damage dir` takes
`CARDCheckExAsync`'s repair arm inside `card_scan`, writing one sector without
any prompt at all.
*Done:* `[exi]` reports a non-zero written count, and
`python tools/cardformat.py show` reads back what the game wrote. **Met.**
**The round trip, 2026-09-23.** One word -- 0x803473B4 = 1, the request a save
point's script opcode 138 makes -- opens the game's own save menu in any
loaded field; five A presses and two X walk it to "Now saving" (frame 15900
shows the file card: #01 Valuan Battle Ship, Lv 1, 0:07, Vyse and Aika), and
the run writes 147,456 bytes. `cardformat.py show` then lists
`GEAE 8P SA_LEGENDS.000`, 3 blocks. A second boot on that card takes title
scenes 12, 13, **16, 17** -- Continue, never entered before -- reads 172,032
bytes, writes none, and starts the field from the Continue path (state 0 from
lr 0x80228B24) on `a101b`: Vyse standing at the save point by frame 2800,
against frame 14710 for New Game. Both runs used a copy of the card
(`build/savetest/`), never `build/cards/slotA.raw`. The recipe is in
`docs/research/save-load.md` and FINDINGS section 11. The repair arm above is
still unexercised.

---

## Track C — The renderer

The feature set matches what this game uses closely: zero indirect stages in
all 10,479 GEN_MODE writes, RGB8/Z24 in all 7,351 PE_CONTROL writes,
trilinear never requested, zero line and point draws.

**C0. Hand the workers off properly across a flush** — *done.*
Fixed by removing the reset rather than ordering it. Commands are numbered
and never re-indexed: `g_published` counts what the producer has handed over,
`g_ran[i]` what worker *i* has finished, each with exactly one writer, each
only ever increasing, and command *n* lives in slot `n & QMASK`. The worker's
spin now reads one shared word where it read two unsynchronised ones, so the
pair of loads whose order C does not fix is gone as a category. Every stale
read is a value that is too small, which can only make a thread wait. The
flush waits for every worker to reach the published count and then recycles
only producer-private state, so it writes nothing a worker reads.
Verified: all 23 pinned frames identical at 1, 2, 3 and 8 threads over two
passes, the scenarios hold, and a reviewer reconstructed the previous machine
code from a listing taken before the change and confirmed the old spin was
safe only by an accident of this compiler version, across three different
spellings of the same test.

**C1. Dump vertex attributes, then settle the searchlights** — *instrument built; the defect was not what this said.*
`tools/fifo.py --verts <range>` now prints positions, normals and texture
coordinates for a range of draws, resolving indexed attributes through the
command processor's array registers against the capture's memory image, and
printing normals both raw and after the transform matrix the lighting sees.
Eleven tests, all fixtures synthesised.

It answered the question and the answer is neither of the two this item
predicted. See docs/FINDINGS.md: **the beams are no longer dark** — that went
with the texture use-after-free fix — and their normals are three populations,
not one, with the end caps near-perpendicular by arithmetic rather than by
intent. This item also miscounted: the 90 additive draws are octagonal prisms
on the bridge cabins, and the beams are 54 draws with a different texture.
*Left, and narrowed twice more.* The depth theory was wrong too: the game
clears the depth-write bit across these draws and we honour it, the cloud
layer is not occluded, and a census of 43,249 draws across all 23 captures
found no draw that combines early depth with a rejecting alpha test. What
remains is coverage: no beam fragment samples a texel alpha below 176, so
the sprite's fade never appears and each beam ends at a hard quad edge.
Look at the texture-coordinate post-transform, not at shading. See
docs/FINDINGS.md.

**C2. Two small defects in the clip and texture paths** — *done.*
The clipper ran two passes, near and w, and its comment claimed the scissor
handled the far side, which is false: a scissor is a screen rectangle and says
nothing about depth, so far geometry reached the rasteriser with depth clamped
to the maximum and passed LEQUAL against a cleared buffer. It now clips three
planes through one shared routine, with the near and w expressions unchanged
character for character so that a polygon which does not cross the far plane
comes out bit-identical. The texture cache's source hash sampled a fixed 64
words whatever the image's size, so a large texture rewritten in place kept
rendering stale; it now depends on the whole image.
All 23 pinned frames are unchanged at four thread counts.

**C3. The EFB copy vertical filter and destination stride** — *done (2026-09-21).*
**Done.** `enqueue_copy` collapses BP 0x53/0x54 onto the three rows they read
and carries them in the command; `filter_sample` (`gxr.c`) applies 16/32/16,
clamped to the copy rectangle rather than to the EFB, truncating, to both
screen and texture copies. All 23 pinned frames moved and were re-blessed
after looking: the 15 captures that only copy to the screen are reproduced
*bit for bit* by applying the kernel to the previous render, and the 8 that
also copy to a texture are softer still, which is what being filtered twice
looks like. Vertical variation fell 8-43% on every frame and rose on none.
`tools/tests/test_gxr_copy_filter.py` pins the pixels without a disc.
*Two defects found on the way, both by a check rather than by reading:* the
copy drains the queue **after** it as well as before, because workers that
finished their share would otherwise run ahead into the next draw and
overwrite rows their neighbours were still sampling — four texture captures
disagreed with themselves at `SOA_THREADS=8` on one sweep in four, after three
green sweeps in a row. And seven zero weights mean the register was never
written, not a kernel that multiplies the frame by nothing; reading it the
other way copied a black frame and the renderer's own selftest said so.

*Superseded, kept for the reasoning:*
The game programs a real 7-tap deflicker filter — BP 0x53 = `30A208` and
0x54 = `00820A` in the frame-start snapshot of all 23 captures, weights
8,8,10,12,10,8,8 over 64 — and we apply none of it, so our output is sharper
and more aliased than the console's and no pixel-exact comparison can
converge. No captured stream ever *writes* 0x53, 0x54 or 0x4E; the game sets
them outside the window. BP 0x4D, the destination stride (39 writes against
39 copies across the corpus), is already read into `D->cp_stride` at
`gxr.c:1846` and referenced nowhere else — dead, not missing. Skip the copy
Y-scale: 0x4E is `000100`, the identity, in all 23, so it cannot change a
committed pixel. After A2 and A4, because it multiplies copy read traffic
threefold — not sevenfold, since the seven taps read three rows — on workers
A4 measured busy 8.8s of 830s, so throughput is not what orders this item.

**The seven taps are not seven rows, and that is what this entry got wrong.**
They are vertical *sub-samples*: two from the row above, three from the row
itself, two from the row below. So 8,8,10,12,10,8,8 collapses to **16/64 ,
32/64 , 16/64** over three rows, with nothing at all at distance 2 or 3. The
source is patent US6999100B1, the Flipper's own description — "seven samples
from three vertically arranged pixels … Three samples are taken from the
current pixel, two samples … immediately above … two … immediately below" —
corroborated by libogc, whose `vfilter` tables are labelled "line n-1 through
n+1" and whose AA sample pattern puts three vertical sub-samples per pixel at
y = 2, 6, 10 twelfths. It is **not** settled by the SDK's filter-off set
{0,0,21,22,21,0,0} (`GXSetCopyFilter` is `fn_8024EF50`; its `vf == 0` arm at
0x8024F138 loads BP 0x53 ← `0x595000`, 0x54 ← `0x000015`, and no caller in
this title reaches it — all three pass a literal `li r5,1`). That set kills
the seven-row reading, since it is an identity only if taps 2,3,4 land on the
current row, but it leaves a *five*-row grouping standing that would give
8/8/32/8/8. Anyone re-deriving this from the register layout alone lands back
on seven rows, which is exactly how the criterion below came to be wrong.
*Done:* a one-pixel white line copied with the game's coefficients leaves
32/64 in its own row and 16/64 in each immediate neighbour, and **zero** two
and three rows away — the zeros are the half that discriminates. And the
SDK's filter-off set must copy bit-identically to today's unfiltered output.

**C4. Speed, when it is needed** — *hours, then several days.*
**Superseded by H1 (2026-09-24):** drawing every frame, the port runs 17.7-22.3
fps in heavy scenes, not "5-11% short"; this item is absorbed into H15 of
`PLAN-60FPS-MODS.md`. The text below is the earlier reading.
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
*Done:* the cheap pair leaves `failed depth` within 0.1% and all 23 diffs at
zero; the specialisation reaches 1.5x on the heaviest captures, or it lands
on A2 and nowhere else — a wrong body neither crashes nor diffs.

**C5a-C5c. Recorded display lists** — *proposed 2026-09-25 in
`docs/specs/gpu-backend.md` §6, re-reading FINDINGS H4's zero-size calls;
scheduled in PLAN-NEXT M1 (C5a) and M2 (C5b, C5c). C5a done 2026-09-25
(750cef0): the chain is confirmed, and the port runs the lists at recording
(FINDINGS "Recorded display lists (C5a)").*

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

**D2. Name every disc read, and add a poke** — *the poke is done; the disc-read list is not.*
**`SOA_POKE=frame:addr=value` is built** (2026-09-21): one 32-bit word into
guest memory at the end of the named frame, once, printing what was there
before, parsed at startup so a mistyped item is refused while you are still
looking. `tools/tests/test_poke.py` covers it with no disc. It immediately
earned itself -- three pokes make the field load an arbitrary one of the 264
maps (FINDINGS "Warping the field by poke"). Note the shape of the plumbing:
`gx.c` calls a frame hook `main.c` installs, rather than calling into `main.c`,
because the renderer links on its own and PLAN A1 counts that as a property
worth keeping -- a direct call compiled cleanly and broke 29 tests at the link
step, which the compile-only CI job cannot see.
*Left:* the `[progress]` disc-read list and `SOA_DUMP`.
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

**D3. Record live input, replay it headlessly** — *built.*
The gate on B4's last stage and on D5. `window.c` read the keyboard and
XInput every poll and stored nothing, and `SOA_PAD` could express only twelve
buttons and a full-deflection stick, which is why the stick in the saved
monkey runs is invisible in their own logs.
**Built.** `window_pad` now reports the whole controller — both sticks at
their real positions, both triggers at their real values — and `si.c` writes
what the port actually read to `SOA_PAD_RECORD=<path>`, keyed by the frame
`gx.c` counts, one line per change, and replays it from `SOA_PAD_FILE=<path>`
in place of every other input. A minute of play is a few hundred lines of
text that can be read, annotated with `#` comments and cut by hand at the
line where the save point was reached, which is how a usable recording will
actually be made. While recording, the first read of a frame is that frame's
input and the rest of the frame's reads are given the same thing, so a replay
is exact rather than close.
The rest of the entry is the ways a recording is not self-contained, each
made visible rather than fixed, because the fix is D4. Frames are the right
key for the game's logic — the guest consumes exactly one pad state per frame
it presents, in all three saved runs — but they are not a clock: saved runs
differ by 30% in retraces per frame between windowed rendering and headless,
so the same input arrives at a different point in the game's own time. Each
line therefore carries the retrace count it was read at (`#r930`), and a
replay says how far it has drifted in guest time the moment it passes two
seconds' worth. A `# config` line records the switches that change the frame
rate and the memory card's path and size, and the replay prints both when
they differ — the card because the D5 workflow creates a save and then
replays the same recording against a title screen that now has a Continue
entry. Both are comments, so a v1 recording and a hand-written line still
replay. A file that ends with input still held — Ctrl-C, a kill, a crash, or
a hand cut at the save point, which is most of them — has a neutral state
added at load, so the replay lets go instead of holding a button for the rest
of the run. The run ends by itself a little after the last line
(`SOA_PAD_STOP`, default 120 frames of grace for whatever the last input
started), through `gx.c`'s frame limit, so a headless replay needs no
`SOA_FRAMES` guessed in advance. Each line is built in a buffer and written
with one locked `fputs`, and a flag stops anything following the totals,
because `si_report` runs on the thread that stops the run while the CPU
thread is still playing — five `fprintf`s per line could be spliced, and the
two halves the loader then rejected were the last two states of the run,
which is exactly the save-point case. The replay cursor advances at most one
entry per read, so a frame the guest never polls shifts a state by one read
instead of dropping it, and the count is in the report. A second run with the
same `SOA_PAD_RECORD` writes beside the first rather than over it.
`tools/tests/test_padrec.py` builds `si.c` with a miniature guest and asserts
the whole of the claim: a fake player who moves the stick and the C stick to
values a script cannot express is recorded, replayed with no player at all,
and the eight bytes the guest reads come back the same at the same frames —
plus the drift line, the configuration line, the added release, the stop and
the v1 file.
*Left:* the `*Done:*` criterion cannot be evaluated yet. It is phrased "the
same field maps in the same order per D2", and D2 is not built, so there is
no `[progress]` file list to compare; and nobody has played the sixty seconds
yet. The drift is reported, not removed: a long recording still walks off,
and D4 is the only real fix. The RTC is still the host wall clock
(`exi.c:436`), so anything the game seeds from it differs every run, input or
no input — a `SOA_RTC=<seconds>` to pin it, written into the recording
header, is the cheap fix and needs `exi.c`. Input during a frame that lasts
seconds — a load — reaches neither the guest nor the file, which one state
per frame cannot express. There is no `SetConsoleCtrlHandler` anywhere in
`runtime/`, so Ctrl-C still loses the totals line; the loader's synthesised
release is what makes that harmless rather than the writer.
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

**D5. Battles, then the ship and the overworld** — *a day, then week-plus; a route to the maps now exists.*
**The teleport works** (2026-09-22). It is the game's own warp request,
driven by name: seven `SOA_POKE` words -- the destination's script name
(`"ME103A.SCT"`) at 0x80305CF0, the map words, and state 15 at 0x80311AEC --
and the field tears the old map down and loads the new one by exactly the path
every story warp takes. `a103a`, the first dungeon island, never reached by
any run before, renders 100 frames later and plays its own arrival scene. The
stage-select route found first (state 2 and a START) is the resolver's debug
path: it skips the teardown, and its black screens were never the gate the
entry here used to blame. See FINDINGS "The name-driven warp works" and the
entries before it; `HANDOFF.md` has the command. What is left of D5's reach
is using it: a census of which of the 255 warpable maps render, and what the
runtime does with code no run has executed.
**Reached by 2026-09-23**, each with its frames opened (FINDINGS section 11):
all 255 warpable maps, field and ship-battle, in seven censuses, with no runtime fault; the developers' part select
(`ME355A.SCT`) to story parts B, H and L; the world map; a ship battle; a
field battle fought, won and returned from; the ending to "the End"; and a
save from the field loaded back through Continue (B4). What is left of D5 is
the battles the plan asked for -- magic, items and Focus, in a story state
where the game allows the fight -- and the ship and world-map controls.
**The seven battle commands are known** and measured off the screen: Attack,
Magic, Focus, S-move, Guard, Run, Item, with the d-pad transitions that reach
them. What is left of the battle half is scripting them, not discovering them.
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

**E1. An AX census: commands, PB fields, voice starts** — *done, and it took two corrections to get right.*
The end-of-run report counts every command opcode, every parameter-block field
ever set away from its default, the auxiliary bus peaks, and voice starts
attributed to the memory region the samples came from. Over the audio
scenario: 77,228 mixed frames, 351,290 voice-frames, 1,899 voice starts across
eleven regions, the tone bank 1,360 of them.

**Correction 1, and it is a real defect.** A first reading of the counts said
ten opcodes are never sent, so the ones the mixer skips are not worth
implementing. That is true only of this scenario. Disassembling the driver's
own command-list builder shows it chooses between opcode 0x05 and **opcode
0x10** on a flag, and the same flag chooses between two bits of the mixer
control word — and the mixer implements neither side of 0x10. So whenever the
game selects that mode, **every auxiliary-B send is silently discarded and the
processed result is never mixed back**: the reverb disappears, with the
command length still parsed correctly so nothing reports an error. That is
what the census's auxiliary-B peak of zero was showing. Opcode 0x00, the
setup command, is sent every frame and is also only measured for its length;
whether that matters depends on a block nobody has dumped yet.

**Correction 2.** A first reading also said the voice bank never reaches audio
memory. It does. Tracing the transfers shows 86 of them immediately after the
voice bank is opened, 262,464 bytes, contiguous, matching the file's own size
and first bytes exactly. The bank is loaded and simply never played in this
scene, so the zero start count says nothing about the driver.

*Correction, the third on this item, and it retires the "one audible gap".*
Opcode 0x10 is implemented now, folded into the arm opcode 0x05 already had,
because the payload is the same five halfwords over the same buffers and only
the surround send differs. But **this game never selects it**: the mode word
that chooses it is written from one constructor argument, and every reachable
producer passes zero — the initialiser and all six re-create sites. It is dead
code in this title and no run can exercise it, so its only cover is a
synthetic case in the selftest.
**The auxiliary-B silence has a different cause**, also visible in the census
and missed twice: the control word only ever takes the values 0, 1, 8 and 9
across 351,290 voice-frames, so the aux-B send bit is never set by any voice.
Bus B is wired up and its command is emitted every frame; nothing is ever fed
into it. **The reverb is on bus A and it already works** — reached in 41,275
frames, bus peak 8,566, returning 8,857 from the effects pass. There was no
audible defect here.
*And the setup block is settled by measurement:* the pointer is the same
address every frame and the block is all zeros, so the mixer zeroing the buses
instead of reading it is exactly right. That question is closed. The third question is answered: this game speaks, the opening does not,
and `config/scenarios/voice.scn` reaches a line.
**And the census cannot name a voice bank**, which is why its zero meant
nothing: it identifies an upload by a 32-byte prefix or by size, and the 72
speaker banks come in identical twins — two of them match across all 262,448
bytes — while the voice streams have identical left and right halves. 23% of
the disc's files can be named by neither. One name in the report is a
size-only guess for a file that run never read, and should be marked as such.

**E2. Testable audio: a selftest case, then a frame capture** — *the selftest half is done, and it found a defect on its first run.*
29 audio cases in `runtime/selftest.c`, every expectation derived from the
sample format's own arithmetic rather than blessed from what the mixer
produces — which matters, because this project has already pinned a bug in
place by blessing output once. One case failed immediately and the failure was
real: the resampler formed `(next - prev) * fraction` in `int`, and a
difference near full scale times a fraction near one overflows by exactly
32,768, wrapping a silent sample to full-scale negative. That is an audible
click on any loud sample crossing near full scale between adjacent source
samples, and the file already disagreed with itself, since the mix command
does the same multiply wide. Fixed by widening the product.

**And the port speaks.** `config/scenarios/voice.scn` reaches the end of the
first battle and the run opens a three-digit voice line, so spoken dialogue
plays. The opening genuinely contains none: of 258 field scripts, 66 name a
stream and all 66 name only the low-frequency ambience numbers, and the
opening's own script names exactly one. So E1's zero was never a driver
defect at all.
*Left:* the frame capture half — a recorded reference to compare a mix
against, which is what would catch a wrong voice rather than a missing one.

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

**F2. PPCArch, then MTX** — *done.*
Both libraries complete: all 17 PPCArch functions and all 25 MTX functions
match. PPCArch is sixteen Metrowerks `asm` blocks (there is no C for `mfmsr`,
`mtspr`, `sc`, `mffs` or `mtfsb1`, and 1.2.5n has no intrinsics) plus one
ordinary C function that matched unaided. Two of its names cannot be read off
their mnemonics: `PPCSync` is `sc`, a trap, and `PPCMfwpar` prefixes its
`mfspr` with a `sync` to drain the write-gather pipe, which is why it is 12
bytes to `PPCMtwpar`'s 8.
MTX took four units, not one, and the reason is worth keeping: `ps_matrix.c`
was built **without the peephole pass**. The rotation builders compile four
bytes short at plain `-O4,p` because the peephole folds a redundant `fmr` and
rewrites two register copies; `-opt nopeep` makes them exact. Two more
findings: mwcc orders `.sdata2` by first *use* rather than declaration, and
`C_QUATSlerp`'s constant pool order is set by an entry point the game does not
link, so the pool has a hole an unused static has to stand in for.
Seven names recovered, each argued from the library's interface and source
order rather than from one instruction.

**F3. The native path: three defects, then two free units** — *done, and the plan was wrong about one of them.*
`strcpy`, `strcmp` and `strstr` now run natively in the shipping path, taking
it from nine functions to twelve, and the selftest compares all twelve against
their recompiled twins rather than the nine it used to.

The three defects, as they actually were. The `_FUNC_DEF` regex really does
capture `void` out of a function-pointer typedef, and worse than stated: a
function-pointer *variable* trips it too, so it now rejects C keywords loudly
instead of renaming one. The string comparison really was inverted on x86,
confirmed by running it — "abcde" against "azzz" returned positive where the
answer is negative — and is guarded so the native side is right while mwcc
still emits the same bytes. But the fill routine was **not** blocked by
assigning to a cast: MSVC accepts that as a documented extension under this
project's own flags, and the unit was simply never marked native. It is
standard C now anyway, since `/Za` and C++ both reject the extension.
*Noted for whoever binds `__fill_mem`:* it passes the bar, but retiring its
shim means `memset` runs the game's word-at-a-time loop instead of the C
library's vectorised one, measured at about 4x slower for fills of 256 bytes
and up. That is a fidelity-versus-speed choice someone should make on
purpose.

---

## Track G — Second-person readiness

None of this moves the port; all of it decides whether anyone else can run
it.

G3-G7 are proposed in PLAN-GAMEPLAY-MODS.md section F. G5's DOL line is
disc-layer I3's stale-link guard, and G4's compiler half is portability
L3a/L3b.

**G1. A LICENSE, and the first-hour traps** — *done (2026-09-18).*
**Done.** `LICENSE` (MIT) and `NOTICE` exist and `README.md:31-34` links both,
the PowerShell trap is documented at `README.md:63-87` with the working form,
and `tools/checkdump.py` hashes `extracted/sys/main.dol` against the sha1 in
`config/GEAE8P/config.yml` and names both hashes when they differ.
There is no LICENSE, COPYING or NOTICE anywhere in the tree, so nobody can
legally fork or contribute. Then `README.md:48` says `set SOA_RENDER=1`,
which in PowerShell silently creates a variable named `SOA_RENDER=1` and
leaves the environment untouched, so the documented command gives a headless
run that **nothing stops at all** — the watchdog fires only when no frame is
presented, and frames keep being counted whether or not anything is drawn, so
it sits there invisible and undriveable until Ctrl-C (measured: still running
after 90 seconds) — `main.c:277` prints the right form
but only under `--help`. And nothing checks the dump is the build `config/`
describes, though `config.yml:6` already records the DOL sha1 for dtk.
*Done:* LICENSE exists and README links it, the run command works in a fresh
PowerShell window, and a mutated DOL is refused with both hashes named.

**G2. The missing pages, the corrections, the boundary** — *done (2026-09-21).*
**Both pages exist** (`docs/TESTING.md`, `docs/ARCHITECTURE.md`, 2026-09-18).
**The duplicated guard list is tied together** (2026-09-21).
`tools/tests/test_guard.py` asserts that CI's history-scan regex covers exactly
`guard.py`'s `FORBIDDEN_SUFFIXES` and that the two 2 MiB limits are the same
number. They were already identical at 28 suffixes; the point is that they
cannot part quietly now. Left deliberately as two lists rather than generating
one from the other: the CI step is bash in YAML, and a test that reads both is
simpler than a build step that writes one, and fails in the same place.
**SPEC §10 now says which of it was built** (2026-09-21). Every line of the
component tree is marked `[built]`, `[built, elsewhere]` with where it actually
lives, or `[not taken]`, and the technology table sets each planned choice
against what was built instead: C rather than C++20, a software rasterizer and
a Win32 window rather than SDL3 + Vulkan, `tools/recompile.py` driving MSVC
rather than CMake + Ninja. The two open questions that assumed Vulkan and SDL3
vendoring are struck through and settled. A banner says outright that the
section is the plan and points at `docs/ARCHITECTURE.md` for the tree, because
a reader was otherwise taking a list of four choices that were never made for a
description of what is there.
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
*Reopened 2026-09-25 as a three-to-four-week spike ending in the owner's
decision: `docs/specs/gpu-backend.md`, PLAN-NEXT M5 and gate G1.*

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

**Band decomposition and per-file splits for game and middleware.**
(Content-sniffing in the guard, parked here once, landed with
PLAN-GAMEPLAY-MODS T0 and T0c: signatures, card images by their directory,
and history read for content.) The first assumes setup is wastefully duplicated
across workers, and it partly is: rows interleave every Nth (`gxr.c:1156`)
and the average triangle runs 58 to 232 pixels — 8 to 20 rows — so most
workers own rows in most triangles. Bands trade that for load imbalance, so
it waits on A4 showing setup is a measurable share. The second is several
days for the SDK libraries and a separate week-plus for game and middleware.

---

## Open questions

Not answerable by reading this repository, and each blocks an item.

**Is the game's logic clock the VI retrace or the presented frame?** *Answered
2026-09-24 (H2): the presented frame.* A fade takes 29 frames whether a frame
lasts two fields or one (58 fields capped, 37 uncapped); the cap is the
immediate at 0x801DC4A4 and the logic advances once per frame. FINDINGS "H2".

**Does the card mount once B2 lands, and where is the first save point?**
Each blocker is fatal alone; whether a fourth sits behind them is unknown,
and the existing scripts reach only the hold. Answered by a thirty-second
run once B3 can log the transaction, then by playing (D3).

**Is mwcc 1.2.5n right for the remaining SDK libraries, and what year did
`src/sdk/ar/` come from?** `ar.c` and `arq.c` match with 1.2.5n and all
twelve SDK banners in the executable say Sep 5 2002, while both decompiled
banners say Nov 10 2003 — so those files carry at least one wrong constant,
and no other library has been checked against either compiler.
