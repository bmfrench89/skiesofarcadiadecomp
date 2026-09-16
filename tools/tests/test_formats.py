"""Format parser tests.

These run in CI, where no game data exists and none ever will. Every fixture is
synthesised in-memory, so the tests exercise parsing logic without depending on
a disc image. Tests that need the real game live in test_game.py and skip
automatically when it is absent.
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa import dol as D  # noqa: E402
from soa.disc import parse_boot, parse_fst  # noqa: E402

GC_MAGIC = 0xC2339F3D


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def make_boot(dol_offset=0x1EC00, fst_offset=0x323E00, fst_size=1024, magic=GC_MAGIC):
    h = bytearray(0x440)
    h[0x00:0x06] = b"GEAE8P"
    h[0x06] = 0  # disc number
    h[0x07] = 0  # version
    h[0x1C:0x20] = struct.pack(">I", magic)
    h[0x20 : 0x20 + 24] = b"Skies of Arcadia Legends"
    h[0x420:0x430] = struct.pack(">IIII", dol_offset, fst_offset, fst_size, fst_size)
    return bytes(h)


def make_dol(
    text=((0x80003100, b"\x60\x00\x00\x00" * 4),),
    data=((0x80400000, b"\xaa" * 8),),
    bss=(0x80500000, 256),
    entry=0x80003100,
):
    """Build a DOL image from (address, bytes) pairs."""
    header = bytearray(0x100)
    payload = bytearray()
    offset = 0x100

    for i, (addr, blob) in enumerate(text):
        struct.pack_into(">I", header, 0x00 + i * 4, offset)
        struct.pack_into(">I", header, 0x48 + i * 4, addr)
        struct.pack_into(">I", header, 0x90 + i * 4, len(blob))
        payload += blob
        offset += len(blob)

    for i, (addr, blob) in enumerate(data):
        struct.pack_into(">I", header, 0x1C + i * 4, offset)
        struct.pack_into(">I", header, 0x64 + i * 4, addr)
        struct.pack_into(">I", header, 0xAC + i * 4, len(blob))
        payload += blob
        offset += len(blob)

    struct.pack_into(">III", header, 0xD8, bss[0], bss[1], entry)
    return bytes(header) + bytes(payload)


def make_fst(entries):
    """Build an FST. `entries` is a list of dicts with keys name/dir/offset/size/next."""
    count = len(entries) + 1
    table = bytearray()
    strtab = bytearray()

    # entry 0: root
    table += bytes([1, 0, 0, 0]) + struct.pack(">II", 0, count)

    for e in entries:
        name_off = len(strtab)
        strtab += e["name"].encode("ascii") + b"\0"
        flag = 1 if e.get("dir") else 0
        table += bytes([flag]) + name_off.to_bytes(3, "big")
        if e.get("dir"):
            table += struct.pack(">II", e.get("parent", 0), e["next"])
        else:
            table += struct.pack(">II", e["offset"], e["size"])

    return bytes(table) + bytes(strtab)


# --------------------------------------------------------------------------
# boot header
# --------------------------------------------------------------------------


def test_boot_header_fields():
    b = parse_boot(make_boot())
    assert b.game_id == "GEAE8P"
    assert b.title == "Skies of Arcadia Legends"
    assert b.is_gamecube
    assert b.dol_offset == 0x1EC00
    assert b.fst_offset == 0x323E00


def test_boot_rejects_bad_magic():
    b = parse_boot(make_boot(magic=0xDEADBEEF))
    assert not b.is_gamecube


# --------------------------------------------------------------------------
# DOL
# --------------------------------------------------------------------------


def test_dol_sections_and_counts():
    d = D.parse(make_dol())
    assert len(d.sections) == 2
    assert d.entry_point == 0x80003100
    assert d.code_size == 16
    assert d.instruction_count == 4
    assert d.text[0].name == ".text0"


def test_dol_skips_empty_sections():
    """Only non-zero-size sections become entries."""
    img = make_dol(text=((0x80003100, b"\x60\x00\x00\x00"),), data=())
    d = D.parse(img)
    assert [s.name for s in d.sections] == [".text0"]


def test_dol_address_mapping():
    d = D.parse(make_dol(text=((0x80003100, bytes(range(16))),)))
    assert d.read(0x80003100, 4) == bytes([0, 1, 2, 3])
    assert d.read(0x80003104, 4) == bytes([4, 5, 6, 7])
    assert d.word(0x80003100) == 0x00010203  # big-endian


def test_dol_section_lookup():
    d = D.parse(make_dol())
    assert d.section_at(0x80003100).name == ".text0"
    assert d.section_at(0x80003104).name == ".text0"
    assert d.section_at(0x80003110) is None  # one past the end
    assert d.section_at(0x80400000).name == ".data0"


def test_dol_unmapped_read_raises():
    d = D.parse(make_dol())
    with pytest.raises(ValueError, match="not mapped"):
        d.read(0x90000000, 4)


def test_dol_image_size():
    img = make_dol()
    assert D.image_size(img[:0x100]) == len(img)


def test_dol_too_short():
    with pytest.raises(ValueError):
        D.parse(b"\x00" * 16)


# --------------------------------------------------------------------------
# FST
# --------------------------------------------------------------------------


def test_fst_flat_files():
    f = parse_fst(
        make_fst(
            [
                {"name": "a.bin", "offset": 0x1000, "size": 10},
                {"name": "b.bin", "offset": 0x2000, "size": 20},
            ]
        )
    )
    assert [x.path for x in f.files] == ["a.bin", "b.bin"]
    assert f.files[0].offset == 0x1000
    assert f.total_bytes == 30


def test_fst_directory_nesting():
    """A directory's next_index bounds its children; entries past it are siblings."""
    f = parse_fst(
        make_fst(
            [
                {"name": "field", "dir": True, "next": 4},  # children: indices 2,3
                {"name": "a.mld", "offset": 0x1000, "size": 8},
                {"name": "b.mld", "offset": 0x2000, "size": 8},
                {"name": "root.bin", "offset": 0x3000, "size": 4},  # index 4, back at root
            ]
        )
    )
    assert f.dirs == ["field"]
    assert [x.path for x in f.files] == ["field/a.mld", "field/b.mld", "root.bin"]


def test_fst_nested_directories():
    f = parse_fst(
        make_fst(
            [
                {"name": "outer", "dir": True, "next": 5},
                {"name": "inner", "dir": True, "next": 4},
                {"name": "deep.bin", "offset": 0x100, "size": 1},
                {"name": "mid.bin", "offset": 0x200, "size": 1},
                {"name": "top.bin", "offset": 0x300, "size": 1},
            ]
        )
    )
    assert [x.path for x in f.files] == [
        "outer/inner/deep.bin",
        "outer/mid.bin",
        "top.bin",
    ]


def test_fst_find_is_case_insensitive():
    f = parse_fst(make_fst([{"name": "A.BIN", "offset": 1, "size": 2}]))
    assert f.find("a.bin") is not None
    assert f.find("/A.BIN") is not None
    assert f.find("missing") is None


def test_fst_empty():
    f = parse_fst(make_fst([]))
    assert f.files == [] and f.dirs == []
    assert f.total_bytes == 0
