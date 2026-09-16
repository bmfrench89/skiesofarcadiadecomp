"""Control-flow recovery: basic blocks, function boundaries, call graph.

Function discovery is seeded from three independent sources, because no single
one is complete in this binary:

  * the DOL entry point
  * every direct ``bl`` target                    (5,375 here)
  * externally supplied addresses -- function-pointer tables, jump tables,
    vtables                                        (1,781 functions are never
                                                    ``bl``-called)

From each seed we walk the CFG, following fall-through and direct branches,
stopping at returns and tail calls. A function's extent is the span its own
blocks cover.

The hard case is distinguishing a *tail call* (``b`` to another function) from
an ordinary intra-function branch. We treat a direct branch as a tail call when
its target is a known seed, which is why seeding matters more than the walk.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from .decode import BCTR, Insn, decode


@dataclass
class BasicBlock:
    start: int
    end: int = 0  # exclusive
    successors: list[int] = field(default_factory=list)
    terminator: str = ""  # mnemonic that ended the block, "" if fall-through

    @property
    def size(self) -> int:
        return self.end - self.start

    def __len__(self) -> int:
        return self.size // 4


@dataclass
class Function:
    entry: int
    blocks: dict[int, BasicBlock] = field(default_factory=dict)
    calls: set[int] = field(default_factory=set)
    tail_calls: set[int] = field(default_factory=set)
    has_frame: bool = False
    returns: int = 0
    indirect_calls: int = 0  # bctrl / blrl: flow continues, target unknown
    jump_tables: list[int] = field(default_factory=list)  # resolved bctr sites
    unresolved_indirect: int = 0  # bctr sites we could not resolve

    @property
    def has_indirect_branch(self) -> bool:
        """True when some computed branch in this function is still unresolved."""
        return self.unresolved_indirect > 0

    @property
    def start(self) -> int:
        return min(self.blocks) if self.blocks else self.entry

    @property
    def end(self) -> int:
        """End of the contiguous run of blocks starting at the entry.

        Deliberately *not* ``max(block.end)``. A single mis-classified tail
        call attaches a far-away block, and taking the maximum would then
        report a function spanning most of ``.text``. Blocks past the first
        hole belong to whatever function actually owns them.
        """
        if not self.blocks:
            return self.entry
        cursor = self.entry
        for start in sorted(self.blocks):
            if start < cursor:
                continue
            if start > cursor:
                break  # hole: stop claiming here
            cursor = self.blocks[start].end
        return cursor

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def detached_blocks(self) -> list[int]:
        """Blocks lying beyond the contiguous extent -- suspected mis-attribution."""
        end = self.end
        return sorted(s for s in self.blocks if s >= end)

    @property
    def instruction_count(self) -> int:
        return sum(len(b) for b in self.blocks.values())

    @property
    def is_leaf(self) -> bool:
        return not self.calls and not self.tail_calls

    @property
    def is_contiguous(self) -> bool:
        """True when the function's blocks tile its extent with no holes."""
        covered = sum(b.size for b in self.blocks.values())
        return covered == self.size

    @property
    def name(self) -> str:
        return f"fn_{self.entry:08X}"


class CodeView:
    """Random access to decoded instructions across a DOL's text sections."""

    def __init__(self, dol):
        self.dol = dol
        self._ranges = [(s.address, s.end, s) for s in dol.text]
        self._cache: dict[int, Insn] = {}

    def contains(self, addr: int) -> bool:
        return any(lo <= addr < hi for lo, hi, _ in self._ranges)

    def at(self, addr: int) -> Insn | None:
        if addr & 3:
            return None
        hit = self._cache.get(addr)
        if hit is not None:
            return hit
        if not self.contains(addr):
            return None
        insn = decode(self.dol.word(addr), addr)
        self._cache[addr] = insn
        return insn


def find_bl_targets(dol) -> set[int]:
    """Every address reached by a direct branch-and-link."""
    targets: set[int] = set()
    for section in dol.text:
        data = dol.read(section.address, section.size)
        for off in range(0, len(data) - 3, 4):
            word = int.from_bytes(data[off : off + 4], "big")
            if (word >> 26) != 18 or not (word & 1):  # b-form, LK set
                continue
            insn = decode(word, section.address + off)
            if insn.target is not None:
                targets.add(insn.target)
    return targets


def find_prologues(dol) -> set[int]:
    """Addresses holding ``stwu r1, -N(r1)`` -- a frame-setup prologue.

    A weak signal on its own: it misses the 431 leaf functions that never
    establish a frame, and it fires on any stack adjustment. Used only to
    cross-check, never as a sole seed.
    """
    found: set[int] = set()
    for section in dol.text:
        data = dol.read(section.address, section.size)
        for off in range(0, len(data) - 3, 4):
            word = int.from_bytes(data[off : off + 4], "big")
            # stwu rS=1, rA=1, negative displacement
            if (word >> 16) == 0x9421 and (word & 0x8000):
                found.add(section.address + off)
    return found


@dataclass
class JumpTable:
    """A resolved switch table: the ``bctr`` that dispatches through it, and its targets."""

    site: int  # address of the bctr
    base: int  # table address in a data section
    targets: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.targets)


_SPR_CTR = 9
_MAX_TABLE = 4096
_LOOKBACK = 24  # instructions to scan backward from a bctr


def find_jump_tables(dol, code: CodeView | None = None) -> dict[int, JumpTable]:
    """Resolve every ``bctr`` that dispatches through an mwcc switch table.

    mwcc emits one idiom for every switch in this binary::

        cmpli  cr0, rX, N          bound check: N+1 cases
        bc     gt -> default
        addis  rT, r0, hi          table address as an @ha/@l pair
        rlwinm rI, rX, 2, 0, 29    index * 4  (sometimes pre-scaled)
        addi   rT, rT, lo
        lwzx   rC, rT, rI
        mtspr  CTR, rC
        bctr

    We walk backward from the ``bctr`` collecting each piece by register. A
    site that does not fit is left unresolved rather than guessed, and shows
    up in ``Function.unresolved_indirect``.

    Resolving these matters twice over: the targets become intra-function
    successors, and they are *excluded* from function-entry seeding -- they
    are case labels, and treating them as functions was the source of a
    2,600-entry over-count.
    """
    code = code or CodeView(dol)
    tables: dict[int, JumpTable] = {}
    for section in dol.text:
        data = dol.read(section.address, section.size)
        for off in range(0, len(data) - 3, 4):
            if int.from_bytes(data[off : off + 4], "big") != BCTR:
                continue
            site = section.address + off
            table = _resolve_table(dol, code, site)
            if table is not None:
                tables[site] = table
    return tables


def _resolve_table(dol, code: CodeView, site: int) -> JumpTable | None:
    ctr_src = table_reg = None
    hi = lo = count = None

    for back in range(1, _LOOKBACK + 1):
        insn = code.at(site - 4 * back)
        if insn is None or not insn.valid:
            break
        m = insn.mnemonic

        # Each stage consumes the nearest matching instruction, walking backward.
        if ctr_src is None:
            if m == "mtspr" and insn.spr == _SPR_CTR:
                ctr_src = insn.rd
            continue
        if table_reg is None:
            if m == "lwzx" and insn.rd == ctr_src:
                table_reg = insn.ra
            continue
        if lo is None:
            if m == "addi" and insn.rd == table_reg and insn.ra == table_reg:
                lo = insn.imm
            continue
        if hi is None:
            if m == "addis" and insn.rd == table_reg and insn.ra == 0:
                hi = insn.imm
            continue
        if m == "cmpli":
            count = insn.imm + 1
            break

    if None in (ctr_src, table_reg, lo, hi, count) or not (0 < count <= _MAX_TABLE):
        return None

    base = ((hi << 16) + lo) & 0xFFFFFFFF
    section = dol.section_at(base)
    if section is None or not section.contains(base + 4 * count - 4):
        return None

    targets = [dol.word(base + 4 * k) for k in range(count)]
    if not all(code.contains(t) for t in targets):
        return None
    return JumpTable(site=site, base=base, targets=targets)


def _walk(
    entry: int,
    code: CodeView,
    seeds: frozenset[int],
    max_insns: int,
    tables: dict[int, JumpTable],
) -> Function:
    """Trace one function's blocks from its entry."""
    fn = Function(entry=entry)
    pending = [entry]
    seen: set[int] = set()
    budget = max_insns

    while pending:
        block_start = pending.pop()
        if block_start in seen or not code.contains(block_start):
            continue
        seen.add(block_start)

        block = BasicBlock(start=block_start)
        addr = block_start

        while budget > 0:
            insn = code.at(addr)
            if insn is None or not insn.valid:
                block.terminator = "invalid"
                break
            budget -= 1
            addr += 4

            if (
                block_start == entry
                and insn.mnemonic == "stwu"
                and insn.ra == 1
                and insn.rd == 1
                and insn.imm < 0
            ):
                fn.has_frame = True

            if not insn.is_branch:
                # A new block begins wherever another branch lands.
                if addr in seen:
                    block.successors.append(addr)
                    break
                continue

            if insn.is_call:
                if insn.is_indirect_branch:
                    fn.indirect_calls += 1
                elif insn.target is not None:
                    fn.calls.add(insn.target)
                continue  # a call returns; flow proceeds to the next instruction

            block.terminator = insn.mnemonic

            if insn.mnemonic == "bclr":
                # A return. When conditional (beqlr, bnelr, ...) execution
                # falls through on the untaken path -- stopping here truncated
                # every function containing one.
                fn.returns += 1
                if not insn.is_unconditional:
                    block.successors.append(addr)
                    pending.append(addr)
                break

            if insn.mnemonic == "bcctr":
                table = tables.get(insn.addr)
                if table is not None:
                    fn.jump_tables.append(insn.addr)
                    for t in table.targets:
                        if t not in block.successors:
                            block.successors.append(t)
                            pending.append(t)
                else:
                    fn.unresolved_indirect += 1
                if not insn.is_unconditional:
                    block.successors.append(addr)
                    pending.append(addr)
                break

            target = insn.target

            if target is not None and target != entry and target in seeds:
                fn.tail_calls.add(target)  # b into another function
                if insn.is_unconditional:
                    break
                block.successors.append(addr)
                pending.append(addr)
                break

            if target is not None and code.contains(target):
                block.successors.append(target)
                pending.append(target)

            if not insn.is_unconditional:
                block.successors.append(addr)
                pending.append(addr)
            break

        block.end = addr
        fn.blocks[block_start] = block

    return fn


def build(
    dol, extra_seeds: set[int] | None = None, max_insns: int = 200_000
) -> dict[int, Function]:
    """Recover every function reachable from the DOL entry and all call sites."""
    code = CodeView(dol)
    tables = find_jump_tables(dol, code)

    seeds = {dol.entry_point}
    seeds |= find_bl_targets(dol)
    if extra_seeds:
        seeds |= {a for a in extra_seeds if code.contains(a)}
    seeds = {a for a in seeds if code.contains(a)}

    frozen = frozenset(seeds)
    return {entry: _walk(entry, code, frozen, max_insns, tables) for entry in sorted(seeds)}


def find_code_pointers(dol) -> set[int]:
    """Aligned words in data sections that point into .text.

    These are function-pointer tables, jump tables and vtables. They matter a
    great deal here: most functions this binary never reaches by ``bl`` are
    reached through one of these instead.
    """
    lo = min(s.address for s in dol.text)
    hi = max(s.end for s in dol.text)
    found: set[int] = set()
    for section in dol.sections:
        if section.is_text:
            continue
        data = dol.read(section.address, section.size)
        for off in range(0, len(data) - 3, 4):
            word = int.from_bytes(data[off : off + 4], "big")
            if lo <= word < hi and not (word & 3):
                found.add(word)
    return found


# The two ways mwcc opens a function: establish a frame, or (for a leaf that
# still calls something) save the link register first.
_MFLR_R0 = 0x7C0802A6


def _looks_like_entry(code: CodeView, addr: int) -> bool:
    insn = code.at(addr)
    if insn is None or not insn.valid:
        return False
    if insn.word == _MFLR_R0:
        return True
    return insn.mnemonic == "stwu" and insn.ra == 1 and insn.rd == 1 and insn.imm < 0


def build_iterative(
    dol, max_rounds: int = 8, max_insns: int = 200_000
) -> tuple[dict[int, Function], dict]:
    """Recover functions, then mine the gaps for entries the seeds missed.

    Seeding only from ``bl`` targets reaches 62% of ``.text`` here. Adding
    data-section code pointers takes it to ~98%. The remainder is code reached
    only through jump tables we have not resolved yet, so we promote a gap to a
    function entry when it *opens* like one -- never merely because it contains
    a ``stwu``, which would turn every mid-function stack adjustment into a
    false entry.
    """
    code = CodeView(dol)
    tables = find_jump_tables(dol, code)
    case_labels = {t for table in tables.values() for t in table.targets}

    # High-confidence seeds only, minus anything a switch table points at:
    # those are case labels inside a function body, never entries.
    seeds = {dol.entry_point} | find_bl_targets(dol)
    seeds = {a for a in seeds if code.contains(a)} - case_labels
    pointers = {a for a in find_code_pointers(dol) if code.contains(a)} - case_labels

    # mwcc lays functions end to end with no padding in the main text section,
    # so once switch tables are resolved any hole there is a function nothing
    # references directly -- even one that opens with no recognisable prologue.
    # Smaller text sections (the init/exception-vector ROM image) do contain
    # data, so there we still insist a gap *look* like a function.
    main_text = max(dol.text, key=lambda s: s.size)

    stats = {
        "rounds": 0,
        "seeds_per_round": [len(seeds)],
        "from_pointers": 0,
        "from_gaps": 0,
        "jump_tables": len(tables),
        "case_labels": len(case_labels),
    }
    functions: dict[int, Function] = {}

    for _ in range(max_rounds):
        stats["rounds"] += 1
        frozen = frozenset(seeds)
        functions = {
            entry: _walk(entry, code, frozen, max_insns, tables) for entry in sorted(seeds)
        }

        claimed = coverage(dol, functions)["claimed"]
        added: set[int] = set()

        # A pointer into already-claimed code is a case label or a mid-function
        # label; a pointer into unclaimed code is a function nothing bl-calls.
        fresh_pointers = {a for a in pointers - seeds if a not in claimed}
        added |= fresh_pointers
        stats["from_pointers"] += len(fresh_pointers)

        gap_starts: set[int] = set()
        for start, _ in find_gaps(dol, functions, min_words=1):
            if start in claimed or start in case_labels:
                continue
            insn = code.at(start)
            if insn is None or not insn.valid:
                continue
            if main_text.contains(start) or _looks_like_entry(code, start):
                gap_starts.add(start)
        gap_starts -= seeds | added
        added |= gap_starts
        stats["from_gaps"] += len(gap_starts)

        if not added:
            break
        seeds |= added
        stats["seeds_per_round"].append(len(seeds))

    stats["final_seeds"] = len(seeds)
    return functions, stats


def coverage(dol, functions: dict[int, Function]) -> dict:
    """How much of .text the recovered functions actually account for."""
    covered = 0
    per_section: dict[str, int] = defaultdict(int)
    claimed: set[int] = set()

    for fn in functions.values():
        for block in fn.blocks.values():
            for addr in range(block.start, block.end, 4):
                if addr not in claimed:
                    claimed.add(addr)
                    covered += 4

    total = sum(s.size for s in dol.text)
    for section in dol.text:
        hits = sum(1 for a in claimed if section.address <= a < section.end)
        per_section[section.name] = hits * 4

    return {
        "functions": len(functions),
        "covered_bytes": covered,
        "total_text_bytes": total,
        "coverage_pct": 100.0 * covered / total if total else 0.0,
        "per_section": dict(per_section),
        "claimed": claimed,
    }


def find_gaps(dol, functions: dict[int, Function], min_words: int = 4) -> list[tuple[int, int]]:
    """Runs of unclaimed instruction words -- candidates for missed entries."""
    cov = coverage(dol, functions)
    claimed = cov["claimed"]
    gaps: list[tuple[int, int]] = []

    for section in dol.text:
        run_start = None
        for addr in range(section.address, section.end, 4):
            if addr in claimed:
                if run_start is not None:
                    if (addr - run_start) // 4 >= min_words:
                        gaps.append((run_start, addr))
                    run_start = None
            elif run_start is None:
                run_start = addr
        if run_start is not None and (section.end - run_start) // 4 >= min_words:
            gaps.append((run_start, section.end))

    return gaps
