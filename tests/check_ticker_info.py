from tools.db import init_db, load_ticker_info
init_db()
info = load_ticker_info('AAPL')
if info:
    keys = [
        'priceToBook', 'priceToSalesTrailing12Months', 'targetMeanPrice',
        'targetHighPrice', 'targetLowPrice', 'currentRatio', 'quickRatio',
        'interestCoverage', 'bookValue', 'enterpriseToRevenue',
    ]
    for k in keys:
        print(f"{k}: {info.get(k, 'MISSING')}")
else:
    print("No AAPL info in cache")
