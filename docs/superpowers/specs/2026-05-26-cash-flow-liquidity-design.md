# Cash Flow Statement, Liquidity Ratios & Routing Fixes — Phase 1 Design

**Date:** 2026-05-26  
**Branch:** feature/multi-agent-architecture  
**Status:** Approved for implementation

---

## Motivation

Three problems surfaced during testing:

1. **Wrong cash burn numbers** — when asked about RKLB cash burn, the orchestrator detected no financial keywords (`"cash"`, `"burn"` were missing from `_FINANCIAL_KEYWORDS`), called no agents, and the model answered from training data. Our balance sheet only shows year-end cash balance — not how fast it's being burned. The cash flow statement (SEC 10-K/10-Q) is the correct source.

2. **Liquidity ratios missing** — current ratio and interest coverage are commonly asked metrics. Current ratio is derivable from our existing `balance_sheets` table. Interest coverage is derivable from our existing `income_statements` table. No new fetches needed.

3. **No date context** — the model doesn't know today's date, so "latest news" or "recent results" are ambiguous. Injecting the date conditionally (only for time-sensitive queries) solves this with negligible latency overhead.

---

## Scope — Phase 1

| Component | Files |
|---|---|
| New DB table + helpers | `tools/db.py` |
| Cash flow parser + fetcher | `tools/cash_flow.py` (new) |
| FCF + cash runway tools | `tools/calc.py` |
| Liquidity ratio tools | `tools/ratios.py` |
| Date injection | `orchestrator.py`, `prompts.py` |
| Agent wiring | `agents/financials.py`, `agents/calc.py`, `agents/ratios.py` |
| Routing fixes | `orchestrator.py` |
| Tests | `tests/test_tools.py` |
| Re-exports | `main.py` |

**Out of scope (Phase 2):** Analyst price targets, P/S ratio, P/B ratio (all yfinance-based, independent of this work).

**Out of scope (Phase 3):** Provider abstraction — see note at bottom.

---

## Section 1: Cash Flow Statement

### DB (`tools/db.py`)

New table `cash_flows` — identical schema to `balance_sheets`:

```sql
CREATE TABLE IF NOT EXISTS cash_flows (
    ticker      VARCHAR,
    fiscal_year VARCHAR,
    section     VARCHAR,
    line_item   VARCHAR,
    value       DOUBLE,
    fetched_at  DOUBLE,
    PRIMARY KEY (ticker, fiscal_year, section, line_item)
)
```

Three helpers added to `tools/db.py`:
- `is_cash_flow_fresh(ticker)` — same TTL as balance sheet (90 days)
- `save_cash_flow(rows)`
- `load_cash_flow(ticker)` — formats grouped by fiscal year → section → line item

### Parser + Fetcher (`tools/cash_flow.py`)

Same pattern as `tools/balance_sheet.py`:

```python
def parse_cash_flow(ticker, raw) -> list[dict]
def get_cash_flow_statement(ticker) -> str
```

Edgar call:
```python
company = Company(ticker)
financials = company.get_financials()
raw = str(financials.cash_flow_statement())
```

Three sections parsed from the statement:
- **Operating Activities** — net cash from/used in operations
- **Investing Activities** — capex, acquisitions, asset sales
- **Financing Activities** — debt issuance/repayment, share issuance/buybacks

Parser logic: same dollar regex, same unit multiplier detection, same section tracking as `balance_sheet.py`.

---

## Section 2: FCF and Cash Runway (`tools/calc.py`)

### `calculate_free_cash_flow(ticker)`

Reads from `cash_flows` table:
- Operating cash flow: line item containing `%operating activities%` or `%cash from operations%`
- Capex: line item containing `%capital expenditure%` or `%purchases of property%`
- FCF = operating cash flow − |capex|
- Shows last 2 fiscal years

### `calculate_cash_runway(ticker)`

Combines two tables:
- Cash balance: from `balance_sheets` (`%cash and cash equivalents%`)
- Annual burn: from FCF (if FCF is negative, that IS the burn rate)
- Runway = cash balance / |annual FCF burn| in months
- Output includes caveat if burn rate is inconsistent year-over-year

Both tools go into `agents/calc.py` (consistent with DCF, PEG — derived calculations).

**Data dependency:** `calculate_cash_runway` reads from both `cash_flows` AND `balance_sheets`. `CALC_SYSTEM` prompt must instruct the agent to call `get_cash_flow_statement` (and `get_balance_sheet` if not already in context) before calling FCF or runway tools — same pattern as RATIOS_SYSTEM telling the agent to call `get_balance_sheet` before D/E calculations.

---

## Section 3: Liquidity Ratios (`tools/ratios.py`)

Both derivable from existing DuckDB tables — no new fetches.

### `calculate_current_ratio(ticker)`

From `balance_sheets`:
- Current assets: `%total current assets%`
- Current liabilities: `%total current liabilities%`
- Current ratio = current assets / current liabilities
- > 1.5 = healthy, < 1.0 = potential short-term liquidity risk

### `calculate_interest_coverage(ticker)`

From `income_statements`:
- EBIT: operating income (`%operating income%` or `%income from operations%`)
- Interest expense: `%interest expense%`
- Coverage = EBIT / interest expense
- > 3x = comfortable, < 1.5x = potential solvency risk

Both go into `agents/ratios.py` (SEC-sourced, same as D/E and ROA/ROE). Ratios agent reaches 6 tools — well under the 10-tool reliability limit.

---

## Section 4: Date Injection (`orchestrator.py`, `prompts.py`)

### Time-sensitivity detection

New function in `orchestrator.py`:

```python
_TIME_SENSITIVE_KEYWORDS = {
    # Explicit time references
    "today", "now", "current", "currently", "latest", "recent", "recently",
    "new", "newest", "updated", "just", "fresh",
    # Relative periods
    "this year", "this quarter", "this month", "this week",
    "last year", "last quarter", "last month", "last week",
    "past year", "past quarter", "past month",
    "previous year", "previous quarter",
    "prior year", "prior quarter",
    "ytd", "ttm", "trailing",
    # Specific years
    "2026", "2025", "2024",
    # Quarter labels
    "q1", "q2", "q3", "q4",
    # Filing / announcement language
    "earnings", "report", "reported", "filing", "filed",
    "announced", "announcement", "released", "release",
    "guidance", "outlook", "forecast", "projection", "estimate",
    "beat", "miss", "surprise",
    # Forward-looking
    "next", "upcoming", "future", "projected",
    # Price movement (implies recent)
    "rally", "surge", "drop", "crash", "spike", "fell", "rose",
    "momentum", "trend", "trending",
    # Cash/burn (implies current position)
    "runway", "burn", "burn rate", "liquidity",
    # Staleness check
    "how old", "stale", "outdated", "when was",
    # Months
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}

def _is_time_sensitive(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _TIME_SENSITIVE_KEYWORDS)
```

Latency impact: ~0.1ms — negligible vs 25–50s total turn time.

### Injection in `process_turn()`

```python
from datetime import date

def process_turn(user_input, messages, persona_system=None):
    today = date.today().strftime("%B %d, %Y") if _is_time_sensitive(user_input) else None
    plan_sys = PLAN_SYSTEM.format(today=f"Today is {today}. " if today else "")
    synth_sys = (persona_system or SYNTHESIS_SYSTEM).format(today=f"Today is {today}. " if today else "")
```

### `prompts.py` changes

`PLAN_SYSTEM` and `SYNTHESIS_SYSTEM` get a `{today}` prefix slot:

```python
PLAN_SYSTEM = (
    "{today}You are a stock analysis orchestrator..."
)
SYNTHESIS_SYSTEM = (
    "{today}You are a stock analysis assistant..."
)
```

---

## Section 5: Agent Wiring + Routing Fixes

### Agent tool additions

| Agent | New tools |
|---|---|
| `agents/financials.py` | `get_cash_flow_statement` |
| `agents/calc.py` | `calculate_free_cash_flow`, `calculate_cash_runway` (→ 11 tools) |
| `agents/ratios.py` | `calculate_current_ratio`, `calculate_interest_coverage` (→ 6 tools) |

Note: `agents/calc.py` reaches 11 tools, slightly over the soft limit of 10 for Qwen 3 14B. Monitor for reliability issues — if the model starts missing tools, split calc into two agents.

### `_FINANCIAL_KEYWORDS` additions

```python
"cash", "burn", "runway", "liquidity", "free cash flow", "fcf",
"cash flow", "operating cash", "capex", "interest coverage",
"current ratio", "price target", "target price",
```

### `_keyword_fallback` additions

```python
if any(w in q for w in ["cash flow", "cash burn", "fcf", "free cash flow", "runway"]):
    return ["financials", "calc"]
if any(w in q for w in ["current ratio", "interest coverage", "liquidity ratio"]):
    return ["ratios"]
if any(w in q for w in ["price target", "target price", "analyst target"]):
    return ["financials"]
```

### `PLAN_SYSTEM` description updates

- `financials`: add "cash flow statement, operating cash flow, capex"
- `calc`: add "free cash flow (FCF), cash burn rate, cash runway"
- `ratios`: add "current ratio, interest coverage ratio"

---

## Testing Strategy

All new tools follow the existing TDD pattern: failing tests first, implement, verify pass, commit.

New tests in `tests/test_tools.py`:

**DB tests (3):**
- `test_init_db_creates_cash_flows_table`
- `test_save_and_load_cash_flow_roundtrip`
- `test_is_cash_flow_fresh_returns_false_when_empty`

**Parser tests (3):**
- `test_parse_cash_flow_extracts_rows`
- `test_parse_cash_flow_three_sections`
- `test_parse_cash_flow_applies_thousands_multiplier`

**Calculation tests (4):**
- `test_calculate_free_cash_flow_from_cache`
- `test_calculate_cash_runway_from_cache`
- `test_calculate_current_ratio_from_cache`
- `test_calculate_interest_coverage_from_cache`

**Routing tests (2):**
- `test_is_time_sensitive_detects_keywords`
- `test_is_time_sensitive_returns_false_for_neutral`

---

## Error Handling

- If cash flow not in cache and edgar fetch fails → return stale cache with warning (same pattern as `get_balance_sheet`)
- If capex not found in investing activities → FCF = operating cash flow only, note in output
- If interest expense is zero or missing → return `ERROR:` string (same pattern as `calculate_debt_to_equity`)
- If current liabilities missing from balance sheet → return `ERROR:` string

---

## Future Phases

**Phase 2 — yfinance market metrics:**
- Analyst price targets (`targetMeanPrice`, `targetHighPrice`, `targetLowPrice`) — expose from cached `ticker_info`
- P/S ratio (`priceToSalesTrailing12Months`) — expose from cached `ticker_info`
- P/B ratio (`priceToBook`) — expose from cached `ticker_info`
- No new DB tables needed — all already stored in `ticker_info` JSON blob

**Phase 3 — Provider abstraction (Ollama + Groq):**

Design decisions to carry forward:
- Unified `llm_chat(messages, tools, options)` wrapper in `tools/llm.py`
- Normalizes response format differences: Groq uses `response.choices[0].message`, Ollama uses `response.message`
- Tool call argument normalization: Groq always returns JSON strings, Ollama sometimes returns dicts
- Config: `PROVIDER=ollama|groq` env var, `GROQ_API_KEY` env var
- Model name mapping: `qwen3:14b` (Ollama) ↔ `llama-3.3-70b-versatile` (Groq)
- All 4 agents + orchestrator switch from direct `ollama.chat()` calls to `llm_chat()`
- Expected latency improvement: plan call 10s → <1s, agent calls 8s → <2s
