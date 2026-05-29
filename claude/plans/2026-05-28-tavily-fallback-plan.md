# Tavily Web Search Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the synthesis LLM produces an uncertain answer, automatically search Tavily, re-synthesize with results, and append source URLs to the final answer.

**Architecture:** `_web_search_with_sources` is added to `tools/search_guardrails.py` (returns snippets + URLs). `orchestrator.py` imports it and hooks into the post-synthesis step — if `is_uncertain(answer)` is True and Tavily returns results, one re-synthesis call is made and URLs are appended.

**Tech Stack:** `tavily-python`, `ollama`, `unittest.mock`

---

## File Map

| File | Change |
|------|--------|
| `tools/search_guardrails.py` | Add `_web_search_with_sources(query) -> tuple[str, list[str]]` |
| `orchestrator.py` | Add import + post-synthesis uncertainty check |
| `tests/test_orchestrator.py` | Add 3 tests for the fallback behaviour |
| `tests/test_tools.py` | Add 3 unit tests for `_web_search_with_sources` |

---

### Task 1: `_web_search_with_sources` in `tools/search_guardrails.py`

**Files:**
- Modify: `tools/search_guardrails.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Add at the end of `tests/test_tools.py`:

```python
# ---------------------------------------------------------------------------
# _web_search_with_sources tests
# ---------------------------------------------------------------------------

def test_web_search_with_sources_returns_snippets_and_urls():
    from unittest.mock import patch, MagicMock
    from tools.search_guardrails import _web_search_with_sources

    mock_result = {
        "results": [
            {"content": "Apple reported strong earnings.", "url": "https://reuters.com/aapl"},
            {"content": "iPhone sales beat estimates.", "url": "https://bloomberg.com/aapl"},
        ]
    }
    with patch("tools.search_guardrails.os.getenv", return_value="test-key"), \
         patch("tools.search_guardrails.TavilyClient") as mock_client:
        mock_client.return_value.search.return_value = mock_result
        snippets, urls = _web_search_with_sources("AAPL earnings")

    assert "Apple reported strong earnings" in snippets
    assert "https://reuters.com/aapl" in urls
    assert "https://bloomberg.com/aapl" in urls
    assert len(urls) == 2


def test_web_search_with_sources_returns_empty_when_no_api_key():
    from tools.search_guardrails import _web_search_with_sources

    with patch("tools.search_guardrails.os.getenv", return_value=None):
        snippets, urls = _web_search_with_sources("AAPL earnings")

    assert snippets == ""
    assert urls == []


def test_web_search_with_sources_returns_empty_on_exception():
    from unittest.mock import patch
    from tools.search_guardrails import _web_search_with_sources

    with patch("tools.search_guardrails.os.getenv", return_value="test-key"), \
         patch("tools.search_guardrails.TavilyClient", side_effect=Exception("API error")):
        snippets, urls = _web_search_with_sources("AAPL earnings")

    assert snippets == ""
    assert urls == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
conda run -n stock pytest tests/test_tools.py::test_web_search_with_sources_returns_snippets_and_urls tests/test_tools.py::test_web_search_with_sources_returns_empty_when_no_api_key tests/test_tools.py::test_web_search_with_sources_returns_empty_on_exception -v
```

Expected: FAIL with `ImportError: cannot import name '_web_search_with_sources'`

- [ ] **Step 3: Add `_web_search_with_sources` to `tools/search_guardrails.py`**

Add after the existing `web_search_fallback` function:

```python
def _web_search_with_sources(query: str) -> tuple[str, list[str]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logging.warning("_web_search_with_sources: TAVILY_API_KEY not set, skipping")
        return "", []
    try:
        import time
        from tavily import TavilyClient
        t0 = time.perf_counter()
        result = TavilyClient(api_key).search(query, max_results=3)
        results = result.get("results", [])
        snippets = "\n\n".join(r.get("content", "") for r in results)
        urls = [r.get("url", "") for r in results if r.get("url")]
        logging.info("_web_search_with_sources('%s') → %.2fs (%d results)", query, time.perf_counter() - t0, len(results))
        return snippets, urls
    except Exception as e:
        logging.warning("_web_search_with_sources failed: %s", e)
        return "", []
```

- [ ] **Step 4: Run tests to verify they pass**

```
conda run -n stock pytest tests/test_tools.py::test_web_search_with_sources_returns_snippets_and_urls tests/test_tools.py::test_web_search_with_sources_returns_empty_when_no_api_key tests/test_tools.py::test_web_search_with_sources_returns_empty_on_exception -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add tools/search_guardrails.py tests/test_tools.py
git commit -m "feat: add _web_search_with_sources to search_guardrails (TDD)"
```

---

### Task 2: Post-synthesis uncertainty hook in `orchestrator.py`

**Files:**
- Modify: `orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Add at the end of `tests/test_orchestrator.py`:

```python
def test_tavily_fallback_triggered_when_uncertain():
    from orchestrator import process_turn

    uncertain_answer = "I don't have sufficient data to answer this."
    enriched_answer = "Based on web results, AAPL revenue was $94B."

    with patch("orchestrator._is_conversational", return_value=True), \
         patch("orchestrator.is_uncertain", return_value=True), \
         patch("orchestrator._web_search_with_sources",
               return_value=("Apple revenue was $94B per Reuters.", ["https://reuters.com/aapl"])), \
         patch("orchestrator.ollama.chat", side_effect=[
             _ollama_response(uncertain_answer),   # synthesis
             _ollama_response(enriched_answer),    # re-synthesis with Tavily context
         ]):
        result, _ = process_turn("What is AAPL revenue?", [])

    assert "https://reuters.com/aapl" in result
    assert "Web sources" in result


def test_tavily_fallback_skipped_when_confident():
    from unittest.mock import MagicMock
    from orchestrator import process_turn

    confident_answer = "AAPL P/E ratio is 28x based on trailing twelve months."

    mock_search = MagicMock()
    with patch("orchestrator._is_conversational", return_value=True), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.ollama.chat", side_effect=[
             _ollama_response(confident_answer),   # synthesis only
         ]):
        result, _ = process_turn("What is AAPL P/E?", [])

    mock_search.assert_not_called()
    assert result == confident_answer


def test_tavily_fallback_skipped_when_empty_results():
    from orchestrator import process_turn

    uncertain_answer = "I'm not certain about that."

    with patch("orchestrator._is_conversational", return_value=True), \
         patch("orchestrator.is_uncertain", return_value=True), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])), \
         patch("orchestrator.ollama.chat", side_effect=[
             _ollama_response(uncertain_answer),   # synthesis only — no re-synthesis
         ]):
        result, _ = process_turn("What is AAPL revenue?", [])

    assert result == uncertain_answer
    assert "Web sources" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

```
conda run -n stock pytest tests/test_orchestrator.py::test_tavily_fallback_triggered_when_uncertain tests/test_orchestrator.py::test_tavily_fallback_skipped_when_confident tests/test_orchestrator.py::test_tavily_fallback_skipped_when_empty_results -v
```

Expected: FAIL — `patch("orchestrator.is_uncertain"...)` raises `AttributeError: <module 'orchestrator'> does not have the attribute 'is_uncertain'`

- [ ] **Step 3: Add the import to `orchestrator.py`**

At the top of `orchestrator.py`, after the existing imports, add:

```python
from tools.search_guardrails import is_uncertain, _web_search_with_sources
```

- [ ] **Step 4: Add the post-synthesis hook to `orchestrator.py`**

Find these two lines in `process_turn` (currently lines 167-168):

```python
    synthesis_response = ollama.chat(model=MODEL, messages=synthesis_messages, options=OPT_SYNTH)
    answer = synthesis_response.message.content or ""
```

Add immediately after `answer = synthesis_response.message.content or ""`:

```python
    if is_uncertain(answer):
        snippets, urls = _web_search_with_sources(user_input)
        if snippets:
            web_messages = synthesis_messages + [{
                "role": "user",
                "content": f"Web search results:\n{snippets}\n\nUse these to answer the question.",
            }]
            web_response = ollama.chat(model=MODEL, messages=web_messages, options=OPT_SYNTH)
            answer = web_response.message.content or answer
            if urls:
                answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in urls)
            logging.info("[Orchestrator] Tavily fallback used (%d sources)", len(urls))
```

- [ ] **Step 5: Run new tests to verify they pass**

```
conda run -n stock pytest tests/test_orchestrator.py::test_tavily_fallback_triggered_when_uncertain tests/test_orchestrator.py::test_tavily_fallback_skipped_when_confident tests/test_orchestrator.py::test_tavily_fallback_skipped_when_empty_results -v
```

Expected: 3 PASSED

- [ ] **Step 6: Run full orchestrator + tools test suite to check for regressions**

```
conda run -n stock pytest tests/test_orchestrator.py tests/test_tools.py tests/test_agents.py -v 2>&1 | tail -15
```

Expected: All previously passing tests still PASS (68 + 3 new = 71 passed)

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire Tavily web search fallback at synthesis level (TDD)"
```
