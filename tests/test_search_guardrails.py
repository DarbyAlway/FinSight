from tools.search_guardrails import agents_returned_nothing


def test_empty_results_is_nothing():
    assert agents_returned_nothing({}) is True


def test_all_error_outputs_is_nothing():
    results = {
        "financials": "## LITE\nERROR: No company info for LITE",
        "calc": "TOOL_ERROR: No quarterly data could be parsed for LITE.",
    }
    assert agents_returned_nothing(results) is True


def test_no_data_phrases_is_nothing():
    results = {"ratios": "No revenue data for AAPL — call get_income_statement first."}
    assert agents_returned_nothing(results) is True


def test_one_real_output_is_not_nothing():
    results = {"financials": "## AAPL\nRevenue: $391,035M\nNet income: $93,736M"}
    assert agents_returned_nothing(results) is False


def test_mixed_real_and_error_is_not_nothing():
    results = {
        "financials": "## AAPL\nRevenue: $391,035M",
        "ratios": "ERROR: No balance sheet data for AAPL",
    }
    assert agents_returned_nothing(results) is False


def test_header_only_error_is_nothing():
    # Markdown header lines must not count as real content.
    results = {"financials": "## AAPL\nERROR: No revenue data"}
    assert agents_returned_nothing(results) is True
