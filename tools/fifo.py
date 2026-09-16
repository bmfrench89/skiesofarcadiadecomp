#!/usr/bin/env python3
"""Decode a captured GX frame (build/fifo/NNNN.{regs,fifo}) into readable text.

    python tools/fifo.py build/fifo/0500            # the command stream
    python tools/fifo.py build/fifo/0500 --regs     # the register state at frame start

Register names follow the hardware manuals / Dolphin. Analysis only.
"""

import argparse
import struct
import sys
from pathlib import Path

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


def f32(v: int) -> float:
    return struct.unpack(">f", struct.pack(">I", v))[0]


def xf_words(addr: int, vals: list[int]) -> str:
    if (
        addr < 0x1000
        or addr in (0x101A, 0x1020)
        or 0x101A <= addr < 0x1020
        or 0x1020 <= addr < 0x1026
    ):
        return " ".join(f"{f32(v):.4g}" for v in vals)
    return " ".join(f"{v:08X}" for v in vals)


def vertex_size(cp: dict, vat: int) -> int:
    lo, hi = cp.get(0x50, 0), cp.get(0x60, 0)
    a, b, c = cp.get(0x70 + vat, 0), cp.get(0x80 + vat, 0), cp.get(0x90 + vat, 0)

    def comp(fmt):
        return 4 if fmt == 4 else (2 if fmt >= 2 else 1)

    def attr(vcd, direct):
        return (0, direct, 1, 2)[vcd & 3]

    size = (lo & 1) + sum((lo >> (1 + i)) & 1 for i in range(8))
    size += attr((lo >> 9) & 3, (3 if a & 1 else 2) * comp((a >> 1) & 7))
    vcd, elems, fmt = (lo >> 11) & 3, (a >> 9) & 1, (a >> 10) & 7
    if vcd >= 2 and elems and (a >> 31) & 1:
        size += 3 * (1 if vcd == 2 else 2)
    else:
        size += attr(vcd, (9 if elems else 3) * comp(fmt))
    csz = [2, 3, 4, 2, 3, 4, 4, 4]
    size += attr((lo >> 13) & 3, csz[(a >> 14) & 7])
    size += attr((lo >> 15) & 3, csz[(a >> 18) & 7])
    tc = [
        ((a >> 21) & 1, (a >> 22) & 7),
        (b & 1, (b >> 1) & 7),
        ((b >> 9) & 1, (b >> 10) & 7),
        ((b >> 18) & 1, (b >> 19) & 7),
        ((b >> 27) & 1, (b >> 28) & 7),
        ((c >> 5) & 1, (c >> 6) & 7),
        ((c >> 14) & 1, (c >> 15) & 7),
        ((c >> 23) & 1, (c >> 24) & 7),
    ]
    for i in range(8):
        size += attr((hi >> (2 * i)) & 3, (2 if tc[i][0] else 1) * comp(tc[i][1]))
    return size


def decode(fifo: bytes, cp: dict, out):
    off = 0
    nops = 0
    while off < len(fifo):
        op = fifo[off]
        if op == 0x00:
            nops += 1
            off += 1
            continue
        if nops:
            out.append(f"  ({nops} nops)")
            nops = 0
        if op == 0x48:
            out.append("  INVALIDATE_VTX_CACHE")
            off += 1
        elif op == 0x08:
            reg, val = fifo[off + 1], int.from_bytes(fifo[off + 2 : off + 6], "big")
            cp[reg] = val
            out.append(f"  CP {reg:02X} {CP_NAMES.get(reg, ''):<14} = {val:08X}")
            off += 6
        elif op == 0x10:
            n = int.from_bytes(fifo[off + 1 : off + 3], "big") + 1
            addr = int.from_bytes(fifo[off + 3 : off + 5], "big")
            vals = [
                int.from_bytes(fifo[off + 5 + 4 * i : off + 9 + 4 * i], "big") for i in range(n)
            ]
            name = XF_NAMES.get(addr, "MTX" if addr < 0x1000 else "")
            out.append(f"  XF {addr:04X} {name:<14} x{n}: {xf_words(addr, vals)}")
            off += 5 + 4 * n
        elif op in (0x20, 0x28, 0x30, 0x38):
            idx = int.from_bytes(fifo[off + 1 : off + 3], "big")
            v = int.from_bytes(fifo[off + 3 : off + 5], "big")
            out.append(
                f"  XF_INDEXED array {12 + (op - 0x20) // 8} index {idx} -> {v & 0xFFF:04X} x{(v >> 12) + 1}"
            )
            off += 5
        elif op == 0x40:
            addr = int.from_bytes(fifo[off + 1 : off + 5], "big")
            size = int.from_bytes(fifo[off + 5 : off + 9], "big")
            out.append(f"  DISPLAY_LIST {addr:08X} size {size}")
            off += 9
        elif op == 0x61:
            v = int.from_bytes(fifo[off + 1 : off + 5], "big")
            reg = v >> 24
            out.append(f"  BP {reg:02X} {BP_NAMES.get(reg, ''):<16} = {v & 0xFFFFFF:06X}")
            off += 5
        elif 0x80 <= op < 0xC0:
            n = int.from_bytes(fifo[off + 1 : off + 3], "big")
            vat = op & 7
            vs = vertex_size(cp, vat)
            out.append(
                f"  DRAW {PRIMS.get(op & 0xF8, hex(op))} vat {vat} count {n} ({vs} bytes/vertex)"
            )
            off += 3 + n * vs
        else:
            out.append(f"  ?? {op:02X}")
            off += 1
    if nops:
        out.append(f"  ({nops} nops)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base")
    ap.add_argument("--regs", action="store_true")
    args = ap.parse_args()
    regs = Path(args.base + ".regs").read_bytes()
    cp_regs = struct.unpack("<256I", regs[:1024])
    xf_regs = struct.unpack("<4352I", regs[1024 : 1024 + 4352 * 4])
    bp_regs = struct.unpack("<256I", regs[1024 + 4352 * 4 :])
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
    out: list[str] = []
    decode(Path(args.base + ".fifo").read_bytes(), cp, out)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
