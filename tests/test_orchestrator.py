import json
from unittest.mock import MagicMock, patch


def _ollama_response(content):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = []
    return MagicMock(message=msg)


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

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response(plan_json),
        _ollama_response(synthesis_text),
    ]), \
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

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response(plan_json),
        _ollama_response("AAPL revenue is $400B."),
    ]), \
         patch("orchestrator.run_financials", return_value="Revenue: $400B") as mock_fin, \
         patch("orchestrator.run_news") as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        result, _ = process_turn("What is AAPL revenue?", [])

    mock_fin.assert_called_once()
    mock_news.assert_not_called()
    mock_calc.assert_not_called()
    assert "400" in result or "revenue" in result.lower()


def test_multi_agent_passes_context_forward():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials", "calc"], "tickers": ["AAPL"]})
    fin_result = "AAPL operating income: $120B"

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response(plan_json),
        _ollama_response("AAPL DCF: $195/share"),
    ]), \
         patch("orchestrator.run_financials", return_value=fin_result), \
         patch("orchestrator.run_calc", return_value="DCF: $195/share") as mock_calc:

        process_turn("Calculate AAPL DCF", [])

    calc_call_args = mock_calc.call_args
    context_passed = calc_call_args[0][1] if calc_call_args[0] else calc_call_args[1].get("context", "")
    assert "operating income" in context_passed or "AAPL" in context_passed


def test_malformed_plan_uses_keyword_fallback():
    from orchestrator import process_turn

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response("I cannot produce a plan right now."),
        _ollama_response("Here are the latest AAPL headlines."),
    ]), \
         patch("orchestrator.run_financials") as mock_fin, \
         patch("orchestrator.run_news", return_value="Headline: Apple up 2%") as mock_news, \
         patch("orchestrator.run_calc") as mock_calc:

        process_turn("latest news on AAPL", [])

    mock_news.assert_called_once()
    mock_fin.assert_not_called()


def test_agent_failure_is_skipped_gracefully():
    from orchestrator import process_turn

    plan_json = json.dumps({"agents": ["financials", "news"], "tickers": ["AAPL"]})

    with patch("orchestrator.ollama.chat", side_effect=[
        _ollama_response(plan_json),
        _ollama_response("Here is what I found."),
    ]), \
         patch("orchestrator.run_financials", side_effect=Exception("Ollama timeout")), \
         patch("orchestrator.run_news", return_value="Apple up 2%"):

        result, _ = process_turn("AAPL news and financials", [])

    assert isinstance(result, str)
