"""Symbol database: the project's function and object inventory.

Two files live in ``config/`` and are committed. They are facts about the
binary -- addresses, sizes, names -- not copies of it (SPEC section 2):

  symbols.txt    dtk's symbol format, so the wider GameCube decompilation
                 tooling can consume the inventory directly
  functions.tsv  our per-function analysis metadata

C-level names are always ``fn_XXXXXXXX``. Pretty names -- from dtk's SDK
signature database, diagnostic strings, or by hand -- are *display* names.
They can collide with C keywords and library symbols (``exit``, ``__start``),
so they never become identifiers in generated code.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# The DOL header only numbers its sections; these are the names the wider
# tooling uses for this binary's layout (see FINDINGS section 3).
DTK_SECTION_NAMES = {
    ".text0": ".init",
    ".text1": ".text",
    ".data0": ".ctors",
    ".data1": ".dtors",
    ".data2": ".rodata",
    ".data3": ".data",
    ".data4": ".sdata",
    ".data5": ".sdata2",
}


@dataclass
class Symbol:
    name: str
    address: int
    section: str
    kind: str = "function"  # function | object | label
    size: int = 0
    scope: str = ""  # global | local | weak | ""
    attrs: dict = field(default_factory=dict)  # anything else dtk carries

    @property
    def is_placeholder(self) -> bool:
        """True for auto-generated names that carry no information."""
        return bool(re.fullmatch(r"(fn|lbl|jumptable|@\d+)_[0-9A-Fa-f]{8}", self.name)) or bool(
            re.fullmatch(r"@\d+", self.name)
        )

    def to_dtk(self) -> str:
        parts = [f"type:{self.kind}"]
        if self.size:
            parts.append(f"size:0x{self.size:X}")
        if self.scope:
            parts.append(f"scope:{self.scope}")
        for key, value in self.attrs.items():
            parts.append(key if value is True else f"{key}:{value}")
        return f"{self.name} = {self.section}:0x{self.address:08X}; // " + " ".join(parts)


_LINE = re.compile(r"^\s*(\S+)\s*=\s*(\S+?):0x([0-9A-Fa-f]+)\s*;\s*(?://\s*(.*))?$")


def parse_dtk(text: str) -> list[Symbol]:
    """Parse a dtk ``symbols.txt``. Unknown attributes are preserved verbatim."""
    out: list[Symbol] = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        name, section, addr, rest = m.groups()
        sym = Symbol(name=name, address=int(addr, 16), section=section)
        for token in (rest or "").split():
            key, _, value = token.partition(":")
            if key == "type":
                sym.kind = value
            elif key == "size":
                sym.size = int(value, 16)
            elif key == "scope":
                sym.scope = value
            else:
                sym.attrs[key] = value if value else True
        out.append(sym)
    return out


def load_dtk(path: Path) -> list[Symbol]:
    return parse_dtk(Path(path).read_text(encoding="utf-8"))


def write_dtk(symbols: list[Symbol], path: Path) -> None:
    lines = [s.to_dtk() for s in sorted(symbols, key=lambda s: (s.address, s.kind))]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# function inventory
# --------------------------------------------------------------------------

TSV_COLUMNS = (
    "address",
    "size",
    "name",
    "source",
    "frame",
    "leaf",
    "calls",
    "tail_calls",
    "jump_tables",
    "unresolved",
)


def name_for(address: int, dtk_by_addr: dict[int, Symbol]) -> tuple[str, str]:
    """Best display name for a function and where it came from."""
    sym = dtk_by_addr.get(address)
    if sym is not None and sym.kind == "function" and not sym.is_placeholder:
        return sym.name, "dtk"
    return f"fn_{address:08X}", "auto"


def build_inventory(dol, functions: dict, dtk_symbols: list[Symbol] | None = None) -> list[dict]:
    """Rows for functions.tsv, one per recovered function."""
    dtk_by_addr = {s.address: s for s in (dtk_symbols or []) if s.kind == "function"}
    rows = []
    for entry in sorted(functions):
        fn = functions[entry]
        name, source = name_for(entry, dtk_by_addr)
        rows.append(
            {
                "address": entry,
                "size": fn.size,
                "name": name,
                "source": source,
                "frame": int(fn.has_frame),
                "leaf": int(fn.is_leaf),
                "calls": len(fn.calls),
                "tail_calls": len(fn.tail_calls),
                "jump_tables": len(fn.jump_tables),
                "unresolved": fn.unresolved_indirect,
            }
        )
    return rows


def write_tsv(rows: list[dict], path: Path) -> None:
    lines = ["\t".join(TSV_COLUMNS)]
    for r in rows:
        lines.append(
            "\t".join(f"0x{r[c]:08X}" if c == "address" else str(r[c]) for c in TSV_COLUMNS)
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_tsv(path: Path) -> dict[int, dict]:
    """functions.tsv -> {address: row}. Numeric columns come back as ints."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    cols = lines[0].split("\t")
    out: dict[int, dict] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        vals = line.split("\t")
        row = {}
        for c, v in zip(cols, vals, strict=True):
            if c == "address":
                row[c] = int(v, 16)
            elif c in ("name", "source"):
                row[c] = v
            else:
                row[c] = int(v)
        out[row["address"]] = row
    return out


def symbols_from_inventory(
    dol, rows: list[dict], passthrough: list[Symbol] | None = None
) -> list[Symbol]:
    """Our functions as dtk symbols, plus any non-function symbols passed through."""
    out: list[Symbol] = []
    for r in rows:
        section = dol.section_at(r["address"])
        sec_name = DTK_SECTION_NAMES.get(section.name, section.name) if section else ".text"
        out.append(
            Symbol(
                name=r["name"],
                address=r["address"],
                section=sec_name,
                kind="function",
                size=r["size"],
                scope="global" if r["source"] != "auto" else "",
            )
        )
    # dtk's own function entries are superseded by ours; its objects and
    # labels pass through so the file stays a complete map for dtk tooling.
    out.extend(s for s in passthrough or [] if s.kind != "function")
    return out
