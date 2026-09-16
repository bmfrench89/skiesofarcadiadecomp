"""Which general-purpose registers an instruction writes.

The destination is not in one field on PowerPC. Most instructions write rD
(bits 6-10), but the logical, shift and rotate families write rA (bits 11-15)
and carry their source in the rD slot; update-form loads and stores write rA
with the effective address as a side effect; ``lmw`` writes a whole range.
Any dataflow analysis that gets this wrong is silently wrong, so it is
tabulated once here and nowhere else.
"""

from .decode import Insn

# Destination is rA; the rD field holds the source rS.
_WRITES_RA = frozenset(
    [
        "and",
        "andc",
        "or",
        "orc",
        "xor",
        "nand",
        "nor",
        "eqv",
        "slw",
        "srw",
        "sraw",
        "srawi",
        "cntlzw",
        "extsb",
        "extsh",
        "rlwinm",
        "rlwimi",
        "rlwnm",
        "ori",
        "oris",
        "xori",
        "xoris",
        "andi.",
        "andis.",
    ]
)

# Update forms write rA with the effective address.
_UPDATE = frozenset(
    [
        "lwzu",
        "lbzu",
        "lhzu",
        "lhau",
        "lfsu",
        "lfdu",
        "stwu",
        "stbu",
        "sthu",
        "stfsu",
        "stfdu",
        "lwzux",
        "lbzux",
        "lhzux",
        "lhaux",
        "lfsux",
        "lfdux",
        "stwux",
        "stbux",
        "sthux",
        "stfsux",
        "stfdux",
        "psq_lu",
        "psq_stu",
        "psq_lux",
        "psq_stux",
    ]
)

# Ordinary results land in rD.
_WRITES_RD = frozenset(
    [
        "add",
        "addc",
        "adde",
        "addme",
        "addze",
        "subf",
        "subfc",
        "subfe",
        "subfme",
        "subfze",
        "neg",
        "mullw",
        "mulhw",
        "mulhwu",
        "divw",
        "divwu",
        "addi",
        "addis",
        "addic",
        "addic.",
        "mulli",
        "subfic",
        "lwz",
        "lbz",
        "lhz",
        "lha",
        "lwzx",
        "lbzx",
        "lhzx",
        "lhax",
        "lwbrx",
        "lhbrx",
        "lswi",
        "lswx",
        "lwarx",
        "mfspr",
        "mfcr",
        "mfmsr",
        "mfsr",
        "mfsrin",
        "mftb",
        "mftbu",
    ]
)


def gpr_defs(insn: Insn) -> frozenset[int]:
    """GPRs written by ``insn``. Empty for stores, compares, branches and FP ops."""
    if not insn.valid:
        return frozenset()
    m = insn.mnemonic
    out: set[int] = set()
    if m in _WRITES_RD:
        out.add(insn.rd)
    if m in _WRITES_RA:
        out.add(insn.ra)
    if m in _UPDATE:
        out.add(insn.ra)
        # Integer load-with-update writes the loaded value to rD as well.
        if m[0] == "l" and m[1] != "f" and not m.startswith("psq"):
            out.add(insn.rd)
    if m == "lmw":
        out.update(range(insn.rd, 32))
    return frozenset(out)


def is_mr(insn: Insn) -> bool:
    """``mr rA, rS`` is ``or rA, rS, rS``."""
    return insn.valid and insn.mnemonic == "or" and insn.rd == insn.rb
