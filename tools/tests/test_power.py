"""runtime/power.c: the power line in every run report (H20, docs/specs/power-line.md).

power_line is a pure function of a reading at the start, one at the report and
the frames drawn between them; this builds power.c with a driver that feeds it
each case the spec names and prints the lines. The readings themselves are
plat.c's, checked on this PC against powercfg (FINDINGS "H20").
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))

# (known, ac, battery, percent, mwh, plan, mode) at the start and the report, frames
AC = (1, 1, 1, 79, 54080, "Turbo", "best performance")
CASES = [
    ("ac", AC, AC, 1000),
    (
        "battery",
        (1, 0, 1, 64, 40000, "Balanced", "best power efficiency"),
        (1, 0, 1, 58, 35790, "Balanced", "best power efficiency"),
        36000,
    ),
    ("changed", AC, (1, 0, 1, 79, 54000, "Turbo", "balanced"), 500),
    ("rose", (1, 0, 1, 50, 30000, "", ""), (1, 0, 1, 51, 30100, "", ""), 900),
    (
        "none",
        (1, 1, 0, -1, -1, "High performance", ""),
        (1, 1, 0, -1, -1, "High performance", ""),
        10,
    ),
    ("unknown", (0, -1, -1, -1, -1, "", ""), (0, -1, -1, -1, -1, "", ""), 10),
]
WANT = {
    "ac": "[power] AC, battery 79%, plan Turbo, mode best performance",
    "battery": "[power] battery 64% -> 58%, plan Balanced, mode best power efficiency; "
    "4210 mWh over 36000 frames, 116 mWh a 1000",
    "changed": "[power] AC at the start, battery at the report: no energy figure for a run that changed source",
    "rose": "[power] battery 50% -> 51%, plan -, mode -; the battery reads 100 mWh more than at the start, "
    "so no energy figure",
    "none": "[power] AC, no battery, plan High performance, mode -",
    "unknown": "[power] not known on this system",
}


def reading(r) -> str:
    known, ac, battery, percent, mwh, plan, mode = r
    return f'{{{known}, {ac}, {battery}, {percent}, {mwh}LL, "{plan}", "{mode}"}}'


def driver_source() -> str:
    rows = ",\n".join(f'    {{"{n}", {reading(a)}, {reading(b)}, {f}u}}' for n, a, b, f in CASES)
    return f"""
#include "power.h"
#include <stdio.h>
int plat_power_read(PlatPower* p) {{ (void)p; return 0; }}
unsigned gx_frame_count(void) {{ return 0; }}
static const struct {{ const char* name; PlatPower a, b; unsigned frames; }} k[] = {{
{rows}
}};
int main(void)
{{
    unsigned i;
    char line[256];
    for (i = 0; i < sizeof k / sizeof k[0]; i++) {{
        power_line(&k[i].a, &k[i].b, k[i].frames, line, sizeof line);
        printf("%s|%s\\n", k[i].name, line);
    }}
    return 0;
}}
"""


@pytest.fixture(scope="module")
def lines(tmp_path_factory):
    if toolchain.compiler_path(PROFILE) is None:
        pytest.skip(f"no {PROFILE.name}")
    out = tmp_path_factory.mktemp("power")
    (out / "driver.c").write_text(driver_source(), encoding="utf-8")
    exe = out / ("power" + PROFILE.exeext)
    proc = toolchain.cc(
        [
            *PROFILE.cflags,
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "runtime" / "power.c"),
            str(out / "driver.c"),
            "/Fe" + str(exe),
        ],
        out,
        PROFILE,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60, check=True)
    return dict(line.split("|", 1) for line in run.stdout.splitlines())


@pytest.mark.parametrize("case", [c[0] for c in CASES])
def test_the_power_line_for_each_reading(lines, case):
    """Each case the spec names. The mutation, the energy taken end minus
    start, fails `battery` (and turns `rose` into a figure)."""
    assert lines[case] == WANT[case]


def test_every_run_registers_it():
    """main.c reads the power at the start and hangs the line on the report."""
    main = (ROOT / "runtime" / "main.c").read_text(encoding="utf-8")
    assert "power_start();" in main and "hle_on_report(power_report);" in main
