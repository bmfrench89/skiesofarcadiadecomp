"""A mod's native library on every system (portability L9).

runtime/mod.c loads mod.dll on Windows and mod.so elsewhere through plat.h,
by its full path. This builds the real loader (mod.c and plat.c, with
test_mods.py's fake guest) and examples/mods/map-log as a shared library with
the toolchain profile SOA_CC names -- MSVC when it is unset, gcc on CI's Linux
legs -- and checks that the library loads, that the recording's config line
names it map-log@1.0, and, as the mutation, that a library exporting no
soa_mod_init is refused in the loader's own words (dlerror() off Windows).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).parent))

from soa import toolchain  # noqa: E402
from test_mods import DRIVER, SHA, fake_dol  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))
needs_cc = pytest.mark.skipif(
    toolchain.compiler_path(PROFILE) is None, reason=f"no {PROFILE.name} to build the loader"
)
LIB = "mod.dll" if os.name == "nt" or PROFILE.name == "mingw" else "mod.so"
SHARED = ["/LD"] if PROFILE.style == "msvc" else ["-shared", "-fPIC"]


def cc(args: list[str], cwd: Path) -> None:
    proc = toolchain.cc(args, cwd, PROFILE)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    out = tmp_path_factory.mktemp("loader")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    runtime = ROOT / "runtime"
    sources = [
        runtime / "mod.c",
        runtime / "sha1.c",
        runtime / "tick.c",
        *toolchain.runtime_support_sources(),
        out / "driver.c",
    ]
    cc(
        [*PROFILE.cflags, "/c", "/I", str(runtime), *map(str, sources), "/Fo" + str(out) + os.sep],
        out,
    )
    exe = out / ("mods" + PROFILE.exeext)
    objs = [str(out / (s.stem + PROFILE.objext)) for s in sources]
    cc([*PROFILE.cflags, *objs, "/Fe" + str(exe), *PROFILE.linker], out)
    dol = out / "fake.dol"
    dol.write_bytes(fake_dol())
    return exe, dol


def library(folder: Path, source: Path) -> None:
    """`source` built as the mod's library in `folder`."""
    cc(
        [
            *PROFILE.cflags,
            *SHARED,
            "/I",
            str(ROOT / "runtime"),
            str(source),
            "/Fe" + str(folder / LIB),
        ],
        folder,
    )


def map_log(root: Path, source: Path | None = None) -> Path:
    d = root / "map-log"
    d.mkdir(parents=True)
    ini = (ROOT / "examples" / "mods" / "map-log" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, source or ROOT / "examples" / "mods" / "map-log" / "mod.c")
    return d


def play(driver, mods: Path, script: str, extra: dict[str, str] | None = None) -> tuple[str, str]:
    exe, dol = driver
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env.update(extra or {})
    proc = subprocess.run(
        [str(exe), str(mods), str(dol)],
        input=script,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, proc.stderr


@needs_cc
def test_the_example_library_loads_and_the_recording_names_it(driver, tmp_path):
    map_log(tmp_path)
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 1" in out, err
    assert f"and {LIB}" in err and "[mod] map-log: map-log loaded" in err, err
    assert "describe [mods=map-log@1.0:" in out, out


# What each shipped mod says when its switch is on (portability L10). The
# switch comes from the environment: GetEnvironmentVariableA on Windows,
# getenv elsewhere, where all three once called the first alone and never
# compiled -- unnoticed until L10 built them, since only map-log was built here.
SWITCHED = {
    "autotext": ("SOA_AUTOTEXT", "on", "a complete page turns itself after 45 frames"),
    "coop": ("SOA_COOP", "1", "pad 2 chooses the commands of party slot(s) 1"),
    "encounter-rate": ("SOA_ENCOUNTERS", "half", "random battles half in the field"),
}


def test_every_shipped_mod_has_a_switch_to_check():
    assert sorted(p.parent.name for p in (ROOT / "mods").glob("*/mod.c")) == sorted(SWITCHED)


@needs_cc
@pytest.mark.parametrize("name", sorted(SWITCHED))
def test_every_shipped_mod_builds_here_loads_and_reads_its_switch(driver, tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    ini = (ROOT / "mods" / name / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "mods" / name / "mod.c")
    var, value, says = SWITCHED[name]
    out, err = play(driver, tmp_path, "", {var: value})
    assert "loaded 1" in out and f"and {LIB}" in err, err
    assert f"[mod] {name}: {says}" in err, err


@needs_cc
def test_a_library_without_soa_mod_init_is_refused_in_the_loaders_words(driver, tmp_path):
    src = tmp_path / "no_init.c"
    src.write_text(
        '#include "soa_mod.h"\nSOA_MOD_EXPORT int not_the_init(void) { return 0; }\n',
        encoding="utf-8",
    )
    map_log(tmp_path / "mods", src)
    out, err = play(driver, tmp_path / "mods", "")
    assert "loaded 0" in out, err
    line = next(ln for ln in err.splitlines() if "exports no soa_mod_init" in ln)
    # the loader's own reason, after the refusal: dlerror()'s, or Windows' error
    assert "soa_mod_init (" in line and (
        "error 127" in line or "soa_mod_init" in line.split("(", 1)[1]
    ), line
