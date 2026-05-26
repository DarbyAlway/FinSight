import json
import logging

import ollama

from tools.config import MODEL
from tools.income import get_income_statement, get_quarterly_statement
from tools.company import get_company_info
from prompts import FINANCIALS_SYSTEM as SYSTEM_PROMPT

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_income_statement",
            "description": "Fetch the latest 3-year annual income statement for a ticker from SEC 10-K filings. Use for: annual revenue, yearly profit, full-year earnings, 3-year income trends.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quarterly_statement",
            "description": "Fetch the last 4 quarters of income statement data for a ticker from SEC 10-Q filings. Use for: Q1/Q2/Q3/Q4 results, this quarter's earnings, quarterly breakdown, recent quarter.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_info",
            "description": "Get company profile and market metrics: P/E ratio, current price, market cap, beta, dividend yield, sector, industry, and analyst recommendation. Use for any market-price-based metrics — NOT for margins, D/E, ROA, or ROE (those are in the ratios agent).",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_income_statement": get_income_statement,
    "get_quarterly_statement": get_quarterly_statement,
    "get_company_info": get_company_info,
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
            logging.info("[FinancialsAgent] %s(%s)", name, args)
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
        msg = response.message

    return msg.content or ""
