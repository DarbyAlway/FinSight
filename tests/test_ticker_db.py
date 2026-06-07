"""Tests for tools/ticker_db.py — the authoritative SEC + NASDAQ ticker lookup.

Pure logic (normalize / parse / dedup) is unit-tested with the REAL NASDAQ file
format; the build + lookup round-trip is tested end-to-end against REAL SEC +
NASDAQ downloads (network-gated).
"""

import pytest

from tools import ticker_db


# --- normalization (pure) ------------------------------------------------

def test_normalize_name_strips_corporate_suffixes():
    assert ticker_db._normalize_name("NVIDIA CORP") == "nvidia"
    assert ticker_db._normalize_name("Alphabet Inc.") == "alphabet"
    assert ticker_db._normalize_name("Microsoft Corporation") == "microsoft"


def test_normalize_name_drops_security_type_descriptor():
    # NASDAQ security names carry a "- Common Stock" descriptor.
    assert ticker_db._normalize_name("Apple Inc. - Common Stock") == "apple"


def test_normalize_name_drops_leading_the():
    assert ticker_db._normalize_name("The Coca-Cola Company") == "coca cola"


# --- NASDAQ Trader parsing (real file format) ----------------------------

def test_parse_nasdaq_listed_extracts_symbol_name_etf():
    # Real nasdaqlisted.txt format (pipe-delimited, trailing footer line).
    text = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
        "QQQ|Invesco QQQ Trust, Series 1|Q|N|N|100|Y|N\n"
        "File Creation Time: 0102202512:00|||||||\n"
    )
    by = {r["symbol"]: r for r in ticker_db._parse_nasdaq(text)}
    assert by["AAPL"]["name"] == "Apple Inc. - Common Stock"
    assert by["AAPL"]["is_etf"] is False
    assert by["QQQ"]["is_etf"] is True
    assert "File Creation Time" not in str(by.keys())  # footer skipped


def test_parse_nasdaq_skips_test_issues():
    text = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "ZZZT|NASDAQ TEST STOCK|Q|Y|N|100|N|N\n"
    )
    assert ticker_db._parse_nasdaq(text) == []


def test_parse_other_listed_uses_act_symbol_column():
    # Real otherlisted.txt format (NYSE/AMEX; "ACT Symbol" column).
    text = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
        "File Creation Time: 0102202512:00||||||\n"
    )
    rows = ticker_db._parse_nasdaq(text)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["is_etf"] is True


# --- dedup (pure) --------------------------------------------------------

def test_dedup_merges_on_symbol_and_ors_etf_flag():
    rows = [
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "source": "nasdaq", "is_etf": True},
        {"symbol": "SPY", "name": "SPDR S&P 500", "source": "sec", "is_etf": False},
    ]
    deduped = ticker_db._dedup(rows)
    assert len(deduped) == 1
    assert deduped[0]["is_etf"] is True  # ETF flag survives if either source sets it


# --- build + lookup round-trip (real data, network-gated) ----------------

@pytest.fixture(scope="module")
def real_table():
    try:
        n = ticker_db.download_and_build()
    except Exception as e:
        pytest.skip(f"SEC/NASDAQ download unavailable: {e}")
    assert n > 5000, f"expected thousands of tickers, got {n}"
    return n


def test_real_build_resolves_common_names(real_table):
    assert ticker_db.lookup_exact("microsoft") == "MSFT"
    assert ticker_db.lookup_exact("nvidia") == "NVDA"
    assert ticker_db.lookup_exact("apple") == "AAPL"


def test_real_build_validates_symbols(real_table):
    assert ticker_db.is_valid_symbol("AAPL") is True
    assert ticker_db.is_valid_symbol("aapl") is True  # case-insensitive
    assert ticker_db.is_valid_symbol("ZZZZNOTREAL") is False


def test_real_build_marks_etfs(real_table):
    # SPY is an ETF (from NASDAQ otherlisted), AAPL is not.
    assert ticker_db.is_etf("SPY") is True
    assert ticker_db.is_etf("AAPL") is False


def test_real_build_all_entries_for_fuzzy(real_table):
    entries = dict(ticker_db.all_entries())
    assert entries.get("microsoft") == "MSFT"
    assert len(entries) > 5000
