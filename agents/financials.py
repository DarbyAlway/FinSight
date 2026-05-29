import json
import time
import logging

from tools.llm import _get_client
from tools.monitoring import record_tool_call, record_token_usage
from tools.config import MODEL_AGENT
from tools.income import get_income_statement, get_quarterly_statement
from tools.company import get_company_info
from tools.cash_flow import get_cash_flow_statement
from tools.earnings_press import get_earnings_press_release
from prompts import FINANCIALS_SYSTEM as SYSTEM_PROMPT

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_income_statement",
            "description": "Fetch the latest 3-year annual income statement for a ticker from SEC 10-K filings. Use for: annual revenue, yearly profit, full-year earnings, 3-year income trends, product revenue breakdown, revenue by segment or product line, how much a company earns from each product or service category.",
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
    {
        "type": "function",
        "function": {
            "name": "get_cash_flow_statement",
            "description": (
                "Fetch the latest 2-year cash flow statement for a ticker from SEC 10-K filings. "
                "Use for: operating cash flow, capex, investing activities, financing activities, "
                "cash burn, free cash flow inputs."
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
            "name": "get_earnings_press_release",
            "description": (
                "Fetch the last 4 quarters of earnings results for a ticker: "
                "EPS actual vs estimate, beat/miss classification, and management guidance text. "
                "Use for: did the company beat expectations, earnings surprise history, "
                "management guidance, analyst estimate vs actual EPS, recent guidance, "
                "next earnings date."
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
    "get_income_statement": get_income_statement,
    "get_quarterly_statement": get_quarterly_statement,
    "get_company_info": get_company_info,
    "get_cash_flow_statement": get_cash_flow_statement,
    "get_earnings_press_release": get_earnings_press_release,
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

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL_AGENT,
        messages=messages,
        tools=TOOLS,
        parallel_tool_calls=True,
        temperature=OPT["temperature"],
    )
    if response.usage:
        record_token_usage("FinancialsAgent", response.usage.prompt_tokens, response.usage.completion_tokens)
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
            logging.info("[FinancialsAgent] %s(%s)", name, args)
            record_tool_call("FinancialsAgent", name, args, duration_ms=_dur, error=_err)
        response = client.chat.completions.create(
            model=MODEL_AGENT,
            messages=messages,
            tools=TOOLS,
            parallel_tool_calls=True,
            temperature=OPT["temperature"],
        )
        if response.usage:
            record_token_usage("FinancialsAgent", response.usage.prompt_tokens, response.usage.completion_tokens)
        msg = response.choices[0].message

    return msg.content or ""
