#!/usr/bin/env python3
"""One scripted run of docs/specs/reach.md: the port with the lab mod.

    python tools/reach.py run u1-hold --card build/savetest/card-partG.raw \\
        --lab "entry:3300:4005;hold-hp:3300-30000;peek:2600-30000:0x80310B60" \\
        --pad "1600:start,1640:a,...,3400:a@150" --frames 30000
    python tools/reach.py run u5-partC --card build/savetest/card-partC.raw --lab objects \\
        --soak-seed 40 --battle --accelerate 600 --snap 0
    python tools/soak.py check build/reach/u1-hold/run.log --expect-flag 304

Each run gets its own folder, build/reach/<name>/: a copy of the card (the
game writes to it), the lab mod alone in mods/ (so no other mod's patches
reach the run), the snapshots in frames/, and run.log. The port runs traced
(SOA_TRACE=1), strict (SOA_STRICT=1), with the settings file off
(SOA_SETTINGS=0) and drawing (SOA_RENDER=1); --snap 0 draws every frame and
writes no snapshot, which is what the renderer's draw tripwires need.

Refused before anything runs: a lab mod.dll older than its mod.c (build it
with `python tools/recompile.py --link`), a missing card, and a name that is
not a plain folder name. Every SOA_ variable of the calling shell is dropped,
so a switch left set in a terminal never reaches a run by accident; --env
K=V sets one on purpose.

Only one soa.exe at a time (CLAUDE.md): runs share nothing here, but the
port's other defaults (build/cards, build/frames) are why that rule exists.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import soak  # tools/ is sys.path[0] when this runs as a script

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "examples" / "mods" / "lab"
EXE = ROOT / "gen" / ("soa.exe" if os.name == "nt" else "soa")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def lab_library() -> Path:
    for name in ("mod.dll", "mod.so"):
        if (LAB / name).is_file():
            return LAB / name
    raise SystemExit(f"no lab mod built in {LAB}: python tools/recompile.py --link builds it")


def check_fresh(lib: Path, source: Path) -> None:
    if lib.stat().st_mtime < source.stat().st_mtime:
        raise SystemExit(
            f"{lib} is older than {source}: python tools/recompile.py --link builds it again"
        )


def pad_script(args: argparse.Namespace) -> str | None:
    if args.pad is not None:
        return args.pad
    if args.soak_seed is not None:
        return soak.script(args.soak_seed, args.first, args.last, battle=args.battle)
    return None


def environment(args: argparse.Namespace, folder: Path, base: dict[str, str]) -> dict[str, str]:
    """The run's environment: the caller's without any SOA_ switch, then the
    run's own. Paths are relative to ROOT, where the port runs."""
    env = {k: v for k, v in base.items() if not k.startswith("SOA_")}
    rel = folder.relative_to(ROOT).as_posix()
    env.update(
        SOA_CARD=f"{rel}/card.raw",
        SOA_MODS=f"{rel}/mods",
        SOA_FRAMES_DIR=f"{rel}/frames",
        SOA_FRAMES=str(args.frames),
        SOA_STRICT="1",
        SOA_TRACE="1",
        SOA_SETTINGS="0",
        SOA_RENDER="1",
    )
    if args.lab:
        env["SOA_LAB"] = args.lab
    if args.snap:
        env["SOA_SNAP"] = str(args.snap)
    pad = pad_script(args)
    if pad:
        env["SOA_PAD"] = pad
    pokes, peeks = list(args.poke or []), list(args.peek or [])
    warp = getattr(args, "warp", None)
    if args.accelerate or warp:
        pokes.append(soak.pokes(warp, soak.WARP_FRAME, args.accelerate, args.first, args.last))
    if args.accelerate:
        peeks.append(soak.peeks(args.first, args.last, args.accelerate))
    if pokes:
        env["SOA_POKE"] = ",".join(pokes)
    if peeks:
        env["SOA_PEEK"] = ",".join(peeks)
    for kv in args.env or []:
        k, sep, v = kv.partition("=")
        if not sep or not k.startswith("SOA_"):
            raise SystemExit(f"--env {kv!r}: give SOA_NAME=value")
        env[k] = v
    return env


def cmd_run(args: argparse.Namespace) -> int:
    if not NAME.fullmatch(args.name):
        raise SystemExit(f"{args.name!r} is not a plain folder name")
    card = Path(args.card)
    if not card.is_file():
        raise SystemExit(f"no card at {card}")
    lib = lab_library()
    check_fresh(lib, LAB / "mod.c")
    if not EXE.is_file():
        raise SystemExit(f"no {EXE}: python tools/recompile.py --compile --link builds it")
    folder = ROOT / "build" / "reach" / args.name
    (folder / "frames").mkdir(parents=True, exist_ok=True)
    mods = folder / "mods" / "lab"
    mods.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LAB / "mod.ini", mods / "mod.ini")
    shutil.copy2(lib, mods / lib.name)
    for extra in args.mod or []:
        src = Path(extra)
        if not (src / "mod.ini").is_file():
            raise SystemExit(f"--mod {extra}: no mod.ini there")
        for name in ("mod.dll", "mod.so", "mod.c"):
            if (src / name).is_file() and (src / "mod.c").is_file() and name != "mod.c":
                check_fresh(src / name, src / "mod.c")
        dest = folder / "mods" / src.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file() and f.suffix in (".ini", ".txt", ".dll", ".so"):
                shutil.copy2(f, dest / f.name)
    shutil.copy2(card, folder / "card.raw")
    env = environment(args, folder, dict(os.environ))
    log = folder / "run.log"
    start = time.monotonic()
    with log.open("wb") as out:
        proc = subprocess.run(
            [str(EXE), "extracted"], cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT
        )
    print(
        f"[reach] {args.name}: exit {proc.returncode} after {time.monotonic() - start:.0f} s; log {log}"
    )
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="one run into build/reach/<name>")
    r.add_argument("name")
    r.add_argument("--card", required=True, help="the save card the run starts from (copied)")
    r.add_argument("--lab", default="", help="SOA_LAB for examples/mods/lab")
    r.add_argument(
        "--mod",
        action="append",
        metavar="DIR",
        help="another mod folder to load beside the lab, e.g. mods/autotext (repeatable)",
    )
    r.add_argument("--frames", type=int, default=20000)
    r.add_argument(
        "--snap", type=int, default=100, help="SOA_SNAP; 0 draws every frame and writes none"
    )
    pad = r.add_mutually_exclusive_group()
    pad.add_argument("--pad", help="SOA_PAD as given")
    pad.add_argument("--soak-seed", type=int, help="soak.py's generated play from this seed")
    r.add_argument("--battle", action="store_true", help="with --soak-seed: the battle mix")
    r.add_argument("--first", type=int, default=None, help="with --soak-seed or --accelerate")
    r.add_argument("--last", type=int, default=33000, help="with --soak-seed or --accelerate")
    r.add_argument(
        "--accelerate",
        type=int,
        metavar="K",
        help="soak.py's encounter accelerator, every K frames",
    )
    r.add_argument(
        "--warp",
        type=soak.map_name,
        metavar="NNNx",
        help="soak.py's warp by name at frame 3300; random play and the accelerator start once it settles",
    )
    r.add_argument("--poke", action="append", help="SOA_POKE items (repeatable)")
    r.add_argument("--peek", action="append", help="SOA_PEEK items (repeatable)")
    r.add_argument(
        "--env", action="append", metavar="SOA_NAME=value", help="one more switch (repeatable)"
    )
    args = p.parse_args(argv)
    if args.first is None:
        args.first = soak.WARP_FRAME + soak.WARP_SETTLE if args.warp else 3200
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
