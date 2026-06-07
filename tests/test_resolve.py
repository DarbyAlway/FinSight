from unittest.mock import patch

import pytest

from tools import resolve, ticker_db
from tools.db import connect


# --- legacy Gate-2 validators (still used by the live orchestrator) --------

def test_is_valid_ticker_uses_sec_set():
    with patch.object(resolve, "_SEC_TICKERS", {"AAPL", "MSFT", "NVDA"}), \
         patch.object(resolve, "_loaded", True):
        assert resolve.is_valid_ticker("AAPL") is True
        assert resolve.is_valid_ticker("aapl") is True          # case-insensitive
        assert resolve.is_valid_ticker("ZZZZ") is False


def test_validate_tickers_partitions_by_sec_set():
    with patch.object(resolve, "_SEC_TICKERS", {"AAPL", "MSFT"}), \
         patch.object(resolve, "_loaded", True):
        valid, invalid = resolve.validate_tickers(["AAPL", "TWTR", "MSFT"])
    assert valid == ["AAPL", "MSFT"]
    assert invalid == ["TWTR"]


def test_validate_tickers_fails_open_when_sec_list_unavailable():
    with patch.object(resolve, "_SEC_TICKERS", set()), \
         patch.object(resolve, "_loaded", True):
        valid, invalid = resolve.validate_tickers(["AAPL", "TWTR"])
    assert valid == ["AAPL", "TWTR"]
    assert invalid == []


# --- resolution ladder (real ticker_db, network-gated build) --------------

@pytest.fixture(scope="module", autouse=True)
def _real_ticker_table():
    try:
        with connect() as con:
            n = con.execute("SELECT count(*) FROM ticker_lookup").fetchone()[0]
    except Exception:
        n = 0
    if n < 5000:
        try:
            ticker_db.download_and_build()
        except Exception as e:
            pytest.skip(f"ticker table unavailable: {e}")
    resolve.clear_cache()


def test_resolve_company_exact_match():
    assert resolve.resolve_company("Microsoft").symbol == "MSFT"
    assert resolve.resolve_company("nvidia").symbol == "NVDA"
    assert resolve.resolve_company("Apple Inc.").symbol == "AAPL"


def test_resolve_company_alias_common_names():
    assert resolve.resolve_company("Google").symbol == "GOOGL"
    assert resolve.resolve_company("Facebook").symbol == "META"


def test_resolve_company_fuzzy_fixes_typo():
    r = resolve.resolve_company("microsft")
    assert r.status == resolve.RESOLVED
    assert r.symbol == "MSFT"


def test_square_never_resolves_to_wrong_company():
    # The Square -> VSQTF trap: alias resolves it to XYZ, and it must never be
    # the wrong-entity Victory Square Technologies symbol.
    r = resolve.resolve_company("Square")
    assert r.symbol == "XYZ"
    assert r.symbol != "VSQTF"


def test_resolve_company_unresolved_for_nonsense():
    r = resolve.resolve_company("Glorbcorp Zzyzx Holdings")
    assert r.status == resolve.UNRESOLVED
    assert r.symbol is None


def test_resolve_query_trusts_verbatim_ticker():
    # GLiNER often misses raw tickers, so the verbatim rule must catch NVDA.
    tickers, _ = resolve.resolve_query("PEG of NVDA", names=[])
    assert "NVDA" in tickers


def test_resolve_query_ignores_finance_abbreviation_as_ticker():
    # 'PEG' is PSEG's ticker but here means the ratio — must NOT resolve PSEG.
    tickers, _ = resolve.resolve_query("what is the PEG of Tesla", names=["Tesla"])
    assert tickers == ["TSLA"]
    assert "PEG" not in tickers and "PSEG" not in tickers


def test_resolve_query_dedupes_and_resolves_names():
    tickers, pending = resolve.resolve_query(
        "compare Microsoft and Nvidia and Microsoft again",
        names=["Microsoft", "Nvidia", "Microsoft"],
    )
    assert tickers == ["MSFT", "NVDA"]
    assert pending == []


def test_resolve_query_semantic_tier_when_nothing_resolves(monkeypatch):
    monkeypatch.setattr(resolve, "_semantic_lookup", lambda q, floor=resolve.SEMANTIC_FLOOR: "AAPL")
    tickers, _ = resolve.resolve_query("analyze the iPhone maker", names=[])
    assert tickers == ["AAPL"]


def test_resolve_query_skips_semantic_when_a_name_resolves(monkeypatch):
    calls = []
    monkeypatch.setattr(resolve, "_semantic_lookup",
                        lambda q, floor=resolve.SEMANTIC_FLOOR: calls.append(q) or "WRONG")
    tickers, _ = resolve.resolve_query("Microsoft earnings", names=["Microsoft"])
    assert tickers == ["MSFT"]
    assert calls == []  # semantic tier not consulted when a name already resolved
