"""R5's Android sysroot (specs/android-sysroot.md R5a): tools/fetch_android_sysroot.py.

The phone's game library is compiled against bionic's own headers and linked
with crt objects built from bionic's own source, all from 44 files at one
pinned commit, each held to a sha256 and a git blob id. These hold:

- the pins themselves: 47 of them, by role, the tree's places, the record's
  and the notice's names clear of the guard, and the CI cache key moving with
  a pin and nothing else;
- the fetching: a file off its pin refused with nothing written, a pinned
  file missing from its archive named, and android.googlesource.com's answers
  (429 with Retry-After in seconds or as a date, 5xx, a body cut short, no
  network, a 404, the run's deadline) waited on, tried again or given up, in
  words that never speak of pins;
- the cache: whole, it makes no request, and a tree not as recorded is built
  again from it; --verify's facts; a record not this script's;
- the build: the crt objects are the pinned bytes in any folder and with
  CPATH poisoned, and refused at -O0 or from another clang; NOTICE.txt holds
  each file's own words and is the pinned text; a stop inside the swap leaves
  no record; the script runs as a package's python runs it;
- --check-upstream against an injected listing.

Those that build need llvm-mingw (python tools/fetch_mingw.py) and the source
cache (python tools/fetch_android_sysroot.py), and skip, saying which, without
them; CI's android-route job runs them with no skips. The rest need nothing.
"""

import base64
import email.message
import email.utils
import io
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_android_sysroot as fas  # noqa: E402
import guard  # noqa: E402
from soa import toolchain  # noqa: E402

CACHE = ROOT / "vendor" / fas.CACHE
has_cache = not fas.cache_problems(CACHE)
needs_cache = pytest.mark.skipif(
    not has_cache, reason="no source cache (python tools/fetch_android_sysroot.py fetches it)"
)
needs_mingw = pytest.mark.skipif(
    toolchain.mingw_clang() is None or toolchain.mingw_lld() is None,
    reason="no llvm-mingw (python tools/fetch_mingw.py)",
)


@pytest.fixture(autouse=True)
def _fresh_run():
    fas.new_run()
    yield
    fas.new_run()


class Clock:
    """A clock that moves only when slept on, and records each sleep."""

    def __init__(self, t: float = 1000.0):
        self.t = t
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://x", code, f"HTTP {code}", headers, None)


def server(*answers):
    """A get() that gives each answer in turn: bytes are a 200's body, an
    exception is raised. The URLs asked are recorded."""
    asked: list[str] = []
    it = iter(answers)

    def get(url):
        asked.append(url)
        a = next(it)
        if isinstance(a, BaseException):
            raise a
        return a

    get.asked = asked
    return get


def tgz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def table(monkeypatch, files: dict[str, bytes], role: str = "build"):
    """SOURCES as a test table of these files, each pinned to its own bytes."""
    rows = {
        p: fas.Source(len(d), role, "both", fas.sha256(d), fas.blob_id(d)) for p, d in files.items()
    }
    monkeypatch.setattr(fas, "SOURCES", rows)
    return rows


# ---- 1 ----------------------------------------------------------------------


def test_the_pins_are_bionic_s_files_at_one_commit(monkeypatch):
    roles = [s.role for s in fas.SOURCES.values()]
    assert len(fas.SOURCES) == 47
    assert (roles.count("ship"), roles.count("build"), roles.count("check")) == (30, 14, 3)
    hexes = set("0123456789abcdef")
    assert len(fas.COMMIT) == 40 and set(fas.COMMIT) <= hexes
    for path, s in fas.SOURCES.items():
        assert len(s.sha256) == 64 and set(s.sha256) <= hexes, path
        assert len(s.blob) == 40 and set(s.blob) <= hexes, path
        assert (s.abi is None) == (s.role == "check"), path
    places = list(fas.SHIP.values())
    assert all(p.startswith("usr/include/") for p in places)
    arm = [p for p in places if "/aarch64-linux-android/" in p]
    x86 = [p for p in places if "/x86_64-linux-android/" in p]
    assert (len(places) - len(arm) - len(x86), len(arm), len(x86)) == (23, 3, 4)
    for name in [*places, fas.RECORD, "NOTICE.txt", *fas.OUTPUTS]:
        assert guard.forbidden_suffix(name) is None, name
    checks = {p for p, s in fas.SOURCES.items() if s.role == "check"}
    assert checks.isdisjoint(fas.SHIP) and checks.isdisjoint(fas.needed())
    key = fas.cache_key()
    assert len(key) == 16 and fas.cache_key() == key
    path, s = next(iter(fas.SOURCES.items()))
    moved = dict(fas.SOURCES, **{path: s._replace(sha256="0" * 64)})
    monkeypatch.setattr(fas, "SOURCES", moved)
    assert fas.cache_key() != key
    for column in ("blob", "role"):
        monkeypatch.setattr(
            fas, "SOURCES", dict(fas.SOURCES, **{path: s._replace(**{column: "x"})})
        )
        assert fas.cache_key() != key, column
    monkeypatch.setattr(fas, "SOURCES", dict(fas.SOURCES, **{path: s._replace(size=s.size + 1)}))
    assert fas.cache_key() != key


def test_the_cache_key_is_the_pins_and_not_the_script_s_bytes(tmp_path):
    """CI restores the cache by this key on Ubuntu and Windows alike: the same
    script with CRLF line ends and a comment more gives the same key."""
    tools = tmp_path / "tools"
    shutil.copytree(
        ROOT / "tools" / "soa", tools / "soa", ignore=shutil.ignore_patterns("__pycache__")
    )
    text = (ROOT / "tools" / "fetch_android_sysroot.py").read_text(encoding="utf-8")
    (tools / "fetch_android_sysroot.py").write_bytes(
        ("# another line\n" + text).replace("\n", "\r\n").encode()
    )
    run = subprocess.run(
        [sys.executable, "-I", str(tools / "fetch_android_sysroot.py"), "--cache-key"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.stdout.strip() == f"key={fas.cache_key()}", run.stderr


# ---- 2, 3 ---------------------------------------------------------------------


def test_a_file_that_is_not_its_pin_is_refused_and_nothing_written(monkeypatch, tmp_path):
    good = b"#define X 1\n"
    table(monkeypatch, {"libc/include/x.h": good})
    clock = Clock()
    cache = tmp_path / fas.CACHE
    get = server(tgz({"x.h": b"#define X 2\n"}))
    with pytest.raises(fas.Refused) as e:
        fas.sources(cache, get=get, sleep=clock.sleep, clock=clock)
    words = str(e.value)
    assert "libc/include/x.h" in words and fas.sha256(good) in words
    assert fas.sha256(b"#define X 2\n") in words and "nothing was written" in words
    assert not (cache / "libc/include/x.h").exists() and not (tmp_path / fas.DEST).exists()
    # the bytes right, the blob pin a digit off
    row = fas.SOURCES["libc/include/x.h"]
    wrong = ("1" if row.blob[0] != "1" else "2") + row.blob[1:]
    monkeypatch.setitem(fas.SOURCES, "libc/include/x.h", row._replace(blob=wrong))
    with pytest.raises(fas.Refused) as e:
        fas.sources(cache, get=server(tgz({"x.h": good})), sleep=clock.sleep, clock=clock)
    assert row.blob in str(e.value) and wrong in str(e.value)
    assert not (cache / "libc/include/x.h").exists()


def test_nothing_is_written_until_every_archive_is_as_pinned(monkeypatch, tmp_path):
    """Archives come in path order, the good one first: a file a byte off in
    the second leaves the first's unwritten too."""
    table(monkeypatch, {"libc/arch-common/bionic/a.h": b"a\n", "libc/private/b.h": b"b\n"})
    clock = Clock()
    get = server(tgz({"a.h": b"a\n"}), tgz({"b.h": b"b, a byte on\n"}))
    with pytest.raises(fas.Refused) as e:
        fas.sources(tmp_path, get=get, sleep=clock.sleep, clock=clock)
    assert "libc/private/b.h" in str(e.value) and len(get.asked) == 2
    assert not (tmp_path / "libc/arch-common/bionic/a.h").exists()
    assert not (tmp_path / "libc/private/b.h").exists()


def test_a_pinned_file_missing_from_its_archive_is_named(monkeypatch, tmp_path):
    table(monkeypatch, {"libc/include/x.h": b"x\n"})
    clock = Clock()
    with pytest.raises(fas.Refused) as e:
        fas.sources(tmp_path, get=server(tgz({"y.h": b"y\n"})), sleep=clock.sleep, clock=clock)
    words = str(e.value)
    assert fas.archive_url("libc/include") in words and "holds no libc/include/x.h" in words
    assert "sha256" not in words and "pinned" in words.split("holds no")[1]  # the commit, not a pin


# ---- 4, 5 ---------------------------------------------------------------------


def run(get, clock, decode=None):
    return fas.fetch(
        "https://android.googlesource.com/x", decode=decode, get=get, sleep=clock.sleep, clock=clock
    )


def test_the_server_s_answers_are_waited_on_retried_or_given_up(capsys):
    # two 429s with Retry-After in seconds: each waited on, the pace already kept
    c = Clock()
    assert run(server(http_error(429, "7"), http_error(429, "7"), b"ok"), c) == b"ok"
    assert c.slept == [7, 7]
    assert (
        "asked this machine to wait (HTTP 429); trying again in 7 s (1 of 6)"
        in capsys.readouterr().err
    )
    # Retry-After as an HTTP date half a minute ahead
    fas.new_run()
    c = Clock()
    when = email.utils.format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    run(server(http_error(429, when), b"ok"), c)
    assert 28 <= c.slept[0] <= 30
    # a day, held to the cap
    fas.new_run()
    c = Clock()
    run(server(http_error(429, "86400"), b"ok"), c)
    assert c.slept == [fas.WAIT_CAP]
    # a 503, then a 200: the first back-off
    fas.new_run()
    c = Clock()
    run(server(http_error(503), b"ok"), c)
    assert c.slept == [fas.WAITS[0]]
    # a 503 with Retry-After: that, not the back-off
    fas.new_run()
    c = Clock()
    run(server(http_error(503, "3"), b"ok"), c)
    assert c.slept == [3]
    # two answers in a row: the second waits out the pace
    fas.new_run()
    c = Clock()
    run(server(b"a"), c)
    run(server(b"b"), c)
    assert c.slept == [fas.PACE]
    # a gzip cut short, then a good one: broken, never pin words
    fas.new_run()
    c = Clock()
    whole = tgz({"a.h": b"a" * 5000})
    capsys.readouterr()
    assert run(server(whole[: len(whole) // 2], whole), c, decode=fas._untar) == {
        "a.h": b"a" * 5000
    }
    err = capsys.readouterr().err
    assert "sent a broken or non-archive response" in err and "pinned" not in err
    # six 429s: the give-up words, and both ways out
    fas.new_run()
    c = Clock()
    with pytest.raises(fas.Refused) as e:
        run(server(*[http_error(429, "1")] * 6), c)
    words = str(e.value)
    assert "would not serve" in words and "after 6 tries" in words
    assert "--from" in words and "--offline" in words and "pinned" not in words
    # no network twice, then an answer
    fas.new_run()
    c = Clock()
    assert (
        run(server(urllib.error.URLError("down"), urllib.error.URLError("down"), b"ok"), c) == b"ok"
    )
    # no network at all: never connected
    fas.new_run()
    c = Clock()
    with pytest.raises(fas.Refused) as e:
        run(server(*[urllib.error.URLError("no route")] * 6), c)
    assert str(e.value).startswith("cannot reach android.googlesource.com (no route)")
    # the deadline: a wait that would pass it is not taken
    fas.new_run()
    c = Clock()
    fas._RUN["first"] = c.t - fas.DEADLINE + 5
    with pytest.raises(fas.Refused) as e:
        run(server(http_error(429, "60"), b"ok"), c)
    assert c.slept == [] and f"pass the run's {fas.DEADLINE:.0f} s" in str(e.value)


def test_a_404_is_not_tried_again():
    c = Clock()
    get = server(http_error(404), b"never")
    with pytest.raises(fas.Refused) as e:
        run(get, c)
    assert len(get.asked) == 1 and c.slept == []
    assert (
        "not found (HTTP 404): the pinned commit or path is not on android.googlesource.com"
        in str(e.value)
    )


# ---- 6 ----------------------------------------------------------------------


def broke(url):
    raise AssertionError(f"no request was to be made, and {url} was asked")


def test_a_whole_cache_makes_no_request_and_a_bad_tree_is_rebuilt_from_it(monkeypatch, tmp_path):
    files = {"libc/include/a.h": b"a\n", "libc/private/b.h": b"b\n"}
    table(monkeypatch, files)
    cache = tmp_path / fas.CACHE
    for p, d in files.items():
        (cache / p).parent.mkdir(parents=True, exist_ok=True)
        (cache / p).write_bytes(d)
    assert fas.sources(cache, get=broke) == cache
    (cache / "libc/private/b.h").unlink()
    with pytest.raises(fas.Refused) as e:
        fas.sources(cache, offline=True, get=broke)
    assert (
        "--offline" in str(e.value)
        and "libc/private/b.h" in str(e.value)
        and "(missing)" in str(e.value)
    )
    (cache / "libc/private/b.h").write_bytes(b"b, a byte on\n")
    with pytest.raises(fas.Refused) as e:
        fas.sources(cache, offline=True, get=broke)
    assert "(sha256 differs)" in str(e.value)
    c = Clock()
    get = server(tgz({"b.h": b"b\n"}))
    fas.sources(cache, get=get, sleep=c.sleep, clock=c)
    assert (
        get.asked == [fas.archive_url("libc/private")]
        and (cache / "libc/private/b.h").read_bytes() == b"b\n"
    )
    # ensure(): a tree not as recorded is built again from the whole cache, asking nothing
    built = []
    monkeypatch.setattr(fas, "mingw_tools", lambda: ("clang", "ld.lld"))
    monkeypatch.setattr(fas, "build", lambda vendor, cache, sleep=None: built.append(cache))
    a_tree(monkeypatch, tmp_path)
    (tmp_path / "android-sysroot/usr/include/a.h").write_bytes(b"a, a byte on\n")
    assert (tmp_path / fas.RECORD).is_file()  # a record there, and not the tree's
    fas.ensure(tmp_path, get=broke)
    assert built == [cache]
    # over a verified tree, neither the cache nor the build
    monkeypatch.setattr(fas, "verify", lambda vendor: [])
    monkeypatch.setattr(fas, "sources", lambda *a, **k: broke("the cache"))
    assert "is there and as recorded" in fas.ensure(tmp_path, get=broke)
    assert built == [cache]


# ---- 7, 8 ---------------------------------------------------------------------


def a_tree(monkeypatch, vendor: Path) -> dict[str, str]:
    files = {"android-sysroot/usr/include/a.h": b"a\n", "android-sysroot/usr/include/b.h": b"b\n"}
    want = {n: fas.sha256(d) for n, d in files.items()}
    monkeypatch.setattr(fas, "expected_record", lambda: dict(want))
    for n, d in files.items():
        (vendor / n).parent.mkdir(parents=True, exist_ok=True)
        (vendor / n).write_bytes(d)
    fas.write_record(vendor / fas.RECORD, want)
    return want


def test_verify_names_a_changed_byte_a_missing_file_and_an_unrecorded_one(
    monkeypatch, tmp_path, capsys
):
    a_tree(monkeypatch, tmp_path)
    assert fas.verify(tmp_path) == []
    (tmp_path / "android-sysroot/usr/include/a.h").write_bytes(b"a, a byte on\n")
    (tmp_path / "android-sysroot/usr/include/b.h").unlink()
    (tmp_path / "android-sysroot/usr/include/stdlib.h").write_bytes(b"/* not ours */\n")
    facts = fas.verify(tmp_path)
    assert facts == [
        "android-sysroot/usr/include/a.h: differs from the record",
        "android-sysroot/usr/include/b.h: recorded but missing",
        "android-sysroot/usr/include/stdlib.h: not in the record",
    ]
    assert not any("run" in f or "python" in f for f in facts)  # facts, never advice
    assert fas.main(["--verify", "--vendor", str(tmp_path)]) == 1
    assert "0 of 2 recorded Android sysroot file(s) unchanged" in capsys.readouterr().out


def test_an_unreadable_record_is_a_fact(tmp_path, capsys):
    (tmp_path / fas.RECORD).write_bytes(b"\xff\xfe not a record\n")
    facts = fas.verify(tmp_path)
    assert len(facts) == 1 and "UnicodeDecodeError" in facts[0]
    assert fas.main(["--verify", "--vendor", str(tmp_path)]) == 1
    assert "0 of 0 recorded" in capsys.readouterr().out


def test_a_record_from_another_script_is_not_this_one_s(tmp_path, capsys):
    want = fas.expected_record()
    crt = "android-sysroot/usr/lib/aarch64-linux-android/33/crtbegin_so.o"
    fas.write_record(tmp_path / fas.RECORD, dict(want, **{crt: "f" * 64}))
    facts = fas.verify(tmp_path)
    assert facts == [
        f"the record is not this script's ({crt}: recorded {'f' * 64}, this script pins {want[crt]})"
    ]
    assert fas.main(["--verify", "--vendor", str(tmp_path)]) == 1
    assert f"0 of {len(want)} recorded" in capsys.readouterr().out  # nothing was compared


# ---- 9, 15 ----------------------------------------------------------------------


@needs_mingw
@needs_cache
def test_the_crt_objects_are_the_pinned_ones_in_any_folder(monkeypatch, tmp_path):
    work = tmp_path / "a folder, with a space"
    work.mkdir()
    out = fas.build_crt(
        Path(os.path.relpath(CACHE)), work
    )  # a relative cache, as --vendor can give
    assert {p: fas.sha256(d) for p, d in out.items()} == {
        p: pin for p, pin in fas.OUTPUTS.items() if p.endswith(".o")
    }
    assert list(work.iterdir()) == []  # the build sysroot was temporary
    with pytest.raises(fas.Refused) as e:
        fas.build_crt(CACHE, work, extra=("-O0",))
    assert "crtbegin_so.o for arm64 built here has sha256" in str(e.value)
    # another clang is refused before anything is built
    monkeypatch.setattr(
        toolchain, "clang_id", lambda exe: "clang version 19.0.1 (https://example 0123456789)"
    )
    monkeypatch.setattr(fas, "_run", lambda cmd, cwd: broke("a build"))
    with pytest.raises(fas.Refused) as e:
        fas.build_crt(CACHE, work)
    assert "clang version 19.0.1" in str(e.value) and "23.1.2" in str(e.value)


@needs_mingw
@needs_cache
def test_the_environment_cannot_reach_the_crt_build(monkeypatch, tmp_path):
    poison = tmp_path / "poison"
    for d in ("asm", "aarch64-linux-android/asm", "x86_64-linux-android/asm"):
        (poison / d).mkdir(parents=True)
        (poison / d / "unistd.h").write_text("#error poisoned\n", encoding="utf-8")
    monkeypatch.setenv("CPATH", str(poison))
    monkeypatch.setenv("C_INCLUDE_PATH", str(poison))
    out = fas.build_crt(CACHE, tmp_path)
    assert all(fas.sha256(d) == fas.OUTPUTS[p] for p, d in out.items())


# ---- 10 ---------------------------------------------------------------------


@needs_cache
def test_the_notice_holds_each_file_s_own_words(monkeypatch, tmp_path):
    text = fas.notice_text(CACHE)
    assert fas.notice_text(CACHE) == text  # the same bytes every time
    assert fas.sha256(text.encode("utf-8")) == fas.OUTPUTS["NOTICE.txt"]
    sections = text.split("\n== ")[1:]
    heads = {s.split("\n", 1)[0]: s for s in sections}
    for path, place in fas.SHIP.items():
        body = heads[f"{place} (bionic {path})"]
        words = fas.leading_comments((CACHE / path).read_text(encoding="utf-8"))
        assert words and words in body, path
    for path in (p for p in fas.needed(("build",))):
        assert f"bionic {path}" in heads, path
    assert (
        "All advertising materials"
        in heads["usr/include/strings.h (bionic libc/include/strings.h)"]
    )
    # a file whose licence is its second comment: setjmp.h's tags come first
    assert (
        "Neither the name of the University"
        in heads["usr/include/setjmp.h (bionic libc/include/setjmp.h)"]
    )
    preface = text.split("\n==== ")[0]
    for name in (
        "licenses/llvm.txt",
        "licenses/linux-gpl-2.0.txt",
        "licenses/linux-syscall-note.txt",
    ):
        assert name in preface
    assert "line " not in preface
    # build() refuses a notice that is not the pinned text, recording nothing
    monkeypatch.setattr(fas, "build_crt", lambda cache: {})
    monkeypatch.setattr(fas, "notice_text", lambda cache: text + "x")
    with pytest.raises(fas.Refused) as e:
        fas.build(tmp_path, CACHE)
    assert "NOTICE.txt made here has sha256" in str(e.value)
    assert not (tmp_path / fas.RECORD).exists() and not (tmp_path / fas.DEST).exists()


def test_leading_comments_are_every_block_before_the_code():
    src = "/* $Tag$ */\n\n/*\n * the licence\n */\n// a line\n#include <x.h>\n/* not this */\n"
    assert fas.leading_comments(src) == "/* $Tag$ */\n\n/*\n * the licence\n */"


# ---- 13 ---------------------------------------------------------------------


def swap_fixture(monkeypatch, tmp_path):
    """build() with nothing compiled: no headers, no crt objects, a notice
    pinned to its own text."""
    monkeypatch.setattr(fas, "SHIP", {})
    monkeypatch.setattr(fas, "build_crt", lambda cache: {})
    monkeypatch.setattr(fas, "notice_text", lambda cache: "notice\n")
    monkeypatch.setattr(fas, "OUTPUTS", {"NOTICE.txt": fas.sha256(b"notice\n")})
    monkeypatch.setattr(fas, "mingw_tools", lambda: ("clang", "ld.lld"))
    monkeypatch.setattr(fas, "sources", lambda cache, **k: cache)
    (tmp_path / fas.DEST).mkdir()
    (tmp_path / fas.DEST / "old.h").write_text("an older tree\n", encoding="utf-8")
    # the older tree's record, which a stop must not leave beside a half-built one
    fas.write_record(tmp_path / fas.RECORD, {f"{fas.DEST}/old.h": fas.sha256(b"an older tree\n")})


def test_a_stop_inside_the_swap_leaves_no_record(monkeypatch, tmp_path, capsys):
    swap_fixture(monkeypatch, tmp_path)
    real = os.rename
    calls = []

    def rename_then_stop(src, dst):
        calls.append((Path(src).name, Path(dst).name))
        if Path(src).name == f"{fas.DEST}.new":
            raise PermissionError("held by another program")
        real(src, dst)

    monkeypatch.setattr(fas, "_rename", rename_then_stop)
    slept = []
    with pytest.raises(fas.Refused) as e:
        fas.build(tmp_path, tmp_path / fas.CACHE, sleep=slept.append)
    assert "would not let this replace" in str(e.value) and "nothing is recorded" in str(e.value)
    assert not (tmp_path / fas.RECORD).exists() and slept == list(fas._PAUSES)
    # the next run builds it again, and the leftovers go
    monkeypatch.setattr(fas, "_rename", real)
    monkeypatch.setattr(
        fas, "expected_record", lambda: {f"{fas.DEST}/NOTICE.txt": fas.sha256(b"notice\n")}
    )
    fas.ensure(tmp_path, sleep=slept.append)
    assert fas.verify(tmp_path) == []
    assert (
        not (tmp_path / f"{fas.DEST}.new").exists() and not (tmp_path / f"{fas.DEST}.old").exists()
    )
    # held twice, then let go: done
    flaky = iter([PermissionError("a moment"), PermissionError("a moment")])

    def rename_later(src, dst):
        e = next(flaky, None)
        if e:
            raise e
        real(src, dst)

    monkeypatch.setattr(fas, "_rename", rename_later)
    (tmp_path / fas.RECORD).unlink()
    fas.build(tmp_path, tmp_path / fas.CACHE, sleep=slept.append)
    assert fas.verify(tmp_path) == []
    # held always: the words from main, exit 1, no traceback
    monkeypatch.setattr(fas, "_rename", rename_then_stop)
    monkeypatch.setattr(fas.time, "sleep", lambda s: None)
    (tmp_path / fas.RECORD).unlink()
    capsys.readouterr()
    assert fas.main(["--vendor", str(tmp_path), "--offline"]) == 1
    err = capsys.readouterr().err
    assert (
        err.startswith("error: ") and "would not let this replace" in err and "Traceback" not in err
    )
    # a leftover android-sysroot.old that will not go: words too
    monkeypatch.setattr(fas, "_rename", real)
    (tmp_path / f"{fas.DEST}.old").mkdir(exist_ok=True)

    def held(path):
        raise PermissionError(13, "in use", str(path))

    monkeypatch.setattr(fas, "_rmtree", held)
    assert fas.main(["--vendor", str(tmp_path), "--offline"]) == 1
    err = capsys.readouterr().err
    assert "would not let this clear" in err and "Traceback" not in err


# ---- 14 ---------------------------------------------------------------------


def test_the_tool_runs_as_a_package_runs_it(tmp_path):
    tools = tmp_path / "tools"
    shutil.copytree(
        ROOT / "tools" / "soa", tools / "soa", ignore=shutil.ignore_patterns("__pycache__")
    )
    script = (ROOT / "tools" / "fetch_android_sysroot.py").read_text(encoding="utf-8")
    (tools / "fetch_android_sysroot.py").write_text(script, encoding="utf-8")
    cmd = [
        sys.executable,
        "-I",
        str(tools / "fetch_android_sysroot.py"),
        "--verify",
        "--vendor",
        str(tmp_path / "v"),
    ]
    ok = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert "0 of 0 recorded Android sysroot file(s) unchanged" in ok.stdout, ok.stderr
    line = "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
    assert script.count(line) == 1
    (tools / "fetch_android_sysroot.py").write_text(script.replace(line, ""), encoding="utf-8")
    gone = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert gone.returncode != 0 and "No module named 'soa'" in gone.stderr


# ---- 17 ---------------------------------------------------------------------


def listing_server(tag_commit: str, change: str | None = None):
    import json

    def get(url):
        if "/+/refs/tags/" in url:
            return (")]}'\n" + json.dumps({"commit": tag_commit})).encode()
        directory = url.split(f"/+/{fas.COMMIT}/", 1)[1].split("?", 1)[0]
        entries = [
            {"name": p.rsplit("/", 1)[1], "id": "0" * 40 if p == change else s.blob}
            for p, s in fas.SOURCES.items()
            if p.rsplit("/", 1)[0] == directory
        ]
        return (")]}'\n" + json.dumps({"entries": entries})).encode()

    return get


def test_upstream_s_listing_is_held_to_the_pins():
    c = Clock()
    assert fas.check_upstream(get=listing_server(fas.COMMIT), sleep=c.sleep, clock=c) == ([], 47)
    fas.new_run()
    # one pin in each directory, the check lists' and linux/version.h's among them
    for change in sorted({p.rsplit("/", 1)[0]: p for p in fas.SOURCES}.values()):
        fas.new_run()
        bad, n = fas.check_upstream(
            get=listing_server(fas.COMMIT, change=change), sleep=c.sleep, clock=c
        )
        assert bad == [f"{change}: bionic's blob is {'0' * 40}, pinned {fas.SOURCES[change].blob}"]
        assert n == 47
    fas.new_run()
    bad, _ = fas.check_upstream(get=listing_server("1" * 40), sleep=c.sleep, clock=c)
    assert bad == [f"refs/tags/{fas.TAG} is {'1' * 40}, not {fas.COMMIT}"]


def test_the_check_lists_come_as_text_and_are_held_to_their_pins(monkeypatch, tmp_path):
    lst = b"LIBC {\n  global:\n    setjmp;\n};\n"
    table(monkeypatch, {"libc/libc.map.txt": lst}, role="check")
    monkeypatch.setattr(fas, "TEXT_FILES", ("libc/libc.map.txt",))
    c = Clock()
    get = server(base64.b64encode(lst))
    fas.sources(tmp_path, roles=("check",), get=get, sleep=c.sleep, clock=c)
    assert (
        get.asked == [fas.text_url("libc/libc.map.txt")]
        and (tmp_path / "libc/libc.map.txt").read_bytes() == lst
    )
    other = tmp_path / "other"
    with pytest.raises(fas.Refused) as e:
        fas.sources(
            other,
            roles=("check",),
            get=server(base64.b64encode(lst + b" ")),
            sleep=c.sleep,
            clock=c,
        )
    assert "libc/libc.map.txt" in str(e.value) and fas.sha256(lst) in str(e.value)
    assert not (other / "libc/libc.map.txt").exists()


def test_from_fills_the_cache_with_what_is_as_pinned_and_names_the_rest(
    monkeypatch, tmp_path, capsys
):
    files = {"libc/include/a.h": b"a\n", "libc/include/b.h": b"b\n", "libc/private/c.h": b"c\n"}
    table(monkeypatch, files)
    src = tmp_path / "bionic"
    (src / "libc/include").mkdir(parents=True)
    (src / "libc/include/a.h").write_bytes(b"a\n")
    (src / "libc/include/b.h").write_bytes(b"b, a byte on\n")
    cache = tmp_path / fas.CACHE
    problems = fas.fill_from(src, cache)
    out = capsys.readouterr().out
    assert out.startswith(f"1 of 3 bionic files the build reads, from {src}, are as pinned")
    assert problems == [
        f"libc/include/b.h: sha256 {fas.sha256(b'b, a byte on' + bytes([10]))}, pinned {fas.sha256(b'b' + bytes([10]))}",
        f"libc/private/c.h: not in {src}",
    ]
    assert (cache / "libc/include/a.h").exists() and not (cache / "libc/include/b.h").exists()


# ---- 11, 12, 16 (R5a part 2): the closure, bionic's placement, --compare ----

SYSROOT = toolchain.android_sysroot()
needs_sysroot = pytest.mark.skipif(
    SYSROOT is None or toolchain.mingw_clang() is None,
    reason="no llvm-mingw or no Android sysroot (python tools/fetch_mingw.py, then python tools/fetch_android_sysroot.py)",
)
needs_lists = pytest.mark.skipif(
    not all((CACHE / p).is_file() for p in fas.TEXT_FILES),
    reason="no check lists (python tools/fetch_android_sysroot.py --lists)",
)


def headers_read(stderr: str) -> list[Path]:
    """The headers clang -H names, one a line after its depth's dots, each
    path whole, spaces kept."""
    out = []
    for line in stderr.splitlines():
        dots = len(line) - len(line.lstrip("."))
        if dots and line[dots : dots + 1] == " ":
            out.append(Path(line[dots + 1 :].rstrip()))
    return out


def test_the_include_parser_keeps_a_path_whole():
    text = ". C:/Skies, the game/runtime/cpu.h\n.. C:/a b/usr/include/math.h\nMultiple include guards may be useful for:\n"
    assert headers_read(text) == [
        Path("C:/Skies, the game/runtime/cpu.h"),
        Path("C:/a b/usr/include/math.h"),
    ]


def closure(p, runtime: Path, tmp: Path) -> subprocess.CompletedProcess:
    unit = tmp / f"closure-{p.name}.c"
    unit.write_text(
        '#include "cpu.h"\n#include "soa_game.h"\n#include <stddef.h>\n#include <stdint.h>\n',
        encoding="utf-8",
    )
    cmd = [
        toolchain.mingw_clang(),
        f"--sysroot={SYSROOT}",
        *p.cflags,
        f"-I{runtime}",
        "-fsyntax-only",
        "-H",
        str(unit),
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=toolchain.clean_clang_env(),
        check=False,
    )


@needs_sysroot
def test_the_sysroot_is_the_closure_of_what_the_game_includes(tmp_path):
    root = SYSROOT.resolve()
    seen = set()
    for p in toolchain.ANDROID:
        run = closure(p, ROOT / "runtime", tmp_path)
        assert run.returncode == 0, run.stderr
        read = {
            h.resolve().relative_to(root).as_posix()
            for h in headers_read(run.stderr)
            if h.resolve().is_relative_to(root)
        }
        other = "x86_64-linux-android" if p.name == "android-arm64" else "aarch64-linux-android"
        want = {place for place in fas.SHIP.values() if f"/{other}/" not in place}
        assert read == want, (p.name, sorted(read ^ want))
        seen |= read
    unused = set(fas.SHIP.values()) - seen
    assert not unused, f"shipped and read by no compile: {sorted(unused)}"
    # a new include the sysroot does not hold fails, naming it
    copy = tmp_path / "runtime"
    shutil.copytree(ROOT / "runtime", copy, ignore=shutil.ignore_patterns("*.obj", "*.o"))
    cpu = copy / "cpu.h"
    cpu.write_text("#include <stdlib.h>\n" + cpu.read_text(encoding="utf-8"), encoding="utf-8")
    run = closure(toolchain.ANDROID_X86_64, copy, tmp_path)
    assert run.returncode != 0 and "stdlib.h" in run.stderr


def libc_block(text: str) -> dict[str, str]:
    """The names in a symbol list's LIBC block, each with its comment."""
    out = {}
    inside = False
    for line in text.splitlines():
        if line.startswith("LIBC {"):
            inside = True
        elif inside and line.startswith("}"):
            break
        elif inside and line.strip().endswith(";") or (inside and ";" in line):
            name, _, comment = line.strip().partition(";")
            if name and " " not in name and name not in ("global:", "local:"):
                out[name] = comment
    return out


@needs_lists
def test_the_seam_s_c_library_names_are_bionic_s():
    import re

    from soa import seam

    the_seam = seam.read_seam(ROOT / "config" / "seam.txt")
    lists = {
        "libc.so": libc_block((CACHE / "libc/libc.map.txt").read_text(encoding="utf-8")),
        "libm.so": libc_block((CACHE / "libm/libm.map.txt").read_text(encoding="utf-8")),
    }
    for lib, names in seam.c_library_names(the_seam).items():
        for name in names:
            assert name in lists[lib], f"{name} is not in {lib}'s LIBC block"
            for level in re.findall(r"introduced(?:-(?:arm64|x86_64))?=(\d+)", lists[lib][name]):
                assert int(level) <= 33, (name, level)
    # and the placement is bionic's: no libc name defined in the other list
    for name in the_seam.libc:
        where = "libm.so" if name in seam.BIONIC_LIBM else "libc.so"
        other = "libc.so" if where == "libm.so" else "libm.so"
        assert name in lists[where] and name not in lists[other], name


@needs_sysroot
def test_compare_names_an_object_that_differs(tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "chunk_000.c").write_text(
        '#include "cpu.h"\n#include <math.h>\ndouble g(double x) { return sqrt(x); }\n',
        encoding="utf-8",
    )
    copy = tmp_path / "sysroot"
    shutil.copytree(SYSROOT, copy)
    units, differ = fas.compare(SYSROOT, copy, gen, "android-x86_64")
    assert (units, differ) == (["chunk_000.c"], [])
    math = copy / "usr" / "include" / "math.h"
    math.write_text(
        math.read_text(encoding="utf-8") + "#define sqrt(x) ((x) * 2.0)\n", encoding="utf-8"
    )
    assert fas.compare(SYSROOT, copy, gen, "android-x86_64") == (["chunk_000.c"], ["chunk_000.c"])
