import importlib

import tools.config as cfg


def test_db_path_defaults_to_cache_db(monkeypatch):
    monkeypatch.delenv("CACHE_DB_PATH", raising=False)
    importlib.reload(cfg)
    assert cfg.DB_PATH == "cache.db"


def test_db_path_honors_env_override(monkeypatch):
    monkeypatch.setenv("CACHE_DB_PATH", "/data/cache.db")
    importlib.reload(cfg)
    assert cfg.DB_PATH == "/data/cache.db"
    # restore module to default so other tests see the original constant
    monkeypatch.delenv("CACHE_DB_PATH", raising=False)
    importlib.reload(cfg)
