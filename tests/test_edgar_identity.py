import webapp.app as appmod


def test_edgar_identity_defaults_to_placeholder(monkeypatch):
    monkeypatch.delenv("EDGAR_IDENTITY", raising=False)
    assert appmod._edgar_identity() == "yourname@email.com"


def test_edgar_identity_reads_env(monkeypatch):
    monkeypatch.setenv("EDGAR_IDENTITY", "Jane Doe jane@example.com")
    assert appmod._edgar_identity() == "Jane Doe jane@example.com"
