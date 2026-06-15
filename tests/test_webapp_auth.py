"""Auth/quota DAO + endpoints. Postgres-gated like tests/test_webapp_db.py."""
import os
import importlib
import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="Set TEST_DATABASE_URL for auth tests.")


@pytest.fixture
def accounts(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    import tools.pg as pg
    importlib.reload(pg)
    from webapp import db as appdb
    importlib.reload(appdb)
    from webapp import accounts as acc
    importlib.reload(acc)
    appdb.init_app_schema()
    acc.init_accounts_schema()
    with pg.get_pool().connection() as conn:
        conn.execute("TRUNCATE usage_ledger, sessions, messages, chats, users RESTART IDENTITY CASCADE")
    return acc


def test_create_and_fetch_user(accounts):
    uid = accounts.create_user("a@x.com", "hash123", is_owner=False)
    u = accounts.get_user_by_email("a@x.com")
    assert u["user_id"] == uid
    assert u["password_hash"] == "hash123"
    assert u["is_owner"] is False
    assert u["tokens_used"] == 0


def test_token_accounting_and_global_total(accounts):
    uid = accounts.create_user("b@x.com", "h", is_owner=False)
    accounts.add_user_tokens(uid, 1500)
    accounts.add_user_tokens(uid, 500)
    assert accounts.get_user_by_id(uid)["tokens_used"] == 2000
    assert accounts.global_tokens_used() == 2000


def test_session_lifecycle(accounts):
    uid = accounts.create_user("c@x.com", "h", is_owner=False)
    token = accounts.create_session(uid, ttl_days=30)
    assert accounts.user_for_session(token)["user_id"] == uid
    accounts.delete_session(token)
    assert accounts.user_for_session(token) is None


def test_record_usage_row(accounts):
    uid = accounts.create_user("d@x.com", "h", is_owner=False)
    accounts.record_usage(uid, tokens=1234, ip="1.2.3.4", user_agent="UA")
    with __import__("tools.pg", fromlist=["pg"]).get_pool().connection() as conn:
        n = conn.execute("SELECT count(*) FROM usage_ledger WHERE user_id=%s", (uid,)).fetchone()[0]
    assert n == 1
