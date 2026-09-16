#!/usr/bin/env python3
"""Recover the function inventory and write it to config/.

    python tools/inventory.py [--dol extracted/sys/main.dol] [--dtk build/dtk-symbols.txt]
                              [--out config]

Runs control-flow recovery over the DOL, merges display names from a dtk
symbol file when one is given, and writes:

    config/symbols.txt    dtk-format symbols (functions + passed-through objects)
    config/functions.tsv  per-function analysis metadata

Both contain only addresses, sizes and names -- never code.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa import dol as D  # noqa: E402
from soa import symbols as S  # noqa: E402
from soa.ppc import cfg  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dol", type=Path, default=Path("extracted/sys/main.dol"))
    ap.add_argument("--dtk", type=Path, default=None, help="dtk symbols.txt to take names from")
    ap.add_argument("--names", type=Path, default=Path("config/names.txt"), help="hand/string-recovered names")
    ap.add_argument(
        "--dtk-project",
        type=Path,
        default=Path("config/GEAE8P/symbols.txt"),
        help="decomp-toolkit symbols file to carry the recovered names into (fn_ entries only)",
    )
    ap.add_argument("--out", type=Path, default=Path("config"))
    args = ap.parse_args()

    if not args.dol.exists():
        print(f"error: {args.dol} not found; run tools/extract.py first", file=sys.stderr)
        return 1

    dol = D.parse(args.dol.read_bytes())
    started = time.time()
    functions, stats = cfg.build_iterative(dol)
    cov = cfg.coverage(dol, functions)
    print(
        f"recovered {len(functions):,} functions in {time.time() - started:.1f}s; "
        f"{cov['coverage_pct']:.2f}% of .text; {stats['jump_tables']} switch tables"
    )

    dtk_syms = S.load_dtk(args.dtk) if args.dtk else []
    if dtk_syms:
        print(f"dtk symbols: {len(dtk_syms):,} loaded from {args.dtk}")

    names = S.load_names(args.names)
    if names:
        print(f"recovered names: {len(names):,} loaded from {args.names}")

    rows = S.build_inventory(dol, functions, dtk_syms, names)
    named = sum(1 for r in rows if r["source"] != "auto")
    print(f"named functions: {named:,} of {len(rows):,}")

    args.out.mkdir(parents=True, exist_ok=True)
    S.write_tsv(rows, args.out / "functions.tsv")
    S.write_dtk(S.symbols_from_inventory(dol, rows, dtk_syms), args.out / "symbols.txt")
    print(f"wrote {args.out / 'functions.tsv'} and {args.out / 'symbols.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
