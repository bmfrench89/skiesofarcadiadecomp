# Skies of Arcadia Legends — Native PC Port

A native PC port of **Skies of Arcadia Legends** (GameCube, `GEAE8P`) built by
static recompilation, with progressive decompilation layered on top.

> **No game data lives in this repository, ever.** You supply your own dump of a
> disc you own. This repo contains only original tooling, runtime code, and
> analysis metadata.

## Why this game

Disc analysis (see [docs/FINDINGS.md](docs/FINDINGS.md)) turned up an unusually
favorable target:

| Signal | Value | Why it matters |
|---|---|---|
| REL modules | **none** | All code is in one DOL. Static recompilation sees the whole program. |
| Gekko-only instructions | **0.76%** | Dreamcast-lineage code barely touches paired singles or locked cache. |
| Function count | **7,144** | Smaller than *any* GameCube game yet fully decompiled. |
| Symbol map | absent | The one real gap — mitigated by SDK signature lifting (see spec). |

## Documents

- **[docs/SPEC.md](docs/SPEC.md)** — architecture and technical decisions
- **[docs/ROADMAP.md](docs/ROADMAP.md)** — work slices, milestones, current status
- **[docs/PLAN.md](docs/PLAN.md)** — what to pick up next, and how to know when it is done
- **[docs/FINDINGS.md](docs/FINDINGS.md)** — disc analysis evidence base
- **[docs/PROGRESS.md](docs/PROGRESS.md)** — what got built, in order
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — clean machine to running game, and the rules

Licence: **[MIT](LICENSE)** over the original work here — the recompiler, the
runtime, the tooling and the prose. It does not and cannot cover `src/`, which
is written to reproduce the original program's compiled output, or `config/`,
which is analysis metadata derived from the game. [NOTICE](NOTICE) says which
is which and why. No game data is in this repository or its history; you
supply your own dump of a disc you own.

## Status

The game boots, plays its intro, reaches the title screen, starts a new
game and plays through the opening cutscenes, the first battle and into
the first fields (the Valuan ship's hold and the room the story carries it
to next: the stick, the minimap, menus and random encounters), with dialogue text, music and sound, rendered by a
software implementation of the GameCube's graphics pipeline in a window
with keyboard or gamepad input. It mounts a memory card and the game
formats one itself, but no save has been written or loaded yet. See the
roadmap for what is done and what is not.

## Building and running

You need Windows, Python 3.14 (its standard library decodes zstd, which the RVZ
reader needs), the Visual Studio 2022 Build Tools with the C++ workload
(`cl.exe` need not be on `PATH` — the tools find it through `vswhere`), and
your own dump of the disc (`.rvz`, `.iso` or `.gcm`).

**PowerShell** — the default shell of Windows Terminal and of VS Code:

```powershell
pip install -e ".[dev]"
python tools/extract.py "path\to\Skies of Arcadia Legends (USA).rvz" --iso
python tools/checkdump.py
python tools/recompile.py --compile --link
$env:SOA_RENDER = '1'
gen\soa.exe extracted
```

**cmd.exe** — the same commands, except for the line that sets the variable:

```bat
set SOA_RENDER=1
gen\soa.exe extracted
```

> **`set SOA_RENDER=1` is cmd.exe syntax and it does not work in PowerShell.**
> There `set` is an alias for `Set-Variable`, so the line quietly creates a
> *shell* variable whose name is the whole string `SOA_RENDER=1` and leaves the
> environment untouched. No error, no window: the port says `[run] headless;
> watchdog if no frame for 20s` and then goes quiet, playing to nobody, with
> the keyboard and gamepad unreachable because they are read through the window
> that never opened. It does not time out either — the watchdog fires only when
> no frame arrives for twenty seconds, and the frames keep arriving — so the run
> sits there until you Ctrl-C it.
>
> Use `$env:SOA_RENDER = '1'`; `gen\soa.exe --help` prints the same form. Every
> `SOA_*` variable below works the same way: `$env:NAME = 'value'` in
> PowerShell, `set NAME=value` in cmd.exe. To clear one again:
> `Remove-Item Env:SOA_RENDER`, or `set SOA_RENDER=` in cmd.

`extract.py` unpacks the disc into `extracted/` (gitignored, never committed)
and finishes by checking the executable it unpacked against the sha1 in
`config/GEAE8P/config.yml`. `checkdump.py` is that same check on its own, for
an `extracted/` that has been sitting around: it needs nothing but the files
already on disk, and it refuses — naming both hashes — if the dump is not the
build `config/` describes. Nothing downstream looks at the executable's
identity again, so a wrong build translates, links, boots and is then wrong in
ways no other check here can see.

`recompile.py` translates the whole executable to C into `gen/` (also
gitignored), compiles it with MSVC and links the runtime into `gen/soa.exe`.
The default compiles the translated code without optimisation (fast to
build, fine for testing); add `--optimize` for a release build of it, which
takes longer but runs the game faster. After changing anything under
`runtime/`, `--link` on its own is enough.
The function inventory it uses is in `config/` and is the only thing derived
from the game that the repository carries: addresses, sizes and names.

A quick check that a build is sane. It still loads the executable, so
`extracted/` has to be there, but it runs checks instead of the game and opens
no window:

```powershell
$env:SOA_SELFTEST = '1'
gen\soa.exe extracted
```

That runs 73 checks over the translated C library, the device models, the card
and SRAM, the AX mixer and the software renderer — including the 12
hand-decompiled functions the port runs natively, compared against their
recompiled twins on random inputs — and ends in `[selftest] 0 failure(s)`.

### Controls

Keyboard when the window has focus: arrows or WASD move the stick, IJKL the
C-stick; X = A, Z = B, C = X, V = Y, Enter or Space = START, R = Z, Q = L,
E = R, T/F/G/H = D-pad up/left/down/right, Escape quits. An XInput gamepad
works as you would expect (triggers are L/R, the right shoulder is Z). The
keyboard is read only while the window is in front, so switching to another
window releases every key; the gamepad keeps driving the game whatever has the
focus.

To record a session and play it back:

```powershell
$env:SOA_RENDER = '1'
$env:SOA_PAD_RECORD = 'build\play.pad'
gen\soa.exe extracted
```

Play, then close the window. The file is a line per change, small enough to
read and to cut by hand at the point you wanted to reach. Replay it with the
same switches set, adding `$env:SOA_PAD_FILE = 'build\play.pad'` and clearing
`SOA_PAD_RECORD` (`Remove-Item Env:SOA_PAD_RECORD`); the run ends by itself
120 frames — about four seconds of game time — after the last line. Two
caveats worth knowing before a long session: input during a frame that lasts
seconds (a load) reaches neither the game nor the file, and the replay only
keeps step with the recording while frames arrive at the same rate, which is
why the run prints how far it has drifted.

### Useful environment variables

Set these the way your shell sets environment variables: `$env:NAME = 'value'`
in PowerShell, `set NAME=value` in cmd.exe. Quote the value in PowerShell —
`$env:SOA_PAD = '9000:sup#120'` — because an unquoted `#` starts a comment and
an unquoted path with a space in it is two arguments.

| Variable | Effect |
|---|---|
| `SOA_RENDER=1` | render (and open the window) |
| `SOA_SCALE=n` | window scale, default 2 |
| `SOA_WINDOW=0` / `=1` | force the window off (render headless) or on |
| `SOA_FRAMES=n` | run n video frames (numbered 0..n-1), then stop and print the report |
| `SOA_SNAP=n` | write `build/frames/NNNN.png` every n frames; needs `SOA_RENDER=1`. With no window open it also skips rasterizing the frames it is not writing, so the game runs at full speed between them |
| `SOA_PAD=frame:buttons,...` | scripted controller for headless runs, e.g. `1700:start,1800:a`; `+` combines (`1800:a+sup`), `3600:a@150` repeats A every 150 frames, `9000:sup#120` holds the stick up for 120 frames |
| `SOA_PAD_RECORD=path` | write down every controller input the port reads, keyed by frame, one line per change; play in the window, then replay it. An existing file is never overwritten — the run records to `path.1` instead |
| `SOA_PAD_FILE=path` | replay a recording instead of live or scripted input (it becomes the whole input; `SOA_PAD` is then ignored). **Replay in the configuration you recorded in**: the recording is keyed by frame, the game runs on guest time, and the two only keep step while frames arrive at the same rate, so `SOA_SPEED`, `SOA_RENDER`, the window, the thread count and the memory card all have to match. The run says what it was recorded with and how far it has drifted |
| `SOA_PAD_STOP=n` | frames to keep running after a replayed recording runs out, then stop (default 120; 0 keeps going) |
| `SOA_SPEED=n` | run guest time n times faster than the wall clock (headless exploration; sound will not keep up) |
| `SOA_FIFO_DUMP=n,n` | capture those frame numbers; each lands as `NNNN.fifo`/`.regs`/`.ram`, zero-padded to four digits, for `gen\soa.exe --replay build/fifo/NNNN` |
| `SOA_FIFO_DIR=path` | where those captures go (default `build/fifo`, the corpus `config/fifo_manifest.tsv` pins; capture somewhere else) |
| `SOA_THREADS=n` | rasterizer worker threads, default half the CPUs |
| `SOA_NOSOUND=1` | no audio device |
| `SOA_WAV=file.wav` | also write everything the game plays to a WAV file (works headless and with `SOA_NOSOUND`) |
| `SOA_WATCHDOG=s` | stop after s seconds with no video frame and print a report (default 20 headless, off when a window is open; 0 disables) |
| `SOA_POKE=f:a=v[,f:a=v]` | store the 32-bit value `v` at guest address `a` at the end of frame `f`, once, printing what was there before. The one way to answer "what does the game do if this variable says that" without a recompile. Fires on the first frame at or after `f`, so a skipped frame number does not silently lose the poke. Up to 256 items, which is 85 field warps at three words each; a mistyped item stops parsing and says so rather than driving a run that looks like it ignored you. The field's own map identity is `0x80311AC4` (map number), `0x80311AC8` (map letter in the top byte) and `0x80311AEC` (field state, 8 is the steady update). A warp is the destination's script name, e.g. `ME103A.SCT`, as three words at `0x80305CF0`, then 15 in `0x80311AEC`: the game's own warp, seven pokes, no button (`HANDOFF.md` has the command). Numbers are decimal or `0x` hex and must fit 32 bits; a sign, a space or a leading zero is refused rather than read some other way |
| `SOA_MEMPOKE=a,b` | store a word at each guest address before the game boots and read it back; an address past the console's 24 MB, e.g. `0x81800000`, is how to fire the out-of-range tripwire on purpose (needs no disc) |
| `SOA_STRICT=1` | stop at the first hardware access outside the modelled range, with a guest backtrace (almost always a garbage pointer); without it the first twenty are reported and the run goes on |
| `SOA_HASH=1` | print an FNV-1a hash of every frame the port presents (what `tools/scenario.py replay` compares) |
| `SOA_MMIO=1` | log the first few accesses of every hardware register as they happen |
| `SOA_SELFTEST=1` | run the library and device checks instead of the game |
| `SOA_PROFILE=n` | `0` turns off the end-of-run sampling profile (one fewer thread); `n>1` shows n rows |
| `SOA_SYMBOLS=path` | function names for that profile (default `config/functions.tsv`, found by running from the repository root) |
| `SOA_CARD=path` | memory card image for slot A (default `build/cards/slotA.raw`, created blank on the first write; `tools/cardformat.py write` makes one the game will mount) |
| `SOA_CARD_VERBOSE=1` | one `[card]` line per EXI transaction: the frame, the device, the command and the card address |
| `SOA_TRACE=1` / `SOA_TRACE_DUMP=1` / `SOA_WATCH=addr,len` | tracepoints from `config/trace.txt`; 12 words of memory at each hit; a store watchpoint |
| `SOA_GXR_DEBUG=N` / `SOA_GXR_DRAWS=N` / `SOA_GXR_PIXEL=x,y` | renderer forensics in `--replay`: triangles from draw N on, stop after N draws, narrate one pixel |
| `SOA_GXR_LIGHTS=N` / `SOA_GXR_NOTEX=1` / `SOA_CULLFLIP=1` | more renderer forensics: dump the lighting setup of the first N draws, draw every texture flat grey, reverse the winding the rasterizer culls by |
| `SOA_NOAX=1` / `SOA_AX_VERBOSE=1` / `SOA_ARAM_VERBOSE=1` | audio forensics: skip the AX mixer entirely, one line per voice command, one line per ARAM DMA |
| `SOA_PACE=1` | yield to the host scheduler on every interrupt delivery (a loaded machine runs the guest more evenly) |
| `SOA_TSC=0` | time the renderer with `QueryPerformanceCounter` instead of the time-stamp counter |
| `SOA_QUIET_GUEST=1` | drop the game's own printf output |

## Checking it still works

```powershell
python -m pytest                     # 589 tests; any that need a dump skip themselves
python -m ruff check tools           # lint and format both gate CI, and the
python -m ruff format --check tools  #   format one has broken it twice
python tools/checkdump.py            # the dump is still the build config/ describes
python tools/scenario.py list        # the 13 scripted runs this port is judged by
python tools/scenario.py run opening --check
```

A scenario is a `.scn` file in `config/scenarios/`: the environment it sets,
the scripted controller input, what the run should show, and the evidence
behind each claim. `show` prints one, along with the exact commands that run
it. `python tools/scenario.py replay` re-renders every capture in `build/fifo`
and compares each frame hash with the 23 rows of `config/fifo_manifest.tsv`.
Those two need your dump; pytest and ruff do not.

## Repository layout

- `tools/` — disc extraction (`extract.py`, `checkdump.py`), analysis, the recompiler (`tools/soa/`), disassembler, capture decoders, the decompilation pipeline (`decomp.py`, `matchcheck.py`), the scenario library (`scenario.py`), the memory-card formatter (`cardformat.py`), the CI checks (`tools/citest/`), tests
- `runtime/` — the native runtime: CPU helpers, memory and MMIO, device models, threads, the software GX, the window
- `config/` — analysis metadata: the function inventory, HLE bindings, hooks, tracepoints, the scenarios and the frame-hash manifest; `config/GEAE8P/` is the decomp-toolkit project (splits, symbols and the executable's sha1)
- `src/`, `include/` — hand-decompiled units, compiled with the original Metrowerks compiler and checked word for word against the executable (`tools/decomp.py`)
- `docs/` — specification, roadmap, plan, findings, progress log
