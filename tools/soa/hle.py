"""Binding lists: where the runtime takes over from recompiled code.

Both files use one ``address name [# note]`` entry per line.

``config/hle.txt`` -- functions the runtime replaces. The recompiler still
emits each one, under the name ``recomp_fn_XXXXXXXX`` so it stays available
for differential testing, while ``fn_XXXXXXXX`` is left for the runtime to
define natively. Every caller then binds to the native version at link time
without being touched. This is the binding table of SPEC section 4.2.

``config/hooks.txt`` -- addresses at which the recompiled code calls back
into the runtime *before* executing the instruction there. The one that
matters most is the scheduler's idle loop: with no hardware to raise
interrupts, that is where the runtime delivers them.
"""

import re
from pathlib import Path

# One entry, the whole line once its comment is gone: a lower-case 0x, exactly
# eight hex digits, and one name.
_LINE = re.compile(r"^\s*(0x[0-9A-Fa-f]{8})\s+(\S+)\s*$")


def load_bindings(path: Path) -> dict[int, str]:
    """{address: name} for every entry; comments and blanks ignored.

    Any other line is a ValueError naming the file and line, and so is a
    second entry for an address. Both used to pass without a word: a line
    the pattern missed (`0X80005520`, `0x8000552`, `80005520`) was skipped,
    and a repeated address replaced the first. Every list this reads is baked
    into the translated C, so a binding lost here is a function the runtime
    was meant to answer that recompiled code answers instead, or a tracepoint
    that never fires -- and nothing notices until someone wonders why.
    """
    out: dict[int, str] = {}
    first: dict[int, int] = {}
    path = Path(path)
    if not path.exists():
        return out
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0]
        if not line.strip():
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(
                f"{path}:{n}: not `0xXXXXXXXX name [# note]` (a lower-case 0x, eight hex "
                f"digits, one name): {raw.strip()!r}"
            )
        addr = int(m.group(1), 16)
        if addr in out:
            raise ValueError(
                f"{path}:{n}: 0x{addr:08X} is already bound, to {out[addr]} at line {first[addr]}"
            )
        out[addr] = m.group(2)
        first[addr] = n
    return out


load_hle = load_bindings
