"""The parts of Track B that are text, and so can be checked with no disc.

The memory-card device model is C and its own checks run only inside the port,
on the owner's machine: runtime/selftest.c needs dispatch() and the recompiled
game, so no CI leg can run it. What CI can hold is the agreement between the
files -- that the device model, the checks written against it and irq.c still
say the same thing about the device ID, the interrupt numbers and the SRAM
offset -- and that config/names.txt, which everything below navigates by,
stays a set of claims about functions that exist.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import matchcheck as M  # noqa: E402
from soa import symbols as S  # noqa: E402

EXI = (ROOT / "runtime" / "exi.c").read_text(encoding="utf-8")
IRQ = (ROOT / "runtime" / "irq.c").read_text(encoding="utf-8")
SELFTEST = (ROOT / "runtime" / "selftest.c").read_text(encoding="utf-8")


def define(text: str, name: str) -> str:
    m = re.search(rf"^#define {name} (.+?)\s*(?:/\*.*)?$", text, re.MULTILINE)
    assert m, f"{name} is not defined any more"
    return m.group(1).strip()


def test_names_txt_is_a_set_of_claims_about_functions_that_exist():
    """Every line is address<TAB>name<TAB>evidence, and the address is a
    function start in the inventory. An entry without evidence is a name
    nobody can disagree with, and an address with no function at it is a claim
    about the executable that the executable does not support."""
    inventory = S.load_tsv(ROOT / "config" / "functions.tsv")
    seen_address: dict[int, int] = {}
    seen_name: dict[str, int] = {}
    entries = 0
    for number, line in enumerate(
        (ROOT / "config" / "names.txt").read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip() or line.startswith("#"):
            continue
        entries += 1
        fields = line.split("\t")
        assert len(fields) == 3, f"line {number}: {len(fields)} tab-separated fields, want 3"
        address, name, evidence = int(fields[0], 16), fields[1].strip(), fields[2].strip()
        assert name, f"line {number}: no name"
        assert evidence, f"line {number}: {name} has no evidence"
        assert address in inventory, f"line {number}: no function starts at 0x{address:08X}"
        assert address not in seen_address, (
            f"line {number}: 0x{address:08X} is already on line {seen_address.get(address)}"
        )
        assert name not in seen_name, (
            f"line {number}: {name} is already on line {seen_name.get(name)}"
        )
        seen_address[address] = number
        seen_name[name] = number
    assert entries > 100, "the file has shrunk to nothing; this check would pass vacuously"


def test_every_recovered_name_still_resolves_to_its_own_address():
    """tools/matchcheck.py resolves a source's spelling through these names, and
    a name two addresses claim resolves to neither -- which would silently stop
    comparing the unit that used it. A new entry colliding with an inventory
    name elsewhere is exactly how that happens."""
    inventory = S.load_tsv(ROOT / "config" / "functions.tsv")
    names = S.load_names(ROOT / "config" / "names.txt")
    index = M.name_index(inventory, names)
    ambiguous = [
        f"{name} (0x{address:08X})"
        for address, (name, _) in names.items()
        if index.get(name) != address
    ]
    assert not ambiguous, f"these recovered names no longer resolve to themselves: {ambiguous}"


def test_the_selftest_expects_the_device_id_the_device_model_answers():
    """CARDIsCard reads the ID as three fields -- size, sector-size index and
    latency index -- so the value and the geometry the rest of exi.c implements
    are one decision. The check in the selftest spells it out as a string,
    which is the only place the two are tied together."""
    assert define(EXI, "CARD_ID") == "0x00000004u"
    assert 'check("card device ID", got, "00000004")' in SELFTEST


def test_the_selftest_installs_handlers_where_irq_c_looks_for_them():
    """The card's interrupt reaching the guest is the third of B2's blockers,
    and the selftest proves it by installing a handler in one slot and counting
    what arrives there. If irq.c renumbers, the check has to move with it."""
    for channel, number in enumerate((9, 12, 15)):
        assert define(IRQ, f"IRQ_EXI_{channel}_EXI") == str(number)
        assert f"irq_handler_slot(s, {number}), EXI_HANDLER" in SELFTEST
    for channel, number in enumerate((10, 13, 16)):
        assert define(IRQ, f"IRQ_EXI_{channel}_TC") == str(number)


def test_the_card_checks_are_all_still_there():
    """Each of these is the only thing standing between a revert and a silent
    return to "card 0 bytes read, 0 written". Deleting one has to be an edit
    here too, not a line quietly dropped from a C file nothing else reads."""
    expected = {
        "card image starts absent",
        "card device ID",
        "card read status",
        "card program and read back",
        "read latency on the DMA path",
        "SRAM flash ID from image",
        "SRAM flash ID checksum",
        "SRAM checksum and flags",
        "SRAM write and read at offset",
        "SRAM DMA both ways",
        "program raises the interrupt",
        "masked interrupt waits",
        "masked, nothing delivered",
        "delivered to interrupt 9",
        "cleared, nothing delivered",
        "handler reads status",
        "handler leaves it quiet",
        "programmed page reads back",
        "erase raises the interrupt",
        "erase handler sees a clear bit",
        "sector erase",
        "consecutive page programs",
        "disabled card stays quiet",
        "card image flushed to disk",
        "reloaded from disk",
        "card counters",
    }
    present = set(re.findall(r'check\("([^"]+)"', SELFTEST))
    assert expected <= present, f"gone from runtime/selftest.c: {sorted(expected - present)}"


def test_the_card_switches_are_documented():
    """SOA_CARD is how B4 points the port at a Dolphin-formatted image and
    SOA_CARD_VERBOSE is the only way to see which frame the probe lands on.
    Both were undiscoverable until they were in the table."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for switch in ("SOA_CARD", "SOA_CARD_VERBOSE"):
        assert f"`{switch}" in readme, (
            f"{switch} is read by runtime/exi.c and named nowhere in README.md"
        )


def test_the_mounts_sram_offset_is_the_same_in_both_files():
    """CARDDoMount sums the twelve flash-ID bytes at SRAM+20 and compares the
    complement against SRAM 58 -- __OSLockSramEx returns SRAM+20 and the store
    is at +38. Leaving that byte zero was the second of B2's blockers, and the
    two files have to agree about where it is or the check proves nothing."""
    assert "g_sram[58] = (uint8_t)~idsum;" in EXI
    assert "sram[58]" in SELFTEST
