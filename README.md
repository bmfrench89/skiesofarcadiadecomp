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

That runs 75 checks over the translated C library, the device models, the card
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

### A settings file, for starting it without a terminal

`gen\soa.ini`, beside the executable, holds the switches a player would set,
one `key = value` a line (`#` starts a comment):

```ini
disc = C:\Games\Skies\extracted   # the extracted disc, used when none is given
render = 1
scale = 3
mods = C:\Games\Skies\mods
```

The keys are `disc`, `render`, `window`, `scale`, `threads`, `mods`, `card`,
`record` (`SOA_PAD_RECORD`), `nosound`, `uncap` and `seed`, each standing for the
switch below. A key that changes what the game does (`seed` today) is also
written into a pad recording's `# config` line when it is set. A variable set in the environment always wins over the file, and
the port says so; a key it does not know is reported with its line and ignored.
The checks -- `scenario.py`'s runs and replays, `perfbench.py` and the self
test -- run with the file off (`SOA_SETTINGS=0`), so a player's settings never
move one.

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
| `SOA_PRESENTER=gdi` | show the window with GDI on an 8 ms poll instead of the DXGI flip-model presenter, which holds each frame for a whole number of the display's refreshes (2 at 60 Hz, 4 at 120; the next refresh at other rates). The report ends with a histogram of present intervals either way |
| `SOA_FRAMES=n` | run n video frames (numbered 0..n-1), then stop and print the report |
| `SOA_SNAP=n` | write `build/frames/NNNN.png` every n frames; needs `SOA_RENDER=1`. With no window open it also skips rasterizing the frames it is not writing, so the game runs at full speed between them |
| `SOA_FRAMES_DIR=path` | where `SOA_SNAP` writes instead of `build/frames`, made if missing. Every run shares `build/frames`, so a job whose snapshots will be judged afterwards (`tools/soak.py check --frames`) needs its own |
| `SOA_PAD=frame:buttons,...` | scripted controller for headless runs, e.g. `1700:start,1800:a`; `+` combines (`1800:a+sup`), `3600:a@150` repeats A every 150 frames, `9000:sup#120` holds the stick up for 120 frames |
| `SOA_PAD_RECORD=path` | write down every controller input the port reads, keyed by frame, one line per change; play in the window, then replay it. An existing file is never overwritten — the run records to `path.1` instead |
| `SOA_PAD_FILE=path` | replay a recording instead of live or scripted input (it becomes the whole input; `SOA_PAD` is then ignored). **Replay in the configuration you recorded in**: the recording is keyed by frame, the game runs on guest time, and the two only keep step while frames arrive at the same rate, so `SOA_SPEED`, `SOA_RENDER`, the window, the thread count and the memory card all have to match. The run says what it was recorded with and how far it has drifted |
| `SOA_PAD_STOP=n` | frames to keep running after a replayed recording runs out, then stop (default 120; 0 keeps going) |
| `SOA_SPEED=n` | run guest time n times faster than the wall clock (headless exploration; sound will not keep up) |
| `SOA_UNCAP=N` | from frame `N` on (`1` is from the start), let the frame end's spin go after one field instead of two: `runtime/tick.c` answers `VIGetRetraceCount` with the frame's start plus one at the spin's call site. The game's logic advances once a frame, so this runs the **whole game** up to twice as fast — it is not 60 fps. Start it after a pad script has reached its scene: disc loads run on the wall clock, so uncapped from boot the script's presses land somewhere else. For measuring how fast the port can go (`docs/PLAN-60FPS-MODS.md` H3), not for play. Every run's report also ends with a `[frametime]` line: frames a second, the median, 95th and 99th percentile and worst wall milliseconds per frame, and the process's CPU seconds; with an uncap, over the frames from `N` on. The `[tick]` line counts the main loop's safe points (one per frame, less the frame shown before the loop starts) and how often the spin was let go |
| `SOA_GX_DLLOG=1` | a diagnostic: every move of the CPU FIFO away from the command processor's (the game recording a display list), the draws parsed while it was away, and each display-list call with its size; the report adds a table per buffer (PLAN C5a, FINDINGS "Recorded display lists"). Changes nothing drawn |
| `SOA_SEED=n` | a 32-bit number, decimal or `0x` hex: the game's three reseeds of its random numbers -- every field load and the two at every battle start, OSGetTick called from `0x801012B0`, `0x8000A1D0` and `0x8000A1D8` -- take values made from it (`runtime/seed.c`), so a run with the same seed starts every battle from the same seeds; every other timebase read is untouched. The report counts the pins per site, each pin prints `[seed] pin: site S (lr X) n N -> 0xV` (`python tools/tests/test_seed.py <log>` checks a run by those lines), and a recording's `# config` line ends `seed=n` with the seed in decimal, or names none when the value was refused (PLAN-GAMEPLAY-MODS P6). Whether the same seeds give the same battle is K6's question |
| `SOA_FRAMETIME_FROM=N` | start the `[frametime]` record at frame `N` without uncapping: a capped run's figures for the same stretch an uncapped one reports |
| `SOA_FIFO_DUMP=n,n` | capture those frame numbers; each lands as `NNNN.fifo`/`.regs`/`.ram`, zero-padded to four digits, for `gen\soa.exe --replay build/fifo/NNNN` |
| `SOA_FIFO_DIR=path` | where those captures go (default `build/fifo`, the corpus `config/fifo_manifest.tsv` pins; capture somewhere else) |
| `SOA_THREADS=n` | rasterizer worker threads, default three quarters of the logical CPUs (12 of 16), which was fastest in the heaviest field scene measured (FINDINGS "H15c") |
| `SOA_NOSOUND=1` | no audio device |
| `SOA_WAV=file.wav` | also write everything the game plays to a WAV file (works headless and with `SOA_NOSOUND`) |
| `SOA_WATCHDOG=s` | stop after s seconds with no video frame and print a report (default 20 headless, off when a window is open; 0 disables) |
| `SOA_POKE=f:a=v[,f:a=v]` | store the 32-bit value `v` at guest address `a` at the end of frame `f`, once, printing what was there before. The one way to answer "what does the game do if this variable says that" without a recompile. Fires on the first frame at or after `f`, so a skipped frame number does not silently lose the poke. Up to 256 items, which is 85 field warps at three words each; a mistyped item stops parsing and says so rather than driving a run that looks like it ignored you. The field's own map identity is `0x80311AC4` (map number), `0x80311AC8` (map letter in the top byte) and `0x80311AEC` (field state, 8 is the steady update). A warp is the destination's script name, e.g. `ME103A.SCT`, as three words at `0x80305CF0`, then 15 in `0x80311AEC`: the game's own warp, no button; also set `0x8030E420` (`sys[15]`, where the party came from) to 0 so the map takes its default entrance, and do not poke the map words (`HANDOFF.md` has the command). Numbers are decimal or `0x` hex and must fit 32 bits; a sign, a space or a leading zero is refused rather than read some other way |
| `SOA_MODS=dir` | load every mod in `dir`: each folder holding a `mod.ini` (`manifest = 2`, a stable `id` and a `version`, which a recording names it by as `id@version`, `name`, optional `authors`, `api`, the least mod API it needs, and `dol_sha1`, the SHA-1 of the DOL it was made for; a `mod.ini` without `manifest` is read as version 1, with no id; two mods with one id are refused; a key beginning `x_` is noted and passed over, any other unknown key refuses the mod) and a `patches.txt` of `trigger 0x80346d28 = value [when scene=N state=N map=NNNx]` lines, where the trigger is `every_frame`, `once` or `on_map_load`. A patch writes one 32-bit word at the end of a frame. A mod with any fault — a misspelled address, one in the hardware window, outside RAM, unaligned or inside the game's code, an unknown key, another DOL — is refused whole and says which line. The report ends with how often each patch applied, and a recording names the mods it was made with. `mods/encounters-off` is an example (`docs/PLAN-60FPS-MODS.md` M1). A mod may also, or instead, hold a `mod.dll`: native code on `runtime/soa_mod.h`, exporting `soa_mod_init`, loaded once `mod.ini` checks out -- see `examples/mods/map-log` for the template and its build line (M3). Its `pad_filter` sees every controller read after `SOA_PAD_RECORD` has its copy, so a recording made with a mod replays with it, its `projection_filter` sees each new projection, its `texture_provider` may replace any texture, by its content hash, with an image of any size, and from a safe-point callback its `call_guest` may call the game's own functions. Mods load under `--replay` too, which renders a captured frame through them deterministically |
| `SOA_MEMPOKE=a,b` | store a word at each guest address before the game boots and read it back; an address past the console's 24 MB, e.g. `0x81800000`, is how to fire the out-of-range tripwire on purpose (needs no disc) |
| `SOA_STRICT=1` | stop at the first hardware access outside the modelled range, with a guest backtrace (almost always a garbage pointer); without it the first twenty are reported and the run goes on |
| `SOA_HASH=1` | print an FNV-1a hash of every frame the port presents (what `tools/scenario.py replay` compares) |
| `--replay A B` | render two consecutive captures, A to `A.png` and B to `B.png`, then the image halfway between them to `B.mid.png`: every draw of B matched in A has its positions interpolated, the rest are drawn as B draws them (PLAN-60FPS-MODS H10). `SOA_PAIR_T=t` (0 to 1, default 0.5) picks another point, `SOA_PAIR_LIST=file` writes the matched pairs, and `python tools/midpoint.py` runs every check on the five pairs in `build/perfset` |
| `SOA_MMIO=1` | log the first few accesses of every hardware register as they happen |
| `SOA_SELFTEST=1` | run the library and device checks instead of the game |
| `SOA_PROFILE=n` | `0` turns off the end-of-run sampling profile (one fewer thread); `n>1` shows n rows |
| `SOA_SYMBOLS=path` | function names for that profile (default `config/functions.tsv`, found by running from the repository root) |
| `SOA_CARD=path` | memory card image for slot A (default `build/cards/slotA.raw`, created blank on the first write; `tools/cardformat.py write` makes one the game will mount) |
| `SOA_CARD_VERBOSE=1` | one `[card]` line per EXI transaction: the frame, the device, the command and the card address |
| `SOA_TRACE=1` / `SOA_TRACE_DUMP=1` / `SOA_WATCH=addr,len` | tracepoints from `config/trace.txt`; 12 words of memory at each hit; a store watchpoint |
| `SOA_PEEK=addr@N[-M][,...]` | print the word at guest address `addr` at the end of frame `N`, or of every frame from `N` to `M`, with the game's retrace count (`[peek] frame F: ADDR = VALUE (retrace R)`); fires before `SOA_POKE` in the same frame, so it reads what the game wrote. Up to 256 items, a list of its own. The way to time something in fields, e.g. a fade at 0x80347510 |
| `SOA_WATCH_FROM=N` | start `SOA_WATCH` at the game's frame `N`: earlier stores are neither printed nor counted against its 201 lines. Every `[watch]` line ends with the frame it happened in |
| `SOA_GXR_DEBUG=N` / `SOA_GXR_DRAWS=N` / `SOA_GXR_PIXEL=x,y` | renderer forensics in `--replay`: triangles from draw N on, stop after N draws, narrate one pixel |
| `SOA_TEXVERIFY=1` | hash every texture on every lookup, as before PLAN-60FPS-MODS H12, and count the textures whose bytes changed inside one texture epoch: a rewrite with no texture-cache invalidate (BP 0x66), EFB copy or frame end since the last hash, which the renderer would otherwise draw from its old decode. The report's `[gxr] textures:` line gives the count, and the first eight are named |
| `SOA_GXR_DRAIN=1` | order EFB copies the way the renderer did before PLAN-60FPS-MODS H14: a full drain before and after every copy that reads rows other workers own (every copy the game makes), and for every texture read from a queued copy. The fallback if a scene draws wrong with H14's fences, and the oracle they are tested against |
| `SOA_GXR_TOKENWAIT=1` | make a draw token (`GXSetDrawSync`) wait for the copies before it. Off, a token is answered as it is parsed, as it always has been, and one that arrives while a copy is still running is counted in the report; on, a game that reads a copy's memory right after its token sees it finished, at the cost of H14's gain (this game's tokens sit at the top of each frame) |
| `SOA_HOSTPROF=1` | sample the instruction pointer of every rasterizer worker and of the guest thread about once a millisecond and end the report with where their time went, by function and by source line (through `gen/soa.pdb`, which `--link` writes): the host code under a translated function -- a memory accessor, a paired-single helper -- that `SOA_PROFILE` charges to the guest function. The workers' table also folds by the innermost inlined function, so the pixel path's `__forceinline` helpers each get their own row and line. For finding what to make faster; a profiled run is for reading, not for timing |
| `SOA_GXR_NOSIMD=1` | the pixel path's SSE4.1 code (the bilinear blend, H15d) takes its scalar loop instead, which is also what a CPU without SSE4.1 gets; the two give the same bytes (`test_gxr_fastpath.py`) |
| `SOA_REPLAY_REPEAT=N` | `--replay` renders the capture N times, each from its own RAM image: a frame long enough for `SOA_HOSTPROF` to sample |
| `SOA_GXR_STALL=w:k:us[,...]` | a test knob: rasterizer worker `w` waits `us` microseconds before every command of kind `k` (0 a draw, 1 a copy, 2 a clear), which turns an ordering race between the workers into a certain failure (`tools/tests/test_gxr_overlap.py`). The run says it is a test |
| `SOA_GXR_LIGHTS=N` / `SOA_GXR_NOTEX=1` / `SOA_CULLFLIP=1` | more renderer forensics: dump the lighting setup of the first N draws, draw every texture flat grey, reverse the winding the rasterizer culls by |
| `SOA_NOAX=1` / `SOA_AX_VERBOSE=1` / `SOA_ARAM_VERBOSE=1` | audio forensics: skip the AX mixer entirely, one line per voice command, one line per ARAM DMA |
| `SOA_PACE=1` | yield to the host scheduler on every interrupt delivery (a loaded machine runs the guest more evenly) |
| `SOA_TSC=0` | time the renderer with `QueryPerformanceCounter` instead of the time-stamp counter |
| `SOA_QUIET_GUEST=1` | drop the game's own printf output |

## Checking it still works

```powershell
python -m pytest                     # 911 tests; any that need a dump skip themselves
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
