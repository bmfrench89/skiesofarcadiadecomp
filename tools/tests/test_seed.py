"""runtime/seed.c: the race seed (PLAN-GAMEPLAY-MODS.md P6).

With SOA_SEED set, OSGetTick called from the three reseed sites -- a field
load (lr 0x801012B0) and the two at a battle start (0x8000A1D0 and
0x8000A1D8) -- returns MurmurHash3's finaliser over the seed, the site and
how many times the site has been reached, and every other timebase read is
left alone. seed.c is built alone here and held to an independent Python
implementation; the self test (seed_selftest) runs the game's own OSGetTick
and srand through it; and the sites themselves are checked in the
translated code, so a retranslation that moves one fails here rather than
leaving the seed quietly unpinned.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_memguard import needs_msvc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

SITES = (0x801012B0, 0x8000A1D0, 0x8000A1D8)
M = 0xFFFFFFFF


def fmix32(h: int) -> int:
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & M
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & M
    h ^= h >> 16
    return h


def pin(seed: int, site: int, n: int) -> int:
    return fmix32(seed ^ ((site + 1) * 0x9E3779B9 & M) ^ (n * 0x85EBCA6B & M))


DRIVER = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
uint32_t seed_value(uint32_t s, int site, uint32_t n);
uint32_t seed_pin(uint32_t lr, uint32_t tb);
void seed_set(int on, uint32_t seed);
int seed_init(void);
void seed_report(void);
int main(int argc, char** argv)
{
    static const uint32_t seeds[] = {0u, 1u, 0xFFFFFFFFu};
    static const uint32_t sites[] = {0x801012B0u, 0x8000A1D0u, 0x8000A1D8u};
    unsigned i, k, n;
    if (argc > 1 && !strcmp(argv[1], "init")) {
        int on = seed_init();
        printf("init %d\n", on);
        seed_report();
        return 0;
    }
    for (i = 0; i < 3; i++)
        for (k = 0; k < 3; k++)
            for (n = 0; n < 4; n++) printf("value %u %u %u %08X\n", seeds[i], k, n, seed_value(seeds[i], (int)k, n));
    seed_set(1, 777u);
    for (n = 0; n < 3; n++)
        for (k = 0; k < 3; k++) printf("pin %08X %08X\n", sites[k], seed_pin(sites[k], 0xDEAD0000u + n));
    printf("pin %08X %08X\n", 0x8000A1DCu, seed_pin(0x8000A1DCu, 0x12345678u));
    printf("pin %08X %08X\n", 0x801012ACu, seed_pin(0x801012ACu, 0x0BADF00Du));
    seed_report();
    return 0;
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    from soa import toolchain

    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    out = tmp_path_factory.mktemp("seed")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = out / "seed.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            str(ROOT / "runtime" / "seed.c"),
            str(out / "driver.c"),
            "/Fo" + str(out) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=out,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


def run(exe, *args, **env_set):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env.update(env_set)
    proc = subprocess.run(
        [str(exe), *args], capture_output=True, text=True, env=env, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, proc.stderr


@needs_msvc
def test_the_values_are_the_finaliser_over_seed_site_and_count(driver):
    out, _ = run(driver)
    rows = re.findall(r"value (\d+) (\d) (\d) ([0-9A-F]{8})", out)
    assert len(rows) == 36, out
    for seed, site, n, got in rows:
        assert int(got, 16) == pin(int(seed), int(site), int(n)), (seed, site, n, got)


@needs_msvc
def test_only_the_three_sites_are_pinned_and_each_counts_its_own_calls(driver):
    out, err = run(driver)
    got = re.findall(r"pin ([0-9A-F]{8}) ([0-9A-F]{8})", out)
    for i, (lr, v) in enumerate(got[:9]):
        n, site = divmod(i, 3)
        assert int(lr, 16) == SITES[site] and int(v, 16) == pin(777, site, n), (i, lr, v)
    # one instruction past a site, and the instruction before one, are clocks
    assert got[9] == ("8000A1DC", "12345678") and got[10] == ("801012AC", "0BADF00D"), got
    assert "field load 3, battle start 3 and 3 pinned; 2 other OSGetTick reads left alone" in err, (
        err
    )


@needs_msvc
@pytest.mark.parametrize(
    "value, on",
    [
        ("12345", 1),
        ("0x3039", 1),
        ("0XFFFFFFFF", 1),
        ("4294967295", 1),
        ("4294967296", 0),
        ("-1", 0),
        ("12x", 0),
        ("0x", 0),
        ("0x123456789", 0),
        (" 1", 0),
        ("", 0),
    ],
)
def test_soa_seed_is_a_32_bit_number_or_refused(driver, value, on):
    out, err = run(driver, "init", SOA_SEED=value)
    assert f"init {on}" in out, (out, err)
    if value and not on:
        assert "is not a 32-bit number" in err, err


def test_the_sites_are_where_the_translated_code_calls_osgettick():
    """Each site is `s->lr = <site>u; fn_8023851C(s);` exactly once in gen/,
    and the next call is srand (fn_8025ECBC): a retranslation that moves a
    site fails here instead of leaving that reseed unpinned."""
    chunks = sorted((ROOT / "gen").glob("chunk_*.c"))
    if not chunks:
        pytest.skip("no gen/: the translated code is built, not committed")
    for site in SITES:
        want = f"s->lr = 0x{site:08X}u; fn_8023851C(s);"
        hits = [(c, t.index(want)) for c in chunks if want in (t := c.read_text(errors="replace"))]
        assert len(hits) == 1, (hex(site), [str(c) for c, _ in hits])
        chunk, at = hits[0]
        after = chunk.read_text(errors="replace")[at + len(want) :]
        nxt = re.search(r"fn_[0-9A-F]{8}\(s\);", after)
        assert nxt and nxt.group(0) == "fn_8025ECBC(s);", (hex(site), nxt and nxt.group(0))
