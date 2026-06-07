"""Phase F integration — balance sheet parser validates rows and the accounting
identity holds on REAL filings (network-gated)."""

import pytest

from tools.balance_sheet import parse_balance_sheet
from tools.schemas import StatementRow, check_balance_sheet_identity


def _real_balance_raw(ticker):
    try:
        from edgar import Company, set_identity
        set_identity("research test@example.com")
        return str(Company(ticker).get_financials().balance_sheet())
    except Exception as e:
        pytest.skip(f"edgar/network unavailable: {e}")


def test_parse_balance_sheet_real_data_all_rows_valid():
    raw = _real_balance_raw("MSFT")
    rows = parse_balance_sheet("MSFT", raw)
    assert rows
    for r in rows:
        StatementRow(**r)  # parser must not emit invalid rows


def test_real_balance_sheet_balances():
    """Assets = Liabilities + Equity must hold for a real filing."""
    raw = _real_balance_raw("MSFT")
    rows = parse_balance_sheet("MSFT", raw)
    results = dict(check_balance_sheet_identity(rows))
    assert results, "expected to locate balance-sheet totals for MSFT"
    assert all(results.values()), f"MSFT balance sheet should balance: {results}"


def test_real_startup_with_mezzanine_equity_still_balances():
    """LCID has redeemable convertible preferred (mezzanine) outside L and E;
    the grand-total check must still confirm it balances, not false-flag it."""
    raw = _real_balance_raw("LCID")
    rows = parse_balance_sheet("LCID", raw)
    results = dict(check_balance_sheet_identity(rows))
    assert results, "expected to locate balance-sheet totals for LCID"
    assert all(results.values()), f"LCID should balance via grand total: {results}"
