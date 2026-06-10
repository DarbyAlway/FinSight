# I4 (history token-cut) + I5 (web-search trigger) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a proactive `market_news` web-search route plus a reliable reactive empty/error fallback (I5), and cut per-turn history token cost by dropping history from data agents and capping synthesis history (I4).

**Architecture:** All changes live in `orchestrator.py`, `prompts.py`, and `tools/search_guardrails.py`. The planner LLM gains an `intent` field; `market_news` fires a web search up front and feeds it to synthesis. A new pure helper `agents_returned_nothing` drives the reactive fallback. History is simply not passed to agents, and synthesis history is sliced to the last N turns.

**Tech Stack:** Python, pytest, existing Tavily wrapper (`_web_search_with_sources`), SambaNova/Ollama LLM via `llm_chat`.

**Spec:** `claude/specs/2026-06-08-i4-history-i5-websearch-design.md`

**Test runner (this project):**
`& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest <args>`
(`pytest.ini` sets `testpaths = tests`.) Per project rules: real data for data tests, Ollama never paid SambaNova for LLM-in-loop tests, pytest needs no permission.

---

## File Structure

- **`tools/search_guardrails.py`** — add pure helper `agents_returned_nothing(agent_results)` (reactive-trigger logic). Lives here so it's unit-testable alongside `is_uncertain`.
- **`prompts.py`** — `PLAN_SYSTEM`: add the `intent` field instruction + a `market_news` example.
- **`orchestrator.py`** — parse `intent`; proactive `market_news` web search; reactive trigger widening; drop agent history; cap synthesis history.
- **`tests/test_search_guardrails.py`** — NEW. Truth table for `agents_returned_nothing`.
- **`tests/test_orchestrator.py`** — add intent-routing, reactive-fallback, and I4 history tests.

Order: Task 1 (helper) → Task 2 (intent + proactive) → Task 3 (reactive wiring) → Task 4 (I4 agent history) → Task 5 (I4 synthesis cap) → Task 6 (full-suite verify + tracker).

---

### Task 1: Reactive helper `agents_returned_nothing`

**Files:**
- Create: `tests/test_search_guardrails.py`
- Modify: `tools/search_guardrails.py` (add helper near top, after imports)

- [ ] **Step 1: Write the failing test**

Create `tests/test_search_guardrails.py`:

```python
from tools.search_guardrails import agents_returned_nothing


def test_empty_results_is_nothing():
    assert agents_returned_nothing({}) is True


def test_all_error_outputs_is_nothing():
    results = {
        "financials": "## LITE\nERROR: No company info for LITE",
        "calc": "TOOL_ERROR: No quarterly data could be parsed for LITE.",
    }
    assert agents_returned_nothing(results) is True


def test_no_data_phrases_is_nothing():
    results = {"ratios": "No revenue data for AAPL — call get_income_statement first."}
    assert agents_returned_nothing(results) is True


def test_one_real_output_is_not_nothing():
    results = {"financials": "## AAPL\nRevenue: $391,035M\nNet income: $93,736M"}
    assert agents_returned_nothing(results) is False


def test_mixed_real_and_error_is_not_nothing():
    results = {
        "financials": "## AAPL\nRevenue: $391,035M",
        "ratios": "ERROR: No balance sheet data for AAPL",
    }
    assert agents_returned_nothing(results) is False


def test_header_only_error_is_nothing():
    # Markdown header lines must not count as real content.
    results = {"financials": "## AAPL\nERROR: No revenue data"}
    assert agents_returned_nothing(results) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_search_guardrails.py -v`
Expected: FAIL with `ImportError: cannot import name 'agents_returned_nothing'`.

- [ ] **Step 3: Write minimal implementation**

In `tools/search_guardrails.py`, add after the imports (above `_UNCERTAIN_ANCHORS`):

```python
# Reactive web-search trigger (I5): an output counts as "no data" when every
# non-blank, non-header line begins with an error/no-data marker. Markdown
# headers (## TICKER) are ignored so an "## AAPL\nERROR: ..." block still reads
# as no-data. If ALL agent outputs are no-data (or none returned), fire the
# web-search fallback.
_NO_DATA_PREFIXES = (
    "error", "tool_error", "no ", "could not", "unable", "unknown tool", "i don't",
)


def _is_no_data(text) -> bool:
    if not isinstance(text, str) or not text.strip():
        return True
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.lower().startswith(_NO_DATA_PREFIXES):
            return False  # a real content line → this output has data
    return True


def agents_returned_nothing(agent_results: dict) -> bool:
    """True if no agent produced usable output: the dict is empty (every agent
    failed/returned None) or every output is entirely no-data/error lines."""
    if not agent_results:
        return True
    return all(_is_no_data(v) for v in agent_results.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_search_guardrails.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_search_guardrails.py tools/search_guardrails.py
git commit -m "feat(I5): agents_returned_nothing reactive web-search helper"
```

---

### Task 2: Planner `intent` field + proactive `market_news` web search

**Files:**
- Modify: `prompts.py` (`PLAN_SYSTEM`)
- Modify: `orchestrator.py` (parse `intent`; proactive search; restructure answer/fallback block)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orchestrator.py`:

```python
def test_market_news_intent_triggers_proactive_web_search():
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "market_news", "agents": ["news"], "tickers": []})

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("Markets fell on rate fears.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources",
               return_value=("S&P fell 2% on rate fears per Reuters.", ["https://reuters.com/mkt"])) as mock_search, \
         patch("orchestrator.run_news", return_value=("Headlines: tech slid", 0)):
        result, _ = process_turn("why is the market down today?", [])

    mock_search.assert_called_once()
    assert "https://reuters.com/mkt" in result
    assert "Web sources" in result


def test_specific_tickers_intent_no_proactive_search():
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    mock_search = MagicMock()

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("AAPL P/E is 28x.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nP/E: 28x", 0)):
        process_turn("what is AAPL P/E?", [])

    mock_search.assert_not_called()


def test_missing_intent_defaults_to_no_proactive_search():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials"], "tickers": ["AAPL"]})  # no intent key
    mock_search = MagicMock()

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("AAPL revenue $391B.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nRevenue: $391B", 0)):
        process_turn("AAPL revenue?", [])

    mock_search.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py::test_market_news_intent_triggers_proactive_web_search -v`
Expected: FAIL — `_web_search_with_sources` not called (no proactive path yet).

- [ ] **Step 3a: Add the `intent` instruction to `PLAN_SYSTEM`**

In `prompts.py`, find:

```python
    "/no_think\n{today}You are a stock analysis orchestrator. Given the user's question, output a JSON plan "
    "with the agents to call and the tickers involved. "
```

Replace with:

```python
    "/no_think\n{today}You are a stock analysis orchestrator. Given the user's question, output a JSON plan "
    "with the agents to call and the tickers involved. "
    "Also include an \"intent\" field classifying the question as exactly one of: "
    "\"specific_tickers\" (named companies or stock symbols), "
    "\"macro_theme\" (a named group like MAG7/FAANG), "
    "\"market_news\" (current overall-market conditions or why the market or a stock moved TODAY — needs live news; "
    "e.g. 'why is the market down today', 'what happened to stocks today', 'why is everything dropping'), "
    "or \"general_qa\" (greeting, definition, or answerable from history alone). "
```

- [ ] **Step 3b: Add `intent` to the example JSONs in `PLAN_SYSTEM`**

In `prompts.py`, find:

```python
    'Broad analysis example: {"agents": ["financials", "ratios", "news"], "tickers": ["SNOW"], "reason": "full analysis"} '
    'Single-metric example: {"agents": ["financials"], "tickers": ["AAPL"], "reason": "P/E only"}'
```

Replace with:

```python
    'Broad analysis example: {"intent": "specific_tickers", "agents": ["financials", "ratios", "news"], "tickers": ["SNOW"], "reason": "full analysis"} '
    'Single-metric example: {"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"], "reason": "P/E only"} '
    'Market-news example: {"intent": "market_news", "agents": ["news"], "tickers": [], "reason": "broad market move needs live news"}'
```

- [ ] **Step 3c: Parse `intent` in `process_turn`**

In `orchestrator.py`, find (around line 106):

```python
    t0 = time.time()
    tickers: list[str] = []
```

Replace with:

```python
    t0 = time.time()
    tickers: list[str] = []
    intent: str | None = None
```

Then inside the `try` block, find:

```python
        reason = plan.get("reason", "")
        logging.info("[Orchestrator] plan → agents=%s  tickers=%s  reason=%s", agents_to_run, tickers, reason)
```

Replace with:

```python
        reason = plan.get("reason", "")
        intent = plan.get("intent")
        logging.info("[Orchestrator] plan → intent=%s agents=%s  tickers=%s  reason=%s", intent, agents_to_run, tickers, reason)
```

- [ ] **Step 3d: Fire the proactive web search before synthesis**

In `orchestrator.py`, find the accumulated-context build (around line 200):

```python
    # Preserve plan order in accumulated context
    for name in agents_to_run:
        if name in agent_results:
            accumulated_context += f"\n\n[{name.upper()} AGENT]\n{agent_results[name]}"
```

Immediately AFTER that block, add:

```python
    # I5 proactive: market_news queries need live web data the local cache
    # cannot provide ("why is the market down today"). Search up front and feed
    # the results into synthesis as a source block.
    proactive_web_urls: list[str] = []
    if intent == "market_news":
        web_snippets, proactive_web_urls = _web_search_with_sources(user_input)
        if web_snippets:
            accumulated_context += f"\n\n[WEB SEARCH RESULTS]\n{web_snippets}"
            logging.info("[Orchestrator] market_news → proactive web search (%d sources)", len(proactive_web_urls))
```

- [ ] **Step 3e: Restructure the post-synthesis fallback block**

In `orchestrator.py`, find (around line 224):

```python
    if agents_to_run and is_uncertain(answer, threshold=0.85):
        snippets, urls = _web_search_with_sources(user_input)
```

Replace ONLY that first `if` line so the block becomes:

```python
    if intent == "market_news":
        if proactive_web_urls:
            answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in proactive_web_urls)
    elif agents_to_run and is_uncertain(answer, threshold=0.85):
        snippets, urls = _web_search_with_sources(user_input)
```

(The rest of the existing fallback body — `if snippets:` … `logging.info("[Orchestrator] Tavily fallback used …")` — stays unchanged under the `elif`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py -v -k "intent or proactive"`
Expected: PASS (3 new tests).

- [ ] **Step 5: Commit**

```bash
git add prompts.py orchestrator.py tests/test_orchestrator.py
git commit -m "feat(I5): planner intent field + proactive market_news web search"
```

---

### Task 3: Reactive empty/error trigger wiring

**Files:**
- Modify: `orchestrator.py` (import helper; widen the `elif` condition)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orchestrator.py`:

```python
def test_reactive_fallback_when_all_agents_return_no_data():
    """is_uncertain is False, but every agent output is an error → fire fallback."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["LITE"]})

    with patch("orchestrator.llm_chat", side_effect=[
        (plan_json, 0),
        ("There is no information available.", 0),
        ("LITE PEG is 1.2 based on web data.", 0),
    ]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources",
               return_value=("LITE PEG 1.2 per Reuters.", ["https://r.com/lite"])), \
         patch("orchestrator.run_financials", return_value=("## LITE\nERROR: No company info for LITE", 0)):
        result, _ = process_turn("what about LITE PEG?", [])

    assert "https://r.com/lite" in result


def test_reactive_fallback_not_fired_on_real_data():
    """Real agent data + confident answer → no web search (no false-firing)."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    mock_search = MagicMock()

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("AAPL revenue was $391B.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nRevenue: $391,035M", 0)):
        process_turn("AAPL revenue?", [])

    mock_search.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py::test_reactive_fallback_when_all_agents_return_no_data -v`
Expected: FAIL — fallback not entered (only `is_uncertain` gates it today, and it's False).

- [ ] **Step 3a: Import the helper**

In `orchestrator.py`, find:

```python
from tools.search_guardrails import is_uncertain, _web_search_with_sources
```

Replace with:

```python
from tools.search_guardrails import is_uncertain, _web_search_with_sources, agents_returned_nothing
```

- [ ] **Step 3b: Widen the reactive condition**

In `orchestrator.py`, find the line added in Task 2:

```python
    elif agents_to_run and is_uncertain(answer, threshold=0.85):
```

Replace with:

```python
    elif agents_to_run and (agents_returned_nothing(agent_results) or is_uncertain(answer, threshold=0.85)):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py -v -k "reactive"`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat(I5): reactive web-search trigger on empty/error agent output"
```

---

### Task 4: I4 — stop passing history to data agents

**Files:**
- Modify: `orchestrator.py` (`_run_agent`)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
def test_agents_called_without_history():
    """I4: data agents no longer receive conversation history (they get the
    resolved ticker via ticker_hint instead)."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("done", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", return_value=("## AAPL\ndata", 0)) as mock_fin:
        process_turn("AAPL revenue?", history)

    assert mock_fin.call_args.kwargs["history"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py::test_agents_called_without_history -v`
Expected: FAIL — `history` is the full `messages` list, not `None`.

- [ ] **Step 3: Stop passing history**

In `orchestrator.py`, inside `_run_agent`, find:

```python
                result, agent_tokens = fn(agent_input, "", history=messages, expected_tickers=tickers if tickers else None)
```

Replace with:

```python
                # I4: data agents are self-sufficient (they get the resolved
                # ticker via ticker_hint), so we no longer pay to re-send
                # conversation history into every agent each turn.
                result, agent_tokens = fn(agent_input, "", history=None, expected_tickers=tickers if tickers else None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py::test_agents_called_without_history -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "perf(I4): stop passing conversation history to data agents"
```

---

### Task 5: I4 — cap synthesis history to recent turns

**Files:**
- Modify: `orchestrator.py` (module constant + synthesis_messages slice)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
def test_synthesis_history_capped_to_recent_turns():
    """I4: synthesis sees only the last _SYNTH_HISTORY_TURNS turns, not the
    whole transcript."""
    from orchestrator import process_turn, _SYNTH_HISTORY_TURNS

    history = []
    for i in range(20):
        history.append({"role": "user", "content": f"q{i}"})
        history.append({"role": "assistant", "content": f"a{i}"})

    plan_json = json.dumps({"intent": "general_qa", "agents": [], "tickers": []})
    calls = []

    def rec(model, messages, **kw):
        calls.append(list(messages))
        return (plan_json, 0) if len(calls) == 1 else ("answer", 0)

    with patch("orchestrator.llm_chat", side_effect=rec), \
         patch("orchestrator.is_uncertain", return_value=False):
        process_turn("most recent question", history)

    synth_messages = calls[1]  # second llm_chat call is synthesis
    # system + at most 2*_SYNTH_HISTORY_TURNS history msgs + 1 question msg
    assert len(synth_messages) <= 2 * _SYNTH_HISTORY_TURNS + 2
    # oldest turn dropped
    assert all(m.get("content") != "q0" for m in synth_messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py::test_synthesis_history_capped_to_recent_turns -v`
Expected: FAIL — `ImportError` for `_SYNTH_HISTORY_TURNS` (and synthesis currently includes all 40 history msgs).

- [ ] **Step 3a: Add the constant**

In `orchestrator.py`, find:

```python
OPT_PLAN = {"temperature": 0.0}
OPT_SYNTH = {"temperature": 0.3}
```

Replace with:

```python
OPT_PLAN = {"temperature": 0.0}
OPT_SYNTH = {"temperature": 0.3}

# I4: synthesis only needs recent turns for conversational continuity; the full
# transcript was re-sent every turn and grows unbounded. Keep the last N turns.
_SYNTH_HISTORY_TURNS = 3
```

- [ ] **Step 3b: Slice the synthesis history**

In `orchestrator.py`, find:

```python
    synthesis_messages = [{"role": "system", "content": synthesis_system}, *messages]
```

Replace with:

```python
    synthesis_messages = [{"role": "system", "content": synthesis_system}, *messages[-2 * _SYNTH_HISTORY_TURNS:]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py::test_synthesis_history_capped_to_recent_turns -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "perf(I4): cap synthesis history to last 3 turns"
```

---

### Task 6: Full-suite verification + tracker update

**Files:**
- Modify: `claude/memory/project_active_plans.md` (or wherever the tracker lives) — mark I4 + I5 done.

- [ ] **Step 1: Run the entire test suite**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest -q`
Expected: all tests PASS (prior suite + the new `test_search_guardrails.py` 6 + the 8 new orchestrator tests). If any pre-existing test broke, fix the regression before continuing.

- [ ] **Step 2: Manual smoke (Ollama, free) — proactive route**

Set the LLM provider to Ollama, run the app, and ask: `why is the market down today?`
Expected: the answer cites live web content and ends with a **Web sources:** list (proactive search fired). Confirm in logs: `market_news → proactive web search`.

- [ ] **Step 3: Manual smoke (Ollama, free) — continuity after cap**

In one session ask 4 turns where turn 4 refers to turn 3 (e.g. "what is AAPL revenue?" … "and its net income?" … "compare to MSFT" … "which of those two did you say was higher?"). Expected: turn 4 still resolves the reference (the 3-turn cap preserves it).

- [ ] **Step 4: Update the active-plans tracker**

In `claude/memory/project_active_plans.md`, under the dual-gate plan's "LEFT" / I-items, mark **I4 (history summarization → Option A done)** and **I5 (web-search trigger — proactive intent + reactive empty/error done)** as complete, referencing spec `2026-06-08-i4-history-i5-websearch-design.md`. Note that `market_news` intent is now live (a forward-compatible slice of Phase D); the other three intents still map to current behavior.

- [ ] **Step 5: Commit**

```bash
git add claude/memory/project_active_plans.md
git commit -m "docs: mark I4 + I5 complete (history cut + web-search trigger)"
```

---

## Self-Review Notes

- **Spec coverage:** I4 Option A (drop agent history = Task 4; synthesis cap = Task 5). I5 proactive (intent field + market_news search = Task 2), I5 reactive (helper = Task 1, wiring = Task 3), `is_uncertain ≥ 0.85` retained (Task 3 keeps it in the `or`). All spec sections mapped.
- **Type consistency:** helper named `agents_returned_nothing` everywhere (search_guardrails + import + call site); constant `_SYNTH_HISTORY_TURNS`; plan field `intent`; variable `proactive_web_urls` defined in Task 2 Step 3d and consumed in Step 3e.
- **Out of scope (not built):** Phase D gates/`resolve_entities`/`response_format`; real history summarization (Option B); `query:`/`passage:` e5 prefixes; fidelity work (#13/#14).
