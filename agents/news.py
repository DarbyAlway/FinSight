from langfuse import observe
from tools.llm import _get_client
from agents._tooling import run_tool_loop
from tools.config import MODEL_AGENT
from tools.news import get_stock_news, search_news
from prompts import NEWS_SYSTEM as SYSTEM_PROMPT

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_news",
            "description": "Fetch live news headlines for a ticker from Yahoo Finance and Google News. Use for: latest news, breaking headlines, fresh articles, what happened today/recently.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Hybrid semantic+keyword search over stored news articles. Use for: searching past articles, thematic queries, finding news about a specific topic across stored results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "ticker": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "days_back": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_stock_news": get_stock_news,
    "search_news": search_news,
}

OPT = {"temperature": 0.1}


@observe(name="news-agent")
def run(user_question: str, context: str = "", history: list[dict] | None = None, expected_tickers: list[str] | None = None) -> tuple[str, int, dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages += history[-6:]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    client = _get_client()
    return run_tool_loop(
        "NewsAgent", client, MODEL_AGENT, messages, TOOLS, TOOL_FUNCTIONS,
        temperature=OPT["temperature"],
    )
