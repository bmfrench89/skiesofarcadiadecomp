"""PowerPC 750CL (Gekko) instruction decoder.

    from soa.ppc import decode
    insn = decode.decode(word, addr)
    if insn.valid:
        print(insn.mnemonic, insn.operands)

The decoder is total: every 32-bit word produces an Insn. Words that do not
correspond to a real instruction come back with `valid=False` rather than
raising, because text sections legitimately contain embedded data (jump
tables, constant pools) and the caller decides what to do about it.
"""

from dataclasses import dataclass

from . import isa
from .isa import AA, LK, OE, RC, Form

# --------------------------------------------------------------------------
# field extraction
# --------------------------------------------------------------------------


def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def opcd(w: int) -> int:
    return (w >> 26) & 0x3F


def _rd(w: int) -> int:
    return (w >> 21) & 0x1F


def _ra(w: int) -> int:
    return (w >> 16) & 0x1F


def _rb(w: int) -> int:
    return (w >> 11) & 0x1F


def _rc_reg(w: int) -> int:
    return (w >> 6) & 0x1F


def spr_number(w: int) -> int:
    """SPR fields are stored with their two 5-bit halves swapped."""
    return ((w >> 16) & 0x1F) | (((w >> 11) & 0x1F) << 5)


@dataclass(frozen=True)
class Insn:
    addr: int
    word: int
    mnemonic: str = "?"
    form: Form | None = None
    valid: bool = False

    # register operands (-1 when unused)
    rd: int = -1
    ra: int = -1
    rb: int = -1
    rc: int = -1

    # immediates
    imm: int = 0  # SIMM / UIMM / d / LI / BD / SH
    mb: int = 0
    me: int = 0
    bo: int = 0
    bi: int = 0
    crf_d: int = 0
    crf_s: int = 0
    spr: int = -1

    # quantized load/store
    gqr: int = -1
    quant_w: int = 0

    # optional bits
    rc_bit: bool = False  # record -> CR update
    oe_bit: bool = False  # overflow enable
    lk_bit: bool = False  # link
    aa_bit: bool = False  # absolute address

    # ---- classification helpers -------------------------------------------

    @property
    def is_branch(self) -> bool:
        return self.mnemonic in _BRANCH

    @property
    def is_direct_branch(self) -> bool:
        return self.mnemonic in ("b", "bc")

    @property
    def is_indirect_branch(self) -> bool:
        return self.mnemonic in ("bclr", "bcctr")

    @property
    def is_call(self) -> bool:
        """A branch that sets LR: the caller expects to come back."""
        return self.is_branch and self.lk_bit

    @property
    def is_return(self) -> bool:
        """Unconditional blr — BO=20 means branch always."""
        return self.mnemonic == "bclr" and not self.lk_bit and self.bo == 20

    @property
    def is_unconditional(self) -> bool:
        if self.mnemonic == "b":
            return True
        # BO bits 2 and 4 both set => ignore CTR and condition
        return self.mnemonic in ("bc", "bclr", "bcctr") and (self.bo & 0b10100) == 0b10100

    @property
    def target(self) -> int | None:
        """Resolved target for a direct branch, else None."""
        if self.mnemonic in ("b", "bc"):
            # Mask both paths: an absolute branch with a negative displacement
            # must wrap to a 32-bit address, not stay a negative Python int.
            return (self.imm if self.aa_bit else self.addr + self.imm) & 0xFFFFFFFF
        return None

    @property
    def writes_ctr(self) -> bool:
        return self.mnemonic == "mtspr" and self.spr == 9

    @property
    def writes_gqr(self) -> bool:
        return self.mnemonic == "mtspr" and self.spr in isa.GQR_SPRS

    @property
    def is_paired_single(self) -> bool:
        return self.mnemonic.startswith("ps_") or self.mnemonic.startswith("psq_")


_BRANCH = frozenset({"b", "bc", "bclr", "bcctr"})

# Words that appear constantly and are worth naming for readability.
NOP = 0x60000000
BLR = 0x4E800020
BCTR = 0x4E800420


# --------------------------------------------------------------------------
# decode
# --------------------------------------------------------------------------


def _flags(w: int, allowed: int) -> tuple[bool, bool, bool, bool]:
    return (
        bool(allowed & RC) and bool(w & 1),
        bool(allowed & OE) and bool((w >> 10) & 1),
        bool(allowed & LK) and bool(w & 1),
        bool(allowed & AA) and bool((w >> 1) & 1),
    )


def decode(word: int, addr: int = 0) -> Insn:
    """Decode one big-endian instruction word. Always returns an Insn."""
    word &= 0xFFFFFFFF
    op = opcd(word)

    entry = None
    if op == 4:
        entry = _decode_op4(word)
    elif op == 19:
        entry = isa.OP19.get((word >> 1) & 0x3FF)
    elif op == 31:
        entry = _decode_op31(word)
    elif op == 59:
        entry = isa.FLOAT_A_SINGLE.get((word >> 1) & 0x1F)
    elif op == 63:
        ext5 = (word >> 1) & 0x1F
        entry = isa.FLOAT_A_DOUBLE.get(ext5) if ext5 >= 18 else None
        if entry is None:
            entry = isa.OP63_X.get((word >> 1) & 0x3FF)
    else:
        entry = isa.PRIMARY.get(op)

    if entry is None:
        return Insn(addr=addr, word=word)

    mnemonic, form, allowed = entry

    # The compare instructions carry an L field at bit 21 selecting a 64-bit
    # compare. The 750CL is 32-bit only, so L=1 is an invalid form and must not
    # be silently decoded as the 32-bit instruction.
    if mnemonic in ("cmp", "cmpl", "cmpi", "cmpli") and (word >> 21) & 1:
        return Insn(addr=addr, word=word)
    rc_bit, oe_bit, lk_bit, aa_bit = _flags(word, allowed)

    kw = dict(
        addr=addr,
        word=word,
        mnemonic=mnemonic,
        form=form,
        valid=True,
        rc_bit=rc_bit,
        oe_bit=oe_bit,
        lk_bit=lk_bit,
        aa_bit=aa_bit,
    )

    if form is Form.I:
        kw["imm"] = sign_extend(word & 0x03FFFFFC, 26)

    elif form is Form.B:
        kw.update(bo=_rd(word), bi=_ra(word), imm=sign_extend(word & 0xFFFC, 16))

    elif form is Form.D:
        signed = mnemonic not in ("ori", "oris", "xori", "xoris", "andi.", "andis.", "cmpli")
        imm = word & 0xFFFF
        kw.update(
            rd=_rd(word),
            ra=_ra(word),
            imm=sign_extend(imm, 16) if signed else imm,
            crf_d=(word >> 23) & 7,
        )

    elif form is Form.M:
        kw.update(
            rd=_rd(word),  # rS
            ra=_ra(word),
            rb=_rb(word),  # rB for rlwnm, SH for rlwinm/rlwimi
            imm=_rb(word),
            mb=(word >> 6) & 0x1F,
            me=(word >> 1) & 0x1F,
        )

    elif form is Form.XO:
        kw.update(rd=_rd(word), ra=_ra(word), rb=_rb(word))

    elif form is Form.A:
        kw.update(rd=_rd(word), ra=_ra(word), rb=_rb(word), rc=_rc_reg(word))

    elif form is Form.XL:
        kw.update(
            bo=_rd(word),
            bi=_ra(word),
            crf_d=(word >> 23) & 7,
            crf_s=(word >> 18) & 7,
        )

    elif form is Form.XFX:
        kw.update(rd=_rd(word))
        if mnemonic in ("mfspr", "mtspr", "mftb"):
            spr = spr_number(word)
            kw["spr"] = spr
            # The time-base halves are separate mnemonics: TBL (268) is mftb,
            # TBU (269) is mftbu.
            if mnemonic == "mftb" and spr == isa.SPR_TBU:
                kw["mnemonic"] = "mftbu"
        elif mnemonic == "mtcrf":
            kw["imm"] = (word >> 12) & 0xFF

    elif form is Form.XFL:
        kw.update(rb=_rb(word), imm=(word >> 17) & 0xFF)

    elif form is Form.PSQ:
        kw.update(
            rd=_rd(word),
            ra=_ra(word),
            quant_w=(word >> 15) & 1,
            gqr=(word >> 12) & 7,
            imm=sign_extend(word & 0xFFF, 12),
        )

    elif form is Form.PSQX:
        kw.update(
            rd=_rd(word),
            ra=_ra(word),
            rb=_rb(word),
            quant_w=(word >> 10) & 1,
            gqr=(word >> 7) & 7,
        )

    else:  # Form.X and Form.SC
        kw.update(
            rd=_rd(word),
            ra=_ra(word),
            rb=_rb(word),
            crf_d=(word >> 23) & 7,
            crf_s=(word >> 18) & 7,
        )
        if mnemonic == "srawi":
            kw["imm"] = _rb(word)

    return Insn(**kw)


def _decode_op31(word: int):
    """Primary opcode 31 mixes two extended-opcode widths.

    X-form uses the full 10-bit field at bits 1-10. XO-form (the arithmetic
    that can set the overflow flag) uses only 9 bits, because bit 10 is the OE
    bit. So `addo` and `add` share extended opcode 266 and differ by bit 10.

    Try the 10-bit field first; on a miss, clear the OE bit and retry, but only
    accept an entry that actually permits OE.
    """
    ext = (word >> 1) & 0x3FF
    entry = isa.OP31.get(ext)
    if entry is not None:
        return entry

    candidate = isa.OP31.get(ext & 0x1FF)
    if candidate is not None and (candidate[2] & OE):
        return candidate
    return None


def _decode_op4(word: int):
    """Primary opcode 4 packs three extended-opcode widths.

    Try the 5-bit A-form field first (its value range is disjoint from the
    others), then the 6-bit quantized load/store field, then the 10-bit field.
    """
    ext5 = (word >> 1) & 0x1F
    if ext5 in isa.PS_A:
        return isa.PS_A[ext5]

    ext6 = (word >> 1) & 0x3F
    if ext6 in isa.PS_QX:
        return isa.PS_QX[ext6]

    return isa.PS_X.get((word >> 1) & 0x3FF)


def decode_stream(data: bytes, base_addr: int = 0):
    """Decode a big-endian instruction stream, yielding one Insn per word."""
    for i in range(0, len(data) - 3, 4):
        word = int.from_bytes(data[i : i + 4], "big")
        yield decode(word, base_addr + i)
