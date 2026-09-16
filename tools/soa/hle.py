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

_LINE = re.compile(r"^\s*(0x[0-9A-Fa-f]{8})\s+(\S+)")


def load_bindings(path: Path) -> dict[int, str]:
    """{address: name} for every entry; comments and blanks ignored."""
    out: dict[int, str] = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0]
        m = _LINE.match(line)
        if m:
            out[int(m.group(1), 16)] = m.group(2)
    return out


load_hle = load_bindings
