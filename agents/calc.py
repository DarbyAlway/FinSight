from langfuse import observe
from tools.llm import _get_client
from agents._tooling import run_tool_loop
from tools.config import MODEL_AGENT
from tools.calc import (
    calculate_dcf, calculate_peg, calculate_pe_vs_sector,
    calculate_revenue_cagr, calculate_margin_trend, calculate_yoy,
    calculate_correlation, rank_tickers,
    calculate_free_cash_flow, calculate_cash_runway,
)
from tools.price import get_price_history
from tools.company import get_company_info
from tools.fetch_compact import (
    get_income_statement_compact,
    get_cash_flow_statement_compact,
    get_balance_sheet_compact,
)
from prompts import CALC_SYSTEM as SYSTEM_PROMPT

TOOLS = [
    # Data-fetch tools — the calculate_* tools read from cache that these populate.
    # Call the relevant fetch first (e.g. get_company_info before calculate_peg /
    # calculate_pe_vs_sector; get_income_statement before CAGR / margin / yoy / dcf;
    # get_cash_flow_statement before free cash flow; get_balance_sheet before runway).
    {"type": "function", "function": {"name": "get_company_info", "description": "Fetch live market metrics (price, market cap, trailing/forward P/E, beta, analyst targets, sector). Call BEFORE calculate_peg or calculate_pe_vs_sector (they need P/E).", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}},
    {"type": "function", "function": {"name": "get_income_statement", "description": "Fetch the 3-year annual income statement from SEC 10-K filings. Call BEFORE calculate_revenue_cagr, calculate_margin_trend, calculate_yoy, calculate_dcf, or calculate_peg (EPS growth needs net income).", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "get_cash_flow_statement", "description": "Fetch the 2-year cash flow statement from SEC 10-K filings. Call BEFORE calculate_free_cash_flow or calculate_cash_runway.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "get_balance_sheet", "description": "Fetch the 2-year balance sheet from SEC 10-K filings. Call BEFORE calculate_cash_runway (needs cash balance).", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_revenue_cagr", "description": "Calculate revenue CAGR for a ticker. Requires get_income_statement first.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "years": {"type": "integer"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_margin_trend", "description": "Show gross and net margin trend by year. Requires get_income_statement first.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_yoy", "description": "Year-over-year change for any income statement metric. Requires get_income_statement first.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "metric": {"type": "string"}}, "required": ["ticker", "metric"]}}},
    {"type": "function", "function": {"name": "calculate_peg", "description": "PEG ratio (P/E divided by EPS growth rate). Requires get_company_info AND get_income_statement first.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_dcf", "description": "5-year DCF valuation using operating income as FCF proxy. Requires get_income_statement first.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "growth_rate": {"type": "number"}, "discount_rate": {"type": "number"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "calculate_pe_vs_sector", "description": "Compare ticker P/E against sector peers. Requires get_company_info first.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
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
    # Fetch tools return a compact confirmation (they only populate the cache;
    # the calculate_* tools read the numbers). Saves re-billing full statement
    # dumps every tool round. See tools/fetch_compact.py.
    "get_company_info": get_company_info,
    "get_income_statement": get_income_statement_compact,
    "get_cash_flow_statement": get_cash_flow_statement_compact,
    "get_balance_sheet": get_balance_sheet_compact,
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
    return run_tool_loop(
        "CalcAgent", client, MODEL_AGENT, messages, TOOLS, TOOL_FUNCTIONS,
        temperature=OPT["temperature"],
    )
