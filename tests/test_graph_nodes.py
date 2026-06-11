# tests/test_graph_nodes.py
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch


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
    assert "mismatch_count" in out
    assert out["mismatch_count"] >= 1


def test_fidelity_node_clean_answer_no_hard():
    from orchestrator import _fidelity_check_node
    state = {"answer": "Revenue was 391,035M in FY2024.",
             "agent_tool_blocks": {"financials": {"t": "Total revenue: 391,035M  (Sep 28, 2024)"}}}
    out = _fidelity_check_node(state)
    assert out["hard_raws"] == []
    assert out["mismatch_count"] == 0


def test_fidelity_node_no_tool_blocks_returns_zeros():
    from orchestrator import _fidelity_check_node
    out = _fidelity_check_node({"answer": "some answer", "agent_tool_blocks": {}})
    assert out["hard_raws"] == []
    assert out["mismatch_count"] == 0


# ---------------------------------------------------------------------------
# _synthesize_node
# ---------------------------------------------------------------------------

def test_synthesize_node_returns_answer_messages_and_tokens():
    from orchestrator import _synthesize_node
    state = {
        "synth_sys": "You are a helpful assistant.",
        "history": [],
        "user_input": "What is AAPL revenue?",
        "accumulated_context": "[MARKET DATA]\nRevenue: $391B",
    }
    with patch("orchestrator._synthesis_step", return_value=("answer text", 42)):
        out = _synthesize_node(state)
    assert out["answer"] == "answer text"
    assert out["tokens"] == {"synthesis": 42}
    assert "synthesis_messages" in out
    assert isinstance(out["synthesis_messages"], list)
    assert len(out["synthesis_messages"]) >= 2


def test_synthesize_node_no_context_uses_plain_user_message():
    from orchestrator import _synthesize_node
    state = {
        "synth_sys": "You are a helpful assistant.",
        "history": [],
        "user_input": "Hello",
        "accumulated_context": "",
    }
    with patch("orchestrator._synthesis_step", return_value=("hi there", 5)):
        out = _synthesize_node(state)
    assert out["answer"] == "hi there"
    # last message should be the plain user_input (no "Agent outputs:" wrapper)
    last_msg = out["synthesis_messages"][-1]
    assert last_msg["role"] == "user"
    assert last_msg["content"] == "Hello"


# ---------------------------------------------------------------------------
# _proactive_web_node
# ---------------------------------------------------------------------------

def test_proactive_web_node_with_snippets_appends_context():
    from orchestrator import _proactive_web_node
    state = {
        "user_input": "market news today",
        "time_sensitive": True,
        "accumulated_context": "[NEWS]\nSome existing context",
    }
    with patch("orchestrator._web_search_with_sources",
               return_value=("snippet text", ["http://example.com"])):
        out = _proactive_web_node(state)
    assert out["web_urls"] == ["http://example.com"]
    assert "[WEB SEARCH RESULTS]" in out["accumulated_context"]
    assert "snippet text" in out["accumulated_context"]
    # existing context should be preserved
    assert "[NEWS]" in out["accumulated_context"]


def test_proactive_web_node_empty_results_only_sets_urls():
    from orchestrator import _proactive_web_node
    state = {
        "user_input": "market news today",
        "time_sensitive": True,
        "accumulated_context": "[NEWS]\nExisting",
    }
    with patch("orchestrator._web_search_with_sources", return_value=("", [])):
        out = _proactive_web_node(state)
    assert out["web_urls"] == []
    # no accumulated_context key when search returns nothing
    assert "accumulated_context" not in out


# ---------------------------------------------------------------------------
# _web_fallback_node
# ---------------------------------------------------------------------------

def test_web_fallback_node_returns_answer_with_sources():
    from orchestrator import _web_fallback_node
    state = {
        "user_input": "AAPL revenue?",
        "time_sensitive": False,
        "synth_sys": "sys",
        "history": [],
        "answer": "old answer",
    }
    with patch("orchestrator._web_search_with_sources",
               return_value=("web snippet", ["http://source1.com"])), \
         patch("orchestrator._synthesis_step", return_value=("web answer", 10)):
        out = _web_fallback_node(state)
    assert out["web_used"] is True
    assert out["tokens"] == {"synthesis": 10}
    assert "**Web sources:**" in out["answer"]
    assert "http://source1.com" in out["answer"]
    assert "web answer" in out["answer"]


def test_web_fallback_node_no_snippets_returns_empty_dict():
    from orchestrator import _web_fallback_node
    state = {
        "user_input": "AAPL revenue?",
        "time_sensitive": False,
        "synth_sys": "sys",
        "history": [],
        "answer": "old answer",
    }
    with patch("orchestrator._web_search_with_sources", return_value=("", [])):
        out = _web_fallback_node(state)
    assert out == {}


def test_web_fallback_node_synthesis_empty_uses_existing_answer():
    from orchestrator import _web_fallback_node
    # When synthesis returns empty string, node uses state["answer"] as fallback
    state = {
        "user_input": "AAPL revenue?",
        "time_sensitive": False,
        "synth_sys": "sys",
        "history": [],
        "answer": "old answer",
    }
    with patch("orchestrator._web_search_with_sources",
               return_value=("snippet", ["http://url.com"])), \
         patch("orchestrator._synthesis_step", return_value=("", 3)):
        out = _web_fallback_node(state)
    assert out["web_used"] is True
    assert "old answer" in out["answer"]


# ---------------------------------------------------------------------------
# _self_critique_node
# ---------------------------------------------------------------------------

def _make_mismatch(raw: str, hard: bool = True):
    """Build a minimal mismatch object matching the fields the node accesses."""
    num = SimpleNamespace(raw=raw, kind="percentage")
    return SimpleNamespace(number=num, hard=hard, year=None)


def test_self_critique_node_corrected_clean():
    from orchestrator import _self_critique_node
    state = {
        "answer": "AAPL fell 20.3% this week.",
        "hard_raws": ["20.3%"],
        "mismatch_count": 1,
        "synthesis_messages": [{"role": "system", "content": "sys"}],
        "agent_tool_blocks": {"financials": {"t": "Revenue: $391B"}},
        "user_input": "AAPL?",
    }
    with patch("orchestrator._synthesis_step", return_value=("clean answer", 5)), \
         patch("orchestrator.verify_fidelity", return_value=[]):
        out = _self_critique_node(state)
    assert out["answer"] == "clean answer"
    assert out["hard_raws"] == []
    assert out["mismatch_count"] == 0
    assert out["critique_done"] is True
    assert out["tokens"] == {"synthesis": 5}


def test_self_critique_node_empty_response_preserves_state(caplog):
    from orchestrator import _self_critique_node
    state = {
        "answer": "original answer",
        "hard_raws": ["20.3%"],
        "mismatch_count": 3,
        "synthesis_messages": [{"role": "system", "content": "sys"}],
        "agent_tool_blocks": {"financials": {"t": "Revenue: $391B"}},
        "user_input": "AAPL?",
    }
    with patch("orchestrator._synthesis_step", return_value=("", 3)), \
         patch("orchestrator._score_fidelity"), \
         caplog.at_level(logging.INFO, logger="root"):
        out = _self_critique_node(state)
    # answer and hard_raws unchanged
    assert out["answer"] == "original answer"
    assert out["hard_raws"] == ["20.3%"]
    # mismatch_count carries the ORIGINAL count from state
    assert out["mismatch_count"] == 3
    assert out["critique_done"] is True
    assert out["tokens"] == {"synthesis": 3}
    # regression: the "checked answer" log must fire with the original count
    assert any("checked answer: 3" in r.message for r in caplog.records)


def test_self_critique_node_corrected_with_surviving_hard_raws():
    from orchestrator import _self_critique_node
    surviving = [_make_mismatch("15%", hard=True)]
    state = {
        "answer": "AAPL fell 20.3% this week.",
        "hard_raws": ["20.3%"],
        "mismatch_count": 1,
        "synthesis_messages": [{"role": "system", "content": "sys"}],
        "agent_tool_blocks": {"financials": {"t": "Revenue: $391B"}},
        "user_input": "AAPL?",
    }
    with patch("orchestrator._synthesis_step", return_value=("revised answer with 15%", 7)), \
         patch("orchestrator.verify_fidelity", return_value=surviving):
        out = _self_critique_node(state)
    assert out["answer"] == "revised answer with 15%"
    assert out["hard_raws"] == ["15%"]
    assert out["mismatch_count"] == 1
    assert out["critique_done"] is True


# ---------------------------------------------------------------------------
# _web_escalate_node
# ---------------------------------------------------------------------------

def test_web_escalate_node_snippets_and_answer():
    from orchestrator import _web_escalate_node
    state = {
        "hard_raws": ["20.3%"],
        "user_input": "AAPL?",
        "time_sensitive": False,
        "synth_sys": "sys",
        "history": [],
        "answer": "original answer",
    }
    with patch("orchestrator._web_search_with_sources",
               return_value=("web snippet", ["http://src.com"])), \
         patch("orchestrator._synthesis_step", return_value=("web-grounded answer", 8)):
        out = _web_escalate_node(state)
    assert out["answer"].startswith("web-grounded answer")
    assert "**Web sources:**" in out["answer"]
    assert "http://src.com" in out["answer"]
    assert out["web_used"] is True
    assert out["tokens"] == {"synthesis": 8}


def test_web_escalate_node_snippets_but_synthesis_empty():
    from orchestrator import _web_escalate_node
    state = {
        "hard_raws": ["20.3%"],
        "user_input": "AAPL?",
        "time_sensitive": False,
        "synth_sys": "sys",
        "history": [],
        "answer": "original answer",
    }
    with patch("orchestrator._web_search_with_sources",
               return_value=("web snippet", ["http://src.com"])), \
         patch("orchestrator._synthesis_step", return_value=("", 4)):
        out = _web_escalate_node(state)
    # answer key must NOT be present (node returns only tokens)
    assert "answer" not in out
    assert out["tokens"] == {"synthesis": 4}


def test_web_escalate_node_no_snippets_adds_caveat():
    from orchestrator import _web_escalate_node
    state = {
        "hard_raws": ["20.3%"],
        "user_input": "AAPL?",
        "time_sensitive": False,
        "synth_sys": "sys",
        "history": [],
        "answer": "original answer",
    }
    with patch("orchestrator._web_search_with_sources", return_value=("", [])):
        out = _web_escalate_node(state)
    assert "**Data caveat:**" in out["answer"]
    assert "20.3%" in out["answer"]
    assert out["answer"].startswith("original answer")


# ---------------------------------------------------------------------------
# _finalize_node
# ---------------------------------------------------------------------------

def test_finalize_node_market_news_with_urls_appends_sources():
    from orchestrator import _finalize_node
    state = {
        "answer": "Here is the news.",
        "intent": "market_news",
        "web_urls": ["http://news1.com", "http://news2.com"],
    }
    out = _finalize_node(state)
    assert "**Web sources:**" in out["answer"]
    assert "http://news1.com" in out["answer"]
    assert "http://news2.com" in out["answer"]


def test_finalize_node_other_intent_passes_through_unchanged():
    from orchestrator import _finalize_node
    state = {
        "answer": "Revenue is $391B.",
        "intent": "specific_tickers",
        "web_urls": ["http://src.com"],
    }
    out = _finalize_node(state)
    assert out["answer"] == "Revenue is $391B."


def test_finalize_node_no_urls_passes_through():
    from orchestrator import _finalize_node
    state = {
        "answer": "Some market news.",
        "intent": "market_news",
        "web_urls": [],
    }
    out = _finalize_node(state)
    assert out["answer"] == "Some market news."


def test_finalize_node_missing_answer_returns_empty_string():
    from orchestrator import _finalize_node
    out = _finalize_node({})
    assert out["answer"] == ""
