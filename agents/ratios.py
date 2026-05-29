import json
import time
import logging

from tools.llm import _get_client
from tools.monitoring import record_tool_call
from tools.config import MODEL_AGENT
from tools.balance_sheet import get_balance_sheet
from tools.ratios import (
    calculate_all_margins, calculate_debt_to_equity, calculate_roa_roe,
    calculate_current_ratio, calculate_interest_coverage,
)
from prompts import RATIOS_SYSTEM 

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
    {
        "type": "function",
        "function": {
            "name": "calculate_current_ratio",
            "description": (
                "Compute current ratio (current assets / current liabilities) from SEC balance sheet. "
                "Call get_balance_sheet first. > 1.5 = healthy, < 1.0 = liquidity risk."
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
            "name": "calculate_interest_coverage",
            "description": (
                "Compute interest coverage ratio (EBIT / interest expense) from SEC income statement. "
                "Call get_income_statement first. > 3x = comfortable, < 1.5x = solvency risk."
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
    "calculate_current_ratio": calculate_current_ratio,
    "calculate_interest_coverage": calculate_interest_coverage,
}

OPT = {"temperature": 0.1}


def run(user_question: str, context: str = "", history: list[dict] | None = None) -> str:
    messages = [{"role": "system", "content": RATIOS_SYSTEM}]
    if history:
        messages += history[-6:]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL_AGENT,
        messages=messages,
        tools=TOOLS,
        parallel_tool_calls=True,
        temperature=OPT["temperature"],
    )
    msg = response.choices[0].message

    while msg.tool_calls:
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            fn = TOOL_FUNCTIONS.get(name)
            _t = time.perf_counter()
            result = fn(**args) if fn else f"Unknown tool: {name}"
            _dur = round((time.perf_counter() - _t) * 1000)
            _err = result[:120] if isinstance(result, str) and result.startswith("TOOL_ERROR") else None
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
            logging.info("[RatiosAgent] %s(%s)", name, args)
            record_tool_call("RatiosAgent", name, args, duration_ms=_dur, error=_err)
        response = client.chat.completions.create(
            model=MODEL_AGENT,
            messages=messages,
            tools=TOOLS,
            parallel_tool_calls=True,
            temperature=OPT["temperature"],
        )
        msg = response.choices[0].message

    return msg.content or ""
