"""The AX census lines a run prints, and the invariants that hold between them.

The census (PLAN E1) is the only account of what the audio driver actually
sends, so a report whose numbers contradict each other is worth catching:
OUTPUT and END are once per mixed frame, a voice-frame belongs to exactly one
source, and a start is counted once wherever it is attributed. The parser here
is the checker; it runs over the fixture below and over any scenario log that
happens to be in build/, so a real run is checked when one exists.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FIXTURE = """\
[aram] 2105 DMAs, 19874208 bytes
[aram] census sources: 5552 disc files indexed; 882 transfers named at the transfer, 775 not, \
in 27 ARAM upload runs of which 22 are named
[aram] census largest named uploads: tone.samp 004500-263820 | s1000000.samp 263820-4B3D60
[ax] 17915 frames mixed, 21260 voice-frames, 2866400 samples output
[ax] census opcodes sent 00:17915 02:10672 03:10672 04:17915 05:17915 06:17915 09:17915 \
0E:17915 0F:17915 11:17915; never sent 01 07 08 0A 0B 0C 0D 10 12 13; 0 lists abandoned \
(first bad op 0), 0 hit the 64-command cap; longest list 10 commands, longest voice chain 5
[ax] census PB values over 21260 voice-frames: src_type 0:21260 | coef_select 1:21260 | \
is_stream 1:21192 0:68 | mixer_ctrl 0:21096 8:96 1:2 9:66 | format 0:21260 | adpcm_gain 0:21260
[ax] census PB set: itd on 0 (shifts 0), dpop 0, unk3 0, this!=own 0, one-shot 68, \
no update list 0; mixer_ctrl bits seen 0009 (aux send 68, bit 0x10 0); \
cmd 01 dropped sends max 0/0 in 0
[ax] census aux: A reached by a voice in 68 frames (peak 1175), B in 0 (peak 0); \
back from the CPU: auxA 501 auxB 0 nowrite 28645 set-LR 0
[ax] census starts: 6 (+0 re-points); RUNNING through the update list by ms on 0/0/0/0/0 \
off 0/0/0/0/0; update writes by PB word  10:20 12:20
[ax] census starts by source (3 distinct runs, 0 unslotted): m01_l.dsp 2 starts 10596 frames \
7FDD80-800EC0 | m01_r.dsp 2 starts 10596 frames 7F7B00-7FAC40 | s1000000.samp 2 starts \
68 frames 263820-4B3D60
"""


class Census:
    """Every number the census prints, pulled out of a run's stderr."""

    def __init__(self, text):
        self.opcodes, self.never, self.fields, self.sources = {}, [], {}, []
        self.frames = self.voice_frames = self.samples = 0
        self.starts = self.repoints = self.abandoned = self.capped = 0
        self.start_ms = self.stop_ms = []
        self.aux = {}
        self.unslotted = self.distinct_sources = 0
        for line in text.splitlines():
            self._line(line)

    def _line(self, line):
        m = re.search(r"\[ax\] (\d+) frames mixed, (\d+) voice-frames, (\d+) samples output", line)
        if m:
            self.frames, self.voice_frames, self.samples = (int(g) for g in m.groups())
        m = re.search(r"census opcodes sent (.*?); never sent (.*?);", line)
        if m:
            self.opcodes = {int(k, 16): int(v) for k, v in re.findall(r"([0-9A-F]{2}):(\d+)", m[1])}
            self.never = [int(op, 16) for op in m[2].split()]
        m = re.search(r"(\d+) lists abandoned .*?, (\d+) hit the 64-command cap", line)
        if m:
            self.abandoned, self.capped = int(m[1]), int(m[2])
        m = re.search(r"census PB values over \d+ voice-frames: (.*)$", line)
        if m:
            for part in m[1].split(" | "):
                name, _, rest = part.partition(" ")
                self.fields[name] = {
                    int(v, 16): int(n) for v, n in re.findall(r"([0-9A-F]+):(\d+)", rest)
                }
        m = re.search(
            r"census aux: A reached by a voice in (\d+) frames \(peak (-?\d+)\), B in (\d+) "
            r"\(peak (-?\d+)\); back from the CPU: auxA (-?\d+) auxB (-?\d+) nowrite (-?\d+) "
            r"set-LR (-?\d+)",
            line,
        )
        if m:
            keys = ("a_frames", "a_peak", "b_frames", "b_peak", "ret_a", "ret_b", "ret_nw", "ret_lr")
            self.aux = dict(zip(keys, (int(g) for g in m.groups()), strict=True))
        m = re.search(
            r"census starts: (\d+) \(\+(\d+) re-points\).*?on ([\d/]+) off ([\d/]+)", line
        )
        if m:
            self.starts, self.repoints = int(m[1]), int(m[2])
            self.start_ms = [int(x) for x in m[3].split("/")]
            self.stop_ms = [int(x) for x in m[4].split("/")]
        m = re.search(r"census starts by source \((\d+) distinct runs, (\d+) unslotted\): (.*)$", line)
        if m:
            self.distinct_sources, self.unslotted = int(m[1]), int(m[2])
            if m[3] != "none":
                self.sources = [
                    (name.strip(), int(starts), int(frames))
                    for name, starts, frames in re.findall(
                        r"([^|]+?) (\d+) starts (\d+) frames [0-9A-F]+-[0-9A-F]+", m[3]
                    )
                ]


def check(c):
    """The invariants. Returns the list of what failed, empty when all hold."""
    bad = []
    if c.frames:
        if c.opcodes.get(0x0E, 0) != c.frames:
            bad.append(f"OUTPUT ran {c.opcodes.get(0x0E, 0)} times for {c.frames} frames")
        if c.opcodes.get(0x0F, 0) + c.abandoned != c.frames:
            bad.append("END plus abandoned lists is not the frame count")
        if c.samples != 160 * c.opcodes.get(0x0E, 0):
            bad.append("samples output is not 160 per OUTPUT")
    for op in c.never:
        if c.opcodes.get(op):
            bad.append(f"opcode {op:02X} is in both lists")
    for name, values in c.fields.items():
        if c.voice_frames and sum(values.values()) > c.voice_frames:
            bad.append(f"{name} counted more than there were voice-frames")
    if c.sources:
        if sum(s for _, s, _ in c.sources) + c.unslotted > c.starts + c.repoints:
            bad.append("more starts attributed to sources than were counted")
        if sum(f for _, _, f in c.sources) > c.voice_frames:
            bad.append("more source voice-frames than voice-frames")
    if c.aux and c.aux["a_frames"] == 0 and c.aux["a_peak"]:
        bad.append("aux A has a peak but no frame reached it")
    return bad


def test_fixture_parses():
    c = Census(FIXTURE)
    assert c.frames == 17915 and c.voice_frames == 21260
    assert c.opcodes[0x00] == 17915 and 0x01 in c.never and 0x10 in c.never
    assert c.fields["is_stream"] == {1: 21192, 0: 68}
    assert c.aux["a_peak"] == 1175 and c.aux["ret_nw"] == 28645
    assert c.starts == 6 and c.start_ms == [0] * 5
    assert ("s1000000.samp", 2, 68) in c.sources


def test_fixture_is_consistent():
    assert check(Census(FIXTURE)) == []


def test_output_count_must_match_frames():
    broken = FIXTURE.replace("0E:17915", "0E:17900")
    assert any("OUTPUT ran" in b for b in check(Census(broken)))


def test_an_opcode_cannot_be_both_sent_and_never_sent():
    broken = FIXTURE.replace("never sent 01 07", "never sent 00 01 07")
    assert any("both lists" in b for b in check(Census(broken)))


def test_sources_cannot_claim_more_starts_than_were_counted():
    broken = FIXTURE.replace("census starts: 6 ", "census starts: 2 ")
    assert any("more starts attributed" in b for b in check(Census(broken)))


def test_saved_runs_are_consistent():
    """Whatever logs are in build/: a real run must satisfy the same invariants."""
    logs = sorted((ROOT / "build").glob("*.log")) if (ROOT / "build").is_dir() else []
    seen = 0
    for log in logs:
        text = log.read_text(encoding="utf-8", errors="replace")
        if "census opcodes sent" not in text:
            continue  # written before the census existed
        seen += 1
        assert check(Census(text)) == [], log.name
    assert seen >= 0
