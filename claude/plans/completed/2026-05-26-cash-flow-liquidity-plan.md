# Cash Flow, Liquidity Ratios & Routing Fixes — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cash flow statement fetching + FCF/runway calculations, current ratio + interest coverage, date injection for time-sensitive queries, and routing fixes for cash/liquidity keywords.

**Architecture:** New `tools/cash_flow.py` mirrors the `tools/balance_sheet.py` pattern (parse + fetch + cache). Two new calc tools read from `cash_flows` + `balance_sheets`. Two new ratio tools read from existing `balance_sheets` + `income_statements` — no new fetches needed. Date injection adds a conditional `{today}` prefix to planner/synthesis prompts via `str.replace` (NOT `.format()` — PLAN_SYSTEM contains JSON curly braces that would break `.format()`).

**Tech Stack:** DuckDB (cash_flows table), edgar `Company.get_financials().cash_flow_statement()`, Python re for parsing, ollama for LLM calls.

---

## File Map

| File | Change |
|---|---|
| `tools/db.py` | Add `cash_flows` table + `is_cash_flow_fresh`, `save_cash_flow`, `load_cash_flow` |
| `tools/cash_flow.py` | Create: `parse_cash_flow`, `get_cash_flow_statement` |
| `tools/calc.py` | Add: `calculate_free_cash_flow`, `calculate_cash_runway` |
| `tools/ratios.py` | Add: `calculate_current_ratio`, `calculate_interest_coverage` |
| `agents/financials.py` | Add `get_cash_flow_statement` tool |
| `agents/calc.py` | Add `calculate_free_cash_flow`, `calculate_cash_runway` tools (→ 11 tools total) |
| `agents/ratios.py` | Add `calculate_current_ratio`, `calculate_interest_coverage` tools (→ 6 tools total) |
| `main.py` | Add re-exports for tests |
| `orchestrator.py` | Add `_is_time_sensitive`, `_TIME_SENSITIVE_KEYWORDS`, update `process_turn`, `_FINANCIAL_KEYWORDS`, `_keyword_fallback` |
| `prompts.py` | Add `{today}` slot to `PLAN_SYSTEM` + `SYNTHESIS_SYSTEM`, update agent descriptions |
| `tests/test_tools.py` | Add 12 new tests |

---

## Task 1: `cash_flows` DB Table + Helpers

**Files:**
- Modify: `tools/db.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the 3 failing tests**

Add to the end of `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# Cash flow DB tests
# ---------------------------------------------------------------------------

def test_init_db_creates_cash_flows_table():
    from main import init_db, DB_PATH
    init_db()
    import duckdb
    with duckdb.connect(DB_PATH) as con:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "cash_flows" in tables


def test_save_and_load_cash_flow_roundtrip():
    import time
    from tools.db import init_db, save_cash_flow, load_cash_flow
    init_db()
    rows = [
        {"ticker": "CFTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Operating Activities",
         "line_item": "Net cash provided by operating activities",
         "value": 200.0, "fetched_at": time.time()},
        {"ticker": "CFTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Investing Activities",
         "line_item": "Purchases of property, plant and equipment",
         "value": -50.0, "fetched_at": time.time()},
    ]
    save_cash_flow(rows)
    result = load_cash_flow("CFTEST")
    assert "Net cash provided by operating activities" in result
    assert "200" in result
    assert "Operating Activities" in result
    assert "Investing Activities" in result


def test_is_cash_flow_fresh_returns_false_when_empty():
    from tools.db import init_db, is_cash_flow_fresh
    init_db()
    assert is_cash_flow_fresh("ZZZNOTREAL_CF") is False
```

- [ ] **Step 2: Run to verify they fail**

```
conda run -n stock python -m pytest tests/test_tools.py::test_init_db_creates_cash_flows_table tests/test_tools.py::test_save_and_load_cash_flow_roundtrip tests/test_tools.py::test_is_cash_flow_fresh_returns_false_when_empty -v
```

Expected: 3 FAILs — `assert "cash_flows" in tables` fails, `save_cash_flow` not found, `is_cash_flow_fresh` not found.

- [ ] **Step 3: Add `cash_flows` table to `init_db()`**

In `tools/db.py`, inside `init_db()` after the `balance_sheets` CREATE TABLE block, add:

```python
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
```

- [ ] **Step 4: Add 3 helpers to `tools/db.py`**

Add after the `load_balance_sheet` function (end of file):

```python
def is_cash_flow_fresh(ticker: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
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
    with duckdb.connect(DB_PATH) as con:
        con.executemany(
            """INSERT OR REPLACE INTO cash_flows
               (ticker, fiscal_year, section, line_item, value, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["fiscal_year"], r["section"],
              r["line_item"], r["value"], r["fetched_at"]) for r in rows],
        )


def load_cash_flow(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        rows = con.execute(
            """SELECT fiscal_year, section, line_item, value FROM cash_flows
               WHERE ticker = ?
               ORDER BY fiscal_year DESC,
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
```

- [ ] **Step 5: Run tests to verify they pass**

```
conda run -n stock python -m pytest tests/test_tools.py::test_init_db_creates_cash_flows_table tests/test_tools.py::test_save_and_load_cash_flow_roundtrip tests/test_tools.py::test_is_cash_flow_fresh_returns_false_when_empty -v
```

Expected: 3 PASSes.

- [ ] **Step 6: Commit**

```
git add tools/db.py tests/test_tools.py
git commit -m "feat: add cash_flows DB table and helpers (TDD)"
```

---

## Task 2: Cash Flow Parser + Fetcher

**Files:**
- Create: `tools/cash_flow.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the 3 failing parser tests**

Add to the end of `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# Cash flow parser tests
# ---------------------------------------------------------------------------

_SAMPLE_CF = (
    "                                               Sep 27, 2025  Sep 28, 2024\n"
    "   ────────────────────────────────────────────────────────\n"
    "    Cash flows from operating activities:\n"
    "          Net income                                 $100,000       $80,000\n"
    "          Depreciation and amortization               $20,000       $18,000\n"
    "          Net cash provided by operating activities  $120,000       $98,000\n"
    "    Cash flows from investing activities:\n"
    "          Purchases of property, plant and equipment  $(30,000)     $(25,000)\n"
    "          Net cash used in investing activities        $(30,000)     $(25,000)\n"
    "    Cash flows from financing activities:\n"
    "          Proceeds from long-term debt issuance        $50,000       $10,000\n"
    "          Net cash from financing activities           $50,000       $10,000\n"
    "   Source: SEC XBRL  •  (In thousands)\n"
)


def test_parse_cash_flow_extracts_rows():
    from tools.cash_flow import parse_cash_flow
    rows = parse_cash_flow("RKLB", _SAMPLE_CF)
    assert len(rows) > 0
    items = [r["line_item"] for r in rows]
    assert "Net income" in items
    assert any("operating activities" in i.lower() for i in items)


def test_parse_cash_flow_three_sections():
    from tools.cash_flow import parse_cash_flow
    rows = parse_cash_flow("RKLB", _SAMPLE_CF)
    sections = {r["section"] for r in rows}
    assert "Operating Activities" in sections
    assert "Investing Activities" in sections
    assert "Financing Activities" in sections


def test_parse_cash_flow_applies_thousands_multiplier():
    from tools.cash_flow import parse_cash_flow
    sample = (
        "                                   Sep 27, 2025\n"
        "    Cash flows from operating activities:\n"
        "          Net cash from operations  $120,000\n"
        "   Source: SEC XBRL  •  (In thousands)\n"
    )
    rows = parse_cash_flow("TEST", sample)
    assert len(rows) > 0
    # $120,000 thousands = $120M stored
    assert rows[0]["value"] == 120.0
```

- [ ] **Step 2: Run to verify they fail**

```
conda run -n stock python -m pytest tests/test_tools.py::test_parse_cash_flow_extracts_rows tests/test_tools.py::test_parse_cash_flow_three_sections tests/test_tools.py::test_parse_cash_flow_applies_thousands_multiplier -v
```

Expected: 3 FAILs — `ModuleNotFoundError: No module named 'tools.cash_flow'`.

- [ ] **Step 3: Create `tools/cash_flow.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
conda run -n stock python -m pytest tests/test_tools.py::test_parse_cash_flow_extracts_rows tests/test_tools.py::test_parse_cash_flow_three_sections tests/test_tools.py::test_parse_cash_flow_applies_thousands_multiplier -v
```

Expected: 3 PASSes.

- [ ] **Step 5: Commit**

```
git add tools/cash_flow.py tests/test_tools.py
git commit -m "feat: add cash flow parser and fetcher with SEC edgar (TDD)"
```

---

## Task 3: FCF and Cash Runway Tools

**Files:**
- Modify: `tools/calc.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the 2 failing tests**

Add to the end of `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# FCF and cash runway tests
# ---------------------------------------------------------------------------

def test_calculate_free_cash_flow_from_cache():
    import time
    from tools.db import init_db, save_cash_flow
    from tools.calc import calculate_free_cash_flow
    init_db()
    save_cash_flow([
        {"ticker": "FCFTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Operating Activities",
         "line_item": "Net cash provided by operating activities",
         "value": 200.0, "fetched_at": time.time()},
        {"ticker": "FCFTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Investing Activities",
         "line_item": "Purchases of property, plant and equipment",
         "value": -50.0, "fetched_at": time.time()},
        {"ticker": "FCFTEST", "fiscal_year": "Dec 31, 2024",
         "section": "Operating Activities",
         "line_item": "Net cash provided by operating activities",
         "value": 150.0, "fetched_at": time.time()},
        {"ticker": "FCFTEST", "fiscal_year": "Dec 31, 2024",
         "section": "Investing Activities",
         "line_item": "Purchases of property, plant and equipment",
         "value": -40.0, "fetched_at": time.time()},
    ])
    result = calculate_free_cash_flow("FCFTEST")
    # 2025 FCF = 200 + (-50) = 150, 2024 FCF = 150 + (-40) = 110
    assert "150" in result
    assert "Dec 31, 2025" in result


def test_calculate_cash_runway_from_cache():
    import time
    from tools.db import init_db, save_cash_flow, save_balance_sheet
    from tools.calc import calculate_cash_runway
    init_db()
    save_balance_sheet([
        {"ticker": "RUNWAY", "fiscal_year": "Dec 31, 2025",
         "section": "Assets",
         "line_item": "Cash and cash equivalents",
         "value": 600.0, "fetched_at": time.time()},
    ])
    save_cash_flow([
        {"ticker": "RUNWAY", "fiscal_year": "Dec 31, 2025",
         "section": "Operating Activities",
         "line_item": "Net cash used in operating activities",
         "value": -120.0, "fetched_at": time.time()},
        {"ticker": "RUNWAY", "fiscal_year": "Dec 31, 2025",
         "section": "Investing Activities",
         "line_item": "Purchases of property, plant and equipment",
         "value": -80.0, "fetched_at": time.time()},
    ])
    result = calculate_cash_runway("RUNWAY")
    # FCF = -120 + (-80) = -200 annual burn
    # Runway = 600 / 200 * 12 = 36 months
    assert "36" in result
    assert "600" in result
```

- [ ] **Step 2: Run to verify they fail**

```
conda run -n stock python -m pytest tests/test_tools.py::test_calculate_free_cash_flow_from_cache tests/test_tools.py::test_calculate_cash_runway_from_cache -v
```

Expected: 2 FAILs — `ImportError: cannot import name 'calculate_free_cash_flow'`.

- [ ] **Step 3: Add `calculate_free_cash_flow` to `tools/calc.py`**

Add after the `calculate_dcf` function, before `SECTOR_PEERS`:

```python
def calculate_free_cash_flow(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        op_rows = con.execute(
            """SELECT fiscal_year, value FROM cash_flows
               WHERE ticker = ?
               AND (lower(line_item) LIKE '%operating activities%'
                    OR lower(line_item) LIKE '%cash from operations%')
               ORDER BY fiscal_year DESC LIMIT 2""",
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
                    OR lower(line_item) LIKE '%purchases of property%')
               ORDER BY fiscal_year DESC LIMIT 2""",
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
```

- [ ] **Step 4: Add `calculate_cash_runway` to `tools/calc.py`**

Add immediately after `calculate_free_cash_flow`:

```python
def calculate_cash_runway(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        cash_rows = con.execute(
            """SELECT fiscal_year, value FROM balance_sheets
               WHERE ticker = ?
               AND lower(line_item) LIKE '%cash and cash equivalents%'
               ORDER BY fiscal_year DESC LIMIT 1""",
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
               ORDER BY fiscal_year DESC LIMIT 2""",
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
                    OR lower(line_item) LIKE '%purchases of property%')
               ORDER BY fiscal_year DESC LIMIT 2""",
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
```

- [ ] **Step 5: Run tests to verify they pass**

```
conda run -n stock python -m pytest tests/test_tools.py::test_calculate_free_cash_flow_from_cache tests/test_tools.py::test_calculate_cash_runway_from_cache -v
```

Expected: 2 PASSes.

- [ ] **Step 6: Commit**

```
git add tools/calc.py tests/test_tools.py
git commit -m "feat: add calculate_free_cash_flow and calculate_cash_runway (TDD)"
```

---

## Task 4: Current Ratio + Interest Coverage

**Files:**
- Modify: `tools/ratios.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the 2 failing tests**

Add to the end of `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# Liquidity ratio tests
# ---------------------------------------------------------------------------

def test_calculate_current_ratio_from_cache():
    import time
    from tools.db import init_db, save_balance_sheet
    from tools.ratios import calculate_current_ratio
    init_db()
    save_balance_sheet([
        {"ticker": "CRTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Assets",
         "line_item": "Total current assets",
         "value": 300.0, "fetched_at": time.time()},
        {"ticker": "CRTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Liabilities",
         "line_item": "Total current liabilities",
         "value": 200.0, "fetched_at": time.time()},
    ])
    result = calculate_current_ratio("CRTEST")
    assert "1.50" in result  # 300 / 200 = 1.50
    assert "Dec 31, 2025" in result


def test_calculate_interest_coverage_from_cache():
    import time
    from tools.db import init_db, save_to_cache
    from tools.ratios import calculate_interest_coverage
    init_db()
    save_to_cache([
        {"ticker": "ICTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Operating",
         "line_item": "Operating income",
         "value": 300.0, "fetched_at": time.time()},
        {"ticker": "ICTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Other",
         "line_item": "Interest expense",
         "value": -60.0, "fetched_at": time.time()},
    ])
    result = calculate_interest_coverage("ICTEST")
    assert "5.0x" in result  # 300 / 60 = 5.0x
```

- [ ] **Step 2: Run to verify they fail**

```
conda run -n stock python -m pytest tests/test_tools.py::test_calculate_current_ratio_from_cache tests/test_tools.py::test_calculate_interest_coverage_from_cache -v
```

Expected: 2 FAILs — `ImportError: cannot import name 'calculate_current_ratio'`.

- [ ] **Step 3: Add `calculate_current_ratio` to `tools/ratios.py`**

Add after `calculate_roa_roe`:

```python
def calculate_current_ratio(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        fy_row = con.execute(
            "SELECT fiscal_year FROM balance_sheets WHERE ticker = ? ORDER BY fiscal_year DESC LIMIT 1",
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
```

- [ ] **Step 4: Add `calculate_interest_coverage` to `tools/ratios.py`**

Add after `calculate_current_ratio`. Note: this function also needs `import duckdb` and `from tools.config import DB_PATH` at the top of `ratios.py` — both are already imported.

```python
def calculate_interest_coverage(ticker: str) -> str:
    ebit_rows = fuzzy_query(ticker, "operating income")
    if not ebit_rows:
        return f"ERROR: No operating income data for {ticker} — call get_income_statement first."

    with duckdb.connect(DB_PATH) as con:
        interest_rows = con.execute(
            """SELECT fiscal_year, value FROM income_statements
               WHERE ticker = ?
               AND lower(line_item) LIKE '%interest expense%'
               ORDER BY fiscal_year DESC LIMIT 2""",
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
```

- [ ] **Step 5: Run tests to verify they pass**

```
conda run -n stock python -m pytest tests/test_tools.py::test_calculate_current_ratio_from_cache tests/test_tools.py::test_calculate_interest_coverage_from_cache -v
```

Expected: 2 PASSes.

- [ ] **Step 6: Commit**

```
git add tools/ratios.py tests/test_tools.py
git commit -m "feat: add calculate_current_ratio and calculate_interest_coverage (TDD)"
```

---

## Task 5: Wire New Tools Into Agents + main.py Re-exports

**Files:**
- Modify: `agents/financials.py`, `agents/calc.py`, `agents/ratios.py`, `main.py`

No new tests — agent integration is tested manually.

- [ ] **Step 1: Add `get_cash_flow_statement` to `agents/financials.py`**

After the existing imports at the top of `agents/financials.py`, add:

```python
from tools.cash_flow import get_cash_flow_statement
```

Add to the `TOOLS` list (after the `get_company_info` tool entry):

```python
    {
        "type": "function",
        "function": {
            "name": "get_cash_flow_statement",
            "description": (
                "Fetch the latest 2-year cash flow statement for a ticker from SEC 10-K filings. "
                "Use for: operating cash flow, capex, investing activities, financing activities, "
                "cash burn, free cash flow inputs."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
```

Add to `TOOL_FUNCTIONS`:

```python
    "get_cash_flow_statement": get_cash_flow_statement,
```

- [ ] **Step 2: Add FCF tools to `agents/calc.py`**

In `agents/calc.py`, update the import from `tools.calc`:

```python
from tools.calc import (
    calculate_dcf, calculate_peg, calculate_pe_vs_sector,
    calculate_revenue_cagr, calculate_margin_trend, calculate_yoy,
    calculate_correlation, rank_tickers,
    calculate_free_cash_flow, calculate_cash_runway,
)
```

Add to the `TOOLS` list (after the `get_price_history` entry):

```python
    {"type": "function", "function": {
        "name": "calculate_free_cash_flow",
        "description": (
            "Calculate free cash flow (operating cash flow minus capex) from SEC 10-K data. "
            "Call get_cash_flow_statement first. Shows last 2 fiscal years."
        ),
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    }},
    {"type": "function", "function": {
        "name": "calculate_cash_runway",
        "description": (
            "Estimate months of cash runway using cash balance (balance sheet) and FCF burn rate. "
            "Call get_balance_sheet AND get_cash_flow_statement first."
        ),
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    }},
```

Add to `TOOL_FUNCTIONS`:

```python
    "calculate_free_cash_flow": calculate_free_cash_flow,
    "calculate_cash_runway": calculate_cash_runway,
```

- [ ] **Step 3: Add liquidity ratio tools to `agents/ratios.py`**

In `agents/ratios.py`, update the import from `tools.ratios`:

```python
from tools.ratios import (
    calculate_all_margins, calculate_debt_to_equity, calculate_roa_roe,
    calculate_current_ratio, calculate_interest_coverage,
)
```

Add to the `TOOLS` list (after the `calculate_roa_roe` entry):

```python
    {
        "type": "function",
        "function": {
            "name": "calculate_current_ratio",
            "description": (
                "Compute current ratio (current assets / current liabilities) from SEC balance sheet. "
                "Call get_balance_sheet first. > 1.5 = healthy, < 1.0 = liquidity risk."
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
            "name": "calculate_interest_coverage",
            "description": (
                "Compute interest coverage ratio (EBIT / interest expense) from SEC income statement. "
                "Call get_income_statement first. > 3x = comfortable, < 1.5x = solvency risk."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
```

Add to `TOOL_FUNCTIONS`:

```python
    "calculate_current_ratio": calculate_current_ratio,
    "calculate_interest_coverage": calculate_interest_coverage,
```

Also update `RATIOS_SYSTEM` instructions in `prompts.py` to mention the new tools (do this in Task 7 with the other prompts changes).

- [ ] **Step 4: Add re-exports to `main.py`**

After the existing ratios re-export line in `main.py`:

```python
from tools.ratios import calculate_all_margins, calculate_debt_to_equity, calculate_roa_roe
```

Add:

```python
from tools.db import is_cash_flow_fresh, save_cash_flow, load_cash_flow
from tools.cash_flow import parse_cash_flow, get_cash_flow_statement
from tools.calc import calculate_free_cash_flow, calculate_cash_runway
from tools.ratios import calculate_current_ratio, calculate_interest_coverage
```

- [ ] **Step 5: Run the full test suite to catch import errors**

```
conda run -n stock python -m pytest tests/test_tools.py -v --tb=short 2>&1 | head -60
```

Expected: all previously-passing tests still pass. No import errors on the new functions.

- [ ] **Step 6: Commit**

```
git add agents/financials.py agents/calc.py agents/ratios.py main.py
git commit -m "feat: wire cash flow, FCF, runway, current ratio, interest coverage into agents"
```

---

## Task 6: Date Injection

**Files:**
- Modify: `orchestrator.py`, `prompts.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the 2 failing tests**

Add to the end of `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# Date injection tests
# ---------------------------------------------------------------------------

def test_is_time_sensitive_detects_keywords():
    from orchestrator import _is_time_sensitive
    assert _is_time_sensitive("What is the latest news about RKLB?") is True
    assert _is_time_sensitive("What is RKLB's current cash burn?") is True
    assert _is_time_sensitive("What were Q3 earnings?") is True
    assert _is_time_sensitive("How much runway does RKLB have today?") is True


def test_is_time_sensitive_returns_false_for_neutral():
    from orchestrator import _is_time_sensitive
    assert _is_time_sensitive("What is the P/E ratio of AAPL?") is False
    assert _is_time_sensitive("Compare revenue of AAPL and MSFT") is False
    assert _is_time_sensitive("Calculate DCF for NVDA") is False
```

- [ ] **Step 2: Run to verify they fail**

```
conda run -n stock python -m pytest tests/test_tools.py::test_is_time_sensitive_detects_keywords tests/test_tools.py::test_is_time_sensitive_returns_false_for_neutral -v
```

Expected: 2 FAILs — `ImportError: cannot import name '_is_time_sensitive'`.

- [ ] **Step 3: Add `_TIME_SENSITIVE_KEYWORDS` and `_is_time_sensitive` to `orchestrator.py`**

Add after the `_TICKER_RE` line (after `_re.compile`):

```python
_TIME_SENSITIVE_KEYWORDS = {
    "today", "now", "current", "currently", "latest", "recent", "recently",
    "new", "newest", "updated", "just", "fresh",
    "this year", "this quarter", "this month", "this week",
    "last year", "last quarter", "last month", "last week",
    "past year", "past quarter", "past month",
    "previous year", "previous quarter",
    "prior year", "prior quarter",
    "ytd", "ttm", "trailing",
    "2026", "2025", "2024",
    "q1", "q2", "q3", "q4",
    "earnings", "report", "reported", "filing", "filed",
    "announced", "announcement", "released", "release",
    "guidance", "outlook", "forecast", "projection", "estimate",
    "beat", "miss", "surprise",
    "next", "upcoming", "future", "projected",
    "rally", "surge", "drop", "crash", "spike", "fell", "rose",
    "momentum", "trend", "trending",
    "runway", "burn", "burn rate", "liquidity",
    "how old", "stale", "outdated", "when was",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}


def _is_time_sensitive(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _TIME_SENSITIVE_KEYWORDS)
```

- [ ] **Step 4: Update `process_turn` in `orchestrator.py`**

Add `from datetime import date` to the top imports block.

In `process_turn`, replace:

```python
    planning_messages = [
        {"role": "system", "content": PLAN_SYSTEM},
```

with:

```python
    today_str = date.today().strftime("%B %d, %Y") if _is_time_sensitive(user_input) else ""
    today_prefix = f"Today is {today_str}. " if today_str else ""
    plan_sys = PLAN_SYSTEM.replace("{today}", today_prefix)
    synth_sys = (persona_system or SYNTHESIS_SYSTEM).replace("{today}", today_prefix)

    planning_messages = [
        {"role": "system", "content": plan_sys},
```

Also replace the synthesis system call later in `process_turn`:

```python
    synthesis_system = persona_system or SYNTHESIS_SYSTEM
```

with:

```python
    synthesis_system = synth_sys
```

- [ ] **Step 5: Add `{today}` slot to `prompts.py`**

In `prompts.py`, update `PLAN_SYSTEM` first line:

```python
PLAN_SYSTEM = (
    "{today}You are a stock analysis orchestrator. Given the user's question, output a JSON plan "
```

Update `SYNTHESIS_SYSTEM` first line:

```python
SYNTHESIS_SYSTEM = (
    "{today}You are a stock analysis assistant. "
```

- [ ] **Step 6: Run tests to verify they pass**

```
conda run -n stock python -m pytest tests/test_tools.py::test_is_time_sensitive_detects_keywords tests/test_tools.py::test_is_time_sensitive_returns_false_for_neutral -v
```

Expected: 2 PASSes.

- [ ] **Step 7: Commit**

```
git add orchestrator.py prompts.py tests/test_tools.py
git commit -m "feat: inject today's date for time-sensitive queries (TDD)"
```

---

## Task 7: Routing Fixes + PLAN_SYSTEM Description Updates

**Files:**
- Modify: `orchestrator.py`, `prompts.py`

No new tests — routing verification is done via manual testing.

- [ ] **Step 1: Update `_FINANCIAL_KEYWORDS` in `orchestrator.py`**

Replace the existing `_FINANCIAL_KEYWORDS` set with:

```python
_FINANCIAL_KEYWORDS = {
    "revenue", "income", "earnings", "profit", "loss", "sales", "margin",
    "cagr", "dcf", "peg", "valuation", "p/e", "pe ratio", "eps",
    "news", "headline", "article", "filing", "10-k", "10-q",
    "stock", "share", "price", "dividend", "sector", "analyst",
    "correlation", "rank", "compare", "quarterly", "annual",
    "debt", "equity", "roa", "roe", "balance sheet",
    "cash", "burn", "runway", "liquidity", "free cash flow", "fcf",
    "cash flow", "operating cash", "capex", "interest coverage",
    "current ratio", "price target", "target price",
}
```

- [ ] **Step 2: Update `_keyword_fallback` in `orchestrator.py`**

Replace the existing `_keyword_fallback` function with:

```python
def _keyword_fallback(question: str) -> list[str]:
    q = question.lower()
    if any(w in q for w in ["news", "headline", "article", "latest"]):
        return ["news"]
    if any(w in q for w in ["p/e", "pe ratio", "price to earnings", "price-to-earnings", "trailing pe", "forward pe"]):
        return ["financials"]
    if any(w in q for w in ["cash flow", "cash burn", "fcf", "free cash flow", "runway"]):
        return ["financials", "calc"]
    if any(w in q for w in ["current ratio", "interest coverage", "liquidity ratio"]):
        return ["ratios"]
    if any(w in q for w in ["price target", "target price", "analyst target"]):
        return ["financials"]
    if any(w in q for w in ["debt", "equity ratio", "d/e", "roa", "roe", "return on"]):
        return ["ratios"]
    if any(w in q for w in ["margin", "profit margin", "gross margin"]):
        return ["ratios"]
    if any(w in q for w in ["dcf", "cagr", "correlation", "peg", "rank", "valuation", "calculate"]):
        return ["calc"]
    return ["financials"]
```

- [ ] **Step 3: Update `PLAN_SYSTEM` agent descriptions in `prompts.py`**

Replace the `PLAN_SYSTEM` string with:

```python
PLAN_SYSTEM = (
    "{today}You are a stock analysis orchestrator. Given the user's question, output a JSON plan "
    "with the agents to call and the tickers involved. "
    "Available agents: "
    "'financials' (income statements, quarterly results, company market info, P/E ratio, EPS, "
    "market cap, beta, cash flow statement, operating cash flow, capex — "
    "use for any question involving stock price or market-based metrics), "
    "'news' (headlines, news search), "
    "'calc' (valuation: DCF, PEG, CAGR, YoY growth, price correlation, sector P/E, "
    "free cash flow (FCF), cash burn rate, cash runway — requires financials agent to run first for cash flow data), "
    "'ratios' (SEC-sourced financial ratios: profit/gross/operating margins, debt-to-equity, ROA, ROE, "
    "current ratio, interest coverage ratio — "
    "always prefer 'ratios' over 'financials' for these metrics; "
    "NOTE: 'ratios' does NOT handle P/E ratio — P/E requires a live stock price, use 'financials' instead). "
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
```

- [ ] **Step 4: Update `RATIOS_SYSTEM` in `prompts.py`**

Replace `RATIOS_SYSTEM` with:

```python
RATIOS_SYSTEM = (
    "You are a financial ratios agent. Compute accurate financial ratios using data sourced "
    "directly from SEC 10-K filings — never from yfinance. "
    "When asked for debt-to-equity, ROA, or ROE: call get_balance_sheet first, then the matching calculate_ tool. "
    "When asked for profit, gross, or operating margins: call calculate_all_margins "
    "(call get_income_statement first if the cache may be empty). "
    "When asked for current ratio: call get_balance_sheet first, then calculate_current_ratio. "
    "When asked for interest coverage: call get_income_statement first, then calculate_interest_coverage. "
    "Always cite the fiscal year and confirm the source is SEC filings."
)
```

Also update `CALC_SYSTEM` in `prompts.py` to mention the new tools:

```python
CALC_SYSTEM = (
    "You are a financial calculation agent. Compute stock metrics using your tools. "
    "Always show the assumptions you used (e.g. discount rate, growth rate). "
    "If data is missing, return the error string from the tool — do not guess. "
    "Do not re-fetch data that is already present in the context you received. "
    "NOTE: For profit margin, gross margin, debt-to-equity, ROA, ROE, current ratio, interest coverage — "
    "these are handled by the ratios agent, not this agent. Do not attempt to compute them here. "
    "Use calculate_margin_trend when the user wants to see how margins have changed over multiple years (trend view). "
    "For FCF and cash runway: call get_cash_flow_statement (via context from financials agent) first, "
    "then calculate_free_cash_flow or calculate_cash_runway. "
    "For a single-point margin value, defer to the ratios agent."
)
```

- [ ] **Step 5: Run full test suite**

```
conda run -n stock python -m pytest tests/test_tools.py -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```
git add orchestrator.py prompts.py
git commit -m "feat: routing fixes for cash/liquidity keywords, update PLAN_SYSTEM descriptions"
```

---

## Final Verification

- [ ] **Run full test suite one last time**

```
conda run -n stock python -m pytest tests/test_tools.py -v
```

Expected: all tests pass (existing + 12 new).

- [ ] **Smoke test manually** — start the app and ask:
  - "What is RKLB's free cash flow?"  → should call financials + calc agents
  - "What is RKLB's current ratio?"  → should call ratios agent
  - "What is the latest news about RKLB?"  → should include date in system prompt

```
conda run -n stock python main.py
```
