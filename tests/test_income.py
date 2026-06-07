"""Phase F integration — the income parser routes parsed rows through the
StatementRow guard. Exercised against REAL SEC data (network-gated)."""

import pytest

from tools.income import parse_income_statement


def _real_msft_income_raw():
    try:
        from edgar import Company, set_identity
        set_identity("research test@example.com")  # SEC requires a User-Agent identity
        return str(Company("MSFT").get_financials().income_statement())
    except Exception as e:  # offline / SEC unavailable
        pytest.skip(f"edgar/network unavailable: {e}")


def test_parse_income_statement_real_data_all_rows_valid():
    """Real MSFT data must parse to rows that ALL pass validation (no false drops)."""
    raw = _real_msft_income_raw()
    rows = parse_income_statement("MSFT", raw)
    assert rows, "real MSFT income statement should parse to rows"

    from tools.schemas import StatementRow
    for r in rows:
        StatementRow(**r)  # raises if the parser let an invalid row through

    # Real total revenue is present and in a sane millions range (not raw dollars).
    revenues = [r["value"] for r in rows if r["line_item"].strip().lower() == "revenue"]
    assert revenues, "expected a 'Revenue' line item"
    assert 100_000 < max(revenues) < 1_000_000  # ~$282B in millions


def test_parse_income_statement_routes_through_validation(monkeypatch):
    """Force the sanity ceiling absurdly low so every real, valid figure fails it.
    If the parser routes rows through validate_rows, all rows get dropped — proving
    the wiring is real, not just that real data happens to be clean."""
    raw = _real_msft_income_raw()

    import tools.schemas as schemas
    monkeypatch.setattr(schemas, "MAX_ABS_VALUE", 1.0)

    rows = parse_income_statement("MSFT", raw)
    assert rows == []  # every real row exceeds the 1.0 ceiling → all dropped
