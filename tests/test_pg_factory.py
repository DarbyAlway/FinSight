"""make_checkpointer() must fall back to SqliteSaver when DATABASE_URL is unset,
so the offline test suite needs no database. The Postgres branch is covered by
tests/test_pg_checkpoint.py (which requires a real Postgres)."""
import os


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


def test_sqlite_path_defaults_to_persistent_repo_root_db(monkeypatch):
    """With no CHECKPOINT_DB, the SQLite fallback must default to the persistent
    repo-root checkpoints.db (NOT ':memory:') — preserving pre-migration
    crash-resume for local runs that don't set DATABASE_URL."""
    monkeypatch.delenv("CHECKPOINT_DB", raising=False)

    from tools.pg import sqlite_checkpoint_path

    path = sqlite_checkpoint_path()
    assert path != ":memory:"
    assert path.endswith("checkpoints.db")
    # lives at the repo root (parent of the tools/ package), not under tools/
    assert os.path.basename(os.path.dirname(path)) != "tools"


def test_sqlite_path_respects_checkpoint_db_override(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB", ":memory:")

    from tools.pg import sqlite_checkpoint_path

    assert sqlite_checkpoint_path() == ":memory:"
