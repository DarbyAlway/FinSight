"""Show exactly what each agent sees in its message context.

For every tool an agent calls, this prints the raw string the model receives,
with a char count and a rough token estimate (~chars/4). That's the thing the
re-send multiplier bills over and over, so it's where the input-token cost lives.

Run:  python inspect_agent_io.py            # defaults to MSFT
      python inspect_agent_io.py AAPL       # any (cached) ticker
      python inspect_agent_io.py NVDA LITE  # multiple

No LLM is called — only the data-fetch / calculate tools (SEC cache + yfinance),
so this is free to run. If a ticker isn't cached yet the first fetch will hit
the SEC/yfinance API once and then cache it.
"""
import sys


def _est_tokens(s: str) -> int:
    return len(s) // 4


def show(label: str, fn, *args, **kwargs):
    try:
        out = fn(*args, **kwargs)
    except Exception as e:
        out = f"[ERROR: {type(e).__name__}: {e}]"
    out = out if isinstance(out, str) else str(out)
    chars = len(out)
    bar = "=" * 70
    print(bar)
    print(f"### {label}    ({chars} chars  ~{_est_tokens(out)} tokens)")
    print(bar)
    print(out)
    print()
    return chars


def run_for_ticker(ticker: str):
    # SEC EDGAR refuses requests without a User-Agent identity. The real app
    # sets this at startup (main.py); this standalone script must do it too,
    # otherwise every SEC statement fetch fails with "identity is not set".
    from edgar import set_identity
    set_identity("yourname@email.com")

    from tools.income import get_income_statement
    from tools.balance_sheet import get_balance_sheet
    from tools.cash_flow import get_cash_flow_statement
    from tools.company import get_company_info
    from tools.calc import (
        calculate_revenue_cagr,
        calculate_margin_trend,
        calculate_peg,
        calculate_free_cash_flow,
    )

    print("\n" + "#" * 70)
    print(f"#  AGENT INPUTS FOR: {ticker}")
    print("#" * 70 + "\n")

    sizes: dict[str, int] = {}

    # --- FETCH TOOLS (the full dumps) -------------------------------------
    # calc & ratios call these ONLY to populate the DuckDB cache, then read
    # the numbers back via calculate_*  ->  the dump text below is re-sent
    # every round for nothing in those two agents.
    print("---- FETCH TOOLS (full statement dumps) " + "-" * 30 + "\n")
    sizes["get_income_statement"] = show(f"get_income_statement({ticker})", get_income_statement, ticker)
    sizes["get_balance_sheet"] = show(f"get_balance_sheet({ticker})", get_balance_sheet, ticker)
    sizes["get_cash_flow_statement"] = show(f"get_cash_flow_statement({ticker})", get_cash_flow_statement, ticker)
    sizes["get_company_info"] = show(f"get_company_info({ticker})", get_company_info, ticker)

    # --- CALCULATE TOOLS (the actual answers) -----------------------------
    # These read the cache and return a small formatted result. This is what
    # the agent's reasoning actually needs.
    print("---- CALCULATE TOOLS (the real results) " + "-" * 30 + "\n")
    sizes["calculate_revenue_cagr"] = show(f"calculate_revenue_cagr({ticker})", calculate_revenue_cagr, ticker)
    sizes["calculate_margin_trend"] = show(f"calculate_margin_trend({ticker})", calculate_margin_trend, ticker)
    sizes["calculate_peg"] = show(f"calculate_peg({ticker})", calculate_peg, ticker)
    sizes["calculate_free_cash_flow"] = show(f"calculate_free_cash_flow({ticker})", calculate_free_cash_flow, ticker)

    # --- SUMMARY ----------------------------------------------------------
    fetch = sum(v for k, v in sizes.items() if k.startswith("get_"))
    calc = sum(v for k, v in sizes.items() if k.startswith("calculate_"))
    print("=" * 70)
    print(f"SUMMARY for {ticker}")
    print("=" * 70)
    for name, chars in sizes.items():
        kind = "FETCH" if name.startswith("get_") else "calc "
        print(f"  [{kind}] {name:<30} {chars:>6} chars  ~{_est_tokens(str(' '*chars)):>5} tok")
    print("-" * 70)
    print(f"  FETCH dumps total:     {fetch:>6} chars  ~{fetch//4:>5} tok")
    print(f"  CALCULATE results tot: {calc:>6} chars  ~{calc//4:>5} tok")
    if fetch:
        print(f"  -> In calc/ratios the {fetch} chars of FETCH text are re-sent every")
        print(f"     round for NOTHING (numbers come from the cache, not this text).")
    print()


def main():
    tickers = sys.argv[1:] or ["RKLB"]
    for t in tickers:
        run_for_ticker(t.upper())


if __name__ == "__main__":
    main()
