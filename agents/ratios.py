import json
import time
import logging

from tools.llm import _get_client
from monitoring import record_tool, update_agent_tokens
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


def run(user_question: str, context: str = "", history: list[dict] | None = None, agent_id: int | None = None, expected_tickers: list[str] | None = None) -> str:
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
            _t = time.perf_counter()
            result = fn(**args) if fn else f"Unknown tool: {name}"
            if isinstance(result, str) and len(result) > 3000:
                result = result[:3000] + "\n... [truncated]"
            _dur = round((time.perf_counter() - _t) * 1000)
            _err = result[:120] if isinstance(result, str) and result.startswith("TOOL_ERROR") else None
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
            logging.info("[RatiosAgent] %s(%s)", name, args)
            if agent_id is not None:
                record_tool(agent_id=agent_id, tool_name=name, duration_ms=_dur, arguments=args, error=_err)
        response = _chat(
            model=MODEL_AGENT,
            messages=messages,
            tools=TOOLS,
            temperature=OPT["temperature"],
        )
        msg = response.choices[0].message

    summary = msg.content or ""
    total_tokens = total_prompt_tokens + total_completion_tokens
    logging.info("[RatiosAgent] tokens: prompt=%d completion=%d total=%d",
                 total_prompt_tokens, total_completion_tokens, total_tokens)
    if agent_id is not None:
        update_agent_tokens(agent_id, total_tokens)

    if expected_tickers:
        missing = [t for t in expected_tickers if t not in summary]
        if missing:
            logging.info("[RatiosAgent] self-critique: missing %s — requesting completion", missing)
            messages.append({"role": "assistant", "content": summary})
            messages.append({"role": "user", "content": f"Your response is missing data for: {', '.join(missing)}. Return ONLY the ## TICKER sections for these missing tickers — do not repeat tickers already covered."})
            fix_response = _chat(
                model=MODEL_AGENT,
                messages=messages,
                tools=TOOLS,
                temperature=OPT["temperature"],
            )
            if fix_response.choices[0].message.content:
                summary += "\n\n" + fix_response.choices[0].message.content

    return summary
