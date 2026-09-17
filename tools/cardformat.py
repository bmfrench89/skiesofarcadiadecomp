#!/usr/bin/env python3
"""A formatted memory card, written and read back without launching the port.

    python tools/cardformat.py write                        # build/cards/slotA.raw
    python tools/cardformat.py write --damage dir           # one repairable error
    python tools/cardformat.py show build/cards/slotA.raw
    python tools/cardformat.py verify build/cards/slotA.raw  # --verify PATH works too

The game has never written a byte to the card because it has never mounted
one. runtime/exi.c hands it a blank image -- 0xFF, the way erased flash reads
-- and CARDVerifyID (0x802478D8) reads 0xFFFF at ID-block offset 32 where the
device ID has to be 0, so __CARDVerify (0x80248020) answers -6 BROKEN and the
five system blocks the mount just read are thrown away. `write` lays those
five blocks down the way __CARDFormatRegionAsync (0x802491F8) lays them down,
so that the mount has something to accept; `verify` re-runs the mount's own
checks over an image and says which pass, so an image can be judged without
building the port; and `show` prints what an image contains, which is how we
will read back whatever the game finally writes.

THE IMAGE. 524288 bytes, 64 blocks of 8192, of which the first five are the
system area and the other 59 hold files. Every field is big-endian.

  block 0  0x000000  ID block: 0xFF, with the header in its first 0x26 bytes
                     and a checksum pair at 508/510 over bytes 0..507
  block 1  0x002000  directory: 127 64-byte entries, all 0xFF (an entry is
                     free when its first byte is 0xFF), then a CARDDirCheck
                     with the check code at 8186 and the checksum pair at
                     8188/8190 over bytes 0..8187
  block 2  0x004000  the directory again, check code 1
  block 3  0x006000  file allocation table: u16 per block, all zero (free),
                     with checkSum/checkSumInv at 0/2 over bytes 4..8191,
                     the check code at 4, the free-block count at 6 and the
                     last allocated block at 8
  block 4  0x008000  the table again, check code 1
  5..63    0x00A000  0xFF, untouched by a format

The ID block's fields: serial[12] at 0, the 64-bit format time at 12, the
SRAM counter bias at 20, the SRAM language at 24, the halfword VI 0xCC00206E
answers at 28, the device ID at 32, the size in Mbit at 34 and the font
encoding at 36. Only the device ID, the size, the encoding, the serial and
the checksum are read again by anything.

WHAT MUST MATCH THE RUNTIME (runtime/exi.c):

  CARD_BYTES 524288        the image is exactly that long, or card_load()
                           warns and uses the first 524288 bytes
  CARD_ID 0x00000004       CARDDoMount derives the geometry from this and
                           nothing else: 4 Mbit, so the size field at 34
                           must read 4; sector-table index 0, so 8192-byte
                           sectors and 64 blocks, so the free-block count
                           must read 64 - 5 = 59
  CARD_SECTOR 0x2000       where each system block starts
  the default path         build/cards/slotA.raw, which SOA_CARD overrides

and one value that must match the DOL rather than the runtime: the encoding
at offset 36 must equal what OSGetFontEncode (0x80234E58) answered when
CARDInit cached it, or the mount returns -13 ENCODING instead of -6. That is
0 on this US NTSC build -- the runtime writes 0 to 0x800000CC and leaves VI
0xCC00206E unmodelled, so it reads as zero -- and --encode exists for the day
that stops being true.

WHAT IS FREE. The 64-bit format time is a pure seed: CARDVerifyID reads it
back out of the image and re-derives the serial from it, so any value works
and this tool uses a fixed one so that two runs produce identical images. The
twelve flash-ID bytes are free too, but only because runtime/exi.c derives
SRAM's flashID[0] from the image's own header (card_flash_id) whenever the
header checksum validates, and falls back to its built-in constant when it
does not -- silently. So an image whose header checksum is wrong is compared
against those built-in bytes and fails CARDVerifyID on the serial as well;
`verify` says so in as many words. The default flash ID here is the runtime's
own constant, which is also what the game would write if it formatted a blank
card itself, so an image from this tool and an image from the game agree. The
SRAM bias, the SRAM language and the VI word are written by the format and
read by nothing; they are zero here. The directory and table contents are
fixed by the format: 0xFF and zero respectively.

EXIT STATUS, the same rule for `verify` and for `write`, which verifies what it
wrote: 0 when the game's card layer would carry on with the image -- the mount
returns READY, or it returns BROKEN with a single damaged system block, which
CARDCheckExAsync (0x802480AC) repairs in place on the next mount -- and 1 when
it would not. A file that is not 524288 bytes long is a warning in the report
and not a rejection: card_load() pads it with erased flash or reads the first
524288 bytes, and the mount never learns which happened.

--damage exists for that second case, and is the cheapest first write we know
of: one sector erase and then sixty-four page programs, with no button pressed
and no menu entered. Sixty-four because __CARDWrite (0x80247044) turns the
length into a page count at 0x80247078 with `rlwinm r0,r5,25,7,31`, len >> 7,
and __CARDWritePage (0x8024555C) programs 128 bytes per command -- so an
8192-byte block is 64 commands, each with its own completion interrupt, not one
big one.

WHERE THE OUTPUT GOES: build/cards/, gitignored, and a directory guard.py
forbids outright -- a card image is game data the moment the game writes to it.
Both this tool's default path and runtime/exi.c's g_card_path are relative, so
they name the same file only while both processes run from the repository root;
give SOA_CARD an absolute path when they do not.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# what runtime/exi.c presents, and what the SDK makes of it
# ---------------------------------------------------------------------------

CARD_ID = 0x00000004  # the EXI device ID the model answers command 0x00 with
CARD_BYTES = 4 << 17  # 524288, and the length card_load() expects
CARD_SECTOR = 0x2000  # the erase granularity in the model's command 0xF1
CARD_PATH = "build/cards/slotA.raw"  # g_card_path, before SOA_CARD
CARD_FLASH_ID = bytes((0x53, 0x4F, 0x41, 0x50, 0x4F, 0x52, 0x54, 0, 0, 0, 0, 0x01))

# SectorSizeTable at 0x802FB560, indexed by (id >> 11) & 7 (CARDDoMount
# 0x80248934). The two zero entries are sizes no EXI ID can name a card with.
SECTOR_SIZES = (0x2000, 0x4000, 0x8000, 0x10000, 0x20000, 0x40000, 0, 0)
CARD_SIZES = (4, 8, 16, 32, 64, 128)  # the id & 0xFC values CARDIsCard accepts

BLOCK_BYTES = 8192  # a system block, whatever the sector size (CARDFormatCallback)
SYSTEM_BLOCKS = 5  # ID, directory, directory copy, table, table copy
DIR_ENTRIES = 127  # the 128th 64-byte entry is the CARDDirCheck
ENTRY_BYTES = 64
FIRST_FILE_BLOCK = 5
FAT_LAST_ALLOCATED = 4  # so the first block handed out is 5
CHECK_BYTES = 8188  # the checksummed span of a directory or table block
ID_CHECK_BYTES = 508

# The time base is the bus clock over four (recalled, not established here),
# and nothing checks the format time anyway: it is the scramble seed and this
# is one hour of it, fixed so that two runs of this tool agree byte for byte.
TIMEBASE_HZ = 40_500_000
DEFAULT_FORMAT_TIME = 3600 * TIMEBASE_HZ

ENCODE_ANSI = 0  # what OSGetFontEncode answers on this build
ENCODE_SJIS = 1

RESULT_NAMES = {
    0: "READY",
    -2: "WRONGDEVICE",
    -3: "NOCARD",
    -5: "IOERROR",
    -6: "BROKEN",
    -13: "ENCODING",
}

MASK64 = (1 << 64) - 1


class CardFormatError(ValueError):
    """Something the caller asked for that cannot be done.

    A ValueError so that argparse's own `type=` handling turns one raised
    inside a converter into a usage error rather than a traceback; main()
    catches it by name everywhere else.
    """


# ---------------------------------------------------------------------------
# the two algorithms the card library uses
# ---------------------------------------------------------------------------


def checksum(data: bytes) -> tuple[int, int]:
    """__CARDCheckSum (0x80247728), written out again here.

    A u16 sum of the big-endian halfwords and a u16 sum of their complements,
    each accumulated mod 2**16 and each folded to 0 when it comes out 0xFFFF
    (0x802478AC, 0x802478C0). An odd trailing byte is ignored, as `bytes >> 1`
    ignores it there.
    """
    total = inverse = 0
    for i in range(0, len(data) - 1, 2):
        word = (data[i] << 8) | data[i + 1]
        total = (total + word) & 0xFFFF
        inverse = (inverse + (~word & 0xFFFF)) & 0xFFFF
    return (0 if total == 0xFFFF else total, 0 if inverse == 0xFFFF else inverse)


def _scramble_step(rand: int) -> int:
    """rand = (rand * 0x41C64E6D + 12345) >> 16, arithmetic, on 64 bits.

    The multiply-add at 0x80249640-0x80249650 is 64-bit and the shift helper
    at 0x8025A78C is a signed right shift, which is what Python's >> does to a
    negative int. Transcribed faithfully, but nothing observable turns on it:
    the two shifts differ only above bit 47, the serial byte takes the low 8
    and the next state is masked to 0x7FFF, so a logical shift would produce
    the same twelve bytes for every seed. The test says so as well.
    """
    value = (rand * 0x41C64E6D + 12345) & MASK64
    if value >> 63:
        value -= 1 << 64
    return value >> 16


def scramble(flash_id: bytes, format_time: int) -> bytes:
    """The serial __CARDFormatRegionAsync writes: each flash-ID byte plus the
    next byte of the sequence, which advances twice per byte and is masked to
    0x7FFF after the second step (0x8024965C-0x80249698)."""
    rand = format_time
    out = bytearray()
    for byte in flash_id:
        rand = _scramble_step(rand)
        out.append((byte + rand) & 0xFF)
        rand = _scramble_step(rand) & 0x7FFF
    return bytes(out)


def unscramble(serial: bytes, format_time: int) -> bytes:
    """The flash ID a serial was made from: CARDVerifyID's comparison
    (0x80247AB8) run backwards, which is what runtime/exi.c card_flash_id
    does to decide what SRAM presents."""
    rand = format_time
    out = bytearray()
    for byte in serial:
        rand = _scramble_step(rand)
        out.append((byte - rand) & 0xFF)
        rand = _scramble_step(rand) & 0x7FFF
    return bytes(out)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Geometry:
    """What CARDDoMount computes from the EXI device ID and stores in the
    control block: the size in Mbit at +8, the sector size at +12 and the
    block count at +16 (0x80248908-0x80248970)."""

    size_mbit: int
    sector_size: int

    @property
    def total_bytes(self) -> int:
        return (self.size_mbit << 20) >> 3

    @property
    def blocks(self) -> int:
        return self.total_bytes // self.sector_size

    @property
    def free_blocks(self) -> int:
        return self.blocks - SYSTEM_BLOCKS

    def offset(self, block: int) -> int:
        return block * self.sector_size

    def describe(self) -> str:
        return (
            f"{self.size_mbit} Mbit, {self.blocks} blocks of {self.sector_size} bytes "
            f"({SYSTEM_BLOCKS} system, {self.free_blocks} for files)"
        )


def geometry_from_exi_id(card_id: int) -> Geometry:
    """The geometry the mount derives, and the only one it will accept."""
    sector = SECTOR_SIZES[(card_id >> 11) & 7]
    if not sector:
        raise CardFormatError(f"EXI ID {card_id:08X} names sector-size table entry 0")
    return Geometry(card_id & 0xFC, sector)


RUNTIME_GEOMETRY = geometry_from_exi_id(CARD_ID)


def is_card(geom: Geometry) -> tuple[bool, str]:
    """__CARDIsCard (0x8024863C), the part that depends on the geometry: a
    size in the table and at least eight blocks (0x802486E8)."""
    if geom.size_mbit not in CARD_SIZES:
        return False, f"{geom.size_mbit} Mbit is not one of {', '.join(str(s) for s in CARD_SIZES)}"
    if geom.blocks < 8:
        return False, f"{geom.blocks} blocks, fewer than the 8 __CARDIsCard requires"
    return True, f"{geom.size_mbit} Mbit, {geom.sector_size}-byte sectors, {geom.blocks} blocks"


# ---------------------------------------------------------------------------
# writing the five system blocks
# ---------------------------------------------------------------------------


def id_block(
    geom: Geometry,
    flash_id: bytes = CARD_FLASH_ID,
    format_time: int = DEFAULT_FORMAT_TIME,
    encode: int = ENCODE_ANSI,
    sram_bias: int = 0,
    sram_language: int = 0,
    vi_select: int = 0,
) -> bytes:
    """Block 0 as 0x8024922C-0x802496EC writes it: 0xFF, eight fields and the
    checksum pair over the first 508 bytes."""
    if len(flash_id) != 12:
        raise CardFormatError(f"a flash ID is 12 bytes, not {len(flash_id)}")
    block = bytearray(b"\xff" * BLOCK_BYTES)
    block[0:12] = scramble(flash_id, format_time)
    block[12:20] = (format_time & MASK64).to_bytes(8, "big")
    block[20:24] = (sram_bias & 0xFFFFFFFF).to_bytes(4, "big")
    block[24:28] = (sram_language & 0xFFFFFFFF).to_bytes(4, "big")
    block[28:32] = (vi_select & 0xFFFF).to_bytes(4, "big")
    block[32:34] = (0).to_bytes(2, "big")  # deviceID: CARDVerifyID demands 0
    block[34:36] = geom.size_mbit.to_bytes(2, "big")
    block[36:38] = encode.to_bytes(2, "big")
    total, inverse = checksum(block[:ID_CHECK_BYTES])
    block[508:510] = total.to_bytes(2, "big")
    block[510:512] = inverse.to_bytes(2, "big")
    return bytes(block)


def directory_block(check_code: int) -> bytes:
    """Block 1 or 2 as 0x802496F4-0x80249734 writes it: 0xFF, so all 127
    entries read as free, with the check code at 8186 and the pair at
    8188/8190 over everything before them."""
    block = bytearray(b"\xff" * BLOCK_BYTES)
    block[8186:8188] = (check_code & 0xFFFF).to_bytes(2, "big")
    total, inverse = checksum(block[:CHECK_BYTES])
    block[8188:8190] = total.to_bytes(2, "big")
    block[8190:8192] = inverse.to_bytes(2, "big")
    return bytes(block)


def fat_block(check_code: int, geom: Geometry) -> bytes:
    """Block 3 or 4 as 0x80249750-0x802497A4 writes it. Zero-filled, not
    0xFF: a zero entry is a free block, and the checksum covers everything
    after the pair itself."""
    block = bytearray(BLOCK_BYTES)
    block[4:6] = (check_code & 0xFFFF).to_bytes(2, "big")
    block[6:8] = geom.free_blocks.to_bytes(2, "big")
    block[8:10] = FAT_LAST_ALLOCATED.to_bytes(2, "big")
    total, inverse = checksum(block[4:])
    block[0:2] = total.to_bytes(2, "big")
    block[2:4] = inverse.to_bytes(2, "big")
    return bytes(block)


def format_image(
    geom: Geometry = RUNTIME_GEOMETRY,
    flash_id: bytes = CARD_FLASH_ID,
    format_time: int = DEFAULT_FORMAT_TIME,
    encode: int = ENCODE_ANSI,
) -> bytearray:
    """A whole card: erased flash with the five system blocks written into it,
    each 8192 bytes at the start of its own sector."""
    if geom.blocks < SYSTEM_BLOCKS:
        raise CardFormatError(
            f"a {geom.size_mbit} Mbit card in {geom.sector_size}-byte sectors is "
            f"{geom.blocks} blocks; a format needs {SYSTEM_BLOCKS} of {BLOCK_BYTES} bytes"
        )
    image = bytearray(b"\xff" * geom.total_bytes)
    blocks = [
        id_block(geom, flash_id, format_time, encode),
        directory_block(0),
        directory_block(1),
        fat_block(0, geom),
        fat_block(1, geom),
    ]
    for index, block in enumerate(blocks):
        start = geom.offset(index)
        image[start : start + BLOCK_BYTES] = block
    return image


DAMAGE_TARGETS = {
    # name: (block, offset of the stored checkSum within it)
    "dir": (2, 8188),
    "fat": (4, 0),
}


def damage(image: bytearray, geom: Geometry, target: str) -> str:
    """Break one system block's stored checksum, and only that.

    CARDVerifyDir (0x80247B5C) / CARDVerifyFat (0x80247D9C) then count exactly
    one error, __CARDVerify (0x80248020) turns that into -6 BROKEN, and the
    game's card layer answers -6 by calling CARDCheckExAsync: fn_801A2500
    compares -6 at 0x801A2588 and calls it at 0x801A25A0, fn_801A28F4 at
    0x801A2A4C and 0x801A2A60. CARDCheckEx takes its one-error arm at
    0x80248178 (the `cmpi r5,1` at 0x80248134 having gone equal), stores
    dir[bad] into card->currentDir at 0x802481A8, memcpys the good twin over
    it at 0x802481C4 and calls __CARDUpdateDir (0x80247664) or
    __CARDUpdateFatBlock (0x80247418): one sector erase, then the block
    rewritten 128 bytes at a time.
    """
    block, offset = DAMAGE_TARGETS[target]
    at = geom.offset(block) + offset
    stored = int.from_bytes(image[at : at + 2], "big")
    image[at : at + 2] = (stored ^ 0xFFFF).to_bytes(2, "big")
    kind = "directory" if target == "dir" else "allocation table"
    return (
        f"{kind} copy in block {block}: checksum at +{offset} flipped from "
        f"{stored:04X} to {stored ^ 0xFFFF:04X}"
    )


# ---------------------------------------------------------------------------
# reading an image back
# ---------------------------------------------------------------------------


def _u16(data: bytes, at: int) -> int:
    return int.from_bytes(data[at : at + 2], "big")


def _s16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _text(raw: bytes) -> str:
    """A fixed-width name as the game leaves it: NUL-padded, and 0xFF when
    nothing has ever been written there."""
    out = raw.split(b"\0", 1)[0].rstrip(b"\xff")
    return "".join(chr(c) if 0x20 <= c < 0x7F else "." for c in out)


@dataclass(frozen=True)
class Header:
    """Block 0's first 0x26 bytes, plus its checksum as stored and as this
    tool recomputes it."""

    serial: bytes
    format_time: int
    sram_bias: int
    sram_language: int
    vi_select: int
    device_id: int
    size_mbit: int
    encode: int
    stored: tuple[int, int]
    computed: tuple[int, int]

    @property
    def checksum_ok(self) -> bool:
        return self.stored == self.computed

    @property
    def flash_id(self) -> bytes | None:
        """What runtime/exi.c will present as SRAM flashID[0]: the serial
        descrambled, or None when the header checksum does not validate and
        card_flash_id falls back to its built-in constant."""
        return unscramble(self.serial, self.format_time) if self.checksum_ok else None


@dataclass(frozen=True)
class SystemBlock:
    """One of the four directory/table blocks, with everything the mount
    checks about it."""

    kind: str  # "directory" or "table"
    block: int
    check_code: int
    stored: tuple[int, int]
    computed: tuple[int, int]
    free_blocks: int | None = None
    last_allocated: int | None = None
    counted_free: int | None = None

    @property
    def checksum_ok(self) -> bool:
        return self.stored == self.computed

    @property
    def free_ok(self) -> bool:
        return self.free_blocks is None or self.free_blocks == self.counted_free

    @property
    def ok(self) -> bool:
        return self.checksum_ok and self.free_ok


@dataclass(frozen=True)
class DirEntry:
    """One 64-byte directory entry (CARDCreateCallback 0x80249CEC,
    CARDGetStatus 0x8024AB94)."""

    index: int
    game: str
    company: str
    banner_format: int
    name: str
    modified: int
    icon_addr: int
    icon_format: int
    icon_speed: int
    permission: int
    copy_times: int
    start_block: int
    blocks: int
    comment_addr: int
    chain: list[int]

    @property
    def chain_ok(self) -> bool:
        return len(self.chain) == self.blocks


@dataclass(frozen=True)
class CardImage:
    path: str
    file_size: int
    geom: Geometry
    data: bytes
    header: Header
    directories: list[SystemBlock]
    tables: list[SystemBlock]

    def block(self, index: int) -> bytes:
        start = self.geom.offset(index)
        return self.data[start : start + BLOCK_BYTES]

    @property
    def current_directory(self) -> int:
        return current_slot(self.directories)

    @property
    def current_table(self) -> int:
        return current_slot(self.tables)

    @property
    def fat(self) -> list[int]:
        """The allocation table the mount ends up using: the newer copy."""
        block = self.block(self.tables[self.current_table ^ 1].block)
        return [_u16(block, 2 * i) for i in range(self.geom.blocks)]

    def entries(self) -> list[DirEntry]:
        """Every directory entry in use, out of the newer copy."""
        block = self.block(self.directories[self.current_directory ^ 1].block)
        fat = self.fat
        out: list[DirEntry] = []
        for index in range(DIR_ENTRIES):
            raw = block[index * ENTRY_BYTES : (index + 1) * ENTRY_BYTES]
            if raw[0] == 0xFF:  # __CARDAccess 0x80249900: free
                continue
            start = _u16(raw, 54)
            out.append(
                DirEntry(
                    index=index,
                    game=_text(raw[0:4]),
                    company=_text(raw[4:6]),
                    banner_format=raw[7],
                    name=_text(raw[8:40]),
                    modified=int.from_bytes(raw[40:44], "big"),
                    icon_addr=int.from_bytes(raw[44:48], "big"),
                    icon_format=_u16(raw, 48),
                    icon_speed=_u16(raw, 50),
                    permission=raw[52],
                    copy_times=raw[53],
                    start_block=start,
                    blocks=_u16(raw, 56),
                    comment_addr=int.from_bytes(raw[60:64], "big"),
                    chain=_walk(fat, start, self.geom),
                )
            )
        return out


def current_slot(pair: list[SystemBlock]) -> int:
    """CARDVerifyDir (0x80247B5C) and CARDVerifyFat (0x80247D9C) pick the slot
    with the lower check code as current and copy the other -- the newer one --
    into it, so the next update writes the stale slot and the two alternate.

    The choice is the signed subtraction of the two `lha`-loaded check codes at
    0x80247D04-0x80247D10 and 0x80247F88-0x80247F94: slot 0 when code0 - code1
    is negative, slot 1 otherwise. The memcpy that follows (0x80247D4C,
    0x80247FD0) is what makes the other copy's contents the ones that survive.
    """
    return 0 if _s16(pair[0].check_code) - _s16(pair[1].check_code) < 0 else 1


def _walk(fat: list[int], start: int, geom: Geometry) -> list[int]:
    """Follow a file's chain: 0xFFFF ends it, and anything outside the file
    blocks ends it too rather than looping forever."""
    chain: list[int] = []
    block = start
    while FIRST_FILE_BLOCK <= block < geom.blocks and block not in chain:
        chain.append(block)
        block = fat[block]
    return chain


def _system_block(data: bytes, geom: Geometry, index: int, kind: str) -> SystemBlock:
    start = geom.offset(index)
    block = data[start : start + BLOCK_BYTES]
    if kind == "directory":
        return SystemBlock(
            kind=kind,
            block=index,
            check_code=_u16(block, 8186),
            stored=(_u16(block, 8188), _u16(block, 8190)),
            computed=checksum(block[:CHECK_BYTES]),
        )
    counted = sum(1 for i in range(FIRST_FILE_BLOCK, geom.blocks) if _u16(block, 2 * i) == 0)
    return SystemBlock(
        kind=kind,
        block=index,
        check_code=_u16(block, 4),
        stored=(_u16(block, 0), _u16(block, 2)),
        computed=checksum(block[4:]),
        free_blocks=_u16(block, 6),
        last_allocated=_u16(block, 8),
        counted_free=counted,
    )


def parse_image(
    data: bytes, geom: Geometry, path: str = "-", file_size: int | None = None
) -> CardImage:
    """Read an image the way the mount reads the five system blocks."""
    head = data[:BLOCK_BYTES]
    header = Header(
        serial=bytes(head[0:12]),
        format_time=int.from_bytes(head[12:20], "big"),
        sram_bias=int.from_bytes(head[20:24], "big"),
        sram_language=int.from_bytes(head[24:28], "big"),
        vi_select=int.from_bytes(head[28:32], "big"),
        device_id=_u16(head, 32),
        size_mbit=_u16(head, 34),
        encode=_u16(head, 36),
        stored=(_u16(head, 508), _u16(head, 510)),
        computed=checksum(head[:ID_CHECK_BYTES]),
    )
    return CardImage(
        path=path,
        file_size=len(data) if file_size is None else file_size,
        geom=geom,
        data=bytes(data),
        header=header,
        directories=[_system_block(data, geom, i, "directory") for i in (1, 2)],
        tables=[_system_block(data, geom, i, "table") for i in (3, 4)],
    )


def load_image(path: str | Path, geom: Geometry = RUNTIME_GEOMETRY) -> CardImage:
    """Read a file the way runtime/exi.c card_load() reads it: into a buffer
    of erased flash, using the first CARD_BYTES and keeping the real length
    so that `verify` can complain about it."""
    raw = Path(path).read_bytes()
    data = bytearray(b"\xff" * geom.total_bytes)
    data[: min(len(raw), geom.total_bytes)] = raw[: geom.total_bytes]
    return parse_image(bytes(data), geom, str(path), len(raw))


# ---------------------------------------------------------------------------
# verify: the mount's own checks, in the mount's own order
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One test, and which of the mount's stages it belongs to.

    The stage matters because the mount stops at the first stage that fails:
    "note" is not a mount test at all (the file's length), "iscard" is
    __CARDIsCard, which CARDDoMount runs before it reads a byte, "id" is
    CARDVerifyID and "blocks" is CARDVerifyDir plus CARDVerifyFat.
    """

    name: str
    ok: bool
    detail: str
    stage: str = "note"


@dataclass(frozen=True)
class Verdict:
    checks: list[Check]
    result: int  # what CARDDoMount would hand the game
    id_result: int  # what CARDVerifyID alone would return
    errors: int  # CARDVerifyDir + CARDVerifyFat
    repairable: bool  # CARDCheckExAsync would rewrite one block and continue
    length_ok: bool

    @property
    def accepted(self) -> bool:
        """Whether the game's card layer carries on with this image."""
        return self.result == 0 or self.repairable

    @property
    def stage(self) -> str:
        """The stage the result came out of, which is the only one whose
        failures the mount ever saw."""
        if self.result == 0:
            return ""
        if self.result == -2:
            return "iscard"
        return "id" if self.id_result else "blocks"

    @property
    def first_failure(self) -> Check | None:
        """The check the mount actually tripped on -- not merely the first
        failing line in the report, which may belong to a stage the mount
        never reached."""
        stage = self.stage
        return next((c for c in self.checks if not c.ok and c.stage == stage), None)


def verify(image: CardImage, encode: int = ENCODE_ANSI, flash_id: bytes = CARD_FLASH_ID) -> Verdict:
    """Re-run __CARDIsCard, CARDVerifyID, CARDVerifyDir and CARDVerifyFat over
    an image, in the order CARDDoMount runs them.

    `flash_id` is what runtime/exi.c falls back to when it cannot descramble
    one out of the header, which is the only way the serial check can fail.
    """
    geom, head = image.geom, image.header
    checks: list[Check] = []
    length_ok = image.file_size == geom.total_bytes
    checks.append(
        Check(
            "image length",
            length_ok,
            f"{image.file_size} bytes"
            + (
                ""
                if length_ok
                else f", not the {geom.total_bytes} of a {geom.size_mbit} Mbit card; "
                "card_load() pads or truncates and the mount never learns"
            ),
            "note",
        )
    )
    # CARDDoMount 0x802488E8 calls __CARDIsCard on the EXI ID, and 0x802488FC
    # answers -2 WRONGDEVICE before the first __CARDRead if it says no.
    card_ok, card_detail = is_card(geom)
    checks.append(Check("__CARDIsCard geometry", card_ok, card_detail, "iscard"))

    id_result = 0
    blank = image.data[:ID_CHECK_BYTES] == b"\xff" * ID_CHECK_BYTES

    ok = head.device_id == 0
    checks.append(
        Check(
            "CARDVerifyID device ID at +32",
            ok,
            "0"
            if ok
            else f"0x{head.device_id:04X}, not 0"
            + (" -- this is erased flash, not a card" if blank else ""),
            "id",
        )
    )
    id_result = id_result or (0 if ok else -6)

    ok = head.size_mbit == geom.size_mbit
    checks.append(
        Check(
            "CARDVerifyID size at +34",
            ok,
            f"{head.size_mbit} Mbit"
            + ("" if ok else f", not the {geom.size_mbit} the EXI ID gives"),
            "id",
        )
    )
    id_result = id_result or (0 if ok else -6)

    ok = head.checksum_ok
    checks.append(
        Check(
            "CARDVerifyID header checksum at +508/+510",
            ok,
            f"{head.stored[0]:04X}/{head.stored[1]:04X}"
            + (
                ""
                if ok
                else f" stored, {head.computed[0]:04X}/{head.computed[1]:04X} over bytes 0..507"
            ),
            "id",
        )
    )
    id_result = id_result or (0 if ok else -6)

    presented = head.flash_id if head.flash_id is not None else flash_id
    ok = scramble(presented, head.format_time) == head.serial
    if head.flash_id is not None:
        detail = f"SRAM presents this image's own flash ID {presented.hex(' ').upper()}"
    else:
        detail = (
            "the header checksum does not validate, so runtime/exi.c cannot descramble a "
            f"flash ID from it and SRAM presents its built-in {flash_id.hex(' ').upper()}; "
            f"the image's serial {head.serial.hex(' ').upper()} does not match"
        )
    checks.append(Check("CARDVerifyID serial against SRAM", ok, detail, "id"))
    id_result = id_result or (0 if ok else -6)

    ok = head.encode == encode
    checks.append(
        Check(
            "CARDVerifyID encode at +36",
            ok,
            f"{head.encode}"
            + ("" if ok else f", not the {encode} CARDInit cached from OSGetFontEncode"),
            "id",
        )
    )
    id_result = id_result or (0 if ok else -13)

    errors = 0
    for pair, label in ((image.directories, "CARDVerifyDir"), (image.tables, "CARDVerifyFat")):
        for entry in pair:
            checks.append(
                Check(
                    f"{label} block {entry.block} checksum",
                    entry.checksum_ok,
                    f"{entry.stored[0]:04X}/{entry.stored[1]:04X} stored"
                    + (
                        f", check code {_s16(entry.check_code)}"
                        if entry.checksum_ok
                        else f", {entry.computed[0]:04X}/{entry.computed[1]:04X} computed"
                    ),
                    "blocks",
                )
            )
            if entry.free_blocks is not None:
                checks.append(
                    Check(
                        f"{label} block {entry.block} free count at +6",
                        entry.free_ok,
                        f"{entry.free_blocks} free, {entry.counted_free} zero entries in "
                        f"{FIRST_FILE_BLOCK}..{geom.blocks - 1}",
                        "blocks",
                    )
                )
            errors += 0 if entry.ok else 1

    if not card_ok:
        # -2 comes out of CARDDoMount before the ID block is read at all, so
        # everything after the geometry check is reported but never reached.
        result, repairable = -2, False
    else:
        result = id_result if id_result else (0 if errors == 0 else -6)
        repairable = id_result == 0 and errors == 1
    return Verdict(checks, result, id_result, errors, repairable, length_ok)


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------


def _when(seconds: int) -> str:
    """The SDK stores a file's time as seconds since 2000-01-01 (recalled,
    not established here), so this is a reading, not a fact."""
    try:
        return (datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)).strftime(
            "%Y-%m-%d %H:%M:%SZ"
        )
    except OverflowError, OSError, ValueError:
        return "out of range"


def describe(image: CardImage) -> list[str]:
    """Everything an image contains, field by field."""
    geom, head = image.geom, image.header
    size = f"{image.file_size} bytes" + (
        "" if image.file_size == geom.total_bytes else f" (read as {geom.total_bytes})"
    )
    lines = [f"{image.path}: {size}, {geom.describe()}", ""]
    lines.append(f"header (block 0, offset 0x{geom.offset(0):06X})")
    lines.append(f"  serial         {head.serial.hex(' ').upper()}")
    recovered = head.flash_id
    lines.append(
        f'  flash ID       {recovered.hex(" ").upper()}  "{_text(recovered)}"'
        "  what SRAM will present"
        if recovered is not None
        else "  flash ID       not recoverable: the header checksum does not validate"
    )
    lines.append(
        f"  format time    0x{head.format_time:016X}  (the scramble seed; nothing else reads it)"
    )
    lines.append(f"  SRAM bias      0x{head.sram_bias:08X}")
    lines.append(f"  SRAM language  {head.sram_language}")
    lines.append(f"  VI 0x6E word   0x{head.vi_select:08X}")
    lines.append(f"  device ID      0x{head.device_id:04X}  (CARDVerifyID demands 0)")
    lines.append(f"  size           {head.size_mbit} Mbit  (CARDVerifyID demands card->size)")
    lines.append(
        f"  encode         {head.encode}  ({'ANSI' if head.encode == ENCODE_ANSI else 'SJIS'})"
    )
    lines.append(
        f"  checksum       {head.stored[0]:04X}/{head.stored[1]:04X} stored, "
        f"{head.computed[0]:04X}/{head.computed[1]:04X} computed over bytes 0..507  "
        f"{'ok' if head.checksum_ok else 'MISMATCH'}"
    )

    for pair, label, current in (
        (image.directories, "directory", image.current_directory),
        (image.tables, "allocation table", image.current_table),
    ):
        lines.append("")
        lines.append(f"{label} (blocks {pair[0].block} and {pair[1].block})")
        for slot, entry in enumerate(pair):
            extra = ""
            if entry.free_blocks is not None:
                extra = (
                    f"  free {entry.free_blocks} (recount {entry.counted_free})"
                    f"  last allocated {entry.last_allocated}"
                )
            lines.append(
                f"  block {entry.block}  check code {_s16(entry.check_code):5d}  "
                f"checksum {entry.stored[0]:04X}/{entry.stored[1]:04X} "
                f"{'ok' if entry.checksum_ok else 'MISMATCH'}{extra}"
                + ("   <- newest" if slot == current ^ 1 else "")
            )
        bad = [slot for slot, entry in enumerate(pair) if not entry.ok]
        if not bad:
            lines.append(
                f"  the mount makes block {pair[current].block} current and copies "
                f"block {pair[current ^ 1].block} into it"
            )
        elif len(bad) == 1:
            # CARDCheckExAsync's one-error arm, 0x80248184: the damaged slot
            # becomes current whatever the check codes say, and the good twin
            # is copied over it and written back.
            lines.append(
                f"  block {pair[bad[0]].block} is damaged, so CARDCheckExAsync makes it "
                f"current, copies block {pair[bad[0] ^ 1].block} over it and rewrites it"
            )
        else:
            lines.append("  both copies are damaged, which is more than CARDCheckExAsync repairs")

    entries = image.entries()
    table = image.tables[image.current_table ^ 1]
    lines.append("")
    if not entries:
        lines.append(
            f"files: none of the {DIR_ENTRIES} entries are in use, {table.counted_free} blocks free"
        )
        return lines
    used = sum(len(e.chain) for e in entries)
    lines.append(
        f"files ({len(entries)} of {DIR_ENTRIES} entries in use, {used} blocks used, "
        f"{table.counted_free} free)"
    )
    lines.append(
        "  entry  game  company  name                              blocks  start  modified"
    )
    for entry in entries:
        lines.append(
            f"  {entry.index:5d}  {entry.game:<4}  {entry.company:<7}  {entry.name:<32}  "
            f"{entry.blocks:6d}  {entry.start_block:5d}  {_when(entry.modified)}"
        )
        chain = " ".join(str(b) for b in entry.chain) or "(none)"
        lines.append(
            f"         chain {chain}"
            + (
                ""
                if entry.chain_ok
                else f"  -- {len(entry.chain)} blocks, not the {entry.blocks} claimed"
            )
        )
        lines.append(
            f"         permission 0x{entry.permission:02X}  copies {entry.copy_times}  "
            f"comment 0x{entry.comment_addr:08X}"
        )
    return lines


def report(verdict: Verdict, image: CardImage, encode: int) -> list[str]:
    """The verify report: every check, then what the mount would return."""
    lines = [
        f"verify {image.path} against the {image.geom.size_mbit} Mbit card runtime/exi.c models "
        f"(EXI ID {CARD_ID:08X}, encode {encode})"
    ]
    for check in verdict.checks:
        lines.append(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
    name = RESULT_NAMES.get(verdict.result, "?")
    lines.append(f"verdict: CARDDoMount would return {verdict.result} ({name})")
    first = verdict.first_failure
    if first is not None:
        lines.append(f"         first failure: {first.name}")
    if verdict.stage == "iscard":
        lines.append(
            "         __CARDIsCard rejects the geometry, so the mount answers before it reads "
            "a byte and the checks below it never run"
        )
    elif verdict.stage == "id":
        lines.append(
            "         CARDVerifyID answers first (__CARDVerify 0x80248044 returns it unchanged), "
            "so the directory and table checks below never run"
        )
    elif verdict.repairable:
        lines.append(
            "         one damaged system block, so CARDCheckExAsync repairs it in place: one "
            "sector erase, then 64 page programs, and the game carries on"
        )
    elif verdict.stage == "blocks":
        lines.append(
            f"         {verdict.errors} damaged system blocks, more than the one CARDCheckExAsync "
            "will repair, so the game offers to format instead"
        )
    if not verdict.length_ok:
        lines.append(
            "         the file is not the length of this card: the runtime warns, pads or "
            "truncates and mounts it anyway, so this is not why it is accepted or rejected"
        )
    lines.append(
        f"the game's card layer would {'accept' if verdict.accepted else 'reject'} this image"
    )
    return lines


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def parse_int(text: str) -> int:
    """A decimal or 0x number, or `now` for the format time."""
    if text.strip().lower() == "now":
        return int(time.time() * TIMEBASE_HZ)
    try:
        return int(text, 0)
    except ValueError:
        raise CardFormatError(f"{text!r} is not a number or `now`") from None


def parse_flash_id(text: str) -> bytes:
    try:
        raw = bytes.fromhex(text.replace(" ", "").replace(":", ""))
    except ValueError:
        raise CardFormatError(f"{text!r} is not twelve bytes of hex") from None
    if len(raw) != 12:
        raise CardFormatError(f"a flash ID is 12 bytes, {len(raw)} given")
    return raw


def geometry_for(args: argparse.Namespace) -> Geometry:
    """The geometry the rest of the tool works in, refusing the ones no EXI ID
    can name -- a sector size outside SectorSizeTable, or one the five 8192-byte
    system blocks would not fit in without overwriting each other."""
    if args.sector_size not in SECTOR_SIZES or not args.sector_size:
        sizes = ", ".join(f"0x{s:X}" for s in SECTOR_SIZES if s)
        raise CardFormatError(
            f"0x{args.sector_size:X} is not one of the sector sizes an EXI ID can name ({sizes})"
        )
    geom = Geometry(args.size, args.sector_size)
    if geom.total_bytes % geom.sector_size:
        raise CardFormatError(
            f"{geom.sector_size}-byte sectors do not divide a {args.size} Mbit card"
        )
    return geom


def cmd_write(args: argparse.Namespace) -> int:
    geom = geometry_for(args)
    path = Path(args.output)
    if path.exists() and not args.force:
        print(
            f"[cardformat] {path} exists; pass --force to overwrite it "
            "(whatever the game wrote is in there)"
        )
        return 2
    image = format_image(
        geom, parse_flash_id(args.flash_id), parse_int(args.format_time), args.encode
    )
    note = damage(image, geom, args.damage) if args.damage != "none" else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image)
    print(f"wrote {path}: {len(image)} bytes, {geom.describe()}")
    if note:
        print(f"damaged on purpose: {note}")
    print("")
    parsed = parse_image(bytes(image), geom, str(path))
    for line in describe(parsed):
        print(line)
    print("")
    verdict = verify(parsed, args.encode, parse_flash_id(args.flash_id))
    for line in report(verdict, parsed, args.encode):
        print(line)
    return 0 if verdict.accepted else 1


def cmd_show(args: argparse.Namespace) -> int:
    image = load_image(args.image, geometry_for(args))
    for line in describe(image):
        print(line)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    image = load_image(args.image, geometry_for(args))
    verdict = verify(image, args.encode, parse_flash_id(args.flash_id))
    for line in report(verdict, image, args.encode):
        print(line)
    return 0 if verdict.accepted else 1


def add_card_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--size",
        type=int,
        default=RUNTIME_GEOMETRY.size_mbit,
        choices=CARD_SIZES,
        help="card size in Mbit (default %(default)s, what runtime/exi.c's CARD_ID advertises)",
    )
    parser.add_argument(
        "--sector-size",
        type=parse_int,
        default=RUNTIME_GEOMETRY.sector_size,
        help="bytes per block (default 0x2000, the only one runtime/exi.c erases)",
    )
    parser.add_argument(
        "--encode",
        type=int,
        default=ENCODE_ANSI,
        choices=(ENCODE_ANSI, ENCODE_SJIS),
        help="the encoding the mount demands (default %(default)s, ANSI, what this build gives)",
    )
    parser.add_argument(
        "--flash-id",
        default=CARD_FLASH_ID.hex(),
        help="the twelve flash bytes, hex (default runtime/exi.c's CARD_FLASH_ID)",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("--write", "--show", "--verify"):
        argv[0] = argv[0][2:]  # --verify IMAGE reads as the mode it is

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("write", help="write a formatted image the mount will accept")
    p.add_argument(
        "-o", "--output", default=CARD_PATH, help="where to write it (default %(default)s)"
    )
    p.add_argument(
        "-f", "--force", action="store_true", help="overwrite an image that is already there"
    )
    p.add_argument(
        "--format-time",
        default=str(DEFAULT_FORMAT_TIME),
        help="the 64-bit scramble seed, or `now` (default fixed, so two runs agree byte for byte)",
    )
    p.add_argument(
        "--damage",
        choices=("none", "dir", "fat"),
        default="none",
        help="break one system block's checksum so CARDCheckExAsync repairs it and writes",
    )
    add_card_options(p)
    p.set_defaults(func=cmd_write)

    p = sub.add_parser("show", help="print what an image contains")
    p.add_argument("image", nargs="?", default=CARD_PATH)
    add_card_options(p)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify", help="re-run the mount's checks over an image")
    p.add_argument("image", nargs="?", default=CARD_PATH)
    add_card_options(p)
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except CardFormatError as e:
        print(f"[cardformat] {e}")
        return 2
    except FileNotFoundError as e:
        print(f"[cardformat] no image at {e.filename}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
