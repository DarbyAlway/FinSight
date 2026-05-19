import re
from edgar import Company, set_identity

set_identity("yourname@email.com")

company = Company("AAPL")
raw = str(company.get_financials().income_statement())

year_re = re.compile(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4})')

print("=== Lines containing month names ===")
for i, line in enumerate(raw.split('\n')):
    if any(m in line for m in ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')):
        print(f"line {i:3d}: {repr(line)}")
        print(f"         findall: {year_re.findall(line)}")
        print(f"         non-ascii: {[hex(ord(c)) for c in line if ord(c) > 127]}")
