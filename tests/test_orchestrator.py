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

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), (synthesis_text, 0)]), \
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

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("AAPL revenue is $400B.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", return_value=("Revenue: $400B", 0)) as mock_fin, \
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

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("AAPL DCF: $195/share", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", return_value=("AAPL operating income: $120B", 0)) as mock_fin, \
         patch("orchestrator.run_calc", return_value=("DCF: $195/share", 0)) as mock_calc:

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
        ("I cannot produce a plan right now.", 0),
        ("Here are the latest AAPL headlines.", 0),
    ]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials") as mock_fin, \
         patch("orchestrator.run_news", return_value=("Headline: Apple up 2%", 0)) as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        process_turn("latest news on AAPL", [])

    mock_news.assert_called_once()
    mock_fin.assert_not_called()


def test_agent_failure_is_skipped_gracefully():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials", "news"], "tickers": ["AAPL"]})

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("Here is what I found.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", side_effect=Exception("timeout")), \
         patch("orchestrator.run_news", return_value=("Apple up 2%", 0)):

        result, _ = process_turn("AAPL news and financials", [])

    assert isinstance(result, str)


def test_gate1_overrides_planner_group_tickers():
    """When the user names a known group, the manifest overrides the planner's
    (unreliable) ticker expansion — the FB/BABA/missing-META-NVDA bug."""
    from orchestrator import process_turn

    # Planner emits the buggy MAG7 expansion seen live.
    buggy = ["AAPL", "MSFT", "AMZN", "GOOGL", "FB", "BABA", "TSLA"]
    plan_json = json.dumps({"agents": ["financials"], "tickers": buggy})

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("done", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", return_value=("data", 0)) as mock_fin:
        process_turn("analyze MAG7", [])

    passed = mock_fin.call_args.kwargs["expected_tickers"]
    assert set(passed) == {"AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"}
    assert "FB" not in passed and "BABA" not in passed


def test_gate1_leaves_non_group_tickers_untouched():
    """A query with no group mention keeps the planner's tickers as-is."""
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials"], "tickers": ["AAPL"]})

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("done", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.run_financials", return_value=("data", 0)) as mock_fin:
        process_turn("analyze AAPL", [])

    assert mock_fin.call_args.kwargs["expected_tickers"] == ["AAPL"]


def test_gate2_drops_dead_ticker_and_skips_agents():
    """A dead/unlisted ticker (TWTR) is dropped; with nothing left to analyze,
    data agents are skipped entirely instead of burning tokens on errors."""
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials", "ratios", "news"], "tickers": ["TWTR"]})
    synthesis_text = "TWTR is no longer publicly listed."

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), (synthesis_text, 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.validate_tickers", return_value=([], ["TWTR"])), \
         patch("orchestrator.run_financials") as mock_fin, \
         patch("orchestrator.run_ratios") as mock_ratios, \
         patch("orchestrator.run_news") as mock_news:
        result, _ = process_turn("analyze Twitter stock", [])

    mock_fin.assert_not_called()
    mock_ratios.assert_not_called()
    mock_news.assert_not_called()
    assert result == synthesis_text


def test_gate2_drops_invalid_keeps_valid_tickers():
    """When some tickers are valid and some dead, only the valid ones reach agents."""
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials"], "tickers": ["AAPL", "TWTR"]})

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("done", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator.validate_tickers", return_value=(["AAPL"], ["TWTR"])), \
         patch("orchestrator.run_financials", return_value=("data", 0)) as mock_fin:
        process_turn("compare AAPL and Twitter", [])

    mock_fin.assert_called_once()
    assert mock_fin.call_args.kwargs["expected_tickers"] == ["AAPL"]


def test_tavily_fallback_triggered_when_uncertain():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials"], "tickers": ["AAPL"]})
    uncertain_answer = "I don't have sufficient data to answer this."
    enriched_answer = "Based on web results, AAPL revenue was $94B."

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), (uncertain_answer, 0), (enriched_answer, 0)]), \
         patch("orchestrator.is_uncertain", return_value=True), \
         patch("orchestrator._web_search_with_sources",
               return_value=("Apple revenue was $94B per Reuters.", ["https://reuters.com/aapl"])), \
         patch("orchestrator.run_financials", return_value=("Revenue: $391B", 0)):
        result, _ = process_turn("What is AAPL revenue?", [])

    assert "https://reuters.com/aapl" in result
    assert "Web sources" in result


def test_tavily_fallback_skipped_when_confident():
    from orchestrator import process_turn

    confident_answer = "AAPL P/E ratio is 28x based on trailing twelve months."

    plan = json.dumps({"agents": ["financials"], "tickers": ["AAPL"]})
    mock_search = MagicMock()
    with patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.run_financials", return_value=("AAPL P/E: 28x", 0)), \
         patch("orchestrator.llm_chat", side_effect=[(plan, 0), (confident_answer, 0)]):
        result, _ = process_turn("What is AAPL P/E?", [])

    mock_search.assert_not_called()
    assert result == confident_answer


def test_tavily_fallback_skipped_when_empty_results():
    from orchestrator import process_turn

    uncertain_answer = "I'm not certain about that."

    plan = json.dumps({"agents": ["financials"], "tickers": ["AAPL"]})
    with patch("orchestrator.is_uncertain", return_value=True), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])), \
         patch("orchestrator.run_financials", return_value=("AAPL revenue: $391B", 0)), \
         patch("orchestrator.llm_chat", side_effect=[(plan, 0), (uncertain_answer, 0)]):
        result, _ = process_turn("What is AAPL revenue?", [])

    assert result == uncertain_answer
    assert "Web sources" not in result


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
