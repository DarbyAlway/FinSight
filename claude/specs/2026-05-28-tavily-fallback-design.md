# Tavily Web Search Fallback — Design Spec
**Date:** 2026-05-28

## Overview

When the synthesis LLM produces an uncertain answer (detected via vector similarity), automatically trigger a Tavily web search, re-synthesize with the search results as extra context, and append source URLs to the final answer. Wired at the synthesis level in `orchestrator.py` — one place, transparent to all agents.

---

## Architecture

Two files changed:

| File | Change |
|------|--------|
| `tools/search_guardrails.py` | Add `_web_search_with_sources(query)` returning `(snippets, urls)` |
| `orchestrator.py` | Post-synthesis uncertainty check + Tavily re-synthesis |

No new files. No agent changes. No DB changes.

---

## Components

### `tools/search_guardrails.py` — `_web_search_with_sources`

New function alongside the existing `web_search_fallback`:

```python
def _web_search_with_sources(query: str) -> tuple[str, list[str]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "", []
    try:
        result = TavilyClient(api_key).search(query, max_results=3)
        results = result.get("results", [])
        snippets = "\n\n".join(r.get("content", "") for r in results)
        urls = [r.get("url", "") for r in results if r.get("url")]
        return snippets, urls
    except Exception as e:
        logging.warning("_web_search_with_sources failed: %s", e)
        return "", []
```

Returns `("", [])` on any failure — never raises.

### `orchestrator.py` — post-synthesis hook

Import addition at top:
```python
from tools.search_guardrails import is_uncertain, _web_search_with_sources
```

Inserted immediately after `answer = synthesis_response.message.content or ""` (currently line 168):

```python
if is_uncertain(answer):
    snippets, urls = _web_search_with_sources(user_input)
    if snippets:
        web_messages = synthesis_messages + [{
            "role": "user",
            "content": f"Web search results:\n{snippets}\n\nUse these to answer the question."
        }]
        web_response = ollama.chat(model=MODEL, messages=web_messages, options=OPT_SYNTH)
        answer = web_response.message.content or answer
        if urls:
            answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in urls)
        logging.info("[Orchestrator] Tavily fallback used (%d sources)", len(urls))
```

---

## Data Flow

```
process_turn(user_input)
    → planning → agents → synthesis → answer
        → is_uncertain(answer)?
            NO  → return answer unchanged
            YES → _web_search_with_sources(user_input) → (snippets, urls)
                    snippets empty? → return original answer unchanged
                    snippets present?
                        → re-synthesize with snippets as extra context → new answer
                        → append "\n\n**Web sources:**\n- url1\n- url2"
                        → return enriched answer
```

---

## Output Format

When Tavily fallback triggers, answer ends with:

```
...synthesized answer text...

**Web sources:**
- https://finance.yahoo.com/...
- https://reuters.com/...
- https://seekingalpha.com/...
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `TAVILY_API_KEY` not set | `_web_search_with_sources` returns `("", [])` — answer unchanged |
| Tavily API returns empty results | `snippets` is empty string — answer unchanged |
| Tavily API raises exception | Caught in `_web_search_with_sources`, returns `("", [])` — answer unchanged |
| Re-synthesis LLM call fails | `process_turn` outer try/except handles it — original answer returned |
| `is_uncertain` raises | Already has its own try/except — returns False — answer unchanged |

---

## Testing

Three tests in `tests/test_orchestrator.py`:

| Test | What it verifies |
|------|-----------------|
| `test_tavily_fallback_triggered_when_uncertain` | `is_uncertain` → True, Tavily returns results → URLs appear in `process_turn` output |
| `test_tavily_fallback_skipped_when_confident` | `is_uncertain` → False → `_web_search_with_sources` never called |
| `test_tavily_fallback_skipped_when_empty_results` | `is_uncertain` → True, Tavily returns `("", [])` → original answer returned unchanged |
