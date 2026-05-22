# Multi-Agent Stock Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the single-agent stock assistant into an orchestrator + 3 specialized sub-agents (FinancialsAgent, NewsAgent, CalcAgent) and add 8 new calculation tools covering valuation ratios, growth metrics, and portfolio analysis.

**Architecture:** Orchestrator makes two LLM calls per turn (plan → synthesize), calling up to 3 sub-agents sequentially and passing accumulated context forward. Each sub-agent sees only its own tool subset. Orchestrator answers directly (`agents: []`) for conversational questions without calling any sub-agent.

**Tech Stack:** Python, Ollama (qwen3:14b), DuckDB, yfinance, pandas (transitive dep of yfinance), pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `tools/config.py` | Modify | Add `MODEL` constant |
| `tools/db.py` | Modify | Add `price_history` table to `init_db` |
| `tools/price.py` | Create | `get_price_history` — yfinance history fetch, cached 24h in DuckDB |
| `tools/calc.py` | Create | 8 calc tools: CAGR, margin trend, YoY, PEG, DCF, sector P/E, correlation, rank |
| `agents/__init__.py` | Create | Package marker |
| `agents/financials.py` | Create | FinancialsAgent — income, quarterly, company_info tools |
| `agents/news.py` | Create | NewsAgent — get_stock_news, search_news tools |
| `agents/calc.py` | Create | CalcAgent — all calc tools + get_price_history |
| `orchestrator.py` | Create | Plan call, agent sequencing, context accumulation, synthesis |
| `main.py` | Modify | Wire orchestrator; keep re-exports for test_tools.py compatibility |
| `tests/conftest.py` | Create | pytest failure-logging hook |
| `tests/failure_log.jsonl` | Create | Persistent failure log (committed to git) |
| `tests/test_calc.py` | Create | Unit tests for tools/price.py and tools/calc.py |
| `tests/test_agents.py` | Create | Tests that each agent routes to correct tools |
| `tests/test_orchestrator.py` | Create | Plan parsing, agent sequencing, direct-answer, fallback |

---

## Task 1: Scaffold

**Files:**
- Modify: `tools/config.py`
- Modify: `tools/db.py`
- Create: `agents/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/failure_log.jsonl`
- Modify: `requirements.txt`

- [ ] **Step 1: Add MODEL to config and pandas to requirements**

In `tools/config.py`, append after the last line:
```python
MODEL = "qwen3:14b"
```

In `requirements.txt`, append:
```
pandas
numpy
```

- [ ] **Step 2: Add price_history table to init_db**

In `tools/db.py`, inside `init_db()`, after the `ticker_info` CREATE TABLE block add:
```python
        con.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                ticker     VARCHAR,
                date       VARCHAR,
                close      DOUBLE,
                fetched_at DOUBLE,
                PRIMARY KEY (ticker, date)
            )
        """)
```

- [ ] **Step 3: Create agents package**

Create `agents/__init__.py` — empty file.

- [ ] **Step 4: Create tests/conftest.py**

```python
import json
import os
from datetime import datetime


def pytest_runtest_logreport(report):
    if report.when == "call" and report.failed:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "test": report.nodeid,
            "error": str(report.longrepr),
        }
        log_path = os.path.join(os.path.dirname(__file__), "failure_log.jsonl")
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
```

- [ ] **Step 5: Create tests/failure_log.jsonl**

Create an empty file at `tests/failure_log.jsonl`.

- [ ] **Step 6: Verify init_db creates the new table**

Run: `conda run -n stock pytest tests/test_tools.py::test_init_db_creates_table -v`

Expected: PASS (existing test still passes with the new table added)

- [ ] **Step 7: Commit**

```bash
git add tools/config.py tools/db.py agents/__init__.py tests/conftest.py tests/failure_log.jsonl requirements.txt
git commit -m "feat: scaffold multi-agent — MODEL constant, price_history table, agents package, test failure logging"
```

---

## Task 2: tools/price.py — price history fetch

**Files:**
- Create: `tools/price.py`
- Create: `tests/test_calc.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_calc.py`:
```python
import time
import duckdb
from tools.db import init_db


def _seed_price(ticker, rows):
    from tools.price import DB_PATH
    init_db()
    with duckdb.connect(DB_PATH) as con:
        con.executemany(
            "INSERT OR REPLACE INTO price_history (ticker, date, close, fetched_at) VALUES (?, ?, ?, ?)",
            rows,
        )


def test_get_price_history_loads_from_cache():
    import tools.price as price_mod
    _seed_price("FAKEPRICE", [
        ("FAKEPRICE", "2025-01-01", 150.0, time.time()),
        ("FAKEPRICE", "2025-01-02", 152.0, time.time()),
        ("FAKEPRICE", "2025-01-03", 148.0, time.time()),
    ])
    result = price_mod.get_price_history("FAKEPRICE")
    assert isinstance(result, str)
    assert "FAKEPRICE" in result
    assert "150" in result or "152" in result or "148" in result


def test_get_price_history_returns_error_for_missing_ticker(monkeypatch):
    import tools.price as price_mod
    import yfinance as yf

    class FakeHistory:
        empty = True

    class FakeTicker:
        def history(self, period):
            return FakeHistory()

    monkeypatch.setattr(yf, "Ticker", lambda t: FakeTicker())
    result = price_mod.get_price_history("ZZZFAKE999")
    assert "No price history" in result or "Failed" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stock pytest tests/test_calc.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.price'`

- [ ] **Step 3: Implement tools/price.py**

Create `tools/price.py`:
```python
import time

import duckdb
import yfinance as yf

from tools.config import DB_PATH

PRICE_TTL_HOURS = 24


def _is_price_fresh(ticker: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT fetched_at FROM price_history WHERE ticker = ? LIMIT 1",
            (ticker,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 3600 < PRICE_TTL_HOURS


def _load_price_rows(ticker: str) -> list[tuple]:
    with duckdb.connect(DB_PATH) as con:
        return con.execute(
            "SELECT date, close FROM price_history WHERE ticker = ? ORDER BY date",
            (ticker,)
        ).fetchall()


def get_price_history(ticker: str, period: str = "1y") -> str:
    if not _is_price_fresh(ticker):
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if hist.empty:
                return f"No price history found for {ticker}."
            now = time.time()
            rows = [
                (ticker, str(date.date()), float(close), now)
                for date, close in zip(hist.index, hist["Close"])
            ]
            with duckdb.connect(DB_PATH) as con:
                con.executemany(
                    "INSERT OR REPLACE INTO price_history "
                    "(ticker, date, close, fetched_at) VALUES (?, ?, ?, ?)",
                    rows,
                )
        except Exception as e:
            return f"Failed to fetch price history for {ticker}: {e}"

    rows = _load_price_rows(ticker)
    if not rows:
        return f"No price history cached for {ticker}."
    lines = [f"{ticker} Price History ({len(rows)} trading days cached):"]
    for date, close in rows[-10:]:
        lines.append(f"  {date}: ${close:.2f}")
    if len(rows) > 10:
        lines.append(f"  ... ({len(rows) - 10} earlier days not shown)")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stock pytest tests/test_calc.py -v`

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/price.py tests/test_calc.py
git commit -m "feat: price history fetch with 24h DuckDB cache (TDD)"
```

---

## Task 3: tools/calc.py — growth metrics

**Files:**
- Create: `tools/calc.py`
- Modify: `tests/test_calc.py`

These three tools load data from the `income_statements` table via `fuzzy_query` and compute. No live network calls.

- [ ] **Step 1: Seed fixture income data and write failing tests**

Add to `tests/test_calc.py`:
```python
from tools.db import save_to_cache


def _seed_income(ticker, rows):
    init_db()
    save_to_cache([
        {"ticker": ticker, "fiscal_year": fy, "section": section,
         "line_item": line_item, "value": value, "fetched_at": time.time()}
        for fy, section, line_item, value in rows
    ])


def test_calculate_revenue_cagr_returns_percentage():
    from tools.calc import calculate_revenue_cagr
    _seed_income("CAGRCO", [
        ("Sep 28, 2024", "Net sales", "Net sales", 400_000.0),
        ("Sep 30, 2023", "Net sales", "Net sales", 370_000.0),
        ("Sep 24, 2022", "Net sales", "Net sales", 340_000.0),
    ])
    result = calculate_revenue_cagr("CAGRCO", years=2)
    assert isinstance(result, str)
    assert "CAGRCO" in result
    assert "%" in result


def test_calculate_revenue_cagr_missing_data():
    from tools.calc import calculate_revenue_cagr
    result = calculate_revenue_cagr("ZZZNOCAGR")
    assert "ERROR" in result or "No revenue data" in result


def test_calculate_margin_trend_returns_table():
    from tools.calc import calculate_margin_trend
    _seed_income("MARGCO", [
        ("Sep 28, 2024", "Net sales", "Net sales", 400_000.0),
        ("Sep 28, 2024", "Gross margin", "Gross margin", 160_000.0),
        ("Sep 28, 2024", "Net income", "Net income", 80_000.0),
        ("Sep 30, 2023", "Net sales", "Net sales", 370_000.0),
        ("Sep 30, 2023", "Gross margin", "Gross margin", 140_000.0),
        ("Sep 30, 2023", "Net income", "Net income", 70_000.0),
    ])
    result = calculate_margin_trend("MARGCO")
    assert "MARGCO" in result
    assert "gross" in result.lower() or "margin" in result.lower()


def test_calculate_yoy_returns_change():
    from tools.calc import calculate_yoy
    _seed_income("YOYCO", [
        ("Sep 28, 2024", "Net sales", "Net sales", 400_000.0),
        ("Sep 30, 2023", "Net sales", "Net sales", 370_000.0),
    ])
    result = calculate_yoy("YOYCO", "revenue")
    assert "YOYCO" in result
    assert "%" in result


def test_calculate_yoy_missing_data():
    from tools.calc import calculate_yoy
    result = calculate_yoy("ZZZNO", "revenue")
    assert "ERROR" in result or "No data" in result
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n stock pytest tests/test_calc.py::test_calculate_revenue_cagr_returns_percentage tests/test_calc.py::test_calculate_margin_trend_returns_table tests/test_calc.py::test_calculate_yoy_returns_change -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.calc'`

- [ ] **Step 3: Implement growth metric tools**

Create `tools/calc.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stock pytest tests/test_calc.py -v -k "cagr or margin or yoy"`

Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/calc.py tests/test_calc.py
git commit -m "feat: growth metric tools — revenue CAGR, margin trend, YoY (TDD)"
```

---

## Task 4: tools/calc.py — valuation ratios (PEG, DCF)

**Files:**
- Modify: `tools/calc.py`
- Modify: `tests/test_calc.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_calc.py`:
```python
from tools.db import save_ticker_info


def test_calculate_peg_returns_ratio():
    from tools.calc import calculate_peg
    _seed_income("PEGCO", [
        ("Sep 28, 2024", "Net income", "Net income", 100_000.0),
        ("Sep 30, 2023", "Net income", "Net income", 80_000.0),
        ("Sep 24, 2022", "Net income", "Net income", 64_000.0),
    ])
    save_ticker_info("PEGCO", {
        "trailingPE": 25.0,
        "sector": "Technology",
        "longBusinessSummary": "A fake company.",
    })
    result = calculate_peg("PEGCO")
    assert "PEGCO" in result
    assert "PEG" in result


def test_calculate_peg_missing_pe():
    from tools.calc import calculate_peg
    save_ticker_info("NOPECO", {
        "sector": "Technology",
        "longBusinessSummary": "No PE company.",
    })
    result = calculate_peg("NOPECO")
    assert "ERROR" in result or "N/A" in result or "unavailable" in result.lower()


def test_calculate_dcf_returns_intrinsic_value():
    from tools.calc import calculate_dcf
    _seed_income("DCFCO", [
        ("Sep 28, 2024", "Operating income", "Operating income", 50_000.0),
    ])
    save_ticker_info("DCFCO", {
        "currentPrice": 150.0,
        "sharesOutstanding": 1_000_000_000,
        "sector": "Technology",
        "longBusinessSummary": "A DCF test company.",
    })
    result = calculate_dcf("DCFCO", growth_rate=0.10, discount_rate=0.10)
    assert "DCFCO" in result
    assert "Intrinsic value" in result or "intrinsic" in result.lower()


def test_calculate_dcf_missing_operating_income():
    from tools.calc import calculate_dcf
    result = calculate_dcf("ZZZNO_OP_INC")
    assert "ERROR" in result
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n stock pytest tests/test_calc.py -v -k "peg or dcf"`

Expected: FAIL with `ImportError` (functions not yet defined)

- [ ] **Step 3: Add PEG and DCF to tools/calc.py**

Append to `tools/calc.py`:
```python
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
    base_fcf = by_year[latest_fy] * 1_000_000  # convert millions → dollars

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stock pytest tests/test_calc.py -v -k "peg or dcf"`

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/calc.py tests/test_calc.py
git commit -m "feat: valuation ratio tools — PEG ratio, DCF (TDD)"
```

---

## Task 5: tools/calc.py — sector P/E, correlation, rank

**Files:**
- Modify: `tools/calc.py`
- Modify: `tests/test_calc.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_calc.py`:
```python
def test_calculate_pe_vs_sector_returns_comparison():
    from tools.calc import calculate_pe_vs_sector
    save_ticker_info("SECCO", {
        "trailingPE": 25.0,
        "sector": "Technology",
        "longBusinessSummary": "Sector test company.",
    })
    result = calculate_pe_vs_sector("SECCO")
    assert "SECCO" in result
    assert "P/E" in result or "sector" in result.lower()


def test_calculate_pe_vs_sector_no_pe():
    from tools.calc import calculate_pe_vs_sector
    save_ticker_info("NOPESEC", {
        "sector": "Technology",
        "longBusinessSummary": "No PE.",
    })
    result = calculate_pe_vs_sector("NOPESEC")
    assert "ERROR" in result or "unavailable" in result.lower()


def test_calculate_correlation_returns_matrix(monkeypatch):
    from tools.calc import calculate_correlation
    import tools.price as price_mod
    _seed_price("CORA", [
        ("CORA", "2025-01-01", 100.0, time.time()),
        ("CORA", "2025-01-02", 102.0, time.time()),
        ("CORA", "2025-01-03", 101.0, time.time()),
        ("CORA", "2025-01-04", 104.0, time.time()),
        ("CORA", "2025-01-05", 103.0, time.time()),
    ])
    _seed_price("CORB", [
        ("CORB", "2025-01-01", 50.0, time.time()),
        ("CORB", "2025-01-02", 51.0, time.time()),
        ("CORB", "2025-01-03", 49.0, time.time()),
        ("CORB", "2025-01-04", 52.0, time.time()),
        ("CORB", "2025-01-05", 51.0, time.time()),
    ])
    monkeypatch.setattr(price_mod, "_is_price_fresh", lambda t: True)
    result = calculate_correlation(["CORA", "CORB"])
    assert "CORA" in result and "CORB" in result
    assert "correlation" in result.lower() or "vs" in result.lower()


def test_rank_tickers_returns_sorted_list():
    from tools.calc import rank_tickers
    _seed_income("RANKA", [("Sep 28, 2024", "Net sales", "Net sales", 500_000.0)])
    _seed_income("RANKB", [("Sep 28, 2024", "Net sales", "Net sales", 300_000.0)])
    _seed_income("RANKC", [("Sep 28, 2024", "Net sales", "Net sales", 700_000.0)])
    result = rank_tickers(["RANKA", "RANKB", "RANKC"], "revenue")
    assert "RANKC" in result
    assert "RANKA" in result
    assert result.index("RANKC") < result.index("RANKA") < result.index("RANKB")
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n stock pytest tests/test_calc.py -v -k "sector or correlation or rank"`

Expected: FAIL with `ImportError`

- [ ] **Step 3: Add remaining tools to tools/calc.py**

Append to `tools/calc.py`:
```python
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


def calculate_pe_vs_sector(ticker: str) -> str:
    info = load_ticker_info(ticker)
    if not info:
        return f"ERROR: No company info for {ticker} — call get_company_info first."
    pe = info.get("trailingPE")
    if not pe or not isinstance(pe, (int, float)):
        return f"ERROR: P/E ratio unavailable for {ticker}."
    sector = info.get("sector", "")
    peers = [t for t in SECTOR_PEERS.get(sector, []) if t != ticker][:5]
    if not peers:
        return (
            f"{ticker} P/E: {pe:.1f} | Sector: {sector}\n"
            f"  No peer benchmark available for sector '{sector}'."
        )
    peer_pes: list[float] = []
    lines = [f"{ticker} P/E vs {sector} Sector Peers:"]
    lines.append(f"  {ticker}: {pe:.1f} (subject)")
    for peer in peers:
        peer_info = load_ticker_info(peer)
        if not peer_info:
            from tools.company import fetch_and_cache_company
            peer_info = fetch_and_cache_company(peer) or {}
        peer_pe = peer_info.get("trailingPE")
        if peer_pe and isinstance(peer_pe, (int, float)):
            peer_pes.append(peer_pe)
            lines.append(f"  {peer}: {peer_pe:.1f}")
    if peer_pes:
        avg_pe = sum(peer_pes) / len(peer_pes)
        diff = pe - avg_pe
        lines.append(f"  Peer avg P/E: {avg_pe:.1f}  |  {ticker} is {diff:+.1f} vs peers")
    return "\n".join(lines)


def calculate_correlation(tickers: list[str], period: str = "1y") -> str:
    import pandas as pd
    from tools.price import DB_PATH as PRICE_DB, _is_price_fresh, get_price_history

    for ticker in tickers:
        if not _is_price_fresh(ticker):
            get_price_history(ticker, period)

    frames: dict[str, pd.Series] = {}
    for ticker in tickers:
        with duckdb.connect(PRICE_DB) as con:
            rows = con.execute(
                "SELECT date, close FROM price_history WHERE ticker = ? ORDER BY date",
                (ticker,)
            ).fetchall()
        if rows:
            dates, closes = zip(*rows)
            frames[ticker] = pd.Series(list(closes), index=list(dates), dtype=float)

    if len(frames) < 2:
        return f"ERROR: Need at least 2 tickers with price data. Got: {list(frames.keys())}"

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
```

- [ ] **Step 4: Run all calc tests**

Run: `conda run -n stock pytest tests/test_calc.py -v`

Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add tools/calc.py tests/test_calc.py
git commit -m "feat: sector P/E, correlation, rank_tickers tools (TDD)"
```

---

## Task 6: agents/financials.py

**Files:**
- Create: `agents/financials.py`
- Create: `tests/test_agents.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_agents.py`:
```python
from unittest.mock import MagicMock, patch


def _make_ollama_response(content="result", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    resp = MagicMock()
    resp.message = msg
    return resp


def test_financials_agent_returns_string():
    from agents.financials import run as run_financials
    with patch("agents.financials.ollama.chat", return_value=_make_ollama_response("AAPL revenue is $400B")):
        result = run_financials("What is AAPL revenue?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_financials_agent_calls_tool_when_requested():
    from agents.financials import run as run_financials, TOOL_FUNCTIONS

    tool_msg = MagicMock()
    tool_msg.content = None
    tool_call = MagicMock()
    tool_call.function.name = "get_income_statement"
    tool_call.function.arguments = {"ticker": "AAPL"}
    tool_msg.tool_calls = [tool_call]

    final_msg = MagicMock()
    final_msg.content = "AAPL revenue: $400B"
    final_msg.tool_calls = []

    responses = [MagicMock(message=tool_msg), MagicMock(message=final_msg)]

    with patch("agents.financials.ollama.chat", side_effect=responses), \
         patch.dict(TOOL_FUNCTIONS, {"get_income_statement": lambda ticker: "Revenue: $400B"}):
        result = run_financials("What is AAPL revenue?")

    assert "AAPL" in result or "400" in result
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n stock pytest tests/test_agents.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.financials'`

- [ ] **Step 3: Implement agents/financials.py**

Create `agents/financials.py`:
```python
import json
import logging

import ollama

from tools.config import MODEL
from tools.income import get_income_statement, get_quarterly_statement
from tools.company import get_company_info

SYSTEM_PROMPT = (
    "You are a financial data agent. Fetch and return structured financial facts for the requested ticker(s). "
    "Do not interpret, advise, or add context beyond what the tools return. "
    "Always cite the exact fiscal year and source filing for every figure."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_income_statement",
            "description": "Fetch the latest 3-year annual income statement for a ticker from SEC 10-K filings.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quarterly_statement",
            "description": "Fetch the last 4 quarters of income statement data for a ticker from SEC 10-Q filings.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_info",
            "description": "Get company profile, sector, and key financial ratios for a ticker.",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_income_statement": get_income_statement,
    "get_quarterly_statement": get_quarterly_statement,
    "get_company_info": get_company_info,
}

OPT = {"temperature": 0.1}


def run(user_question: str, context: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
    msg = response.message

    while msg.tool_calls:
        messages.append(msg)
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = (
                tool_call.function.arguments
                if isinstance(tool_call.function.arguments, dict)
                else json.loads(tool_call.function.arguments)
            )
            fn = TOOL_FUNCTIONS.get(name)
            result = fn(**args) if fn else f"Unknown tool: {name}"
            messages.append({"role": "tool", "content": result})
            logging.info("[FinancialsAgent] %s(%s)", name, args)
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
        msg = response.message

    return msg.content or ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stock pytest tests/test_agents.py -v`

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/financials.py tests/test_agents.py
git commit -m "feat: FinancialsAgent with income, quarterly, company_info tools (TDD)"
```

---

## Task 7: agents/news.py

**Files:**
- Create: `agents/news.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_agents.py`:
```python
def test_news_agent_returns_string():
    from agents.news import run as run_news
    with patch("agents.news.ollama.chat", return_value=_make_ollama_response("Apple released iPhone 17.")):
        result = run_news("What is the latest news on AAPL?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_news_agent_only_has_news_tools():
    from agents.news import TOOL_FUNCTIONS
    assert set(TOOL_FUNCTIONS.keys()) == {"get_stock_news", "search_news"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n stock pytest tests/test_agents.py::test_news_agent_returns_string tests/test_agents.py::test_news_agent_only_has_news_tools -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.news'`

- [ ] **Step 3: Implement agents/news.py**

Create `agents/news.py`:
```python
import json
import logging

import ollama

from tools.config import MODEL
from tools.news import get_stock_news, search_news

SYSTEM_PROMPT = (
    "You are a news retrieval agent. Fetch and summarise news for the requested ticker(s). "
    "Always cite the publisher, headline, and publication date for every item."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_news",
            "description": "Fetch live news headlines for a ticker from Yahoo Finance and Google News.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Hybrid semantic+keyword search over stored news articles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "ticker": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "days_back": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_stock_news": get_stock_news,
    "search_news": search_news,
}

OPT = {"temperature": 0.1}


def run(user_question: str, context: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
    msg = response.message

    while msg.tool_calls:
        messages.append(msg)
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = (
                tool_call.function.arguments
                if isinstance(tool_call.function.arguments, dict)
                else json.loads(tool_call.function.arguments)
            )
            fn = TOOL_FUNCTIONS.get(name)
            result = fn(**args) if fn else f"Unknown tool: {name}"
            messages.append({"role": "tool", "content": result})
            logging.info("[NewsAgent] %s(%s)", name, args)
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
        msg = response.message

    return msg.content or ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stock pytest tests/test_agents.py -v`

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/news.py tests/test_agents.py
git commit -m "feat: NewsAgent with get_stock_news, search_news tools (TDD)"
```

---

## Task 8: agents/calc.py

**Files:**
- Create: `agents/calc.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_agents.py`:
```python
def test_calc_agent_returns_string():
    from agents.calc import run as run_calc
    with patch("agents.calc.ollama.chat", return_value=_make_ollama_response("AAPL revenue CAGR: 8.2%")):
        result = run_calc("What is AAPL 3-year revenue CAGR?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_calc_agent_only_has_calc_tools():
    from agents.calc import TOOL_FUNCTIONS
    expected = {
        "calculate_dcf", "calculate_peg", "calculate_pe_vs_sector",
        "calculate_revenue_cagr", "calculate_margin_trend", "calculate_yoy",
        "calculate_correlation", "rank_tickers", "get_price_history",
    }
    assert set(TOOL_FUNCTIONS.keys()) == expected
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n stock pytest tests/test_agents.py::test_calc_agent_returns_string tests/test_agents.py::test_calc_agent_only_has_calc_tools -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.calc'`

- [ ] **Step 3: Implement agents/calc.py**

Create `agents/calc.py`:
```python
import json
import logging

import ollama

from tools.config import MODEL
from tools.calc import (
    calculate_dcf, calculate_peg, calculate_pe_vs_sector,
    calculate_revenue_cagr, calculate_margin_trend, calculate_yoy,
    calculate_correlation, rank_tickers,
)
from tools.price import get_price_history

SYSTEM_PROMPT = (
    "You are a financial calculation agent. Compute stock metrics using your tools. "
    "Always show the assumptions you used (e.g. discount rate, growth rate). "
    "If data is missing, return the error string from the tool — do not guess. "
    "Do not re-fetch data that is already present in the context you received."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculate_revenue_cagr",
            "description": "Calculate revenue compound annual growth rate for a ticker from cached income data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "years": {"type": "integer", "description": "Number of years (default 3)"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_margin_trend",
            "description": "Show gross and net margin trend by year for a ticker.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_yoy",
            "description": "Calculate year-over-year change for any income statement metric.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "metric": {"type": "string", "description": "e.g. 'revenue', 'net income'"},
                },
                "required": ["ticker", "metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_peg",
            "description": "Calculate PEG ratio (P/E divided by EPS growth rate) for a ticker.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_dcf",
            "description": "5-year DCF valuation using operating income as FCF proxy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "growth_rate": {"type": "number", "description": "Annual growth rate (default 0.10)"},
                    "discount_rate": {"type": "number", "description": "Discount rate / WACC (default 0.10)"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_pe_vs_sector",
            "description": "Compare a ticker's P/E ratio against 5 sector peers.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_correlation",
            "description": "Calculate price return correlation between 2+ tickers over a period.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of ticker symbols",
                    },
                    "period": {"type": "string", "description": "yfinance period string, e.g. '1y' (default)"},
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_tickers",
            "description": "Rank a list of tickers by a financial metric (highest first).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "metric": {"type": "string", "description": "e.g. 'revenue', 'net income'"},
                },
                "required": ["tickers", "metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": "Fetch daily close price history for a ticker (cached 24h).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "period": {"type": "string", "description": "yfinance period, e.g. '1y'"},
                },
                "required": ["ticker"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "calculate_dcf": calculate_dcf,
    "calculate_peg": calculate_peg,
    "calculate_pe_vs_sector": calculate_pe_vs_sector,
    "calculate_revenue_cagr": calculate_revenue_cagr,
    "calculate_margin_trend": calculate_margin_trend,
    "calculate_yoy": calculate_yoy,
    "calculate_correlation": calculate_correlation,
    "rank_tickers": rank_tickers,
    "get_price_history": get_price_history,
}

OPT = {"temperature": 0.1}


def run(user_question: str, context: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
    msg = response.message

    while msg.tool_calls:
        messages.append(msg)
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = (
                tool_call.function.arguments
                if isinstance(tool_call.function.arguments, dict)
                else json.loads(tool_call.function.arguments)
            )
            fn = TOOL_FUNCTIONS.get(name)
            result = fn(**args) if fn else f"Unknown tool: {name}"
            messages.append({"role": "tool", "content": result})
            logging.info("[CalcAgent] %s(%s)", name, args)
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
        msg = response.message

    return msg.content or ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stock pytest tests/test_agents.py -v`

Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/calc.py tests/test_agents.py
git commit -m "feat: CalcAgent with all 8 calculation tools + price history (TDD)"
```

---

## Task 9: orchestrator.py

**Files:**
- Create: `orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_orchestrator.py`:
```python
import json
from unittest.mock import MagicMock, patch, call


def _ollama_response(content):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = []
    return MagicMock(message=msg)


def test_plan_parses_valid_json():
    from orchestrator import _parse_plan
    raw = '{"agents": ["financials", "calc"], "tickers": ["AAPL"]}'
    plan = _parse_plan(raw)
    assert plan["agents"] == ["financials", "calc"]
    assert plan["tickers"] == ["AAPL"]


def test_plan_parses_json_embedded_in_text():
    from orchestrator import _parse_plan
    raw = 'Sure, here is the plan: {"agents": ["news"], "tickers": ["TSLA"]} Let me proceed.'
    plan = _parse_plan(raw)
    assert plan["agents"] == ["news"]


def test_keyword_fallback_news():
    from orchestrator import _keyword_fallback
    assert _keyword_fallback("latest news on AAPL") == ["news"]


def test_keyword_fallback_calc():
    from orchestrator import _keyword_fallback
    assert _keyword_fallback("calculate CAGR for NVDA") == ["calc"]


def test_keyword_fallback_financials():
    from orchestrator import _keyword_fallback
    assert _keyword_fallback("show me AAPL revenue") == ["financials"]


def test_direct_answer_skips_agents():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": [], "tickers": []})
    synthesis_text = "P/E ratio is a valuation metric."

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response(plan_json),
        _ollama_response(synthesis_text),
    ]) as mock_chat, \
         patch("orchestrator.run_financials") as mock_fin, \
         patch("orchestrator.run_news") as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        result, _ = process_turn("What is P/E ratio?", [])

    assert result == synthesis_text
    mock_fin.assert_not_called()
    mock_news.assert_not_called()
    mock_calc.assert_not_called()


def test_single_agent_plan_calls_correct_agent():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials"], "tickers": ["AAPL"]})

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response(plan_json),
        _ollama_response("AAPL revenue is $400B."),
    ]), \
         patch("orchestrator.run_financials", return_value="Revenue: $400B") as mock_fin, \
         patch("orchestrator.run_news") as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        result, _ = process_turn("What is AAPL revenue?", [])

    mock_fin.assert_called_once()
    mock_news.assert_not_called()
    mock_calc.assert_not_called()
    assert "400" in result or "revenue" in result.lower()


def test_multi_agent_passes_context_forward():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials", "calc"], "tickers": ["AAPL"]})
    fin_result = "AAPL operating income: $120B"

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response(plan_json),
        _ollama_response("AAPL DCF: $195/share"),
    ]), \
         patch("orchestrator.run_financials", return_value=fin_result) as mock_fin, \
         patch("orchestrator.run_calc", return_value="DCF: $195/share") as mock_calc:

        process_turn("Calculate AAPL DCF", [])

    calc_call_args = mock_calc.call_args
    context_passed = calc_call_args[0][1] if calc_call_args[0] else calc_call_args[1].get("context", "")
    assert "operating income" in context_passed or "AAPL" in context_passed


def test_malformed_plan_uses_keyword_fallback():
    from orchestrator import process_turn

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response("I cannot produce a plan right now."),
        _ollama_response("Here are the latest AAPL headlines."),
    ]), \
         patch("orchestrator.run_financials") as mock_fin, \
         patch("orchestrator.run_news", return_value="Headline: Apple up 2%") as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        process_turn("latest news on AAPL", [])

    mock_news.assert_called_once()
    mock_fin.assert_not_called()


def test_agent_failure_is_skipped_gracefully():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials", "news"], "tickers": ["AAPL"]})

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response(plan_json),
        _ollama_response("Here is what I found."),
    ]), \
         patch("orchestrator.run_financials", side_effect=Exception("Ollama timeout")), \
         patch("orchestrator.run_news", return_value="Apple up 2%"):

        result, _ = process_turn("AAPL news and financials", [])

    assert isinstance(result, str)
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n stock pytest tests/test_orchestrator.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator'`

- [ ] **Step 3: Implement orchestrator.py**

Create `orchestrator.py`:
```python
import json
import logging
import re

import ollama

from tools.config import MODEL
from agents.financials import run as run_financials
from agents.news import run as run_news
from agents.calc import run as run_calc

PLAN_SYSTEM = (
    "You are a stock analysis orchestrator. Given the user's question, output a JSON plan "
    "with the agents to call and the tickers involved. "
    "Available agents: 'financials' (income statements, company info), "
    "'news' (headlines, news search), 'calc' (valuation ratios, growth metrics, portfolio analysis). "
    "If the question is conversational or can be answered from conversation context alone, use agents=[]. "
    "Respond with ONLY valid JSON in this format: "
    '{"agents": ["financials"], "tickers": ["AAPL"], "reason": "one line"}'
)

SYNTHESIS_SYSTEM = (
    "You are a stock analysis assistant. "
    "Synthesise the agent outputs below into a clear, direct answer. "
    "Cite which agent/tool provided each fact. "
    "Only state facts that came from agent outputs. "
    "If agent data is insufficient, say so rather than guessing."
)

OPT_PLAN = {"temperature": 0.0}
OPT_SYNTH = {"temperature": 0.3}


def _parse_plan(content: str) -> dict:
    content = content.strip()
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(content)


def _keyword_fallback(question: str) -> list[str]:
    q = question.lower()
    if any(w in q for w in ["news", "headline", "article", "latest"]):
        return ["news"]
    if any(w in q for w in ["dcf", "cagr", "correlation", "peg", "margin", "rank", "valuation", "calculate"]):
        return ["calc"]
    return ["financials"]


def process_turn(
    user_input: str,
    messages: list[dict],
    persona_system: str | None = None,
) -> tuple[str, list[dict]]:
    planning_messages = [
        {"role": "system", "content": PLAN_SYSTEM},
        *messages,
        {"role": "user", "content": user_input},
    ]
    plan_response = ollama.chat(model=MODEL, messages=planning_messages, options=OPT_PLAN)
    plan_content = plan_response.message.content or ""

    try:
        plan = _parse_plan(plan_content)
        agents_to_run: list[str] = plan.get("agents", [])
    except (json.JSONDecodeError, ValueError):
        logging.warning("Orchestrator plan JSON malformed — using keyword fallback")
        agents_to_run = _keyword_fallback(user_input)

    accumulated_context = ""
    agent_map = {
        "financials": run_financials,
        "news": run_news,
        "calc": run_calc,
    }

    for agent_name in agents_to_run:
        fn = agent_map.get(agent_name)
        if fn is None:
            continue
        try:
            result = fn(user_input, accumulated_context)
            accumulated_context += f"\n\n[{agent_name.upper()} AGENT]\n{result}"
            logging.info("Orchestrator: %s agent completed", agent_name)
        except Exception as e:
            logging.warning("Orchestrator: %s agent failed — %s", agent_name, e)

    synthesis_system = persona_system or SYNTHESIS_SYSTEM
    synthesis_messages = [{"role": "system", "content": synthesis_system}, *messages]
    synthesis_messages.append({"role": "user", "content": user_input})
    if accumulated_context:
        synthesis_messages.append({
            "role": "user",
            "content": (
                f"Agent outputs:\n{accumulated_context}\n\n"
                "Based ONLY on the above agent outputs, answer the user's question. "
                "Quote specific figures directly from the outputs."
            ),
        })

    synthesis_response = ollama.chat(model=MODEL, messages=synthesis_messages, options=OPT_SYNTH)
    answer = synthesis_response.message.content or ""

    updated_messages = messages + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, updated_messages
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stock pytest tests/test_orchestrator.py -v`

Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator — plan/synthesize loop, agent sequencing, context accumulation (TDD)"
```

---

## Task 10: Refactor main.py + smoke test

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Replace main.py chat loop with orchestrator**

Replace the entire content of `main.py` with:
```python
import logging
import os

from dotenv import load_dotenv
load_dotenv()

from edgar import set_identity

from tools.config import MODEL
from tools.db import init_db
from tools.vector import init_qdrant
from tools.search import _get_anchor_vecs
from orchestrator import process_turn, SYNTHESIS_SYSTEM

# Re-exports for tests/test_tools.py compatibility
from tools.db import (
    is_cache_fresh, save_to_cache, load_from_cache, fuzzy_query,
    save_ticker_info, load_ticker_info, is_ticker_info_fresh, get_summary_hash,
    is_quarterly_cache_fresh, save_quarterly_cache, load_quarterly_cache,
)
from tools.income import parse_income_statement, get_income_statement, get_quarterly_statement
from tools.vector import (
    init_qdrant,  # noqa: F811 — re-export for test_tools.py
    store_articles, hybrid_search, upsert_company_profile, search_company_profiles,
)
from tools.news import get_stock_news, search_news
from tools.config import DB_PATH, QDRANT_COLLECTION, COMPANY_PROFILES_COLLECTION

set_identity("yourname@email.com")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

PERSONAS = {
    "buffett": (
        "Warren Buffett",
        "Respond as Warren Buffett. Focus on intrinsic value, competitive moats, long-term holding, "
        "and margin of safety. Use plain folksy language. Be skeptical of high-P/E growth stocks.",
    ),
    "munger": (
        "Charlie Munger",
        "Respond as Charlie Munger. Apply mental models, invert problems, and be blunt. "
        "Emphasize business quality and rational thinking over clever financial engineering.",
    ),
    "lynch": (
        "Peter Lynch",
        "Respond as Peter Lynch. Focus on growth at a reasonable price (GARP) and PEG ratio. "
        "Be optimistic and practical. Look for ten-baggers in everyday businesses people understand.",
    ),
    "dalio": (
        "Ray Dalio",
        "Respond as Ray Dalio. Think in macro cycles, debt cycles, and risk parity. "
        "Emphasize diversification, correlation, and understanding the economy as a machine.",
    ),
    "wood": (
        "Cathie Wood",
        "Respond as Cathie Wood. Focus on disruptive innovation and exponential growth curves. "
        "Be bullish on AI, genomics, and fintech. Think in 5-year price targets.",
    ),
}

PANEL_PROMPT = (
    "You are a panel of five famous investors: Warren Buffett, Charlie Munger, Peter Lynch, "
    "Ray Dalio, and Cathie Wood. For every question give a SHORT response from each investor "
    "labeled with their name, reflecting their known philosophy and speaking style."
)


def _build_persona_system(persona_key: str | None) -> str | None:
    if persona_key == "panel":
        return SYNTHESIS_SYSTEM + " " + PANEL_PROMPT
    if persona_key and persona_key in PERSONAS:
        return SYNTHESIS_SYSTEM + " " + PERSONAS[persona_key][1]
    return None


def chat():
    persona: str | None = None
    messages: list[dict] = []
    names = ", ".join(PERSONAS.keys())
    print(f"Stock Assistant ({MODEL}) — type 'exit' to quit")
    print(f"Personas: /persona <{names}|panel|off>\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        if user_input.startswith("/persona"):
            parts = user_input.split()
            key = parts[1].lower() if len(parts) > 1 else "off"
            if key == "off":
                persona = None
                print("[Persona off — back to default]\n")
            elif key in ("panel", *PERSONAS):
                persona = key
                label = "investor panel" if key == "panel" else PERSONAS[key][0]
                print(f"[Persona: {label}]\n")
            else:
                print(f"[Unknown persona '{key}'. Available: {names}, panel, off]\n")
            continue

        answer, messages = process_turn(user_input, messages, _build_persona_system(persona))
        print(f"\nAssistant: {answer}\n")


if __name__ == "__main__":
    init_db()
    init_qdrant()
    _get_anchor_vecs()
    chat()
```

- [ ] **Step 2: Run full test suite to verify nothing broke**

Run: `conda run -n stock pytest tests/ -v --tb=short`

Expected: All pre-existing tests in `test_tools.py` PASS. New tests in `test_calc.py`, `test_agents.py`, `test_orchestrator.py` PASS.

- [ ] **Step 3: Run smoke test**

Run: `conda run -n stock python smoke_test.py`

Expected: No exceptions. Smoke test completes.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "refactor: wire orchestrator into main.py, keep re-exports for test compat"
```

---

## Done

All tasks complete when:
- `conda run -n stock pytest tests/ -v` passes with zero failures
- `conda run -n stock python smoke_test.py` runs without exceptions
- `python main.py` starts the chat loop and routes a test question through the orchestrator
