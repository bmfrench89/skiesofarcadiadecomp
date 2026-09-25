#!/usr/bin/env python3
"""Disassemble a field script (`/field/meNNNx.sct`), the bytecode each map runs.

    python tools/sct.py 103a                 # every entry of me103a.sct
    python tools/sct.py 103a M04100 me103aa19  # only these entries
    python tools/sct.py path/to/me103a.sct
    python tools/sct.py 103a --data D:/dumps/Skies.iso   # any extraction or image

A map's script decides what the map does -- which event plays, where the camera
and the party go, which exit warps where -- and it decides from story flags.
`a200a` drew black on 2026-09-22 because its loop does nothing once flag 2 is
set, which took a day to find by rendering and would have taken a minute by
reading. docs/research/story-flags.md has the format and the interpreter.

The file is AKLZ-compressed and big-endian: `u32, u32, u32 count`, then `count`
entries of `(u32 offset, char name[16])`, then code at `12 + 20 * count`. Each
instruction is an opcode word (0..265; the handler table is at 0x802F7940, 12
bytes an entry) and operands. Operands are RPN expressions ended by token 29
(`scptAnarize`, 0x801F6120): tokens below 23 are operators; 0x04000000 is
followed by a float; 0x08.. is fixed-point, 0x1.. a byte variable B[n], 0x2..
and 0x3.. flag n, 0x4.. a float variable, 0x5.. a system variable.

Opcodes with raw or variable-length operands the table does not describe (23,
24, 25, 33, 69, 144 among them) can desynchronise a linear pass; when that
happens the entry says so rather than printing guesses.

Reads the disc, prints nothing but the script: the loose file when there is
one, else the script read through the data directory's `disc.iso` (the loose
tree is written only by `extract.py --files`). Opcode names come from
config/functions.tsv through the DOL's handler table when `sys/main.dol` is
there.
"""

import argparse
import csv
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from soa import aklz, disc  # noqa: E402

OPCODE_TABLE = 0x802F7940
OPCODES = 266
END = 29  # ends an expression
NAMED = {
    0: "IF",
    3: "SWITCH",
    5: "SETB",
    6: "SETI",
    7: "SETF",
    9: "EVAL",
    10: "GOTO",
    11: "CALL",
    12: "RET",
    15: "OP15",
    16: "WAIT?",
    17: "FLAGSET",
    18: "FLAGCLR",
    19: "FLAGTOG",
    20: "ITEMADD",
    21: "ITEMDEL",
    22: "YIELD",
    43: "WARP",
    112: "BATTLE",
    138: "SAVEPOINT",
    157: "JOIN",
    158: "LEAVE",
    210: "SHIPBATTLE",
}
OPERATORS = (
    ["<", "<=", ">", ">=", "==", "!=", "&", "|", "&&", "||", "=", "*", "/", "%", "+", "-"]
    + ["&", "|", "*", "/", "%", "+", "-"]  # 16-22: the handler table repeats seven
)
DEFAULT = 0x7F7FFFFF


def opcode_names(dol_path: Path | None = None) -> dict[int, str]:
    """NAMED, completed from the DOL's handler table where there is one."""
    names = dict(NAMED)
    dol_path = dol_path or ROOT / "extracted" / "sys" / "main.dol"
    tsv = ROOT / "config" / "functions.tsv"
    if not dol_path.exists() or not tsv.exists():
        return names
    from soa.dol import parse

    dol = parse(dol_path.read_bytes())
    funcs = {int(r["address"], 16): r["name"] for r in csv.DictReader(tsv.open(), delimiter="\t")}
    for i in range(OPCODES):
        handler = struct.unpack(">I", dol.read(OPCODE_TABLE + i * 12 + 8, 4))[0]
        names.setdefault(i, funcs.get(handler, f"0x{handler:08X}"))
    return names


def _w(d: bytes, o: int) -> int:
    return struct.unpack(">I", d[o : o + 4])[0]


def _rel(d: bytes, o: int) -> int:
    """A branch offset: signed, since a loop jumps backwards. Read unsigned it
    printed 04cc0's GOTO in me103a as -> 100004c90."""
    return struct.unpack(">i", d[o : o + 4])[0]


def operand(t: int) -> str:
    if t >= 0x50000000:
        return f"sys[{t & 0xFFFFFF}]"
    if t >= 0x40000000:
        return f"fvar[{t & 0xFFFFFF}]"
    if t >= 0x20000000:
        return f"FLAG[{t & 0xFFFFFF}]"
    if t >= 0x10000000:
        return f"B[{t & 0xFFFFFF}]"
    if t >= 0x08000000:
        return f"fix({t:x})"
    return f"?{t:x}"


def expression(d: bytes, o: int) -> tuple[str, int]:
    """One RPN expression from `o`, as text, and the offset after its END."""
    toks = []
    while True:
        t = _w(d, o)
        o += 4
        if t == END:
            return " ".join(toks), o
        if t < len(OPERATORS):
            toks.append(OPERATORS[t])
        elif t >= 0x08000000:
            toks.append(operand(t))
        elif t >= 0x04000000:
            toks.append(f"{struct.unpack('>f', d[o : o + 4])[0]:g}")
            o += 4
        else:
            toks.append(f"?{t:x}")


def entries(d: bytes) -> tuple[int, list[tuple[int, str]]]:
    """The code base and (offset, name) for every entry, in file order."""
    n = _w(d, 8)
    ents = [
        (_w(d, 12 + i * 20), d[16 + i * 20 : 32 + i * 20].split(b"\0")[0].decode("latin1"))
        for i in range(n)
    ]
    return 12 + n * 20, ents


def disassemble(d: bytes, base: int, start: int, end: int, names: dict[int, str]) -> list[str]:
    """Lines for the code in [start, end), offsets relative to `base`."""
    out, o = [], start
    while o < end:
        at, op = o - base, _w(d, o)
        o += 4
        if op >= OPCODES:
            out.append(f"{at:05x}  ??? {op:08x}")
            continue
        args = []
        if op == 43:  # WARP: a self-relative offset to the destination's name
            sa = o + _w(d, o)
            name = d[sa : d.index(b"\0", sa)].decode("latin1")
            args.append(f'"{name}"')
            o += 4
        elif op in (10, 11):  # GOTO, CALL
            args.append(f"-> {o - base + _rel(d, o):05x}")
            o += 4
        elif op == 0:  # IF expr, else-offset
            e, o = expression(d, o)
            args.append(f"({e}) else-> {o - base + _rel(d, o):05x}")
            o += 4
        elif op == 3:  # SWITCH expr, count, (value, offset) pairs
            e, o = expression(d, o)
            n = _w(d, o)
            o += 4
            if n > 64:
                raise ValueError(f"switch at {at:05x} claims {n} cases")
            cases = []
            for _ in range(n):
                v, off = _w(d, o), _rel(d, o + 4)
                target = o + 4 - base + off
                cases.append(f"default->{target:05x}" if v == 0xFFFFFFFF else f"{v}->{target:05x}")
                o += 8
            args.append(f"({e}) " + " ".join(cases))
        elif op not in (12, 15, 22):  # everything else: expressions until a non-operand word
            while o < end:
                t = _w(d, o)
                if t == DEFAULT:
                    args.append("DEF")
                    o += 4
                elif t >= 0x04000000:
                    e, o = expression(d, o)
                    args.append(f"({e})")
                else:
                    break
        out.append(f"{at:05x}  [{op}]{names.get(op, '')} {' '.join(args)}".rstrip())
    return out


def script(d: bytes, want: list[str] | None = None, names: dict[int, str] | None = None):
    """(name, offset, end, lines) for each entry of a decompressed script."""
    names = names if names is not None else dict(NAMED)
    base, ents = entries(d)
    bounds = sorted({off for off, _ in ents} | {len(d) - base})
    for off, name in ents:
        if want and name not in want:
            continue
        end = min(b for b in bounds if b > off)
        try:
            lines = disassemble(d, base, base + off, base + end, names)
        except (ValueError, IndexError, struct.error) as e:
            lines = [f"!! desynchronised: {e}"]
        yield name, off, end, lines


def load(script: str, data: Path) -> bytes:
    """The raw (still compressed) script: a path as given, else a map name
    looked up under the data directory or in its image."""
    path = Path(script)
    if path.suffix.lower() == ".sct" or len(path.parts) > 1:
        return disc.read_data_path(path)
    return disc.read_data_file(data, f"field/me{script.lower()}.sct")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("script", help="a map like 103a, or a path to a .sct")
    p.add_argument("entry", nargs="*", help="only these entries")
    p.add_argument(
        "--data",
        type=Path,
        default=ROOT / "extracted",
        help="the extraction (or disc image) a map name is looked up in",
    )
    a = p.parse_args(argv)
    try:
        raw = load(a.script, a.data)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    d = aklz.decompress(raw)
    beside = a.data if a.data.is_dir() else a.data.parent
    names = opcode_names(beside / "sys" / "main.dol")
    for name, off, end, lines in script(d, a.entry, names):
        print(f"==== {name} @{off:05x}..{end:05x}")
        for line in lines:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
