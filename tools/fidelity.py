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


def extract_numbers(text: str) -> list[Number]:
    """Extract only UNIT-BEARING numbers. Bare integers, counts, and 4-digit
    years are deliberately ignored (primary false-positive defense)."""
    if not text:
        return []
    consumed: list[tuple[int, int]] = []  # spans already claimed, highest priority first

    def _claim(m) -> bool:
        s, e = m.span()
        for cs, ce in consumed:
            if s < ce and cs < e:  # overlaps an already-claimed span
                return False
        consumed.append((s, e))
        return True

    out: list[Number] = []
    # priority: money (suffix) > dollars > percent > ratio
    for m in _MONEY_RE.finditer(text):
        if _claim(m):
            out.append(Number(m.group(0).strip(), _to_float(m.group(1)) * _MAG[m.group(2)], "money_millions"))
    for m in _DOLLARS_RE.finditer(text):
        if _claim(m):
            out.append(Number(m.group(0).strip(), _to_float(m.group(1)), "dollars"))
    for m in _PCT_RE.finditer(text):
        if _claim(m):
            out.append(Number(m.group(0).strip(), _to_float(m.group(1)), "percent"))
    for m in _RATIO_RE.finditer(text):
        if _claim(m):
            out.append(Number(m.group(0).strip(), _to_float(m.group(1)), "ratio"))
    return out
