# tests/test_graph_nodes.py
import json
from unittest.mock import MagicMock, patch


def test_plan_node_parses_plan_and_counts_tokens():
    from orchestrator import _plan_node
    plan_json = json.dumps({"intent": "specific_tickers", "agents": ["financials"],
                            "tickers": ["AAPL"], "reason": "r"})
    with patch("orchestrator.llm_chat", return_value=(plan_json, 42)):
        out = _plan_node({"user_input": "AAPL revenue?", "history": [], "persona_system": None})
    assert out["agents_to_run"] == ["financials"]
    assert out["tickers"] == ["AAPL"]
    assert out["intent"] == "specific_tickers"
    assert out["tokens"] == {"plan": 42}
    assert "synth_sys" in out


def test_plan_node_malformed_json_uses_keyword_fallback():
    from orchestrator import _plan_node
    with patch("orchestrator.llm_chat", return_value=("not json at all", 0)):
        out = _plan_node({"user_input": "latest news on AAPL", "history": [], "persona_system": None})
    assert out["agents_to_run"] == ["news"]


def test_gates_node_drops_invalid_tickers():
    from orchestrator import _gates_node
    with patch("orchestrator.validate_tickers", return_value=([], ["FAKETICK"])), \
         patch("orchestrator.detect_group_in_query", return_value=None):
        out = _gates_node({"user_input": "analyze FAKETICK", "tickers": ["FAKETICK"],
                           "agents_to_run": ["financials"]})
    assert out["tickers"] == []
    assert out["agents_to_run"] == []   # all invalid → skip data agents


def test_agent_node_returns_result_blocks_and_tokens():
    from orchestrator import _agent_node
    with patch("orchestrator.run_financials",
               return_value=("## AAPL\nRevenue: $391,035M", 99, {"t": "raw"})):
        out = _agent_node({"agent_name": "financials", "agent_input": "AAPL revenue?",
                           "history": [], "tickers": ["AAPL"]})
    assert out["agent_results"] == {"financials": "## AAPL\nRevenue: $391,035M"}
    assert out["agent_tool_blocks"] == {"financials": {"t": "raw"}}
    assert out["tokens"] == {"agents": 99}


def test_agent_node_failure_contributes_nothing():
    from orchestrator import _agent_node
    with patch("orchestrator.run_financials", side_effect=RuntimeError("boom")):
        out = _agent_node({"agent_name": "financials", "agent_input": "x",
                           "history": [], "tickers": []})
    assert out["agent_results"] == {}
    assert out["agent_tool_blocks"] == {}


def test_collect_node_orders_context_with_neutral_labels():
    from orchestrator import _collect_node
    out = _collect_node({
        "agents_to_run": ["financials", "ratios"],
        "agent_results": {"ratios": "MARGIN DATA", "financials": "PRICE DATA"},
    })
    ctx = out["accumulated_context"]
    assert ctx.index("[MARKET DATA]") < ctx.index("[SEC RATIOS]")   # plan order kept
    assert "AGENT]" not in ctx


def test_fidelity_node_flags_hard_raws():
    from orchestrator import _fidelity_check_node
    state = {"answer": "AAPL fell 20.3% this week.",
             "agent_tool_blocks": {"financials": {"get_company_info({})": "Current Price: $290.55"}}}
    out = _fidelity_check_node(state)
    assert out["hard_raws"] == ["20.3%"]


def test_fidelity_node_clean_answer_no_hard():
    from orchestrator import _fidelity_check_node
    state = {"answer": "Revenue was 391,035M in FY2024.",
             "agent_tool_blocks": {"financials": {"t": "Total revenue: 391,035M  (Sep 28, 2024)"}}}
    out = _fidelity_check_node(state)
    assert out["hard_raws"] == []
