"""Users, sessions, and usage accounting (Postgres). Companion to webapp/db.py
(chats). Sessions are opaque random tokens stored server-side and delivered as an
HTTP-only cookie; usage_ledger holds per-turn rows + soft abuse signals."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row

from tools.pg import get_pool


def _require_pool():
    pool = get_pool()
    if pool is None:
        raise RuntimeError("DATABASE_URL is not set — the web app requires Postgres.")
    return pool


def init_accounts_schema() -> None:
    """Create users/sessions/usage_ledger tables if absent. Idempotent."""
    pool = _require_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       UUID        PRIMARY KEY,
                email         TEXT        NOT NULL UNIQUE,
                password_hash TEXT        NOT NULL,
                is_owner      BOOLEAN     NOT NULL DEFAULT FALSE,
                tokens_used   BIGINT      NOT NULL DEFAULT 0,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT        PRIMARY KEY,
                user_id    UUID        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_ledger (
                id         BIGSERIAL   PRIMARY KEY,
                user_id    UUID        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                tokens     INTEGER     NOT NULL,
                ip         TEXT,
                user_agent TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def create_user(email: str, password_hash: str, is_owner: bool = False) -> str:
    pool = _require_pool()
    uid = str(uuid.uuid4())
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, email, password_hash, is_owner) VALUES (%s, %s, %s, %s)",
            (uid, email.lower(), password_hash, is_owner),
        )
    return uid


def _get_user(where: str, val) -> dict | None:
    pool = _require_pool()
    with pool.connection() as conn:
        row = conn.cursor(row_factory=dict_row).execute(
            f"SELECT user_id, email, password_hash, is_owner, tokens_used FROM users WHERE {where} = %s",
            (val,),
        ).fetchone()
    if row is None:
        return None
    return {**row, "user_id": str(row["user_id"])}


def get_user_by_email(email: str) -> dict | None:
    return _get_user("email", email.lower())


def get_user_by_id(user_id: str) -> dict | None:
    return _get_user("user_id", user_id)


def add_user_tokens(user_id: str, tokens: int) -> None:
    pool = _require_pool()
    with pool.connection() as conn:
        conn.execute("UPDATE users SET tokens_used = tokens_used + %s WHERE user_id = %s",
                     (tokens, user_id))


def global_tokens_used() -> int:
    pool = _require_pool()
    with pool.connection() as conn:
        return conn.execute("SELECT COALESCE(SUM(tokens_used), 0) FROM users").fetchone()[0]


def create_session(user_id: str, ttl_days: int = 30) -> str:
    pool = _require_pool()
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, expires_at) VALUES (%s, %s, %s)",
            (token, user_id, expires),
        )
    return token


def user_for_session(token: str | None) -> dict | None:
    """The user for a non-expired session token, else None."""
    if not token:
        return None
    pool = _require_pool()
    with pool.connection() as conn:
        row = conn.cursor(row_factory=dict_row).execute(
            "SELECT user_id FROM sessions WHERE session_id = %s AND expires_at > now()",
            (token,),
        ).fetchone()
    if row is None:
        return None
    return get_user_by_id(str(row["user_id"]))


def delete_session(token: str) -> None:
    pool = _require_pool()
    with pool.connection() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = %s", (token,))


def record_usage(user_id: str, tokens: int, ip: str | None, user_agent: str | None) -> None:
    pool = _require_pool()
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO usage_ledger (user_id, tokens, ip, user_agent) VALUES (%s, %s, %s, %s)",
            (user_id, tokens, ip, user_agent),
        )
