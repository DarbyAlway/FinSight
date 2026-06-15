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


import os

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg_required = pytest.mark.skipif(not TEST_DB, reason="Set TEST_DATABASE_URL (postgres) for API tests.")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    monkeypatch.setenv("WEBAPP_SKIP_WARMUP", "1")
    import importlib

    import tools.pg as pg
    importlib.reload(pg)
    from webapp import db as appdb
    importlib.reload(appdb)
    from webapp import accounts as acc
    importlib.reload(acc)
    from webapp import auth as a
    importlib.reload(a)
    appdb.init_app_schema()
    acc.init_accounts_schema()
    with pg.get_pool().connection() as conn:
        conn.execute("TRUNCATE usage_ledger, sessions, messages, chats, users RESTART IDENTITY CASCADE")

    from fastapi.testclient import TestClient
    from webapp import app as appmod
    importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        c.post("/auth/register", json={"email": "t@x.com", "password": "pw12345"})
        yield c


@pg_required
def test_create_list_get_delete_chat(client):
    r = client.post("/chats", json={"title": "Apple"})
    assert r.status_code == 200
    chat_id = r.json()["id"]

    r = client.get("/chats")
    assert r.status_code == 200
    assert any(c["id"] == chat_id for c in r.json())

    r = client.get(f"/chats/{chat_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == chat_id
    assert body["messages"] == []

    r = client.delete(f"/chats/{chat_id}")
    assert r.status_code == 200
    r = client.get(f"/chats/{chat_id}")
    assert r.status_code == 404


@pg_required
def test_get_missing_chat_is_404(client):
    r = client.get("/chats/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


import json as _json
from unittest.mock import patch as _patch


@pg_required
def test_post_message_streams_stages_then_answer_and_persists(client, monkeypatch):
    r = client.post("/chats", json={"title": "t"})
    chat_id = r.json()["id"]

    def fake_process_turn(user_input, history, persona_system=None, on_stage=None):
        on_stage("planning", "")
        on_stage("fetching", "AAPL: financials")
        on_stage("writing", "")
        ans = "Revenue was 391,035M in FY2024."
        return (ans, history + [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": ans},
        ])

    with _patch("webapp.turn_runner.process_turn", side_effect=fake_process_turn):
        with client.stream("POST", f"/chats/{chat_id}/messages",
                           json={"content": "AAPL revenue?"}) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())

    assert "event: stage" in body
    assert "event: answer" in body
    assert "391,035M" in body

    chat = client.get(f"/chats/{chat_id}").json()
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][0]["content"] == "AAPL revenue?"


@pg_required
def test_post_message_to_missing_chat_is_404(client):
    r = client.post("/chats/00000000-0000-0000-0000-000000000000/messages",
                    json={"content": "hi"})
    assert r.status_code == 404
