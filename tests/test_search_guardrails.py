from unittest.mock import MagicMock, patch

from tools.search_guardrails import agents_returned_nothing


# ----------------------------------------------------------------------------
# Tavily params (live evidence 2026-06-10, same query both modes): basic depth
# returned a 52-week-high factoid, a YouTube blurb, and a 2025 article for a
# "past week" query; advanced depth + time_range=week returned current CNBC
# coverage and price-change tables that answer it. raw_content is deliberately
# NOT requested — it is 15-50KB of nav/cookie boilerplate per page.
# ----------------------------------------------------------------------------

def test_web_search_time_sensitive_uses_advanced_depth_and_week_filter(monkeypatch):
    from tools import search_guardrails as sg
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    fake = MagicMock()
    fake.search.return_value = {"results": [
        {"content": "| MU | -7.74% |", "url": "https://barchart.com/x"},
    ]}
    with patch.object(sg, "TavilyClient", return_value=fake):
        snippets, urls = sg._web_search_with_sources(
            "tech stocks down 20% past week", time_sensitive=True)

    kwargs = fake.search.call_args.kwargs
    assert kwargs["search_depth"] == "advanced"
    assert kwargs["time_range"] == "week"
    assert not kwargs.get("include_raw_content")
    assert "| MU | -7.74% |" in snippets
    assert urls == ["https://barchart.com/x"]


def test_web_search_evergreen_query_has_no_time_filter(monkeypatch):
    from tools import search_guardrails as sg
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    fake = MagicMock()
    fake.search.return_value = {"results": [{"content": "PEG explained", "url": "https://inv.com"}]}
    with patch.object(sg, "TavilyClient", return_value=fake):
        sg._web_search_with_sources("what is LITE PEG ratio")  # default: not time-sensitive

    kwargs = fake.search.call_args.kwargs
    assert kwargs["search_depth"] == "advanced"
    assert "time_range" not in kwargs


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
