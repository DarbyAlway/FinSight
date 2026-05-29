# LLM Provider Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `tools/groq_client.py` with a provider-agnostic `tools/llm.py` so the orchestrator can switch LLM providers via env vars with zero code changes.

**Architecture:** New `tools/llm.py` exposes `llm_chat(model, messages, temperature)` — identical signature to the current `groq_chat`. Provider is configured via `LLM_BASE_URL` and `LLM_API_KEY` env vars (defaults to Groq; falls back to `GROQ_API_KEY` for backward compat). Orchestrator import and 3 call sites are renamed. `groq_client.py` is deleted. Agents are untouched.

**Tech Stack:** `openai` Python SDK (already installed), `unittest.mock`, `pytest`

---

## File Map

| File | Change |
|---|---|
| `tools/llm.py` | **New** — `_get_client()` + `llm_chat()` |
| `tools/groq_client.py` | **Deleted** |
| `orchestrator.py` | 1 import line + 3 call-site renames |
| `tests/test_tools.py` | 2 new unit tests for `llm_chat` |
| `tests/test_orchestrator.py` | 8 mock-target renames (`groq_chat` → `llm_chat`) |

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
