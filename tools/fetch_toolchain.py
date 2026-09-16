"""Fetch the Metrowerks compilers the game was built with (and the object
diff tool) into vendor/, which is gitignored.

    python tools/fetch_toolchain.py [--versions 1.3.2,2.0]

The compilers come from the decompilation community's archive
(files.decomp.dev/compilers_latest.zip, about 80 MB); only the GameCube
versions asked for are unpacked. Nothing here touches game data.
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ARCHIVE = "https://files.decomp.dev/compilers_latest.zip"
OBJDIFF = (
    "https://github.com/encounter/objdiff/releases/download/v3.8.1/objdiff-cli-windows-x86_64.exe"
)


def fetch(url: str) -> bytes:
    print(f"fetching {url}")
    with urllib.request.urlopen(url) as r:  # noqa: S310 - fixed https URLs
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--versions", default="1.3.2", help="comma-separated GameCube compiler versions"
    )
    ap.add_argument("--vendor", type=Path, default=Path("vendor"))
    ap.add_argument("--objdiff", action="store_true", help="also fetch objdiff-cli")
    args = ap.parse_args()

    dest = args.vendor / "mwcc"
    dest.mkdir(parents=True, exist_ok=True)
    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    missing = [v for v in versions if not (dest / "GC" / v / "mwcceppc.exe").exists()]
    if missing:
        blob = fetch(ARCHIVE)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            members = [n for n in z.namelist() if any(n.startswith(f"GC/{v}/") for v in missing)]
            if not members:
                print(f"error: none of {missing} in the archive", file=sys.stderr)
                return 1
            z.extractall(dest, members=members)
        print(f"unpacked {', '.join(missing)} into {dest / 'GC'}")
    else:
        print(f"compilers present: {', '.join(versions)}")

    if args.objdiff:
        exe = args.vendor / "objdiff-cli.exe"
        if not exe.exists():
            exe.write_bytes(fetch(OBJDIFF))
            print(f"wrote {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
