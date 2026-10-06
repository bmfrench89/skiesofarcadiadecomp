"""A game library checked as a file (specs/android.md 3.3, L12b): the Python
twin of runtime/elfcheck.c, so the PC that built a library can say, before it
goes to a phone, what the phone's runtime would say of it, in the same words.

    from soa import elfcheck
    elfcheck.problems(elfcheck.read(path), machine=183, exports=..., libc=..., record=...)

read() parses a 64-bit little-endian ELF shared object's headers: its machine
and type, every PT_LOAD's alignment, DT_NEEDED, DT_SONAME and text
relocations, the record in .note.soa, and its dynamic symbols. problems()
lists what elfcheck.c would refuse, first refusal first, and, stricter than
the phone (which needs only its own table), any export but soa_game.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from soa import seam

MACHINES = {3: "32-bit x86", 40: "32-bit ARM", 62: "x86-64", 183: "64-bit ARM (AArch64)"}
EM_AARCH64, EM_X86_64 = 183, 62
MIN_ALIGN = 16384
PT_LOAD, SHT_DYNAMIC, SHT_DYNSYM = 1, 6, 11
DT_NEEDED, DT_SONAME, DT_TEXTREL, DT_FLAGS, DF_TEXTREL = 1, 14, 22, 30, 4
STB_WEAK = 2
C_LIBRARIES = ("libc.so", "libm.so", "libdl.so")


class NotElf(ValueError):
    pass


@dataclass
class Elf:
    machine: int
    type: int
    load_aligns: list[int] = field(default_factory=list)
    needed: list[str] = field(default_factory=list)
    soname: str = ""
    textrel: bool = False
    record: str | None = None
    imports: list[tuple[str, bool]] = field(default_factory=list)  # (name, weak)
    exports: list[str] = field(default_factory=list)


def _cstr(blob: bytes, at: int) -> str:
    end = blob.find(b"\0", at)
    return blob[at : end if end >= 0 else len(blob)].decode("utf-8", "replace")


def _note_record(blob: bytes) -> str | None:
    at = 0
    while at + 12 <= len(blob):
        namesz, descsz, _ = struct.unpack_from("<III", blob, at)
        name = at + 12
        desc = name + ((namesz + 3) & ~3)
        if desc + descsz > len(blob):
            return None
        if namesz == 4 and blob[name : name + 4] == b"SOA\0":
            return _cstr(blob[desc : desc + descsz], 0)
        at = desc + ((descsz + 3) & ~3)
    return None


def read(path: Path) -> Elf:
    """The headers of an ELF shared object; NotElf when it is none."""
    data = Path(path).read_bytes()
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise NotElf(f"{path} is not a library for this system")
    if data[4] != 2 or data[5] != 1:
        raise NotElf(f"{path} is not a 64-bit library for this system")
    e_type, machine = struct.unpack_from("<HH", data, 16)
    phoff, shoff = struct.unpack_from("<QQ", data, 32)
    phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from("<HHHHH", data, 54)
    elf = Elf(machine=machine, type=e_type)
    if phentsize != 56 or shentsize != 64 or shstrndx >= shnum:
        raise NotElf(f"{path} is damaged: its headers are not where it says")
    for i in range(phnum):
        p_type = struct.unpack_from("<I", data, phoff + i * 56)[0]
        if p_type == PT_LOAD:
            elf.load_aligns.append(struct.unpack_from("<Q", data, phoff + i * 56 + 48)[0])
    sections = []
    for i in range(shnum):
        name, kind = struct.unpack_from("<II", data, shoff + i * 64)
        off, size = struct.unpack_from("<QQ", data, shoff + i * 64 + 24)
        link = struct.unpack_from("<I", data, shoff + i * 64 + 40)[0]
        sections.append((name, kind, off, size, link))
    _, _, stroff, strsize, _ = sections[shstrndx]
    shstr = data[stroff : stroff + strsize]
    dynamic = dynsym = None
    for name, kind, off, size, link in sections:
        if kind == SHT_DYNAMIC:
            dynamic = data[off : off + size]
        elif kind == SHT_DYNSYM:
            dynsym = (data[off : off + size], link)
        elif _cstr(shstr, name) == ".note.soa":
            elf.record = _note_record(data[off : off + size])
    if dynamic is None or dynsym is None:
        raise NotElf(f"{path} has no dynamic symbols: it is not a library this package built")
    _, _, doff, dsize, _ = sections[dynsym[1]]
    dynstr = data[doff : doff + dsize]
    for at in range(0, len(dynamic) - 15, 16):
        tag, val = struct.unpack_from("<qQ", dynamic, at)
        if tag == 0:
            break
        if tag == DT_NEEDED:
            elf.needed.append(_cstr(dynstr, val))
        elif tag == DT_SONAME:
            elf.soname = _cstr(dynstr, val)
        elif tag == DT_TEXTREL or (tag == DT_FLAGS and val & DF_TEXTREL):
            elf.textrel = True
    syms = dynsym[0]
    for at in range(0, len(syms) - 23, 24):
        st_name, st_info, _, st_shndx = struct.unpack_from("<IBBH", syms, at)
        name = _cstr(dynstr, st_name)
        if not name:
            continue
        if st_shndx == 0:
            elf.imports.append((name, (st_info >> 4) == STB_WEAK))
        else:
            elf.exports.append(name)
    return elf


def _c_library(name: str) -> bool:
    return any(name == lib or name.startswith(lib + ".") for lib in C_LIBRARIES)


def _field(rec: str, key: str) -> str:
    for part in rec.split():
        k, _, v = part.partition("=")
        if k == key:
            return v
    return ""


def problems(
    elf: Elf,
    *,
    machine: int,
    exports: set[str] | list[str],
    libc: set[str] | tuple[str, ...],
    record: str,
    path: str = "this library",
) -> list[str]:
    """What runtime/elfcheck.c would refuse, in its words, first refusal
    first; and then, for the PC's own check, any export but soa_game."""
    out: list[str] = []
    if elf.machine != machine:
        out.append(
            f"this library was built for {MACHINES.get(elf.machine, 'another machine')}, not this device "
            f"({MACHINES.get(machine, 'another machine')}): rebuild it for this device with Setup"
        )
        return out
    if elf.type != 3:
        return [f"{path} is a program, not a game library"]
    for a in elf.load_aligns:
        if a < MIN_ALIGN:
            out.append(
                f"this library was built for {a}-byte pages, and devices may use 16 KB ones: rebuild it with "
                "this package's Setup"
            )
            break
    if elf.textrel:
        out.append(
            "this library has text relocations, which Android refuses to load: rebuild it with this package"
        )
    for name in elf.needed:
        if name != seam.RUNTIME_SONAME and not _c_library(name):
            out.append(
                f"this library needs {name}, which this app does not have: rebuild it with this package"
            )
    if seam.RUNTIME_SONAME not in elf.needed:
        out.append(
            f"this library was not built against this app's runtime (it does not need {seam.RUNTIME_SONAME}): "
            "rebuild it with this package"
        )
    if elf.record is None:
        out.append("this library carries no build record: it was not made by this package's Setup")
    else:
        for key in ("abi", "mode", "baked"):
            theirs, mine = _field(elf.record, key), _field(record, key)
            if theirs != mine:
                out.append(
                    f"this library was built from other sources than this app (its {key} is "
                    f"{theirs or 'missing'}, the app's {mine}): rebuild it with this package's Setup"
                )
                break
    allowed = set(exports) | set(libc)
    for name, weak in elf.imports:
        if not weak and name not in allowed:
            out.append(
                f"this library needs {name}, which this app's runtime does not have: rebuild it with this "
                "package's Setup"
            )
    if "soa_game" not in elf.exports:
        out.append(f"{path} has no soa_game table: it is not a game library")
    extra = sorted(set(elf.exports) - {"soa_game", "_init", "_fini"})
    if extra:
        out.append(
            f"{path} exports {', '.join(extra[:5])} beside soa_game: its functions are not hidden"
        )
    return out
