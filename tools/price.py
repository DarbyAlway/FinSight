import time

import duckdb
import yfinance as yf

from tools.config import DB_PATH

PRICE_TTL_HOURS = 24


def _is_price_fresh(ticker: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT fetched_at FROM price_history WHERE ticker = ? LIMIT 1",
            (ticker,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 3600 < PRICE_TTL_HOURS


def _load_price_rows(ticker: str) -> list[tuple]:
    with duckdb.connect(DB_PATH) as con:
        return con.execute(
            "SELECT date, close FROM price_history WHERE ticker = ? ORDER BY date",
            (ticker,)
        ).fetchall()


def get_price_history(ticker: str, period: str = "1y", force: bool = False) -> str:
    if force or not _is_price_fresh(ticker):
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if hist.empty:
                return f"No price history found for {ticker}."
            now = time.time()
            rows = [
                (ticker, str(date.date()), float(close), now)
                for date, close in zip(hist.index, hist["Close"])
            ]
            with duckdb.connect(DB_PATH) as con:
                con.executemany(
                    "INSERT OR REPLACE INTO price_history "
                    "(ticker, date, close, fetched_at) VALUES (?, ?, ?, ?)",
                    rows,
                )
        except Exception as e:
            return f"Failed to fetch price history for {ticker}: {e}"

    rows = _load_price_rows(ticker)
    if not rows:
        return f"No price history cached for {ticker}."
    lines = [f"{ticker} Price History ({len(rows)} trading days cached):"]
    for date, close in rows[-10:]:
        lines.append(f"  {date}: ${close:.2f}")
    if len(rows) > 10:
        lines.append(f"  ... ({len(rows) - 10} earlier days not shown)")
    return "\n".join(lines)
