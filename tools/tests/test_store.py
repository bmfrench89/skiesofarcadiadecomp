"""The disc store (disc-layer I4): tools/soa/store.py and extract.py's importer.

On tools/soa/discfixture.py's synthetic image, with a tail past a mebibyte so
the store keeps less than the whole image: an ISO and an RVZ import; the store
reads back as the image at every offset below its covered end and zeros
above; every block digest is hashlib's over its slice. Then each way it can
be wrong, each named: a payload byte flipped (one block and one extent, the
file by name), a truncated store, an unfinished .part, a header byte changed,
another game id, an executable that is not config/'s, files that are not the
pinned ones (refused, unless forced), and a padding-only difference (accepted
with a warning). --compare finds 0 differing bytes, and exactly 1 with --flip;
--sys-only writes the four system files; the formats Dolphin reads and this
does not are named. The pins here are worked out from the fixture's files
directly, not through store.py.
"""

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import extract  # noqa: E402
from soa import discfixture, store  # noqa: E402
from soa.disc import parse_fst  # noqa: E402

TAIL = 3 << 20  # past the store's mebibyte, so covered_end < the image's size


def sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def pins_of(fx) -> dict[str, str]:
    files = parse_fst(fx.system["fst.bin"]).files  # table order
    digest = hashlib.sha1(b"".join(hashlib.sha1(fx.files[f.path]).digest() for f in files))
    return {
        "image_size": str(len(fx.image)),
        "image_sha1": sha1(fx.image),
        "fst_sha1": sha1(fx.system["fst.bin"]),
        "files_sha1": digest.hexdigest(),
    }


def write_config(tmp: Path, fx, pins: dict[str, str] | None = None, dol: str | None = None):
    config = tmp / "config.yml"
    config.write_text(f"object: x\nhash: {dol or fx.dol_sha1}\n", encoding="utf-8")
    pinned = tmp / "disc.yml"
    pinned.write_text(
        "".join(f"{k}: {v}\n" for k, v in (pins or pins_of(fx)).items()), encoding="utf-8"
    )
    return config, pinned


def run_import(tmp: Path, image: Path, fx, *, force=False, pins=None, dol=None, game_id=None):
    config, pinned = write_config(tmp, fx, pins, dol)
    out = tmp / "out"
    code = extract.import_store(
        image, out, force=force, pins_path=pinned, config=config, game_id=game_id or fx.game_id
    )
    return code, out / f"{game_id or fx.game_id}{store.STORE_SUFFIX}"


@pytest.fixture
def fx(tmp_path):
    return discfixture.build(tmp_path / "src" / "disc.iso", tail=TAIL)


def test_an_iso_imports_and_reads_back_as_the_image(tmp_path, fx, capsys):
    code, path = run_import(tmp_path, fx.path, fx)
    assert code == 0 and "verdict: a verified dump" in capsys.readouterr().out
    with store.Store(path) as st:
        h = st.header
        assert h.image_size == len(fx.image) and h.covered_end < h.image_size
        assert st.read(0, h.covered_end) == fx.image[: h.covered_end]  # every offset below
        assert st.read(h.covered_end, 4096) == bytes(4096)  # zeros above
        for k, digest in enumerate(h.blocks):
            piece = fx.image[k * store.BLOCK_SIZE : min((k + 1) * store.BLOCK_SIZE, h.covered_end)]
            assert digest == hashlib.sha1(piece).digest(), k
        assert h.flags == store.FLAG_IMAGE | store.FLAG_FILES
        assert h.extents[0].disc_offset == 0 and h.extents[-1].end == h.covered_end
        for a, b in zip(h.extents, h.extents[1:], strict=False):
            assert a.end == b.disc_offset  # contiguous, in order
        assert sum(e.kind == store.FILE for e in h.extents) == len(fx.files)
        assert h.extents[-1].kind == store.TAIL and h.extents[0].kind == store.SYSTEM
    assert store.check(path) == []
    assert not path.with_name(path.name + ".part").exists()


def test_an_rvz_imports_to_the_same_payload(tmp_path, fx):
    pytest.importorskip("compression.zstd")
    rvz = tmp_path / "src" / "disc.rvz"
    discfixture.write_rvz(fx.image, rvz)
    code, path = run_import(tmp_path, rvz, fx)
    assert code == 0
    with store.Store(path) as st:
        assert st.header.source_kind == store.SOURCE_RVZ
        assert st.read(0, st.covered_end) == fx.image[: st.covered_end]


def test_a_flipped_payload_byte_is_named_by_its_file_one_block_one_extent(tmp_path, fx):
    code, path = run_import(tmp_path, fx.path, fx)
    with store.Store(path) as st:
        at = st.header.payload_offset + fx.offsets["field/fa00.dat"] + 100
    data = bytearray(path.read_bytes())
    data[at] ^= 1
    path.write_bytes(bytes(data))
    problems = store.check(path)
    assert len(problems) == 2, problems
    assert sum("field/fa00.dat" in p for p in problems) == 1
    assert sum(p.startswith("block ") for p in problems) == 1


def test_a_truncated_store_a_part_and_a_changed_header_are_refused(tmp_path, fx, capsys):
    code, path = run_import(tmp_path, fx.path, fx)
    data = path.read_bytes()
    short = tmp_path / "short.soadisc"
    short.write_bytes(data[:-1])
    with pytest.raises(store.StoreError, match="truncated"):
        store.Store(short)
    part = tmp_path / "x.soadisc.part"
    part.write_bytes(data)
    with pytest.raises(store.StoreError, match="unfinished"):
        store.Store(part)
    bad = bytearray(data)
    bad[0x30] ^= 1  # covered_end's low byte
    changed = tmp_path / "changed.soadisc"
    changed.write_bytes(bytes(bad))
    with pytest.raises(store.StoreError):
        store.Store(changed)
    # the importer deletes a stale .part, naming it, and the import still works
    stale = path.with_name(path.name + ".part")
    stale.write_bytes(b"half a store")
    assert run_import(tmp_path, fx.path, fx)[0] == 0
    assert f"deleting {stale}" in capsys.readouterr().out and not stale.exists()


def test_another_game_and_another_executable_are_refused(tmp_path, fx, capsys):
    other = discfixture.build(tmp_path / "other" / "disc.iso", game_id="GTSP01", tail=TAIL)
    code, _ = run_import(tmp_path, other.path, other, game_id=fx.game_id)
    assert code == 1 and "is GTSP01 disc 0 revision 0" in capsys.readouterr().err
    code, path = run_import(tmp_path, fx.path, fx, dol="0" * 40)
    assert code == 1 and "not config/'s" in capsys.readouterr().err and not path.exists()
    assert run_import(tmp_path, fx.path, fx, dol="0" * 40, force=True)[0] == 0


def test_files_that_are_not_the_pinned_ones_are_refused_unless_forced(tmp_path, fx, capsys):
    pins = {**pins_of(fx), "files_sha1": "1" * 40}
    code, path = run_import(tmp_path, fx.path, fx, pins=pins)
    assert code == 1 and "a bad or patched dump, refused" in capsys.readouterr().err
    assert not path.exists()  # nothing left behind
    code, path = run_import(tmp_path, fx.path, fx, pins=pins, force=True)
    assert code == 0 and path.exists() and "accepted under --force" in capsys.readouterr().out


def test_a_padding_only_difference_is_accepted_with_a_warning(tmp_path, fx, capsys):
    image = bytearray(fx.image)
    junk = [(at, filler) for kind, at, filler in fx.gaps if kind == "junk"]
    assert junk
    for at, filler in junk:  # the junk zeroed: the files are untouched
        image[at : at + len(filler)] = bytes(len(filler))
    scrubbed = tmp_path / "scrubbed.iso"
    scrubbed.write_bytes(bytes(image))
    code, path = run_import(tmp_path, scrubbed, fx, pins=pins_of(fx))
    out = capsys.readouterr().out
    assert code == 0 and "accepted, with a warning" in out and "scrubbed or trimmed" in out
    with store.Store(path) as st:
        assert st.header.flags == store.FLAG_FILES


def test_compare_finds_nothing_and_then_exactly_the_flipped_byte(tmp_path, fx, capsys):
    code, path = run_import(tmp_path, fx.path, fx)
    assert extract.compare_store(path, fx.path, None) == 0
    assert "0 bytes differ" in capsys.readouterr().out
    first = min(fx.offsets.values())
    assert extract.compare_store(path, fx.path, first) == 1
    out = capsys.readouterr().out
    assert "1 bytes differ" in out and f"first at 0x{first:X}" in out


def test_sys_only_writes_the_four_system_files(tmp_path, fx):
    code, path = run_import(tmp_path, fx.path, fx)
    assert extract.sys_only(path, tmp_path / "again") == 0
    for name in ("boot.bin", "bi2.bin", "main.dol", "fst.bin"):
        assert (tmp_path / "again" / "sys" / name).read_bytes() == fx.system[name], name


@pytest.mark.parametrize(
    ("at", "magic", "name"),
    [
        (0, b"\x01\xc0\x0b\xb1", "GCZ"),
        (0, b"WIA\x01", "WIA"),
        (0, b"CISO", "CISO"),
        (0, b"WBFS", "WBFS"),
        (0x200, b"NKIT", "NKit"),
    ],  # fmt: skip
)
def test_formats_this_does_not_read_are_named(tmp_path, fx, capsys, at, magic, name):
    data = bytearray(fx.image[:0x1000])
    data[at : at + len(magic)] = magic
    image = tmp_path / f"x.{name.lower()}"
    image.write_bytes(bytes(data))
    assert run_import(tmp_path, image, fx)[0] == 1
    err = capsys.readouterr().err
    assert f"is a {name} image" in err and "ISO or RVZ" in err


def test_a_table_whose_files_overlap_is_refused():
    place = {"a.dat": (0x8000, 0x100), "b.dat": (0x80F0, 0x100)}
    fst, _ = discfixture.make_fst(["a.dat", "b.dat"], place)
    with pytest.raises(store.StoreError, match="overlaps"):
        store.layout(fst, 0x10000)
    with pytest.raises(store.StoreError, match="past the image's end"):
        store.layout(fst, 0x8100)


def test_the_pinned_hashes_read_in_their_form_and_a_mistyped_one_is_refused(tmp_path):
    from soa.dump import ProjectError, read_disc_pins

    pins = read_disc_pins()  # config/GEAE8P/disc.yml, as committed
    assert pins["image_size"] == "1459978240" and all(
        len(pins[k]) == 40 for k in pins if k != "image_size"
    )
    text = (ROOT / "config" / "GEAE8P" / "disc.yml").read_text(encoding="utf-8")
    short = tmp_path / "disc.yml"
    short.write_text(text.replace(pins["files_sha1"], pins["files_sha1"][:39]), encoding="utf-8")
    with pytest.raises(ProjectError, match="files_sha1"):
        read_disc_pins(short)


def test_a_folder_holding_a_store_is_read_through_it(tmp_path, fx):
    from soa.disc import STORE_NAME, open_data

    code, path = run_import(tmp_path, fx.path, fx)
    folder = path.parent
    (folder / "disc.iso").write_bytes(b"not read: the store comes first")
    assert path.name == STORE_NAME.replace("GEAE8P", fx.game_id)
    (folder / STORE_NAME).write_bytes(path.read_bytes())  # under the real game's name
    with open_data(folder) as disc:
        assert isinstance(disc.reader, store.Store)
        assert disc.read_path("field/fa00.dat") == fx.files["field/fa00.dat"]
