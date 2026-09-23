"""tools/sct.py, the field-script disassembler, on scripts built word by word.

The tool was checked against the disc once when it was written -- `me103a.sct`
disassembled to the same 875 lines as the research script it came from -- and
these tests hold the format to what that check established, with no disc:
a flag test, a set, a self-relative warp name, a jump, a switch, and a script
that runs off its end, which must say so instead of printing guesses.
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import sct  # noqa: E402

END, FLOAT, EQ = 29, 0x04000000, 4


def f(x: float) -> list[int]:
    return [FLOAT, struct.unpack(">I", struct.pack(">f", x))[0]]


def build(entries: list[tuple[str, list[int]]], tail: bytes = b"") -> bytes:
    """A decompressed script: the header, the entry table, the code, then
    `tail` (where warp names live)."""
    head = struct.pack(">III", 0, 0, len(entries))
    code, table = b"", b""
    for name, words in entries:
        table += struct.pack(">I", len(code)) + name.encode().ljust(16, b"\0")
        code += b"".join(struct.pack(">I", w & 0xFFFFFFFF) for w in words)
    return head + table + code + tail


def lines_of(d: bytes, want=None) -> dict[str, list[str]]:
    return {name: lines for name, _, _, lines in sct.script(d, want)}


def test_a_flag_test_a_set_and_a_jump():
    # Branch offsets count from the offset word itself, and a loop's is negative.
    loop = [0, 0x20000000 | 1856, *f(0), EQ, END, 0x14]  # the IF's offset word is at 0x18
    loop += [17, *f(18), END]
    loop += [10, -0x30]  # the GOTO's offset word is at 0x30
    got = lines_of(build([("loop", loop)]))["loop"]
    assert got == [
        "00000  [0]IF (FLAG[1856] 0 ==) else-> 0002c",
        "0001c  [17]FLAGSET (18)",
        "0002c  [10]GOTO -> 00000",
    ], got


def test_a_warp_names_its_destination_through_a_self_relative_offset():
    # The operand is the distance from the operand's own position to the
    # string, which lives after the code.
    code = [43, 0]  # patched below
    d = bytearray(build([("exit", code), ("tail", [12])], b"me101b.sct\0\0"))
    base = 12 + 2 * 20
    operand_at = base + 4
    string_at = base + 4 * len(code) + 4  # after exit's two words and tail's one
    struct.pack_into(">I", d, operand_at, string_at - operand_at)
    got = lines_of(bytes(d))
    assert got["exit"] == ['00000  [43]WARP "me101b.sct"'], got
    # Names live in a pool after the code, and the last entry runs into it:
    # the real me103a ends the same way. Shown as data, not decoded as code.
    assert got["tail"][0] == "00008  [12]RET", got
    assert all("???" in line for line in got["tail"][1:]), got


def test_a_switch_lists_its_cases_and_default():
    words = [3, 0x50000000 | 15, END, 2, 990, 0x0, 0xFFFFFFFF, 0x8]
    got = lines_of(build([("from", words), ("next", [12])]))["from"]
    # sys[15] is the map the party came from: 990 means 099a.
    assert got == ["00000  [3]SWITCH (sys[15]) 990->00014 default->00024"], got


def test_an_entry_is_disassembled_only_up_to_the_next():
    d = build([("a", [12]), ("b", [22]), ("c", [12])])
    assert lines_of(d) == {
        "a": ["00000  [12]RET"],
        "b": ["00004  [22]YIELD"],
        "c": ["00008  [12]RET"],
    }
    assert list(lines_of(d, ["b"])) == ["b"]


def test_a_script_that_runs_off_its_end_says_so():
    """An expression with no END word reads past the buffer: that has to come
    out as a desynchronised entry, never as invented instructions."""
    got = lines_of(build([("bad", [17, 0x20000001])]))["bad"]
    assert len(got) == 1 and got[0].startswith("!! desynchronised"), got
