"""The player's build (specs/distribution.md R2).

A player's package holds no src/ or include/ (3.1), so its build leaves out
what uses them: recompile.py --no-decomp drops every binding runtime/
decomp_swap.c answers with decompiled code -- the game's own MSL then runs
translated -- builds no native unit, and links with SOA_NO_DECOMP, which
empties decomp_swap.c and has the self test say its comparison is skipped.
The bindings decomp_swap.c answers must be exactly the ones config/hle.txt
notes as decompiled, so neither can grow without the other.
"""

import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import player_build  # noqa: E402
import recompile  # noqa: E402
from soa import discfixture, toolchain  # noqa: E402
from soa.hle import load_hle  # noqa: E402


def noted_as_decompiled() -> set[int]:
    """hle.txt's entries whose note names a file under src/."""
    out = set()
    for line in (ROOT / "config" / "hle.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(0x[0-9A-Fa-f]{8})\s+\S+\s*#\s*src/", line)
        if m:
            out.add(int(m.group(1), 16))
    return out


def test_the_swapped_bindings_are_the_ones_hle_txt_notes_as_decompiled():
    swapped = recompile.decomp_bound()
    assert len(swapped) == 12
    assert swapped == noted_as_decompiled()
    assert swapped <= set(load_hle(ROOT / "config" / "hle.txt"))


def test_an_adapter_added_without_its_note_is_seen(tmp_path):
    swap = tmp_path / "decomp_swap.c"
    text = (ROOT / "runtime" / "decomp_swap.c").read_text(encoding="utf-8")
    swap.write_text(text + "\nvoid fn_80001234(CpuState* s) { (void)s; }\n", encoding="utf-8")
    assert recompile.decomp_bound(swap) != noted_as_decompiled()


def test_the_no_decomp_link_builds_no_native_unit_and_defines_soa_no_decomp():
    for p in (toolchain.MSVC, toolchain.MINGW):
        plain = recompile.link_plan(p, Path(p.out), ["src/sdk/msl/mem.c"], ["/Dmemset=dc_memset"])
        assert any("src/sdk/msl/mem.c" in cmd for cmd, _ in plain)
        player = recompile.link_plan(p, Path(p.out), [], [], defines=("/DSOA_NO_DECOMP=1",))
        link = next(cmd for cmd, cwd in player if cwd == Path("."))
        assert "/DSOA_NO_DECOMP=1" in link
        assert not any("src/" in a for cmd, _ in player for a in cmd)


def test_the_runtime_keeps_a_no_decomp_branch_where_it_names_decompiled_code():
    """decomp_swap.c is empty and the self test names its skip under
    SOA_NO_DECOMP; the twins it calls are then the plain fn_ names."""
    swap = (ROOT / "runtime" / "decomp_swap.c").read_text(encoding="utf-8")
    assert "#ifndef SOA_NO_DECOMP" in swap
    selftest = (ROOT / "runtime" / "selftest.c").read_text(encoding="utf-8")
    for addr in recompile.decomp_bound():
        assert f"#define recomp_fn_{addr:08X} fn_{addr:08X}" in selftest
    assert "a build without src/: the translated MSL runs" in selftest


# ---- tools/player_build.py: the disc's checks, never a stale gen/, and RVZ ----

EMBED = ROOT / "vendor" / "python-3.14.8-embed-amd64.zip"


@pytest.fixture(scope="module")
def fixture_disc(tmp_path_factory):
    return discfixture.build(tmp_path_factory.mktemp("disc") / "disc.iso")


def test_a_disc_of_another_game_is_refused_by_name(fixture_disc):
    with pytest.raises(
        player_build.Refused, match="not the North American GameCube release.*GTSE01"
    ):
        player_build.check_disc(fixture_disc.path, dol_sha1=fixture_disc.dol_sha1)


def test_an_executable_with_another_sha1_is_refused(fixture_disc):
    game = fixture_disc.game_id
    player_build.check_disc(fixture_disc.path, game_id=game, dol_sha1=fixture_disc.dol_sha1)
    with pytest.raises(
        player_build.Refused, match="executable is not the one this package was made"
    ):
        player_build.check_disc(fixture_disc.path, game_id=game, dol_sha1="0" * 40)


def test_an_image_that_is_not_a_disc_is_refused(tmp_path):
    junk = tmp_path / "holiday.iso"
    junk.write_bytes(bytes(range(256)) * 64)
    with pytest.raises(player_build.Refused, match="is not a GameCube disc image"):
        player_build.check_disc(junk, dol_sha1="0" * 40)


def test_a_disc_this_cannot_check_is_refused_not_warned(fixture_disc, monkeypatch, tmp_path):
    monkeypatch.setattr(player_build, "SOURCE", tmp_path)  # no config/ to read the hash from
    with pytest.raises(player_build.Refused, match="cannot check the disc's executable"):
        player_build.check_disc(fixture_disc.path, game_id=fixture_disc.game_id)


def test_a_refusal_is_a_build_line_and_exit_2(fixture_disc, tmp_path, capsys):
    assert player_build.main(["--disc", str(fixture_disc.path), "--root", str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert "[build] check" in out and "[build] refused: this is not the North American" in out
    assert not (tmp_path / "extracted").exists()


def run_main(monkeypatch, root, source, *extra):
    """player_build.main with the disc's checks, extraction and the build
    itself stood in for: whether it asks the build to translate again."""
    asked = []
    monkeypatch.setattr(player_build, "SOURCE", source)
    monkeypatch.setattr(player_build, "check_disc", lambda image: None)
    monkeypatch.setattr(player_build, "extract", lambda image, out: None)
    monkeypatch.setattr(player_build, "install", lambda root, gen: "0" * 64)

    def build(root_, gen, retranslate):
        asked.append(retranslate)
        return 0

    monkeypatch.setattr(player_build, "build", build)
    assert player_build.main(["--disc", "x.iso", "--root", str(root), *extra]) == 0
    return asked[0]


def test_a_changed_input_retranslates_and_an_unchanged_one_relinks(monkeypatch, tmp_path, capsys):
    source = tmp_path / "source"
    for rel in player_build.BAKED:
        p = source / (rel if "." in Path(rel).name else rel + "/x.py")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel, encoding="utf-8")
    root = tmp_path / "root"
    assert run_main(monkeypatch, root, source) is True  # no record: a first build
    assert "no record of the last translation" in capsys.readouterr().out
    assert run_main(monkeypatch, root, source) is False  # nothing moved: relink
    (source / "runtime" / "cpu.h").write_text("runtime/cpu.h, one byte on", encoding="utf-8")
    assert run_main(monkeypatch, root, source) is True
    assert "[build] translate: runtime/cpu.h" in capsys.readouterr().out
    # the mutation: without the check a changed cpu.h would only relink
    monkeypatch.setattr(player_build, "stale", lambda gen, now: [])
    (source / "runtime" / "cpu.h").write_text("runtime/cpu.h, two bytes on", encoding="utf-8")
    assert run_main(monkeypatch, root, source) is False


def test_setups_rebuild_translates_again_when_nothing_moved(monkeypatch, tmp_path, capsys):
    source = tmp_path / "source"
    (source / "runtime").mkdir(parents=True)
    (source / "runtime" / "cpu.h").write_text("cpu.h", encoding="utf-8")
    root = tmp_path / "root"
    assert run_main(monkeypatch, root, source) is True
    assert run_main(monkeypatch, root, source) is False  # the record matches
    capsys.readouterr()
    assert run_main(monkeypatch, root, source, "--rebuild") is True  # 3.8: Rebuild retranslates
    assert "[build] translate: Rebuild asked for" in capsys.readouterr().out


def test_the_baked_digest_reads_crlf_as_lf(tmp_path):
    """R5-0: a checkout's line endings are not the commit's -- GitHub's
    Windows runner checks out with core.autocrlf on -- and baked= is made of
    this record, so the same files with CRLF endings make the same record,
    while a changed line still moves it."""
    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    for rel in player_build.BAKED:
        name = rel if "." in Path(rel).name else rel + "/x.py"
        text = f"{rel}\none\ntwo\n".encode()
        for tree, data in ((lf, text), (crlf, text.replace(b"\n", b"\r\n"))):
            (tree / name).parent.mkdir(parents=True, exist_ok=True)
            (tree / name).write_bytes(data)
    assert player_build.inputs_record(lf) == player_build.inputs_record(crlf)
    (crlf / "runtime" / "cpu.h").write_bytes(b"runtime/cpu.h\r\none\r\nthree\r\n")
    assert player_build.inputs_record(lf) != player_build.inputs_record(crlf)


def test_an_rvz_reads_back_as_the_disc(fixture_disc, tmp_path):
    from soa.disc import Disc
    from soa.rvz import RVZ

    discfixture.write_rvz(fixture_disc.image, tmp_path / "disc.rvz")
    assert RVZ(str(tmp_path / "disc.rvz")).read(0, len(fixture_disc.image)) == fixture_disc.image
    with Disc(player_build.open_image(tmp_path / "disc.rvz")) as disc:
        assert disc.boot.game_id == fixture_disc.game_id


RVZ_SCRIPT = """
import sys, tempfile
from pathlib import Path
sys.path.insert(0, {tools!r})
from soa import discfixture
from soa.rvz import RVZ
d = Path(tempfile.mkdtemp())
fx = discfixture.build(d / "disc.iso")
discfixture.write_rvz(fx.image, d / "disc.rvz")
assert RVZ(str(d / "disc.rvz")).read(0, len(fx.image)) == fx.image
print("rvz ok")
"""


def test_the_embedded_python_reads_an_rvz_and_needs_its_zstd(tmp_path):
    """3.5: the package's python/ carries compression.zstd, which the RVZ
    reader needs; the same run with _zstd.pyd taken out fails."""
    if not EMBED.exists():
        pytest.skip(f"no {EMBED.name} in vendor/ (python tools/package.py stage fetches it)")
    with zipfile.ZipFile(EMBED) as z:
        z.extractall(tmp_path / "python")
    exe = tmp_path / "python" / "python.exe"
    script = RVZ_SCRIPT.format(tools=str(ROOT / "tools"))
    ok = subprocess.run([str(exe), "-c", script], capture_output=True, text=True, check=False)
    assert ok.returncode == 0 and "rvz ok" in ok.stdout, ok.stderr
    (tmp_path / "python" / "_zstd.pyd").unlink()
    gone = subprocess.run([str(exe), "-c", script], capture_output=True, text=True, check=False)
    assert gone.returncode != 0 and "zstd" in gone.stderr
