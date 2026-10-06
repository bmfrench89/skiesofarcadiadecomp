"""The import's Java and C agree (specs/android.md L12d), read from the source.

runtime/android.c finds SoaActivity's import methods and its `destroyed`
field by name and JNI signature, from SDL's thread; SDL finds the
messageboxShowMessageBox override the same way; app/proguard-rules.pro keeps
every one of them for the day a release is shrunk. Nothing in Java calls
them, CI never builds the Java, and a rename or a changed parameter in any of
the three places compiles everywhere and builds an APK whose every launch ends
at android.c's java_init, before a single box. So, from the three files:

- every member android.c looks up is declared in SoaActivity.java with that
  name and that signature;
- the override has the exact signature SDL calls (SDL_android.c), so SDL
  reaches it rather than its own box;
- proguard-rules.pro keeps exactly those members, with those signatures.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID_C = ROOT / "runtime" / "android.c"
ACTIVITY = ROOT / "android/app/src/main/java/io/github/bmfrench89/soa/SoaActivity.java"
RULES = ROOT / "android/app/proguard-rules.pro"
CLASS = "io.github.bmfrench89.soa.SoaActivity"
# What SDL_android.c's Android_JNI_ShowMessageBox asks for, by name, on the activity.
SDL_BOX = (
    "messageboxShowMessageBox",
    "(ILjava/lang/String;Ljava/lang/String;[I[I[Ljava/lang/String;[I)I",
)
PRIMITIVE = {
    "int": "I",
    "boolean": "Z",
    "void": "V",
    "long": "J",
    "byte": "B",
    "char": "C",
    "short": "S",
    "float": "F",
    "double": "D",
}


def descriptor(java_type: str) -> str:
    """A Java type as source or a keep rule spells it, as JNI writes it."""
    t = java_type.strip()
    dims = t.count("[]")
    base = t.replace("[]", "").strip()
    if base in PRIMITIVE:
        one = PRIMITIVE[base]
    else:
        if "." not in base:  # only java.lang's names go unqualified in SoaActivity.java
            base = f"java.lang.{base}"
        one = f"L{base.replace('.', '/')};"
    return "[" * dims + one


def signature(ret: str, params: str) -> str:
    """(params)ret, from a declaration's text: each parameter its type, less
    `final` and its name (a keep rule's has no name)."""
    types = []
    for p in params.split(","):
        words = [w for w in p.replace("final ", " ").split() if w]
        if not words:
            continue
        types.append(words[0] if len(words) == 1 else " ".join(words[:-1]))
    return "(" + "".join(descriptor(t) for t in types) + ")" + descriptor(ret)


def looked_up() -> dict[str, str]:
    """What android.c's java_init finds: method(cls, name, sig) and the field."""
    text = ANDROID_C.read_text(encoding="utf-8")
    found = dict(re.findall(r'\bmethod\(cls, "(\w+)", "([^"]+)"\)', text))
    found.update(re.findall(r'GetFieldID\(g_env, cls, "(\w+)", "([^"]+)"\)', text))
    return found


def declared() -> dict[str, list[str]]:
    """Every method and field SoaActivity.java declares: name to signatures."""
    text = ACTIVITY.read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    for ret, name, params in re.findall(
        r"^\s*(?:@Override\s+)?(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?"
        r"(?:synchronized\s+)?([\w.]+(?:\[\])*)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws [\w., ]+)?\{",
        text,
        re.M,
    ):
        if ret not in ("new", "return", "else"):
            out.setdefault(name, []).append(signature(ret, params))
    for ftype, name in re.findall(
        r"^\s*(?:public|protected|private)?\s*(?:static\s+)?(?:volatile\s+)?(?:final\s+)?"
        r"([\w.]+(?:\[\])*)\s+(\w+)\s*(?:=[^;]*)?;",
        text,
        re.M,
    ):
        if ftype not in ("return", "throw"):
            out.setdefault(name, []).append(descriptor(ftype))
    return out


def kept() -> dict[str, str]:
    """The members proguard-rules.pro keeps in SoaActivity: name to signature."""
    text = RULES.read_text(encoding="utf-8")
    block = re.search(r"-keep class " + re.escape(CLASS) + r"\s*\{(.*?)\}", text, re.S)
    assert block, f"{RULES.name} keeps nothing of {CLASS}"
    out = {}
    for line in block.group(1).splitlines():
        line = line.split("#", 1)[0].strip().rstrip(";").strip()
        if not line:
            continue
        line = re.sub(r"^(public|protected|private)\s+", "", line)
        m = re.fullmatch(r"([\w.]+(?:\[\])*)\s+(\w+)\s*\(([^)]*)\)", line)
        if m:
            out[m.group(2)] = signature(m.group(1), m.group(3))
            continue
        m = re.fullmatch(r"(?:volatile\s+)?([\w.]+(?:\[\])*)\s+(\w+)", line)
        assert m, f"{RULES.name}: cannot read {line!r}"
        out[m.group(2)] = descriptor(m.group(1))
    return out


def test_descriptors():
    """The reading itself, on the shapes the three files use."""
    assert signature("String", "final int kind, boolean picker") == "(IZ)Ljava/lang/String;"
    assert signature("int", "java.lang.String[]") == "([Ljava/lang/String;)I"
    assert signature("void", "") == "()V"
    assert descriptor("boolean") == "Z"


def test_android_c_finds_what_java_declares():
    want = looked_up()
    assert len(want) >= 8, f"android.c's lookups not found where they were: {want}"
    have = declared()
    wrong = {n: s for n, s in want.items() if s not in have.get(n, [])}
    assert not wrong, (
        "android.c looks these up, and SoaActivity.java declares them otherwise: "
        + ", ".join(f"{n}{s} (Java: {have.get(n) or 'none'})" for n, s in wrong.items())
    )


def test_the_box_override_is_the_one_sdl_calls():
    name, sig = SDL_BOX
    assert sig in declared().get(name, []), (
        f"SoaActivity.{name} is not {sig}: SDL would draw its own box"
    )


def test_proguard_keeps_exactly_those():
    want = dict(looked_up())
    want[SDL_BOX[0]] = SDL_BOX[1]
    assert kept() == want
