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


def test_password_hash_roundtrip():
    from webapp import auth
    h = auth.hash_password("s3cret")
    assert h != "s3cret"
    assert auth.verify_password("s3cret", h) is True
    assert auth.verify_password("wrong", h) is False


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    monkeypatch.setenv("WEBAPP_SKIP_WARMUP", "1")
    monkeypatch.setenv("OWNER_EMAIL", "owner@x.com")
    import tools.pg as pg
    importlib.reload(pg)
    from webapp import db as appdb; importlib.reload(appdb)
    from webapp import accounts as acc; importlib.reload(acc)
    from webapp import auth as a; importlib.reload(a)
    appdb.init_app_schema(); acc.init_accounts_schema()
    with pg.get_pool().connection() as conn:
        conn.execute("TRUNCATE usage_ledger, sessions, messages, chats, users RESTART IDENTITY CASCADE")
    from fastapi.testclient import TestClient
    from webapp import app as appmod; importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        yield c


def test_register_login_me_logout(client):
    r = client.post("/auth/register", json={"email": "u@x.com", "password": "pw12345"})
    assert r.status_code == 200
    assert r.json()["email"] == "u@x.com"
    assert r.json()["is_owner"] is False

    r = client.get("/auth/me")
    assert r.status_code == 200 and r.json()["email"] == "u@x.com"

    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401

    r = client.post("/auth/login", json={"email": "u@x.com", "password": "pw12345"})
    assert r.status_code == 200
    assert client.get("/auth/me").status_code == 200


def test_owner_flag_from_env(client):
    r = client.post("/auth/register", json={"email": "owner@x.com", "password": "pw12345"})
    assert r.json()["is_owner"] is True


def test_duplicate_email_rejected(client):
    client.post("/auth/register", json={"email": "u@x.com", "password": "pw12345"})
    r = client.post("/auth/register", json={"email": "u@x.com", "password": "other123"})
    assert r.status_code == 409


def test_bad_login_rejected(client):
    client.post("/auth/register", json={"email": "u@x.com", "password": "pw12345"})
    assert client.post("/auth/login", json={"email": "u@x.com", "password": "nope"}).status_code == 401


from unittest.mock import patch as _patch


def _fake_stream(monkeypatch):
    """Patch the turn runner to emit one answer and report 1000 tokens via on_usage."""
    def fake_stream_turn(user_input, history, **kw):
        if kw.get("on_usage"):
            kw["on_usage"](1000)
        if kw.get("on_answer"):
            kw["on_answer"]("ok")
        yield "event: answer\ndata: {\"markdown\": \"ok\"}\n\n"
    return fake_stream_turn


def test_per_user_cap_blocks_non_owner(client, monkeypatch):
    client.post("/auth/register", json={"email": "u@x.com", "password": "pw12345"})
    chat_id = client.post("/chats", json={"title": "t"}).json()["id"]
    # Force the user over the cap.
    from webapp import accounts
    uid = accounts.get_user_by_email("u@x.com")["user_id"]
    accounts.add_user_tokens(uid, 200_000)
    r = client.post(f"/chats/{chat_id}/messages", json={"content": "hi"})
    assert r.status_code == 429


def test_owner_is_exempt(client, monkeypatch):
    client.post("/auth/register", json={"email": "owner@x.com", "password": "pw12345"})
    chat_id = client.post("/chats", json={"title": "t"}).json()["id"]
    from webapp import accounts
    uid = accounts.get_user_by_email("owner@x.com")["user_id"]
    accounts.add_user_tokens(uid, 500_000)  # way over, but owner exempt
    with _patch("webapp.app.stream_turn", side_effect=_fake_stream(monkeypatch)):
        with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "hi"}) as resp:
            assert resp.status_code == 200


def test_global_cap_blocks_everyone(client, monkeypatch):
    monkeypatch.setenv("GLOBAL_TOKEN_CAP", "100")
    client.post("/auth/register", json={"email": "u@x.com", "password": "pw12345"})
    chat_id = client.post("/chats", json={"title": "t"}).json()["id"]
    from webapp import accounts
    accounts.add_user_tokens(accounts.get_user_by_email("u@x.com")["user_id"], 200)  # over global 100
    r = client.post(f"/chats/{chat_id}/messages", json={"content": "hi"})
    assert r.status_code == 503


def test_usage_recorded_after_turn(client, monkeypatch):
    client.post("/auth/register", json={"email": "u@x.com", "password": "pw12345"})
    chat_id = client.post("/chats", json={"title": "t"}).json()["id"]
    with _patch("webapp.app.stream_turn", side_effect=_fake_stream(monkeypatch)):
        with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "hi"}) as resp:
            "".join(resp.iter_text())
    from webapp import accounts
    assert accounts.get_user_by_email("u@x.com")["tokens_used"] == 1000
