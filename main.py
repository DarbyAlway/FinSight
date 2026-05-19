import hashlib
import json
import re
import time

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


init_db()
