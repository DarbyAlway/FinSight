import json
import logging

import ollama

from tools.config import MODEL
from tools.calc import (
    calculate_dcf, calculate_peg, calculate_pe_vs_sector,
    calculate_revenue_cagr, calculate_margin_trend, calculate_yoy,
    calculate_correlation, rank_tickers,
    calculate_free_cash_flow, calculate_cash_runway,
)
from tools.price import get_price_history
from prompts import CALC_SYSTEM as SYSTEM_PROMPT

TOOLS = [
    {"type": "function", "function": {"name": "calculate_revenue_cagr", "description": "Calculate revenue CAGR for a ticker.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "years": {"type": "integer"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_margin_trend", "description": "Show gross and net margin trend by year.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_yoy", "description": "Year-over-year change for any income statement metric.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "metric": {"type": "string"}}, "required": ["ticker", "metric"]}}},
    {"type": "function", "function": {"name": "calculate_peg", "description": "PEG ratio (P/E divided by EPS growth rate).", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_dcf", "description": "5-year DCF valuation using operating income as FCF proxy.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "growth_rate": {"type": "number"}, "discount_rate": {"type": "number"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_pe_vs_sector", "description": "Compare ticker P/E against sector peers.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_correlation", "description": "Price return correlation between 2+ tickers.", "parameters": {"type": "object", "properties": {"tickers": {"type": "array", "items": {"type": "string"}}, "period": {"type": "string"}}, "required": ["tickers"]}}},
    {"type": "function", "function": {"name": "rank_tickers", "description": "Rank tickers by a financial metric (highest first).", "parameters": {"type": "object", "properties": {"tickers": {"type": "array", "items": {"type": "string"}}, "metric": {"type": "string"}}, "required": ["tickers", "metric"]}}},
    {"type": "function", "function": {"name": "get_price_history", "description": "Fetch daily close price history for a ticker (cached 24h).", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "period": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {
        "name": "calculate_free_cash_flow",
        "description": (
            "Calculate free cash flow (operating cash flow minus capex) from SEC 10-K data. "
            "Call get_cash_flow_statement first. Shows last 2 fiscal years."
        ),
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    }},
    {"type": "function", "function": {
        "name": "calculate_cash_runway",
        "description": (
            "Estimate months of cash runway using cash balance (balance sheet) and FCF burn rate. "
            "Call get_balance_sheet AND get_cash_flow_statement first."
        ),
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    }},
]

TOOL_FUNCTIONS = {
    "calculate_dcf": calculate_dcf,
    "calculate_peg": calculate_peg,
    "calculate_pe_vs_sector": calculate_pe_vs_sector,
    "calculate_revenue_cagr": calculate_revenue_cagr,
    "calculate_margin_trend": calculate_margin_trend,
    "calculate_yoy": calculate_yoy,
    "calculate_correlation": calculate_correlation,
    "rank_tickers": rank_tickers,
    "get_price_history": get_price_history,
    "calculate_free_cash_flow": calculate_free_cash_flow,
    "calculate_cash_runway": calculate_cash_runway,
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
            logging.info("[CalcAgent] %s(%s)", name, args)
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options=OPT)
        msg = response.message

    return msg.content or ""
