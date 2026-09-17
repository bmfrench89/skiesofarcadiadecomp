"""Tests for the checks CI runs over the C (tools/citest/).

Those three scripts need MSVC and are the one part of tools/ that cannot run
on the ubuntu leg of the matrix, so what is testable here is what they claim
rather than what they compile: that no runtime file has quietly fallen out of
the compile check, that the driver's report cannot disagree with the list of
routines it ran, and that the copy of the render recipe in
tools/citest/render_driver.c is still the one runtime/selftest.c runs inside
the port. All of that is text, and needs no compiler and no disc.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CITEST = ROOT / "tools" / "citest"


def load(name):
    spec = importlib.util.spec_from_file_location(name, CITEST / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


compile_runtime = load("compile_runtime")


def test_every_runtime_file_is_compiled_or_named_as_not_compiled():
    """UNCOVERED is an escape hatch: a name added to it turns a failing file
    into a silent one. It stays honest only if every entry is a real file with
    a reason, and every file that is not in it gets compiled."""
    sources = {p.name for p in (ROOT / "runtime").glob("*.c")}
    assert sources, "no runtime sources found; the check would pass vacuously"
    for name, why in compile_runtime.UNCOVERED.items():
        assert name in sources, f"UNCOVERED names {name}, which is not a runtime file"
        assert why.strip(), f"{name} is excluded without a reason"
    assert sources - set(compile_runtime.UNCOVERED), "every runtime file excluded at once"


def test_a_call_to_a_function_that_does_not_exist_is_an_error_there():
    """Nothing in that job links, so C4013 -- "assuming extern returning int"
    -- is the only sign a caller was left behind by a rename. As a warning it
    would be green."""
    assert "/we4013" in compile_runtime.STRICT
    # and the real build's flags are not touched: this check may be stricter
    # than the build, never different from it.
    sys.path.insert(0, str(ROOT / "tools"))
    from soa import toolchain

    assert not set(compile_runtime.STRICT) & set(toolchain.CFLAGS)


def test_the_driver_reports_the_routines_it_actually_runs():
    """The count used to be the literal 9 in two format strings; PLAN F3 takes
    the decompiled MSL routines past nine in an evening."""
    text = (CITEST / "dc_driver.c").read_text(encoding="utf-8")
    declared = set(re.findall(r"\b(dc_\w+)\(", text.split("#define ITER")[0]))
    tabled = {"dc_" + name for name in re.findall(r'\{"(\w+)", test_\w+\}', text)}
    assert declared == tabled, "the routine table and the declarations disagree"
    assert re.search(r"of %u routines", text), "the count must come from the table"


def test_the_native_job_needs_no_pip_install():
    """tools/citest/dc_check.py imports recompile.py for one helper, and the
    CI job that runs it installs nothing. That works only while the
    recompiler's import graph stays inside the standard library -- a fact
    nothing else in the tree records, and the first third-party import
    anywhere in it would break a job that has nothing to do with it."""
    probe = (
        "import sys, json;"
        f"sys.path.insert(0, {str(ROOT / 'tools')!r});"
        "import recompile;"
        "print(json.dumps([getattr(m, '__file__', '') or '' for m in list(sys.modules.values())]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=ROOT
    )
    outside = [f for f in json.loads(out.stdout) if "site-packages" in f.replace("\\", "/")]
    assert not outside, f"importing recompile.py now pulls in {outside}"


def test_the_render_driver_still_runs_the_ports_own_checks():
    """tools/citest/render_driver.c carries a verbatim copy of the render
    recipe in runtime/selftest.c, because the original is static in a file
    that cannot link outside the port. A copy that drifts is a CI check of
    something the port no longer does."""
    driver = (CITEST / "render_driver.c").read_text(encoding="utf-8")
    original = (ROOT / "runtime" / "selftest.c").read_text(encoding="utf-8")
    copied = driver.split("BEGIN COPY")[1].split("\n", 1)[1].split("/* ---- END COPY")[0]
    assert copied.strip(), "the markers are there but the block between them is empty"
    assert copied.strip() in original, (
        "the copy in tools/citest/render_driver.c no longer matches runtime/selftest.c; "
        "update it so CI checks what the port checks"
    )
    assert "render full-screen quad" in copied and "render triangle rows" in copied
