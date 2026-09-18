"""Vertex-attribute dump tests for tools/fifo.py.

Every stream here is built byte by byte from the register layouts in the
hardware manuals, and the "RAM image" the indexed attributes point into is a
few hundred synthesised bytes -- no capture, no disc, no corpus.
"""

import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fifo  # noqa: E402

# --------------------------------------------------------------------------
# stream construction
# --------------------------------------------------------------------------


def cp_write(reg: int, val: int) -> bytes:
    return bytes([0x08, reg]) + val.to_bytes(4, "big")


def xf_write(addr: int, vals: list[int]) -> bytes:
    return (
        bytes([0x10])
        + (len(vals) - 1).to_bytes(2, "big")
        + addr.to_bytes(2, "big")
        + b"".join(v.to_bytes(4, "big") for v in vals)
    )


def xf_indexed(op: int, idx: int, dst: int, count: int) -> bytes:
    return bytes([op]) + idx.to_bytes(2, "big") + (((count - 1) << 12) | dst).to_bytes(2, "big")


def draw(prim: int, vat: int, count: int, payload: bytes) -> bytes:
    return bytes([prim | vat]) + count.to_bytes(2, "big") + payload


def be_f32(x: float) -> bytes:
    return struct.pack(">f", x)


def word(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


# The descriptor every test below shares: a per-vertex position-matrix index,
# an 8-bit-indexed f32 position, a 16-bit-indexed s16 normal, a direct RGBA8
# colour and a 16-bit-indexed s16 texture coordinate. Ten bytes per vertex.
VCD_LO = 1 | (2 << 9) | (3 << 11) | (1 << 13)
VCD_HI = 3
VAT_A = (
    1  # position count XYZ
    | (4 << 1)  # position format f32
    | (0 << 9)  # normal count XYZ
    | (3 << 10)  # normal format s16 (fixed 1/2**14)
    | (1 << 13)  # colour 0 count RGBA
    | (5 << 14)  # colour 0 format RGBA8
    | (1 << 21)  # texture 0 count ST
    | (3 << 22)  # texture 0 format s16
    | (8 << 25)  # texture 0 shift
    | (1 << 30)  # byte dequant
)

POS_BASE, NRM_BASE, TEX_BASE, MTX_BASE = 0x100, 0x200, 0x300, 0x400


def synth_ram() -> bytes:
    ram = bytearray(0x1000)
    ram[POS_BASE : POS_BASE + 24] = (
        be_f32(1.0) + be_f32(2.0) + be_f32(3.0) + be_f32(-4.0) + be_f32(5.0) + be_f32(-6.0)
    )
    ram[NRM_BASE : NRM_BASE + 12] = struct.pack(">6h", 16384, 0, 0, 0, 0, -16384)
    ram[TEX_BASE : TEX_BASE + 8] = struct.pack(">4h", 128, 64, 256, 512)
    # A normal matrix in an array, for the indexed-XF-load test: 90 degrees
    # about z, so x turns into y.
    rot = [0, -1, 0, 1, 0, 0, 0, 0, 1]
    ram[MTX_BASE : MTX_BASE + 36] = b"".join(be_f32(float(v)) for v in rot)
    return bytes(ram)


def setup_stream() -> bytes:
    return (
        cp_write(0x50, VCD_LO)
        + cp_write(0x60, VCD_HI)
        + cp_write(0x70, VAT_A)
        + cp_write(0x80, 0)
        + cp_write(0x90, 0)
        + cp_write(0xA0, POS_BASE)
        + cp_write(0xB0, 12)
        + cp_write(0xA1, NRM_BASE)
        + cp_write(0xB1, 6)
        + cp_write(0xA4, TEX_BASE)
        + cp_write(0xB4, 4)
    )


def two_vertices() -> bytes:
    v0 = (
        bytes([2, 0])
        + (0).to_bytes(2, "big")
        + bytes([0x11, 0x22, 0x33, 0x44])
        + (0).to_bytes(2, "big")
    )
    v1 = (
        bytes([2, 1])
        + (1).to_bytes(2, "big")
        + bytes([0x55, 0x66, 0x77, 0x88])
        + (1).to_bytes(2, "big")
    )
    return v0 + v1


def run(stream: bytes, ram, verts=(1, 1)) -> list[str]:
    out: list[str] = []
    fifo.decode(stream, {}, out, xf=[0] * 4352, ram=ram, verts=verts)
    return out


VEC = re.compile(r"\(([-0-9., ]+)\)")


def vecs(line: str) -> list[list[float]]:
    return [[float(x) for x in m.split(",")] for m in VEC.findall(line)]


def approx(got, want, tol=1e-4):
    assert len(got) == len(want), (got, want)
    assert all(abs(a - b) <= tol for a, b in zip(got, want, strict=True)), (got, want)


# --------------------------------------------------------------------------
# layout
# --------------------------------------------------------------------------


def test_vertex_size_is_the_sum_of_the_layout():
    cp = {0x50: VCD_LO, 0x60: VCD_HI, 0x70: VAT_A}
    layout = fifo.vertex_layout(cp, 0)
    # 1 matrix index + 1 position index + 2 normal index + 4 direct colour
    # + 2 texture index.
    assert fifo.vertex_size(cp, 0) == 10
    assert sum(at.stream_bytes for at in layout) == 10
    present = {at.name: at for at in layout if at.mode}
    assert set(present) == {"pmtx", "pos", "nrm", "clr0", "tex0"}
    assert present["pos"].elem == 12  # three f32 in the array, one byte in the stream
    assert present["pos"].stream_bytes == 1
    assert present["nrm"].frac == 14  # s16 normals are fixed 1/2**14 by format


def test_direct_attributes_still_size_the_same_way():
    """A descriptor with nothing indexed: 3 f32 + RGBA8 + 2 f32."""
    cp = {
        0x50: (1 << 9) | (1 << 13),
        0x60: 1,
        0x70: 1 | (4 << 1) | (1 << 13) | (5 << 14) | (1 << 21) | (4 << 22),
    }
    assert fifo.vertex_size(cp, 0) == 12 + 4 + 8


def test_nbt_with_three_indices_spends_three_indices():
    """GX reads a normal/binormal/tangent triple as three separate indices."""
    lo = (1 << 9) | (3 << 11)
    a = 1 | (4 << 1) | (1 << 9) | (3 << 10) | (1 << 31)
    cp = {0x50: lo, 0x60: 0, 0x70: a}
    nrm = next(at for at in fifo.vertex_layout(cp, 0) if at.name == "nrm")
    assert nrm.triple and nrm.stream_bytes == 6 and nrm.elem == 6
    assert fifo.vertex_size(cp, 0) == 12 + 6


# --------------------------------------------------------------------------
# reading the vertices
# --------------------------------------------------------------------------


def test_indexed_attributes_resolve_through_the_arrays():
    xf = xf_write(
        0x0008,
        [word(1.0), 0, 0, word(10.0), 0, word(1.0), 0, word(20.0), 0, 0, word(1.0), word(30.0)],
    )
    stream = setup_stream() + xf + draw(0x98, 0, 2, two_vertices())
    out = run(stream, synth_ram())
    assert out[0].startswith("  DRAW #1 TRISTRIP vat 0 count 2 (10 bytes/vertex)")
    assert "pos=idx8/f32x3" in out[1] and "nrm=idx16/s16x3>>14" in out[1]
    assert f"@arr0[{POS_BASE:08X}+12]" in out[1]

    v0, v1 = vecs(out[2]), vecs(out[3])
    approx(v0[0], [1.0, 2.0, 3.0])  # position, straight out of array 0
    approx(v0[1], [11.0, 22.0, 33.0])  # after the position matrix for index 2
    approx(v0[2], [1.0, 0.0, 0.0])  # normal, s16 over 2**14
    approx(v0[5], [0.5, 0.25])  # texture coordinate, s16 over 2**8
    assert "clr0 (17, 34, 51, 68)" in out[2]
    approx(v1[0], [-4.0, 5.0, -6.0])
    approx(v1[1], [6.0, 25.0, 24.0])
    approx(v1[2], [0.0, 0.0, -1.0])
    approx(v1[5], [1.0, 2.0])
    assert "clr0 (85, 102, 119, 136)" in out[3]
    # The array addresses each index resolved to are printed, so a stale
    # ARRAY_BASE is visible in the dump itself.
    assert f"tex0@{TEX_BASE:08X}" in out[2] and f"tex0@{TEX_BASE + 4:08X}" in out[3]


def test_the_normal_matrix_is_applied_and_renormalised():
    """Raw and transformed both print; the transformed one is what lights."""
    rot = [0, -1, 0, 1, 0, 0, 0, 0, 1]  # 90 degrees about z, then scaled by 4
    mtx = xf_write(0x0406, [word(4.0 * v) for v in rot])
    stream = setup_stream() + mtx + draw(0x98, 0, 2, two_vertices())
    out = run(stream, synth_ram())
    v0 = vecs(out[2])
    approx(v0[2], [1.0, 0.0, 0.0])  # as the stream carries it
    approx(v0[3], [0.0, 1.0, 0.0])  # after the matrix, renormalised


def test_xf_indexed_loads_the_matrix_from_memory():
    """XF_INDEXED array 13 fills normal matrix memory from the RAM image."""
    stream = (
        setup_stream()
        + cp_write(0xAD, MTX_BASE)
        + cp_write(0xBD, 36)
        + xf_indexed(0x28, 0, 0x0406, 9)
        + draw(0x98, 0, 2, two_vertices())
    )
    out = run(stream, synth_ram())
    approx(vecs(out[2])[3], [0.0, 1.0, 0.0])


def test_without_a_ram_image_indexed_attributes_say_so():
    stream = setup_stream() + draw(0x98, 0, 2, two_vertices())
    out = run(stream, None)
    assert "pos <unresolved>" in out[2] and "nrm <unresolved>" in out[2]
    assert "clr0 (17, 34, 51, 68)" in out[2]  # the direct attribute still reads


def test_an_index_past_the_end_of_memory_is_unresolved_not_a_crash():
    stream = setup_stream() + cp_write(0xA0, 0x0FFF) + draw(0x98, 0, 2, two_vertices())
    out = run(stream, synth_ram())
    assert "pos <unresolved>" in out[2]


# --------------------------------------------------------------------------
# selecting draws
# --------------------------------------------------------------------------


def test_only_the_selected_draws_are_printed():
    body = draw(0x98, 0, 2, two_vertices())
    stream = setup_stream() + body + body + body
    out = run(stream, synth_ram(), verts=(2, 2))
    assert [line for line in out if "DRAW" in line] == [
        "  DRAW #2 TRISTRIP vat 0 count 2 (10 bytes/vertex)"
    ]
    assert len(out) == 4  # header, layout, two vertices


def test_draw_numbers_appear_in_the_plain_listing():
    body = draw(0x98, 0, 2, two_vertices())
    out: list[str] = []
    fifo.decode(setup_stream() + body + body, {}, out)
    assert [line.strip() for line in out if "DRAW" in line] == [
        "DRAW #1 TRISTRIP vat 0 count 2 (10 bytes/vertex)",
        "DRAW #2 TRISTRIP vat 0 count 2 (10 bytes/vertex)",
    ]


def test_parse_range():
    assert fifo.parse_range("12") == (12, 12)
    assert fifo.parse_range("12-30") == (12, 30)
    assert fifo.parse_range("12-")[0] == 12
    assert fifo.parse_range("-30")[1] == 30
    assert fifo.parse_range("all")[0] == 1
