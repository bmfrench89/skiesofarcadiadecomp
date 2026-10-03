"""tools/fifo.py --summary (specs/gpu-backend.md V1) on a synthetic stream:
what a GPU path must reproduce besides the draws, read out of a capture.

The stream holds one draw under a logic OR, one display list of 0x40 bytes
(inline, as a capture since C5b records it), and two copies to texture, R8
and RGB565, each with its own destination and size."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import fifo  # noqa: E402


def bp(reg: int, v: int) -> bytes:
    return b"\x61" + ((reg << 24) | v).to_bytes(4, "big")


def cpw(reg: int, v: int) -> bytes:
    return bytes([0x08, reg]) + v.to_bytes(4, "big")


def copy(fmt_bits: int, dest: int, w: int, h: int) -> bytes:
    return (
        bp(0x49, 0)
        + bp(0x4A, (w - 1) | ((h - 1) << 10))
        + bp(0x4B, dest >> 5)
        + bp(0x52, fmt_bits << 3)  # bits 3-6: the format, rotated (copy_format)
    )


def stream() -> bytes:
    s = cpw(0x50, 0x200) + cpw(0x70, 0x9)  # position direct, three F32s
    s += bp(0x41, (7 << 12) | (1 << 1))  # logic op on (OR), blend off
    s += b"\x90" + (3).to_bytes(2, "big") + bytes(36)  # one triangle
    s += bp(0x41, 0)
    s += bytes([fifo.CAP_LIST]) + (0x80200000).to_bytes(4, "big") + (0x40).to_bytes(4, "big")
    s += bytes(0x40)  # the list: nops
    s += copy(2, 0x00100000, 64, 32)  # R8
    s += copy(8, 0x00200000, 128, 64)  # RGB565
    return s


def run() -> list[str]:
    return fifo.summary(stream(), {}, [0] * 4352, {}, None)


def test_the_summary_line():
    assert run()[0] == "summary: 1 draws, 2 copies, 1 draws under a logic op, 1 display lists"


def test_each_copy_with_its_format_destination_and_size():
    lines = run()
    assert "copy 1: to texture R8 at 00100000, 64x32 from (0,0)" in lines
    assert "copy 2: to texture RGB565 at 00200000, 128x64 from (0,0)" in lines


def test_the_logic_op_and_the_list():
    lines = run()
    assert "logic OR: 1 draws" in lines
    assert "lists: 1 (0 empty, 64 bytes): 0x40" in lines


def test_a_blend_overrides_the_logic_op():
    """GX blends when both are enabled, and so does the renderer (gxr.c
    pixel_prepare), so such a draw is not a logic-op draw."""
    s = stream().replace(bp(0x41, (7 << 12) | (1 << 1)), bp(0x41, (7 << 12) | (1 << 1) | 1))
    assert not any(line.startswith("logic ") for line in fifo.summary(s, {}, [0] * 4352, {}, None))


def test_intensity_copies_are_named_as_such():
    assert fifo.copy_format((1 << 15) | (2 << 3)) == "I8"
    assert fifo.copy_format(2 << 3) == "R8"
