"""PostgreSQL connection foundation.

Owns a process-wide psycopg connection pool (lazily created) and the
checkpointer factory used by orchestrator. Production sets DATABASE_URL and
gets a PostgresSaver over the shared pool; with no DATABASE_URL the factory
falls back to the in-memory SqliteSaver so the offline test suite needs no
database. Later plans (chats/messages/users tables) reuse get_pool().
"""
import os
import sqlite3

_POOL = None  # process-wide psycopg_pool.ConnectionPool, created on first use


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def get_pool():
    """Return the shared psycopg connection pool, or None when DATABASE_URL is
    unset (offline/test fallback). PostgresSaver requires autocommit and
    prepare_threshold=0 on its connections, so those are set pool-wide."""
    global _POOL
    url = database_url()
    if not url:
        return None
    if _POOL is None:
        from psycopg_pool import ConnectionPool
        _POOL = ConnectionPool(
            conninfo=url,
            max_size=20,
            open=True,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
    return _POOL


def make_checkpointer():
    """Production: PostgresSaver over the shared pool (DATABASE_URL set), with
    its tables created via setup(). Offline/tests: SqliteSaver on CHECKPOINT_DB
    (default ':memory:'), preserving the previous behavior."""
    pool = get_pool()
    if pool is not None:
        from langgraph.checkpoint.postgres import PostgresSaver
        saver = PostgresSaver(pool)
        saver.setup()  # idempotent: CREATE TABLE IF NOT EXISTS for checkpoint tables
        return saver

    from langgraph.checkpoint.sqlite import SqliteSaver
    ckpt = os.environ.get("CHECKPOINT_DB", ":memory:")
    return SqliteSaver(sqlite3.connect(ckpt, check_same_thread=False))
