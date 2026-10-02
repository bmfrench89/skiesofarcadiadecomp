"""The render queue's rule 4 (docs/specs/portability.md 3.4): every read of
another thread's count in runtime/gxr.c goes through a plat_* helper.

On x64 a forgotten helper changes nothing -- every load there is ordered --
and on ARM64 it lets a worker read a command slot or a neighbour's rows stale,
or lets a sleeper miss its wake. No test that runs here can see that, so this
one reads the source instead: each use of a shared counter must be an
argument of a plat_* call, its declaration, or the producer's plain read of
its own g_published on a line marked "own count". Text only: no compiler.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GXR = ROOT / "runtime" / "gxr.c"

SHARED = ("g_ran", "g_published", "g_sleepers", "g_fence_sleepers", "g_frames_presented")
NAME = re.compile(r"\b(" + "|".join(SHARED) + r")\b")
OWN = "/* own count */"
DECL = re.compile(r"^\s*static\s+plat_a(?:32|64)\s+(\w+)")


def blank(src: str) -> str:
    """Comments, strings and character literals as spaces, newlines kept, so
    positions and line numbers still match the source."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        two = src[i : i + 2]
        if two == "/*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif two == "//":
            j = src.find("\n", i)
            j = n if j < 0 else j
        elif src[i] in "\"'":
            q, j = src[i], i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            j += 1
        else:
            i += 1
            continue
        for k in range(i, min(j, n)):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


def uses(src: str) -> list[tuple[int, str, str | None]]:
    """Every use of a shared counter: (line, name, the call it is directly
    inside, or None)."""
    text = blank(src)
    stack: list[str | None] = []
    prev = None
    found = []
    for m in re.finditer(r"[A-Za-z_]\w*|[()]|\S", text):
        tok = m.group()
        if tok == "(":
            stack.append(prev if prev and re.fullmatch(r"[A-Za-z_]\w*", prev) else None)
        elif tok == ")":
            if stack:
                stack.pop()
        elif NAME.fullmatch(tok):
            line = text.count("\n", 0, m.start()) + 1
            found.append((line, tok, stack[-1] if stack else None))
        prev = tok
    return found


def violations(src: str) -> list[str]:
    lines = src.splitlines()
    bad = []
    for line, name, call in uses(src):
        here = lines[line - 1]
        decl = DECL.match(here)
        if decl and decl.group(1) == name:
            continue
        if call and call.startswith("plat_"):
            continue
        if name == "g_published" and OWN in here:
            continue
        bad.append(f"gxr.c:{line}: {name} read or written outside a plat_* helper: {here.strip()}")
    return bad


def test_every_shared_counter_goes_through_a_helper():
    src = GXR.read_text(encoding="utf-8")
    assert violations(src) == []


def test_each_counter_is_reached_through_a_helper_somewhere():
    """So the test cannot pass vacuously after a rename: a counter that no
    longer appears is a counter this file no longer checks."""
    src = GXR.read_text(encoding="utf-8")
    for name in SHARED:
        calls = {
            call for line, n, call in uses(src) if n == name and call and call.startswith("plat_")
        }
        assert calls, f"{name} is never an argument of a plat_* call in gxr.c"


def worker_with(extra: str) -> str:
    """gxr.c with one line added at the top of worker()'s loop."""
    src = GXR.read_text(encoding="utf-8").replace("\r\n", "\n")
    anchor = "        const DrawCmd* D;\n        unsigned spins = 0;\n"
    assert src.count(anchor) == 1, "worker()'s loop has moved; update the anchor"
    return src.replace(anchor, anchor + extra + "\n")


def test_a_bare_read_in_the_worker_is_caught():
    """The spec's mutation: one plain read of another worker's count."""
    bad = violations(worker_with("        if (g_ran[1] > mine) spins = 1;"))
    assert len(bad) == 1 and "g_ran" in bad[0]


def test_the_marker_covers_only_the_producers_own_count():
    """The marker "own count" is true of g_published read by the producer and
    of nothing else: a worker's count is always another thread's."""
    assert violations(worker_with("        if (g_ran[1] > mine) spins = 1; /* own count */"))
    assert not violations(worker_with("        if (plat_load64(&g_ran[1]) > mine) spins = 1;"))


def test_a_cast_or_a_condition_is_not_a_helper():
    """Only the call the name sits directly inside counts: a cast's or an if's
    parentheses do not make a read safe."""
    assert violations(worker_with("        if ((long long)g_published > mine) spins = 1;"))
    assert violations(worker_with("        if (labs(g_sleepers)) spins = 1;"))
