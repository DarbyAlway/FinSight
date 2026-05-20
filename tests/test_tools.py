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
    assert is_cache_fresh("AAPL") is False


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
