"""What a fresh checkout is able to check, and with which compiler.

config/GEAE8P/units.txt is the list of what gets built, which compiler builds
it, and -- read the other way -- which compilers a checkout needs. Two things
used to be out of step with it: fetch_toolchain defaulted to 1.3.2 alone while
four units want 1.2.5n, and decomp stopped at the first unit whose compiler was
missing, so the units after it were never reported at all. Neither tool records
what it downloaded, so a compiler that changes under a match leaves no trace.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import decomp as DC  # noqa: E402
import fetch_toolchain as FT  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "config" / "GEAE8P" / "units.txt"

FLAGS = "-O4,p -nodefaults -proc gekko"
SAMPLE = (
    "# a comment\n"
    f"src/a.c\t1.3.2\t{FLAGS}\tnative\n"
    f"src/b.c\t1.2.5n\t{FLAGS}\n"
    f"src/c.c\t1.3.2\t{FLAGS}\n"
    f"src/d.c\t1.2.5n\t{FLAGS}\n"
)


def units_file(tmp_path: Path) -> Path:
    path = tmp_path / "units.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# which compilers a checkout needs
# --------------------------------------------------------------------------


def test_versions_come_from_the_units(tmp_path):
    assert FT.versions_from_units(units_file(tmp_path)) == ["1.3.2", "1.2.5n"]


def test_the_real_units_need_more_than_one_compiler():
    """The default that broke a fresh checkout: one version, hard-coded."""
    versions = FT.versions_from_units(UNITS)
    assert len(versions) > 1
    assert "1.2.5n" in versions


def test_a_units_file_that_is_not_there_asks_for_nothing(tmp_path):
    assert FT.versions_from_units(tmp_path / "nope.txt") == []


def test_every_unit_missing_a_compiler_is_named(tmp_path):
    """Not the first one: the run is incomplete, and how incomplete is the
    thing a reader needs to know."""
    vendor = tmp_path / "GC"
    (vendor / "1.3.2").mkdir(parents=True)
    (vendor / "1.3.2" / "mwcceppc.exe").write_bytes(b"MZ")
    absent = DC.missing_compilers(DC.load_units(units_file(tmp_path)), vendor)
    assert list(absent) == ["1.2.5n"]
    assert [p.name for p in absent["1.2.5n"]] == ["b.c", "d.c"]


def test_nothing_is_missing_when_every_compiler_is_there(tmp_path):
    vendor = tmp_path / "GC"
    for version in ("1.3.2", "1.2.5n"):
        (vendor / version).mkdir(parents=True)
        (vendor / version / "mwcceppc.exe").write_bytes(b"MZ")
    assert DC.missing_compilers(DC.load_units(units_file(tmp_path)), vendor) == {}


# --------------------------------------------------------------------------
# which compiler the match was made with
# --------------------------------------------------------------------------


def vendor_with(tmp_path: Path, **compilers: bytes) -> Path:
    vendor = tmp_path / "vendor"
    for version, body in compilers.items():
        exe = vendor / "mwcc" / "GC" / version.replace("_", ".") / "mwcceppc.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(body)
    return vendor


def test_the_record_says_what_is_on_disk(tmp_path):
    vendor = vendor_with(tmp_path, **{"1_3_2": b"compiler bytes"})
    units = units_file(tmp_path)
    assert FT.main(["--versions", "1.3.2", "--vendor", str(vendor), "--units", str(units)]) == 0
    record = FT.read_record(vendor / FT.RECORD)
    assert record == {"mwcc/GC/1.3.2/mwcceppc.exe": FT.sha256(b"compiler bytes")}
    assert FT.main(["--verify", "--vendor", str(vendor)]) == 0


def test_a_compiler_that_changed_under_a_match_is_noticed(tmp_path):
    vendor = vendor_with(tmp_path, **{"1_3_2": b"compiler bytes"})
    FT.main(["--versions", "1.3.2", "--vendor", str(vendor)])
    (vendor / "mwcc" / "GC" / "1.3.2" / "mwcceppc.exe").write_bytes(b"other bytes")
    assert FT.main(["--verify", "--vendor", str(vendor)]) == 1
    # and the next fetch says so rather than quietly rewriting the record
    assert FT.main(["--versions", "1.3.2", "--vendor", str(vendor)]) == 1
    assert FT.read_record(vendor / FT.RECORD) == {
        "mwcc/GC/1.3.2/mwcceppc.exe": FT.sha256(b"other bytes")
    }


def test_a_recorded_file_that_vanished_is_noticed(tmp_path):
    vendor = vendor_with(tmp_path, **{"1_3_2": b"compiler bytes"})
    FT.main(["--versions", "1.3.2", "--vendor", str(vendor)])
    (vendor / "mwcc" / "GC" / "1.3.2" / "mwcceppc.exe").unlink()
    assert FT.main(["--verify", "--vendor", str(vendor)]) == 1


def test_verifying_without_a_record_is_an_error(tmp_path):
    assert FT.main(["--verify", "--vendor", str(tmp_path / "empty")]) == 1


def test_provenance_survives_a_run_that_downloads_nothing(tmp_path):
    vendor = vendor_with(tmp_path, **{"1_3_2": b"compiler bytes"})
    vendor.mkdir(parents=True, exist_ok=True)
    (vendor / FT.RECORD).write_text(
        f"# compilers_latest.zip: {FT.ARCHIVE} sha256 deadbeef\n"
        f"{FT.sha256(b'compiler bytes')}  mwcc/GC/1.3.2/mwcceppc.exe\n",
        encoding="utf-8",
    )
    FT.main(["--versions", "1.3.2", "--vendor", str(vendor)])
    assert "sha256 deadbeef" in (vendor / FT.RECORD).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# the units list against the sources it is meant to name
# --------------------------------------------------------------------------


def test_units_name_every_source_with_a_stem_of_its_own():
    """decomp.py compiles each unit to build/src/<stem>.o, so two sources with
    the same stem would silently overwrite each other's object and one of them
    would be checked twice; a source in no unit is never checked at all."""
    units = DC.load_units(UNITS)
    listed = {Path(src).as_posix() for src, _, _ in units}
    on_disk = {p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.c")}
    assert on_disk - listed == set(), "sources in src/ that no unit names"
    assert listed - on_disk == set(), "units naming a source that is not there"
    stems = [Path(src).stem for src, _, _ in units]
    assert len(stems) == len(set(stems)), "two units share an object stem"
