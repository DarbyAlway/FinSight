# 8-K Earnings Press Release Feature — Design Spec
**Date:** 2026-05-28

## Overview

Add a `get_earnings_press_release(ticker)` tool that returns the last 4 quarters of structured earnings data — EPS actual vs estimate, revenue actual vs estimate, beat/miss flag, and guidance text snippet — to enrich the AI recommendation for long-term investors.

---

## Data Model

New DuckDB table: `earnings_releases`

```sql
CREATE TABLE IF NOT EXISTS earnings_releases (
    ticker            VARCHAR,
    period_end        VARCHAR,   -- quarter end date, e.g. "2024-09-30"
    eps_actual        DOUBLE,
    eps_estimate      DOUBLE,
    revenue_actual    DOUBLE,    -- in millions
    revenue_estimate  DOUBLE,    -- in millions
    beat_miss         VARCHAR,   -- "beat", "miss", "in-line"
    guidance_text     VARCHAR,   -- raw snippet from 8-K Exhibit 99, NULL if parse fails
    fetched_at        DOUBLE,
    PRIMARY KEY (ticker, period_end)
)
```

Cache TTL: 7 days. Up to 4 rows per ticker (last 4 quarters). Demand-driven — rows are only created when a ticker is first requested.

---

## Architecture

### Files Modified/Created

| File | Change |
|------|--------|
| `tools/earnings_press.py` | **New** — fetch, parse, format |
| `tools/db.py` | **Modified** — add table + cache helpers |
| `agents/financials.py` | **Modified** — add tool definition + wire in |

### `tools/earnings_press.py`

Two internal fetchers merged by a public function:

- `_fetch_yfinance_earnings(ticker)` — uses `yfinance.Ticker.earnings_history` to get EPS actual/estimate for last 4 quarters. Computes `beat_miss` from `eps_actual - eps_estimate` (>2% = beat, <-2% = miss, else in-line).
- `_fetch_edgar_guidance(ticker)` — uses `edgar.Company(ticker).get_filings(form="8-K")` to get the most recent 8-K. Looks for Exhibit 99 (press release), extracts a guidance paragraph (sentences containing "expect", "guidance", "outlook", "forecast").
- `get_earnings_press_release(ticker)` — public entry point. Checks cache, on miss calls both fetchers, merges by period_end, saves to DB, returns formatted string.

### `tools/db.py` additions

- `init_db()` — add `earnings_releases` table creation
- `is_earnings_fresh(ticker)` — 7-day TTL check
- `save_earnings(rows)` — INSERT OR REPLACE
- `load_earnings(ticker)` — SELECT last 4 quarters, return formatted string

### `agents/financials.py` additions

New tool definition added to `TOOLS` list:

```python
{
    "type": "function",
    "function": {
        "name": "get_earnings_press_release",
        "description": "Fetch the last 4 quarters of earnings results for a ticker: EPS actual vs estimate, revenue actual vs estimate, beat/miss, and management guidance. Use for: earnings beat/miss history, did they meet expectations, recent guidance, management outlook.",
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
}
```

---

## Data Flow

```
user question
    → financials agent (LLM calls get_earnings_press_release)
        → is_earnings_fresh(ticker)?
            YES → load_earnings(ticker) → formatted string
            NO  →
                _fetch_yfinance_earnings(ticker)  → EPS/revenue rows (4 quarters)
                _fetch_edgar_guidance(ticker)     → guidance_text (best-effort)
                merge by period_end
                save_earnings(rows)
                load_earnings(ticker) → formatted string
```

---

## Output Format

```
AAPL Earnings (last 4 quarters)
  Q3 2024 (Sep 30, 2024)
    EPS: $1.64 actual | $1.60 estimate | BEAT (+2.5%)
    Revenue: $94,930M actual | $94,300M estimate | BEAT
    Guidance: "We expect revenue in the range of $89-93 billion..."

  Q2 2024 (Jun 30, 2024)
    EPS: $1.40 actual | $1.35 estimate | BEAT (+3.7%)
    Revenue: $85,777M actual | $84,500M estimate | BEAT
    Guidance: (not available)
  ...
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| yfinance fetch fails | Return `TOOL_ERROR: ...` — do not fall back to training data |
| EDGAR guidance parse fails | Store `guidance_text = NULL`, still return EPS/revenue data |
| Stale cache + fetch failure | Return stale data with `[Stale cache]` prefix |
| Ticker not found in yfinance | Return `TOOL_ERROR` |

---

## Testing

| Test | Type | Covers |
|------|------|--------|
| `test_parse_beat_miss` | Unit | EPS delta → beat/miss/in-line classification |
| `test_extract_guidance_text` | Unit | Regex guidance extraction from sample 8-K HTML |
| `test_get_earnings_press_release_cache_miss` | Integration | Full fetch with mocked yfinance + EDGAR, verify DB write |
| `test_get_earnings_press_release_cache_hit` | Integration | Second call returns cached data without API calls |
| `test_get_earnings_press_release_edgar_failure` | Integration | EDGAR fails gracefully, EPS data still returned |
| `test_financials_agent_routes_earnings_question` | Agent | Agent calls `get_earnings_press_release` for beat/miss questions |
