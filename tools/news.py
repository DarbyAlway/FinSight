import logging
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

import yfinance as yf
from gnews import GNews

from tools.vector import store_articles, hybrid_search, _get_qdrant


def _parse_iso(date_str: str) -> float:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()


def _parse_rfc2822(date_str: str) -> float:
    try:
        return parsedate_to_datetime(date_str).timestamp()
    except Exception:
        return time.time()


def get_stock_news(ticker: str, max_results: int = 10) -> str:
    headlines = []
    seen_titles = set()
    articles_to_store = []

    try:
        yf_ticker = yf.Ticker(ticker)
        for article in (yf_ticker.news or [])[:max_results]:
            content = article.get("content", {})
            title = content.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                publisher = content.get("provider", {}).get("displayName", "Yahoo Finance")
                link = content.get("canonicalUrl", {}).get("url", "")
                published_at = _parse_iso(content["pubDate"]) if content.get("pubDate") else time.time()
                age_days = (time.time() - published_at) / 86400
                headlines.append(f"- [{publisher}] {title} ({age_days:.1f}d ago) {link}")
                articles_to_store.append({
                    "ticker": ticker, "title": title, "publisher": publisher,
                    "link": link, "source": "yfinance", "published_at": published_at,
                })
    except Exception as e:
        logging.warning("yfinance fetch failed for %s: %s", ticker, e)

    try:
        gn = GNews(max_results=max_results)
        for article in gn.get_news(ticker):
            title = article.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                publisher = article.get("publisher", {}).get("title", "Google News")
                link = article.get("url", "")
                raw_date = article.get("published date", "")
                published_at = _parse_rfc2822(raw_date) if raw_date else time.time()
                age_days = (time.time() - published_at) / 86400
                headlines.append(f"- [{publisher}] {title} ({age_days:.1f}d ago) {link}")
                articles_to_store.append({
                    "ticker": ticker, "title": title, "publisher": publisher,
                    "link": link, "source": "gnews", "published_at": published_at,
                })
    except Exception as e:
        logging.warning("gnews fetch failed for %s: %s", ticker, e)

    try:
        store_articles(_get_qdrant(), articles_to_store)
    except Exception as e:
        logging.warning("Qdrant store failed for %s: %s", ticker, e)

    if not headlines:
        return f"No news found for {ticker}."
    displayed = headlines[:max_results]
    return f"Recent news for {ticker} ({len(displayed)} articles):\n" + "\n".join(displayed)


def search_news(query: str, ticker: str = None, top_k: int = 10, days_back: int = 30) -> str:
    try:
        cutoff = time.time() - days_back * 86400
        results = hybrid_search(_get_qdrant(), query, ticker=ticker, top_k=top_k, cutoff=cutoff)
        if not results:
            return f"No news matched '{query}' in the last {days_back} days."
        scope = f" for {ticker}" if ticker else ""
        lines = [f"Hybrid search results{scope} — '{query}' (last {days_back} days):"]
        for r in results:
            published_at = r.get("published_at", 0)
            age_days = (time.time() - published_at) / 86400 if published_at else 0
            lines.append(f"- [{r.get('publisher','')}] {r.get('title','')} ({age_days:.1f}d ago) {r.get('link','')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"
