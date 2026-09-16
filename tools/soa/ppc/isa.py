"""PowerPC 750CL (Gekko) instruction tables.

Covers the base 32-bit PowerPC user ISA plus the GameCube-specific Gekko
extensions: paired-single arithmetic (primary opcode 4) and quantized
load/store (primary opcodes 4, 56, 57, 60, 61).

Tables are keyed by (primary_opcode, extended_opcode). The extended opcode
field width varies by form, so decode.py tries the widths in the order the
hardware does; see EXT_WIDTHS.
"""

from enum import Enum


class Form(str, Enum):
    """Instruction encoding form. Determines which operand fields are valid."""

    I = "I"  # b, bl, ba, bla
    B = "B"  # bc
    SC = "SC"  # sc
    D = "D"  # rD, rA, immediate
    X = "X"  # rD, rA, rB
    XL = "XL"  # condition-register / branch-to-register
    XFX = "XFX"  # SPR and CR field moves
    XFL = "XFL"  # mtfsf
    XO = "XO"  # arithmetic with OE bit
    A = "A"  # floating multiply-add family (4 register operands)
    M = "M"  # rotate-and-mask
    PSQ = "PSQ"  # quantized load/store, D-form  (opcodes 56/57/60/61)
    PSQX = "PSQX"  # quantized load/store, X-form (opcode 4)


# Flags describing which optional bits an instruction carries.
RC = 1 << 0  # record bit -> updates CR0 (or CR1 for float)
OE = 1 << 1  # overflow enable
LK = 1 << 2  # link bit
AA = 1 << 3  # absolute address


# --------------------------------------------------------------------------
# primary opcode -> (mnemonic, form, flags)
# Instructions whose primary opcode alone identifies them.
# --------------------------------------------------------------------------

PRIMARY: dict[int, tuple[str, Form, int]] = {
    2: ("tdi", Form.D, 0),
    3: ("twi", Form.D, 0),
    7: ("mulli", Form.D, 0),
    8: ("subfic", Form.D, 0),
    10: ("cmpli", Form.D, 0),
    11: ("cmpi", Form.D, 0),
    12: ("addic", Form.D, 0),
    13: ("addic.", Form.D, 0),
    14: ("addi", Form.D, 0),
    15: ("addis", Form.D, 0),
    16: ("bc", Form.B, AA | LK),
    17: ("sc", Form.SC, 0),
    18: ("b", Form.I, AA | LK),
    20: ("rlwimi", Form.M, RC),
    21: ("rlwinm", Form.M, RC),
    23: ("rlwnm", Form.M, RC),
    24: ("ori", Form.D, 0),
    25: ("oris", Form.D, 0),
    26: ("xori", Form.D, 0),
    27: ("xoris", Form.D, 0),
    28: ("andi.", Form.D, 0),
    29: ("andis.", Form.D, 0),
    32: ("lwz", Form.D, 0),
    33: ("lwzu", Form.D, 0),
    34: ("lbz", Form.D, 0),
    35: ("lbzu", Form.D, 0),
    36: ("stw", Form.D, 0),
    37: ("stwu", Form.D, 0),
    38: ("stb", Form.D, 0),
    39: ("stbu", Form.D, 0),
    40: ("lhz", Form.D, 0),
    41: ("lhzu", Form.D, 0),
    42: ("lha", Form.D, 0),
    43: ("lhau", Form.D, 0),
    44: ("sth", Form.D, 0),
    45: ("sthu", Form.D, 0),
    46: ("lmw", Form.D, 0),
    47: ("stmw", Form.D, 0),
    48: ("lfs", Form.D, 0),
    49: ("lfsu", Form.D, 0),
    50: ("lfd", Form.D, 0),
    51: ("lfdu", Form.D, 0),
    52: ("stfs", Form.D, 0),
    53: ("stfsu", Form.D, 0),
    54: ("stfd", Form.D, 0),
    55: ("stfdu", Form.D, 0),
    # Gekko quantized load/store, D-form
    56: ("psq_l", Form.PSQ, 0),
    57: ("psq_lu", Form.PSQ, 0),
    60: ("psq_st", Form.PSQ, 0),
    61: ("psq_stu", Form.PSQ, 0),
}


# --------------------------------------------------------------------------
# opcode 19 — condition register and branch-to-register (XL-form)
# extended opcode: bits 21-30 (10 bits)
# --------------------------------------------------------------------------

OP19: dict[int, tuple[str, Form, int]] = {
    0: ("mcrf", Form.XL, 0),
    16: ("bclr", Form.XL, LK),
    33: ("crnor", Form.XL, 0),
    50: ("rfi", Form.XL, 0),
    129: ("crandc", Form.XL, 0),
    150: ("isync", Form.XL, 0),
    193: ("crxor", Form.XL, 0),
    225: ("crnand", Form.XL, 0),
    257: ("crand", Form.XL, 0),
    289: ("creqv", Form.XL, 0),
    417: ("crorc", Form.XL, 0),
    449: ("cror", Form.XL, 0),
    528: ("bcctr", Form.XL, LK),
}


# --------------------------------------------------------------------------
# opcode 31 — the main integer / system space
# extended opcode: bits 21-30 (10 bits). XO-form entries also honour OE.
# --------------------------------------------------------------------------

OP31: dict[int, tuple[str, Form, int]] = {
    0: ("cmp", Form.X, 0),
    4: ("tw", Form.X, 0),
    8: ("subfc", Form.XO, RC | OE),
    10: ("addc", Form.XO, RC | OE),
    11: ("mulhwu", Form.XO, RC),
    19: ("mfcr", Form.X, 0),
    20: ("lwarx", Form.X, 0),
    23: ("lwzx", Form.X, 0),
    24: ("slw", Form.X, RC),
    26: ("cntlzw", Form.X, RC),
    28: ("and", Form.X, RC),
    32: ("cmpl", Form.X, 0),
    40: ("subf", Form.XO, RC | OE),
    54: ("dcbst", Form.X, 0),
    55: ("lwzux", Form.X, 0),
    60: ("andc", Form.X, RC),
    75: ("mulhw", Form.XO, RC),
    83: ("mfmsr", Form.X, 0),
    86: ("dcbf", Form.X, 0),
    87: ("lbzx", Form.X, 0),
    104: ("neg", Form.XO, RC | OE),
    119: ("lbzux", Form.X, 0),
    124: ("nor", Form.X, RC),
    136: ("subfe", Form.XO, RC | OE),
    138: ("adde", Form.XO, RC | OE),
    144: ("mtcrf", Form.XFX, 0),
    146: ("mtmsr", Form.X, 0),
    150: ("stwcx.", Form.X, 0),
    151: ("stwx", Form.X, 0),
    183: ("stwux", Form.X, 0),
    200: ("subfze", Form.XO, RC | OE),
    202: ("addze", Form.XO, RC | OE),
    210: ("mtsr", Form.X, 0),
    215: ("stbx", Form.X, 0),
    232: ("subfme", Form.XO, RC | OE),
    234: ("addme", Form.XO, RC | OE),
    235: ("mullw", Form.XO, RC | OE),
    242: ("mtsrin", Form.X, 0),
    246: ("dcbtst", Form.X, 0),
    247: ("stbux", Form.X, 0),
    266: ("add", Form.XO, RC | OE),
    278: ("dcbt", Form.X, 0),
    279: ("lhzx", Form.X, 0),
    284: ("eqv", Form.X, RC),
    306: ("tlbie", Form.X, 0),
    310: ("eciwx", Form.X, 0),
    311: ("lhzux", Form.X, 0),
    316: ("xor", Form.X, RC),
    339: ("mfspr", Form.XFX, 0),
    343: ("lhax", Form.X, 0),
    370: ("tlbia", Form.X, 0),
    371: ("mftb", Form.XFX, 0),
    375: ("lhaux", Form.X, 0),
    407: ("sthx", Form.X, 0),
    412: ("orc", Form.X, RC),
    438: ("ecowx", Form.X, 0),
    439: ("sthux", Form.X, 0),
    444: ("or", Form.X, RC),
    459: ("divwu", Form.XO, RC | OE),
    467: ("mtspr", Form.XFX, 0),
    470: ("dcbi", Form.X, 0),
    476: ("nand", Form.X, RC),
    491: ("divw", Form.XO, RC | OE),
    512: ("mcrxr", Form.X, 0),
    533: ("lswx", Form.X, 0),
    534: ("lwbrx", Form.X, 0),
    535: ("lfsx", Form.X, 0),
    536: ("srw", Form.X, RC),
    566: ("tlbsync", Form.X, 0),
    567: ("lfsux", Form.X, 0),
    595: ("mfsr", Form.X, 0),
    597: ("lswi", Form.X, 0),
    598: ("sync", Form.X, 0),
    599: ("lfdx", Form.X, 0),
    631: ("lfdux", Form.X, 0),
    659: ("mfsrin", Form.X, 0),
    661: ("stswx", Form.X, 0),
    662: ("stwbrx", Form.X, 0),
    663: ("stfsx", Form.X, 0),
    695: ("stfsux", Form.X, 0),
    725: ("stswi", Form.X, 0),
    727: ("stfdx", Form.X, 0),
    759: ("stfdux", Form.X, 0),
    790: ("lhbrx", Form.X, 0),
    792: ("sraw", Form.X, RC),
    824: ("srawi", Form.X, RC),
    854: ("eieio", Form.X, 0),
    918: ("sthbrx", Form.X, 0),
    922: ("extsh", Form.X, RC),
    954: ("extsb", Form.X, RC),
    982: ("icbi", Form.X, 0),
    983: ("stfiwx", Form.X, 0),
    1014: ("dcbz", Form.X, 0),
}


# --------------------------------------------------------------------------
# opcodes 59 and 63 — floating point
# 63 uses 10-bit extended opcodes for X-form ops and 5-bit for A-form.
# --------------------------------------------------------------------------

# A-form (5-bit extended opcode, bits 26-30) — shared by 59 and 63
FLOAT_A: dict[int, tuple[str, Form, int]] = {
    18: ("fdiv", Form.A, RC),
    20: ("fsub", Form.A, RC),
    21: ("fadd", Form.A, RC),
    22: ("fsqrt", Form.A, RC),
    23: ("fsel", Form.A, RC),
    24: ("fres", Form.A, RC),
    25: ("fmul", Form.A, RC),
    26: ("frsqrte", Form.A, RC),
    28: ("fmsub", Form.A, RC),
    29: ("fmadd", Form.A, RC),
    30: ("fnmsub", Form.A, RC),
    31: ("fnmadd", Form.A, RC),
}

# opcode 63 X-form (10-bit extended opcode, bits 21-30)
OP63_X: dict[int, tuple[str, Form, int]] = {
    0: ("fcmpu", Form.X, 0),
    12: ("frsp", Form.X, RC),
    14: ("fctiw", Form.X, RC),
    15: ("fctiwz", Form.X, RC),
    32: ("fcmpo", Form.X, 0),
    38: ("mtfsb1", Form.X, RC),
    40: ("fneg", Form.X, RC),
    64: ("mcrfs", Form.X, 0),
    70: ("mtfsb0", Form.X, RC),
    72: ("fmr", Form.X, RC),
    134: ("mtfsfi", Form.X, RC),
    136: ("fnabs", Form.X, RC),
    264: ("fabs", Form.X, RC),
    583: ("mffs", Form.X, RC),
    711: ("mtfsf", Form.XFL, RC),
}


# --------------------------------------------------------------------------
# opcode 4 — Gekko paired singles
# Three different extended-opcode widths share this primary opcode.
# --------------------------------------------------------------------------

# 5-bit extended opcode (bits 26-30): paired-single arithmetic, A-form
PS_A: dict[int, tuple[str, Form, int]] = {
    10: ("ps_sum0", Form.A, RC),
    11: ("ps_sum1", Form.A, RC),
    12: ("ps_muls0", Form.A, RC),
    13: ("ps_muls1", Form.A, RC),
    14: ("ps_madds0", Form.A, RC),
    15: ("ps_madds1", Form.A, RC),
    18: ("ps_div", Form.A, RC),
    20: ("ps_sub", Form.A, RC),
    21: ("ps_add", Form.A, RC),
    23: ("ps_sel", Form.A, RC),
    24: ("ps_res", Form.A, RC),
    25: ("ps_mul", Form.A, RC),
    26: ("ps_rsqrte", Form.A, RC),
    28: ("ps_msub", Form.A, RC),
    29: ("ps_madd", Form.A, RC),
    30: ("ps_nmsub", Form.A, RC),
    31: ("ps_nmadd", Form.A, RC),
}

# 6-bit extended opcode (bits 25-30): quantized load/store, X-form
PS_QX: dict[int, tuple[str, Form, int]] = {
    6: ("psq_lx", Form.PSQX, 0),
    7: ("psq_stx", Form.PSQX, 0),
    38: ("psq_lux", Form.PSQX, 0),
    39: ("psq_stux", Form.PSQX, 0),
}

# 10-bit extended opcode (bits 21-30): compare, move, merge, cache
PS_X: dict[int, tuple[str, Form, int]] = {
    0: ("ps_cmpu0", Form.X, 0),
    32: ("ps_cmpo0", Form.X, 0),
    40: ("ps_neg", Form.X, RC),
    64: ("ps_cmpu1", Form.X, 0),
    72: ("ps_mr", Form.X, RC),
    96: ("ps_cmpo1", Form.X, 0),
    136: ("ps_nabs", Form.X, RC),
    264: ("ps_abs", Form.X, RC),
    528: ("ps_merge00", Form.X, RC),
    560: ("ps_merge01", Form.X, RC),
    592: ("ps_merge10", Form.X, RC),
    624: ("ps_merge11", Form.X, RC),
    1014: ("dcbz_l", Form.X, 0),
}


# --------------------------------------------------------------------------
# special purpose registers
# --------------------------------------------------------------------------

SPR_NAMES: dict[int, str] = {
    1: "XER",
    8: "LR",
    9: "CTR",
    18: "DSISR",
    19: "DAR",
    22: "DEC",
    25: "SDR1",
    26: "SRR0",
    27: "SRR1",
    272: "SPRG0",
    273: "SPRG1",
    274: "SPRG2",
    275: "SPRG3",
    282: "EAR",
    287: "PVR",
    528: "IBAT0U",
    529: "IBAT0L",
    530: "IBAT1U",
    531: "IBAT1L",
    532: "IBAT2U",
    533: "IBAT2L",
    534: "IBAT3U",
    535: "IBAT3L",
    536: "DBAT0U",
    537: "DBAT0L",
    538: "DBAT1U",
    539: "DBAT1L",
    540: "DBAT2U",
    541: "DBAT2L",
    542: "DBAT3U",
    543: "DBAT3L",
    912: "GQR0",
    913: "GQR1",
    914: "GQR2",
    915: "GQR3",
    916: "GQR4",
    917: "GQR5",
    918: "GQR6",
    919: "GQR7",
    920: "HID2",
    921: "WPAR",
    922: "DMAU",
    923: "DMAL",
    936: "UMMCR0",
    940: "UMMCR1",
    952: "MMCR0",
    953: "PMC1",
    954: "PMC2",
    955: "SIA",
    956: "MMCR1",
    957: "PMC3",
    958: "PMC4",
    1008: "HID0",
    1009: "HID1",
    1010: "IABR",
    1013: "DABR",
    1017: "L2CR",
    1019: "ICTC",
    1020: "THRM1",
    1021: "THRM2",
    1022: "THRM3",
}

GQR_SPRS = range(912, 920)

# Quantized load/store scale types (GQR LD_TYPE / ST_TYPE field).
QUANT_TYPES: dict[int, str] = {
    0: "f32",
    4: "u8",
    5: "u16",
    6: "s8",
    7: "s16",
}
