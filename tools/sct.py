#!/usr/bin/env python3
"""Disassemble a field script (`/field/meNNNx.sct`), the bytecode each map runs.

    python tools/sct.py 103a                 # every entry of me103a.sct
    python tools/sct.py 103a M04100 me103aa19  # only these entries
    python tools/sct.py path/to/me103a.sct
    python tools/sct.py 103a --data D:/dumps/Skies.iso   # any extraction or image
    python tools/sct.py --story                # every script: flags set, maps warped to

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

A message (op 144, 0x8020A734) is a self-relative offset, masked to four
bytes, to an entry of its own, then one expression; a choice (op 155,
0x8020A338) is an expression, then the same offset to its options, then an
expression. The entry is op 9, which skips words to the first END
(0x801F60C4), then the text, NUL-padded to four bytes. The listing prints the
text at both ends. Opcodes with raw or
variable-length operands the table does not describe (23, 24, 25, 33 and 69
among them) can desynchronise a linear pass; when that happens the entry says
so rather than printing guesses.

Reads the disc, prints nothing but the script: the loose file when there is
one, else the script read through the data directory's `disc.iso` (the loose
tree is written only by `extract.py --files`). Opcode names come from
config/functions.tsv through the DOL's handler table when `sys/main.dol` is
there.
"""

import argparse
import csv
import re
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
    144: "MESSAGE",
    155: "CHOICE",
    210: "SHIPBATTLE",
}
OPERATORS = (
    ["<", "<=", ">", ">=", "==", "!=", "&", "|", "&&", "||", "=", "*", "/", "%", "+", "-"]
    + ["&", "|", "*", "/", "%", "+", "-"]  # 16-22: the handler table repeats seven
)
DEFAULT = 0x7F7FFFFF
# Words scptAnarize takes alone, as DEFAULT (801F616C-801F6190): a message's
# "no value" among them.
ALONE = (0x7FFFFFFF, 0x7FFFFFFE)
MESSAGE, CHOICE = 144, 155


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
    if _w(d, o) in ALONE or _w(d, o) == DEFAULT:
        return "DEF", o + 4
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


def _past_end(d: bytes, o: int) -> int:
    """The offset after the first END word from `o`, word by word, as op 9
    skips (0x801F60C4)."""
    while _w(d, o) != END:
        o += 4
    return o + 4


def _text(d: bytes, o: int) -> tuple[str, int] | None:
    """A message's text at `o`, shown short, and the offset past its padding;
    None where `o` holds an opcode or no NUL-ended text."""
    nul = d.find(b"\0", o, o + 4096)
    if nul <= o or _w(d, o) < OPCODES:
        return None
    text = d[o:nul].decode("latin1").replace("\x7f", " ")
    text = "".join(c if " " <= c < "\x7f" else "." for c in text)
    return (text if len(text) <= 60 else text[:57] + "..."), (nul + 4) & ~3


def disassemble(d: bytes, base: int, start: int, end: int, names: dict[int, str]) -> list[str]:
    """Lines for the code in [start, end), offsets relative to `base`."""
    out, o = [], start
    while o < end:
        at = o - base
        if end - o < 4:  # the last entry runs into the name pool, which need not end on a word
            out.append(f"{at:05x}  ... {end - o} byte(s)")
            break
        op = _w(d, o)
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
        elif op in (MESSAGE, CHOICE):  # (a choice's expression,) the text's entry, an expression
            if op == CHOICE:
                e, o = expression(d, o)
                args.append(f"({e})")
            at_text = o + (_rel(d, o) & ~3)
            o += 4
            e, o = expression(d, o)
            shown = _text(d, _past_end(d, at_text)) if _w(d, at_text) == 9 else None
            args.append(f"@{at_text - base:05x}" + (f' "{shown[0]}"' if shown else "") + f" ({e})")
        elif op == 9 and (shown := _text(d, _past_end(d, o))):
            # A message's own entry: op 9 skips its words, and the text follows.
            args.append(f'"{shown[0]}"')
            o = shown[1]
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


STORY_FLAGS = 1024  # 1024 up are the field's own: 1087 the event lock, 1856 up one map's
# Flags 1856-2047 are one map's temporaries, cleared on a load (story-flags.md): a requirement on
# one is that map's own business, not a step to take elsewhere (part G's walker aimed at 1858,
# which every town's loop sets).
MAP_TEMPORARIES = range(1856, 2048)
_WARP_NAME = re.compile(rb"me(\d{3}[a-z])\.sct\0", re.IGNORECASE)
# The world map at the letter B[6] gives when it loads: map 99 takes its
# letter from B[6] whatever a warp names (content-systems.md, map 99).
WORLD = "099@"


def _world(name: str, letter: str | None = None) -> str:
    """A warp's place: the world map at `letter` where the entry set B[6]
    before the warp, else at whatever B[6] holds then (WORLD)."""
    if name.startswith("099"):
        return "099" + letter if letter else WORLD
    return name


def _b6(d: bytes, o: int) -> str | None:
    """At `o`, SETB (B[6] k =), the words [5, B[6], 0x04000000, k as a float,
    =, END]: the world map's letter it gives; else None. a019d's 4005 sets it
    to 8 (099i) before its op 238, where a019a's 4001 leaves it as it is."""
    if (
        o + 24 <= len(d)
        and _w(d, o) == 5
        and _w(d, o + 4) == 0x10000006
        and _w(d, o + 8) == 0x04000000
        and _w(d, o + 16) == 10
        and _w(d, o + 20) == END
    ):
        v = struct.unpack(">f", d[o + 12 : o + 16])[0]
        if v == int(v) and 0 <= v < 26:
            return chr(ord("a") + int(v))
    return None


def story(d: bytes) -> dict[str, tuple[set[int], set[str]]]:
    """For each entry: the flags below STORY_FLAGS it sets and the maps it warps
    to, its own and those of every entry it CALLs, however deep.

    A raw scan, not the disassembly, so an opcode the disassembler cannot size
    (op 23's raw offset to a model's name, for one) hides nothing:
    FLAGSET n is the words [17, 0x04000000, n as a float, 29]; a WARP is [43,
    a self-relative offset to "meNNNx.sct"]; a CALL is [11, an offset] landing
    exactly on another entry's start. Op 238 (fn_802074B0) is the way back to
    the world map at a position: its fn_800C8E44 warps to "me099a.sct", and
    the world map, however named, loads at the letter B[6] gives: a warp to
    map 99 is to "099" and the letter of a SETB (B[6] k =) earlier in the same
    entry, else to WORLD, the letter B[6] holds then. What the scan cannot
    see is a flag set from an expression, and a walk off an island's edge
    onto the world map."""
    base, ents = entries(d)
    bounds = sorted({off for off, _ in ents} | {len(d) - base})
    starts: dict[int, str] = {}
    for off, name in ents:
        starts.setdefault(off, name)
    own: dict[str, tuple[set[int], set[str], set[str]]] = {}
    for off, name in ents:
        end = base + min(b for b in bounds if b > off)
        sets, warps, calls = own.setdefault(name, (set(), set(), set()))
        o = base + off
        letter = None
        while o + 8 <= end:
            w = _w(d, o)
            if w == 17 and o + 16 <= len(d) and _w(d, o + 4) == 0x04000000 and _w(d, o + 12) == END:
                v = struct.unpack(">f", d[o + 8 : o + 12])[0]
                if v == int(v) and 0 <= v < STORY_FLAGS:
                    sets.add(int(v))
            elif w == 5:
                letter = _b6(d, o) or letter
            elif w == 43:
                m = _WARP_NAME.match(d, o + 4 + _w(d, o + 4))
                if m:
                    warps.add(_world(m.group(1).decode("latin1").lower(), letter))
            elif w == 238 and _w(d, o + 4) >= 0x04000000:  # an operand follows, not data
                warps.add(_world("099a", letter))
            elif w == 11:
                target = starts.get(o + 4 + _rel(d, o + 4) - base)
                if target and target != name:
                    calls.add(target)
            o += 4
    out = {}
    for name in own:
        sets, warps, seen, todo = set(), set(), {name}, [name]
        while todo:
            s, w, c = own[todo.pop()]
            sets |= s
            warps |= w
            todo += [n for n in c - seen]
            seen |= c
        out[name] = (sets, warps)
    return out


def flags_set(d: bytes) -> set[int]:
    """Every flag a FLAGSET of a constant sets, anywhere in the script."""
    out = set()
    for o in range(0, len(d) - 15, 4):
        if _w(d, o) == 17 and _w(d, o + 4) == 0x04000000 and _w(d, o + 12) == END:
            v = struct.unpack(">f", d[o + 8 : o + 12])[0]
            if v == int(v) and 0 <= v < 27328:
                out.add(int(v))
    return out


def hooks(d: bytes) -> dict[int, tuple[set[int], set[str]]]:
    """The story flags set and the warps inside each `IF (FLAG[T] 1 ==)` block
    with T at STORY_FLAGS or above, the block's own and those of the entries it
    CALLs (`story`): what waits for a flag the field sets. On the world map
    these are where the ship's arrival takes the story on: me099f's loop warps
    to 243a, part C's first cutscene, once flag 1766 is set, which no script
    sets and a fldHakken object in a099f.mld carries (the ship sailing to it);
    me099i's calls me099ah03, which sets 352, part H's first, once 1781 is.
    The block is the words [0, flag T, 0x04000000, 1.0, ==, END, offset], and
    runs from after its offset to where the offset points."""
    base, ents = entries(d) if len(d) >= 12 else (0, [])
    starts: dict[int, str] = {}
    for off, name in ents:
        starts.setdefault(off, name)
    called: dict[str, tuple[set[int], set[str]]] | None = None
    out: dict[int, tuple[set[int], set[str]]] = {}
    for o in range(0, len(d) - 27, 4):
        w = struct.unpack(">7I", d[o : o + 28])
        if (
            w[0] != 0
            or not 0x20000000 <= w[1] < 0x40000000
            or w[2:6] != (0x04000000, 0x3F800000, 4, END)
        ):
            continue
        flag, end = w[1] & 0xFFFFFF, o + 24 + _rel(d, o + 24)
        if flag < STORY_FLAGS:
            continue
        sets, warps = set(), set()
        for q in range(o + 28, min(end, len(d) - 7), 4):
            if _w(d, q) == 43:
                m = _WARP_NAME.match(d, q + 4 + _w(d, q + 4))
                if m:
                    warps.add(_world(m.group(1).decode("latin1").lower()))
            elif _w(d, q) == 238 and _w(d, q + 4) >= 0x04000000:
                warps.add(WORLD)
            elif (
                _w(d, q) == 17
                and q + 16 <= len(d)
                and _w(d, q + 4) == 0x04000000
                and _w(d, q + 12) == END
            ):
                v = struct.unpack(">f", d[q + 8 : q + 12])[0]
                if v == int(v) and 0 <= v < STORY_FLAGS:
                    sets.add(int(v))
            elif _w(d, q) == 11:
                target = starts.get(q + 4 + _rel(d, q + 4) - base)
                if target:
                    called = called if called is not None else story(d)
                    sets |= called[target][0]
                    warps |= called[target][1]
        if sets or warps:
            got = out.setdefault(flag, (set(), set()))
            got[0].update(sets)
            got[1].update(warps)
    return out


def _warps_in(d: bytes, lo: int, hi: int) -> set[str]:
    """The places the words [lo, hi) warp to: WARP's name, map 99 and op 238
    as WORLD."""
    out = set()
    for q in range(lo, min(hi, len(d) - 7), 4):
        if _w(d, q) == 43:
            m = _WARP_NAME.match(d, q + 4 + _w(d, q + 4))
            if m:
                out.add(_world(m.group(1).decode("latin1").lower()))
        elif _w(d, q) == 238 and _w(d, q + 4) >= 0x04000000:
            out.add(WORLD)
    return out


def _flag_if(d: bytes, o: int) -> tuple[list[tuple[int, int]], int, int] | None:
    """At `o`, an IF whose condition is only `FLAG[n] v ==` terms, v 0 or 1,
    joined by `&&` (the words [0, flag, 0x04000000, v, ==, ... &&, ..., END,
    offset]): its terms (n, v) and its block [lo, hi); else None."""
    if _w(d, o) != 0:
        return None
    terms, q = [], o + 4
    while q + 16 <= len(d):
        t = _w(d, q)
        if t == END:
            break
        v = struct.unpack(">3I", d[q + 4 : q + 16])
        if (
            0x20000000 <= t < 0x40000000
            and v[0] == 0x04000000
            and v[1] in (0, 0x3F800000)
            and v[2] == 4
        ):
            terms.append((t & 0xFFFFFF, 1 if v[1] else 0))
            q += 16
        elif t == 8 and terms:
            q += 4
        else:
            return None
    if not terms or q + 8 > len(d) or _w(d, q) != END:
        return None
    return terms, q + 8, q + 4 + _rel(d, q + 4)


def requirements(d: bytes) -> dict[int, set[int]]:
    """For each story flag this script sets, the flags every place it sets it
    waits for, story or field: the `FLAG[g] 1 ==` terms of the IFs around the FLAGSET
    (`_flag_if`'s), and those around each CALL into the entry it is in, the
    callers' own taken too, however deep; an entry nothing calls waits for
    nothing. Only a flag every place waits on has them. a013b's 6113 calls
    the cutscene that sets 271 inside `IF (FLAG[272] 1 == FLAG[271] 0 ==
    &&)`, and its 6111 sets 272 only once 290 is set: part F's walker, which
    aims at the lowest flag still clear, spent 30,000 frames on each. a013a's
    loop plays the cutscene that sets 274 only once field flag 1610 is set,
    which a115a's 4000 sets."""
    base, ents = entries(d)
    bounds = sorted({off for off, _ in ents} | {len(d) - base})
    spans = [(base + off, base + min(b for b in bounds if b > off), name) for off, name in ents]
    starts = {base + off: name for off, name in reversed(ents)}
    blocks = []
    for o in range(base, len(d) - 8, 4):
        b = _flag_if(d, o)
        if b:
            need = {n for n, v in b[0] if v == 1 and n not in MAP_TEMPORARIES}
            if need:
                blocks.append((b[1], b[2], need))

    def around(p: int) -> set[int]:
        return set().union(*(need for lo, hi, need in blocks if lo <= p < hi))

    sites: list[tuple[int, str, set[int]]] = []
    callers: dict[str, list[tuple[str, set[int]]]] = {}
    for lo, hi, name in spans:
        for q in range(lo, min(hi, len(d) - 15), 4):
            w = struct.unpack(">4I", d[q : q + 16])
            if w[0] == 17 and w[1] == 0x04000000 and w[3] == END:
                v = struct.unpack(">f", d[q + 8 : q + 12])[0]
                if v == int(v) and 0 <= v < STORY_FLAGS:
                    sites.append((int(v), name, around(q)))
            elif w[0] == 11 and starts.get(q + 4 + _rel(d, q + 4)) not in (None, name):
                callers.setdefault(starts[q + 4 + _rel(d, q + 4)], []).append((name, around(q)))

    def entry_need(name: str, seen: frozenset[str]) -> set[int]:
        if name not in callers or name in seen:
            return set()
        each = [need | entry_need(c, seen | {name}) for c, need in callers[name]]
        return set.intersection(*each)

    out: dict[int, set[int]] = {}
    for flag in {f for f, _, _ in sites}:
        each = [need | entry_need(name, frozenset()) for f, name, need in sites if f == flag]
        need = set.intersection(*each) - {flag}
        if need:
            out[flag] = need
    return out


def gates(d: bytes) -> dict[str, tuple[set[int], set[str]]]:
    """The entries that open a block by setting a field flag it waits for, and
    the story flags and places that block sets and warps to.

    For each IF whose condition is only `FLAG[n] 1 ==` terms joined by `&&`
    (the words [0, flag, 0x04000000, 1.0, ==, ... &&, ..., END, offset]), each
    other entry of this script that sets one of its flags at STORY_FLAGS or
    above (FLAGSET, raw) sets and warps to what the block does: its own
    FLAGSETs and warps, and those of the entries it CALLs, however deep.
    me099h's landing 4008 warps to 112a once 1590, 1591 and 213 are set, and
    its glittering spots 4506 and 4516 set 1590 and 1591 (the Great Bird's
    Eyes); me112c's touch 6002 sets 1870 and starts a battle, after which
    the loop's block on 1870 calls the cutscene that sets 216. Part E's
    walker, knowing nothing of either, passed 215 and 216 over. A hook is the
    same with a flag no script sets."""
    base, ents = entries(d)
    bounds = sorted({off for off, _ in ents} | {len(d) - base})
    spans = [(off, min(b for b in bounds if b > off), name) for off, name in ents]
    setters: dict[int, set[str]] = {}
    for lo, hi, name in spans:
        for q in range(base + lo, min(base + hi, len(d) - 15), 4):
            w = struct.unpack(">4I", d[q : q + 16])
            if w[0] == 17 and w[1] == 0x04000000 and w[3] == END:
                f = struct.unpack(">f", d[q + 8 : q + 12])[0]
                if f == int(f) and STORY_FLAGS <= f < 0x1000000:
                    setters.setdefault(int(f), set()).add(name)
    starts = {off: name for off, name in reversed(ents)}
    told = story(d)
    out: dict[str, tuple[set[int], set[str]]] = {}
    for o in range(base, len(d) - 8, 4):
        b = _flag_if(d, o)
        field = [f for f, v in b[0] if v == 1 and f >= STORY_FLAGS and f in setters] if b else []
        if not field:
            continue
        lo, hi = b[1], min(b[2], len(d) - 15)
        warps, sets = _warps_in(d, lo, hi), set()
        for r in range(lo, hi, 4):
            w = struct.unpack(">4I", d[r : r + 16])
            if w[0] == 17 and w[1] == 0x04000000 and w[3] == END:
                v = struct.unpack(">f", d[r + 8 : r + 12])[0]
                if v == int(v) and 0 <= v < STORY_FLAGS:
                    sets.add(int(v))
            elif w[0] == 11 and starts.get(r + 4 + _rel(d, r + 4) - base) in told:
                s, ws = told[starts[r + 4 + _rel(d, r + 4) - base]]
                sets |= s
                warps |= ws
        here = next((name for lo, hi, name in spans if base + lo <= o < base + hi), None)
        for f in field if sets or warps else ():
            for name in setters[f] - {here}:
                got = out.setdefault(name, (set(), set()))
                got[0].update(sets)
                got[1].update(warps)
    return out


def _sets_of(d: bytes, flags: set[int]) -> dict[str, set[int]]:
    """The entries that set any of `flags` (FLAGSET, raw), each with those it
    sets, its own and through the entries it CALLs, however deep."""
    base, ents = entries(d)
    bounds = sorted({off for off, _ in ents} | {len(d) - base})
    starts = {base + off: name for off, name in reversed(ents)}
    own: dict[str, tuple[set[int], set[str]]] = {}
    for off, name in ents:
        sets, calls = own.setdefault(name, (set(), set()))
        hi = base + min(b for b in bounds if b > off)
        for q in range(base + off, min(hi, len(d) - 15), 4):
            w = struct.unpack(">4I", d[q : q + 16])
            if w[0] == 17 and w[1] == 0x04000000 and w[3] == END:
                v = struct.unpack(">f", d[q + 8 : q + 12])[0]
                if v == int(v) and int(v) in flags:
                    sets.add(int(v))
            elif w[0] == 11 and starts.get(q + 4 + _rel(d, q + 4)) not in (None, name):
                calls.add(starts[q + 4 + _rel(d, q + 4)])
    out = {}
    for name in own:
        sets, seen, todo = set(), {name}, [name]
        while todo:
            s, c = own[todo.pop()]
            sets |= s
            todo += [n for n in c - seen]
            seen |= c
        if sets:
            out[name] = sets
    return out


SYS15 = 0x5000000F  # sys[15], the map the party came from: map x 10 + its letter


def _sets_in(d: bytes, ranges, starts: dict[int, str], base: int, called) -> set[int]:
    """The story flags the words in `ranges` set: their FLAGSETs, and those of
    the entries they CALL (`called`, story's)."""
    out: set[int] = set()
    for lo, hi in ranges:
        for q in range(lo, min(hi, len(d) - 15), 4):
            w = _w(d, q)
            if w == 17 and _w(d, q + 4) == 0x04000000 and _w(d, q + 12) == END:
                v = struct.unpack(">f", d[q + 8 : q + 12])[0]
                if v == int(v) and 0 <= v < STORY_FLAGS:
                    out.add(int(v))
            elif w == 11:
                target = starts.get(q + 4 + _rel(d, q + 4) - base)
                if target:
                    out |= called[target][0]
    return out


def arrivals(d: bytes) -> tuple[dict[str, set[int]], set[int]]:
    """The story flags the map's loop sets only on an arrival from one place:
    its SWITCH (sys[15]) picks a case by the map the party came from, map times
    ten plus its letter (content-systems.md: 1233 is a123d), and a123b's loop
    plays the cutscene that sets 403 only on the arrival from a123d. Returns
    {the map came from: those flags} and the set of them, flags the loop sets
    in no other case and nowhere outside the switch. A case for a return from
    battle (10000), a load (20000) or none (the default) is no one arrival."""
    base, ents = entries(d)
    bounds = sorted({off for off, _ in ents} | {len(d) - base})
    starts: dict[int, str] = {}
    for off, entry in ents:
        starts.setdefault(off, entry)
    loop = next((off for off, entry in ents if entry == "loop"), None)
    if loop is None:
        return {}, set()
    lo, hi = base + loop, base + min(b for b in bounds if b > loop)
    called = story(d)
    per: dict[str, set[int]] = {}
    blocks = []
    o = lo
    while o + 16 <= hi:
        n = _w(d, o + 12)
        if _w(d, o) == 3 and _w(d, o + 4) == SYS15 and _w(d, o + 8) == END and 0 < n < 64:
            cases = [
                (_w(d, o + 16 + 8 * i), o + 20 + 8 * i + _rel(d, o + 20 + 8 * i)) for i in range(n)
            ]
            targets = sorted({t for _, t in cases})
            for v, t in cases:
                if v >= 10000 or not lo <= t < hi:
                    continue
                end = min([x for x in targets if x > t] or [hi])
                blocks.append((t, end))
                src = f"{v // 10:03d}{chr(ord('a') + v % 10)}"
                per.setdefault(src, set()).update(_sets_in(d, [(t, end)], starts, base, called))
            o += 16 + 8 * n
            continue
        o += 4
    outside, pos = [], lo
    for t, end in sorted(blocks):
        if t > pos:
            outside.append((pos, t))
        pos = max(pos, end)
    if pos < hi:
        outside.append((pos, hi))
    elsewhere = _sets_in(d, outside, starts, base, called)
    for src in per:
        elsewhere |= set().union(*(f for s, f in per.items() if s != src)) & per[src]
    only = set().union(*per.values()) - elsewhere if per else set()
    return {src: f & only for src, f in per.items() if f & only}, only


def game_started(d: bytes) -> set[str]:
    """The entries the game starts itself, by name: none of the script's
    CALLs lands on them, and they are not the loop, init, an M%05d volume's
    or a developer's test or debug entry. a127b's Fship (463) and Delocco
    (467) start as the Delphinus flies there."""
    base, ents = entries(d)
    starts = {off: name for off, name in ents}
    called = set()
    for o in range(base, len(d) - 7, 4):
        if _w(d, o) == 11:
            target = starts.get(o + 4 + _rel(d, o + 4) - base)
            if target:
                called.add(target)
    return {
        name
        for _, name in ents
        if name not in called
        and name not in ("loop", "init")
        and not re.fullmatch(r"M\d{5}", name)
        and not re.match(r"(test|debug)", name, re.IGNORECASE)
    }


def _hook_blocks(d: bytes, flags: set[int]) -> list[tuple[int, int]]:
    """The word ranges of the blocks `IF (FLAG[T] 1 ==)` with T in `flags`."""
    out = []
    for o in range(0, len(d) - 27, 4):
        w = struct.unpack(">7I", d[o : o + 28])
        if (
            w[0] == 0
            and 0x20000000 <= w[1] < 0x40000000
            and w[2:6] == (0x04000000, 0x3F800000, 4, END)
            and w[1] & 0xFFFFFF in flags
        ):
            out.append((o + 28, o + 24 + _rel(d, o + 24)))
    return out


def hook_conditions(d: bytes) -> dict[int, list[tuple[int, int]]]:
    """For each hook's flag, the flags its block then tests before anything
    else, `IF (FLAG[n] v == ...)`, as (n, v): me099l's loop warps to 205a once
    1782 is set only if 468 is set and 460 clear, and part J's walker set 1782
    with 468 still clear, for no warp."""
    out: dict[int, list[tuple[int, int]]] = {}
    for o in range(0, len(d) - 27, 4):
        w = struct.unpack(">7I", d[o : o + 28])
        if (
            w[0] != 0
            or not 0x20000000 <= w[1] < 0x40000000
            or w[2:6] != (0x04000000, 0x3F800000, 4, END)
        ):
            continue
        flag = w[1] & 0xFFFFFF
        inner = _flag_if(d, o + 28) if flag >= STORY_FLAGS else None
        if inner:
            out.setdefault(flag, []).extend(inner[0])
    return out


def bounces(d: bytes) -> set[str]:
    """The maps an arrival from which the loop sends straight back: a126c's
    loop, for the party come from a126b (1261), plays a scene and warps to
    a126b; only the way in from a126d leaves the party in a126c, where 454 is
    set. Each a case of the loop's SWITCH (sys[15]) whose words, or the
    entries they CALL, warp to the map the case is for."""
    base, ents = entries(d)
    bounds = sorted({off for off, _ in ents} | {len(d) - base})
    starts: dict[int, str] = {}
    for off, entry in ents:
        starts.setdefault(off, entry)
    loop = next((off for off, entry in ents if entry == "loop"), None)
    if loop is None:
        return set()
    lo, hi = base + loop, base + min(b for b in bounds if b > loop)
    called = story(d)
    out: set[str] = set()
    o = lo
    while o + 16 <= hi:
        n = _w(d, o + 12)
        if _w(d, o) == 3 and _w(d, o + 4) == SYS15 and _w(d, o + 8) == END and 0 < n < 64:
            cases = [
                (_w(d, o + 16 + 8 * i), o + 20 + 8 * i + _rel(d, o + 20 + 8 * i)) for i in range(n)
            ]
            targets = sorted({t for _, t in cases})
            for v, t in cases:
                if v >= 10000 or not lo <= t < hi:
                    continue
                end = min([x for x in targets if x > t] or [hi])
                src = f"{v // 10:03d}{chr(ord('a') + v % 10)}"
                warps = _warps_in(d, t, end)
                for q in range(t, min(end, len(d) - 7), 4):
                    if _w(d, q) == 11:
                        target = starts.get(q + 4 + _rel(d, q + 4) - base)
                        if target:
                            warps |= called[target][1]
                if src in warps:
                    out.add(src)
            o += 16 + 8 * n
            continue
        o += 4
    return out


def story_lines(
    name: str,
    d: bytes,
    unset: set[int] | None = None,
    needed: set[int] | frozenset[int] = frozenset(),
) -> list[str]:
    """`story` as text, one entry a line, for the entries that set or warp:
    `004a M03005 w250a`. The lab's walker reads these (reach.md U4). With
    `unset`, the flags no script sets, each hook on one of them is a line too,
    named for its flag: `099f hook1766 w243a`, `099i hook1781 s352`, with the
    flags its block then tests, set (r) or clear (x): `099l hook1782 w205a
    r468 x460`. An entry the game starts by name (`game_started`) ends in g:
    `127b Fship s463 g`. An entry that opens a block by
    setting the field flag it waits for (`gates`) sets and warps as it does.
    And for each flag every place here sets only once others are set, a line
    naming them (`requirements`): `013b req271 r272`. With `needed`, the
    field flags requirements name, an entry that sets one sets it on its line
    too: `115a M04000 s1610`. A flag the loop sets only on an arrival from
    one map (`arrivals`) is that map's, on a line naming where the arrival is
    to: `123d via123b s403`; the loop and the cutscenes here, which the walker
    cannot start, do not say they set it. An arrival the loop sends straight
    back (`bounces`) says so on that line: `126b via126c w126b`."""
    lines = []
    opens = gates(d)
    field = _sets_of(d, set(needed)) if needed else {}
    via, only = arrivals(d)
    game = game_started(d)
    hooked = hooks(d)
    held = {f for f in hooked if unset is not None and f in unset}
    for entry, (sets, warps) in story(d).items():
        more = opens.get(entry, (set(), set()))
        sets, warps = sets | more[0] | field.get(entry, set()), warps | more[1]
        if entry == "loop" and held:
            # A warp the loop makes only inside a hook's block is the hook's,
            # on the hook's line with what the block then tests: me099l's
            # loop warps to 205a past 1782 only once 468 is set, and its line
            # saying w205a made every map two warps from 205a for part J's
            # walker before 468.
            base, ents = entries(d)
            bounds = sorted({off for off, _ in ents} | {len(d) - base})
            off = next(o for o, e in ents if e == "loop")
            lo, hi = base + off, base + min(b for b in bounds if b > off)
            blocks = sorted(_hook_blocks(d, held))
            outside, pos = [], lo
            for b_lo, b_hi in blocks:
                if b_lo > pos and b_lo < hi:
                    outside.append((pos, b_lo))
                pos = max(pos, b_hi)
            if pos < hi:
                outside.append((pos, hi))
            own = set().union(*(_warps_in(d, a, b) for a, b in outside)) if outside else set()
            warps = warps - (set().union(*(hooked[f][1] for f in held)) - own)
        if not re.fullmatch(r"M\d{5}", entry):
            sets = sets - only
        if sets or warps:
            words = [f"s{f}" for f in sorted(sets)] + [f"w{m}" for m in sorted(warps)]
            words += ["g"] if entry in game else []
            lines.append(f"{name} {entry} {' '.join(words)}")
    conds = hook_conditions(d)
    for flag, (sets, warps) in sorted(hooks(d).items()) if unset is not None else ():
        if flag in unset:
            words = [f"s{f}" for f in sorted(sets)] + [f"w{m}" for m in sorted(warps)]
            words += [f"{'r' if v else 'x'}{n}" for n, v in conds.get(flag, [])]
            lines.append(f"{name} hook{flag} {' '.join(words)}")
    for flag, need in sorted(requirements(d).items()):
        lines.append(f"{name} req{flag} {' '.join(f'r{g}' for g in sorted(need))}")
    back = bounces(d)
    for src in sorted(set(via) | back):
        words = [f"s{f}" for f in sorted(via.get(src, ()))] + ([f"w{src}"] if src in back else [])
        lines.append(f"{src} via{name} {' '.join(words)}")
    return lines


def story_index(data: Path) -> list[str]:
    """story_lines for every field script under `data`, in map order, with the
    hooks on flags that no script sets."""
    with disc.open_data(data) as src:
        scripts = sorted(
            (q.lower()[8:12], aklz.decompress(src.read_path(q)))
            for q in src.paths()
            if re.fullmatch(r"field/me\d{3}[a-z]\.sct", q.lower())
        )
    anywhere = set().union(*(flags_set(d) for _, d in scripts))
    unset = set(range(STORY_FLAGS, 27328)) - anywhere
    needed = {
        g for _, d in scripts for need in requirements(d).values() for g in need if g >= STORY_FLAGS
    }
    return [line for name, d in scripts for line in story_lines(name, d, unset, needed)]


def load(script: str, data: Path) -> bytes:
    """The raw (still compressed) script: a path as given, else a map name
    looked up under the data directory or in its image."""
    path = Path(script)
    if path.suffix.lower() == ".sct" or len(path.parts) > 1:
        return disc.read_data_path(path)
    return disc.read_data_file(data, f"field/me{script.lower()}.sct")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("script", nargs="?", help="a map like 103a, or a path to a .sct")
    p.add_argument("entry", nargs="*", help="only these entries")
    p.add_argument(
        "--data",
        type=Path,
        default=ROOT / "extracted",
        help="the extraction (or disc image) a map name is looked up in",
    )
    p.add_argument(
        "--story",
        action="store_true",
        help="print each entry's flags set and maps warped to (story_lines), of "
        "this script or, with none named, of every field script",
    )
    a = p.parse_args(argv)
    if a.story and not a.script:
        for line in story_index(a.data):
            print(line)
        return 0
    if not a.script:
        p.error("name a script, or give --story for every one")
    try:
        raw = load(a.script, a.data)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    d = aklz.decompress(raw)
    if a.story:
        name = Path(a.script).stem.lower().removeprefix("me")
        for line in story_lines(name, d):
            print(line)
        return 0
    beside = a.data if a.data.is_dir() else a.data.parent
    names = opcode_names(beside / "sys" / "main.dol")
    for name, off, end, lines in script(d, a.entry, names):
        print(f"==== {name} @{off:05x}..{end:05x}")
        for line in lines:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
