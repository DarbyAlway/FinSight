import tools.vector as vector


class _FakeClient:
    """Captures constructor args; stubs the two methods init_qdrant calls."""
    last = {}

    def __init__(self, host, port):
        _FakeClient.last = {"host": host, "port": port}

    def get_collections(self):
        class _R:
            collections = []
        return _R()

    def create_collection(self, **kwargs):
        pass


def test_init_qdrant_reads_host_and_port_from_env(monkeypatch):
    monkeypatch.setattr(vector, "QdrantClient", _FakeClient)
    monkeypatch.setenv("QDRANT_HOST", "qdrant")
    monkeypatch.setenv("QDRANT_PORT", "6333")
    vector.init_qdrant()
    assert _FakeClient.last == {"host": "qdrant", "port": 6333}


def test_init_qdrant_defaults_to_localhost(monkeypatch):
    monkeypatch.setattr(vector, "QdrantClient", _FakeClient)
    monkeypatch.delenv("QDRANT_HOST", raising=False)
    monkeypatch.delenv("QDRANT_PORT", raising=False)
    vector.init_qdrant()
    assert _FakeClient.last == {"host": "localhost", "port": 6333}
