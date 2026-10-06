"""Build runtime/disc.c on its own and hold it to synthetic disc images.

    python tools/citest/disc_check.py [--cc PROFILE] [--cflag FLAG]... [--out DIR]
                                      [--mutate fst-offset]
    python tools/citest/disc_check.py --log LOG --data DIR

disc-layer I1 (docs/specs/disc-layer.md §6). The first form writes a fixture
image (tools/soa/discfixture.py: a test game id, a fake executable, nested
directories, abutting files, zero and junk gaps, a tail), builds disc.c with
that id and that executable's SHA-1 in place of the real ones, and checks:

  - the executable, boot.bin and file table disc.c hands back are the exact
    slices the fixture placed, from a directory holding disc.iso and from
    the image named directly;
  - every file read as the game's reader reads it (its length rounded up to
    32, reaching the next file's first bytes) is the image's bytes, and a
    read past the image's end is the image's last bytes then zeros, counted;
  - each file is named at its first and last byte, and padding, junk gaps
    and the system area are named by none;
  - ten images are refused, each with its own words: no image, an RVZ, bad
    boot magic, another game id, another revision, the file table past the
    end, a truncated image ending inside it, an executable section past the
    end, an executable with one byte changed, and a malformed file table;
  - built as --no-embed builds it (I3), it has no system files of its own;
    built with the fixture's in its disc_sys.c, it hands them back with no
    image open, opens their image saying the table matches, refuses an image
    whose table differs by one byte as not the build's, and a built-in copy
    that misses its own SHA-1 is refused before anything is handed out.

--mutate fst-offset moves the fixture's file-table offset by 4, which must
fail it. The second form checks a live run's SOA_DISC_LOG=1 lines against the
file table as tools/soa/disc.py parses it -- an independent parser, not
disc_name_at: every read names the file that holds its offset, with the right
count of bytes past that file's end, and none names no file.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import discfixture, embed, store, toolchain  # noqa: E402
from soa.disc import Disc, ImageFile  # noqa: E402

PROF = toolchain.MSVC  # --cc sets it

HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
LOG_LINE = re.compile(
    r"^\[disc\] frame (\d+) read 0x([0-9A-Fa-f]+) \+(\d+) (.+?)(?:, (\d+) past its end)?$"
)


def sha1(b: bytes) -> str:
    return hashlib.sha1(b, usedforsecurity=False).hexdigest()


def run_cl(what: str, args: list[str]) -> bool:
    proc = toolchain.cc(args, ROOT, PROF)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        print(out)
    if proc.returncode != 0:
        print(f"::error::{what} failed", file=sys.stderr)
        return False
    return True


def build(
    out: Path,
    game_id: str,
    dol_sha1: str,
    cflags: list[str],
    system: dict[str, bytes] | None = None,
    disc_sys: str | None = None,
) -> Path | None:
    """disc.c with the fixture's id and executable hash, sha1.c, the driver,
    and a disc_sys.c: `system` built in (I3), or none, as --no-embed; or
    `disc_sys` as given, for a broken one."""
    out.mkdir(parents=True, exist_ok=True)
    wrapper = out / "disc_fixture.c"
    wrapper.write_text(
        f"/* disc.c built for a synthetic image (disc_check.py) */\n"
        f'#define DISC_GAME_ID "{game_id}"\n#define DISC_DOL_SHA1 "{dol_sha1}"\n'
        f'#include "disc.c"\n',
        encoding="utf-8",
    )
    text = disc_sys if disc_sys is not None else embed.disc_sys_c(system)
    (out / "disc_sys.c").write_text(text, encoding="utf-8")
    sources = [wrapper, RUNTIME / "sha1.c", HERE / "disc_driver.c", out / "disc_sys.c"]
    if not run_cl(
        "compiling disc.c",
        [*PROF.cflags, *cflags, "/c", f"/I{RUNTIME}", f"/Fo{out}/", *map(str, sources)],
    ):
        return None
    exe = out / f"disc_driver{PROF.exeext}"
    objs = [out / (s.stem + PROF.objext) for s in sources]
    if not run_cl(
        "linking disc.c", [*PROF.cflags, *cflags, *map(str, objs), f"/Fe:{exe}", *PROF.linker]
    ):
        return None
    return exe


def drive(
    exe: Path,
    cmds: list[str],
    env: dict[str, str] | None = None,
    code: int = 0,
    pass_fds: tuple[int, ...] = (),
) -> tuple[list[str], str]:
    """The driver's answers to `cmds`, with the disc layer's switches only as
    `env` gives them; it must exit `code` (9 is the disc layer's stop).
    `pass_fds` are descriptors the driver inherits under the same numbers."""
    full = {k: v for k, v in os.environ.items() if not k.startswith("SOA_DISC_")}
    full.update(env or {})
    proc = subprocess.run(
        [str(exe)],
        input="\n".join(cmds) + "\n",
        capture_output=True,
        text=True,
        timeout=120,
        env=full,
        pass_fds=pass_fds,
    )
    if proc.returncode != code:
        raise RuntimeError(
            f"the driver exited {proc.returncode}, not {code}: {proc.stderr[-2000:]}"
        )
    return proc.stdout.splitlines(), proc.stderr


class Checks:
    def __init__(self) -> None:
        self.failed = 0
        self.passed = 0

    def check(self, ok: bool, what: str) -> None:
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            print(f"FAIL {what}")


def broken_images(fx: discfixture.Fixture, out: Path) -> dict[str, tuple[Path, str]]:
    """name -> (image, words its refusal must hold). Each from the good one."""
    img = fx.image
    dol_off, _ = fx.slices["main.dol"]
    fst_off, fst_len = fx.slices["fst.bin"]
    cases: dict[str, tuple[bytes | None, str]] = {}

    def patched(at: int, fmt: str, value: int) -> bytes:
        b = bytearray(img)
        struct.pack_into(fmt, b, at, value)
        return bytes(b)

    cases["bad boot magic"] = (patched(0x1C, ">I", 0), "boot magic")
    other = "GTSP01" if fx.game_id != "GTSP01" else "GTSJ01"
    cases["another game id"] = (other.encode() + img[6:], f"is {other}, not {fx.game_id}")
    cases["another revision"] = (img[:7] + b"\x01" + img[8:], "revision 1")
    cases["file table past the end"] = (
        patched(0x424, ">I", len(img) + 0x1000),
        "the file table starts",
    )
    cases["truncated inside the file table"] = (
        img[: fst_off + fst_len // 2],
        "the image ends inside the file table",
    )
    # the last data slot's offset moved past the image: the section-bound
    # refusal, before the executable is hashed
    cases["executable section past the end"] = (
        patched(dol_off + 0x1C + 4 * 2, ">I", len(img)),
        "a section of the executable lies past the image's end",
    )
    b = bytearray(img)
    b[dol_off + 0x180] ^= 1
    cases["executable with one byte changed"] = (
        bytes(b),
        "executable is not the one this port was built for",
    )
    # the root entry's count past the table: nothing in it can be trusted
    cases["malformed file table"] = (
        patched(fst_off + 8, ">I", 0x7FFFFFFF),
        "the file table is malformed",
    )
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, tuple[Path, str]] = {}
    for n, (name, (data, words)) in enumerate(cases.items()):
        p = out / f"broken{n}.iso"
        p.write_bytes(data)
        result[name] = (p, words)
    # disc.c names Dolphin's format by its first four bytes, so a header is
    # enough, and needs no zstd on a runner whose Python lacks it
    rvz = out / "image.rvz"
    rvz.write_bytes(b"RVZ\x01" + bytes(0x1000))
    result["an RVZ"] = (rvz, "RVZ/WIA format")
    empty = out / "empty"
    empty.mkdir(exist_ok=True)
    result["no image"] = (empty, "no disc image at")
    return result


def check_built_in(c: Checks, fx: discfixture.Fixture, out: Path, cflags: list[str]) -> None:
    """I3: the fixture's system files built in. disc_system hands them back
    with no image open; the image they came from opens and is said to match;
    one whose file table differs by a byte is refused as not the build's; a
    built-in copy that does not hash to its own SHA-1 is refused at once.
    And the --no-embed build (the checks above) has none to give."""
    want = [
        "system ok",
        f"dol {len(fx.system['main.dol'])} {sha1(fx.system['main.dol'])}",
        f"boot 1088 {sha1(fx.system['boot.bin'])}",
        f"fst {len(fx.system['fst.bin'])} {sha1(fx.system['fst.bin'])}",
    ]
    plain = out / "image" / f"disc_driver{PROF.exeext}"
    lines, _ = drive(plain, ["builtin", "system"])
    c.check(lines[:1] == ["builtin 0 "], f"--no-embed: builtin says {lines[:1]}")
    c.check(
        lines[1:2] == ["refused no disc image is open"], f"--no-embed: system says {lines[1:2]}"
    )

    exe = build(out / "embedded", fx.game_id, fx.dol_sha1, cflags, fx.system)
    c.check(exe is not None, "the embedding build compiles")
    if exe is None:
        return
    b = bytearray(fx.image)
    fst_off, _ = fx.slices["fst.bin"]
    names = fst_off + struct.unpack_from(">I", b, fst_off + 8)[0] * 12
    b[names] ^= 0x20  # one letter of the first name, upper case: the table still parses
    other = out / "embedded" / "other.iso"
    other.write_bytes(bytes(b))
    lines, err = drive(exe, ["builtin", "system", f"open {fx.path}", f"open {other}"])
    c.check(lines[:1] == ["builtin 1 "], f"embedded: builtin says {lines[:1]}")
    c.check(lines[1:5] == want, f"embedded, no image open: {lines[1:5]}")
    c.check(lines[5:6] == ["open ok"], f"embedded, its own image: {lines[5:6]}")
    c.check("; FST matches this build" in err, "the open line says the table is the build's")
    refusal = lines[9] if len(lines) > 9 else ""
    c.check(
        refusal.startswith("refused this disc image is not the one this build was made from"),
        f"embedded, an image whose table differs by one byte: {refusal!r}",
    )

    # a built-in copy that is not what its own SHA-1 says: a generator fault
    bad = embed.disc_sys_c(fx.system).replace(sha1(fx.system["fst.bin"]), "0" * 40)
    exe = build(out / "broken-embed", fx.game_id, fx.dol_sha1, cflags, disc_sys=bad)
    c.check(exe is not None, "the broken embedding build compiles")
    if exe is not None:
        lines, _ = drive(exe, ["builtin", "system"])
        c.check(
            lines[:1] != [] and lines[0].startswith("builtin -1 the file table built into"),
            f"a built-in table that misses its SHA-1: {lines[:1]}",
        )
        c.check(lines[1:2] != [] and lines[1].startswith("refused "), "and nothing is handed out")


def check_store(c: Checks, fx: discfixture.Fixture, out: Path, exe: Path) -> None:
    """I5: the store backend, on a store tools/soa/store.py writes from the
    fixture with a long tail. The C reader gives the image's bytes at every
    offset below the covered end, zeros above, and is preferred in a folder;
    every block a read touches is hashed; SOA_DISC_VERIFY=all compares each
    read with the ISO and finds nothing; a flipped byte is caught by both
    checks -- the ISO comparison names its offset, and the hash check stops
    the run, exit 9, naming the file; three broken stores are refused at
    open; --check-disc's check passes the store and fails the flip."""
    sfx = discfixture.build(out / "store" / "disc.iso", tail=3 << 20)
    c.check(sfx.dol_sha1 == fx.dol_sha1, "the long-tailed fixture has the same executable")
    path = out / "store" / f"{sfx.game_id}{store.STORE_SUFFIX}"
    path.unlink(missing_ok=True)
    reader = ImageFile(sfx.path)
    try:
        st = store.write(reader, len(sfx.image), path, store.SOURCE_ISO, "disc_check.py").header
    finally:
        reader.close()
    folder, img, covered = path.parent, sfx.image, st.covered_end
    c.check(covered < len(img), f"the store covers less than the image ({covered} of {len(img)})")
    reads = []
    for name, off in sorted(sfx.offsets.items(), key=lambda kv: kv[1]):
        n = (len(sfx.files[name]) + 31) & ~31
        reads.append((name, off, n))
    serve = [f"serve {off} {n}" for _, off, n in reads]
    want = [f"serve {sha1(img[off : off + n])}" for _, off, n in reads]

    lines, err = drive(
        exe, [f"open {folder}", f"peek 0 {covered}", f"peek {covered} 4096", *serve, "report"]
    )
    c.check(
        lines[:1] == ["open ok"] and " store v1" in err, f"the folder opens its store: {lines[:1]}"
    )
    c.check(
        lines[4:5] == [f"peek {covered} {sha1(img[:covered])}"],
        "every offset below the covered end",
    )
    c.check(lines[5:6] == [f"peek 0 {sha1(bytes(4096))}"], "zeros above it")
    c.check(lines[6 : 6 + len(want)] == want, "each file read as the game reads it")
    c.check(
        "[disc] hashed " in err and "[disc] backend store;" in err,
        "the report names the store and its hashing",
    )

    lines, err = drive(exe, [f"open {folder}", *serve, "report"], {"SOA_DISC_VERIFY": "all"})
    c.check(
        f"[disc] verify: {len(reads)} reads compared with" in err and ", 0 differ, 0 past" in err,
        f"every read compared with the ISO, none differing: {err.strip()[-200:]!r}",
    )

    victim, at, n = reads[3]
    env = {"SOA_DISC_VERIFY": "iso", "SOA_DISC_FLIP": victim}
    lines, err = drive(exe, [f"open {folder}", f"serve {at} {n}", "report"], env)
    c.check(
        "differs from" in err and f"first at disc offset 0x{at:X}" in err and ", 1 differ," in err,
        f"the ISO comparison finds the flipped byte: {err.strip()[-300:]!r}",
    )
    lines, err = drive(
        exe, [f"open {folder}", f"serve {at} {n}"], {"SOA_DISC_FLIP": victim}, code=9
    )
    c.check(
        "does not match its SHA-1" in err and victim in err and "re-import" in err,
        f"the hash check stops the run, exit 9, naming the file: {err.strip()[-300:]!r}",
    )

    data = path.read_bytes()
    broken = {
        "header hash": (
            bytes(data[:0x30]) + bytes([data[0x30] ^ 1]) + data[0x31:],
            "do not match their SHA-1",
        ),
        "truncated payload": (data[:-1], "truncated"),
        "format 2": (data[:8] + (2).to_bytes(4, "little") + data[12:], "store format 2"),
    }
    for what, (blob, words) in broken.items():
        bad = out / "store" / f"broken-{what.replace(' ', '-')}.soadisc"
        bad.write_bytes(blob)
        lines, _ = drive(exe, [f"open {bad}"])
        c.check(
            lines[:1] != [] and lines[0].startswith("refused ") and words in lines[0],
            f"{what}: {lines[:1]}",
        )
    lines, _ = drive(exe, [f"open {sfx.path}"], {"SOA_DISC_VERIFY": "hash"})
    c.check(
        lines[:1] != [] and "is an ISO" in lines[0],
        f"a hash check of an ISO is refused: {lines[:1]}",
    )

    lines, err = drive(exe, [f"checkstore {path}"])
    c.check(
        lines[-1:] == ["checkstore 0"] and ", 0 and 0 differ;" in err,
        f"--check-disc passes: {err.strip()[-200:]!r}",
    )
    lines, err = drive(exe, [f"checkstore {path}"], {"SOA_DISC_FLIP": f"0x{at:X}"})
    c.check(
        lines[-1:] == ["checkstore 9"] and victim in err,
        f"--check-disc fails the flip: {err.strip()[-200:]!r}",
    )


def check_descriptors(c: Checks, fx: discfixture.Fixture, out: Path, exe: Path) -> None:
    """Off Windows, a disc handed over open, as /proc/self/fd/N (specs/android.md
    L12d: Android's file picker gives the app a descriptor, never a path it
    may open again). The image is read through the descriptor itself: once it
    is open its file is made unreadable by name, so code that opened the path
    again would be refused (for anyone but root, which reads it anyway: then
    that half is said to be unproven). A store with no suffix is known by its
    contents, and a pipe is refused as a stream."""
    if os.name == "nt":
        return
    folder = out / "fd"
    folder.mkdir(parents=True, exist_ok=True)
    want = {
        "dol": f"dol {len(fx.system['main.dol'])} {sha1(fx.system['main.dol'])}",
        "boot": f"boot {0x440} {sha1(fx.system['boot.bin'])}",
        "fst": f"fst {len(fx.system['fst.bin'])} {sha1(fx.system['fst.bin'])}",
    }

    image = folder / "picked-image"
    image.write_bytes(fx.image)
    fd = os.open(image, os.O_RDONLY)
    try:
        image.chmod(0)
        try:
            os.close(os.open(f"/proc/self/fd/{fd}", os.O_RDONLY))
            print("  the descriptor cases run as root: opening the path again is not refused here")
        except PermissionError:
            pass
        lines, err = drive(exe, [f"open /proc/self/fd/{fd}"], pass_fds=(fd,))
        c.check(lines[:1] == ["open ok"], f"an image read through its descriptor: {lines[:1]}")
        c.check(lines[1:4] == list(want.values()), "and its system files are the image's")
        c.check(
            f"[disc] /proc/self/fd/{fd}: " in err, "the [disc] line names the descriptor's path"
        )
    finally:
        image.chmod(0o644)
        os.close(fd)

    store_path = out / "store" / f"{fx.game_id}{store.STORE_SUFFIX}"
    if store_path.exists():
        picked = folder / "picked-store"
        picked.write_bytes(store_path.read_bytes())
        fd = os.open(picked, os.O_RDONLY)
        try:
            lines, err = drive(exe, [f"open /proc/self/fd/{fd}"], pass_fds=(fd,))
            c.check(lines[:1] == ["open ok"], f"a store with no suffix, by descriptor: {lines[:1]}")
            c.check(" store v1" in err, "and it is read as the store it is")
        finally:
            os.close(fd)
    else:
        c.check(False, f"no store at {store_path} to pick")

    r, w = os.pipe()
    try:
        os.write(w, fx.image[:4096])
        os.close(w)
        w = -1
        lines, _ = drive(exe, [f"open /proc/self/fd/{r}"], pass_fds=(r,))
        c.check(
            lines[:1] != [] and lines[0].startswith("refused ") and "is a stream" in lines[0],
            f"a pipe is refused as a stream: {lines[:1]}",
        )
    finally:
        os.close(r)
        if w >= 0:
            os.close(w)


def check_fixture(out: Path, cflags: list[str], mutate: str | None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    fx = discfixture.build(out / "good" / "disc.iso")
    if mutate == "fst-offset":  # the mutation: the file table's offset moved by 4
        b = bytearray(fx.image)
        struct.pack_into(">I", b, 0x424, struct.unpack_from(">I", b, 0x424)[0] + 4)
        fx.path.write_bytes(bytes(b))
    exe = build(out / "image", fx.game_id, fx.dol_sha1, cflags)  # --no-embed's: the image's own
    if exe is None:
        return 1
    c = Checks()
    img = fx.image
    size = len(img)

    # the system files, from the directory and from the image named directly
    for where in (fx.path.parent, fx.path):
        lines, _ = drive(exe, [f"open {where}"])
        c.check(lines[:1] == ["open ok"], f"open {where}: {lines[:1]}")
        want = {
            "dol": (len(fx.system["main.dol"]), sha1(fx.system["main.dol"])),
            "boot": (0x440, sha1(fx.system["boot.bin"])),
            "fst": (len(fx.system["fst.bin"]), sha1(fx.system["fst.bin"])),
        }
        for ln in lines[1:4]:
            kind, n, digest = ln.split()
            c.check(
                (int(n), digest) == want[kind], f"{where}: {kind} is {n} {digest}, not {want[kind]}"
            )

    # reads, as the game's reader makes them, and one past the image's end
    cmds = [f"open {fx.path}"]
    expect: list[str] = []
    for path, off in sorted(fx.offsets.items(), key=lambda kv: kv[1]):
        n = (len(fx.files[path]) + 31) & ~31
        cmds.append(f"serve {off} {n}")
        want = img[off : off + n]
        expect.append(f"serve {sha1(want + bytes(n - len(want)))}")
    cmds.append(f"serve {size - 100} 300")
    expect.append(f"serve {sha1(img[-100:] + bytes(200))}")
    cmds.append(f"peek {size - 100} 300")
    expect.append(f"peek 100 {sha1(img[-100:] + bytes(200))}")
    # names: each file at both ends; the system area, padding and junk name none
    for path, off in fx.offsets.items():
        n = len(fx.files[path])
        for at in (off, off + n - 1):
            cmds.append(f"name {at}")
            expect.append(f"name {path} {off} {n}")
    cmds.append("name 0")
    expect.append("name -")
    for kind, at, filler in fx.gaps:
        if filler:
            cmds.append(f"name {at}")
            expect.append("name -")
            c.check(kind in ("pad32", "align32k", "junk"), f"a gap of kind {kind}")
    cmds.append(f"name {size - 1}")
    expect.append("name -")
    cmds.append("report")
    lines, err = drive(exe, cmds)
    got = lines[4:]  # past "open ok" and its three lines
    c.check(len(got) == len(expect) + 1, f"{len(got)} answers for {len(expect) + 1} questions")
    for q, want, have in zip(cmds[1:], expect, got, strict=False):
        c.check(have == want, f"{q}: {have!r}, not {want!r}")
    c.check(
        "1 reads past the image's end (200 bytes of zeros)" in err,
        f"the report counts the read past the end: {err.strip()!r}",
    )
    c.check("reaches past the image's end" in err, "the first read past the end is said")
    c.check(
        sum(1 for g in fx.gaps if g[0] == "junk") > 0 and len(fx.offsets) >= 10,
        "the fixture holds junk gaps and ten files",
    )

    # the refusals, each in its own words
    said: dict[str, str] = {}
    for name, (path, words) in broken_images(fx, out / "broken").items():
        lines, _ = drive(exe, [f"open {path}"])
        line = lines[0] if lines else ""
        c.check(
            line.startswith("refused ") and words in line, f"{name}: {line!r} (wanted {words!r})"
        )
        said[name] = line
    c.check(len(set(said.values())) == len(said), "every refusal says something different")
    check_built_in(c, fx, out, cflags)
    check_store(c, fx, out, out / "image" / f"disc_driver{PROF.exeext}")
    check_descriptors(c, fx, out, out / "image" / f"disc_driver{PROF.exeext}")

    print(
        f"disc check: {c.passed} passed, {c.failed} failed ({len(fx.offsets)} files, {size} bytes)"
    )
    folder = str(out / "broken")
    for name, line in said.items():
        words = line[8:].replace(folder + "/", "").replace(folder + "\\", "").replace(folder, "")
        print(f"  refused {name}: {words[:110]}")
    return 1 if c.failed else 0


def check_log(log: Path, data: Path) -> int:
    """A run's SOA_DISC_LOG=1 lines against the file table tools/soa/disc.py
    parses from the image under `data`."""
    image = data / "disc.iso" if data.is_dir() else data
    with Disc.from_file(image) as disc:
        files = sorted(disc.fst.files, key=lambda f: f.offset)
    starts = [f.offset for f in files]
    reads = wrong = nameless = 0
    for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LOG_LINE.match(ln.strip())
        if not m:
            continue
        reads += 1
        off, length, name = int(m.group(2), 16), int(m.group(3)), m.group(4)
        past = int(m.group(5) or 0)
        i = bisect.bisect_right(starts, off) - 1
        holder = files[i] if i >= 0 and off < files[i].offset + files[i].size else None
        if holder is None:
            nameless += 1
            if name != "(no file)":
                wrong += 1
                print(f"WRONG {ln.strip()}: no file holds 0x{off:X}")
            continue
        want_past = max(0, off + length - (holder.offset + holder.size))
        if name != holder.path or past != want_past:
            wrong += 1
            if wrong <= 10:
                print(f"WRONG {ln.strip()}: the table says {holder.path}, {want_past} past its end")
    print(f"disc log: {reads} reads, {wrong} named wrongly, {nameless} naming no file")
    if reads == 0:
        print("::error::no [disc] read lines (was SOA_DISC_LOG=1 set?)")
    return 0 if reads and not wrong and not nameless else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--cc", choices=tuple(toolchain.PROFILES), default="msvc", help="the toolchain profile"
    )
    ap.add_argument("--cflag", action="append", default=[], help="added to every compile and link")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--mutate", choices=("fst-offset",), help="a mutation that must fail the check")
    ap.add_argument("--log", type=Path, help="a run's log, with SOA_DISC_LOG=1")
    ap.add_argument(
        "--data", type=Path, default=ROOT / "extracted", help="the image --log is checked against"
    )
    args = ap.parse_args()
    if args.log:
        return check_log(args.log, args.data)
    global PROF
    PROF = toolchain.profile(args.cc)
    if args.out is None:
        args.out = (
            ROOT / "build" / "citest" / ("disc" if PROF.name == "msvc" else f"disc-{PROF.name}")
        )
    cl = toolchain.compiler_path(PROF)
    if cl is None:
        print(f"{PROF.name} not found (see tools/soa/toolchain.py compiler_path)", file=sys.stderr)
        print("this check must not pass silently, so it fails instead", file=sys.stderr)
        return 1
    print(f"compiler: {cl}")
    return check_fixture(args.out, args.cflag, args.mutate)


if __name__ == "__main__":
    raise SystemExit(main())
