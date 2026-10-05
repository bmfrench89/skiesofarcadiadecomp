"""The player's system files built into soa.exe (disc-layer I3): <--out>/disc_sys.c.

recompile.py writes it at every run from the disc the build is made from: the
executable, boot.bin (0x440 bytes) and the file table, each as an array of
32-bit words whose little-endian bytes are the file's bytes (words compile
about three times faster than bytes), with its size and SHA-1. runtime/disc.c
prefers these copies, hashes the built-in executable at boot to catch a
generator or byte-order bug, and refuses an image whose file table is not this
one. --no-embed writes the same symbols with nothing in them, and the runtime
then reads the image's own (and says so).

An embedding file's first line is MARKER, which tools/guard.py refuses in any
tracked file: these are verbatim copies of the player's game files, for their
build and no one else's. The literal is built by concatenation here and in the
guard, so neither source file holds it.
"""

from __future__ import annotations

import hashlib

MARKER = "soa" + ":" + "embedded-game-data"
WORDS_PER_LINE = 8
PARTS = (("dol", "main.dol"), ("boot", "boot.bin"), ("fst", "fst.bin"))


def words(data: bytes) -> list[int]:
    """`data` as little-endian 32-bit words, its tail padded with zeros."""
    padded = data + bytes(-len(data) % 4)
    return [int.from_bytes(padded[i : i + 4], "little") for i in range(0, len(padded), 4)]


def array(name: str, data: bytes) -> str:
    ws = words(data) or [0]  # C has no empty array; the size says 0
    rows = [
        "    " + ", ".join(f"0x{w:08X}u" for w in ws[i : i + WORDS_PER_LINE]) + ","
        for i in range(0, len(ws), WORDS_PER_LINE)
    ]
    return f"const uint32_t {name}[{len(ws)}] = {{\n" + "\n".join(rows) + "\n};\n"


def disc_sys_c(system: dict[str, bytes] | None) -> str:
    """The C for <--out>/disc_sys.c: `system` holds main.dol, boot.bin and
    fst.bin as the disc does; None is --no-embed, the same symbols empty."""
    out = []
    if system is not None:
        out.append(
            f"/* {MARKER}: never commit or share this file, or the soa.exe it is built into */"
        )
        out.append(
            "/* The player's own executable, disc header and file table (disc-layer I3), from"
        )
        out.append(" * tools/recompile.py: little-endian words of the files' bytes. */")
    else:
        out.append(
            "/* Built without the player's system files (recompile.py --no-embed, disc-layer I3):"
        )
        out.append(" * the runtime reads them from the image, and says so at boot. */")
    out += ["#include <stddef.h>", "#include <stdint.h>", ""]
    for sym, name in PARTS:
        data = system[name] if system is not None else b""
        digest = hashlib.sha1(data, usedforsecurity=False).hexdigest() if data else ""
        out.append(array(f"disc_sys_{sym}", data))
        out.append(f"const size_t disc_sys_{sym}_size = {len(data)}u;")
        out.append(f'const char disc_sys_{sym}_sha1[] = "{digest}";')
        out.append("")
    return "\n".join(out)
