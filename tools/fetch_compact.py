"""I6 — compact fetch-tool output for the calc/ratios agents.

In calc/ratios the get_*_statement tools exist only to populate the DuckDB cache;
the calculate_* tools read the actual numbers from that cache. Returning the full
statement text is therefore dead weight — and because every tool round re-sends
the whole message history (SambaNova has no prompt caching), each dump is re-billed
once per remaining round. A live 7-ticker MAG7 query hit ~95k tokens this way, with
the income/balance dumps making up ~60% of the heavy agents' prompt tokens.

These wrappers run the same fetch (the cache still gets populated) but return a
short confirmation instead of the full dump. The financials agent keeps the full
text — it summarizes the raw numbers for the user — so only calc/ratios use these.
"""

from tools.income import get_income_statement
from tools.balance_sheet import get_balance_sheet
from tools.cash_flow import get_cash_flow_statement
from tools.db import load_from_cache, load_balance_sheet, load_cash_flow

_ERROR_PREFIXES = ("Error", "TOOL_ERROR", "[Stale", "No ")


def _compact(ticker: str, label: str, full_result: str, cache_loader) -> str:
    # Surface real errors / stale-cache notices unchanged so failures stay visible.
    if full_result.startswith(_ERROR_PREFIXES):
        return full_result
    # Success only if the parse actually populated the cache — calculate_* reads it.
    if cache_loader(ticker):
        return (
            f"{ticker} {label} fetched and cached. Use the calculate_* tools to read "
            f"exact figures from the cache — do not estimate from memory."
        )
    # Parse produced nothing (cache empty): return the raw result so it's visible.
    return full_result


def get_income_statement_compact(ticker: str) -> str:
    return _compact(ticker, "income statement", get_income_statement(ticker), load_from_cache)


def get_balance_sheet_compact(ticker: str) -> str:
    return _compact(ticker, "balance sheet", get_balance_sheet(ticker), load_balance_sheet)


def get_cash_flow_statement_compact(ticker: str) -> str:
    return _compact(ticker, "cash flow statement", get_cash_flow_statement(ticker), load_cash_flow)
