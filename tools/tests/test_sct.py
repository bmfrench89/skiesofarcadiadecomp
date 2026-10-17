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


def words_of(text: bytes) -> list[int]:
    """Text as the script holds it: NUL-ended, padded to whole words."""
    text += b"\0" * (4 - len(text) % 4)
    return list(struct.unpack(f">{len(text) // 4}I", text))


def test_a_message_and_a_choice_print_their_text():
    """A message (144) is an offset to an entry of its own, then one
    expression, here 0x7FFFFFFF, which the game's evaluator takes alone; a
    choice (155) is an expression, the offset, an expression. The entry is
    op 9 skipping to its END, then the text: listed as text, not decoded as
    code. Before, the offset read as an expression and the listing lost its
    place (me008a's dancer, M03004)."""
    talk = [144, 40 - 4, 0x7FFFFFFF, 155, *f(2), END, 84 - 28, sct.DEFAULT, 12]
    said = [9, *f(1), END, *words_of(b"\\h(\x81sBellena\x81t)Stay\x7fhere.")]
    options = [9, *f(1), END, *words_of(b"[Yes]\\n[No]")]
    got = lines_of(build([("talk", talk), ("M04060008", said), ("M04060009", options)]))
    assert got == {
        "talk": [
            '00000  [144]MESSAGE @00028 "\\h(.sBellena.t)Stay here." (DEF)',
            '0000c  [155]CHOICE (2) @00054 "[Yes]\\n[No]" (DEF)',
            "00024  [12]RET",
        ],
        "M04060008": ['00028  [9]EVAL "\\h(.sBellena.t)Stay here."'],
        "M04060009": ['00054  [9]EVAL "[Yes]\\n[No]"'],
    }, got


def test_the_last_entry_may_end_off_a_word():
    """The last entry runs into the name pool, which need not end on a word:
    its stray bytes are said, and the entry is listed, not lost."""
    assert lines_of(build([("a", [12])], b"me1")) == {
        "a": ["00000  [12]RET", "00004  ... 3 byte(s)"]
    }


def test_the_story_scan_sees_through_calls_and_what_desynchronises_the_listing():
    """`story`: an entry's flags set and maps warped to include those of every
    entry it calls, however deep, and a message (op 144, which the listing
    cannot size) hides nothing after it. Op 238, the way back to the world
    map, is a warp to 099a. A flag set from an expression, a flag at 1024 or
    above (the field's own: 1087 the event lock), and a CALL that lands
    mid-entry are not counted."""
    talk = [144, 0xC824, 0x7FFFFFFF, 11, 0]  # a message, then a CALL patched below
    talk += [17, *f(1087), END, 17, 0x20000000 | 5, END, 12]
    sub = [17, *f(100), END, 11, 0, 12]  # 100, and a CALL to deeper
    deeper = [43, 0, 238, 0x40000040, END, 12]  # a WARP, then op 238
    d = bytearray(build([("M03005", talk), ("sub", sub), ("deeper", deeper)], b"me116d.sct\0\0"))
    base = 12 + 3 * 20
    sub_at, deeper_at = 4 * len(talk), 4 * (len(talk) + len(sub))
    struct.pack_into(">i", d, base + 16, sub_at - 16)  # talk's CALL operand is word 4
    struct.pack_into(">i", d, base + sub_at + 20, deeper_at - (sub_at + 20))
    name_at = base + 4 * (len(talk) + len(sub) + len(deeper))
    struct.pack_into(">I", d, base + deeper_at + 4, name_at - (base + deeper_at + 4))
    got = sct.story(bytes(d))
    assert got["deeper"] == (set(), {"116d", "099a"}), got
    assert got["sub"] == ({100}, {"116d", "099a"}), got
    assert got["M03005"] == ({100}, {"116d", "099a"}), got
    assert sct.story_lines("004a", bytes(d)) == [
        "004a M03005 s100 w099a w116d",
        "004a sub s100 w099a w116d",
        "004a deeper w099a w116d",
    ]
    # A CALL into the middle of an entry is not a call the scan follows.
    struct.pack_into(">i", d, base + 16, sub_at + 4 - 16)
    assert sct.story(bytes(d))["M03005"] == (set(), set()), sct.story(bytes(d))


def test_a_hook_is_a_warp_inside_an_if_on_a_flag_the_field_sets():
    """`IF (FLAG[1766] 1 ==)` around a warp, as me099f's loop has it: a hook,
    listed only when no script sets the flag. A block on a story flag (below
    1024) is not one, nor is a warp after the block ends."""
    ONE = 0x3F800000
    loop = [0, 0x20000000 | 1766, FLOAT, ONE, EQ, END, 0]  # the else-offset patched below
    loop += [43, 0, 10, 0]  # the WARP inside, its name patched; a GOTO pads the block
    loop += [0, 0x20000000 | 62, FLOAT, ONE, EQ, END, 0x10, 43, 0]  # a story flag's block
    loop += [12]
    d = bytearray(build([("loop", loop)], b"me243a.sct\0\0"))
    base = 12 + 20
    struct.pack_into(">i", d, base + 24, 4 * 11 - 24)  # the block ends at word 11
    name_at = base + 4 * len(loop)
    for word in (8, 19):
        struct.pack_into(">I", d, base + 4 * word, name_at - (base + 4 * word))
    assert sct.hooks(bytes(d)) == {1766: {"243a"}}
    assert sct.story_lines("099f", bytes(d), unset={1766}) == [
        "099f loop w243a",
        "099f hook1766 w243a",
    ]
    assert sct.story_lines("099f", bytes(d), unset=set()) == ["099f loop w243a"]
    struct.pack_into(">i", d, base + 24, 4 * 7 - 24)  # a block that ends before the warp
    assert sct.hooks(bytes(d)) == {}


def test_a_flag_set_only_once_another_is_says_which():
    """a013b's 6113 calls the cutscene that sets 271 inside `IF (FLAG[272] 1
    == FLAG[271] 0 == &&)`, and 6111 sets 272 inside `IF (FLAG[290] 1 ==
    FLAG[272] 0 == &&)`: 271 waits for 272 (through the call), 272 for 290.
    A flag also set somewhere unguarded waits for nothing."""
    ONE, ZERO = 0x3F800000, 0
    gate271 = [0x20000000 | 272, FLOAT, ONE, EQ, 0x20000000 | 271, FLOAT, ZERO, EQ, 8, END]
    talk = [0, *gate271, 0, 11, 0, 12]  # IF ... else-> the RET; CALL cut; RET
    cut = [17, *f(271), END, 12]
    gate272 = [0x20000000 | 290, FLOAT, ONE, EQ, 0x20000000 | 272, FLOAT, ZERO, EQ, 8, END]
    exit_ = [0, *gate272, 0, 17, *f(272), END, 12]  # IF ... else-> the RET; FLAGSET 272; RET
    loose = [17, *f(290), END, 12]
    entries = [("M06113", talk), ("me013bf24", cut), ("M06111", exit_), ("M06120", loose)]
    d = bytearray(build(entries, b""))
    base = 12 + 4 * 20
    struct.pack_into(">i", d, base + 4 * 11, 4 * 14 - 4 * 11)  # talk's else-offset
    struct.pack_into(">i", d, base + 4 * 13, 4 * 15 - 4 * 13)  # CALL: cut starts at word 15
    struct.pack_into(
        ">i", d, base + 4 * (20 + 11), 4 * (20 + 16) - 4 * (20 + 11)
    )  # exit's else-offset
    assert sct.requirements(bytes(d)) == {271: {272}, 272: {290}}
    lines = sct.story_lines("013b", bytes(d))
    assert "013b req271 r272" in lines and "013b req272 r290" in lines, lines
    struct.pack_into(">f", d, base + 4 * 39, 272.0)  # M06120 now sets 272 unguarded
    assert sct.requirements(bytes(d)) == {271: {272}}


def test_an_entry_setting_a_field_flag_a_requirement_names_says_so():
    """a013a's 274 waits on field flag 1610 (`013a req274 r1610`), which only
    a115a's 4000 sets: given the field flags requirements name, that entry's
    line says it sets 1610, through a call too; otherwise field flags stay
    off the lines."""
    door = [11, 0, 12]  # CALL set; RET
    sets = [17, *f(1610), END, 12]
    d = bytearray(build([("M04000", door), ("set1610", sets)], b""))
    struct.pack_into(">i", d, 12 + 2 * 20 + 4, 4 * 3 - 4)  # the CALL lands on set1610
    assert sct.story_lines("115a", bytes(d)) == []
    assert sct.story_lines("115a", bytes(d), needed={1610}) == [
        "115a M04000 s1610",
        "115a set1610 s1610",
    ]


def test_an_entry_that_sets_a_blocks_field_flag_does_what_the_block_does():
    """me099h's landing 4008 warps to 112a inside `IF (FLAG[1590] 1 ==
    FLAG[213] 1 == &&)`, and its glittering spot 4506 sets 1590: so 4506
    leads to 112a as well, and sets what the block's CALLs set (me112c's
    touch 6002 sets 1870, and the loop's block on it calls the cutscene that
    sets 216): a gate. A story flag (213) opens nothing this way, nor does a
    condition with `||` in it."""
    ONE = 0x3F800000
    cond = [0x20000000 | 1590, FLOAT, ONE, EQ, 0x20000000 | 213, FLOAT, ONE, EQ, 8, END]
    land = [0, *cond, 0, 11, 0, 43, 0, 12]  # IF ... else-> the RET; CALL cut; WARP; RET
    spot = [17, *f(1590), END, 12]
    story = [17, *f(213), END, 12]
    cut = [17, *f(216), END, 12]
    entries = [("M04008", land), ("M04506", spot), ("M03000", story), ("me112ce17", cut)]
    d = bytearray(build(entries, b"me112a.sct\0\0"))
    base = 12 + 4 * 20
    struct.pack_into(">i", d, base + 4 * 11, 4 * 16 - 4 * 11)  # the else-offset
    struct.pack_into(">i", d, base + 4 * 13, 4 * 27 - 4 * 13)  # CALL: cut starts at word 27
    name_at = base + 4 * (len(land) + len(spot) + len(story) + len(cut))
    struct.pack_into(">I", d, base + 4 * 15, name_at - (base + 4 * 15))
    assert sct.gates(bytes(d)) == {"M04506": ({216}, {"112a"})}
    lines = sct.story_lines("099h", bytes(d))
    assert "099h M04506 s216 w112a" in lines, lines
    struct.pack_into(">I", d, base + 4 * 9, 9)  # && becomes ||
    assert sct.gates(bytes(d)) == {}


def test_a_script_that_runs_off_its_end_says_so():
    """An expression with no END word reads past the buffer: that has to come
    out as a desynchronised entry, never as invented instructions."""
    got = lines_of(build([("bad", [17, 0x20000001])]))["bad"]
    assert len(got) == 1 and got[0].startswith("!! desynchronised"), got
