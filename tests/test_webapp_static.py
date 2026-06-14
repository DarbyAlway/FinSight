"""mount_frontend() serves the built SPA only when the build dir exists. Offline:
no DB needed (uses a bare FastAPI app + a temp dir)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webapp.app import mount_frontend


def test_mount_frontend_serves_index_when_dir_exists(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>finsight ui</body></html>", encoding="utf-8")
    app = FastAPI()
    mount_frontend(app, str(tmp_path))
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "finsight ui" in r.text


def test_mount_frontend_noop_when_dir_absent(tmp_path):
    app = FastAPI()
    mount_frontend(app, str(tmp_path / "does-not-exist"))
    assert all(getattr(route, "path", None) != "/" for route in app.routes)
