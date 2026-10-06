"""The import's portable half (specs/android.md L12d; runtime/import.c).

What the phone does with a descriptor its file picker handed over -- read it
in place or copy it -- and the copy itself are in runtime/import.c, so that
they run here, on CI's Linux legs, where no phone is. A driver includes
import.c and is built with the profile SOA_CC names (gcc or clang), and each
case hands it real descriptors -- files, pipes fed by a thread, sockets --
with pass_fds:

- a file, a pipe and a socket are classified, and only a regular file from
  the phone's own three providers, not served from /mnt/appfuse and with its
  grant kept, is read in place, each other case naming its reason;
- a pipe is copied byte for byte, its first MiB checked while the .tmp holds
  exactly that (or all of it, at its end, when less came), and a file from
  its start wherever its offset was left;
- a pipe that ends short of the size its provider gave is refused (the
  mutation the design names: a copy without the size comparison fails it),
  as is one that sends more, or more than the limit; one said to hold 0
  bytes is copied as one whose size was not given;
- the free space the margin leaves, at its exact boundary, and without a
  size looked at again before each MiB; a full disk (ENOSPC: a 1 MiB tmpfs
  where this may mount one, as root in a container, else writes made to fail
  as a full disk's do) and a file-size limit (EFBIG, RLIMIT_FSIZE) are
  refused with the .tmp gone and the old file kept;
- a cancel at a given byte, one while the stream is silent, and one while it
  trickles, when only the clock can ask;
- a 0444 file replaced with the old one kept as .old; stale .tmp files swept;
  a small file written whole or not at all;
- what a file is from its first bytes, the copy's name taken from that, and
  a message's internal path replaced by the picked file's name.

Four of import.c's calls are answered by stand-ins the driver puts in front
of them, each the real call unless asked: statvfs (--free, less what the
copy has written since, as a real disk fills), so the margin is held at its
boundary whatever the disk holds; write and fallocate (--room), a full disk
where none can be mounted, and write's short answers (--short); and
readlink (--link), so a descriptor can be shown to come from /mnt/appfuse
without making that folder.

Everything here wants Linux, the phone's kernel, and gcc or clang, and skips
without them, as on Windows.
"""

import errno
import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))
RUNTIME = ROOT / "runtime"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux")
    or PROFILE.name not in ("gcc", "clang")
    or toolchain.compiler_path(PROFILE) is None,
    reason="needs Linux (the phone's kernel) and gcc or clang (SOA_CC)",
)
MIB = 1 << 20
MARGIN = 512 * MIB  # import.h's IMPORT_MARGIN
LOCAL = (
    "com.android.externalstorage.documents",
    "com.android.providers.downloads.documents",
    "com.android.providers.media.documents",
)

DRIVER = r"""
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/vfs.h>
#include <time.h>
#include <unistd.h>

/* The stand-ins: each the real call until an option arms it. Every header
 * import.c includes is included above, so the macros below reach only its
 * calls, never a header's declarations. */
static long long g_free = -1, g_room = -1, g_short = 0, g_written = 0;
static int g_link_fd = -1;
static const char* g_link;

/* --free: a disk with that much free, less what has been written since, as a
 * real one fills, so a copy that looks again finds less */
static int fake_statvfs(const char* path, struct statvfs* st)
{
    int r = statvfs(path, st);
    if (r == 0 && g_free >= 0) {
        st->f_frsize = 1;
        st->f_bavail = (fsblkcnt_t)(g_free > g_written ? g_free - g_written : 0);
    }
    return r;
}

/* --room: a disk that holds that many more bytes; --short: writes of at most
 * that many, as a kernel may return */
static ssize_t fake_write(int fd, const void* b, size_t n)
{
    ssize_t w;
    if (g_short > 0 && (long long)n > g_short) n = (size_t)g_short;
    if (g_room == 0) {
        errno = ENOSPC;
        return -1;
    }
    if (g_room > 0 && (long long)n > g_room) n = (size_t)g_room; /* a full disk's short write first */
    w = write(fd, b, n);
    if (w > 0) {
        g_written += w;
        if (g_room > 0) g_room -= w;
    }
    return w;
}

static int fake_fallocate(int fd, int mode, off_t off, off_t len)
{
    if (g_room >= 0 && off + len > g_room) {
        errno = ENOSPC;
        return -1;
    }
    return fallocate(fd, mode, off, len);
}

static ssize_t fake_readlink(const char* path, char* buf, size_t n)
{
    char self[32];
    snprintf(self, sizeof self, "/proc/self/fd/%d", g_link_fd);
    if (g_link && !strcmp(path, self)) {
        size_t k = strlen(g_link);
        if (k > n) k = n;
        memcpy(buf, g_link, k);
        return (ssize_t)k;
    }
    return readlink(path, buf, n);
}

#define statvfs(path, st) fake_statvfs(path, st)
#define write(fd, b, n) fake_write(fd, b, n)
#define fallocate(fd, mode, off, len) fake_fallocate(fd, mode, off, len)
#define readlink(path, buf, n) fake_readlink(path, buf, n)
#include "import.c"
#undef statvfs
#undef write
#undef fallocate
#undef readlink

/* What the copy's callbacks were asked, on stdout, and when they say stop. */
typedef struct {
    unsigned long long cancel_at;
    int cancel_after, asks, refuse;
} Ask;

static int on_progress(uint64_t done, int64_t expect, void* user)
{
    Ask* a = (Ask*)user;
    a->asks++;
    printf("progress %llu %lld\n", (unsigned long long)done, (long long)expect);
    if (a->cancel_after && a->asks >= a->cancel_after) return 1;
    return a->cancel_at && done >= a->cancel_at;
}

static int on_peek(const char* tmp, uint64_t have, void* user, char* why, size_t cap)
{
    Ask* a = (Ask*)user;
    struct stat st;
    printf("peek %llu %lld\n", (unsigned long long)have, stat(tmp, &st) == 0 ? (long long)st.st_size : -1LL);
    if (!a->refuse) return 0;
    snprintf(why, cap, "%s is not what was asked for", tmp);
    return 1;
}

/* key=value among the arguments, or dflt */
static const char* opt(int n, char** a, const char* key, const char* dflt)
{
    size_t k = strlen(key);
    int i;
    for (i = 0; i < n; i++)
        if (!strncmp(a[i], key, k) && a[i][k] == '=') return a[i] + k + 1;
    return dflt;
}
static long long num(int n, char** a, const char* key, const char* dflt)
{
    return strtoll(opt(n, a, key, dflt), NULL, 0);
}

static const char* answer(int rc) { return rc == IMPORT_OK ? "ok" : rc == IMPORT_CANCELLED ? "cancelled" : "refused"; }

int main(int argc, char** argv)
{
    static char why[4096];
    static uint8_t head[4096];
    const char* cmd;
    char** a;
    int i = 1, n;
    for (; i + 1 < argc && !strncmp(argv[i], "--", 2); i += 2) {
        if (!strcmp(argv[i], "--free")) g_free = strtoll(argv[i + 1], NULL, 0);
        else if (!strcmp(argv[i], "--room")) g_room = strtoll(argv[i + 1], NULL, 0);
        else if (!strcmp(argv[i], "--short")) g_short = strtoll(argv[i + 1], NULL, 0);
        else if (!strcmp(argv[i], "--link")) {
            g_link_fd = atoi(argv[i + 1]);
            g_link = strchr(argv[i + 1], '=') + 1;
        } else if (!strcmp(argv[i], "--fsize")) { /* writes past it fail EFBIG, not with the signal */
            struct rlimit r;
            r.rlim_cur = r.rlim_max = (rlim_t)strtoll(argv[i + 1], NULL, 0);
            signal(SIGXFSZ, SIG_IGN);
            if (setrlimit(RLIMIT_FSIZE, &r) != 0) return 3;
        } else return 2;
    }
    if (i >= argc) return 2;
    cmd = argv[i];
    a = argv + i + 1;
    n = argc - i - 1;
    if (!strcmp(cmd, "classify")) {
        int64_t size;
        int k = import_classify(atoi(a[0]), &size);
        printf("%s %lld\n", k == IMPORT_FILE ? "file" : k == IMPORT_STREAM ? "stream" : "other", (long long)size);
    } else if (!strcmp(cmd, "inplace")) {
        const char* reason = "unset";
        if (import_in_place(strcmp(a[0], "-") ? a[0] : NULL, atoi(a[1]), atoi(a[2]), &reason)) puts("in place");
        else printf("copy: %s\n", reason);
    } else if (!strcmp(cmd, "free")) {
        printf("%lld\n", (long long)import_free(a[0]));
    } else if (!strcmp(cmd, "sniff")) {
        FILE* f = fopen(a[0], "rb");
        size_t got = f ? fread(head, 1, n > 1 ? (size_t)atoi(a[1]) : sizeof head, f) : 0;
        int k = import_sniff(head, got);
        if (f) fclose(f);
        printf("%s %s\n", k == IMPORT_ELF ? "elf" : k == IMPORT_PE ? "pe" : k == IMPORT_STORE ? "store"
                          : k == IMPORT_ISO ? "iso" : k == IMPORT_RVZ ? "rvz" : "unknown", import_copy_name(k));
    } else if (!strcmp(cmd, "namein")) {
        size_t cap = (size_t)atoi(a[0]);
        snprintf(why, sizeof why, "%s", a[1]);
        import_name_in(why, cap, a[2], a[3]);
        printf("%s\n", why);
    } else if (!strcmp(cmd, "head")) {
        ImportCopy c;
        Ask ask = {0, 0, 0, 0};
        size_t got = 0, k;
        int rc;
        memset(&c, 0, sizeof c);
        c.fd = atoi(a[0]);
        c.progress = on_progress;
        c.user = &ask;
        rc = import_head(&c, head, (size_t)atoi(a[1]), &got, why, sizeof why);
        printf("head %s %zu ", answer(rc), got);
        for (k = 0; k < got; k++) printf("%02x", head[k]);
        printf(" offset %lld\n", (long long)lseek(c.fd, 0, SEEK_CUR));
    } else if (!strcmp(cmd, "copy")) {
        ImportCopy c;
        Ask ask;
        uint64_t copied = 0;
        size_t got = 0;
        int rc = IMPORT_OK;
        memset(&c, 0, sizeof c);
        ask.cancel_at = (unsigned long long)num(n, a, "cancel_at", "0");
        ask.cancel_after = (int)num(n, a, "cancel_after", "0");
        ask.asks = 0;
        ask.refuse = !strcmp(opt(n, a, "peek", "none"), "refuse");
        c.fd = (int)num(n, a, "fd", "-1");
        c.dir = opt(n, a, "dir", ".");
        c.name = opt(n, a, "name", "disc.iso");
        c.expect = num(n, a, "expect", "-1");
        c.limit = (uint64_t)num(n, a, "limit", "0x80000000");
        c.peek_at = (uint64_t)num(n, a, "peek_at", "0");
        c.peek = strcmp(opt(n, a, "peek", "none"), "none") ? on_peek : NULL;
        c.progress = on_progress;
        c.user = &ask;
        if (num(n, a, "head", "0") > 0) { /* as android.c does: the head read first, to name the copy */
            rc = import_head(&c, head, (size_t)num(n, a, "head", "0"), &got, why, sizeof why);
            c.head = head;
            c.nhead = got;
        }
        if (rc == IMPORT_OK) rc = import_copy(&c, &copied, why, sizeof why);
        if (rc == IMPORT_OK) printf("ok %llu\n", (unsigned long long)copied);
        else printf("%s %s\n", answer(rc), why);
    } else if (!strcmp(cmd, "place")) {
        if (import_place(a[0], a[1], atoi(a[2]), why, sizeof why) == 0) puts("ok");
        else printf("refused %s\n", why);
    } else if (!strcmp(cmd, "sweep")) {
        printf("%d\n", import_sweep(a[0]));
    } else if (!strcmp(cmd, "write")) {
        if (import_write_text(a[0], a[1], why, sizeof why) == 0) puts("ok");
        else printf("refused %s\n", why);
    } else if (!strcmp(cmd, "probe")) {
        import_probe(atoi(a[0]), why, sizeof why);
        printf("%s\n", why);
    } else {
        return 2;
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("import")
    (d / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = d / "import_driver"
    proc = toolchain.cc(
        [*PROFILE.cflags, f"/I{RUNTIME}", str(d / "driver.c"), f"/Fe{exe}", *PROFILE.linker],
        d,
        PROFILE,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


def drive(exe: Path, *args, opts=(), fds=(), timeout=60) -> list[str]:
    """The driver's lines for one command, with the descriptors `fds` inherited
    under their own numbers."""
    proc = subprocess.run(
        [str(exe), *map(str, opts), *map(str, args)],
        capture_output=True,
        encoding="utf-8",  # strict: half a character fails the case
        timeout=timeout,
        pass_fds=fds,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return proc.stdout.splitlines()


class Feed:
    """A pipe a thread fills with `data` and then closes (after `hold` is set,
    when given: a stream gone silent), `piece` bytes at a time with `gap`
    seconds between (a slow provider): the read end for the driver, and how
    much went in before the reader went away."""

    def __init__(
        self,
        data: bytes,
        hold: threading.Event | None = None,
        piece: int = 65536,
        gap: float = 0.0,
    ):
        self.r, self.w = os.pipe()
        self.data, self.hold, self.piece, self.gap = data, hold, piece, gap
        self.sent, self.broken = 0, False
        self.thread = threading.Thread(target=self._fill, daemon=True)
        self.thread.start()

    def _fill(self) -> None:
        try:
            while self.sent < len(self.data):
                self.sent += os.write(self.w, self.data[self.sent : self.sent + self.piece])
                if self.gap:
                    time.sleep(self.gap)
            if self.hold is not None:
                self.hold.wait(30)
        except BrokenPipeError:
            self.broken = True
        finally:
            os.close(self.w)

    def close(self) -> None:
        """The test's read end closed, so a writer the driver stopped reading
        from sees the reader gone; then the thread is waited for."""
        os.close(self.r)
        if self.hold is not None:
            self.hold.set()
        self.thread.join(30)


def copy(
    exe: Path, feed_or_fd: Feed | int, folder: Path, *, opts=(), timeout=60, **kw
) -> tuple[list[str], Feed | int]:
    """import_copy of a Feed (closed afterwards) or a descriptor into folder;
    kw are the driver's key=value options."""
    fd = feed_or_fd.r if isinstance(feed_or_fd, Feed) else feed_or_fd
    args = [f"fd={fd}", f"dir={folder}", *(f"{k}={v}" for k, v in kw.items())]
    try:
        return drive(exe, "copy", *args, opts=opts, fds=(fd,), timeout=timeout), feed_or_fd
    finally:
        if isinstance(feed_or_fd, Feed):
            feed_or_fd.close()


def store_like(n: int) -> bytes:
    """n bytes that begin as a disc store does, the rest random."""
    return b"SOADISC1" + os.urandom(n - 8)


def tmp_files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp"))


def old_file(folder: Path, name="disc.soadisc") -> tuple[Path, bytes]:
    """The copy a refused or cancelled one must leave alone, 0444 as import makes them."""
    old = folder / name
    data = b"the disc that works\n" * 100
    old.write_bytes(data)
    old.chmod(0o444)
    return old, data


def test_a_file_a_pipe_and_a_socket_are_told_apart(driver, tmp_path):
    f = tmp_path / "picked"
    f.write_bytes(b"x" * 12345)
    fd = os.open(f, os.O_RDONLY)
    r, w = os.pipe()
    a, b = socket.socketpair()
    folder = os.open(tmp_path, os.O_RDONLY)
    try:
        assert drive(driver, "classify", fd, fds=(fd,)) == ["file 12345"]
        assert drive(driver, "classify", r, fds=(r,)) == ["stream -1"]
        assert drive(driver, "classify", a.fileno(), fds=(a.fileno(),)) == ["stream -1"]
        assert drive(driver, "classify", folder, fds=(folder,)) == ["other -1"]
        assert drive(driver, "classify", 99) == ["other -1"]  # nothing open there
    finally:
        for x in (fd, r, w, folder):
            os.close(x)
        a.close()
        b.close()


def test_only_the_phone_s_own_regular_files_with_their_grant_are_read_in_place(driver, tmp_path):
    f = tmp_path / "GEAE8P.soadisc"
    f.write_bytes(store_like(4096))
    fd = os.open(f, os.O_RDONLY)
    r, w = os.pipe()
    try:
        for authority in LOCAL:
            assert drive(driver, "inplace", authority, fd, 1, fds=(fd,)) == ["in place"], authority

        def why(authority, d, kept, link=None):
            opts = ("--link", f"{d}={link}") if link else ()
            return drive(driver, "inplace", authority, d, kept, fds=(d,), opts=opts)

        # compared whole: a provider cannot borrow the phone's name
        for other in (
            "com.google.android.apps.docs.storage",
            "com.android.externalstorage.documents.evil",
            "com.android.externalstorage",
            "-",
        ):
            assert why(other, fd, 1) == ["copy: not this phone's storage"], other
        assert why(LOCAL[0], fd, 0) == ["copy: the permission could not be kept"]
        assert why(LOCAL[1], fd, 1, "/mnt/appfuse/10234_5/3") == ["copy: a proxy (/mnt/appfuse)"]
        assert why(LOCAL[1], fd, 1, "/mnt/appfuse") == ["copy: a proxy (/mnt/appfuse)"]
        assert why(LOCAL[1], fd, 1, "/mnt/appfusex/1") == ["in place"]
        assert why(LOCAL[1], fd, 1, "/storage/emulated/0/Download/GEAE8P.soadisc") == ["in place"]
        # a stream is said first: a pipe from anywhere is a stream to copy
        assert why(LOCAL[0], r, 1) == ["copy: a stream (a pipe or a socket)"]
        assert why("io.github.bmfrench89.soa.dev.testfiles", r, 0) == [
            "copy: a stream (a pipe or a socket)"
        ]
        assert why("io.github.bmfrench89.soa.dev.testfiles", fd, 1) == [
            "copy: not this phone's storage"
        ]
    finally:
        os.close(fd)
        os.close(r)
        os.close(w)


def test_a_pipe_is_copied_byte_for_byte_and_its_first_mib_checked_first(driver, tmp_path):
    data = store_like(3 * MIB + 17)
    lines, feed = copy(
        driver,
        Feed(data),
        tmp_path,
        name="disc.soadisc",
        expect=len(data),
        head=64,
        peek_at=MIB,
        peek="accept",
    )
    assert lines[-1] == f"ok {len(data)}", lines
    # asked once, with the .tmp holding exactly the first MiB
    assert [x for x in lines if x.startswith("peek")] == [f"peek {MIB} {MIB}"], lines
    # at the start and once in each further MiB: a pipe's reads end where
    # they end, so only the peek's MiB is exact
    asked = [int(x.split()[1]) for x in lines if x.startswith("progress")]
    assert asked[0] == 0 and MIB in asked, asked
    assert all(any(k * MIB <= x < (k + 1) * MIB for x in asked) for k in (2, 3)), asked
    tmp = tmp_path / "disc.soadisc.tmp"
    assert tmp.read_bytes() == data
    assert stat.S_IMODE(tmp.stat().st_mode) == 0o444
    assert feed.sent == len(data) and not feed.broken
    # and whole through writes that each take only part of what they are
    # given, over the 0444 .tmp the copy before left, as a killed one would
    lines, _ = copy(
        driver, Feed(data), tmp_path, name="disc.soadisc", expect=len(data), opts=("--short", 1000)
    )
    assert lines[-1] == f"ok {len(data)}", lines
    assert tmp.read_bytes() == data


def test_a_file_is_copied_from_its_start_wherever_its_offset_was_left(driver, tmp_path):
    data = os.urandom(2 * MIB + 5)
    f = tmp_path / "picked"
    f.write_bytes(data)
    fd = os.open(f, os.O_RDONLY)
    try:
        os.lseek(fd, 1000, os.SEEK_SET)  # where a check through a dup left it
        out = tmp_path / "out"
        out.mkdir()
        head = drive(driver, "head", fd, 64, fds=(fd,))
        assert head == [f"head ok 64 {data[:64].hex()} offset 1000"], head
        lines, _ = copy(
            driver, fd, out, name="disc.iso", expect=len(data), head=64, peek_at=MIB, peek="accept"
        )
        assert lines[-1] == f"ok {len(data)}", lines
        # a file's reads are a MiB each, so this one is cut to land on the peek
        assert [x for x in lines if x.startswith("peek")] == [f"peek {MIB} {MIB}"], lines
        assert (out / "disc.iso.tmp").read_bytes() == data
        assert os.lseek(fd, 0, os.SEEK_CUR) == 1000
    finally:
        os.close(fd)


def test_a_stream_cut_short_of_its_size_is_refused(driver, tmp_path):
    old, before = old_file(tmp_path)
    size = 2236416  # a fixture store's, as the emulator's ?truncate=65536 check sends it
    lines, _ = copy(
        driver,
        Feed(store_like(size)[:65536]),
        tmp_path,
        name="disc.soadisc",
        expect=size,
        peek_at=MIB,
        peek="refuse",
    )
    assert lines[-1].startswith(f"refused the copy stopped at 65536 of {size} bytes: "), lines
    # the size is said, not what its first bytes lacked: the peek never ran
    assert not [x for x in lines if x.startswith("peek")], lines
    assert tmp_files(tmp_path) == [] and old.read_bytes() == before


def test_a_stream_that_sends_more_than_its_size_or_its_limit_is_refused(driver, tmp_path):
    old, before = old_file(tmp_path)
    lines, feed = copy(driver, Feed(os.urandom(2 * MIB)), tmp_path, name="disc.soadisc", expect=MIB)
    assert lines[-1].startswith(f"refused /proc/self/fd/{feed.r} sent more than the {MIB} bytes"), (
        lines
    )
    # 3 MiB left unread: more than a pipe holds even with 64 KiB pages
    lines, feed = copy(
        driver, Feed(os.urandom(5 * MIB)), tmp_path, name="disc.soadisc", limit=2 * MIB
    )
    assert lines[-1].startswith(f"refused /proc/self/fd/{feed.r} sent more than 2 MB, "), lines
    assert feed.broken  # it was not read to its end
    lines, feed = copy(
        driver, Feed(os.urandom(64)), tmp_path, name="disc.soadisc", expect=3 * MIB, limit=2 * MIB
    )
    assert lines[-1] == (
        f"refused /proc/self/fd/{feed.r} is 3 MB, and the file asked for is never more than 2 MB: "
        "pick the right one"
    ), lines
    assert tmp_files(tmp_path) == [] and old.read_bytes() == before


def test_a_stream_said_to_hold_0_bytes_is_copied_as_one_of_no_size(driver, tmp_path):
    """Some providers say 0 for a size they do not know. Held to it, a pipe
    would be refused at its first byte as sending more than it said, however
    often the player picked it again."""
    data = store_like(MIB + 17)
    lines, _ = copy(
        driver,
        Feed(data),
        tmp_path,
        name="disc.soadisc",
        expect=0,
        head=64,
        peek_at=MIB,
        peek="accept",
    )
    assert lines[-1] == f"ok {len(data)}", lines
    # and progress is told no size, not 0
    asked = [x for x in lines if x.startswith("progress")]
    assert asked and all(x.endswith(" -1") for x in asked), lines
    assert (tmp_path / "disc.soadisc.tmp").read_bytes() == data


def test_a_peek_refusal_stops_the_copy_before_the_rest_is_read(driver, tmp_path):
    old, before = old_file(tmp_path)
    size = 2236416
    lines, feed = copy(
        driver,
        Feed(store_like(size)),
        tmp_path,
        name="disc.soadisc",
        expect=size,
        peek_at=MIB,
        peek="refuse",
    )
    assert [x for x in lines if x.startswith("peek")] == [f"peek {MIB} {MIB}"], lines
    tmp = tmp_path / "disc.soadisc.tmp"
    assert lines[-1] == (
        f"refused the copy was stopped after {MIB} of {size} bytes: {tmp} is not what was asked for"
    ), lines
    assert feed.broken and feed.sent < size
    # a library's: its ELF header, the head import_head took to name it
    lines, _ = copy(
        driver,
        Feed(b"\x7fELF" + os.urandom(MIB)),
        tmp_path,
        name="libsoa_game.so",
        expect=MIB + 4,
        head=64,
        peek_at=64,
        peek="refuse",
    )
    assert [x for x in lines if x.startswith("peek")] == ["peek 64 64"], lines
    assert lines[-1].startswith(f"refused the copy was stopped after 64 of {MIB + 4} bytes: "), (
        lines
    )
    assert tmp_files(tmp_path) == [] and old.read_bytes() == before


def test_a_stream_shorter_than_its_peek_is_peeked_at_at_its_end(driver, tmp_path):
    """A stream that ends before peek_at is still checked, once, with the .tmp
    holding all of it -- its size given and right, or not given -- rather than
    put in place unchecked."""
    old, before = old_file(tmp_path)
    tmp = tmp_path / "disc.soadisc.tmp"
    for expect, of in ((1000, " of 1000"), (-1, "")):
        lines, _ = copy(
            driver,
            Feed(store_like(1000)),
            tmp_path,
            name="disc.soadisc",
            expect=expect,
            head=64,
            peek_at=MIB,
            peek="refuse",
        )
        assert [x for x in lines if x.startswith("peek")] == ["peek 1000 1000"], lines
        assert lines[-1] == (
            f"refused the copy was stopped after 1000{of} bytes: {tmp} is not what was asked for"
        ), lines
        assert tmp_files(tmp_path) == [] and old.read_bytes() == before


def test_the_margin_stays_free_to_the_byte(driver, tmp_path):
    old, before = old_file(tmp_path)
    size = 3 * MIB
    data = os.urandom(size)
    lines, feed = copy(
        driver,
        Feed(data),
        tmp_path,
        name="disc.soadisc",
        expect=size,
        opts=("--free", size + MARGIN - 1),
    )
    assert lines[-1] == (
        f"refused copying /proc/self/fd/{feed.r} needs 3 MB, and 512 MB more must stay free, "
        "but 514 MB is free: make room on this device and pick it again"
    ), lines
    assert tmp_files(tmp_path) == [] and old.read_bytes() == before
    lines, _ = copy(
        driver,
        Feed(data),
        tmp_path,
        name="disc.soadisc",
        expect=size,
        opts=("--free", size + MARGIN),
    )
    assert lines[-1] == f"ok {size}", lines
    (tmp_path / "disc.soadisc.tmp").unlink()
    # no size given: the free space is looked at again before each MiB, and
    # finds less each time as the copy fills the disk; that MiB must fit
    # above the margin, so 3 MiB need 3 MiB free above it, to the byte. From
    # a pipe, whose reads end where they end, and from a file, whose reads are
    # a MiB long, each after the head that names the copy, as android.c gives
    # it: either way no read runs past the next look
    picked = tmp_path / "picked"
    picked.write_bytes(data)
    fd = os.open(picked, os.O_RDONLY)
    try:
        for source in ("pipe", "file"):
            for free, stopped in (
                (MARGIN + MIB - 1, 0),
                (MARGIN + 3 * MIB - 1, 2 * MIB),
                (MARGIN + 3 * MIB, None),
            ):
                lines, fed = copy(
                    driver,
                    Feed(data) if source == "pipe" else fd,
                    tmp_path,
                    name="disc.soadisc",
                    head=64,
                    opts=("--free", free),
                )
                if stopped is None:
                    assert lines[-1] == f"ok {size}", (source, lines)
                    assert (tmp_path / "disc.soadisc.tmp").read_bytes() == data
                    (tmp_path / "disc.soadisc.tmp").unlink()
                    continue
                src = f"/proc/self/fd/{fed.r if source == 'pipe' else fd}"
                assert lines[-1] == (
                    "refused this device has 512 MB free and 512 MB of it must stay free, so the "
                    f"copy of {src} stopped at {stopped} bytes: make room and pick it again"
                ), (source, lines)
                assert tmp_files(tmp_path) == [], source
    finally:
        os.close(fd)
    assert old.read_bytes() == before


def mount_tiny(folder: Path) -> bool:
    """A 1 MiB tmpfs at folder, where this process may mount one (root with
    CAP_SYS_ADMIN, as in a container run so); False elsewhere."""
    folder.mkdir()
    if os.geteuid() != 0 or shutil.which("mount") is None:
        return False
    proc = subprocess.run(
        ["mount", "-t", "tmpfs", "-o", "size=1m", "tmpfs", str(folder)], capture_output=True
    )
    return proc.returncode == 0


def test_a_full_disk_and_a_file_size_limit_are_refused_and_the_old_file_kept(driver, tmp_path):
    tiny = tmp_path / "tiny"
    mounted = mount_tiny(tiny)
    try:
        old, before = old_file(tiny)
        # a mounted tmpfs is truly full: statvfs is told there is room so the
        # copy gets that far; without one, the disk is made to fail as a full
        # one does
        full = ("--free", 8 << 30) if mounted else ("--room", MIB)
        print(f"ENOSPC from {'a 1 MiB tmpfs' if mounted else 'writes made to fail'}")
        enospc = os.strerror(errno.ENOSPC)
        # with its size given, refused as the space is taken, before a byte is written
        lines, _ = copy(
            driver, Feed(os.urandom(4 * MIB)), tiny, name="disc.soadisc", expect=4 * MIB, opts=full
        )
        assert lines == [f"refused cannot make room for {tiny}/disc.soadisc.tmp: {enospc}"], lines
        assert tmp_files(tiny) == [] and old.read_bytes() == before
        # without, by the write that finds no room
        lines, _ = copy(driver, Feed(os.urandom(4 * MIB)), tiny, name="disc.soadisc", opts=full)
        assert lines[-1] == f"refused cannot write {tiny}/disc.soadisc.tmp: {enospc}", lines
        assert tmp_files(tiny) == [] and old.read_bytes() == before
    finally:
        if mounted:
            subprocess.run(["umount", str(tiny)], check=True)
    old, before = old_file(tmp_path)
    lines, _ = copy(
        driver,
        Feed(os.urandom(3 * MIB)),
        tmp_path,
        name="disc.soadisc",
        expect=3 * MIB,
        opts=("--fsize", MIB),
    )
    assert lines[-1].startswith("refused cannot "), lines
    assert lines[-1].endswith(f"{tmp_path}/disc.soadisc.tmp: {os.strerror(errno.EFBIG)}"), lines
    assert tmp_files(tmp_path) == [] and old.read_bytes() == before


def test_a_copy_cancels_at_a_byte_and_while_its_stream_is_silent(driver, tmp_path):
    old, before = old_file(tmp_path)
    size = 5 * MIB
    lines, feed = copy(
        driver,
        Feed(os.urandom(size)),
        tmp_path,
        name="disc.soadisc",
        expect=size,
        cancel_at=2 * MIB,
    )
    last = lines[-1].split()
    assert lines[-1].startswith("cancelled the copy was cancelled at ") and last[-2:] == [
        str(size),
        "bytes",
    ], lines
    assert 2 * MIB <= int(last[-4]) < 3 * MIB, lines
    assert feed.broken and feed.sent < size
    assert tmp_files(tmp_path) == [] and old.read_bytes() == before
    # a provider that stops sending: the third asking, half a second on, cancels
    lines, _ = copy(
        driver,
        Feed(os.urandom(1000), hold=threading.Event()),
        tmp_path,
        name="disc.soadisc",
        cancel_after=3,
        timeout=10,
    )
    assert lines[-1] == "cancelled the copy was cancelled at 1000 bytes", lines
    assert [x for x in lines if x.startswith("progress")] == [
        "progress 0 -1",
        *["progress 1000 -1"] * 2,
    ]
    assert tmp_files(tmp_path) == [] and old.read_bytes() == before
    # and while the head that names the copy is awaited, before any .tmp
    lines, feed = copy(
        driver,
        Feed(os.urandom(10), hold=threading.Event()),
        tmp_path,
        name="disc.soadisc",
        head=64,
        cancel_after=2,
        timeout=10,
    )
    assert lines[-1] == f"cancelled cancelled while waiting for /proc/self/fd/{feed.r}", lines
    assert [x for x in lines if x.startswith("progress")] == ["progress 10 -1"] * 2
    assert tmp_files(tmp_path) == [] and old.read_bytes() == before


def test_a_stream_that_trickles_is_asked_every_quarter_second(driver, tmp_path):
    """A slow provider is never silent for a quarter second, so only the clock
    asks before the next MiB: 8 KiB each 20 ms is 400 KB/s, and that MiB 2.6 s
    away. Cancel must not wait for it."""
    old, before = old_file(tmp_path)
    lines, feed = copy(
        driver,
        Feed(os.urandom(2 * MIB), piece=8192, gap=0.02),
        tmp_path,
        name="disc.soadisc",
        cancel_after=2,
        timeout=30,
    )
    asked = [x for x in lines if x.startswith("progress")]
    at = int(asked[-1].split()[1])
    assert asked == ["progress 0 -1", f"progress {at} -1"], lines
    assert at < MIB // 2, lines
    assert lines[-1] == f"cancelled the copy was cancelled at {at} bytes", lines
    assert feed.broken and tmp_files(tmp_path) == [] and old.read_bytes() == before


def test_a_0444_file_is_replaced_and_the_old_one_kept(driver, tmp_path):
    final = tmp_path / "libsoa_game.so"
    final.write_bytes(b"the library that loads")
    final.chmod(0o444)
    tmp = tmp_path / "libsoa_game.so.tmp"
    lines, _ = copy(driver, Feed(b"the new one"), tmp_path, name="libsoa_game.so", expect=11)
    assert lines[-1] == "ok 11", lines
    assert drive(driver, "place", tmp, final, 1) == ["ok"]
    assert final.read_bytes() == b"the new one" and stat.S_IMODE(final.stat().st_mode) == 0o444
    assert (tmp_path / "libsoa_game.so.old").read_bytes() == b"the library that loads"
    assert not tmp.exists()
    # without keep_old the .old is left as it was
    tmp.write_bytes(b"newer")
    assert drive(driver, "place", tmp, final, 0) == ["ok"]
    assert final.read_bytes() == b"newer" and not tmp.exists()
    assert (tmp_path / "libsoa_game.so.old").read_bytes() == b"the library that loads"
    # nothing to put in place costs nothing, not even the .old
    lines = drive(driver, "place", tmp, final, 1)
    assert lines[0].startswith(f"refused cannot put {tmp} in place of {final}: "), lines
    assert final.read_bytes() == b"newer"
    assert (tmp_path / "libsoa_game.so.old").read_bytes() == b"the library that loads"
    # a rename that fails once the old one is moved aside puts it back: one
    # from another filesystem (EXDEV), as /dev/shm's tmpfs is to this folder
    shm = Path("/dev/shm")
    assert shm.is_dir() and shm.stat().st_dev != tmp_path.stat().st_dev, "needs /dev/shm"
    elsewhere = shm / f"soa-import-{os.getpid()}.tmp"
    elsewhere.write_bytes(b"from elsewhere")
    try:
        lines = drive(driver, "place", elsewhere, final, 1)
        assert lines[0] == (
            f"refused cannot put {elsewhere} in place of {final}: {os.strerror(errno.EXDEV)}"
        ), lines
        assert final.read_bytes() == b"newer" and elsewhere.exists()
    finally:
        elsewhere.unlink()


def test_stale_tmp_files_are_swept_and_nothing_else(driver, tmp_path):
    for name in (
        "disc.soadisc.tmp",
        "libsoa_game.so.tmp",
        "libsoa_game.so",
        "disc.txt",
        "x.tmpx",
        ".tmp",
    ):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "disc.soadisc.tmp").chmod(0o444)  # a killed copy's, finished but not renamed
    (tmp_path / "folder.tmp").mkdir()
    (tmp_path / "link.tmp").symlink_to(tmp_path / "disc.txt")
    assert drive(driver, "sweep", tmp_path) == ["2"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        ".tmp",
        "disc.txt",
        "folder.tmp",
        "libsoa_game.so",
        "link.tmp",
        "x.tmpx",
    ]
    assert drive(driver, "sweep", tmp_path / "copy") == ["0"]  # no folder yet


def test_a_small_file_is_written_whole_or_not_at_all(driver, tmp_path):
    ini = tmp_path / "soa.ini"
    ini.write_text("render = 0\n", encoding="utf-8")
    ini.chmod(0o444)
    assert drive(driver, "write", ini, "render = 1\n") == ["ok"]
    assert ini.read_text(encoding="utf-8") == "render = 1\n" and tmp_files(tmp_path) == []
    assert stat.S_IMODE(ini.stat().st_mode) == 0o600
    lines = drive(driver, "write", tmp_path / "no-such-folder" / "disc.txt", "uri=x\n")
    assert lines[0].startswith("refused cannot create "), lines


def test_what_a_file_is_and_its_copy_s_name_come_from_its_bytes(driver, tmp_path):
    iso = bytearray(0x440)
    iso[0:6] = b"GEAE8P"
    iso[0x1C:0x20] = bytes.fromhex("C2339F3D")
    cases = {
        "store": (b"SOADISC1" + bytes(56), "store disc.soadisc"),
        "iso": (bytes(iso), "iso disc.iso"),
        "elf": (b"\x7fELF\x02\x01\x01" + bytes(57), "elf libsoa_game.so"),
        "pe": (b"MZ\x90\x00" + bytes(60), "pe disc.iso"),
        "rvz": (b"RVZ\x01" + bytes(60), "rvz disc.iso"),
        "wia": (b"WIA\x01" + bytes(60), "rvz disc.iso"),
        "text": (b"uri=content://x\n", "unknown disc.iso"),
        "empty": (b"", "unknown disc.iso"),
    }
    for name, (data, said) in cases.items():
        (tmp_path / name).write_bytes(data)
        assert drive(driver, "sniff", tmp_path / name) == [said], name
    # the boot magic needs all 0x20 bytes
    assert drive(driver, "sniff", tmp_path / "iso", 0x1F) == ["unknown disc.iso"]
    assert drive(driver, "sniff", tmp_path / "iso", 0x20) == ["iso disc.iso"]


def test_a_message_names_the_picked_file_not_the_descriptor(driver):
    def name_in(why, internal, display, cap=4096):
        return drive(driver, "namein", cap, why, internal, display)[0]

    fd7 = "/proc/self/fd/7"
    assert name_in(f"cannot read {fd7}: Input/output error", fd7, "GEAE8P.soadisc") == (
        "cannot read GEAE8P.soadisc: Input/output error"
    )
    # whole paths only, and a sentence may end on one
    assert name_in(f"{fd7} and /proc/self/fd/71 and x{fd7} and {fd7}.", fd7, "D.iso") == (
        "D.iso and /proc/self/fd/71 and x/proc/self/fd/7 and D.iso."
    )
    copy_ = "/data/user/0/p/no_backup/copy/disc.iso"
    assert name_in(f"{copy_}.tmp is GTSE01; {copy_} is not", f"{copy_}.tmp", "GTSE01.iso") == (
        f"GTSE01.iso is GTSE01; {copy_} is not"
    )
    assert name_in(f"{copy_}.tmp is GTSE01", copy_, "GTSE01.iso") == f"{copy_}.tmp is GTSE01"
    # cut to fit, and never inside a character: 16 bytes hold one of these
    # three-byte ones after "cannot read ", not two
    assert name_in(f"cannot read {fd7}: gone", fd7, "ディスク.iso", cap=17) == "cannot read デ"
    assert name_in(f"cannot read {fd7}: gone", fd7, "ディスク.iso", cap=19) == "cannot read ディ"
    assert name_in("nothing to replace", fd7, "x") == "nothing to replace"


def test_the_free_space_is_the_filesystem_s(driver, tmp_path):
    said = int(drive(driver, "free", tmp_path)[0])
    st = os.statvfs(tmp_path)
    assert abs(said - st.f_bavail * st.f_frsize) < 256 * MIB, said
    assert drive(driver, "free", tmp_path / "no-such-folder") == ["-1"]


def test_the_probe_says_where_a_descriptor_points_and_whether_its_path_opens(driver, tmp_path):
    f = tmp_path / "picked"
    f.write_bytes(b"x" * 100)
    fd = os.open(f, os.O_RDONLY)
    try:
        f.chmod(0)  # what a picked file the app does not own is to a by-name open
        line = drive(driver, "probe", fd, fds=(fd,))[0]
        # statfs's f_type, which Python's statvfs lacks, as coreutils says it
        f_type = subprocess.run(
            ["stat", "-f", "-c", "%t", str(tmp_path)], capture_output=True, text=True, check=True
        ).stdout.strip()
        assert line.startswith(f"{f}, f_type 0x{f_type}, "), line
        opened = "ok" if os.geteuid() == 0 else os.strerror(errno.EACCES)
        assert line.endswith(f", open by name: {opened}"), line
    finally:
        f.chmod(0o644)
        os.close(fd)
    # a named pipe with no writer: opening its path to read would wait for
    # one, and the probe must not (an anonymous pipe's path never waits)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    r = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        line = drive(driver, "probe", r, fds=(r,), timeout=10)[0]
        assert line.startswith(f"{fifo}, f_type 0x") and line.endswith(", open by name: ok"), line
    finally:
        os.close(r)
