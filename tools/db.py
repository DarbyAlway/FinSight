import hashlib
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime

import duckdb

from tools.config import DB_PATH, CACHE_TTL_DAYS, TICKER_INFO_TTL_HOURS, SYNONYMS

QUARTERLY_TTL_DAYS = 7
EARNINGS_TTL_DAYS = 7

# DuckDB allows only one writer on the database file. Agents run in parallel
# (LangGraph dispatches Send-fanned agent nodes on worker threads); when two
# of them each open their own
# connection and one writes, the others crash with "Conflict on update" or
# "file being used by another process". Serializing every connection through
# this process-wide lock makes concurrent cache access safe. Cache ops are
# sub-50ms, so the serialization cost is negligible. Use connect() everywhere
# instead of duckdb.connect(DB_PATH) directly — including from other modules.
_DB_LOCK = threading.RLock()


@contextmanager
def connect():
    """Open a DuckDB connection to the shared cache under the process-wide lock."""
    with _DB_LOCK:
        con = duckdb.connect(DB_PATH)
        try:
            yield con
        finally:
            con.close()


def init_db():
    with connect() as con:
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
                quarter_label VARCHAR,
                section       VARCHAR,
                line_item     VARCHAR,
                value         DOUBLE,
                fetched_at    DOUBLE,
                PRIMARY KEY (ticker, period_end, section, line_item)
            )
        """)
        try:
            con.execute("ALTER TABLE quarterly_statements ADD COLUMN quarter_label VARCHAR DEFAULT ''")
        except Exception:
            pass  # column already exists
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
        con.execute("""
            CREATE TABLE IF NOT EXISTS earnings_releases (
                ticker            VARCHAR,
                period_end        VARCHAR,
                eps_actual        DOUBLE,
                eps_estimate      DOUBLE,
                revenue_actual    DOUBLE,
                revenue_estimate  DOUBLE,
                beat_miss         VARCHAR,
                guidance_text     VARCHAR,
                fetched_at        DOUBLE,
                PRIMARY KEY (ticker, period_end)
            )
        """)


def is_cache_fresh(ticker: str) -> bool:
    with connect() as con:
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
    with connect() as con:
        con.executemany(
            """INSERT OR REPLACE INTO income_statements
               (ticker, fiscal_year, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["fiscal_year"], r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_from_cache(ticker: str) -> str:
    with connect() as con:
        rows = con.execute(
            "SELECT fiscal_year, section, line_item, value FROM income_statements "
            "WHERE ticker = ? ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST, section, line_item",
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
    seen: set[tuple] = set()
    results: list[dict] = []
    for pattern in patterns:
        with connect() as con:
            rows = con.execute(
                """SELECT fiscal_year, section, line_item, value
                   FROM income_statements
                   WHERE ticker = ?
                     AND (lower(section) LIKE ? OR lower(line_item) LIKE ?)
                   ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST""",
                (ticker, pattern, pattern),
            ).fetchall()
        for r in rows:
            key = (r[0], r[2])  # (fiscal_year, line_item) — deduplicate
            if key not in seen:
                seen.add(key)
                results.append({"fiscal_year": r[0], "section": r[1], "line_item": r[2], "value": r[3]})
    return results


def save_ticker_info(symbol: str, info: dict):
    summary = info.get("longBusinessSummary", "")
    summary_hash = hashlib.md5(summary.encode()).hexdigest()
    with connect() as con:
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
    with connect() as con:
        row = con.execute(
            "SELECT info_json FROM ticker_info WHERE symbol = ?", (symbol,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def is_ticker_info_fresh(symbol: str) -> bool:
    with connect() as con:
        row = con.execute(
            "SELECT cached_at FROM ticker_info WHERE symbol = ?", (symbol,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 3600 < TICKER_INFO_TTL_HOURS


def get_summary_hash(symbol: str) -> str | None:
    with connect() as con:
        row = con.execute(
            "SELECT summary_hash FROM ticker_info WHERE symbol = ?", (symbol,)
        ).fetchone()
    return row[0] if row else None


def is_quarterly_cache_fresh(ticker: str) -> bool:
    with connect() as con:
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
    with connect() as con:
        con.executemany(
            """INSERT OR REPLACE INTO quarterly_statements
               (ticker, period_end, quarter_label, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["period_end"], r.get("quarter_label", ""), r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_quarterly_cache(ticker: str) -> str:
    with connect() as con:
        rows = con.execute(
            "SELECT period_end, quarter_label, section, line_item, value FROM quarterly_statements "
            "WHERE ticker = ? ORDER BY period_end DESC, section, line_item",
            (ticker,)
        ).fetchall()
    if not rows:
        return ""
    lines = [f"{ticker} Quarterly Income Statement (SEC 10-Q, single quarter only)"]
    current_period = None
    current_section = None
    for period_end, quarter_label, section, line_item, value in rows:
        if period_end != current_period:
            label_str = f" ({quarter_label} — fiscal)" if quarter_label else ""
            lines.append(f"\n  Period ending: {period_end}{label_str}")
            current_period = period_end
            current_section = None
        if section != current_section:
            lines.append(f"    {section}")
            current_section = section
        lines.append(f"      {line_item}: ${value:,.1f}M")
    return "\n".join(lines)


def is_balance_sheet_fresh(ticker: str) -> bool:
    with connect() as con:
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
    with connect() as con:
        con.executemany(
            """INSERT OR REPLACE INTO balance_sheets
               (ticker, fiscal_year, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["fiscal_year"], r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_balance_sheet(ticker: str) -> str:
    with connect() as con:
        rows = con.execute(
            "SELECT fiscal_year, section, line_item, value FROM balance_sheets "
            "WHERE ticker = ? ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST, section, line_item",
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
    with connect() as con:
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
    with connect() as con:
        con.executemany(
            """INSERT OR REPLACE INTO cash_flows
               (ticker, fiscal_year, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["fiscal_year"], r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_cash_flow(ticker: str) -> str:
    with connect() as con:
        rows = con.execute(
            """SELECT fiscal_year, section, line_item, value FROM cash_flows
               WHERE ticker = ?
               ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST,
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


def is_earnings_fresh(ticker: str) -> bool:
    with connect() as con:
        row = con.execute(
            "SELECT fetched_at FROM earnings_releases WHERE ticker = ? ORDER BY fetched_at DESC LIMIT 1",
            (ticker,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 86400 < EARNINGS_TTL_DAYS


def save_earnings(rows: list[dict]):
    if not rows:
        return
    with connect() as con:
        con.executemany(
            """INSERT OR REPLACE INTO earnings_releases
               (ticker, period_end, eps_actual, eps_estimate, revenue_actual,
                revenue_estimate, beat_miss, guidance_text, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["period_end"], r["eps_actual"], r["eps_estimate"],
              r.get("revenue_actual"), r.get("revenue_estimate"),
              r["beat_miss"], r.get("guidance_text"), r["fetched_at"]) for r in rows],
        )


def load_earnings(ticker: str) -> str:
    with connect() as con:
        # Grab the 4 most recent earnings releases we have saved for this ticker.
        rows = con.execute(
            """SELECT period_end, eps_actual, eps_estimate, beat_miss,
                      revenue_actual, guidance_text
               FROM earnings_releases
               WHERE ticker = ?
               ORDER BY period_end DESC
               LIMIT 4""",
            (ticker,)
        ).fetchall()
        # Fiscal quarter labels (e.g. NVDA's Jan-year-end) come from the SEC filing
        # itself via quarterly_statements.quarter_label — calendar-quarter math from
        # the period-end month is wrong for any company whose fiscal year isn't
        # calendar-aligned, so borrow the label edgartools already parsed instead
        # of recomputing it.
        fiscal_rows = con.execute(
            "SELECT DISTINCT period_end, quarter_label FROM quarterly_statements "
            "WHERE ticker = ? AND quarter_label != ''",
            (ticker,)
        ).fetchall()
    if not rows:
        return ""
    # Turn the (period_end, quarter_label) pairs into a dict so we can look up a label by date directly, e.g. fiscal_labels["2025-01-26"] -> "Q4 FY2025".
    fiscal_labels = dict(fiscal_rows)

    # The two tables don't always store dates in the same text format (one might say "2025-01-26", the other "Jan 26, 2025").
    # So this turns either style into a real date object we can compare and subtract.
    # Returns None if the string doesn't match either known format.
    def _parse_date(s: str):
        for fmt in ("%Y-%m-%d", "%b %d, %Y"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
        return None

    lines = [f"{ticker} Earnings (last {len(rows)} quarters)"]
    for period_end, eps_actual, eps_estimate, beat_miss, revenue_actual, guidance_text in rows:
        # First try an exact date match against the fiscal labels we loaded above.
        fiscal_label = fiscal_labels.get(period_end)
        target = _parse_date(period_end)
        # SEC filing dates and our saved earnings dates can be off by a few days (e.g. the filing date vs. the actual quarter-end date).
        # So if there was no exact match, look for a fiscal label within 10 days of this date instead of giving up.
        if fiscal_label is None and target is not None:
            for pe, ql in fiscal_labels.items():
                pe_dt = _parse_date(pe)
                if pe_dt is not None and abs((pe_dt - target).days) <= 10:
                    fiscal_label = ql
                    break
        date_str = target.strftime('%b %d, %Y') if target is not None else period_end
        # If we still don't have a fiscal label at this point, show the date plainly and mark it "unconfirmed" rather than guessing at a quarter name that might be wrong.
        label = f"{fiscal_label} ({date_str})" if fiscal_label else f"period ending {date_str} (fiscal quarter unconfirmed)"
        # How far actual EPS beat or missed the analyst estimate, as a percent.
        pct = ""
        if eps_estimate:
            pct = f" ({(eps_actual - eps_estimate) / abs(eps_estimate) * 100:+.1f}%)"
        lines.append(f"\n  {label}")
        eps_str = f"${eps_actual:.2f}" if eps_actual is not None else "N/A"
        est_str = f"${eps_estimate:.2f}" if eps_estimate is not None else "N/A"
        lines.append(f"    EPS: {eps_str} actual | {est_str} estimate | {beat_miss.upper()}{pct}")
        if revenue_actual:
            lines.append(f"    Revenue: ${revenue_actual:,.0f}M actual")
        if guidance_text:
            lines.append(f"    Guidance: \"{guidance_text}\"")
        else:
            lines.append("    Guidance: (not available)")
    return "\n".join(lines)
