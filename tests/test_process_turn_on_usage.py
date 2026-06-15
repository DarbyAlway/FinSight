"""process_turn(on_usage=...) reports the turn's total token count. Offline."""
import json
from unittest.mock import patch


def _plan(agents, tickers):
    return (json.dumps({"intent": "specific_tickers", "agents": agents, "tickers": tickers}), 7)


def _fake_fin(*a, **k):
    return ("## AAPL\nRevenue: 391,035M", 11, {"get_income_statement({})": "Total revenue: 391,035M"})


def test_on_usage_reports_total_tokens():
    from orchestrator import process_turn
    seen = {}
    with patch("orchestrator.llm_chat",
               side_effect=[_plan(["financials"], ["AAPL"]), ("Revenue was 391,035M.", 5)]), \
         patch("orchestrator.run_financials", side_effect=_fake_fin), \
         patch("orchestrator.validate_tickers", return_value=(["AAPL"], [])), \
         patch("orchestrator.detect_group_in_query", return_value=None), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])):
        process_turn("AAPL revenue?", [], on_usage=lambda t: seen.setdefault("t", t))
    assert seen["t"] > 0  # plan + agents + synthesis tokens summed
