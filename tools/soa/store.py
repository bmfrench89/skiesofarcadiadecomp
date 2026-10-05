"""The disc store, GEAE8P.soadisc (docs/specs/disc-layer.md section 3.7, I4).

Every byte of the disc from offset 0 to one mebibyte past the last file's end
(rounded to 32 KiB), as shipped and in disc order -- the system area, the
files and the padding between them -- with a table naming each stretch and a
SHA-1 of every 64 KiB block, so a copy on another device can be checked. It
saves about 2% against disc.iso; it is an integrity format, not a space
saving (section 3.7.1). Only the tail past that margin is dropped, and reads there
give zeros.

    header (4096 bytes)  magic SOADISC1, sizes, hashes, header SHA-1 at 0xFEC
    extents (64 bytes each, sorted, contiguous over [0, covered_end))
    block digests (20 bytes each, over the payload in 64 KiB blocks)
    payload, from a 4096-aligned offset: the disc's own bytes

All integers little-endian. `Store(path)` reads one with the `read(offset,
length)` every `Disc` reader has, so `Disc(Store(...))` works for every tool.
`write` makes one from any such reader in one pass, `check` re-hashes one,
`compare` holds one to an ISO byte for byte.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .disc import FST_ENTRY_SIZE, Disc

MAGIC = b"SOADISC1"
FORMAT_VERSION = 1
HEADER_SIZE = 4096
EXTENT_SIZE = 64
BLOCK_SIZE = 65536
DIGEST = 20
TAIL_MARGIN = 1 << 20
TAIL_ALIGN = 32 << 10
SYSTEM, FILE, PADDING, TAIL = 0, 1, 2, 3
KIND_NAMES = ("system area", "file", "padding", "tail")
NO_FILE = 0xFFFFFFFF
SOURCE_ISO, SOURCE_RVZ = 1, 2
FLAG_IMAGE, FLAG_FILES = 1, 2  # the image's / the files' SHA-1 matched the pinned one
HEADER_SHA1_AT = 0xFEC
STREAM = 8 << 20
STORE_SUFFIX = ".soadisc"


class StoreError(Exception):
    """A store this cannot use; the message says why and what to do."""


def sha1(data: bytes = b"") -> hashlib._Hash:
    return hashlib.sha1(data, usedforsecurity=False)


def align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


@dataclass
class Extent:
    disc_offset: int
    length: int
    kind: int
    fst_index: int = NO_FILE
    digest: bytes = b""

    @property
    def end(self) -> int:
        return self.disc_offset + self.length


@dataclass
class Header:
    extent_count: int
    payload_offset: int
    payload_size: int
    image_size: int
    covered_end: int
    game_id: str
    disc_number: int
    revision: int
    dol_sha1: bytes
    fst_sha1: bytes
    files_sha1: bytes
    image_sha1: bytes
    source_kind: int
    flags: int
    importer: str
    block_count: int
    extent_table_offset: int = HEADER_SIZE
    block_table_offset: int = 0
    header_sha1: bytes = b""
    extents: list[Extent] = field(default_factory=list)
    blocks: list[bytes] = field(default_factory=list)

    def pack(self) -> bytes:
        """The header's 4096 bytes, its own SHA-1 included (over the bytes
        before it, then both tables)."""
        h = bytearray(HEADER_SIZE)
        h[0:8] = MAGIC
        struct.pack_into(
            "<IIII", h, 0x08, FORMAT_VERSION, HEADER_SIZE, EXTENT_SIZE, self.extent_count
        )
        struct.pack_into("<QQQQQ", h, 0x18, self.extent_table_offset, self.payload_offset,
                         self.payload_size, self.image_size, self.covered_end)  # fmt: skip
        h[0x40:0x46] = self.game_id.encode("ascii")[:6].ljust(6, b"\0")
        h[0x46], h[0x47] = self.disc_number, self.revision
        for at, digest in ((0x48, self.dol_sha1), (0x5C, self.fst_sha1), (0x70, self.files_sha1),
                           (0x84, self.image_sha1)):  # fmt: skip
            h[at : at + DIGEST] = digest.ljust(DIGEST, b"\0")
        struct.pack_into("<II", h, 0x98, self.source_kind, self.flags)
        h[0xA0:0xE0] = self.importer.encode("ascii", "replace")[:64].ljust(64, b"\0")
        struct.pack_into("<IIQ", h, 0xE0, BLOCK_SIZE, self.block_count, self.block_table_offset)
        digest = sha1(bytes(h[:HEADER_SHA1_AT]))
        digest.update(self.extent_table())
        digest.update(self.block_table())
        h[HEADER_SHA1_AT : HEADER_SHA1_AT + DIGEST] = digest.digest()
        return bytes(h)

    def extent_table(self) -> bytes:
        out = bytearray()
        for e in self.extents:
            row = bytearray(EXTENT_SIZE)
            struct.pack_into("<QQQIBB", row, 0, e.disc_offset, e.length, e.disc_offset, e.fst_index,
                             e.kind, 0)  # fmt: skip
            row[32 : 32 + DIGEST] = e.digest
            out += row
        return bytes(out)

    def block_table(self) -> bytes:
        return b"".join(self.blocks)


# ---- the layout ------------------------------------------------------------


def fst_files(fst: bytes) -> list[tuple[int, int, int]]:
    """(entry index, disc offset, size) of every file entry, in table order."""
    n = struct.unpack_from(">I", fst, 8)[0]
    out = []
    for i in range(1, n):
        kind, off, size = struct.unpack_from(">BxxxII", fst, i * FST_ENTRY_SIZE)
        if kind == 0:
            out.append((i, off, size))
    return out


def layout(fst: bytes, image_size: int) -> tuple[list[Extent], int]:
    """The extents over [0, covered_end): the system area, each file, the
    padding between files, and the tail. Refuses a file past the image's
    end and two files that overlap: nothing in such a table can be trusted."""
    files = sorted((off, i, size) for i, off, size in fst_files(fst) if size)
    if not files:
        raise StoreError("the file table names no file")
    out: list[Extent] = []
    pos = 0
    for off, i, size in files:
        if off + size > image_size:
            raise StoreError(f"file table entry {i} lies past the image's end (0x{off:X} + {size})")
        if off < pos:
            raise StoreError(f"file table entry {i} at 0x{off:X} overlaps the file before it")
        if off > pos:
            out.append(Extent(pos, off - pos, SYSTEM if not out else PADDING))
        out.append(Extent(off, size, FILE, i))
        pos = off + size
    covered = min(align(pos + TAIL_MARGIN, TAIL_ALIGN), image_size)
    if covered > pos:
        out.append(Extent(pos, covered - pos, TAIL))
    return out, covered


def files_digest(fst: bytes, digests: dict[int, bytes]) -> bytes:
    """section 3.7.3's files SHA-1: over every file entry's SHA-1, in table order. A
    file of no bytes has the SHA-1 of nothing."""
    h = sha1()
    for i, _, size in fst_files(fst):
        h.update(digests[i] if size else sha1().digest())
    return h.digest()


# ---- writing ---------------------------------------------------------------


@dataclass
class Written:
    header: Header
    path: Path
    image_sha1: str
    files_sha1: str
    fst_sha1: str
    dol_sha1: str


def write(reader, image_size: int, dest: Path, source_kind: int, importer: str,
          pins: dict[str, str] | None = None) -> Written:  # fmt: skip
    """`reader`'s image as a store at `dest`: written to `<dest>.part`, read back
    and checked, then renamed. One pass over the image, which hashes it whole
    while writing the covered part. `pins` (disc.yml) set the flags; the
    caller judges them, and may delete what this wrote."""
    disc = Disc(reader)
    fst = reader.read(disc.boot.fst_offset, disc.boot.fst_size)
    dol = disc.read_dol()
    extents, covered = layout(fst, image_size)
    blocks = (covered + BLOCK_SIZE - 1) // BLOCK_SIZE
    table_end = HEADER_SIZE + len(extents) * EXTENT_SIZE + blocks * DIGEST
    payload_at = align(table_end, 4096)
    part = dest.with_name(dest.name + ".part")
    image_h = sha1()
    block_digests: list[bytes] = []
    block_h, block_left = sha1(), min(BLOCK_SIZE, covered)
    ext_i, ext_h, ext_left = 0, sha1(), extents[0].length
    try:
        with open(part, "wb") as f:
            f.seek(payload_at)
            pos = 0
            while pos < image_size:
                data = reader.read(pos, min(STREAM, image_size - pos))
                if not data:
                    raise StoreError(f"the image ends at {pos:,} bytes of {image_size:,}")
                image_h.update(data)
                piece = memoryview(data)[: max(0, min(len(data), covered - pos))]
                f.write(piece)
                k = 0
                while k < len(piece):  # the extents' hashes
                    take = min(ext_left, len(piece) - k)
                    ext_h.update(piece[k : k + take])
                    k, ext_left = k + take, ext_left - take
                    if ext_left == 0:
                        extents[ext_i].digest = ext_h.digest()
                        ext_i += 1
                        if ext_i < len(extents):
                            ext_h, ext_left = sha1(), extents[ext_i].length
                k = 0
                while k < len(piece):  # the blocks'
                    take = min(block_left, len(piece) - k)
                    block_h.update(piece[k : k + take])
                    k, block_left = k + take, block_left - take
                    if block_left == 0:
                        block_digests.append(block_h.digest())
                        done = len(block_digests) * BLOCK_SIZE
                        block_h, block_left = sha1(), min(BLOCK_SIZE, covered - done)
                pos += len(data)
            files = files_digest(fst, {e.fst_index: e.digest for e in extents if e.kind == FILE})
            fst_d, dol_d, image_d = sha1(fst).digest(), sha1(dol).digest(), image_h.digest()
            flags = 0
            if pins and pins.get("image_sha1") == image_d.hex():
                flags |= FLAG_IMAGE
            if pins and pins.get("files_sha1") == files.hex():
                flags |= FLAG_FILES
            header = Header(
                extent_count=len(extents),
                payload_offset=payload_at,
                payload_size=covered,
                image_size=image_size,
                covered_end=covered,
                game_id=disc.boot.game_id,
                disc_number=disc.boot.disc_number,
                revision=disc.boot.version,
                dol_sha1=dol_d,
                fst_sha1=fst_d,
                files_sha1=files,
                image_sha1=image_d,
                source_kind=source_kind,
                flags=flags,
                importer=importer,
                block_count=blocks,
                block_table_offset=HEADER_SIZE + len(extents) * EXTENT_SIZE,
                extents=extents,
                blocks=block_digests,
            )
            f.seek(0)
            f.write(header.pack())
            f.write(header.extent_table())
            f.write(header.block_table())
        problems = check(part, allow_part=True)
        if problems:
            raise StoreError(f"{part}: read back wrong: {problems[0]}")
        os.replace(part, dest)
    finally:
        if part.exists():
            part.unlink()
    return Written(header, dest, image_d.hex(), files.hex(), fst_d.hex(), dol_d.hex())


# ---- reading ---------------------------------------------------------------


class Store:
    """A store opened for reading, its header and tables checked against the
    header's SHA-1 first. `read` gives the disc's bytes below covered_end and
    zeros above it."""

    def __init__(self, path, allow_part: bool = False):
        self.path = Path(path)
        if self.path.name.endswith(".part") and not allow_part:
            raise StoreError(f"{self.path}: an unfinished import; run the importer again")
        self.f = open(self.path, "rb")  # noqa: SIM115 -- closed by close()
        try:
            self.header = self._read_header()
        except BaseException:
            self.f.close()
            raise
        self.covered_end = self.header.covered_end
        self.iso_size = self.header.image_size
        self.size = self.header.image_size

    def _read_header(self) -> Header:
        size = os.fstat(self.f.fileno()).st_size
        h = self.f.read(HEADER_SIZE)
        if len(h) < HEADER_SIZE or h[:8] != MAGIC:
            raise StoreError(f"{self.path}: not a disc store (no {MAGIC.decode()} header)")
        version, header_size, extent_size, n = struct.unpack_from("<IIII", h, 0x08)
        if version != FORMAT_VERSION:
            raise StoreError(f"{self.path}: store format {version}; this reads {FORMAT_VERSION}")
        if header_size != HEADER_SIZE or extent_size != EXTENT_SIZE:
            raise StoreError(f"{self.path}: header or extent size is not this format's")
        ext_at, pay_at, pay_n, image_n, covered = struct.unpack_from("<QQQQQ", h, 0x18)
        block_size, blocks, block_at = struct.unpack_from("<IIQ", h, 0xE0)
        if block_size != BLOCK_SIZE or blocks != (pay_n + BLOCK_SIZE - 1) // BLOCK_SIZE:
            raise StoreError(f"{self.path}: the block table is not this format's")
        if (
            ext_at != HEADER_SIZE
            or block_at != ext_at + n * EXTENT_SIZE
            or pay_at < block_at + blocks * DIGEST
        ):
            raise StoreError(f"{self.path}: the tables are not where the header says")
        if size < pay_at + pay_n:
            raise StoreError(
                f"{self.path}: truncated ({size:,} bytes, the payload needs {pay_at + pay_n:,}); "
                "run the importer again"
            )
        tables = self.f.read(pay_at - HEADER_SIZE)
        ext_table = tables[: n * EXTENT_SIZE]
        block_table = tables[n * EXTENT_SIZE : n * EXTENT_SIZE + blocks * DIGEST]
        want = h[HEADER_SHA1_AT : HEADER_SHA1_AT + DIGEST]
        got = sha1(h[:HEADER_SHA1_AT])
        got.update(ext_table)
        got.update(block_table)
        if got.digest() != want:
            raise StoreError(
                f"{self.path}: its header and tables do not match their SHA-1; re-import"
            )
        extents = []
        for k in range(n):
            off, length, data_off, idx, kind = struct.unpack_from(
                "<QQQIB", ext_table, k * EXTENT_SIZE
            )
            if data_off != off:  # version 1 stores the disc in order
                raise StoreError(f"{self.path}: extent {k} is not stored in disc order")
            dig = ext_table[k * EXTENT_SIZE + 32 : k * EXTENT_SIZE + 52]
            extents.append(Extent(off, length, kind, idx, dig))
        return Header(
            extent_count=n,
            payload_offset=pay_at,
            payload_size=pay_n,
            image_size=image_n,
            covered_end=covered,
            game_id=h[0x40:0x46].decode("ascii", "replace"),
            disc_number=h[0x46],
            revision=h[0x47],
            dol_sha1=h[0x48:0x5C],
            fst_sha1=h[0x5C:0x70],
            files_sha1=h[0x70:0x84],
            image_sha1=h[0x84:0x98],
            source_kind=struct.unpack_from("<I", h, 0x98)[0],
            flags=struct.unpack_from("<I", h, 0x9C)[0],
            importer=h[0xA0:0xE0].rstrip(b"\0").decode("ascii", "replace"),
            block_count=blocks,
            block_table_offset=block_at,
            header_sha1=bytes(want),
            extents=extents,
            blocks=[block_table[i * DIGEST : (i + 1) * DIGEST] for i in range(blocks)],
        )

    def read(self, offset: int, length: int) -> bytes:
        stored = max(0, min(length, self.covered_end - offset)) if offset < self.covered_end else 0
        data = b""
        if stored:
            self.f.seek(self.header.payload_offset + offset)
            data = self.f.read(stored)
        return data + bytes(length - len(data))

    def close(self) -> None:
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def check(path, allow_part: bool = False) -> list[str]:
    """Every extent and block of the store at `path` re-hashed against its
    table (the header's own SHA-1 already held by opening it): one line per
    extent or block that differs, a file named by its path."""
    with Store(path, allow_part=allow_part) as st:
        problems = []
        names: dict[int, str] = {}
        try:
            disc = Disc(st)
            paths = {(f.offset, f.size): f.path for f in disc.fst.files}
            fst = st.read(disc.boot.fst_offset, disc.boot.fst_size)
            names = {i: paths.get((off, size), "") for i, off, size in fst_files(fst)}
        except ValueError, StoreError, struct.error:
            pass  # unnamed, then; the hashes below still say what moved
        for e in st.header.extents:
            got = sha1(st.read(e.disc_offset, e.length)).digest()
            if got != e.digest:
                what = names.get(e.fst_index) or KIND_NAMES[e.kind]
                problems.append(
                    f"extent at 0x{e.disc_offset:X} (+{e.length}, {what}) does not match its SHA-1"
                )
        for k, want in enumerate(st.header.blocks):
            start = k * BLOCK_SIZE
            got = sha1(st.read(start, min(BLOCK_SIZE, st.covered_end - start))).digest()
            if got != want:
                problems.append(f"block {k} (0x{start:X}) does not match its SHA-1")
        return problems


def compare(store_path, iso_path, flip: int | None = None) -> tuple[int, list[int]]:
    """The store against an ISO over [0, covered_end), in 8 MiB blocks: how many
    bytes differ, and the first few offsets that do. `flip` XORs 0x01 into one
    byte of the store's side, in memory: the mutation that must show."""
    with Store(store_path) as st, open(iso_path, "rb") as iso:
        differ, where = 0, []
        pos = 0
        while pos < st.covered_end:
            n = min(STREAM, st.covered_end - pos)
            a = bytearray(st.read(pos, n))
            b = iso.read(n)
            if flip is not None and pos <= flip < pos + n:
                a[flip - pos] ^= 1
            if a != b:
                for k in range(min(len(a), len(b))):
                    if a[k] != b[k]:
                        differ += 1
                        if len(where) < 8:
                            where.append(pos + k)
                differ += abs(len(a) - len(b))
            pos += n
        return differ, where
