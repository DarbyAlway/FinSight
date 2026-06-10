# LangGraph Migration — Design

**Date:** 2026-06-10
**Branch:** `feature/sambanova`
**Status:** Approved by user 2026-06-10
**Source:** Brainstormed in session 2026-06-10. Activates the LangGraph migration deferred in `claude/plans/pending/2026-06-04-dual-gate-routing-ticker-validation.md` (Phase D + "Connection to LangGraph migration") and explicitly scoped out of `claude/specs/2026-06-09-structured-handoff-fidelity-design.md`.

---

## Motivation (user-confirmed)

Migrate for **new capabilities** — all four, phased:
1. Query decomposition / re-planning (the deferred "headline feature")
2. Graph-native retry loops (fidelity critique, web fallback, escalation as visible conditional edges)
3. Checkpointing / resume
4. Human-in-the-loop (HITL)

Evidence the migration pays for itself: on 2026-06-10 three conditional behaviors (`web_used` flag, HARD-survival escalation, web-synthesis message rebuilding) were hand-patched into the ~250-line `process_turn`. Each is one explicit, testable edge in a graph.

## Decisions (user-confirmed)

- **Strategy: incremental, parity first.** Phase 1 rebuilds `process_turn` as a graph whose nodes wrap the EXISTING functions. Behavior identical; all existing tests (260 as of writing) stay green. Capabilities layer on afterwards.
- **Agent tool loops stay as-is.** Agent nodes call `agents/*.run()` → `run_tool_loop` untouched. Its guardrails (max-iterations, duplicate-call cache, no-progress brake, token budget, expected-tickers self-critique) are battle-tested; LangGraph's prebuilt ReAct agent has none of them. Convert later only on concrete need.
- **Phasing (Approach A — capabilities by cost):** parity → checkpointing → structured router (old Phase D) → decomposition → HITL. Each phase makes the next cheaper.

## Phase 1 — Parity graph

### Topology

```
START → plan → gates ─┬─(agents=[])──────────────→ synthesize
                      └─(Send per agent)→ [financials] [news] [calc] [ratios]
                                              └────── join ──┘
                                                       │
                                     (market_news?) proactive_web
                                                       ↓
                                                  synthesize
                                                       │
        ┌─(market_news: web-sourced, append sources)───┼──────────→ finalize
        │                                              │
        │                     (empty/uncertain?) web_fallback ────→ finalize
        │                                              ↓ (grounded)    ↑
        │                                       fidelity_check ─(clean/soft)
        │                                              ↓ (HARD, 1st pass)
        │                                     self_critique → fidelity_recheck ─(clean)→ finalize
        │                                                         ↓ (HARD survived)
        │                                                  web_escalate ──→ finalize
        │                                     (search → web-grounded answer, or
        └──────────────────────────────────── unverified-figures caveat if web empty)
```

Routing note (parity-critical): after `synthesize`, the `market_news` path goes
DIRECTLY to `finalize` — it must bypass `web_fallback` AND `fidelity_check`,
because its figures are web-sourced and legitimately untraceable in the agents'
tool blocks (today's `intent != "market_news"` / `web_used` guards). The same
applies to any answer produced by `web_fallback` or `web_escalate`: web-grounded
answers are never fidelity-checked against tool blocks.

- `plan` node = `_plan_step` + `_parse_plan` + `_keyword_fallback`, unchanged.
- `gates` node = Gate 1 group-manifest override + Gate 2 `validate_tickers`. Deterministic.
- Agent fan-out via the `Send` API (dynamic parallel dispatch) replaces `ThreadPoolExecutor`; results merge through state reducers instead of `as_completed`.
- Retry behaviors become conditional edges (they are current behavior, not new): web fallback, fidelity self-critique (bounded to one pass by `critique_done`), HARD-survival web escalation.

### State schema

```python
class TurnState(TypedDict):
    # inputs
    user_input: str
    history: list[dict]
    persona_system: str | None
    # planning
    intent: str | None
    agents_to_run: list[str]
    tickers: list[str]
    time_sensitive: bool
    # agent results (merged by reducers from parallel Send nodes)
    agent_results: Annotated[dict[str, str], merge_dicts]
    agent_tool_blocks: Annotated[dict[str, dict], merge_dicts]
    # synthesis
    accumulated_context: str
    answer: str
    web_used: bool
    web_urls: list[str]
    # fidelity control
    hard_mismatches: list[str]
    critique_done: bool
    # accounting
    tokens: Annotated[dict[str, int], add_token_counts]
```

### Compatibility constraints

- `process_turn(user_input, messages, persona_system) -> (answer, updated_messages)` keeps its exact signature — `main.py` untouched.
- Graph nodes call the same module-level names existing tests patch (`orchestrator.llm_chat`, `orchestrator.run_financials`, `orchestrator._web_search_with_sources`, `orchestrator.is_uncertain`) — patch targets preserved.
- Langfuse: keep `@observe` on node functions; the existing OTEL context-attach fix moves into Send-dispatched nodes (LangGraph also runs parallel nodes in threads). One trace per turn, as today.

### Parity criterion

All existing tests pass unchanged, plus a live `fidelity_live_check.py` run produces an equivalent Langfuse trace.

## Phase 2 — Checkpointing

- Compile with `SqliteSaver` from `langgraph-checkpoint-sqlite`, file `checkpoints.db` (separate from the DuckDB data cache).
- One `thread_id` per conversation session; every node output checkpointed.
- Win: an interrupted multi-agent run resumes at the failed node without refetching (~15k agent tokens on a MAG7 query). Prerequisite for HITL.

## Phase 3 — Structured router (activates pending Phase D)

- Replace the `plan` node with a router returning Pydantic `QueryIntent`:
  `action: execute_analysis | grounded_search | fallback_chat`, plus `agents`, `tickers`, and (Phase 4) `sub_questions`.
- I3 fix folded in: router prompt enumerates each agent's concrete tool inventory so routing maps capability → agent. A query no agent can serve (e.g. "screen stocks by weekly price change", live failure 2026-06-10) routes to `grounded_search` directly instead of being discovered via two fabrication rounds.
- **Open question (verify first):** does SambaNova support `response_format` json-schema? Fallback: JSON-mode + Pydantic validation (pydantic 2.x already installed; `instructor` only if needed).

## Phase 4 — Query decomposition (headline)

- Router may emit `sub_questions: list[SubQuestion]` for complex queries.
- Graph gains `decompose → Send(per sub-question subgraph) → gather → completeness_check`.
- `completeness_check` may re-plan ONCE (bounded, like the critique loop) when a sub-answer lacks data.
- Token guardrails: hard cap on sub-questions (5) + per-turn token budget carried in state (lesson from the 95k-token MAG7 incident).

## Phase 5 — HITL (last, smallest)

- `interrupt()` before agent dispatch when Gate 2 dropped tickers or name→ticker resolution confidence is low ("did you mean RKLB or RL?").
- `main.py` CLI handles the interrupt payload with a terminal prompt; resumes via `Command(resume=...)`.
- Requires Phase 2 checkpointer.

## Error handling

- Agent nodes keep try/except + `_log_agent_error`; a failed agent contributes nothing to state (today's behavior).
- Graph-level: any node exception surfaces to `process_turn`'s caller exactly as today (no silent swallowing).

## Testing

Per project rules (real data; Ollama for LLM-loop integration tests, never paid SambaNova; broad edge cases; pytest needs no permission):
- Phase 1 gate: full existing suite green, zero test edits beyond imports if any.
- New graph tests per phase: topology (which edges fire on which state), reducer merging, checkpoint resume (kill mid-run, resume, assert no agent refetch), router actions per query class, decomposition caps, HITL interrupt/resume.
- Live checks on SambaNova only as final validation per phase.

## Dependencies

`langgraph`, `langgraph-checkpoint-sqlite`. Nothing else changes — agents, tools, fidelity verifier, prompts all stay put.

## Out of scope

- Converting `run_tool_loop` to subgraphs (revisit only on concrete need).
- LLM-judge semantic fidelity checks (deterministic verifier stays).
- Streaming UI (LangGraph enables it later; not a goal here).
- New data tools (e.g. a yfinance screener for price-change queries) — separate workstream; noted as a Phase-3 router capability candidate.

## Build order

1. Phase 1 parity graph → all tests green → live check.
2. Phase 2 checkpointing → resume test.
3. Phase 3 structured router (verify SambaNova `response_format` FIRST).
4. Phase 4 decomposition.
5. Phase 5 HITL.
