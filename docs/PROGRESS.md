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

- The card mounts. `tools/cardformat.py` writes a formatted image by
  laying down the five system blocks the way the game's own format
  routine lays them down: the identity block with its serial derived
  from the flash identifier through the SDK's own pseudorandom
  sequence, both directory copies, both allocation tables, and every
  checksum the mount recomputes. No Dolphin image was needed to get
  there. Traced through a real run, `__CARDVerify` returns 0 and the
  game's own card layer receives it: the first successful mount.

- Colours, corrected. Mounting the card made the game draw something it
  never had, and that crashed the renderer: a worker thread reading a
  texture buffer that had already been freed. Two defects, both
  pre-existing. A draw captured its queue slot and vertex arena, then
  looked up its textures, and that lookup could flush the queue and
  reset both underneath it, so the workers re-ran a stale command
  holding pointers the same flush had freed. Separately, a palette load
  freed up to 256 cached textures in one call without the check that
  bounds how many may be freed between drains. Fixing them changed 8 of
  the 23 pinned captures, and the new frames are the correct ones: the
  old renders were washed green and blue over whole scenes, with the
  gold, maroon and skin tones missing. The manifest had pinned that.

- The memory card, written. A blank card makes the mount answer BROKEN,
  which is the one card status that opens the title screen's "Proceed with
  formatting?" prompt, and confirming it runs the only call to
  CARDFormatAsync in the whole executable: five sector erases, 960 page
  programs, 40,960 bytes, and 325 completion interrupts. The image the
  game left behind verifies as one its own mount would accept and carries
  the game's serial, not ours. Two earlier attempts failed for reasons
  worth keeping: the title screen spends the first START snapping its logo
  flyover, which is what puts the title on screen in the first place, and
  the value that kept routing the run away was not a menu choice but the
  attract-mode timeout, 92 seconds of host wall clock.

## Open

- Saves: the game formats a card, but has not yet saved or loaded one.
  That needs a save point, which needs recorded input to reach.
- The battleship's searchlight beams render dark; every step matches the
  hardware rules as modelled, so a reference capture is needed.
- Beyond the hold: the ship and overworld sections, and the long tail of
  every scene.
