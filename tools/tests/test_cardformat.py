"""Memory-card formatter tests: does the image say what the mount reads?

    python -m pytest tools/tests/test_cardformat.py

Nothing here needs a disc, a card image or a built port. The fixtures are
synthesised: a formatted image from the tool itself, an erased one (0xFF, the
way runtime/exi.c fills a card it could not open), an all-zero one, and one
carrying a directory entry and a three-block chain shaped like the save the
game writes.

The point of the checks is that two implementations have to agree rather than
one being wrong twice. __CARDCheckSum and the serial scrambler are written out
again here -- the checksum as a sum over a list of halfwords, the scrambler
through ctypes.c_int64 -- so the tool's versions are compared against another
reading of the same instructions, not against themselves. The block-level
constants (F003/0000 for an erased directory block, 003F/EFC3 for a fresh
allocation table) are derived by hand in the comments, so a change to either
implementation that moved them would have to move them both.

One section is not about the image at all: it checks that every entry in
config/trace.txt names a real instruction inside a real function, because the
recompiler drops one that does not without saying so, and most of that file is
now the card mount and the first write. It reads config/functions.tsv, which is
metadata the repository carries, not game data.

The last section is `.gci` import and export (P3). Its saves are made up too:
a GEAE8P entry over random blocks, and cards whose files are laid down here by
hand rather than by the import under test.
"""

import bisect
import ctypes
import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import cardformat as C  # noqa: E402

EXI = (ROOT / "runtime" / "exi.c").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# second implementations of the two algorithms
# --------------------------------------------------------------------------


def sdk_checksum(data: bytes) -> tuple[int, int]:
    """__CARDCheckSum (0x80247728) again, written the other way round: build
    the halfwords first, sum them at the end, and use 0xFFFF - w where the
    tool uses ~w & 0xFFFF."""
    words = [int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data) - 1, 2)]
    total = sum(words) % 0x10000
    inverse = sum(0xFFFF - w for w in words) % 0x10000
    return (0 if total == 0xFFFF else total, 0 if inverse == 0xFFFF else inverse)


def sdk_step(rand: int) -> int:
    """rand = (rand * 0x41C64E6D + 12345) >> 16 on 64 signed bits, with the
    truncation done by the C type rather than by masking."""
    return ctypes.c_int64(rand * 0x41C64E6D + 12345).value >> 16


def sdk_serial(flash_id: bytes, seed: int) -> bytes:
    """__CARDFormatRegionAsync 0x8024965C-0x80249698 again."""
    rand, out = seed, bytearray()
    for byte in flash_id:
        rand = sdk_step(rand)
        out.append(ctypes.c_uint8(byte + ctypes.c_uint8(rand).value).value)
        rand = sdk_step(rand) & 0x7FFF
    return bytes(out)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

GEOM = C.RUNTIME_GEOMETRY


@pytest.fixture
def formatted() -> bytearray:
    return C.format_image()


def parsed(image: bytes) -> C.CardImage:
    return C.parse_image(bytes(image), GEOM)


def blank_image() -> bytes:
    """What runtime/exi.c card_load() puts in front of the game today."""
    return b"\xff" * GEOM.total_bytes


def with_a_file(image: bytearray) -> bytearray:
    """The same card after a save: one directory entry in both copies, a
    three-block chain in both tables, and every checksum brought up to date
    the way __CARDUpdateDir and __CARDUpdateFatBlock bring them up to date."""
    entry = bytearray(b"\xff" * C.ENTRY_BYTES)
    entry[0:4] = b"GEAE"
    entry[4:6] = b"8P"
    entry[6] = 0xFF
    entry[7] = 2  # bannerFormat
    entry[8:40] = b"SA_LEGENDS.000".ljust(32, b"\0")
    entry[40:44] = (0x0EE00000).to_bytes(4, "big")  # modified
    entry[44:48] = (0x00000060).to_bytes(4, "big")  # iconAddr
    entry[48:50] = (0x0002).to_bytes(2, "big")
    entry[50:52] = (0x0003).to_bytes(2, "big")
    entry[52] = 4  # permission
    entry[53] = 0  # copyTimes
    entry[54:56] = (5).to_bytes(2, "big")  # startBlock
    entry[56:58] = (3).to_bytes(2, "big")  # length, in blocks
    entry[58:60] = (0xFFFF).to_bytes(2, "big")
    entry[60:64] = (0x00002000).to_bytes(4, "big")  # commentAddr

    for index in (1, 2):
        at = GEOM.offset(index)
        block = bytearray(image[at : at + C.BLOCK_BYTES])
        block[0 : C.ENTRY_BYTES] = entry
        total, inverse = sdk_checksum(block[: C.CHECK_BYTES])
        block[8188:8190] = total.to_bytes(2, "big")
        block[8190:8192] = inverse.to_bytes(2, "big")
        image[at : at + C.BLOCK_BYTES] = block

    for index in (3, 4):
        at = GEOM.offset(index)
        block = bytearray(image[at : at + C.BLOCK_BYTES])
        block[6:8] = (GEOM.free_blocks - 3).to_bytes(2, "big")
        block[8:10] = (7).to_bytes(2, "big")  # lastAllocated
        block[2 * 5 : 2 * 5 + 2] = (6).to_bytes(2, "big")  # fat[5] -> 6
        block[2 * 6 : 2 * 6 + 2] = (7).to_bytes(2, "big")  # fat[6] -> 7
        block[2 * 7 : 2 * 7 + 2] = (0xFFFF).to_bytes(2, "big")  # end of chain
        total, inverse = sdk_checksum(block[4:])
        block[0:2] = total.to_bytes(2, "big")
        block[2:4] = inverse.to_bytes(2, "big")
        image[at : at + C.BLOCK_BYTES] = block
    return image


# --------------------------------------------------------------------------
# the tool and the device model have to describe the same card
# --------------------------------------------------------------------------


def define(text: str, name: str) -> str:
    m = re.search(rf"^#define {name} (.+?)\s*(?:/\*.*)?$", text, re.MULTILINE)
    assert m, f"{name} is not defined in runtime/exi.c any more"
    return m.group(1).strip()


def c_int(text: str) -> int:
    """A C integer constant as these defines spell them: a literal with the
    unsigned suffix, optionally shifted. No eval, so a define that grew an
    expression fails here instead of being run."""
    body = text.strip().strip("()").replace("u", "").replace("U", "")
    if "<<" in body:
        left, right = body.split("<<")
        return int(left, 0) << int(right, 0)
    return int(body, 0)


def test_the_formatter_describes_the_card_the_runtime_models():
    """An image for a card of another size, another sector size or another
    flash ID is an image the mount reads as damaged, and the tool would have
    no way of saying so. So the numbers are checked against their one source
    of truth, runtime/exi.c, rather than kept in step by hand."""
    assert c_int(define(EXI, "CARD_BYTES")) == C.CARD_BYTES == GEOM.total_bytes == 524288
    assert c_int(define(EXI, "CARD_SECTOR")) == C.CARD_SECTOR == GEOM.sector_size == 0x2000
    assert c_int(define(EXI, "CARD_ID")) == C.CARD_ID == 0x00000004
    assert GEOM.size_mbit == C.CARD_ID & 0xFC == 4
    assert GEOM.blocks == 64 and GEOM.free_blocks == 59


def test_the_default_flash_id_and_path_are_the_runtimes():
    """card_flash_id() recovers the flash ID from a valid header, so any
    twelve bytes work -- but only while the header validates. Defaulting to
    the runtime's own constant means an image this tool writes and an image
    the game formats for itself carry the same twelve bytes."""
    m = re.search(r"CARD_FLASH_ID\[12\] = \{([^}]*)\}", EXI)
    assert m, "runtime/exi.c no longer declares CARD_FLASH_ID"
    assert bytes(int(v, 0) for v in m.group(1).split(",")) == C.CARD_FLASH_ID
    m = re.search(r'g_card_path = "([^"]+)"', EXI)
    assert m and m.group(1) == C.CARD_PATH


# --------------------------------------------------------------------------
# the checksum, against the second implementation
# --------------------------------------------------------------------------


SPANS = {
    "empty": b"",
    "one byte": b"\0",
    "one zero halfword": b"\0\0",
    "one ffff halfword": b"\xff\xff",
    "an erased id block": b"\xff" * C.ID_CHECK_BYTES,
    "a zeroed directory span": b"\0" * C.CHECK_BYTES,
    "every byte value": bytes(range(256)) * 4,
    "odd length": b"\x12\x34\x56\x78\x9a",  # the trailing byte is ignored
}


@pytest.mark.parametrize("span", list(SPANS))
def test_checksum_agrees_with_a_second_implementation(span):
    assert C.checksum(SPANS[span]) == sdk_checksum(SPANS[span])


def test_checksum_folds_ffff_to_zero():
    """0x802478AC and 0x802478C0: either half coming out 0xFFFF is stored as
    0. One 0xFFFF halfword sums to 0xFFFF, which folds, and complements to 0;
    one zero halfword does it the other way round. Nothing else folds."""
    assert C.checksum(b"\xff\xff") == (0, 0)
    assert C.checksum(b"\x00\x00") == (0, 0)
    assert C.checksum(b"\x00\x01") == (1, 0xFFFE)


def test_every_checksum_the_mount_checks_is_the_one_an_independent_reader_computes(formatted):
    """The four spans __CARDVerify covers: bytes 0..507 of the ID block, then
    0..8187 of each directory block and 4..8191 of each table block."""
    image = parsed(formatted)
    assert image.header.stored == sdk_checksum(formatted[: C.ID_CHECK_BYTES])
    for index in (1, 2):
        at = GEOM.offset(index)
        block = formatted[at : at + C.BLOCK_BYTES]
        stored = (int.from_bytes(block[8188:8190], "big"), int.from_bytes(block[8190:8192], "big"))
        assert stored == sdk_checksum(block[: C.CHECK_BYTES])
    for index in (3, 4):
        at = GEOM.offset(index)
        block = formatted[at : at + C.BLOCK_BYTES]
        stored = (int.from_bytes(block[0:2], "big"), int.from_bytes(block[2:4], "big"))
        assert stored == sdk_checksum(block[4:])


def test_the_system_blocks_checksum_to_the_values_derived_by_hand(formatted):
    """4094 halfwords, all 0xFF except the check code: sum = -4093 mod 2**16
    = 0xF003 and the complements sum to 0xFFFF, which folds to 0. The table's
    span is 4094 zero halfwords except the code, 59 free and 4 last
    allocated: sum 0x3F, complements -(4094+63) = 0xEFC3."""
    image = parsed(formatted)
    assert [b.stored for b in image.directories] == [(0xF003, 0x0000), (0xF004, 0xFFFE)]
    assert [b.stored for b in image.tables] == [(0x003F, 0xEFC3), (0x0040, 0xEFC2)]


# --------------------------------------------------------------------------
# the serial
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seed", [0, 1, 12345, C.DEFAULT_FORMAT_TIME, -1, 2**63 - 1, 0x0123456789ABCDEF]
)
def test_scrambler_agrees_with_a_ctypes_transcription(seed):
    assert C.scramble(C.CARD_FLASH_ID, seed) == sdk_serial(C.CARD_FLASH_ID, seed)


@pytest.mark.parametrize("seed", [0, 7, C.DEFAULT_FORMAT_TIME, -3, 2**64 - 1])
def test_unscramble_inverts_scramble(seed):
    flash = bytes(range(0x40, 0x4C))
    assert C.unscramble(C.scramble(flash, seed), seed) == flash


def test_a_zero_seed_is_the_degenerate_case():
    """(0 * k + 12345) >> 16 is 0, so the sequence never leaves zero and the
    serial is the flash ID verbatim. Legal, and the reason the tool's default
    seed is not zero: it would hide a broken scrambler in both directions."""
    assert C.scramble(C.CARD_FLASH_ID, 0) == C.CARD_FLASH_ID
    assert C.DEFAULT_FORMAT_TIME != 0
    assert C.scramble(C.CARD_FLASH_ID, C.DEFAULT_FORMAT_TIME) != C.CARD_FLASH_ID


# --------------------------------------------------------------------------
# round trip: what was written is what is read back
# --------------------------------------------------------------------------


def test_round_trip_through_its_own_reader(formatted):
    image = parsed(formatted)
    head = image.header
    assert len(formatted) == GEOM.total_bytes == 524288
    assert head.device_id == 0
    assert head.size_mbit == GEOM.size_mbit
    assert head.encode == C.ENCODE_ANSI
    assert head.format_time == C.DEFAULT_FORMAT_TIME
    assert head.sram_bias == head.sram_language == head.vi_select == 0
    assert head.checksum_ok and head.flash_id == C.CARD_FLASH_ID
    assert head.serial == C.scramble(C.CARD_FLASH_ID, C.DEFAULT_FORMAT_TIME)
    assert [b.check_code for b in image.directories] == [0, 1]
    assert [b.check_code for b in image.tables] == [0, 1]
    assert all(b.free_blocks == b.counted_free == GEOM.free_blocks for b in image.tables)
    assert all(b.last_allocated == C.FAT_LAST_ALLOCATED for b in image.tables)
    assert image.entries() == []


def test_the_image_is_laid_out_the_way_the_format_routine_lays_it_out(formatted):
    """0xFF everywhere but the two table blocks, which are zeroed (the memset
    at 0x80249764 takes 0 where the others take 255), and nothing written
    outside the five system blocks."""
    assert formatted[38:508] == b"\xff" * 470
    assert formatted[512 : C.BLOCK_BYTES] == b"\xff" * (C.BLOCK_BYTES - 512)
    for index in (1, 2):
        at = GEOM.offset(index)
        assert formatted[at : at + 8186] == b"\xff" * 8186
    for index in (3, 4):
        at = GEOM.offset(index)
        assert formatted[at + 10 : at + C.BLOCK_BYTES] == bytes(C.BLOCK_BYTES - 10)
    assert formatted[GEOM.offset(5) :] == b"\xff" * (GEOM.total_bytes - GEOM.offset(5))


def test_two_runs_produce_the_same_image():
    assert C.format_image() == C.format_image()


def test_the_current_copy_is_the_stale_one(formatted):
    """CARDVerifyDir/Fat make the lower check code current and copy the newer
    one into it, so the next update writes the slot that was stale."""
    image = parsed(formatted)
    assert image.current_directory == 0 and image.directories[0].block == 1
    assert image.current_table == 0 and image.tables[0].block == 3
    assert C.current_slot(image.directories) == 0
    swapped = C.format_image()
    at = GEOM.offset(1)
    swapped[at : at + C.BLOCK_BYTES] = C.directory_block(2)
    assert C.current_slot(parsed(swapped).directories) == 1


# --------------------------------------------------------------------------
# reading back what a save would leave behind
# --------------------------------------------------------------------------


def test_the_reader_finds_a_file_and_follows_its_chain(formatted):
    image = parsed(with_a_file(formatted))
    files = image.entries()
    assert len(files) == 1
    entry = files[0]
    assert entry.game == "GEAE" and entry.company == "8P"
    assert entry.name == "SA_LEGENDS.000"
    assert entry.start_block == 5 and entry.blocks == 3
    assert entry.chain == [5, 6, 7] and entry.chain_ok
    assert entry.permission == 4
    assert [b.free_blocks for b in image.tables] == [GEOM.free_blocks - 3] * 2
    assert C.verify(image).result == 0


def test_a_chain_that_runs_away_does_not_hang_the_reader(formatted):
    """A file whose table entry points back at itself is a card the game
    corrupted, not a reason for the reader to loop forever."""
    image = with_a_file(formatted)
    for index in (3, 4):
        at = GEOM.offset(index) + 2 * 6
        image[at : at + 2] = (5).to_bytes(2, "big")  # 5 -> 6 -> 5
    entry = parsed(image).entries()[0]
    assert entry.chain == [5, 6] and not entry.chain_ok


def test_describe_says_what_is_on_the_card(formatted):
    text = "\n".join(C.describe(parsed(with_a_file(formatted))))
    assert "SA_LEGENDS.000" in text
    assert "flash ID       53 4F 41 50 4F 52 54 00 00 00 00 01" in text
    assert "chain 5 6 7" in text
    assert "1 of 127 entries in use" in text


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------


def test_verify_accepts_what_write_produces(formatted):
    verdict = C.verify(parsed(formatted))
    assert [c.name for c in verdict.checks if not c.ok] == []
    assert verdict.result == 0 and verdict.errors == 0 and verdict.accepted


def test_verify_rejects_a_blank_image():
    """The card the game is handed today: erased flash. CARDVerifyID reads
    0xFFFF where the device ID has to be 0 and stops there, so the answer is
    -6 BROKEN before any directory or table block is looked at."""
    verdict = C.verify(parsed(blank_image()))
    assert verdict.result == -6
    assert not verdict.accepted
    assert verdict.first_failure.name == "CARDVerifyID device ID at +32"
    assert not verdict.repairable


def test_verify_rejects_an_all_zero_image():
    """Zeros pass the device-ID test -- 0 is the value it wants -- and fail
    on the size instead."""
    verdict = C.verify(parsed(bytes(GEOM.total_bytes)))
    assert verdict.result == -6
    assert verdict.first_failure.name == "CARDVerifyID size at +34"


CORRUPTIONS = {
    "device id": ([(32, b"\x00\x01")], True, "CARDVerifyID device ID at +32", -6),
    "size": ([(34, b"\x00\x08")], True, "CARDVerifyID size at +34", -6),
    "encode": ([(36, b"\x00\x01")], True, "CARDVerifyID encode at +36", -13),
    "header checksum": (
        [(508, b"\xde\xad")],
        False,
        "CARDVerifyID header checksum at +508/+510",
        -6,
    ),
    "a flipped serial byte": (
        [(0, b"\x5a")],
        False,
        "CARDVerifyID header checksum at +508/+510",
        -6,
    ),
    "a flipped header byte": (
        [(40, b"\x00")],
        False,
        "CARDVerifyID header checksum at +508/+510",
        -6,
    ),
    "both directories": (
        [(C.CARD_SECTOR + 8188, b"\xde\xad"), (2 * C.CARD_SECTOR + 8188, b"\xde\xad")],
        False,
        "CARDVerifyDir block 1 checksum",
        -6,
    ),
    "both tables": (
        [(3 * C.CARD_SECTOR, b"\xde\xad"), (4 * C.CARD_SECTOR, b"\xde\xad")],
        False,
        "CARDVerifyFat block 3 checksum",
        -6,
    ),
}


@pytest.mark.parametrize("case", list(CORRUPTIONS))
def test_verify_rejects_a_corrupted_image(formatted, case):
    """Each mutation is meant to be caught by one named check. Where it lands
    inside the header's checksummed span and the point is the check after the
    checksum, the checksum is brought back up to date first; where it is not,
    the checksum is what catches it, which is the mount's own order. The two
    system-block cases break both copies, because one broken copy is a card
    CARDCheckExAsync repairs rather than one the game rejects."""
    mutations, fix, first, result = CORRUPTIONS[case]
    for at, raw in mutations:
        assert formatted[at : at + len(raw)] != raw, "that mutation would change nothing"
        formatted[at : at + len(raw)] = raw
    if fix:
        total, inverse = sdk_checksum(formatted[: C.ID_CHECK_BYTES])
        formatted[508:510] = total.to_bytes(2, "big")
        formatted[510:512] = inverse.to_bytes(2, "big")
    verdict = C.verify(parsed(formatted))
    assert verdict.result == result
    assert verdict.first_failure.name == first
    assert not verdict.accepted


def test_a_serial_that_does_not_match_sram_is_named_as_such(formatted):
    """Change a serial byte and fix the header checksum over it: the header
    now validates, so runtime/exi.c presents the flash ID this image implies
    and the serial check still passes -- the arrangement is a fixed point.
    It is only when the checksum does not validate that SRAM falls back to
    its built-in bytes and the serial can disagree."""
    formatted[0] ^= 0xFF
    total, inverse = sdk_checksum(formatted[: C.ID_CHECK_BYTES])
    formatted[508:510] = total.to_bytes(2, "big")
    formatted[510:512] = inverse.to_bytes(2, "big")
    verdict = C.verify(parsed(formatted))
    assert verdict.result == 0
    assert parsed(formatted).header.flash_id != C.CARD_FLASH_ID

    formatted[509] ^= 0xFF  # and now it does not validate
    verdict = C.verify(parsed(formatted))
    failed = [c.name for c in verdict.checks if not c.ok]
    assert "CARDVerifyID serial against SRAM" in failed
    detail = {c.name: c.detail for c in verdict.checks}["CARDVerifyID serial against SRAM"]
    assert "built-in" in detail


def test_verify_counts_a_wrong_free_block_count_as_an_error(formatted):
    """CARDVerifyFat recounts the zero entries in blocks 5..cBlock-1 and
    compares (0x80247F04-0x80247F48); a table that lies about it is damaged
    even though its checksum is right."""
    at = GEOM.offset(3)
    block = bytearray(formatted[at : at + C.BLOCK_BYTES])
    block[6:8] = (58).to_bytes(2, "big")
    total, inverse = sdk_checksum(block[4:])
    block[0:2] = total.to_bytes(2, "big")
    block[2:4] = inverse.to_bytes(2, "big")
    formatted[at : at + C.BLOCK_BYTES] = block
    verdict = C.verify(parsed(formatted))
    assert verdict.errors == 1 and verdict.result == -6 and verdict.repairable


@pytest.mark.parametrize("target", ["dir", "fat"])
def test_damage_leaves_exactly_one_repairable_error(formatted, target):
    """One broken copy is what CARDCheckExAsync repairs in place: the mount
    still says -6, but the game's card layer answers -6 by calling it, and it
    erases and rewrites that one block."""
    C.damage(formatted, GEOM, target)
    verdict = C.verify(parsed(formatted))
    assert verdict.errors == 1
    assert verdict.result == -6
    assert verdict.repairable and verdict.accepted


def test_two_broken_copies_are_beyond_repair(formatted):
    C.damage(formatted, GEOM, "dir")
    C.damage(formatted, GEOM, "fat")
    verdict = C.verify(parsed(formatted))
    assert verdict.errors == 2 and not verdict.repairable and not verdict.accepted


def test_a_short_file_is_read_the_way_the_runtime_reads_it(tmp_path):
    """card_load() fills 0xFF and reads what there is, so a truncated image is
    a card with erased tail -- and a file of the wrong length is reported,
    because the size the EXI ID advertises is what the mount believes."""
    path = tmp_path / "short.raw"
    path.write_bytes(bytes(C.format_image())[: GEOM.offset(3)])
    image = C.load_image(path)
    assert image.file_size == GEOM.offset(3)
    assert len(image.data) == GEOM.total_bytes
    verdict = C.verify(image)
    assert not verdict.length_ok
    assert verdict.result == -6  # the tables read as erased flash


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------


def test_write_show_and_verify_from_the_command_line(tmp_path, capsys):
    path = tmp_path / "cards" / "slotA.raw"
    assert C.main(["write", "-o", str(path)]) == 0
    assert path.read_bytes() == bytes(C.format_image())
    out = capsys.readouterr().out
    assert "CARDDoMount would return 0 (READY)" in out

    assert C.main(["verify", str(path)]) == 0
    assert C.main(["--verify", str(path)]) == 0  # the same thing spelled as a mode
    assert "would return 0 (READY)" in capsys.readouterr().out

    assert C.main(["show", str(path)]) == 0
    assert "none of the 127 entries are in use" in capsys.readouterr().out


def test_write_refuses_to_overwrite_without_force(tmp_path, capsys):
    path = tmp_path / "slotA.raw"
    path.write_bytes(b"whatever the game wrote")
    assert C.main(["write", "-o", str(path)]) == 2
    assert path.read_bytes() == b"whatever the game wrote"
    assert "--force" in capsys.readouterr().out
    assert C.main(["write", "-o", str(path), "--force"]) == 0
    assert len(path.read_bytes()) == GEOM.total_bytes


def test_verify_exits_nonzero_on_a_card_the_game_would_reject(tmp_path, capsys):
    path = tmp_path / "blank.raw"
    path.write_bytes(blank_image())
    assert C.main(["verify", str(path)]) == 1
    assert "would reject this image" in capsys.readouterr().out


def test_a_damaged_image_still_exits_zero_because_the_game_repairs_it(tmp_path, capsys):
    path = tmp_path / "slotA.raw"
    assert C.main(["write", "-o", str(path), "--damage", "dir"]) == 0
    out = capsys.readouterr().out
    assert "CARDCheckExAsync repairs it" in out
    assert C.main(["verify", str(path)]) == 0


def test_a_missing_image_is_said_so_not_traced_back(tmp_path, capsys):
    assert C.main(["verify", str(tmp_path / "nothing.raw")]) == 2
    assert "no image at" in capsys.readouterr().out


def test_another_card_size_is_formatted_consistently(tmp_path):
    """--size and --sector-size exist so an image can be built for a card
    this port does not model; the free-block count has to follow."""
    assert C.main(["write", "-o", str(tmp_path / "big.raw"), "--size", "16"]) == 0
    big = C.Geometry(16, 0x2000)
    image = C.load_image(tmp_path / "big.raw", big)
    assert image.file_size == 16 * 0x20000
    assert image.header.size_mbit == 16
    assert image.tables[0].free_blocks == big.blocks - C.SYSTEM_BLOCKS == 251
    assert C.verify(image).result == 0


# --------------------------------------------------------------------------
# the stage the mount stops at
# --------------------------------------------------------------------------


def test_a_geometry_the_mount_will_not_take_is_wrongdevice(formatted):
    """CARDDoMount calls __CARDIsCard at 0x802488E8 and answers -2 at
    0x802488FC before the first __CARDRead, so a geometry it rejects is not a
    card the image can rescue -- however good the image is. Five 8192-byte
    system blocks in 0x40000-byte sectors is a 2-block card, which is fewer
    than the eight 0x802486E8 requires."""
    verdict = C.verify(C.parse_image(bytes(formatted), C.Geometry(4, 0x40000)))
    assert verdict.result == -2
    assert not verdict.accepted and not verdict.repairable
    assert verdict.first_failure.name == "__CARDIsCard geometry"
    assert verdict.stage == "iscard"


def test_a_broken_block_under_a_rejected_geometry_is_still_wrongdevice(formatted):
    """One error would be repairable on a card the mount accepts. Under a
    geometry it does not, nothing is repaired because nothing is read."""
    C.damage(formatted, GEOM, "dir")
    verdict = C.verify(C.parse_image(bytes(formatted), C.Geometry(4, 0x40000)))
    assert verdict.result == -2 and not verdict.repairable and not verdict.accepted


def test_first_failure_names_the_check_the_mount_tripped_on(formatted):
    """CARDVerifyID returning -13 means CARDVerifyDir never ran, so a damaged
    directory block underneath it is not the failure to report."""
    C.damage(formatted, GEOM, "dir")
    formatted[36:38] = (1).to_bytes(2, "big")
    total, inverse = sdk_checksum(formatted[: C.ID_CHECK_BYTES])
    formatted[508:510] = total.to_bytes(2, "big")
    formatted[510:512] = inverse.to_bytes(2, "big")
    verdict = C.verify(C.parse_image(bytes(formatted), GEOM))
    assert verdict.result == -13 and verdict.stage == "id"
    assert verdict.first_failure.name == "CARDVerifyID encode at +36"
    assert [c.name for c in verdict.checks if not c.ok][0] == "CARDVerifyID encode at +36"


def test_an_image_the_mount_accepts_has_no_first_failure(formatted):
    verdict = C.verify(parsed(formatted))
    assert verdict.result == 0 and verdict.stage == ""
    assert verdict.first_failure is None


def test_the_length_is_a_warning_and_not_a_verdict(tmp_path, capsys):
    """runtime/exi.c card_load() reads the first CARD_BYTES of a longer file
    and pads a shorter one with 0xFF; neither reaches the mount, so neither
    can be the reason an image is rejected. Both commands say so the same
    way, which is the rule the docstring states."""
    path = tmp_path / "long.raw"
    path.write_bytes(bytes(C.format_image()) + b"\x00" * 16)
    assert C.main(["verify", str(path)]) == 0
    out = capsys.readouterr().out
    assert "would return 0 (READY)" in out
    assert "not the length of this card" in out
    assert "would accept this image" in out
    image = C.load_image(path)
    assert not C.verify(image).length_ok and C.verify(image).first_failure is None


# --------------------------------------------------------------------------
# arguments that cannot be honoured
# --------------------------------------------------------------------------


def test_a_sector_size_no_exi_id_can_name_is_refused(tmp_path, capsys):
    """SectorSizeTable (0x802FB560) holds six sizes, and a system block is
    8192 bytes whatever the sector size (0x80248C24, 0x80249714) -- so a
    4096-byte sector would lay the five blocks half on top of each other."""
    assert C.main(["write", "-o", str(tmp_path / "x.raw"), "--sector-size", "0x1000"]) == 2
    assert "not one of the sector sizes" in capsys.readouterr().out
    assert not (tmp_path / "x.raw").exists()


def test_a_card_too_small_for_five_system_blocks_is_refused(tmp_path, capsys):
    """Without the guard the slice assignment past the end of the image would
    grow it instead of failing."""
    with pytest.raises(C.CardFormatError):
        C.format_image(C.Geometry(4, 0x40000))
    assert C.main(["write", "-o", str(tmp_path / "x.raw"), "--sector-size", "0x40000"]) == 2
    assert "a format needs 5" in capsys.readouterr().out
    assert not (tmp_path / "x.raw").exists()


@pytest.mark.parametrize(
    ("option", "value", "said"),
    [
        ("--flash-id", "zz", "twelve bytes of hex"),
        ("--flash-id", "0011", "a flash ID is 12 bytes"),
        ("--format-time", "lunchtime", "is not a number"),
    ],
)
def test_an_argument_that_cannot_be_parsed_is_named_not_traced_back(
    tmp_path, capsys, option, value, said
):
    """Both converters run inside cmd_write, after argparse, so a bad value
    has to come back through main()'s handler rather than as a traceback."""
    assert C.main(["write", "-o", str(tmp_path / "x.raw"), option, value]) == 2
    out = capsys.readouterr().out
    assert out.startswith("[cardformat] ") and said in out
    assert not (tmp_path / "x.raw").exists()


def test_argparse_converters_raise_something_argparse_handles():
    """parse_int is also a `type=`, where argparse turns a ValueError into a
    usage error and lets anything else escape as a traceback."""
    assert issubclass(C.CardFormatError, ValueError)
    with pytest.raises(SystemExit) as caught:
        C.main(["write", "--sector-size", "zz"])
    assert caught.value.code == 2


# --------------------------------------------------------------------------
# config/trace.txt: a tracepoint that names no instruction says nothing
# --------------------------------------------------------------------------
#
# These belong with a general test of the file rather than with the card
# image, but the card mount and the first write are what the file is mostly
# made of now, and nothing else checks it: emit.py's `if a in self.traces`
# (recomp/emit.py:259) drops an address that is not an instruction start
# without a word, so a typo is a tracepoint that silently never fires.


TRACE = ROOT / "config" / "trace.txt"
TRACE_LINE = re.compile(r"^\s*(0x[0-9A-Fa-f]{8})\s+(\S+)\s*(?:#.*)?$")


def trace_entries() -> list[tuple[int, str]]:
    """Every entry, read the way tools/soa/hle.py load_bindings reads it."""
    out = []
    for line in TRACE.read_text(encoding="utf-8").splitlines():
        body = line.split("#", 1)[0]
        if not body.strip():
            continue
        m = TRACE_LINE.match(body)
        assert m, f"config/trace.txt line not `0xADDRESS name [# note]`: {line!r}"
        out.append((int(m.group(1), 16), m.group(2)))
    return out


def functions() -> list[tuple[int, int]]:
    """(start, size) for every function in the inventory, sorted."""
    rows = TSV.read_text(encoding="utf-8").splitlines()[1:]
    spans = [(int(r.split("\t")[0], 16), int(r.split("\t")[1])) for r in rows if r.strip()]
    return sorted(spans)


TSV = ROOT / "config" / "functions.tsv"


def test_every_tracepoint_names_an_instruction_inside_a_known_function():
    """An address that is not in the function's instruction list is dropped
    silently by the emitter, so the tracepoint never fires and the run looks
    like the site was never reached -- which is exactly the conclusion these
    entries exist to support or refute."""
    spans = functions()
    starts = [s for s, _ in spans]
    for address, name in trace_entries():
        assert address % 4 == 0, f"{name} at {address:08X} is not 4-byte aligned"
        i = bisect.bisect_right(starts, address) - 1
        assert i >= 0, f"{name} at {address:08X} is below the first function"
        start, size = spans[i]
        assert address < start + size, (
            f"{name} at {address:08X} is not inside {start:08X}+{size}, "
            "so the emitter would drop it"
        )


def test_tracepoint_names_fit_the_column_the_runtime_prints_them_in():
    """runtime/trace.c formats the name with %-24s, and two sites sharing a
    name make a log nobody can read back."""
    seen: dict[str, int] = {}
    for address, name in trace_entries():
        assert len(name) <= 24, f"{name} is {len(name)} characters, more than trace.c's %-24s"
        assert re.fullmatch(r"[A-Za-z0-9_]+(@r\d{1,2})?", name), f"{name} is not a plain name"
        assert name not in seen, f"{name} is at both {seen[name]:08X} and {address:08X}"
        seen[name] = address


def test_the_card_tracepoints_sit_in_the_functions_they_claim():
    """The entries this work added, against the inventory: a site named after
    CARDMountAsync that has drifted into its neighbour is worse than no site,
    because the log still prints the name."""
    names = {name: address for address, name in trace_entries()}
    spans = dict(functions())
    for name, start in (
        ("CardMountAsync", 0x80248DCC),
        ("CardMountAsyncRet", 0x80248DCC),
        ("CardMountCallback", 0x80248C94),
        ("CardDoMount", 0x80248884),
        ("VerifyIdVerdict", 0x80248020),
        ("VerifyIdSum", 0x802478D8),
        ("CardUpdateDirErase", 0x80247664),
        ("CardUpdateFatErase", 0x80247418),
        ("CardWritePage", 0x8024555C),
        ("CardEraseSector", 0x80245678),
        ("CardWrite", 0x80247044),
        ("CardExiFatalLock", 0x802449F4),
        ("CardExiStatusBad", 0x802449F4),
        ("CardExiHandlerDone", 0x802449F4),
        ("CardTimeout", 0x80244E94),
        ("CardCheckExRepairDir", 0x802480AC),
        ("CardCheckExRepairFat", 0x802480AC),
    ):
        assert name in names, f"config/trace.txt no longer carries {name}"
        assert start in spans, f"{start:08X} is not a function in the inventory"
        assert start <= names[name] < start + spans[start], (
            f"{name} at {names[name]:08X} is outside {start:08X}+{spans[start]}"
        )


def test_show_names_the_block_the_repair_would_rewrite(formatted):
    """With both copies intact the check codes decide which is current. With
    one damaged, CARDCheckExAsync's one-error arm (0x80248184) takes the
    damaged one instead, whatever its check code -- so `show` must not keep
    narrating the undamaged rule over a damaged image."""
    text = "\n".join(C.describe(parsed(formatted)))
    assert "the mount makes block 1 current and copies block 2 into it" in text
    C.damage(formatted, GEOM, "dir")
    text = "\n".join(C.describe(parsed(formatted)))
    assert "block 2 is damaged, so CARDCheckExAsync makes it current" in text
    assert "copies block 1 over it" in text
    at = GEOM.offset(1) + 8188
    formatted[at : at + 2] = b"\xde\xad"  # and now the other copy too
    text = "\n".join(C.describe(parsed(formatted)))
    assert "both copies are damaged" in text
    assert "the mount makes block 3 current" in text  # the table pair is untouched


def test_the_report_does_not_count_blocks_the_mount_never_looked_at(tmp_path, capsys):
    """An erased card fails every check in the report, but CARDVerifyID
    answers -6 first and __CARDVerify hands it straight back at 0x80248044,
    so the four directory and table failures below are not four damaged
    blocks the game saw -- and the report must not offer them as the reason."""
    path = tmp_path / "blank.raw"
    path.write_bytes(blank_image())
    assert C.main(["verify", str(path)]) == 1
    out = capsys.readouterr().out
    assert "first failure: CARDVerifyID device ID at +32" in out
    assert "the directory and table checks below never run" in out
    assert "damaged system blocks" not in out


@pytest.mark.parametrize("seed", [0, -1, 1 << 63, C.DEFAULT_FORMAT_TIME, 0xDEADBEEFCAFEF00D])
def test_the_signed_shift_is_faithful_but_not_load_bearing(seed):
    """fn_8025A78C is `sraw`, so the transcription uses an arithmetic shift --
    but a logical one gives the same serial for every seed, and a reader who
    changes it should learn that from a test rather than from a save that
    still works. The two results differ only above bit 47; the serial byte
    takes the low 8, and the second step's `& 0x7FFF` throws the rest away."""

    def logical(rand: int) -> int:
        return ((rand * 0x41C64E6D + 12345) & (2**64 - 1)) >> 16

    def serial(flash_id: bytes, start: int) -> bytes:
        rand, out = start, bytearray()
        for byte in flash_id:
            rand = logical(rand)
            out.append((byte + rand) & 0xFF)
            rand = logical(rand) & 0x7FFF
        return bytes(out)

    assert serial(C.CARD_FLASH_ID, seed) == C.scramble(C.CARD_FLASH_ID, seed)


# --------------------------------------------------------------------------
# .gci import and export (P3)
# --------------------------------------------------------------------------
#
# A .gci is the 64-byte directory entry as it sat on the card, then 8192
# bytes a block. Nothing here is a real save: the entries are shaped like the
# game's (GEAE 8P SA_LEGENDS.000, 3 blocks, permission 4) and the blocks are
# random. The cards the refusals are tested against have their files laid
# down by card_with_files below, not by the import being tested.

SAVE = b"SA_LEGENDS.000"


def gci_entry(
    name: bytes = SAVE, blocks: int = 3, game: bytes = b"GEAE", maker: bytes = b"8P", start=0x40
) -> bytearray:
    """The entry a .gci carries. Its start block is whatever the card it came
    from had, 0x40 here, which an import has to replace; its copy count is 7,
    which an import has to keep."""
    entry = bytearray(b"\xff" * C.ENTRY_BYTES)
    entry[0:4] = game
    entry[4:6] = maker
    entry[7] = 2  # bannerFormat
    entry[8:40] = name.ljust(32, b"\0")
    entry[40:44] = (0x0EE00000).to_bytes(4, "big")  # modified
    entry[44:48] = (0x00000060).to_bytes(4, "big")  # iconAddr
    entry[48:50] = (0x0002).to_bytes(2, "big")
    entry[50:52] = (0x0003).to_bytes(2, "big")
    entry[52] = 4  # permission
    entry[53] = 7  # copyTimes
    entry[54:56] = start.to_bytes(2, "big")  # startBlock
    entry[56:58] = blocks.to_bytes(2, "big")  # length, in blocks
    entry[60:64] = (0x00002000).to_bytes(4, "big")  # commentAddr
    return entry


def synthetic_gci(name: bytes = SAVE, blocks: int = 3, seed: int = 0, **fields) -> bytes:
    return bytes(gci_entry(name, blocks, **fields)) + random.Random(seed).randbytes(blocks * 8192)


def system(image: bytes, index: int, geom: C.Geometry = GEOM) -> bytes:
    at = geom.offset(index)
    return bytes(image[at : at + C.BLOCK_BYTES])


def sealed_directory(block: bytearray, code: int) -> bytearray:
    block[8186:8188] = (code & 0xFFFF).to_bytes(2, "big")
    total, inverse = sdk_checksum(block[: C.CHECK_BYTES])
    block[8188:8190] = total.to_bytes(2, "big")
    block[8190:8192] = inverse.to_bytes(2, "big")
    return block


def sealed_table(block: bytearray, code: int) -> bytearray:
    block[4:6] = (code & 0xFFFF).to_bytes(2, "big")
    total, inverse = sdk_checksum(block[4:])
    block[0:2] = total.to_bytes(2, "big")
    block[2:4] = inverse.to_bytes(2, "big")
    return block


def card_with_files(files, geom: C.Geometry = GEOM, last_allocated: int | None = None):
    """A formatted card holding `files`, (name, chain) pairs over random
    blocks: every entry in both directory copies and every chain in both
    tables, with the free count and last-allocated a save would leave."""
    image = C.format_image(geom)
    directory = bytearray(b"\xff" * C.BLOCK_BYTES)
    table = bytearray(C.BLOCK_BYTES)
    rng = random.Random(len(files))
    used = []
    for index, (name, chain) in enumerate(files):
        directory[index * 64 : (index + 1) * 64] = gci_entry(name, len(chain), start=chain[0])
        for here, after in zip(chain, [*chain[1:], 0xFFFF], strict=True):
            table[2 * here : 2 * here + 2] = after.to_bytes(2, "big")
            image[geom.offset(here) : geom.offset(here) + 8192] = rng.randbytes(8192)
        used += chain
    table[6:8] = (geom.free_blocks - len(used)).to_bytes(2, "big")
    last = last_allocated if last_allocated is not None else max(used, default=4)
    table[8:10] = last.to_bytes(2, "big")
    for index, code in ((1, 0), (2, 1)):
        image[geom.offset(index) : geom.offset(index) + 8192] = sealed_directory(
            bytearray(directory), code
        )
    for index, code in ((3, 0), (4, 1)):
        image[geom.offset(index) : geom.offset(index) + 8192] = sealed_table(bytearray(table), code)
    return image


def run(*args) -> int:
    return C.main([str(a) for a in args])


@pytest.fixture
def card(tmp_path) -> Path:
    path = tmp_path / "slotA.raw"
    path.write_bytes(bytes(C.format_image()))
    return path


@pytest.fixture
def save(tmp_path) -> Path:
    path = tmp_path / "save.gci"
    path.write_bytes(synthetic_gci())
    return path


def test_a_synthetic_save_imports_and_the_card_verifies_ready(tmp_path, card, save, capsys):
    out = tmp_path / "new.raw"
    assert run("import", card, save, "--out", out) == 0
    assert "CARDDoMount would return 0 (READY)" in capsys.readouterr().out
    assert card.read_bytes() == bytes(C.format_image()), "--out must leave the card alone"
    image = C.load_image(out)
    assert C.verify(image).result == 0
    (entry,) = image.entries()
    assert (entry.game, entry.company, entry.name) == ("GEAE", "8P", "SA_LEGENDS.000")
    assert entry.chain == [5, 6, 7] and entry.chain_ok
    assert b"".join(image.block(b) for b in entry.chain) == save.read_bytes()[64:]
    newest = image.tables[image.current_table ^ 1]
    assert newest.free_blocks == newest.counted_free == 56 and newest.last_allocated == 7


def test_the_default_import_writes_a_new_image_beside_the_card(tmp_path, card, save):
    assert run("import", card, save) == 0
    assert C.verify(C.load_image(tmp_path / "slotA-imported.raw")).result == 0
    assert card.read_bytes() == bytes(C.format_image())


def test_an_export_is_the_file_imported_but_for_its_start_block(tmp_path, card, save):
    """The blocks come back exactly; the entry comes back exactly except the
    start block at 0x36, which is where this card put the file."""
    assert run("import", card, save, "--out", tmp_path / "new.raw") == 0
    out = tmp_path / "back.gci"
    assert run("export", tmp_path / "new.raw", "--name", "SA_LEGENDS.000", out) == 0
    sent, back = save.read_bytes(), out.read_bytes()
    assert len(back) == len(sent) == 64 + 3 * 8192
    assert back[64:] == sent[64:]
    assert back[:0x36] == sent[:0x36] and back[0x38:64] == sent[0x38:64]
    assert back[0x36:0x38] == (5).to_bytes(2, "big") != sent[0x36:0x38]
    assert run("export", tmp_path / "new.raw", "--index", "0", tmp_path / "i.gci") == 0
    assert (tmp_path / "i.gci").read_bytes() == back


def test_an_export_imports_into_a_second_card_with_the_same_blocks(tmp_path, card, save):
    """The second card already holds a file, so the chain lands elsewhere
    and only the blocks can make the two agree."""
    assert run("import", card, save, "--out", tmp_path / "first.raw") == 0
    assert run("export", tmp_path / "first.raw", "--index", "0", tmp_path / "moved.gci") == 0
    second = tmp_path / "second.raw"
    second.write_bytes(bytes(card_with_files([(b"OTHER.000", [5, 6])])))
    assert run("import", second, tmp_path / "moved.gci", "--out", tmp_path / "second2.raw") == 0
    image = C.load_image(tmp_path / "second2.raw")
    assert C.verify(image).result == 0
    moved = next(e for e in image.entries() if e.name == "SA_LEGENDS.000")
    assert moved.chain == [7, 8, 9]
    assert b"".join(image.block(b) for b in moved.chain) == save.read_bytes()[64:]
    other = next(e for e in image.entries() if e.name == "OTHER.000")
    assert other.chain == [5, 6]


def test_two_imports_give_two_chains_that_do_not_overlap(tmp_path, card, save):
    other = tmp_path / "other.gci"
    other.write_bytes(synthetic_gci(b"SA_LEGENDS.001", blocks=4, seed=1))
    assert run("import", card, save, "--out", tmp_path / "one.raw") == 0
    assert run("import", tmp_path / "one.raw", other, "--out", tmp_path / "two.raw") == 0
    image = C.load_image(tmp_path / "two.raw")
    assert C.verify(image).result == 0
    first, second = image.entries()
    assert first.chain == [5, 6, 7] and second.chain == [8, 9, 10, 11]
    assert not set(first.chain) & set(second.chain)
    for entry, gci in ((first, save), (second, other)):
        assert b"".join(image.block(b) for b in entry.chain) == gci.read_bytes()[64:]
    assert image.tables[image.current_table ^ 1].free_blocks == 59 - 7


# Check codes before the import, (directory slot 0, slot 1) and (table slot 0,
# slot 1), chosen so that current_slot() picks each slot at least once for each
# pair, the two pairs disagree once, and the +1 crosses both s16 boundaries.
SLOT_CODES = {
    "a fresh card, both pairs pick slot 0": ((0, 1), (0, 1)),
    "one update on, both pick slot 1": ((2, 1), (2, 1)),
    "the pairs pick different slots": ((5, 3), (0, 1)),
    "codes across the s16 wraps": ((0x7FFE, 0x7FFF), (0xFFFF, 0xFFFE)),
}


def restamped(dir_codes, fat_codes) -> bytearray:
    image = C.format_image()
    for index, code in zip((1, 2), dir_codes, strict=True):
        at = GEOM.offset(index)
        image[at : at + 8192] = sealed_directory(bytearray(system(image, index)), code)
    for index, code in zip((3, 4), fat_codes, strict=True):
        at = GEOM.offset(index)
        image[at : at + 8192] = sealed_table(bytearray(system(image, index)), code)
    return image


@pytest.mark.parametrize("case", list(SLOT_CODES))
def test_the_import_writes_the_slot_current_slot_picks_and_leaves_the_other(case):
    """verify() would pass an import that wrote the wrong copy or left the
    check code alone -- both copies still checksum -- so this looks at the
    slots. The copy current_slot() picked before the import must now hold
    the newer copy's contents plus the file, with that copy's check code + 1;
    the newer copy must be byte for byte what it was."""
    before = restamped(*SLOT_CODES[case])
    image = parsed(before)
    assert C.verify(image).result == 0
    after = C.import_gci(image, C.parse_gci(synthetic_gci())).data
    now = parsed(after)

    for label, pair, now_pair in (
        ("directory", image.directories, now.directories),
        ("table", image.tables, now.tables),
    ):
        pick = C.current_slot(pair)
        kept = pair[pick ^ 1].block
        assert system(after, kept) == system(before, kept), (
            f"{label} block {kept}, the newer copy, was written"
        )
        assert now_pair[pick].check_code == (pair[pick ^ 1].check_code + 1) & 0xFFFF, (
            f"{label} block {pair[pick].block}: check code {now_pair[pick].check_code:#06x}, "
            f"not {pair[pick ^ 1].check_code:#06x} + 1"
        )

    pick = C.current_slot(image.directories)
    newer = image.directories[pick ^ 1]
    expected = bytearray(system(before, newer.block))
    expected[0:64] = gci_entry(start=5)
    sealed_directory(expected, newer.check_code + 1)
    assert system(after, image.directories[pick].block) == bytes(expected)

    pick = C.current_slot(image.tables)
    newer = image.tables[pick ^ 1]
    expected = bytearray(system(before, newer.block))
    for here, then in ((5, 6), (6, 7), (7, 0xFFFF)):
        expected[2 * here : 2 * here + 2] = then.to_bytes(2, "big")
    expected[6:8] = (56).to_bytes(2, "big")
    expected[8:10] = (7).to_bytes(2, "big")
    sealed_table(expected, newer.check_code + 1)
    assert system(after, image.tables[pick].block) == bytes(expected)


def test_what_was_written_is_verified_from_disk_and_exits_1_unless_ready(
    tmp_path, card, save, monkeypatch, capsys
):
    """The re-verification reads the file back rather than trusting the
    bytes it meant to write: here the write breaks both directory copies on
    the way to disk."""
    write = C._write_image

    def broken(path, data):
        data = bytearray(data)
        for index in (1, 2):
            data[GEOM.offset(index) + 8188] ^= 0xFF
        write(path, bytes(data))

    monkeypatch.setattr(C, "_write_image", broken)
    assert run("import", card, save, "--out", tmp_path / "new.raw") == 1
    assert "CARDDoMount would return -6 (BROKEN)" in capsys.readouterr().out


def test_a_directory_code_crossing_0x7fff_reads_back_as_the_old_directory(tmp_path, save, capsys):
    """0x7FFF + 1 is 0x8000, -32768 to the mount's signed subtraction, so the
    copy just written reads as the older one and the mount would show the
    card without the file -- as it would after the game's own 32768th
    update. The image is READY; the read-back is what says so."""
    card = tmp_path / "old.raw"
    card.write_bytes(bytes(restamped((0x7FFE, 0x7FFF), (0, 1))))
    assert run("import", card, save, "--out", tmp_path / "new.raw") == 1
    text = capsys.readouterr().out
    assert "CARDDoMount would return 0 (READY)" in text
    assert "entry 0 does not read back as the file imported" in text
    assert C.load_image(tmp_path / "new.raw").entries() == []


def test_blocks_are_handed_out_after_the_last_allocated_one_and_wrap_to_5():
    """__CARDAllocBlock starts one past the table's last-allocated block, not
    at the first free one: 10 is free here but 63 goes first, and the search
    then wraps from the card's end to block 5."""
    image = parsed(card_with_files([(b"OTHER.000", [5, 6, 7, 8, 9])], last_allocated=62))
    done = C.import_gci(image, C.parse_gci(synthetic_gci()))
    assert done.chain == [63, 10, 11]
    now = parsed(done.data)
    newest = now.tables[now.current_table ^ 1]
    assert newest.last_allocated == 11 and newest.free_blocks == 59 - 8
    assert now.fat[63] == 10 and now.fat[10] == 11 and now.fat[11] == 0xFFFF


GCI_REFUSALS = {
    "another maker": (lambda: synthetic_gci(maker=b"01"), "only GEAE 8P"),
    "another game": (lambda: synthetic_gci(game=b"GEAJ"), "only GEAE 8P"),
    "a size that is not 0x40 + 8192 x n": (lambda: synthetic_gci()[:-1], "not 0x40 + 8192 x n"),
    "shorter than an entry": (lambda: synthetic_gci()[:63], "not 0x40 + 8192 x n"),
    "a size the entry disagrees with": (
        lambda: synthetic_gci()[: 64 + 2 * 8192],
        "says 3 blocks at 0x38, but the file holds 2",
    ),
    "zero blocks": (lambda: bytes(gci_entry(blocks=0)), "says 0 blocks"),
}


@pytest.mark.parametrize("case", list(GCI_REFUSALS))
def test_a_gci_that_cannot_go_on_the_card_is_refused_and_nothing_written(
    tmp_path, card, capsys, case
):
    make, said = GCI_REFUSALS[case]
    gci = tmp_path / "bad.gci"
    gci.write_bytes(make())
    out = tmp_path / "new.raw"
    assert run("import", card, gci, "--out", out) == 2
    text = capsys.readouterr().out
    assert text.startswith("[cardformat] ") and said in text
    assert not out.exists()
    assert card.read_bytes() == bytes(C.format_image())


def test_a_name_already_on_the_card_is_refused_unless_replace(tmp_path, save, capsys):
    """--replace deletes the old file first, in the same update: its chain is
    freed and its entry erased, and the new one is allocated after the old
    one's last block, as __CARDAllocBlock would."""
    card = tmp_path / "held.raw"
    card.write_bytes(bytes(card_with_files([(SAVE, [5, 6, 7])])))
    out = tmp_path / "new.raw"
    assert run("import", card, save, "--out", out) == 2
    assert "entry 0 is already GEAE 8P SA_LEGENDS.000; --replace" in capsys.readouterr().out
    assert not out.exists()

    assert run("import", card, save, "--out", out, "--replace") == 0
    assert "deleted entry 0, SA_LEGENDS.000, and freed its 3 blocks" in capsys.readouterr().out
    image = C.load_image(out)
    assert C.verify(image).result == 0
    (entry,) = image.entries()
    assert entry.chain == [8, 9, 10]
    assert b"".join(image.block(b) for b in entry.chain) == save.read_bytes()[64:]
    assert [image.fat[b] for b in (5, 6, 7)] == [0, 0, 0]
    assert image.tables[image.current_table ^ 1].free_blocks == 56


@pytest.mark.parametrize("state", ["one damaged directory copy", "erased flash"])
def test_a_card_that_does_not_verify_ready_is_refused(tmp_path, save, capsys, state):
    """A card with one damaged copy is one the game repairs, but not READY:
    which directory it would keep is not what the check codes say."""
    image = C.format_image()
    if state == "erased flash":
        image = bytearray(blank_image())
    else:
        C.damage(image, GEOM, "dir")
    card = tmp_path / "bad.raw"
    card.write_bytes(bytes(image))
    out = tmp_path / "new.raw"
    assert run("import", card, save, "--out", out) == 2
    assert "does not verify" in capsys.readouterr().out
    assert not out.exists()


def test_not_enough_free_blocks_on_the_runtimes_card(tmp_path, capsys):
    """59 blocks for files, 57 of them used: a 3-block save does not fit and
    a 2-block one does, exactly."""
    files = [(f"FILLER.{n:03d}".encode(), [5 + 3 * n, 6 + 3 * n, 7 + 3 * n]) for n in range(19)]
    card = tmp_path / "full.raw"
    card.write_bytes(bytes(card_with_files(files)))
    image = C.load_image(card)
    assert GEOM.free_blocks == 59 and C.verify(image).result == 0
    assert image.tables[0].free_blocks == 2

    gci = tmp_path / "three.gci"
    gci.write_bytes(synthetic_gci(blocks=3))
    out = tmp_path / "new.raw"
    assert run("import", card, gci, "--out", out) == 2
    text = capsys.readouterr().out
    assert "not enough free blocks" in text and "is 3 blocks and the card has 2 free" in text
    assert not out.exists()

    gci.write_bytes(synthetic_gci(blocks=2))
    assert run("import", card, gci, "--out", out) == 0
    assert next(e for e in C.load_image(out).entries() if e.name == "SA_LEGENDS.000").chain == [
        62,
        63,
    ]


def test_no_free_entry_on_a_16_mbit_card_with_127_files(tmp_path, capsys):
    """251 blocks for files and 127 used, one each: the blocks are there,
    the directory entries are not."""
    big = C.Geometry(16, 0x2000)
    files = [(f"FILLER.{n:03d}".encode(), [5 + n]) for n in range(127)]
    card = tmp_path / "big.raw"
    card.write_bytes(bytes(card_with_files(files, big)))
    image = C.load_image(card, big)
    assert big.free_blocks == 251 and C.verify(image).result == 0
    assert len(image.entries()) == 127 and image.tables[0].free_blocks == 124

    gci = tmp_path / "one.gci"
    gci.write_bytes(synthetic_gci(blocks=1))
    out = tmp_path / "new.raw"
    assert run("import", card, gci, "--out", out, "--size", "16") == 2
    assert "no free entry: all 127" in capsys.readouterr().out
    assert not out.exists()


def test_in_place_backs_the_card_up_before_it_writes(tmp_path, card, save, monkeypatch, capsys):
    monkeypatch.setattr(C, "soa_running", lambda name: False)
    before = card.read_bytes()
    backups_at_write = []
    write = C._write_image

    def spy(path, data):
        backups_at_write.append(sorted(p.name for p in tmp_path.glob("slotA.raw.bak-*")))
        write(path, data)

    monkeypatch.setattr(C, "_write_image", spy)
    assert run("import", card, save, "--in-place") == 0
    (backup,) = tmp_path.glob("slotA.raw.bak-*")
    assert re.fullmatch(r"slotA\.raw\.bak-\d{8}-\d{6}", backup.name)
    assert backups_at_write == [[backup.name]], "the card was written before its backup"
    assert backup.read_bytes() == before
    assert card.read_bytes() != before
    assert C.verify(C.load_image(card)).result == 0
    assert f"backed up {card} to {backup}" in capsys.readouterr().out


def test_in_place_refuses_while_the_port_is_running(tmp_path, card, save, monkeypatch, capsys):
    """runtime/exi.c keeps the card open and writes through, so an import
    under a running port could be overwritten half-way."""
    asked = []

    def running(name):
        asked.append(name)
        return True

    monkeypatch.setattr(C, "soa_running", running)
    assert run("import", card, save, "--in-place") == 2
    assert asked == ["soa.exe"]
    assert "soa.exe is running" in capsys.readouterr().out
    assert card.read_bytes() == bytes(C.format_image())
    assert list(tmp_path.glob("*.bak-*")) == []


@pytest.mark.skipif(sys.platform != "win32", reason="tasklist is Windows'")
def test_the_process_check_finds_what_runs_and_not_what_does_not():
    """The real tasklist: the interpreter running this test is running, and
    a name nothing has is not -- whether or not a soa.exe is up right now."""
    assert C.soa_running(Path(sys.executable).name)
    assert not C.soa_running("p3-no-such-process.exe")


def test_a_process_check_that_cannot_run_refuses(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError(2, "no tasklist here")

    monkeypatch.setattr(C.subprocess, "run", missing)
    with pytest.raises(C.CardFormatError, match="cannot tell whether soa.exe is running"):
        C.soa_running()


def test_out_may_not_be_the_card_or_an_existing_file(tmp_path, card, save, capsys):
    assert run("import", card, save, "--out", card) == 2
    assert "--in-place does that" in capsys.readouterr().out
    taken = tmp_path / "taken.raw"
    taken.write_bytes(b"something")
    assert run("import", card, save, "--out", taken) == 2
    assert "--force" in capsys.readouterr().out
    assert taken.read_bytes() == b"something"
    assert run("import", card, save, "--out", taken, "--force") == 0


def test_the_default_export_name_is_a_dolphin_gci_folders(tmp_path, capsys):
    """DEntry::GCI_FileName as recalled -- maker, game, file name -- and not
    checked against Dolphin's source; see gci_file_name."""
    card = tmp_path / "held.raw"
    card.write_bytes(bytes(card_with_files([(SAVE, [5, 6, 7])])))
    assert run("export", card, "--index", "0") == 0
    assert (tmp_path / "8P-GEAE-SA_LEGENDS.000.gci").stat().st_size == 64 + 3 * 8192
    folder = tmp_path / "gci"
    folder.mkdir()
    assert run("export", card, "--name", "SA_LEGENDS.000", folder) == 0
    assert (folder / "8P-GEAE-SA_LEGENDS.000.gci").exists()
    assert run("export", card, "--index", "0", folder) == 2
    assert "--force" in capsys.readouterr().out
    assert C.gci_file_name(gci_entry(b"A/B:C__D")) == "8P-GEAE-A__2f__B__3a__C__5f____5f__D.gci"


@pytest.mark.parametrize(
    ("which", "said"),
    [
        (["--index", "3"], "entry 3 is free"),
        (["--index", "127"], "not one of 0..126"),
        (["--name", "NOPE"], "no file named 'NOPE'"),
    ],
)
def test_export_says_which_file_it_could_not_find(tmp_path, capsys, which, said):
    card = tmp_path / "held.raw"
    card.write_bytes(bytes(card_with_files([(SAVE, [5, 6, 7])])))
    assert run("export", card, *which, tmp_path / "x.gci") == 2
    assert said in capsys.readouterr().out
    assert not (tmp_path / "x.gci").exists()
