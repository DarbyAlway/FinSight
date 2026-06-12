# LangGraph Migration — Phase 1 (Parity Graph) + Phase 2 (Checkpointing) Implementation Plan

> **✅ COMPLETED 2026-06-12** — all 8 tasks done via subagent-driven development, each with
> spec-compliance + code-quality review. Final suite: **304 passed, 0 failed** (incl. Qdrant
> vector tests). Key commits: `4f3eb7e` (state), `f0486d3` (routes), `5506823`+`52d3ceb`+`6820ac7`
> (nodes + parity fixes), `7077614`+`9800d69` (graph cutover + empty-web-fallback parity edge),
> `38d69f2`+`aeeeb30` (sqlite checkpointing + test-isolation fixes). Langfuse trace nesting
> verified live (single `process_turn` trace, agent spans nested — no OTEL bridge needed).
> Review-driven additions beyond the plan: `mismatch_count` state field (unconditional fidelity
> log/score parity), `_route_after_web_fallback` (empty Tavily result re-enters fidelity chain),
> `CHECKPOINT_DB` env override (tests use `:memory:`), thread_id logging + reuse-hazard docs.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `process_turn` as a LangGraph `StateGraph` with identical behavior (all 260 tests stay green), then add SQLite checkpointing for crash-resume.

**Architecture:** Nodes are thin wrappers around the EXISTING orchestrator functions, defined inside `orchestrator.py` so test patch targets (`orchestrator.llm_chat`, `orchestrator.run_financials`, …) keep working. Parallel agent dispatch uses the `Send` API with dict-merge reducers replacing `ThreadPoolExecutor`. All `if`-based retry behavior (web fallback, fidelity critique, escalation) becomes conditional edges. Spec: `claude/specs/2026-06-10-langgraph-migration-design.md`.

**Tech Stack:** langgraph, langgraph-checkpoint-sqlite, existing stack (openai client via `tools/llm.py`, langfuse, pydantic).

**Environment note:** ALWAYS run python/pytest via `C:\Users\Yatta\miniconda3\envs\stock\python.exe` (base env has broken edgartools). Qdrant docker must be running for 4 vector tests.

---

### Task 1: Install dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Install**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pip install langgraph langgraph-checkpoint-sqlite`

- [ ] **Step 2: Smoke-verify imports**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -c "from langgraph.graph import StateGraph, START, END; from langgraph.types import Send; from langgraph.checkpoint.sqlite import SqliteSaver; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Add to requirements.txt** (append two lines)

```
langgraph
langgraph-checkpoint-sqlite
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add langgraph + sqlite checkpointer deps"
```

---

### Task 2: Graph state schema + reducers

**Files:**
- Create: `graph_state.py` (repo root, next to orchestrator.py)
- Test: `tests/test_graph_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph_state.py
from graph_state import merge_dicts, add_token_counts


def test_merge_dicts_combines_parallel_agent_results():
    assert merge_dicts({"financials": "a"}, {"news": "b"}) == {"financials": "a", "news": "b"}


def test_merge_dicts_handles_none_sides():
    assert merge_dicts(None, {"x": 1}) == {"x": 1}
    assert merge_dicts({"x": 1}, None) == {"x": 1}
    assert merge_dicts(None, None) == {}


def test_merge_dicts_right_side_wins_on_collision():
    assert merge_dicts({"x": 1}, {"x": 2}) == {"x": 2}


def test_add_token_counts_sums_per_key():
    assert add_token_counts({"agents": 100}, {"agents": 50, "plan": 10}) == {"agents": 150, "plan": 10}


def test_add_token_counts_handles_none():
    assert add_token_counts(None, {"plan": 5}) == {"plan": 5}
```

- [ ] **Step 2: Run to verify failure**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest tests/test_graph_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'graph_state'`

- [ ] **Step 3: Implement graph_state.py**

```python
"""LangGraph state schema for the orchestrator turn graph (Phase 1 parity).

Reducers replace the ThreadPoolExecutor `as_completed` merging: parallel
Send-dispatched agent nodes each return their slice; LangGraph merges them.
"""
from typing import Annotated, TypedDict


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


def add_token_counts(a: dict | None, b: dict | None) -> dict:
    out = dict(a or {})
    for key, value in (b or {}).items():
        out[key] = out.get(key, 0) + value
    return out


class TurnState(TypedDict, total=False):
    # inputs
    user_input: str
    history: list          # prior conversation messages (role/content dicts)
    persona_system: str | None
    # derived once in plan_node
    synth_sys: str
    time_sensitive: bool
    # planning
    intent: str | None
    agents_to_run: list
    tickers: list
    # agent results — merged by reducers from parallel Send nodes
    agent_results: Annotated[dict, merge_dicts]
    agent_tool_blocks: Annotated[dict, merge_dicts]
    # synthesis
    accumulated_context: str
    synthesis_messages: list   # kept for critique/escalation re-prompts
    answer: str
    web_used: bool
    web_urls: list             # proactive (market_news) source urls
    # fidelity control
    hard_raws: list            # raw strings of HARD-mismatched figures
    critique_done: bool
    # accounting
    tokens: Annotated[dict, add_token_counts]
    # Send-payload fields (set per agent_node invocation only)
    agent_name: str
    agent_input: str
```

- [ ] **Step 4: Run to verify pass**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest tests/test_graph_state.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add graph_state.py tests/test_graph_state.py
git commit -m "feat(langgraph): turn-state schema + merge reducers"
```

---

### Task 3: Pure routing functions (the conditional edges)

**Files:**
- Modify: `orchestrator.py` (add functions; do NOT touch `process_turn` yet)
- Test: `tests/test_graph_routes.py`

These four functions encode every `if` that becomes an edge. They are pure
(state-dict in, route-name or Send-list out) so they get exhaustive unit tests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph_routes.py
from unittest.mock import patch

from langgraph.types import Send


def _send_names(routes):
    return sorted(s.arg["agent_name"] for s in routes)


def test_route_after_gates_dispatches_one_send_per_agent():
    from orchestrator import _route_after_gates
    state = {"agents_to_run": ["financials", "news"], "tickers": ["AAPL"],
             "user_input": "analyze AAPL", "history": []}
    routes = _route_after_gates(state)
    assert all(isinstance(s, Send) and s.node == "agent" for s in routes)
    assert _send_names(routes) == ["financials", "news"]
    # ticker hint must be prepended exactly as today
    assert routes[0].arg["agent_input"] == "[Use exactly these tickers: AAPL]\nanalyze AAPL"


def test_route_after_gates_no_agents_goes_to_collect():
    from orchestrator import _route_after_gates
    assert _route_after_gates({"agents_to_run": [], "tickers": [], "user_input": "hi", "history": []}) == "collect"


def test_route_after_collect_market_news_goes_proactive():
    from orchestrator import _route_after_collect
    assert _route_after_collect({"intent": "market_news"}) == "proactive_web"
    assert _route_after_collect({"intent": "specific_tickers"}) == "synthesize"


def test_route_after_synthesis_market_news_finalizes_directly():
    """Review fix in spec: market_news bypasses web_fallback AND fidelity."""
    from orchestrator import _route_after_synthesis
    state = {"intent": "market_news", "agents_to_run": ["news"], "agent_results": {"news": "data"},
             "agent_tool_blocks": {"news": {"t": "x"}}, "answer": "markets fell"}
    assert _route_after_synthesis(state) == "finalize"


def test_route_after_synthesis_empty_agents_data_goes_web_fallback():
    from orchestrator import _route_after_synthesis
    state = {"intent": "specific_tickers", "agents_to_run": ["financials"],
             "agent_results": {"financials": "ERROR: nothing"}, "agent_tool_blocks": {},
             "answer": "no data"}
    with patch("orchestrator.is_uncertain", return_value=False):
        assert _route_after_synthesis(state) == "web_fallback"


def test_route_after_synthesis_grounded_goes_fidelity():
    from orchestrator import _route_after_synthesis
    state = {"intent": "specific_tickers", "agents_to_run": ["financials"],
             "agent_results": {"financials": "## AAPL\nRevenue: $391,035M"},
             "agent_tool_blocks": {"financials": {"get_income_statement({})": "Revenue: 391,035M"}},
             "answer": "Revenue was $391,035M"}
    with patch("orchestrator.is_uncertain", return_value=False):
        assert _route_after_synthesis(state) == "fidelity_check"


def test_route_after_synthesis_no_tool_blocks_finalizes():
    from orchestrator import _route_after_synthesis
    state = {"intent": "specific_tickers", "agents_to_run": ["financials"],
             "agent_results": {"financials": "## AAPL\nreal data"}, "agent_tool_blocks": {},
             "answer": "answer"}
    with patch("orchestrator.is_uncertain", return_value=False):
        assert _route_after_synthesis(state) == "finalize"


def test_route_after_fidelity_hard_goes_critique():
    from orchestrator import _route_after_fidelity
    assert _route_after_fidelity({"hard_raws": ["20.3%"], "critique_done": False}) == "self_critique"
    assert _route_after_fidelity({"hard_raws": [], "critique_done": False}) == "finalize"


def test_route_after_critique_surviving_hard_escalates():
    from orchestrator import _route_after_critique
    assert _route_after_critique({"hard_raws": ["20.3%"], "critique_done": True}) == "web_escalate"
    assert _route_after_critique({"hard_raws": [], "critique_done": True}) == "finalize"
```

- [ ] **Step 2: Run to verify failure**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest tests/test_graph_routes.py -q`
Expected: FAIL — `ImportError: cannot import name '_route_after_gates'`

- [ ] **Step 3: Implement the four route functions in orchestrator.py** (add below `_web_synthesis_messages`; add `from langgraph.types import Send` to imports)

```python
def _route_after_gates(state: dict):
    """Fan out one Send per planned agent, or skip straight to collect."""
    agents_to_run = state.get("agents_to_run") or []
    if not agents_to_run:
        return "collect"
    tickers = state.get("tickers") or []
    ticker_hint = f"[Use exactly these tickers: {', '.join(tickers)}]\n" if tickers else ""
    agent_input = ticker_hint + state["user_input"]
    return [
        Send("agent", {
            "agent_name": name,
            "agent_input": agent_input,
            "history": state.get("history", []),
            "tickers": tickers,
        })
        for name in agents_to_run
    ]


def _route_after_collect(state: dict) -> str:
    return "proactive_web" if state.get("intent") == "market_news" else "synthesize"


def _route_after_synthesis(state: dict) -> str:
    """market_news is web-sourced → finalize directly (never fidelity-checked).
    Empty/uncertain agent data → web fallback. Grounded + tool blocks → fidelity."""
    if state.get("intent") == "market_news":
        return "finalize"
    agents_to_run = state.get("agents_to_run") or []
    if agents_to_run and (
        agents_returned_nothing(state.get("agent_results") or {})
        or is_uncertain(state.get("answer", ""), threshold=0.85)
    ):
        return "web_fallback"
    if state.get("agent_tool_blocks"):
        return "fidelity_check"
    return "finalize"


def _route_after_fidelity(state: dict) -> str:
    return "self_critique" if state.get("hard_raws") else "finalize"


def _route_after_critique(state: dict) -> str:
    return "web_escalate" if state.get("hard_raws") else "finalize"
```

- [ ] **Step 4: Run new tests + existing orchestrator tests**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest tests/test_graph_routes.py tests/test_orchestrator.py -q`
Expected: all pass (route functions are additive; process_turn untouched)

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_graph_routes.py
git commit -m "feat(langgraph): pure routing functions for conditional edges"
```

---

### Task 4: Node functions (transplant process_turn bodies)

**Files:**
- Modify: `orchestrator.py` (add node functions; `process_turn` STILL untouched)
- Test: `tests/test_graph_nodes.py`

Nodes wrap existing module-level functions. CRITICAL: resolve patchable names
at CALL time inside node bodies (e.g. build the agent map inside `_agent_node`),
never at import time — otherwise `patch("orchestrator.run_financials")` breaks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph_nodes.py
import json
from unittest.mock import MagicMock, patch


def test_plan_node_parses_plan_and_counts_tokens():
    from orchestrator import _plan_node
    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"],
                            "tickers": ["AAPL"], "reason": "r"})
    with patch("orchestrator.llm_chat", return_value=(plan_json, 42)):
        out = _plan_node({"user_input": "AAPL revenue?", "history": [], "persona_system": None})
    assert out["agents_to_run"] == ["financials"]
    assert out["tickers"] == ["AAPL"]
    assert out["intent"] == "specific_tickers"
    assert out["tokens"] == {"plan": 42}
    assert "synth_sys" in out


def test_plan_node_malformed_json_uses_keyword_fallback():
    from orchestrator import _plan_node
    with patch("orchestrator.llm_chat", return_value=("not json at all", 0)):
        out = _plan_node({"user_input": "latest news on AAPL", "history": [], "persona_system": None})
    assert out["agents_to_run"] == ["news"]


def test_gates_node_drops_invalid_tickers():
    from orchestrator import _gates_node
    with patch("orchestrator.validate_tickers", return_value=([], ["FAKETICK"])), \
         patch("orchestrator.detect_group_in_query", return_value=None):
        out = _gates_node({"user_input": "analyze FAKETICK", "tickers": ["FAKETICK"],
                           "agents_to_run": ["financials"]})
    assert out["tickers"] == []
    assert out["agents_to_run"] == []   # all invalid → skip data agents


def test_agent_node_returns_result_blocks_and_tokens():
    from orchestrator import _agent_node
    with patch("orchestrator.run_financials",
               return_value=("## AAPL\nRevenue: $391,035M", 99, {"t": "raw"})):
        out = _agent_node({"agent_name": "financials", "agent_input": "AAPL revenue?",
                           "history": [], "tickers": ["AAPL"]})
    assert out["agent_results"] == {"financials": "## AAPL\nRevenue: $391,035M"}
    assert out["agent_tool_blocks"] == {"financials": {"t": "raw"}}
    assert out["tokens"] == {"agents": 99}


def test_agent_node_failure_contributes_nothing():
    from orchestrator import _agent_node
    with patch("orchestrator.run_financials", side_effect=RuntimeError("boom")):
        out = _agent_node({"agent_name": "financials", "agent_input": "x",
                           "history": [], "tickers": []})
    assert out["agent_results"] == {}
    assert out["agent_tool_blocks"] == {}


def test_collect_node_orders_context_with_neutral_labels():
    from orchestrator import _collect_node
    out = _collect_node({
        "agents_to_run": ["financials", "ratios"],
        "agent_results": {"ratios": "MARGIN DATA", "financials": "PRICE DATA"},
    })
    ctx = out["accumulated_context"]
    assert ctx.index("[MARKET DATA]") < ctx.index("[SEC RATIOS]")   # plan order kept
    assert "AGENT]" not in ctx


def test_fidelity_node_flags_hard_raws():
    from orchestrator import _fidelity_check_node
    state = {"answer": "AAPL fell 20.3% this week.",
             "agent_tool_blocks": {"financials": {"get_company_info({})": "Current Price: $290.55"}}}
    out = _fidelity_check_node(state)
    assert out["hard_raws"] == ["20.3%"]


def test_fidelity_node_clean_answer_no_hard():
    from orchestrator import _fidelity_check_node
    state = {"answer": "Revenue was 391,035M in FY2024.",
             "agent_tool_blocks": {"financials": {"t": "Total revenue: 391,035M  (Sep 28, 2024)"}}}
    out = _fidelity_check_node(state)
    assert out["hard_raws"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest tests/test_graph_nodes.py -q`
Expected: FAIL — `ImportError: cannot import name '_plan_node'`

- [ ] **Step 3: Implement the node functions in orchestrator.py**

Each is a verbatim transplant of the corresponding `process_turn` segment, with
locals replaced by state keys. Add these below the route functions:

```python
_SOURCE_LABELS = {
    "financials": "MARKET DATA",
    "news": "NEWS",
    "calc": "CALCULATIONS",
    "ratios": "SEC RATIOS",
}


@observe(name="plan_node")
def _plan_node(state: dict) -> dict:
    user_input = state["user_input"]
    time_sensitive = _is_time_sensitive(user_input)
    today_str = date.today().strftime("%B %d, %Y") if time_sensitive else ""
    today_prefix = f"Today is {today_str}. " if today_str else ""
    plan_sys = PLAN_SYSTEM.replace("{today}", today_prefix)
    synth_sys = (state.get("persona_system") or SYNTHESIS_SYSTEM).replace("{today}", today_prefix)

    planning_messages = [
        {"role": "system", "content": plan_sys},
        *state.get("history", []),
        {"role": "user", "content": user_input},
    ]
    plan_content, plan_tokens = _plan_step(planning_messages)
    intent = None
    try:
        plan = _parse_plan(plan_content)
        agents_to_run = plan.get("agents", [])
        tickers = plan.get("tickers", [])
        intent = plan.get("intent")
        logging.info("[Orchestrator] plan → intent=%s agents=%s  tickers=%s  reason=%s",
                     intent, agents_to_run, tickers, plan.get("reason", ""))
    except (json.JSONDecodeError, ValueError):
        logging.warning("[Orchestrator] plan JSON malformed — using keyword fallback")
        agents_to_run = _keyword_fallback(user_input)
        tickers = []
        logging.info("[Orchestrator] keyword fallback → agents=%s", agents_to_run)
    return {
        "intent": intent, "agents_to_run": agents_to_run, "tickers": tickers,
        "time_sensitive": time_sensitive, "synth_sys": synth_sys,
        "tokens": {"plan": plan_tokens},
    }


def _gates_node(state: dict) -> dict:
    user_input = state["user_input"]
    tickers = list(state.get("tickers") or [])
    agents_to_run = list(state.get("agents_to_run") or [])
    group_tickers = detect_group_in_query(user_input)
    if group_tickers:
        if set(group_tickers) != set(tickers):
            logging.info("[Gate1] manifest override: planner tickers=%s → %s", tickers, group_tickers)
        tickers = group_tickers
    if tickers:
        valid_tickers, invalid_tickers = validate_tickers(tickers)
        if invalid_tickers:
            logging.info("[Gate2] dropped invalid/unlisted tickers %s (kept %s)",
                         invalid_tickers, valid_tickers)
            tickers = valid_tickers
            if not tickers:
                logging.info("[Gate2] all requested tickers invalid — skipping data agents")
                agents_to_run = []
    return {"tickers": tickers, "agents_to_run": agents_to_run}


@observe(name="agent_node")
def _agent_node(state: dict) -> dict:
    # Build the map at CALL time so tests can patch orchestrator.run_financials etc.
    agent_map = {"financials": run_financials, "news": run_news,
                 "calc": run_calc, "ratios": run_ratios}
    name = state["agent_name"]
    fn = agent_map.get(name)
    if fn is None:
        logging.warning("[Orchestrator] unknown agent '%s' — skipping", name)
        return {"agent_results": {}, "agent_tool_blocks": {}, "tokens": {"agents": 0}}
    try:
        logging.info("[Orchestrator] → calling agent: %s", name)
        t1 = time.time()
        result, agent_tokens, tool_blocks = fn(
            state["agent_input"], "", history=state.get("history", []),
            expected_tickers=state.get("tickers") or None,
        )
        logging.info("[Orchestrator] ✓ agent %s done (%.2fs)", name, time.time() - t1)
        return {
            "agent_results": {name: result} if result is not None else {},
            "agent_tool_blocks": {name: tool_blocks} if tool_blocks else {},
            "tokens": {"agents": agent_tokens},
        }
    except Exception as e:
        logging.warning("[Orchestrator] %s agent failed — %s", name, e)
        _log_agent_error(name, e)
        return {"agent_results": {}, "agent_tool_blocks": {}, "tokens": {"agents": 0}}


def _collect_node(state: dict) -> dict:
    accumulated_context = ""
    agent_results = state.get("agent_results") or {}
    for name in state.get("agents_to_run") or []:
        if name in agent_results:
            label = _SOURCE_LABELS.get(name, name.upper())
            accumulated_context += f"\n\n[{label}]\n{agent_results[name]}"
    return {"accumulated_context": accumulated_context}


def _proactive_web_node(state: dict) -> dict:
    web_snippets, urls = _web_search_with_sources(
        state["user_input"], time_sensitive=state.get("time_sensitive", False))
    updates: dict = {"web_urls": urls}
    if web_snippets:
        updates["accumulated_context"] = (
            state.get("accumulated_context", "") + f"\n\n[WEB SEARCH RESULTS]\n{web_snippets}")
        logging.info("[Orchestrator] market_news → proactive web search (%d sources)", len(urls))
    return updates


@observe(name="synthesize_node")
def _synthesize_node(state: dict) -> dict:
    accumulated_context = state.get("accumulated_context", "")
    synthesis_messages = [{"role": "system", "content": state["synth_sys"]},
                          *state.get("history", [])]
    if accumulated_context:
        synthesis_messages.append({
            "role": "user",
            "content": (
                f"Question: {state['user_input']}\n\n"
                f"Agent outputs:\n{accumulated_context}\n\n"
                "Answer the question above using ONLY the agent outputs. "
                "Quote specific figures directly from the outputs."
            ),
        })
    else:
        synthesis_messages.append({"role": "user", "content": state["user_input"]})
    logging.info("[Synthesis] model=%s agents_context=%d chars", MODEL_SYNTHESIS, len(accumulated_context))
    answer, synth_tokens = _synthesis_step(synthesis_messages)
    logging.info("[Synthesis] output preview: %s", answer[:120].replace("\n", " "))
    return {"answer": answer, "synthesis_messages": synthesis_messages,
            "tokens": {"synthesis": synth_tokens}}


def _web_fallback_node(state: dict) -> dict:
    snippets, urls = _web_search_with_sources(
        state["user_input"], time_sensitive=state.get("time_sensitive", False))
    if not snippets:
        return {}
    web_messages = _web_synthesis_messages(
        state["synth_sys"], state.get("history", []), state["user_input"], snippets)
    fallback_answer, fallback_tokens = _synthesis_step(web_messages)
    answer = fallback_answer or state.get("answer", "")
    logging.info("[Synthesis] web-fallback output preview: %s", answer[:120].replace("\n", " "))
    if urls:
        answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in urls)
    logging.info("[Orchestrator] Tavily fallback used (%d sources)", len(urls))
    return {"answer": answer, "web_used": True, "tokens": {"synthesis": fallback_tokens}}


def _fidelity_check_node(state: dict) -> dict:
    merged_blocks: dict = {}
    for blocks in (state.get("agent_tool_blocks") or {}).values():
        merged_blocks.update(blocks)
    if not merged_blocks:
        return {"hard_raws": []}
    mismatches = verify_fidelity(state["answer"], merged_blocks)
    for m in mismatches:
        logging.warning("[fidelity] %s untraced number %r (kind=%s, year=%s)",
                        "HARD" if m.hard else "soft", m.number.raw, m.number.kind, m.year)
    hard_raws = sorted({m.number.raw for m in mismatches if m.hard})
    if not hard_raws:
        logging.info("[fidelity] checked answer: %d untraced unit-bearing number(s)", len(mismatches))
        _score_fidelity(len(mismatches))
    return {"hard_raws": hard_raws}


def _self_critique_node(state: dict) -> dict:
    merged_blocks: dict = {}
    for blocks in (state.get("agent_tool_blocks") or {}).values():
        merged_blocks.update(blocks)
    bad = ", ".join(state["hard_raws"])
    logging.warning("[fidelity] %d HARD mismatch(es) [%s] → self-critique re-prompt",
                    len(state["hard_raws"]), bad)
    critique_messages = state["synthesis_messages"] + [
        {"role": "assistant", "content": state["answer"]},
        {"role": "user", "content": (
            f"Self-check: the figures [{bad}] in your answer do NOT appear in the agent "
            "outputs above — they look like prior knowledge, not the provided data. "
            "Re-read the agent outputs and rewrite your answer using ONLY figures that "
            "appear there. For any value not present, state that it is not available "
            "rather than estimating or recalling it."
        )},
    ]
    corrected, corr_tokens = _synthesis_step(critique_messages)
    answer = state["answer"]
    hard_raws = state["hard_raws"]
    if corrected:
        answer = corrected
        mismatches = verify_fidelity(answer, merged_blocks)
        hard_raws = sorted({m.number.raw for m in mismatches if m.hard})
        logging.info("[fidelity] after self-critique: %d untraced (%d hard)",
                     len(mismatches), len(hard_raws))
        logging.info("[fidelity] checked answer: %d untraced unit-bearing number(s)", len(mismatches))
        _score_fidelity(len(mismatches))
    return {"answer": answer, "hard_raws": hard_raws, "critique_done": True,
            "tokens": {"synthesis": corr_tokens}}


def _web_escalate_node(state: dict) -> dict:
    bad_after = ", ".join(state["hard_raws"])
    logging.warning("[fidelity] %d HARD mismatch(es) [%s] survived self-critique → web escalation",
                    len(state["hard_raws"]), bad_after)
    snippets, urls = _web_search_with_sources(
        state["user_input"], time_sensitive=state.get("time_sensitive", False))
    if snippets:
        web_messages = _web_synthesis_messages(
            state["synth_sys"], state.get("history", []), state["user_input"], snippets)
        web_answer, web_tokens = _synthesis_step(web_messages)
        if web_answer:
            answer = web_answer
            if urls:
                answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in urls)
            logging.info("[fidelity] escalation: web-grounded re-answer (%d sources)", len(urls))
            return {"answer": answer, "web_used": True, "tokens": {"synthesis": web_tokens}}
        return {"tokens": {"synthesis": web_tokens}}
    answer = state["answer"] + (
        "\n\n**Data caveat:** the figures "
        f"[{bad_after}] could not be verified against the fetched data — "
        "treat them as unreliable."
    )
    logging.warning("[fidelity] escalation: web empty — shipped with unverified-figures caveat")
    return {"answer": answer}


def _finalize_node(state: dict) -> dict:
    answer = state.get("answer", "")
    if state.get("intent") == "market_news" and state.get("web_urls"):
        answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in state["web_urls"])
    return {"answer": answer}
```

- [ ] **Step 4: Run node + route + existing orchestrator tests**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest tests/test_graph_nodes.py tests/test_graph_routes.py tests/test_orchestrator.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_graph_nodes.py
git commit -m "feat(langgraph): node functions transplanted from process_turn"
```

---

### Task 5: Build the graph and rewire process_turn (parity gate)

**Files:**
- Modify: `orchestrator.py` (add `build_graph()`; replace `process_turn` body)

- [ ] **Step 1: Add build_graph + compiled module-level graph** (below the nodes)

```python
from langgraph.graph import StateGraph, START, END
from graph_state import TurnState


def build_graph(checkpointer=None):
    g = StateGraph(TurnState)
    g.add_node("plan", _plan_node)
    g.add_node("gates", _gates_node)
    g.add_node("agent", _agent_node)
    g.add_node("collect", _collect_node)
    g.add_node("proactive_web", _proactive_web_node)
    g.add_node("synthesize", _synthesize_node)
    g.add_node("web_fallback", _web_fallback_node)
    g.add_node("fidelity_check", _fidelity_check_node)
    g.add_node("self_critique", _self_critique_node)
    g.add_node("web_escalate", _web_escalate_node)
    g.add_node("finalize", _finalize_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "gates")
    g.add_conditional_edges("gates", _route_after_gates, ["agent", "collect"])
    g.add_edge("agent", "collect")
    g.add_conditional_edges("collect", _route_after_collect, ["proactive_web", "synthesize"])
    g.add_edge("proactive_web", "synthesize")
    g.add_conditional_edges("synthesize", _route_after_synthesis,
                            ["finalize", "web_fallback", "fidelity_check"])
    g.add_edge("web_fallback", "finalize")
    g.add_conditional_edges("fidelity_check", _route_after_fidelity, ["self_critique", "finalize"])
    g.add_conditional_edges("self_critique", _route_after_critique, ["web_escalate", "finalize"])
    g.add_edge("web_escalate", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


_GRAPH = build_graph()
```

- [ ] **Step 2: Replace the body of process_turn**

```python
@observe(name="process_turn")
def process_turn(
    user_input: str,
    messages: list[dict],
    persona_system: str | None = None,
) -> tuple[str, list[dict]]:
    t0 = time.time()
    initial_state = {
        "user_input": user_input,
        "history": messages,
        "persona_system": persona_system,
        "agent_results": {},
        "agent_tool_blocks": {},
        "accumulated_context": "",
        "answer": "",
        "web_used": False,
        "web_urls": [],
        "hard_raws": [],
        "critique_done": False,
        "tokens": {},
    }
    final_state = _GRAPH.invoke(initial_state)
    answer = final_state.get("answer", "")
    tokens = final_state.get("tokens", {})
    logging.info("[tokens] plan=%d agents=%d synthesis=%d total=%d",
                 tokens.get("plan", 0), tokens.get("agents", 0),
                 tokens.get("synthesis", 0), sum(tokens.values()))
    logging.info("[timing] total turn: %.2fs", time.time() - t0)
    updated_messages = messages + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, updated_messages
```

Delete the now-dead inline body (the old gates/ThreadPoolExecutor/synthesis/
fidelity code) and the now-unused imports: `ThreadPoolExecutor`, `as_completed`,
`otel_context` IF nothing else uses them (verify with grep before removing).
KEEP: `_plan_step`, `_synthesis_step`, `_parse_plan`, `_keyword_fallback`,
`_is_time_sensitive`, `_web_synthesis_messages`, `_log_agent_error`,
`_score_fidelity` — the nodes call them.

- [ ] **Step 3: PARITY GATE — run the FULL suite**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest -q`
Expected: ALL tests pass (260 + ~20 new). Any orchestrator test failure here is
a parity bug in a node/route — fix the node, never the test. Known watch-items:
(a) tests asserting log text ("self-critique", "soft untraced", "untraced number")
— node logging strings are verbatim copies, keep them so;
(b) `test_fidelity_escalates_to_web_when_critique_fails` asserts the search is
called once with `time_sensitive=True` — `_web_escalate_node` must pass the flag;
(c) llm_chat side_effect ORDER (plan → synthesis → critique → web) must match
the old call order — the graph preserves it because edges are sequential.

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "feat(langgraph): process_turn runs the parity graph (all tests green)"
```

---

### Task 6: Langfuse trace nesting verification (live)

**Files:** none (verification only; fallback patch below if needed)

- [ ] **Step 1: Run one live query** (cheap, single turn — SambaNova as final validation per project rules)

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe fidelity_live_check.py "What was Apple's revenue in FY2024 and FY2023?"`
Expected: correct grounded answer; `[fidelity] checked answer: 0 untraced ...`

- [ ] **Step 2: Check the Langfuse UI trace**

Open the latest trace. Expected: ONE row for the turn with plan/agent/synthesize
spans nested under `process_turn`. LangGraph propagates contextvars to its
worker threads (`contextvars.copy_context`), so the old manual OTEL re-attach
should be unnecessary.

- [ ] **Step 3 (ONLY if agent spans appear as separate root traces):** re-add the
context bridge inside `_agent_node`:

```python
# at top of _agent_node, replacing the plain body wrapper:
    ctx_token = otel_context.attach(_PARENT_CTX.get())
    try:
        ...existing body...
    finally:
        otel_context.detach(ctx_token)
```

with a module-level `_PARENT_CTX: contextvars.ContextVar` set in `process_turn`
before `_GRAPH.invoke`:

```python
import contextvars
_PARENT_CTX = contextvars.ContextVar("parent_otel_ctx")
# in process_turn, before invoke:
_PARENT_CTX.set(otel_context.get_current())
```

- [ ] **Step 4: Commit (only if Step 3 was needed)**

```bash
git add orchestrator.py
git commit -m "fix(langgraph): bridge OTEL context into Send-dispatched agent nodes"
```

---

### Task 7: Phase 2 — SQLite checkpointing + resume

**Files:**
- Modify: `orchestrator.py`
- Test: `tests/test_graph_checkpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_checkpoint.py
import json
import sqlite3
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver


def _plan(agents, tickers):
    return (json.dumps({"intent": "specific_tickers", "agents": agents, "tickers": tickers}), 0)


def test_crashed_turn_resumes_without_refetching_agents(tmp_path):
    """Kill the turn at synthesis; resume on the same thread_id; the agent node
    must NOT run again (its output came from the checkpoint)."""
    from orchestrator import build_graph

    saver = SqliteSaver(sqlite3.connect(tmp_path / "ckpt.db", check_same_thread=False))
    graph = build_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": "turn-1"}}
    initial = {
        "user_input": "AAPL revenue?", "history": [], "persona_system": None,
        "agent_results": {}, "agent_tool_blocks": {}, "accumulated_context": "",
        "answer": "", "web_used": False, "web_urls": [], "hard_raws": [],
        "critique_done": False, "tokens": {},
    }
    agent_calls = {"n": 0}

    def fake_financials(*a, **k):
        agent_calls["n"] += 1
        return ("## AAPL\nRevenue: 391,035M  (Sep 28, 2024)", 10,
                {"get_income_statement({})": "Total revenue: 391,035M  (Sep 28, 2024)"})

    # First run: synthesis LLM call explodes AFTER the agent ran.
    with patch("orchestrator.llm_chat",
               side_effect=[_plan(["financials"], ["AAPL"]), RuntimeError("boom")]), \
         patch("orchestrator.run_financials", side_effect=fake_financials), \
         patch("orchestrator.validate_tickers", return_value=(["AAPL"], [])), \
         patch("orchestrator.detect_group_in_query", return_value=None):
        try:
            graph.invoke(initial, config)
        except RuntimeError:
            pass
    assert agent_calls["n"] == 1

    # Resume: invoke(None) continues from the checkpoint — plan + agent must
    # NOT re-run; only the failed synthesis (and downstream) executes.
    with patch("orchestrator.llm_chat",
               side_effect=[("Revenue was 391,035M in FY2024.", 5)]), \
         patch("orchestrator.run_financials", side_effect=fake_financials), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])):
        final = graph.invoke(None, config)

    assert agent_calls["n"] == 1            # agent NOT refetched
    assert "391,035M" in final["answer"]
```

- [ ] **Step 2: Run to verify it fails or errors meaningfully**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest tests/test_graph_checkpoint.py -q`
Expected: PASS is possible already since `build_graph(checkpointer=...)` exists from
Task 5 — if it passes, this test still locks the resume contract. If it FAILS,
debug per the failure (most likely cause: `invoke(None, config)` semantics
changed in the installed langgraph version — check `graph.get_state(config)`).

- [ ] **Step 3: Wire a persistent checkpointer into process_turn**

```python
# module level (near _GRAPH), replacing the bare compile:
import sqlite3 as _sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

_CHECKPOINT_DB = os.path.join(os.path.dirname(__file__), "checkpoints.db")
_GRAPH = build_graph(
    checkpointer=SqliteSaver(_sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False))
)
```

```python
# process_turn, complete final version (replaces Task 5's version):
import uuid

@observe(name="process_turn")
def process_turn(
    user_input: str,
    messages: list[dict],
    persona_system: str | None = None,
    thread_id: str | None = None,
) -> tuple[str, list[dict]]:
    t0 = time.time()
    initial_state = {
        "user_input": user_input,
        "history": messages,
        "persona_system": persona_system,
        "agent_results": {},
        "agent_tool_blocks": {},
        "accumulated_context": "",
        "answer": "",
        "web_used": False,
        "web_urls": [],
        "hard_raws": [],
        "critique_done": False,
        "tokens": {},
    }
    config = {"configurable": {"thread_id": thread_id or uuid.uuid4().hex}}
    final_state = _GRAPH.invoke(initial_state, config)
    answer = final_state.get("answer", "")
    tokens = final_state.get("tokens", {})
    logging.info("[tokens] plan=%d agents=%d synthesis=%d total=%d",
                 tokens.get("plan", 0), tokens.get("agents", 0),
                 tokens.get("synthesis", 0), sum(tokens.values()))
    logging.info("[timing] total turn: %.2fs", time.time() - t0)
    updated_messages = messages + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, updated_messages
```

Default = fresh uuid per turn → turns stay isolated (no state leakage between
turns); resume is opt-in by passing the same thread_id. Add `checkpoints.db`
to `.gitignore`.

- [ ] **Step 4: Run checkpoint test + FULL suite**

Run: `& C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_graph_checkpoint.py .gitignore
git commit -m "feat(langgraph): sqlite checkpointing — crashed turns resume without refetch"
```

---

### Task 8: Update plan tracker

**Files:**
- Modify: `claude/plans/pending/2026-06-10-langgraph-phase1-2-implementation.md` (move to `claude/plans/done/` if that convention exists, else mark progress log at top)

- [ ] **Step 1:** Add a progress log entry at the top of this plan noting completion date + final test count.
- [ ] **Step 2:** Commit: `git add claude/plans && git commit -m "docs(plan): langgraph phase 1+2 complete"`

---

## Out of scope for this plan
- Phase 3 (structured router / SambaNova `response_format` verification) — next plan.
- Phase 4 (decomposition), Phase 5 (HITL) — separate plans on the stable base.
- Streaming, run_tool_loop subgraph conversion.
