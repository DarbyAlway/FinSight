"""
Quick diagnostic: print raw yfinance output for a ticker.
Usage: conda run -n stock python check_yfinance.py AAPL
       conda run -n stock python check_yfinance.py RKLB
"""
import sys
import json
import yfinance as yf

FINANCIAL_RATIO_FIELDS = [
    "profitMargins", "grossMargins", "operatingMargins", "ebitdaMargins",
    "debtToEquity", "returnOnAssets", "returnOnEquity",
    "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
    "enterpriseToEbitda", "enterpriseToRevenue",
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
]

MARKET_FIELDS = [
    "currentPrice", "marketCap", "beta", "sharesOutstanding",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "recommendationKey", "numberOfAnalystOpinions",
]

META_FIELDS = [
    "longName", "sector", "industry", "country",
    "mostRecentQuarter", "fiscalYearEnd",
]

ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
print(f"\n{'='*60}")
print(f"  yfinance raw output for: {ticker}")
print(f"{'='*60}\n")

info = yf.Ticker(ticker).info

print("--- COMPANY META ---")
for k in META_FIELDS:
    print(f"  {k:40s} {info.get(k, 'N/A')}")

print("\n--- MARKET DATA (reliable) ---")
for k in MARKET_FIELDS:
    v = info.get(k, "N/A")
    if isinstance(v, float) and k == "marketCap":
        print(f"  {k:40s} ${v:,.0f}")
    else:
        print(f"  {k:40s} {v}")

print("\n--- FINANCIAL RATIOS (unreliable — yfinance pre-computed) ---")
for k in FINANCIAL_RATIO_FIELDS:
    v = info.get(k, "N/A")
    if isinstance(v, float) and "Margin" in k:
        print(f"  {k:40s} {v:.1%}")
    else:
        print(f"  {k:40s} {v}")

print("\n--- ALL OTHER FIELDS (raw) ---")
skip = set(FINANCIAL_RATIO_FIELDS + MARKET_FIELDS + META_FIELDS + ["longBusinessSummary"])
for k, v in sorted(info.items()):
    if k not in skip:
        print(f"  {k:40s} {v}")

print(f"\n--- TOTAL FIELDS RETURNED: {len(info)} ---\n")
