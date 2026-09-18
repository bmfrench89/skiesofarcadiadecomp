"""What it takes for a decompiled unit to run natively, checked by building it.

config/GEAE8P/units.txt marks a unit ``native`` when it can be compiled for the
host as a twin of the recompiled code. The bar is four things: it compiles
under MSVC, it reads nothing whose meaning depends on byte order, it touches no
memory-mapped register, and it calls nothing undecompiled. The first is a
compile, the second is behaviour, and neither is visible in the object that
matches the executable -- which is why both of the defects these tests were
written for sat in units that had matched for weeks.

``__fill_mem`` walked its pointer by assigning to a cast. Metrowerks offers
that as an extension and so, by default, does MSVC, so the unit built and
nothing said otherwise; any conformance mode rejects it. ``strcmp`` compares
two words loaded out of the strings, which is the comparison of the strings on
the big-endian target and the comparison of their last characters first on the
host, so the native twin returned the wrong sign for most inputs while the
object still matched word for word.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa import toolchain  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "config" / "GEAE8P" / "units.txt"

needs_msvc = pytest.mark.skipif(
    toolchain.cl_path() is None, reason="no MSVC: the native twins cannot be built here"
)

# The units behind the adapters in runtime/decomp_swap.c. Named here rather
# than read out of units.txt because this file is about what decomp_swap.c
# calls: an adapter and the `native` flag on its unit land in separate files,
# and the test has to hold while one of them is ahead of the other.
SWAPPED_IN = [
    "src/sdk/msl/string.c",
    "src/sdk/msl/mem.c",
    "src/sdk/msl/fillmem.c",
    "src/sdk/msl/strcpy.c",
    "src/sdk/msl/strcmp.c",
    "src/sdk/msl/strstr.c",
]

_DEFINES_OR_DECLARES = re.compile(
    r"^(?!typedef\b)[A-Za-z_][^\n;{}=]*?\b(\w+)\s*\([^;{}]*\)\s*(?:\n\{|;)", re.M
)


def renames(sources: list[str]) -> list[str]:
    """The /D flags tools/recompile.py builds these units with."""
    names: set[str] = set()
    for src in sources:
        names.update(_DEFINES_OR_DECLARES.findall((ROOT / src).read_text(encoding="utf-8")))
    return [f"/D{n}=dc_{n}" for n in sorted(names)]


def native_units() -> list[str]:
    rows = []
    for line in UNITS.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        listed = line.strip() and not line.startswith("#") and len(cols) >= 4
        if listed and cols[3].strip() == "native":
            rows.append(cols[0])
    return rows


# --------------------------------------------------------------------------
# no compiler extensions
# --------------------------------------------------------------------------


@needs_msvc
@pytest.mark.parametrize("src", sorted(set(native_units()) | set(SWAPPED_IN)))
def test_a_native_unit_holds_no_compiler_extension(src, tmp_path):
    """/Za is MSVC's conformance mode and rejects the assignment-to-a-cast that
    kept __fill_mem stubbed. /std and /Za are mutually exclusive, so the
    standard version goes and the rest of the flags stay."""
    flags = [f for f in toolchain.CFLAGS if not f.startswith("/std")]
    proc = toolchain.cl(
        [*flags, "/Za", "/c", "/Iinclude", *renames([src]), "/Fo" + str(tmp_path) + os.sep, src],
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# the same answers as the host's own C library
# --------------------------------------------------------------------------

DRIVER = r"""
/* Call the adapters the way dispatch() does and compare with the host's
   library. The strings are chosen so that several pairs decide in the word
   loop rather than bytewise, which is the path that was inverted. */
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void fn_8025F120(CpuState* s); /* strcpy */
void fn_8025EF88(CpuState* s); /* strcmp */
void fn_8025ED74(CpuState* s); /* strstr */
void fn_80005434(CpuState* s); /* memset, over __fill_mem */

#define BASE 0x80100000u

static CpuState st;

static uint32_t put(uint32_t ea, const char* text)
{
    memcpy(mem_ptr(&st, ea), text, strlen(text) + 1);
    return ea;
}

static int sgn(int v) { return v < 0 ? -1 : (v > 0 ? 1 : 0); }

int main(void)
{
    static const char* words[] = {"", "a", "ab", "abcde", "azzz", "abcdefgh", "abcdefgi",
        "hello world", "hello worle", "hello worlds", "\x80z", "\x01z", "the quick brown fox"};
    const int nw = (int)(sizeof words / sizeof *words);
    int i, j, oa, ob, bad = 0;

    st.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    if (!st.mem) return 2;

    for (i = 0; i < nw; i++)
        for (j = 0; j < nw; j++)
            for (oa = 0; oa < 4; oa++)
                for (ob = 0; ob < 4; ob++) {
                    uint32_t a = put(BASE + 0x100 + (uint32_t)oa, words[i]);
                    uint32_t b = put(BASE + 0x200 + (uint32_t)ob, words[j]);

                    st.gpr[3] = a;
                    st.gpr[4] = b;
                    fn_8025EF88(&st);
                    if (sgn((int)st.gpr[3]) != sgn(strcmp(words[i], words[j]))) {
                        printf("strcmp: '%s' vs '%s' gave %d\n", words[i], words[j],
                            (int)st.gpr[3]);
                        bad = 1;
                    }
                    if (st.pc != 0x8025EF88u) {
                        printf("strcmp: pc not stamped\n");
                        bad = 1;
                    }

                    memset(mem_ptr(&st, BASE + 0x300), 0x5A, 64);
                    st.gpr[3] = BASE + 0x300 + (uint32_t)ob;
                    st.gpr[4] = a;
                    fn_8025F120(&st);
                    if (st.gpr[3] != BASE + 0x300 + (uint32_t)ob
                        || strcmp((const char*)mem_ptr(&st, st.gpr[3]), words[i]) != 0) {
                        printf("strcpy: '%s' to offset %d\n", words[i], ob);
                        bad = 1;
                    }

                    st.gpr[3] = a;
                    st.gpr[4] = b;
                    fn_8025ED74(&st);
                    {
                        const char* hit = strstr(words[i], words[j]);
                        uint32_t want = hit ? a + (uint32_t)(hit - words[i]) : 0u;
                        if (st.gpr[3] != want) {
                            printf("strstr: '%s' in '%s' gave %08X, wanted %08X\n", words[j],
                                words[i], st.gpr[3], want);
                            bad = 1;
                        }
                    }
                }

    /* The NULL the executable's strstr defends against: guest address 0 must
       not arrive as the first byte of MEM1. */
    {
        uint32_t a = put(BASE + 0x100, "abc");
        st.gpr[3] = a;
        st.gpr[4] = 0;
        fn_8025ED74(&st);
        if (st.gpr[3] != a) {
            printf("strstr: a NULL pattern gave %08X, wanted %08X\n", st.gpr[3], a);
            bad = 1;
        }
    }

    /* memset reaches __fill_mem, which is the unit that used to be stubbed;
       every length and alignment around its 32-byte threshold. */
    {
        static unsigned char want[512];
        int off, len;
        for (off = 0; off < 8; off++)
            for (len = 0; len < 200; len++) {
                memset(mem_ptr(&st, BASE + 0x400), 0x11, sizeof want);
                memset(want, 0x11, sizeof want);
                memset(want + 16 + off, 0xA5, (size_t)len);
                st.gpr[3] = BASE + 0x400 + 16 + (uint32_t)off;
                st.gpr[4] = 0xA5;
                st.gpr[5] = (uint32_t)len;
                fn_80005434(&st);
                if (memcmp(mem_ptr(&st, BASE + 0x400), want, sizeof want) != 0) {
                    printf("memset: offset %d length %d\n", off, len);
                    bad = 1;
                    off = 8;
                    break;
                }
            }
    }

    printf(bad ? "FAILED\n" : "agreed\n");
    return bad;
}
"""


@needs_msvc
def test_the_swapped_in_routines_agree_with_the_host_library(tmp_path):
    """Build what runtime/decomp_swap.c calls, then call the adapters the way
    dispatch() does. A wrong answer here is a routine the port would run in
    place of the game's own."""
    (tmp_path / "driver.c").write_text(DRIVER, encoding="utf-8")
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/c",
            "/Iinclude",
            *renames(SWAPPED_IN),
            "/Fo" + str(tmp_path) + os.sep,
            *SWAPPED_IN,
        ],
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/I" + str(ROOT / "runtime"),
            str(ROOT / "runtime" / "decomp_swap.c"),
            str(ROOT / "runtime" / "decomp_shims.c"),
            str(tmp_path / "driver.c"),
            *sorted(str(o) for o in tmp_path.glob("*.obj")),
            "/Fo" + str(tmp_path) + os.sep,
            "/Fe" + str(tmp_path / "twins.exe"),
        ],
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    run = subprocess.run(
        [str(tmp_path / "twins.exe")], capture_output=True, text=True, timeout=120, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "agreed" in run.stdout


# --------------------------------------------------------------------------
# the stub list and the decompiled units cannot both define a symbol
# --------------------------------------------------------------------------


def test_nothing_is_stubbed_that_a_unit_already_defines():
    """runtime/decomp_shims.c stands in for callees nobody has decompiled. A
    stub left behind after its unit went native is two definitions of the same
    dc_ symbol, and the native link is the only thing that would notice."""
    shims = (ROOT / "runtime" / "decomp_shims.c").read_text(encoding="utf-8")
    stubbed = {m[3:] for m in re.findall(r"^\w[\w \*]*?\b(dc_\w+)\s*\(", shims, re.M)}
    defined: set[str] = set()
    for src in ROOT.joinpath("src").rglob("*.c"):
        text = src.read_text(encoding="utf-8")
        defined.update(
            re.findall(r"^(?!typedef\b)[A-Za-z_][^\n;{}=]*?\b(\w+)\s*\([^;{}]*\)\s*\n\{", text)
        )
    assert stubbed & defined == set(), "a stub and a decompiled unit define the same function"
