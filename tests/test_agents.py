from unittest.mock import MagicMock, patch


def _make_openai_response(content="result", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_financials_agent_returns_string():
    from agents.financials import run as run_financials
    with patch("agents.financials._get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = _make_openai_response("AAPL revenue is $400B")
        result = run_financials("What is AAPL revenue?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_financials_agent_calls_tool_when_requested():
    from agents.financials import run as run_financials, TOOL_FUNCTIONS

    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = "get_income_statement"
    tool_call.function.arguments = '{"ticker": "AAPL"}'

    tool_response = _make_openai_response(content=None, tool_calls=[tool_call])
    final_response = _make_openai_response(content="AAPL revenue: $400B")

    with patch("agents.financials._get_client") as mock_client, \
         patch.dict(TOOL_FUNCTIONS, {"get_income_statement": lambda ticker: "Revenue: $400B"}):
        mock_client.return_value.chat.completions.create.side_effect = [tool_response, final_response]
        result = run_financials("What is AAPL revenue?")

    assert "AAPL" in result or "400" in result


def test_news_agent_returns_string():
    from agents.news import run as run_news
    with patch("agents.news._get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = _make_openai_response("Apple released iPhone 17.")
        result = run_news("What is the latest news on AAPL?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_news_agent_only_has_news_tools():
    from agents.news import TOOL_FUNCTIONS
    assert set(TOOL_FUNCTIONS.keys()) == {"get_stock_news", "search_news"}


def test_calc_agent_returns_string():
    from agents.calc import run as run_calc
    with patch("agents.calc._get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = _make_openai_response("AAPL revenue CAGR: 8.2%")
        result = run_calc("What is AAPL 3-year revenue CAGR?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_calc_agent_only_has_calc_tools():
    from agents.calc import TOOL_FUNCTIONS
    expected = {
        "calculate_dcf", "calculate_peg", "calculate_pe_vs_sector",
        "calculate_revenue_cagr", "calculate_margin_trend", "calculate_yoy",
        "calculate_correlation", "rank_tickers", "get_price_history",
        "calculate_free_cash_flow", "calculate_cash_runway",
    }
    assert set(TOOL_FUNCTIONS.keys()) == expected
