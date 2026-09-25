"""tools/extract.py, and the tools reading the disc through its image (I2).

    python -m pytest tools/tests/test_extract.py

An extraction is `disc.iso` plus `sys/`; the 5,552 loose files are written only
with `--files`, `--prune-loose` deletes the ones an earlier extraction left
after comparing each with the image, and `sct.py`, `validate_assets.py` and
`audio_check.py` read a file through the image when it is not there loose
(docs/specs/disc-layer.md, §3.5 and slice I2).

Every image here is `soa/discfixture.py`'s: built at test time into a
temporary directory, from a seed, with a test game id. No byte of the game is
read or written, so this runs in CI exactly as on the owner's machine. The
build check extract.py ends with is pointed at a config naming the fixture's
own DOL hash, and the expected game id at the fixture's, so the extraction
under test is the one a real dump gets, not the `--force` path.

What each part is for:

  * the fixture is what it says: `parse_fst` finds every file where it was
    placed, `aklz.decompress` gives back each wrapped file, and each layout
    feature (files that abut, zero padding, junk gaps, a tail) is really
    there -- a fixture that quietly lost one would pass everything below and
    prove nothing about it;
  * `extract.py` writes `disc.iso` and the four `sys/` files, each equal to
    its slice, and no loose file; `--files` writes each file equal to its
    slice; `--iso` is accepted and says it is now the default;
  * `--prune-loose` deletes exactly the files equal to the image and keeps,
    and names, the ones the test altered (the mutation: one byte flipped, one
    file a byte short); `--dry-run` deletes nothing and says the same;
    emptied directories go, and `sys/` and the image are never touched;
  * each of the three tools reads a file that is only in the image, and
    `validate_assets.py` fails a broken container it can only see there.
"""

import random
import shutil
import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import extract as EX  # noqa: E402
import sct  # noqa: E402
import validate_assets  # noqa: E402
from soa import aklz, discfixture, dspadpcm  # noqa: E402
from soa import disc as D  # noqa: E402
from soa import dol as DOL  # noqa: E402
from soa.dump import verify  # noqa: E402

SYS = {"sys/boot.bin", "sys/bi2.bin", "sys/main.dol", "sys/fst.bin"}


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    """One default image for the module: the tests only read it."""
    return discfixture.build(tmp_path_factory.mktemp("fixture") / "dump.iso")


def tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def dirs_of(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir()}


def image_only(fixture, where: Path) -> Path:
    """A data directory holding the image and nothing else: every file a tool
    reads from it is present only in the image."""
    where.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture.path, where / "disc.iso")
    return where


def run(fixture, tmp_path, monkeypatch, capsys, *argv):
    """extract.main, with the build check and the game id pointed at the
    fixture's own: (exit status, stdout, stderr)."""
    config = tmp_path / "config.yml"
    config.write_text(
        f"object: extracted/sys/main.dol\nhash: {fixture.dol_sha1}\n", encoding="utf-8"
    )
    monkeypatch.setattr(EX, "verify", lambda dol: verify(config, dol=dol))
    monkeypatch.setattr(EX, "EXPECTED_GAME_ID", fixture.game_id)
    code = EX.main([str(a) for a in argv])
    got = capsys.readouterr()
    return code, got.out, got.err


# --------------------------------------------------------------------------
# the fixture
# --------------------------------------------------------------------------


def test_the_fixture_is_what_it_says(fx):
    img = fx.image
    boot = D.parse_boot(img[: D.BOOT_HEADER_SIZE])
    assert boot.is_gamecube and boot.game_id == fx.game_id
    assert boot.game_id != "GEAE8P" and not img.startswith(b"GEAE8P")
    assert boot.fst_size == boot.fst_max_size

    fst = D.parse_fst(img[boot.fst_offset : boot.fst_offset + boot.fst_size])
    placed = {p: (fx.offsets[p], len(b)) for p, b in fx.files.items()}
    assert {f.path: (f.offset, f.size) for f in fst.files} == placed
    assert sorted(fst.dirs) == sorted(fx.dirs) and "battle/enemy" in fst.dirs
    for f in fst.files:
        assert img[f.offset : f.offset + f.size] == fx.files[f.path], f.path
    # battle/zz.dat follows battle/enemy/ and zz.gvr follows every directory:
    # the parser's directory stack has to pop for both to land right
    assert {"battle/zz.dat", "zz.gvr"} <= {f.path for f in fst.files}

    assert len(fx.plain) >= 3
    for path, plain in fx.plain.items():
        assert aklz.decompress(fx.files[path]) == plain, path
        assert fx.files[path][8:12] == bytes.fromhex("3dcccccd"), "0.1f at +8"

    dol = DOL.parse(fx.system["main.dol"])
    assert DOL.image_size(fx.system["main.dol"][:0x100]) == len(fx.system["main.dol"])
    assert dol.entry_point == discfixture.DOL_ENTRY and len(dol.text) == 2

    # the layout features the spec asks for, each really there
    by_offset = sorted(fx.files, key=fx.offsets.__getitem__)
    assert by_offset != [f.path for f in fst.files], "disc order is not FST order"
    assert all(o % 4 == 0 for o in fx.offsets.values())
    kinds = {kind for kind, _, _ in fx.gaps}
    assert {"abut", "pad32", "junk", "align32k"} <= kinds
    assert any(kind == "abut" and not filler for kind, _, filler in fx.gaps)
    pads = [filler for kind, _, filler in fx.gaps if kind == "pad32" and filler]
    assert pads and all(1 <= len(f) <= 31 and not any(f) for f in pads)
    junk = [filler for kind, _, filler in fx.gaps if kind == "junk"]
    assert junk and all(not any(f[:28]) and any(f[28:]) for f in junk)
    assert sum(len(b) % 32 != 0 for b in fx.files.values()) >= 5
    assert fx.tail > 0 and any(img[-fx.tail :])
    assert len(img) % discfixture.FILES_ALIGN == 0


def test_the_fixture_refuses_the_real_game_id(tmp_path):
    with pytest.raises(ValueError, match="never carries GEAE8P"):
        discfixture.build(tmp_path / "x.iso", game_id="GEAE8P")
    assert not (tmp_path / "x.iso").exists()


# --------------------------------------------------------------------------
# extract.py
# --------------------------------------------------------------------------


def test_extract_writes_the_image_and_sys_and_no_loose_file(fx, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    code, stdout, err = run(fx, tmp_path, monkeypatch, capsys, fx.path, "--out", out)
    assert code == 0, err
    assert tree(out) == {"disc.iso"} | SYS
    assert dirs_of(out) == {"sys"}
    assert (out / "disc.iso").read_bytes() == fx.image
    for name, (offset, length) in fx.slices.items():
        got = (out / "sys" / name).read_bytes()
        assert got == fx.image[offset : offset + length] == fx.system[name], name
    assert "matches" in stdout and fx.dol_sha1 in stdout  # the build check ran and passed
    assert "--iso is now the default" not in stdout


def test_iso_is_accepted_and_says_it_is_now_the_default(fx, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    code, stdout, err = run(fx, tmp_path, monkeypatch, capsys, fx.path, "--iso", "--out", out)
    assert code == 0, err
    assert "--iso is now the default" in stdout
    assert tree(out) == {"disc.iso"} | SYS


def test_files_writes_every_file_equal_to_its_slice(fx, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    code, stdout, err = run(fx, tmp_path, monkeypatch, capsys, fx.path, "--files", "--out", out)
    assert code == 0, err
    assert tree(out) == {"disc.iso"} | SYS | set(fx.files)
    for path, data in fx.files.items():
        offset = fx.offsets[path]
        assert (out / path).read_bytes() == fx.image[offset : offset + len(data)], path


def test_a_later_extraction_names_the_loose_files_left_behind(fx, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    assert run(fx, tmp_path, monkeypatch, capsys, fx.path, "--files", "--out", out)[0] == 0
    code, stdout, _ = run(fx, tmp_path, monkeypatch, capsys, fx.path, "--out", out)
    assert code == 0
    assert f"{len(fx.files)} loose files from an earlier extraction" in stdout
    assert "--prune-loose" in stdout


def test_extracting_the_image_onto_itself_leaves_it_whole(fx, tmp_path, monkeypatch, capsys):
    """After a prune, `extract.py extracted/disc.iso` is how sys/ comes back.
    Opening the output for writing first would truncate the input."""
    out = image_only(fx, tmp_path / "out")
    code, stdout, err = run(fx, tmp_path, monkeypatch, capsys, out / "disc.iso", "--out", out)
    assert code == 0, err
    assert "left as it is" in stdout
    assert (out / "disc.iso").read_bytes() == fx.image
    assert tree(out) == {"disc.iso"} | SYS


def test_arguments_that_do_not_go_together_are_refused(fx, tmp_path, capsys):
    out = str(tmp_path / "out")
    for argv in (
        ["--prune-loose", str(fx.path), "--out", out],  # a prune reads --out's own image
        ["--prune-loose", "--files", "--out", out],
        ["--dry-run", str(fx.path), "--out", out],  # --dry-run is the prune's alone
        ["--out", out],  # nothing to extract
    ):
        with pytest.raises(SystemExit) as stop:
            EX.main(argv)
        assert stop.value.code == 2, argv
    capsys.readouterr()
    assert not (tmp_path / "out").exists()


# --------------------------------------------------------------------------
# --prune-loose
# --------------------------------------------------------------------------


def test_prune_deletes_exactly_the_equal_files_and_keeps_the_altered_ones(
    fx, tmp_path, monkeypatch, capsys
):
    """The mutation: two loose files the test altered -- one byte flipped,
    one a byte short -- must survive both runs, each named with what differs."""
    out = tmp_path / "out"
    assert run(fx, tmp_path, monkeypatch, capsys, fx.path, "--files", "--out", out)[0] == 0
    flipped, short = "field/fa00.dat", "battle/enemy/e001.dat"
    altered = bytearray(fx.files[flipped])
    altered[1000] ^= 0x01
    (out / flipped).write_bytes(altered)
    (out / short).write_bytes(fx.files[short][:-1])
    (out / "battle" / "notes.txt").write_text("the owner's, not the disc's", encoding="utf-8")
    before = tree(out)
    equal = len(fx.files) - 2
    equal_bytes = sum(len(b) for p, b in fx.files.items() if p not in (flipped, short))

    code, stdout, _ = run(
        fx, tmp_path, monkeypatch, capsys, "--prune-loose", "--dry-run", "--out", out
    )
    assert code == 1
    assert tree(out) == before, "a dry run deleted something"
    assert f"{equal} equal to the image: would be deleted ({equal_bytes:,} bytes)" in stdout
    assert "2 differ from the image: kept" in stdout
    assert f"kept {flipped}: differs from the image at byte 0x3E8" in stdout
    assert f"kept {short}: 4 bytes, the image's 5" in stdout
    assert "2 directories emptied: would be removed" in stdout  # sound/, title/
    assert "1 other files" in stdout  # notes.txt, not in the file table

    code, stdout, err = run(fx, tmp_path, monkeypatch, capsys, "--prune-loose", "--out", out)
    assert code == 1 and "were kept" in err
    assert f"{equal} equal to the image: deleted ({equal_bytes:,} bytes)" in stdout
    assert f"kept {flipped}: differs from the image at byte 0x3E8" in stdout
    assert f"kept {short}: 4 bytes, the image's 5" in stdout
    assert tree(out) == {"disc.iso", flipped, short, "battle/notes.txt"} | SYS
    assert (out / flipped).read_bytes() == bytes(altered)
    assert (out / short).read_bytes() == fx.files[short][:-1]
    assert dirs_of(out) == {"sys", "field", "battle", "battle/enemy"}
    assert (out / "disc.iso").read_bytes() == fx.image
    for name, (offset, length) in fx.slices.items():
        assert (out / "sys" / name).read_bytes() == fx.image[offset : offset + length]


def test_prune_on_a_clean_tree_leaves_the_image_and_sys(fx, tmp_path, monkeypatch, capsys):
    """The owner's Done line in small: every loose file deleted, none kept,
    and what is left is disc.iso and sys/."""
    out = tmp_path / "out"
    assert run(fx, tmp_path, monkeypatch, capsys, fx.path, "--files", "--out", out)[0] == 0
    total = sum(len(b) for b in fx.files.values())
    code, stdout, _ = run(fx, tmp_path, monkeypatch, capsys, "--prune-loose", "--out", out)
    assert code == 0
    assert f"{len(fx.files)} equal to the image: deleted ({total:,} bytes)" in stdout
    assert "0 differ from the image: kept" in stdout
    assert tree(out) == {"disc.iso"} | SYS
    assert dirs_of(out) == {"sys"}
    # and again: nothing left to do, which is not a failure
    code, stdout, _ = run(fx, tmp_path, monkeypatch, capsys, "--prune-loose", "--out", out)
    assert code == 0 and f"0 of the image's {len(fx.files)} files are loose" in stdout


def test_prune_refuses_without_an_image_to_compare_with(fx, tmp_path, capsys):
    out = tmp_path / "out"
    with D.Disc(D.ImageFile(fx.path)) as disc:
        disc.extract_files(out)
        disc.write_system_files(out)
    before = tree(out)
    assert EX.main(["--prune-loose", "--out", str(out)]) == 1
    assert "no image to compare with" in capsys.readouterr().err
    (out / "disc.iso").write_bytes(bytes(0x10000))  # not a GameCube image
    assert EX.main(["--prune-loose", "--out", str(out)]) == 1
    assert "bad magic" in capsys.readouterr().err
    assert tree(out) == before | {"disc.iso"}


# --------------------------------------------------------------------------
# reading through the image
# --------------------------------------------------------------------------


def test_open_data_reads_the_image_else_the_loose_tree(fx, tmp_path):
    data = image_only(fx, tmp_path / "data")
    with D.open_data(data) as d:
        assert isinstance(d, D.Disc)
        for path, blob in fx.files.items():
            assert d.read_path(path) == blob, path
        # without regard to case, as DVDConvertPathToEntrynum compares
        assert d.read_path("FIELD/FA00.DAT") == fx.files["field/fa00.dat"]
        with pytest.raises(FileNotFoundError, match="not in"):
            d.read_path("field/none.dat")
    with D.open_data(data / "disc.iso") as d:  # the image named directly
        assert d.read_path("zz.gvr") == fx.files["zz.gvr"]

    loose = tmp_path / "loose"
    with D.Disc(D.ImageFile(fx.path)) as disc:
        disc.extract_files(loose)
        disc.write_system_files(loose)
    with D.open_data(loose) as d:
        assert isinstance(d, D.LooseTree)
        assert sorted(d.paths()) == sorted(fx.files)  # sys/ is not one of them
        assert d.read_path("battle/zz.dat") == fx.files["battle/zz.dat"]

    with pytest.raises(FileNotFoundError, match="extract.py"):
        D.open_data(tmp_path / "nothing")


def test_a_path_that_is_not_there_is_read_through_the_image(fx, tmp_path, monkeypatch):
    data = image_only(fx, tmp_path / "data")
    assert D.read_data_path(data / "sound" / "s000_L.dsp") == fx.files["sound/s000_L.dsp"]
    assert D.read_data_path(data / "disc.iso" / "title" / "t00.dat") == fx.files["title/t00.dat"]
    monkeypatch.chdir(tmp_path)  # relative, as the .scn notes quote it
    assert D.read_data_path(Path("data/sound/s000_R.dsp")) == fx.files["sound/s000_R.dsp"]
    # a loose file, where there is one, is what is read
    (data / "banner.bnr").write_bytes(b"edited")
    assert D.read_data_path(data / "banner.bnr") == b"edited"
    assert D.read_data_file(data, "banner.bnr") == b"edited"
    assert D.read_data_file(data, "zz.gvr") == fx.files["zz.gvr"]
    with pytest.raises(FileNotFoundError, match="no disc.iso"):
        D.read_data_path(tmp_path / "elsewhere" / "x.dsp")


def script() -> bytes:
    """A decompressed field script of one entry: FLAGSET 18, then RET (the
    shape tools/tests/test_sct.py builds)."""
    words = [17, 0x04000000, struct.unpack(">I", struct.pack(">f", 18.0))[0], 29, 12]
    head = struct.pack(">III", 0, 0, 1) + struct.pack(">I", 0) + b"main".ljust(16, b"\0")
    return head + b"".join(struct.pack(">I", w) for w in words)


def test_sct_reads_a_script_present_only_in_the_image(tmp_path, capsys):
    fixture = discfixture.build(
        tmp_path / "dump.iso", extra={"field/me001a.sct": discfixture.wrap_aklz(script())}
    )
    data = image_only(fixture, tmp_path / "data")
    assert not (data / "field").exists()
    for argv in (
        ["001a", "--data", str(data)],
        ["001a", "--data", str(data / "disc.iso")],
        [str(data / "field" / "me001a.sct")],
    ):
        assert sct.main(argv) == 0, argv
        out = capsys.readouterr().out
        assert "==== main @00000" in out and "[17]FLAGSET (18)" in out and "[12]RET" in out
    assert sct.main(["999z", "--data", str(data)]) == 1
    assert "not in" in capsys.readouterr().err


def test_validate_assets_reads_every_file_through_the_image(fx, tmp_path, capsys):
    data = image_only(fx, tmp_path / "data")
    decoded = sum(len(fx.plain.get(p, b)) for p, b in fx.files.items())
    assert validate_assets.main(["--root", str(data), "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert f"scanning {len(fx.files)} files in {data / 'disc.iso'}" in out
    assert f"AKLZ containers   {len(fx.plain)} of {len(fx.files)}" in out
    assert f"decoded bytes     {decoded:,}" in out
    assert "decode failures   0" in out

    # the same counts from a loose tree with no image, sys/ left out
    loose = tmp_path / "loose"
    with D.Disc(D.ImageFile(fx.path)) as disc:
        disc.extract_files(loose)
        disc.write_system_files(loose)
    assert validate_assets.main(["--root", str(loose), "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert f"AKLZ containers   {len(fx.plain)} of {len(fx.files)}" in out
    assert f"decoded bytes     {decoded:,}" in out


def test_validate_assets_fails_a_container_broken_in_the_image(tmp_path, capsys):
    """A check that reads through the image has to be able to fail there.
    Through the worker pool, as the owner runs it."""
    broken = discfixture.wrap_aklz(bytes(range(256)) * 8)[:-40]
    fixture = discfixture.build(tmp_path / "dump.iso", extra={"field/bad.dat": broken})
    data = image_only(fixture, tmp_path / "data")
    assert validate_assets.main(["--root", str(data), "--jobs", "2"]) == 1
    out = capsys.readouterr().out
    assert "decode failures   1" in out and "FAIL field/bad.dat" in out


def dsp_stream(rate: int, frames: int, seed: int = 7) -> bytes:
    """A DSP-ADPCM stream of random frames with no prediction: header plus
    8-byte frames, as tools/tests/test_dspadpcm.py builds them."""
    rng = random.Random(seed)
    header = bytearray(0x60)
    struct.pack_into(">III", header, 0, frames * 14, frames * 16, rate)
    body = b"".join(bytes([rng.randrange(1, 12)]) + rng.randbytes(7) for _ in range(frames))
    return bytes(header) + body


def test_audio_check_reads_a_stream_present_only_in_the_image(tmp_path, capsys):
    pytest.importorskip("numpy", reason="audio_check.py needs numpy, which CI does not install")
    import audio_check

    rate = 8000
    dsp = dsp_stream(rate, frames=600)
    fixture = discfixture.build(tmp_path / "dump.iso", extra={"sound/t01_L.dsp": dsp})
    data = image_only(fixture, tmp_path / "data")
    pcm = dspadpcm.decode(dsp)
    wav = tmp_path / "rec.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))

    dsp_path = data / "sound" / "t01_L.dsp"
    assert not dsp_path.exists()
    code = audio_check.main([str(wav), str(dsp_path), "--start", "0", "--seconds", "0.5"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "the stream plays as the disc holds it" in out
    missing = data / "sound" / "t02_L.dsp"
    assert audio_check.main([str(wav), str(missing), "--start", "0", "--seconds", "0.5"]) == 1
    assert "not in" in capsys.readouterr().err
