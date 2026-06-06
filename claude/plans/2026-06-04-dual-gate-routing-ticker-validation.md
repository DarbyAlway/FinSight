# Dual-Gate Routing + Ticker Validation + Token-Explosion Fixes

**Date:** 2026-06-04
**Branch:** `feature/sambanova`
**Status:** In progress
**Models in use:** agents = `gpt-oss-120b`, planner/synthesis = `Meta-Llama-3.3-70B-Instruct` (SambaNova)

### Progress log
- **2026-06-04 — Phase A DONE** (committed `3f247ca`): shared guarded `run_tool_loop` (max-iter / duplicate-call cache / no-progress / token budget) wired into all 4 agents; ratios made self-sufficient (`get_income_statement` + `get_company_info`). Validated on SambaNova: the 85k ratios loop → ~11k. 7 new tests.
- **2026-06-05 — Data-integrity parser fixes DONE** (committed `63d3b0f`), ahead of Phase F: (1) **fiscal-year swap** — parsers grabbed the `"X to Y"` period label instead of the column header, swapping every value's year on all 2-column statements (every balance sheet + 2-year cash flows; e.g. MSFT assets/ROE, LITE FCF trend inverted) → skip `" to "` lines in all 3 parsers; (2) **lexicographic `ORDER BY fiscal_year`** on date strings → `try_strptime(...)` across 12 queries; (3) **capex "not found"** → broadened LIKE patterns. Cache flushed for real tickers. Verified vs SEC 10-K + stockanalysis.com.
- **2026-06-05 — calc agent self-sufficiency DONE** (pending commit): added `get_company_info` / `get_income_statement` / `get_cash_flow_statement` / `get_balance_sheet` to calc + prerequisite hints in `calculate_*` descriptions (fixes "No company info" PEG failure on a calc-only plan — see I2/I3 principle). **Decision: keep the DuckDB cache** — it's what makes per-agent self-sufficiency cheap (first fetch ~5s, cached ~50ms; duplicate fetches de-duped by cache + guardrail).
- **2026-06-06 — Phase B (Gate 1 group manifest) DONE** (pending commit): new `tools/groups.py` with `GROUP_MANIFEST` (MAG7, FAANG — minimal by design, per user; anything else → None → dynamic path), `check_local_manifest()` and `detect_group_in_query()`. Wired into `orchestrator.process_turn`: after planning, `detect_group_in_query(user_input)` overrides the planner's ticker list when a known group is named — directly fixes the FB/BABA/missing-META-NVDA bug. 12 new tests (10 `test_groups.py` + 2 `test_orchestrator.py` covering MAG7 override + normal-query passthrough). Added `pytest.ini` (`testpaths = tests`) so bare `pytest` stops collecting root `smoke_test.py` (it `sys.exit()`s at import → INTERNALERROR). Also added the **`market_news`** intent to the router taxonomy (no ticker, no group — e.g. "why is the market down today" → news agent / web search, bypasses both gates). Suite: **120 passed**.
- **2026-06-06 — Phase C (Gate 2 validation) DONE** (committed `ef7c2a7`): new `tools/resolve.py` — `validate_tickers()` partitions against the SEC filer set (`edgar.get_company_tickers()`, ~10.7k, **fails open** if unavailable), `resolve_name()` (yfinance Search first EQUITY — handles brand renames the SEC legal-name index misses, e.g. Facebook→META), `resolve_entities()` (verbatim-ticker rule, ready for grounding). Wired into `orchestrator`: after Gate 1, drop invalid/dead/hallucinated tickers; if **all** invalid, skip data agents and let synthesis explain cheaply. **Evidence that drove it:** live `analyze Twitter stock` → planner emitted dead `TWTR` → 3 agents + ~17k tokens wasted; also user reports planner sometimes emits never-existed tickers. Verified vs SEC list: TWTR/SQ/FB **not** current filers (caught); XYZ/META are. 18 new tests. Suite: **132 passed**.
  - **KEY GAP (drives Phase D):** validation only catches NON-EXISTENT tickers. A **valid-but-wrong-entity** ticker (FB→ProShares ETF: FB is a *real* ETF) passes validation. Catching it needs **grounding** — resolve the user's company NAME independently and compare. `resolve_entities()` does exactly this but needs the extracted NAME → that's Phase D's `extracted_entities`. Resolver half is built+tested; Phase D = structured router (name extraction) + wire `resolve_entities`. Not yet observed live, so evidence-gated.
- **Still pending:** Phase D (structured router — name extraction + grounding via resolve_entities; also home for market_news intent + I3 capability routing; LangGraph entry point), Phase F (Pydantic parser validation + "LLM quotes tool numbers, never recomputes" — seen live: synthesis recomputed PEG 1.53 despite the tool erroring), I1/I4, I6 (token reduction — 95k MAG7 query), and **I5** (web-search trigger, below).

---

## Problem statement

Two distinct problems surfaced while testing broad/MAG7 queries on SambaNova:

### Problem 1 — Wrong tickers from the orchestrator
The planner LLM emits stale/wrong tickers because **LLM company→ticker memory is a coin flip**:
- `"analyze MAG7"` → planner produced `['AAPL','MSFT','AMZN','GOOGL','FB','BABA','TSLA']`
  - `FB` = dead Facebook ticker → `get_company_info('FB')` resolved to a random **"ProShares S&P 500 Buffer ETF"**
  - `BABA` (Alibaba) is **not** in MAG7
  - `META` and `NVDA` were **missing**
- Same model got it **right** on a different run (`META` correct) → proves it's non-deterministic.

### Problem 2 — Token explosion (one query hit 139,002 tokens)
Breakdown of the 139k run: `plan=833, agents=134,346, synthesis=3,823`.
- The **ratios agent looped ~85k tokens** calling `get_income_statement` — a tool it does **not** have in its toolset. Its prompt + the `calculate_all_margins` error message both say "call get_income_statement first," so the LLM tried it → `Unknown tool` → retried the margin calc → same error → loop.
- Compounded by a **cross-agent data dependency broken by parallelism**: `calculate_all_margins` reads income data that the *financials* agent populates, but agents run in parallel, so ratios calls it before the data exists.
- No **iteration cap** on any agent's `while msg.tool_calls:` loop → unbounded burn.

---

## Root-cause insight: two different ticker failure types

The key realization (why Claude-in-chat caught the errors but the orchestrator didn't):
**The orchestrator emits tickers blind — it never sees what they resolve to.** Claude saw the tool output (`FB → ProShares ETF`) and noticed the mismatch. The fix is to give the orchestrator that same feedback / grounding.

There are **two independent failure modes**, each needing its own gate:

| Failure type | Example | Detected by | Gate |
|---|---|---|---|
| **Resolution error** — ticker resolves to wrong entity | `FB` → ProShares ETF (meant Meta) | Grounding: compare resolved company vs intended name | **Gate 2** |
| **Membership error** — valid ticker, wrong set | `BABA` in MAG7 (BABA is a *real* ticker for Alibaba) | Known group definition | **Gate 1** |

Grounding (fetch-and-check) catches resolution errors but **not** membership errors (BABA resolves correctly to Alibaba — it just doesn't belong in MAG7). Membership needs a canonical group definition.

### Map vs index — the bounded/unbounded distinction
- A **per-ticker correction map** (`FB→META`, `GOOG→GOOGL`, ...) is **unbounded** and doesn't scale — rejected.
- A **group-definition map** (`MAG7 = 7 names`) is **bounded** (~handful of stable acronyms) — appropriate for Gate 1.
- **Name→ticker resolution** should use an **authoritative index** (SEC `company_tickers.json`, ~10k companies), not a hand-maintained map — for Gate 2.

### Latency comparison (measured from logs)
| Approach | Added latency/query | Reliability |
|---|---|---|
| LLM validator (smart model checks) | ~1–2s (extra model call) | Probabilistic — can confirm BABA |
| Fetch-to-verify (yfinance) | ~50ms cached / ~1s uncached (parallelizable, ~free since agents fetch anyway) | Catches resolution only |
| **Local SEC ticker index** (load once at startup) | **~0ms/query** (in-memory dict) | **Authoritative / exact** |

**Conclusion:** the deterministic pair (group map + SEC index) is both the **fastest (0ms)** and the **most reliable (exact)**. An LLM validator is the slowest *and* weakest option, kept only as a rare fallback for names the SEC index can't match.

---

## Design: Dual-Gate Routing Architecture

A structured-output **router node** classifies intent, then a query passes through up to two deterministic gates before agents run. This doubles as the **LangGraph router** (router node + conditional edges = the migration entry point).

### Static path vs Dynamic path (the cost model)

The router is built around a **90 / 10 split**:

- **Static Path (~90% of cases) — bypass web search entirely:**
  - **Known group** ("MAG7", "FAANG") → local hardcoded config/dict (Gate 1 manifest)
  - **Explicit tickers / company names** (`['MSFT','GOOGL']`, "Nvidia and Alphabet") → resolve via SEC index (Gate 2) → straight to the financial API
  - Both paths are **0ms, deterministic, no web search, no expensive discovery.**

- **Dynamic Path (~10%, the exception) — only for novel phrases the router has never seen:**
  - e.g. *"Analyze the Top 5 AI robotics penny stocks right now"* — no fixed membership, not explicit tickers
  - Only **this** case triggers the expensive **Web Search API** to discover tickers dynamically (`trigger_grounded_search`)
  - This is where the latency/cost lives — and it's deliberately rare.

The intent classifier itself should be **lightweight** — a small/fast LLM, or even an **embedding-based classifier** — because it only judges the *structural intent* of the sentence (named-stocks vs macro-theme vs general-QA), NOT the market analysis. Keep the heavy model for synthesis, not routing.

### Structured intent (Pydantic)
```python
from pydantic import BaseModel, Field
from typing import Literal

class QueryIntent(BaseModel):
    intent_type: Literal["specific_tickers", "macro_theme", "market_news", "general_qa"] = Field(
        description="Did the user name specific stocks, a named group/theme, ask about "
                    "overall market conditions/news, or general QA?"
    )
    extracted_entities: list[str] = Field(
        description="Company NAMES or raw symbols the user mentioned — do NOT guess tickers."
    )
```
**Critical:** the LLM extracts *entities/names* (reliable), NOT tickers (stale). Ticker resolution is owned by deterministic code.

**`market_news` — the "no direct stock" intent (added 2026-06-06).** Queries like
*"what's wrong with the stock market today, why is everything going down"* name no
ticker and no fixed group, but DO need live data — so they're neither `specific_tickers`,
`macro_theme` (which requires a manifest-defined membership), nor `general_qa` (greetings/
chit-chat). They route to the **news agent** (optionally seeded with index proxies like
`^GSPC`/`SPY`/`^IXIC`) and/or the **grounded web-search dynamic path** — they bypass both
gates (no manifest group, no entities to resolve). This is the broad-market sibling of the
dynamic path: `macro_theme` with no manifest hit goes to grounded search for a *ticker set*;
`market_news` goes to news/web search for *current market explanation* (no ticker set needed).

### Router flow
```python
def orchestrator_router_node(user_query: str) -> dict:
    intent = structured_llm(QueryIntent, user_query)   # fast model, structured output

    if intent.intent_type == "specific_tickers":
        # Gate 2 — Resolution: names -> tickers via SEC index (0ms, authoritative)
        tickers, unresolved = resolve_entities(intent.extracted_entities)
        if unresolved:
            return {"action": "trigger_grounded_search", "concept": unresolved}
        return {"action": "execute_analysis", "tickers": tickers}

    elif intent.intent_type == "macro_theme":
        # Gate 1 — Membership: group definition from local manifest (0ms, bounded)
        local = check_local_manifest(intent.extracted_entities[0])   # "MAG7" -> 7 tickers
        if local:
            return {"action": "execute_analysis", "tickers": local}
        return {"action": "trigger_grounded_search", "concept": intent.extracted_entities[0]}

    elif intent.intent_type == "market_news":
        # No ticker, no group — broad-market "why is everything down today".
        # Bypass both gates; go to news agent (+ index proxies) / grounded search.
        return {"action": "market_news"}   # -> news agent / web search, no ticker set

    return {"action": "fallback_chat"}   # general_qa / greeting
```

### The two gates
- **Gate 1 — Scope / Membership** (`macro_theme` path): `check_local_manifest("MAG7")` → canonical 7 tickers. Fixes BABA / missing-META-NVDA. Bounded map, 0ms.
- **Gate 2 — Resolution** (`specific_tickers` path): resolve entities → tickers. Fixes FB→ETF.

### CRITICAL RULE: never trust an LLM-emitted ticker
The `specific_tickers` branch's `extracted_entities` comes from the LLM, so it can inject a stale ticker (user says "Meta" → LLM emits `FB` → `FB` resolves to a real ProShares ETF → slips through). Rule that closes it:

> **A ticker is trusted only if it appears verbatim in the user's query. Otherwise resolve the entity as a company NAME.**

```
"analyze NVDA"  → "NVDA" literally in query  → accept → validate → NVDA   ✅
"analyze Meta"  → LLM emits "FB"             → "FB" NOT in query → discard, resolve NAME "Meta" → META ✅
"analyze Meta"  → LLM emits "Meta"           → not a verbatim ticker → resolve name → META ✅
```
The final ticker comes from deterministic resolution keyed off the user's literal words — never the LLM's guess. **Principle: the LLM identifies entities; deterministic code assigns tickers.**

### Priority insight (from live test "what is PE for facebook stock?")
The Llama-3.3 planner correctly resolved `Facebook → META` for a **single explicit company**, but produced `FB`/`BABA` for **group expansion (MAG7)**. So the model is:
- **Mostly reliable** for single/explicit company mentions → Gate 2 is **lower-risk**
- **Unreliable** for group/list expansion → Gate 1 is where the real failures live

**Re-prioritization:** Gate 1 (manifest) + the token-explosion safety fixes are the **high-value work**. Gate 2 starts as a **lightweight backstop** — the verbatim-ticker rule + a single validation fetch (reject if it resolves to an ETF/garbage) — NOT a full SEC index build. Promote Gate 2 to the full SEC `company_tickers.json` index later only if single-company resolution proves unreliable in practice.

A plan reaches the agents only after clearing the relevant gate(s). On failure → grounded search or one capped re-plan (no infinite loop).

### How this also closes Problem 2's front door
Bad tickers are caught **before** agent dispatch, so we never spend 3 agents fetching a garbage ETF. The validation step can be net token-**positive** (it prevents wasted agent fetches).

---

## Implementation tasks (ordered)

### Phase A — Token-explosion safety (do first, independent of routing)
1. **Add layered loop guardrails to all 4 agents' tool loops** (`financials`, `ratios`, `news`, `calc`). The 139k loop had a clear signature — same tool, same args, same error, repeated — so catch it at several levels, cheapest/earliest first:
   - **a. Max-iteration cap (~8 rounds)** — hard universal brake. Any runaway loop stops, no matter the cause. After the cap, break and synthesize with whatever data was gathered (don't error out).
   - **b. Duplicate tool-call detection** — track `(tool_name, args)` seen this turn; if the LLM requests an identical call already executed, **skip it and feed back the cached result** (or a "already called, do not repeat" note) instead of re-running. Kills the `calculate_all_margins('MSFT')` retry loop directly.
   - **c. No-progress / repeated-error detection** — if the last N tool results are identical error strings (e.g. the same `ERROR: No revenue data...` or `Unknown tool...`), break the loop — the model is stuck.
   - **d. Per-agent token budget (hard cap, e.g. ~30k)** — if an agent's accumulated tokens exceed the budget, break. Final backstop so no single agent can ever cost 85k again.
   - On any guardrail trip: log a clear warning (which guardrail, which tool) so it's visible in console + Langfuse, then return whatever the agent has so far. **Highest-priority safety net — implement before anything else.**
2. **Make the ratios agent self-sufficient — add `get_income_statement` AND `get_company_info` to its `TOOLS` + `TOOL_FUNCTIONS`.**
   - `get_income_statement` — *required*: `calculate_all_margins` and `calculate_interest_coverage` need income data. Direct fix for the 85k loop (agent self-serves instead of looping on a missing tool).
   - `get_company_info` — *defensive*: prevents another "Unknown tool" loop if the LLM decides to call it, and provides sector/industry context for ratio commentary. Cost is at most one extra call, bounded by the iteration cap (task 1).
   - General principle: **every tool an agent's prompt or reasoning might reference must be in its toolset**, or it risks an unbounded "Unknown tool" retry loop (this is the root pattern behind the 139k incident).
   - Verify margin/interest-coverage calcs then work standalone (no dependency on the parallel financials agent).

### Phase B — Group membership (Gate 1)
3. **Build a bounded group-definition manifest** (`MAG7`, `FAANG`, maybe Dow/“big banks”) → list of canonical company names or tickers. Local JSON/dict, 0ms lookup. `check_local_manifest()`.

### Phase C — Name→ticker resolution (Gate 2)
4. **Build the SEC ticker index** from `company_tickers.json` (verify edgartools exposes it: `edgar.reference.tickers.get_company_tickers` or download+cache). Load once at startup into an in-memory `name → ticker` dict (normalized/fuzzy match). `resolve_entities()`.
5. **Wire Gate 2 into the specific-tickers path** so the LLM never emits a raw ticker.

### Phase D — Structured router
6. **Replace `_plan_step` JSON-regex parsing with structured output** (`QueryIntent`). Verify SambaNova supports `response_format`/json-schema; if not, use the `instructor` library or JSON-mode + Pydantic validation.
7. **Restructure `process_turn`** around `orchestrator_router_node` returning `{"action": ...}` → `execute_analysis` / `trigger_grounded_search` / `fallback_chat`. (This is the LangGraph router shape.)

### Phase E — Test
8. Re-run and verify on: `"what is MAG7"`, `"analyze MAG7"`, `"which MAG7 is best to invest"`, `"analyze rocket lab for me"`, `"analyze Meta"`, plus a greeting. Assert: correct tickers (META not FB, no BABA, NVDA present), bounded tokens (no 100k), no hallucination on chat.
9. Keep `pytest` green (101 tests). Update/add tests for gates + resolver.

---

## Available tools — USE THESE, don't hardcode (verified 2026-06-04 in `stock` env)

| Need | Use this (already installed) | Notes |
|---|---|---|
| **Name→ticker resolution (Gate 2)** | **`edgar.get_company_tickers()`** | Returns **10,769 rows** `[cik, ticker, exchange, company]` — the authoritative SEC list, **no download**. Build an in-memory `name→ticker` + `valid-ticker` dict from it at startup. **This makes the full index ≈ free — skip the "lightweight backstop only" compromise.** |
| also | `edgar.find_company(name)`, `edgar.get_ticker_to_cik_lookup()` | edgartools name search + ticker↔CIK |
| secondary / dynamic-path fallback | `yfinance.Search`, `yfinance.Lookup` (yf 1.3.0) | name→ticker search for the rare dynamic path |
| **Structured output (router)** | `openai` 2.40 native `response_format` (json_schema) + `pydantic` 2.13 | `instructor` is **NOT** installed → `pip install instructor` *only if* SambaNova doesn't support native `response_format`. Verify SambaNova first. |
| **Embedding intent classifier** (optional, avoids an LLM router call) | **`fastembed` 0.8.0** | Already used by Qdrant — reuse the same embedder for cheap structural intent classification |
| **LangGraph orchestration** (later phase) | `langgraph` — **NOT installed** | `pip install langgraph` when we build the state-machine router |
| Tracing | `langfuse` 4.7.0 ✓ | already wired |

**Impact on the plan:** Gate 2 is no longer a "build a parser / hardcode" task — it's "load `get_company_tickers()` into a dict." So implement the **full authoritative index** (not the lightweight backstop) — it's one function call and removes the coin-flip entirely. Group manifest (Gate 1) stays a small hardcoded dict (MAG7/FAANG aren't SEC-defined groups).

## Open questions to verify next session
- Does **SambaNova** support structured outputs (`response_format` json-schema)? If not → `instructor` or JSON-mode fallback.
- Does **edgartools** expose `get_company_tickers()` (SEC `company_tickers.json`)? If not → download + cache the JSON directly.
- Foreign/ADR names (e.g., Alibaba) and share-class ambiguity (GOOGL vs GOOG) — confirm the SEC index + normalization handle these.

## Phase F — Data integrity: Pydantic-validated parsers (new workstream)

**Principle (same as tickers): the LLM should never *type* a number.** Numbers flow through validated structured models; the LLM decides *what to fetch* and writes prose *around* the numbers — it never re-enters them.

**Context:** in our architecture the **Python parsers** (`parse_income_statement`, `parse_quarterly_statement`, `parse_balance_sheet`, `parse_cash_flow`) already extract numbers from SEC text — the LLM only summarizes. Every data bug fixed manually this session was an *unvalidated parser* bug: `383` stored as millions (meant `383,000`, the unit-multiplier bug), `204.6%` gross margin, YTD figures mislabeled as single-quarter, FCF "capex not found". Pydantic validation would have caught all of them **at parse time, automatically.**

10. **Define Pydantic models for each parsed statement** with sanity validators, e.g.:
    ```python
    class MarginRow(BaseModel):
        fiscal_year: str
        revenue: float = Field(gt=0)                 # revenue can't be ≤ 0
        gross_margin_pct: float = Field(ge=-1, le=1) # >100% margin is impossible → raises
    ```
    Cover: income statement, quarterly, balance sheet, cash flow. Add domain constraints (margins in [-1,1], revenue > 0, assets = liabilities + equity tolerance check, capex present for FCF, etc.).
11. **Have the parsers return `list[Model]`** instead of dicts; a bad parse **raises/flags at the source** so it's never stored in DuckDB or shown. Log + skip the bad row rather than silently corrupting.
12. **Format for the LLM deterministically from the validated model** (don't hand the LLM free numbers to retype).
13. **Stretch (do carefully):** have agents pass **structured data** through to synthesis instead of re-typed prose — note we tried "tool-select only, no agent summary" earlier this session and reverted it (missing-ticker problem), so this needs the dual-gate/self-critique safeguards in place first.
14. **Later (flag, don't build yet):** post-validate the synthesis answer — assert numbers in the final prose exist in the source data — to close the last LLM-retyping gap.

This is the **systematic, permanent version of the manual bug-hunting done 2026-06-04** (unit multiplier, fiscal quarters, ratios, YTD). Priority: after Phase A safety, alongside the Gate work — parser validation is independent and high-value.

## Additional issues observed 2026-06-04 (fold into next session)

### I1 — Slow responses (LITE/Lumentum query took 102s) — DIAGNOSE FIRST
**DONE 2026-06-06 (committed `9bf2898`):** the agents' `_chat` wrapper now logs each LLM round's latency + tokens (`[Agent] llm call: Nms prompt=.. completion=..`) and logs failed calls with latency + exception (429 visibility). Unit-tested via caplog. The *diagnosis* (why agents were slow) is now possible from logs; any concurrency/rate-limit fix follows once observed.

Tool executions were fast (cash-flow fetch ~6s, FCF calc 22ms, edgar init ~10s one-time) but the **financials agent took 50.75s and calc took 99.57s**. The time is in the agents' **internal LLM calls**, which use the `_chat` wrapper that does **not log latency** (only `llm_chat` does) — so it's invisible.
- **Action: add latency logging to the agents' `_chat` wrapper** (model, prompt/completion tokens, latency) + log any `429`/rate-limit. Without this we're guessing.
- **Prime suspects:** (1) **SambaNova throttling** under parallel agent load — 2-3 agents fire concurrent requests via ThreadPoolExecutor → RPM limit → silent client ret/backoff; (2) **calc-depends-on-financials run in parallel** (see I2). 50–99s/agent for 2 LLM calls is abnormal (normal SambaNova call ≈1–2s).
- Possible fixes once diagnosed: limit agent concurrency / add a small rate-limit-aware semaphore; or sequence dependent agents (financials before calc).

### I2 — Cross-agent data dependency run in parallel (correctness + speed)
`calc.calculate_free_cash_flow` and the ratios margin calcs need data that the **financials** agent fetches, but agents run **concurrently** → race. Fallout in the LITE run: calc reported FCF **+$25M/+$126M ("capex not found")** while synthesis said **−$105M/−$108M** — a contradiction + a **capex-parsing bug** (capex not found in the cash-flow statement). 
- Fix options: (a) make each agent self-sufficient (fetch its own inputs — same principle as the ratios `get_income_statement` fix), or (b) introduce dependency ordering (calc/ratios run after financials). Self-sufficiency is more parallel-friendly.
- Also fix the **capex parser** (`calculate_free_cash_flow` "capex not found") — separate data-quality bug.

### I3 — Orchestrator picks wrong agent (doesn't know which agent owns which tools)
The planner routes by a high-level agent description but doesn't know each agent's exact tool inventory, so it sometimes mis-routes.
- **Fix:** in `PLAN_SYSTEM` (or the new router's intent prompt), enumerate **each agent's concrete tools/capabilities** explicitly so routing maps capability→agent precisely. The structured router (Phase D) is the natural home for this — encode the agent→tools map and let the router pick by capability.

### I4 — Summarize prior turns to cut token cost (history accumulation)
Conversation history is fed into agents (`history[-6:]`) and full into synthesis, so tokens grow every turn (the SNOW run jumped 17.5k→20k from one prior turn). 
- **Fix:** (a) stop feeding raw history to data-fetch agents (they rarely need it), and/or (b) **summarize previous turns** into a short running summary instead of passing full prior responses. Reduces per-turn token cost, especially in long sessions.

### I5 — Web-search fallback trigger is unreliable (don't just lower the threshold) — added 2026-06-05
Observed on `"what about PEG?"` for LITE: the calc agent returned only `ERROR: No company info`, synthesis said *"There is no information available…"*, but the Tavily fallback did **not** fire (`is_uncertain score=0.837 < 0.85`). Tempting fix = lower the threshold. **Measured the score distribution and proved that won't work** — `is_uncertain` embeds the answer and takes max cosine vs ~130 "I don't know" anchors, but the scores barely separate:

| Answer | Score |
|---|---|
| UNCERTAIN — "I don't have enough data" | **0.982** |
| UNCERTAIN — PEG "no information available" | **0.836** |
| CONFIDENT — greeting | 0.832 |
| CONFIDENT — "FCF −$105M / −$108M" | 0.802 |
| CONFIDENT — "MSFT ROA 16.5%, ROE 29.6%" | 0.796 |
| CONFIDENT — "PEG ≈ 1.53…" | 0.775 |

The failing answer (0.836) is **tied with a confident greeting (0.832)** and sits on top of the confident cluster (0.775–0.832). No threshold catches it without false-firing on confident answers. **Root cause:** `multilingual-e5-large` is used **without its required `query:`/`passage:` prefixes**, compressing all short English sentences into a 0.77–0.98 band; only blatant "I don't know" (0.98) stands out.

**Fix (do this, not threshold-tuning):**
- **Primary — deterministic empty/error trigger.** Fire the web fallback when agents returned nothing usable: `accumulated_context` empty, or every agent output is an `ERROR:` / `No …` / `TOOL_ERROR` line. This is the reliable signal (the failing run had `agents_context=77 chars`). Reliable, zero false positives on confident answers. (This is the "fire on empty agent outputs vs text-scoring" item, now promoted from out-of-scope.)
- **Secondary — keep `is_uncertain` at the high threshold** (≥0.85) so blatant "I don't know" (0.98) still fires; stop relying on it for borderline cases it can't separate.
- **Optional — add `query:`/`passage:` prefixes** to anchors + candidate to sharpen the e5 signal (separate, lower-priority improvement).
- Note: for the specific PEG/LITE case the *real* fix was self-sufficiency (calc now fetches its own data) — web search shouldn't be the answer for locally-computable metrics. The empty/error trigger is the safety net for genuinely-unanswerable queries.

### I6 — Agent input-token cost: measured breakdown + no SambaNova caching — added 2026-06-05
Instrumented a real ratios turn (MSFT, data cached). The per-call prompt growth shows the cost is the **re-send multiplier**, not one big prompt — the *final* call was only 2,814 tokens but the agent billed **10,232** cumulative over 5 LLM calls:

```
call 1: prompt=  715   (system + 8 tool schemas)
call 2: prompt= 1574   (+859  income statement dump)
call 3: prompt= 2476   (+902  balance sheet dump)
call 4: prompt= 2653   (+177  margins table)
call 5: prompt= 2814   (+161  ROA/ROE table)
SUM   = 10,232 over 5 calls
```

| Component | Size | Re-sent | Cumulative | Share |
|---|---|---|---|---|
| Static prefix (system + 8 tool schemas) | 715 | ×5 | ~3,575 | **35%** |
| Income statement dump | ~859 | ×4 | ~3,436 | **34%** |
| Balance sheet dump | ~902 | ×3 | ~2,706 | **26%** |
| Actual calc result tables | ~170 ea | — | small | ~5% |

**SambaNova does NOT support prompt caching** (verified): `prompt_tokens_details.cached_tokens = null`; an identical 1,838-token prompt sent back-to-back was billed 1,838 both times, same latency. So the "cache the static prefix" lever is unavailable — every re-sent byte is paid.

**Key insight:** the data-fetch tools (`get_income_statement`, `get_balance_sheet`) dump the **full statement** into context, but in the **calc/ratios** agents those tools exist only to populate the DuckDB cache — the real numbers come from the `calculate_*` tools reading the DB. So ~1,760 tokens of statement text is carried and re-billed 3–4× for nothing.

**Levers (caching ruled out), by ROI:**
1. **Compact fetch-tool output in calc/ratios** — ✅ **DONE 2026-06-06 (committed `24d47d8`)**. `tools/fetch_compact.py` wraps `get_income_statement`/`get_balance_sheet`/`get_cash_flow_statement` to return a short confirmation (cache still populated; `calculate_*` reads the numbers). Wired into calc + ratios `TOOL_FUNCTIONS`; **financials keeps the full text** (it summarizes for the user); tool schemas unchanged. Returns the original result on error/stale/parse-empty so failures stay visible. 6 unit tests, suite 138 passed. **Live MAG7 token-drop verification still pending** (paid SambaNova). Evidence trail: live `analyze Twitter`/`Square`/`MAG7` runs; 95k MAG7 turn (financials 37k + ratios 45k + news 10k).
2. **Slim the tool schemas** — 715×5 = 35%; with no caching every schema byte is paid per round. Tighter descriptions / fewer tools per agent.
3. **Fewer rounds** — 4 sequential tool calls = 5 re-sends; batching fetches into one round helps but the model controls it.

Estimated ~50–65% input-token reduction on the heavy agents from #1+#2. Independent of the routing work; pairs naturally with Phase F (structured data → less free-text re-sending).

### I7 — Langfuse: one trace per agent instead of one per query — added 2026-06-05
**DONE 2026-06-06 (committed `9bf2898`):** capture the OTEL context before the `ThreadPoolExecutor` and re-attach it inside each `_run_agent` worker (with `finally: detach`). Agent spans now nest under the query's `process_turn` trace. Verify in the Langfuse UI (no unit test for cross-thread OTEL context); suite confirms no regression.

In the Langfuse UI each query produces **multiple top-level rows — one per agent** (financials, calc, …) instead of a **single query trace with the agents nested inside it**. Desired: `"what is MSFT PEG?"` = one row → planner + financials + calc + synthesis as child spans.

**Root cause:** agents run in a `ThreadPoolExecutor` (`_run_agent` in `orchestrator.py`). Langfuse 4.7.0 is OTEL-based, and the `@observe` decorator nests via the **OpenTelemetry context** — which is **not propagated across thread boundaries**. So each agent thread has an empty context and its `@observe` (`ratios-agent`, etc.) starts a **new root trace**. The planner/synthesis nest fine because they run on the main thread.

**Fix (planned, ~6 lines):** capture the current OTEL context in the main thread and re-attach it inside each worker thread:
```python
from opentelemetry import context as otel_context
# inside process_turn, before the ThreadPoolExecutor:
parent_ctx = otel_context.get_current()
def _run_agent(agent_name):
    ctx_token = otel_context.attach(parent_ctx)
    try:
        ...existing body...
    finally:
        otel_context.detach(ctx_token)
```
Verify by running a multi-agent query (e.g. `"what is MSFT PEG?"` → financials+calc) and confirming all agent spans share the `process_turn` trace id (one row, nested children). No SDK upgrade needed.

## Connection to LangGraph migration
This router *is* the LangGraph entry node. `orchestrator_router_node` → conditional edges → agent nodes. Implementing the dual-gate router is the first concrete step of the LangGraph migration we brainstormed (re-planning / decomposition is the later phase, built on this stable base).

## Out of scope (later)
- Query decomposition / self-generated sub-questions (the LangGraph re-planning headline feature).
- ~~Improving the Tavily trigger (fire on empty agent outputs vs text-scoring).~~ → promoted to **I5** (with measured evidence).
