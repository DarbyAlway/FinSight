import sys
sys.path.insert(0, ".")
from main import (
    get_income_statement, get_stock_news, search_news, get_company_info,
)
from orchestrator import process_turn

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

# Tool 5: orchestrator end-to-end (direct-answer path, no network needed)
print("\n--- process_turn (orchestrator wiring) ---")
try:
    answer, msgs = process_turn("What is the stock market?", [])
    results["orchestrator"] = isinstance(answer, str) and len(answer) > 0 and isinstance(msgs, list)
    print(answer[:200])
    print("PASS" if results["orchestrator"] else "FAIL")
except Exception as e:
    results["orchestrator"] = False
    print(f"FAIL: {e}")

# Summary
print("\n=== SMOKE TEST SUMMARY ===")
for name, passed in results.items():
    print(f"  {'PASS' if passed else 'FAIL'}  {name}")
all_passed = all(results.values())
print(f"\n{'ALL PASSED' if all_passed else 'SOME FAILED'}")
sys.exit(0 if all_passed else 1)
