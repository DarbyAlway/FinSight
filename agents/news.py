import json
import logging

import ollama

from tools.config import MODEL
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


def run(user_question: str, context: str = "", history: list[dict] | None = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages += history[-6:]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
    msg = response.message

    while msg.tool_calls:
        messages.append(msg)
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = (
                tool_call.function.arguments
                if isinstance(tool_call.function.arguments, dict)
                else json.loads(tool_call.function.arguments)
            )
            fn = TOOL_FUNCTIONS.get(name)
            result = fn(**args) if fn else f"Unknown tool: {name}"
            messages.append({"role": "tool", "content": result})
            logging.info("[NewsAgent] %s(%s)", name, args)
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
        msg = response.message

    return msg.content or ""
