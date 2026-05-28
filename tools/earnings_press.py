import logging
import re
import time

import yfinance as yf
from edgar import Company

from tools.db import is_earnings_fresh, save_earnings, load_earnings


_GUIDANCE_KEYWORDS = ["expect", "guidance", "outlook", "forecast", "anticipate", "project"]


def _parse_beat_miss(actual: float, estimate: float) -> str:
    if not estimate or estimate == 0:
        return "in-line"
    pct = (actual - estimate) / abs(estimate) * 100
    if pct > 2:
        return "beat"
    if pct < -2:
        return "miss"
    return "in-line"


def _extract_guidance_text(text: str) -> str | None:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    found = []
    for sentence in sentences:
        if any(kw in sentence.lower() for kw in _GUIDANCE_KEYWORDS):
            found.append(sentence.strip())
            if len(found) >= 2:
                break
    return " ".join(found) if found else None


def _fetch_yfinance_earnings(ticker: str) -> list[dict]:
    t = yf.Ticker(ticker)
    try:
        hist = t.earnings_history
    except Exception:
        hist = None

    if hist is None or (hasattr(hist, "empty") and hist.empty):
        return []

    rows = []
    now = time.time()
    for period_end, row in list(hist.iterrows())[:4]:
        eps_actual = float(row.get("epsActual") or 0)
        eps_estimate = float(row.get("epsEstimate") or 0)
        pe_str = str(period_end.date()) if hasattr(period_end, "date") else str(period_end)[:10]
        rows.append({
            "ticker": ticker,
            "period_end": pe_str,
            "eps_actual": eps_actual,
            "eps_estimate": eps_estimate,
            "revenue_actual": None,
            "revenue_estimate": None,
            "beat_miss": _parse_beat_miss(eps_actual, eps_estimate),
            "guidance_text": None,
            "fetched_at": now,
        })
    return rows


def _fetch_edgar_guidance(ticker: str) -> str | None:
    try:
        company = Company(ticker)
        filings = company.get_filings(form="8-K")
        if not filings:
            return None
        filing = filings[0]
        try:
            text = str(filing.document)
        except Exception:
            text = str(filing)
        return _extract_guidance_text(text)
    except Exception as e:
        logging.warning("_fetch_edgar_guidance failed for %s: %s", ticker, e)
        return None


def _fetch_next_earnings_date(ticker: str) -> str | None:
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return None
        # calendar may be a dict or DataFrame depending on yfinance version
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or cal.get("Earnings Dates")
            if dates and len(dates) > 0:
                return str(dates[0])[:10]
        return None
    except Exception:
        return None


def get_earnings_press_release(ticker: str) -> str:
    try:
        if is_earnings_fresh(ticker):
            logging.info("earnings cache hit: %s", ticker)
            base = load_earnings(ticker)
            next_date = _fetch_next_earnings_date(ticker)
            if next_date:
                return f"Next earnings: ~{next_date}\n{base}"
            return base

        rows = _fetch_yfinance_earnings(ticker)
        if not rows:
            return (
                f"TOOL_ERROR: No earnings history found for {ticker}. "
                "Do not use training data to answer — tell the user the data is unavailable."
            )

        guidance = _fetch_edgar_guidance(ticker)
        if guidance:
            rows[0]["guidance_text"] = guidance

        save_earnings(rows)
        base = load_earnings(ticker)
        next_date = _fetch_next_earnings_date(ticker)
        if next_date:
            return f"Next earnings: ~{next_date}\n{base}"
        return base
    except Exception as e:
        stale = load_earnings(ticker)
        if stale:
            return f"[Stale cache] {stale}\n(Refresh failed: {e})"
        return (
            f"TOOL_ERROR: Failed to fetch earnings data for {ticker}: {e}. "
            "Do not use training data to answer — tell the user the data is unavailable."
        )
