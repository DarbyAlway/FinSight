from unittest.mock import patch

from tools import fetch_compact


def test_income_compact_returns_short_confirmation_on_success():
    full = "AAPL Income Statement (cached)\n" + "x" * 2000
    with patch.object(fetch_compact, "get_income_statement", return_value=full), \
         patch.object(fetch_compact, "load_from_cache", return_value="cached rows present"):
        out = fetch_compact.get_income_statement_compact("AAPL")
    assert "AAPL" in out
    assert "cached" in out.lower()
    assert len(out) < 200          # short confirmation, not the full dump
    assert "xxxx" not in out       # the 2000-char dump is gone


def test_income_compact_passes_through_tool_error():
    err = "TOOL_ERROR: Failed to fetch income statement for SQ: Company not found"
    with patch.object(fetch_compact, "get_income_statement", return_value=err), \
         patch.object(fetch_compact, "load_from_cache", return_value=""):
        assert fetch_compact.get_income_statement_compact("SQ") == err


def test_income_compact_passes_through_when_cache_empty():
    """Parse produced nothing (cache empty) — return the raw result so the failure
    stays visible instead of falsely confirming a successful load."""
    raw = "raw unparsed statement text " * 50
    with patch.object(fetch_compact, "get_income_statement", return_value=raw), \
         patch.object(fetch_compact, "load_from_cache", return_value=""):
        assert fetch_compact.get_income_statement_compact("AAPL") == raw


def test_income_compact_passes_through_stale_cache_notice():
    stale = "[Stale cache] AAPL Income Statement ...\n(Refresh failed: boom)"
    with patch.object(fetch_compact, "get_income_statement", return_value=stale), \
         patch.object(fetch_compact, "load_from_cache", return_value="rows"):
        assert fetch_compact.get_income_statement_compact("AAPL") == stale


def test_balance_compact_returns_short_confirmation_on_success():
    full = "AAPL Balance Sheet (cached)\n" + "y" * 2000
    with patch.object(fetch_compact, "get_balance_sheet", return_value=full), \
         patch.object(fetch_compact, "load_balance_sheet", return_value="rows"):
        out = fetch_compact.get_balance_sheet_compact("AAPL")
    assert "AAPL" in out and "cached" in out.lower() and len(out) < 200


def test_cash_flow_compact_returns_short_confirmation_on_success():
    full = "AAPL Cash Flow (cached)\n" + "z" * 2000
    with patch.object(fetch_compact, "get_cash_flow_statement", return_value=full), \
         patch.object(fetch_compact, "load_cash_flow", return_value="rows"):
        out = fetch_compact.get_cash_flow_statement_compact("AAPL")
    assert "AAPL" in out and "cached" in out.lower() and len(out) < 200
