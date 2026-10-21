"""tools/mod.py, the mod kit (T10, docs/specs/mod-kit.md).

`check` and `test` run the port's own runtime/mod.c on the fake guest in
tools/soa/modkit.py; `build` compiles a mod's library and refuses one built
for another machine; `api` writes docs/MODDING-API.md from soa_mod.h, which a
test here holds current. `check` reads the real DOL and skips without it.
"""

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import mod as kit  # noqa: E402
from soa import modkit, toolchain  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))
needs_cc = pytest.mark.skipif(
    toolchain.compiler_path(PROFILE) is None, reason=f"no {PROFILE.name} to build the fake guest"
)
needs_dol = pytest.mark.skipif(not kit.DEFAULT_DOL.is_file(), reason="no extracted DOL here")


def run(capsys, *argv: str) -> tuple[int, str]:
    rc = kit.main(list(argv))
    return rc, capsys.readouterr().out


# ---- the API reference -------------------------------------------------------


def test_the_api_reference_is_current():
    """docs/MODDING-API.md is what `mod.py api` makes of soa_mod.h now: a
    member appended without `api --write` fails here."""
    want = kit.api_reference(kit.HEADER.read_text(encoding="utf-8"))
    have = kit.API_DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert have == want, "run `python tools/mod.py api --write`"


def test_the_api_reference_has_every_member_with_its_words():
    header = kit.HEADER.read_text(encoding="utf-8")
    body = header[header.index("typedef struct SoaModApi {") :]
    members = re.findall(r"^    [\w ]+\**\s*\(\*(\w+)\)", body[: body.index("} SoaModApi;")], re.M)
    doc = kit.api_reference(header)
    assert len(members) > 25 and all(f"### `{m}`" in doc for m in members), members
    # a comment above a member and one after it on its line are both kept
    assert "Appended (M16)." in doc and "0x803475CC: 6 is the field, 7 battle" in doc
    grown = header.replace("} SoaModApi;", "    int (*later)(void); /* a new one */\n} SoaModApi;")
    assert "### `later`" in kit.api_reference(grown)


# ---- a library's machine -----------------------------------------------------


def pe(machine: int) -> bytes:
    head = bytearray(0x200)
    head[0:2] = b"MZ"
    head[0x3C:0x40] = (0x80).to_bytes(4, "little")
    head[0x80:0x84] = b"PE\0\0"
    head[0x84:0x86] = machine.to_bytes(2, "little")
    return bytes(head)


def elf(machine: int) -> bytes:
    head = bytearray(0x40)
    head[0:4] = b"\x7fELF"
    head[5] = 1  # little-endian
    head[0x12:0x14] = machine.to_bytes(2, "little")
    return bytes(head)


def test_a_library_s_machine_is_read_from_its_header():
    assert modkit.library_machine(pe(0x8664)) == "x86-64"
    assert modkit.library_machine(pe(0x014C)) == "x86 (32-bit)"
    assert modkit.library_machine(pe(0xAA64)) == "arm64"
    assert modkit.library_machine(elf(0x3E)) == "x86-64"
    assert modkit.library_machine(elf(0xB7)) == "arm64"
    assert modkit.library_machine(b"not a library") is None


def test_a_library_for_another_machine_is_refused_by_name(tmp_path, monkeypatch):
    """A 32-bit mod.dll is the case that fails inside the port as a bare
    'error 193'; the kit names it instead. The mutation, the machine test
    removed, passes it."""
    monkeypatch.setattr(modkit, "host_machine", lambda: "x86-64")
    lib = tmp_path / "mod.dll"
    lib.write_bytes(pe(0x014C))
    problem = kit.machine_problem(lib)
    assert problem and "built for x86 (32-bit), and this port runs on x86-64" in problem
    lib.write_bytes(pe(0x8664))
    assert kit.machine_problem(lib) is None


def test_swap_sha_changes_the_dol_line_only():
    ini = "name = x\n# dol_sha1 = keep this comment\ndol_sha1 = abc  \napi = 1\n"
    assert (
        modkit.swap_sha(ini, "f00")
        == "name = x\n# dol_sha1 = keep this comment\ndol_sha1 = f00\napi = 1\n"
    )


# ---- new -------------------------------------------------------------------


def test_new_makes_a_mod_and_never_overwrites(tmp_path, capsys):
    rc, out = run(capsys, "new", str(tmp_path / "my-mod"))
    assert rc == 0, out
    ini = (tmp_path / "my-mod" / "mod.ini").read_text(encoding="utf-8")
    assert "id = my-mod" in ini and f"dol_sha1 = {kit.dol_sha1()}" in ini and "manifest = 2" in ini
    assert "every_frame    0x80346d28 = 0   when scene=6" in (
        tmp_path / "my-mod" / "patches.txt"
    ).read_text(encoding="utf-8")
    rc, out = run(capsys, "new", str(tmp_path / "my-mod"))
    assert rc == 1 and "nothing is overwritten" in out
    rc, out = run(capsys, "new", str(tmp_path / "My Mod"))
    assert rc == 1 and "a mod's folder is its id" in out


def test_the_commands_test_lists_are_the_driver_s():
    """`test --help` lists the driver's commands: each is one the driver
    takes, and the help names each."""
    for name in kit.COMMAND_NAMES:
        assert f'!strcmp(cmd, "{name}")' in modkit.DRIVER, name
        assert re.search(rf"(^|\s){name} ", kit.COMMANDS, re.M), name


# ---- test, on the fake guest -----------------------------------------------


@needs_cc
def test_new_then_test_loads_and_does_what_it_says(tmp_path, capsys):
    """A new patch mod on the fake guest, its dol_sha1 swapped: the step
    counter held at 0 in the field. The mutation, the sha not swapped,
    refuses every real mod here."""
    run(capsys, "new", str(tmp_path / "hello"))
    rc, out = run(capsys, "test", str(tmp_path / "hello"), "set", "803475cc", "6", "set", "80346d28", "63",
                  "frame", "get", "80346d28")  # fmt: skip
    assert rc == 0, out
    assert "80346D28=00000000" in out and "hello: loaded on the fake guest" in out, out
    assert (
        "[mod] hello writes, patches.txt:7: every_frame u32 80346D28 = 00000000 when scene=6" in out
    )


@needs_cc
def test_new_dll_builds_and_its_callback_runs(tmp_path, capsys):
    run(capsys, "new", str(tmp_path / "native"), "--dll")
    rc, out = run(capsys, "build", str(tmp_path / "native"))
    assert rc == 0, out
    script = (
        "set 803475cc 6 set 80311aec 3 safe set 80311aec 8 set 80311ac0 74 setb 80311ac8 61 safe"
    )
    rc, out = run(capsys, "test", str(tmp_path / "native"), *script.split())
    assert rc == 0, out
    assert "[mod] native: entered a116a" in out and "[mod] native registers: map load" in out, out


# ---- check, against the real DOL -------------------------------------------


@needs_cc
@needs_dol
def test_check_loads_the_examples_against_the_dol(capsys):
    for name in ("encounters-off", "encounter-scale"):
        rc, out = run(capsys, "check", str(ROOT / "examples" / "mods" / name))
        assert rc == 0 and f"{name}: loads against" in out.replace("\\", "/"), out


@needs_cc
@needs_dol
@pytest.mark.parametrize(
    "edit, why",
    [
        (("mod.ini", "dol_sha1 = 8c0e", "dol_sha1 = 9c0e"), "made for the DOL with SHA-1 9c0e"),
        (("patches.txt", "0x80346d28", "0x8034d28"), "`0x8034d28` is not an address"),
    ],
)
def test_check_fails_a_wrong_dol_and_a_misspelled_address(tmp_path, capsys, edit, why):
    """Done line 1. The mutation, `check` returning 0 whatever the driver
    printed, fails the exit code."""
    run(capsys, "new", str(tmp_path / "hello"))
    name, old, new = edit
    f = tmp_path / "hello" / name
    text = f.read_text(encoding="utf-8")
    assert old in text
    f.write_text(text.replace(old, new), encoding="utf-8")
    rc, out = run(capsys, "check", str(tmp_path / "hello"))
    assert rc == 1 and why in out and "hello: is refused against" in out, out


@needs_cc
def test_the_guide_s_examples_load(tmp_path, capsys):
    """docs/MODDING.md's patches.txt block and its option lines are ones the
    port takes: a guide whose example is refused teaches the wrong grammar."""
    guide = (ROOT / "docs" / "MODDING.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```\n(.*?)```", guide, re.S)
    patches = next(b for b in blocks if "every_frame" in b and "on_map_load" in b)
    options = next(b for b in blocks if b.startswith("option ="))
    run(capsys, "new", str(tmp_path / "guide"))
    ini = tmp_path / "guide" / "mod.ini"
    ini.write_text(ini.read_text(encoding="utf-8") + options, encoding="utf-8")
    (tmp_path / "guide" / "patches.txt").write_text(patches, encoding="utf-8")
    rc, out = run(capsys, "test", str(tmp_path / "guide"))
    assert rc == 0 and "1 mod(s) loaded, 3 patch(es)" in out, out
