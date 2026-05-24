# Data Accuracy Fixes — 2026-05-26

Identified during live testing on 2026-05-25. yfinance pre-computed ratios are
unreliable for debt/equity, profit margin, and forward P/E. Root causes and fixes below.

---

## Task 1 — Reduce ticker_info TTL from 72h to 24h (Quick fix)

**File:** `tools/config.py`

Change:
```python
TICKER_INFO_TTL_HOURS = 24   # was 72
```

**Why:** yfinance ratio data (forward P/E, profit margin) was lagging by 1-2 quarters.
Refreshing more often reduces stale data risk.

---

## Task 2 — Add disclaimer to synthesis prompt (Quick fix)

**File:** `prompts.py`

Append to `SYNTHESIS_SYSTEM`:
> "When citing ratios from company_info (P/E, debt/equity, margins), note that these
> are sourced from yfinance and may lag by 1-2 quarters. For precise figures, prefer
> values computed directly from SEC filings."

Bump `VERSION` to `1.3.0`.

---

## Task 3 — Compute profit margin from cached income data (Medium)

**File:** `tools/calc.py`

Add a new `calculate_profit_margin(ticker)` function that:
1. Calls `fuzzy_query(ticker, "revenue")` and `fuzzy_query(ticker, "net income")`
2. Divides net income / revenue per fiscal year
3. Returns a formatted table (same style as `calculate_margin_trend`)

**Why:** We already have revenue and net income from SEC 10-K filings in `cache.db`.
Computing the ratio ourselves is more accurate than the yfinance pre-computed value.

Add it as a tool to `agents/calc.py` and register it in `prompts.py` CALC_SYSTEM
with a note to prefer it over `get_company_info` for margin questions.

---

## Task 4 — Add balance sheet fetch from SEC (Proper fix for debt/equity)

**File:** `tools/balance_sheet.py` (new)

Use the `edgar` library to fetch the balance sheet from 10-K filings, same pattern
as `tools/income.py`. Key line items needed:
- `LongTermDebt` (or `LongTermDebtNoncurrent`)
- `StockholdersEquity` (or `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`)

Compute: `debt_to_equity = long_term_debt / stockholders_equity`

Cache results in a new `balance_sheets` DuckDB table with the same TTL as
`income_statements` (90 days).

Add `get_balance_sheet(ticker)` as a tool to `agents/financials.py`.

**Why:** The yfinance debt/equity for RKLB returned 6.124 vs the actual ~0.06.
SEC filings are the authoritative source.

---

## Notes

- Tasks 1 & 2 are ~5 minutes each — do these first.
- Task 3 reuses existing cached data — no new API calls needed.
- Task 4 requires studying how `tools/income.py` uses the `edgar` library and
  replicating the pattern for balance sheet concepts.
- After Task 4, add tests to `tests/test_tools.py` covering the new balance sheet cache.
