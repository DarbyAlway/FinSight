"""
Quick diagnostic: print raw edgar output for a ticker.
Usage: conda run -n stock python check_edgar.py AAPL
       conda run -n stock python check_edgar.py RKLB
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from edgar import Company, set_identity

set_identity("pattaranon23@gmail.com")

ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
print(f"\n{'='*60}")
print(f"  edgar raw output for: {ticker}")
print(f"{'='*60}\n")

company = Company(ticker)
financials = company.get_financials()

print("--- INCOME STATEMENT (10-K annual) ---")
try:
    income = financials.income_statement()
    print(income)
except Exception as e:
    print(f"  ERROR: {e}")

print("\n--- BALANCE SHEET (10-K annual) ---")
try:
    balance = financials.balance_sheet()
    print(balance)
except Exception as e:
    print(f"  ERROR: {e}")

print("\n--- CASH FLOW STATEMENT (10-K annual) ---")
try:
    cashflow = financials.cash_flow_statement()
    print(cashflow)
except Exception as e:
    print(f"  ERROR: {e}")
