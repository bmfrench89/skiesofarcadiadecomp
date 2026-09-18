"""Does the tree notice a dump that is not the build config/ describes?

    python -m pytest tools/tests/test_dump.py

Every fixture here is synthesised: a two-line config.yml, a handful of bytes
standing in for the executable, and a 0x440-byte disc header built field by
field. No disc, no dump, no `extracted/`, no compiler -- so this runs in CI on
Linux exactly as it runs on the owner's machine.

The point of the checks, in the order they matter:

  * a mutated executable is refused, and the message names BOTH hashes. That
    is the whole feature: a message saying only "wrong dump" leaves the reader
    with nothing to compare, and the first thing anyone does with this failure
    is paste the pair into a search box.
  * the expected hash is read out of config.yml rather than written down
    again here, so the check cannot drift away from the file dtk verifies.
  * a config.yml this cannot read raises rather than passing. The failure
    mode a hash check has to avoid is agreeing with everything, and the two
    ways to get there are an unreadable config and a hash that is not a sha1
    (a sha256 pasted in, a truncated copy), so both are refused loudly.
  * tools/extract.py's own call is exercised through check_build(), which is
    the integration the README's first command depends on -- and which cannot
    be tested end to end anywhere, here or in CI, because extract.py's other
    input is a disc image.

The one thing not synthesised is the repository's real config/GEAE8P/config.yml,
which is metadata the repository carries and no part of the game.
"""

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import extract as EX  # noqa: E402
from soa.dump import DEFAULT_CONFIG, ProjectError, read_project, sha1_file, verify  # noqa: E402

# sha1 of b"not the game", computed the long way round in test_the_fixture_is_honest.
DECOY = "5057341f5f197225d126af2d3b9e9f852583566d"
REAL = "8c0e278126fa3b0173400fdb632038172743cc13"  # the DOL config.yml names


def write_config(tmp_path: Path, *, sha1: str = REAL, obj: str = "extracted/sys/main.dol") -> Path:
    path = tmp_path / "config.yml"
    path.write_text(
        "# decomp-toolkit project configuration.\n"
        f"object: {obj}\n"
        f"hash: {sha1}\n"
        "symbols: config/GEAE8P/symbols.txt\n"
        "splits: config/GEAE8P/splits.txt\n"
        "mw_comment_version: 8\n",
        encoding="utf-8",
    )
    return path


def write_dol(tmp_path: Path, data: bytes) -> Path:
    """A stand-in executable at the layout an extraction produces."""
    sys_dir = tmp_path / "extracted" / "sys"
    sys_dir.mkdir(parents=True, exist_ok=True)
    dol = sys_dir / "main.dol"
    dol.write_bytes(data)
    return dol


def write_boot(tmp_path: Path, game_id: bytes = b"GEAE8P", version: int = 0) -> Path:
    """A 0x440-byte disc header, the four fields describe_disc() reads."""
    header = bytearray(0x440)
    header[0x00:0x06] = game_id
    header[0x06] = 0  # disc number
    header[0x07] = version
    header[0x1C:0x20] = struct.pack(">I", 0xC2339F3D)
    header[0x20:0x2C] = b"Test Title\0\0"
    path = tmp_path / "extracted" / "sys" / "boot.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header))
    return path


# --------------------------------------------------------------------------
# the fixture, and the hash of it
# --------------------------------------------------------------------------


def test_the_fixture_is_honest(tmp_path):
    """DECOY above is the sha1 of the bytes, not a number that happens to be
    40 hex digits: a test whose "wrong" hash is invented proves only that two
    unequal strings are unequal."""
    import hashlib

    assert hashlib.sha1(b"not the game", usedforsecurity=False).hexdigest() == DECOY
    digest, size = sha1_file(write_dol(tmp_path, b"not the game"))
    assert (digest, size) == (DECOY, 12)


def test_sha1_file_streams_more_than_one_chunk(tmp_path):
    """The DOL is 3 MB and a disc image is 1.3 GB; the loop has to survive a
    file longer than its buffer."""
    data = bytes(range(256)) * 400  # 102,400 bytes
    path = write_dol(tmp_path, data)
    assert sha1_file(path, chunk=1024) == sha1_file(path, chunk=1 << 20)
    assert sha1_file(path)[1] == len(data)


# --------------------------------------------------------------------------
# reading the project file
# --------------------------------------------------------------------------


def test_the_real_config_is_readable_and_names_a_sha1():
    """Not a copy of the value: whatever config/GEAE8P/config.yml says today
    is what the check compares against, so the two cannot drift apart."""
    project = read_project(DEFAULT_CONFIG)
    assert len(project.sha1) == 40
    assert project.object.as_posix() == "extracted/sys/main.dol"
    assert project.sha1 == REAL, "config.yml's hash moved; this test is the record of it"


def test_a_missing_config_is_an_error_not_a_pass(tmp_path):
    with pytest.raises(ProjectError, match="cannot be read"):
        read_project(tmp_path / "nope.yml")


def test_a_hash_that_is_not_a_sha1_is_refused(tmp_path):
    """A sha256 pasted in would refuse every dump including the right one,
    which reads exactly like a bad dump. Say which file is wrong instead."""
    with pytest.raises(ProjectError, match="not a 40-digit sha1"):
        read_project(write_config(tmp_path, sha1="0" * 64))


def test_a_config_without_a_hash_is_refused(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("object: extracted/sys/main.dol\n", encoding="utf-8")
    with pytest.raises(ProjectError, match="no `hash:` line"):
        read_project(path)


def test_a_config_without_an_object_is_refused(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(f"hash: {REAL}\n", encoding="utf-8")
    with pytest.raises(ProjectError, match="no `object:` line"):
        read_project(path)


def test_nested_yaml_is_refused_rather_than_half_read(tmp_path):
    """The parser handles the flat file dtk writes. If dtk ever nests these
    keys, the right answer is a line number, not a check that quietly stops
    finding the hash."""
    path = tmp_path / "config.yml"
    path.write_text(f"project:\n  hash: {REAL}\n", encoding="utf-8")
    with pytest.raises(ProjectError, match="indented line"):
        read_project(path)


def test_quotes_and_comments_come_off(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(
        f"# a comment\n\nobject: 'extracted/sys/main.dol'\nhash: \"{REAL.upper()}\"\n",
        encoding="utf-8",
    )
    project = read_project(path)
    assert project.sha1 == REAL  # dtk writes lowercase; a pasted uppercase one still matches
    assert project.object.as_posix() == "extracted/sys/main.dol"


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------


def test_the_right_bytes_pass(tmp_path):
    data = b"the real thing"
    digest, _ = sha1_file(write_dol(tmp_path, data))
    verdict = verify(write_config(tmp_path, sha1=digest), root=tmp_path)
    assert verdict.ok and verdict.status == "match"
    assert digest in verdict.report()


def test_a_mutated_executable_is_refused_naming_both_hashes(tmp_path):
    """The feature. One byte of the executable changes and the message has to
    carry the pair -- what was expected, what was there."""
    good = b"the real thing"
    bad = bytearray(good)
    bad[0] ^= 0x01
    expected, _ = sha1_file(write_dol(tmp_path, good))
    actual, _ = sha1_file(write_dol(tmp_path, bytes(bad)))
    assert expected != actual

    verdict = verify(write_config(tmp_path, sha1=expected), root=tmp_path)
    assert not verdict.ok and verdict.status == "differs"
    assert verdict.expected == expected and verdict.actual == actual
    report = verdict.report()
    assert expected in report and actual in report
    assert "expected" in report and "found" in report
    assert str(len(good)) in report  # the size, so a truncated dump is obvious


def test_a_missing_executable_says_so_rather_than_mismatching(tmp_path):
    """ "not extracted yet" and "extracted the wrong disc" are different
    problems with different answers, and one message for both sends the
    first reader hunting for a dump they never made."""
    (tmp_path / "extracted" / "sys").mkdir(parents=True)
    verdict = verify(write_config(tmp_path), root=tmp_path)
    assert not verdict.ok and verdict.status == "missing"
    assert verdict.actual == ""
    assert "tools/extract.py" in verdict.report()


def test_the_disc_header_names_the_dump_when_it_is_there(tmp_path):
    """A sha1 says "not that one"; "GEAE9P rev 1" says which one."""
    digest, _ = sha1_file(write_dol(tmp_path, b"whatever"))
    write_boot(tmp_path, game_id=b"GEAE9P", version=1)
    verdict = verify(write_config(tmp_path, sha1=digest), root=tmp_path)
    assert verdict.disc == "GEAE9P rev 1"
    assert "GEAE9P rev 1" in verdict.report()


def test_no_disc_header_still_gives_a_verdict(tmp_path):
    """describe_disc is a garnish. An extraction missing boot.bin, or a DOL
    handed over on its own with --dol, must still be hashed and judged."""
    dol = write_dol(tmp_path, b"whatever")
    verdict = verify(write_config(tmp_path, sha1=DECOY), dol=dol)
    assert verdict.status == "differs" and verdict.disc == ""
    assert DECOY in verdict.report()


def test_a_truncated_header_is_ignored_not_crashed_on(tmp_path):
    digest, _ = sha1_file(write_dol(tmp_path, b"whatever"))
    (tmp_path / "extracted" / "sys" / "boot.bin").write_bytes(b"GEAE8P")
    assert verify(write_config(tmp_path, sha1=digest), root=tmp_path).disc == ""


def test_dol_overrides_the_configs_own_path(tmp_path):
    """What extract.py --out somewhere-else needs: the hash comes from the
    config, the file comes from the caller."""
    elsewhere = tmp_path / "elsewhere" / "sys"
    elsewhere.mkdir(parents=True)
    (elsewhere / "main.dol").write_bytes(b"not the game")
    verdict = verify(write_config(tmp_path, sha1=DECOY), dol=elsewhere / "main.dol")
    assert verdict.ok


# --------------------------------------------------------------------------
# the caller in tools/extract.py
# --------------------------------------------------------------------------


def test_extract_refuses_a_wrong_build(tmp_path, capsys):
    """check_build returns the exit status extract.py returns. Its config is
    the repository's real one, so this fixture -- b"not the game" -- is the
    wrong build by construction."""
    write_dol(tmp_path, b"not the game")
    assert EX.check_build(tmp_path / "extracted") == 1
    err = capsys.readouterr().err
    assert REAL in err and DECOY in err


def test_extract_force_reports_but_does_not_fail(tmp_path, capsys):
    """--force already means "I know this is not the disc you expected"."""
    write_dol(tmp_path, b"not the game")
    assert EX.check_build(tmp_path / "extracted", force=True) == 0
    assert DECOY in capsys.readouterr().err


def test_extract_passes_the_build_it_should(tmp_path, capsys, monkeypatch):
    """The happy path has to be silent about failure, or the check would be a
    new way for a good extraction to look broken."""
    real_verify = EX.verify

    def fake(dol):
        return real_verify(write_config(tmp_path, sha1=DECOY), dol=dol)

    monkeypatch.setattr(EX, "verify", fake)
    write_dol(tmp_path, b"not the game")
    assert EX.check_build(tmp_path / "extracted") == 0
    out = capsys.readouterr()
    assert DECOY in out.out and out.err == ""


def test_an_unreadable_config_warns_but_keeps_the_extraction(tmp_path, capsys, monkeypatch):
    """Twenty minutes of extraction must not be thrown away because the
    checker could not find its own metadata."""

    def boom(dol):
        raise ProjectError("config.yml: cannot be read (No such file or directory)")

    monkeypatch.setattr(EX, "verify", boom)
    assert EX.check_build(tmp_path / "extracted") == 0
    assert "warning: cannot check the build" in capsys.readouterr().err
