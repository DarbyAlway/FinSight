from unittest.mock import patch

from langgraph.types import Send


def _send_names(routes):
    return sorted(s.arg["agent_name"] for s in routes)


def test_route_after_gates_dispatches_one_send_per_agent():
    from orchestrator import _route_after_gates
    state = {"agents_to_run": ["financials", "news"], "tickers": ["AAPL"],
             "user_input": "analyze AAPL", "history": []}
    routes = _route_after_gates(state)
    assert all(isinstance(s, Send) and s.node == "agent" for s in routes)
    assert _send_names(routes) == ["financials", "news"]
    # ticker hint must be prepended exactly as today
    assert routes[0].arg["agent_input"] == "[Use exactly these tickers: AAPL]\nanalyze AAPL"


def test_route_after_gates_no_agents_goes_to_collect():
    from orchestrator import _route_after_gates
    assert _route_after_gates({"agents_to_run": [], "tickers": [], "user_input": "hi", "history": []}) == "collect"


def test_route_after_collect_market_news_goes_proactive():
    from orchestrator import _route_after_collect
    assert _route_after_collect({"intent": "market_news"}) == "proactive_web"
    assert _route_after_collect({"intent": "specific_tickers"}) == "synthesize"


def test_route_after_synthesis_market_news_finalizes_directly():
    """Review fix in spec: market_news bypasses web_fallback AND fidelity."""
    from orchestrator import _route_after_synthesis
    state = {"intent": "market_news", "agents_to_run": ["news"], "agent_results": {"news": "data"},
             "agent_tool_blocks": {"news": {"t": "x"}}, "answer": "markets fell"}
    assert _route_after_synthesis(state) == "finalize"


def test_route_after_synthesis_empty_agents_data_goes_web_fallback():
    from orchestrator import _route_after_synthesis
    state = {"intent": "specific_tickers", "agents_to_run": ["financials"],
             "agent_results": {"financials": "ERROR: nothing"}, "agent_tool_blocks": {},
             "answer": "no data"}
    with patch("orchestrator.is_uncertain", return_value=False):
        assert _route_after_synthesis(state) == "web_fallback"


def test_route_after_synthesis_grounded_goes_fidelity():
    from orchestrator import _route_after_synthesis
    state = {"intent": "specific_tickers", "agents_to_run": ["financials"],
             "agent_results": {"financials": "## AAPL\nRevenue: $391,035M"},
             "agent_tool_blocks": {"financials": {"get_income_statement({})": "Revenue: 391,035M"}},
             "answer": "Revenue was $391,035M"}
    with patch("orchestrator.is_uncertain", return_value=False):
        assert _route_after_synthesis(state) == "fidelity_check"


def test_route_after_synthesis_no_tool_blocks_finalizes():
    from orchestrator import _route_after_synthesis
    state = {"intent": "specific_tickers", "agents_to_run": ["financials"],
             "agent_results": {"financials": "## AAPL\nreal data"}, "agent_tool_blocks": {},
             "answer": "answer"}
    with patch("orchestrator.is_uncertain", return_value=False):
        assert _route_after_synthesis(state) == "finalize"


def test_route_after_fidelity_hard_goes_critique():
    from orchestrator import _route_after_fidelity
    assert _route_after_fidelity({"hard_raws": ["20.3%"], "critique_done": False}) == "self_critique"
    assert _route_after_fidelity({"hard_raws": [], "critique_done": False}) == "finalize"


def test_route_after_critique_surviving_hard_escalates():
    from orchestrator import _route_after_critique
    assert _route_after_critique({"hard_raws": ["20.3%"], "critique_done": True}) == "web_escalate"
    assert _route_after_critique({"hard_raws": [], "critique_done": True}) == "finalize"
