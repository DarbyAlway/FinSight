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


# ---------------------------------------------------------------------------
# tools/ratios.py tests
# ---------------------------------------------------------------------------

def test_calculate_all_margins_from_cache():
    import time
    from tools.db import init_db, save_to_cache
    from tools.ratios import calculate_all_margins
    init_db()
    save_to_cache([
        {"ticker": "MARGINTEST", "fiscal_year": "Dec 31, 2025", "section": "Revenue",
         "line_item": "Net sales", "value": 1000.0, "fetched_at": time.time()},
        {"ticker": "MARGINTEST", "fiscal_year": "Dec 31, 2025", "section": "Gross",
         "line_item": "Gross profit", "value": 400.0, "fetched_at": time.time()},
        {"ticker": "MARGINTEST", "fiscal_year": "Dec 31, 2025", "section": "Net",
         "line_item": "Net income", "value": 100.0, "fetched_at": time.time()},
    ])
    result = calculate_all_margins("MARGINTEST")
    assert "40.0%" in result  # gross margin 400/1000
    assert "10.0%" in result  # net margin 100/1000


def test_calculate_debt_to_equity_from_cache():
    import time
    from tools.db import init_db, save_balance_sheet
    from tools.ratios import calculate_debt_to_equity
    init_db()
    save_balance_sheet([
        {"ticker": "DTETEST", "fiscal_year": "Dec 31, 2025", "section": "Liabilities",
         "line_item": "Long-term debt", "value": 150.0, "fetched_at": time.time()},
        {"ticker": "DTETEST", "fiscal_year": "Dec 31, 2025", "section": "Equity",
         "line_item": "Total stockholders equity", "value": 1700.0, "fetched_at": time.time()},
    ])
    result = calculate_debt_to_equity("DTETEST")
    assert "0.088" in result  # 150/1700 = 0.0882
    assert "Dec 31, 2025" in result


def test_calculate_roa_roe_from_cache():
    import time
    from tools.db import init_db, save_to_cache, save_balance_sheet
    from tools.ratios import calculate_roa_roe
    init_db()
    save_to_cache([
        {"ticker": "ROATEST", "fiscal_year": "Dec 31, 2025", "section": "Net",
         "line_item": "Net income", "value": 200.0, "fetched_at": time.time()},
    ])
    save_balance_sheet([
        {"ticker": "ROATEST", "fiscal_year": "Dec 31, 2025", "section": "Assets",
         "line_item": "Total assets", "value": 2000.0, "fetched_at": time.time()},
        {"ticker": "ROATEST", "fiscal_year": "Dec 31, 2025", "section": "Equity",
         "line_item": "Total stockholders equity", "value": 1000.0, "fetched_at": time.time()},
    ])
    result = calculate_roa_roe("ROATEST")
    assert "10.0%" in result   # ROA = 200/2000
    assert "20.0%" in result   # ROE = 200/1000


def test_calculate_debt_to_equity_missing_data():
    from tools.ratios import calculate_debt_to_equity
    result = calculate_debt_to_equity("ZZZNOTREAL_DTE")
    assert result.startswith("ERROR:")


# ---------------------------------------------------------------------------
# Cash flow DB tests
# ---------------------------------------------------------------------------

def test_init_db_creates_cash_flows_table():
    from tools.db import init_db
    from tools.config import DB_PATH
    init_db()
    import duckdb
    with duckdb.connect(DB_PATH) as con:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "cash_flows" in tables


def test_save_and_load_cash_flow_roundtrip():
    import time
    from tools.db import init_db, save_cash_flow, load_cash_flow
    init_db()
    rows = [
        {"ticker": "CFTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Operating Activities",
         "line_item": "Net cash provided by operating activities",
         "value": 200.0, "fetched_at": time.time()},
        {"ticker": "CFTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Investing Activities",
         "line_item": "Purchases of property, plant and equipment",
         "value": -50.0, "fetched_at": time.time()},
    ]
    save_cash_flow(rows)
    result = load_cash_flow("CFTEST")
    assert "Net cash provided by operating activities" in result
    assert "200" in result
    assert "Operating Activities" in result
    assert "Investing Activities" in result
    assert "Purchases of property, plant and equipment" in result
    assert "-50" in result


def test_is_cash_flow_fresh_returns_false_when_empty():
    from tools.db import init_db, is_cash_flow_fresh
    init_db()
    assert is_cash_flow_fresh("ZZZNOTREAL_CF") is False


# ---------------------------------------------------------------------------
# Cash flow parser tests
# ---------------------------------------------------------------------------

_SAMPLE_CF = (
    "                                               Sep 27, 2025  Sep 28, 2024\n"
    "   ────────────────────────────────────────────────────────\n"
    "    Cash flows from operating activities:\n"
    "          Net income                                 $100,000       $80,000\n"
    "          Depreciation and amortization               $20,000       $18,000\n"
    "          Net cash provided by operating activities  $120,000       $98,000\n"
    "    Cash flows from investing activities:\n"
    "          Purchases of property, plant and equipment  $(30,000)     $(25,000)\n"
    "          Net cash used in investing activities        $(30,000)     $(25,000)\n"
    "    Cash flows from financing activities:\n"
    "          Proceeds from long-term debt issuance        $50,000       $10,000\n"
    "          Net cash from financing activities           $50,000       $10,000\n"
    "   Source: SEC XBRL  •  (In thousands)\n"
)


def test_parse_cash_flow_extracts_rows():
    from tools.cash_flow import parse_cash_flow
    rows = parse_cash_flow("RKLB", _SAMPLE_CF)
    assert len(rows) > 0
    items = [r["line_item"] for r in rows]
    assert "Net income" in items
    assert any("operating activities" in i.lower() for i in items)


def test_parse_cash_flow_three_sections():
    from tools.cash_flow import parse_cash_flow
    rows = parse_cash_flow("RKLB", _SAMPLE_CF)
    sections = {r["section"] for r in rows}
    assert "Operating Activities" in sections
    assert "Investing Activities" in sections
    assert "Financing Activities" in sections


def test_parse_cash_flow_applies_thousands_multiplier():
    from tools.cash_flow import parse_cash_flow
    sample = (
        "                                   Sep 27, 2025\n"
        "    Cash flows from operating activities:\n"
        "          Net cash from operations  $120,000\n"
        "   Source: SEC XBRL  •  (In thousands)\n"
    )
    rows = parse_cash_flow("TEST", sample)
    assert len(rows) > 0
    # $120,000 thousands = $120M stored
    assert rows[0]["value"] == 120.0


# ---------------------------------------------------------------------------
# FCF and cash runway tests
# ---------------------------------------------------------------------------

def test_calculate_free_cash_flow_from_cache():
    import time
    from tools.db import init_db, save_cash_flow
    from tools.calc import calculate_free_cash_flow
    init_db()
    save_cash_flow([
        {"ticker": "FCFTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Operating Activities",
         "line_item": "Net cash provided by operating activities",
         "value": 200.0, "fetched_at": time.time()},
        {"ticker": "FCFTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Investing Activities",
         "line_item": "Purchases of property, plant and equipment",
         "value": -50.0, "fetched_at": time.time()},
        {"ticker": "FCFTEST", "fiscal_year": "Dec 31, 2024",
         "section": "Operating Activities",
         "line_item": "Net cash provided by operating activities",
         "value": 150.0, "fetched_at": time.time()},
        {"ticker": "FCFTEST", "fiscal_year": "Dec 31, 2024",
         "section": "Investing Activities",
         "line_item": "Purchases of property, plant and equipment",
         "value": -40.0, "fetched_at": time.time()},
    ])
    result = calculate_free_cash_flow("FCFTEST")
    # 2025 FCF = 200 + (-50) = 150, 2024 FCF = 150 + (-40) = 110
    assert "150" in result
    assert "Dec 31, 2025" in result


def test_calculate_cash_runway_from_cache():
    import time
    from tools.db import init_db, save_cash_flow, save_balance_sheet
    from tools.calc import calculate_cash_runway
    init_db()
    save_balance_sheet([
        {"ticker": "RUNWAY", "fiscal_year": "Dec 31, 2025",
         "section": "Assets",
         "line_item": "Cash and cash equivalents",
         "value": 600.0, "fetched_at": time.time()},
    ])
    save_cash_flow([
        {"ticker": "RUNWAY", "fiscal_year": "Dec 31, 2025",
         "section": "Operating Activities",
         "line_item": "Net cash used in operating activities",
         "value": -120.0, "fetched_at": time.time()},
        {"ticker": "RUNWAY", "fiscal_year": "Dec 31, 2025",
         "section": "Investing Activities",
         "line_item": "Purchases of property, plant and equipment",
         "value": -80.0, "fetched_at": time.time()},
    ])
    result = calculate_cash_runway("RUNWAY")
    # FCF = -120 + (-80) = -200 annual burn
    # Runway = 600 / 200 * 12 = 36 months
    assert "36" in result
    assert "600" in result


# ---------------------------------------------------------------------------
# Liquidity ratio tests
# ---------------------------------------------------------------------------

def test_calculate_current_ratio_from_cache():
    import time
    from tools.db import init_db, save_balance_sheet
    from tools.ratios import calculate_current_ratio
    init_db()
    save_balance_sheet([
        {"ticker": "CRTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Assets",
         "line_item": "Total current assets",
         "value": 300.0, "fetched_at": time.time()},
        {"ticker": "CRTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Liabilities",
         "line_item": "Total current liabilities",
         "value": 200.0, "fetched_at": time.time()},
    ])
    result = calculate_current_ratio("CRTEST")
    assert "1.50" in result  # 300 / 200 = 1.50
    assert "Dec 31, 2025" in result


def test_calculate_interest_coverage_from_cache():
    import time
    from tools.db import init_db, save_to_cache
    from tools.ratios import calculate_interest_coverage
    init_db()
    save_to_cache([
        {"ticker": "ICTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Operating",
         "line_item": "Operating income",
         "value": 300.0, "fetched_at": time.time()},
        {"ticker": "ICTEST", "fiscal_year": "Dec 31, 2025",
         "section": "Other",
         "line_item": "Interest expense",
         "value": -60.0, "fetched_at": time.time()},
    ])
    result = calculate_interest_coverage("ICTEST")
    assert "5.0x" in result  # 300 / 60 = 5.0x


# ---------------------------------------------------------------------------
# Date injection tests
# ---------------------------------------------------------------------------

def test_is_time_sensitive_detects_keywords():
    from orchestrator import _is_time_sensitive
    assert _is_time_sensitive("What is the latest news about RKLB?") is True
    assert _is_time_sensitive("What is RKLB's current cash burn?") is True
    assert _is_time_sensitive("What were Q3 earnings?") is True
    assert _is_time_sensitive("How much runway does RKLB have today?") is True


def test_is_time_sensitive_returns_false_for_neutral():
    from orchestrator import _is_time_sensitive
    assert _is_time_sensitive("What is the P/E ratio of AAPL?") is False
    assert _is_time_sensitive("Compare revenue of AAPL and MSFT") is False
    assert _is_time_sensitive("Calculate DCF for NVDA") is False


# ---------------------------------------------------------------------------
# get_company_info output tests
# ---------------------------------------------------------------------------

def test_get_company_info_includes_price_targets_and_multiples():
    import time
    from tools.db import init_db, save_ticker_info
    from tools.company import get_company_info
    init_db()
    save_ticker_info("PTTEST", {
        "longName": "Price Target Test Inc",
        "sector": "Technology",
        "industry": "Software",
        "longBusinessSummary": "A test company.",
        "marketCap": 1_000_000_000,
        "trailingPE": 25.0,
        "forwardPE": 20.0,
        "beta": 1.2,
        "currentPrice": 50.0,
        "recommendationKey": "buy",
        "numberOfAnalystOpinions": 10,
        "targetMeanPrice": 65.0,
        "targetHighPrice": 80.0,
        "targetLowPrice": 50.0,
        "priceToSalesTrailing12Months": 8.5,
        "priceToBook": 3.2,
        "_cached_at": time.time(),
    })
    result = get_company_info("PTTEST")
    assert "65.0" in result      # targetMeanPrice
    assert "80.0" in result      # targetHighPrice
    assert "8.5" in result       # P/S
    assert "3.2" in result       # P/B
    assert "Price Targets" in result
    assert "P/S" in result


# ---------------------------------------------------------------------------
# Earnings releases DB tests
# ---------------------------------------------------------------------------

def test_init_db_creates_earnings_releases_table():
    from tools.db import init_db
    from tools.config import DB_PATH
    init_db()
    import duckdb
    with duckdb.connect(DB_PATH) as con:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "earnings_releases" in tables


def test_save_and_load_earnings_roundtrip():
    import time
    from tools.db import init_db, save_earnings, load_earnings
    init_db()
    rows = [
        {
            "ticker": "EARNTEST",
            "period_end": "2024-09-30",
            "eps_actual": 1.64,
            "eps_estimate": 1.60,
            "revenue_actual": None,
            "revenue_estimate": None,
            "beat_miss": "beat",
            "guidance_text": "We expect revenue of $89-93B next quarter.",
            "fetched_at": time.time(),
        },
        {
            "ticker": "EARNTEST",
            "period_end": "2024-06-30",
            "eps_actual": 1.40,
            "eps_estimate": 1.45,
            "revenue_actual": None,
            "revenue_estimate": None,
            "beat_miss": "miss",
            "guidance_text": None,
            "fetched_at": time.time(),
        },
    ]
    save_earnings(rows)
    result = load_earnings("EARNTEST")
    assert "EARNTEST Earnings" in result
    assert "BEAT" in result
    assert "MISS" in result
    assert "We expect revenue" in result
    assert "(not available)" in result


def test_is_earnings_fresh_returns_false_when_empty():
    from tools.db import init_db, is_earnings_fresh
    init_db()
    assert is_earnings_fresh("ZZZNOTREAL_EARN") is False


def test_is_earnings_fresh_returns_true_after_save():
    import time
    from tools.db import init_db, save_earnings, is_earnings_fresh
    init_db()
    save_earnings([{
        "ticker": "FRESHTEST",
        "period_end": "2024-09-30",
        "eps_actual": 1.0,
        "eps_estimate": 1.0,
        "revenue_actual": None,
        "revenue_estimate": None,
        "beat_miss": "in-line",
        "guidance_text": None,
        "fetched_at": time.time(),
    }])
    assert is_earnings_fresh("FRESHTEST") is True


# ---------------------------------------------------------------------------
# earnings_press pure function tests
# ---------------------------------------------------------------------------

def test_parse_beat_miss_beat():
    from tools.earnings_press import _parse_beat_miss
    assert _parse_beat_miss(1.64, 1.60) == "beat"


def test_parse_beat_miss_miss():
    from tools.earnings_press import _parse_beat_miss
    assert _parse_beat_miss(1.50, 1.60) == "miss"


def test_parse_beat_miss_inline():
    from tools.earnings_press import _parse_beat_miss
    assert _parse_beat_miss(1.61, 1.60) == "in-line"  # +0.6% < 2% threshold


def test_parse_beat_miss_zero_estimate():
    from tools.earnings_press import _parse_beat_miss
    assert _parse_beat_miss(1.64, 0) == "in-line"


def test_extract_guidance_text_finds_guidance():
    from tools.earnings_press import _extract_guidance_text
    text = (
        "Revenue was $94B in Q3. "
        "We expect revenue in the range of $89-93 billion for Q4. "
        "Strong demand continues across all segments."
    )
    result = _extract_guidance_text(text)
    assert result is not None
    assert "expect" in result.lower()


def test_extract_guidance_text_finds_outlook():
    from tools.earnings_press import _extract_guidance_text
    text = (
        "Net income increased 12% year-over-year. "
        "Our outlook for fiscal 2025 remains positive with guidance of $6.50-6.80 EPS. "
        "We anticipate continued margin expansion."
    )
    result = _extract_guidance_text(text)
    assert result is not None
    assert len(result) > 0


def test_extract_guidance_text_returns_none_when_no_guidance():
    from tools.earnings_press import _extract_guidance_text
    text = "Revenue was $94B in Q3. Operating income increased 10%. Margins improved."
    result = _extract_guidance_text(text)
    assert result is None


# ---------------------------------------------------------------------------
# earnings_press fetcher tests (real API — requires internet)
# ---------------------------------------------------------------------------

def test_fetch_yfinance_earnings_returns_rows():
    from tools.earnings_press import _fetch_yfinance_earnings
    rows = _fetch_yfinance_earnings("AAPL")
    assert isinstance(rows, list)
    assert len(rows) > 0
    for r in rows:
        assert "ticker" in r and r["ticker"] == "AAPL"
        assert "period_end" in r
        assert "eps_actual" in r
        assert "eps_estimate" in r
        assert r["beat_miss"] in ("beat", "miss", "in-line")


def test_fetch_yfinance_earnings_period_end_is_iso_date():
    from tools.earnings_press import _fetch_yfinance_earnings
    rows = _fetch_yfinance_earnings("MSFT")
    assert len(rows) > 0
    for r in rows:
        # period_end must be parseable as YYYY-MM-DD
        parts = r["period_end"].split("-")
        assert len(parts) == 3 and len(parts[0]) == 4


def test_fetch_edgar_guidance_returns_string_or_none():
    from tools.earnings_press import _fetch_edgar_guidance
    result = _fetch_edgar_guidance("AAPL")
    # Must return a non-empty string or None — never raises
    assert result is None or (isinstance(result, str) and len(result) > 0)


# ---------------------------------------------------------------------------
# get_earnings_press_release integration tests
# ---------------------------------------------------------------------------

def test_get_earnings_press_release_returns_string():
    from tools.db import init_db
    from tools.earnings_press import get_earnings_press_release
    init_db()
    result = get_earnings_press_release("AAPL")
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_earnings_press_release_contains_beat_miss():
    from tools.db import init_db
    from tools.earnings_press import get_earnings_press_release
    init_db()
    result = get_earnings_press_release("AAPL")
    assert any(word in result.upper() for word in ["BEAT", "MISS", "IN-LINE"])


def test_get_earnings_press_release_cache_hit():
    import time
    from tools.db import init_db, save_earnings, is_earnings_fresh
    from tools.earnings_press import get_earnings_press_release
    init_db()
    save_earnings([{
        "ticker": "CACHEHIT",
        "period_end": "2024-09-30",
        "eps_actual": 2.00,
        "eps_estimate": 1.90,
        "revenue_actual": None,
        "revenue_estimate": None,
        "beat_miss": "beat",
        "guidance_text": "Strong guidance ahead.",
        "fetched_at": time.time(),
    }])
    assert is_earnings_fresh("CACHEHIT") is True
    result = get_earnings_press_release("CACHEHIT")
    assert "CACHEHIT" in result
    assert "BEAT" in result
    assert "Strong guidance ahead" in result


def test_get_earnings_press_release_edgar_failure_still_returns_eps():
    from unittest.mock import patch
    from tools.db import init_db
    from tools.earnings_press import get_earnings_press_release
    init_db()
    with patch("tools.earnings_press._fetch_edgar_guidance", return_value=None):
        result = get_earnings_press_release("MSFT")
    assert isinstance(result, str)
    assert any(word in result.upper() for word in ["BEAT", "MISS", "IN-LINE"])


# ---------------------------------------------------------------------------
# Financials agent — earnings tool wiring
# ---------------------------------------------------------------------------

def test_financials_agent_has_earnings_tool():
    from agents.financials import TOOLS
    names = [t["function"]["name"] for t in TOOLS]
    assert "get_earnings_press_release" in names


def test_financials_agent_earnings_tool_function_is_wired():
    from agents.financials import TOOL_FUNCTIONS
    assert "get_earnings_press_release" in TOOL_FUNCTIONS
    assert callable(TOOL_FUNCTIONS["get_earnings_press_release"])
