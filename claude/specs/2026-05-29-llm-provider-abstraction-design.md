# LLM Provider Abstraction — Phase 3 Design

**Date:** 2026-05-29
**Branch:** feature/llm-provider-abstraction
**Status:** Approved for implementation

---

## Motivation

The orchestrator currently uses a Groq-specific `groq_client.py`. Switching to any other OpenAI-compatible provider (Cerebras, Together AI, Ollama, etc.) requires code changes. The goal is to make provider switching a config change only — 2 env vars, zero code changes.

Agents remain on `ollama.chat()` for now and are migrated separately once Groq is validated for orchestrator use.

---

## Scope

| File | Change |
|---|---|
| `tools/llm.py` | **New** — `llm_chat()` wrapper, env-var-driven |
| `tools/groq_client.py` | **Deleted** — replaced by `tools/llm.py` |
| `orchestrator.py` | Import + 3 call-site renames only |
| `tests/test_tools.py` | 2 new unit tests for `llm_chat` |
| `tests/test_orchestrator.py` | Mock target rename: `groq_chat` → `llm_chat` |

**Out of scope:** Agent migration (financials, news, calc, ratios — all stay on `ollama.chat()`).

---

## Section 1: `tools/llm.py`

Single public function `llm_chat(model, messages, temperature)` — identical signature to the current `groq_chat` so the orchestrator diff is minimal.

```python
def llm_chat(model: str, messages: list[dict], temperature: float = 0.0) -> str:
```

### Provider config (env vars)

| Var | Default | Notes |
|---|---|---|
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | Any OpenAI-compat endpoint |
| `LLM_API_KEY` | falls back to `GROQ_API_KEY` | Provider auth token |

Switching providers = set `LLM_BASE_URL` + `LLM_API_KEY` in `.env`. Zero code changes.

### Implementation

- Uses `openai.OpenAI(base_url=..., api_key=...)` (already installed)
- Client cached in module-level `_client` — same pattern as current `groq_client.py`
- Raises `RuntimeError("LLM_API_KEY not set")` if neither `LLM_API_KEY` nor `GROQ_API_KEY` is found
- Logs and re-raises on API errors

---

## Section 2: Orchestrator migration

### `orchestrator.py`

One import line change:
```python
# before
from tools.groq_client import groq_chat
# after
from tools.llm import llm_chat
```

Three call-site renames (`groq_chat` → `llm_chat`). Signature is identical — no other changes.

### `tools/groq_client.py`

Deleted after orchestrator tests pass.

---

## Section 3: Tests

### `tests/test_tools.py` — 2 new unit tests

- `test_llm_chat_raises_when_no_api_key` — patches both `LLM_API_KEY` and `GROQ_API_KEY` to `None`, asserts `RuntimeError`
- `test_llm_chat_returns_string` — mocks `openai.OpenAI` client, asserts `llm_chat` returns a string

### `tests/test_orchestrator.py` — mock rename only

All 8 `patch("orchestrator.groq_chat", ...)` calls become `patch("orchestrator.llm_chat", ...)`. No logic changes.

---

## Provider switching examples

**Cerebras (fastest):**
```
LLM_BASE_URL=https://api.cerebras.ai/v1
LLM_API_KEY=your_cerebras_key
```

**Ollama (local):**
```
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
```

**Groq (current default — no change needed if GROQ_API_KEY already set):**
```
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=your_groq_key   # or keep GROQ_API_KEY
```

---

## What stays unchanged

- `tools/config.py` — `MODEL_PLAN` and `MODEL_SYNTHESIS` constants remain; model names are still passed per-call
- All 4 agents — `ollama.chat()` calls untouched
- All existing orchestrator test assertions — only mock target name changes
