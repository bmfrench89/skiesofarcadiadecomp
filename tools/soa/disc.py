"""GameCube disc layout: boot header, FST parsing, file extraction.

FST format: a flat array of 12-byte entries followed by a string table.
Entry 0 is the root directory, whose `next_index` is the total entry count.

  byte  0     type (0 = file, 1 = directory)
  bytes 1-3   24-bit big-endian offset into the string table
  bytes 4-7   file: disc offset        directory: parent index
  bytes 8-11  file: size               directory: next index (first entry past it)

Directory nesting is recovered by tracking `next_index` on a stack rather than
by following parent pointers, which keeps the walk single-pass.
"""

import struct
from dataclasses import dataclass, field
from pathlib import Path

BOOT_HEADER_SIZE = 0x440
BI2_OFFSET = 0x440
APPLOADER_OFFSET = 0x2440
FST_ENTRY_SIZE = 12


@dataclass(frozen=True)
class BootInfo:
    game_id: str
    disc_number: int
    version: int
    title: str
    magic: int
    dol_offset: int
    fst_offset: int
    fst_size: int
    fst_max_size: int

    @property
    def is_gamecube(self) -> bool:
        return self.magic == 0xC2339F3D


@dataclass(frozen=True)
class FstFile:
    path: str
    offset: int
    size: int


@dataclass
class Fst:
    files: list[FstFile] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    entry_count: int = 0

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def find(self, path: str) -> FstFile | None:
        want = path.strip("/").lower()
        for f in self.files:
            if f.path.lower() == want:
                return f
        return None


def parse_boot(header: bytes) -> BootInfo:
    """Parse the 0x440-byte boot header (boot.bin)."""
    dol_offset, fst_offset, fst_size, fst_max_size = struct.unpack(">IIII", header[0x420:0x430])
    return BootInfo(
        game_id=header[0x00:0x06].decode("ascii", errors="replace"),
        disc_number=header[0x06],
        version=header[0x07],
        title=header[0x20:0x60].split(b"\0")[0].decode("ascii", errors="replace"),
        magic=struct.unpack(">I", header[0x1C:0x20])[0],
        dol_offset=dol_offset,
        fst_offset=fst_offset,
        fst_size=fst_size,
        fst_max_size=fst_max_size,
    )


def parse_fst(data: bytes) -> Fst:
    """Parse a raw FST blob into a file and directory listing."""
    entry_count = struct.unpack(">I", data[8:12])[0]
    strtab = entry_count * FST_ENTRY_SIZE
    fst = Fst(entry_count=entry_count)

    def name_at(offset: int) -> str:
        start = strtab + offset
        end = data.index(b"\0", start)
        return data[start:end].decode("ascii", errors="replace")

    # (name, next_index) for each open directory; root is implicit
    stack: list[tuple[str, int]] = [("", entry_count)]

    for i in range(1, entry_count):
        base = i * FST_ENTRY_SIZE
        is_dir = data[base] == 1
        name_offset = struct.unpack(">I", b"\0" + data[base + 1 : base + 4])[0]
        a, b = struct.unpack(">II", data[base + 4 : base + 12])

        while len(stack) > 1 and i >= stack[-1][1]:
            stack.pop()

        parent = "/".join(n for n, _ in stack if n)
        name = name_at(name_offset)
        full = f"{parent}/{name}" if parent else name

        if is_dir:
            fst.dirs.append(full)
            stack.append((name, b))  # b = next_index
        else:
            fst.files.append(FstFile(full, a, b))  # a = offset, b = size

    return fst


class Disc:
    """A decoded GameCube disc, backed by any object exposing read(offset, length)."""

    def __init__(self, reader):
        self.reader = reader
        self.boot = parse_boot(reader.read(0, BOOT_HEADER_SIZE))
        if not self.boot.is_gamecube:
            raise ValueError(f"bad magic word 0x{self.boot.magic:08X}")
        self._fst: Fst | None = None

    @property
    def fst(self) -> Fst:
        if self._fst is None:
            self._fst = parse_fst(self.reader.read(self.boot.fst_offset, self.boot.fst_size))
        return self._fst

    def read_file(self, entry: FstFile) -> bytes:
        return self.reader.read(entry.offset, entry.size)

    def read_dol(self) -> bytes:
        from . import dol

        header = self.reader.read(self.boot.dol_offset, 0x100)
        return self.reader.read(self.boot.dol_offset, dol.image_size(header))

    def extract(self, dest: Path, progress=None) -> int:
        """Write every file in the FST under `dest`. Returns bytes written."""
        dest = Path(dest)
        written = 0
        files = sorted(self.fst.files, key=lambda f: f.offset)  # sequential disc reads
        for n, entry in enumerate(files):
            out = dest / entry.path
            out.parent.mkdir(parents=True, exist_ok=True)
            data = self.read_file(entry)
            if len(data) != entry.size:
                raise OSError(f"{entry.path}: read {len(data)} bytes, FST says {entry.size}")
            out.write_bytes(data)
            written += len(data)
            if progress:
                progress(n + 1, len(files), entry, written)

        # system files the FST does not list
        sysdir = dest / "sys"
        sysdir.mkdir(parents=True, exist_ok=True)
        (sysdir / "boot.bin").write_bytes(self.reader.read(0, BOOT_HEADER_SIZE))
        (sysdir / "bi2.bin").write_bytes(self.reader.read(BI2_OFFSET, 0x2000))
        (sysdir / "main.dol").write_bytes(self.read_dol())
        (sysdir / "fst.bin").write_bytes(self.reader.read(self.boot.fst_offset, self.boot.fst_size))
        return written
