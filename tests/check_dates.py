"""
Run this to verify that yfinance and gnews return parseable publish dates.
Usage: python check_dates.py
"""
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import yfinance as yf
from gnews import GNews

TICKER = "AAPL"


def parse_gnews_date(date_str: str) -> float | None:
    """Parse RFC 2822 date string from gnews to Unix timestamp."""
    try:
        return parsedate_to_datetime(date_str).timestamp()
    except Exception:
        return None


print("=" * 60)
print(f"Checking publish date fields for: {TICKER}")
print("=" * 60)

# --- yfinance ---
print("\n[yfinance]")
ticker = yf.Ticker(TICKER)
articles = ticker.news or []

if not articles:
    print("  No articles returned.")
else:
    print(f"  Full structure of article[0]:")
    import json as _json
    print(_json.dumps(articles[0], indent=4, default=str))
    print()
    for i, article in enumerate(articles[:3]):
        # Try old field first, then nested content
        raw = article.get("providerPublishTime")
        content = article.get("content", {})
        title = article.get("title") or content.get("title", "(no title)")

        if raw is None:
            # Try nested content fields
            raw = (
                content.get("pubDate")
                or content.get("publishedAt")
                or content.get("displayTime")
                or content.get("providerPublishTime")
            )

        # Also extract the correct title/publisher/link from new API structure
        title = content.get("title", "(no title)")
        publisher = content.get("provider", {}).get("displayName", "Yahoo Finance")
        link = content.get("canonicalUrl", {}).get("url", "")

        if raw is None:
            print(f"  Article {i+1}: MISSING date — content keys: {list(content.keys())}")
        else:
            try:
                if isinstance(raw, (int, float)):
                    ts = float(raw)
                else:
                    # ISO 8601: "2026-05-19T17:45:00Z"
                    ts = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                age_days = (time.time() - ts) / 86400
                print(f"  Article {i+1}: OK")
                print(f"    title    : {title[:60]}")
                print(f"    publisher: {publisher}")
                print(f"    link     : {link[:60]}")
                print(f"    raw date : {raw!r}")
                print(f"    parsed   : {dt.strftime('%Y-%m-%d %H:%M UTC')}")
                print(f"    age      : {age_days:.1f} days")
            except Exception as e:
                print(f"  Article {i+1}: PARSE FAILED — raw: {raw!r}, error: {e}")

# --- gnews ---
print("\n[gnews]")
gn = GNews(max_results=3)
gnews_articles = gn.get_news(TICKER)

if not gnews_articles:
    print("  No articles returned.")
else:
    for i, article in enumerate(gnews_articles[:3]):
        raw = article.get("published date")
        title = article.get("title", "(no title)")
        if raw is None:
            print(f"  Article {i+1}: MISSING 'published date' — keys: {list(article.keys())}")
        else:
            ts = parse_gnews_date(raw)
            if ts is None:
                print(f"  Article {i+1}: PARSE FAILED — raw value: {raw!r}")
            else:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                age_days = (time.time() - ts) / 86400
                print(f"  Article {i+1}: OK")
                print(f"    title    : {title[:60]}")
                print(f"    raw value: {raw!r}")
                print(f"    parsed   : {dt.strftime('%Y-%m-%d %H:%M UTC')}")
                print(f"    age      : {age_days:.1f} days")

print("\n" + "=" * 60)
print("If all articles show OK, both sources are ready.")
print("If any show MISSING or PARSE FAILED, the field name changed")
print("and needs to be updated in main.py before storing to Qdrant.")
print("=" * 60)
