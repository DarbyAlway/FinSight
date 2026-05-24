from datetime import datetime

import duckdb

from tools.config import DB_PATH
from tools.db import fuzzy_query, load_ticker_info


def _parse_fiscal_year(fy: str) -> datetime:
    try:
        return datetime.strptime(fy, "%b %d, %Y")
    except ValueError:
        return datetime.min


def _get_revenue_by_year(ticker: str) -> list[tuple[datetime, float]]:
    rows = fuzzy_query(ticker, "revenue")
    if not rows:
        return []
    by_year: dict[str, float] = {}
    for r in rows:
        fy = r["fiscal_year"]
        if fy not in by_year:
            by_year[fy] = r["value"]
    return sorted(
        [(_parse_fiscal_year(fy), val) for fy, val in by_year.items()],
        key=lambda x: x[0]
    )


def calculate_revenue_cagr(ticker: str, years: int = 3) -> str:
    series = _get_revenue_by_year(ticker)
    if len(series) < 2:
        return f"ERROR: No revenue data found for {ticker} — call get_income_statement first."
    series = series[-max(years + 1, 2):]
    start_date, start_val = series[0]
    end_date, end_val = series[-1]
    if start_val <= 0:
        return f"ERROR: Invalid start revenue for {ticker}."
    actual_years = (end_date - start_date).days / 365.25
    if actual_years <= 0:
        return f"ERROR: Insufficient date range for {ticker} CAGR."
    cagr = (end_val / start_val) ** (1 / actual_years) - 1
    return (
        f"{ticker} Revenue CAGR ({start_date.strftime('%Y')} → {end_date.strftime('%Y')}):\n"
        f"  Start: ${start_val:,.0f}M  |  End: ${end_val:,.0f}M\n"
        f"  CAGR: {cagr:.1%} over {actual_years:.1f} years"
    )


def calculate_margin_trend(ticker: str) -> str:
    revenue_rows = fuzzy_query(ticker, "revenue")
    gross_rows = fuzzy_query(ticker, "gross margin")
    net_rows = fuzzy_query(ticker, "net income")

    if not revenue_rows:
        return f"ERROR: No revenue data for {ticker} — call get_income_statement first."

    rev_by_year = {r["fiscal_year"]: r["value"] for r in revenue_rows}
    gross_by_year = {r["fiscal_year"]: r["value"] for r in gross_rows}
    net_by_year = {r["fiscal_year"]: r["value"] for r in net_rows}

    years = sorted(rev_by_year.keys(), key=_parse_fiscal_year, reverse=True)
    lines = [f"{ticker} Margin Trend:"]
    lines.append(f"  {'Year':<14} {'Revenue':>12} {'Gross %':>9} {'Net %':>9}")
    lines.append("  " + "-" * 46)
    for fy in years:
        rev = rev_by_year[fy]
        gross_pct = gross_by_year.get(fy, 0) / rev if rev else 0
        net_pct = net_by_year.get(fy, 0) / rev if rev else 0
        lines.append(f"  {fy:<14} ${rev:>10,.0f}M {gross_pct:>8.1%} {net_pct:>8.1%}")
    return "\n".join(lines)


def calculate_yoy(ticker: str, metric: str) -> str:
    rows = fuzzy_query(ticker, metric)
    if not rows:
        return f"ERROR: No data for '{metric}' for {ticker} — call get_income_statement first."
    by_year = {}
    for r in rows:
        fy = r["fiscal_year"]
        if fy not in by_year:
            by_year[fy] = r["value"]
    years = sorted(by_year.keys(), key=_parse_fiscal_year)
    if len(years) < 2:
        return f"ERROR: Need at least 2 years of data for {ticker} YoY — only {len(years)} found."
    lines = [f"{ticker} {metric} YoY Change:"]
    for i in range(1, len(years)):
        prev_fy, curr_fy = years[i - 1], years[i]
        prev_val, curr_val = by_year[prev_fy], by_year[curr_fy]
        if prev_val != 0:
            change = (curr_val - prev_val) / abs(prev_val)
            lines.append(f"  {prev_fy} → {curr_fy}: ${curr_val:,.0f}M ({change:+.1%})")
        else:
            lines.append(f"  {prev_fy} → {curr_fy}: ${curr_val:,.0f}M (prev was 0)")
    return "\n".join(lines)


def calculate_peg(ticker: str) -> str:
    info = load_ticker_info(ticker)
    if not info:
        return f"ERROR: No company info for {ticker} — call get_company_info first."
    pe = info.get("trailingPE")
    if not pe or not isinstance(pe, (int, float)):
        return f"ERROR: P/E ratio unavailable for {ticker}."

    net_rows = fuzzy_query(ticker, "net income")
    if len(net_rows) < 2:
        return f"ERROR: Need at least 2 years of net income for {ticker} EPS growth."
    by_year = {}
    for r in net_rows:
        fy = r["fiscal_year"]
        if fy not in by_year:
            by_year[fy] = r["value"]
    years = sorted(by_year.keys(), key=_parse_fiscal_year)
    start_val, end_val = by_year[years[0]], by_year[years[-1]]
    if start_val <= 0:
        return f"ERROR: Invalid net income start value for {ticker}."
    n_years = (
        (_parse_fiscal_year(years[-1]) - _parse_fiscal_year(years[0])).days / 365.25
    )
    eps_growth_rate = ((end_val / start_val) ** (1 / n_years) - 1) * 100
    if eps_growth_rate <= 0:
        return f"{ticker} PEG: N/A (negative EPS growth rate: {eps_growth_rate:.1f}%)"
    peg = pe / eps_growth_rate
    return (
        f"{ticker} PEG Ratio:\n"
        f"  Trailing P/E: {pe:.1f}\n"
        f"  EPS Growth Rate (annualised): {eps_growth_rate:.1f}%\n"
        f"  PEG = {peg:.2f}  (< 1 suggests undervalued relative to growth)"
    )


def calculate_dcf(
    ticker: str, growth_rate: float = 0.10, discount_rate: float = 0.10
) -> str:
    op_rows = fuzzy_query(ticker, "operating income")
    if not op_rows:
        return f"ERROR: No operating income data for {ticker} — call get_income_statement first."

    by_year = {}
    for r in op_rows:
        fy = r["fiscal_year"]
        if fy not in by_year:
            by_year[fy] = r["value"]
    latest_fy = max(by_year.keys(), key=_parse_fiscal_year)
    base_fcf = by_year[latest_fy] * 1_000_000  # millions → dollars

    terminal_growth = 0.03
    pv_total = 0.0
    for t in range(1, 6):
        fcf_t = base_fcf * (1 + growth_rate) ** t
        pv_total += fcf_t / (1 + discount_rate) ** t
    fcf_5 = base_fcf * (1 + growth_rate) ** 5
    terminal_value = fcf_5 * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_total += terminal_value / (1 + discount_rate) ** 5

    info = load_ticker_info(ticker)
    shares = info.get("sharesOutstanding") if info else None
    current_price = info.get("currentPrice") if info else None

    lines = [
        f"{ticker} DCF Valuation (5-year, operating income as FCF proxy):",
        f"  Base FCF ({latest_fy}): ${base_fcf / 1e9:.2f}B",
        f"  Assumed growth rate: {growth_rate:.0%} | Discount rate: {discount_rate:.0%}",
        f"  Terminal growth: 3%",
        f"  PV of cash flows + terminal value: ${pv_total / 1e9:.2f}B",
    ]
    if shares and shares > 0:
        iv_per_share = pv_total / shares
        lines.append(f"  Intrinsic value per share: ${iv_per_share:.2f}")
        if current_price:
            upside = (iv_per_share - current_price) / current_price
            lines.append(f"  Current price: ${current_price:.2f}  |  Upside/Downside: {upside:+.1%}")
    else:
        lines.append("  Intrinsic value per share: N/A (shares outstanding unavailable)")
    lines.append("  Note: Uses operating income as FCF proxy. Treat as directional estimate only.")
    return "\n".join(lines)
