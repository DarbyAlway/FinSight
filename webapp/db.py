"""Chat persistence (Postgres). Chats and their messages, stored via the shared
psycopg pool from tools.pg. This is the primary app DB introduced in the web-ui
design; later plans add users/usage/portfolios alongside these tables.
"""
import uuid

from psycopg.rows import dict_row

from tools.pg import get_pool


def _require_pool():
    pool = get_pool()
    if pool is None:
        raise RuntimeError(
            "DATABASE_URL is not set — the web app requires Postgres. "
            "Set DATABASE_URL (e.g. postgresql://postgres:postgres@localhost:5432/finsight)."
        )
    return pool


def init_app_schema() -> None:
    """Create the chats/messages tables if absent. Idempotent; called at app
    startup. `updated_at` tracks last activity for sidebar ordering."""
    pool = _require_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id     UUID        PRIMARY KEY,
                title       TEXT        NOT NULL DEFAULT 'New chat',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_id  BIGSERIAL   PRIMARY KEY,
                chat_id     UUID        NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                role        TEXT        NOT NULL,
                content     TEXT        NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS messages_chat_id_idx ON messages(chat_id, message_id)"
        )
        conn.execute("ALTER TABLE chats ADD COLUMN IF NOT EXISTS user_id UUID")
        conn.execute("CREATE INDEX IF NOT EXISTS chats_user_id_idx ON chats(user_id)")


def create_chat(user_id: str, title: str = "New chat") -> str:
    pool = _require_pool()
    chat_id = str(uuid.uuid4())
    with pool.connection() as conn:
        conn.execute("INSERT INTO chats (chat_id, user_id, title) VALUES (%s, %s, %s)",
                     (chat_id, user_id, title))
    return chat_id


def list_chats(user_id: str) -> list[dict]:
    """The user's chats, most-recently-updated first (for the sidebar)."""
    pool = _require_pool()
    with pool.connection() as conn:
        rows = conn.cursor(row_factory=dict_row).execute(
            "SELECT chat_id, title, updated_at FROM chats WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [{"id": str(r["chat_id"]), "title": r["title"], "updated_at": r["updated_at"].isoformat()}
            for r in rows]


def get_messages(chat_id: str) -> list[dict]:
    pool = _require_pool()
    with pool.connection() as conn:
        rows = conn.cursor(row_factory=dict_row).execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE chat_id = %s ORDER BY message_id",
            (chat_id,),
        ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "created_at": r["created_at"].isoformat()}
        for r in rows
    ]


def get_chat(chat_id: str, user_id: str) -> dict | None:
    """A chat (owned by user_id) with its messages, or None if absent/not theirs."""
    pool = _require_pool()
    with pool.connection() as conn:
        row = conn.cursor(row_factory=dict_row).execute(
            "SELECT chat_id, title, created_at, updated_at FROM chats WHERE chat_id = %s AND user_id = %s",
            (chat_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": str(row["chat_id"]),
        "title": row["title"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "messages": get_messages(chat_id),
    }


def add_message(chat_id: str, role: str, content: str) -> None:
    """Append a message and bump the chat's updated_at (for sidebar ordering)."""
    pool = _require_pool()
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (%s, %s, %s)",
            (chat_id, role, content),
        )
        conn.execute("UPDATE chats SET updated_at = now() WHERE chat_id = %s", (chat_id,))


def delete_chat(chat_id: str, user_id: str) -> None:
    pool = _require_pool()
    with pool.connection() as conn:
        conn.execute("DELETE FROM chats WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
