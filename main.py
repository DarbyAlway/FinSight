import hashlib
import json
import logging
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

import duckdb
import matplotlib.pyplot as plt
import ollama
import yfinance as yf
from edgar import Company, set_identity
from gnews import GNews
from qdrant_client import QdrantClient, models as qmodels

set_identity("yourname@email.com")

MODEL = "qwen2.5:14b"
DB_PATH = "cache.db"
CACHE_TTL_DAYS = 90
QDRANT_COLLECTION = "stock_news"
DENSE_MODEL = "BAAI/bge-small-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"
COMPANY_PROFILES_COLLECTION = "company_profiles"
TICKER_INFO_TTL_HOURS = 72

SYSTEM_PROMPT = (
    "You are a stock analysis assistant. "
    "You have four tools: get_income_statement (SEC 10-K financial data), "
    "get_stock_news (fetch and store recent headlines), "
    "search_news (hybrid semantic+keyword search over stored news), "
    "and compare_tickers (compare a financial metric across tickers with a chart). "
    "Use them when the user asks about stocks. "
    "Always cite key figures and mention which tool you used."
)

SYNONYMS = {
    "revenue":          ["%revenue%", "%net sales%", "%total sales%"],
    "net income":       ["%net income%", "%net earnings%", "%profit%"],
    "gross margin":     ["%gross margin%", "%gross profit%"],
    "r&d":              ["%research%", "%development%", "%technology and content%"],
    "operating income": ["%operating income%", "%income from operations%"],
    "cost of sales":    ["%cost of sales%", "%cost of revenue%", "%cost of goods%"],
    "eps":              ["%earnings per share%", "%diluted%"],
}


def init_db():
    with duckdb.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS income_statements (
                ticker      VARCHAR,
                fiscal_year VARCHAR,
                section     VARCHAR,
                line_item   VARCHAR,
                value       DOUBLE,
                fetched_at  DOUBLE,
                PRIMARY KEY (ticker, fiscal_year, section, line_item)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS ticker_info (
                symbol          VARCHAR PRIMARY KEY,
                sector          VARCHAR,
                industry        VARCHAR,
                summary         VARCHAR,
                summary_hash    VARCHAR,
                info_json       VARCHAR,
                cached_at       DOUBLE
            )
        """)


def is_cache_fresh(ticker: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT fetched_at FROM income_statements WHERE ticker = ? LIMIT 1",
            (ticker,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 86400 < CACHE_TTL_DAYS


def save_to_cache(rows: list[dict]):
    if not rows:
        return
    with duckdb.connect(DB_PATH) as con:
        con.executemany(
            """INSERT OR REPLACE INTO income_statements
               (ticker, fiscal_year, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["fiscal_year"], r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_from_cache(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT fiscal_year, section, line_item, value FROM income_statements "
            "WHERE ticker = ? ORDER BY fiscal_year DESC, section, line_item",
            (ticker,)
        ).fetchall()
    if not rows:
        return ""
    lines = [f"{ticker} Income Statement (cached)"]
    current_section = None
    for fiscal_year, section, line_item, value in rows:
        if section != current_section:
            lines.append(f"\n  {section}")
            current_section = section
        lines.append(f"    {line_item}: {value:,.0f}M  ({fiscal_year})")
    return "\n".join(lines)


def fuzzy_query(ticker: str, line_item: str) -> list[dict]:
    term = line_item.lower().strip()
    patterns = SYNONYMS.get(term, [f"%{term}%"])
    for pattern in patterns:
        with duckdb.connect(DB_PATH) as con:
            rows = con.execute(
                """SELECT fiscal_year, section, line_item, value
                   FROM income_statements
                   WHERE ticker = ?
                     AND (lower(section) LIKE ? OR lower(line_item) LIKE ?)
                   ORDER BY fiscal_year DESC""",
                (ticker, pattern, pattern),
            ).fetchall()
        if rows:
            return [
                {"fiscal_year": r[0], "section": r[1], "line_item": r[2], "value": r[3]}
                for r in rows
            ]
    return []


def save_ticker_info(symbol: str, info: dict):
    summary = info.get("longBusinessSummary", "")
    summary_hash = hashlib.md5(summary.encode()).hexdigest()
    with duckdb.connect(DB_PATH) as con:
        con.execute("""
            INSERT OR REPLACE INTO ticker_info
                (symbol, sector, industry, summary, summary_hash, info_json, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            info.get("sector", ""),
            info.get("industry", ""),
            summary,
            summary_hash,
            json.dumps(info),
            time.time(),
        ))


def load_ticker_info(symbol: str) -> dict | None:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT info_json FROM ticker_info WHERE symbol = ?", (symbol,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def is_ticker_info_fresh(symbol: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT cached_at FROM ticker_info WHERE symbol = ?", (symbol,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 3600 < TICKER_INFO_TTL_HOURS


def get_summary_hash(symbol: str) -> str | None:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT summary_hash FROM ticker_info WHERE symbol = ?", (symbol,)
        ).fetchone()
    return row[0] if row else None


def parse_income_statement(ticker: str, raw: str) -> list[dict]:
    rows = []
    now = time.time()

    year_re = re.compile(
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4})'
    )
    fiscal_years = []
    for line in raw.split('\n'):
        years = year_re.findall(line)
        if len(years) > len(fiscal_years):
            fiscal_years = years

    if not fiscal_years:
        return rows

    # edgar Company.get_financials().income_statement() returns plain indented text with $ values
    dollar_re = re.compile(r'\$(\([\d,]+\)|[\d,]+)')
    current_section = "General"

    for line in raw.split('\n'):
        stripped = line.strip()
        if not stripped or re.match(r'^[─━+=\-\s]+$', stripped):
            continue

        # Update section from header lines (e.g. "Net sales:") before checking values
        if stripped.endswith(':') and not dollar_re.search(line):
            current_section = stripped.rstrip(':').strip()
            continue

        matches = dollar_re.findall(line)
        if not matches:
            continue

        values = []
        for m in matches:
            if m.startswith('('):
                values.append(-float(m.strip('()').replace(',', '')))
            else:
                values.append(float(m.replace(',', '')))

        if len(values) != len(fiscal_years):
            continue

        label_part = line[:line.index('$')].strip()
        if not label_part:
            continue

        name = label_part.rstrip(':').strip()

        for i, year in enumerate(fiscal_years):
            rows.append({
                "ticker": ticker, "fiscal_year": year,
                "section": current_section, "line_item": name,
                "value": values[i], "fetched_at": now,
            })

    return rows


def get_income_statement(ticker: str) -> str:
    try:
        if is_cache_fresh(ticker):
            return load_from_cache(ticker)
        company = Company(ticker)
        financials = company.get_financials()
        raw = str(financials.income_statement())
        rows = parse_income_statement(ticker, raw)
        if rows:
            save_to_cache(rows)
            return load_from_cache(ticker)
        return raw
    except Exception as e:
        stale = load_from_cache(ticker)
        if stale:
            return f"[Stale cache] {stale}\n(Refresh failed: {e})"
        return f"Error fetching income statement for {ticker}: {e}"


def compare_tickers(tickers: list[str], line_item: str) -> str:
    if not tickers:
        return "No tickers provided."
    fetch_errors = []
    for ticker in tickers:
        if not is_cache_fresh(ticker):
            result = get_income_statement(ticker)
            if result.startswith("Error"):
                fetch_errors.append(f"{ticker}: {result}")

    results = {t: fuzzy_query(t, line_item) for t in tickers}
    all_years = sorted(
        {r["fiscal_year"] for rows in results.values() for r in rows},
        key=lambda y: time.strptime(y, "%b %d, %Y"),
        reverse=True
    )

    if not all_years:
        lines = [f"No match found for '{line_item}'. Available line items:"]
        for ticker in tickers:
            with duckdb.connect(DB_PATH) as con:
                items = [i[0] for i in con.execute(
                    "SELECT DISTINCT line_item FROM income_statements WHERE ticker = ?",
                    (ticker,)
                ).fetchall()]
            lines.append(f"  {ticker}: {', '.join(items[:10])}")
        return "\n".join(lines)

    x = range(len(all_years))
    width = 0.8 / len(tickers)
    fig, ax = plt.subplots(figsize=(10, 6))
    for i, ticker in enumerate(tickers):
        row_by_year = {r["fiscal_year"]: r["value"] for r in results.get(ticker, [])}
        vals = [row_by_year.get(y, 0) for y in all_years]
        offset = (i - len(tickers) / 2 + 0.5) * width
        ax.bar([xi + offset for xi in x], vals, width, label=ticker)

    matched_label = results[tickers[0]][0]["line_item"] if results.get(tickers[0]) else line_item
    ax.set_title(f"{matched_label}: {' vs '.join(tickers)}")
    ax.set_xlabel("Fiscal Year")
    ax.set_ylabel("Value (millions)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(all_years)
    ax.legend()
    plt.tight_layout()
    plt.show()

    summary = [f"Comparison: '{line_item}' — {', '.join(tickers)}\n"]
    for ticker in tickers:
        rows = results.get(ticker, [])
        if rows:
            vals_str = ", ".join(f"{r['fiscal_year']}: ${r['value']:,.0f}M" for r in rows)
            summary.append(f"  {ticker} (matched '{rows[0]['line_item']}'): {vals_str}")
        else:
            summary.append(f"  {ticker}: no match found")
    summary.append("Chart displayed.")
    if fetch_errors:
        summary.append("Fetch warnings: " + "; ".join(fetch_errors))
    return "\n".join(summary)


_dense_encoder = None
_sparse_encoder = None


def _get_encoders():
    global _dense_encoder, _sparse_encoder
    if _dense_encoder is None or _sparse_encoder is None:
        from fastembed import TextEmbedding, SparseTextEmbedding
        if _dense_encoder is None:
            _dense_encoder = TextEmbedding(DENSE_MODEL)
        if _sparse_encoder is None:
            _sparse_encoder = SparseTextEmbedding(SPARSE_MODEL)
    return _dense_encoder, _sparse_encoder


def init_qdrant() -> QdrantClient:
    client = QdrantClient("localhost", port=6333)
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config={
                "dense": qmodels.VectorParams(size=384, distance=qmodels.Distance.COSINE)
            },
            sparse_vectors_config={
                "sparse": qmodels.SparseVectorParams(
                    index=qmodels.SparseIndexParams(on_disk=False)
                )
            },
        )
    if COMPANY_PROFILES_COLLECTION not in existing:
        client.create_collection(
            collection_name=COMPANY_PROFILES_COLLECTION,
            vectors_config={
                "dense": qmodels.VectorParams(size=384, distance=qmodels.Distance.COSINE)
            },
        )
    return client


def store_articles(client: QdrantClient, articles: list[dict]):
    if not articles:
        return
    dense_enc, sparse_enc = _get_encoders()
    texts = [a["title"] for a in articles]
    dense_vecs = list(dense_enc.embed(texts))
    sparse_vecs = list(sparse_enc.embed(texts))
    points = []
    for i, article in enumerate(articles):
        point_id = int(hashlib.md5(f"{article.get('ticker','')}::{article['title']}".encode()).hexdigest(), 16) % (2 ** 63)
        points.append(
            qmodels.PointStruct(
                id=point_id,
                vector={
                    "dense": dense_vecs[i].tolist(),
                    "sparse": qmodels.SparseVector(
                        indices=sparse_vecs[i].indices.tolist(),
                        values=sparse_vecs[i].values.tolist(),
                    ),
                },
                payload={**article, "stored_at": time.time()},
            )
        )
    client.upsert(collection_name=QDRANT_COLLECTION, points=points)


def hybrid_search(client: QdrantClient, query: str, ticker: str = None, top_k: int = 10, cutoff: float = 0.0) -> list[dict]:
    try:
        dense_enc, sparse_enc = _get_encoders()
        q_dense = list(dense_enc.embed([query]))[0].tolist()
        q_sparse = list(sparse_enc.embed([query]))[0]

        must = []
        if ticker:
            must.append(qmodels.FieldCondition(key="ticker", match=qmodels.MatchValue(value=ticker)))
        if cutoff > 0:
            must.append(qmodels.FieldCondition(key="published_at", range=qmodels.Range(gte=cutoff)))
        payload_filter = qmodels.Filter(must=must) if must else None

        results = client.query_points(
            collection_name=QDRANT_COLLECTION,
            prefetch=[
                qmodels.Prefetch(query=q_dense, using="dense", limit=20),
                qmodels.Prefetch(
                    query=qmodels.SparseVector(
                        indices=q_sparse.indices.tolist(),
                        values=q_sparse.values.tolist(),
                    ),
                    using="sparse",
                    limit=20,
                ),
            ],
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            query_filter=payload_filter,
            limit=top_k,
        )
        return [r.payload for r in results.points]
    except Exception:
        return []


_qdrant_client = None


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = init_qdrant()
    return _qdrant_client


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


def upsert_company_profile(client: QdrantClient, symbol: str, summary: str, sector: str, industry: str):
    dense_enc, _ = _get_encoders()
    vec = list(dense_enc.embed([summary]))[0].tolist()
    point_id = int(hashlib.md5(symbol.encode()).hexdigest(), 16) % (2 ** 63)
    client.upsert(
        collection_name=COMPANY_PROFILES_COLLECTION,
        points=[qmodels.PointStruct(
            id=point_id,
            vector={"dense": vec},
            payload={"symbol": symbol, "sector": sector, "industry": industry, "summary": summary},
        )],
    )


def search_company_profiles(client: QdrantClient, query: str, top_k: int = 5) -> list[dict]:
    dense_enc, _ = _get_encoders()
    q_vec = list(dense_enc.embed([query]))[0].tolist()
    results = client.query_points(
        collection_name=COMPANY_PROFILES_COLLECTION,
        query=q_vec,
        using="dense",
        limit=top_k,
    )
    return [r.payload for r in results.points]


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


init_db()
