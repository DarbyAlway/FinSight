"""Crash/resume on a REAL Postgres-backed PostgresSaver — the proof that the
checkpoint migration preserves resume semantics. Mirrors the SQLite tests in
tests/test_graph_checkpoint.py.

Requires a Postgres instance. Quick start:
  docker run -d --name finsight-pg -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=finsight -p 5432:5432 postgres:16
  set TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/finsight
"""
import json
import os
from unittest.mock import patch

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB,
    reason=(
        "Set TEST_DATABASE_URL to run Postgres checkpoint tests. Quick start: "
        "docker run -d --name finsight-pg -e POSTGRES_PASSWORD=postgres "
        "-e POSTGRES_DB=finsight -p 5432:5432 postgres:16 ; "
        "TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/finsight"
    ),
)


def _plan(agents, tickers):
    return (json.dumps({"intent": "specific_tickers", "agents": agents, "tickers": tickers}), 0)


def _fake_financials(calls):
    def _fn(*a, **k):
        calls["n"] += 1
        return ("## AAPL\nRevenue: 391,035M  (Sep 28, 2024)", 10,
                {"get_income_statement({})": "Total revenue: 391,035M  (Sep 28, 2024)"})
    return _fn


@pytest.fixture
def pg_saver():
    """A PostgresSaver on TEST_DATABASE_URL, checkpoint tables created and
    truncated for isolation. Pool is closed after the test."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        conninfo=TEST_DB, max_size=5, open=True,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    saver = PostgresSaver(pool)
    saver.setup()
    with pool.connection() as conn:
        conn.execute("TRUNCATE checkpoints, checkpoint_blobs, checkpoint_writes")
    try:
        yield saver
    finally:
        pool.close()


def test_crashed_turn_resumes_on_postgres(pg_saver):
    """Kill the turn at synthesis; resume on the same thread_id against Postgres;
    the agent node must NOT run again (its output came from the checkpoint)."""
    from orchestrator import build_graph

    graph = build_graph(checkpointer=pg_saver)
    config = {"configurable": {"thread_id": "pg-turn-1"}}
    initial = {
        "user_input": "AAPL revenue?", "history": [], "persona_system": None,
        "agent_results": {}, "agent_tool_blocks": {}, "accumulated_context": "",
        "answer": "", "web_used": False, "web_urls": [], "hard_raws": [],
        "critique_done": False, "tokens": {},
    }
    calls = {"n": 0}
    fake = _fake_financials(calls)

    with patch("orchestrator.llm_chat",
               side_effect=[_plan(["financials"], ["AAPL"]), RuntimeError("boom")]), \
         patch("orchestrator.run_financials", side_effect=fake), \
         patch("orchestrator.validate_tickers", return_value=(["AAPL"], [])), \
         patch("orchestrator.detect_group_in_query", return_value=None):
        try:
            graph.invoke(initial, config)
        except RuntimeError:
            pass
    assert calls["n"] == 1

    with patch("orchestrator.llm_chat",
               side_effect=[("Revenue was 391,035M in FY2024.", 5)]), \
         patch("orchestrator.run_financials", side_effect=fake), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])):
        final = graph.invoke(None, config)

    assert calls["n"] == 1            # agent NOT refetched from Postgres checkpoint
    assert "391,035M" in final["answer"]


def test_process_turn_resumes_on_postgres(pg_saver, monkeypatch):
    """Resume THROUGH process_turn against a Postgres-backed module graph."""
    import orchestrator

    monkeypatch.setattr(orchestrator, "_GRAPH", build := orchestrator.build_graph(checkpointer=pg_saver))
    assert build is orchestrator._GRAPH  # sanity: the patched graph is in place

    calls = {"n": 0}
    fake = _fake_financials(calls)

    with patch("orchestrator.llm_chat",
               side_effect=[_plan(["financials"], ["AAPL"]), RuntimeError("boom")]), \
         patch("orchestrator.run_financials", side_effect=fake), \
         patch("orchestrator.validate_tickers", return_value=(["AAPL"], [])), \
         patch("orchestrator.detect_group_in_query", return_value=None):
        with pytest.raises(RuntimeError):
            orchestrator.process_turn("AAPL revenue?", [], thread_id="pg-resume-1")
    assert calls["n"] == 1

    with patch("orchestrator.llm_chat",
               side_effect=[("Revenue was 391,035M in FY2024.", 5)]), \
         patch("orchestrator.run_financials", side_effect=fake), \
         patch("orchestrator.is_uncertain", return_value=False), \
         patch("orchestrator._web_search_with_sources", return_value=("", [])):
        answer, _ = orchestrator.process_turn("AAPL revenue?", [], thread_id="pg-resume-1")

    assert calls["n"] == 1
    assert "391,035M" in answer
