import json
import logging

import ollama

from tools.config import MODEL
from tools.income import get_income_statement, get_quarterly_statement
from tools.company import get_company_info

SYSTEM_PROMPT = (
    "You are a financial data agent. Fetch and return structured financial facts for the requested ticker(s). "
    "Do not interpret, advise, or add context beyond what the tools return. "
    "Always cite the exact fiscal year and source filing for every figure."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_income_statement",
            "description": "Fetch the latest 3-year annual income statement for a ticker from SEC 10-K filings.",
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
            "description": "Fetch the last 4 quarters of income statement data for a ticker from SEC 10-Q filings.",
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
            "description": "Get company profile, sector, and key financial ratios for a ticker.",
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


def run(user_question: str, context: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
