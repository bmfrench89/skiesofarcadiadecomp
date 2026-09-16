"""The native twin build finds every function a decompiled unit defines."""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

spec = importlib.util.spec_from_file_location("recompile", Path(__file__).resolve().parents[1] / "recompile.py")
recompile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recompile)


def test_function_definitions_are_found(tmp_path):
    (tmp_path / "a.c").write_text(
        "#include \"types.h\"\n"
        "size_t strlen(const char* str)\n{\n    return 0;\n}\n\n"
        "char* strchr(const char* str, int chr)\n{\n    return 0;\n}\n\n"
        "static int helper(void)\n{\n    return 1;\n}\n"
        "int forward_decl(int x);\n",
        encoding="utf-8",
    )
    files, defines = recompile.native_decomp_sources(tmp_path)
    assert files == [str(tmp_path / "a.c")]
    assert defines == ["/Dhelper=dc_helper", "/Dstrchr=dc_strchr", "/Dstrlen=dc_strlen"]


def test_missing_source_dir_is_empty(tmp_path):
    assert recompile.native_decomp_sources(tmp_path / "nope") == ([], [])
