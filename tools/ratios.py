import logging

from tools.db import fuzzy_query, connect
from tools.schemas import MarginRow


def _parse_fiscal_year(fy: str):
    from datetime import datetime
    try:
        return datetime.strptime(fy, "%b %d, %Y")
    except ValueError:
        return datetime.min


def calculate_all_margins(ticker: str) -> str:
    revenue_rows = fuzzy_query(ticker, "revenue")
    gross_rows = fuzzy_query(ticker, "gross margin")
    net_rows = fuzzy_query(ticker, "net income")
    op_rows = fuzzy_query(ticker, "operating income")

    if not revenue_rows:
        return f"ERROR: No revenue data for {ticker} — call get_income_statement first."

    # Use max value for revenue (total revenue > sub-items like product revenue or cost of revenue)
    rev_by_year: dict[str, float] = {}
    for r in revenue_rows:
        fy = r["fiscal_year"]
        if r["value"] > rev_by_year.get(fy, 0):
            rev_by_year[fy] = r["value"]

    gross_by_year = {r["fiscal_year"]: r["value"] for r in gross_rows}

    # Use max absolute value for net income/loss (total > sub-items like noncontrolling interest)
    net_by_year: dict[str, float] = {}
    for r in net_rows:
        fy = r["fiscal_year"]
        if abs(r["value"]) > abs(net_by_year.get(fy, 0)):
            net_by_year[fy] = r["value"]

    op_by_year = {r["fiscal_year"]: r["value"] for r in op_rows}

    years = sorted(rev_by_year.keys(), key=_parse_fiscal_year, reverse=True)
    lines = [f"{ticker} Margins (SEC 10-K):"]
    lines.append(f"  {'Year':<14} {'Revenue':>12} {'Gross %':>9} {'Oper %':>9} {'Net %':>9}")
    lines.append("  " + "-" * 56)
    for fy in years:
        rev = rev_by_year[fy]
        if not rev:
            continue
        gross_pct = gross_by_year.get(fy, 0) / rev
        op_pct = op_by_year.get(fy, 0) / rev if fy in op_by_year else None
        net_pct = net_by_year.get(fy, 0) / rev if fy in net_by_year else None
        # Phase F guard: skip a year with impossible/inconsistent margins
        # (>100% gross, or operating margin above gross — a row mismatch).
        try:
            MarginRow(
                fiscal_year=fy, revenue=rev, gross_margin_pct=gross_pct,
                operating_margin_pct=op_pct, net_margin_pct=net_pct,
            )
        except Exception as e:
            logging.warning("ratios: skipping bad margin row %s %s: %s", ticker, fy, e)
            continue
        op_str = f"{op_pct:>8.1%}" if op_pct is not None else "     N/A"
        net_str = f"{net_pct:>8.1%}" if net_pct is not None else "     N/A"
        lines.append(f"  {fy:<14} ${rev:>10,.0f}M {gross_pct:>8.1%} {op_str} {net_str}")
    return "\n".join(lines)


def calculate_debt_to_equity(ticker: str) -> str:
    DEBT_PATTERNS = [
        "%long-term debt%",
        "%long term debt%",
        "%convertible%notes%",
        "%long-term borrowings%",
        "%notes payable%",
    ]
    EQUITY_PATTERNS = [
        "%total stockholders%equity%",
        "%total equity%",
        "%shareholders%equity%",
    ]

    with connect() as con:
        fy_row = con.execute(
            "SELECT fiscal_year FROM balance_sheets WHERE ticker = ? ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST LIMIT 1",
            (ticker,)
        ).fetchone()
        if not fy_row:
            return f"ERROR: No balance sheet data for {ticker} — call get_balance_sheet first."
        fy = fy_row[0]

        debt_items: list[tuple[str, float]] = []
        seen_items: set[str] = set()
        for pattern in DEBT_PATTERNS:
            rows = con.execute(
                "SELECT line_item, value FROM balance_sheets "
                "WHERE ticker = ? AND fiscal_year = ? AND lower(line_item) LIKE ?",
                (ticker, fy, pattern)
            ).fetchall()
            for item, val in rows:
                if item not in seen_items:
                    seen_items.add(item)
                    debt_items.append((item, val))

        equity_val = None
        for pattern in EQUITY_PATTERNS:
            row = con.execute(
                "SELECT value FROM balance_sheets "
                "WHERE ticker = ? AND fiscal_year = ? AND lower(line_item) LIKE ? LIMIT 1",
                (ticker, fy, pattern)
            ).fetchone()
            if row:
                equity_val = row[0]
                break

    if equity_val is None:
        return f"ERROR: Stockholders equity not found for {ticker} — call get_balance_sheet first."
    if equity_val == 0:
        return f"ERROR: Stockholders equity is zero for {ticker} — cannot compute D/E."

    debt_total = sum(v for _, v in debt_items)
    dte = debt_total / equity_val

    lines = [f"{ticker} Debt-to-Equity (SEC 10-K, {fy}):"]
    if debt_items:
        lines.append("  Long-term debt components:")
        for item, val in debt_items:
            lines.append(f"    {item}: ${val:,.0f}M")
    else:
        lines.append("  Long-term debt: $0M (none found)")
    lines.append(f"  Total long-term debt: ${debt_total:,.0f}M")
    lines.append(f"  Stockholders' equity: ${equity_val:,.0f}M")
    lines.append(f"  Debt-to-Equity: {dte:.3f}")
    return "\n".join(lines)


def calculate_roa_roe(ticker: str) -> str:
    net_rows = fuzzy_query(ticker, "net income")
    if not net_rows:
        return f"ERROR: No net income data for {ticker} — call get_income_statement first."

    # Use max absolute value (total net income/loss > sub-items like noncontrolling interest)
    net_by_year: dict[str, float] = {}
    for r in net_rows:
        fy = r["fiscal_year"]
        if abs(r["value"]) > abs(net_by_year.get(fy, 0)):
            net_by_year[fy] = r["value"]

    with connect() as con:
        asset_rows = con.execute(
            "SELECT fiscal_year, value FROM balance_sheets "
            "WHERE ticker = ? AND lower(line_item) LIKE '%total assets%'",
            (ticker,)
        ).fetchall()
        equity_rows = con.execute(
            "SELECT fiscal_year, value FROM balance_sheets "
            "WHERE ticker = ? AND (lower(line_item) LIKE '%total stockholders%equity%' "
            "OR lower(line_item) LIKE '%total equity%')",
            (ticker,)
        ).fetchall()

    if not asset_rows:
        return f"ERROR: No balance sheet data for {ticker} — call get_balance_sheet first."

    assets_by_year = {r[0]: r[1] for r in asset_rows}
    equity_by_year = {r[0]: r[1] for r in equity_rows}

    common_years = sorted(
        set(net_by_year.keys()) & set(assets_by_year.keys()),
        key=_parse_fiscal_year, reverse=True
    )
    if not common_years:
        return (
            f"ERROR: Income statement and balance sheet years don't overlap for {ticker}. "
            f"Income years: {list(net_by_year.keys())}. Balance sheet years: {list(assets_by_year.keys())}."
        )

    lines = [f"{ticker} ROA / ROE (SEC 10-K):"]
    lines.append(f"  {'Year':<14} {'Net Income':>12} {'Total Assets':>14} {'Equity':>12} {'ROA':>8} {'ROE':>8}")
    lines.append("  " + "-" * 72)
    for fy in common_years:
        net = net_by_year[fy]
        assets = assets_by_year[fy]
        equity = equity_by_year.get(fy)
        roa = net / assets if assets else None
        roe = net / equity if equity else None
        equity_str = f"${equity:,.0f}M" if equity is not None else "N/A"
        roa_str = f"{roa:.1%}" if roa is not None else "N/A"
        roe_str = f"{roe:.1%}" if roe is not None else "N/A"
        lines.append(
            f"  {fy:<14} ${net:>10,.0f}M ${assets:>12,.0f}M {equity_str:>12} {roa_str:>8} {roe_str:>8}"
        )
    return "\n".join(lines)


def calculate_current_ratio(ticker: str) -> str:
    with connect() as con:
        fy_row = con.execute(
            "SELECT fiscal_year FROM balance_sheets WHERE ticker = ? ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST LIMIT 1",
            (ticker,)
        ).fetchone()
        if not fy_row:
            return f"ERROR: No balance sheet data for {ticker} — call get_balance_sheet first."
        fy = fy_row[0]

        ca_row = con.execute(
            """SELECT value FROM balance_sheets
               WHERE ticker = ? AND fiscal_year = ?
               AND lower(line_item) LIKE '%total current assets%'
               LIMIT 1""",
            (ticker, fy)
        ).fetchone()
        cl_row = con.execute(
            """SELECT value FROM balance_sheets
               WHERE ticker = ? AND fiscal_year = ?
               AND lower(line_item) LIKE '%total current liabilities%'
               LIMIT 1""",
            (ticker, fy)
        ).fetchone()

    if not ca_row:
        return f"ERROR: Total current assets not found for {ticker} — call get_balance_sheet first."
    if not cl_row:
        return f"ERROR: Total current liabilities not found for {ticker} — call get_balance_sheet first."

    current_assets = ca_row[0]
    current_liabilities = cl_row[0]
    if current_liabilities == 0:
        return f"ERROR: Current liabilities is zero for {ticker} — cannot compute current ratio."

    ratio = current_assets / current_liabilities
    if ratio >= 1.5:
        health = "healthy"
    elif ratio >= 1.0:
        health = "adequate"
    else:
        health = "potential short-term liquidity risk"

    return (
        f"{ticker} Current Ratio (SEC 10-K, {fy}):\n"
        f"  Total current assets:      ${current_assets:,.0f}M\n"
        f"  Total current liabilities: ${current_liabilities:,.0f}M\n"
        f"  Current ratio: {ratio:.2f}  ({health}; > 1.5 = healthy, < 1.0 = liquidity risk)"
    )


def calculate_interest_coverage(ticker: str) -> str:
    ebit_rows = fuzzy_query(ticker, "operating income")
    if not ebit_rows:
        return f"ERROR: No operating income data for {ticker} — call get_income_statement first."

    with connect() as con:
        interest_rows = con.execute(
            """SELECT fiscal_year, value FROM income_statements
               WHERE ticker = ?
               AND lower(line_item) LIKE '%interest expense%'
               ORDER BY try_strptime(fiscal_year, '%b %d, %Y') DESC NULLS LAST LIMIT 2""",
            (ticker,)
        ).fetchall()

    if not interest_rows:
        return (
            f"ERROR: Interest expense not found for {ticker} "
            "— call get_income_statement first."
        )

    ebit_by_year: dict[str, float] = {}
    for r in ebit_rows:
        fy = r["fiscal_year"]
        if fy not in ebit_by_year:
            ebit_by_year[fy] = r["value"]

    interest_by_year = {r[0]: r[1] for r in interest_rows}
    common_years = sorted(
        set(ebit_by_year.keys()) & set(interest_by_year.keys()),
        key=_parse_fiscal_year, reverse=True
    )

    if not common_years:
        return (
            f"ERROR: No overlapping years between operating income and "
            f"interest expense for {ticker}."
        )

    lines = [f"{ticker} Interest Coverage (SEC 10-K):"]
    for fy in common_years:
        ebit = ebit_by_year[fy]
        interest = interest_by_year[fy]
        if interest == 0:
            lines.append(f"  {fy}: Interest expense = $0M (no debt servicing)")
            continue
        coverage = ebit / abs(interest)
        if coverage >= 3.0:
            health = "comfortable"
        elif coverage >= 1.5:
            health = "adequate"
        else:
            health = "potential solvency risk"
        lines.append(
            f"  {fy}: EBIT ${ebit:,.0f}M / Interest ${abs(interest):,.0f}M"
            f" = {coverage:.1f}x ({health})"
        )
    return "\n".join(lines)
