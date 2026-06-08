# #13 Structured Hand-off + #14 Year-Aware Fidelity Verifier — Design

**Date:** 2026-06-09
**Branch:** `feature/sambanova`
**Status:** Designed, pending review
**Source:** Activates Phase F stretch items #13 + #14 from `claude/plans/pending/2026-06-04-dual-gate-routing-ticker-validation.md`. Design brainstormed in session 2026-06-08/09.

---

## Problem

A financial figure is retyped **twice as free text** before the user sees it:

```
tool output (validated)  →  agent LLM prose  →  synthesis LLM prose
   ✓ correct at source        ✗ retyped           ✗ retyped
```

Nothing checks that a number in the final answer matches a number the tools actually returned. This is the **retype-drift** failure mode.

### Scope note (from the 2026-06-08 Langfuse trace investigation)
The Apple "FY2025 = $383,058M, decreased $7,977M" hallucination was **NOT** retype-drift — the planner returned `agents=[]` ("conversational"), **no agent ran**, and synthesis answered from chat history + training data. That is a **routing** failure, tracked separately (planner must not drop a follow-up data question as chit-chat; guard the no-agent path). `#13` does not fix it. `#14`'s verifier **does flag it** (empty grounding → every `$` number untraceable). This spec targets retype-drift; the verifier doubles as a detector for the no-agent case.

---

## Design overview

Two pieces, built **detector-first**:

1. **`#14` verifier (build first — cheap, flag-only, immediate observability).** After synthesis, deterministically check every unit-bearing number in the answer against the **raw tool outputs** for that ticker, **year-aware**, within tolerance. Log mismatches + emit a Langfuse score. Never mutate the answer. This requires plumbing the agents' raw tool outputs up to the orchestrator (they're already captured in `run_tool_loop`'s `seen` dict, then discarded).

2. **`#13` structured hand-off (build second — bigger, the actual prevention).** Tools return **code-filled** structured `(fiscal_year, line_item, value)` data; the agent passes that structured data to synthesis alongside a **number-free** qualitative summary; synthesis quotes figures from the structured data. Removes the retype hops so the value can't be detached from its year.

Building `#14` first lets us **measure the real drift rate** in Langfuse before paying for the `#13` refactor — and tells us whether `#13` is even worth it.

---

## Phase 1 — Plumb raw tool outputs up (prerequisite for `#14`)

`run_tool_loop` (`agents/_tooling.py`) already keeps every tool result in `seen: dict[(name, args_json) -> result]`, then throws it away. Surface it.

- `run_tool_loop(...)` returns `(summary, total, tool_blocks)` where `tool_blocks` is a `dict[str, str]` of `"name(args)" -> result` from `seen` (results already capped at 3000 chars by `execute_tool`).
- All four agent `run()` functions (`financials/news/calc/ratios`) propagate the third value (they currently `return run_tool_loop(...)` directly — one-line change each + signature update to `tuple[str, int, dict]`).
- `orchestrator._run_agent` collects `tool_blocks` per agent into a `agent_tool_blocks: dict[str, dict]` keyed by agent name. No behavior change yet — just carrying the data.

## Phase 2 — `#14` year-aware verifier (flag-only)

New module `tools/fidelity.py`, pure + unit-testable:

- `extract_numbers(text) -> list[Number]` — captures only **unit-bearing** numbers (`$…` with optional T/B/M/K suffix, `…%`, `…x`). Each normalized to `(value, kind)`:
  - `$` + magnitude → `money_millions` (`$391B` → `391000`); `$` plain → `dollars` (`$182.50`); `%` → `percent`; `x` → `ratio`.
  - **Ignored:** bare integers, 4-digit years, counts ("3-year", "5 stocks") — primary false-positive defense.
- `extract_year_bound_numbers(text) -> list[(fiscal_year|None, value, kind)]` — associate a number with the nearest fiscal-year token on its line/sentence (e.g. "FY2025", "Sep 27, 2025", "2025"). When a year is present, the check is year-scoped; when absent, fall back to any-year matching.
- `build_grounding(tool_blocks) -> grounding` — parse the raw tool outputs the same way into `{(fiscal_year, kind) -> set[value]}` plus an any-year index.
- `verify(answer, tool_blocks, rel_tol=0.01) -> list[Mismatch]` — for each answer number: if it carries a year, require a same-kind grounding value **for that year** within ±1%; else require a same-kind value in any year. None → mismatch.

**Why year-aware:** `$383,058M` labeled FY2025 is within 0.06% of FY2023's real `$383,285M`; a value-only check passes it. Year-scoping catches the mislabel.

### Wiring (orchestrator, after the final `answer` is settled)
```python
if agent_tool_blocks:  # only when agents actually ran
    mismatches = verify(answer, _merge(agent_tool_blocks))
    for m in mismatches:
        logging.warning("[fidelity] %s '%s' (%s, year=%s) not traced to tool output",
                        m.ticker_hint, m.raw, m.kind, m.year)
    lf.score(name="fidelity_mismatches", value=len(mismatches))  # Langfuse trace score
# NEVER mutate `answer`.
```
On the **no-agent path** (`agent_tool_blocks` empty) the grounding is empty, so any `$`/`%` number in a "conversational" answer is reported — this is the detector for the routing-hallucination case.

## Phase 3 — `#13` structured hand-off (prevention)

Done only if Phase-2 logs show meaningful drift. Build incrementally, **financials/income path first** (the revenue case), then ratios/calc.

- Tools return code-filled structured results (extend existing `tools/schemas.py` `StatementRow`), e.g. `get_income_statement` also yields `list[StatementRow]` (already parsed — just stop discarding the structure). Reuse the DuckDB rows; the LLM never types these.
- The agent returns `(structured_data, number_free_summary)`:
  - structured_data → exact figures, the source of truth;
  - summary → LLM prose with **zero unit-bearing numbers** (qualitative trends only). Keep the summary — a prior "tool-select only, no agent summary" attempt was reverted for the missing-ticker problem; the now-present `expected_tickers` self-critique is the safeguard that makes it safe.
- Synthesis context gains a `[SOURCE DATA]` block built from the structured data; `SYNTHESIS_SYSTEM` gains one line: *"Quote figures only from the SOURCE DATA block; use the summary for narrative."*
- **Pydantic enforces** both: structure validity AND a validator that **rejects a summary containing unit-bearing numbers**.
- **Completeness check:** extend the existing `expected_tickers` self-critique to "expected metrics present"; on failure, re-prompt via the **existing tool-loop pattern** — NOT LangGraph (rejected: large migration, the loop already exists).

---

## Out of scope
- Routing / no-agent-path fix (separate workstream — the actual Apple-trace fix).
- LangGraph migration (Phase D) — the retry uses the existing self-critique loop.
- Auto-correcting/re-prompting on a fidelity mismatch — `#14` is flag-only by decision; revisit after measuring.
- LLM-judge for semantic checks — deferred; deterministic year-aware check is cheaper and more reliable for numbers.

## Testing
Per project rules (real data, Ollama not paid SambaNova, every edge case, pytest no-permission):
- `tests/test_fidelity.py` — `extract_numbers` across real tool formats (`$391,035M`, `$1.23B`, `45.2%`, `1.85x`, `0.733`, `$182.50`); `verify` cases: exact, reformatted unit, rounded, genuinely-wrong, **year-mislabel ($383,058M as FY2025 vs FY2023 $383,285M → MUST flag)**, year/count ignored, empty-grounding (no-agent) flags all.
- Orchestrator test: tool_blocks reach the verifier; a planted wrong number is logged, answer unchanged.
- Phase 3: structured income path returns `StatementRow`s; summary-with-a-number is rejected by Pydantic; synthesis quotes the structured value.

## Build order
1. Phase 1 (plumb tool_blocks) + Phase 2 (`#14` verifier, flag-only) → ship, watch Langfuse drift rate.
2. Decide on Phase 3 (`#13`) based on measured drift; build financials/income path first.
