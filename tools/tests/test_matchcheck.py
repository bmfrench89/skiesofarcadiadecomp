"""How an object's symbol is matched to a function in the executable.

The oracle used to resolve by name alone, so regenerating config/functions.tsv
-- which renames whatever config/names.txt has since recovered -- unmatched
eleven functions across three units with no source change: eight reported "not
in the inventory" and the three static ones were silently skipped as inlined
helpers. These tests pin both directions of the fallback.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matchcheck as M  # noqa: E402


def inventory(*entries):
    return {addr: {"name": name, "size": 4} for addr, name in entries}


def test_address_in_the_symbol_wins_over_the_inventorys_name():
    inv = inventory((0x8025EF88, "strcmp"))
    index = M.name_index(inv)
    assert M.resolve_address("fn_8025EF88", inv, index) == 0x8025EF88
    assert M.resolve_address("strcmp", inv, index) == 0x8025EF88


def test_lowercase_address_resolves_too():
    inv = inventory((0x80243C04, "fn_80243C04"))
    assert M.resolve_address("fn_80243c04", inv, M.name_index(inv)) == 0x80243C04


def test_a_recovered_name_resolves_before_the_inventory_carries_it():
    # names.txt is written first; a source may use the name a regeneration later.
    inv = inventory((0x80248884, "fn_80248884"))
    index = M.name_index(inv, {0x80248884: ("CARDMount", "SDK call sequence")})
    assert M.resolve_address("CARDMount", inv, index) == 0x80248884
    assert M.resolve_address("fn_80248884", inv, index) == 0x80248884


def test_an_unknown_symbol_resolves_to_nothing():
    inv = inventory((0x80243C04, "ARQInit"))
    index = M.name_index(inv)
    assert M.resolve_address("ARQFlush", inv, index) is None
    # An address the inventory never recovered is not a match either.
    assert M.resolve_address("fn_80243C08", inv, index) is None


def test_a_name_two_addresses_claim_resolves_to_neither():
    inv = inventory((0x80001000, "memcpy"), (0x80002000, "memcpy"), (0x80003000, "strlen"))
    index = M.name_index(inv, {0x80004000: ("strlen", "self-naming string")})
    assert "memcpy" not in index
    assert "strlen" not in index
    assert M.resolve_address("memcpy", inv, index) is None


def test_the_inventory_and_names_agreeing_is_not_a_collision():
    inv = inventory((0x8025EF88, "strcmp"))
    index = M.name_index(inv, {0x8025EF88: ("strcmp", "decompiled byte-for-byte (src/)")})
    assert index["strcmp"] == 0x8025EF88


def test_a_symbol_that_spells_an_address_is_never_passed_over():
    """The silent failure this file's docstring describes: a local symbol
    nothing resolves is reported as an inlined helper and its words are never
    compared. When the symbol spells an address that is a wrong claim about
    the executable, not a helper, whatever its binding."""
    note, fatal = M.unresolved_reason("fn_80243A34", 0)
    assert fatal and "no function starts" in note
    note, fatal = M.unresolved_reason("fn_80243A34", 1)
    assert fatal


def test_an_inlined_local_is_skipped_but_counted():
    note, fatal = M.unresolved_reason("compare_entries", 0)
    assert not fatal and "inlined" in note


def test_an_unresolved_global_is_an_error():
    note, fatal = M.unresolved_reason("ARQFlush", 1)
    assert fatal and "not in the inventory" in note
