from edgar import Company, set_identity
set_identity("yourname@email.com")  # just for SEC rate-limit politeness

# Pull Apple's latest 10-K text
aapl = Company("AAPL")
filing = aapl.get_filings(form="10-K").latest(1)
doc = filing.obj()

# Get structured financials
financials = aapl.get_financials()
income_df = financials.income_statement()  # DataFrame — ready for chunking
print(income_df)