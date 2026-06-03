import logging
import re
import time

from edgar import Company

from tools.db import is_balance_sheet_fresh, save_balance_sheet, load_balance_sheet


def _unit_multiplier(raw: str) -> float:
    lower = raw.lower()
    if re.search(r'\(in thousands', lower):
        return 0.001
    if re.search(r'\(in billions', lower):
        return 1000.0
    return 1.0


def parse_balance_sheet(ticker: str, raw: str) -> list[dict]:
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

    dollar_re = re.compile(r'\$(\([\d,]+\)|[\d,]+)')
    multiplier = _unit_multiplier(raw)
    current_section = "General"

    for line in raw.split('\n'):
        stripped = line.strip()
        if not stripped or re.match(r'^[─━+=\-\s•]+$', stripped):
            continue
        if stripped.lower().startswith('source:'):
            continue

        if not dollar_re.search(line):
            if stripped.endswith(':'):
                current_section = stripped.rstrip(':').strip()
            elif not any(c.isdigit() for c in stripped):
                current_section = stripped.strip()
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


def get_balance_sheet(ticker: str) -> str:
    try:
        if is_balance_sheet_fresh(ticker):
            logging.info("balance sheet cache hit: %s", ticker)
            return load_balance_sheet(ticker)
        company = Company(ticker)
        financials = company.get_financials()
        raw = str(financials.balance_sheet())
        rows = parse_balance_sheet(ticker, raw)
        if rows:
            save_balance_sheet(rows)
            return load_balance_sheet(ticker)
        return raw
    except Exception as e:
        stale = load_balance_sheet(ticker)
        if stale:
            return f"[Stale cache] {stale}\n(Refresh failed: {e})"
        return f"TOOL_ERROR: Failed to fetch balance sheet for {ticker}: {e}. Do not use training data to answer — tell the user the data is unavailable."
