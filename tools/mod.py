#!/usr/bin/env python3
"""The mod kit (T10, docs/specs/mod-kit.md; the guide is docs/MODDING.md).

    python tools/mod.py new DIR [--dll]       a mod folder at DIR, ready to edit
    python tools/mod.py build DIR             mod.c -> mod.dll (mod.so off Windows)
    python tools/mod.py check DIR [--dol F]   load it against your DOL, no game started
    python tools/mod.py test DIR [CMD ...]    run it on the fake guest, no disc needed
    python tools/mod.py api [--write]         the API reference, from runtime/soa_mod.h

`check` and `test` run the port's own runtime/mod.c, linked with the fake
guest in tools/soa/modkit.py -- the one tools/tests/test_mods.py builds -- so
what they say is what the port would say at load. `check` reads the real DOL
(extracted/sys/main.dol by default) and the mod as it is; `test` swaps the
mod's dol_sha1 for the fake DOL's and plays a script of the driver's commands
(`python tools/mod.py test --help` lists them). Neither starts the game: a
mod that loads may still do the wrong thing there, which only a run shows.

SOA_MOD_OPT and SOA_MOD_ORDER pass through to both, as to the port. SOA_CC
picks the compiler as everywhere else (MSVC when unset); no developer prompt
is needed, since the toolchain finds the compiler itself.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa import modkit, toolchain  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "GEAE8P" / "config.yml"
HEADER = ROOT / "runtime" / "soa_mod.h"
API_DOC = ROOT / "docs" / "MODDING-API.md"
DEFAULT_DOL = ROOT / "extracted" / "sys" / "main.dol"
ID_RULE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")

# The driver's commands, as `test` takes them, kept in step with its
# handlers by test_mod_kit.py.
COMMAND_NAMES = (
    "set",
    "setb",
    "get",
    "frame",
    "safe",
    "pad",
    "pad2",
    "host",
    "proj",
    "tex",
    "game",
    "report",
    "describe",
)
COMMANDS = """\
  set ADDR VALUE     store a word at ADDR (hex)     setb ADDR VALUE   store a byte
  get ADDR           print the word at ADDR         frame             one frame end (patches, on_frame_end)
  safe               the top of the main loop: a safe point, and the scene and map callbacks
  pad F B            a controller read at frame F with buttons B (hex), through the pad filters
  pad2 B             pad 2 connected, buttons B     host B            the host buttons held
  proj O P0..P5      a new projection (O 1 orthographic), through the projection filters
  tex HASH W H       a W x H texture decoded, source hash HASH, through the texture providers
  game               the game's registers at a safe point (call_guest refuses without them)
  report             the end-of-run report          describe          the recording's mods= entry

  Scene, field state and map are words too: `set 803475cc 6` is the field,
  `set 80311aec 3` then `set 80311aec 8` a map load, `set 80311ac0 74 setb
  80311ac8 61` map 116a."""


def dol_sha1() -> str:
    """The DOL every mod here is made for: the hash config.yml pins."""
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        if line.startswith("hash:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit(f"{CONFIG}: no `hash:` line")


def profile() -> toolchain.Profile:
    return toolchain.profile(os.environ.get("SOA_CC"))


# ---- new -------------------------------------------------------------------

INI = """\
# {name}: made with `python tools/mod.py new` (docs/MODDING.md).
manifest = 2
id = {id}
version = 1.0
name = {name}
authors = you
# The least mod API it needs: a port that speaks a later one loads it too.
api = 1
# The DOL this was made for: config/GEAE8P/config.yml pins the same hash, and
# a mod made for another build of the game is refused, not guessed at.
dol_sha1 = {sha}
# Options a player can set (M16), as `{id}.NAME = VALUE` in soa.ini:
# option = strength int 0..100 50
"""

PATCHES = """\
# trigger      [width]  address       value   [when condition...]
#
# A patch writes at the end of a frame: every_frame, once, or on_map_load.
# This one is encounters-off's (examples/mods): the step counter at
# 0x80346D28 held at 0 in the field (scene 6), so no random battle's roll
# can win. Change it or replace it; docs/MODDING.md has the whole grammar.
every_frame    0x80346d28 = 0   when scene=6
"""

SOURCE = """\
/*
 * {name}: a native mod, made with `python tools/mod.py new --dll`
 * (docs/MODDING.md; the API is runtime/soa_mod.h, its reference
 * docs/MODDING-API.md). Build it with `python tools/mod.py build {dir}`.
 */
#include "soa_mod.h"

#include <stdio.h>

static const SoaModApi* g_api;

/* At a safe point, once a map is entered: the field running after a load. */
static void on_map_loaded(void* user, uint32_t map)
{{
    char line[96];
    (void)user;
    snprintf(line, sizeof line, "entered a%03u%c at frame %u", (unsigned)(map >> 8), (char)(map & 0xFF),
             g_api->frame());
    g_api->log(line);
}}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{{
    /* on_map_loaded and log are in every table the port has handed out;
     * check api->size before using anything appended since (SOA_MOD_HAS). */
    if (version < 1 || api->size < SOA_MOD_HAS(log)) return 1;
    g_api = api;
    api->on_map_loaded(on_map_loaded, NULL);
    api->log("{id} loaded");
    return 0;
}}
"""


def cmd_new(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    mod_id = d.name
    if not ID_RULE.match(mod_id):
        print(
            f"{mod_id}: a mod's folder is its id: lowercase letters, digits, '.', '_' and '-', "
            "a letter or digit first, under 64 characters"
        )
        return 1
    if d.exists():
        print(f"{d} is there already; nothing is overwritten")
        return 1
    d.mkdir(parents=True)
    name = mod_id.replace("-", " ").replace("_", " ").capitalize()
    (d / "mod.ini").write_text(
        INI.format(id=mod_id, name=name, sha=dol_sha1()), encoding="utf-8", newline="\n"
    )
    if args.dll:
        (d / "mod.c").write_text(
            SOURCE.format(id=mod_id, name=name, dir=d.as_posix()), encoding="utf-8", newline="\n"
        )
        print(f"made {d}: mod.ini and mod.c; next, `python tools/mod.py build {d.as_posix()}`")
    else:
        (d / "patches.txt").write_text(PATCHES, encoding="utf-8", newline="\n")
        print(
            f"made {d}: mod.ini and patches.txt; next, `python tools/mod.py check {d.as_posix()}`"
        )
    return 0


# ---- build -----------------------------------------------------------------


def machine_problem(lib: Path) -> str | None:
    """Why the port could not load `lib`, by its header, or None."""
    got = modkit.library_machine(lib.read_bytes())
    want = modkit.host_machine()
    if got is None:
        return f"{lib} is not a library (no PE or ELF header)"
    if got != want:
        return (
            f"{lib} is built for {got}, and this port runs on {want}: "
            "the system would refuse it (on Windows, a bare 'error 193')"
        )
    return None


def cmd_build(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    src = d / "mod.c"
    if not src.is_file():
        print(f"{src}: no mod.c to build")
        return 1
    p = profile()
    try:
        lib = modkit.build_library(d.resolve(), src.resolve(), p)
    except modkit.BuildError as e:
        print(f"{src}: the build failed:\n{e}")
        return 1
    problem = machine_problem(lib)
    if problem:
        print(problem)
        return 1
    print(f"built {lib} ({modkit.host_machine()}, {p.name})")
    return 0


# ---- check and test --------------------------------------------------------


def driver(p: toolchain.Profile) -> tuple[Path, Path]:
    """The fake guest, kept in build/modkit and rebuilt when a source is newer."""
    out = ROOT / "build" / "modkit" / p.name
    exe = out / ("mods" + p.exeext)
    sources = [
        ROOT / "runtime" / "mod.c",
        ROOT / "runtime" / "sha1.c",
        ROOT / "runtime" / "tick.c",
        ROOT / "runtime" / "soa_mod.h",
        ROOT / "runtime" / "mod.h",
        Path(modkit.__file__),
        *toolchain.runtime_support_sources(),
    ]
    if exe.is_file() and all(s.stat().st_mtime <= exe.stat().st_mtime for s in sources):
        return exe, out / "fake.dol"
    out.mkdir(parents=True, exist_ok=True)
    return modkit.build_driver(out, p)


def run_driver(mod: Path, dol: Path, sha: str | None, script: str) -> tuple[int, str]:
    """`mod` alone, copied into a scratch folder of mods (its dol_sha1 swapped
    for `sha` when given), loaded by the fake guest against `dol` with
    `script` on stdin. Returns whether it loaded, and what came out."""
    exe, _ = driver(profile())
    with tempfile.TemporaryDirectory(prefix="modkit-") as tmp:
        mods = Path(tmp) / "mods"
        dest = mods / mod.name
        shutil.copytree(mod, dest)
        if sha:
            ini = dest / "mod.ini"
            ini.write_text(modkit.swap_sha(ini.read_text(encoding="utf-8"), sha), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
        for key in ("SOA_MOD_OPT", "SOA_MOD_ORDER"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        proc = subprocess.run(
            [str(exe), str(mods), str(dol)],
            input=script,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
    text = (proc.stderr or "") + (proc.stdout or "")
    text = (
        text.replace(str(mods) + os.sep, "")
        .replace(str(mods) + "/", "")
        .replace(str(mods), "<mods>")
    )
    loaded = proc.returncode == 0 and re.search(r"^loaded 1$", proc.stdout or "", re.M) is not None
    return (1 if loaded else 0), text


def check_library(d: Path) -> str | None:
    lib = d / modkit.lib_name(profile())
    return machine_problem(lib) if lib.is_file() else None


def cmd_check(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    if not (d / "mod.ini").is_file():
        print(f"{d}: no mod.ini, so not a mod")
        return 1
    dol = Path(args.dol) if args.dol else DEFAULT_DOL
    if not dol.is_file():
        print(f"{dol}: no DOL to check against (tools/extract.py puts it there, or pass --dol)")
        return 1
    problem = check_library(d)
    if problem:
        print(problem)
        return 1
    loaded, text = run_driver(d, dol, None, "")
    print(text.rstrip())
    print(f"{d.as_posix()}: {'loads' if loaded else 'is refused'} against {dol.as_posix()}")
    return 0 if loaded else 1


def cmd_test(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    if not (d / "mod.ini").is_file():
        print(f"{d}: no mod.ini, so not a mod")
        return 1
    problem = check_library(d)
    if problem:
        print(problem)
        return 1
    _, dol = driver(profile())
    loaded, text = run_driver(d, dol, modkit.FAKE_SHA, " ".join(args.script))
    print(text.rstrip())
    print(f"{d.as_posix()}: {'loaded' if loaded else 'refused'} on the fake guest")
    return 0 if loaded else 1


# ---- api -------------------------------------------------------------------


def _comment(text: str) -> str:
    """A C comment's words, its stars and indents taken off."""
    body = text.strip()
    body = body[2:] if body.startswith("/*") else body
    body = body[:-2] if body.endswith("*/") else body
    lines = [re.sub(r"^\s*\* ?", "", ln).rstrip() for ln in body.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(ln.strip() if not ln.startswith("    ") else ln for ln in lines)


def api_reference(header: str) -> str:
    """docs/MODDING-API.md from soa_mod.h's text: the header's own words,
    the constants, the two structs, and each SoaModApi member in order with
    the comment that documents it."""
    out = [
        "# The mod API reference",
        "",
        "Generated by `python tools/mod.py api --write` from `runtime/soa_mod.h`; "
        "`tools/tests/test_mod_kit.py` fails when the two differ. The guide is "
        "[MODDING.md](MODDING.md).",
        "",
    ]
    intro = re.match(r"\s*/\*(.*?)\*/", header, re.S)
    if intro:
        out += ["## The header", "", _comment("/*" + intro.group(1) + "*/"), ""]
    defines = re.findall(
        r"^#define (SOA_(?:PAD|HOST)_\w+) (0x[0-9A-Fa-f]+u)[ \t]*(?:/\*(.*?)\*/)?", header, re.M
    )
    out += ["## Buttons", "", "| Name | Value | |", "|---|---|---|"]
    out += [f"| `{n}` | `{v}` | {(c or '').strip()} |" for n, v, c in defines]
    out.append("")
    for name in ("SoaPad", "SoaImage"):
        m = re.search(r"typedef struct " + name + r" \{.*?\} " + name + ";", header, re.S)
        if not m:
            continue
        out += [f"## `{name}`", "", "```c", m.group(0), "```", ""]
        before = header[: m.start()].rstrip()
        if before.endswith("*/"):  # the comment right above it documents it
            out += [_comment(before[before.rfind("/*") :]), ""]
    body = re.search(r"typedef struct SoaModApi \{(.*?)\} SoaModApi;", header, re.S)
    if not body:
        raise SystemExit("soa_mod.h: no SoaModApi")
    out += ["## `SoaModApi`, member by member", ""]
    comment, decl = "", ""
    for line in body.group(1).splitlines():
        s = line.strip()
        if not decl and (s.startswith("/*") or comment and not comment.rstrip().endswith("*/")):
            comment += line + "\n"
            continue
        if not s:
            if not decl:
                comment = comment if comment.rstrip().endswith("*/") else ""
            continue
        decl += " " + s
        if ";" not in s:
            continue
        code, _, trailing = decl.partition(";")
        code = re.sub(r"\s+", " ", code).strip() + ";"
        m = re.search(r"\(\*(\w+)\)", code) or re.search(r"(\w+)\s*;$", code)
        member = m.group(1) if m else code
        out += [f"### `{member}`", "", "```c", code, "```", ""]
        words = _comment(comment) if comment else ""
        tail = re.search(r"/\*(.*?)\*/", trailing)
        if tail:
            words = (words + "\n\n" if words else "") + tail.group(1).strip()
        if words:
            out += [words, ""]
        comment, decl = "", ""
    return "\n".join(out).rstrip() + "\n"


def cmd_api(args: argparse.Namespace) -> int:
    text = api_reference(HEADER.read_text(encoding="utf-8"))
    if args.write:
        API_DOC.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {API_DOC.relative_to(ROOT).as_posix()}")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="a mod folder at DIR, ready to edit")
    n.add_argument("dir")
    n.add_argument("--dll", action="store_true", help="a native mod: mod.c in place of patches.txt")
    n.set_defaults(fn=cmd_new)
    b = sub.add_parser("build", help="mod.c -> the mod's library, for this machine")
    b.add_argument("dir")
    b.set_defaults(fn=cmd_build)
    c = sub.add_parser("check", help="load the mod against your DOL, without the game")
    c.add_argument("dir")
    c.add_argument("--dol", help=f"the DOL (default {DEFAULT_DOL.relative_to(ROOT).as_posix()})")
    c.set_defaults(fn=cmd_check)
    t = sub.add_parser(
        "test",
        help="run the mod on the fake guest",
        description="Run a mod on the fake guest, its dol_sha1 swapped for the fake DOL's, "
        "with the commands given. The commands:\n\n" + COMMANDS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    t.add_argument("dir")
    t.add_argument(
        "script", nargs="*", help="the driver's commands, e.g. set 803475cc 6 frame get 80346d28"
    )
    t.set_defaults(fn=cmd_test)
    a = sub.add_parser("api", help="the API reference from runtime/soa_mod.h")
    a.add_argument(
        "--write", action="store_true", help=f"write {API_DOC.relative_to(ROOT).as_posix()}"
    )
    a.set_defaults(fn=cmd_api)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
