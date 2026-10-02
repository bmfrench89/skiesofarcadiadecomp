"""The arithmetic in tools/citest/libm_check.py (portability L6), no compiler run.

The C driver does the 3.2 billion evaluations; what is checked here is the
part that decides whether an output is right where the driver cannot: the
50-digit value, its rounding to a float, the slicing every leg's hash
depends on, and the pinned file.
"""

import math
import struct
import sys
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "citest"))

import libm_check as L  # noqa: E402


def bits(f: float) -> int:
    return struct.unpack("<I", struct.pack("<f", f))[0]


def test_the_slices_cover_each_domain_once_in_order():
    """Every leg hashes the same 64 slices in the same order, or no two legs
    could print the same hash."""
    for fn, (first, last, _) in L.DOMAINS.items():
        s = L.slices(first, last)
        assert len(s) == L.SLICES, fn
        assert s[0][0] == first and s[-1][1] == last, fn
        assert all(a[1] + 1 == b[0] for a, b in zip(s, s[1:], strict=False)), fn
        assert sum(hi - lo + 1 for lo, hi in s) == last - first + 1, fn


def test_the_domains_are_the_renderers():
    """2.5's counts: every float in [-8, 0] for fog's exp2f, every positive
    finite float for LOD's log2f."""
    counts = {fn: last - first + 1 for fn, (first, last, _) in L.DOMAINS.items()}
    assert counts == {"exp2f": 1_090_519_041, "log2f": 2_139_095_039}


def test_exact_values_round_to_themselves():
    assert L.round_f32(L.exact("exp2f", -1.0)) == bits(0.5)
    assert L.round_f32(L.exact("exp2f", -8.0)) == bits(1 / 256)
    assert L.round_f32(L.exact("log2f", 8.0)) == bits(3.0)
    assert L.round_f32(L.exact("log2f", 0.25)) == bits(-2.0)


def test_rounding_goes_to_the_nearer_float_and_ties_to_even():
    # 60 digits: the default context's 28 would round mid + 1e-30 back to mid
    with localcontext() as c:
        c.prec = 60
        one, up = Decimal(1.0), Decimal(L.f32(bits(1.0) + 1))
        mid = (one + up) / 2
        below, above = mid - Decimal("1e-30"), mid + Decimal("1e-30")
        odd_mid = (up + Decimal(L.f32(bits(1.0) + 2))) / 2
    assert L.round_f32(below) == bits(1.0)
    assert L.round_f32(above) == bits(1.0) + 1
    assert L.round_f32(mid) == bits(1.0), "a tie goes to the even mantissa"
    assert L.round_f32(odd_mid) == bits(1.0) + 2


def test_the_arbitration_is_needed():
    """At x = -0.029743773862719536 the double-precision exp2 rounds to the
    wrong float: the one input that put the 2.5 probe's UCRT count at 74,154
    where the true count is 74,153. Decimal gets it right, and it is one of
    the inputs CORE-MATH's exp2f handles by name."""
    x = L.f32(0xBCF3A937)
    right = L.round_f32(L.exact("exp2f", x))
    assert L.f32(right) == 0.9795942902565002
    assert bits(math.exp2(x)) != right


def test_the_pinned_file_names_both_functions_over_their_domains():
    pinned = L.read_pinned()
    assert set(pinned) == {"exp2f", "log2f"}
    for fn, (first, last, _) in L.DOMAINS.items():
        inputs, h = pinned[fn]
        assert inputs == last - first + 1
        assert len(h) == 16 and int(h, 16) >= 0


def test_fnv1a_is_the_drivers():
    """The C driver hashes four bytes an output, low byte first; this is the
    same function over the slice hashes, so the two have to agree on FNV-1a
    itself."""
    assert L.fnv1a(L.FNV_OFFSET, b"") == 0xCBF29CE484222325
    assert L.fnv1a(L.FNV_OFFSET, b"a") == 0xAF63DC4C8601EC8C
