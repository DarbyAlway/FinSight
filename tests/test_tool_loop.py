"""Tests for the shared guarded tool-loop (Phase A — token-explosion safety)."""
import json
from unittest.mock import MagicMock

from agents._tooling import run_tool_loop


def _tool_call(name, args, cid="c1"):
    tc = MagicMock()
    tc.id = cid
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _resp(content=None, tool_calls=None, pt=10, ct=5):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = msg
    r = MagicMock()
    r.choices = [choice]
    r.usage.prompt_tokens = pt
    r.usage.completion_tokens = ct
    return r


def _client_with(responses):
    client = MagicMock()
    client.chat.completions.create.side_effect = responses
    return client


def test_returns_content_when_no_tools():
    client = _client_with([_resp(content="done")])
    out, tokens = run_tool_loop("T", client, "m", [], [], {}, temperature=0.0)
    assert out == "done"
    assert tokens == 15


def test_executes_tool_then_returns_final():
    fn = MagicMock(return_value="Revenue: $400B")
    responses = [
        _resp(content=None, tool_calls=[_tool_call("get_x", {"ticker": "AAPL"})]),
        _resp(content="AAPL revenue is $400B"),
    ]
    client = _client_with(responses)
    out, _ = run_tool_loop("T", client, "m", [], [], {"get_x": fn}, temperature=0.0)
    assert out == "AAPL revenue is $400B"
    fn.assert_called_once_with(ticker="AAPL")


def test_duplicate_call_is_served_from_cache():
    calls = {"n": 0}

    def fn(ticker):
        calls["n"] += 1
        return f"data for {ticker}"

    responses = [
        _resp(content=None, tool_calls=[_tool_call("get_x", {"ticker": "AAPL"})]),
        _resp(content=None, tool_calls=[_tool_call("get_x", {"ticker": "AAPL"})]),  # identical
        _resp(content="final"),
    ]
    client = _client_with(responses)
    out, _ = run_tool_loop("T", client, "m", [], [], {"get_x": fn}, temperature=0.0)
    assert out == "final"
    assert calls["n"] == 1  # second identical call never re-executed


def test_max_iterations_cap_stops_runaway_loop():
    # Model never stops requesting a tool — cap must brake it.
    def make(**_):
        return _resp(content="more", tool_calls=[_tool_call("get_x", {"ticker": "AAPL"})])

    client = MagicMock()
    client.chat.completions.create.side_effect = make
    out, _ = run_tool_loop(
        "T", client, "m", [], [], {"get_x": lambda ticker: "ok"},
        temperature=0.0, max_iterations=3,
    )
    # 1 initial + 3 loop rounds + 1 forced final answer
    assert client.chat.completions.create.call_count == 5
    assert isinstance(out, str)


def test_repeated_errors_break_before_cap():
    counter = {"i": 0}

    def make(**_):
        counter["i"] += 1
        return _resp(content="hmm", tool_calls=[_tool_call("get_x", {"ticker": f"T{counter['i']}"})])

    client = MagicMock()
    client.chat.completions.create.side_effect = make
    out, _ = run_tool_loop(
        "T", client, "m", [], [], {"get_x": lambda ticker: "ERROR: no data"},
        temperature=0.0, max_iterations=8,
    )
    # 3 consecutive error results trip no-progress: 1 init + 3 loop + 1 forced final
    assert client.chat.completions.create.call_count == 4
    assert isinstance(out, str)


def test_token_budget_breaks_loop():
    def make(**_):
        return _resp(content="x", tool_calls=[_tool_call("get_x", {"ticker": "AAPL"})], pt=20000, ct=20000)

    client = MagicMock()
    client.chat.completions.create.side_effect = make
    out, tokens = run_tool_loop(
        "T", client, "m", [], [], {"get_x": lambda ticker: "ok"},
        temperature=0.0, token_budget=30000, max_iterations=99,
    )
    # first call already blows the 30k budget → break next iteration: 1 init + 1 forced final
    assert client.chat.completions.create.call_count == 2
    assert tokens >= 40000


def test_logs_per_call_latency_and_tokens(caplog):
    """I1: each agent LLM round logs its own latency + token counts, so a slow
    agent's time is visible instead of hidden inside the loop."""
    import logging as _logging
    client = _client_with([_resp(content="done", pt=12, ct=7)])
    with caplog.at_level(_logging.INFO):
        run_tool_loop("RatiosAgent", client, "m", [], [], {}, temperature=0.0)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("llm call" in m and "prompt=12" in m and "completion=7" in m for m in msgs)
    assert any("ms" in m for m in msgs if "llm call" in m)


def test_self_critique_requests_missing_tickers():
    responses = [
        _resp(content="## AAPL\nRevenue $400B"),         # initial answer (no tools)
        _resp(content="## MSFT\nRevenue $210B"),          # self-critique completion
    ]
    client = _client_with(responses)
    out, _ = run_tool_loop(
        "T", client, "m", [], [], {}, temperature=0.0,
        expected_tickers=["AAPL", "MSFT"],
    )
    assert "AAPL" in out and "MSFT" in out
