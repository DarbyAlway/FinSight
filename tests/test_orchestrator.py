import json
from unittest.mock import MagicMock, patch


def test_plan_parses_valid_json():
    from orchestrator import _parse_plan
    raw = '{"agents": ["financials", "calc"], "tickers": ["AAPL"]}'
    plan = _parse_plan(raw)
    assert plan["agents"] == ["financials", "calc"]
    assert plan["tickers"] == ["AAPL"]


def test_plan_parses_json_embedded_in_text():
    from orchestrator import _parse_plan
    raw = 'Sure, here is the plan: {"agents": ["news"], "tickers": ["TSLA"]} Let me proceed.'
    plan = _parse_plan(raw)
    assert plan["agents"] == ["news"]


def test_keyword_fallback_news():
    from orchestrator import _keyword_fallback
    assert _keyword_fallback("latest news on AAPL") == ["news"]


def test_keyword_fallback_calc():
    from orchestrator import _keyword_fallback
    assert _keyword_fallback("calculate CAGR for NVDA") == ["calc"]


def test_keyword_fallback_financials():
    from orchestrator import _keyword_fallback
    assert _keyword_fallback("show me AAPL revenue") == ["financials"]


def test_direct_answer_skips_agents():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": [], "tickers": []})
    synthesis_text = "P/E ratio is a valuation metric."

    with patch("orchestrator.llm_chat", side_effect=[plan_json, synthesis_text]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials") as mock_fin, \
         patch("orchestrator.run_news") as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        result, _ = process_turn("What is P/E ratio?", [])

    assert result == synthesis_text
    mock_fin.assert_not_called()
    mock_news.assert_not_called()
    mock_calc.assert_not_called()


def test_single_agent_plan_calls_correct_agent():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials"], "tickers": ["AAPL"]})

    with patch("orchestrator.llm_chat", side_effect=[plan_json, "AAPL revenue is $400B."]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", return_value="Revenue: $400B") as mock_fin, \
         patch("orchestrator.run_news") as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        result, _ = process_turn("What is AAPL revenue?", [])

    mock_fin.assert_called_once()
    mock_news.assert_not_called()
    mock_calc.assert_not_called()
    assert "400" in result or "revenue" in result.lower()


def test_multi_agent_both_called_in_parallel():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials", "calc"], "tickers": ["AAPL"]})

    with patch("orchestrator.llm_chat", side_effect=[plan_json, "AAPL DCF: $195/share"]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", return_value="AAPL operating income: $120B") as mock_fin, \
         patch("orchestrator.run_calc", return_value="DCF: $195/share") as mock_calc:

        result, _ = process_turn("Calculate AAPL DCF", [])

    mock_fin.assert_called_once()
    mock_calc.assert_called_once()
    fin_context = mock_fin.call_args[0][1] if mock_fin.call_args[0] else mock_fin.call_args[1].get("context", "")
    calc_context = mock_calc.call_args[0][1] if mock_calc.call_args[0] else mock_calc.call_args[1].get("context", "")
    assert fin_context == ""
    assert calc_context == ""


def test_malformed_plan_uses_keyword_fallback():
    from orchestrator import process_turn

    with patch("orchestrator.llm_chat", side_effect=[
        "I cannot produce a plan right now.",
        "Here are the latest AAPL headlines.",
    ]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials") as mock_fin, \
         patch("orchestrator.run_news", return_value="Headline: Apple up 2%") as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        process_turn("latest news on AAPL", [])

    mock_news.assert_called_once()
    mock_fin.assert_not_called()


def test_agent_failure_is_skipped_gracefully():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials", "news"], "tickers": ["AAPL"]})

    with patch("orchestrator.llm_chat", side_effect=[plan_json, "Here is what I found."]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", side_effect=Exception("timeout")), \
         patch("orchestrator.run_news", return_value="Apple up 2%"):

        result, _ = process_turn("AAPL news and financials", [])

    assert isinstance(result, str)


def test_tavily_fallback_triggered_when_uncertain():
    from orchestrator import process_turn

    uncertain_answer = "I don't have sufficient data to answer this."
    enriched_answer = "Based on web results, AAPL revenue was $94B."

    with patch("orchestrator._is_conversational", return_value=True), \
         patch("orchestrator.is_uncertain", return_value=True), \
         patch("orchestrator._web_search_with_sources",
               return_value=("Apple revenue was $94B per Reuters.", ["https://reuters.com/aapl"])), \
         patch("orchestrator.llm_chat", side_effect=[uncertain_answer, enriched_answer]):
        result, _ = process_turn("What is AAPL revenue?", [])

    assert "https://reuters.com/aapl" in result
    assert "Web sources" in result


def test_tavily_fallback_skipped_when_confident():
    from orchestrator import process_turn

    confident_answer = "AAPL P/E ratio is 28x based on trailing twelve months."

    mock_search = MagicMock()
    with patch("orchestrator._is_conversational", return_value=True), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.llm_chat", return_value=confident_answer):
        result, _ = process_turn("What is AAPL P/E?", [])

    mock_search.assert_not_called()
    assert result == confident_answer


def test_tavily_fallback_skipped_when_empty_results():
    from orchestrator import process_turn

    uncertain_answer = "I'm not certain about that."

    with patch("orchestrator._is_conversational", return_value=True), \
         patch("orchestrator.is_uncertain", return_value=True), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])), \
         patch("orchestrator.llm_chat", return_value=uncertain_answer):
        result, _ = process_turn("What is AAPL revenue?", [])

    assert result == uncertain_answer
    assert "Web sources" not in result
