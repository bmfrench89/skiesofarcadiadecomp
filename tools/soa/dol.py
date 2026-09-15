"""GameCube DOL executable parsing.

The DOL header is 0x100 bytes: 7 text sections then 11 data sections, each with
parallel arrays of file offset, virtual address and size, followed by BSS and
the entry point.
"""

import struct
from dataclasses import dataclass

DOL_HEADER_SIZE = 0x100
N_TEXT = 7
N_DATA = 11


@dataclass(frozen=True)
class Section:
    name: str
    file_offset: int
    address: int
    size: int
    is_text: bool

    @property
    def end(self) -> int:
        return self.address + self.size

    def contains(self, addr: int) -> bool:
        return self.address <= addr < self.end


@dataclass
class Dol:
    sections: list[Section]
    bss_address: int
    bss_size: int
    entry_point: int
    data: bytes

    @property
    def text(self) -> list[Section]:
        return [s for s in self.sections if s.is_text]

    @property
    def code_size(self) -> int:
        return sum(s.size for s in self.text)

    @property
    def instruction_count(self) -> int:
        return self.code_size // 4

    def section_at(self, addr: int) -> Section | None:
        for s in self.sections:
            if s.contains(addr):
                return s
        return None

    def read(self, addr: int, length: int) -> bytes:
        """Read `length` bytes from virtual address `addr`."""
        s = self.section_at(addr)
        if s is None:
            raise ValueError(f"address 0x{addr:08X} is not mapped")
        off = s.file_offset + (addr - s.address)
        return self.data[off:off + length]

    def word(self, addr: int) -> int:
        """Read one big-endian u32 from virtual address `addr`."""
        return struct.unpack(">I", self.read(addr, 4))[0]


def parse(data: bytes) -> Dol:
    """Parse a DOL image already in memory."""
    if len(data) < DOL_HEADER_SIZE:
        raise ValueError("too short to be a DOL")

    text_off = struct.unpack(">7I", data[0x00:0x1C])
    data_off = struct.unpack(">11I", data[0x1C:0x48])
    text_addr = struct.unpack(">7I", data[0x48:0x64])
    data_addr = struct.unpack(">11I", data[0x64:0x90])
    text_size = struct.unpack(">7I", data[0x90:0xAC])
    data_size = struct.unpack(">11I", data[0xAC:0xD8])
    bss_address, bss_size, entry_point = struct.unpack(">III", data[0xD8:0xE4])

    sections: list[Section] = []
    for i, (o, a, s) in enumerate(zip(text_off, text_addr, text_size)):
        if s:
            sections.append(Section(f".text{i}", o, a, s, True))
    for i, (o, a, s) in enumerate(zip(data_off, data_addr, data_size)):
        if s:
            sections.append(Section(f".data{i}", o, a, s, False))

    return Dol(sections, bss_address, bss_size, entry_point, data)


def image_size(header: bytes) -> int:
    """Total DOL size from its header alone, for reading the image off a disc."""
    text_off = struct.unpack(">7I", header[0x00:0x1C])
    data_off = struct.unpack(">11I", header[0x1C:0x48])
    text_size = struct.unpack(">7I", header[0x90:0xAC])
    data_size = struct.unpack(">11I", header[0xAC:0xD8])
    return max(
        [o + s for o, s in zip(text_off, text_size)]
        + [o + s for o, s in zip(data_off, data_size)]
    )
