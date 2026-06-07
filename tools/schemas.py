"""Phase F — Pydantic data-integrity guards for parsed financial figures.

Principle (same as tickers): the LLM should never *type* a number, and the data
layer should never *store* an impossible one. A bad parse — NaN/inf, a unit-scale
error, a >100% gross margin from the wrong denominator — is caught here at the
source, logged, and skipped, so it can never reach DuckDB or the model's summary.

This is the systematic, permanent version of the manual 2026-06-04 bug hunt
(unit multiplier, fiscal quarters, the MSFT 220.8% margin).
"""

import logging
import math
from collections import defaultdict

from pydantic import BaseModel, Field, field_validator, model_validator

# Sanity ceiling for a single line item, expressed in MILLIONS of USD. The
# largest real figures (total assets of the biggest banks) are ~4e6 ($4T). 1e8
# (= $100 trillion) is a generous ceiling that still catches gross unit-scale
# errors, e.g. revenue left in raw dollars instead of normalized to millions.
MAX_ABS_VALUE = 1e8


class StatementRow(BaseModel):
    """One parsed financial line item, as produced by the statement parsers."""

    ticker: str
    fiscal_year: str
    section: str = ""
    line_item: str
    value: float
    fetched_at: float

    @field_validator("ticker", "fiscal_year", "line_item")
    @classmethod
    def _non_empty(cls, v: str, info) -> str:
        if not v or not str(v).strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return v

    @field_validator("value")
    @classmethod
    def _finite_and_bounded(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("value must be finite (got NaN/inf)")
        if abs(v) > MAX_ABS_VALUE:
            raise ValueError(
                f"value {v:,.0f} exceeds sanity bound {MAX_ABS_VALUE:,.0f}M "
                "— likely a unit-scale parse error"
            )
        return v


def validate_rows(rows: list[dict], context: str = "") -> list[dict]:
    """Return only the rows that pass StatementRow validation.

    Bad rows are logged and dropped rather than raising, so one corrupt line in a
    statement never discards the whole fetch. Output stays dict-shaped because
    downstream cache writers (save_to_cache, etc.) consume dicts directly.
    """
    valid: list[dict] = []
    for r in rows:
        try:
            StatementRow(**r)
            valid.append(r)
        except Exception as e:
            logging.warning(
                "schemas: dropping invalid row%s: %s — %r",
                f" ({context})" if context else "", e, r,
            )
    return valid


class MarginRow(BaseModel):
    """A derived per-year margin figure. Margins are fractions (0.688 = 68.8%).

    Bounds are deliberately asymmetric so they catch parse errors WITHOUT
    rejecting real businesses: gross margin is physically capped at 100% (you
    can't keep more than you sold) but net/operating margins can be deeply
    negative for real loss-making companies, so their floors stay loose.
    """

    fiscal_year: str
    revenue: float = Field(gt=0)  # revenue can't be zero or negative
    gross_margin_pct: float | None = None
    operating_margin_pct: float | None = None
    net_margin_pct: float | None = None  # informational only — NO floor (see below)

    @field_validator("gross_margin_pct")
    @classmethod
    def _gross_not_over_100(cls, v: float | None) -> float | None:
        # >100% gross margin is physically impossible (gross profit <= revenue):
        # it means the denominator was a revenue sub-item, not Total revenue
        # (the MSFT 220.8% bug). We intentionally do NOT floor gross/net margins:
        # a real pre-revenue/distressed company can lose many multiples of its
        # tiny revenue, so any negative floor would false-reject real filings.
        if v is not None and v > 1.0001:
            raise ValueError(
                f"gross margin {v:.1%} exceeds 100% — wrong revenue denominator"
            )
        return v

    @model_validator(mode="after")
    def _operating_not_above_gross(self) -> "MarginRow":
        # operating income = gross profit − opex, so operating margin can never
        # exceed gross margin. If it does, the rows were mismatched.
        if self.operating_margin_pct is not None and self.gross_margin_pct is not None:
            if self.operating_margin_pct > self.gross_margin_pct + 0.0001:
                raise ValueError(
                    f"operating margin {self.operating_margin_pct:.1%} exceeds "
                    f"gross margin {self.gross_margin_pct:.1%} — mismatched rows"
                )
        return self


class BalanceSheetIdentity(BaseModel):
    """The fundamental accounting identity: Assets = Liabilities + Equity.

    A balance sheet that doesn't balance (beyond a small rounding tolerance)
    means rows were mis-parsed or mis-signed — the strongest structural guard.
    """

    fiscal_year: str
    total_assets: float = Field(gt=0)
    total_liabilities: float
    total_equity: float
    tolerance_frac: float = 0.01  # 1% of total assets

    @model_validator(mode="after")
    def _balances(self) -> "BalanceSheetIdentity":
        rhs = self.total_liabilities + self.total_equity
        if abs(self.total_assets - rhs) > self.tolerance_frac * abs(self.total_assets):
            raise ValueError(
                f"balance sheet does not balance: assets {self.total_assets:,.0f} "
                f"!= liabilities+equity {rhs:,.0f}"
            )
        return self


def _find_total(items: list[tuple[str, float]], includes, excludes=()) -> float | None:
    """Find the first value whose line-item contains all `includes` and none of
    `excludes` (case-insensitive)."""
    for line_item, value in items:
        low = line_item.lower()
        if all(i in low for i in includes) and not any(e in low for e in excludes):
            return value
    return None


def check_balance_sheet_identity(rows: list[dict], tolerance_frac: float = 0.01):
    """Verify Assets = Liabilities + Equity per fiscal year from parsed rows.

    Returns a list of (fiscal_year, ok) and logs a warning for any year that
    doesn't balance. Years missing one of the three totals are skipped (can't
    check). Warn-only: we never drop balance-sheet data, just flag corruption.
    """
    by_year: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        by_year[r["fiscal_year"]].append((r["line_item"], r["value"]))

    results: list[tuple[str, bool]] = []
    for fy, items in by_year.items():
        assets = _find_total(items, ["total assets"])
        if assets is None:
            continue

        # PRIMARY (robust): the grand-total line "Total liabilities and equity"
        # must equal total assets. It inherently includes mezzanine/redeemable
        # preferred and noncontrolling interests — which a two-bucket A=L+E check
        # would wrongly exclude, false-flagging real startups (LCID, PLUG).
        grand = (
            _find_total(items, ["total", "liabilities", "equity"])
            or _find_total(items, ["total", "liabilities", "preferred"])
        )
        if grand is not None:
            ok = abs(assets - grand) <= tolerance_frac * abs(assets)
            if not ok:
                logging.warning(
                    "schemas: %s balance check failed: assets %s != "
                    "total liabilities+equity %s", fy, f"{assets:,.0f}", f"{grand:,.0f}",
                )
            results.append((fy, ok))
            continue

        # FALLBACK: two-bucket A = L + E. Only TRUST a positive result — a
        # mismatch here may just be unbooked mezzanine/NCI, so we SKIP (never
        # false-flag) rather than report False.
        liabilities = _find_total(items, ["total liabilities"], excludes=["equity", "preferred"])
        equity = _find_total(items, ["total", "equity"], excludes=["liabilities"])
        if liabilities is None or equity is None:
            continue
        if abs(assets - (liabilities + equity)) <= tolerance_frac * abs(assets):
            results.append((fy, True))
        # else: uncertain (possible mezzanine/NCI) → skip, do not flag
    return results
