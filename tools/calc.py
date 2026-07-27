import logging
from datetime import datetime

from tools.db import fuzzy_query, load_ticker_info, connect
from tools.schemas import MarginRow


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
    # Keep only the last N+1 years of data, since CAGR only needs a start point and an end point — everything in between is ignored.
    series = series[-max(years + 1, 2):]
    start_date, start_val = series[0]
    end_date, end_val = series[-1]
    if start_val <= 0:
        return f"ERROR: Invalid start revenue for {ticker}."
    # CAGR (Compound Annual Growth Rate) answers "what single steady yearly growth rate, applied every year, would turn start_val into end_val over this many years?"
    # The formula is (end/start) raised to the power of (1 / number of years), minus 1.
    # Using the exact number of days between the two dates (instead of just counting calendar years) keeps this accurate even when the years aren't exactly 365 days apart.
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

    # Use the max value per year for revenue — total revenue > sub-items like
    # "Cost of revenue", which also matches the %revenue% synonym. Without this
    # the denominator could be a sub-item, yielding impossible >100% margins
    # (MSFT showed 220.8%). Mirrors calculate_all_margins.
    rev_by_year: dict[str, float] = {}
    for r in revenue_rows:
        fy = r["fiscal_year"]
        if r["value"] > rev_by_year.get(fy, 0):
            rev_by_year[fy] = r["value"]
    gross_by_year = {r["fiscal_year"]: r["value"] for r in gross_rows}
    # Max absolute value per year (total net income/loss > sub-items).
    net_by_year: dict[str, float] = {}
    for r in net_rows:
        fy = r["fiscal_year"]
        if abs(r["value"]) > abs(net_by_year.get(fy, 0)):
            net_by_year[fy] = r["value"]

    years = sorted(rev_by_year.keys(), key=_parse_fiscal_year, reverse=True)
    lines = [f"{ticker} Margin Trend:"]
    lines.append(f"  {'Year':<14} {'Revenue':>12} {'Gross %':>9} {'Net %':>9}")
    lines.append("  " + "-" * 46)
    for fy in years:
        rev = rev_by_year[fy]
        gross_pct = gross_by_year.get(fy, 0) / rev if rev else 0
        net_pct = net_by_year.get(fy, 0) / rev if rev else 0
        # Phase F guard: drop a year whose margins are impossible (e.g. a >100%
        # gross margin from a bad denominator) rather than print garbage.
        try:
            MarginRow(
                fiscal_year=fy, revenue=rev,
                gross_margin_pct=gross_pct if fy in gross_by_year else None,
                net_margin_pct=net_pct if fy in net_by_year else None,
            )
        except Exception as e:
            logging.warning("calc: skipping bad margin row %s %s: %s", ticker, fy, e)
            continue
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
    # Same CAGR-style formula as calculate_revenue_cagr above, but applied to net income instead of revenue.
    # This gives an annualised earnings growth rate as a percentage (e.g. 15.0 means "15% per year").
    n_years = (
        (_parse_fiscal_year(years[-1]) - _parse_fiscal_year(years[0])).days / 365.25
    )
    eps_growth_rate = ((end_val / start_val) ** (1 / n_years) - 1) * 100
    if eps_growth_rate <= 0:
        return f"{ticker} PEG: N/A (negative EPS growth rate: {eps_growth_rate:.1f}%)"
    # PEG = P/E divided by the growth rate.
    # It's a way of asking "is this stock's price expensive relative to how fast its earnings are growing?"
    # PEG < 1 is the common rule-of-thumb for "cheap relative to growth".
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
    terminal_growth = 0.03
    # The terminal-value formula below divides by (discount_rate - terminal_growth).
    # If discount_rate is equal to terminal_growth that's a division by zero (crash).
    # If it's LOWER, the result is a large negative number that looks like a valid answer but is actually nonsense.
    # Catch both cases here before doing any work.
    if discount_rate <= terminal_growth:
        return (
            f"ERROR: discount_rate ({discount_rate:.1%}) must be greater than "
            f"the assumed terminal growth rate ({terminal_growth:.1%}) for a "
            "DCF to be valid."
        )
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

    # DCF (Discounted Cash Flow) estimates what a company is worth TODAY by projecting its future cash flows and converting each one back to today's dollars.
    # A dollar next year is worth less than a dollar today, so we "discount" it — divide by (1 + discount_rate) raised to how many years away it is.
    pv_total = 0.0
    # Project 5 years of cash flow, growing each year by growth_rate, and add up the discounted ("present value") version of each year.
    for t in range(1, 6):
        fcf_t = base_fcf * (1 + growth_rate) ** t
        pv_total += fcf_t / (1 + discount_rate) ** t
    # The company doesn't stop existing after year 5, so "terminal value" estimates all cash flow from year 6 onward as one lump sum, assuming slower permanent growth (terminal_growth).
    # It then discounts that lump sum back to today the same way.
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


def calculate_free_cash_flow(ticker: str) -> str:
    with connect() as con:
        op_rows = con.execute(
            """SELECT fiscal_year, value FROM cash_flows
               WHERE ticker = ?
               AND (lower(line_item) LIKE '%operating activities%'
                    OR lower(line_item) LIKE '%cash from operations%')
               ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST LIMIT 2""",
            (ticker,)
        ).fetchall()
        if not op_rows:
            return (
                f"ERROR: No operating cash flow data for {ticker} "
                "— call get_cash_flow_statement first."
            )
        capex_rows = con.execute(
            """SELECT fiscal_year, value FROM cash_flows
               WHERE ticker = ?
               AND section = 'Investing Activities'
               AND (lower(line_item) LIKE '%capital expenditure%'
                    OR lower(line_item) LIKE '%purchases of property%'
                    OR lower(line_item) LIKE '%acquisition of property%'
                    OR lower(line_item) LIKE '%payments for property%')
               ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST LIMIT 2""",
            (ticker,)
        ).fetchall()

    op_by_year = {r[0]: r[1] for r in op_rows}
    capex_by_year = {r[0]: r[1] for r in capex_rows}
    years = sorted(op_by_year.keys(), key=_parse_fiscal_year, reverse=True)

    lines = [f"{ticker} Free Cash Flow (SEC 10-K):"]
    for fy in years:
        op_cf = op_by_year[fy]
        capex = capex_by_year.get(fy, 0)  # stored negative for outflows
        fcf = op_cf + capex
        capex_label = f"${abs(capex):,.0f}M capex" if capex != 0 else "capex not found"
        lines.append(
            f"  {fy}: OpCF ${op_cf:,.0f}M − {capex_label} = FCF ${fcf:,.0f}M"
        )
    return "\n".join(lines)


def calculate_cash_runway(ticker: str) -> str:
    with connect() as con:
        cash_rows = con.execute(
            """SELECT fiscal_year, value FROM balance_sheets
               WHERE ticker = ?
               AND lower(line_item) LIKE '%cash and cash equivalents%'
               ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST LIMIT 1""",
            (ticker,)
        ).fetchall()
        if not cash_rows:
            return (
                f"ERROR: No cash balance data for {ticker} "
                "— call get_balance_sheet and get_cash_flow_statement first."
            )
        op_rows = con.execute(
            """SELECT fiscal_year, value FROM cash_flows
               WHERE ticker = ?
               AND (lower(line_item) LIKE '%operating activities%'
                    OR lower(line_item) LIKE '%cash from operations%')
               ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST LIMIT 2""",
            (ticker,)
        ).fetchall()
        if not op_rows:
            return (
                f"ERROR: No operating cash flow data for {ticker} "
                "— call get_cash_flow_statement first."
            )
        capex_rows = con.execute(
            """SELECT fiscal_year, value FROM cash_flows
               WHERE ticker = ?
               AND section = 'Investing Activities'
               AND (lower(line_item) LIKE '%capital expenditure%'
                    OR lower(line_item) LIKE '%purchases of property%'
                    OR lower(line_item) LIKE '%acquisition of property%'
                    OR lower(line_item) LIKE '%payments for property%')
               ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST LIMIT 2""",
            (ticker,)
        ).fetchall()

    cash_balance_fy, cash_balance = cash_rows[0]
    op_by_year = {r[0]: r[1] for r in op_rows}
    capex_by_year = {r[0]: r[1] for r in capex_rows}
    years = sorted(op_by_year.keys(), key=_parse_fiscal_year, reverse=True)
    fcf_by_year = {fy: op_by_year[fy] + capex_by_year.get(fy, 0) for fy in years}

    latest_fy = years[0]
    latest_fcf = fcf_by_year[latest_fy]

    lines = [
        f"{ticker} Cash Runway:",
        f"  Cash & equivalents ({cash_balance_fy}): ${cash_balance:,.0f}M",
        f"  Latest FCF ({latest_fy}): ${latest_fcf:,.0f}M",
    ]

    if latest_fcf >= 0:
        lines.append("  Runway: N/A (FCF positive — company is cash-generative)")
        return "\n".join(lines)

    # "Runway" = how many months the company can keep operating before it runs out of cash, if it keeps burning cash at the current yearly rate.
    # cash_balance / annual_burn gives years of runway, so multiply by 12 to express it in months instead.
    annual_burn = abs(latest_fcf)
    runway_months = (cash_balance / annual_burn) * 12

    if len(years) > 1:
        prev_fcf = fcf_by_year[years[1]]
        if prev_fcf != 0 and abs(latest_fcf - prev_fcf) / abs(prev_fcf) > 0.3:
            lines.append(
                f"  Note: Burn rate changed >30% YoY ({prev_fcf:,.0f}M → {latest_fcf:,.0f}M)"
            )

    lines.append(f"  Estimated runway: {runway_months:.1f} months")
    return "\n".join(lines)


SECTOR_PEERS: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK"],
    "Financial Services": ["JPM", "BAC", "WFC", "GS", "MS"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "T"],
    "Industrials": ["HON", "UPS", "CAT", "BA", "GE"],
    "Consumer Defensive": ["WMT", "PG", "KO", "PEP", "COST"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Utilities": ["NEE", "DUK", "SO", "AEP", "EXC"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA"],
    "Basic Materials": ["LIN", "APD", "ECL", "SHW", "FCX"],
}


def _pick_valuation_multiple(info: dict) -> tuple[str, float, str] | None:
    """Best available valuation multiple, in preference order: trailing P/E,
    then forward P/E, then P/S. Returns (field, value, label), or None if all
    are missing/non-positive. Unprofitable growth names (e.g. RBRK, CRWD) have
    an N/A trailing P/E but a usable forward P/E or P/S already in the cache."""
    for field, label in (
        ("trailingPE", "trailing P/E"),
        ("forwardPE", "forward P/E"),
        ("priceToSalesTrailing12Months", "P/S"),
    ):
        v = info.get(field)
        if isinstance(v, (int, float)) and v > 0:
            return field, float(v), label
    return None


def calculate_pe_vs_sector(ticker: str) -> str:
    info = load_ticker_info(ticker)
    if not info:
        return f"ERROR: No company info for {ticker} — call get_company_info first."
    picked = _pick_valuation_multiple(info)
    if not picked:
        return f"ERROR: No trailing P/E, forward P/E, or P/S available for {ticker}."
    field, value, label = picked
    sector = info.get("sector", "")
    # Compare peers on the SAME multiple so the comparison is apples-to-apples.
    note = ""
    if field != "trailingPE":
        note = (f"  Note: {ticker} has no trailing P/E (negligible/negative TTM "
                f"earnings); comparing on {label} instead.")
    peers = [t for t in SECTOR_PEERS.get(sector, []) if t != ticker][:5]
    if not peers:
        out = f"{ticker} {label}: {value:.1f} | Sector: {sector}"
        if note:
            out += "\n" + note
        return out + f"\n  No peer benchmark available for sector '{sector}'."
    peer_vals: list[float] = []
    lines = [f"{ticker} {label} vs {sector} Sector Peers:"]
    if note:
        lines.append(note)
    lines.append(f"  {ticker}: {value:.1f} (subject)")
    for peer in peers:
        peer_info = load_ticker_info(peer)
        if not peer_info:
            from tools.company import fetch_and_cache_company
            peer_info = fetch_and_cache_company(peer) or {}
        peer_val = peer_info.get(field)
        if isinstance(peer_val, (int, float)) and peer_val > 0:
            peer_vals.append(peer_val)
            lines.append(f"  {peer}: {peer_val:.1f}")
    if peer_vals:
        avg = sum(peer_vals) / len(peer_vals)
        diff = value - avg
        lines.append(f"  Peer avg {label}: {avg:.1f}  |  {ticker} is {diff:+.1f} vs peers")
    return "\n".join(lines)


def calculate_correlation(tickers: list[str], period: str = "1y") -> str:
    import pandas as pd
    from tools.price import get_price_history

    for ticker in tickers:
        get_price_history(ticker, period, force=True)

    frames: dict[str, pd.Series] = {}
    for ticker in tickers:
        with connect() as con:
            rows = con.execute(
                "SELECT date, close FROM price_history WHERE ticker = ? ORDER BY date",
                (ticker,)
            ).fetchall()
        if rows:
            dates, closes = zip(*rows)
            frames[ticker] = pd.Series(list(closes), index=list(dates), dtype=float)

    if len(frames) < 2:
        return f"ERROR: Need at least 2 tickers with price data. Got: {list(frames.keys())}"

    # Build one table (a pandas DataFrame) with a column of closing prices per ticker, aligned by date.
    # pct_change() turns each price into "percent change from the previous day" (daily returns), since comparing raw prices would be misleading — two stocks can move together in percentage terms while having very different price levels.
    # corr() then computes, for every pair of tickers, how closely their daily returns move together: +1 = always move the same direction, -1 = always opposite, 0 = unrelated.
    df = pd.DataFrame(frames).dropna()
    returns = df.pct_change().dropna()
    corr = returns.corr()

    lines = [f"Price Return Correlation ({period}):"]
    for i, t1 in enumerate(tickers):
        for t2 in tickers[i + 1:]:
            if t1 in corr.columns and t2 in corr.columns:
                val = corr.loc[t1, t2]
                label = (
                    "strongly positive" if val > 0.7
                    else "weakly positive" if val > 0.3
                    else "neutral" if val > -0.3
                    else "weakly negative" if val > -0.7
                    else "strongly negative"
                )
                lines.append(f"  {t1} vs {t2}: {val:.3f} ({label})")
    return "\n".join(lines)


def rank_tickers(tickers: list[str], metric: str) -> str:
    scores: list[tuple[str, float]] = []
    for ticker in tickers:
        rows = fuzzy_query(ticker, metric)
        if rows:
            by_year = {}
            for r in rows:
                fy = r["fiscal_year"]
                if fy not in by_year:
                    by_year[fy] = r["value"]
            latest_fy = max(by_year.keys(), key=_parse_fiscal_year)
            scores.append((ticker, by_year[latest_fy]))
        else:
            info = load_ticker_info(ticker)
            if info:
                val = info.get(metric)
                if val and isinstance(val, (int, float)):
                    scores.append((ticker, val))

    if not scores:
        return f"ERROR: No data for metric '{metric}' for any of {tickers}."

    scores.sort(key=lambda x: x[1], reverse=True)
    lines = [f"Ticker Ranking by {metric} (highest first):"]
    for rank, (ticker, val) in enumerate(scores, 1):
        lines.append(f"  {rank}. {ticker}: ${val:,.0f}M")
    return "\n".join(lines)
