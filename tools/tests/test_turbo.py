"""The check for a turbo run (PLAN-GAMEPLAY-MODS M11a).

`python tools/tests/test_turbo.py <log>` reads a battle run made with
`SOA_TURBO=battle` and `SOA_PEEK` of the game's frame counter (0x803475C0)
and scene word (0x803475CC) every frame, and holds it to a same-run
contrast: over the battle's scene-7 frames the game's counter advances one
per retrace (twice the normal rate), over the field's scene-6 frames before
the battle one per two retraces, within 5%; the battle ends inside the run
(a scene-6 frame after the last 7); and the audio reached the device at
128,000 bytes a second of wall time within 3%, since turbo must not speed
the music. It exits 1 and names each problem. The pytest below feeds it a
synthetic log with each rule broken.
"""

import re
import sys
from pathlib import Path

COUNTER = 0x803475C0
SCENE = 0x803475CC
RE_PEEK = re.compile(
    r"^\[peek\] frame (\d+): ([0-9A-Fa-f]{8}) = ([0-9A-Fa-f]{8}) \(retrace (\d+)\)"
)
RE_AUDIO = re.compile(r"^\[audio\] \d+ bytes over [\d.]+ s of wall time .*: (\d+) bytes a second")


def rate(frames: list[int], counter: dict[int, int], retrace: dict[int, int]) -> float | None:
    """Counter steps per retrace from the first to the last of `frames`."""
    if len(frames) < 2:
        return None
    a, b = frames[0], frames[-1]
    d = retrace[b] - retrace[a]
    return (counter[b] - counter[a]) / d if d > 0 else None


def check_log(log: str, audio_tolerance: float = 0.03) -> list[str]:
    counter, scene, retrace = {}, {}, {}
    for ln in log.splitlines():
        m = RE_PEEK.match(ln)
        if not m:
            continue
        f, a, v, r = int(m.group(1)), int(m.group(2), 16), int(m.group(3), 16), int(m.group(4))
        retrace[f] = r
        if a == COUNTER:
            counter[f] = v
        elif a == SCENE:
            scene[f] = v
    frames = sorted(f for f in scene if f in counter)
    problems = []
    battle = [f for f in frames if scene[f] == 7]
    if not battle:
        return ["no scene-7 frame: the run never reached the battle"]
    first7, last7 = battle[0], battle[-1]
    run7 = [first7]  # the first unbroken stretch of battle frames
    for f in battle[1:]:
        if f != run7[-1] + 1:
            break
        run7.append(f)
    field = [f for f in frames if f < first7 and scene[f] == 6]
    fast = rate(run7, counter, retrace)
    slow = rate(field, counter, retrace)
    if fast is None or abs(fast - 1.0) > 0.05:
        problems.append(f"in battle the counter advanced {fast} a retrace, not 1 within 5%")
    if slow is None or abs(slow - 0.5) > 0.025:
        problems.append(
            f"in the field before it the counter advanced {slow} a retrace, not 0.5 within 5%"
        )
    if not any(scene[f] == 6 for f in frames if f > last7):
        problems.append(
            "no scene-6 frame after the last scene-7 frame: the battle did not end inside the run"
        )
    audio = [int(m.group(1)) for ln in log.splitlines() if (m := RE_AUDIO.match(ln))]
    if not audio:
        problems.append("no [audio] rate line")
    elif abs(audio[-1] - 128000) > 128000 * audio_tolerance:
        problems.append(
            f"audio reached the device at {audio[-1]} bytes a second, not 128000 within 3%"
        )
    return problems


def synthetic(
    battle_rate: float = 1.0, field_rate: float = 0.5, ends: bool = True, audio: int = 128400
) -> str:
    """A run: field frames 100-199, battle 200-399, field again 400-450."""
    lines, count, r = [], 1000.0, 5000
    for f in range(100, 451):
        s = 7 if 200 <= f < 400 else 6
        if not ends and f >= 400:
            s = 7
        lines.append(f"[peek] frame {f}: 803475C0 = {int(count):08X} (retrace {r})")
        lines.append(f"[peek] frame {f}: 803475CC = {s:08X} (retrace {r})")
        # one frame is one retrace at turbo, two at normal speed
        step = 1 if s == 7 else 2
        count += (battle_rate if s == 7 else field_rate) * step
        r += step
    lines.append(
        f"[audio] 5000000 bytes over 39.1 s of wall time between the first block and the last: {audio} bytes a second"
    )
    return "\n".join(lines)


def test_a_good_run_passes():
    assert check_log(synthetic()) == []


def test_each_rule_broken_fails_its_line():
    assert "in battle" in check_log(synthetic(battle_rate=0.5))[0]
    assert "in the field" in check_log(synthetic(field_rate=1.0))[0]
    assert "did not end" in check_log(synthetic(ends=False))[0]
    assert "256000 bytes a second" in check_log(synthetic(audio=256000))[0]
    assert check_log("")[0].startswith("no scene-7 frame")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python tools/tests/test_turbo.py <log>")
    found = check_log(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
    for p in found:
        print(f"[turbo-check] {p}")
    print(f"[turbo-check] {'FAIL' if found else 'ok'}")
    sys.exit(1 if found else 0)
