"""Webapp turn-runner + API tests. The runner test is offline (process_turn is
patched). The API tests (added in later tasks) are Postgres-gated."""
import json
from unittest.mock import patch


def _collect(gen):
    """Parse an SSE string generator into a list of (event, data-dict)."""
    events = []
    for chunk in gen:
        lines = [ln for ln in chunk.strip().splitlines() if ln]
        ev = next(ln[len("event:"):].strip() for ln in lines if ln.startswith("event:"))
        data = next(ln[len("data:"):].strip() for ln in lines if ln.startswith("data:"))
        events.append((ev, json.loads(data)))
    return events


def test_stream_turn_emits_stages_then_answer():
    from webapp.turn_runner import stream_turn

    def fake_process_turn(user_input, history, persona_system=None, on_stage=None):
        on_stage("planning", "")
        on_stage("fetching", "AAPL: financials")
        on_stage("writing", "")
        return ("Revenue was 391,035M in FY2024.", history + [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": "Revenue was 391,035M in FY2024."},
        ])

    with patch("webapp.turn_runner.process_turn", side_effect=fake_process_turn):
        events = _collect(stream_turn(user_input="AAPL revenue?", history=[]))

    kinds = [e for e, _ in events]
    assert kinds[:3] == ["stage", "stage", "stage"]
    assert kinds[-1] == "answer"
    assert events[0][1]["stage"] == "planning"
    assert events[1][1]["detail"] == "AAPL: financials"
    assert "391,035M" in events[-1][1]["markdown"]


def test_stream_turn_emits_error_on_exception():
    from webapp.turn_runner import stream_turn

    def boom(*a, **k):
        raise RuntimeError("EDGAR timed out")

    with patch("webapp.turn_runner.process_turn", side_effect=boom):
        events = _collect(stream_turn(user_input="x", history=[]))

    assert events[-1][0] == "error"
    assert "EDGAR timed out" in events[-1][1]["message"]
