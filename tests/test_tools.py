import time


def test_init_db_creates_table():
    from main import init_db, DB_PATH
    init_db()
    import duckdb
    con = duckdb.connect(DB_PATH)
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    con.close()
    assert "income_statements" in tables


def test_is_cache_fresh_returns_false_when_empty():
    from main import init_db, is_cache_fresh
    init_db()
    assert is_cache_fresh("ZZZNOTREAL") is False


def test_save_and_load_roundtrip():
    from main import init_db, save_to_cache, load_from_cache
    init_db()
    rows = [
        {"ticker": "TEST", "fiscal_year": "2025", "section": "Revenue",
         "line_item": "Total", "value": 100.0, "fetched_at": time.time()}
    ]
    save_to_cache(rows)
    result = load_from_cache("TEST")
    assert "Total" in result
    assert "100" in result


def test_parse_income_statement_extracts_rows():
    from main import parse_income_statement
    sample = (
        "                                               Sep 27, 2025  Sep 28, 2024\n"
        "Net sales:\n"
        "  Products                                        $307,003      $294,866\n"
        "  Services                                        $109,158       $96,169\n"
        "Gross margin                                      $195,201      $180,683\n"
    )
    rows = parse_income_statement("AAPL", sample)
    assert len(rows) > 0
    items = [r["line_item"] for r in rows]
    assert "Products" in items
    assert "Gross margin" in items


def test_parse_income_statement_negative_values():
    from main import parse_income_statement
    sample = (
        "                                               Sep 27, 2025\n"
        "Net sales:\n"
        "  Other income/(expense), net                       $(321)\n"
    )
    rows = parse_income_statement("AAPL", sample)
    other = [r for r in rows if "Other" in r["line_item"]]
    assert len(other) > 0
    assert other[0]["value"] == -321.0


def test_parse_income_statement_section_tracking():
    from main import parse_income_statement
    sample = (
        "                                               Sep 27, 2025\n"
        "Net sales:\n"
        "  Products                                        $307,003\n"
        "Cost of sales:\n"
        "  Products                                        $194,116\n"
    )
    rows = parse_income_statement("AAPL", sample)
    products_rows = [r for r in rows if r["line_item"] == "Products"]
    assert len(products_rows) == 2
    assert products_rows[0]["section"] != products_rows[1]["section"]


def test_get_income_statement_returns_string():
    from main import get_income_statement
    result = get_income_statement("AAPL")
    assert isinstance(result, str) and len(result) > 0


def test_fuzzy_query_finds_synonym():
    from main import init_db, save_to_cache, fuzzy_query
    init_db()
    save_to_cache([
        {"ticker": "FAKECO", "fiscal_year": "2025", "section": "Net sales",
         "line_item": "Net sales", "value": 500.0, "fetched_at": time.time()}
    ])
    result = fuzzy_query("FAKECO", "revenue")
    assert len(result) > 0 and result[0]["value"] == 500.0


def test_fuzzy_query_no_match_returns_empty():
    from main import init_db, save_to_cache, fuzzy_query
    init_db()
    save_to_cache([
        {"ticker": "FAKECO2", "fiscal_year": "2025", "section": "Revenue",
         "line_item": "Products", "value": 200.0, "fetched_at": time.time()}
    ])
    assert fuzzy_query("FAKECO2", "zzznomatch") == []


def test_init_qdrant_creates_collection():
    from main import init_qdrant, QDRANT_COLLECTION
    client = init_qdrant()
    names = [c.name for c in client.get_collections().collections]
    assert QDRANT_COLLECTION in names


def test_store_and_search_articles():
    from main import init_qdrant, store_articles, hybrid_search, QDRANT_COLLECTION
    client = init_qdrant()
    articles = [
        {"ticker": "AAPL", "title": "Apple reports record iPhone sales",
         "publisher": "Reuters", "link": "http://example.com/1", "source": "test"}
    ]
    store_articles(client, articles)
    results = hybrid_search(client, "iPhone sales record", ticker="AAPL", top_k=5)
    assert len(results) > 0
    assert any("Apple" in r["title"] for r in results)


def test_get_stock_news_returns_string():
    from main import get_stock_news
    result = get_stock_news("AAPL")
    assert isinstance(result, str) and len(result) > 0


def test_get_stock_news_respects_max_results():
    from main import get_stock_news
    result = get_stock_news("AAPL", max_results=3)
    lines = [l for l in result.split("\n") if l.strip().startswith("-")]
    assert len(lines) <= 6


def test_search_news_returns_string():
    from main import get_stock_news, search_news
    get_stock_news("AAPL", max_results=5)
    result = search_news("Apple revenue earnings", ticker="AAPL", top_k=3)
    assert isinstance(result, str) and len(result) > 0


def test_init_db_creates_ticker_info_table():
    from main import init_db, DB_PATH
    init_db()
    import duckdb
    with duckdb.connect(DB_PATH) as con:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "ticker_info" in tables


def test_save_and_load_ticker_info():
    from main import init_db, save_ticker_info, load_ticker_info
    init_db()
    save_ticker_info("AAPL", {"trailingPE": 36.2, "sector": "Technology", "longBusinessSummary": "Apple makes iPhones."})
    result = load_ticker_info("AAPL")
    assert result is not None
    assert result["sector"] == "Technology"


def test_ticker_info_cache_freshness():
    from main import init_db, save_ticker_info, is_ticker_info_fresh
    init_db()
    save_ticker_info("MSFT", {"trailingPE": 30.0, "sector": "Technology", "longBusinessSummary": "Microsoft makes Windows."})
    assert is_ticker_info_fresh("MSFT") is True
    assert is_ticker_info_fresh("ZZZNOTREAL2") is False


def test_company_profiles_collection_exists():
    from main import init_qdrant, COMPANY_PROFILES_COLLECTION
    client = init_qdrant()
    names = [c.name for c in client.get_collections().collections]
    assert COMPANY_PROFILES_COLLECTION in names


def test_upsert_and_search_company_profile():
    from main import init_qdrant, upsert_company_profile, search_company_profiles
    client = init_qdrant()
    upsert_company_profile(client, "AAPL", "Apple designs iPhones, Macs, and wearables.", "Technology", "Consumer Electronics")
    results = search_company_profiles(client, "company that makes smartphones and wearables", top_k=3)
    assert len(results) > 0
    assert any(r["symbol"] == "AAPL" for r in results)


# ---------------------------------------------------------------------------
# Balance sheet DB tests
# ---------------------------------------------------------------------------

def test_init_db_creates_balance_sheet_table():
    from main import init_db, DB_PATH
    init_db()
    import duckdb
    with duckdb.connect(DB_PATH) as con:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "balance_sheets" in tables


def test_save_and_load_balance_sheet_roundtrip():
    import time
    from tools.db import init_db, save_balance_sheet, load_balance_sheet
    init_db()
    rows = [
        {"ticker": "BSTEST", "fiscal_year": "Dec 31, 2025", "section": "Assets",
         "line_item": "Total assets", "value": 2324.0, "fetched_at": time.time()},
        {"ticker": "BSTEST", "fiscal_year": "Dec 31, 2025", "section": "Equity",
         "line_item": "Total stockholders equity", "value": 1721.0, "fetched_at": time.time()},
    ]
    save_balance_sheet(rows)
    result = load_balance_sheet("BSTEST")
    assert "Total assets" in result
    assert "2,324" in result


def test_is_balance_sheet_fresh_returns_false_when_empty():
    from tools.db import init_db, is_balance_sheet_fresh
    init_db()
    assert is_balance_sheet_fresh("ZZZNOTREAL_BS") is False


# ---------------------------------------------------------------------------
# Balance sheet parser tests
# ---------------------------------------------------------------------------

_SAMPLE_BS = (
    "                                               Dec 31, 2025   Dec 31, 2024\n"
    "   ────────────────────────────────────────────────────────\n"
    "    Assets\n"
    "      Current assets:\n"
    "            Cash and cash equivalents              $828,660       $271,042\n"
    "          Total current assets                   $1,365,544       $692,621\n"
    "        Total assets                             $2,324,478     $1,184,342\n"
    "          Total liabilities                        $602,624       $801,889\n"
    "      Stockholders' equity:\n"
    "          Total stockholders' equity:           $1,721,854       $382,453\n"
    "   Source: SEC XBRL  •  (In thousands, except shares and per share data)\n"
)


def test_parse_balance_sheet_extracts_rows():
    from tools.balance_sheet import parse_balance_sheet
    rows = parse_balance_sheet("RKLB", _SAMPLE_BS)
    assert len(rows) > 0
    items = [r["line_item"] for r in rows]
    assert "Total assets" in items
    assert any("equity" in i.lower() for i in items)


def test_parse_balance_sheet_two_fiscal_years():
    from tools.balance_sheet import parse_balance_sheet
    rows = parse_balance_sheet("RKLB", _SAMPLE_BS)
    fiscal_years = {r["fiscal_year"] for r in rows}
    assert "Dec 31, 2025" in fiscal_years
    assert "Dec 31, 2024" in fiscal_years


def test_parse_balance_sheet_applies_thousands_multiplier():
    from tools.balance_sheet import parse_balance_sheet
    sample = (
        "                         Dec 31, 2025\n"
        "   ───────────────────────────────\n"
        "        Total assets       $2,000,000\n"
        "   Source: SEC XBRL  •  (In thousands)\n"
    )
    rows = parse_balance_sheet("TEST", sample)
    asset_row = next(r for r in rows if r["line_item"] == "Total assets")
    assert asset_row["value"] == 2000.0
