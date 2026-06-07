import time
import duckdb
from tools.db import init_db


def _seed_price(ticker, rows):
    from tools.config import DB_PATH
    init_db()
    with duckdb.connect(DB_PATH) as con:
        con.executemany(
            "INSERT OR REPLACE INTO price_history (ticker, date, close, fetched_at) VALUES (?, ?, ?, ?)",
            rows,
        )


def test_get_price_history_loads_from_cache():
    import tools.price as price_mod
    _seed_price("FAKEPRICE", [
        ("FAKEPRICE", "2025-01-01", 150.0, time.time()),
        ("FAKEPRICE", "2025-01-02", 152.0, time.time()),
        ("FAKEPRICE", "2025-01-03", 148.0, time.time()),
    ])
    result = price_mod.get_price_history("FAKEPRICE")
    assert isinstance(result, str)
    assert "FAKEPRICE" in result
    assert "150" in result or "152" in result or "148" in result


def test_get_price_history_returns_error_for_missing_ticker(monkeypatch):
    import tools.price as price_mod
    import yfinance as yf

    class FakeHistory:
        empty = True

    class FakeTicker:
        def history(self, period):
            return FakeHistory()

    monkeypatch.setattr(yf, "Ticker", lambda t: FakeTicker())
    result = price_mod.get_price_history("ZZZFAKE999")
    assert "No price history" in result or "Failed" in result


from tools.db import save_to_cache


def _seed_income(ticker, rows):
    init_db()
    save_to_cache([
        {"ticker": ticker, "fiscal_year": fy, "section": section,
         "line_item": line_item, "value": value, "fetched_at": time.time()}
        for fy, section, line_item, value in rows
    ])


def test_calculate_revenue_cagr_returns_percentage():
    from tools.calc import calculate_revenue_cagr
    _seed_income("CAGRCO", [
        ("Sep 28, 2024", "Net sales", "Net sales", 400_000.0),
        ("Sep 30, 2023", "Net sales", "Net sales", 370_000.0),
        ("Sep 24, 2022", "Net sales", "Net sales", 340_000.0),
    ])
    result = calculate_revenue_cagr("CAGRCO", years=2)
    assert isinstance(result, str)
    assert "CAGRCO" in result
    assert "%" in result


def test_calculate_revenue_cagr_missing_data():
    from tools.calc import calculate_revenue_cagr
    result = calculate_revenue_cagr("ZZZNOCAGR")
    assert "ERROR" in result or "No revenue data" in result


def test_calculate_margin_trend_returns_table():
    from tools.calc import calculate_margin_trend
    _seed_income("MARGCO", [
        ("Sep 28, 2024", "Net sales", "Net sales", 400_000.0),
        ("Sep 28, 2024", "Gross margin", "Gross margin", 160_000.0),
        ("Sep 28, 2024", "Net income", "Net income", 80_000.0),
        ("Sep 30, 2023", "Net sales", "Net sales", 370_000.0),
        ("Sep 30, 2023", "Gross margin", "Gross margin", 140_000.0),
        ("Sep 30, 2023", "Net income", "Net income", 70_000.0),
    ])
    result = calculate_margin_trend("MARGCO")
    assert "MARGCO" in result
    assert "gross" in result.lower() or "margin" in result.lower()


def test_calculate_margin_trend_ignores_cost_of_revenue_subitem():
    """Regression: 'Cost of revenue' matches the %revenue% synonym, and the old
    code kept the last-matched row as the denominator → MSFT showed a 220.8%
    gross margin. Must divide by TOTAL revenue (the max), not the sub-item."""
    from tools.calc import calculate_margin_trend
    _seed_income("MARGBUG", [
        ("Jun 30, 2025", "General", "Total revenue", 281_724.0),
        ("Jun 30, 2025", "General", "Cost of revenue", 87_831.0),
        ("Jun 30, 2025", "General", "Gross margin", 193_893.0),
        ("Jun 30, 2025", "General", "Net income", 101_832.0),
    ])
    result = calculate_margin_trend("MARGBUG")
    assert "281,724" in result      # denominator is total revenue, not 87,831
    assert "220" not in result      # the impossible 220.8% gross margin is gone
    assert "68.8%" in result        # 193,893 / 281,724
    assert "36.1%" in result        # 101,832 / 281,724


def test_calculate_margin_trend_real_msft_no_impossible_margin():
    """Real SEC data end-to-end: the 220.8% gross-margin bug must be gone, and
    the denominator must be MSFT's real total revenue (281,724), not a sub-item."""
    import pytest
    try:
        from edgar import set_identity
        set_identity("research test@example.com")  # SEC requires a User-Agent identity
        from tools.income import get_income_statement
        get_income_statement("MSFT")  # fetch + parse + cache real SEC data
    except Exception as e:
        pytest.skip(f"edgar/network unavailable: {e}")

    from tools.calc import calculate_margin_trend
    result = calculate_margin_trend("MSFT")
    assert "281,724" in result   # real FY2025 total revenue as denominator
    assert "220" not in result   # the impossible 220.8% gross margin is gone
    assert "68.8%" in result     # 193,893 / 281,724


def test_calculate_yoy_returns_change():
    from tools.calc import calculate_yoy
    _seed_income("YOYCO", [
        ("Sep 28, 2024", "Net sales", "Net sales", 400_000.0),
        ("Sep 30, 2023", "Net sales", "Net sales", 370_000.0),
    ])
    result = calculate_yoy("YOYCO", "revenue")
    assert "YOYCO" in result
    assert "%" in result


def test_calculate_yoy_missing_data():
    from tools.calc import calculate_yoy
    result = calculate_yoy("ZZZNO", "revenue")
    assert "ERROR" in result or "No data" in result


from tools.db import save_ticker_info


def test_calculate_peg_returns_ratio():
    from tools.calc import calculate_peg
    _seed_income("PEGCO", [
        ("Sep 28, 2024", "Net income", "Net income", 100_000.0),
        ("Sep 30, 2023", "Net income", "Net income", 80_000.0),
        ("Sep 24, 2022", "Net income", "Net income", 64_000.0),
    ])
    save_ticker_info("PEGCO", {
        "trailingPE": 25.0,
        "sector": "Technology",
        "longBusinessSummary": "A fake company.",
    })
    result = calculate_peg("PEGCO")
    assert "PEGCO" in result
    assert "PEG" in result


def test_calculate_peg_missing_pe():
    from tools.calc import calculate_peg
    save_ticker_info("NOPECO", {
        "sector": "Technology",
        "longBusinessSummary": "No PE company.",
    })
    result = calculate_peg("NOPECO")
    assert "ERROR" in result or "N/A" in result or "unavailable" in result.lower()


def test_calculate_dcf_returns_intrinsic_value():
    from tools.calc import calculate_dcf
    _seed_income("DCFCO", [
        ("Sep 28, 2024", "Operating income", "Operating income", 50_000.0),
    ])
    save_ticker_info("DCFCO", {
        "currentPrice": 150.0,
        "sharesOutstanding": 1_000_000_000,
        "sector": "Technology",
        "longBusinessSummary": "A DCF test company.",
    })
    result = calculate_dcf("DCFCO", growth_rate=0.10, discount_rate=0.10)
    assert "DCFCO" in result
    assert "Intrinsic value" in result or "intrinsic" in result.lower()


def test_calculate_dcf_missing_operating_income():
    from tools.calc import calculate_dcf
    result = calculate_dcf("ZZZNO_OP_INC")
    assert "ERROR" in result


def test_calculate_pe_vs_sector_returns_comparison():
    from tools.calc import calculate_pe_vs_sector
    save_ticker_info("SECCO", {
        "trailingPE": 25.0,
        "sector": "Technology",
        "longBusinessSummary": "Sector test company.",
    })
    result = calculate_pe_vs_sector("SECCO")
    assert "SECCO" in result
    assert "P/E" in result or "sector" in result.lower()


def test_calculate_pe_vs_sector_no_pe():
    from tools.calc import calculate_pe_vs_sector
    save_ticker_info("NOPESEC", {
        "sector": "Technology",
        "longBusinessSummary": "No PE.",
    })
    result = calculate_pe_vs_sector("NOPESEC")
    assert "ERROR" in result or "unavailable" in result.lower()


def test_calculate_correlation_returns_matrix(monkeypatch):
    from tools.calc import calculate_correlation
    import tools.price as price_mod
    _seed_price("CORA", [
        ("CORA", "2025-01-01", 100.0, time.time()),
        ("CORA", "2025-01-02", 102.0, time.time()),
        ("CORA", "2025-01-03", 101.0, time.time()),
        ("CORA", "2025-01-04", 104.0, time.time()),
        ("CORA", "2025-01-05", 103.0, time.time()),
    ])
    _seed_price("CORB", [
        ("CORB", "2025-01-01", 50.0, time.time()),
        ("CORB", "2025-01-02", 51.0, time.time()),
        ("CORB", "2025-01-03", 49.0, time.time()),
        ("CORB", "2025-01-04", 52.0, time.time()),
        ("CORB", "2025-01-05", 51.0, time.time()),
    ])
    monkeypatch.setattr(price_mod, "_is_price_fresh", lambda t: True)
    result = calculate_correlation(["CORA", "CORB"])
    assert "CORA" in result and "CORB" in result
    assert "correlation" in result.lower() or "vs" in result.lower()


def test_rank_tickers_returns_sorted_list():
    from tools.calc import rank_tickers
    _seed_income("RANKA", [("Sep 28, 2024", "Net sales", "Net sales", 500_000.0)])
    _seed_income("RANKB", [("Sep 28, 2024", "Net sales", "Net sales", 300_000.0)])
    _seed_income("RANKC", [("Sep 28, 2024", "Net sales", "Net sales", 700_000.0)])
    result = rank_tickers(["RANKA", "RANKB", "RANKC"], "revenue")
    assert "RANKC" in result
    assert "RANKA" in result
    assert result.index("RANKC") < result.index("RANKA") < result.index("RANKB")
