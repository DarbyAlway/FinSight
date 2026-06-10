import logging
import os

import numpy as np

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

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


_UNCERTAIN_ANCHORS = [
    "I don't have sufficient data to answer this.",
    "I don't know the answer to that.",
    "I don't have access to that information.",
    "That information is not available to me.",
    "I cannot answer this question.",
    "I am unable to provide that information.",
    "This is outside the scope of my available tools.",

    # General uncertainty
    "I'm not certain about that.",
    "I'm unsure about that.",
    "I don't have enough information to answer that.",
    "I can't determine the answer with confidence.",
    "I'm unable to verify that information.",
    "I don't have a reliable answer for that.",
    "I can't say for sure.",
    "I'm not confident enough to answer that accurately.",
    "I may not have the correct information on that.",
    "I don't have sufficient context to answer that.",
    "I'm not able to confirm that.",
    "I don't have visibility into that.",
    "I don't have evidence to support an answer.",
    "I can't verify the accuracy of that claim.",
    "I don't have the necessary data to answer that.",
    "I'm unable to determine that from the information available.",
    "I don't have a definitive answer.",
    "I'm uncertain about the details.",
    "I don't have enough reliable information.",
    "I cannot confidently answer that question.",
    "I don't have the ability to check that.",
    "I don't have direct knowledge of that.",
    "I can't reliably answer that.",
    "The available information is inconclusive.",
    "I don't have enough evidence to make a determination.",
    "I cannot validate that information.",
    "I don't have a trustworthy source for that.",
    "I can't infer that safely.",
    "I don't have enough clarity to answer that properly.",
    "I don't have the required context.",
    "I can't establish that as fact.",
    "I don't know whether that's correct.",
    "I can't confirm or deny that.",
    "I don't have the means to verify that claim.",
    "I cannot assess that accurately.",
    "I don't have enough background information.",
    "I don't have access to real-time verification.",
    "I can't determine whether that's true.",
    "I'm missing key information needed to answer that.",
    "I don't have enough detail to provide an accurate response.",
    "That falls outside my current knowledge.",
    "I cannot provide a reliable conclusion.",
    "I don't have enough certainty to respond definitively.",
    "I can't validate that with confidence.",
    "I don't have access to authoritative information on that.",
    "I can't provide a factually grounded answer.",
    "I don't have enough supporting information.",
    "I can't reach a reliable conclusion from the available data.",
    "I don't have enough information to make that judgment.",
    "I'm unable to establish the accuracy of that statement.",
    "I don't have enough certainty to answer responsibly.",
    "I cannot determine the validity of that claim.",
    "The information I have is incomplete.",
    "I don't have enough information to verify that.",
    "I cannot confidently infer the answer.",
    "I don't have a dependable answer for that.",
    "I can't establish that with certainty.",
    "I don't have enough insight into that topic.",
    "I cannot provide a verified answer.",
    "I'm not able to authenticate that information.",
    "I don't have the authority to determine that.",
    "I can't evaluate that reliably.",
    "I don't have enough grounding to answer that safely.",
    "I cannot substantiate that claim.",
    "I don't have sufficient evidence to support an answer.",
    "I can't reliably determine the outcome.",
    "I'm unable to resolve that ambiguity.",
    "I don't have enough confidence in the available information.",
    "I can't produce a trustworthy answer to that.",
    "I don't have access to the necessary records.",
    "I cannot independently confirm that.",
    "I'm unable to conclude that from the available evidence.",
    "I don't have enough information to provide a precise answer.",
    "I can't determine the reliability of that information.",
    "I don't have enough detail to verify the claim.",
    "I'm not able to answer that accurately.",
    "I cannot establish the truth of that statement.",
    "I don't have enough certainty to make that claim.",
    "I cannot determine that conclusively.",
    "I don't have access to the underlying data.",
    "I can't answer that with high confidence.",
    "I don't have enough information to draw a conclusion.",
    "I cannot verify whether that is accurate.",
    "I don't have a clear answer for that.",
    "I'm unable to provide a definitive response.",
    "I can't determine that based on the information available.",
    "I don't have enough information to make a reliable assessment.",
    "I cannot confidently validate that information.",
    "I don't have enough supporting evidence for an answer.",
    "I can't establish that as accurate.",
    "I don't have the necessary verification.",
    "I'm unable to confirm the authenticity of that information.",
    "I don't have enough information to answer with certainty.",
    "I cannot provide confirmation on that.",
    "I don't have enough reliable context to answer.",
    "I can't verify that independently.",
    "I don't have the necessary insight to answer that accurately.",
    "I cannot confidently determine the answer.",
    "I'm unable to provide a fully reliable response.",
    "I don't have enough trustworthy information to answer that.",
    "I can't determine that reliably from current information.",
    "I don't have enough evidence to confidently respond.",
    "I cannot establish that conclusively.",
    "I don't have enough information to support a definitive answer.",
    "I cannot verify that statement.",
    "I don't have enough clarity to provide an accurate answer.",
    "I can't reliably validate that claim.",
    "I don't have sufficient verified information.",
    "I'm unable to determine the correctness of that.",
    "I cannot provide a certainty-backed answer.",
    "I don't have enough information to provide confirmation.",
    "I can't assess the validity of that information.",
    "I don't have enough reliable context to verify that.",
    "I cannot determine that with confidence.",
    "I don't have enough evidence to make a factual claim.",
    "I can't provide a conclusive answer.",
    "I don't have enough information to assess that properly.",
    "I cannot verify the legitimacy of that information.",
    "I don't have enough reliable data to conclude that.",
]

_anchor_vecs = None


def _get_anchor_vecs():
    global _anchor_vecs
    if _anchor_vecs is None:
        from tools.vector import _get_encoders
        dense_enc, _ = _get_encoders()
        _anchor_vecs = np.array(list(dense_enc.embed(_UNCERTAIN_ANCHORS)))
    return _anchor_vecs


def is_uncertain(text: str, threshold: float = 0.75) -> bool:
    if not text:
        return False
    try:
        from tools.vector import _get_encoders
        dense_enc, _ = _get_encoders()
        vec = np.array(list(dense_enc.embed([text]))[0])
        anchors = _get_anchor_vecs()
        scores = anchors @ vec / (np.linalg.norm(anchors, axis=1) * np.linalg.norm(vec) + 1e-9)
        result = float(scores.max()) >= threshold
        logging.info("is_uncertain score=%.3f threshold=%.2f → %s", scores.max(), threshold, result)
        return result
    except Exception as e:
        logging.warning("is_uncertain failed: %s", e)
        return False


def web_search_fallback(query: str) -> str:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logging.warning("web_search_fallback: TAVILY_API_KEY not set, skipping")
        return ""
    try:
        import time
        from tavily import TavilyClient
        t0 = time.perf_counter()
        result = TavilyClient(api_key).search(query, max_results=3)
        snippets = [r.get("content", "") for r in result.get("results", [])]
        logging.info("web_search_fallback('%s') → %.2fs (%d results)", query, time.perf_counter() - t0, len(snippets))
        return "\n\n".join(snippets) or f"No results found for: {query}"
    except Exception as e:
        logging.warning("Tavily search failed: %s", e)
        return ""


def _web_search_with_sources(query: str, time_sensitive: bool = False) -> tuple[str, list[str]]:
    """Search with ADVANCED depth: basic-depth snippets are headline fragments
    (live A/B 2026-06-10: basic gave a 52-week factoid + a 2025 article for a
    'past week' query; advanced gave current coverage with price-change tables).
    `time_sensitive=True` restricts results to the past week — without it, stale
    articles rank for 'this week' questions. raw_content is deliberately not
    requested (15-50KB of nav/cookie boilerplate per page)."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logging.warning("_web_search_with_sources: TAVILY_API_KEY not set, skipping")
        return "", []
    try:
        import time as _time
        t0 = _time.perf_counter()
        kwargs = {"max_results": 3, "search_depth": "advanced"}
        if time_sensitive:
            kwargs["time_range"] = "week"
        result = TavilyClient(api_key).search(query, **kwargs)
        results = result.get("results", [])
        snippets = "\n\n".join(r.get("content", "") for r in results)
        urls = [r.get("url", "") for r in results if r.get("url")]
        logging.info("_web_search_with_sources('%s', time_sensitive=%s) → %.2fs (%d results)",
                     query, time_sensitive, _time.perf_counter() - t0, len(results))
        return snippets, urls
    except Exception as e:
        logging.warning("_web_search_with_sources failed: %s", e)
        return "", []
