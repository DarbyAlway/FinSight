# I4 (history token cost) + I5 (web-search fallback trigger) — Design

**Date:** 2026-06-08
**Branch:** `feature/sambanova`
**Status:** Designed, pending implementation
**Source:** Activates two open items from `claude/plans/pending/2026-06-04-dual-gate-routing-ticker-validation.md` (I4, I5). Independent of the fidelity/structured-output work (Phase F #13/#14), which comes after.

---

## Why

Two independent, router-independent issues observed in live testing:

- **I4 — history token cost.** Every data agent is handed `history[-6:]` (`agents/*.py`), and synthesis is handed the **full** message history (`orchestrator.py:206`). Tokens grow every turn (the SNOW run jumped 17.5k→20k from one prior turn). SambaNova has **no prompt caching**, so every re-sent byte is paid.
- **I5 — web-search trigger is both missing a case and unreliable.** (1) There is **no proactive trigger**: a current-events query ("why is the market down today?") needs live web data, but the orchestrator only ever runs local agents. (2) The lone reactive trigger is `is_uncertain(answer, 0.85)` (`orchestrator.py:224`), which the plan **measured** cannot separate a real "no data" answer (0.836) from a confident greeting (0.832). Net effect: market-news queries get a weak non-answer and genuinely-unanswerable queries silently get no fallback.

---

## I4 — Cut history token cost (Option A + synthesis cap)

**Decision:** drop raw history from the data agents, and cap (not summarize) synthesis history. **No summarizer LLM call** — zero added cost/latency.

### Rationale
The data agents don't need conversation history: the orchestrator already injects the resolved ticker via `ticker_hint` (`orchestrator.py:160`), and the current metric/intent is in `user_input`. History was pure overhead for them. Synthesis still needs *recent* turns for conversational continuity ("what did you just say"), but not the whole transcript.

### Changes
1. **Stop passing history to agents.** In `orchestrator._run_agent` (`orchestrator.py:180`), call agents with `history=None` instead of `history=messages`. The agents' existing `if history:` guard then simply skips — no change needed inside the agent files (their `history[-6:]` code stays as dead-safe fallback).
2. **Cap synthesis history.** In `process_turn`, build `synthesis_messages` from the last `_SYNTH_HISTORY_TURNS` turns only:
   - Add constant `_SYNTH_HISTORY_TURNS = 3` (→ last 6 messages).
   - `synthesis_messages = [{system}, *messages[-2 * _SYNTH_HISTORY_TURNS:]]` instead of `*messages`.
3. **Planner left unchanged.** The planner needs prior-turn context for ticker corrections ("I meant LITE not LUMN" re-runs the *previous* question) and its messages are tiny (plan JSON). Out of scope for I4.

### Out of scope (promote later only if measured)
- Real summarization of old turns (plan's Option B) — only if long sessions still balloon after the cap. Measure first.

---

## I5 — Reliable web-search trigger (proactive + reactive)

**Decision:** two triggers. **Proactive** — the planner classifies query `intent`; a `market_news` intent fires web search **up front** (local SEC/cache data can't explain "why is the market down today"). **Reactive** — a deterministic "agents returned nothing usable" fallback as the safety net for other queries. Keep `is_uncertain` as a tertiary signal but stop relying on it alone (the plan measured that it cannot separate a real no-data answer (0.836) from a confident greeting (0.832)).

### Why proactive is required
For *"why is everything down today?"* the data agents return **something** (stale headlines, a cached price) — not an `ERROR` — so the reactive empty/error trigger never fires and the user gets a weak non-answer, after wasting a full agent round. Such queries are known to need live web data at routing time, so the orchestrator must route to web search before running data agents.

### Part 1 — Proactive: planner `intent` classification
1. **Add an `intent` field to the planner's JSON output** `{intent, agents, tickers, reason}`. Values reuse Phase D's taxonomy (`prompts.PLAN_SYSTEM` + the plan's `QueryIntent.intent_type`):
   `"specific_tickers" | "macro_theme" | "market_news" | "general_qa"`.
   Update `PLAN_SYSTEM` to define each and give a `market_news` example (`"why is the market down today"` → `intent="market_news"`, `agents=["news"]`, `tickers=[]`).
2. **Parse it** in `process_turn`: `intent = plan.get("intent")` with a safe default of `None` (malformed/missing → treated as non-`market_news`, current behavior; existing `_parse_plan` + keyword fallback already covers malformed JSON).
3. **Route in `process_turn`** — only the `market_news` branch is new behavior:

   | `intent` | Action |
   |---|---|
   | `market_news` | Fire `_web_search_with_sources(user_input)` **before/independent of** synthesis, feed snippets + sources into the synthesis context; still run any listed agents (e.g. news) for hybrids like "why did NVDA drop today". |
   | `specific_tickers` / `macro_theme` | Unchanged — run the data agents on the tickers (Gate 1/2 as today). |
   | `general_qa` | Unchanged — answer directly, no web search (today's `agents=[]`). |

   This also disambiguates a current gap: a greeting and "why is the market down" can both yield `agents=[]` today and are indistinguishable; `intent` separates them (`general_qa` → answer directly vs `market_news` → web search).

   **Scope guard:** only `market_news` is wired now. The other three labels are recorded but map to existing behavior — we are NOT building Phase D's gates/resolver here. This is a minimal forward-compatible slice of the Phase D router.

### Part 2 — Reactive: deterministic empty/error fallback
4. **New helper** in `tools/search_guardrails.py` (unit-testable in `test_search_guardrails`), `agents_returned_nothing(agent_results: dict) -> bool`:
   - `True` if `agent_results` is empty (every dispatched agent failed/returned `None`), **or**
   - every agent output is "no-data": each non-blank line starts with an error/no-data marker (`ERROR`, `TOOL_ERROR`, `No `, `Could not`, `Unable`, `Unknown tool`, `I don't`). Reuses the marker logic in `agents/_tooling.py:_is_error_result`, extended for `TOOL_ERROR`.
5. **Widen the existing trigger** at `orchestrator.py:224` (this runs only when `intent` was NOT `market_news`, since that path already searched):
   ```python
   if agents_to_run and (agents_returned_nothing(agent_results) or is_uncertain(answer, threshold=0.85)):
       ...existing Tavily fallback...
   ```
6. **Keep `is_uncertain` at ≥0.85** as the tertiary signal so blatant "I don't know" (0.98) still fires. Do **not** lower the threshold (proven not to work).

### Out of scope
- Full Phase D router (gates, `resolve_entities`, structured-output/`response_format`) — the other three intents stay mapped to current behavior.
- `query:`/`passage:` e5 prefix tweak (optional, separate, lower priority).

---

## Testing

Per project testing rules: real data where data is exercised, Ollama (never paid SambaNova) for any LLM-in-the-loop test, every edge case, pytest needs no permission.

### I4
- `test_orchestrator`: assert agents are called with `history=None` (mock `_run_agent`/agent fns, inspect kwargs).
- `test_orchestrator`: with a long fabricated `messages` list, assert `synthesis_messages` contains at most `2 * _SYNTH_HISTORY_TURNS + 2` entries (system + capped history + the question block).
- Continuity smoke (Ollama): a 4-turn conversation where turn 4 references turn 3 still answers correctly (cap preserves recent context).

### I5 — proactive (intent)
- `test_orchestrator`: planner returns `intent="market_news"` → assert `_web_search_with_sources` is called proactively (mocked) and its snippets appear in the synthesis context, regardless of agent outputs.
- `test_orchestrator`: planner returns `intent="specific_tickers"`/`"general_qa"` → assert **no** proactive web search (current behavior preserved).
- `test_orchestrator`: planner omits/garbles `intent` → defaults to non-`market_news`, no proactive search (safe default).

### I5 — reactive (empty/error)
- `test_search_guardrails`: `agents_returned_nothing` truth table — empty dict → True; all-`ERROR:`/`TOOL_ERROR`/`No data` values → True; one real `## AAPL …` value present → False; mixed (one real, one error) → False.
- `test_orchestrator`: non-`market_news` query where all agents return error strings → assert the reactive fallback path is entered (mock `_web_search_with_sources`); when an agent returns real data, assert it is **not** entered (regression against false-firing on confident answers).

---

## Sequencing
I4 and I5 are independent and can land in either order or together. Neither depends on the structured-output (#13) or fidelity-verifier (#14) work; those follow as a separate spec.
