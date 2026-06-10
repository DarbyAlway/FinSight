"""#14 — year-aware number-fidelity verifier.

Deterministically check that every unit-bearing number in the final answer can be
traced, FOR ITS FISCAL YEAR, to a number the tools actually returned. Flag-only:
callers log mismatches; the answer is never mutated. See
claude/specs/2026-06-09-structured-handoff-fidelity-design.md.
"""
import re
from collections import defaultdict
from dataclasses import dataclass

# magnitude suffix -> multiplier to normalize money into MILLIONS of USD
_MAG = {"T": 1_000_000.0, "B": 1_000.0, "M": 1.0, "K": 0.001}

# money: optional '$', grouped digits with optional decimals, REQUIRED magnitude
# suffix. Matches "391,035M", "$93,736M", "$1.23B", "$3T".
_MONEY_RE = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([TBMK])\b")
# word-form magnitudes the synthesis model routinely writes ("$391 billion",
# "1.5 million"). Same normalization to MILLIONS as the suffix form.
_MONEY_WORD_MAG = {"trillion": 1_000_000.0, "billion": 1_000.0, "million": 1.0, "thousand": 0.001}
_MONEY_WORD_RE = re.compile(
    r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(trillion|billion|million|thousand)\b",
    re.IGNORECASE,
)
# plain dollars (price/EPS): '$' + number, NO magnitude suffix. "$182.50", "$1.64"
_DOLLARS_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)(?![0-9TBMK%])")
_PCT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
_RATIO_RE = re.compile(r"(?<![A-Za-z0-9.])([0-9]+(?:\.[0-9]+)?)\s*x\b")
# a 4-digit fiscal year, optionally prefixed FY. Used to EXCLUDE years from the
# number set and (later) to associate a number with its year.
_YEAR_RE = re.compile(r"(?:FY[\s-]?)?((?:19|20)\d{2})\b")


@dataclass(frozen=True)
class Number:
    raw: str
    value: float
    kind: str  # "money_millions" | "dollars" | "percent" | "ratio"


def _to_float(digits: str) -> float:
    return float(digits.replace(",", ""))


def _iter_number_matches(text: str) -> list[tuple[int, Number]]:
    """Yield (start_offset, Number) for every UNIT-BEARING number, de-overlapped
    in priority order. Bare integers, counts, and 4-digit years are ignored."""
    consumed: list[tuple[int, int]] = []  # spans already claimed, highest priority first

    def _claim(m) -> bool:
        s, e = m.span()
        for cs, ce in consumed:
            if s < ce and cs < e:  # overlaps an already-claimed span
                return False
        consumed.append((s, e))
        return True

    out: list[tuple[int, Number]] = []
    # priority: money (suffix) > money (word) > dollars > percent > ratio
    for m in _MONEY_RE.finditer(text):
        if _claim(m):
            out.append((m.start(), Number(m.group(0).strip(), _to_float(m.group(1)) * _MAG[m.group(2)], "money_millions")))
    for m in _MONEY_WORD_RE.finditer(text):
        if _claim(m):
            out.append((m.start(), Number(m.group(0).strip(), _to_float(m.group(1)) * _MONEY_WORD_MAG[m.group(2).lower()], "money_millions")))
    for m in _DOLLARS_RE.finditer(text):
        if _claim(m):
            out.append((m.start(), Number(m.group(0).strip(), _to_float(m.group(1)), "dollars")))
    for m in _PCT_RE.finditer(text):
        if _claim(m):
            out.append((m.start(), Number(m.group(0).strip(), _to_float(m.group(1)), "percent")))
    for m in _RATIO_RE.finditer(text):
        if _claim(m):
            out.append((m.start(), Number(m.group(0).strip(), _to_float(m.group(1)), "ratio")))
    return out


def extract_numbers(text: str) -> list[Number]:
    """Extract only UNIT-BEARING numbers. Bare integers, counts, and 4-digit
    years are deliberately ignored (primary false-positive defense)."""
    if not text:
        return []
    return [num for _, num in _iter_number_matches(text)]


def _nearest_year(start: int, year_positions: list[tuple[int, int]]) -> int | None:
    """Pick the fiscal year for a number at offset `start`. Prefer the closest
    year token AT OR AFTER the number ('$391,035M in FY2024' — the dominant prose
    pattern, and how tool lines read: 'Revenue: 391,035M  (Sep 28, 2024)'); fall
    back to the closest year before it ('FY2024 revenue was $391,035M')."""
    if not year_positions:
        return None
    after = [(pos, yr) for pos, yr in year_positions if pos >= start]
    if after:
        return min(after, key=lambda py: py[0] - start)[1]
    return min(year_positions, key=lambda py: start - py[0])[1]


def extract_year_bound_numbers(
    text: str, inherit_block_year: bool = False
) -> list[tuple[int | None, Number]]:
    """Pair each unit-bearing number with its fiscal year, per line.

    Two phrasings are handled:
      * Interleaved ('$391,035M in FY2024 and $383,285M in FY2023') — each figure
        binds to its NEAREST year (preferring one at/after it).
      * Enumeration ('FY2023, FY2024, FY2025 ... are $X, $Y, $Z respectively') —
        when N year tokens ALL precede N same-kind values, they bind IN ORDER
        (i-th year <-> i-th value). Without this, all values fall back to the last
        preceding year and the earlier ones false-flag.
    When no year token is on the line, the year is None (any-year match) —
    UNLESS inherit_block_year is set: then the line inherits the most recent
    year seen on a previous line. The cash-flow/balance-sheet tool formats put
    the date on a header line ('  Dec 31, 2025') with figures below it; without
    inheritance every such figure loses its year. Grounding-only — answers keep
    per-line binding so yearless prose stays on the lenient any-year match."""
    out: list[tuple[int | None, Number]] = []
    block_year: int | None = None
    for line in text.splitlines():
        year_positions = sorted((m.start(1), int(m.group(1))) for m in _YEAR_RE.finditer(line))
        if year_positions:
            block_year = year_positions[-1][1]
        nums = _iter_number_matches(line)
        if inherit_block_year and not year_positions and block_year is not None:
            out.extend((block_year, num) for _, num in nums)
            continue

        # Enumeration pass: per kind, if #years == #values and every year token
        # comes before every value of that kind, bind them positionally.
        enum_year: dict[int, int] = {}  # index into nums -> year
        if len(year_positions) >= 2:
            max_year_pos = year_positions[-1][0]
            by_kind: dict[str, list[tuple[int, int]]] = defaultdict(list)
            for i, (start, num) in enumerate(nums):
                by_kind[num.kind].append((start, i))
            for group in by_kind.values():
                group.sort()
                if len(group) == len(year_positions) and group[0][0] > max_year_pos:
                    for (_, yr), (_, idx) in zip(year_positions, group):
                        enum_year[idx] = yr

        for i, (start, num) in enumerate(nums):
            if i in enum_year:
                out.append((enum_year[i], num))
            else:
                out.append((_nearest_year(start, year_positions), num))
    return out


@dataclass(frozen=True)
class Mismatch:
    number: Number
    year: int | None
    hard: bool  # True = value absent from EVERY fetched year (likely fabricated);
    #             False = value is real for some OTHER year (mislabel or phrasing)


def build_grounding(tool_blocks: dict[str, str]):
    """Index the tools' raw outputs into year-scoped and any-year value sets,
    keyed by number kind. Returns (by_year, any_year)."""
    by_year: dict[tuple[int, str], set[float]] = defaultdict(set)
    any_year: dict[str, set[float]] = defaultdict(set)
    for block in (tool_blocks or {}).values():
        if not isinstance(block, str):
            continue
        for year, num in extract_year_bound_numbers(block, inherit_block_year=True):
            any_year[num.kind].add(num.value)
            if year is not None:
                by_year[(year, num.kind)].add(num.value)
    return by_year, any_year


def _close(value: float, candidates, rel_tol: float) -> bool:
    for c in candidates:
        denom = max(abs(value), abs(c), 1e-9)
        if abs(value - c) <= rel_tol * denom:
            return True
    return False


def verify(answer: str, tool_blocks: dict[str, str], rel_tol: float = 0.01) -> list[Mismatch]:
    """Flag every unit-bearing number in `answer` that cannot be traced to the
    tool outputs. Year-aware: a number carrying a fiscal year must match a value
    grounded FOR THAT YEAR; a number with no year falls back to any-year matching.
    Pure + flag-only — never mutates `answer`."""
    by_year, any_year = build_grounding(tool_blocks)
    grounded_years = {y for (y, _kind) in by_year}
    mismatches: list[Mismatch] = []
    for year, num in extract_year_bound_numbers(answer):
        if year is not None:
            candidates = by_year.get((year, num.kind), set())
        else:
            candidates = any_year.get(num.kind, set())
        if not _close(num.value, candidates, rel_tol):
            # HARD when the value is real for NO fetched year (likely fabricated);
            # SOFT when it matches some other year (mislabel or list phrasing).
            hard = not _close(num.value, any_year.get(num.kind, set()), rel_tol)
            # A figure bound to a year the tools NEVER returned cannot be a
            # mislabel-between-fetched-years — it is prior knowledge even when
            # its value coincides with a fetched year's (AAPL FY2022 revenue is
            # within 1% of FY2024's). Coverage windows differ per ticker/turn,
            # so the year set is derived from THIS query's grounding. Skipped
            # when the grounding carries no year info at all (can't judge).
            if year is not None and grounded_years and year not in grounded_years:
                hard = True
            mismatches.append(Mismatch(number=num, year=year, hard=hard))
    return mismatches
