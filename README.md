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
- **[docs/FINDINGS.md](docs/FINDINGS.md)** — disc analysis evidence base
- **[docs/PROGRESS.md](docs/PROGRESS.md)** — what got built, in order

## Status

The game boots, plays its intro, reaches the title screen, starts a new
game and plays through the opening cutscenes, the first battle and into
the first field (the Valuan ship's hold: walking, the minimap, menus and
random encounters), with dialogue text, music and sound, rendered by a
software implementation of the GameCube's graphics pipeline in a window
with keyboard or gamepad input. See the roadmap for
what is done and what is not (saves are not implemented yet).

## Building and running

You need Windows, Python 3.14 (its standard library decodes zstd, which the RVZ reader needs), the Visual Studio 2022 Build Tools (MSVC),
and your own dump of the disc (`.rvz`, `.iso` or `.gcm`).

```
pip install -e .[dev]
python tools/extract.py "path/to/Skies of Arcadia Legends (USA).rvz" --iso
python tools/recompile.py --compile --link
set SOA_RENDER=1
gen\soa.exe extracted
```

`extract.py` unpacks the disc into `extracted/` (gitignored, never committed).
`recompile.py` translates the whole executable to C into `gen/` (also
gitignored), compiles it with MSVC and links the runtime into `gen/soa.exe`.
The default compiles the translated code without optimisation (fast to
build, fine for testing); add `--optimize` for a release build of it, which
takes longer but runs the game faster.
The function inventory it uses is in `config/` and is the only thing derived
from the game that the repository carries: addresses, sizes and names.

### Controls

Keyboard when the window has focus: arrows or WASD move the stick, IJKL the
C-stick; X = A, Z = B, C = X, V = Y, Enter or Space = START, R = Z, Q = L,
E = R, T/F/G/H = D-pad, Escape quits. An XInput gamepad works as you would
expect (triggers are L/R, the right shoulder is Z).

### Useful environment variables

| Variable | Effect |
|---|---|
| `SOA_RENDER=1` | render (and open the window) |
| `SOA_SCALE=n` | window scale, default 2 |
| `SOA_WINDOW=0` | render without a window |
| `SOA_FRAMES=n` | headless: write every nth frame to `build/frames/` and skip rendering the rest |
| `SOA_PAD=frame:buttons,...` | scripted controller for headless runs, e.g. `1700:start,1800:a`; `3600:a@150` repeats A every 150 frames, `9000:sup#120` holds the stick up for 120 frames |
| `SOA_SPEED=n` | run guest time n times faster than the wall clock (headless exploration; sound will not keep up) |
| `SOA_FIFO_DUMP=a,b` | capture those frames for `gen\soa.exe --replay build/fifo/000a` |
| `SOA_FIFO_DIR=path` | where those captures go (default `build/fifo`, the corpus `config/fifo_manifest.tsv` pins; capture somewhere else) |
| `SOA_THREADS=n` | rasterizer worker threads, default half the CPUs |
| `SOA_NOSOUND=1` | no audio device |
| `SOA_WAV=file.wav` | also write everything the game plays to a WAV file (works headless and with `SOA_NOSOUND`) |
| `SOA_WATCHDOG=s` | stop after s seconds with a report (default 20; 0 disables) |
| `SOA_CARD=path` | memory card image for slot A (default `build/cards/slotA.raw`, created blank on the first write; `tools/cardformat.py write` makes one the game will mount) |
| `SOA_CARD_VERBOSE=1` | one `[card]` line per EXI transaction: the frame, the device, the command and the card address |
| `SOA_TRACE=1` / `SOA_WATCH=addr,len` | tracepoints from `config/trace.txt`; a store watchpoint |
| `SOA_GXR_DEBUG=N` / `SOA_GXR_DRAWS=N` / `SOA_GXR_PIXEL=x,y` | renderer forensics in `--replay`: triangles from draw N on, stop after N draws, narrate one pixel |

## Repository layout

- `tools/` — disc extraction, analysis, the recompiler (`tools/soa/`), disassembler, capture decoders, the memory-card formatter (`cardformat.py`), tests
- `runtime/` — the native runtime: CPU helpers, memory and MMIO, device models, threads, the software GX, the window
- `config/` — analysis metadata: the function inventory, HLE bindings, hooks, tracepoints; `config/GEAE8P/` is the decomp-toolkit project (splits and symbols)
- `src/`, `include/` — hand-decompiled units, compiled with the original Metrowerks compiler and checked word for word against the executable (`tools/decomp.py`)
- `docs/` — specification, roadmap, findings, progress log
