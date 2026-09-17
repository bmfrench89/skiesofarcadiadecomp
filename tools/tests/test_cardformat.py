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

The last section is not about the image at all: it checks that every entry in
config/trace.txt names a real instruction inside a real function, because the
recompiler drops one that does not without saying so, and most of that file is
now the card mount and the first write. It reads config/functions.tsv, which is
metadata the repository carries, not game data.
"""

import bisect
import ctypes
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
