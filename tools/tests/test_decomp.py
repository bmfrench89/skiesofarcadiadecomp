"""The native twin build takes the units marked native and renames every
function they define or declare."""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
