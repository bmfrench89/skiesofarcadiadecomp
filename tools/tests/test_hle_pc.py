"""Every native adapter says which guest function it is.

A sample is whatever the guest thread last stored into `s->pc`, and the
recompiled code stores it at the head of every basic block. A function swapped
out for native C stores nothing, so its time is charged to whichever block ran
last -- the caller's call site. That is worse than the function being
invisible: it makes an innocent block look expensive, and memcpy and memset
are among the hottest things the game does.

The fix is one store of the adapter's own entry address, first thing. Nothing
existing would catch it going missing: runtime/selftest.c compares `gpr[3]`
and guest memory between the twin and the native code and never looks at
`pc`, and it calls `recomp_fn_*` and `dc_*` directly rather than the `fn_*`
adapters. So the check has to be on the source, and it has to be one that the
next adapter added to runtime/decomp_swap.c cannot walk past.

Needs no disc.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SWAP = ROOT / "runtime" / "decomp_swap.c"
HLE = ROOT / "config" / "hle.txt"

ADAPTER = re.compile(r"^void fn_([0-9A-F]{8})\(CpuState\* s\)\s*\{(.*)$", re.MULTILINE)


def adapters() -> list[tuple[str, str]]:
    return ADAPTER.findall(SWAP.read_text(encoding="utf-8"))


def test_every_adapter_stores_its_own_address_before_it_does_anything():
    found = adapters()
    assert found, "no fn_XXXXXXXX adapters found in runtime/decomp_swap.c"
    for addr, body in found:
        first = body.strip().split(";")[0].strip() + ";"
        assert first == f"s->pc = 0x{addr}u;", (
            f"fn_{addr} starts with {first!r}; it has to store its own entry address into s->pc "
            "before any native work, or a sample taken inside it names its caller"
        )


def test_the_address_stored_is_the_function_entry_config_hle_names():
    """The entry address literally, so the profile's containment lookup lands
    inside that function's own row in config/functions.tsv and the sample
    prints as `strlen`. Any other value would need a second table."""
    bound = {
        line.split()[0].lower()
        for line in HLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for addr, _ in adapters():
        assert f"0x{addr.lower()}" in bound, (
            f"runtime/decomp_swap.c defines fn_{addr}, which config/hle.txt does not bind"
        )


def test_the_caller_s_pc_is_not_saved_and_restored():
    """The generated call sites do not restore it either -- a caller's
    straight-line tail after a call is charged to the callee until the caller
    reaches its next block header -- so a store-only adapter has exactly the
    attribution shape of the translation it replaces, at one store instead of
    a load, a live register across the call and a second store. Interrupts are
    the case that argues the other way, and runtime/irq.c handles those."""
    for addr, body in adapters():
        assert body.count("s->pc") == 1, f"fn_{addr} touches s->pc more than once"


def test_the_five_adapters_outside_this_file_are_still_a_known_hole():
    """config/hle.txt binds every function the runtime provides natively; the
    ones in this file are PLAN A4's and F3's. The other seven are two no-ops
    in hle_os.c, the two printf paths
    in hle_stdio.c and the three context-switch adapters in threads.c -- of
    which OSSaveContext memcpys a five-kilobyte CpuState about fifteen
    thousand times a run, all of it charged to SelectThread. Those files are
    not A4's to edit; this records the hole rather than letting it be
    forgotten."""
    bound = [
        line.split()[0]
        for line in HLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    here = {f"0x{addr}".lower() for addr, _ in adapters()}
    elsewhere = [a for a in bound if a.lower() not in here]
    assert len(elsewhere) == 7, (
        f"config/hle.txt now binds {len(elsewhere)} adapters outside runtime/decomp_swap.c "
        f"({', '.join(elsewhere)}); each one is invisible to the sampler until it stores s->pc too"
    )
