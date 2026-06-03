import json
import time
import logging

from langfuse import observe
from tools.llm import _get_client
from agents._tooling import execute_tool
from tools.config import MODEL_AGENT
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


@observe(name="calc-agent")
def run(user_question: str, context: str = "", history: list[dict] | None = None, expected_tickers: list[str] | None = None) -> tuple[str, int]:
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
    total_prompt_tokens = 0
    total_completion_tokens = 0

    def _chat(*args, **kwargs):
        nonlocal total_prompt_tokens, total_completion_tokens
        r = client.chat.completions.create(*args, **kwargs)
        if r.usage:
            total_prompt_tokens += r.usage.prompt_tokens
            total_completion_tokens += r.usage.completion_tokens
        return r

    response = _chat(
        model=MODEL_AGENT,
        messages=messages,
        tools=TOOLS,
        tool_choice="required",
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
            result = execute_tool("CalcAgent", name, args, fn)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
        response = _chat(
            model=MODEL_AGENT,
            messages=messages,
            tools=TOOLS,
            temperature=OPT["temperature"],
        )
        msg = response.choices[0].message

    total_tokens = total_prompt_tokens + total_completion_tokens
    logging.info("[CalcAgent] tokens: prompt=%d completion=%d total=%d",
                 total_prompt_tokens, total_completion_tokens, total_tokens)
    return (msg.content or ""), total_tokens
