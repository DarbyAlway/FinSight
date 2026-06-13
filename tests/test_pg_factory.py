"""make_checkpointer() must fall back to SqliteSaver when DATABASE_URL is unset,
so the offline test suite needs no database. The Postgres branch is covered by
tests/test_pg_checkpoint.py (which requires a real Postgres)."""


def test_make_checkpointer_falls_back_to_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CHECKPOINT_DB", ":memory:")

    from langgraph.checkpoint.sqlite import SqliteSaver
    from tools.pg import make_checkpointer

    saver = make_checkpointer()
    assert isinstance(saver, SqliteSaver)


def test_get_pool_is_none_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import importlib

    import tools.pg as pg
    importlib.reload(pg)  # reset the module-level _POOL cache
    assert pg.get_pool() is None
