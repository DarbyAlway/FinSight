import logging
import re
import time

from edgar import Company

from tools.db import is_cash_flow_fresh, save_cash_flow, load_cash_flow


def _unit_multiplier(raw: str) -> float:
    lower = raw.lower()
    if 'in thousands' in lower:
        return 0.001
    if 'in billions' in lower:
        return 1000.0
    return 1.0


def parse_cash_flow(ticker: str, raw: str) -> list[dict]:
    rows = []
    now = time.time()

    year_re = re.compile(
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4})'
    )
    fiscal_years = []
    for line in raw.split('\n'):
        # Skip period-range labels like "Jun 29, 2024 to Jun 28, 2025": they list
        # dates ascending and tie the real (descending) column header on 2-column
        # statements, which would swap every value onto the wrong fiscal year.
        if ' to ' in line:
            continue
        years = year_re.findall(line)
        if len(years) > len(fiscal_years):
            fiscal_years = years

    if not fiscal_years:
        return rows

    dollar_re = re.compile(r'\$(\([\d,]+\)|[\d,]+)')
    multiplier = _unit_multiplier(raw)
    current_section = "General"

    for line in raw.split('\n'):
        stripped = line.strip()
        if not stripped or re.match(r'^[─━+=\-\s•]+$', stripped):
            continue
        if stripped.lower().startswith('source:'):
            continue

        lower_stripped = stripped.lower()
        if 'operating activities' in lower_stripped:
            current_section = "Operating Activities"
        elif 'investing activities' in lower_stripped:
            current_section = "Investing Activities"
        elif 'financing activities' in lower_stripped:
            current_section = "Financing Activities"

        if not dollar_re.search(line):
            continue

        matches = dollar_re.findall(line)
        if not matches:
            continue

        values = []
        for m in matches:
            if m.startswith('('):
                values.append(-float(m.strip('()').replace(',', '')) * multiplier)
            else:
                values.append(float(m.replace(',', '')) * multiplier)

        if len(values) != len(fiscal_years):
            continue

        label_part = line[:line.index('$')].strip()
        if not label_part:
            continue
        name = label_part.rstrip(':').strip()

        for i, year in enumerate(fiscal_years):
            rows.append({
                "ticker": ticker,
                "fiscal_year": year,
                "section": current_section,
                "line_item": name,
                "value": values[i],
                "fetched_at": now,
            })

    return rows


def get_cash_flow_statement(ticker: str) -> str:
    try:
        if is_cash_flow_fresh(ticker):
            logging.info("cash flow cache hit: %s", ticker)
            return load_cash_flow(ticker)
        company = Company(ticker)
        financials = company.get_financials()
        raw = str(financials.cash_flow_statement())
        rows = parse_cash_flow(ticker, raw)
        if rows:
            save_cash_flow(rows)
            return load_cash_flow(ticker)
        return raw
    except Exception as e:
        stale = load_cash_flow(ticker)
        if stale:
            return f"[Stale cache] {stale}\n(Refresh failed: {e})"
        return (
            f"TOOL_ERROR: Failed to fetch cash flow statement for {ticker}: {e}. "
            "Do not use training data to answer — tell the user the data is unavailable."
        )
