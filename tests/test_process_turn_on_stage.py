"""process_turn(on_stage=...) emits high-level stages as graph nodes complete,
de-duplicated to consecutive-distinct labels. Offline: LLM + agent are mocked."""
import json
from unittest.mock import patch


def _plan(agents, tickers):
    return (json.dumps({"intent": "specific_tickers", "agents": agents, "tickers": tickers}), 0)


def _fake_financials(*a, **k):
    return ("## AAPL\nRevenue: 391,035M  (Sep 28, 2024)", 10,
            {"get_income_statement({})": "Total revenue: 391,035M  (Sep 28, 2024)"})


def test_on_stage_emits_pipeline_stages_in_order():
    from orchestrator import process_turn

    stages = []

    def on_stage(stage, detail=""):
        stages.append((stage, detail))

    with patch("orchestrator.llm_chat",
               side_effect=[_plan(["financials"], ["AAPL"]),
                            ("Revenue was 391,035M in FY2024.", 5)]), \
         patch("orchestrator.run_financials", side_effect=_fake_financials), \
         patch("orchestrator.validate_tickers", return_value=(["AAPL"], [])), \
         patch("orchestrator.detect_group_in_query", return_value=None), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])):
        answer, _ = process_turn("AAPL revenue?", [], on_stage=on_stage)

    labels = [s for s, _ in stages]
    assert all(labels[i] != labels[i + 1] for i in range(len(labels) - 1))
    for expected in ["planning", "fetching", "writing", "verifying"]:
        assert expected in labels
    assert labels.index("planning") < labels.index("fetching") < labels.index("writing")
    fetch_detail = next(d for s, d in stages if s == "fetching")
    assert "AAPL" in fetch_detail
    assert "391,035M" in answer


def test_no_on_stage_keeps_plain_invoke_behavior():
    from orchestrator import process_turn

    with patch("orchestrator.llm_chat",
               side_effect=[_plan(["financials"], ["AAPL"]),
                            ("Revenue was 391,035M in FY2024.", 5)]), \
         patch("orchestrator.run_financials", side_effect=_fake_financials), \
         patch("orchestrator.validate_tickers", return_value=(["AAPL"], [])), \
         patch("orchestrator.detect_group_in_query", return_value=None), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])):
        answer, messages = process_turn("AAPL revenue?", [])

    assert "391,035M" in answer
    assert messages[-1]["role"] == "assistant"
