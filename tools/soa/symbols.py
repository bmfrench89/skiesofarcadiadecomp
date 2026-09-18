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


def load_names(path: Path) -> dict[int, tuple[str, str]]:
    """config/names.txt: ``address<TAB>name<TAB>evidence`` -> {address: (name, evidence)}.

    Names recovered by hand or from the binary's own diagnostic strings; they
    fill in where the SDK signature database has nothing.
    """
    out: dict[int, tuple[str, str]] = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        addr, name, evidence = (line.split("\t") + ["", ""])[:3]
        out[int(addr, 16)] = (name.strip(), evidence.strip() or "names")
    return out


_DTK_PLACEHOLDER = re.compile(r"(fn_([0-9A-Fa-f]{8})) = (\S+?):0x([0-9A-Fa-f]+)(;.*)?$")


def apply_names_to_dtk(path: Path, names: dict[int, tuple[str, str]], write: bool = True) -> int:
    """Carry recovered names into a dtk symbols file, returning how many landed.

    This is what puts our names in ``build/dtk/obj/``, which objdiff matches by
    name: that build is generated from ``config/GEAE8P/symbols.txt``, a
    separate file from our own ``config/symbols.txt``, so without this pass the
    two disagree about every name in ``config/names.txt``.

    Only placeholder ``fn_XXXXXXXX`` entries are renamed, so dtk's own SDK
    signature matches stand, and a name already used in the file is left alone
    rather than duplicated -- two symbols of one name would make the diff
    ambiguous in exactly the unit someone is working on. ``write=False``
    reports the count without touching the file.
    """
    text = Path(path).read_text(encoding="utf-8")
    taken = {line.split(" = ", 1)[0] for line in text.splitlines() if " = " in line}
    out = []
    renamed = 0
    for line in text.splitlines():
        m = _DTK_PLACEHOLDER.match(line)
        if m:
            placeholder, hexaddr, section, lineaddr, rest = m.groups()
            address = int(hexaddr, 16)
            # The address in the placeholder is the one in the entry; a file
            # where they disagree is not one to rewrite by name.
            name = names.get(address, (None,))[0]
            if name and address == int(lineaddr, 16) and name not in taken:
                line = f"{name} = {section}:0x{lineaddr}{rest or ''}"
                taken.discard(placeholder)
                taken.add(name)
                renamed += 1
        out.append(line)
    if write and renamed:
        Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")
    return renamed


def name_for(
    address: int, dtk_by_addr: dict[int, Symbol], names: dict[int, tuple[str, str]] | None = None
) -> tuple[str, str]:
    """Best display name for a function and where it came from."""
    sym = dtk_by_addr.get(address)
    if sym is not None and sym.kind == "function" and not sym.is_placeholder:
        return sym.name, "dtk"
    if names and address in names:
        return names[address][0], "string"
    return f"fn_{address:08X}", "auto"


def build_inventory(
    dol,
    functions: dict,
    dtk_symbols: list[Symbol] | None = None,
    names: dict[int, tuple[str, str]] | None = None,
) -> list[dict]:
    """Rows for functions.tsv, one per recovered function."""
    dtk_by_addr = {s.address: s for s in (dtk_symbols or []) if s.kind == "function"}
    rows = []
    for entry in sorted(functions):
        fn = functions[entry]
        name, source = name_for(entry, dtk_by_addr, names)
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


def main(argv: list[str] | None = None) -> int:
    """``python tools/soa/symbols.py [--dtk P] [--names P] [--dry-run]``

    Applies config/names.txt to the decomp-toolkit project's symbol file, the
    one build/dtk/obj/ is generated from. tools/inventory.py does this as part
    of a regeneration; this is the same pass on its own, for checking what a
    new name in names.txt would land (``--dry-run``) without rebuilding the
    inventory.
    """
    import argparse  # noqa: PLC0415 - only the command line needs it

    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--dtk", type=Path, default=Path("config/GEAE8P/symbols.txt"))
    ap.add_argument("--names", type=Path, default=Path("config/names.txt"))
    ap.add_argument("--dry-run", action="store_true", help="count without writing")
    args = ap.parse_args(argv)

    names = load_names(args.names)
    renamed = apply_names_to_dtk(args.dtk, names, write=not args.dry_run)
    verb = "would rename" if args.dry_run else "renamed"
    print(f"{verb} {renamed} of {len(names)} recovered names in {args.dtk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
