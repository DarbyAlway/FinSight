# Agent Migration to Groq with Parallel Tool Calls — Design

**Date:** 2026-05-29
**Branch:** feature/llm-provider-abstraction
**Status:** Approved for implementation

---

## Motivation

All 4 agents currently use `ollama.chat()` (local qwen3:14b). Migrating to Groq qwen/qwen3-32b gives:
- A smarter model (32B vs 14B) — better tool selection, fewer ticker hallucinations
- `parallel_tool_calls=True` — model returns multiple independent tool calls in one response, collapsing loop iterations and saving API calls
- Consistent provider (all Groq) — one env var switches everything

Sequential loops are preserved for cases where tool B depends on tool A's result. The model decides automatically per-response whether to parallelize or not.

---

## Scope

| File | Change |
|---|---|
| `tools/config.py` | Add `MODEL_AGENT = "qwen/qwen3-32b"` |
| `agents/financials.py` | Migrate to OpenAI SDK + parallel tool calls |
| `agents/news.py` | Migrate to OpenAI SDK + parallel tool calls |
| `agents/calc.py` | Migrate to OpenAI SDK + parallel tool calls |
| `agents/ratios.py` | Migrate to OpenAI SDK + parallel tool calls |
| `tests/test_agents.py` | Update mocks: `ollama.chat` → `openai` client |

**Out of scope:** Orchestrator (already on Groq), `tools/llm.py` (unchanged), tool functions.

---

## Architecture

All agents reuse the same `_get_client()` singleton from `tools/llm.py`. No new client setup per agent. Provider switches via existing `LLM_BASE_URL` / `LLM_API_KEY` env vars — already in `.env`.

---

## API differences: Ollama → OpenAI SDK

### Response structure
```python
# Ollama
msg = response.message
msg.tool_calls        # list or None
msg.content           # str

# OpenAI SDK
msg = response.choices[0].message
msg.tool_calls        # list or None
msg.content           # str or None
```

### Appending assistant message with tool calls
```python
# Ollama — passes the message object directly
messages.append(msg)

# OpenAI SDK — must serialize to dict with tool_calls array
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
```

### Tool result messages
```python
# Ollama — no tool_call_id needed
messages.append({"role": "tool", "content": result})

# OpenAI SDK — tool_call_id required
messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
```

### Tool call arguments
```python
# Ollama — can be dict or str
args = tc.function.arguments if isinstance(tc.function.arguments, dict) else json.loads(tc.function.arguments)

# OpenAI SDK — always a JSON string
args = json.loads(tc.function.arguments)
```

### Parallel tool calls
```python
# New parameter on every create() call
parallel_tool_calls=True
```

---

## New agent pattern (all 4 agents)

```python
from tools.llm import _get_client
from tools.config import MODEL_AGENT

OPT_AGENT = {"temperature": 0.1}

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
        temperature=OPT_AGENT["temperature"],
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
            logging.info("[%sAgent] %s(%s)", agent_label, name, args)
        response = client.chat.completions.create(
            model=MODEL_AGENT,
            messages=messages,
            tools=TOOLS,
            parallel_tool_calls=True,
            temperature=OPT_AGENT["temperature"],
        )
        msg = response.choices[0].message

    return msg.content or ""
```

---

## Observability

- Phoenix `OpenAIInstrumentor` already active — all agent calls traced automatically (no extra work)
- LangFuse tracks orchestrator calls only (plan + synthesis) — agents not explicitly logged, but visible in Phoenix

---

## What stays unchanged

- `TOOLS` definitions in each agent (tool schemas are already OpenAI-compatible)
- `TOOL_FUNCTIONS` dicts
- All tool implementations (`tools/*.py`)
- Orchestrator — no changes
- `tools/llm.py` — no changes
