# Contributing

This repository holds tooling, a runtime and analysis metadata for a native
port of Skies of Arcadia Legends. It never holds game data. Before anything
else, read that rule twice: no disc images, no executables from the disc, no
extracted assets, no translated C. `tools/guard.py` refuses to let such files
into the tree and CI scans the whole history for them.

## From a clean machine to a running game

1. Install Python 3.14 (the RVZ reader uses the standard library's zstd
   decoder, which arrived in 3.14) and the Visual Studio 2022 Build Tools with
   the C++ workload. `cl.exe` does not need to be on `PATH`; the tools find it
   through `vswhere`.
2. Clone the repository and install the Python package with its development
   extras:

       pip install -e ".[dev]"

3. Unpack your own disc dump. Every format the extractor understands ends up
   in `extracted/`, which is gitignored:

       python tools/extract.py "path/to/Skies of Arcadia Legends (USA).rvz" --iso

4. Translate the executable, compile it and link the runtime:

       python tools/recompile.py --compile --link

   The first build compiles the translated code without optimisation; add
   `--optimize` for a build that runs the game at full speed (a minute or two
   longer). After changing anything under `runtime/`, `--link` on its own is
   enough.
5. Run it. In PowerShell:

       $env:SOA_RENDER = '1'
       gen\soa.exe extracted

   In cmd.exe it is `set SOA_RENDER=1` instead. The two are not
   interchangeable: PowerShell reads `set SOA_RENDER=1` as creating a
   variable whose name contains the equals sign, leaves the environment
   untouched, and gives you a headless run that nothing stops, because the
   watchdog only fires when no frame is presented and frames keep being
   counted whether or not anything is drawn.

   `$env:SOA_SELFTEST = '1'; gen\soa.exe extracted` exercises the translated C library,
   the device models and the software renderer (a synthetic frame through the
   real GX pipe) without the game, and is a quick check that a build is sane.

## Tests and style

    python -m pytest
    ruff check tools

The tests need no disc: anything that depends on game data is skipped when
`extracted/` is absent. Keep it that way when adding tests -- synthesise the
bytes you need or skip.

## What goes where

- `tools/` -- the analysis and recompilation pipeline (`tools/soa/` is the
  package; `tools/*.py` are entry points).
- `runtime/` -- the C runtime the translated code links against: CPU state,
  memory, the device models, the software GX and the AX mixer.
- `config/` -- the only material derived from the game: function addresses,
  sizes, names, and the HLE, hook and tracepoint lists. Never anything from
  the disc itself.
- `docs/` -- the spec, roadmap and findings. The roadmap is the source of
  truth for what is done; update it in the same change as the work.

## Regenerating the function inventory

`config/functions.tsv` and `config/symbols.txt` come from
`tools/inventory.py`, which runs control-flow recovery over the DOL, merges
the evidence-backed names in `config/names.txt` and can merge display names
from a decomp-toolkit (`dtk`) symbol file. `dtk` is
optional and not vendored: drop a release binary into `vendor/dtk/` (also
gitignored) and pass its `symbols.txt` with `--dtk`. Without it, functions
keep their `fn_XXXXXXXX` names, which is fine for building and running.

## Decompilation project

`config/GEAE8P/` is a decomp-toolkit project: with your dump unpacked,

    vendor/dtk/dtk.exe dol split config/GEAE8P/config.yml build/dtk

writes disassembly, relocatable objects and a linker script under `build/`
(never committed). `splits.txt` names the translation units; refine it as
functions get identified, and `dtk` keeps `symbols.txt` updated. The
recompiler reads its own inventory in `config/functions.tsv` and
`config/symbols.txt`.

The two symbol files are not the same file and do not come from the same
place. `config/symbols.txt` is ours, written by `tools/inventory.py` from the
control-flow recovery plus every name in `config/names.txt`.
`config/GEAE8P/symbols.txt` belongs to the `dtk` project and is what
`build/dtk/obj/` -- the objects objdiff matches *by name* -- is generated
from, so a name only we knew would leave objdiff calling the function
`fn_XXXXXXXX` and the two tools disagreeing about the same address.
`tools/inventory.py` therefore also rewrites the `fn_XXXXXXXX` entries of the
dtk file with the recovered names, leaving dtk's own SDK signature matches
alone; `python tools/soa/symbols.py --dry-run` shows what that pass would
rename without running the whole recovery.

## Decompiling functions

Hand-written C lives under `src/`, compiled with the original Metrowerks
compiler and checked byte for byte against the executable:

    python tools/fetch_toolchain.py          # once: the compilers into vendor/
    python tools/decomp.py                   # build every unit, compare every function

`config/GEAE8P/units.txt` names each unit's source, compiler version and
flags. A function counts as done when `tools/matchcheck.py` reports MATCH;
`tools/disasm.py <name>` shows the target when it does not. The port keeps
running the recompiled code either way: matching functions are proof of
understanding. They are also compiled natively (renamed `dc_*`) into the
port; an adapter in `runtime/decomp_swap.c` plus a line in `config/hle.txt`
swaps one in for its translation, and `SOA_SELFTEST=1` runs each pair on
random inputs, so a match that is somehow wrong still gets caught. Callees
that are not decompiled yet come from `runtime/decomp_shims.c`. Rebuild
with `--compile --optimize --link` after touching `config/hle.txt`.

## Commits

Small, self-contained commits with a subject line that says what changed and
a body that says why. Run the guard and the tests before pushing:

    python tools/guard.py
    python -m pytest
