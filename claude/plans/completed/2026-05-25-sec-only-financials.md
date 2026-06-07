# SEC-Only Financials + RatiosAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all yfinance-sourced financial ratios (margins, D/E, ROA, ROE) with SEC/edgar-sourced values, and introduce a dedicated RatiosAgent to keep the CalcAgent under 10 tools.

**Architecture:** A new `tools/ratios.py` module computes SEC-derived ratios from the existing `income_statements` and new `balance_sheets` DuckDB tables. A new `agents/ratios.py` (RatiosAgent) exposes these tools. The orchestrator learns to route ratio questions to this agent. `get_company_info` drops the yfinance-derived ratio lines.

**Tech Stack:** Python, edgar library, DuckDB, Ollama (Qwen 3 14B), existing `tools/db.py` cache patterns.

**All commands must be run as:** `conda run -n stock pytest tests/... -v`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `tools/config.py` | TTL 72→24, add operating loss synonym |
| Modify | `tools/db.py` | Add `balance_sheets` table + 3 helpers |
| **Create** | `tools/balance_sheet.py` | Fetch/parse/cache balance sheet from edgar |
| **Create** | `tools/ratios.py` | `calculate_all_margins`, `calculate_debt_to_equity`, `calculate_roa_roe` |
| **Create** | `agents/ratios.py` | RatiosAgent — wires 4 tools, same loop pattern as CalcAgent |
| Modify | `tools/company.py` | Remove profitMargins, grossMargins, debtToEquity, ROA, ROE from output |
| Modify | `prompts.py` | Add `RATIOS_SYSTEM`, update `PLAN_SYSTEM`, `SYNTHESIS_SYSTEM`, `CALC_SYSTEM`, bump VERSION |
| Modify | `orchestrator.py` | Import + register `run_ratios`, update `_keyword_fallback` |
| Modify | `main.py` | Re-export new functions for test compat |
| Modify | `tests/test_tools.py` | Add balance sheet DB + ratios function tests |

---

## Task 1: Config + Prompt Changes

**Files:**
- Modify: `tools/config.py`
- Modify: `prompts.py`

- [ ] **Step 1: Update config.py**

```python
# tools/config.py — final state
DB_PATH = "cache.db"
CACHE_TTL_DAYS = 90
QDRANT_COLLECTION = "stock_news"
DENSE_MODEL = "BAAI/bge-large-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"
COMPANY_PROFILES_COLLECTION = "company_profiles"
TICKER_INFO_TTL_HOURS = 24  # was 72

SYNONYMS = {
    "revenue":          ["%revenue%", "%net sales%", "%total sales%", "%total revenues%"],
    "net income":       ["%net income%", "%net earnings%", "%profit%", "%net loss%"],
    "gross margin":     ["%gross margin%", "%gross profit%"],
    "r&d":              ["%research%", "%development%", "%technology and content%"],
    "operating income": ["%operating income%", "%income from operations%", "%operating loss%"],
    "cost of sales":    ["%cost of sales%", "%cost of revenue%", "%cost of goods%"],
    "eps":              ["%earnings per share%", "%diluted%"],
}

MODEL = "qwen3:14b"
```

- [ ] **Step 2: Update prompts.py**

Replace the full file with this content:

```python
# Central prompt registry.
VERSION = "1.3.0"

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

PLAN_SYSTEM = (
    "You are a stock analysis orchestrator. Given the user's question, output a JSON plan "
    "with the agents to call and the tickers involved. "
    "Available agents: "
    "'financials' (income statements, quarterly results, company market info), "
    "'news' (headlines, news search), "
    "'calc' (valuation: DCF, PEG, CAGR, YoY growth, price correlation, sector P/E), "
    "'ratios' (SEC-sourced financial ratios: profit/gross/operating margins, debt-to-equity, ROA, ROE — "
    "always prefer 'ratios' over 'financials' for these metrics). "
    "TICKER RESOLUTION: When the user mentions a company by name, resolve it to the correct stock ticker. "
    "Be careful — short names can conflict: 'Rocket Lab' = RKLB (not RL which is Ralph Lauren), "
    "'Meta' = META, 'Apple' = AAPL, 'Google' = GOOGL, 'Amazon' = AMZN, 'Tesla' = TSLA. "
    "Always use the primary US exchange ticker (NYSE/NASDAQ). "
    "IMPORTANT: If the question is conversational, a greeting, an apology, a correction with no new task, "
    "or can be answered from conversation history alone — set agents=[] and answer directly. "
    "Examples that must use agents=[]: 'hello', 'thanks', 'I want to sleep', 'sorry I meant INTC' (with no prior task), 'what did you just say'. "
    "Only call agents when the user is asking for real financial data, news, or calculations. "
    "Respond with ONLY valid JSON — no explanation, no markdown, no extra text: "
    '{"agents": ["financials"], "tickers": ["AAPL"], "reason": "one line"}'
)

SYNTHESIS_SYSTEM = (
    "You are a stock analysis assistant. "
    "Synthesise the agent outputs below into a clear, direct answer. "
    "Cite which agent/tool provided each fact. "
    "Only state facts that came from agent outputs. "
    "If agent data is insufficient, say so rather than guessing. "
    "IMPORTANT: When citing financial ratios (margins, debt/equity, ROA, ROE), "
    "always prefer values from the 'ratios' agent (SEC 10-K sourced) over values from 'financials' (yfinance). "
    "If only yfinance values are available, note they may lag by 1-2 quarters."
)

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

FINANCIALS_SYSTEM = (
    "You are a financial data agent. Fetch and return structured financial facts for the requested ticker(s). "
    "Do not interpret, advise, or add context beyond what the tools return. "
    "Always cite the exact fiscal year and source filing for every figure."
)

NEWS_SYSTEM = (
    "You are a news retrieval agent. Fetch and summarise news for the requested ticker(s). "
    "Always cite the publisher, headline, and publication date for every item."
)

CALC_SYSTEM = (
    "You are a financial calculation agent. Compute stock metrics using your tools. "
    "Always show the assumptions you used (e.g. discount rate, growth rate). "
    "If data is missing, return the error string from the tool — do not guess. "
    "Do not re-fetch data that is already present in the context you received. "
    "NOTE: For profit margin, gross margin, debt-to-equity, ROA, ROE — "
    "these are handled by the ratios agent, not this agent. Do not attempt to compute them here."
)

RATIOS_SYSTEM = (
    "You are a financial ratios agent. Compute accurate financial ratios using data sourced "
    "directly from SEC 10-K filings — never from yfinance. "
    "When asked for debt-to-equity, ROA, or ROE: call get_balance_sheet first, then the matching calculate_ tool. "
    "When asked for profit, gross, or operating margins: call calculate_all_margins "
    "(it reads cached SEC income data — call get_income_statement first if the cache may be empty). "
    "Always cite the fiscal year and confirm the source is SEC filings."
)

# ---------------------------------------------------------------------------
# Personas (used in main.py)
# ---------------------------------------------------------------------------

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
```

- [ ] **Step 3: Commit**

```
git add tools/config.py prompts.py
git commit -m "feat: reduce ticker_info TTL, add ratios agent prompts, VERSION 1.3.0"
```

---

## Task 2: Add balance_sheets Table to DB

**Files:**
- Modify: `tools/db.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_tools.py`:

```python
def test_init_db_creates_balance_sheet_table():
    from main import init_db, DB_PATH
    init_db()
    import duckdb
    with duckdb.connect(DB_PATH) as con:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "balance_sheets" in tables


def test_save_and_load_balance_sheet_roundtrip():
    import time
    from tools.db import init_db, save_balance_sheet, load_balance_sheet
    init_db()
    rows = [
        {"ticker": "BSTEST", "fiscal_year": "Dec 31, 2025", "section": "Assets",
         "line_item": "Total assets", "value": 2324.0, "fetched_at": time.time()},
        {"ticker": "BSTEST", "fiscal_year": "Dec 31, 2025", "section": "Equity",
         "line_item": "Total stockholders equity", "value": 1721.0, "fetched_at": time.time()},
    ]
    save_balance_sheet(rows)
    result = load_balance_sheet("BSTEST")
    assert "Total assets" in result
    assert "2,324" in result


def test_is_balance_sheet_fresh_returns_false_when_empty():
    from tools.db import init_db, is_balance_sheet_fresh
    init_db()
    assert is_balance_sheet_fresh("ZZZNOTREAL_BS") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
conda run -n stock pytest tests/test_tools.py::test_init_db_creates_balance_sheet_table tests/test_tools.py::test_save_and_load_balance_sheet_roundtrip tests/test_tools.py::test_is_balance_sheet_fresh_returns_false_when_empty -v
```

Expected: FAIL (balance_sheets table doesn't exist, functions not defined)

- [ ] **Step 3: Add balance_sheets table to init_db() in tools/db.py**

In `tools/db.py`, inside `init_db()`, add after the `price_history` table creation:

```python
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
```

- [ ] **Step 4: Add 3 helper functions to tools/db.py**

Add at the end of `tools/db.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

```
conda run -n stock pytest tests/test_tools.py::test_init_db_creates_balance_sheet_table tests/test_tools.py::test_save_and_load_balance_sheet_roundtrip tests/test_tools.py::test_is_balance_sheet_fresh_returns_false_when_empty -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```
git add tools/db.py tests/test_tools.py
git commit -m "feat: add balance_sheets table and cache helpers to db.py (TDD)"
```

---

## Task 3: tools/balance_sheet.py

**Files:**
- Create: `tools/balance_sheet.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tools.py`:

```python
def test_parse_balance_sheet_extracts_rows():
    from tools.balance_sheet import parse_balance_sheet
    sample = (
        "                                               Dec 31, 2025   Dec 31, 2024\n"
        "   ────────────────────────────────────────────────────────\n"
        "    Assets\n"
        "      Current assets:\n"
        "            Cash and cash equivalents              $828,660       $271,042\n"
        "          Total current assets                   $1,365,544       $692,621\n"
        "        Total assets                             $2,324,478     $1,184,342\n"
        "          Total liabilities                        $602,624       $801,889\n"
        "      Stockholders' equity:\n"
        "          Total stockholders' equity:           $1,721,854       $382,453\n"
        "   Source: SEC XBRL  •  (In thousands, except shares and per share data)\n"
    )
    rows = parse_balance_sheet("RKLB", sample)
    assert len(rows) > 0
    items = [r["line_item"] for r in rows]
    assert "Total assets" in items
    assert any("equity" in i.lower() for i in items)


def test_parse_balance_sheet_two_fiscal_years():
    from tools.balance_sheet import parse_balance_sheet
    sample = (
        "                                               Dec 31, 2025   Dec 31, 2024\n"
        "   ────────────────────────────────────────────────────────\n"
        "        Total assets                             $2,324,478     $1,184,342\n"
        "   Source: SEC XBRL  •  (In thousands)\n"
    )
    rows = parse_balance_sheet("RKLB", sample)
    fiscal_years = {r["fiscal_year"] for r in rows}
    assert "Dec 31, 2025" in fiscal_years
    assert "Dec 31, 2024" in fiscal_years


def test_parse_balance_sheet_applies_thousands_multiplier():
    from tools.balance_sheet import parse_balance_sheet
    sample = (
        "                         Dec 31, 2025\n"
        "   ───────────────────────────────\n"
        "        Total assets       $2,000,000\n"
        "   Source: SEC XBRL  •  (In thousands)\n"
    )
    rows = parse_balance_sheet("TEST", sample)
    asset_row = next(r for r in rows if r["line_item"] == "Total assets")
    assert asset_row["value"] == 2000.0  # 2,000,000 thousands → 2,000M
```

- [ ] **Step 2: Run tests to verify they fail**

```
conda run -n stock pytest tests/test_tools.py::test_parse_balance_sheet_extracts_rows tests/test_tools.py::test_parse_balance_sheet_two_fiscal_years tests/test_tools.py::test_parse_balance_sheet_applies_thousands_multiplier -v
```

Expected: FAIL (module not found)

- [ ] **Step 3: Create tools/balance_sheet.py**

```python
import logging
import re
import time

from edgar import Company

from tools.db import is_balance_sheet_fresh, save_balance_sheet, load_balance_sheet


def _unit_multiplier(raw: str) -> float:
    lower = raw.lower()
    if 'in thousands' in lower:
        return 0.001
    if 'in billions' in lower:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
conda run -n stock pytest tests/test_tools.py::test_parse_balance_sheet_extracts_rows tests/test_tools.py::test_parse_balance_sheet_two_fiscal_years tests/test_tools.py::test_parse_balance_sheet_applies_thousands_multiplier -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```
git add tools/balance_sheet.py tests/test_tools.py
git commit -m "feat: balance sheet parser and edgar fetch with DuckDB cache (TDD)"
```

---

## Task 4: tools/ratios.py

**Files:**
- Create: `tools/ratios.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tools.py`:

```python
def test_calculate_all_margins_from_cache():
    import time
    from tools.db import init_db, save_to_cache
    from tools.ratios import calculate_all_margins
    init_db()
    save_to_cache([
        {"ticker": "MARGINTEST", "fiscal_year": "Dec 31, 2025", "section": "Revenue",
         "line_item": "Net sales", "value": 1000.0, "fetched_at": time.time()},
        {"ticker": "MARGINTEST", "fiscal_year": "Dec 31, 2025", "section": "Gross",
         "line_item": "Gross profit", "value": 400.0, "fetched_at": time.time()},
        {"ticker": "MARGINTEST", "fiscal_year": "Dec 31, 2025", "section": "Net",
         "line_item": "Net income", "value": 100.0, "fetched_at": time.time()},
    ])
    result = calculate_all_margins("MARGINTEST")
    assert "40.0%" in result  # gross margin 400/1000
    assert "10.0%" in result  # net margin 100/1000


def test_calculate_debt_to_equity_from_cache():
    import time
    from tools.db import init_db, save_balance_sheet
    from tools.ratios import calculate_debt_to_equity
    init_db()
    save_balance_sheet([
        {"ticker": "DTETEST", "fiscal_year": "Dec 31, 2025", "section": "Liabilities",
         "line_item": "Long-term debt", "value": 150.0, "fetched_at": time.time()},
        {"ticker": "DTETEST", "fiscal_year": "Dec 31, 2025", "section": "Equity",
         "line_item": "Total stockholders equity", "value": 1700.0, "fetched_at": time.time()},
    ])
    result = calculate_debt_to_equity("DTETEST")
    assert "0.088" in result  # 150/1700 = 0.0882
    assert "Dec 31, 2025" in result


def test_calculate_roa_roe_from_cache():
    import time
    from tools.db import init_db, save_to_cache, save_balance_sheet
    from tools.ratios import calculate_roa_roe
    init_db()
    save_to_cache([
        {"ticker": "ROATEST", "fiscal_year": "Dec 31, 2025", "section": "Net",
         "line_item": "Net income", "value": 200.0, "fetched_at": time.time()},
    ])
    save_balance_sheet([
        {"ticker": "ROATEST", "fiscal_year": "Dec 31, 2025", "section": "Assets",
         "line_item": "Total assets", "value": 2000.0, "fetched_at": time.time()},
        {"ticker": "ROATEST", "fiscal_year": "Dec 31, 2025", "section": "Equity",
         "line_item": "Total stockholders equity", "value": 1000.0, "fetched_at": time.time()},
    ])
    result = calculate_roa_roe("ROATEST")
    assert "10.0%" in result   # ROA = 200/2000
    assert "20.0%" in result   # ROE = 200/1000


def test_calculate_debt_to_equity_missing_data():
    from tools.ratios import calculate_debt_to_equity
    result = calculate_debt_to_equity("ZZZNOTREAL_DTE")
    assert result.startswith("ERROR:")
```

- [ ] **Step 2: Run tests to verify they fail**

```
conda run -n stock pytest tests/test_tools.py::test_calculate_all_margins_from_cache tests/test_tools.py::test_calculate_debt_to_equity_from_cache tests/test_tools.py::test_calculate_roa_roe_from_cache tests/test_tools.py::test_calculate_debt_to_equity_missing_data -v
```

Expected: FAIL (module not found)

- [ ] **Step 3: Create tools/ratios.py**

```python
import duckdb

from tools.config import DB_PATH
from tools.db import fuzzy_query


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

    rev_by_year = {r["fiscal_year"]: r["value"] for r in revenue_rows}
    gross_by_year = {r["fiscal_year"]: r["value"] for r in gross_rows}
    net_by_year = {r["fiscal_year"]: r["value"] for r in net_rows}
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

    with duckdb.connect(DB_PATH) as con:
        fy_row = con.execute(
            "SELECT fiscal_year FROM balance_sheets WHERE ticker = ? ORDER BY fiscal_year DESC LIMIT 1",
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

    net_by_year = {}
    for r in net_rows:
        fy = r["fiscal_year"]
        if fy not in net_by_year:
            net_by_year[fy] = r["value"]

    with duckdb.connect(DB_PATH) as con:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
conda run -n stock pytest tests/test_tools.py::test_calculate_all_margins_from_cache tests/test_tools.py::test_calculate_debt_to_equity_from_cache tests/test_tools.py::test_calculate_roa_roe_from_cache tests/test_tools.py::test_calculate_debt_to_equity_missing_data -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```
git add tools/ratios.py tests/test_tools.py
git commit -m "feat: SEC-sourced ratio calculations — margins, D/E, ROA/ROE (TDD)"
```

---

## Task 5: agents/ratios.py (RatiosAgent)

**Files:**
- Create: `agents/ratios.py`

- [ ] **Step 1: Create agents/ratios.py**

```python
import json
import logging

import ollama

from tools.config import MODEL
from tools.balance_sheet import get_balance_sheet
from tools.ratios import calculate_all_margins, calculate_debt_to_equity, calculate_roa_roe
from prompts import RATIOS_SYSTEM as SYSTEM_PROMPT

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_balance_sheet",
            "description": (
                "Fetch the latest 2-year balance sheet for a ticker from SEC 10-K filings. "
                "Call this before calculate_debt_to_equity or calculate_roa_roe."
            ),
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
            "name": "calculate_all_margins",
            "description": (
                "Compute gross, operating, and net profit margins from SEC 10-K income data. "
                "Use for any question about profit margin, gross margin, or operating margin. "
                "Requires get_income_statement to have been called first."
            ),
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
            "name": "calculate_debt_to_equity",
            "description": (
                "Compute debt-to-equity ratio from SEC 10-K balance sheet data. "
                "Call get_balance_sheet first. More accurate than yfinance debtToEquity."
            ),
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
            "name": "calculate_roa_roe",
            "description": (
                "Compute Return on Assets and Return on Equity from SEC 10-K data. "
                "Requires both get_income_statement and get_balance_sheet to have been called."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_balance_sheet": get_balance_sheet,
    "calculate_all_margins": calculate_all_margins,
    "calculate_debt_to_equity": calculate_debt_to_equity,
    "calculate_roa_roe": calculate_roa_roe,
}

OPT = {"temperature": 0.1}


def run(user_question: str, context: str = "", history: list[dict] | None = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages += history[-6:]
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
            logging.info("[RatiosAgent] %s(%s)", name, args)
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
        msg = response.message

    return msg.content or ""
```

- [ ] **Step 2: Verify import works**

```
conda run -n stock python -c "from agents.ratios import run; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```
git add agents/ratios.py
git commit -m "feat: RatiosAgent with 4 SEC-sourced ratio tools"
```

---

## Task 6: Wire Everything Together

**Files:**
- Modify: `tools/company.py`
- Modify: `orchestrator.py`
- Modify: `main.py`

- [ ] **Step 1: Remove ratio lines from get_company_info in tools/company.py**

Replace the `lines` list inside `get_company_info` with:

```python
    lines = [
        f"{info.get('longName', symbol)} ({symbol})",
        f"Data as of: {as_of} (cached)",
        f"Sector: {info.get('sector','')} | Industry: {info.get('industry','')}",
        f"Market Cap: ${info.get('marketCap',0):,.0f}  [point-in-time as of {as_of}]",
        f"P/E trailing: {info.get('trailingPE','N/A')} | Forward P/E: {info.get('forwardPE','N/A')}  [TTM / next-12m estimates]",
        f"Beta: {info.get('beta','N/A')} | Current Price: ${info.get('currentPrice','N/A')}",
        f"Recommendation: {info.get('recommendationKey','N/A')} ({info.get('numberOfAnalystOpinions',0)} analysts)",
        f"Note: For margins and D/E, use the ratios agent tools (SEC-sourced, more accurate than yfinance).",
        f"\n{info.get('longBusinessSummary','')}",
    ]
```

- [ ] **Step 2: Update orchestrator.py**

Replace the import block and `agent_map` in `orchestrator.py`:

```python
# At top with other imports, add:
from agents.ratios import run as run_ratios
```

Replace the `agent_map` dict (lines 99-103):

```python
    agent_map = {
        "financials": run_financials,
        "news": run_news,
        "calc": run_calc,
        "ratios": run_ratios,
    }
```

Replace `_keyword_fallback`:

```python
def _keyword_fallback(question: str) -> list[str]:
    q = question.lower()
    if any(w in q for w in ["news", "headline", "article", "latest"]):
        return ["news"]
    if any(w in q for w in ["debt", "equity ratio", "d/e", "roa", "roe", "return on"]):
        return ["ratios"]
    if any(w in q for w in ["margin", "profit margin", "gross margin"]):
        return ["ratios"]
    if any(w in q for w in ["dcf", "cagr", "correlation", "peg", "rank", "valuation", "calculate"]):
        return ["calc"]
    return ["financials"]
```

Also add `"ratios"` to `_FINANCIAL_KEYWORDS` set:

```python
_FINANCIAL_KEYWORDS = {
    "revenue", "income", "earnings", "profit", "loss", "sales", "margin",
    "cagr", "dcf", "peg", "valuation", "p/e", "pe ratio", "eps",
    "news", "headline", "article", "filing", "10-k", "10-q",
    "stock", "share", "price", "dividend", "sector", "analyst",
    "correlation", "rank", "compare", "quarterly", "annual",
    "debt", "equity", "roa", "roe", "balance sheet",
}
```

- [ ] **Step 3: Add re-exports to main.py**

Add to the re-exports block in `main.py`:

```python
from tools.db import is_balance_sheet_fresh, save_balance_sheet, load_balance_sheet
from tools.balance_sheet import parse_balance_sheet, get_balance_sheet
from tools.ratios import calculate_all_margins, calculate_debt_to_equity, calculate_roa_roe
```

- [ ] **Step 4: Verify full import chain**

```
conda run -n stock python -c "from orchestrator import process_turn; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```
git add tools/company.py orchestrator.py main.py
git commit -m "feat: wire RatiosAgent into orchestrator, remove yfinance ratios from company_info"
```

---

## Task 7: Run Full Test Suite

- [ ] **Step 1: Run all tests**

```
conda run -n stock pytest tests/test_tools.py -v
```

Expected: All existing tests pass + all new tests pass. No regressions.

- [ ] **Step 2: Quick smoke check — does a ratio question route correctly?**

```
conda run -n stock python -c "
from orchestrator import process_turn
answer, _ = process_turn('What is RKLB debt to equity ratio?', [])
print(answer[:300])
"
```

Expected: Response mentions SEC/balance sheet data (not yfinance). May take 30-60 seconds.

- [ ] **Step 3: Final commit if any fixes were needed**

```
git add -A
git commit -m "fix: test suite clean-up after SEC-only financials refactor"
```

---

## Notes

- `calculate_margin_trend` in CalcAgent is kept as-is — it already reads from the SEC income cache and provides a complementary view. No removal needed.
- The `_keyword_fallback` in orchestrator routes "margin" questions to ratios agent now. The LLM-based plan will also learn this from the updated `PLAN_SYSTEM`.
- Balance sheet from edgar only covers 2 years (it's a point-in-time statement). Income statement covers 3 years. ROA/ROE will show at most 2 years.
- If RKLB has no "long-term debt" label in its balance sheet (it uses "Convertible senior notes, net" + "Long-term borrowings"), `calculate_debt_to_equity` uses patterns `%convertible%notes%` and `%long-term borrowings%` which cover this case.
