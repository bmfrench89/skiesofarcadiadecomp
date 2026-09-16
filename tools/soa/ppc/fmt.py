"""Readable one-line disassembly of an Insn, for diagnostics and tooling.

Raw mnemonics with explicit fields; no simplified forms. Good enough to read
a function by eye, which is what the runtime work keeps needing.
"""

from .decode import Insn
from .isa import Form

_RA_DEST = frozenset(
    [
        "or",
        "and",
        "xor",
        "nor",
        "nand",
        "eqv",
        "andc",
        "orc",
        "slw",
        "srw",
        "sraw",
        "srawi",
        "cntlzw",
        "extsb",
        "extsh",
    ]
)


def format_insn(i: Insn) -> str:
    if i is None or not i.valid:
        return f".4byte 0x{i.word:08X}" if i is not None else "??"
    m = i.mnemonic
    f = i.form
    if m == "b":
        return f"b{'l' if i.lk_bit else ''}{'a' if i.aa_bit else ''} -> {i.target:08X}"
    if m == "bc":
        return f"bc{'l' if i.lk_bit else ''} {i.bo},{i.bi} -> {i.target:08X}"
    if m == "bclr":
        if i.is_unconditional:
            return "blrl" if i.lk_bit else "blr"
        return f"bclr{'l' if i.lk_bit else ''} {i.bo},{i.bi}"
    if m == "bcctr":
        if i.is_unconditional:
            return "bctrl" if i.lk_bit else "bctr"
        return f"bcctr{'l' if i.lk_bit else ''} {i.bo},{i.bi}"
    if m in ("mtspr", "mfspr"):
        return f"{m} {i.spr}, r{i.rd}"
    if f is Form.D:
        if m in ("cmpi", "cmpli"):
            return f"{m} cr{i.crf_d}, r{i.ra}, {i.imm}"
        if m in ("ori", "oris", "xori", "xoris", "andi.", "andis."):
            return f"{m} r{i.ra}, r{i.rd}, 0x{i.imm:04X}"
        if m in ("addi", "addis", "mulli", "subfic", "addic", "addic."):
            return f"{m} r{i.rd}, r{i.ra}, {i.imm}"
        reg = "f" if (m[0] in "ls" and m[1] == "f") else "r"
        return f"{m} {reg}{i.rd}, {i.imm}(r{i.ra})"
    if f is Form.PSQ:
        return f"{m} f{i.rd}, {i.imm}(r{i.ra}), {i.quant_w}, {i.gqr}"
    if f is Form.PSQX:
        return f"{m} f{i.rd}, r{i.ra}, r{i.rb}, {i.quant_w}, {i.gqr}"
    if f is Form.M:
        rb = f"r{i.rb}" if m == "rlwnm" else str(i.imm)
        return f"{m} r{i.ra}, r{i.rd}, {rb}, {i.mb}, {i.me}"
    if f in (Form.X, Form.XO):
        if m in ("cmp", "cmpl"):
            return f"{m} cr{i.crf_d}, r{i.ra}, r{i.rb}"
        if m == "srawi":
            return f"srawi r{i.ra}, r{i.rd}, {i.imm}"
        if m in _RA_DEST:
            return f"{m} r{i.ra}, r{i.rd}, r{i.rb}"
        if m.startswith(("f", "ps_")) or m in ("mffs",):
            return f"{m} f{i.rd}, f{i.ra}, f{i.rb}"
        return f"{m} r{i.rd}, r{i.ra}, r{i.rb}"
    if f is Form.A:
        reg = "f"
        return f"{m} {reg}{i.rd}, {reg}{i.ra}, {reg}{i.rc}, {reg}{i.rb}"
    if f is Form.XL:
        return f"{m} {i.bo}, {i.bi}, {i.rb}"
    return m


def disassemble(code, start: int, end: int) -> str:
    """Lines of `ADDR  insn` for [start, end)."""
    return "\n".join(f"{a:08X}  {format_insn(code.at(a))}" for a in range(start, end, 4))
