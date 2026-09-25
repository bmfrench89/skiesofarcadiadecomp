"""GameCube disc layout: boot header, FST parsing, file extraction, and reading
one file of an extracted disc without the loose tree.

FST format: a flat array of 12-byte entries followed by a string table.
Entry 0 is the root directory, whose `next_index` is the total entry count.

  byte  0     type (0 = file, 1 = directory)
  bytes 1-3   24-bit big-endian offset into the string table
  bytes 4-7   file: disc offset        directory: parent index
  bytes 8-11  file: size               directory: next index (first entry past it)

Directory nesting is recovered by tracking `next_index` on a stack rather than
by following parent pointers, which keeps the walk single-pass.

An extraction (`tools/extract.py`) is `disc.iso` plus `sys/`; the loose files
are written only with `--files`, and the port never reads them. So a tool that
wants one file asks `open_data(root)`, which hands back a `Disc` over the image
when there is one and a `LooseTree` over the files of an older extraction when
there is not. Both answer `read_path("field/me101b.sct")`.
"""

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

BOOT_HEADER_SIZE = 0x440
BI2_OFFSET = 0x440
BI2_SIZE = 0x2000
APPLOADER_OFFSET = 0x2440
FST_ENTRY_SIZE = 12

# An extraction: the image, and the system files beside it (`Disc.system_files`).
IMAGE_NAME = "disc.iso"
SYSTEM_DIR = "sys"

EXTRACT_HINT = "python tools/extract.py <your disc dump>"


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


class ImageFile:
    """A flat disc image (.iso/.gcm) read in place: the `read(offset, length)`
    every `Disc` reader has, over a file held open for the object's life."""

    def __init__(self, path):
        self.path = Path(path)
        self.f = open(self.path, "rb")  # noqa: SIM115 -- closed by close()
        self.size = os.fstat(self.f.fileno()).st_size

    def read(self, offset: int, length: int) -> bytes:
        self.f.seek(offset)
        return self.f.read(length)

    def close(self) -> None:
        self.f.close()


class Disc:
    """A decoded GameCube disc, backed by any object exposing read(offset, length)."""

    def __init__(self, reader, source: str = ""):
        self.reader = reader
        self.source = source or str(getattr(reader, "path", "the disc image"))
        self.boot = parse_boot(reader.read(0, BOOT_HEADER_SIZE))
        if not self.boot.is_gamecube:
            raise ValueError(f"{self.source}: bad magic word 0x{self.boot.magic:08X}")
        self._fst: Fst | None = None
        self._by_path: dict[str, FstFile] | None = None

    @classmethod
    def from_file(cls, path) -> Disc:
        """A `Disc` over a flat image, its file closed again if it is not one."""
        reader = ImageFile(path)
        try:
            return cls(reader)
        except BaseException:
            reader.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        close = getattr(self.reader, "close", None)
        if close:
            close()

    @property
    def fst(self) -> Fst:
        if self._fst is None:
            self._fst = parse_fst(self.reader.read(self.boot.fst_offset, self.boot.fst_size))
        return self._fst

    def entry(self, path: str) -> FstFile | None:
        """The FST entry for `path`, compared as the game's own lookup does
        (DVDConvertPathToEntrynum): without regard to case."""
        if self._by_path is None:
            self._by_path = {f.path.lower(): f for f in self.fst.files}
        return self._by_path.get(path.replace("\\", "/").strip("/").lower())

    def read_file(self, entry: FstFile) -> bytes:
        return self.reader.read(entry.offset, entry.size)

    def read_path(self, path: str) -> bytes:
        """One file by its path on the disc, e.g. "field/me101b.sct"."""
        entry = self.entry(path)
        if entry is None:
            raise FileNotFoundError(f"{path}: not in {self.source}'s file table")
        data = self.read_file(entry)
        if len(data) != entry.size:
            raise OSError(
                f"{entry.path}: read {len(data):,} bytes of {self.source}, FST says {entry.size:,}"
            )
        return data

    def paths(self) -> list[str]:
        return [f.path for f in self.fst.files]

    def extents(self) -> list[tuple[str, Path, int, int]]:
        """(path on the disc, host file, offset, length) for every file, in FST
        order, so a worker process can read its own slice without this object."""
        image = getattr(self.reader, "path", None)
        if image is None:
            raise TypeError(f"{self.source}: not a flat image, so its files have no host extent")
        return [(f.path, image, f.offset, f.size) for f in self.fst.files]

    def read_dol(self) -> bytes:
        from . import dol

        header = self.reader.read(self.boot.dol_offset, 0x100)
        return self.reader.read(self.boot.dol_offset, dol.image_size(header))

    def system_files(self) -> dict[str, bytes]:
        """The four files the FST does not list, as `sys/` holds them."""
        return {
            "boot.bin": self.reader.read(0, BOOT_HEADER_SIZE),
            "bi2.bin": self.reader.read(BI2_OFFSET, BI2_SIZE),
            "main.dol": self.read_dol(),
            "fst.bin": self.reader.read(self.boot.fst_offset, self.boot.fst_size),
        }

    def write_system_files(self, dest: Path) -> list[Path]:
        """Write `dest/sys/` -- what the tools and today's runtime read."""
        sysdir = Path(dest) / SYSTEM_DIR
        sysdir.mkdir(parents=True, exist_ok=True)
        written = []
        for name, data in self.system_files().items():
            (sysdir / name).write_bytes(data)
            written.append(sysdir / name)
        return written

    def extract_files(self, dest: Path, progress=None) -> int:
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
        return written


class LooseTree:
    """The loose files of an extraction made before the image was the default:
    one file per FST entry under `root`, `sys/` beside them. Read only when
    there is no image to read instead (`open_data`)."""

    def __init__(self, root):
        self.root = Path(root)
        self.source = str(self.root)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        pass

    def read_path(self, path: str) -> bytes:
        p = self.root / path.replace("\\", "/").strip("/")
        if not p.is_file():
            raise FileNotFoundError(f"{path}: not under {self.root} (and no {IMAGE_NAME} there)")
        return p.read_bytes()

    def paths(self) -> list[str]:
        """Every file but `sys/` and the image, as paths relative to the root."""
        out = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if rel.parts[0].lower() == SYSTEM_DIR or not p.is_file():
                continue
            if len(rel.parts) == 1 and rel.name.lower() == IMAGE_NAME:
                continue
            out.append(rel.as_posix())
        return out

    def extents(self) -> list[tuple[str, Path, int, int]]:
        return [(p, self.root / p, 0, -1) for p in self.paths()]


def find_image(root) -> Path | None:
    """The disc image an extraction at `root` reads from, or None. `root` may
    be the image itself. (I4 puts the store ahead of disc.iso here.)"""
    root = Path(root)
    if root.is_file():
        return root
    if (root / IMAGE_NAME).is_file():
        return root / IMAGE_NAME
    return None


def open_data(root) -> Disc | LooseTree:
    """What an extraction at `root` holds, to read files from: a `Disc` over
    its image when it has one, else a `LooseTree` over its loose files.
    `root` may also name an .iso/.gcm directly."""
    root = Path(root)
    image = find_image(root)
    if image is not None:
        if image.suffix.lower() == ".rvz":
            raise ValueError(f"{image}: an RVZ is read by the extractor only; {EXTRACT_HINT}")
        return Disc.from_file(image)
    if root.is_dir():
        return LooseTree(root)
    raise FileNotFoundError(f"{root}: no extracted disc -- {EXTRACT_HINT}")


def read_data_file(root, path: str) -> bytes:
    """`root/path` when that loose file exists, else `path` read through the
    image `open_data(root)` finds."""
    root = Path(root)
    if root.is_dir() and (root / path).is_file():
        return (root / path).read_bytes()
    with open_data(root) as data:
        return data.read_path(path)


def read_data_path(path) -> bytes:
    """`path` when it exists. When it does not, the nearest directory above it
    that holds a disc image (or the image itself, as in
    `extracted/disc.iso/sound/m01_L.dsp`) is taken as the data directory, and
    the rest of the path is looked up in the image's file table. So a command
    quoting `extracted/sound/m01_L.dsp` still works once the loose tree is
    gone."""
    path = Path(path)
    if path.is_file():
        return path.read_bytes()
    for parent in path.parents:
        image = find_image(parent)
        if image is None:
            continue
        rel = path.relative_to(parent).as_posix()
        with open_data(image) as data:
            return data.read_path(rel)
    raise FileNotFoundError(
        f"{path}: no such file, and no {IMAGE_NAME} in any directory above it to read it from"
    )
