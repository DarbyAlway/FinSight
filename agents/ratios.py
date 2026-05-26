import json
import logging

import ollama

from tools.config import MODEL
from tools.balance_sheet import get_balance_sheet
from tools.ratios import calculate_all_margins, calculate_debt_to_equity, calculate_roa_roe
from prompts import RATIOS_SYSTEM as SYSTEM_PROMPT

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_balance_sheet",
            "description": (
                "Fetch the latest 2-year balance sheet for a ticker from SEC 10-K filings. "
                "Call this before calculate_debt_to_equity or calculate_roa_roe."
            ),
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
            "name": "calculate_all_margins",
            "description": (
                "Compute gross, operating, and net profit margins from SEC 10-K income data. "
                "Use for any question about profit margin, gross margin, or operating margin. "
                "Requires get_income_statement to have been called first."
            ),
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
            "name": "calculate_debt_to_equity",
            "description": (
                "Compute debt-to-equity ratio from SEC 10-K balance sheet data. "
                "Call get_balance_sheet first. More accurate than yfinance debtToEquity."
            ),
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
            "name": "calculate_roa_roe",
            "description": (
                "Compute Return on Assets and Return on Equity from SEC 10-K data. "
                "Requires both get_income_statement and get_balance_sheet to have been called."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_balance_sheet": get_balance_sheet,
    "calculate_all_margins": calculate_all_margins,
    "calculate_debt_to_equity": calculate_debt_to_equity,
    "calculate_roa_roe": calculate_roa_roe,
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
            logging.info("[RatiosAgent] %s(%s)", name, args)
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
        msg = response.message

    return msg.content or ""
