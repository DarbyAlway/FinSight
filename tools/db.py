import hashlib
import json
import time

import duckdb

from tools.config import DB_PATH, CACHE_TTL_DAYS, TICKER_INFO_TTL_HOURS, SYNONYMS

QUARTERLY_TTL_DAYS = 7


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
            CREATE TABLE IF NOT EXISTS quarterly_statements (
                ticker        VARCHAR,
                period_end    VARCHAR,
                section       VARCHAR,
                line_item     VARCHAR,
                value         DOUBLE,
                fetched_at    DOUBLE,
                PRIMARY KEY (ticker, period_end, section, line_item)
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
        con.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                ticker     VARCHAR,
                date       VARCHAR,
                close      DOUBLE,
                fetched_at DOUBLE,
                PRIMARY KEY (ticker, date)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS balance_sheets (
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
            CREATE TABLE IF NOT EXISTS cash_flows (
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


def is_quarterly_cache_fresh(ticker: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT fetched_at FROM quarterly_statements WHERE ticker = ? ORDER BY fetched_at DESC LIMIT 1",
            (ticker,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 86400 < QUARTERLY_TTL_DAYS


def save_quarterly_cache(rows: list[dict]):
    if not rows:
        return
    with duckdb.connect(DB_PATH) as con:
        con.executemany(
            """INSERT OR REPLACE INTO quarterly_statements
               (ticker, period_end, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["period_end"], r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_quarterly_cache(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT period_end, section, line_item, value FROM quarterly_statements "
            "WHERE ticker = ? ORDER BY period_end DESC, section, line_item",
            (ticker,)
        ).fetchall()
    if not rows:
        return ""
    lines = [f"{ticker} Quarterly Income Statement (cached)"]
    current_period = None
    current_section = None
    for period_end, section, line_item, value in rows:
        if period_end != current_period:
            lines.append(f"\n  Period ending: {period_end}")
            current_period = period_end
            current_section = None
        if section != current_section:
            lines.append(f"    {section}")
            current_section = section
        lines.append(f"      {line_item}: ${value:,.1f}M")
    return "\n".join(lines)


def is_balance_sheet_fresh(ticker: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT fetched_at FROM balance_sheets WHERE ticker = ? LIMIT 1",
            (ticker,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 86400 < CACHE_TTL_DAYS


def save_balance_sheet(rows: list[dict]):
    if not rows:
        return
    with duckdb.connect(DB_PATH) as con:
        con.executemany(
            """INSERT OR REPLACE INTO balance_sheets
               (ticker, fiscal_year, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["fiscal_year"], r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_balance_sheet(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT fiscal_year, section, line_item, value FROM balance_sheets "
            "WHERE ticker = ? ORDER BY fiscal_year DESC, section, line_item",
            (ticker,)
        ).fetchall()
    if not rows:
        return ""
    lines = [f"{ticker} Balance Sheet (SEC 10-K, cached)"]
    current_fy = None
    current_section = None
    for fiscal_year, section, line_item, value in rows:
        if fiscal_year != current_fy:
            lines.append(f"\n  {fiscal_year}")
            current_fy = fiscal_year
            current_section = None
        if section != current_section:
            lines.append(f"    {section}")
            current_section = section
        lines.append(f"      {line_item}: ${value:,.0f}M")
    return "\n".join(lines)


def is_cash_flow_fresh(ticker: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT fetched_at FROM cash_flows WHERE ticker = ? LIMIT 1",
            (ticker,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 86400 < CACHE_TTL_DAYS


def save_cash_flow(rows: list[dict]):
    if not rows:
        return
    with duckdb.connect(DB_PATH) as con:
        con.executemany(
            """INSERT OR REPLACE INTO cash_flows
               (ticker, fiscal_year, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["fiscal_year"], r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_cash_flow(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        rows = con.execute(
            """SELECT fiscal_year, section, line_item, value FROM cash_flows
               WHERE ticker = ?
               ORDER BY fiscal_year DESC,
                        CASE section
                            WHEN 'Operating Activities' THEN 1
                            WHEN 'Investing Activities' THEN 2
                            WHEN 'Financing Activities' THEN 3
                            ELSE 4
                        END,
                        line_item""",
            (ticker,)
        ).fetchall()
    if not rows:
        return ""
    lines = [f"{ticker} Cash Flow Statement (SEC 10-K, cached)"]
    current_fy = None
    current_section = None
    for fiscal_year, section, line_item, value in rows:
        if fiscal_year != current_fy:
            lines.append(f"\n  {fiscal_year}")
            current_fy = fiscal_year
            current_section = None
        if section != current_section:
            lines.append(f"    {section}")
            current_section = section
        lines.append(f"      {line_item}: ${value:,.0f}M")
    return "\n".join(lines)
