"""Synthetic GameCube disc images for tests. No game bytes, ever.

    from soa import discfixture
    fx = discfixture.build(tmp_path / "disc.iso")
    fx.files["field/fa00.dat"]      # the bytes it placed, as the disc holds them
    fx.plain["field/fa00.dat"]      # the same file before its AKLZ wrapping

Every byte here is made at test time from a seed, into whatever directory the
test hands over -- a temporary one, never the tree: the guard refuses a
binary file that begins `GEAE8P` anywhere in it, so the fixture carries a
test game id and refuses the real one. The expected game id and the DOL's
hash are properties of the result, so a test checks the code against the
fixture and never against the real disc's values.

What it holds is the real disc's layout in miniature (docs/specs/disc-layer.md
§2, measured on the owner's image):

  0x0000   boot.bin (0x440): game id, magic 0xC2339F3D, title, and the DOL
           and FST offsets at 0x420 -- with FST max == FST size, as there
  0x0440   bi2.bin (0x2000)
  0x2440   an apploader header and body of random bytes
  ...      a DOL with a valid header and random sections, then the FST, with
           nested directories, a directory closed before a later sibling
           file, and a root file after every directory
  32 KiB   the files, placed in an order that is not the FST's, each starting
           on four bytes: files that abut, zero padding to 32 bytes (the
           disc's 2,970 gaps of 1-31 bytes are all zeros), junk gaps (a zero
           run of 28 bytes then random bytes, as the disc's 245 are), a gap to
           the next 32 KiB, lengths that are not a multiple of 32, one file
           of five bytes, and some files wrapped as AKLZ (literal-only LZSS,
           0.1f at +8, the three things akFio tests)
  tail     random bytes after the last file, to a 32 KiB boundary, so a read
           past the last file's end reaches something that is not zero
"""

from __future__ import annotations

import hashlib
import random
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import aklz
from .disc import BI2_OFFSET, BI2_SIZE, BOOT_HEADER_SIZE, FST_ENTRY_SIZE

TEST_GAME_ID = "GTSE01"  # never GEAE8P: see the docstring
REAL_GAME_ID = "GEAE8P"
MAGIC = 0xC2339F3D
AKLZ_RATIO = 0.1  # akFio checks the float at +8 is 0.1f (0x3DCCCCCD)

APPLOADER_OFFSET = 0x2440
APPLOADER_BODY = 0x1C00
FILES_ALIGN = 0x8000

# (path, bytes before wrapping, wrapped as AKLZ, the gap after it), in the
# order the files lie on the disc -- not the FST's order, which is by name.
# Each gap kind is here at least once; test_extract.py checks it still is.
LAYOUT: tuple[tuple[str, int, bool, str], ...] = (
    ("sound/s000_L.dsp", 300_008, False, "abut"),
    ("sound/s000_R.dsp", 300_012, False, "pad32"),
    ("field/fa00.dat", 120_011, True, "junk"),
    ("banner.bnr", 6_496, False, "abut"),  # a multiple of 32
    ("battle/enemy/e000.dat", 90_001, True, "pad32"),
    ("battle/b001.dat", 17_777, False, "pad32"),
    ("zz.gvr", 43_270, False, "align32k"),  # a root file after every directory
    ("battle/b000.dat", 40_003, True, "pad32"),
    ("title/t00.dat", 12_345, True, "junk"),
    ("battle/enemy/e001.dat", 5, False, "pad32"),
    ("battle/zz.dat", 33_333, False, "pad32"),  # after battle/enemy/ closes
    ("field/fb00.dat", 64_000, False, "pad32"),  # a multiple of 32
)

# A DOL of 7 text and 11 data slots, three of each used: (address, size).
DOL_TEXT = ((0x80003100, 0x2000), (0x80005100, 0x3E00))
DOL_DATA = ((0x80008F00, 0x0800), (0x80009700, 0x1000), (0x8000A700, 0x02E0))
DOL_BSS = (0x8000AA00, 0x4000)
DOL_ENTRY = 0x80003100


@dataclass
class Fixture:
    path: Path
    game_id: str
    image: bytes
    files: dict[str, bytes]  # every file, as the disc holds it
    offsets: dict[str, int]
    plain: dict[str, bytes]  # the files this builder wrapped, before wrapping
    dirs: list[str]
    system: dict[str, bytes]  # boot.bin, bi2.bin, main.dol, fst.bin
    slices: dict[str, tuple[int, int]]  # each system file's (offset, length)
    gaps: list[tuple[str, int, bytes]] = field(default_factory=list)  # (kind, after, bytes)
    tail: int = 0

    @property
    def dol_sha1(self) -> str:
        return hashlib.sha1(self.system["main.dol"]).hexdigest()


def align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def wrap_aklz(plain: bytes, ratio: float = AKLZ_RATIO) -> bytes:
    """An AKLZ container whose LZSS stream is all literals: one flag byte of
    eight 1s before each eight bytes. The decoder in soa/aklz.py (and the
    game's) reads it back exactly; nothing here compresses anything."""
    out = bytearray(aklz.MAGIC + struct.pack(">fI", ratio, len(plain)))
    for i in range(0, len(plain), 8):
        out.append(0xFF)
        out += plain[i : i + 8]
    return bytes(out)


def make_boot(game_id: str, dol_offset: int, fst_offset: int, fst_size: int) -> bytes:
    h = bytearray(BOOT_HEADER_SIZE)
    h[0x00:0x06] = game_id.encode("ascii")
    h[0x06] = 0  # disc number
    h[0x07] = 0  # revision
    struct.pack_into(">I", h, 0x1C, MAGIC)
    title = b"SOA disc fixture (synthetic, no game data)"
    h[0x20 : 0x20 + len(title)] = title
    struct.pack_into(">IIII", h, 0x420, dol_offset, fst_offset, fst_size, fst_size)
    return bytes(h)


def make_bi2() -> bytes:
    b = bytearray(BI2_SIZE)
    struct.pack_into(">I", b, 0x04, 0x01800000)  # simulated memory size
    struct.pack_into(">I", b, 0x18, 1)  # country code: NTSC-U
    return bytes(b)


def make_apploader(rng: random.Random) -> bytes:
    head = bytearray(0x20)
    head[0:10] = b"2026/09/25"
    struct.pack_into(">III", head, 0x10, 0x81200000, APPLOADER_BODY, 0)
    return bytes(head) + rng.randbytes(APPLOADER_BODY)


def make_dol(rng: random.Random) -> bytes:
    """A DOL whose header is valid and whose sections are random bytes."""
    header = bytearray(0x100)
    body = bytearray()
    offset = 0x100
    for slots, (off_at, addr_at, size_at) in (
        (DOL_TEXT, (0x00, 0x48, 0x90)),
        (DOL_DATA, (0x1C, 0x64, 0xAC)),
    ):
        for i, (addr, size) in enumerate(slots):
            struct.pack_into(">I", header, off_at + 4 * i, offset)
            struct.pack_into(">I", header, addr_at + 4 * i, addr)
            struct.pack_into(">I", header, size_at + 4 * i, size)
            body += rng.randbytes(size)
            offset += size
    struct.pack_into(">III", header, 0xD8, DOL_BSS[0], DOL_BSS[1], DOL_ENTRY)
    return bytes(header + body)


def make_fst(paths: list[str], place: dict[str, tuple[int, int]]) -> tuple[bytes, list[str]]:
    """An FST naming `paths`, each at `place[path]` = (offset, size); returns
    the blob and its directories. Entries are in name order within each
    directory, files and directories together, as the SDK's are."""
    tree: dict = {}
    for p in paths:
        node = tree
        *dirs, name = p.split("/")
        for d in dirs:
            node = node.setdefault(d, {})
        node[name] = p
    entries: list[list[int]] = [[1, 0, 0, 0]]  # the root, finished below
    names = bytearray()
    dirs_out: list[str] = []

    def walk(node: dict, parent: int, prefix: str) -> None:
        for name in sorted(node, key=str.lower):
            name_off = len(names)
            names.extend(name.encode("ascii") + b"\0")
            child = node[name]
            if isinstance(child, dict):
                me = len(entries)
                entries.append([1, name_off, parent, 0])
                dirs_out.append(prefix + name)
                walk(child, me, prefix + name + "/")
                entries[me][3] = len(entries)  # the first entry past it
            else:
                offset, size = place[child]
                entries.append([0, name_off, offset, size])

    walk(tree, 0, "")
    entries[0][3] = len(entries)
    blob = bytearray()
    for kind, name_off, a, b in entries:
        blob += struct.pack(">I", (kind << 24) | name_off) + struct.pack(">II", a, b)
    assert len(blob) == len(entries) * FST_ENTRY_SIZE
    return bytes(blob + names), dirs_out


def build(
    dest,
    *,
    game_id: str = TEST_GAME_ID,
    seed: int = 0x50A,
    extra: dict[str, bytes] | None = None,
) -> Fixture:
    """Write a synthetic image to `dest` and return what it holds. `extra`
    adds files (path -> the bytes the disc should hold), placed after the
    defaults; a path the defaults use is replaced."""
    if game_id == REAL_GAME_ID:
        raise ValueError(
            f"the fixture never carries {REAL_GAME_ID}: the guard refuses a binary file "
            "that begins with it, and a test must not depend on the real id"
        )
    if len(game_id) != 6 or not game_id.isascii():
        raise ValueError(f"a game id is six ASCII characters, not {game_id!r}")
    rng = random.Random(seed)
    extra = dict(extra or {})

    files: dict[str, bytes] = {}
    plain: dict[str, bytes] = {}
    order: list[tuple[str, str]] = []  # (path, gap after) in disc order
    for path, size, wrapped, gap in LAYOUT:
        if path in extra:
            continue
        data = rng.randbytes(size)
        if wrapped:
            plain[path] = data
            data = wrap_aklz(data)
        files[path] = data
        order.append((path, gap))
    for path, data in extra.items():
        files[path] = data
        order.append((path, "pad32"))

    apploader = make_apploader(rng)
    dol = make_dol(rng)
    dol_offset = align(APPLOADER_OFFSET + len(apploader), 0x100)
    # The FST's length does not depend on the offsets in it: measure it with
    # placeholders, lay the files out after it, then build it for real.
    paths = sorted(files)
    fst_len = len(make_fst(paths, dict.fromkeys(paths, (0, 0)))[0])
    fst_offset = align(dol_offset + len(dol), 0x100)
    first = align(fst_offset + fst_len, FILES_ALIGN)

    place: dict[str, tuple[int, int]] = {}
    gaps: list[tuple[str, int, bytes]] = []
    pos = first
    for n, (path, gap) in enumerate(order):
        data = files[path]
        if pos % 4:
            raise ValueError(f"{path}: would start at 0x{pos:X}, not on four bytes")
        place[path] = (pos, len(data))
        end = pos + len(data)
        if n == len(order) - 1:
            pos = end
            break
        if gap == "abut":
            filler = b""
        elif gap == "pad32":
            filler = bytes(align(end, 32) - end)
        elif gap == "align32k":
            filler = bytes(align(end, FILES_ALIGN) - end)
        elif gap == "junk":
            nxt = align(end + 28 + 1024, FILES_ALIGN)
            filler = bytes(28) + rng.randbytes(nxt - end - 28)
        else:
            raise ValueError(f"{path}: unknown gap {gap!r}")
        gaps.append((gap, end, filler))
        pos = end + len(filler)
    last_end = pos
    size = align(last_end + 0x1000, FILES_ALIGN)

    fst, dirs = make_fst(paths, place)
    assert len(fst) == fst_len
    boot = make_boot(game_id, dol_offset, fst_offset, len(fst))
    bi2 = make_bi2()

    image = bytearray(size)
    image[0:BOOT_HEADER_SIZE] = boot
    image[BI2_OFFSET : BI2_OFFSET + BI2_SIZE] = bi2
    image[APPLOADER_OFFSET : APPLOADER_OFFSET + len(apploader)] = apploader
    image[dol_offset : dol_offset + len(dol)] = dol
    image[fst_offset : fst_offset + len(fst)] = fst
    for path, (offset, length) in place.items():
        image[offset : offset + length] = files[path]
    for _kind, at, filler in gaps:
        image[at : at + len(filler)] = filler
    image[last_end:size] = rng.randbytes(size - last_end)  # the tail

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image)
    return Fixture(
        path=dest,
        game_id=game_id,
        image=bytes(image),
        files=files,
        offsets={p: o for p, (o, _) in place.items()},
        plain=plain,
        dirs=dirs,
        system={"boot.bin": boot, "bi2.bin": bi2, "main.dol": dol, "fst.bin": fst},
        slices={
            "boot.bin": (0, BOOT_HEADER_SIZE),
            "bi2.bin": (BI2_OFFSET, BI2_SIZE),
            "main.dol": (dol_offset, len(dol)),
            "fst.bin": (fst_offset, len(fst)),
        },
        gaps=gaps,
        tail=size - last_end,
    )
