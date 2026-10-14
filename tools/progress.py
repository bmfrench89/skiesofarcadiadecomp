"""How far the decompilation has come: README.md's progress section, and the list behind it.

    python tools/progress.py --measure   rebuild config/decompiled.tsv, then the README
    python tools/progress.py             rewrite README.md's section from what is committed
    python tools/progress.py --check     exit 1 if either is out of date (a test runs this)

``--measure`` builds every unit in config/GEAE8P/units.txt with the vendored
compiler, the way tools/decomp.py does, and runs tools/matchcheck.py on each, so
it needs the compiler and your dump. It records only units that match: one that
differs, or one whose compiler is missing, stops it, because a list that counts
a broken unit or skips an unbuilt one is a progress figure nobody can trust.
Each defined function the executable has a counterpart for becomes one row of
config/decompiled.tsv; a static helper the compiler inlined has none, and is
not counted, which is how tools/decomp.py reports it too.

Everything else needs neither: the README section is rendered from that list,
config/functions.tsv (the whole program), config/GEAE8P/splits.txt (the areas)
and config/hle.txt (what runs in the port). ``--check`` is what keeps the
numbers from rotting the way counts in prose do here: it fails when the README
differs from a fresh render, when units.txt names a unit the list has never
measured or the list keeps one units.txt dropped, or when a listed function no
longer appears in its unit's source.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decomp as DC  # noqa: E402
import matchcheck as MC  # noqa: E402
from soa import symbols as S  # noqa: E402
from soa.hle import load_bindings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
LIST = ROOT / "config" / "decompiled.tsv"
UNITS = ROOT / "config" / "GEAE8P" / "units.txt"
SPLITS = ROOT / "config" / "GEAE8P" / "splits.txt"
FUNCTIONS = ROOT / "config" / "functions.tsv"
NAMES = ROOT / "config" / "names.txt"
HLE = ROOT / "config" / "hle.txt"

BEGIN = "<!-- progress:begin, written by python tools/progress.py: edit that, not this -->"
END = "<!-- progress:end -->"

VERIFIED, LINK = "verified", "link"
COLUMNS = ("unit", "state", "address", "size", "name")

# What each range in splits.txt holds, for a reader who has not met the SDK's
# library names; a range not listed here is shown by its split name.
AREAS = {
    "sdk/init.c": "Start-up code (`.init`)",
    "game/game.c": "Game code",
    "sdk/ppc/PPCArch.c": "SDK: PowerPC architecture",
    "sdk/os/os.c": "SDK: operating system",
    "sdk/db/db.c": "SDK: debugger hooks",
    "sdk/mtx/mtx.c": "SDK: matrix and vector maths",
    "sdk/dvd/dvd.c": "SDK: disc drive",
    "sdk/vi/vi.c": "SDK: video output",
    "sdk/pad_ar_ai_dsp_card.c": "SDK: controller, ARAM, audio, DSP, memory card",
    "sdk/gx/gx.c": "SDK: GX graphics",
    "sdk/trk/MetroTRK.c": "MetroTRK debug monitor",
    "sdk/msl/msl.c": "C library (MSL)",
    "sdk/exi/exi.c": "SDK: EXI bus",
    "sdk/si/si.c": "SDK: serial bus",
    "lib/middleware.c": "Rendering middleware",
}


@dataclass(frozen=True)
class Row:
    unit: str
    state: str
    address: int
    size: int
    name: str


# --------------------------------------------------------------------------
# config/decompiled.tsv
# --------------------------------------------------------------------------


def read_list(path: Path = LIST) -> list[Row]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != COLUMNS:
        raise ValueError(f"{path}:1: the header is not {chr(9).join(COLUMNS)!r}")
    rows = []
    for n, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != len(COLUMNS) or cols[1] not in (VERIFIED, LINK):
            raise ValueError(f"{path}:{n}: not a row of {', '.join(COLUMNS)}: {line!r}")
        rows.append(Row(cols[0], cols[1], int(cols[2], 16), int(cols[3]), cols[4]))
    return rows


def write_list(rows: list[Row], path: Path = LIST) -> None:
    out = ["\t".join(COLUMNS)]
    out += [f"{r.unit}\t{r.state}\t0x{r.address:08X}\t{r.size}\t{r.name}" for r in rows]
    path.write_bytes(("\n".join(out) + "\n").encode("utf-8"))


def measure(vendor: Path, dol: Path, out: Path) -> list[Row]:
    """Every function every unit defines and matches, or SystemExit saying why not.

    Run from the repository root, as tools/decomp.py is: units.txt's flags
    name ``-i include`` relative to it.
    """
    units = DC.read_units(UNITS)
    absent = DC.missing_compilers([(u.src, u.version, u.flags) for u in units], vendor)
    if absent:
        raise SystemExit(
            "compiler(s) missing, so the list would skip units: run "
            f"python tools/fetch_toolchain.py --versions {','.join(sorted(absent))}"
        )
    if not dol.exists():
        raise SystemExit(f"{dol} is missing: --measure compares against your dump")
    inventory = S.load_tsv(FUNCTIONS)
    index = MC.name_index(inventory, S.load_names(NAMES))
    out.mkdir(parents=True, exist_ok=True)

    rows: list[Row] = []
    for unit in units:
        obj, proc = DC.compile_unit(unit.src, unit.version, unit.flags, vendor, out)
        if proc.returncode != 0:
            raise SystemExit(f"{unit.src}: compile failed\n{proc.stdout}{proc.stderr}")
        check = subprocess.run(
            [sys.executable, "tools/matchcheck.py", str(obj), "--dol", str(dol)],
            capture_output=True,
            text=True,
        )
        if check.returncode not in (MC.EXIT_OK, MC.EXIT_UNVERIFIED):
            raise SystemExit(f"{unit.src} does not match; python tools/decomp.py says how")
        state = VERIFIED if check.returncode == MC.EXIT_OK else LINK
        sections, symbols, _ = MC.read_elf(obj.read_bytes())
        for sym in symbols:
            if sym["type"] != MC.STT_FUNC or not MC.defined(sym, sections):
                continue
            addr = MC.resolve_address(sym["name"], inventory, index)
            if addr is not None:
                rows.append(
                    Row(unit.src.as_posix(), state, addr, inventory[addr]["size"], sym["name"])
                )
    return rows


# --------------------------------------------------------------------------
# the README section
# --------------------------------------------------------------------------


def read_splits(path: Path = SPLITS) -> list[tuple[str, list[tuple[int, int]]]]:
    """``[(split name, [(start, end), ...]), ...]`` in file order; the section table skipped."""
    out: list[tuple[str, list[tuple[int, int]]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line[0].isspace() and line.endswith(":") and line != "Sections:":
            out.append((line[:-1], []))
            continue
        m = re.search(r"start:(0x[0-9A-Fa-f]+)\s+end:(0x[0-9A-Fa-f]+)", line)
        if m and out:
            out[-1][1].append((int(m.group(1), 16), int(m.group(2), 16)))
    return out


def bar(done: int, total: int, width: int = 20) -> str:
    filled = round(width * done / total) if total else 0
    return "`" + "█" * filled + "░" * (width - filled) + "`"


def percent(done: int, total: int) -> str:
    if not total or not done:
        return "0%"
    if done == total:
        return "100%"
    return f"{100 * done / total:.2f}%"


def render(
    rows: list[Row],
    inventory: dict[int, dict],
    splits: list[tuple[str, list[tuple[int, int]]]],
    bindings: dict[int, str],
    native_units: set[str],
) -> str:
    """The README section, from its four inputs alone: nothing here reads a file."""
    done = {r.address: r.size for r in rows}
    total_fns = len(inventory)
    total_bytes = sum(row["size"] for row in inventory.values())
    done_bytes = sum(done.values())
    swapped = {a: done[a] for a in bindings if a in done}
    units = list(dict.fromkeys(r.unit for r in rows))

    out = [
        BEGIN,
        "",
        f"Every one of the game's **{total_fns:,} functions already runs natively**: the static",
        "recompiler translates the original PowerPC machine code into C. Decompilation is the",
        "slower second layer — rewriting functions as readable C that the original Metrowerks",
        "compiler turns back into exactly the bytes on the disc, checked word for word by",
        "`tools/decomp.py`. A decompiled function can then replace its recompiled twin in the",
        "port, be read and changed like any other source, and be built for any machine.",
        "",
        "| Layer | Functions | Code | Progress |",
        "|---|---:|---:|---|",
        f"| Recompiled to native code | {total_fns:,} of {total_fns:,} | {total_bytes:,} bytes "
        f"| {bar(1, 1)} 100% |",
        f"| Decompiled, matching byte for byte | {len(done):,} of {total_fns:,} "
        f"| {done_bytes:,} bytes | {bar(done_bytes, total_bytes)} "
        f"{percent(done_bytes, total_bytes)} |",
        "",
        f"{len(swapped):,} of the {len(done):,} decompiled functions ({sum(swapped.values()):,} "
        "bytes) already run in the port in place of their recompiled",
        "twins (`config/hle.txt`); the rest are proven matches whose recompiled twins, which do",
        "the same thing, still run. Progress is by code size, so one large function counts for",
        "more than many small ones. **By area** (the ranges in `config/GEAE8P/splits.txt`):",
        "",
        "| Area | Functions decompiled | Code decompiled | Progress |",
        "|---|---:|---:|---|",
    ]
    placed: set[int] = set()
    for split, ranges in sorted(splits, key=lambda s: min(lo for lo, _ in s[1]) if s[1] else 0):
        inside = [a for a in inventory if any(lo <= a < hi for lo, hi in ranges)]
        if not inside:
            continue
        placed.update(inside)
        area_bytes = sum(inventory[a]["size"] for a in inside)
        area_done = [a for a in inside if a in done]
        area_done_bytes = sum(done[a] for a in area_done)
        out.append(
            f"| {AREAS.get(split, f'`{split}`')} | {len(area_done):,} of {len(inside):,} "
            f"| {area_done_bytes:,} of {area_bytes:,} bytes "
            f"| {bar(area_done_bytes, area_bytes)} {percent(area_done_bytes, area_bytes)} |"
        )
    rest = [a for a in inventory if a not in placed]
    if rest:
        rest_bytes = sum(inventory[a]["size"] for a in rest)
        rest_done = sum(done[a] for a in rest if a in done)
        out.append(
            f"| Outside every split | {sum(a in done for a in rest):,} of {len(rest):,} "
            f"| {rest_done:,} of {rest_bytes:,} bytes "
            f"| {bar(rest_done, rest_bytes)} {percent(rest_done, rest_bytes)} |"
        )

    out += [
        "",
        f"<details><summary><b>The {len(units)} decompiled units</b>, each a source file "
        "in <code>src/</code></summary>",
        "",
        "| Unit | Functions | Bytes | Match | Native twin | Swapped in |",
        "|---|---:|---:|---|---|---:|",
    ]
    for unit in units:
        mine = {r.address: r for r in rows if r.unit == unit}
        state = next(iter(mine.values())).state
        out.append(
            f"| [`{unit}`]({unit}) | {len(mine)} | {sum(r.size for r in mine.values()):,} "
            f"| {'verified' if state == VERIFIED else 'link pending'} "
            f"| {'yes' if unit in native_units else '—'} "
            f"| {sum(a in bindings for a in mine) or '—'} |"
        )
    out += [
        "",
        "*verified*: every word compared, and identical. *link pending*: identical wherever it",
        "can be compared, but something in it — usually a word pointing at a global this",
        "project has no address for yet — only a link could settle. A *native twin* is also",
        "compiled for the PC, and *swapped in* counts its functions that `config/hle.txt` runs",
        "in place of the recompiled ones.",
        "",
        "</details>",
        "",
        END,
    ]
    return "\n".join(out)


def current_render(rows: list[Row]) -> str:
    return render(
        rows,
        S.load_tsv(FUNCTIONS),
        read_splits(),
        load_bindings(HLE),
        {u.src.as_posix() for u in DC.read_units(UNITS) if u.native},
    )


def splice(readme: str, section: str) -> str:
    """``readme`` with the text between the markers replaced; ValueError without them."""
    start, end = readme.find(BEGIN), readme.find(END)
    if start < 0 or end < start:
        raise ValueError(f"README.md has no {BEGIN!r} ... {END!r} section")
    return readme[:start] + section + readme[end + len(END) :]


def read_text_lf(path: Path) -> tuple[str, str]:
    """The file with ``\\n`` line ends, and the ending it really uses, to write back with."""
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), eol


# --------------------------------------------------------------------------
# --check
# --------------------------------------------------------------------------


def problems(rows: list[Row], readme: str) -> list[str]:
    """Why the committed list or README is stale; empty when both are current."""
    out = []
    listed = {r.unit for r in rows}
    named = {u.src.as_posix() for u in DC.read_units(UNITS)}
    for unit in sorted(named - listed):
        out.append(f"{unit} is in units.txt but not in config/decompiled.tsv")
    for unit in sorted(listed - named):
        out.append(f"{unit} is in config/decompiled.tsv but no longer in units.txt")
    inventory = S.load_tsv(FUNCTIONS)
    for r in rows:
        if inventory.get(r.address, {}).get("size") != r.size:
            out.append(f"{r.name} (0x{r.address:08X}): config/functions.tsv disagrees")
        src = ROOT / r.unit
        if src.exists() and not re.search(
            rf"\b{re.escape(r.name)}\b", src.read_text(encoding="utf-8")
        ):
            out.append(f"{r.name} is listed for {r.unit}, which no longer mentions it")
    if out:
        out.append("run: python tools/progress.py --measure")
        return out
    try:
        fresh = splice(readme, current_render(rows))
    except ValueError as e:
        return [str(e)]
    if fresh != readme:
        out.append("README.md's progress section is stale; run: python tools/progress.py")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--measure", action="store_true", help="rebuild the list, then the README")
    mode.add_argument("--check", action="store_true", help="change nothing; exit 1 if stale")
    ap.add_argument("--vendor", type=Path, default=Path("vendor/mwcc/GC"))
    ap.add_argument("--dol", type=Path, default=Path("extracted/sys/main.dol"))
    ap.add_argument("--out", type=Path, default=Path("build/src"))
    args = ap.parse_args(argv)

    readme, eol = read_text_lf(README)
    if args.check:
        found = problems(read_list(), readme)
        for message in found:
            print(message, file=sys.stderr)
        return 1 if found else 0

    if args.measure:
        os.chdir(ROOT)
        rows = measure(args.vendor, args.dol, args.out)
        write_list(rows)
    else:
        rows = read_list()
    updated = splice(readme, current_render(rows))
    if updated != readme:
        README.write_bytes(updated.replace("\n", eol).encode("utf-8"))
    print(
        f"{len(rows)} functions across {len({r.unit for r in rows})} units, "
        f"{sum(r.size for r in rows):,} bytes; README.md "
        + ("updated" if updated != readme else "already current")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
