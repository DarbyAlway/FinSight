from unittest.mock import patch

from tools import resolve


def test_is_valid_ticker_uses_sec_set():
    with patch.object(resolve, "_SEC_TICKERS", {"AAPL", "MSFT", "NVDA"}), \
         patch.object(resolve, "_loaded", True):
        assert resolve.is_valid_ticker("AAPL") is True
        assert resolve.is_valid_ticker("aapl") is True          # case-insensitive
        assert resolve.is_valid_ticker("ZZZZ") is False


def test_resolve_entities_keeps_verbatim_ticker():
    """A symbol the user literally typed, valid in the SEC set, is kept as-is."""
    with patch.object(resolve, "is_valid_ticker", side_effect=lambda s: s.upper() == "NVDA"), \
         patch.object(resolve, "resolve_name") as mock_name:
        resolved, unresolved = resolve.resolve_entities(["NVDA"], "analyze NVDA")
    assert resolved == ["NVDA"]
    assert unresolved == []
    mock_name.assert_not_called()           # never re-resolve a verbatim valid ticker


def test_resolve_entities_resolves_name_not_in_query_as_company():
    """LLM-emitted ticker NOT in the user's text is discarded; the name is resolved.
    The classic FB-vs-Meta case: user said 'Meta', so 'FB' is untrusted."""
    with patch.object(resolve, "is_valid_ticker", return_value=True), \
         patch.object(resolve, "resolve_name", side_effect=lambda n: {"Meta": "META"}.get(n)):
        resolved, unresolved = resolve.resolve_entities(["Meta"], "analyze Meta")
    assert resolved == ["META"]
    assert unresolved == []


def test_resolve_entities_collects_unresolved():
    with patch.object(resolve, "is_valid_ticker", return_value=False), \
         patch.object(resolve, "resolve_name", return_value=None):
        resolved, unresolved = resolve.resolve_entities(["Glorbcorp"], "analyze Glorbcorp")
    assert resolved == []
    assert unresolved == ["Glorbcorp"]


def test_resolve_entities_dedupes_preserving_order():
    with patch.object(resolve, "is_valid_ticker", side_effect=lambda s: s.upper() in {"AAPL", "MSFT"}), \
         patch.object(resolve, "resolve_name", return_value=None):
        resolved, _ = resolve.resolve_entities(["AAPL", "MSFT", "AAPL"], "compare AAPL MSFT AAPL")
    assert resolved == ["AAPL", "MSFT"]


def test_resolve_name_returns_first_equity_symbol():
    """resolve_name takes the first EQUITY hit from yfinance Search, skipping ETFs."""
    class FakeSearch:
        def __init__(self, *a, **k):
            self.quotes = [
                {"symbol": "FB3.L", "quoteType": "ETF", "shortname": "Leverage FB"},
                {"symbol": "META", "quoteType": "EQUITY", "shortname": "Meta Platforms, Inc."},
            ]
    with patch("yfinance.Search", FakeSearch):
        assert resolve.resolve_name("Facebook") == "META"


def test_resolve_name_returns_none_on_no_equity():
    class FakeSearch:
        def __init__(self, *a, **k):
            self.quotes = [{"symbol": "XYZ.L", "quoteType": "ETF"}]
    with patch("yfinance.Search", FakeSearch):
        assert resolve.resolve_name("nothing real") is None


def test_resolve_name_handles_search_exception():
    def boom(*a, **k):
        raise RuntimeError("network down")
    with patch("yfinance.Search", boom):
        assert resolve.resolve_name("Apple") is None


def test_validate_tickers_partitions_by_sec_set():
    with patch.object(resolve, "_SEC_TICKERS", {"AAPL", "MSFT"}), \
         patch.object(resolve, "_loaded", True):
        valid, invalid = resolve.validate_tickers(["AAPL", "TWTR", "MSFT"])
    assert valid == ["AAPL", "MSFT"]
    assert invalid == ["TWTR"]


def test_validate_tickers_fails_open_when_sec_list_unavailable():
    """If the SEC list couldn't load, treat all tickers as valid — never drop
    everything just because the reference data is missing."""
    with patch.object(resolve, "_SEC_TICKERS", set()), \
         patch.object(resolve, "_loaded", True):
        valid, invalid = resolve.validate_tickers(["AAPL", "TWTR"])
    assert valid == ["AAPL", "TWTR"]
    assert invalid == []
