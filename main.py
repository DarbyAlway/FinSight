import json
import subprocess

import ollama
from edgar import set_identity

from tools.config import *
from tools.db import init_db
from tools.income import get_income_statement, compare_tickers, parse_income_statement
from tools.news import get_stock_news, search_news
from tools.company import get_company_info
from tools.vector import (
    init_qdrant, store_articles, hybrid_search,
    upsert_company_profile, search_company_profiles,
)
from tools.db import (
    is_cache_fresh, save_to_cache, load_from_cache, fuzzy_query,
    save_ticker_info, load_ticker_info, is_ticker_info_fresh, get_summary_hash,
)

set_identity("yourname@email.com")

MODEL = "qwen3:30b-a3b"

SYSTEM_PROMPT = (
    "You are a stock analysis assistant. "
    "You have five tools: get_income_statement (SEC 10-K financial data), "
    "get_stock_news (fetch and store recent headlines), "
    "search_news (hybrid semantic+keyword search over stored news), "
    "compare_tickers (compare a financial metric across tickers with a chart), "
    "and get_company_info (company profile, sector, and key financial ratios). "
    "Use tools when the user asks about stocks. "
    "Always cite key figures and mention which tool you used. "
    "If you cannot answer and have no suitable tool, say so clearly."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_income_statement",
            "description": "Fetch the latest 3-year income statement for a single ticker from SEC filings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker, e.g. AAPL"}
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_news",
            "description": "Fetch recent news for a ticker from Yahoo Finance and Google News. Also stores articles for later search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker, e.g. AAPL"},
                    "max_results": {"type": "integer", "description": "Max results per source (default 10)"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": (
                "Hybrid semantic+keyword search over all stored news articles. "
                "Use for thematic queries like 'iPhone supply chain' or 'rate hike impact'. "
                "Optionally filter by ticker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "ticker": {"type": "string", "description": "Optional ticker filter"},
                    "top_k": {"type": "integer", "description": "Number of results (default 10)"},
                    "days_back": {"type": "integer", "description": "Only return articles within this many days (default 30)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_tickers",
            "description": "Compare a financial metric across multiple tickers. Opens a bar chart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tickers, e.g. ['AAPL', 'MSFT']",
                    },
                    "line_item": {
                        "type": "string",
                        "description": "Metric to compare, e.g. 'revenue', 'net income', 'r&d'",
                    },
                },
                "required": ["tickers", "line_item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_info",
            "description": (
                "Get company profile, sector, key financial ratios (P/E, margins, debt/equity), "
                "and business description for a ticker. Use for 'what does X do?' or 'what sector is X in?' queries. "
                "Data is cached for 72 hours."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker, e.g. AAPL"}
                },
                "required": ["symbol"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_income_statement": get_income_statement,
    "get_stock_news": get_stock_news,
    "search_news": search_news,
    "compare_tickers": compare_tickers,
    "get_company_info": get_company_info,
}


def dispatch_tool(tool_call) -> str:
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    return fn(**args)


def web_search_fallback(query: str) -> str:
    try:
        result = subprocess.run(
            ["npx", "-y", "@modelcontextprotocol/server-brave-search"],
            input=query, capture_output=True, text=True, timeout=15
        )
        return result.stdout.strip() or f"No web results found for: {query}"
    except Exception as e:
        return f"Web search unavailable: {e}"


def chat():
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    print(f"Stock Assistant ({MODEL}) — type 'exit' to quit\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
        msg = response.message

        tool_was_called = False
        while msg.tool_calls:
            tool_was_called = True
            messages.append(msg)
            for tool_call in msg.tool_calls:
                result = dispatch_tool(tool_call)
                messages.append({"role": "tool", "content": result})
            response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
            msg = response.message

        uncertain_phrases = ("i don't know", "i'm not sure", "i cannot", "no information", "not available")
        if not tool_was_called and any(p in (msg.content or "").lower() for p in uncertain_phrases):
            web_result = web_search_fallback(user_input)
            messages.append({"role": "user", "content": f"[Web search result]: {web_result}\nPlease answer based on the above."})
            response = ollama.chat(model=MODEL, messages=messages)
            msg = response.message

        messages.append({"role": "assistant", "content": msg.content or ""})
        print(f"\nAssistant: {msg.content or ''}\n")


if __name__ == "__main__":
    chat()


init_db()
