#!/usr/bin/env python3
"""Decode a captured GX frame (build/fifo/NNNN.{regs,fifo,ram}) into readable text.

    python tools/fifo.py build/fifo/0500                    # the command stream
    python tools/fifo.py build/fifo/0500 --regs             # the registers at frame start
    python tools/fifo.py build/fifo/4200 --verts 1276-1365  # the vertices of those draws

Draws are numbered from 1 in stream order and the listing prints that number,
which is what --verts takes (N, N-M, N-, -M or "all"). With --verts only the
selected draws are printed, one line per vertex: positions, normals, colours
and texture coordinates as the stream carries them, indexed attributes
resolved through the command processor's array base and stride against the
capture's .ram image, and the normal both raw and through the XF normal
matrix -- the latter being what the lighting stage actually dots against the
light direction.

Register names follow the hardware manuals / Dolphin. Analysis only.
"""

import argparse
import struct
import sys
from pathlib import Path

MEM_MASK = 0x01FFFFFF  # what the console's address decode narrows a guest address to

BP_NAMES = {
    0x00: "GEN_MODE",
    0x20: "SU_SCIS0",
    0x21: "SU_SCIS1",
    0x28: "TREF0",
    0x40: "PE_ZMODE",
    0x41: "PE_CMODE0",
    0x42: "PE_CMODE1",
    0x43: "PE_CONTROL",
    0x45: "PE_DONE",
    0x47: "PE_TOKEN",
    0x48: "PE_TOKEN_INT",
    0x49: "EFB_COPY_TL",
    0x4A: "EFB_COPY_WH",
    0x4B: "EFB_COPY_DEST",
    0x4D: "EFB_COPY_STRIDE",
    0x4E: "EFB_COPY_YSCALE",
    0x4F: "PE_CLEAR_AR",
    0x50: "PE_CLEAR_GB",
    0x51: "PE_CLEAR_Z",
    0x52: "PE_COPY_EXECUTE",
    0x59: "SCISSOR_OFFSET",
    0x64: "LOADTLUT0",
    0x65: "LOADTLUT1",
    0xF3: "ALPHA_COMPARE",
    0xFE: "BP_MASK",
}
for i in range(8):
    BP_NAMES[0x28 + i] = f"TREF{i}"
for i in range(16):
    BP_NAMES[0xC0 + 2 * i] = f"TEV{i}_COLOR"
    BP_NAMES[0xC1 + 2 * i] = f"TEV{i}_ALPHA"
for i in range(8):
    BP_NAMES[0x30 + 2 * i] = f"SU_SSIZE{i}"
    BP_NAMES[0x31 + 2 * i] = f"SU_TSIZE{i}"
for i in range(4):
    BP_NAMES[0xE0 + 2 * i] = f"TEVREG{i}_RA"
    BP_NAMES[0xE1 + 2 * i] = f"TEVREG{i}_BG"
    BP_NAMES[0x80 + i] = f"TX_MODE0_{i}"
    BP_NAMES[0x84 + i] = f"TX_MODE1_{i}"
    BP_NAMES[0x88 + i] = f"TX_IMAGE0_{i}"
    BP_NAMES[0x8C + i] = f"TX_IMAGE1_{i}"
    BP_NAMES[0x90 + i] = f"TX_IMAGE2_{i}"
    BP_NAMES[0x94 + i] = f"TX_IMAGE3_{i}"
    BP_NAMES[0x98 + i] = f"TX_TLUT_{i}"
    BP_NAMES[0xA0 + i] = f"TX_MODE0_{i + 4}"
    BP_NAMES[0xA4 + i] = f"TX_MODE1_{i + 4}"
    BP_NAMES[0xA8 + i] = f"TX_IMAGE0_{i + 4}"
    BP_NAMES[0xAC + i] = f"TX_IMAGE1_{i + 4}"
    BP_NAMES[0xB0 + i] = f"TX_IMAGE2_{i + 4}"
    BP_NAMES[0xB4 + i] = f"TX_IMAGE3_{i + 4}"
    BP_NAMES[0xB8 + i] = f"TX_TLUT_{i + 4}"
for i in range(8):
    BP_NAMES[0xF6 + i] = f"TEV_KSEL{i}"

XF_NAMES = {
    0x1005: "CLIP_DISABLE",
    0x1008: "IN_VERTEX_SPEC",
    0x1009: "NUM_COLOR_CHANS",
    0x100A: "AMBIENT0",
    0x100B: "AMBIENT1",
    0x100C: "MATERIAL0",
    0x100D: "MATERIAL1",
    0x100E: "COLOR0_CTRL",
    0x100F: "COLOR1_CTRL",
    0x1010: "ALPHA0_CTRL",
    0x1011: "ALPHA1_CTRL",
    0x1012: "DUAL_TEX_TRANS",
    0x1018: "MATINDEX_A",
    0x1019: "MATINDEX_B",
    0x101A: "VIEWPORT",
    0x1020: "PROJECTION",
    0x1026: "PROJECTION_TYPE",
    0x103F: "NUM_TEXGENS",
}
for i in range(8):
    XF_NAMES[0x1040 + i] = f"TEXGEN{i}"
    XF_NAMES[0x1050 + i] = f"POSTMTX{i}"

CP_NAMES = {
    0x20: "MATINDEX_A",
    0x30: "MATINDEX_A",
    0x40: "MATINDEX_B",
    0x50: "VCD_LO",
    0x60: "VCD_HI",
}
for i in range(8):
    CP_NAMES[0x70 + i] = f"VAT{i}_A"
    CP_NAMES[0x80 + i] = f"VAT{i}_B"
    CP_NAMES[0x90 + i] = f"VAT{i}_C"
for i in range(16):
    CP_NAMES[0xA0 + i] = f"ARRAY_BASE{i}"
    CP_NAMES[0xB0 + i] = f"ARRAY_STRIDE{i}"

PRIMS = {
    0x80: "QUADS",
    0x90: "TRIANGLES",
    0x98: "TRISTRIP",
    0xA0: "TRIFAN",
    0xA8: "LINES",
    0xB0: "LINESTRIP",
    0xB8: "POINTS",
}

ATTR_MODE = ("none", "direct", "idx8", "idx16")
COMP_FMT = ("u8", "s8", "u16", "s16", "f32", "?5", "?6", "?7")
COLOR_FMT = ("rgb565", "rgb8", "rgbx8", "rgba4", "rgba6", "rgba8", "rgba8", "rgba8")
COLOR_BYTES = (2, 3, 4, 2, 3, 4, 4, 4)


def f32(v: int) -> float:
    return struct.unpack(">f", struct.pack(">I", v))[0]


def xff(xf, i: int) -> float:
    """One XF register read as the float the transform unit sees."""
    return f32(xf[i]) if 0 <= i < len(xf) else 0.0


def xf_words(addr: int, vals: list[int]) -> str:
    if (
        addr < 0x1000
        or addr in (0x101A, 0x1020)
        or 0x101A <= addr < 0x1020
        or 0x1020 <= addr < 0x1026
    ):
        return " ".join(f"{f32(v):.4g}" for v in vals)
    return " ".join(f"{v:08X}" for v in vals)


def comp_bytes(fmt: int) -> int:
    return 4 if fmt == 4 else (2 if fmt >= 2 else 1)


class Attr:
    """One vertex attribute: where its bytes live and how to read them.

    `elem` is the size of one element wherever it sits -- inline in the stream
    for a direct attribute, in the array for an indexed one -- while
    `stream_bytes` is what the vertex itself spends on it, which for an
    indexed attribute is just the index.
    """

    __slots__ = ("array", "comps", "elem", "fmt", "frac", "kind", "mode", "name", "triple")

    def __init__(self, name, mode, array, comps, fmt, frac, elem, kind="num", triple=False):
        self.name = name
        self.mode = mode
        self.array = array
        self.comps = comps
        self.fmt = fmt
        self.frac = frac
        self.elem = elem
        self.kind = kind
        self.triple = triple

    @property
    def stream_bytes(self) -> int:
        if self.mode == 0:
            return 0
        if self.mode == 1:
            return self.elem
        width = 1 if self.mode == 2 else 2
        return 3 * width if self.triple else width


def vertex_layout(cp: dict, vat: int) -> list[Attr]:
    """The attributes of one vertex, in the order the stream carries them."""
    lo, hi = cp.get(0x50, 0), cp.get(0x60, 0)
    a, b, c = cp.get(0x70 + vat, 0), cp.get(0x80 + vat, 0), cp.get(0x90 + vat, 0)
    attrs: list[Attr] = []

    if lo & 1:
        attrs.append(Attr("pmtx", 1, -1, 1, 0, 0, 1, "mtxidx"))
    for i in range(8):
        if (lo >> (1 + i)) & 1:
            attrs.append(Attr(f"tmtx{i}", 1, -1, 1, 0, 0, 1, "mtxidx"))

    cnt, fmt, frac = (3 if a & 1 else 2), (a >> 1) & 7, (a >> 4) & 31
    attrs.append(
        Attr("pos", (lo >> 9) & 3, 0, cnt, fmt, 0 if fmt == 4 else frac, cnt * comp_bytes(fmt))
    )

    mode, elems, fmt = (lo >> 11) & 3, (a >> 9) & 1, (a >> 10) & 7
    # Normals are quantised by format, not by a VAT shift field (GXSetVtxAttrFmt).
    frac = 6 if fmt == 1 else (14 if fmt == 3 else 0)
    triple = bool(mode >= 2 and elems and (a >> 31) & 1)
    elem = 3 * comp_bytes(fmt) if triple else (9 if elems else 3) * comp_bytes(fmt)
    attrs.append(Attr("nrm", mode, 1, 3, fmt, frac, elem, triple=triple))

    for i in range(2):
        mode = (lo >> (13 + 2 * i)) & 3
        fmt = ((a >> 14) if i == 0 else (a >> 18)) & 7
        attrs.append(Attr(f"clr{i}", mode, 2 + i, 4, fmt, 0, COLOR_BYTES[fmt], "color"))

    tc = [
        ((a >> 21) & 1, (a >> 22) & 7, (a >> 25) & 31),
        (b & 1, (b >> 1) & 7, (b >> 4) & 31),
        ((b >> 9) & 1, (b >> 10) & 7, (b >> 13) & 31),
        ((b >> 18) & 1, (b >> 19) & 7, (b >> 22) & 31),
        ((b >> 27) & 1, (b >> 28) & 7, c & 31),
        ((c >> 5) & 1, (c >> 6) & 7, (c >> 9) & 31),
        ((c >> 14) & 1, (c >> 15) & 7, (c >> 18) & 31),
        ((c >> 23) & 1, (c >> 24) & 7, (c >> 27) & 31),
    ]
    for i in range(8):
        cnt, fmt, frac = 2 if tc[i][0] else 1, tc[i][1], tc[i][2]
        attrs.append(
            Attr(
                f"tex{i}",
                (hi >> (2 * i)) & 3,
                4 + i,
                cnt,
                fmt,
                0 if fmt == 4 else frac,
                cnt * comp_bytes(fmt),
            )
        )
    return attrs


def vertex_size(cp: dict, vat: int) -> int:
    return sum(at.stream_bytes for at in vertex_layout(cp, vat))


def read_comp(buf, off: int, fmt: int, frac: int) -> float:
    if fmt == 4:
        return struct.unpack_from(">f", buf, off)[0]
    if fmt == 0:
        v = buf[off]
    elif fmt == 1:
        v = struct.unpack_from(">b", buf, off)[0]
    elif fmt == 2:
        v = struct.unpack_from(">H", buf, off)[0]
    else:
        v = struct.unpack_from(">h", buf, off)[0]
    return v / float(1 << frac)


def read_color(buf, off: int, fmt: int) -> tuple[float, float, float, float]:
    if fmt == 0:  # RGB565
        v = struct.unpack_from(">H", buf, off)[0]
        return ((v >> 11) & 31) / 31.0, ((v >> 5) & 63) / 63.0, (v & 31) / 31.0, 1.0
    if fmt in (1, 2):  # RGB8, RGBX8
        return buf[off] / 255.0, buf[off + 1] / 255.0, buf[off + 2] / 255.0, 1.0
    if fmt == 3:  # RGBA4
        v = struct.unpack_from(">H", buf, off)[0]
        return (
            ((v >> 12) & 15) / 15.0,
            ((v >> 8) & 15) / 15.0,
            ((v >> 4) & 15) / 15.0,
            (v & 15) / 15.0,
        )
    if fmt == 4:  # RGBA6
        v = (buf[off] << 16) | (buf[off + 1] << 8) | buf[off + 2]
        return (
            ((v >> 18) & 63) / 63.0,
            ((v >> 12) & 63) / 63.0,
            ((v >> 6) & 63) / 63.0,
            (v & 63) / 63.0,
        )
    return buf[off] / 255.0, buf[off + 1] / 255.0, buf[off + 2] / 255.0, buf[off + 3] / 255.0


def array_elem(cp: dict, ram, array: int, idx: int, size: int):
    """Resolve an indexed attribute: CP ARRAY_BASE/ARRAY_STRIDE into the RAM image.

    Returns (buffer, offset, address); buffer is None when there is no image or
    the element falls outside it, which is the same condition the runtime
    counts as a bad vertex reference.
    """
    base = cp.get(0xA0 + array, 0) & 0x1FFFFFFF
    stride = cp.get(0xB0 + array, 0) & 0xFF
    addr = base + idx * stride
    off = addr & MEM_MASK
    if ram is None or off + size > len(ram):
        return None, 0, addr
    return ram, off, addr


def read_vertex(layout: list[Attr], buf, off: int, cp: dict, ram):
    """One vertex from the stream at `off`; returns (values, next offset)."""
    vals: dict[str, object] = {}
    for at in layout:
        if at.mode == 0:
            continue
        if at.kind == "mtxidx":
            vals[at.name] = buf[off]
            off += 1
            continue
        if at.mode == 1:
            src, soff, addr = buf, off, None
        else:
            width = 1 if at.mode == 2 else 2
            idx = int.from_bytes(bytes(buf[off : off + width]), "big")
            # An NBT triple spends three indices and the lighting uses the first.
            src, soff, addr = array_elem(cp, ram, at.array, idx, at.elem)
            vals[at.name + ".at"] = (idx, addr)
        off += at.stream_bytes
        if src is None:
            vals[at.name] = None
        elif at.kind == "color":
            vals[at.name] = read_color(src, soff, at.fmt)
        else:
            nb = comp_bytes(at.fmt)
            vals[at.name] = [
                read_comp(src, soff + k * nb, at.fmt, at.frac) for k in range(at.comps)
            ]
    return vals, off


def transform_normal(xf, posidx: int, nrm) -> list[float]:
    """The normal the lighting sees: XF normal matrix for this position index,
    then normalised, exactly as the transform unit does it."""
    nb = 0x400 + 3 * (posidx & 0x3F)
    out = [
        xff(xf, nb + 3 * r) * nrm[0]
        + xff(xf, nb + 3 * r + 1) * nrm[1]
        + xff(xf, nb + 3 * r + 2) * nrm[2]
        for r in range(3)
    ]
    length = (out[0] ** 2 + out[1] ** 2 + out[2] ** 2) ** 0.5
    return [c / length for c in out] if length > 1e-12 else out


def transform_position(xf, posidx: int, pos) -> list[float]:
    """View-space position: the XF position matrix applied as a 3x4."""
    row0 = 4 * (posidx & 0x3F)
    p = list(pos) + [0.0] * (3 - len(pos)) + [1.0]
    return [
        xff(xf, row0 + 4 * r) * p[0]
        + xff(xf, row0 + 4 * r + 1) * p[1]
        + xff(xf, row0 + 4 * r + 2) * p[2]
        + xff(xf, row0 + 4 * r + 3)
        for r in range(3)
    ]


def layout_summary(layout: list[Attr], cp: dict) -> str:
    parts = []
    for at in layout:
        if at.mode == 0:
            continue
        if at.kind == "mtxidx":
            parts.append(f"{at.name}=direct/u8")
            continue
        fmt = COLOR_FMT[at.fmt] if at.kind == "color" else f"{COMP_FMT[at.fmt]}x{at.comps}"
        s = f"{at.name}={ATTR_MODE[at.mode]}/{fmt}"
        if at.frac:
            s += f">>{at.frac}"
        if at.triple:
            s += "/nbt3"
        if at.mode >= 2:
            base = cp.get(0xA0 + at.array, 0) & 0x1FFFFFFF
            stride = cp.get(0xB0 + at.array, 0) & 0xFF
            s += f"@arr{at.array}[{base:08X}+{stride}]"
        parts.append(s)
    return " ".join(parts)


def fmt_vec(v, digits: int) -> str:
    return "(" + ", ".join(f"{c:.{digits}f}" for c in v) + ")"


def dump_vertices(fifo: bytes, off: int, count: int, layout, cp, xf, ram, out):
    """Print one line per vertex of a draw whose payload starts at `off`."""
    out.append(f"    {layout_summary(layout, cp)}")
    default_posidx = xf[0x1018] & 0x3F
    for i in range(count):
        vals, off = read_vertex(layout, fifo, off, cp, ram)
        posidx = vals.get("pmtx", default_posidx) & 0x3F
        cells = [f"v{i:<3d} pmtx {posidx:2d}"]
        pos = vals.get("pos")
        if pos is None and "pos" in vals:
            cells.append("pos <unresolved>")
        elif pos is not None:
            cells.append(f"pos {fmt_vec(pos, 3)}")
            cells.append(f"view {fmt_vec(transform_position(xf, posidx, pos), 3)}")
        nrm = vals.get("nrm")
        if nrm is None and "nrm" in vals:
            cells.append("nrm <unresolved>")
        elif nrm is not None:
            cells.append(
                f"nrm {fmt_vec(nrm, 4)} -> {fmt_vec(transform_normal(xf, posidx, nrm), 4)}"
            )
        for k in range(2):
            col = vals.get(f"clr{k}")
            if col is not None:
                cells.append(f"clr{k} ({', '.join(f'{round(c * 255)}' for c in col)})")
            elif f"clr{k}" in vals:
                cells.append(f"clr{k} <unresolved>")
        for k in range(8):
            tex = vals.get(f"tex{k}")
            at = vals.get(f"tex{k}.at")
            where = f"@{at[1]:08X}" if at else ""
            if tex is not None:
                cells.append(f"tex{k}{where} {fmt_vec(tex, 4)}")
            elif f"tex{k}" in vals:
                cells.append(f"tex{k}{where} <unresolved>")
        out.append("      " + " ".join(cells))
    return off


def walk(buf, cp: dict, xf, ram=None, bp=None, follow_lists: bool = False):
    """Walk a command stream, one command at a time, applying each register
    write to `cp`, `xf` and (when given) `bp` before yielding the command, so
    whoever consumes a draw sees the state it was issued under.

    Every item is a tuple that starts (kind, offset, list): `offset` is where
    the command starts in whatever holds it, and `list` is None for a command
    in the stream itself or the address of the display list it sits in. Then,
    by kind:

      "nop", "inval"                      nothing more
      "cp"          reg, value
      "xf"          address, values       (one int per register written)
      "xf_indexed"  array, index, first register, count, source address
      "call"        address, size         a display-list call
      "bp"          reg, value            (the 24-bit payload)
      "draw"        opcode, count, layout, bytes per vertex, buffer, offset
                    -- the last two are where the vertices can be read from
      "unknown"     opcode                (skipped one byte at a time)

    With `follow_lists` a call is followed into `ram` the way the runtime's
    parser follows it (gx.c parse): one level deep, only when the list lies
    wholly inside the image, and a command the end of a list cuts off ends the
    list. Without it -- decode's listing -- a call is only reported.
    """
    yield from _walk(buf, 0, len(buf), None, cp, xf, ram, bp, follow_lists)


def _walk(buf, start: int, end: int, where, cp, xf, ram, bp, follow: bool):
    inside = where is not None
    off = start
    while off < end:
        op = buf[off]
        rel = off - start
        if op == 0x00 or op == 0x48:
            yield ("nop" if op == 0 else "inval", rel, where)
            off += 1
        elif op == 0x08:
            if inside and off + 6 > end:
                return
            reg, val = buf[off + 1], int.from_bytes(buf[off + 2 : off + 6], "big")
            cp[reg] = val
            yield ("cp", rel, where, reg, val)
            off += 6
        elif op == 0x10:
            n = int.from_bytes(buf[off + 1 : off + 3], "big") + 1
            if inside and off + 5 + 4 * n > end:
                return
            addr = int.from_bytes(buf[off + 3 : off + 5], "big")
            vals = [int.from_bytes(buf[off + 5 + 4 * i : off + 9 + 4 * i], "big") for i in range(n)]
            for i, v in enumerate(vals):
                if addr + i < len(xf):
                    xf[addr + i] = v
            yield ("xf", rel, where, addr, vals)
            off += 5 + 4 * n
        elif op in (0x20, 0x28, 0x30, 0x38):
            if inside and off + 5 > end:
                return
            idx = int.from_bytes(buf[off + 1 : off + 3], "big")
            v = int.from_bytes(buf[off + 3 : off + 5], "big")
            array = 12 + (op - 0x20) // 8
            dst, n = v & 0xFFF, (v >> 12) + 1
            src, soff, addr = array_elem(cp, ram, array, idx, 4 * n)
            if src is not None:
                for i in range(n):
                    if dst + i < len(xf):
                        xf[dst + i] = int.from_bytes(
                            bytes(src[soff + 4 * i : soff + 4 * i + 4]), "big"
                        )
            yield ("xf_indexed", rel, where, array, idx, dst, n, addr)
            off += 5
        elif op == 0x40:
            if inside and off + 9 > end:
                return
            addr = int.from_bytes(buf[off + 1 : off + 5], "big")
            size = int.from_bytes(buf[off + 5 : off + 9], "big")
            yield ("call", rel, where, addr, size)
            off += 9
            if follow and not inside and ram is not None:
                lo = addr & MEM_MASK
                if size <= len(ram) and lo <= len(ram) - size:
                    yield from _walk(ram, lo, lo + size, addr, cp, xf, ram, bp, follow)
        elif op == 0x61:
            if inside and off + 5 > end:
                return
            v = int.from_bytes(buf[off + 1 : off + 5], "big")
            reg = v >> 24
            if bp is not None:
                bp[reg] = v & 0xFFFFFF
            yield ("bp", rel, where, reg, v & 0xFFFFFF)
            off += 5
        elif 0x80 <= op < 0xC0:
            if inside and off + 3 > end:
                return
            n = int.from_bytes(buf[off + 1 : off + 3], "big")
            layout = vertex_layout(cp, op & 7)
            vs = sum(at.stream_bytes for at in layout)
            if inside and off + 3 + n * vs > end:
                return
            yield ("draw", rel, where, op, n, layout, vs, buf, off + 3)
            off += 3 + n * vs
        else:
            yield ("unknown", rel, where, op)
            off += 1


def decode(fifo: bytes, cp: dict, out, xf=None, ram=None, verts=None):
    """Walk the command stream. `verts` is an inclusive (first, last) range of
    draw numbers whose vertices to print; when it is set nothing else is."""
    if xf is None:
        xf = [0] * 4352
    quiet = verts is not None
    nops = 0
    draw = 0

    def emit(line):
        if not quiet:
            out.append(line)

    for cmd in walk(fifo, cp, xf, ram):
        kind = cmd[0]
        if kind == "nop":
            nops += 1
            continue
        if nops:
            emit(f"  ({nops} nops)")
            nops = 0
        if kind == "inval":
            emit("  INVALIDATE_VTX_CACHE")
        elif kind == "cp":
            reg, val = cmd[3:]
            emit(f"  CP {reg:02X} {CP_NAMES.get(reg, ''):<14} = {val:08X}")
        elif kind == "xf":
            addr, vals = cmd[3:]
            name = XF_NAMES.get(addr, "MTX" if addr < 0x1000 else "")
            emit(f"  XF {addr:04X} {name:<14} x{len(vals)}: {xf_words(addr, vals)}")
        elif kind == "xf_indexed":
            array, idx, dst, n, addr = cmd[3:]
            emit(f"  XF_INDEXED array {array} index {idx} -> {dst:04X} x{n} (from {addr:08X})")
        elif kind == "call":
            addr, size = cmd[3:]
            emit(f"  DISPLAY_LIST {addr:08X} size {size}")
        elif kind == "bp":
            reg, val = cmd[3:]
            emit(f"  BP {reg:02X} {BP_NAMES.get(reg, ''):<16} = {val:06X}")
        elif kind == "draw":
            op, n, layout, vs, buf, voff = cmd[3:]
            draw += 1
            line = (
                f"  DRAW #{draw} {PRIMS.get(op & 0xF8, hex(op))} vat {op & 7} "
                f"count {n} ({vs} bytes/vertex)"
            )
            if verts is not None and verts[0] <= draw <= verts[1]:
                out.append(line)
                dump_vertices(buf, voff, n, layout, cp, xf, ram, out)
            else:
                emit(line)
        else:
            emit(f"  ?? {cmd[3]:02X}")
    if nops:
        emit(f"  ({nops} nops)")


def parse_range(spec: str) -> tuple[int, int]:
    """An inclusive draw-number range from 12, 12-30, 12-, -30 or all."""
    spec = spec.strip()
    if spec == "all":
        return 1, 1 << 30
    if "-" not in spec:
        n = int(spec)
        return n, n
    first, last = spec.split("-", 1)
    return int(first) if first else 1, int(last) if last else 1 << 30


def read_regs(path) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    """A capture's .regs: the CP, XF and BP shadows as the frame began, as
    gx.c frame_end writes them (256 + 4352 + 256 little-endian words)."""
    regs = Path(path).read_bytes()
    cp_regs = struct.unpack("<256I", regs[:1024])
    xf_regs = struct.unpack("<4352I", regs[1024 : 1024 + 4352 * 4])
    bp_regs = struct.unpack("<256I", regs[1024 + 4352 * 4 :])
    return cp_regs, xf_regs, bp_regs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base")
    ap.add_argument("--regs", action="store_true")
    ap.add_argument("--verts", metavar="RANGE", help="print the vertices of draws N, N-M or all")
    ap.add_argument(
        "--ram", metavar="PATH", help="RAM image for indexed attributes (default BASE.ram)"
    )
    args = ap.parse_args()
    cp_regs, xf_regs, bp_regs = read_regs(args.base + ".regs")
    cp = {i: v for i, v in enumerate(cp_regs) if v}
    if args.regs:
        for i, v in enumerate(cp_regs):
            if v:
                print(f"CP {i:02X} {CP_NAMES.get(i, ''):<14} = {v:08X}")
        for i, v in enumerate(xf_regs):
            if v and i >= 0x1000:
                print(f"XF {i:04X} {XF_NAMES.get(i, ''):<14} = {v:08X} ({f32(v):.4g})")
        for i, v in enumerate(bp_regs):
            if v:
                print(f"BP {i:02X} {BP_NAMES.get(i, ''):<16} = {v:06X}")
        return 0
    ram_path = Path(args.ram) if args.ram else Path(args.base + ".ram")
    ram = ram_path.read_bytes() if ram_path.exists() else None
    if ram is None and args.verts:
        print(
            f"note: {ram_path} is missing; indexed attributes cannot be resolved", file=sys.stderr
        )
    out: list[str] = []
    decode(
        Path(args.base + ".fifo").read_bytes(),
        cp,
        out,
        xf=list(xf_regs),
        ram=ram,
        verts=parse_range(args.verts) if args.verts else None,
    )
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
