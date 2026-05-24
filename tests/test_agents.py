from unittest.mock import MagicMock, patch


def _make_ollama_response(content="result", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    resp = MagicMock()
    resp.message = msg
    return resp


def test_financials_agent_returns_string():
    from agents.financials import run as run_financials
    with patch("agents.financials.ollama.chat", return_value=_make_ollama_response("AAPL revenue is $400B")):
        result = run_financials("What is AAPL revenue?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_financials_agent_calls_tool_when_requested():
    from agents.financials import run as run_financials, TOOL_FUNCTIONS

    tool_msg = MagicMock()
    tool_msg.content = None
    tool_call = MagicMock()
    tool_call.function.name = "get_income_statement"
    tool_call.function.arguments = {"ticker": "AAPL"}
    tool_msg.tool_calls = [tool_call]

    final_msg = MagicMock()
    final_msg.content = "AAPL revenue: $400B"
    final_msg.tool_calls = []

    responses = [MagicMock(message=tool_msg), MagicMock(message=final_msg)]

    with patch("agents.financials.ollama.chat", side_effect=responses), \
         patch.dict(TOOL_FUNCTIONS, {"get_income_statement": lambda ticker: "Revenue: $400B"}):
        result = run_financials("What is AAPL revenue?")

    assert "AAPL" in result or "400" in result


def test_news_agent_returns_string():
    from agents.news import run as run_news
    with patch("agents.news.ollama.chat", return_value=_make_ollama_response("Apple released iPhone 17.")):
        result = run_news("What is the latest news on AAPL?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_news_agent_only_has_news_tools():
    from agents.news import TOOL_FUNCTIONS
    assert set(TOOL_FUNCTIONS.keys()) == {"get_stock_news", "search_news"}
