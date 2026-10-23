"""The game's data, by name (T9, docs/specs/game-names.md).

``config/gamedata.txt`` holds a name a line -- its address, its type, and
``ref``, the address of an instruction in the DOL that reaches it -- and the
records that sit behind an address. This module reads it, says which address an
instruction reaches (``reach``), finds the instructions that reach an address
(``find``), holds every line to the DOL (``verify``), and writes what is made
from the file: the C header mods include, the table the runtime resolves
``patches.txt`` names through, and the reference a person reads.

An instruction reaches an address one of two ways here, the two CodeWarrior
emits for game data: a D-form access or ``addi`` off r13 or r2 (small data,
whose bases ``__init_registers`` sets), or off a register a ``lis`` set within
the instructions before it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "gamedata.txt"

SCALARS = {"u8": 1, "s8": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4, "f32": 4, "ptr": 4}

# D-form loads and stores, and addi: what an instruction's displacement means.
D_FORMS = {
    32: "lwz", 33: "lwzu", 34: "lbz", 35: "lbzu", 36: "stw", 37: "stwu", 38: "stb", 39: "stbu",
    40: "lhz", 41: "lhzu", 42: "lha", 43: "lhau", 44: "sth", 45: "sthu", 46: "lmw", 47: "stmw",
    48: "lfs", 49: "lfsu", 50: "lfd", 51: "lfdu", 52: "stfs", 53: "stfsu", 54: "stfd", 55: "stfdu",
    14: "addi",
}  # fmt: skip
LOADS_RD = {32, 33, 34, 35, 40, 41, 42, 43, 46, 14, 15}  # write rD (bits 21-25)
UPDATES = {33, 35, 37, 39, 41, 43, 45, 49, 51, 53, 55}  # write rA too


@dataclass
class Field:
    name: str
    offset: int
    type: str
    ref: int | None
    line: int


@dataclass
class Record:
    name: str
    size: int
    fields: list[Field] = field(default_factory=list)
    line: int = 0


@dataclass
class Entry:
    name: str
    address: int
    type: str
    ref: int
    evidence: str
    line: int
    ref_off: int = 0  # REF+OFF: the instruction reaches the address less OFF, a block's base

    @property
    def pointee(self) -> str | None:
        """``ptr:RECORD``'s record."""
        return self.type[4:].split("[")[0] if self.type.startswith("ptr:") else None

    def pointee_count(self) -> int:
        """``ptr:RECORD[N]``'s N, 0 for one record."""
        if not self.type.startswith("ptr:") or "[" not in self.type:
            return 0
        return int(self.type.split("[")[1].rstrip("]"))

    def array(self) -> tuple[str, int] | None:
        """``ELEM[N]``'s element type and count."""
        m = re.fullmatch(r"([a-z_0-9]+)\[(\d+)\]", self.type)
        return (m.group(1), int(m.group(2))) if m else None


@dataclass
class GameData:
    entries: list[Entry]
    records: dict[str, Record]

    def by_name(self) -> dict[str, Entry]:
        return {e.name: e for e in self.entries}


class GameDataError(ValueError):
    pass


def _int(text: str, line: int, what: str) -> int:
    try:
        return int(text, 0)
    except ValueError:
        raise GameDataError(f"gamedata.txt:{line}: {what} {text!r} is not a number") from None


def parse(text: str) -> GameData:
    """The file's grammar, every name and type known, every record's fields
    inside it. Refuses the first fault with its line."""
    entries: list[Entry] = []
    records: dict[str, Record] = {}
    current: Record | None = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        words = line.split()
        if words[0] == "record":
            if len(words) != 3:
                raise GameDataError(f"gamedata.txt:{n}: a record is 'record NAME SIZE'")
            if words[1] in records:
                raise GameDataError(f"gamedata.txt:{n}: record {words[1]} twice")
            current = Record(words[1], _int(words[2], n, "size"), line=n)
            records[current.name] = current
            continue
        if raw[:1].isspace():
            if current is None:
                raise GameDataError(f"gamedata.txt:{n}: a field outside any record")
            if len(words) not in (3, 4):
                raise GameDataError(f"gamedata.txt:{n}: a field is 'NAME OFFSET TYPE [REF]'")
            ref = _int(words[3], n, "ref") if len(words) == 4 else None
            current.fields.append(Field(words[0], _int(words[1], n, "offset"), words[2], ref, n))
            continue
        current = None
        if len(words) < 5:
            raise GameDataError(f"gamedata.txt:{n}: a name is 'NAME ADDRESS TYPE REF EVIDENCE'")
        if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*", words[0]):
            raise GameDataError(
                f"gamedata.txt:{n}: {words[0]!r} is not a name (lower case, dots between words)"
            )
        if not re.fullmatch(r"0x[0-9A-F]{8}", words[1]):
            raise GameDataError(
                f"gamedata.txt:{n}: an address is 0x and eight upper-case hex digits"
            )
        ref, _, off = words[3].partition("+")
        entries.append(
            Entry(
                words[0],
                int(words[1], 16),
                words[2],
                _int(ref, n, "ref"),
                " ".join(words[4:]),
                n,
                _int(off, n, "ref offset") if off else 0,
            )
        )
    data = GameData(entries, records)
    _check(data)
    return data


def type_size(t: str, records: dict[str, Record]) -> int:
    if t in SCALARS:
        return SCALARS[t]
    if t.startswith("ptr:"):
        return 4
    if t.startswith("bytes[") and t.endswith("]"):
        return int(t[6:-1])
    m = re.fullmatch(r"([a-z_0-9]+)\[(\d+)\]", t)
    if m:
        return type_size(m.group(1), records) * int(m.group(2))
    if t.startswith("bytes[") and t.endswith("]"):
        return int(t[6:-1])
    if t in records:
        return records[t].size
    raise KeyError(t)


def _check(data: GameData) -> None:
    seen: set[str] = set()
    for r in data.records.values():
        names: set[str] = set()
        for f in r.fields:
            if f.name in names:
                raise GameDataError(f"gamedata.txt:{f.line}: field {f.name} twice in {r.name}")
            names.add(f.name)
            try:
                size = type_size(f.type, data.records)
            except KeyError:
                raise GameDataError(f"gamedata.txt:{f.line}: {f.type!r} is not a type") from None
            if f.offset < 0 or f.offset + size > r.size:
                raise GameDataError(
                    f"gamedata.txt:{f.line}: {f.name} runs outside {r.name}'s {r.size} bytes"
                )
    for e in data.entries:
        if e.name in seen:
            raise GameDataError(f"gamedata.txt:{e.line}: {e.name} twice")
        seen.add(e.name)
        try:
            type_size(e.type, data.records)
        except KeyError:
            raise GameDataError(f"gamedata.txt:{e.line}: {e.type!r} is not a type") from None
        if e.pointee and e.pointee not in data.records:
            raise GameDataError(f"gamedata.txt:{e.line}: no record {e.pointee}")
        width = SCALARS.get(e.type, 0)
        if width and e.address % width:
            raise GameDataError(
                f"gamedata.txt:{e.line}: {e.name} is not aligned to its {width} bytes"
            )


def load(path: Path = CONFIG) -> GameData:
    return parse(path.read_text(encoding="utf-8"))


# ---- what an instruction reaches -----------------------------------------


def _simm(word: int) -> int:
    return ((word & 0xFFFF) ^ 0x8000) - 0x8000


def _writes(word: int, reg: int) -> bool:
    """Whether the instruction may leave `reg` holding something else. Errs
    toward yes: a pair it cannot see through is no proof."""
    op, rd, ra = word >> 26, (word >> 21) & 31, (word >> 16) & 31
    if op in LOADS_RD and rd == reg:
        return True
    if op in UPDATES and ra == reg:
        return True
    if (
        op in (24, 25, 26, 27, 28, 29, 20, 21, 23) and ra == reg
    ):  # ori, oris, xori, xoris, andi., andis., rlw*
        return True
    if op in (7, 8, 10, 11, 12, 13) and rd == reg:  # mulli, subfic, cmpli/cmpi (no), addic, addic.
        return op not in (10, 11)
    if op == 31:
        xo = (word >> 1) & 0x3FF
        logical = xo in (
            28,
            60,
            124,
            284,
            316,
            412,
            444,
            476,
            24,
            536,
            792,
            824,
            26,
            922,
            954,
            0x358,
        )
        if logical and ra == reg:
            return True
        if (
            not logical
            and rd == reg
            and xo not in (0, 32, 151, 183, 215, 247, 407, 439, 662, 918, 150, 86, 54, 278)
        ):
            return True
    return op in (16, 18, 19)  # a branch: the block before it is another path


def reach(dol, ref: int, sda: dict[int, int], back: int = 32) -> int | None:
    """The address the instruction at `ref` reaches, or None: a D-form access
    or addi off r13 or r2, or off a register a lis set within `back`
    instructions before it with nothing between that changes it."""
    try:
        word = dol.word(ref)
    except ValueError:
        return None
    op, ra = word >> 26, (word >> 16) & 31
    if op not in D_FORMS:
        return None
    if ra in (2, 13) and ra in sda:
        return (sda[ra] + _simm(word)) & 0xFFFFFFFF
    if ra == 0:
        return None
    for i in range(1, back + 1):
        try:
            prev = dol.word(ref - 4 * i)
        except ValueError:
            return None
        if prev >> 26 == 15 and (prev >> 21) & 31 == ra and (prev >> 16) & 31 == 0:  # lis ra, hi
            return (((prev & 0xFFFF) << 16) + _simm(word)) & 0xFFFFFFFF
        if _writes(prev, ra):
            return None
    return None


def find(dol, address: int, sda: dict[int, int]) -> list[int]:
    """Every instruction in the DOL's code that reaches `address` exactly."""
    out = []
    for sec in dol.text:
        for at in range(sec.address, sec.end, 4):
            word = dol.word(at)
            if word >> 26 in D_FORMS and reach(dol, at, sda) == address:
                out.append(at)
    return out


def displacement(dol, ref: int) -> int | None:
    try:
        word = dol.word(ref)
    except ValueError:
        return None
    return _simm(word) if word >> 26 in D_FORMS else None


def verify(
    data: GameData, dol, sda: dict[int, int], objects: list[tuple[int, int]] | None = None
) -> list[str]:
    """Every line held to the DOL: each ref reaches its name's address, each
    field ref carries its offset modulo the record's size, and -- given the
    data objects of symbols.txt as (address, size) -- each name lies inside one
    big enough for its type. The faults, each naming its line."""
    faults = []
    for e in data.entries:
        got = reach(dol, e.ref, sda)
        if got is None or got + e.ref_off != e.address:
            seen = f"0x{got:08X}" if got is not None else "nothing it can see"
            want = f"0x{e.address - e.ref_off:08X}"
            if e.ref_off:
                want += f" (0x{e.address:08X} less {e.ref_off})"
            faults.append(
                f"gamedata.txt:{e.line}: {e.name}: the instruction at 0x{e.ref:08X} reaches {seen}, not {want}"
            )
        if objects is not None:
            size = type_size(e.type, data.records)
            inside = [(a, s) for a, s in objects if a <= e.address < a + max(s, 1)]
            if not inside:
                faults.append(
                    f"gamedata.txt:{e.line}: {e.name}: 0x{e.address:08X} is in no data object of symbols.txt"
                )
            elif all(e.address + size > a + s for a, s in inside):
                faults.append(
                    f"gamedata.txt:{e.line}: {e.name}: its {size} bytes run past every object holding it"
                )
    for r in data.records.values():
        for f in r.fields:
            if f.ref is None:
                continue
            d = displacement(dol, f.ref)
            if d is None or d % r.size != f.offset % r.size:
                faults.append(
                    f"gamedata.txt:{f.line}: {r.name}.{f.name}: the instruction at 0x{f.ref:08X} "
                    f"has displacement {d}, not {f.offset} (modulo {r.size})"
                )
    return faults


def data_objects(symbols_text: str) -> list[tuple[int, int]]:
    """symbols.txt's data objects, (address, size)."""
    out = []
    for m in re.finditer(
        r"= \.[a-z0-9]+:0x([0-9A-Fa-f]{8}); // type:object size:0x([0-9A-Fa-f]+)", symbols_text
    ):
        out.append((int(m.group(1), 16), int(m.group(2), 16)))
    return out


# ---- what is made from it --------------------------------------------------


def c_ident(name: str) -> str:
    return name.replace(".", "_")


def _read_write(t: str) -> tuple[str, str, str]:
    """The C type, and the API's read and write, for a scalar type."""
    return {
        "u8": ("uint8_t", "read8", "write8"),
        "s8": ("int8_t", "read8", "write8"),
        "u16": ("uint16_t", "read16", "write16"),
        "s16": ("int16_t", "read16", "write16"),
        "u32": ("uint32_t", "read32", "write32"),
        "s32": ("int32_t", "read32", "write32"),
        "ptr": ("uint32_t", "read32", "write32"),
        "f32": ("float", "read_f32", "write_f32"),
    }[t if not t.startswith("ptr:") else "ptr"]


def resolvable(data: GameData) -> list[tuple[str, int, int, int, str, bool]]:
    """Every form a patch or an accessor can name, flattened: (path, base,
    stride, offset, scalar type, through a pointer). `path` has `[]` where an
    index goes."""
    out = []
    for e in data.entries:
        arr = e.array()
        if e.type in SCALARS or e.pointee:
            out.append((e.name, e.address, 0, 0, "ptr" if e.pointee else e.type, False))
        if e.pointee:
            rec = data.records[e.pointee]
            many = e.pointee_count() > 0
            for f in rec.fields:
                if f.type in SCALARS:
                    path = f"{e.name}[].{f.name}" if many else f"{e.name}.{f.name}"
                    out.append((path, e.address, rec.size if many else 0, f.offset, f.type, True))
        if arr:
            elem, _count = arr
            if elem in SCALARS:
                out.append((f"{e.name}[]", e.address, SCALARS[elem], 0, elem, False))
            elif elem in data.records:
                rec = data.records[elem]
                for f in rec.fields:
                    if f.type in SCALARS:
                        out.append(
                            (f"{e.name}[].{f.name}", e.address, rec.size, f.offset, f.type, False)
                        )
        if e.type in data.records:
            for f in data.records[e.type].fields:
                if f.type in SCALARS:
                    out.append((f"{e.name}.{f.name}", e.address, 0, f.offset, f.type, False))
    return out


HEADER_TOP = """/* Generated from config/gamedata.txt by tools/gamedata.py; do not edit.
 *
 * The game's data by name (T9, docs/specs/game-names.md), each address proved
 * against the instruction in the DOL that reaches it. Accessors go through the
 * mod API's big-endian reads and writes and return what they do: 1, or 0 when
 * the address is refused. A name behind a pointer follows the pointer first.
 * Include after soa_mod.h. */
#ifndef SOA_GAMEDATA_H
#define SOA_GAMEDATA_H

"""


def header(data: GameData) -> str:
    out = [HEADER_TOP]
    for e in data.entries:
        out.append(f"#define SOA_{c_ident(e.name).upper()} 0x{e.address:08X}u /* {e.type} */\n")
    out.append("\n")
    for path, base, stride, offset, t, through in resolvable(data):
        ctype, rd, wr = _read_write(t)
        fn = "soa_" + c_ident(path.replace("[]", ""))
        idx = ", uint32_t i" if stride else ""
        step = f" + i * {stride}u" if stride else ""
        utype = {"int8_t": "uint8_t", "int16_t": "uint16_t", "int32_t": "uint32_t"}.get(
            ctype, ctype
        )
        signed = utype != ctype
        if through:  # the pointer first, then the index and the field inside what it points at
            where = f"p{step} + {offset}u"
            locate = f"    if (!api->read32(0x{base:08X}u, &p)) return 0;\n"
        else:
            where = f"0x{base:08X}u{step}" + (f" + {offset}u" if offset else "")
            locate = ""
        decl_get = ("    uint32_t p;\n" if through else "") + (
            f"    {utype} v;\n" if signed else ""
        )
        decl_set = "    uint32_t p;\n" if through else ""
        if signed:
            tail = f"    if (!api->{rd}({where}, &v)) return 0;\n    *out = ({ctype})v;\n    return 1;\n"
        else:
            tail = f"    return api->{rd}({where}, out);\n"
        out.append(f"static inline int {fn}_get(const SoaModApi* api{idx}, {ctype}* out)\n{{\n")
        out.append(decl_get + locate + tail + "}\n")
        cast = f"({utype})" if signed else ""
        out.append(f"static inline int {fn}_set(const SoaModApi* api{idx}, {ctype} v)\n{{\n")
        out.append(decl_set + locate + f"    return api->{wr}({where}, {cast}v);\n}}\n")
    out.append("\n#endif\n")
    return "".join(out)


TABLE_TOP = """/* Generated from config/gamedata.txt by tools/gamedata.py; do not edit.
 * The names patches.txt may give (T9): path, base, stride (an index's), field
 * offset, width (patch_width's codes: 1 u8 2 u16 4 u32, negative signed), and
 * 1 where the base is a pointer the offset is taken through. */
"""


def table(data: GameData) -> str:
    widths = {"u8": 1, "s8": -1, "u16": 2, "s16": -2, "u32": 4, "s32": -4, "ptr": 4, "f32": 4}
    rows = [TABLE_TOP]
    for path, base, stride, offset, t, through in resolvable(data):
        rows.append(
            f'{{"{path}", 0x{base:08X}u, {stride}u, {offset}u, {widths[t]}, {int(through)}}},\n'
        )
    return "".join(rows)


def markdown(data: GameData) -> str:
    out = [
        "# The game's data by name\n\n",
        "Generated from `config/gamedata.txt` by `python tools/gamedata.py generate --write`; do not edit. Each name's\n",
        "address is proved against the instruction in the game's code that reaches it (`ref`), by\n",
        "`tools/tests/test_gamedata.py` (T9, [specs/game-names.md](specs/game-names.md)). A `patches.txt` line may give a\n",
        "name wherever it gives an address, a field after a dot and an index in brackets (`party.character[1].hp`);\n",
        "a DLL mod includes `runtime/soa_gamedata.h`.\n\n",
        "| Name | Address | Type | Ref | Evidence |\n|---|---|---|---|---|\n",
    ]
    for e in data.entries:
        ref = f"0x{e.ref:08X}" + (f"+{e.ref_off}" if e.ref_off else "")
        out.append(f"| `{e.name}` | `0x{e.address:08X}` | `{e.type}` | `{ref}` | {e.evidence} |\n")
    for r in data.records.values():
        out.append(
            f"\n**`{r.name}`**, {r.size} bytes:\n\n| Field | Offset | Type |\n|---|---|---|\n"
        )
        for f in r.fields:
            out.append(f"| `{f.name}` | {f.offset} | `{f.type}` |\n")
    return "".join(out)
