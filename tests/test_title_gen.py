"""webapp.title_gen tests. llm_chat is mocked — no network/API calls."""
from unittest.mock import patch


def test_generate_title_uses_llm_output():
    from webapp.title_gen import generate_title

    with patch("webapp.title_gen.llm_chat", return_value=("AAPL Q4 Revenue", 42)):
        title, tokens = generate_title("What was Apple's revenue in Q4?")

    assert title == "AAPL Q4 Revenue"
    assert tokens == 42


def test_generate_title_strips_quotes_from_llm_output():
    from webapp.title_gen import generate_title

    with patch("webapp.title_gen.llm_chat", return_value=('"AAPL Q4 Revenue"', 5)):
        title, tokens = generate_title("What was Apple's revenue?")

    assert title == "AAPL Q4 Revenue"


def test_generate_title_falls_back_on_llm_error():
    from webapp.title_gen import generate_title

    with patch("webapp.title_gen.llm_chat", side_effect=RuntimeError("SambaNova timeout")):
        title, tokens = generate_title("x" * 55)

    assert title == "x" * 40 + "…"
    assert tokens == 0


def test_generate_title_fallback_keeps_short_message_whole():
    from webapp.title_gen import generate_title

    with patch("webapp.title_gen.llm_chat", side_effect=RuntimeError("boom")):
        title, tokens = generate_title("hi")

    assert title == "hi"
    assert tokens == 0


def test_generate_title_caps_long_llm_output():
    from webapp.title_gen import generate_title

    with patch("webapp.title_gen.llm_chat", return_value=("A" * 100, 10)):
        title, tokens = generate_title("some question")

    assert title == "A" * 60
    assert tokens == 10
