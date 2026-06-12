# tests/test_graph_checkpoint.py
import contextlib
import json
import sqlite3
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver


def _plan(agents, tickers):
    return (json.dumps({"intent": "specific_tickers", "agents": agents, "tickers": tickers}), 0)


def test_crashed_turn_resumes_without_refetching_agents(tmp_path):
    """Kill the turn at synthesis; resume on the same thread_id; the agent node
    must NOT run again (its output came from the checkpoint)."""
    from orchestrator import build_graph

    conn = sqlite3.connect(tmp_path / "ckpt.db", check_same_thread=False)
    with contextlib.closing(conn):
        saver = SqliteSaver(conn)
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": "turn-1"}}
        initial = {
            "user_input": "AAPL revenue?", "history": [], "persona_system": None,
            "agent_results": {}, "agent_tool_blocks": {}, "accumulated_context": "",
            "answer": "", "web_used": False, "web_urls": [], "hard_raws": [],
            "critique_done": False, "tokens": {},
        }
        agent_calls = {"n": 0}

        def fake_financials(*a, **k):
            agent_calls["n"] += 1
            return ("## AAPL\nRevenue: 391,035M  (Sep 28, 2024)", 10,
                    {"get_income_statement({})": "Total revenue: 391,035M  (Sep 28, 2024)"})

        # First run: synthesis LLM call explodes AFTER the agent ran.
        with patch("orchestrator.llm_chat",
                   side_effect=[_plan(["financials"], ["AAPL"]), RuntimeError("boom")]), \
             patch("orchestrator.run_financials", side_effect=fake_financials), \
             patch("orchestrator.validate_tickers", return_value=(["AAPL"], [])), \
             patch("orchestrator.detect_group_in_query", return_value=None):
            try:
                graph.invoke(initial, config)
            except RuntimeError:
                pass
        assert agent_calls["n"] == 1

        # Resume: invoke(None) continues from the checkpoint — plan + agent must
        # NOT re-run; only the failed synthesis (and downstream) executes.
        with patch("orchestrator.llm_chat",
                   side_effect=[("Revenue was 391,035M in FY2024.", 5)]), \
             patch("orchestrator.run_financials", side_effect=fake_financials), \
             patch("orchestrator.is_uncertain", return_value=False), \
             patch("orchestrator._web_search_with_sources", return_value=("", [])):
            final = graph.invoke(None, config)

        assert agent_calls["n"] == 1            # agent NOT refetched
        assert "391,035M" in final["answer"]
