# CLAUDE.md

Skies of Arcadia Legends (GameCube `GEAE8P`) on native Windows: the executable statically
recompiled to C in `gen/` (never committed), a hand-written console in `runtime/`, and
hand-decompiled C in `src/` matched byte for byte against the original. Plan of record
[docs/PLAN.md](docs/PLAN.md); how to check anything [docs/TESTING.md](docs/TESTING.md);
how it fits together [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Every rule here was
broken here first, with its reason attached, because one without its reason is argued away.

**No game data enters this repository, ever.** `tools/guard.py` refuses 41 extensions,
16 directory names and anything in a mod folder that is not text, and CI rescans all
history: a later commit cannot undo a leak.

## Before you push

In this order, cheapest first — about a minute in total:

```
python tools/guard.py
python tools/guard.py --history
python -m ruff check tools
python -m ruff format --check tools
python -m pytest
```

**The formatter check is a separate command from the lint check.** `ruff check` passing
feels like it covered formatting and does not: five broken CI windows, 28 red commits, 23
of them the formatter alone. `python -m ruff format tools` is the idempotent fix, and CI
pins `ruff==0.16.7`.

Then, only if you touched the matching thing:

| You touched | Also run | Why |
|---|---|---|
| `runtime/` | `python tools/citest/compile_runtime.py`, then `--link` and `$env:SOA_SELFTEST='1'; gen\soa.exe extracted` | CI compiles every runtime file and has caught breakage the author did not |
| `runtime/gx*.c`, or anything a draw passes through | `python tools/scenario.py replay` (18 s) | the only check that will tell you a pixel moved |
| `src/`, `include/`, `config/GEAE8P/units.txt` | `python tools/decomp.py` (4 s) | 83 functions across 21 units still match byte for byte |
| `config/hle.txt` | `--compile --optimize --link`, then the self test | see below; selftest case 73 is what checks the swap |
| `config/scenarios/`, `tools/scenario.py`, `runtime/si.c` | `python tools/scenario.py run title --check` (71 s) | the pad grammar lives in two places |

The guard is not a hook — `.git/hooks/` holds only samples, so CI is its only enforcer.

## Relink, or retranslate

`--link` never rebuilds translated code: it globs the `chunk_*.obj` that already exist
(`tools/recompile.py:203`), and nothing tracks dependencies or warns about staleness.

**`--link` alone is enough** after editing `runtime/*.c`, a runtime-only header
(`runtime/gxr.h`), `src/**`, `include/`, or `config/GEAE8P/units.txt`.

**A full `python tools/recompile.py --compile --link` is required** after editing:

- `runtime/cpu.h` — `gen/functions.h` includes it and every `gen/chunk_*.c` includes
  that. It is a struct plus ~25 `static inline` accessors, so stale chunks keep the
  old layout, the link succeeds with no diagnostic at all, and the binary is wrong.
- `config/trace.txt` — tracepoints are emitted inline into the translated C (68
  today), so new ones never fire and `SOA_TRACE=1` looks like it worked. The file
  most often edited during a chase, and no build instruction elsewhere names it.
- `config/hle.txt` — which of the 25 bound functions the runtime answers natively (12
  decompiled). Adding a line and relinking gives LNK2005; *removing* one silently leaves
  the native version in charge. `hooks.txt` and `savepoints.txt` bake in the same way.

`--compile` builds translated code at `/Od` unless given `--optimize`, while `--link`
always builds `runtime/` and `src/` at `/O2`: the exe's optimisation level comes from the
last `--compile`, not from the `--link` that produced it.

## Directories you cannot get back

Both are gitignored game data and exist on exactly one machine.

- `build/fifo/` — 23 captures (`.fifo`/`.regs`/`.ram`) pinned by `config/fifo_manifest.tsv`.
  **Set `SOA_FIFO_DIR` to anything but the default `build/fifo` whenever you set
  `SOA_FIFO_DUMP`** (`runtime/gx.c:121`): the test suite once captured into it and
  overwrote three, gone for good. `--replay` also overwrites `<base>.png`.
- `build/cards/` — card images, including the one the game formatted itself; default
  `build/cards/slotA.raw` (`runtime/exi.c:90`), override with `SOA_CARD` — but not for
  `cardwrite.scn`, where a damaged image takes the repair arm and measures something else.

**Run one `soa.exe` at a time.** Two share `build/frames/`, `build/cards/slotA.raw` and
the log path; three scenarios died part-way, silently, exit `-1`, with a second live.

## What you must not conclude

- **Re-render or re-measure before trusting any written description of a defect.**
  The searchlight-beam entry was rewritten three times, each describing a build that no
  longer existed: wrong object counted, wrong cause named, a "needs a hardware capture"
  gate on a question the vertex data answered. `docs/FINDINGS.md:627` — *re-look at the
  frame before trusting a written description of it.*
- **A count from one scenario is evidence about that scenario, not about the game.**
  One run's opcode census produced a fabricated P1 defect, a retired claim that the
  voice bank never loaded, and an opcode implemented for code no run can reach — four
  commits in a day. Every round that was right came from the driver or the disassembly;
  every round that was wrong came from a report.
- **A run completing proves nothing when the fault is layout-sensitive.** The
  frame-8100 access violation vanished when guest memory was allocated differently,
  without being fixed. Only bisection showed it reproduced with the renderer exactly as
  committed; the cause was two use-after-frees, found by building the renderer
  standalone and watching them execute.
- **A check that agrees with everything is worse than no check, and output nobody has
  looked at must never be blessed.** `matchcheck.py` compared relocated words on their
  six-bit opcode alone and called 41 functions matching for two days; `replay --bless`
  pinned washed-out colour on 8 of 23 frames for a day, so the correct fix would have
  failed the suite. Mutate a real input to prove a new oracle can fail; open the PNG
  before re-blessing, because a hash moving is a question, not a verdict.
- **The first bless is the dangerous one.** The rule above is easy to follow when a hash
  moves, and the day that was lost had no hash to move: the manifest was *created* from a
  render nobody had inspected, so there was nothing to disagree with and every later check
  faithfully defended the wrong colours. When you establish a baseline of any kind --
  frame hashes, expected samples, a golden log -- look at what you are about to pin, and
  say in the commit how you checked it. A baseline is a claim that this output is correct,
  and it is the one claim nothing downstream can ever test.

## Silent traps

- **PowerShell:** `$env:SOA_RENDER = '1'`, never `set SOA_RENDER=1`, which creates a
  variable *named* `SOA_RENDER=1` and leaves the environment untouched. Nothing stops the
  resulting run — the watchdog fires only when no frame is presented, and frames are
  counted whether or not anything is drawn. Quote values too: an unquoted `#` starts a
  comment and pad scripts contain one (`SOA_PAD='9000:sup#120'`).
- **Game code goes in `src/`, headers in `include/`** — both compilers hardcode those
  paths, and `.gitignore` has a bare `game/` matching at any depth, so a unit written
  to `src/game/` is untracked, `git add` says nothing, and a session's decompilation
  was invisible for a commit that way.
- **Binding lists want lowercase `0x` and exactly eight hex digits** (`tools/soa/hle.py:20`):
  `0X80005520`, `0x8000552` and `80005520` were each dropped with no error and no count
  until 2026-09-22; now any line that is not an entry, and a repeated address, stops the
  build with the file and line. The rule is the same; only the silence is gone.
- **`units.txt` is tab-separated and `native` is lowercase.** Spaces used to raise an
  unhandled `ValueError` and `Native` was silently ignored, so the unit matched under
  `decomp.py` while never entering the port. Since 2026-09-22 both readers share
  `decomp.read_units`, which refuses either with the file and line -- but
  `fetch_toolchain.py` and `test_decomp_native.py` still parse the file themselves.
- **Counts in prose rot, and it is always the top-of-file status table.** `docs/PLAN.md`'s
  said 41 matching functions, 9 swapped in and 362 tests for three days, against a tree
  holding 83, 12 and 475 — and its C3 entry still said "all 20 captures" when the corpus
  had been 23 since `hold.scn`. Both are fixed. A single test module landing on
  2026-09-21 then moved the test count in six files at once, which is the real shape of
  this problem: one number lives in `docs/PLAN.md`, `docs/TESTING.md` (four places),
  `HANDOFF.md`, `README.md`, `docs/ARCHITECTURE.md` and `.claude/skills/check/SKILL.md`
  (the last copy found, 2026-09-22, still said 455).
  Measure before quoting a number; when you change one, fix every copy in the same change.
  `grep -rn "<the old number>" --include="*.md" .` is how you find them all.
