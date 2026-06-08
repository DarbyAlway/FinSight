# I4 (history token cost) + I5 (web-search fallback trigger) — Design

**Date:** 2026-06-08
**Branch:** `feature/sambanova`
**Status:** Designed, pending implementation
**Source:** Activates two open items from `claude/plans/pending/2026-06-04-dual-gate-routing-ticker-validation.md` (I4, I5). Independent of the fidelity/structured-output work (Phase F #13/#14), which comes after.

---

## Why

Two independent, router-independent issues observed in live testing:

- **I4 — history token cost.** Every data agent is handed `history[-6:]` (`agents/*.py`), and synthesis is handed the **full** message history (`orchestrator.py:206`). Tokens grow every turn (the SNOW run jumped 17.5k→20k from one prior turn). SambaNova has **no prompt caching**, so every re-sent byte is paid.
- **I5 — unreliable web-search fallback.** The Tavily fallback fires only on `is_uncertain(answer, 0.85)` (`orchestrator.py:224`). The plan **measured** that this embedding score cannot separate a real "no data" answer (0.836) from a confident greeting (0.832) — so genuinely-unanswerable queries silently get no fallback.

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

## I5 — Reliable web-search fallback trigger

**Decision:** add a **deterministic "agents returned nothing usable" trigger** alongside the existing `is_uncertain` check. Straight from the plan's measured conclusion.

### Changes
1. **New helper** in `tools/search_guardrails.py` (so it's unit-testable in `test_search_guardrails`), `agents_returned_nothing(agent_results: dict) -> bool`:
   - `True` if `agent_results` is empty (every dispatched agent failed/returned `None`), **or**
   - every agent output is "no-data": each non-blank line starts with an error/no-data marker (`ERROR`, `TOOL_ERROR`, `No `, `Could not`, `Unable`, `Unknown tool`, `I don't`). Reuses the marker logic already in `agents/_tooling.py:_is_error_result`, extended for `TOOL_ERROR`.
2. **Widen the trigger** at `orchestrator.py:224`:
   ```python
   if agents_to_run and (agents_returned_nothing(agent_results) or is_uncertain(answer, threshold=0.85)):
       ...existing Tavily fallback...
   ```
3. **Keep `is_uncertain` at ≥0.85** as the secondary signal so blatant "I don't know" (0.98) still fires. Do **not** lower the threshold (proven not to work).

### Out of scope
- `query:`/`passage:` e5 prefix tweak (optional, separate, lower priority).

---

## Testing

Per project testing rules: real data where data is exercised, Ollama (never paid SambaNova) for any LLM-in-the-loop test, every edge case, pytest needs no permission.

### I4
- `test_orchestrator`: assert agents are called with `history=None` (mock `_run_agent`/agent fns, inspect kwargs).
- `test_orchestrator`: with a long fabricated `messages` list, assert `synthesis_messages` contains at most `2 * _SYNTH_HISTORY_TURNS + 2` entries (system + capped history + the question block).
- Continuity smoke (Ollama): a 4-turn conversation where turn 4 references turn 3 still answers correctly (cap preserves recent context).

### I5
- `test_search_guardrails`: `_agents_returned_nothing` truth table — empty dict → True; all-`ERROR:`/`TOOL_ERROR`/`No data` values → True; one real `## AAPL …` value present → False; mixed (one real, one error) → False.
- `test_orchestrator`: when all agents return error strings, assert the fallback path is entered (mock `_web_search_with_sources`); when an agent returns real data, assert it is **not** entered (regression against false-firing on confident answers).

---

## Sequencing
I4 and I5 are independent and can land in either order or together. Neither depends on the structured-output (#13) or fidelity-verifier (#14) work; those follow as a separate spec.
