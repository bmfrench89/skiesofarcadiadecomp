"""runtime/disc.c's two constants are config/'s (disc-layer I1).

disc.c refuses an image whose executable does not hash to DISC_DOL_SHA1, and
one whose game id is not DISC_GAME_ID. Both are copies of what config/GEAE8P
says: the hash in config.yml, which tools/extract.py and player_build.py check
the same executable against, and the directory's own name. A copy that drifts
would refuse every player's disc, or accept the wrong one; this holds them
equal, and a copy with one hex digit changed is refused by the same checker.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa.dump import read_project  # noqa: E402

DISC_C = ROOT / "runtime" / "disc.c"
CONFIG = ROOT / "config" / "GEAE8P" / "config.yml"


def problems(text: str, config: Path = CONFIG) -> list[str]:
    """What disc.c's text says that config/ does not."""
    out = []
    sha = re.search(r'#define DISC_DOL_SHA1 "([0-9a-fA-F]*)"', text)
    gid = re.search(r'#define DISC_GAME_ID "([^"]*)"', text)
    want_sha = read_project(config).sha1.lower()
    want_id = config.parent.name
    if not sha:
        out.append("no DISC_DOL_SHA1")
    elif sha.group(1).lower() != want_sha:
        out.append(f"DISC_DOL_SHA1 is {sha.group(1)}, and config.yml's hash is {want_sha}")
    if not gid:
        out.append("no DISC_GAME_ID")
    elif gid.group(1) != want_id:
        out.append(f"DISC_GAME_ID is {gid.group(1)}, and the config directory is {want_id}")
    return out


def test_disc_cs_constants_are_configs():
    assert problems(DISC_C.read_text(encoding="utf-8")) == []


def test_one_hex_digit_changed_is_refused():
    text = DISC_C.read_text(encoding="utf-8")
    m = re.search(r'#define DISC_DOL_SHA1 "([0-9a-f]{40})"', text)
    assert m, "disc.c names the executable's hash in 40 lowercase hex digits"
    digit = m.group(1)[17]
    changed = text.replace(
        m.group(1), m.group(1)[:17] + ("0" if digit != "0" else "1") + m.group(1)[18:]
    )
    assert len(problems(changed)) == 1 and "DISC_DOL_SHA1" in problems(changed)[0]


def test_another_game_id_is_refused():
    text = DISC_C.read_text(encoding="utf-8").replace(
        '#define DISC_GAME_ID "GEAE8P"', '#define DISC_GAME_ID "GEAP8P"'
    )
    assert any("DISC_GAME_ID is GEAP8P" in p for p in problems(text))


def test_the_constants_are_behind_ifndef_for_the_fixture_build():
    # tools/citest/disc_check.py defines both before including disc.c
    text = DISC_C.read_text(encoding="utf-8")
    for name in ("DISC_GAME_ID", "DISC_DOL_SHA1"):
        assert f"#ifndef {name}\n#define {name} " in text.replace("\r\n", "\n"), name
