"""Is the extracted executable the build config/ describes?

Everything in `config/` -- 7,144 function addresses and sizes, the HLE
bindings, the hooks, the tracepoints, the splits and symbols under
`config/GEAE8P/` -- is an address in *one* build of one executable. Point any
of it at a different region, a different revision or an executable somebody
patched and nothing complains: the recompiler translates whatever it is
given, the linker links it, the port boots it, and the result is wrong in
ways no other check in this repository can see, because every other check is
written in terms of those same addresses.

`config/GEAE8P/config.yml` already records the sha1 that decomp-toolkit
verifies before it splits. This module is the rest of the tree reading the
same line: `verify()` hashes the user's extracted executable, compares, and
returns a verdict that names both hashes. `tools/checkdump.py` is the command
that prints it; `tools/extract.py` calls it at the end of an extraction so
the answer arrives without anyone having to know the command exists.

Nothing here needs a disc image or the recompiler, and nothing here reads a
byte of the executable except to hash it.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .disc import BOOT_HEADER_SIZE, parse_boot

# tools/soa/dump.py -> the checkout this module belongs to. config.yml's paths
# are written relative to it ("Run from the repository root"), and resolving
# them here rather than against the current directory is what lets the check
# still happen when someone runs the extractor from somewhere else -- which is
# the person most likely to need it.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "GEAE8P" / "config.yml"

# The disc header the extractor writes beside the executable. Optional: it
# only ever sharpens the diagnosis, never decides it.
BOOT_BIN = Path("sys") / "boot.bin"

_SHA1 = re.compile(r"\A[0-9a-f]{40}\Z")

# config.yml is read with a parser narrow enough to describe in a sentence:
# `key: value` at column 0, one scalar per line, `#` comments and blank lines
# dropped. That is the whole of the file dtk writes, and this repository has
# no YAML dependency to spend on the other 95% of the spec -- `pip install -e
# .[dev]` brings in pytest, ruff and capstone and nothing else. Anything the
# parser does not understand is an error naming the line, never a silent
# default: a config.yml this could not read is exactly the case where
# guessing loses the check.
_SCALAR = re.compile(r"\A(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*?)\s*\Z")


class ProjectError(Exception):
    """config.yml does not say what this check needs it to say."""


def _show(path: Path) -> str:
    """A path as a reader of the message would have typed it: relative to the
    current directory when that is shorter, absolute when it is not. The
    defaults above are absolute so the check works from any directory, and an
    absolute path in every line of the report would bury the two hashes the
    message is actually about."""
    try:
        rel = os.path.relpath(path, Path.cwd())
    except ValueError:  # different drive on Windows
        return str(path)
    return rel if not rel.startswith("..") else str(path)


@dataclass(frozen=True)
class Project:
    """The two fields of the dtk project this check is about."""

    config: Path
    object: Path  # the executable, relative to the repository root
    sha1: str  # lowercase hex, 40 digits


@dataclass(frozen=True)
class Verdict:
    status: str  # "match", "differs" or "missing"
    path: Path  # the executable that was (or was not) hashed
    project: Project
    expected: str
    actual: str  # "" when the file is missing
    size: int  # bytes hashed; 0 when the file is missing
    disc: str  # what sys/boot.bin says this dump is; "" when unavailable

    @property
    def ok(self) -> bool:
        return self.status == "match"

    def report(self) -> str:
        """The whole message, ready to print. Both hashes appear on a
        mismatch, labelled and aligned, because the first thing anyone does
        with this failure is paste it into a search box."""
        where = f" ({self.disc})" if self.disc else ""
        dol, config = _show(self.path), _show(self.project.config)
        if self.status == "match":
            return (
                f"{dol}: sha1 {self.expected}{where}\n"
                f"  matches {config}; this is the build config/ describes."
            )
        if self.status == "missing":
            return (
                f"error: {dol} not found.\n"
                f"  {config} expects sha1 {self.expected} there.\n"
                f"  Unpack your own dump first:\n"
                f'    python tools/extract.py "path\\to\\Skies of Arcadia Legends (USA).rvz" --iso'
            )
        return (
            f"error: {dol} is not the build {config} describes.\n"
            f"  expected  {self.expected}  ({config})\n"
            f"  found     {self.actual}  ({dol}, {self.size:,} bytes{where})\n"
            "  Every address in config/ -- functions, HLE bindings, hooks, tracepoints,\n"
            "  splits, symbols -- belongs to that one build. A different region or\n"
            "  revision, or a patched executable, still translates, links and boots,\n"
            "  and is then wrong in ways nothing else here checks.\n"
            "  Re-extract from a dump of the USA disc (GEAE8P), or, if you mean to port\n"
            "  a different build, change the hash in config.yml and expect to rebuild\n"
            "  the inventory with tools/inventory.py."
        )


def read_project(config: Path) -> Project:
    """Read `object:` and `hash:` out of a decomp-toolkit config.yml."""
    try:
        text = Path(config).read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectError(f"{config}: cannot be read ({exc.strerror or exc})") from exc

    fields: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        # A whole-line comment is dropped; a `#` inside a value stays part of
        # the value, since neither a path nor a sha1 can contain one and
        # guessing at inline comments is how a parser this small goes wrong.
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            raise ProjectError(
                f"{config}:{n}: indented line {line.strip()!r}. This reader understands "
                f"only `key: value` at column 0; see tools/soa/dump.py."
            )
        m = _SCALAR.match(line)
        if not m:
            raise ProjectError(f"{config}:{n}: not `key: value`: {line!r}")
        fields[m["key"]] = m["value"].strip().strip("'\"")

    for key in ("object", "hash"):
        if key not in fields:
            raise ProjectError(f"{config}: no `{key}:` line, so there is nothing to check against")

    sha1 = fields["hash"].lower()
    if not _SHA1.match(sha1):
        raise ProjectError(
            f"{config}: `hash: {fields['hash']}` is not a 40-digit sha1. "
            f"dtk writes sha1 here; a sha256 or a truncated paste would make this check "
            f"refuse every dump, including the right one."
        )
    if not fields["object"]:
        raise ProjectError(f"{config}: `object:` is empty, so there is no file to hash")
    return Project(config=Path(config), object=Path(fields["object"]), sha1=sha1)


def sha1_file(path: Path, chunk: int = 1 << 20) -> tuple[str, int]:
    """(lowercase hex digest, bytes read). Streamed: the DOL is 3 MB today,
    but this is the one function anything else here would reuse on a disc
    image, and a 1.3 GB read into a bytes object is not a useful default."""
    # usedforsecurity=False: this is an identity check on a file the user
    # already has, and a FIPS-restricted Python otherwise refuses sha1
    # outright -- which would fail the check on a dump that is perfectly fine.
    h = hashlib.sha1(usedforsecurity=False)
    size = 0
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


def describe_disc(root: Path) -> str:
    """ "GEAE8P rev 0" from the extracted disc header, or "" if it is not
    there or not readable. A wrong dump usually announces itself here in
    terms a person recognises, where a sha1 alone says only "not that one"."""
    header = Path(root) / BOOT_BIN
    try:
        data = header.read_bytes()
    except OSError:
        return ""
    if len(data) < BOOT_HEADER_SIZE:
        return ""
    boot = parse_boot(data)
    return f"{boot.game_id} rev {boot.version}"


def verify(
    config: Path = DEFAULT_CONFIG,
    dol: Path | None = None,
    root: Path = REPO_ROOT,
) -> Verdict:
    """Hash the extracted executable and compare it with the project's hash.

    `dol` overrides the file to hash; otherwise the project's own `object:`
    path is used, resolved against `root`. The disc header is looked for
    beside it (`../boot.bin`), so an extraction somewhere other than
    `extracted/` still gets named.
    """
    project = read_project(config)
    path = Path(dol) if dol is not None else Path(root) / project.object
    disc_root = path.parent.parent
    if not path.is_file():
        return Verdict("missing", path, project, project.sha1, "", 0, describe_disc(disc_root))
    actual, size = sha1_file(path)
    status = "match" if actual == project.sha1 else "differs"
    return Verdict(status, path, project, project.sha1, actual, size, describe_disc(disc_root))
