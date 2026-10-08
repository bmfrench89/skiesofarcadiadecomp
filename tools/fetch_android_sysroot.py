"""Build R5's Android sysroot, the phone's C headers and crt objects, from bionic's pinned sources.

    python tools/fetch_android_sysroot.py [--vendor DIR] [--offline] [--from DIR] [--lists]
    python tools/fetch_android_sysroot.py --verify [--vendor DIR]
    python tools/fetch_android_sysroot.py --check-upstream
    python tools/fetch_android_sysroot.py --cache-key

specs/android-sysroot.md R5a (D-31, D-34): the phone's game library is built
by llvm-mingw's clang, the compiler a player's package already carries, against
this repository's own sysroot, so no part of Android's NDK is shipped or
fetched for players. The sysroot is built where it is used, by this script,
from 44 files of bionic, Android's C library, at one pinned commit
(android-17.0.0_r1), each held to a sha256 and a git blob id this script holds:

- the 30 headers the translated C reads (runtime/cpu.h's math.h, setjmp.h,
  string.h and stdlib.h's types, and what they include), shipped unmodified
  in the NDK's layout under android-sysroot/usr/include;
- crtbegin_so.o and crtend_so.o for arm64 and x86_64, which every shared
  library's link takes, built from bionic's own source with llvm-mingw's
  clang into android-sysroot/usr/lib/<triple>/33, each held to a pinned sha256:
  the six arch-common files and four private headers they compile from, and
  the four unistd headers the build reads, are the other 14;
- android-sysroot/NOTICE.txt: each of those files' own licence words.

The 44 come from android.googlesource.com as four directory archives, kept in
vendor/android-sysroot-src (no request once it holds them all); --from fills
it from any folder laid out as bionic, and --offline never asks the network.
Three more files are read only by tests: bionic's two symbol lists (--lists)
and linux/version.h. vendor/ANDROID-SYSROOT.sha256 records the 35 files of the
tree; --verify reports any changed, missing or not recorded.

A new llvm-mingw release fails the crt objects' pins by design: whoever bumps
fetch_mingw.RELEASE bumps toolchain.MINGW_RELEASE and MINGW_CLANG with it (a
test holds the two releases equal), derives the new pins, and runs R5a's
emulator checks again. A new #include in runtime/cpu.h or soa_game.h fails
the closure test (R5a part 2): whoever adds it pins the new headers
(--check-upstream checks them against bionic's own listing), then runs the
emulator. A count this tool prints that the docs quote is found everywhere by
grep -rn "<the old number>" --include="*.md" . Nothing here touches game data.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import email.utils
import gzip
import hashlib
import http.client
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

# A package's python adds no script folder to sys.path (its ._pth names only
# python314.zip and .), so this script's own folder goes in by hand.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from soa import toolchain  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "06356e41c5ed7b12220b24c05ba4fdb873b126a7"
TAG = "android-17.0.0_r1"
BASE = "https://android.googlesource.com/platform/bionic"
API = 33
ABIS = {"arm64": "aarch64-linux-android", "x86_64": "x86_64-linux-android"}
# The directories whose archives hold the 44 a build reads, and so the rest
# of what SOURCES names in them (linux/version.h comes with libc/kernel/uapi).
ARCHIVES = ("libc/include", "libc/kernel/uapi", "libc/arch-common/bionic", "libc/private")
# Read one at a time, only with --lists: the endpoint that answers 429 soonest.
TEXT_FILES = ("libc/libc.map.txt", "libm/libm.map.txt")
DEST = "android-sysroot"
CACHE = "android-sysroot-src"
RECORD = "ANDROID-SYSROOT.sha256"
CRT_FLAGS = ("-fPIC", "-O2", "-Wall", "-Werror", "-Wno-gcc-compat")
PACE = 2.0  # seconds between any two requests
TRIES = 6
WAIT_CAP = 300.0
WAITS = (10, 20, 40, 80, 120)
DEADLINE = 600.0  # seconds from a run's first request


class Source(NamedTuple):
    """One pinned file of bionic: its size, its role (ship: in the tree;
    build: read while building the crt objects; check: read only by tests),
    the ABI it is for (None for a check file), its sha256 and git blob id."""

    size: int
    role: str
    abi: str | None
    sha256: str
    blob: str


SOURCES: dict[str, Source] = {
    "libc/arch-common/bionic/__dso_handle_so.h": Source(
        1930,
        "build",
        "both",
        "50b6bbb9aaa1692175e45839c0b90810a962449d0b9842960caf8119595bdc32",
        "2c0df7bc74cdf364ac7527a4a15322300083502f",
    ),
    "libc/arch-common/bionic/atexit.h": Source(
        1797,
        "build",
        "both",
        "8671df24f92b375fe8ff233e88d5b55f01e91c608ee838045431444101bf70af",
        "90aa030eafcfc7c7a47585d40c6f927e5d1d3e73",
    ),
    "libc/arch-common/bionic/crtbegin_so.c": Source(
        2936,
        "build",
        "both",
        "7339e128550f8f90a254fef776c8a23b96a13190e93981cb20a588a2e6342bf3",
        "2f3b1189075191332b841e0954f1faa7b140fdfb",
    ),
    "libc/arch-common/bionic/crtbrand.S": Source(
        1942,
        "build",
        "both",
        "27f3d6eda81ba614020871c8cc46fa0e92d9900413f38469fdb2081715cb3bb5",
        "26b973fecbbf1bdd0dd1353452e91e1c6a2c3bdb",
    ),
    "libc/arch-common/bionic/crtend_so.S": Source(
        1668,
        "build",
        "both",
        "bb9e63f580f756b7cddb5a36e53c2545df7bcea681a248c647f090ee2c05ef29",
        "1e0a3943eba46d49539ab797e1675cfb8dce72fa",
    ),
    "libc/arch-common/bionic/pthread_atfork.h": Source(
        1327,
        "build",
        "both",
        "bdc11ac701a0847a51a7e93760bb0fe12389b8d25b36080f1e0d1fb7ba07e2b1",
        "02e383d31f8f41c666be50082494830b95a3b555",
    ),
    "libc/include/android/api-level.h": Source(
        7953,
        "ship",
        "both",
        "31fee93a32b3bfce3a8f2eef90b578a940081c0956cbe66468dc8ff43015f7bc",
        "2965bb58005c143411bf0106bd826e190fb404ae",
    ),
    "libc/include/android/versioning.h": Source(
        4020,
        "ship",
        "both",
        "e89f59dda1cb8e1dd37575e24c8f928f697c776b1bfe0e0bb607da4f931e5bbc",
        "1cf6e5107ea09e43400b51d0bd562a09b2a696aa",
    ),
    "libc/include/bits/posix_limits.h": Source(
        9168,
        "ship",
        "both",
        "d1c3d19e43a95185144caf7a8b2372cf9a88b67a5b254e3947521e461a19b1d5",
        "2cb91ff46df9fde5b3977a723e2fc87aa0503a1a",
    ),
    "libc/include/bits/pthread_types.h": Source(
        2556,
        "ship",
        "both",
        "a383b92a43cef5cd43b36ec965f7b33dbd14bab51b447ce4d3783cda8e2a6de7",
        "f0ab2a6fae53142c0f094a6d48b89165a0d7f4b7",
    ),
    "libc/include/bits/strcasecmp.h": Source(
        2911,
        "ship",
        "both",
        "43e9619daee9abcd034362846e5522acfad8df388f70e20d6cd802d74b00c001",
        "c5bdae16405f16c808634e2c498278bfdcd63838",
    ),
    "libc/include/bits/wchar_limits.h": Source(
        1856,
        "ship",
        "both",
        "8b0309028526bde5d40be47ef28d40aa4463b79322340e0a1ebd83a094eeff8f",
        "eb2271382479c3cd6019177e177cea10fed4ae4b",
    ),
    "libc/include/limits.h": Source(
        5100,
        "ship",
        "both",
        "ea2234585f42e2b0f0cba2babb72eb0077139d8ab38f464b5659a45b127e04d2",
        "a8ff2cbc53fbc367a67e76f275d85fd49408f0e9",
    ),
    "libc/include/math.h": Source(
        13179,
        "ship",
        "both",
        "e50651fab9321e622d899d48dc3c30113f3d11f65a97775253c543afec8aaa10",
        "0d0394026354e1b4491403b1ecce1ad51795853b",
    ),
    "libc/include/setjmp.h": Source(
        4950,
        "ship",
        "both",
        "fe68fb9043c92ef91acb174d2f3b71d41fc4814b3434d75df3b589eb190345f9",
        "0236fe6e821483cb802992590c081de9c8659b3f",
    ),
    "libc/include/stdint.h": Source(
        7439,
        "ship",
        "both",
        "c37028b9bf6b76e9ebe4d2c6ca2cd3bc280b57d9d2593da3bbf2888d9966c3f4",
        "1e228fa559110459c537aa19504a36e7653a0087",
    ),
    "libc/include/string.h": Source(
        15340,
        "ship",
        "both",
        "a8fad67dad381339e4f47a711f962f2d9e97a9d7d5878dd2637f0319ad9451a3",
        "06793c34e8b431f273476736f963655073de88e6",
    ),
    "libc/include/strings.h": Source(
        3747,
        "ship",
        "both",
        "3fd37db73727cabb576562e9bfa2cdbd59a7659a832619dac8e5f43137ad8668",
        "7543edca533675c3837bad031ae6a9663675b051",
    ),
    "libc/include/sys/cdefs.h": Source(
        14297,
        "ship",
        "both",
        "e5c5aad8f5a5d28ec6d8741e7672ba091977c9f281fddce6e4310960ad8c15cd",
        "bd57ef035128cda273c1e0bdbf8a351fa5ad04d0",
    ),
    "libc/include/sys/types.h": Source(
        4980,
        "ship",
        "both",
        "dbf62d44925a1b5265be69234de54e6022d58e5fde835a7573bf1964bde9b235",
        "dcb0e58589c887d46c520c18da01e1f21ddc0579",
    ),
    "libc/include/xlocale.h": Source(
        1987,
        "ship",
        "both",
        "0ca127f21e39067cb1c5f272adeea80a4c0110158023f6a321600f8c85292ec0",
        "aa1cefd5c1d33749926ed70ba3365c9c62548bc1",
    ),
    "libc/kernel/uapi/asm-arm64/asm/bitsperlong.h": Source(
        300,
        "ship",
        "arm64",
        "e17e530bc6dc93aa7fe66ec8c176e86487b8eb14e80255531c04cc9808513053",
        "312224c20ff2a38a5c989b08b5952651c6477c2b",
    ),
    "libc/kernel/uapi/asm-arm64/asm/posix_types.h": Source(
        405,
        "ship",
        "arm64",
        "54c9c13ed0a1894336d70abb439bcd182a19c04396a05e379f217f0ff5eb132f",
        "00df90d44aeb7f09a7b5e0e90b89bbee8f1de0ac",
    ),
    "libc/kernel/uapi/asm-arm64/asm/types.h": Source(
        204,
        "ship",
        "arm64",
        "4b8d02254d1d5ee1b7eb6ee962a63a935330799c14eaf07f93698c2cf8e59e2a",
        "a030be86d321b3e51c78cb0f18085d2145682427",
    ),
    "libc/kernel/uapi/asm-arm64/asm/unistd.h": Source(
        200,
        "build",
        "arm64",
        "4da7ddf17f9f2c986e2aeffba0c3247ac7984dd96ef1120996db176b78f88d23",
        "178578fdf907905542639789661c76cc7c68e9dc",
    ),
    "libc/kernel/uapi/asm-arm64/asm/unistd_64.h": Source(
        9086,
        "build",
        "arm64",
        "7e830959a08125428f0b1b870dc9bb39a04f74ef7c2ef89c55dfb8c0e4857b37",
        "41b77d7d8dd38467c3ef80fbde334890f068d8a5",
    ),
    "libc/kernel/uapi/asm-generic/bitsperlong.h": Source(
        512,
        "ship",
        "both",
        "363e0abd35c267c94d736d8bb04af196fa4f8e5959d26fe1be9b041adb3f154b",
        "11dcc1a11f197028d168fcc9fb907975f4a8a873",
    ),
    "libc/kernel/uapi/asm-generic/int-ll64.h": Source(
        686,
        "ship",
        "both",
        "a34ebb4aa0604ff54f78922f50bb7dc82d9587cfc426aa4f0c1ef0c74b051dbe",
        "505efc646249c3171792063dba986923b7838b3a",
    ),
    "libc/kernel/uapi/asm-generic/posix_types.h": Source(
        2039,
        "ship",
        "both",
        "fd5996951df10efc97bd123c91fa6d3dcf877251ed0ccb32761d4083a1bf293b",
        "4792662e4f9443f40bffd5f344bce5efbf342cd4",
    ),
    "libc/kernel/uapi/asm-generic/types.h": Source(
        282,
        "ship",
        "both",
        "f676ab1191fcad85565228eb0e4cf53edc98e5fb0b4dba9ae3ebf1855e9ada96",
        "d3e6944626023dae8909c4a3ecc5d2aa38324ceb",
    ),
    "libc/kernel/uapi/asm-x86/asm/bitsperlong.h": Source(
        395,
        "ship",
        "x86_64",
        "e343383ddabdc6ebd93054b2d758efc6247daf8ec5e1e0769f0dfa9f9e63be84",
        "e5df11c2766a98aa7e62e79fcae121409bb3a0d6",
    ),
    "libc/kernel/uapi/asm-x86/asm/posix_types.h": Source(
        324,
        "ship",
        "x86_64",
        "1248ea8b090d92a712b85cb0e4a71464404b100e7c85e90b4edb19a66198c30a",
        "c57f1e06465d4d4860a0078eed06b9fdfe172a3a",
    ),
    "libc/kernel/uapi/asm-x86/asm/posix_types_64.h": Source(
        505,
        "ship",
        "x86_64",
        "daba3320e459d498913ce51af77fc820f1edcfcb64e551170259c82a2ac99e1b",
        "26db149e54994c1d9317e1699ed35ddb17d21a8b",
    ),
    "libc/kernel/uapi/asm-x86/asm/types.h": Source(
        204,
        "ship",
        "x86_64",
        "4b8d02254d1d5ee1b7eb6ee962a63a935330799c14eaf07f93698c2cf8e59e2a",
        "a030be86d321b3e51c78cb0f18085d2145682427",
    ),
    "libc/kernel/uapi/asm-x86/asm/unistd.h": Source(
        415,
        "build",
        "x86_64",
        "5f2173b31c189b51c081277e4ad876e822fcc6050ed35686aad9ff4551d6ab7f",
        "fc9d18d2d8d1a58f5473417f8d4eef2b8922bfd8",
    ),
    "libc/kernel/uapi/asm-x86/asm/unistd_64.h": Source(
        10553,
        "build",
        "x86_64",
        "f5932f5da1d4bbec377207d7694a1918d6362174a840a271efa346977128b8d6",
        "47976abdcda2ca485eb85d203351b6ebc199edca",
    ),
    "libc/kernel/uapi/linux/limits.h": Source(
        544,
        "ship",
        "both",
        "b67c7dc51627702441cc1761f20dc7f358e0e9cbfc1d8e690cf16890d3e1a2e7",
        "e2d5103c3f12355bb51268e843666a182af2754f",
    ),
    "libc/kernel/uapi/linux/posix_types.h": Source(
        537,
        "ship",
        "both",
        "b4dfa3505ea263b2867e7305c6ca1274415cde7236496cf524556ce0ce59099d",
        "b21f63fcc0a0b382263bff27e2dd6e4ab14c77ca",
    ),
    "libc/kernel/uapi/linux/stddef.h": Source(
        918,
        "ship",
        "both",
        "23f0b9bcbe8652a75f05fea737d5312ac240101d59397af33bc041f19f80f082",
        "5c9e2570bd4a1cfc0fe85689071703493355e30a",
    ),
    "libc/kernel/uapi/linux/types.h": Source(
        1048,
        "ship",
        "both",
        "841ed4d21f88467caf5d01af9e551f25e5e7167bb2bd25139712cf9b1f81bf1d",
        "f33febd72d49730db3340b9a12d9d6e15d07caa1",
    ),
    "libc/kernel/uapi/linux/version.h": Source(
        389,
        "check",
        None,
        "48fdd11cab86262fa1c5215ce695966732d3e699cccd4eae645195bbd04fd94b",
        "8b12181eefdb93cdccc9fe572fa449d3240d4bd2",
    ),
    "libc/private/bionic_asm.h": Source(
        4344,
        "build",
        "both",
        "6291935944e995c5111f913a34446fadb529b5dabf0c3d099eaffca6a550c819",
        "05af4abc03894f51f2934375c357b61a9dce9893",
    ),
    "libc/private/bionic_asm_arm64.h": Source(
        3097,
        "build",
        "arm64",
        "b6f66c98e064969b75e2af97481517ac5ce7fa0d89fa0052ea021fd30f1d8104",
        "d245967373a74cbbe48fd5541fd63bb32c0986df",
    ),
    "libc/private/bionic_asm_note.h": Source(
        1548,
        "build",
        "both",
        "57e505697ec2ab18ceda59187db33b7a9c829a9180a8721fea3afa24958b8cf1",
        "9a533c0000837777ff3beee4ab24f1f144b1ddb5",
    ),
    "libc/private/bionic_asm_x86_64.h": Source(
        2044,
        "build",
        "x86_64",
        "0e4299fd7fe15b4bba4f3d79849e558a5fdc63e64e239a14f7519644420745af",
        "b8e38071734097acbecc3eeccd758bb4a98d2f07",
    ),
    "libc/libc.map.txt": Source(
        38678,
        "check",
        None,
        "5831b40390f17a34536513c79735bc632aa3d3f4d81fc4ed5f5ea8ff6ed5107c",
        "b0633eb32feabe48f2e1575184a69e423626913f",
    ),
    "libm/libm.map.txt": Source(
        4751,
        "check",
        None,
        "addb0e674222bb262646809f768328e27325266e122f569e80282216cf5c84c0",
        "b9a0db23a6d93dd5e457602647a7f3a73241773a",
    ),
}

# Where each shipped file goes in the tree, from its place in bionic.
_UAPI_ARCH = {"libc/kernel/uapi/asm-arm64/": "arm64", "libc/kernel/uapi/asm-x86/": "x86_64"}


def ship_place(path: str) -> str:
    """The NDK's place, under usr/include, of a shipped bionic file."""
    for prefix, abi in _UAPI_ARCH.items():
        if path.startswith(prefix):
            return f"usr/include/{ABIS[abi]}/{path[len(prefix) :]}"
    for prefix in ("libc/kernel/uapi/", "libc/include/"):
        if path.startswith(prefix):
            return f"usr/include/{path[len(prefix) :]}"
    raise ValueError(f"{path} has no place in the sysroot")


SHIP = {p: ship_place(p) for p, s in SOURCES.items() if s.role == "ship"}
# The build's own copy of the four unistd headers, beside the shipped ones,
# in the temporary build sysroot only.
_BUILD_HEADERS = {
    p: ship_place(p)
    for p, s in SOURCES.items()
    if s.role == "build" and p.startswith("libc/kernel/")
}
# What the build makes, relative to android-sysroot/, each held to its pin.
OUTPUTS = {
    "usr/lib/aarch64-linux-android/33/crtbegin_so.o": "5781a58d6c1f273ec5a642548f6fc37a22b8916febaf4fb8ccb12966431d2520",
    "usr/lib/aarch64-linux-android/33/crtend_so.o": "8703453e41637538b26a57ce0461f0ad5f2abfbcdf9303166b82b47131a3d4be",
    "usr/lib/x86_64-linux-android/33/crtbegin_so.o": "ecf36375989bce14e04491cecc765f874aa0104736e5b083900110341f515906",
    "usr/lib/x86_64-linux-android/33/crtend_so.o": "022ba53c856b6a2c5028b4fbb11be638b102e100606b594b111c3ea4012834b6",
    "NOTICE.txt": "8eb2fa94fd79faedd4abdd76b013f1a0685df40af338b31f8110e6d7f0b3c066",
}
RECORD_HEAD = (
    "# R5's Android sysroot (tools/fetch_android_sysroot.py, specs/android-sysroot.md): bionic's headers and crt objects, built here.",
    f"# bionic: {BASE} at {COMMIT} ({TAG}): each file held to its pinned sha256 and git blob",
    f"# built with llvm-mingw {toolchain.MINGW_RELEASE}'s clang {toolchain.MINGW_CLANG[0]} (toolchain.MINGW_RELEASE); the crt objects and NOTICE.txt held to their pins",
)


class Refused(Exception):
    """What a run could not do, in the words it prints after "error: "."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_id(data: bytes) -> str:
    """git's id for these bytes as a blob."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def held(path: str, data: bytes) -> str | None:
    """None when data is the pinned file at path; else what differs."""
    pin = SOURCES[path]
    got = sha256(data)
    if got != pin.sha256:
        return f"sha256 {got}, pinned {pin.sha256}"
    got = blob_id(data)
    if got != pin.blob:
        return f"git blob {got}, pinned {pin.blob}"
    return None


def needed(roles: tuple[str, ...] = ("ship", "build")) -> list[str]:
    return sorted(p for p, s in SOURCES.items() if s.role in roles)


def show(path: Path) -> str:
    """A path as a person reads it: relative to the checkout when inside it."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def cache_key() -> str:
    """The first 16 hex of a sha256 over COMMIT and every pin: the source
    cache's key in CI, which moves with a pin and with nothing else."""
    text = (
        COMMIT
        + "\n"
        + "".join(
            f"{p} {s.size} {s.role} {s.abi} {s.sha256} {s.blob}\n"
            for p, s in sorted(SOURCES.items())
        )
    )
    return sha256(text.encode("utf-8"))[:16]


# ---- fetching ---------------------------------------------------------------

# One run's requests: when the first was made (the deadline counts from it),
# when the last was, and whether any answer came back at all.
_RUN: dict[str, float | bool | None] = {"first": None, "last": None, "answered": False}


# Failures of a body while it is read or decoded: tried again, never pin words.
class _CutShort(Exception):
    """A body that failed while it was read, after the server answered."""


_BROKEN = (
    _CutShort,
    http.client.HTTPException,
    EOFError,
    tarfile.ReadError,
    zlib.error,
    gzip.BadGzipFile,
    binascii.Error,
    UnicodeDecodeError,
    json.JSONDecodeError,
)
# Failures to reach the server at all.
_UNREACHED = (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError)


def new_run() -> None:
    """Forget the pacing, the deadline and whether anything answered."""
    _RUN.update(first=None, last=None, answered=False)


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - fixed https URLs
        try:
            return r.read()
        except OSError as exc:  # a reset or a timeout mid-body: it answered
            raise _CutShort(f"{type(exc).__name__}: {exc}") from None


def _retry_after(exc: urllib.error.HTTPError, now: float) -> float | None:
    """Retry-After, in seconds or as an HTTP date, in seconds from now."""
    value = exc.headers.get("Retry-After") if exc.headers else None
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def fetch(url: str, *, decode=None, get=None, sleep=time.sleep, clock=time.monotonic):
    """One request, paced, waited on and tried again as android.googlesource.com
    needs: what `decode` makes of the body (the body when None). Raises Refused
    in words that never speak of pins: only a file whose bytes are not its
    pin's does that, and that is the caller's to say."""
    get = get or _get
    host = urllib.parse.urlsplit(url).hostname or url
    last_reason = ""
    for k in range(1, TRIES + 1):
        now = clock()
        if _RUN["last"] is not None and now - _RUN["last"] < PACE:
            sleep(PACE - (now - _RUN["last"]))
        if _RUN["first"] is None:
            _RUN["first"] = clock()
        _RUN["last"] = clock()
        wait: float | None = None
        try:
            body = get(url)
            _RUN["answered"] = True
            return decode(body) if decode else body
        except urllib.error.HTTPError as exc:
            _RUN["answered"] = True
            if exc.code == 404:
                raise Refused(
                    f"{url}: not found (HTTP 404): the pinned commit or path is not on {host}"
                ) from None
            if exc.code != 429 and exc.code < 500:
                raise Refused(f"{host} refused {url} (HTTP {exc.code})") from None
            last_reason = f"HTTP {exc.code}"
            wait = _retry_after(exc, clock())
            words = f"{host} asked this machine to wait (HTTP {exc.code})"
        except _UNREACHED as exc:
            last_reason = str(getattr(exc, "reason", exc))
            words = f"could not reach {host} ({last_reason})"
        except (*_BROKEN, OSError) as exc:
            _RUN["answered"] = True
            last_reason = f"{type(exc).__name__}: {exc}"
            words = f"{host} sent a broken or non-archive response for {url} ({last_reason})"
        if k == TRIES:
            break
        if wait is None:
            wait = float(WAITS[min(k - 1, len(WAITS) - 1)])
        wait = min(wait, WAIT_CAP)
        if clock() + wait - _RUN["first"] > DEADLINE:
            last_reason += f"; waiting {wait:.0f} s more would pass the run's {DEADLINE:.0f} s"
            break
        print(f"{words}; trying again in {wait:.0f} s ({k} of {TRIES})", file=sys.stderr)
        sleep(wait)
    ways = (
        f"or fill vendor/{CACHE} from a checkout of bionic at {COMMIT[:8]} (--from <folder>); "
        "or copy it from a machine that has it and pass --offline"
    )
    if not _RUN["answered"]:
        raise Refused(f"cannot reach {host} ({last_reason}): connect and run this again, {ways}")
    raise Refused(
        f"{host} would not serve {url} after {k} tries ({last_reason}): try again later; {ways}"
    )


def archive_url(directory: str) -> str:
    return f"{BASE}/+archive/{COMMIT}/{directory}.tar.gz"


def text_url(path: str) -> str:
    return f"{BASE}/+/{COMMIT}/{path}?format=TEXT"


def _archive_of(path: str) -> str:
    return next(d for d in ARCHIVES if path.startswith(d + "/"))


def _untar(blob: bytes) -> dict[str, bytes]:
    """Every regular file in a gzipped tar, by its name; read whole, so a
    body cut short fails here and is tried again."""
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
        for m in t.getmembers():
            if m.isfile():
                f = t.extractfile(m)
                assert f is not None
                out[m.name.removeprefix("./")] = f.read()
    return out


def cache_problems(cache: Path, roles: tuple[str, ...] = ("ship", "build")) -> list[str]:
    """Each file of those roles the cache lacks or holds off its pins."""
    out = []
    for path in needed(roles):
        f = cache / path
        if not f.is_file():
            out.append(f"{path}: missing")
        else:
            why = held(path, f.read_bytes())
            if why:
                out.append(f"{path}: {why}")
    return out


def sources(
    cache: Path,
    *,
    roles=("ship", "build"),
    offline=False,
    get=None,
    sleep=time.sleep,
    clock=time.monotonic,
) -> Path:
    """The cache, holding every file of those roles as pinned: each one it
    holds off its pins is fetched again, and nothing is written until every
    fetched file is as pinned. Offline, what is missing is named."""
    want = [p for p in needed(roles) if p not in TEXT_FILES]
    bad = [p for p in want if not (cache / p).is_file() or held(p, (cache / p).read_bytes())]
    texts = [p for p in needed(roles) if p in TEXT_FILES]
    bad_texts = [p for p in texts if not (cache / p).is_file() or held(p, (cache / p).read_bytes())]
    if offline and (bad or bad_texts):
        p = (bad or bad_texts)[0]
        why = "missing"
        if (cache / p).is_file():
            why = (
                "sha256 differs"
                if held(p, (cache / p).read_bytes()).startswith("sha256")
                else "git blob differs"
            )
        raise Refused(f"--offline, and {show(cache)} has no {p} as pinned ({why})")
    got: dict[str, bytes] = {}
    for directory in sorted({_archive_of(p) for p in bad}):
        url = archive_url(directory)
        print(f"fetching {url}")
        members = fetch(url, decode=_untar, get=get, sleep=sleep, clock=clock)
        for path in (p for p in SOURCES if p not in TEXT_FILES and _archive_of(p) == directory):
            name = path[len(directory) + 1 :]
            if name not in members:
                raise Refused(
                    f"{url} holds no {path}: the pinned commit or path is not what "
                    f"{urllib.parse.urlsplit(url).hostname} serves; nothing was written"
                )
            why = held(path, members[name])
            if why:
                raise Refused(f"{path} from {url}: {why}; nothing was written")
            got[path] = members[name]
    for path in bad_texts:
        url = text_url(path)
        print(f"fetching {url}")
        data = fetch(url, decode=base64.b64decode, get=get, sleep=sleep, clock=clock)
        why = held(path, data)
        if why:
            raise Refused(f"{path} from {url}: {why}; nothing was written")
        got[path] = data
    try:
        for path, data in sorted(got.items()):
            f = cache / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
    except OSError as exc:
        raise Refused(f"could not write {show(cache)} ({exc})") from None
    return cache


def fill_from(folder: Path, cache: Path) -> list[str]:
    """The cache filled from a folder laid out as bionic, each file held to
    its pins as it is copied: what the folder lacked or held off them."""
    problems = []
    n = 0
    for path in needed(("ship", "build", "check")):
        src = folder / path
        if not src.is_file():
            if SOURCES[path].role != "check":
                problems.append(f"{path}: not in {folder}")
            continue
        data = src.read_bytes()
        why = held(path, data)
        if why:
            problems.append(f"{path}: {why}")
            continue
        (cache / path).parent.mkdir(parents=True, exist_ok=True)
        (cache / path).write_bytes(data)
        n += SOURCES[path].role != "check"
    print(f"{n} of {len(needed())} bionic files the build reads, from {folder}, are as pinned")
    for line in problems:
        print(f"  {line}")
    return problems


# ---- building ---------------------------------------------------------------


def mingw_tools() -> tuple[str, str]:
    """llvm-mingw's clang and ld.lld, the ones the game library is built with,
    or Refused before anything is fetched or built."""
    clang, lld = toolchain.mingw_clang(), toolchain.mingw_lld()
    if clang is None or lld is None:
        raise Refused(
            "no llvm-mingw (python tools/fetch_mingw.py fetches it): the crt objects are built with its clang"
        )
    problem = toolchain.mingw_identity_problem(clang)
    if problem:
        raise Refused(
            f"{problem}, and the crt objects are built by it: python tools/fetch_mingw.py fetches it"
        )
    return clang, lld


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=toolchain.clean_clang_env(),
        check=False,
    )
    if proc.returncode != 0:
        raise Refused(
            f"{Path(cmd[0]).name} failed building the crt objects:\n{proc.stdout}{proc.stderr}".rstrip()
        )


def build_crt(
    cache: Path, work: Path | None = None, *, extra: tuple[str, ...] = ()
) -> dict[str, bytes]:
    """crtbegin_so.o and crtend_so.o for both ABIs, built from the cache by
    llvm-mingw's clang in a temporary build sysroot (under `work` when given),
    each held to its pin: their place under android-sysroot/ -> bytes.
    `extra` is more flags, for the mutation that shows the pins hold."""
    clang, lld = mingw_tools()
    cache = cache.resolve()  # clang runs in the build sysroot's folder
    common = cache / "libc" / "arch-common" / "bionic"
    out: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="soa-sysroot-", dir=work) as tmp:
        root = Path(tmp)
        sysroot = root / "sysroot"
        for path, place in {**SHIP, **_BUILD_HEADERS}.items():
            (sysroot / place).parent.mkdir(parents=True, exist_ok=True)
            (sysroot / place).write_bytes((cache / path).read_bytes())
        for abi, triple in ABIS.items():
            o = root / abi
            o.mkdir()
            cc = [
                clang,
                f"--target={triple}{API}",
                f"--sysroot={sysroot}",
                *CRT_FLAGS,
                *extra,
                f"-I{cache / 'libc'}",
            ]
            _run([*cc, "-c", str(common / "crtbegin_so.c"), "-o", str(o / "crtbegin_so_c.o")], root)
            _run(
                [
                    *cc,
                    f"-DPLATFORM_SDK_VERSION={API}",
                    "-c",
                    str(common / "crtbrand.S"),
                    "-o",
                    str(o / "crtbrand.o"),
                ],
                root,
            )
            _run(
                [
                    lld,
                    "-r",
                    str(o / "crtbegin_so_c.o"),
                    str(o / "crtbrand.o"),
                    "-o",
                    str(o / "crtbegin_so.o"),
                ],
                root,
            )
            _run([*cc, "-c", str(common / "crtend_so.S"), "-o", str(o / "crtend_so.o")], root)
            for name in ("crtbegin_so.o", "crtend_so.o"):
                place = f"usr/lib/{triple}/{API}/{name}"
                data = (o / name).read_bytes()
                if sha256(data) != OUTPUTS[place]:
                    raise Refused(
                        f"{name} for {abi} built here has sha256 {sha256(data)}, pinned {OUTPUTS[place]}: the clang "
                        f"is not llvm-mingw {toolchain.MINGW_RELEASE}'s {toolchain.MINGW_CLANG[0]}, or the recipe changed; "
                        "nothing was written"
                    )
                out[place] = data
    return out


def leading_comments(text: str) -> str:
    """Every /* ... */ block before a file's first line of code, verbatim, one
    after another: where bionic's files say whose they are and on what terms."""
    blocks = []
    i = 0
    while True:
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                break
            blocks.append(text[i : end + 2])
            i = end + 2
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        else:
            break
    return "\n\n".join(blocks)


NOTICE_PREFACE = f"""\
R5's Android sysroot: the C headers the phone's game library is compiled against, and the crt objects
every shared library's link takes, for arm64 and x86_64 at Android API {API}.

Every file of it is bionic's, Android's C library, at commit {COMMIT} ({TAG}) of
{BASE}, unmodified, or built from bionic's source by llvm-mingw
{toolchain.MINGW_RELEASE}'s clang {toolchain.MINGW_CLANG[0]}. Below, each file's own words on whose it is and on what terms, as
the file holds them: the 30 headers in the sysroot, then the files compiled into crtbegin_so.o and
crtend_so.o, then the headers read while building them, of which nothing is compiled in.

Texts the notices name but do not hold:
- the Apache License, Version 2.0, is the first part of licenses/llvm.txt, LLVM's licence, which is that
  text followed by LLVM's exceptions;
- the Linux user-space headers in usr/include/linux, usr/include/asm-generic and usr/include/<triple>/asm
  say only that they are generated: Linux marks them GPL-2.0 WITH Linux-syscall-note, whose texts are
  licenses/linux-gpl-2.0.txt and licenses/linux-syscall-note.txt.
"""


def notice_text(cache: Path) -> str:
    """NOTICE.txt: the preface, then each file's leading comments under its
    name, in three groups. The same bytes on every machine."""
    parts = [NOTICE_PREFACE]
    groups = (
        (
            "the headers in the sysroot",
            sorted(SHIP, key=lambda p: SHIP[p]),
            lambda p: f"{SHIP[p]} (bionic {p})",
        ),
        (
            "compiled into crtbegin_so.o or crtend_so.o",
            [p for p in needed(("build",)) if not p.startswith("libc/kernel/")],
            lambda p: f"bionic {p}",
        ),
        (
            "read while building the crt objects; nothing of it is compiled in",
            [p for p in needed(("build",)) if p.startswith("libc/kernel/")],
            lambda p: f"bionic {p}",
        ),
    )
    for title, paths, head in groups:
        parts.append(f"\n==== {title} ====\n")
        for path in paths:
            text = (cache / path).read_bytes().decode("utf-8")
            parts.append(f"\n== {head(path)}\n\n{leading_comments(text)}\n")
    return "".join(parts)


def expected_record() -> dict[str, str]:
    """The record a tree this script builds holds: android-sysroot/<path> ->
    sha256, from the pins alone."""
    out = {f"{DEST}/{place}": SOURCES[path].sha256 for path, place in SHIP.items()}
    out.update({f"{DEST}/{place}": pin for place, pin in OUTPUTS.items()})
    return out


def read_record(path: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                digest, _, name = line.partition("  ")
                files[name.strip()] = digest.strip()
    return files


def write_record(path: Path, files: dict[str, str]) -> None:
    lines = [*RECORD_HEAD, *(f"{d}  {n}" for n, d in sorted(files.items()))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def verify(vendor: Path) -> list[str]:
    """What is not as recorded, as facts and never advice: no record; a record
    not this script's; each recorded file missing or changed; each file under
    the tree the record does not name. An OSError is a fact too."""
    record = vendor / RECORD
    if not record.is_file():
        return [f"no {show(record)}"]
    try:
        files = read_record(record)
        want = expected_record()
        for name in sorted(set(files) | set(want)):
            if files.get(name) != want.get(name):
                return [
                    f"the record is not this script's ({name}: recorded {files.get(name, 'nothing')}, this script pins {want.get(name, 'nothing')})"
                ]
        out = []
        for name, digest in sorted(files.items()):
            f = vendor / name
            if not f.is_file():
                out.append(f"{name}: recorded but missing")
            elif sha256(f.read_bytes()) != digest:
                out.append(f"{name}: differs from the record")
        tree = vendor / DEST
        if tree.is_dir():
            for f in sorted(tree.rglob("*")):
                name = f.relative_to(vendor).as_posix()
                if f.is_file() and name not in files:
                    out.append(f"{name}: not in the record")
        return out
    except (OSError, ValueError) as exc:
        return [f"{show(vendor / DEST)}: {type(exc).__name__}: {exc}"]


def sysroot_digest(vendor: Path) -> str:
    """sha256 of the record's usr/ lines alone, the headers and crt objects a
    compile or a link reads: NOTICE.txt and the comments move nothing."""
    files = read_record(vendor / RECORD)
    lines = [f"{d}  {n}\n" for n, d in sorted(files.items()) if n.startswith(f"{DEST}/usr/")]
    return sha256("".join(lines).encode("utf-8"))


# Renames and removals, which Windows' Defender or indexer can refuse for a
# moment after the files were written; patched by the tests.
_rename = os.rename
_rmtree = shutil.rmtree
_PAUSES = (0.2, 0.4, 0.8, 1.6, 3.2)


def _retrying(fn, *args, sleep=None) -> None:
    sleep = sleep or time.sleep
    for pause in (*_PAUSES, None):
        try:
            fn(*args)
            return
        except OSError:
            if pause is None:
                raise
            sleep(pause)


def build(vendor: Path, cache: Path, *, sleep=None) -> None:
    """The tree from the cache, put in place so that a stop at any step leaves
    no record, which the next run takes as "build it again"."""
    record, dest = vendor / RECORD, vendor / DEST
    new, old = vendor / f"{DEST}.new", vendor / f"{DEST}.old"
    try:
        record.unlink(missing_ok=True)
        for leftover in (new, old):
            if leftover.exists():
                _retrying(_rmtree, leftover, sleep=sleep)
        new.mkdir(parents=True)
    except OSError as exc:
        who = "Windows" if os.name == "nt" else "the system"
        raise Refused(
            f"{who} would not let this clear {show(vendor)} for the build ({exc}): close anything "
            "using that folder, such as an Explorer window, and run this again; nothing is recorded, "
            "so the next run builds it again"
        ) from None
    crt = build_crt(cache)
    print(f"built crtbegin_so.o and crtend_so.o for {' and '.join(ABIS)}: as pinned")
    for path, place in SHIP.items():
        data = (cache / path).read_bytes()
        why = held(path, data)
        if why:
            raise Refused(f"{path} in {show(cache)}: {why}; nothing was written")
        (new / place).parent.mkdir(parents=True, exist_ok=True)
        (new / place).write_bytes(data)
    for place, data in crt.items():
        (new / place).parent.mkdir(parents=True, exist_ok=True)
        (new / place).write_bytes(data)
    notice = notice_text(cache).encode("utf-8")
    if sha256(notice) != OUTPUTS["NOTICE.txt"]:
        raise Refused(
            f"NOTICE.txt made here has sha256 {sha256(notice)}, pinned {OUTPUTS['NOTICE.txt']}; nothing is recorded"
        )
    (new / "NOTICE.txt").write_bytes(notice)
    print(f"wrote {DEST}/NOTICE.txt: as pinned")
    try:
        if dest.exists():
            _retrying(_rename, dest, old, sleep=sleep)
        _retrying(_rename, new, dest, sleep=sleep)
    except OSError as exc:
        who = "Windows" if os.name == "nt" else "the system"
        raise Refused(
            f"{who} would not let this replace {dest} ({exc}): close anything using that folder, such as an "
            "Explorer window, and run this again; nothing is recorded, so the next run builds it again"
        ) from None
    files = {
        f.relative_to(vendor).as_posix(): sha256(f.read_bytes())
        for f in sorted(dest.rglob("*"))
        if f.is_file()
    }
    write_record(record, files)
    print(f"recorded {len(files)} file(s) in {show(record)}")
    if old.exists():
        try:
            _retrying(_rmtree, old, sleep=sleep)
        except OSError as exc:
            print(f"note: {show(old)} could not be removed ({exc}); the next run removes it")


def ensure(
    vendor: Path, *, offline: bool = False, get=None, sleep=None, clock=time.monotonic
) -> str:
    """The plain run: the tree when it is there and as recorded; else built
    again from the cache, filled first (no request when it is whole)."""
    dest, cache = vendor / DEST, vendor / CACHE
    facts = verify(vendor)
    if not facts:
        return f"{show(dest)} is there and as recorded ({len(read_record(vendor / RECORD))} file(s) checked)"
    if dest.exists() or (vendor / RECORD).exists():
        print(f"{show(dest)} is not as recorded ({facts[0]}); building it again from {show(cache)}")
    mingw_tools()
    sources(cache, offline=offline, get=get, sleep=sleep or time.sleep, clock=clock)
    print(
        f"{len(needed())} of {len(needed())} bionic files the build reads, at {COMMIT[:8]} ({TAG}), are as pinned"
    )
    build(vendor, cache, sleep=sleep)
    return ""


def check_upstream(get=None, sleep=time.sleep, clock=time.monotonic) -> tuple[list[str], int]:
    """Each pin that is not bionic's own blob at COMMIT by its tree listing,
    and the tag's commit when it is not COMMIT ([] when all hold), and how
    many pins were compared."""

    def listing(body: bytes) -> dict:
        text = body.decode("utf-8")
        if "{" not in text:
            raise json.JSONDecodeError("no JSON in the answer", text, 0)
        return json.loads(text[text.index("{") :])

    out = []
    compared = 0
    tag = fetch(
        f"{BASE}/+/refs/tags/{TAG}?format=JSON", decode=listing, get=get, sleep=sleep, clock=clock
    )
    if tag.get("commit") != COMMIT:
        out.append(f"refs/tags/{TAG} is {tag.get('commit')}, not {COMMIT}")
    for directory in sorted({p.rsplit("/", 1)[0] for p in SOURCES}):
        tree = fetch(
            f"{BASE}/+/{COMMIT}/{directory}?format=JSON",
            decode=listing,
            get=get,
            sleep=sleep,
            clock=clock,
        )
        ids = {e["name"]: e["id"] for e in tree.get("entries", [])}
        for path, pin in sorted(SOURCES.items()):
            if path.rsplit("/", 1)[0] != directory:
                continue
            compared += 1
            if ids.get(path.rsplit("/", 1)[1]) != pin.blob:
                out.append(
                    f"{path}: bionic's blob is {ids.get(path.rsplit('/', 1)[1], 'missing')}, pinned {pin.blob}"
                )
    return out, compared


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--vendor", type=Path, default=ROOT / "vendor")
    ap.add_argument(
        "--offline", action="store_true", help="never ask the network; the cache must hold the 44"
    )
    ap.add_argument(
        "--from",
        dest="from_",
        type=Path,
        metavar="DIR",
        help="fill the cache from a folder laid out as bionic",
    )
    ap.add_argument(
        "--lists",
        action="store_true",
        help="also fetch bionic's two symbol lists, which tests read",
    )
    ap.add_argument("--verify", action="store_true", help="only check the tree against the record")
    ap.add_argument(
        "--check-upstream", action="store_true", help="hold every pin to bionic's own tree listing"
    )
    ap.add_argument("--cache-key", action="store_true", help="print the source cache's key, for CI")
    args = ap.parse_args(argv)
    vendor = args.vendor
    new_run()
    try:
        if args.cache_key:
            print(f"key={cache_key()}")
            return 0
        if args.verify:
            facts = verify(vendor)
            for line in facts:
                print(line, file=sys.stderr)
            try:
                n = len(read_record(vendor / RECORD))
            except OSError, ValueError:
                n = 0
            bad = [
                f for f in facts if f.endswith(("recorded but missing", "differs from the record"))
            ]
            whole = facts and not bad and not facts[0].startswith(f"{DEST}/")
            print(
                f"{0 if whole else n - len(bad)} of {n} recorded Android sysroot file(s) unchanged"
            )
            return 1 if facts else 0
        if args.check_upstream:
            bad, compared = check_upstream()
            for line in bad:
                print(line, file=sys.stderr)
            if not bad:
                print(
                    f"{compared} of {len(SOURCES)} pins are bionic's own blobs at {COMMIT[:8]} (refs/tags/{TAG} is {COMMIT[:8]})"
                )
            return 1 if bad else 0
        if args.from_:
            fill_from(args.from_, vendor / CACHE)
        line = ensure(vendor, offline=args.offline)
        if line:
            print(line)
        if args.lists:
            sources(vendor / CACHE, roles=("check",), offline=args.offline)
            print(f"the {len(TEXT_FILES)} check lists ({', '.join(TEXT_FILES)}) are as pinned")
        return 0
    except Refused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:  # what no step above put in words, still not a traceback
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
