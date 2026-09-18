#!/usr/bin/env python3
"""Check the extracted executable is the build config/ describes.

    python tools/checkdump.py

Hashes `extracted/sys/main.dol` and compares it with the sha1
`config/GEAE8P/config.yml` already records for decomp-toolkit. On a mismatch
it names both hashes and exits non-zero.

Why this exists as a command of its own, rather than a check inside
`recompile.py`: the executable has five readers in this repository
(`recompile.py`, `inventory.py`, `decomp.py`, `matchcheck.py` and dtk itself)
and `gen/soa.exe` is a sixth, and every one of them would happily run on the
wrong build. Asking each to check separately is five copies of one question;
asking once, in a command that takes a second and needs nothing but
`extracted/`, is the same coverage. `tools/extract.py` calls the same code at
the end of an extraction, so the answer arrives the first time through the
README whether or not anyone runs this; run it by hand when an `extracted/`
has been sitting around and you no longer remember which dump made it.

Needs no disc image, no compiler and no `gen/`.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa.dump import DEFAULT_CONFIG, ProjectError, verify  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"decomp-toolkit project file holding the hash (default {DEFAULT_CONFIG})",
    )
    ap.add_argument(
        "--dol",
        type=Path,
        default=None,
        help="the executable to hash (default: the config's own object: path)",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="directory the config's object: path is relative to (default .)",
    )
    args = ap.parse_args()

    try:
        verdict = verify(args.config, args.dol, args.root)
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(verdict.report(), file=sys.stdout if verdict.ok else sys.stderr)
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
