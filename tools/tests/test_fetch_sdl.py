"""SDL3, fetched and built for the window and sound off Windows (portability L10).

tools/fetch_sdl.py pins SDL3's source archive and refuses any other bytes; it
records every file its build installs, and --verify finds one changed by a
byte or missing, for this host's build alone. What SDL's build config says
was built is read as drivers, not their features; what a static libSDL3.a
needs after it is read from sdl3.pc, as SDL writes it. With a build in
vendor/sdl3, the Linux link compiles every runtime file with SOA_SDL and the
headers, and puts the library after the objects and before the profile's
own libraries; without one, the link is as it was. On Windows the build is
refused: Windows keeps its own window (D2).
"""

import hashlib
import io
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_sdl  # noqa: E402
import recompile  # noqa: E402
from soa import toolchain  # noqa: E402


def archive(files: dict[str, bytes]) -> bytes:
    """A .tar.gz with these files under SDL3-<version>/."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(f"SDL3-{fetch_sdl.VERSION}/{name}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_a_download_that_is_not_the_pinned_archive_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not the pinned"):
        fetch_sdl.source(tmp_path, get=lambda url: archive({"CMakeLists.txt": b"x"}))
    assert not (tmp_path / "sdl3").exists()


def test_the_pinned_archive_is_unpacked_once_and_its_headers_found(tmp_path, monkeypatch):
    blob = archive({"CMakeLists.txt": b"project(SDL3)\n", "include/SDL3/SDL.h": b"/* SDL */\n"})
    monkeypatch.setattr(fetch_sdl, "PIN", hashlib.sha256(blob).hexdigest())
    asked = []
    src = fetch_sdl.source(tmp_path, get=lambda url: asked.append(url) or blob)
    assert asked == [fetch_sdl.URL] and (src / "CMakeLists.txt").exists()
    assert (fetch_sdl.headers(tmp_path) / "SDL3" / "SDL.h").exists()

    def no_second_fetch(url):
        raise AssertionError("fetched again")

    assert fetch_sdl.source(tmp_path, get=no_second_fetch) == src


def installed(vendor: Path) -> Path:
    """A stand-in install under vendor/sdl3/<host>, recorded."""
    h = fetch_sdl.host_dir(vendor)
    (h / "include" / "SDL3").mkdir(parents=True)
    (h / "lib" / "pkgconfig").mkdir(parents=True)
    (h / "include" / "SDL3" / "SDL.h").write_bytes(b"/* SDL */\n")
    (h / "lib" / "libSDL3.a").write_bytes(b"!<arch>\n")
    (h / "lib" / "pkgconfig" / "sdl3.pc").write_text(
        "Libs: -L${libdir}  -lSDL3   -pthread -lm\n", encoding="utf-8"
    )
    files = {
        p.relative_to(vendor).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in h.rglob("*")
        if p.is_file()
    }
    files["sdl3/linux-otherarch/lib/libSDL3.a"] = "0" * 64  # another host's, not on this one
    fetch_sdl.write_record(vendor / fetch_sdl.RECORD, files, ["# test"])
    return h


def test_verify_finds_a_changed_byte_and_a_missing_file_of_this_host_s_build(tmp_path):
    h = installed(tmp_path)
    assert fetch_sdl.available(tmp_path) and fetch_sdl.verify(tmp_path) == []
    (h / "include" / "SDL3" / "SDL.h").write_bytes(b"/* SDL! */\n")
    (h / "lib" / "pkgconfig" / "sdl3.pc").unlink()
    bad = fetch_sdl.verify(tmp_path)
    assert len(bad) == 2, bad
    assert any("SDL.h: sha256 differs" in b for b in bad)
    assert any("sdl3.pc: recorded but missing" in b for b in bad)


def test_with_no_build_recorded_verify_says_how_to_make_one(tmp_path):
    assert fetch_sdl.verify(tmp_path) == [
        f"no {fetch_sdl.host_name()} build in {tmp_path / fetch_sdl.RECORD}: run tools/fetch_sdl.py first"
    ]


CONFIG = """
#define SDL_VIDEO_DRIVER_DUMMY 1
#define SDL_VIDEO_DRIVER_X11 1
#define SDL_VIDEO_DRIVER_X11_DYNAMIC "libX11.so.6"
#define SDL_VIDEO_DRIVER_X11_XRANDR 1
/* #undef SDL_VIDEO_DRIVER_KMSDRM */
#define SDL_VIDEO_DRIVER_WAYLAND 1
#define SDL_AUDIO_DRIVER_PIPEWIRE 1
#define SDL_AUDIO_DRIVER_PIPEWIRE_DYNAMIC "libpipewire-0.3.so.0"
#define SDL_AUDIO_DRIVER_ALSA 1
"""


def test_the_build_config_names_drivers_not_their_features():
    assert fetch_sdl.drivers(CONFIG) == {
        "video": ["dummy", "x11", "wayland"],
        "audio": ["pipewire", "alsa"],
    }


def test_what_the_static_library_needs_comes_from_sdl3_pc():
    static_only = "Libs: -L${libdir}  -lSDL3   -pthread -lm\n"
    both = "Libs: -L${libdir} -lSDL3\nLibs.private: -lm -ldl -pthread -lrt\n"
    assert fetch_sdl.pc_libs(static_only) == ["-pthread", "-lm"]
    assert fetch_sdl.pc_libs(both) == ["-lm", "-ldl", "-pthread", "-lrt"]


def test_the_linux_link_builds_the_window_in_with_sdl_and_links_it_after_the_objects(tmp_path):
    h = installed(tmp_path)
    sdl = fetch_sdl.link_args(tmp_path)
    assert sdl == (
        ["/DSOA_SDL=1", f"/I{h / 'include'}"],
        [str(h / "lib" / "libSDL3.a"), "-pthread", "-lm"],
    )
    out = Path("gen/linux")
    link, cwd = recompile.link_plan(toolchain.GCC, out, [], [], sdl=sdl)[0]
    assert cwd == Path(".")
    first_source = min(i for i, a in enumerate(link) if a.endswith(".c"))
    last_input = max(i for i, a in enumerate(link) if a.endswith((".c", ".o")))
    assert (
        link.index("/DSOA_SDL=1") < first_source and link.index(f"/I{h / 'include'}") < first_source
    )
    lib = link.index(str(h / "lib" / "libSDL3.a"))
    assert last_input < lib < len(link) - len(toolchain.GCC.linker)
    assert link[-len(toolchain.GCC.linker) :] == list(toolchain.GCC.linker)
    assert any(a.endswith("window_sdl.c") for a in link) and any(
        a.endswith("audio_sdl.c") for a in link
    )
    # with no SDL the link is as it was: no SOA_SDL, no library
    plain, _ = recompile.link_plan(toolchain.GCC, out, [], [])[0]
    assert "/DSOA_SDL=1" not in plain and not any("libSDL3" in a for a in plain)


def test_on_windows_the_build_is_refused(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(fetch_sdl.platform, "system", lambda: "Windows")
    assert fetch_sdl.main(["--vendor", str(tmp_path)]) == 1
    assert "Windows keeps its own window and waveOut (D2)" in capsys.readouterr().err
