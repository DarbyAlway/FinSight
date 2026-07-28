"""Postgres-backed chat persistence DAO. Requires TEST_DATABASE_URL (skips
without it). Quick start:
  docker run -d --name finsight-pg -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=finsight -p 5432:5432 postgres:16
  TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/finsight
"""
import os

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DB,
    reason="Set TEST_DATABASE_URL (postgres) to run webapp DB tests.",
)

# Chats are scoped per user (user_id is a plain UUID column, no FK), so these
# DAO tests use one fixed owner id.
USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def db(monkeypatch):
    """Point tools.pg at TEST_DATABASE_URL, init the app schema, and start each
    test from empty chats/messages tables."""
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    import importlib

    import tools.pg as pg
    importlib.reload(pg)  # reset cached _POOL so it picks up TEST_DATABASE_URL

    from webapp import db as appdb
    importlib.reload(appdb)
    appdb.init_app_schema()
    with pg.get_pool().connection() as conn:
        conn.execute("TRUNCATE messages, chats RESTART IDENTITY CASCADE")
    yield appdb


def test_create_and_get_chat(db):
    chat_id = db.create_chat(USER, title="Apple deep-dive")
    assert isinstance(chat_id, str) and chat_id
    chat = db.get_chat(chat_id, USER)
    assert chat["id"] == chat_id
    assert chat["title"] == "Apple deep-dive"
    assert chat["messages"] == []


def test_list_chats_newest_first(db):
    a = db.create_chat(USER, title="first")
    b = db.create_chat(USER, title="second")
    rows = db.list_chats(USER)
    ids = [r["id"] for r in rows]
    assert ids.index(b) < ids.index(a)  # most-recently-updated first
    assert {"id", "title", "updated_at"} <= set(rows[0].keys())


def test_add_and_get_messages_in_order(db):
    chat_id = db.create_chat(USER, title="t")
    db.add_message(chat_id, role="user", content="AAPL revenue?")
    db.add_message(chat_id, role="assistant", content="It was 391,035M in FY2024.")
    msgs = db.get_messages(chat_id)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"].endswith("FY2024.")


def test_get_chat_includes_messages(db):
    chat_id = db.create_chat(USER, title="t")
    db.add_message(chat_id, role="user", content="hi")
    chat = db.get_chat(chat_id, USER)
    assert len(chat["messages"]) == 1
    assert chat["messages"][0]["content"] == "hi"


def test_delete_chat_removes_it_and_messages(db):
    chat_id = db.create_chat(USER, title="t")
    db.add_message(chat_id, role="user", content="hi")
    db.delete_chat(chat_id, USER)
    assert db.get_chat(chat_id, USER) is None
    assert db.get_messages(chat_id) == []


def test_get_missing_chat_returns_none(db):
    assert db.get_chat("00000000-0000-0000-0000-000000000000", USER) is None


def test_update_chat_title_changes_title(db):
    chat_id = db.create_chat(USER, title="New chat")
    db.update_chat_title(chat_id, "AAPL Q4 Revenue")
    chat = db.get_chat(chat_id, USER)
    assert chat["title"] == "AAPL Q4 Revenue"
