"""Chats are private per user. Postgres-gated."""
import os, importlib
import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="Set TEST_DATABASE_URL.")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    monkeypatch.setenv("WEBAPP_SKIP_WARMUP", "1")
    import tools.pg as pg; importlib.reload(pg)
    from webapp import db as appdb; importlib.reload(appdb)
    from webapp import accounts as acc; importlib.reload(acc)
    from webapp import auth as a; importlib.reload(a)
    appdb.init_app_schema(); acc.init_accounts_schema()
    with pg.get_pool().connection() as conn:
        conn.execute("TRUNCATE usage_ledger, sessions, messages, chats, users RESTART IDENTITY CASCADE")
    from fastapi.testclient import TestClient
    from webapp import app as appmod; importlib.reload(appmod)
    return TestClient(appmod.app)


def _auth(c, email):
    c.post("/auth/register", json={"email": email, "password": "pw12345"})


def test_user_cannot_see_others_chats(client):
    with client as c:
        _auth(c, "a@x.com")
        chat_id = c.post("/chats", json={"title": "A's chat"}).json()["id"]
        assert any(x["id"] == chat_id for x in c.get("/chats").json())
        c.post("/auth/logout")

        _auth(c, "b@x.com")
        assert c.get("/chats").json() == []                 # B sees nothing
        assert c.get(f"/chats/{chat_id}").status_code == 404 # B can't open A's chat
        assert c.delete(f"/chats/{chat_id}").status_code == 404


def test_chats_require_auth(client):
    with client as c:
        assert c.get("/chats").status_code == 401
