# Agent Migration to Groq — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all 4 agents from `ollama.chat()` to Groq `qwen/qwen3-32b` via the OpenAI SDK, with `parallel_tool_calls=True` so the model collapses independent tool calls into one response.

**Architecture:** All agents import `_get_client()` from `tools/llm.py` (same singleton as orchestrator). Response structure changes from `response.message` to `response.choices[0].message`. Tool result messages gain a `tool_call_id`. `parallel_tool_calls=True` is passed on every call — the model decides automatically whether to parallelize or go sequential.

**Tech Stack:** `openai` SDK (already installed), `qwen/qwen3-32b` on Groq, `unittest.mock`, `pytest`

---

## File Map

| File | Change |
|---|---|
| `tools/config.py` | Add `MODEL_AGENT = "qwen/qwen3-32b"` |
| `agents/financials.py` | Replace `ollama.chat` loop with OpenAI SDK loop |
| `agents/news.py` | Replace `ollama.chat` loop with OpenAI SDK loop |
| `agents/calc.py` | Replace `ollama.chat` loop with OpenAI SDK loop |
| `agents/ratios.py` | Replace `ollama.chat` loop with OpenAI SDK loop |
| `tests/test_agents.py` | Replace ollama mock helper with OpenAI mock helper, update all patches |

---

## Task 1: Add `MODEL_AGENT` to config + update test helpers

**Files:**
- Modify: `tools/config.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Add `MODEL_AGENT` to `tools/config.py`**

Open `tools/config.py` and add after the existing model constants:

```python
MODEL_AGENT = "qwen/qwen3-32b"          # agents — Groq
```

- [ ] **Step 2: Replace the test helper in `tests/test_agents.py`**

Replace the `_make_ollama_response` helper at the top of the file:

```python
# OLD
def _make_ollama_response(content="result", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    resp = MagicMock()
    resp.message = msg
    return resp
```

```python
# NEW
def _make_openai_response(content="result", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp
```

- [ ] **Step 3: Update all tests in `tests/test_agents.py` to use the new helper and mock target**

Replace the full content of `tests/test_agents.py` with:

```python
from unittest.mock import MagicMock, patch


def _make_openai_response(content="result", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_financials_agent_returns_string():
    from agents.financials import run as run_financials
    with patch("agents.financials._get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = _make_openai_response("AAPL revenue is $400B")
        result = run_financials("What is AAPL revenue?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_financials_agent_calls_tool_when_requested():
    from agents.financials import run as run_financials, TOOL_FUNCTIONS

    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = "get_income_statement"
    tool_call.function.arguments = '{"ticker": "AAPL"}'

    tool_response = _make_openai_response(content=None, tool_calls=[tool_call])
    final_response = _make_openai_response(content="AAPL revenue: $400B")

    with patch("agents.financials._get_client") as mock_client, \
         patch.dict(TOOL_FUNCTIONS, {"get_income_statement": lambda ticker: "Revenue: $400B"}):
        mock_client.return_value.chat.completions.create.side_effect = [tool_response, final_response]
        result = run_financials("What is AAPL revenue?")

    assert "AAPL" in result or "400" in result


def test_news_agent_returns_string():
    from agents.news import run as run_news
    with patch("agents.news._get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = _make_openai_response("Apple released iPhone 17.")
        result = run_news("What is the latest news on AAPL?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_news_agent_only_has_news_tools():
    from agents.news import TOOL_FUNCTIONS
    assert set(TOOL_FUNCTIONS.keys()) == {"get_stock_news", "search_news"}


def test_calc_agent_returns_string():
    from agents.calc import run as run_calc
    with patch("agents.calc._get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = _make_openai_response("AAPL revenue CAGR: 8.2%")
        result = run_calc("What is AAPL 3-year revenue CAGR?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_calc_agent_only_has_calc_tools():
    from agents.calc import TOOL_FUNCTIONS
    expected = {
        "calculate_dcf", "calculate_peg", "calculate_pe_vs_sector",
        "calculate_revenue_cagr", "calculate_margin_trend", "calculate_yoy",
        "calculate_correlation", "rank_tickers", "get_price_history",
        "calculate_free_cash_flow", "calculate_cash_runway",
    }
    assert set(TOOL_FUNCTIONS.keys()) == expected
```

- [ ] **Step 4: Run tests to confirm they fail (expected — agents still use ollama)**

```
conda run -n stock pytest tests/test_agents.py -v 2>&1 | tail -15
```

Expected: tests fail because agents still import `ollama`

- [ ] **Step 5: Commit config change only**

```bash
git add tools/config.py tests/test_agents.py
git commit -m "feat: add MODEL_AGENT config, update agent test helpers for OpenAI SDK"
```

---

## Task 2: Migrate all 4 agents

**Files:**
- Modify: `agents/financials.py`
- Modify: `agents/news.py`
- Modify: `agents/calc.py`
- Modify: `agents/ratios.py`

- [ ] **Step 1: Migrate `agents/financials.py`**

Replace the `import ollama` line and the `run()` function:

Remove:
```python
import ollama
from tools.config import MODEL
```

Add:
```python
import json
from tools.llm import _get_client
from tools.config import MODEL_AGENT
```

Replace the entire `run()` function with:

```python
OPT = {"temperature": 0.1}


def run(user_question: str, context: str = "", history: list[dict] | None = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages += history[-6:]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL_AGENT,
        messages=messages,
        tools=TOOLS,
        parallel_tool_calls=True,
        temperature=OPT["temperature"],
    )
    msg = response.choices[0].message

    while msg.tool_calls:
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            fn = TOOL_FUNCTIONS.get(name)
            result = fn(**args) if fn else f"Unknown tool: {name}"
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
            logging.info("[FinancialsAgent] %s(%s)", name, args)
        response = client.chat.completions.create(
            model=MODEL_AGENT,
            messages=messages,
            tools=TOOLS,
            parallel_tool_calls=True,
            temperature=OPT["temperature"],
        )
        msg = response.choices[0].message

    return msg.content or ""
```

- [ ] **Step 2: Migrate `agents/news.py`**

Same pattern — replace `import ollama` + `from tools.config import MODEL` with:
```python
import json
from tools.llm import _get_client
from tools.config import MODEL_AGENT
```

Replace `run()` with the same loop pattern (change log label to `[NewsAgent]`):

```python
OPT = {"temperature": 0.1}


def run(user_question: str, context: str = "", history: list[dict] | None = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages += history[-6:]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL_AGENT,
        messages=messages,
        tools=TOOLS,
        parallel_tool_calls=True,
        temperature=OPT["temperature"],
    )
    msg = response.choices[0].message

    while msg.tool_calls:
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            fn = TOOL_FUNCTIONS.get(name)
            result = fn(**args) if fn else f"Unknown tool: {name}"
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
            logging.info("[NewsAgent] %s(%s)", name, args)
        response = client.chat.completions.create(
            model=MODEL_AGENT,
            messages=messages,
            tools=TOOLS,
            parallel_tool_calls=True,
            temperature=OPT["temperature"],
        )
        msg = response.choices[0].message

    return msg.content or ""
```

- [ ] **Step 3: Migrate `agents/calc.py`**

Same pattern (log label `[CalcAgent]`):

Remove:
```python
import ollama
from tools.config import MODEL
```

Add:
```python
import json
from tools.llm import _get_client
from tools.config import MODEL_AGENT
```

Replace `run()` with same loop (change log label to `[CalcAgent]`).

- [ ] **Step 4: Migrate `agents/ratios.py`**

Same pattern (log label `[RatiosAgent]`):

Remove:
```python
import ollama
from tools.config import MODEL
```

Add:
```python
import json
from tools.llm import _get_client
from tools.config import MODEL_AGENT
```

Replace `run()` with same loop (change log label to `[RatiosAgent]`).

- [ ] **Step 5: Run agent tests to verify they pass**

```
conda run -n stock pytest tests/test_agents.py -v 2>&1 | tail -15
```

Expected: all agent tests PASS

- [ ] **Step 6: Run full test suite to check for regressions**

```
conda run -n stock pytest tests/test_tools.py tests/test_agents.py tests/test_orchestrator.py -q 2>&1 | tail -5
```

Expected: 87 passed, 0 failures

- [ ] **Step 7: Commit**

```bash
git add agents/financials.py agents/news.py agents/calc.py agents/ratios.py
git commit -m "feat: migrate all agents to Groq qwen3-32b with parallel tool calls"
```
