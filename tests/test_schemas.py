"""Phase F — Pydantic data-integrity guards for parsed financial figures.

These models are the systematic version of the manual 2026-06-04 bug hunt: a bad
parse (NaN, unit-scale error, >100% gross margin from the wrong denominator) must
be caught at the source, logged, and skipped — never stored in DuckDB or shown.
"""

import pytest
from pydantic import ValidationError

from tools import schemas


def _row(**over):
    base = {
        "ticker": "AAPL", "fiscal_year": "Sep 28, 2024", "section": "General",
        "line_item": "Net sales", "value": 391035.0, "fetched_at": 0.0,
    }
    base.update(over)
    return base


# --- StatementRow (single parsed line item) ------------------------------

def test_statement_row_accepts_valid():
    schemas.StatementRow(**_row())  # must not raise


def test_statement_row_rejects_empty_line_item():
    with pytest.raises(ValidationError):
        schemas.StatementRow(**_row(line_item=""))


def test_statement_row_rejects_empty_ticker():
    with pytest.raises(ValidationError):
        schemas.StatementRow(**_row(ticker="  "))


def test_statement_row_rejects_nan_value():
    with pytest.raises(ValidationError):
        schemas.StatementRow(**_row(value=float("nan")))


def test_statement_row_rejects_infinite_value():
    with pytest.raises(ValidationError):
        schemas.StatementRow(**_row(value=float("inf")))


def test_statement_row_rejects_absurd_magnitude():
    # 3.9e11 looks like revenue left in raw dollars (unit multiplier missed),
    # not normalized to millions — a gross-scale error we must reject.
    with pytest.raises(ValidationError):
        schemas.StatementRow(**_row(value=391_035_000_000.0))


# --- validate_rows (drop bad, keep good) ---------------------------------

def test_validate_rows_drops_invalid_keeps_valid():
    rows = [_row(), _row(value=float("inf")), _row(line_item="  ")]
    valid = schemas.validate_rows(rows, context="income AAPL")
    assert len(valid) == 1
    assert valid[0]["line_item"] == "Net sales"


def test_validate_rows_returns_plain_dicts_for_db():
    # Downstream save_to_cache consumes dicts with r["ticker"] etc., so the
    # validated output must stay dict-shaped, not become model instances.
    valid = schemas.validate_rows([_row()])
    assert isinstance(valid[0], dict)
    assert valid[0]["ticker"] == "AAPL"


# --- MarginRow (derived metric) ------------------------------------------

def test_margin_row_accepts_normal_margin():
    schemas.MarginRow(fiscal_year="2025", revenue=281_724.0, gross_margin_pct=0.688)


def test_margin_row_rejects_revenue_not_positive():
    with pytest.raises(ValidationError):
        schemas.MarginRow(fiscal_year="2025", revenue=0.0)


def test_margin_row_rejects_gross_margin_over_100pct():
    # The MSFT 220.8% bug: gross margin computed against a revenue sub-item
    # (Cost of revenue) instead of Total revenue. >100% gross margin is impossible.
    with pytest.raises(ValidationError):
        schemas.MarginRow(fiscal_year="2025", revenue=87_831.0, gross_margin_pct=2.208)


def test_margin_row_accepts_real_msft_2025_margins():
    # Real MSFT FY2025: revenue 281,724; gross 193,893 (68.8%); operating
    # 128,528 (45.6%). All sane and internally consistent (operating <= gross).
    schemas.MarginRow(
        fiscal_year="Jun 30, 2025", revenue=281_724.0,
        gross_margin_pct=193_893 / 281_724,
        operating_margin_pct=128_528 / 281_724,
    )


def test_margin_row_rejects_operating_margin_above_gross():
    # Operating income = gross profit − opex, so operating margin can never
    # exceed gross margin. If it does, rows were mismatched.
    with pytest.raises(ValidationError):
        schemas.MarginRow(
            fiscal_year="2025", revenue=1000.0,
            gross_margin_pct=0.30, operating_margin_pct=0.50,
        )


def test_margin_row_allows_extreme_negative_net_margin_for_microcap():
    # A real pre-revenue micro-cap can lose 100x its tiny revenue (-10,000%).
    # That is NOT a parse error — net margin must have no floor at all.
    schemas.MarginRow(fiscal_year="2025", revenue=1.0, net_margin_pct=-100.0)


def test_margin_row_allows_negative_operating_margin():
    # Deep operating losses are real; only operating > gross is impossible.
    schemas.MarginRow(
        fiscal_year="2025", revenue=100.0,
        gross_margin_pct=0.20, operating_margin_pct=-5.0,
    )


# --- BalanceSheetIdentity (A = L + E) ------------------------------------

def test_balance_sheet_identity_accepts_balanced():
    schemas.BalanceSheetIdentity(
        fiscal_year="2025", total_assets=600_000.0,
        total_liabilities=350_000.0, total_equity=250_000.0,
    )


def test_balance_sheet_identity_rejects_unbalanced():
    with pytest.raises(ValidationError):
        schemas.BalanceSheetIdentity(
            fiscal_year="2025", total_assets=600_000.0,
            total_liabilities=350_000.0, total_equity=100_000.0,  # 200k short
        )


def test_balance_sheet_identity_tolerates_rounding():
    # A few million off on a $600B balance sheet is rounding, not an error.
    schemas.BalanceSheetIdentity(
        fiscal_year="2025", total_assets=600_000.0,
        total_liabilities=350_000.0, total_equity=249_990.0,
    )


def test_check_balance_sheet_identity_finds_totals_in_rows():
    rows = [
        {"fiscal_year": "2025", "line_item": "Total assets", "value": 600_000.0},
        {"fiscal_year": "2025", "line_item": "Total liabilities", "value": 350_000.0},
        {"fiscal_year": "2025", "line_item": "Total stockholders' equity", "value": 250_000.0},
    ]
    results = dict(schemas.check_balance_sheet_identity(rows))
    assert results["2025"] is True


def test_check_balance_sheet_identity_flags_corrupt_grand_total():
    # A grand-total line that disagrees with total assets is a genuine parse
    # corruption (the two numbers are two copies of the same figure).
    rows = [
        {"fiscal_year": "2025", "line_item": "Total assets", "value": 600_000.0},
        {"fiscal_year": "2025", "line_item": "Total liabilities and equity", "value": 500_000.0},
    ]
    results = dict(schemas.check_balance_sheet_identity(rows))
    assert results["2025"] is False


def test_check_balance_sheet_identity_handles_mezzanine_equity():
    # LCID-style: A = liabilities + redeemable preferred + equity. Two-bucket
    # L+E under-sums, but the grand-total line equals assets — must NOT flag.
    rows = [
        {"fiscal_year": "2025", "line_item": "Total assets", "value": 8387.0},
        {"fiscal_year": "2025", "line_item": "Total liabilities", "value": 5386.0},
        {"fiscal_year": "2025", "line_item": "Total stockholders' equity", "value": 717.0},
        {"fiscal_year": "2025",
         "line_item": "Total liabilities, redeemable convertible preferred stock and equity",
         "value": 8387.0},
    ]
    results = dict(schemas.check_balance_sheet_identity(rows))
    assert results["2025"] is True


def test_check_balance_sheet_identity_skips_uncertain_two_bucket_mismatch():
    # No grand-total line and L+E != A → could be unbooked mezzanine/NCI, so we
    # skip (do not false-flag) rather than report an imbalance.
    rows = [
        {"fiscal_year": "2025", "line_item": "Total assets", "value": 600_000.0},
        {"fiscal_year": "2025", "line_item": "Total liabilities", "value": 350_000.0},
        {"fiscal_year": "2025", "line_item": "Total equity", "value": 100_000.0},
    ]
    results = dict(schemas.check_balance_sheet_identity(rows))
    assert "2025" not in results  # skipped, not falsely flagged
