from tools.groups import check_local_manifest, detect_group_in_query


def test_mag7_returns_seven_canonical_tickers():
    tickers = check_local_manifest("MAG7")
    assert tickers is not None
    assert len(tickers) == 7
    # The exact bug this gate fixes: META and NVDA present, FB and BABA absent.
    assert "META" in tickers
    assert "NVDA" in tickers
    assert "FB" not in tickers
    assert "BABA" not in tickers
    assert set(tickers) == {"AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"}


def test_faang_returns_five_canonical_tickers():
    tickers = check_local_manifest("FAANG")
    assert tickers is not None
    assert set(tickers) == {"META", "AAPL", "AMZN", "NFLX", "GOOGL"}


def test_lookup_is_case_insensitive():
    assert check_local_manifest("mag7") == check_local_manifest("MAG7")
    assert check_local_manifest("faang") == check_local_manifest("FAANG")


def test_spelled_out_and_spaced_aliases_resolve():
    mag7 = check_local_manifest("MAG7")
    assert check_local_manifest("Magnificent Seven") == mag7
    assert check_local_manifest("mag 7") == mag7
    assert check_local_manifest("magnificent 7") == mag7


def test_unknown_group_returns_none():
    assert check_local_manifest("the top 5 AI penny stocks") is None
    assert check_local_manifest("BABA") is None
    assert check_local_manifest("") is None


def test_returned_list_is_a_copy_not_the_internal_manifest():
    first = check_local_manifest("MAG7")
    first.append("ZZZZ")
    second = check_local_manifest("MAG7")
    assert "ZZZZ" not in second


# --- detect_group_in_query: find a group mention inside a free-text query ---

def test_detects_mag7_in_natural_query():
    assert detect_group_in_query("analyze MAG7 for me") == check_local_manifest("MAG7")
    assert detect_group_in_query("which MAG7 is best to invest") == check_local_manifest("MAG7")


def test_detects_spelled_out_group_in_query():
    assert detect_group_in_query("compare the magnificent seven") == check_local_manifest("MAG7")


def test_detects_faang_in_query():
    assert detect_group_in_query("show me FAANG stocks") == check_local_manifest("FAANG")


def test_no_group_mention_returns_none():
    assert detect_group_in_query("analyze AAPL and MSFT") is None
    assert detect_group_in_query("what is the weather today") is None
    assert detect_group_in_query("") is None
