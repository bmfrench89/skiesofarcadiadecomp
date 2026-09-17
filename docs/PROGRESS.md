# Progress log

What got built, in order, with the time each step landed. Times are local
to the machine the work ran on; the whole log so far is one overnight
session (15–16 September 2026). The roadmap says what is done; this says
how it went.

## Evening: analysis and tooling (20:11–21:30)

- Disc extraction (FST parsing, RVZ decoding), the game-data guard and CI,
  the Gekko decoder, the AKLZ container decoder with an exhaustive gate
  over every file on the disc.
- The spec, roadmap and findings revised after an adversarial review:
  per-vertex submission is inlined, so the port needs a write-gather pipe
  and a real GX implementation, not API interception.
- Control-flow recovery: basic blocks, functions, the call graph; six
  decoder defects found by cross-validation against two other decoders.

## Late evening: the whole executable as C (21:30–23:30)

- mwcc switch tables resolved by walking definition chains backwards;
  function recovery converged to 99.77% size agreement with the
  decomp toolkit's view of the same binary.
- Milestone M3: 696,171 instructions translate to C that compiles.
- Guest threads on host fibers; interrupts delivered at the idle loop.

## Night: hardware models, first frames, sound (23:30–02:40)

- DVD, the GP front end, the DSP mailbox protocol, interrupts at loop
  edges, the game's own printf: the game boots to its main loop.
- The software GX renders the first frame from the game's command stream;
  the serial interface and a scripted controller reach the title screen;
  frame-based input scripting plays the opening cutscene.
- Per-draw TEV setup, worker threads, a deferred command queue, persistent
  textures, fog and mipmaps; a window with live keyboard and gamepad
  input; the AX mixer and sound output; the EXI bus with a memory card,
  the real-time clock and SRAM.

## Small hours: the first logic divergence (02:40–04:15)

- Diagnostics for chasing divergences (tracepoints with register dumps,
  watchpoints, a strict mode that stops at the first garbage pointer).
- DVD and ARAM commands given realistic completion times.
- The battle-transition crash: the ARAM DMA control register did not read
  back its direction bit, so every fetch from ARAM became a store that
  wiped the cached package. One line; the selftest now round-trips a DMA
  each way.

## Morning: the game opens up (04:15–07:45)

- The first battle plays through; the scripted controller learns to
  repeat and hold; guest time can run faster than the wall clock.
- The last four unresolved switches (bound check by conditional return);
  the field after the battle loads and Vyse walks the Valuan ship's hold.
- Text: the texture coordinate scale registers are indexed by coordinate,
  not by map. Dialogue, names, menus and battle messages appear.
- RVZ junk runs regenerated from their seeds; streamed music verified
  against the disc by cross-correlation; the write-gather pipe fast path
  (headless, the game runs about ten times real time).
- The title backdrop's black wedges: a rasterizer row-span overflow on a
  nearly horizontal edge, now guarded by a synthetic-frame selftest.
- A decomp-toolkit project (`config/GEAE8P/`) with the SDK split per
  library; 61 functions named from their own diagnostic strings.
- Three 25-minute mixed-input runs at triple speed: menus, random
  encounters, a game over and a restart from the title, no errors.
- The decompilation pipeline: the original Metrowerks compiler fetched
  into `vendor/`, hand-written C compiled and compared word for word with
  the executable, and the same C compiled natively and run against its
  recompiled twin on random inputs. Nine MSL string and memory routines
  match, and the port now runs them natively in place of the translation:
  the first decompiled code in the shipping path. Three of the
  game's ARAM cache helpers followed (`src/soa/aramcache.c`).

- The memory card, read for the first time. Three defects each fatal on
  their own kept every mount from starting: the device ID landed at the
  wrong byte of the transaction, SRAM held no flash identifier for the
  mount to checksum, and the card's completion interrupt was never
  raised, so every write waited out a 100 ms timeout. With those fixed
  the game probes slot A at frame 3418 and reads all five system blocks,
  40,960 bytes, twice. A selftest covers the command set end to end,
  including that reverting any one of the three fixes fails it.

## Open

- Saves: the card is read but never written. A blank image has nothing
  to load, and no scripted playthrough has reached a save point.
- The battleship's searchlight beams render dark; every step matches the
  hardware rules as modelled, so a reference capture is needed.
- Beyond the hold: the ship and overworld sections, and the long tail of
  every scene.
