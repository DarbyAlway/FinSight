import time
import duckdb
from tools.db import init_db


def _seed_price(ticker, rows):
    from tools.price import DB_PATH
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
