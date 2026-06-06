from langfuse import observe
from tools.llm import _get_client
from agents._tooling import run_tool_loop
from tools.config import MODEL_AGENT
from tools.company import get_company_info
from tools.fetch_compact import (
    get_income_statement_compact,
    get_balance_sheet_compact,
)
from tools.ratios import (
    calculate_all_margins, calculate_debt_to_equity, calculate_roa_roe,
    calculate_current_ratio, calculate_interest_coverage,
)
from prompts import RATIOS_SYSTEM

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_income_statement",
            "description": (
                "Fetch the latest 3-year annual income statement for a ticker from SEC 10-K filings. "
                "Call this BEFORE calculate_all_margins, calculate_roa_roe, or calculate_interest_coverage "
                "(they need revenue, net income, and operating income from this statement)."
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
            "name": "get_company_info",
            "description": (
                "Get live market context for a company: sector, industry, market cap, current price. "
                "Use for sector/industry context when commenting on ratios. "
                "Does NOT provide margins or balance-sheet ratios — compute those with the calculate_* tools."
            ),
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
    # Fetch tools return a compact confirmation (cache-only; calculate_* reads the
    # numbers) to avoid re-billing full statement dumps. See tools/fetch_compact.py.
    "get_income_statement": get_income_statement_compact,
    "get_company_info": get_company_info,
    "get_balance_sheet": get_balance_sheet_compact,
    "calculate_all_margins": calculate_all_margins,
    "calculate_debt_to_equity": calculate_debt_to_equity,
    "calculate_roa_roe": calculate_roa_roe,
    "calculate_current_ratio": calculate_current_ratio,
    "calculate_interest_coverage": calculate_interest_coverage,
}

OPT = {"temperature": 0.1}


@observe(name="ratios-agent")
def run(user_question: str, context: str = "", history: list[dict] | None = None, expected_tickers: list[str] | None = None) -> tuple[str, int]:
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
    return run_tool_loop(
        "RatiosAgent", client, MODEL_AGENT, messages, TOOLS, TOOL_FUNCTIONS,
        temperature=OPT["temperature"], expected_tickers=expected_tickers,
    )
