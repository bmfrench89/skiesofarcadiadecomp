"""Pair-analyser tests for tools/fifopair.py (PLAN-60FPS-MODS H4).

Every capture here is synthesised byte by byte -- a .regs image, a command
stream and a small RAM image holding a display list -- in the style of
test_fifo_verts.py: no disc, no corpus. The frame is set up so that view space
IS screen space (an orthographic projection and a viewport that map x to x and
y to y), which makes every area and displacement a number worked out by hand.
"""

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fifo  # noqa: E402
import fifopair  # noqa: E402

# --------------------------------------------------------------------------
# building captures
# --------------------------------------------------------------------------


def word(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


def be_f32(x: float) -> bytes:
    return struct.pack(">f", x)


def cp_write(reg: int, val: int) -> bytes:
    return bytes([0x08, reg]) + val.to_bytes(4, "big")


def bp_write(reg: int, val: int) -> bytes:
    return bytes([0x61]) + ((reg << 24) | (val & 0xFFFFFF)).to_bytes(4, "big")


def call_list(addr: int, size: int) -> bytes:
    return bytes([0x40]) + addr.to_bytes(4, "big") + size.to_bytes(4, "big")


def draw(prim: int, vat: int, count: int, payload: bytes) -> bytes:
    return bytes([prim | vat]) + count.to_bytes(2, "big") + payload


QUADS, TRIANGLES = 0x80, 0x90
TEX_A, TEX_B, TEX_C = 0x00100000, 0x00200000, 0x00300000
LIST_AT = 0x2000  # where the display list sits in the RAM image
XFB_COPY = bp_write(0x52, 0x4803)  # the copy to the XFB that ends every captured frame


def quad(x: float, y: float, w: float, h: float, z: float = -50.0) -> bytes:
    """A direct-f32 quad covering [x, x+w] by [y, y+h] on the screen."""
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return draw(QUADS, 0, 4, b"".join(be_f32(a) + be_f32(b) + be_f32(z) for a, b in corners))


def texture(addr: int) -> bytes:
    return bp_write(0x94, addr >> 5)  # TX_IMAGE3_0: map 0's image address


def regs_image() -> bytes:
    """Frame-start state: one TEV stage sampling map 0, positions direct f32,
    an identity position matrix, and a projection and viewport under which
    view (x, y) lands on screen pixel (x, y)."""
    cp = [0] * 256
    cp[0x50] = 1 << 9  # VCD_LO: position direct
    cp[0x70] = 1 | (4 << 1)  # VAT0_A: position XYZ, f32
    cp[0x71] = 1 | (3 << 1)  # VAT1_A: position XYZ, s16
    xf = [0] * 4352
    for r in range(3):
        xf[4 * r + r] = word(1.0)  # position matrix 0: identity
    ortho = (1 / 320, -1.0, -1 / 240, 1.0, 0.01, 0.0)  # x/320 - 1, 1 - y/240, z/100
    for i, v in enumerate(ortho):
        xf[0x1020 + i] = word(v)
    xf[0x1026] = 1  # orthographic
    for i, v in enumerate((320.0, -240.0, 16777215.0, 320.0, 240.0, 16777215.0)):
        xf[0x101A + i] = word(v)
    bp = [0] * 256
    bp[0x28] = 0x40  # TREF0: stage 0 samples map 0 through coordinate 0, enabled
    bp[0xC0] = 0x08FFF8  # TEV0 colour: some setup, its value does not matter
    return struct.pack("<256I", *cp) + struct.pack("<4352I", *xf) + struct.pack("<256I", *bp)


def padded_list(body: bytes) -> bytes:
    return body + bytes(-len(body) % 32)  # GX lists are padded to 32 bytes with NOPs


def capture(tmp_path: Path, name: str, stream: bytes, dlist: bytes = b"") -> str:
    base = tmp_path / name
    ram = bytearray(0x4000)
    ram[LIST_AT : LIST_AT + len(dlist)] = dlist
    Path(f"{base}.regs").write_bytes(regs_image())
    Path(f"{base}.fifo").write_bytes(stream)
    Path(f"{base}.ram").write_bytes(bytes(ram))
    return str(base)


def scene(tmp_path, name, tex_first=TEX_A, first=(10, 10), tex_list=TEX_B) -> str:
    """Two draws: a direct 100x100 quad at `first` (10,000 px), and a 200x100
    quad reached through a display list (20,000 px)."""
    dlist = padded_list(quad(300, 300, 200, 100))
    stream = (
        texture(tex_first)
        + quad(first[0], first[1], 100, 100)
        + texture(tex_list)
        + call_list(0x80000000 | LIST_AT, len(dlist))
        + XFB_COPY
    )
    return capture(tmp_path, name, stream, dlist)


def report(a: str, b: str) -> dict:
    return fifopair.pair_report(fifopair.load_frame(a), fifopair.load_frame(b))


def hist(rep: dict) -> dict:
    d = rep["displacement"]
    return dict(zip(d["labels"], d["vertices"], strict=True))


# --------------------------------------------------------------------------
# the area proxy
# --------------------------------------------------------------------------


def test_a_quad_covers_its_area_and_the_screen_edge_clips_it(tmp_path):
    stream = texture(TEX_A) + quad(10, 10, 100, 100) + quad(590, 0, 100, 100) + XFB_COPY
    frame = fifopair.load_frame(capture(tmp_path, "f", stream))
    assert [d.area for d in frame.draws] == pytest.approx([10000.0, 5000.0], abs=0.5)
    assert frame.draws[0].screen[2] == pytest.approx((110.0, 110.0), abs=1e-3)


# Clip space under an identity-like viewport: x -> 320 + 320x, y -> 240 - 240y.
VP = (320.0, -240.0, 320.0, 240.0)
TRI = [(0.0, 0.0, -0.5, 1.0), (0.5, 0.0, -0.5, 1.0), (0.0, 0.5, -0.5, 1.0)]  # 9,600 px


def test_cull_modes_drop_triangles_by_their_screen_winding():
    # (0,0) (160,0) (0,-120) relative: twice the signed area is negative.
    assert fifopair.draw_area(TRIANGLES, TRI, VP, 0) == pytest.approx(9600.0)
    assert fifopair.draw_area(TRIANGLES, TRI, VP, 1) == 0.0
    assert fifopair.draw_area(TRIANGLES, TRI, VP, 2) == pytest.approx(9600.0)
    assert fifopair.draw_area(TRIANGLES, TRI, VP, 3) == 0.0
    assert fifopair.draw_area(TRIANGLES, TRI[::-1], VP, 2) == 0.0


def test_the_part_past_the_near_plane_is_clipped_away():
    """The third vertex is past the near plane (z + w = -2): the triangle is
    cut a third and two thirds along its two edges into a trapezoid of
    (0.5 + 1/3) / 2 * 1/6 = 5/72 in clip units, 5/72 * 76,800 pixels."""
    tri = [(0.0, 0.0, 0.0, 1.0), (0.5, 0.0, 0.0, 1.0), (0.0, 0.5, -3.0, 1.0)]
    assert fifopair.draw_area(TRIANGLES, tri, VP, 0) == pytest.approx(5 / 72 * 76800)


def test_a_triangle_behind_the_eye_covers_nothing():
    behind = [(x, y, z, -1.0) for x, y, z, _ in TRI]
    assert fifopair.draw_area(TRIANGLES, behind, VP, 0) == 0.0


def test_strips_and_fans_split_as_the_renderer_splits_them():
    assert list(fifopair.triangles(0x98, 5)) == [(0, 1, 2), (2, 1, 3), (2, 3, 4)]
    assert list(fifopair.triangles(0xA0, 5)) == [(0, 1, 2), (0, 2, 3), (0, 3, 4)]
    assert list(fifopair.triangles(QUADS, 8)) == [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    assert list(fifopair.triangles(0xA8, 4)) == []  # lines cover nothing


# --------------------------------------------------------------------------
# pairing
# --------------------------------------------------------------------------


def test_identical_frames_match_all_their_area(tmp_path):
    rep = report(scene(tmp_path, "5000"), scene(tmp_path, "5001"))
    m = rep["matched"]
    assert rep["frames"]["n1"]["area"] == pytest.approx(30000.0, abs=1.0)
    assert m["area_share"] == 1.0 and m["draw_share"] == 1.0
    assert m["below_kill_line"] is False
    assert m["equal_matrices_share"] == 1.0
    assert m["order_changed"] == 0
    assert m["changed"]["none"]["draws"] == 2
    assert hist(rep)["0"] == 8 and sum(rep["displacement"]["vertices"]) == 8
    assert rep["largest_unmatched"] == []


def test_a_changed_texture_unmatches_that_draw(tmp_path):
    """The kill test must be able to fail: one draw's texture address moved,
    so its 10,000 of the frame's 30,000 pixels have no partner."""
    rep = report(scene(tmp_path, "5000"), scene(tmp_path, "5001", tex_first=TEX_C))
    m = rep["matched"]
    assert m["area_share"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["below_kill_line"] is True
    assert m["draws"] == 1 and m["draw_share"] == 0.5
    # Dropping the texture from the key is what would have paired it.
    assert rep["near_miss"]["textures"]["draws"] == 1
    assert rep["near_miss"]["textures"]["area"] == pytest.approx(10000.0, abs=0.5)
    assert rep["near_miss"]["tev"]["draws"] == 0
    (miss,) = rep["largest_unmatched"]
    assert miss["textures"] == [f"{TEX_C:08X}"]
    assert miss["would_match_without"] == ["textures"]


def test_a_moved_draw_puts_its_displacement_in_the_histogram(tmp_path):
    """Moved by (6, 8): ten pixels, so its four vertices land in 8-16 and the
    other draw's four in 0. It is still matched -- the key has no position."""
    rep = report(scene(tmp_path, "5000"), scene(tmp_path, "5001", first=(16, 18)))
    h = hist(rep)
    assert h["8-16"] == 4 and h["0"] == 4 and sum(h.values()) == 4 + 4
    assert rep["displacement"]["max"] == pytest.approx(10.0, abs=1e-3)
    assert rep["matched"]["area_share"] == 1.0
    assert rep["matched"]["changed"]["vertex_data"]["draws"] == 1


def test_list_draws_and_direct_draws_are_counted_apart(tmp_path):
    rep = report(scene(tmp_path, "5000"), scene(tmp_path, "5001", tex_first=TEX_C))
    for name in ("n", "n1"):
        f = rep["frames"][name]
        assert f["through_list"]["draws"] == 1 and f["direct"]["draws"] == 1
        assert f["through_list"]["area"] == pytest.approx(20000.0, abs=1.0)
        assert f["direct"]["area"] == pytest.approx(10000.0, abs=1.0)
        assert f["list_calls"] == 1 and f["empty_list_calls"] == 0
    routes = rep["routes"]
    assert routes["through_list"]["matched_area_share"] == 1.0
    assert routes["direct"]["matched_area_share"] == 0.0
    frame = fifopair.load_frame(str(tmp_path / "5000"))
    assert [d.dl for d in frame.draws] == [None, 0x80000000 | LIST_AT]


def test_the_list_address_is_part_of_the_key(tmp_path):
    """The same quad drawn directly in one frame and through a list in the
    next is not the same draw as far as the key can tell."""
    dlist = padded_list(quad(10, 10, 100, 100))
    direct = capture(tmp_path, "a", texture(TEX_A) + quad(10, 10, 100, 100) + XFB_COPY)
    listed = capture(
        tmp_path, "b", texture(TEX_A) + call_list(LIST_AT, len(dlist)) + XFB_COPY, dlist
    )
    rep = report(direct, listed)
    assert rep["matched"]["draws"] == 0
    assert rep["near_miss"]["dl"]["draws"] == 1


def test_array_bases_are_part_of_the_key(tmp_path):
    """An indexed-position draw whose array moved between frames is unmatched."""

    def indexed(base: int) -> bytes:
        return (
            cp_write(0x50, 2 << 9)  # position idx8
            + cp_write(0xA0, base)
            + cp_write(0xB0, 6)
            + draw(TRIANGLES, 1, 3, bytes([0, 1, 2]))
        )

    ram = struct.pack(">9h", 0, 0, -50, 100, 0, -50, 0, 100, -50)
    a = capture(tmp_path, "a", texture(TEX_A) + indexed(0x1000) + XFB_COPY)
    b = capture(tmp_path, "b", texture(TEX_A) + indexed(0x1100) + XFB_COPY)
    for base in (a, b):  # both images hold the triangle at both addresses
        img = bytearray(Path(f"{base}.ram").read_bytes())
        img[0x1000 : 0x1000 + len(ram)] = ram
        img[0x1100 : 0x1100 + len(ram)] = ram
        Path(f"{base}.ram").write_bytes(bytes(img))
    rep = report(a, b)
    assert rep["frames"]["n1"]["area"] == pytest.approx(5000.0, abs=0.5)
    assert rep["matched"]["draws"] == 0
    assert rep["near_miss"]["arrays"]["draws"] == 1


def test_draws_that_swap_places_are_matched_and_counted_as_reordered(tmp_path):
    first = texture(TEX_A) + quad(10, 10, 100, 100)
    second = texture(TEX_B) + quad(300, 300, 50, 50)
    a = capture(tmp_path, "a", first + second + XFB_COPY)
    b = capture(tmp_path, "b", second + first + XFB_COPY)
    rep = report(a, b)
    assert rep["matched"]["area_share"] == 1.0
    assert rep["matched"]["order_changed"] == 1
    assert hist(rep)["0"] == 8


def test_repeated_draws_pair_in_stream_order_even_when_that_is_wrong(tmp_path):
    """The known limit of keying by content: two draws with equal keys are
    paired first-with-first. Swap them and each is paired with the other's
    instance, which shows as displacement, not as a mismatch."""
    left, right = quad(10, 10, 100, 100), quad(400, 10, 100, 100)
    a = capture(tmp_path, "a", texture(TEX_A) + left + right + XFB_COPY)
    b = capture(tmp_path, "b", texture(TEX_A) + right + left + XFB_COPY)
    rep = report(a, b)
    assert rep["matched"]["area_share"] == 1.0 and rep["matched"]["order_changed"] == 0
    assert hist(rep)[">=128"] == 8  # every vertex "moved" 390 pixels


def test_a_count_change_unmatches_and_the_loose_pairing_says_so(tmp_path):
    tri = draw(TRIANGLES, 0, 3, b"".join(be_f32(v) for v in (0, 0, -50, 100, 0, -50, 0, 100, -50)))
    six = draw(TRIANGLES, 0, 6, (tri[3:]) * 2)
    a = capture(tmp_path, "a", texture(TEX_A) + tri + XFB_COPY)
    b = capture(tmp_path, "b", texture(TEX_A) + six + XFB_COPY)
    rep = report(a, b)
    assert rep["matched"]["draws"] == 0
    assert rep["without_count"] == {"draws": 1, "equal_counts": 0, "equal_counts_share": 0.0}
    assert rep["near_miss"]["count"]["draws"] == 1


def test_a_clearing_copy_to_texture_marks_the_draws_before_it(tmp_path):
    stream = (
        texture(TEX_A)
        + quad(0, 0, 64, 64)
        + bp_write(0x52, 0x0803)  # copy to texture, clearing the EFB behind it
        + quad(10, 10, 100, 100)
        + XFB_COPY
    )
    frame = fifopair.load_frame(capture(tmp_path, "f", stream))
    assert frame.texture_copies == 1
    assert [d.wiped for d in frame.draws] == [True, False]
    assert [d.copies_before for d in frame.draws] == [0, 1]


# --------------------------------------------------------------------------
# the walker under it, and the command line
# --------------------------------------------------------------------------


def test_walk_follows_a_list_one_level_deep_and_only_inside_the_image():
    inner = padded_list(call_list(LIST_AT, 32) + quad(0, 0, 1, 1))
    ram = bytearray(0x4000)
    ram[LIST_AT : LIST_AT + len(inner)] = inner
    stream = call_list(LIST_AT, len(inner)) + call_list(0x3FF0, 0x100)  # the second runs off

    def kinds(follow):
        cp = {0x50: 1 << 9, 0x70: 1 | (4 << 1)}  # the quad's direct f32 positions
        cmds = fifo.walk(stream, cp, [0] * 4352, bytes(ram), follow_lists=follow)
        return [(c[0], c[2]) for c in cmds if c[0] != "nop"]

    assert kinds(False) == [("call", None), ("call", None)]
    assert kinds(True) == [
        ("call", None),
        ("call", LIST_AT),  # the nested call is reported, not followed
        ("draw", LIST_AT),
        ("call", None),
    ]


def test_the_command_line_prints_a_report_and_json(tmp_path, capsys):
    a, b = scene(tmp_path, "5000"), scene(tmp_path, "5001", tex_first=TEX_C)
    assert fifopair.main([a, b]) == 0
    text = capsys.readouterr().out
    assert "area is an estimate" in text
    assert "66.7%  UNDER the ~90% kill line" in text
    assert fifopair.main([a, b, "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["matched"]["area_share"] == pytest.approx(2 / 3, abs=1e-4)
    assert rep["bases"] == [a, b]
