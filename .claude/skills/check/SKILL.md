---
name: check
description: The full pre-push verification for this port, cheapest first, with what each step catches, what to do when it fails, and the rule for when frame hashes move. Use before any commit or push, and before claiming a change works.
---

# I am about to push — check everything

Run every command from the repository root. Stop at the first failure: the
order below is cheapest first precisely so that the failure you read is the
one you can afford to read.

Every transcript on this page was produced by running the command while
writing it, on Windows 11, 16 logical CPUs, Python 3.14, ruff 0.16.7, VS 2022
Build Tools, with an extracted disc in `extracted/` and the capture corpus in
`build/fifo/`. One block says where it came from instead, and says so.

## The order, and what each step needs

| # | Step | Here | Needs |
|---|---|---|---|
| 1 | `python tools/guard.py` | 0.19 s | nothing |
| 2 | `python -m ruff check tools` | 0.09 s | nothing |
| 3 | `python -m ruff format --check tools` | 0.09 s | nothing |
| 4 | `python tools/checkdump.py` | 0.10 s | disc |
| 5 | `python tools/citest/compile_runtime.py` | 2.8 s | MSVC |
| 5b | `python tools/citest/dc_check.py` | 2.5 s | MSVC |
| 5c | `python tools/citest/render_check.py` | 3.1 s | MSVC |
| 6 | `python tools/decomp.py` | 3.6 s | disc, `vendor/mwcc/` |
| 7 | `python -m pytest tools/tests -q` | 48.6 s | nothing (69 tests want MSVC) |
| 8 | `python tools/recompile.py --link` | not run here | disc, MSVC |
| 9 | `$env:SOA_SELFTEST='1'; gen\soa.exe extracted` | 0.11 s | disc, built exe |
| 10 | `python tools/scenario.py run title --check --quiet` | 70.9 s | disc, built exe |
| 11 | `python tools/scenario.py replay` | 16.6 s | disc, exe, corpus |

**Steps 1–3 and 7 are the whole of what CI can run.** Steps 4–6 and 8–11 need
your disc, your vendored compilers or captures that are game data, and nobody
else can run them for you. A green CI tick means the C compiles, nine MSL
routines behave like libc and the rasterizer still fills a triangle. It says
nothing about the game running.

**Steps to run in the background** (`run_in_background: true`): step 7, step 8
when it is a full `--compile --optimize` (103 s), and step 10 or any other
scenario. Steps 9, 10 and 11 all launch `gen/soa.exe`, so **never background
two of them at once**: two runs share `build/frames/`, `build/cards/slotA.raw`
and the default log path, and three scenarios have already died part-way
through, silently, exit `-1`, because a second run was live.

**Steps you can skip, and only these:** 6 unless you touched `src/`,
`include/` or `config/GEAE8P/units.txt`; 10 unless you touched
`config/scenarios/`, `tools/scenario.py`, `runtime/si.c` or anything in the
game's own control flow; 11 unless you touched anything a draw passes through.
Steps 1, 2, 3 and 7 are never skippable — they are what CI will run anyway,
and it is cheaper to fail here.

This is a PowerShell repository. `set NAME=value` is cmd.exe syntax; in
PowerShell it creates a *shell* variable whose name contains the equals sign,
leaves the environment alone, and gives you a headless run that nothing stops.
Use `$env:NAME = 'value'`, and quote the value, because PowerShell reads an
unquoted `#` as a comment and several pad scripts contain one.

---

## 1. The game-data guard

```
python tools/guard.py
```
```
guard: 161 tracked files, no game data
```

Catches game data about to enter the repository: 43 forbidden extensions
wherever they sit in a name (`.rvz`, `.iso`, `.dol`, `.tpl`, `.dsp`, `.bin`, `.map`,
`.gci`, …, and `slotA.raw.bak`), eighteen directory
names that must never be tracked (`extracted/`, `gen/`, `build/`, `vendor/`,
`scratch/`, `packs/`, `photos/`, …), any tracked file over 2 MiB, a binary file that
begins as game data whatever it is named (a card image by the save in its
directory), and in a mod folder any file that is not text. It lists `git ls-files`, so it
sees what would be committed, not what is lying around.

**On failure:** do not "fix" it by renaming the file. Move it out of the tree.
CI also scans every blob in the whole history (names, directories and
content, through `python tools/guard.py --history`), so a file committed and
deleted again still fails, renamed or not, and rewriting history is the only
cure — much more expensive than not committing it.

**The trap on the other side of this rule:** `.gitignore` line 15 is a bare
`game/`, which matches at any depth, and the guard treats it as a game-data
folder. Hand-written code that lands in `src/game/` is silently invisible to
`git add` — this has already eaten a session's decompilation output. If work
you did seems not to be staged, check it is not under an ignored path.

## 2. The lint check

```
python -m ruff check tools
```
```
All checks passed!
```

Rules `E,F,W,I,UP,B,SIM`, with `E501` ignored. `I001` (import order) is the one
that bites: it is sensitive to what looks like a first-party package, so adding
a directory named after an existing package can break it in files you never
touched. `pyproject.toml` pins `src = ["tools", "tools/tests"]` for exactly
that reason.

**On failure:** `python -m ruff check tools --fix` for the mechanical ones, then
read what is left. CI pins `ruff==0.16.7`; check `python -m ruff --version`
agrees before you conclude the code is wrong.

## 3. The formatter check — a separate step, and the one people drop

```
python -m ruff format --check tools
```
```
70 files already formatted
```

**This is not covered by step 2.** `ruff check` passing feels like it covered
formatting; it does not. Running the lint check and not this one is the single
most expensive habit in this repository's history: five windows of red CI, 28
commits pushed red between them, and 23 of those 28 were the formatter alone —
20 in a single window. `CONTRIBUTING.md` still does not name this command; CI
has run it since the first CI commit.

**On failure** the tool prints the diff it would apply and exits 1. The fix is
its own diff:

```
python -m ruff format tools
```
```
68 files left unchanged
```

## 4. The dump is the build `config/` describes

```
python tools/checkdump.py
```
```
extracted\sys\main.dol: sha1 8c0e278126fa3b0173400fdb632038172743cc13 (GEAE8P rev 0)
  matches config\GEAE8P\config.yml; this is the build config/ describes.
```

Cheap, and nothing downstream checks it again. A wrong build extracts,
translates, links, boots, and is then wrong in ways no other check here can
see — every address in `config/` would be pointing at different code. It reads
the sha1 out of the decomp toolkit's own config rather than restating it, so it
cannot drift, and it refuses by name when it cannot parse rather than passing
silently.

**On failure:** stop. Re-extract from a dump of the build `config/` names; do
not edit the config to match your dump.

## 5. The compile-only runtime check

```
python tools/citest/compile_runtime.py
```
```
...
ok   window.c

compiled 26/26 runtime translation units
not compiled here: nothing, every runtime/*.c is covered
```

Every `runtime/*.c` compiled on its own with `/c` and nine warnings promoted to
errors. Nothing links, so C4013 — implicit declaration — is first among them:
it is the only sign that a rename left a caller behind. This catches, in three
seconds and with no disc, what would otherwise surface as a link failure in
step 8 after a minute of building, or not at all.

Two more in the same family, same cost, also no disc:

```
python tools/citest/dc_check.py
```
```
...
ok   memset      3000 cases

all 9 routines agree with the host C library
```

```
python tools/citest/render_check.py
```
```
[gxr] rasterizing on 1 worker thread
[selftest] render full-screen quad      ok    got "307200 of 307200 red"
[selftest] render triangle rows         ok    got "complete, 53301 px"
[render] second frame hash 63a57c77609efd77 (not asserted)
[render] both render checks pass
```

`dc_check.py` is there because matching bytes says nothing about behaviour on
x86: the string comparison in this tree that returned positive where the answer
was negative byte-matched perfectly the whole time. `render_check.py` is the
only check in this group that
looks at a pixel; everything above it would pass for a renderer that drew
nothing. Its frame hash is printed and deliberately **not** asserted.

**On failure:** these three fail loudly rather than skipping when `cl.exe` is
missing, so a failure is real. Read the first `FAIL` line; the later ones are
usually the same rename.

## 6. The decompilation check

```
python tools/decomp.py
```
```
...
pool_order_seed          static helper, inlined (no executable counterpart)
fn_802394C4              MATCH  88/93 words, 5 need a link  (object 372 bytes, executable 372)
@5                       MATCH  4/4 bytes  (data at 0x8034C7E8 via fn_802394C4)
@13                      MATCH  4/4 bytes  (data at 0x8034C7EC via fn_802394C4)
@14                      MATCH  4/4 bytes  (data at 0x8034C7F0 via fn_802394C4)
1 local symbol(s) not compared
5 word(s) only a link can decide, across 1 otherwise-matching symbol(s)
7 unit(s) fully verified; 14 with words only a link can decide
```

Builds every unit in `config/GEAE8P/units.txt` with the Metrowerks compiler it
names and compares every function **and every data object** against the
executable's bytes. Today: 21 units, 83 functions, 17 data objects, nothing
differs, exit 0. One object on its own:

```
python tools/matchcheck.py build/src/strcpy.o
```
```
strcpy                   MATCH  46/46 words  (object 184 bytes, executable 184)
```

**"needs a link"** is neither a match nor a failure: the bits outside a
relocated field are identical but nothing here knows the target's address.
`--strict` turns those into failures.

**Exit codes matter here.** `decomp.py` returns 2 when a compiler named in
`units.txt` is missing, and names every unit that wanted it — the run was
incomplete, not clean. `matchcheck.py` on one object: 0 verified, 1 differs,
3 nothing differs but something was left undecided. Do not read a non-zero exit
as "a function regressed" without reading which.

**A match is not a behaviour test.** It proves you understand what the compiler
did. Whether the routine is called correctly is step 5b; whether the native
twin behaves the same is case 73 of step 9.

## 7. The Python tests

```
python -m pytest tools/tests -q
```
```
996 passed in 179.15s
```

996 tests in 53 files, none of which reads the disc. The count you see depends
on what is installed, and the tool tells you: `977 passed, 1 skipped` without
capstone (what CI installs — the 19 cross-validation tests collapse into one
module-level skip), `688 passed, 308 skipped` without MSVC.

**Watch the skip count, not just the pass count.** A number that went *up*
while the pass count went down means a test stopped being able to run rather
than starting to pass. The 69 MSVC-gated tests build one `runtime/*.c` and run
it; on a machine without a compiler the Python is checked and the C is not.

**On failure:** run the one file — `python -m pytest tools/tests/test_x.py -q`
— and read the assertion before changing either side. A test in this tree has
been wrong rather than the code at least once, but assume the code until you
can say what the test's model of the world got wrong.

## 8. The build

```
python tools/recompile.py --compile --link
```

This transcript is quoted from `docs/TESTING.md` §2 rather than from a run
here — it is the one block on this page that was not produced while writing it.
Its shape comes from `tools/recompile.py` and its counts are checkable without
building: `config/hle.txt`, `hooks.txt` and `savepoints.txt` hold 19, 1 and 1
entries, which I did check.

```
7,144 functions, <n> switch tables (<t>s)
20 functions bound to HLE, 1 runtime hooks, 1 savepoints
emitted 7,144 functions into 18 files, 55.7 MB of C (<t>s)

instruction coverage: 100.000%  (696,171 translated, 0 not)

compiling 19 translation units with MSVC (/Od) ...
compiled 19/19 units in <t>s
linked gen\soa.exe (<t>s)
```

Three lines are worth reading every time: `instruction coverage: 100.000%` with
`0 not` (anything less prints a table of dropped mnemonics, and the port runs
past those instructions doing nothing), `compiled 19/19 units`, and
`linked gen\soa.exe`. Without the last there is no binary and steps 9, 10 and
11 are checking yesterday's.

### `--link` alone, or a full `--compile`?

`--link` never rebuilds the translated code. It globs the `chunk_*.obj` that
already exist and recompiles `runtime/*.c` and the native `src/` twins. There
is **no dependency tracking and no staleness warning anywhere in this
project**, so getting this wrong is silent.

| You changed | Enough | Why |
|---|---|---|
| `runtime/*.c`, `runtime/gxr.h` | `--link` | compiled at link time |
| `src/**`, `include/`, `units.txt` | `--link` | the native twins are built by the link step |
| `config/functions.tsv` | nothing | names are a comment, and the profile reads the file at run time |
| **`runtime/cpu.h`** | **`--compile --link`** | `gen/functions.h` includes it and every `chunk_*.c` includes that |
| **`config/trace.txt`** | **`--compile --link`** | `trace_hit(...)` calls are emitted inline |
| **`config/hle.txt`** | **`--compile --link`** | the emitter renames bound bodies to `recomp_fn_*` |
| **`config/hooks.txt`, `config/savepoints.txt`** | **`--compile --link`** | emitted into the call site |

`cpu.h` is the worst of these because `struct CpuState` and ~25 accessors are
`static inline`: 18 stale objects keep the old layout, the fresh `runtime/*.obj`
use the new one, the link succeeds, and the binary is wrong. `trace.txt` is the
most often edited during a chase and the easiest to get wrong — new tracepoints
simply never fire, and `SOA_TRACE=1` reports the old set and looks like it
worked. Checking the two agree is one command:

```
python -c "import pathlib,re; print(len(re.findall(r'trace_hit', ''.join(p.read_text() for p in pathlib.Path('gen').glob('chunk_*.c')))))"
```

which prints 68 here against 68 address lines in `config/trace.txt`.

One more flag trap: `--compile` builds the translated code at `/Od` unless you
pass `--optimize`, while `--link` always uses `/O2` for `runtime/` and the
`src/` twins. The optimisation level of the shipped `gen/soa.exe` is decided by
the last `--compile`, not by the `--link` that produced the binary.

## 9. The built-in self test

```
$env:SOA_SELFTEST='1'
gen\soa.exe extracted
```
```
...
[gxr] rasterizing on 1 worker thread
[selftest] render full-screen quad      ok    got "307200 of 307200 red"
[selftest] render triangle rows         ok    got "complete, 53301 px"
[selftest] decompiled vs recompiled     ok    got "12 functions agree over 200 rounds"
[selftest] VIGetRetraceCount native vs twin ok    got "the count at 0x80347A64 over 200 rounds and four call sites"
[selftest] a mod's call into the game   ok    got "strlen 16, every register as it was"
[selftest] 0 failure(s)
```

**0.16 s, 91 lines, 80 cases** — the cheapest real check in the project and the
one to run after every `--link`. It calls the recompiled library, the device
models, the AX mixer and the software renderer directly, outside the game's
control flow, so a wrong answer is a bug with a two-line repro. Every case
prints what it got; a failure exits **7**.

It needs the disc, because `main.c` loads the DOL before it runs anything.
Without one you get the boot message and exit 1, not a self-test result — read
the last line, not the exit status alone.

Case 73 is the one that checks a hand-decompiled function swapped into the
running port against its recompiled twin on random inputs. If you touched
`config/hle.txt`, this is what makes the rebuild worth it.

There is one check on the binary that needs no disc at all, worth a second
after any change to memory or the exception handler:

```
$env:SOA_MEMPOKE='0x81800000'
gen\soa.exe nodisc
```
```
[mem] a store from block 00000000 reached 81800000, past the console's 24 MB of RAM; the port keeps zeroed scratch up there so that it does not reach the host heap. An address up there means the port is not modelling something. Reported once.
  backtrace from r1:
[mem] SOA_MEMPOKE: 81800000 <- DEADBEEF, reads back DEADBEEF
cannot open nodisc/sys/main.dol
```

That is the MEM1 out-of-range tripwire firing on purpose. The `cannot open`
lines and exit 1 are expected: `nodisc` is not a disc. (In PowerShell, do not
pipe the port's output through `2>&1` — it wraps every stderr line in a
NativeCommandError and reports failure even on exit 0.)

## 10. At least one scenario

```
python tools/scenario.py run title --check --quiet
```
```
[scenario] title: Boot through the logos to the title screen, press START, then New Game.
[scenario] gen/soa.exe extracted  (SOA_PAD=1600:start,1640:a, SOA_FRAMES=2000, SOA_RENDER=1, SOA_SNAP=50, SOA_STRICT=1)
[scenario] 2000 frames, 2 pad events; log: build/scenario-title.log
[check] the run exits 0                     pass  exit 0, 2000 frames
[check] no MMIO outside the modelled range  pass  no [mmio!] lines
[check] no unknown FIFO bytes               pass  0 unknown bytes of 354742716
[check] no bad vertex references            pass  0 bad vertex refs over 7876470 vertices, 112310 triangles
[check] the pad script was understood       pass  2 events
title: 4 of 4 invariants hold
```

**70.9 s.** `title` is the one to run: it is the cheapest scenario that boots
the game, renders, and drives the pad. `python tools/scenario.py list` shows
all thirteen; `opening` at ~4 minutes reaches the boarding and is the next one
up if you changed the game's own control flow. `monkey` is 26 minutes — start
it in the background or not at all.

The four invariants are built so that **every one of them fails rather than
passes when its input is absent**, and the two counters fail at zero, since a
run that pushed nothing to the GP has checked nothing. That is the property to
preserve if you ever add one.

**What this does not check:** a pixel, a sample, or any counter's value. A
renderer that painted every frame black passes all four. `--check` counts only
positives, so a stray `[gxr]` or `[mem]` tripwire line sits in the log without
failing anything — read `build/scenario-<name>.log` when the renderer changed.

Free, and worth doing on any run you drove by hand:

```
python tools/scenario.py check build/scenario-title.log --name title
```
```
[check] the run exits 0                     pass  reached its frame limit at 2000 frames, which exits 0
...
scenario-title.log: 4 of 4 invariants hold
```

**The invariants are not the point of every scenario.** `cardwrite` is judged
by one number in the `[exi]` line that `--check` does not read, and it needs
`build/cards/blank.raw` deleted first — a blank card is the *absence* of the
file, so a second run finds a valid card, never draws the format prompt, writes
nothing, and reports all the ticks it can. Run `python tools/scenario.py show
<name>` and read its `shows:` and `note:` lines before trusting a green line.

## 11. The frame-hash sweep

```
python tools/scenario.py replay
```
```
[replay] 23 captures x 4 thread counts x 2 passes = 184 replays, each loading a 24 MB memory image
[replay] pass 1, SOA_THREADS=1
...
  ok    0100: ced8f6518129ba7a
  ok    0300: 060aa3991d5675e2
...
  ok    8000: f672349f32fb0053
[replay] 23 captures match config/fifo_manifest.tsv at SOA_THREADS 1,2,3,8
```

**16.6 s, and it is the only check in this project that compares what the game
actually drew with what it drew before.** Each capture is a frame's command
stream, its register shadows and a 24 MB image of MEM1; `gen/soa.exe --replay`
renders one with no game running at all.

What the 184 replays prove: the same bytes in give the same pixels out; the
answer does not depend on how many threads rasterize it (that is the whole
reason for sweeping 1, 2, 3 and 8 — a hash that moves with the thread count is
a race in the rasterizer, not a rendering); and a change to the renderer is
visible and attributable. What they do not prove: that the frames are *right*.
They are pinned to what this port rendered, not to a console.

---

# When the frame hashes move

**A changed frame is a failed change until you can name which capture moved and
say why the old pixel was wrong.** Not "the new one looks fine". Not "the sweep
still agrees with itself". Which capture, and what was wrong with the pixel it
used to draw.

Re-blessing is a deliberate act performed *after* looking at the frame. It is
never a way to make a check go green, and `--bless` cannot tell the difference:
it refuses a sweep that disagreed with itself, and that is all it refuses.
Nothing in the tool stops you blessing a frame nobody has looked at.

**This project has already done it.** On 2026-09-16 the manifest was blessed
from output rendered by a renderer with a texture use-after-free. On
2026-09-17 the fix moved 8 of the 23 frames, and the commit that found it says
what the blessed frames had been:

> The fix changes 8 of the 23 pinned captures, so both were rendered and
> compared with their references: the old frames are washed green and blue
> across whole scenes, missing the gold, maroon and skin tones; the new ones
> are right. The manifest had been blessed from the broken output and was
> holding it in place.

A day with the bug pinned, and worse than inaction, because the manifest
asserted the wrong colours were correct — a *correct* fix would have failed the
suite.

## Read the failure before you do anything

The sweep reports four different things and they mean four different things.

**`DIFFS` — the pixels changed.** The line is
`  DIFFS <name>: <new hash>, manifest <old hash>` (`compare_manifest`,
`tools/scenario.py`), followed by
`[replay] FAILED -- N capture(s) differ, 0 run(s) went wrong`. Same capture,
same input bytes, different picture. This is the one that needs the procedure
below.

**`input` — you are not comparing what you think.** Real output, from a sweep I
pointed at a copy of capture `0100` with one byte of its `.ram` changed:

```
  input 0100: this capture hashes 78eb83328c8be80b, the manifest was blessed from a6b3bbd56bb3d101 -- a different capture, so the frame hash means nothing
```

The frame hash is not evidence of anything here, and the tool says so rather
than claiming a rendering regression. That column is the reason the corpus
being destroyed by the test suite in 2026-09-17 was diagnosed in minutes
instead of chased as a renderer bug. **If you see this, you overwrote a
capture, and it is gone** — `build/fifo/` is game data, gitignored, and exists
on exactly one machine.

**`gone` / `new` — the corpus changed shape.** `gone <name>: in the manifest,
not in build/fifo` and `new <name>: <hash> (not in the manifest; --bless adds
it)`. Both fail the sweep rather than being quietly ignored.

**`[replay] ... hash X, but <name> at SOA_THREADS=n (pass p) gave Y`** — the
sweep disagreed with *itself*. That is non-determinism in the renderer: a race
between the rasterizer workers, or a read of uninitialised memory. It is a
worse bug than a moved pixel, and `--bless` refuses outright:
`[replay] not blessing a sweep that did not agree with itself`.

## ### Establishing a baseline for the first time

Everything below assumes a baseline exists and a hash moved. The first time you create
one there is nothing to compare against, and that is when this project lost a day: the
frame manifest was blessed from a render nobody had opened, so eight of twenty-three
frames pinned washed-out colour and a correct fix would have failed the suite.

So before creating any baseline -- a frame manifest, an expected-sample table, a golden
log -- look at what you are pinning. Open the frames. Derive the expected values from the
format's own definition rather than from what the code currently emits. Then say in the
commit message how you checked, so the next reader knows whether the baseline was
inspected or merely captured.

What to do when you get `DIFFS`

1. **Write down which captures moved.** Not "some frames". The names. If your
   change was to one code path and eight unrelated captures moved, that is
   information.

2. **Render the frame and look at it.** `--replay` writes the PNG next to the
   capture:

   ```
   $env:SOA_HASH='1'
   $env:SOA_THREADS='1'
   gen\soa.exe --replay build/fifo/0100
   ```
   ```
   [boot] DOL 3166656 bytes, FST 134426 bytes at 816DF2E0; entering fn_80003140
   [gxr] rasterizing on 1 worker thread
   [gxr] wrote build/fifo/0100.png (640x480)
   [gxr] frame 0 640x480 hash ced8f6518129ba7a
   [gx] replayed 1637 of 1637 bytes
   [gx] 0 pipe bytes, 227 commands: 94 BP, 38 XF, 26 CP loads, 0 display lists, 4 draws (16 vertices); 0 draw-dones, 2 tokens, 1 EFB copies, 0 unknown bytes
   ...
   [gxr] 8 triangles, 0 lines, 0 points; 678361 pixels shaded (0 outside, 0 failed alpha, 0 failed depth); 0 clipped away; 0 bad vertex refs; 0 texture copies, 1 screen copies
   ```

   That hash is the manifest's row for `0100`, so this replay left the corpus
   exactly as it found it.

   Open both PNGs with the Read tool, which renders images: the new one at
   `build/fifo/<name>.png`, and the frame as it was at
   `build/fifo/ref-before/<name>.png` — the first sweep ever run copied 27 of
   them there before overwriting any, and it never copies again. **This is the
   step that was skipped in 2026-09-16.** It costs one tool call.

3. **Say why the old pixel was wrong.** In words, about that frame: a colour
   that should have been gold and was green, a polygon that should have been
   occluded, an edge that should not have been aliased. If you cannot, you do
   not yet know whether you fixed something or broke something, and the answer
   is not to bless. The renderer forensics switches exist for this — `--replay`
   honours `SOA_GXR_DEBUG=N`, `SOA_GXR_DRAWS=N`, `SOA_GXR_PIXEL=x,y`,
   `SOA_GXR_LIGHTS=N`, `SOA_GXR_NOTEX=1`, `SOA_CULLFLIP=1`. They are how a
   written description of a visual defect has been corrected three times in
   this project by looking at the frame again.

   For what a moved hash looks like when you cause one on purpose, here is the
   same capture with every texture forced flat grey:

   ```
   $env:SOA_GXR_NOTEX='1'
   gen\soa.exe --replay <a scratch copy of the capture>
   ```
   ```
   [gxr] frame 0 640x480 hash 6d21111751854cf7
   ```

   `ced8f65…` against `6d21111…`, one frame, one changed render. (The sweep
   itself strips every `SOA_*` from the child's environment, so switches you
   set in your shell do not reach `scenario.py replay` — set them only on a
   hand replay.)

4. **Only then bless**, and say in the commit message which captures moved and
   why:

   ```
   python tools/scenario.py replay --bless
   ```

   It rewrites all 23 rows of `config/fifo_manifest.tsv` from this sweep. There
   is no partial bless. If some of the moved frames are right and some are not,
   fix the renderer first.

5. **If you cannot explain it, the change is failed.** Revert it, or hold it,
   and say so. "The sweep is green again" is not a result; it is the absence of
   one.

## Never point a capturing run at the corpus

`SOA_FIFO_DUMP` writes into `SOA_FIFO_DIR`, which **defaults to `build/fifo`** —
the corpus. Set it somewhere else, always:

```
$env:SOA_FIFO_DIR='build/fifo-new'
```

The two capturing scenarios (`capture`, `hold`) already do. Adding a capture to
the corpus is a deliberate three-step: capture into `build/fifo-new`, sweep it
on its own with `python tools/scenario.py replay --fifo build/fifo-new` to see
that it renders the same way at every thread count, then move the three files
into `build/fifo` and `--bless`.

`SOA_HASH=1` is for replays and nothing else: in a live run it forces a
`gxr_flush()` on every presented frame, which spoils any frame-rate
measurement, and `SOA_SNAP` skips rasterizing the frames it is not writing, so
most of the hashes would be of a frame nothing drew.

---

# What none of this covers

- **That the frames are correct.** Everything here is pinned to what this port
  rendered, not to a console. The corpus contains no line and no point draw, so
  the row-ownership rule in `raster_line` and `raster_point` is unpinned
  entirely.
- **Audio.** No step above listens to anything. `tools/audio_check.py` cross-
  correlates a `SOA_WAV` recording against the disc's own stream, and needs
  numpy, which `pyproject.toml` does not list.
- **A layout-sensitive fault.** From the commit that fixed one: *"changing how
  guest memory is allocated makes it vanish without fixing anything, so a run
  that completes proves nothing."* If the bug you are chasing is a stray
  pointer, a clean run of steps 9–11 is not evidence. Build the component
  standalone and watch it execute.
- **That a check can fail at all.** Four oracles in this project have agreed
  with everything put in front of them — a relocation comparison that inspected
  930 of 4,960 bits, a symbol lookup that reported "not in the inventory"
  instead of failing, a profiler that printed nothing on a healthy run, and an
  argument about compressed files that could not have been sound. Before
  trusting a new check, break the thing it watches on purpose and see it fail.
  A check that agrees with everything is worse than no check.

# Before you write the commit

- The counts in `README.md`, `docs/PLAN.md`, `docs/TESTING.md` and
  `docs/ARCHITECTURE.md` drift, and it is always the top-of-file status table
  that rots, because the entries below it are updated by whoever does the work
  and the table is not. If your change moved a number those files state — test
  count, scenario count, matching functions, tracked files — fix it in the same
  commit.
- `git add` an ignored path is silent. If you wrote code under a `game/`
  directory anywhere, it is not staged.
- End the commit message with the `Co-Authored-By:` trailer; 88 of the 91
  commits in this history carry one and nothing enforces it.
- If a step above failed and you are pushing anyway, say which, in the commit
  body, and why it is not a reason to stop. A known failure named in the
  history costs an hour; an unnamed one has cost this project a day more than
  once.

`CLAUDE.md` carries the short form of these rules and is loaded for you
automatically; this page is the procedure, with what each command actually
printed. `docs/TESTING.md` is the long form, organised by question rather than
by order.
