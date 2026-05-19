"""
Test the full pipeline: fetch from edgar → parse → store in DuckDB → inspect.
Usage: conda run -n stock python check_db_storage.py
"""
import re
import time

import duckdb
from edgar import Company, set_identity

set_identity("pattaranon23@gmail.com")

TICKER = "GOOGL"
DB_PATH = "check_test.db"


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_income_statement(ticker: str, raw: str) -> list[dict]:
    rows = []
    now = time.time()

    # Find fiscal year headers
    year_re = re.compile(
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4})'
    )
    # Take the line with the most year matches (avoids "Sep 30, 2023 to Sep 27, 2025" title line)
    fiscal_years = []
    for line in raw.split('\n'):
        years = year_re.findall(line)
        if len(years) > len(fiscal_years):
            fiscal_years = years

    if not fiscal_years:
        print("  ERROR: could not find fiscal year headers")
        return rows

    print(f"  Fiscal years found: {fiscal_years}")

    # Debug: show the first few lines that contain $ signs
    print("\n  [Debug: lines containing $ or digit patterns]")
    for i, line in enumerate(raw.split('\n')):
        if '$' in line or any(c.isdigit() for c in line[:5]):
            print(f"  line {i:3d} repr: {repr(line[:120])}")
        if i > 30:
            break

    # Match dollar values including negatives like $(321)
    dollar_re = re.compile(r'\$(\([\d,]+\)|[\d,]+)')
    current_section = "General"

    for line in raw.split('\n'):
        # Skip decorative/separator lines
        stripped = line.strip()
        if not stripped or any(c in stripped for c in ('─', '━', '+', '=')):
            continue

        # Find all dollar values on this line
        matches = dollar_re.findall(line)
        if not matches:
            continue

        values = []
        for m in matches:
            if m.startswith('('):
                values.append(-float(m.strip('()').replace(',', '')))
            else:
                values.append(float(m.replace(',', '')))

        if len(values) != len(fiscal_years):
            continue

        # Label is everything before the first $
        label_part = line[:line.index('$')].strip()
        if not label_part:
            continue

        name = label_part.rstrip(':').strip()
        is_section_header = label_part.rstrip().endswith(':')

        if is_section_header:
            current_section = name

        for i, year in enumerate(fiscal_years):
            rows.append({
                "ticker": ticker, "fiscal_year": year,
                "section": current_section, "line_item": name,
                "value": values[i], "fetched_at": now,
            })

    return rows


# ── DuckDB helpers ────────────────────────────────────────────────────────────

def init_db():
    con = duckdb.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS income_statements (
            ticker      VARCHAR,
            fiscal_year VARCHAR,
            section     VARCHAR,
            line_item   VARCHAR,
            value       DOUBLE,
            fetched_at  DOUBLE,
            PRIMARY KEY (ticker, fiscal_year, section, line_item)
        )
    """)
    con.commit()
    con.close()


def save_to_db(rows: list[dict]):
    if not rows:
        print("  WARNING: no rows to store")
        return
    con = duckdb.connect(DB_PATH)
    con.executemany(
        """INSERT OR REPLACE INTO income_statements
           (ticker, fiscal_year, section, line_item, value, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(r["ticker"], r["fiscal_year"], r["section"],
          r["line_item"], r["value"], r["fetched_at"]) for r in rows],
    )
    con.commit()
    con.close()


# ── Run ───────────────────────────────────────────────────────────────────────

print("=" * 70)
print(f"Fetching {TICKER} income statement from SEC...")
print("=" * 70)

company = Company(TICKER)
financials = company.get_financials()
raw = str(financials.income_statement())

print("\n[Raw edgar output (first 10 lines)]")
for line in raw.split('\n')[:10]:
    print(line)
print("  ...")

print(f"\n[Parsing...]")
rows = parse_income_statement(TICKER, raw)
print(f"  Parsed {len(rows)} rows")

print(f"\n[Storing in DuckDB: {DB_PATH}]")
init_db()
save_to_db(rows)
print(f"  Stored {len(rows)} rows")

# ── Inspect DB ────────────────────────────────────────────────────────────────

con = duckdb.connect(DB_PATH)

print("\n" + "=" * 70)
print("DB CONTENTS — all rows ordered by fiscal_year, section, line_item")
print("=" * 70)
result = con.execute("""
    SELECT fiscal_year, section, line_item, value
    FROM income_statements
    WHERE ticker = ?
    ORDER BY fiscal_year DESC, section, line_item
""", [TICKER]).fetchall()

current_section = None
current_year = None
for fiscal_year, section, line_item, value in result:
    if fiscal_year != current_year:
        print(f"\n── {fiscal_year} ──")
        current_year = fiscal_year
        current_section = None
    if section != current_section:
        print(f"  [{section}]")
        current_section = section
    print(f"    {line_item:<45} {value:>12,.0f}M")

print("\n" + "=" * 70)
print(f"Total rows in DB: {con.execute('SELECT COUNT(*) FROM income_statements').fetchone()[0]}")
print(f"Distinct sections: {con.execute('SELECT COUNT(DISTINCT section) FROM income_statements').fetchone()[0]}")
print(f"Distinct line_items: {con.execute('SELECT COUNT(DISTINCT line_item) FROM income_statements').fetchone()[0]}")

print("\n[Duplicate line_item check — same name under different sections]")
dupes = con.execute("""
    SELECT line_item, COUNT(DISTINCT section) as section_count,
           STRING_AGG(DISTINCT section, ' | ') as sections
    FROM income_statements
    WHERE ticker = ?
    GROUP BY line_item
    HAVING COUNT(DISTINCT section) > 1
""", [TICKER]).fetchall()
if dupes:
    for item, count, sections in dupes:
        print(f"  '{item}' appears in {count} sections: {sections}")
else:
    print("  None found.")

con.close()

import os
os.remove(DB_PATH)
print(f"\n(Cleaned up {DB_PATH})")
