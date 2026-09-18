"""The native twin build takes the units marked native and renames every
function they define or declare.

The scanner is a regex over C, so the interesting cases are the declarations
that look like a function and are not one. A function-pointer typedef ends in
a parameter list of its own, and the identifier before it is the return type:
``typedef void (*ARCallback)(void);`` read as a function gives one called
"void", and the rename that follows is ``/Dvoid=dc_void`` over every unit in
the build. src/sdk/ar/ar.c and arq.c have had that typedef all along and were
harmless only because neither is marked native.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location(
    "recompile", Path(__file__).resolve().parents[1] / "recompile.py"
)
recompile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recompile)


def test_native_units_and_their_renames(tmp_path):
    (tmp_path / "a.c").write_text(
        '#include "types.h"\n'
        "size_t strlen(const char* str)\n{\n    return 0;\n}\n\n"
        "char* strchr(const char* str, int chr)\n{\n    return 0;\n}\n\n"
        "static int helper(void)\n{\n    return 1;\n}\n"
        "int forward_decl(int x);\n",
        encoding="utf-8",
    )
    (tmp_path / "b.c").write_text("int game_only(void)\n{\n    return 2;\n}\n", encoding="utf-8")
    units = tmp_path / "units.txt"
    units.write_text(
        f"# comment\n{tmp_path / 'a.c'}\t1.3.2\t-O4,p\tnative\n{tmp_path / 'b.c'}\t1.3.2\t-O4,p\n",
        encoding="utf-8",
    )
    files, defines = recompile.native_decomp_sources(units)
    assert files == [str(tmp_path / "a.c")]
    assert defines == [
        "/Dforward_decl=dc_forward_decl",
        "/Dhelper=dc_helper",
        "/Dstrchr=dc_strchr",
        "/Dstrlen=dc_strlen",
    ]


def test_missing_units_file_is_empty(tmp_path):
    assert recompile.native_decomp_sources(tmp_path / "nope.txt") == ([], [])


def native_unit(tmp_path, body: str) -> Path:
    (tmp_path / "a.c").write_text(body, encoding="utf-8")
    units = tmp_path / "units.txt"
    units.write_text(f"{tmp_path / 'a.c'}\t1.3.2\t-O4,p\tnative\n", encoding="utf-8")
    return units


def test_a_function_pointer_typedef_is_not_a_function(tmp_path):
    units = native_unit(
        tmp_path,
        "typedef void (*ARCallback)(void);\n"
        "typedef void (*__OSInterruptHandler)(int irq, OSContext* context);\n"
        "typedef int (*Comparator)(const void*, const void*);\n\n"
        "void ARRegisterDMACallback(ARCallback cb)\n{\n}\n",
    )
    assert recompile.native_decomp_sources(units)[1] == [
        "/DARRegisterDMACallback=dc_ARRegisterDMACallback"
    ]


def test_a_rename_of_a_keyword_is_refused(tmp_path):
    """The typedef is handled, but the scanner is still a regex: anything else
    shaped that way has to stop the build rather than reach the compiler."""
    units = native_unit(
        tmp_path, "static void (*handler)(void);\n\nint f(void)\n{\n    return 0;\n}\n"
    )
    with pytest.raises(recompile.RenameError) as exc:
        recompile.native_decomp_sources(units)
    assert "void" in str(exc.value)
    assert "a.c" in str(exc.value)


def test_no_unit_in_the_tree_scans_to_a_keyword():
    """Every src/ unit, not only the ones marked native today: the failure
    arrives the day one of them is promoted, which is the worst time for it."""
    for src in sorted(ROOT.joinpath("src").rglob("*.c")):
        found = set(recompile._FUNC_DEF.findall(src.read_text(encoding="utf-8")))
        assert not (found & recompile._C_KEYWORDS), f"{src}: scanned to a keyword"


def test_the_typedefs_that_started_this_are_still_there():
    """Guard against the test above passing because ar.c stopped having one."""
    text = ROOT.joinpath("src/sdk/ar/ar.c").read_text(encoding="utf-8")
    assert "typedef void (*ARCallback)(void);" in text
