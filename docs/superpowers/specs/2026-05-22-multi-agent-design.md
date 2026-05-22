# Multi-Agent Stock Assistant — Design Spec

**Date:** 2026-05-22
**Status:** Approved
**Replaces:** Single-agent dispatcher in `main.py`

---

## Overview

Refactor the existing single-agent stock assistant into a multi-agent system: one orchestrator coordinating three specialized sub-agents (FinancialsAgent, NewsAgent, CalcAgent). Adds a new CalcAgent with 8 calculation tools covering valuation ratios, growth metrics, and portfolio-level analysis.

**Why:** Tool count grows to ~13 total. A single agent seeing all tools degrades tool-selection accuracy. Isolating tools per agent keeps each context window focused.

**LLM:** Qwen3 14B via Ollama — unchanged. No LangGraph, LangChain, or external orchestration frameworks.

---

## File Structure

```
main.py                        # entry point: init, chat loop, persona handling
orchestrator.py                # orchestrator LLM call + agent sequencing logic
agents/
  __init__.py
  financials.py                # FinancialsAgent
  news.py                      # NewsAgent
  calc.py                      # CalcAgent
tools/
  calc.py                      # NEW: all calculation tools
  price.py                     # NEW: price history fetch via yfinance (cached 24h)
  config.py                    # (unchanged)
  db.py                        # (unchanged)
  income.py                    # (unchanged)
  news.py                      # (unchanged)
  vector.py                    # (unchanged)
  company.py                   # (unchanged)
  search.py                    # (unchanged)
tests/
  test_calc.py                 # NEW: unit tests for all calc tools
  test_orchestrator.py         # NEW: plan parsing, agent sequencing, context flow
  test_agents.py               # NEW: each agent calls correct tools
  conftest.py                  # NEW: failure logging hook
  failure_log.jsonl            # NEW: persistent failure log (committed to git)
  test_tools.py                # (unchanged)
```

---

## Agents

### Orchestrator (`orchestrator.py`)

- Owns the conversation history
- Makes two LLM calls per user turn: **plan** then **synthesize**
- Has no tools of its own
- Calls sub-agents sequentially, accumulates their outputs as context

**Planning call** — input: conversation history + user message. Output: JSON plan:

```json
{
  "agents": ["financials", "calc"],
  "tickers": ["AAPL", "NVDA"],
  "reason": "need income data before running DCF and correlation"
}
```

Valid agent values: `"financials"`, `"news"`, `"calc"`. If `agents` is empty `[]`, orchestrator answers directly from conversation context — no sub-agent calls.

**Fallback:** If plan JSON is malformed, keyword-match the user message to pick one agent (`income/revenue/P/E → financials`, `news/headline → news`, `DCF/CAGR/correlation → calc`).

**Synthesis call** — input: conversation history + user question + all agent outputs. Output: final natural-language answer citing which agent/tool provided each fact.

---

### FinancialsAgent (`agents/financials.py`)

**Tools:** `get_income_statement`, `get_quarterly_statement`, `get_company_info`

**System prompt focus:** Fetch data accurately and return structured facts. Do not interpret or add strategic context. Cite exact figures and the filing/source they came from.

---

### NewsAgent (`agents/news.py`)

**Tools:** `get_stock_news`, `search_news`

**System prompt focus:** Retrieve and summarize news. Always cite the publisher, headline, and date for each item.

---

### CalcAgent (`agents/calc.py`)

**Tools:** all tools from `tools/calc.py` + `get_price_history` from `tools/price.py`

**System prompt focus:** Compute metrics, show assumptions clearly (e.g. discount rate used in DCF), flag any data gaps. Do not re-fetch data already present in the context passed from prior agents.

Receives prior agent outputs as accumulated context — uses this to compute over already-fetched income/company data without redundant tool calls.

---

## New Tools

### `tools/price.py`

Single function: `get_price_history(ticker, period="1y") -> str`

- Wraps `yfinance` `.history()` to return a time series of daily close prices
- Cached in DuckDB for 24 hours (same cache pattern as existing tools)
- Used by: `calculate_correlation`, `calculate_dcf` (current price cross-check)
- Returns structured string of date→close price pairs

### `tools/calc.py`

| Tool | Inputs | Data source |
|------|--------|-------------|
| `calculate_dcf` | ticker, growth_rate, discount_rate | Operating income from income cache (used as FCF proxy) + current price from company_info |
| `calculate_peg` | ticker | P/E from company_info + EPS growth from income cache |
| `calculate_pe_vs_sector` | ticker | P/E from company_info + fetches 5 sector peers via yfinance |
| `calculate_revenue_cagr` | ticker, years | income statement cache |
| `calculate_margin_trend` | ticker | income statement cache (gross + net margin per year) |
| `calculate_yoy` | ticker, metric | income statement cache |
| `calculate_correlation` | tickers (list), period | `get_price_history` (new fetch) |
| `rank_tickers` | tickers (list), metric | income cache or company_info per ticker |

Tools that compute over cached data (`calculate_revenue_cagr`, `calculate_margin_trend`, `calculate_yoy`, `calculate_peg`, `calculate_dcf`) load from DuckDB — no live network calls.

Tools that fetch new data (`calculate_correlation`, `calculate_pe_vs_sector`) call yfinance directly and cache the result.

---

## Context Flow

```
User message
    │
    ▼
Orchestrator plan call (no tools)
    │  → JSON: {agents: [...], tickers: [...]}
    ▼
[for each agent in plan, sequentially]
    │
    ├─ FinancialsAgent(user_question, conversation_context)
    │      → accumulated_context += financials_result
    │
    ├─ NewsAgent(user_question, accumulated_context)
    │      → accumulated_context += news_result
    │
    └─ CalcAgent(user_question, accumulated_context)
           → accumulated_context += calc_result
    │
    ▼
Orchestrator synthesis call (no tools)
    │  → final answer citing agent sources
    ▼
User
```

Sub-agents never call each other. Only the orchestrator sequences them.

---

## Error Handling

| Failure | Handling |
|---------|----------|
| Plan JSON malformed | Keyword fallback to single most-likely agent |
| Agent LLM call fails / times out | Log warning, skip agent, pass empty string to next |
| Calc tool missing cached data | Return `"ERROR: No income data for {ticker} — call get_income_statement first"` |
| Price history fetch fails | Return empty result with explanatory message; correlation/DCF degrade gracefully |
| Agent returns empty output | Orchestrator skips in synthesis, notes gap in final answer |

No retries on any failure. Log and move on.

---

## Testing

### `tests/conftest.py` — Failure Logging

```python
import json
from datetime import datetime

def pytest_runtest_logreport(report):
    if report.when == "call" and report.failed:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "test": report.nodeid,
            "error": str(report.longrepr),
        }
        with open("tests/failure_log.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
```

`tests/failure_log.jsonl` is committed to git — provides persistent regression history across branches.

### Test Files

**`tests/test_calc.py`** — unit tests for each calc tool using fixture data; no live network calls. At minimum: correct output type, correct formula result, graceful handling of missing cache data.

**`tests/test_orchestrator.py`** — mock `ollama.chat()` to return fixture plans and agent outputs. Must cover:
1. Single-agent plan (news only)
2. Multi-agent plan (financials → calc)
3. No-agent plan (conversational question)
4. Malformed JSON plan → keyword fallback
5. Agent failure → skipped gracefully, synthesis continues

**`tests/test_agents.py`** — verify each agent calls the correct tools given a mock user question; mock tool functions to return fixtures.

**`tests/test_tools.py`** — unchanged.

---

## Conversation & Persona Handling

Persona switching (`/persona buffett`, `/persona panel`, etc.) and conversation history remain in `main.py`. The orchestrator's system prompt is wrapped with the active persona the same way the current single-agent system prompt is. No changes to persona logic.

---

## Out of Scope

- Parallel agent execution (resource-heavy on local Qwen3 14B; sequential is sufficient)
- LangGraph / LangChain / OpenClaw integrations
- Human-in-the-loop interrupts or agent retry loops
- Technical indicators (moving averages, RSI) — no price tick data source
