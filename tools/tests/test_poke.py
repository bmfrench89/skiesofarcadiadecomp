"""SOA_POKE: writing guest memory while the game runs (PLAN D2).

Nothing in ``runtime/`` could write guest memory during a run, so every question
of the form "what does the game do if this variable says that" cost a
recompile to ask. ``SOA_POKE=frame:addr=value`` answers it instead.

Two properties are worth a test and neither is about the store itself, which
is one line of ``mem_w32``. The first is that a malformed switch is refused
out loud: a run driven by a mistyped poke is indistinguishable from a run whose
poke did nothing, and this project has already lost days to switches that
failed silently -- ``set SOA_RENDER=1`` in PowerShell, ``Native`` in
``units.txt``, a binding list without its ``0x``. The second is that the
parsing happens at startup rather than at the frame that needs it, which is
what makes the first property useful while the person who typed it is still
watching.

The boot path is built the way ``test_memguard.py`` builds it, and its stubs
and helpers are imported from there rather than copied, so the two cannot
drift. It needs a compiler and no disc.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_memguard import build, needs_msvc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def run(exe, tmp_path, poke):
    """One boot with no disc: main() parses SOA_POKE, then finds no
    sys/main.dol and gives up, which is as far as this needs to get."""
    env = dict(os.environ)
    for name in ("SOA_POKE", "SOA_MEMPOKE"):
        env.pop(name, None)
    if poke is not None:
        env["SOA_POKE"] = poke
    proc = subprocess.run(
        [str(exe), str(tmp_path / "no-disc-here")],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    return proc.stdout + proc.stderr


@needs_msvc
def test_well_formed_pokes_are_armed_and_counted(tmp_path):
    """Both radices, in one switch: a decimal frame with a 0x address and a 0x
    value, and a wholly decimal item."""
    out = run(
        build(tmp_path),
        tmp_path,
        "16000:0x80311AC4=200,100:2148535492=0x62000000,0:0x80311AEC=0,1:0xFFFFFFFF=0xFFFFFFFF",
    )
    assert "[poke] 4 poke(s) armed" in out, out
    assert "stopped at" not in out, out


@needs_msvc
@pytest.mark.parametrize(
    "bad,why",
    [
        ("16000", "no colon, so no address at all"),
        ("16000:0x80311AC4", "an address with no value"),
        ("16000:0x80311AC4:200", "a colon where the equals sign goes"),
        ("frame:0x80311AC4=200", "a frame that is not a number"),
        ("16000:=200", "an equals sign with no address"),
        # The first six of these used to arm, and store something other than
        # what was typed; the seventh was already refused and stays as a guard.
        ("16000:0x80311AC4=0x100000000", "a value past 32 bits, saturated to FFFFFFFF"),
        ("99999999999:0x80311AC4=1", "a frame past 32 bits, which then never fired"),
        ("16000:0x180311AC4=1", "an address past 32 bits"),
        ("16000:0x80311AC4=-1", "a sign, read as FFFFFFFF"),
        ("16000:0x80311AC4=0101", "a leading zero, read as octal 65"),
        ("16000: 0x80311AC4=1", "a space, which strtoul skips"),
        ("16000:0x80311AC4=5x", "trailing junk after the value"),
    ],
    ids=[
        "no-colon",
        "no-value",
        "colon-for-equals",
        "frame-not-a-number",
        "no-address",
        "value-over-32-bits",
        "frame-over-32-bits",
        "address-over-32-bits",
        "negative",
        "octal",
        "space",
        "junk-after-value",
    ],
)
def test_a_malformed_item_is_refused_out_loud(tmp_path, bad, why):
    """Each of these used to be the shape of a switch that drove nothing and
    said nothing. The run has to name where it stopped."""
    out = run(build(tmp_path), tmp_path, bad)
    assert "[poke] SOA_POKE: stopped at" in out, f"{why}: {out}"


@needs_msvc
def test_a_good_item_before_a_bad_one_is_kept_and_the_rest_reported(tmp_path):
    """Partial parsing is the honest outcome: what was understood is armed,
    and the tail that was not is quoted back."""
    out = run(build(tmp_path), tmp_path, "16000:0x80311AC4=200,nonsense")
    assert "stopped at nonsense" in out, out
    assert "1 parsed" in out, out


@needs_msvc
def test_no_switch_says_nothing(tmp_path):
    """A facility that announces itself in every log is one people stop
    reading, which is the argument the renderer's tripwire header makes."""
    assert "[poke]" not in run(build(tmp_path), tmp_path, None)
    assert "[poke]" not in run(build(tmp_path), tmp_path, "")


def test_the_switch_is_documented_where_the_port_says_it_is():
    """``gen/soa.exe --help`` lists nine switches and points at the README for
    the rest, so an undocumented switch is an unfindable one."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`SOA_POKE=" in readme, "SOA_POKE is not in the README's switch table"
    # The addresses the switch exists to reach, so the next person does not
    # have to re-derive them from three MEM1 images.
    for addr in ("0x80311AC4", "0x80311AC8", "0x80311AEC"):
        assert addr in readme, f"{addr} is not named in the README"
