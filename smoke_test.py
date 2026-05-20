import sys
sys.path.insert(0, ".")
from main import (
    get_income_statement, get_stock_news, search_news,
    get_company_info, compare_tickers, TOOLS, TOOL_FUNCTIONS, dispatch_tool
)

results = {}

# Tool 1: income statement
print("--- get_income_statement(AAPL) ---")
r = get_income_statement("AAPL")
results["income"] = len(r) > 0 and "AAPL" in r
print(r[:200])
print("PASS" if results["income"] else "FAIL")

# Tool 2: company info
print("\n--- get_company_info(MSFT) ---")
r = get_company_info("MSFT")
results["company"] = len(r) > 0 and "Microsoft" in r
print(r[:300])
print("PASS" if results["company"] else "FAIL")

# Tool 3: stock news
print("\n--- get_stock_news(TSLA, max_results=3) ---")
r = get_stock_news("TSLA", max_results=3)
results["news"] = len(r) > 0
print(r[:300])
print("PASS" if results["news"] else "FAIL")

# Tool 4: search news (needs news fetched first)
print("\n--- search_news(Tesla earnings) ---")
r = search_news("Tesla earnings revenue", ticker="TSLA", top_k=3)
results["search"] = len(r) > 0
print(r[:300])
print("PASS" if results["search"] else "FAIL")

# Check TOOLS and TOOL_FUNCTIONS wired correctly
print("\n--- Tool schemas ---")
tool_names = [t["function"]["name"] for t in TOOLS]
expected = {"get_income_statement", "get_stock_news", "search_news", "compare_tickers", "get_company_info"}
results["schemas"] = expected == set(tool_names) == set(TOOL_FUNCTIONS.keys())
print(f"Tools: {tool_names}")
print("PASS" if results["schemas"] else "FAIL")

# Summary
print("\n=== SMOKE TEST SUMMARY ===")
for name, passed in results.items():
    print(f"  {'PASS' if passed else 'FAIL'}  {name}")
all_passed = all(results.values())
print(f"\n{'ALL PASSED' if all_passed else 'SOME FAILED'}")
sys.exit(0 if all_passed else 1)
