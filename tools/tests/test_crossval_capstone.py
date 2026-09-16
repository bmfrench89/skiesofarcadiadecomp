"""Cross-validate our Gekko decoder against an INDEPENDENT disassembler.

We wrote soa.ppc ourselves, so it can only be trusted as far as something else
agrees with it.  This module diffs it against capstone's PowerPC backend
(``pip install capstone``), which is derived from LLVM and therefore shares no
code or tables with ours.

Two layers:

  * ``test_synthetic_*``  — sweep the encoding space directly.  Needs no game
    data, so it runs in CI.  This is the layer that matters: the game image
    does not contain a single OE-form instruction, so bugs in that path are
    invisible to any test that only reads main.dol.

  * ``test_image_*``      — decode every word of .text0/.text1 and diff.  Skips
    itself when ``extracted/sys/main.dol`` is absent.

KNOWN CAPSTONE GAPS (asserted here so a capstone upgrade that fixes them shows
up as a test failure rather than silently changing the baseline).  All three
were confirmed against decomp-toolkit (dtk, the ppc750cl crate), which is
written from the 750CL manual for this exact console:

  * capstone rejects every OE-form (``addo``, ``subfo.``, ``nego`` ...).
  * capstone rejects ``fcmpo`` (opcode 63 XO=32) and ``mcrxr`` (31 XO=512).
  * capstone's CS_MODE_PS still resolves opcode 4 XO10 = 0/32/64/96 as AltiVec
    (``vaddubm`` etc.) instead of ``ps_cmpu0/ps_cmpo0/ps_cmpu1/ps_cmpo1``, and
    does not know ``dcbz_l``.  For opcode 4 capstone is NOT ground truth.

Reproducing the dtk half of the audit (not run here, it needs the 8 MB binary):
    dtk dol config main.dol -o cfg.yml && dtk dol split cfg.yml out
    # out/asm/*.s carries `/* ADDR FILEOFF  AA BB CC DD */\tmnemonic ops`
"""

# ruff: noqa: SIM905  - opcode groups read better as whitespace-separated text
import random
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa.ppc import decode  # noqa: E402

capstone = pytest.importorskip("capstone", reason="pip install capstone")

MODE = capstone.CS_MODE_32 | capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_PS
BASE = 0x80005600
DOL = Path(__file__).resolve().parents[2] / "extracted" / "sys" / "main.dol"


@pytest.fixture(scope="module")
def md():
    cs = capstone.Cs(capstone.CS_ARCH_PPC, MODE)
    cs.detail = True
    return cs


def cap_one(md, word, addr=BASE):
    """Disassemble a single word. Returns (mnemonic, op_str, operands) or None."""
    out = list(md.disasm(word.to_bytes(4, "big"), addr))
    if not out:
        return None
    i = out[0]
    ops = []
    for o in i.operands:
        if o.type == capstone.ppc.PPC_OP_REG:
            ops.append(("reg", i.reg_name(o.reg)))
        elif o.type == capstone.ppc.PPC_OP_IMM:
            ops.append(("imm", o.imm))
        elif o.type == capstone.ppc.PPC_OP_MEM:
            ops.append(("mem", i.reg_name(o.mem.base) if o.mem.base else None, o.mem.disp))
    return i.mnemonic, i.op_str, tuple(ops)


# --------------------------------------------------------------------------
# normalisation: capstone prints simplified mnemonics, we emit raw forms
# --------------------------------------------------------------------------

SIMPLIFIED = {
    "nop": "ori",
    "li": "addi",
    "lis": "addis",
    "subi": "addi",
    "subis": "addis",
    "subic": "addic",
    "subic.": "addic.",
    "mr": "or",
    "mr.": "or.",
    "not": "nor",
    "not.": "nor.",
    "sub": "subf",
    "sub.": "subf.",
    "cmpwi": "cmpi",
    "cmplwi": "cmpli",
    "cmpw": "cmp",
    "cmplw": "cmpl",
    "crset": "creqv",
    "crclr": "crxor",
    "crmove": "cror",
    "crnot": "crnor",
    "mtcr": "mtcrf",
    "twui": "twi",
    "mbar": "eieio",
    # ISA 2.01 split the CRM!=0 encodings out as mfocrf/mtocrf.  The 750CL has
    # no such instruction: those bits are simply reserved in mfcr/mtcrf.
    "mfocrf": "mfcr",
    "mtocrf": "mtcrf",
    # dcbzl is ISA 2.06; on the 750CL that bit of dcbz is reserved.
    "dcbzl": "dcbz",
}
ROTATES = {
    "slwi": "rlwinm",
    "srwi": "rlwinm",
    "clrlwi": "rlwinm",
    "clrrwi": "rlwinm",
    "rotlwi": "rlwinm",
    "rotrwi": "rlwinm",
    "extlwi": "rlwinm",
    "extrwi": "rlwinm",
    "clrlslwi": "rlwinm",
    "inslwi": "rlwimi",
    "insrwi": "rlwimi",
    # rotlw rA,rS,rB is rlwnm rA,rS,rB,0,31 -- the register-rotate form.
    "rotlw": "rlwnm",
}
COND = ("lt", "gt", "eq", "so", "ge", "le", "ne", "ns", "un", "nu")
TRAP_COND = (
    "lgt",
    "llt",
    "lge",
    "lle",
    "lnl",
    "lng",
    "eq",
    "ne",
    "lt",
    "le",
    "ge",
    "gt",
    "nl",
    "ng",
    "u",
)
BRANCH_TAIL = {
    "lrl": "bclrl",
    "lr": "bclr",
    "ctrl": "bcctrl",
    "ctr": "bcctr",
    "la": "bcla",
    "l": "bcl",
    "a": "bca",
    "": "bc",
}
MF_NAMED = {"mfcr", "mfmsr", "mfsr", "mfsrin", "mffs", "mftb", "mftbu"}
MT_NAMED = {"mtcrf", "mtmsr", "mtsr", "mtsrin", "mtfsf", "mtfsfi", "mtfsb0", "mtfsb1"}


def canon_theirs(m):
    """capstone mnemonic -> the raw base form our decoder emits."""
    if m is None:
        return None
    dot = m.endswith(".")
    stem = m[:-1] if dot else m
    if stem in ROTATES:
        return ROTATES[stem] + ("." if dot else "")
    if m in SIMPLIFIED:
        return SIMPLIFIED[m]
    if stem in SIMPLIFIED:
        return SIMPLIFIED[stem] + ("." if dot else "")
    if stem.startswith("mf") and stem not in MF_NAMED:
        return "mfspr"
    if stem.startswith("mt") and stem not in MT_NAMED:
        return "mtspr"
    s = m.rstrip("+-")  # branch-prediction hint
    if s in ("b", "ba", "bl", "bla"):
        return s
    if s in ("blr", "blrl"):
        return "bclr" + ("l" if s.endswith("rl") else "")
    if s in ("bctr", "bctrl"):
        return "bcctr" + ("l" if s.endswith("rl") else "")
    for head in ("bdnzt", "bdnzf", "bdzt", "bdzf", "bdnz", "bdz"):
        if s.startswith(head):
            return BRANCH_TAIL.get(s[len(head) :])
    for c in COND:
        if s.startswith("b" + c):
            return BRANCH_TAIL.get(s[1 + len(c) :])
    for c in TRAP_COND:  # tweqi, twlgti, tdui, trap ...
        if stem == "tw" + c + "i":
            return "twi"
        if stem == "td" + c + "i":
            return "tdi"
        if stem == "tw" + c:
            return "tw"
        if stem == "td" + c:
            return "td"
    if stem in ("trap", "trapd"):
        return "tw" if stem == "trap" else "td"
    if s in ("bt", "bf"):
        return "bc"
    if s in ("btlr", "bflr"):
        return "bclr"
    if s in ("btctr", "bfctr"):
        return "bcctr"
    return m


def canon_ours(i):
    """Our Insn -> the same raw base form, with optional-bit suffixes applied."""
    m = i.mnemonic
    if m in ("b", "bc"):
        return m + ("l" if i.lk_bit else "") + ("a" if i.aa_bit else "")
    if m in ("bclr", "bcctr"):
        return m + ("l" if i.lk_bit else "")
    return m + ("o" if i.oe_bit else "") + ("." if i.rc_bit else "")


# --------------------------------------------------------------------------
# operand comparison
# --------------------------------------------------------------------------

# rD lives in bits 6-10 and is the destination: printed (rD, rA, rB)
DEST_RD = set(
    """add addc adde addme addze subf subfc subfe subfme subfze neg mullw mulhw mulhwu
    divw divwu lwzx lwzux lbzx lbzux lhzx lhzux lhax lhaux stwx stwux stbx stbux sthx
    sthux lfsx lfsux lfdx lfdux stfsx stfsux stfdx stfdux stfiwx lwbrx lhbrx stwbrx
    sthbrx""".split()
)
# rS lives in bits 6-10 but rA is the destination: printed (rA, rS, rB)
DEST_RA_X = set("and andc or orc xor nand nor eqv slw srw sraw cntlzw extsb extsh".split())
DEST_RA_D = set("ori oris xori xoris andi. andis.".split())
ARITH_D = set("addi addis addic addic. subfic mulli".split())
LOADSTORE_D = set(
    """lwz lwzu lbz lbzu lhz lhzu lha lhau stw stwu stb stbu sth sthu lmw stmw
    lfs lfsu lfd lfdu stfs stfsu stfd stfdu""".split()
)
A_AB = set("fadd fsub fdiv ps_add ps_sub ps_div".split())
A_AC = set("fmul ps_mul ps_muls0 ps_muls1".split())
A_B = set("fsqrt fres frsqrte ps_res ps_rsqrte".split())
A_ACB = set(
    """fsel fmadd fmsub fnmadd fnmsub ps_sel ps_madd ps_msub ps_nmadd ps_nmsub
    ps_sum0 ps_sum1 ps_madds0 ps_madds1""".split()
)
FMOVE = set("fmr fneg fabs fnabs frsp fctiw fctiwz ps_mr ps_neg ps_abs ps_nabs".split())
FMERGE = set("ps_merge00 ps_merge01 ps_merge10 ps_merge11".split())
PSQ_D = {"psq_l", "psq_lu", "psq_st", "psq_stu"}
PSQ_X = {"psq_lx", "psq_stx", "psq_lux", "psq_stux"}
FCMP = {"fcmpu", "fcmpo", "ps_cmpu0", "ps_cmpo0", "ps_cmpu1", "ps_cmpo1"}


def _rn(x):
    """capstone register name -> number. A missing base register prints as 0."""
    if x is None:
        return 0
    return int(x[1:]) if isinstance(x, str) and x[:1] in "rf" and x[1:].isdigit() else x


def _rot_fields(cm, n):
    """Invert capstone's rlwinm/rlwimi simplifications back to (SH, MB, ME)."""
    if cm in ("rlwinm", "rlwinm.", "rlwimi", "rlwimi."):
        return n[0], n[1], n[2]
    table = {
        "slwi": lambda: (n[0], 0, 31 - n[0]),
        "srwi": lambda: ((32 - n[0]) % 32, n[0], 31),
        "clrlwi": lambda: (0, n[0], 31),
        "clrrwi": lambda: (0, 0, 31 - n[0]),
        "rotlwi": lambda: (n[0], 0, 31),
        "rotrwi": lambda: ((32 - n[0]) % 32, 0, 31),
        "extlwi": lambda: (n[1], 0, n[0] - 1),
        "extrwi": lambda: ((n[1] + n[0]) % 32, 32 - n[0], 31),
        "clrlslwi": lambda: (n[1], n[0] - n[1], 31 - n[1]),
        "inslwi": lambda: ((32 - n[1]) % 32, n[1], n[1] + n[0] - 1),
        "insrwi": lambda: ((32 - (n[1] + n[0])) % 32, n[1], n[1] + n[0] - 1),
    }
    f = table.get(cm.rstrip("."))
    return f() if f else None


def compare_operands(i, cm, ops, addr):
    """Return (ours, theirs) tuples to compare, or None when not modelled here."""
    regs = [_rn(o[1]) for o in ops if o[0] == "reg"]
    imms = [o[1] for o in ops if o[0] == "imm"]
    mems = [(_rn(o[1]) if o[1] else 0, o[2]) for o in ops if o[0] == "mem"]
    crs = [o[1] for o in ops if o[0] == "reg" and isinstance(o[1], str) and o[1].startswith("cr")]
    m = i.mnemonic

    if m in LOADSTORE_D and mems:
        return (i.rd, i.ra, i.imm), (regs[0], mems[0][0], mems[0][1])
    if m in ARITH_D:
        if cm in ("li", "lis"):
            return (i.rd, 0, i.imm), (regs[0], 0, imms[0])
        if cm in ("subi", "subis", "subic", "subic."):
            return (i.rd, i.ra, i.imm), (regs[0], regs[1], -imms[0])
        if len(regs) >= 2 and imms:
            return (i.rd, i.ra, i.imm), (regs[0], regs[1], imms[0])
        return None
    if m in DEST_RA_D:
        return None if cm == "nop" else ((i.ra, i.rd, i.imm), (regs[0], regs[1], imms[0]))
    if m in ("cmpi", "cmpli"):
        crf = int(crs[0][2:]) if crs else 0
        return (i.crf_d, i.ra, i.imm), (crf, regs[1] if crs else regs[0], imms[0])
    if m in ("cmp", "cmpl") or m in FCMP:
        crf = int(crs[0][2:]) if crs else 0
        ra, rb = (regs[1], regs[2]) if crs else (regs[0], regs[1])
        return (i.crf_d, i.ra, i.rb), (crf, ra, rb)
    if m in DEST_RD:
        if cm in ("sub", "sub."):
            return (i.rd, i.ra, i.rb), (regs[0], regs[2], regs[1])
        if len(regs) == 3:
            return (i.rd, i.ra, i.rb), tuple(regs)
        if len(regs) == 2:
            return (i.rd, i.ra), tuple(regs)
        return None
    if m in DEST_RA_X:
        if cm in ("mr", "mr.", "not", "not."):
            return (i.ra, i.rd, i.rb), (regs[0], regs[1], regs[1])
        if len(regs) == 3:
            return (i.ra, i.rd, i.rb), tuple(regs)
        if len(regs) == 2:
            return (i.ra, i.rd), tuple(regs)
        return None
    if m == "srawi":
        return (i.ra, i.rd, i.imm), (regs[0], regs[1], imms[0])
    if m in ("rlwinm", "rlwimi"):
        u = _rot_fields(cm, imms)
        return None if u is None else ((i.ra, i.rd, i.imm, i.mb, i.me), (regs[0], regs[1], *u))
    if m in ("mfspr", "mtspr", "mftb", "mftbu") and cm in ("mfspr", "mtspr", "mftb", "mftbu"):
        # mftb/mftbu name the time-base half in the mnemonic itself, so
        # capstone emits no SPR immediate to compare against.
        return (i.spr, imms[0]) if imms else None
    if m in ("b", "bc") and imms:
        tgt = i.imm if i.aa_bit else (addr + i.imm) & 0xFFFFFFFF
        return tgt & 0xFFFFFFFF, imms[-1] & 0xFFFFFFFF
    if m in A_AB or m in FMERGE:
        return (i.rd, i.ra, i.rb), tuple(regs)
    if m in A_AC:
        return (i.rd, i.ra, i.rc), tuple(regs)
    if m in A_B or m in FMOVE:
        return (i.rd, i.rb), tuple(regs)
    if m in A_ACB:
        return (i.rd, i.ra, i.rc, i.rb), tuple(regs)
    if m in PSQ_D:
        return (i.rd, i.ra, i.imm, i.quant_w, i.gqr), (
            regs[0],
            mems[0][0],
            mems[0][1],
            imms[0],
            imms[1],
        )
    if m in PSQ_X:
        return (i.rd, i.ra, i.rb, i.quant_w, i.gqr), (regs[0], regs[1], regs[2], imms[0], imms[1])
    return None


# capstone cannot decode these; verified correct against dtk/ppc750cl instead.
CAPSTONE_BLIND = {"fcmpo", "mcrxr", "dcbz_l", "ps_cmpu0", "ps_cmpo0", "ps_cmpu1", "ps_cmpo1"}

# Instructions capstone decodes that the 750CL simply does not have: 64-bit
# PowerPC, AltiVec, VSX, BookE and ISA 2.06+ additions.  Our decoder rejecting
# them is correct, not a missing table entry.  Anything capstone decodes that
# is NOT covered here is a genuine hole in isa.py and fails the test.
# 2  = tdi, trap-doubleword-immediate, 64-bit only
# 30 = 64-bit rotates
# 58, 62 = DS-form ld/std/lwa
# capstone is a full modern PowerPC decoder and accepts all of these; dtk,
# which is written for this console, rejects them, and so do we.
NOT_ON_750CL_PRIMARY = {2, 30, 58, 62}
NOT_ON_750CL_PREFIX = (
    "v",
    "xs",
    "xv",
    "lxv",
    "lxs",
    "stxv",
    "stxs",
    "bcd",
    "mfvsr",
    "mtvsr",
    "lv",
    "stv",
    "rld",
    "rotld",
    "sldi",
    "clrldi",
)
NOT_ON_750CL = frozenset(
    """
addpcis attn bpermd cmpb cmpeqb cmprb copy dcbtep dcbtstep dcbzep divd divde divdeu
divdu divwe divweu dst dstt extswsli fcfid fcfidu fcfidus fcpsgn fctiduz fctiwuz frip
icblc icblq icbt icbtls isel lbarx lbepx lbzcix ld ldarx ldat ldbrx ldcix ldmx ldu ldux
ldx lfdepx lfiwax lfiwzx lharx lhepx lhzcix lwa lwat lwaux lwax lwepx lwzcix mfbhrbe
mfdcr mfpmr modsd modsw modud moduw mtdcr mtmsrd mtpmr mulhd mulhdu mulld paste slbie
cnttzd cnttzw cntlzd popcntd popcntw popcntb prtyd prtyw bpermd darn addex setb
extsw extsw. dcbfep dcbflp cmpbd msgsnd msgclr cmpdi cmpldi cmpd cmpld
slbmte sld srad sradi srd stbcix stbcx stbepx std stdat stdbrx stdcix stdcx stdu stdux
stdx stfdepx sthcix sthcx sthepx stwat stwcix stwepx tabortdc tabortdci tabortwc
tabortwci td tdeq tlbrehi tlbrelo tlbsx tlbwehi tlbwelo wrtee wrteei
""".split()
)


def is_not_on_750cl(word, mnemonic):
    if (word >> 26) & 0x3F in NOT_ON_750CL_PRIMARY:
        return True
    stem = mnemonic.rstrip(".")
    return stem in NOT_ON_750CL or mnemonic.startswith(NOT_ON_750CL_PREFIX)


def diff_word(md, word, addr=BASE, strict_reserved=False):
    """One word -> None if the tools agree, else a short description of the gap.

    ``strict_reserved`` controls the direction where we decode a word capstone
    refuses.  That is almost always our decoder being deliberately total: it
    ignores reserved bits (``cmp`` with bit 31 set, ``fadd`` with a nonzero rC)
    where capstone insists they are zero.  soa.ppc documents that behaviour, so
    it is off by default; ``test_synthetic_reserved_bit_leniency`` measures it.
    """
    i = decode(word, addr)
    got = cap_one(md, word, addr)
    if got is None:
        if not i.valid:
            return None
        if i.mnemonic in CAPSTONE_BLIND or i.oe_bit:
            return None  # documented capstone gap
        if not strict_reserved:
            return None
        return f"ours={canon_ours(i)} capstone=INVALID"
    cm, _, ops = got
    if not i.valid:
        if is_not_on_750cl(word, cm):
            return None  # correct rejection: not a Gekko opcode
        return f"ours=INVALID capstone={cm}"
    if is_not_on_750cl(word, cm):
        return None
    if (word >> 26) & 0x3F == 4:
        return None  # capstone prefers AltiVec here; dtk is the authority
    a, b = canon_ours(i), canon_theirs(cm)
    if a != b:
        return f"mnemonic ours={a} capstone={cm} (->{b})"
    cmp_ = compare_operands(i, cm, ops, addr)
    if cmp_ is not None and cmp_[0] != cmp_[1]:
        return f"operands {a}: ours={cmp_[0]} capstone={cmp_[1]}"
    return None


def report(md, words, limit=25, strict_reserved=False):
    bad = []
    for w, note in words:
        d = diff_word(md, w, strict_reserved=strict_reserved)
        if d:
            bad.append(f"{w:08X} ({note}): {d}")
    return bad[:limit], len(bad)


# --------------------------------------------------------------------------
# synthetic sweeps — no game data needed
# --------------------------------------------------------------------------

XO_ARITH = {
    8: "subfc",
    10: "addc",
    40: "subf",
    104: "neg",
    136: "subfe",
    138: "adde",
    200: "subfze",
    202: "addze",
    232: "subfme",
    234: "addme",
    235: "mullw",
    266: "add",
    459: "divwu",
    491: "divw",
}


def test_synthetic_xo_form_oe_bit(md):
    """XO-form: with OE set the extended opcode is 9 bits, not 10.

    capstone refuses every OE form, so ``diff_word`` cannot see these.  Assert
    our own naming directly; dtk (ppc750cl) confirmed all 56 combinations.
    """
    for xo, name in XO_ARITH.items():
        rb = 0 if name in ("neg", "subfze", "addze", "subfme", "addme") else 5
        for oe in (0, 1):
            for rc in (0, 1):
                w = (31 << 26) | (3 << 21) | (4 << 16) | (rb << 11) | (oe << 10) | (xo << 1) | rc
                i = decode(w)
                assert i.valid, f"{w:08X} {name} oe={oe} rc={rc} should decode"
                assert i.mnemonic == name
                assert i.oe_bit == bool(oe), f"{w:08X}: OE bit misread"
                assert i.rc_bit == bool(rc), f"{w:08X}: Rc bit misread"
                assert (i.rd, i.ra) == (3, 4)


def test_synthetic_mulhw_has_no_oe(md):
    """mulhw/mulhwu are XO-form but bit 10 is reserved, not OE."""
    for xo in (11, 75):
        w = (31 << 26) | (3 << 21) | (4 << 16) | (5 << 11) | (1 << 10) | (xo << 1)
        assert not decode(w).valid, f"{w:08X}: bit 10 set must not decode"
        assert cap_one(md, w) is None


def test_synthetic_primary_31(md):
    rnd = random.Random(31)
    words = [
        (
            (31 << 26)
            | (rnd.randrange(32) << 21)
            | (rnd.randrange(32) << 16)
            | (rnd.randrange(32) << 11)
            | (oe << 10)
            | (xo << 1)
            | rc,
            f"31/{xo}",
        )
        for xo in range(1024)
        for oe in (0, 1)
        for rc in (0, 1)
    ]
    bad, n = report(md, words)
    assert n == 0, f"{n} disagreements, first:\n  " + "\n  ".join(bad)


def test_synthetic_primary_19_and_63(md):
    rnd = random.Random(63)
    words = []
    for op in (19, 63):
        words += [
            (
                (op << 26)
                | (rnd.randrange(32) << 21)
                | (rnd.randrange(32) << 16)
                | (rnd.randrange(32) << 11)
                | (xo << 1)
                | rc,
                f"{op}/{xo}",
            )
            for xo in range(1024)
            for rc in (0, 1)
        ]
    bad, n = report(md, words)
    assert n == 0, f"{n} disagreements, first:\n  " + "\n  ".join(bad)


def test_synthetic_primary_59_single_precision(md):
    """Opcode 59 is the SINGLE-precision float group: fadds, not fadd."""
    shape = {
        18: "AB",
        20: "AB",
        21: "AB",
        24: "B",
        25: "AC",
        28: "ACB",
        29: "ACB",
        30: "ACB",
        31: "ACB",
    }
    for xo, sh in shape.items():
        w = (
            (59 << 26)
            | (1 << 21)
            | ((2 if "A" in sh else 0) << 16)
            | ((3 if "B" in sh else 0) << 11)
            | ((4 if "C" in sh else 0) << 6)
            | (xo << 1)
        )
        i = decode(w)
        got = cap_one(md, w)
        assert i.valid and got, f"{w:08X} opcode 59 XO={xo}"
        assert i.mnemonic == got[0], (
            f"{w:08X} opcode 59 XO={xo}: ours={i.mnemonic} capstone={got[0]}"
        )


def test_synthetic_primary_59_reserved_xo(md):
    """fsel (23), fsqrts (22) and frsqrtes (26) are not Gekko opcode-59 forms.

    dtk/ppc750cl rejects all three; the 750CL manual does not list them.
    """
    for xo in (22, 23, 26):
        w = (59 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (4 << 6) | (xo << 1)
        assert not decode(w).valid, f"{w:08X}: opcode 59 XO={xo} is not a 750CL instruction"


def test_synthetic_primary_63_reserved_xo(md):
    """fres (24) is single-precision only; opcode 63 XO=24 is not on the 750CL.

    Nor is fsqrt (22), which the 750 does not implement.
    """
    for xo in (22, 24):
        w = (63 << 26) | (1 << 21) | (3 << 11) | (xo << 1)
        assert not decode(w).valid, f"{w:08X}: opcode 63 XO={xo} is not a 750CL instruction"


PS_A_SHAPE = {
    10: "ACB",
    11: "ACB",
    12: "AC",
    13: "AC",
    14: "ACB",
    15: "ACB",
    18: "AB",
    20: "AB",
    21: "AB",
    23: "ACB",
    24: "B",
    25: "AC",
    26: "B",
    28: "ACB",
    29: "ACB",
    30: "ACB",
    31: "ACB",
}


def test_synthetic_paired_single_arithmetic(md):
    """Gekko opcode 4 A-form. capstone's PS mode does know these."""
    for xo, sh in PS_A_SHAPE.items():
        w = (
            (4 << 26)
            | (1 << 21)
            | ((2 if "A" in sh else 0) << 16)
            | ((3 if "B" in sh else 0) << 11)
            | ((4 if "C" in sh else 0) << 6)
            | (xo << 1)
        )
        i, got = decode(w), cap_one(md, w)
        assert i.valid and got, f"{w:08X} opcode 4 XO={xo}"
        assert i.mnemonic == got[0], f"{w:08X}: ours={i.mnemonic} capstone={got[0]}"


def test_synthetic_paired_single_x_form():
    """Opcode 4 X-form. capstone picks AltiVec here, so assert against dtk's answer."""
    expected = {
        40: "ps_neg",
        72: "ps_mr",
        136: "ps_nabs",
        264: "ps_abs",
        528: "ps_merge00",
        560: "ps_merge01",
        592: "ps_merge10",
        624: "ps_merge11",
    }
    for xo, name in expected.items():
        w = (4 << 26) | (1 << 21) | (3 << 11) | (xo << 1)
        i = decode(w)
        assert i.valid and i.mnemonic == name, f"{w:08X}: {i.mnemonic} != {name}"
    for crf, xo, name in [
        (0, 0, "ps_cmpu0"),
        (1, 32, "ps_cmpo0"),
        (2, 64, "ps_cmpu1"),
        (3, 96, "ps_cmpo1"),
    ]:
        w = (4 << 26) | (crf << 23) | (2 << 16) | (3 << 11) | (xo << 1)
        i = decode(w)
        assert i.valid and i.mnemonic == name and i.crf_d == crf, f"{w:08X}: {i.mnemonic}"
    w = (4 << 26) | (2 << 16) | (3 << 11) | (1014 << 1)
    assert decode(w).mnemonic == "dcbz_l"


def test_synthetic_quantized_load_store(md):
    """psq_* W (scale-vs-not) and I (which GQR) fields, X-form and D-form."""
    for xo, name in [(6, "psq_lx"), (7, "psq_stx"), (38, "psq_lux"), (39, "psq_stux")]:
        for wbit in (0, 1):
            for gqr in range(8):
                w = (
                    (4 << 26)
                    | (1 << 21)
                    | (2 << 16)
                    | (3 << 11)
                    | (wbit << 10)
                    | (gqr << 7)
                    | (xo << 1)
                )
                i, got = decode(w), cap_one(md, w)
                assert i.valid and i.mnemonic == name
                assert (i.quant_w, i.gqr) == (wbit, gqr), f"{w:08X}: W/I misread"
                assert got and got[0] == name
                assert [o[1] for o in got[2] if o[0] == "imm"] == [wbit, gqr]
    for op, name in [(56, "psq_l"), (57, "psq_lu"), (60, "psq_st"), (61, "psq_stu")]:
        for disp in (0, 1, 2047, -2048, -1):
            for wbit in (0, 1):
                for gqr in (0, 5, 7):
                    w = (
                        (op << 26)
                        | (1 << 21)
                        | (2 << 16)
                        | (wbit << 15)
                        | (gqr << 12)
                        | (disp & 0xFFF)
                    )
                    i = decode(w)
                    assert i.mnemonic == name
                    assert (i.imm, i.quant_w, i.gqr) == (disp, wbit, gqr), f"{w:08X}"


def test_synthetic_spr_halves_are_swapped(md):
    for spr in (1, 8, 9, 18, 19, 22, 26, 27, 272, 275, 287, *range(912, 920), 1008, 1017):
        enc = ((spr & 0x1F) << 16) | ((spr >> 5) << 11)
        for xo in (339, 467):
            w = (31 << 26) | (3 << 21) | enc | (xo << 1)
            assert decode(w).spr == spr, f"{w:08X}: SPR {decode(w).spr} != {spr}"


def test_synthetic_rotate_masks(md):
    """rlwinm/rlwimi SH, MB and ME, including mb > me (wrapped masks)."""
    for sh in (0, 1, 8, 16, 31):
        for mb in (0, 1, 15, 16, 31):
            for me in (0, 1, 15, 16, 31):
                for op in (20, 21):
                    w = (op << 26) | (3 << 21) | (4 << 16) | (sh << 11) | (mb << 6) | (me << 1)
                    i = decode(w)
                    assert (i.imm, i.mb, i.me) == (sh, mb, me), f"{w:08X}"
                    assert (i.rd, i.ra) == (3, 4)
                    d = diff_word(md, w)
                    assert d is None, f"{w:08X}: {d}"


def test_synthetic_branch_displacements(md):
    """Signed LI/BD, including the largest negative displacements."""
    for bd in (0, 4, -4, 0x7FFC, -0x8000, 0x1FFFFFC, -0x2000000):
        for aa in (0, 1):
            for lk in (0, 1):
                w = (18 << 26) | (bd & 0x03FFFFFC) | (aa << 1) | lk
                i = decode(w, 0x80100000)
                assert i.imm == bd, f"{w:08X}: LI {i.imm} != {bd}"
                assert i.lk_bit == bool(lk) and i.aa_bit == bool(aa)
                want = (bd if aa else 0x80100000 + bd) & 0xFFFFFFFF
                assert i.target == want, f"{w:08X}: target {i.target!r} != 0x{want:08X}"
    for bd in (0, 4, -4, 0x7FFC, -0x8000):
        w = (16 << 26) | (12 << 21) | (2 << 16) | (bd & 0xFFFC)
        i = decode(w, 0x80100000)
        assert i.imm == bd and (i.bo, i.bi) == (12, 2)
        assert i.target == (0x80100000 + bd) & 0xFFFFFFFF
        assert diff_word(md, w, 0x80100000) is None


def test_synthetic_all_primary_opcodes(md):
    rnd = random.Random(7)
    words = [
        ((op << 26) | rnd.randrange(1 << 26), f"op{op}") for op in range(64) for _ in range(500)
    ]
    bad, n = report(md, words)
    assert n == 0, f"{n} disagreements, first:\n  " + "\n  ".join(bad)


def test_synthetic_random_words(md):
    rnd = random.Random(20260915)
    words = [(rnd.randrange(1 << 32), "random") for _ in range(60000)]
    bad, n = report(md, words)
    assert n == 0, f"{n} disagreements, first:\n  " + "\n  ".join(bad)


def test_synthetic_entries_not_on_750cl():
    for w, name in [
        ((2 << 26) | (4 << 21) | (3 << 16) | 0x1234, "tdi"),
        ((31 << 26) | (370 << 1), "tlbia"),
    ]:
        assert not decode(w).valid, f"{w:08X}: {name} is not a 750CL instruction"


def test_synthetic_compare_l_field(md):
    """L must be 0 on a 32-bit implementation."""
    for op in (10, 11):  # cmpli, cmpi
        w = (op << 26) | (1 << 23) | (1 << 21) | (3 << 16) | 0x20
        assert not decode(w).valid, f"{w:08X}: L=1 is not a 750CL form"
    for xo in (0, 32):  # cmp, cmpl
        w = (31 << 26) | (1 << 23) | (1 << 21) | (3 << 16) | (4 << 11) | (xo << 1)
        assert not decode(w).valid, f"{w:08X}: L=1 is not a 750CL form"


def test_synthetic_reserved_bit_leniency(md):
    """We accept words capstone rejects for reserved bits. Bound that behaviour.

    This does not fail on leniency itself -- soa.ppc is a total decoder on
    purpose -- but it does fail if we ever start emitting a mnemonic that is
    not a real 750CL instruction, which is how an invented table entry shows up.
    """
    from soa.ppc import isa

    legal = set()
    for table in (
        isa.PRIMARY,
        isa.OP19,
        isa.OP31,
        isa.FLOAT_A_SINGLE,
        isa.FLOAT_A_DOUBLE,
        isa.OP63_X,
        isa.PS_A,
        isa.PS_QX,
        isa.PS_X,
    ):
        legal.update(v[0] for v in table.values())
    rnd = random.Random(4242)
    seen, n = set(), 0
    for _ in range(200000):
        w = rnd.randrange(1 << 32)
        i = decode(w)
        if i.valid and cap_one(md, w) is None and not i.oe_bit and i.mnemonic not in CAPSTONE_BLIND:
            seen.add(i.mnemonic)
            n += 1
    unknown = seen - legal
    assert not unknown, f"mnemonics not in isa.py tables: {sorted(unknown)}"
    assert n / 200000 < 0.15, f"leniency jumped to {n / 2000:.1f}% of random words"


# --------------------------------------------------------------------------
# whole-image diff
# --------------------------------------------------------------------------


def _text_sections():
    raw = DOL.read_bytes()
    offs = struct.unpack(">7I", raw[0x00:0x1C])
    addrs = struct.unpack(">7I", raw[0x48:0x64])
    sizes = struct.unpack(">7I", raw[0x90:0xAC])
    return [(a, raw[o : o + s]) for o, a, s in zip(offs, addrs, sizes, strict=True) if s]


@pytest.mark.skipif(not DOL.exists(), reason="extracted/sys/main.dol not present")
def test_image_every_word_agrees(md):
    words = []
    for addr, buf in _text_sections():
        for k in range(0, len(buf) - 3, 4):
            words.append((addr + k, int.from_bytes(buf[k : k + 4], "big")))
    bad = []
    for addr, w in words:
        d = diff_word(md, w, addr)
        if d:
            bad.append(f"{addr:08X} {w:08X}: {d}")
    assert not bad, f"{len(bad)}/{len(words)} words disagree, first 25:\n  " + "\n  ".join(bad[:25])
