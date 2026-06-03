import logging
import re
import time

from edgar import Company

from tools.db import (
    is_cache_fresh, load_from_cache, save_to_cache,
    is_quarterly_cache_fresh, save_quarterly_cache, load_quarterly_cache,
)


def _unit_multiplier(raw: str) -> float:
    lower = raw.lower()
    # Match "(in thousands" only when the whole statement is in thousands.
    # Avoid false positive on "(in millions, except shares in thousands...)".
    if re.search(r'\(in thousands', lower):
        return 0.001
    if re.search(r'\(in billions', lower):
        return 1000.0
    return 1.0  # default: already in millions


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
    multiplier = _unit_multiplier(raw)
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
                "ticker": ticker, "fiscal_year": year,
                "section": current_section, "line_item": name,
                "value": values[i], "fetched_at": now,
            })

    return rows


def parse_quarterly_statement(ticker: str, raw: str, period_end: str) -> list[dict]:
    """Parse a 10-Q income statement, extracting only single-quarter columns."""
    rows = []
    now = time.time()
    date_re = re.compile(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4})')
    # Matches dates with explicit quarter labels: "Oct 31, 2025 (Q3)" or "(YTD)"
    date_label_re = re.compile(
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4})\s*\(([^)]+)\)'
    )
    dollar_re = re.compile(r'\$(\([\d,]+\)|[\d,]+)')
    lines = raw.split('\n')

    quarterly_dates = []
    ytd_count = 0

    # Method 1: detect edgartools labeled columns like "(Q3)" and "(YTD)"
    for line in lines:
        labeled = date_label_re.findall(line)
        if labeled:
            q_dates = [d for d, lbl in labeled if re.match(r'Q\d', lbl, re.I)]
            ytd_n = sum(1 for _, lbl in labeled if 'YTD' in lbl.upper())
            if q_dates:
                quarterly_dates = q_dates
                ytd_count = ytd_n
                break

    # Method 2: detect "Three Months Ended" / "Six/Nine Months Ended" text headers
    if not quarterly_dates:
        pending_period = None
        for line in lines:
            lower = line.lower()
            if 'three months' in lower:
                pending_period = 'quarterly'
            elif 'six months' in lower or 'nine months' in lower:
                pending_period = 'ytd'
            dates = date_re.findall(line)
            if not dates:
                continue
            if pending_period == 'quarterly' and not quarterly_dates:
                quarterly_dates = dates
                pending_period = None
            elif pending_period == 'ytd' and ytd_count == 0:
                ytd_count = len(dates)
                pending_period = None

    # Method 3: fallback — use all dates from densest header line
    if not quarterly_dates:
        best = []
        for line in lines:
            found = date_re.findall(line)
            if len(found) > len(best):
                best = found
        quarterly_dates = best

    if not quarterly_dates:
        return rows

    total_cols = len(quarterly_dates) + ytd_count
    multiplier = _unit_multiplier(raw)
    current_section = "General"

    for line in lines:
        stripped = line.strip()
        if not stripped or re.match(r'^[─━+=\-\s]+$', stripped):
            continue
        if stripped.endswith(':') and not dollar_re.search(line):
            current_section = stripped.rstrip(':').strip()
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

        if len(values) not in (len(quarterly_dates), total_cols):
            continue

        label_part = line[:line.index('$')].strip()
        if not label_part:
            continue
        name = label_part.rstrip(':').strip()

        for i, date in enumerate(quarterly_dates):
            rows.append({
                "ticker": ticker, "period_end": date,
                "section": current_section, "line_item": name,
                "value": values[i], "fetched_at": now,
            })

    return rows


def get_quarterly_statement(ticker: str) -> str:
    try:
        if is_quarterly_cache_fresh(ticker):
            logging.info("quarterly cache hit: %s", ticker)
            return load_quarterly_cache(ticker)
        company = Company(ticker)
        filings = company.get_filings(form="10-Q")
        if not filings:
            return f"No 10-Q filings found for {ticker}."
        rows = []
        for filing in list(filings)[:4]:
            try:
                tenq = filing.obj()
                raw = str(tenq.financials.income_statement())
                period_end = str(filing.period_of_report)
                rows.extend(parse_quarterly_statement(ticker, raw, period_end))
            except Exception as e:
                logging.warning("10-Q parse failed for %s (%s): %s", ticker, filing.period_of_report, e)
        if rows:
            save_quarterly_cache(rows)
            return load_quarterly_cache(ticker)
        return f"TOOL_ERROR: No quarterly data could be parsed for {ticker}. Do not use training data to answer — tell the user the data is unavailable."
    except Exception as e:
        stale = load_quarterly_cache(ticker)
        if stale:
            return f"[Stale cache] {stale}\n(Refresh failed: {e})"
        return f"TOOL_ERROR: Failed to fetch quarterly statement for {ticker}: {e}. Do not use training data to answer — tell the user the data is unavailable."


def get_income_statement(ticker: str) -> str:
    try:
        if is_cache_fresh(ticker):
            logging.info("cache hit: %s", ticker)
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


