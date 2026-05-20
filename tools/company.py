import hashlib
import logging

import yfinance as yf

from tools.db import save_ticker_info, load_ticker_info, is_ticker_info_fresh, get_summary_hash
from tools.vector import upsert_company_profile, _get_qdrant


def fetch_and_cache_company(symbol: str) -> dict | None:
    try:
        info = yf.Ticker(symbol).info
        new_summary = info.get("longBusinessSummary", "")
        new_hash = hashlib.md5(new_summary.encode()).hexdigest()
        old_hash = get_summary_hash(symbol)
        save_ticker_info(symbol, info)
        if new_hash != old_hash and new_summary:
            upsert_company_profile(
                _get_qdrant(), symbol, new_summary,
                info.get("sector", ""), info.get("industry", "")
            )
        return info
    except Exception as e:
        logging.warning("fetch_and_cache_company failed for %s: %s", symbol, e)
        return None


def get_company_info(symbol: str) -> str:
    if not is_ticker_info_fresh(symbol):
        fetch_and_cache_company(symbol)
    info = load_ticker_info(symbol)
    if not info:
        return f"No company info found for {symbol}."
    lines = [
        f"{info.get('longName', symbol)} ({symbol})",
        f"Sector: {info.get('sector','')} | Industry: {info.get('industry','')}",
        f"Market Cap: ${info.get('marketCap',0):,.0f}",
        f"P/E (trailing): {info.get('trailingPE','N/A')} | Forward P/E: {info.get('forwardPE','N/A')}",
        f"Profit Margin: {info.get('profitMargins',0):.1%} | Gross Margin: {info.get('grossMargins',0):.1%}",
        f"Debt/Equity: {info.get('debtToEquity','N/A')} | Beta: {info.get('beta','N/A')}",
        f"Recommendation: {info.get('recommendationKey','N/A')} ({info.get('numberOfAnalystOpinions',0)} analysts)",
        f"\n{info.get('longBusinessSummary','')}",
    ]
    return "\n".join(lines)
