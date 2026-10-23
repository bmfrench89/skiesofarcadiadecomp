#!/usr/bin/env python3
"""The game's data by name (T9, docs/specs/game-names.md).

    python tools/gamedata.py find 0x803474BC [...]   # instructions in the DOL that reach an address
    python tools/gamedata.py check                   # every line of config/gamedata.txt against the DOL
    python tools/gamedata.py generate [--write]      # the header, the runtime's table, MODDING-NAMES.md

`find` is how a line's `ref` is chosen: an address goes into the file only with
an instruction that reaches it. `check` is what test_gamedata.py runs.
`generate` without --write says which made file is out of date and exits 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import matchcheck  # noqa: E402
from soa import dol as D  # noqa: E402
from soa import gamedata as G  # noqa: E402

DOL = ROOT / "extracted" / "sys" / "main.dol"
SYMBOLS = ROOT / "config" / "symbols.txt"
MADE = {
    ROOT / "runtime" / "soa_gamedata.h": G.header,
    ROOT / "runtime" / "gamedata_names.h": G.table,
    ROOT / "docs" / "MODDING-NAMES.md": G.markdown,
}


def open_dol(path: Path = DOL):
    dol = D.parse(path.read_bytes())
    return dol, matchcheck.sda_bases(dol)


def made(data: G.GameData) -> dict[Path, str]:
    return {path: fn(data) for path, fn in MADE.items()}


def stale(data: G.GameData) -> list[Path]:
    """The made files that differ from what the file makes now."""
    out = []
    for path, text in made(data).items():
        # A Windows checkout may give the file CRLF (MODDING-API.md's check does the same).
        have = path.read_bytes().decode("utf-8").replace("\r\n", "\n") if path.exists() else None
        if have != text:
            out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("command", choices=("find", "check", "generate"))
    ap.add_argument("addresses", nargs="*")
    ap.add_argument("--dol", type=Path, default=DOL)
    ap.add_argument("--file", type=Path, default=G.CONFIG)
    ap.add_argument("--write", action="store_true", help="generate: write the made files")
    args = ap.parse_args(argv)
    if args.command == "find":
        dol, sda = open_dol(args.dol)
        for text in args.addresses:
            addr = int(text, 16)
            refs = G.find(dol, addr, sda)
            print(
                f"0x{addr:08X}: {len(refs)} instruction(s)"
                + "".join(f" 0x{r:08X}" for r in refs[:12])
            )
        return 0
    data = G.load(args.file)
    if args.command == "check":
        dol, sda = open_dol(args.dol)
        faults = G.verify(data, dol, sda, G.data_objects(SYMBOLS.read_text(encoding="utf-8")))
        for f in faults:
            print(f"FAIL {f}")
        print(
            f"gamedata: {len(data.entries) - len({f.split(':')[1] for f in faults})} of {len(data.entries)} names re-found in the code"
            if not faults
            else f"gamedata: {len(faults)} fault(s)"
        )
        return 1 if faults else 0
    if args.write:
        for path, text in made(data).items():
            path.write_bytes(text.encode("utf-8"))
            print(f"wrote {path.relative_to(ROOT)}")
        return 0
    old = stale(data)
    for path in old:
        print(f"stale: {path.relative_to(ROOT)} (python tools/gamedata.py generate --write)")
    return 1 if old else 0


if __name__ == "__main__":
    raise SystemExit(main())
