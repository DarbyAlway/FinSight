import re
import time

import duckdb
import matplotlib.pyplot as plt
from edgar import Company

from tools.config import DB_PATH
from tools.db import is_cache_fresh, load_from_cache, save_to_cache, fuzzy_query


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
