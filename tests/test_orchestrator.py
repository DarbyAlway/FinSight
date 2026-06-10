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
         patch("orchestrator.run_financials", return_value=("Revenue: $400B", 0, {})) as mock_fin, \
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
         patch("orchestrator.run_financials", return_value=("AAPL operating income: $120B", 0, {})) as mock_fin, \
         patch("orchestrator.run_calc", return_value=("DCF: $195/share", 0, {})) as mock_calc:

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
         patch("orchestrator.run_news", return_value=("Headline: Apple up 2%", 0, {})) as mock_news, \
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
         patch("orchestrator.run_news", return_value=("Apple up 2%", 0, {})):

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
         patch("orchestrator.run_financials", return_value=("data", 0, {})) as mock_fin:
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
         patch("orchestrator.run_financials", return_value=("data", 0, {})) as mock_fin:
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
         patch("orchestrator.run_financials", return_value=("data", 0, {})) as mock_fin:
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
         patch("orchestrator.run_financials", return_value=("Revenue: $391B", 0, {})):
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
         patch("orchestrator.run_financials", return_value=("AAPL P/E: 28x", 0, {})), \
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
         patch("orchestrator.run_financials", return_value=("AAPL revenue: $391B", 0, {})), \
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
         patch("orchestrator.run_news", return_value=("Headlines: tech slid", 0, {})):
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
         patch("orchestrator.run_financials", return_value=("## AAPL\nP/E: 28x", 0, {})):
        process_turn("what is AAPL P/E?", [])

    mock_search.assert_not_called()


def test_missing_intent_defaults_to_no_proactive_search():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials"], "tickers": ["AAPL"]})  # no intent key
    mock_search = MagicMock()

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("AAPL revenue $391B.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nRevenue: $391B", 0, {})):
        process_turn("AAPL revenue?", [])

    mock_search.assert_not_called()


def test_reactive_fallback_when_all_agents_return_no_data():
    """is_uncertain is False, but every agent output is an error → fire fallback."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["LITE"]})

    with patch("orchestrator.llm_chat", side_effect=[
        (plan_json, 0),
        ("There is no information available.", 0),
        ("LITE PEG is 1.2 based on web data.", 0),
    ]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources",
               return_value=("LITE PEG 1.2 per Reuters.", ["https://r.com/lite"])), \
         patch("orchestrator.run_financials", return_value=("## LITE\nERROR: No company info for LITE", 0, {})):
        result, _ = process_turn("what about LITE PEG?", [])

    assert "https://r.com/lite" in result


def test_fidelity_soft_mismatch_is_flag_only(caplog):
    """A SOFT mismatch (value real for another year, just wrong-year labeled) is
    logged but NOT re-prompted — answer returned unchanged."""
    import logging
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    # Grounding: FY2024=391,035 and FY2023=383,285.
    tool_blocks = {"get_income_statement({})":
                   "Total revenue: 391,035M  (Sep 28, 2024)\nTotal revenue: 383,285M  (Sep 30, 2023)"}
    # 391,035 is real but labeled FY2023 (it's the FY2024 value) -> SOFT.
    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("FY2023 revenue was 391,035M.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", MagicMock()), \
         patch("orchestrator.run_financials", return_value=("## AAPL\ndata", 0, tool_blocks)):
        with caplog.at_level(logging.WARNING):
            result, _ = process_turn("AAPL revenue?", [])

    assert "391,035M" in result  # flag-only: answer unchanged
    assert any("soft untraced" in r.message.lower() for r in caplog.records)


def test_fidelity_reprompts_on_hard_hallucination(caplog):
    """A HARD mismatch (figure absent from ALL fetched years) triggers a grounded
    self-critique re-prompt; the corrected answer replaces the hallucinated one."""
    import logging
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["MSFT"]})
    tool_blocks = {"get_income_statement({})": "Total revenue: 281,724M  (Jun 30, 2025)"}
    hallucinated = "MSFT FY2020 revenue was $143,015 million."   # absent from grounding -> HARD
    corrected = "MSFT FY2020 revenue is not available in the provided data."

    with patch("orchestrator.llm_chat",
               side_effect=[(plan_json, 0), (hallucinated, 0), (corrected, 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", MagicMock()), \
         patch("orchestrator.run_financials", return_value=("## MSFT\nRevenue: 281,724M  (Jun 30, 2025)", 0, tool_blocks)):
        with caplog.at_level(logging.WARNING):
            result, _ = process_turn("MSFT FY2020 revenue?", [])

    assert result == corrected  # self-critique replaced the hallucinated answer
    assert any("self-critique" in r.message.lower() for r in caplog.records)


def test_fidelity_silent_when_numbers_traceable(caplog):
    """When synthesis quotes a number present in tool_blocks, no fidelity WARNING."""
    import logging
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    tool_blocks = {"get_income_statement({})": "Total revenue: 391,035M  (Sep 28, 2024)"}

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("FY2024 revenue was 391,035M.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", MagicMock()), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nRevenue: 391,035M  (Sep 28, 2024)", 0, tool_blocks)):
        with caplog.at_level(logging.WARNING):
            process_turn("AAPL FY2024 revenue?", [])

    assert not any("untraced number" in r.message.lower() for r in caplog.records)


def test_reactive_fallback_not_fired_on_real_data():
    """Real agent data + confident answer → no web search (no false-firing)."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    mock_search = MagicMock()

    with patch("orchestrator.llm_chat", side_effect=[(plan_json, 0), ("AAPL revenue was $391B.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nRevenue: $391,035M", 0, {})):
        process_turn("AAPL revenue?", [])

    mock_search.assert_not_called()


# ----------------------------------------------------------------------------
# Escalation (live case 2026-06-10): "tech stocks that dropped ~20% this week".
# No tool provides weekly price change, so synthesis fabricated WoW percents and
# kept them THROUGH the self-critique ("after self-critique: 9 untraced (9
# hard)") — and the answer shipped. When HARD mismatches survive the critique,
# the agents demonstrably cannot support the answer: escalate to web search,
# or disclose the unverified figures if the web has nothing.
# ----------------------------------------------------------------------------

def test_fidelity_escalates_to_web_when_critique_fails():
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    tool_blocks = {"get_company_info({})": "Current Price: $290.55"}
    fabricated = "AAPL fell 20.3% this week."
    still_bad = "AAPL declined roughly 20.3% week-over-week."
    web_answer = "Per Reuters, AAPL fell 4.1% this week."

    with patch("orchestrator.llm_chat", side_effect=[
            (plan_json, 0), (fabricated, 0), (still_bad, 0), (web_answer, 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources",
               return_value=("AAPL weekly change -4.1% (Reuters).", ["https://reuters.com/aapl"])) as mock_search, \
         patch("orchestrator.run_financials", return_value=("## AAPL\nCurrent Price: $290.55", 0, tool_blocks)):
        result, _ = process_turn("which tech stocks dropped about 20 percent this week?", [])

    # 'this week' makes the query time-sensitive → search must use the week filter
    mock_search.assert_called_once_with(
        "which tech stocks dropped about 20 percent this week?", time_sensitive=True)
    assert "Reuters" in result
    assert "https://reuters.com/aapl" in result
    assert "20.3%" not in result  # fabricated figure must NOT ship


def test_fidelity_no_escalation_when_critique_fixes():
    """When the self-critique rewrite is clean, no web escalation fires."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["MSFT"]})
    tool_blocks = {"get_income_statement({})": "Total revenue: 281,724M  (Jun 30, 2025)"}
    mock_search = MagicMock()

    with patch("orchestrator.llm_chat", side_effect=[
            (plan_json, 0),
            ("MSFT FY2020 revenue was $143,015 million.", 0),          # HARD
            ("MSFT FY2020 revenue is not available in the data.", 0),  # clean fix
    ]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", mock_search), \
         patch("orchestrator.run_financials", return_value=("## MSFT\nRevenue: 281,724M  (Jun 30, 2025)", 0, tool_blocks)):
        process_turn("MSFT FY2020 revenue?", [])

    mock_search.assert_not_called()


def test_fidelity_escalation_discloses_when_web_empty():
    """Persistent HARD misses + empty web results → ship with an explicit
    unverified-figures caveat rather than silently."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    tool_blocks = {"get_company_info({})": "Current Price: $290.55"}

    with patch("orchestrator.llm_chat", side_effect=[
            (plan_json, 0),
            ("AAPL fell 20.3% this week.", 0),
            ("AAPL declined roughly 20.3% week-over-week.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nCurrent Price: $290.55", 0, tool_blocks)):
        result, _ = process_turn("which tech stocks dropped about 20 percent this week?", [])

    assert "could not be verified" in result


def test_web_fallback_answer_skips_fidelity(caplog):
    """An answer regenerated from WEB results must not be verified against the
    agents' tool blocks (web figures are legitimately untraceable there)."""
    import logging
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["LITE"]})
    tool_blocks = {"get_company_info({})": "No company info found for LITE."}

    with patch("orchestrator.llm_chat", side_effect=[
            (plan_json, 0),
            ("There is no information available.", 0),
            ("LITE fell 5.2% this week per Reuters.", 0)]), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources",
               return_value=("LITE weekly -5.2% (Reuters).", ["https://r.com/lite"])), \
         patch("orchestrator.run_financials",
               return_value=("## LITE\nERROR: No company info for LITE", 0, tool_blocks)):
        with caplog.at_level(logging.WARNING):
            process_turn("how did LITE do this week?", [])

    assert not any("untraced number" in r.message.lower() for r in caplog.records)


def test_context_headers_are_neutral_source_labels():
    """gpt-oss cites block headers verbatim (【FINANCIALS AGENT】 leaked to a
    user). Headers must be neutral source labels, never '<NAME> AGENT'."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    mock_llm = MagicMock(side_effect=[(plan_json, 0), ("AAPL price is $290.55.", 0)])

    with patch("orchestrator.llm_chat", mock_llm), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", MagicMock()), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nCurrent Price: $290.55", 0, {})):
        process_turn("AAPL price?", [])

    synthesis_messages = mock_llm.call_args_list[1].args[1]
    context = synthesis_messages[-1]["content"]
    assert "AGENT]" not in context
    assert "[MARKET DATA]" in context


def test_web_synthesis_authorizes_web_figures():
    """Live failure 2026-06-10: escalation searched the web but the re-answer
    said 'not provided in the agent outputs' — the web re-synthesis inherited
    the 'using ONLY the agent outputs' instruction, which overrides the web
    snippets. Web-grounded synthesis must NOT carry that instruction and must
    explicitly authorize answering from the web results."""
    from orchestrator import process_turn

    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"], "tickers": ["AAPL"]})
    tool_blocks = {"get_company_info({})": "Current Price: $290.55"}
    mock_llm = MagicMock(side_effect=[
        (plan_json, 0),
        ("AAPL fell 20.3% this week.", 0),                  # HARD
        ("AAPL declined roughly 20.3% week-over-week.", 0),  # critique fails
        ("Per Reuters, AAPL fell 4.1% this week.", 0),       # web re-answer
    ])

    with patch("orchestrator.llm_chat", mock_llm), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources",
               return_value=("AAPL weekly change -4.1% (Reuters).", ["https://reuters.com/aapl"])), \
         patch("orchestrator.run_financials", return_value=("## AAPL\nCurrent Price: $290.55", 0, tool_blocks)):
        process_turn("which tech stocks dropped about 20 percent this week?", [])

    web_call_messages = mock_llm.call_args_list[3].args[1]
    final_user_content = web_call_messages[-1]["content"]
    assert "ONLY the agent outputs" not in final_user_content
    assert "AAPL weekly change -4.1%" in final_user_content  # snippets present
    assert "web search results" in final_user_content.lower()
    # no earlier message in the web call may demand agent-outputs-only either
    assert not any("ONLY the agent outputs" in m.get("content", "") for m in web_call_messages)


def test_synthesis_prompt_allows_web_result_figures():
    from prompts import SYNTHESIS_SYSTEM
    assert "web search results" in SYNTHESIS_SYSTEM.lower()
