"""Where runtime/ may say `_WIN32` (portability L9).

Everything that differs between Windows and the rest goes through
runtime/plat.h and plat.c, so a port to Linux or Android (L10, L12) finds one
place to fill in -- except at the sites listed below, each Windows-only for a
reason the list gives: the window and the console, waveOut, the fibers a
second guest thread uses, the profilers, the GPU's Win32 surface, and the two
directory helpers the renderer-only check builds without plat.c.

Every `#if`, `#ifdef`, `#ifndef` or `#elif` naming `_WIN32` in a runtime file
is found and named by the function it sits in (or the file's top level), with
comments and strings blanked first so neither can hide or fake one. A site
not on the list fails; so does a listed site that no longer exists, which
keeps the list honest. The mutation: an `#ifdef _WIN32` added to another
function of exi.c is caught.
"""

import re
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
TOP = "(top level)"

# (file, function or TOP): why it may say _WIN32. A file listed with "*" may
# anywhere.
ALLOWED = {
    ("window.c", "*"): "the Win32 window, DXGI presenter and XInput; SDL3's is L10's",
    ("plat.h", "*"): "the platform layer",
    ("plat.c", "*"): "the platform layer's cold half",
    ("audio_out.c", TOP): "the waveOut backend; SDL3's audio is L10's",
    ("threads.c", "*"): "the fibers a second guest thread runs on (Windows only)",
    ("main.c", TOP): "the sampler's includes and its stubs elsewhere",
    ("main.c", "main"): "no window off Windows until L10",
    ("gxr.c", TOP): "SOA_HOSTPROF's includes, and ensure_frames_dir's mkdir",
    ("gxr.c", "workers_start"): "SOA_HOSTPROF keeps each worker's handle",
    ("gxr.c", "ensure_frames_dir"): "mkdir, in the renderer-only build that links no plat.c",
    ("exi.c", TOP): "make_parents' mkdir header",
    ("exi.c", "make_parents"): "mkdir, as gxr.c's (the card's folders)",
    ("gxv.c", "load_loader"): "the Vulkan loader's file name on each system",
    ("gxv.c", "gxv_init"): "the Win32 surface's instance extension; SDL3's is L10's",
    ("soa_mod.h", TOP): "SOA_MOD_EXPORT, dllexport or default visibility, for a mod's soa_mod_init",
    ("settings.c", TOP): "settings_console_to_log's includes",
    ("settings.c", "settings_console_to_log"): "a Windows console's own window",
}

IF_WIN32 = re.compile(r"^\s*#\s*(?:if|ifdef|ifndef|elif)\b.*\b_WIN32\b")
HEADER = re.compile(r"\b([A-Za-z_]\w*)\s*\([^;]*$")


def blank(text: str) -> str:
    """The text with comments and string and character literals blanked,
    newlines kept, so the line numbers stay and no brace or `_WIN32` inside
    one is counted."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(c + " " * (min(j, n) - i - 1) + (c if j < n else ""))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def win32_sites(text: str) -> list[tuple[str, int]]:
    """(function or TOP, line) for every conditional naming _WIN32."""
    sites, depth, current, pending = [], 0, TOP, TOP
    for number, line in enumerate(blank(text).splitlines(), 1):
        if IF_WIN32.match(line):
            sites.append((current if depth else TOP, number))
            continue
        if line.lstrip().startswith("#"):
            continue
        if depth == 0:
            m = HEADER.search(line)
            if m:
                pending = m.group(1)
        for ch in line:
            if ch == "{":
                if depth == 0:
                    current = pending
                depth += 1
            elif ch == "}" and depth:
                depth -= 1
                if depth == 0:
                    current = pending = TOP
    return sites


def allowed(file: str, where: str) -> bool:
    return (file, "*") in ALLOWED or (file, where) in ALLOWED


def tree_sites() -> dict[tuple[str, str], list[int]]:
    found: dict[tuple[str, str], list[int]] = {}
    for path in sorted([*RUNTIME.glob("*.c"), *RUNTIME.glob("*.h")]):
        for where, line in win32_sites(path.read_text(encoding="utf-8", errors="replace")):
            found.setdefault((path.name, where), []).append(line)
    return found


def test_runtime_says_win32_only_where_it_is_allowed():
    stray = [
        f"{f}:{lines[0]} in {w}" for (f, w), lines in tree_sites().items() if not allowed(f, w)
    ]
    assert not stray, "an #ifdef _WIN32 outside plat.h's list (portability L9): " + ", ".join(stray)


def test_every_listed_site_still_exists():
    found = tree_sites()
    gone = [
        f"{f} {w}"
        for f, w in ALLOWED
        if w != "*" and (f, w) not in found and (RUNTIME / f).exists()
    ]
    assert not gone, "listed but no longer there, so the list should lose them: " + ", ".join(gone)


def test_an_ifdef_added_to_another_function_of_exi_c_is_caught():
    text = (RUNTIME / "exi.c").read_text(encoding="utf-8")
    m = re.search(r"\n(?:static )?(?:void|int|uint32_t) (\w+)\([^;{]*\)\s*\{\n", text)
    assert m and m.group(1) != "make_parents"
    at = m.end()
    mutated = text[:at] + "#ifdef _WIN32\n    (void)0;\n#endif\n" + text[at:]
    wheres = {w for w, _ in win32_sites(mutated)}
    assert m.group(1) in wheres and not allowed("exi.c", m.group(1))


def test_comments_and_strings_neither_hide_nor_fake_a_site():
    text = 'int f(void)\n{\n    const char* s = "{";\n    /* } */\n#ifdef _WIN32\n    return 1;\n#endif\n}\n'
    assert win32_sites(text) == [("f", 5)]
    assert win32_sites("/*\n#ifdef _WIN32\n*/\nint g;\n") == []
