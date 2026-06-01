import hashlib
import logging
from datetime import datetime

import yfinance as yf

from tools.db import save_ticker_info, load_ticker_info, is_ticker_info_fresh, get_summary_hash
from tools.vector import upsert_company_profile, _get_qdrant


def fetch_and_cache_company(symbol: str) -> dict | None:
    try:
        import time
        info = yf.Ticker(symbol).info # get info from "yahoo finance" we need to change to "edgar" instead
        info["_cached_at"] = time.time()
        new_summary = info.get("longBusinessSummary", "") # store the summarize business in here
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
    if not is_ticker_info_fresh(symbol): # check that the symbol are in cache database or not
        fetch_and_cache_company(symbol)
    info = load_ticker_info(symbol)
    if not info:
        return f"No company info found for {symbol}."
    cached_at = info.get("_cached_at")
    as_of = datetime.fromtimestamp(cached_at).strftime("%Y-%m-%d %H:%M") if cached_at else "unknown"
    market_cap = info.get('marketCap', 0) or 0
    market_cap_str = f"${market_cap/1e12:.2f}T" if market_cap >= 1e12 else f"${market_cap/1e9:.1f}B"

    raw_yield = info.get('dividendYield') or 0
    # yfinance returns dividendYield as a decimal fraction (0.0073 = 0.73%)
    # but some versions return it already multiplied (0.73 = 0.73%) — cap sanity check
    div_yield_pct = raw_yield if raw_yield > 1 else raw_yield * 100
    div_yield_str = f"{div_yield_pct:.2f}%" if raw_yield else "N/A"

    lines = [
        f"{info.get('longName', symbol)} ({symbol})",
        f"Data as of: {as_of} (cached)",
        f"Sector: {info.get('sector','')} | Industry: {info.get('industry','')}",
        f"Market Cap: {market_cap_str}  [as of {as_of}]",
        f"P/E trailing: {info.get('trailingPE','N/A')} | Forward P/E: {info.get('forwardPE','N/A')}",
        f"Beta: {info.get('beta','N/A')} | Current Price: ${info.get('currentPrice','N/A')}",
        f"Dividend Yield: {div_yield_str}",
        f"Recommendation: {info.get('recommendationKey','N/A')} ({info.get('numberOfAnalystOpinions',0)} analysts)",
        f"Price Targets: mean ${info.get('targetMeanPrice','N/A')} | high ${info.get('targetHighPrice','N/A')} | low ${info.get('targetLowPrice','N/A')}",
        f"P/S (TTM): {info.get('priceToSalesTrailing12Months','N/A')} | P/B: {info.get('priceToBook','N/A')}",
        f"Note: For margins and D/E, use the ratios agent tools (SEC-sourced, more accurate than yfinance).",
        f"\n{info.get('longBusinessSummary','')}",
    ]
    return "\n".join(lines)
