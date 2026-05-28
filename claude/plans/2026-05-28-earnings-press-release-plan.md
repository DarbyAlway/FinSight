# 8-K Earnings Press Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `get_earnings_press_release(ticker)` that returns the last 4 quarters of EPS beat/miss history and management guidance to enrich the financials agent.

**Architecture:** yfinance provides EPS actual/estimate for 4 quarters; SEC EDGAR provides guidance text from the most recent 8-K press release. Data is cached in a new `earnings_releases` DuckDB table with a 7-day TTL. The tool is registered in `agents/financials.py` so the LLM can call it for beat/miss and guidance questions.

**Tech Stack:** yfinance, edgartools (`edgar`), DuckDB, Python `unittest.mock`

---

## File Map

| File | Change |
|------|--------|
| `tools/db.py` | Add `earnings_releases` table to `init_db()` + 3 cache helpers |
| `tools/earnings_press.py` | **New** — pure functions + fetchers + public entry point |
| `agents/financials.py` | Add tool definition + wire into `TOOL_FUNCTIONS` |
| `main.py` | Add re-exports for test compatibility |
| `tests/test_tools.py` | Add all tests |

---

### Task 1: `earnings_releases` DB table + cache helpers

**Files:**
- Modify: `tools/db.py`
- Modify: `main.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# Earnings releases DB tests
# ---------------------------------------------------------------------------

def test_init_db_creates_earnings_releases_table():
    from tools.db import init_db
    from tools.config import DB_PATH
    init_db()
    import duckdb
    with duckdb.connect(DB_PATH) as con:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "earnings_releases" in tables


def test_save_and_load_earnings_roundtrip():
    import time
    from tools.db import init_db, save_earnings, load_earnings
    init_db()
    rows = [
        {
            "ticker": "EARNTEST",
            "period_end": "2024-09-30",
            "eps_actual": 1.64,
            "eps_estimate": 1.60,
            "revenue_actual": None,
            "revenue_estimate": None,
            "beat_miss": "beat",
            "guidance_text": "We expect revenue of $89-93B next quarter.",
            "fetched_at": time.time(),
        },
        {
            "ticker": "EARNTEST",
            "period_end": "2024-06-30",
            "eps_actual": 1.40,
            "eps_estimate": 1.45,
            "revenue_actual": None,
            "revenue_estimate": None,
            "beat_miss": "miss",
            "guidance_text": None,
            "fetched_at": time.time(),
        },
    ]
    save_earnings(rows)
    result = load_earnings("EARNTEST")
    assert "EARNTEST Earnings" in result
    assert "BEAT" in result
    assert "MISS" in result
    assert "We expect revenue" in result
    assert "(not available)" in result


def test_is_earnings_fresh_returns_false_when_empty():
    from tools.db import init_db, is_earnings_fresh
    init_db()
    assert is_earnings_fresh("ZZZNOTREAL_EARN") is False


def test_is_earnings_fresh_returns_true_after_save():
    import time
    from tools.db import init_db, save_earnings, is_earnings_fresh
    init_db()
    save_earnings([{
        "ticker": "FRESHTEST",
        "period_end": "2024-09-30",
        "eps_actual": 1.0,
        "eps_estimate": 1.0,
        "revenue_actual": None,
        "revenue_estimate": None,
        "beat_miss": "in-line",
        "guidance_text": None,
        "fetched_at": time.time(),
    }])
    assert is_earnings_fresh("FRESHTEST") is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_tools.py::test_init_db_creates_earnings_releases_table tests/test_tools.py::test_save_and_load_earnings_roundtrip tests/test_tools.py::test_is_earnings_fresh_returns_false_when_empty tests/test_tools.py::test_is_earnings_fresh_returns_true_after_save -v
```

Expected: FAIL with `ImportError` or `cannot import name 'save_earnings'`

- [ ] **Step 3: Add `earnings_releases` table to `init_db()` in `tools/db.py`**

In `tools/db.py`, add `EARNINGS_TTL_DAYS = 7` after the existing `QUARTERLY_TTL_DAYS = 7` line:

```python
EARNINGS_TTL_DAYS = 7
```

Inside `init_db()`, after the `cash_flows` table block, add:

```python
        con.execute("""
            CREATE TABLE IF NOT EXISTS earnings_releases (
                ticker            VARCHAR,
                period_end        VARCHAR,
                eps_actual        DOUBLE,
                eps_estimate      DOUBLE,
                revenue_actual    DOUBLE,
                revenue_estimate  DOUBLE,
                beat_miss         VARCHAR,
                guidance_text     VARCHAR,
                fetched_at        DOUBLE,
                PRIMARY KEY (ticker, period_end)
            )
        """)
```

- [ ] **Step 4: Add the three cache helpers to `tools/db.py`**

Add after `load_cash_flow`:

```python
def is_earnings_fresh(ticker: str) -> bool:
    with duckdb.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT fetched_at FROM earnings_releases WHERE ticker = ? LIMIT 1",
            (ticker,)
        ).fetchone()
    if row is None:
        return False
    return (time.time() - row[0]) / 86400 < EARNINGS_TTL_DAYS


def save_earnings(rows: list[dict]):
    if not rows:
        return
    with duckdb.connect(DB_PATH) as con:
        con.executemany(
            """INSERT OR REPLACE INTO earnings_releases
               (ticker, period_end, eps_actual, eps_estimate, revenue_actual,
                revenue_estimate, beat_miss, guidance_text, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(r["ticker"], r["period_end"], r["eps_actual"], r["eps_estimate"],
              r.get("revenue_actual"), r.get("revenue_estimate"),
              r["beat_miss"], r.get("guidance_text"), r["fetched_at"]) for r in rows],
        )


def load_earnings(ticker: str) -> str:
    with duckdb.connect(DB_PATH) as con:
        rows = con.execute(
            """SELECT period_end, eps_actual, eps_estimate, beat_miss,
                      revenue_actual, guidance_text
               FROM earnings_releases
               WHERE ticker = ?
               ORDER BY period_end DESC
               LIMIT 4""",
            (ticker,)
        ).fetchall()
    if not rows:
        return ""
    lines = [f"{ticker} Earnings (last {len(rows)} quarters)"]
    for period_end, eps_actual, eps_estimate, beat_miss, revenue_actual, guidance_text in rows:
        try:
            from datetime import datetime as _dt
            dt = _dt.strptime(period_end, "%Y-%m-%d")
            label = f"Q{(dt.month - 1) // 3 + 1} {dt.year} ({dt.strftime('%b %d, %Y')})"
        except Exception:
            label = period_end
        pct = ""
        if eps_estimate and eps_estimate != 0:
            pct = f" ({(eps_actual - eps_estimate) / abs(eps_estimate) * 100:+.1f}%)"
        lines.append(f"\n  {label}")
        lines.append(f"    EPS: ${eps_actual:.2f} actual | ${eps_estimate:.2f} estimate | {beat_miss.upper()}{pct}")
        if revenue_actual:
            lines.append(f"    Revenue: ${revenue_actual:,.0f}M actual")
        if guidance_text:
            lines.append(f"    Guidance: \"{guidance_text}\"")
        else:
            lines.append("    Guidance: (not available)")
    return "\n".join(lines)
```

- [ ] **Step 5: Add re-exports to `main.py`**

After the `from tools.db import is_cash_flow_fresh, save_cash_flow, load_cash_flow` line, add:

```python
from tools.db import is_earnings_fresh, save_earnings, load_earnings
```

- [ ] **Step 6: Run tests to verify they pass**

```
pytest tests/test_tools.py::test_init_db_creates_earnings_releases_table tests/test_tools.py::test_save_and_load_earnings_roundtrip tests/test_tools.py::test_is_earnings_fresh_returns_false_when_empty tests/test_tools.py::test_is_earnings_fresh_returns_true_after_save -v
```

Expected: 4 PASSED

- [ ] **Step 7: Commit**

```bash
git add tools/db.py main.py tests/test_tools.py
git commit -m "feat: add earnings_releases DB table and cache helpers (TDD)"
```

---

### Task 2: Pure functions — `_parse_beat_miss` and `_extract_guidance_text`

**Files:**
- Create: `tools/earnings_press.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# earnings_press pure function tests
# ---------------------------------------------------------------------------

def test_parse_beat_miss_beat():
    from tools.earnings_press import _parse_beat_miss
    assert _parse_beat_miss(1.64, 1.60) == "beat"


def test_parse_beat_miss_miss():
    from tools.earnings_press import _parse_beat_miss
    assert _parse_beat_miss(1.50, 1.60) == "miss"


def test_parse_beat_miss_inline():
    from tools.earnings_press import _parse_beat_miss
    assert _parse_beat_miss(1.61, 1.60) == "in-line"  # +0.6% < 2% threshold


def test_parse_beat_miss_zero_estimate():
    from tools.earnings_press import _parse_beat_miss
    assert _parse_beat_miss(1.64, 0) == "in-line"


def test_extract_guidance_text_finds_guidance():
    from tools.earnings_press import _extract_guidance_text
    text = (
        "Revenue was $94B in Q3. "
        "We expect revenue in the range of $89-93 billion for Q4. "
        "Strong demand continues across all segments."
    )
    result = _extract_guidance_text(text)
    assert result is not None
    assert "expect" in result.lower()


def test_extract_guidance_text_finds_outlook():
    from tools.earnings_press import _extract_guidance_text
    text = (
        "Net income increased 12% year-over-year. "
        "Our outlook for fiscal 2025 remains positive with guidance of $6.50-6.80 EPS. "
        "We anticipate continued margin expansion."
    )
    result = _extract_guidance_text(text)
    assert result is not None
    assert len(result) > 0


def test_extract_guidance_text_returns_none_when_no_guidance():
    from tools.earnings_press import _extract_guidance_text
    text = "Revenue was $94B in Q3. Operating income increased 10%. Margins improved."
    result = _extract_guidance_text(text)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_tools.py::test_parse_beat_miss_beat tests/test_tools.py::test_parse_beat_miss_miss tests/test_tools.py::test_parse_beat_miss_inline tests/test_tools.py::test_parse_beat_miss_zero_estimate tests/test_tools.py::test_extract_guidance_text_finds_guidance tests/test_tools.py::test_extract_guidance_text_finds_outlook tests/test_tools.py::test_extract_guidance_text_returns_none_when_no_guidance -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.earnings_press'`

- [ ] **Step 3: Create `tools/earnings_press.py` with the two pure functions**

Create `tools/earnings_press.py`:

```python
import logging
import re
import time

import yfinance as yf
from edgar import Company

from tools.db import is_earnings_fresh, save_earnings, load_earnings


_GUIDANCE_KEYWORDS = ["expect", "guidance", "outlook", "forecast", "anticipate", "project"]


def _parse_beat_miss(actual: float, estimate: float) -> str:
    if not estimate or estimate == 0:
        return "in-line"
    pct = (actual - estimate) / abs(estimate) * 100
    if pct > 2:
        return "beat"
    if pct < -2:
        return "miss"
    return "in-line"


def _extract_guidance_text(text: str) -> str | None:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    found = []
    for sentence in sentences:
        if any(kw in sentence.lower() for kw in _GUIDANCE_KEYWORDS):
            found.append(sentence.strip())
            if len(found) >= 2:
                break
    return " ".join(found) if found else None
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_tools.py::test_parse_beat_miss_beat tests/test_tools.py::test_parse_beat_miss_miss tests/test_tools.py::test_parse_beat_miss_inline tests/test_tools.py::test_parse_beat_miss_zero_estimate tests/test_tools.py::test_extract_guidance_text_finds_guidance tests/test_tools.py::test_extract_guidance_text_finds_outlook tests/test_tools.py::test_extract_guidance_text_returns_none_when_no_guidance -v
```

Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add tools/earnings_press.py tests/test_tools.py
git commit -m "feat: add _parse_beat_miss and _extract_guidance_text pure functions (TDD)"
```

---

### Task 3: `_fetch_yfinance_earnings` and `_fetch_edgar_guidance`

**Files:**
- Modify: `tools/earnings_press.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# earnings_press fetcher tests (real API — requires internet)
# ---------------------------------------------------------------------------

def test_fetch_yfinance_earnings_returns_rows():
    from tools.earnings_press import _fetch_yfinance_earnings
    rows = _fetch_yfinance_earnings("AAPL")
    assert isinstance(rows, list)
    assert len(rows) > 0
    for r in rows:
        assert "ticker" in r and r["ticker"] == "AAPL"
        assert "period_end" in r
        assert "eps_actual" in r
        assert "eps_estimate" in r
        assert r["beat_miss"] in ("beat", "miss", "in-line")


def test_fetch_yfinance_earnings_period_end_is_iso_date():
    from tools.earnings_press import _fetch_yfinance_earnings
    rows = _fetch_yfinance_earnings("MSFT")
    assert len(rows) > 0
    for r in rows:
        # period_end must be parseable as YYYY-MM-DD
        parts = r["period_end"].split("-")
        assert len(parts) == 3 and len(parts[0]) == 4


def test_fetch_edgar_guidance_returns_string_or_none():
    from tools.earnings_press import _fetch_edgar_guidance
    result = _fetch_edgar_guidance("AAPL")
    # Must return a non-empty string or None — never raises
    assert result is None or (isinstance(result, str) and len(result) > 0)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_tools.py::test_fetch_yfinance_earnings_returns_rows tests/test_tools.py::test_fetch_yfinance_earnings_period_end_is_iso_date tests/test_tools.py::test_fetch_edgar_guidance_returns_string_or_none -v
```

Expected: FAIL with `ImportError` (functions not yet defined in `tools/earnings_press.py`)

- [ ] **Step 3: Add `_fetch_yfinance_earnings` and `_fetch_edgar_guidance` to `tools/earnings_press.py`**

Add after `_extract_guidance_text`:

```python
def _fetch_yfinance_earnings(ticker: str) -> list[dict]:
    t = yf.Ticker(ticker)
    try:
        hist = t.earnings_history
    except Exception:
        hist = None

    if hist is None or (hasattr(hist, "empty") and hist.empty):
        return []

    rows = []
    now = time.time()
    for period_end, row in list(hist.iterrows())[:4]:
        eps_actual = float(row.get("epsActual") or 0)
        eps_estimate = float(row.get("epsEstimate") or 0)
        pe_str = str(period_end.date()) if hasattr(period_end, "date") else str(period_end)[:10]
        rows.append({
            "ticker": ticker,
            "period_end": pe_str,
            "eps_actual": eps_actual,
            "eps_estimate": eps_estimate,
            "revenue_actual": None,
            "revenue_estimate": None,
            "beat_miss": _parse_beat_miss(eps_actual, eps_estimate),
            "guidance_text": None,
            "fetched_at": now,
        })
    return rows


def _fetch_edgar_guidance(ticker: str) -> str | None:
    try:
        company = Company(ticker)
        filings = company.get_filings(form="8-K")
        if not filings:
            return None
        filing = filings[0]
        text = str(filing.document)
        return _extract_guidance_text(text)
    except Exception as e:
        logging.warning("_fetch_edgar_guidance failed for %s: %s", ticker, e)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_tools.py::test_fetch_yfinance_earnings_returns_rows tests/test_tools.py::test_fetch_yfinance_earnings_period_end_is_iso_date tests/test_tools.py::test_fetch_edgar_guidance_returns_string_or_none -v
```

Expected: 3 PASSED

> **Note:** If `filing.document` raises an AttributeError, try `str(filing)` instead. EDGAR's Python client exposes 8-K text differently per version. The fallback returns `None` safely regardless.

- [ ] **Step 5: Commit**

```bash
git add tools/earnings_press.py tests/test_tools.py
git commit -m "feat: add _fetch_yfinance_earnings and _fetch_edgar_guidance (TDD)"
```

---

### Task 4: `get_earnings_press_release` — cache logic + full pipeline

**Files:**
- Modify: `tools/earnings_press.py`
- Modify: `main.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# get_earnings_press_release integration tests
# ---------------------------------------------------------------------------

def test_get_earnings_press_release_returns_string():
    from tools.db import init_db
    from tools.earnings_press import get_earnings_press_release
    init_db()
    result = get_earnings_press_release("AAPL")
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_earnings_press_release_contains_beat_miss():
    from tools.db import init_db
    from tools.earnings_press import get_earnings_press_release
    init_db()
    result = get_earnings_press_release("AAPL")
    assert any(word in result.upper() for word in ["BEAT", "MISS", "IN-LINE"])


def test_get_earnings_press_release_cache_hit():
    import time
    from tools.db import init_db, save_earnings, is_earnings_fresh
    from tools.earnings_press import get_earnings_press_release
    init_db()
    save_earnings([{
        "ticker": "CACHEHIT",
        "period_end": "2024-09-30",
        "eps_actual": 2.00,
        "eps_estimate": 1.90,
        "revenue_actual": None,
        "revenue_estimate": None,
        "beat_miss": "beat",
        "guidance_text": "Strong guidance ahead.",
        "fetched_at": time.time(),
    }])
    assert is_earnings_fresh("CACHEHIT") is True
    result = get_earnings_press_release("CACHEHIT")
    assert "CACHEHIT" in result
    assert "BEAT" in result
    assert "Strong guidance ahead" in result


def test_get_earnings_press_release_edgar_failure_still_returns_eps():
    from unittest.mock import patch
    from tools.db import init_db
    from tools.earnings_press import get_earnings_press_release
    init_db()
    with patch("tools.earnings_press._fetch_edgar_guidance", return_value=None):
        result = get_earnings_press_release("MSFT")
    assert isinstance(result, str)
    assert any(word in result.upper() for word in ["BEAT", "MISS", "IN-LINE"])
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_tools.py::test_get_earnings_press_release_returns_string tests/test_tools.py::test_get_earnings_press_release_contains_beat_miss tests/test_tools.py::test_get_earnings_press_release_cache_hit tests/test_tools.py::test_get_earnings_press_release_edgar_failure_still_returns_eps -v
```

Expected: FAIL with `ImportError` (function not yet defined)

- [ ] **Step 3: Add `get_earnings_press_release` to `tools/earnings_press.py`**

Add at the end of the file:

```python
def get_earnings_press_release(ticker: str) -> str:
    try:
        if is_earnings_fresh(ticker):
            logging.info("earnings cache hit: %s", ticker)
            return load_earnings(ticker)

        rows = _fetch_yfinance_earnings(ticker)
        if not rows:
            return (
                f"TOOL_ERROR: No earnings history found for {ticker}. "
                "Do not use training data to answer — tell the user the data is unavailable."
            )

        guidance = _fetch_edgar_guidance(ticker)
        if guidance:
            rows[0]["guidance_text"] = guidance

        save_earnings(rows)
        return load_earnings(ticker)
    except Exception as e:
        stale = load_earnings(ticker)
        if stale:
            return f"[Stale cache] {stale}\n(Refresh failed: {e})"
        return (
            f"TOOL_ERROR: Failed to fetch earnings data for {ticker}: {e}. "
            "Do not use training data to answer — tell the user the data is unavailable."
        )
```

- [ ] **Step 4: Add re-export to `main.py`**

After `from tools.db import is_earnings_fresh, save_earnings, load_earnings`, add:

```python
from tools.earnings_press import get_earnings_press_release
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_tools.py::test_get_earnings_press_release_returns_string tests/test_tools.py::test_get_earnings_press_release_contains_beat_miss tests/test_tools.py::test_get_earnings_press_release_cache_hit tests/test_tools.py::test_get_earnings_press_release_edgar_failure_still_returns_eps -v
```

Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add tools/earnings_press.py main.py tests/test_tools.py
git commit -m "feat: add get_earnings_press_release with cache + EDGAR fallback (TDD)"
```

---

### Task 5: Wire into `agents/financials.py`

**Files:**
- Modify: `agents/financials.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# Financials agent — earnings tool wiring
# ---------------------------------------------------------------------------

def test_financials_agent_has_earnings_tool():
    from agents.financials import TOOLS
    names = [t["function"]["name"] for t in TOOLS]
    assert "get_earnings_press_release" in names


def test_financials_agent_earnings_tool_function_is_wired():
    from agents.financials import TOOL_FUNCTIONS
    assert "get_earnings_press_release" in TOOL_FUNCTIONS
    assert callable(TOOL_FUNCTIONS["get_earnings_press_release"])
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_tools.py::test_financials_agent_has_earnings_tool tests/test_tools.py::test_financials_agent_earnings_tool_function_is_wired -v
```

Expected: FAIL — `assert "get_earnings_press_release" in names`

- [ ] **Step 3: Add the import to `agents/financials.py`**

At the top of `agents/financials.py`, after the existing imports, add:

```python
from tools.earnings_press import get_earnings_press_release
```

- [ ] **Step 4: Add the tool definition to `TOOLS` in `agents/financials.py`**

After the `get_cash_flow_statement` tool dict (before the closing `]` of `TOOLS`), add:

```python
    {
        "type": "function",
        "function": {
            "name": "get_earnings_press_release",
            "description": (
                "Fetch the last 4 quarters of earnings results for a ticker: "
                "EPS actual vs estimate, beat/miss classification, and management guidance text. "
                "Use for: did the company beat expectations, earnings surprise history, "
                "management guidance, analyst estimate vs actual EPS, recent guidance."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
```

- [ ] **Step 5: Add to `TOOL_FUNCTIONS` in `agents/financials.py`**

In the `TOOL_FUNCTIONS` dict, add:

```python
    "get_earnings_press_release": get_earnings_press_release,
```

- [ ] **Step 6: Run tests to verify they pass**

```
pytest tests/test_tools.py::test_financials_agent_has_earnings_tool tests/test_tools.py::test_financials_agent_earnings_tool_function_is_wired -v
```

Expected: 2 PASSED

- [ ] **Step 7: Run the full test suite to check for regressions**

```
pytest tests/test_tools.py tests/test_agents.py -v
```

Expected: All existing tests PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git add agents/financials.py tests/test_tools.py
git commit -m "feat: wire get_earnings_press_release into financials agent (TDD)"
```
