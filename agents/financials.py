from langfuse import observe
from tools.llm import _get_client
from agents._tooling import run_tool_loop
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
            "description": (
                "Get live market metrics for a company: current price, market cap (in T/B), "
                "trailing P/E, forward P/E, beta, dividend yield (%), "
                "analyst recommendation (strong_buy/buy/hold/sell), number of analysts, "
                "mean/high/low price targets, P/S ratio, P/B ratio, sector, industry. "
                "Use for: valuation comparison, investment ranking, cheapest/most valuable stock, "
                "price targets, analyst sentiment. "
                "Do NOT use for: margins, D/E ratio, ROA, ROE — those are in the ratios agent."
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


@observe(name="financials-agent")
def run(user_question: str, context: str = "", history: list[dict] | None = None, expected_tickers: list[str] | None = None) -> tuple[str, int, dict]:
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
    return run_tool_loop(
        "FinancialsAgent", client, MODEL_AGENT, messages, TOOLS, TOOL_FUNCTIONS,
        temperature=OPT["temperature"], expected_tickers=expected_tickers,
    )
