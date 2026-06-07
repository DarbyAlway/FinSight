# LLM Provider Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `tools/groq_client.py` with a provider-agnostic `tools/llm.py`, migrate the orchestrator, and add optional LangFuse tracing so every LLM call is observable from a self-hosted dashboard.

**Architecture:** New `tools/llm.py` exposes `llm_chat(model, messages, temperature)` — identical signature to the current `groq_chat`. Provider is configured via `LLM_BASE_URL` and `LLM_API_KEY` env vars (defaults to Groq; falls back to `GROQ_API_KEY` for backward compat). LangFuse tracing is opt-in: if `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are set, every `llm_chat` call is logged as a generation; if not set, the function works normally with no error. Orchestrator import and 3 call sites are renamed. `groq_client.py` is deleted. Agents are untouched.

**Tech Stack:** `openai` Python SDK (already installed), `langfuse` Python SDK, Docker Compose, `unittest.mock`, `pytest`

---

## File Map

| File | Change |
|---|---|
| `tools/llm.py` | **New** — `_get_client()` + `llm_chat()` |
| `tools/groq_client.py` | **Deleted** |
| `orchestrator.py` | 1 import line + 3 call-site renames + ticker hint fix |
| `tests/test_tools.py` | 2 unit tests for `llm_chat` |
| `tests/test_orchestrator.py` | 8 mock-target renames (`groq_chat` → `llm_chat`) |
| `main.py` | Add `_init_phoenix()` + call in `__main__` |
| `requirements.txt` | Add Phoenix packages |

---

## Task 1: Create `tools/llm.py` (TDD)

**Files:**
- Create: `tools/llm.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the 2 failing tests**

Add at the end of `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# tools/llm tests
# ---------------------------------------------------------------------------

def test_llm_chat_raises_when_no_api_key():
    import tools.llm as llm_module
    from unittest.mock import patch
    import pytest
    llm_module._client = None
    with patch("tools.llm.os.getenv", return_value=None):
        with pytest.raises(RuntimeError, match="LLM_API_KEY not set"):
            llm_module._get_client()
    llm_module._client = None


def test_llm_chat_returns_string():
    import tools.llm as llm_module
    from unittest.mock import MagicMock, patch
    llm_module._client = None
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "mocked answer"
    with patch("tools.llm.os.getenv", return_value="fake-key"), \
         patch("tools.llm.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.chat.completions.create.return_value = mock_response
        result = llm_module.llm_chat("test-model", [{"role": "user", "content": "hi"}])
    assert result == "mocked answer"
    llm_module._client = None
```

- [ ] **Step 2: Run to verify they fail**

```
conda run -n stock pytest tests/test_tools.py::test_llm_chat_raises_when_no_api_key tests/test_tools.py::test_llm_chat_returns_string -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.llm'`

- [ ] **Step 3: Create `tools/llm.py`**

Create `tools/llm.py` with this exact content:

```python
import logging
import os

from openai import OpenAI

_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_API_KEY not set in environment")
        base_url = os.getenv("LLM_BASE_URL", _DEFAULT_BASE_URL)
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def llm_chat(model: str, messages: list[dict], temperature: float = 0.0) -> str:
    try:
        response = _get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logging.error("llm_chat failed: %s", e)
        raise
```

- [ ] **Step 4: Run to verify they pass**

```
conda run -n stock pytest tests/test_tools.py::test_llm_chat_raises_when_no_api_key tests/test_tools.py::test_llm_chat_returns_string -v
```

Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add tools/llm.py tests/test_tools.py
git commit -m "feat: add tools/llm.py provider-agnostic wrapper (TDD)"
```

---

## Task 2: Migrate orchestrator + update tests + delete groq_client

**Files:**
- Modify: `orchestrator.py`
- Modify: `tests/test_orchestrator.py`
- Delete: `tools/groq_client.py`

- [ ] **Step 1: Update the import in `orchestrator.py`**

Find line 26 in `orchestrator.py`:
```python
from tools.groq_client import groq_chat
```
Replace with:
```python
from tools.llm import llm_chat
```

- [ ] **Step 2: Rename the 3 `groq_chat` call sites in `orchestrator.py`**

Find and replace each of these 3 lines (they are at lines ~118, ~168, ~176):

```python
# line ~118 — plan call
plan_content = groq_chat(MODEL_PLAN, planning_messages, temperature=0.0)
# becomes:
plan_content = llm_chat(MODEL_PLAN, planning_messages, temperature=0.0)
```

```python
# line ~168 — synthesis call
answer = groq_chat(MODEL_SYNTHESIS, synthesis_messages, temperature=0.3)
# becomes:
answer = llm_chat(MODEL_SYNTHESIS, synthesis_messages, temperature=0.3)
```

```python
# line ~176 — Tavily re-synthesis call
answer = groq_chat(MODEL_SYNTHESIS, web_messages, temperature=0.3) or answer
# becomes:
answer = llm_chat(MODEL_SYNTHESIS, web_messages, temperature=0.3) or answer
```

- [ ] **Step 3: Run orchestrator tests to verify they fail (expected — mock target is stale)**

```
conda run -n stock pytest tests/test_orchestrator.py -v 2>&1 | tail -15
```

Expected: 8 tests FAIL with `AttributeError: <module 'orchestrator'> does not have the attribute 'groq_chat'`

- [ ] **Step 4: Update all 8 mock targets in `tests/test_orchestrator.py`**

Replace every occurrence of `"orchestrator.groq_chat"` with `"orchestrator.llm_chat"` throughout the file. There are exactly 8 occurrences across these tests:

- `test_direct_answer_skips_agents` (line 41)
- `test_single_agent_plan_calls_correct_agent` (line 59)
- `test_multi_agent_passes_context_forward` (line 78)
- `test_malformed_plan_uses_keyword_fallback` (line 92)
- `test_agent_failure_is_skipped_gracefully` (line 111)
- `test_tavily_fallback_triggered_when_uncertain` (line 130)
- `test_tavily_fallback_skipped_when_confident` (line 146)
- `test_tavily_fallback_skipped_when_empty_results` (line 161)

- [ ] **Step 5: Run orchestrator tests to verify they pass**

```
conda run -n stock pytest tests/test_orchestrator.py -v 2>&1 | tail -15
```

Expected: 13 PASSED

- [ ] **Step 6: Run full test suite to check for regressions**

```
conda run -n stock pytest tests/test_tools.py tests/test_agents.py tests/test_orchestrator.py -q 2>&1 | tail -10
```

Expected: 86 passed (84 existing + 2 new), 0 failures unrelated to Qdrant

- [ ] **Step 7: Delete `tools/groq_client.py`**

```bash
git rm tools/groq_client.py
```

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat: migrate orchestrator to llm_chat, delete groq_client (TDD)"
```

---

## Task 3: Phoenix observability (Groq + Ollama + Qdrant auto-instrumentation)

**Files:**
- Modify: `main.py` — add optional Phoenix init + instrumentors
- Modify: `requirements.txt` — add phoenix packages
- No changes to `tools/llm.py` or agents (auto-instrumented at SDK level)

> **Note:** Phoenix instruments the OpenAI SDK and Ollama library globally — every `llm_chat()` call and every `ollama.chat()` agent call is traced automatically with zero changes to those files.

- [ ] **Step 1: Install Phoenix packages in the conda env**

```
conda run -n stock pip install "arize-phoenix>=4.0" "openinference-instrumentation-openai>=0.1" "openinference-instrumentation-ollama>=0.1" -q
```

- [ ] **Step 2: Add packages to `requirements.txt`**

Open `requirements.txt` and add:
```
arize-phoenix>=4.0
openinference-instrumentation-openai>=0.1
openinference-instrumentation-ollama>=0.1
```

- [ ] **Step 3: Add `_init_phoenix()` to `main.py`**

After the existing imports in `main.py`, add this function (before `_build_persona_system`):

```python
def _init_phoenix():
    try:
        import phoenix as px
        from openinference.instrumentation.openai import OpenAIInstrumentor
        from openinference.instrumentation.ollama import OllamaInstrumentor
        session = px.launch_app()
        OpenAIInstrumentor().instrument()
        OllamaInstrumentor().instrument()
        logging.info("Phoenix tracing enabled: %s", session.url)
    except ImportError:
        pass
    except Exception as e:
        logging.warning("Phoenix init failed — tracing disabled: %s", e)
```

- [ ] **Step 4: Call `_init_phoenix()` in the `__main__` block**

Find the `if __name__ == "__main__":` block at the bottom of `main.py`:

```python
if __name__ == "__main__":
    init_db()
    init_qdrant()
    _get_anchor_vecs()
    chat()
```

Change to:

```python
if __name__ == "__main__":
    init_db()
    init_qdrant()
    _get_anchor_vecs()
    _init_phoenix()
    chat()
```

- [ ] **Step 5: Run full test suite to confirm no regressions**

```
conda run -n stock pytest tests/test_tools.py tests/test_agents.py tests/test_orchestrator.py -q 2>&1 | tail -5
```

Expected: 87 passed, 0 failures

- [ ] **Step 6: Commit**

```bash
git add main.py requirements.txt
git commit -m "feat: add Phoenix auto-instrumentation for Groq + Ollama tracing"
```

---

## How to use Phoenix

When you run `python main.py`, Phoenix starts automatically and prints a URL:

```
Phoenix tracing enabled: http://localhost:6006
```

Open `http://localhost:6006` in your browser to see:
- Every Groq plan + synthesis call with full query and response
- Every Ollama agent call with tool arguments
- Latency breakdown per step
- Token counts per call

**To switch to Phoenix cloud later** — just set `PHOENIX_COLLECTOR_ENDPOINT=https://app.phoenix.arize.com/...` in `.env`. Zero code changes.
