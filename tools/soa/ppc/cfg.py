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
from .regs import gpr_defs, is_mr


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
_TRACK_BACK = 256  # how far a register's definition chain may be followed
_BOUND_BACK = 64  # how far above the bgt the bound check may be hoisted


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

    The register allocator does not keep this tidy: the @ha and @l halves often
    land in different registers, the table address may be loaded well ahead of
    the dispatch (or copied through ``mr``, or offset from a pooled base), and
    the bound check gets hoisted above unrelated stores. So rather than pattern
    matching a fixed window we follow the *definition chain* of the table
    register backward until an absolute address resolves, and find the bound by
    locating the ``bgt`` and then the nearest instruction that defines CR0
    above it. A site that still does not fit is left unresolved rather than
    guessed, and shows up in ``Function.unresolved_indirect``.

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


def _track_address(code: CodeView, from_addr: int, reg: int) -> int | None:
    """Resolve ``reg`` at ``from_addr`` to a constant by walking its definitions backward.

    Follows ``addi``/``addis``/``ori``/``mr`` chains; anything else that writes
    the tracked register (a load, an argument, arithmetic) means the value is
    not a link-time constant and we give up. Leaving the function through an
    unconditional return also gives up.
    """
    lo = 0
    addr = from_addr
    for _ in range(_TRACK_BACK):
        addr -= 4
        insn = code.at(addr)
        if insn is None or not insn.valid:
            return None
        if insn.mnemonic == "bclr" and insn.is_unconditional:
            return None
        if reg not in gpr_defs(insn):
            continue

        m = insn.mnemonic
        if m == "addi":
            lo += insn.imm
            if insn.ra == 0:  # li
                return lo & 0xFFFFFFFF
            reg = insn.ra
        elif m == "ori":
            lo += insn.imm
            reg = insn.rd  # ori's source sits in the rD field
        elif m == "addis":
            if insn.ra != 0:
                # addis off a register we would have to propagate first.
                return None
            return ((insn.imm << 16) + lo) & 0xFFFFFFFF
        elif is_mr(insn):
            reg = insn.rd
        else:
            return None
    return None


def _bound_count(code: CodeView, lwzx_addr: int) -> int | None:
    """Entry count from the switch's bound check.

    Find the ``bgt default`` (BO=12, BI=1: CR0[GT] set) immediately above the
    table load, then the nearest instruction above *that* which defines CR0.
    Only a ``cmpli``/``cmpi`` against CR0 gives a usable bound.
    """
    bgt = None
    for k in range(1, 16):
        insn = code.at(lwzx_addr - 4 * k)
        if insn is None or not insn.valid:
            return None
        if insn.mnemonic == "bc" and insn.bo == 12 and insn.bi == 1:
            bgt = insn.addr
            break
    if bgt is None:
        return None

    for k in range(1, _BOUND_BACK):
        insn = code.at(bgt - 4 * k)
        if insn is None or not insn.valid:
            return None
        m = insn.mnemonic
        if m in ("cmpli", "cmpi") and insn.crf_d == 0:
            return insn.imm + 1 if insn.imm >= 0 else None
        if m in ("cmp", "cmpl") and insn.crf_d == 0:
            return None
        if insn.rc_bit:  # record form clobbers CR0
            return None
        if m == "bclr" and insn.is_unconditional:
            return None
    return None


def _resolve_table(dol, code: CodeView, site: int) -> JumpTable | None:
    # The mtctr sits within a few instructions of its bctr.
    ctr_src = mtctr_addr = None
    for k in range(1, 5):
        insn = code.at(site - 4 * k)
        if insn is None or not insn.valid:
            return None
        if insn.mnemonic == "mtspr" and insn.spr == _SPR_CTR:
            ctr_src, mtctr_addr = insn.rd, insn.addr
            break
    if ctr_src is None:
        return None

    # The value moved to CTR must come straight from an indexed load.
    load = None
    for k in range(1, 9):
        insn = code.at(mtctr_addr - 4 * k)
        if insn is None or not insn.valid:
            return None
        if insn.mnemonic == "lwzx" and insn.rd == ctr_src:
            load = insn
            break
        if ctr_src in gpr_defs(insn):
            return None
    if load is None:
        return None

    # Either operand may hold the table; the other is the scaled index.
    base = _track_address(code, load.addr, load.ra)
    if base is None:
        base = _track_address(code, load.addr, load.rb)
    if base is None:
        return None

    count = _bound_count(code, load.addr)
    if count is None or not (0 < count <= _MAX_TABLE):
        return None

    section = dol.section_at(base)
    if section is None or section.is_text or not section.contains(base + 4 * count - 4):
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

            if insn.mnemonic == "rfi":
                # Return from interrupt: an exception-handler epilogue. Control
                # never falls through, and what follows is the next handler.
                block.terminator = "rfi"
                fn.returns += 1
                break

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


def find_materialized_pointers(dol, code: CodeView | None = None) -> set[int]:
    """Addresses of .text formed in registers by a lis/addi or lis/ori pair.

    A function whose address is *taken* this way -- to install a handler, pass
    a callback, or fill a table at runtime -- may never be bl-called and never
    appear as a data-section word. OSDefaultExceptionHandler was one: it is
    written into the exception table by OSExceptionInit through exactly this
    idiom, and nothing else references it.
    """
    code = code or CodeView(dol)
    lo = min(s.address for s in dol.text)
    hi = max(s.end for s in dol.text)
    found: set[int] = set()
    for section in dol.text:
        insns = [code.at(a) for a in range(section.address, section.end, 4)]
        for k, i in enumerate(insns):
            if i is None or not i.valid or i.mnemonic != "addis" or i.ra != 0:
                continue
            for j in range(k + 1, min(k + 9, len(insns))):
                n = insns[j]
                if n is None or not n.valid:
                    break
                if n.mnemonic == "addi" and n.ra == i.rd:
                    value = ((i.imm << 16) + n.imm) & 0xFFFFFFFF
                elif n.mnemonic == "ori" and n.rd == i.rd and n.ra == i.rd:
                    value = ((i.imm << 16) | n.imm) & 0xFFFFFFFF
                elif i.rd in gpr_defs(n):
                    break  # the high half was overwritten before a low half arrived
                else:
                    continue
                if lo <= value < hi and not (value & 3):
                    found.add(value)
                break
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


def _owns(fn: Function, addr: int) -> bool:
    return any(b.start <= addr < b.end for b in fn.blocks.values())


def _interior_owner(
    functions: dict[int, Function],
    end_index: dict[int, list[int]],
    code: CodeView,
    start: int,
    end: int,
) -> int | None:
    """The function a gap is a dead hole *inside* of, or None.

    mwcc leaves single unreachable ``b`` instructions behind an unconditional
    branch -- a jump to a label nothing else can reach. Nothing references
    them, so they surface as one-word gaps in the middle of a function. A gap
    belongs to F when F's blocks run right up to it and either resume right
    after it, or every branch inside the gap lands back in F (a dead jump at
    the function's tail). Promoting these as functions manufactured hundreds
    of phantom entries that then rebuilt their owner's tail from the inside.
    """
    for entry in end_index.get(start, ()):
        fn = functions[entry]
        if end in fn.blocks:
            return entry
        targets: list[int] | None = []
        for addr in range(start, end, 4):
            insn = code.at(addr)
            if insn is None or not insn.valid:
                targets = None
                break
            if insn.is_direct_branch and insn.target is not None:
                targets.append(insn.target)
        if targets and all(_owns(fn, t) for t in targets):
            return entry
    return None


def build_iterative(
    dol, max_rounds: int = 32, max_insns: int = 200_000
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

    # Two tiers of entry. HARD entries -- the DOL entry point, bl targets, and
    # data-section pointers that land in unclaimed code -- are believed to be
    # functions, so a `b` into one is a tail call and terminates the caller's
    # walk. SOFT entries are gap starts we promoted on the strength of nothing
    # but "code was left over here". A `b` into a soft entry is *followed*, so
    # that if it was really a mid-function label its owner reclaims it and we
    # can prune it. Making gap starts terminators was self-reinforcing: once a
    # label was mis-promoted, every later round saw the owner's branch to it as
    # a tail call and the fragment could never be reabsorbed.
    # mwcc lays functions end to end in the main text section, so once switch
    # tables are resolved any hole there is a function nothing references --
    # even one with no recognisable prologue. The small init/vector section
    # contains data, so there a gap must still *look* like a function.
    main_text = max(dol.text, key=lambda s: s.size)

    def plausible_entry(a: int) -> bool:
        insn = code.at(a)
        if insn is None or not insn.valid:
            return False
        return main_text.contains(a) or _looks_like_entry(code, a)

    hard = {dol.entry_point} | find_bl_targets(dol)
    # An address formed in registers is an address taken: a function entry
    # unless it is a switch label. It is hard so that a `b` into it is a tail
    # call, which keeps the neighbour that precedes it from swallowing it.
    hard |= {a for a in find_materialized_pointers(dol, code) if plausible_entry(a)}
    hard = {a for a in hard if code.contains(a)} - case_labels
    pointers = {a for a in find_code_pointers(dol) if code.contains(a)} - case_labels
    soft: set[int] = set()

    def gap_entry(start: int, end: int) -> int | None:
        """Where the function in a gap begins: the first word that decodes.

        A gap can open with padding or a stray data word -- one of the three
        non-instruction words in this binary's ``.text1`` sat at the head of
        the gap holding ``InitMetroTRK``, ``TRK_main`` and ``exit``, and
        rejecting the whole gap for its first word hid all three.
        """
        for addr in range(start, end, 4):
            if addr in case_labels:
                continue
            insn = code.at(addr)
            if insn is None or not insn.valid:
                continue
            if main_text.contains(addr) or _looks_like_entry(code, addr):
                return addr
            return None
        return None

    stats = {
        "rounds": 0,
        "seeds_per_round": [len(hard)],
        "from_pointers": 0,
        "from_gaps": 0,
        "absorbed": 0,
        "pruned": 0,
        "jump_tables": len(tables),
        "case_labels": len(case_labels),
    }
    functions: dict[int, Function] = {}

    for _ in range(max_rounds):
        stats["rounds"] += 1
        terminators = frozenset(hard)
        functions = {
            entry: _walk(entry, code, terminators, max_insns, tables)
            for entry in sorted(hard | soft)
        }

        # Pointers into unclaimed code are functions nothing bl-calls. Promote
        # them before mining gaps: they are stronger evidence than a leftover
        # run of code, and walking them now keeps the gap pass from claiming
        # them as anonymous remainders.
        claimed = coverage(dol, functions)["claimed"]
        fresh = {a for a in pointers - hard if a not in claimed}
        for entry in fresh:
            functions[entry] = _walk(entry, code, terminators, max_insns, tables)
        hard |= fresh
        terminators = frozenset(hard)
        stats["from_pointers"] += len(fresh)

        # Fill every remaining hole. Soft walks never affect other walks, so
        # this can iterate to a fixpoint without rebuilding the hard set --
        # which matters when a run of back-to-back unreferenced functions would
        # otherwise surface one per round.
        while True:
            end_index: dict[int, list[int]] = defaultdict(list)
            for fn in functions.values():
                for block in fn.blocks.values():
                    end_index[block.end].append(fn.entry)

            gap_starts: set[int] = set()
            absorbed = 0
            for start, end in find_gaps(dol, functions, min_words=1):
                owner = _interior_owner(functions, end_index, code, start, end)
                if owner is not None:
                    functions[owner].blocks[start] = BasicBlock(start, end, terminator="dead")
                    absorbed += 1
                    continue
                entry = gap_entry(start, end)
                if entry is not None:
                    gap_starts.add(entry)
            stats["absorbed"] += absorbed
            gap_starts -= hard | soft
            if not gap_starts:
                if absorbed:
                    continue  # coverage changed; look again
                break
            for entry in gap_starts:
                functions[entry] = _walk(entry, code, terminators, max_insns, tables)
            soft |= gap_starts
            stats["from_gaps"] += len(gap_starts)

        # A soft entry strictly inside another function's contiguous extent was
        # a mid-function label after all. An entry that merely *starts* where
        # another ends is a neighbour, and is kept.
        extents = sorted((f.start, f.end, f.entry) for f in functions.values())
        reach = 0
        pruned: set[int] = set()
        for start, end, entry in extents:
            if entry in soft and start < reach:
                pruned.add(entry)
                continue
            reach = max(reach, end)
        for entry in pruned:
            functions.pop(entry)
        soft -= pruned
        stats["pruned"] += len(pruned)

        # Soft survivors are real functions; harden them so tail calls into
        # them classify correctly on the next pass.
        grew = bool(fresh) or bool(soft)
        hard |= soft
        soft.clear()
        stats["seeds_per_round"].append(len(hard))
        if not grew:
            break

    stats["final_seeds"] = len(hard)
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
