"""Authoritative ticker lookup table — built from SEC EDGAR + NASDAQ Trader.

The principle: the LLM names a company; this deterministic table assigns the
ticker. No LLM-invented symbols. Two free sources, downloaded in full and
deduped on symbol into one local DuckDB table:

  - SEC EDGAR  (`edgar.get_company_tickers`) — symbol + company name for every
    filer (~10.7k), incl. foreign ADRs. The validator-grade source.
  - NASDAQ Trader (`nasdaqlisted.txt` + `otherlisted.txt`) — all US-exchange
    securities INCLUDING ETFs, which SEC misses, plus an ETF flag.

Everything fails open: a download failure keeps the last cached table; a missing
table degrades to verbatim-symbol-only resolution, never a crash.
"""

import logging
import re
import time
import urllib.request

from tools.db import connect

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
REFRESH_TTL_DAYS = 7

# Trailing corporate suffixes stripped during name normalization.
_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "plc", "holdings", "holding", "group", "sa", "ag", "nv", "lp",
    "llc", "trust",
}


def _normalize_name(name: str) -> str:
    """Lowercase, drop the security-type descriptor, punctuation and corporate
    suffixes. 'NVIDIA CORP' -> 'nvidia'; 'Apple Inc. - Common Stock' -> 'apple'."""
    s = (name or "").lower()
    s = s.split(" - ")[0]                       # drop "- Common Stock" descriptor
    s = re.sub(r"[^a-z0-9 ]", " ", s)           # punctuation -> space
    tokens = s.split()
    while tokens and tokens[0] == "the":        # drop leading "the"
        tokens.pop(0)
    while tokens and tokens[-1] in _SUFFIXES:   # drop trailing suffixes
        tokens.pop()
    return " ".join(tokens)


def _parse_nasdaq(text: str) -> list[dict]:
    """Parse a NASDAQ Trader pipe-delimited file (nasdaqlisted or otherlisted).

    Handles either 'Symbol' or 'ACT Symbol', reads the ETF flag, skips test
    issues and the trailing 'File Creation Time' footer line.
    """
    lines = text.strip().splitlines()
    if not lines:
        return []
    header = lines[0].split("|")

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    sym_i = col("Symbol", "ACT Symbol")
    name_i = col("Security Name")
    etf_i = col("ETF")
    test_i = col("Test Issue")
    if sym_i is None:
        return []

    rows: list[dict] = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) <= sym_i:
            continue
        symbol = parts[sym_i].strip().upper()
        if not symbol:
            continue
        if test_i is not None and len(parts) > test_i and parts[test_i].strip() == "Y":
            continue  # skip test issues
        name = parts[name_i].strip() if name_i is not None and len(parts) > name_i else ""
        is_etf = etf_i is not None and len(parts) > etf_i and parts[etf_i].strip() == "Y"
        rows.append({"symbol": symbol, "name": name, "source": "nasdaq", "is_etf": is_etf})
    return rows


def _rows_from_sec(df) -> list[dict]:
    """Build rows from the SEC `get_company_tickers()` dataframe (symbol + name)."""
    cols = {c.lower(): c for c in df.columns}
    tcol = cols.get("ticker")
    ncol = cols.get("company") or cols.get("title") or cols.get("name")
    rows: list[dict] = []
    for _, r in df.iterrows():
        symbol = str(r[tcol]).strip().upper() if tcol else ""
        if not symbol:
            continue
        name = str(r[ncol]).strip() if ncol else ""
        rows.append({"symbol": symbol, "name": name, "source": "sec", "is_etf": False})
    return rows


def _dedup(rows: list[dict]) -> list[dict]:
    """One row per symbol. ETF flag is OR'd across sources; prefer the shorter
    non-empty display name."""
    by_symbol: dict[str, dict] = {}
    for r in rows:
        sym = r["symbol"].upper()
        if sym not in by_symbol:
            by_symbol[sym] = {**r, "symbol": sym}
            continue
        existing = by_symbol[sym]
        existing["is_etf"] = bool(existing["is_etf"]) or bool(r["is_etf"])
        if r["name"] and (not existing["name"] or len(r["name"]) < len(existing["name"])):
            existing["name"] = r["name"]
    return list(by_symbol.values())


def build_lookup(rows: list[dict]) -> int:
    """Replace the lookup table with the deduped rows. Returns the row count."""
    deduped = _dedup(rows)
    with connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ticker_lookup (
                symbol     VARCHAR PRIMARY KEY,
                name       VARCHAR,
                norm_name  VARCHAR,
                source     VARCHAR,
                is_etf     BOOLEAN
            )
        """)
        con.execute("CREATE TABLE IF NOT EXISTS ticker_lookup_meta (built_at DOUBLE)")
        con.execute("DELETE FROM ticker_lookup")
        con.executemany(
            "INSERT OR REPLACE INTO ticker_lookup (symbol, name, norm_name, source, is_etf) "
            "VALUES (?, ?, ?, ?, ?)",
            [(r["symbol"], r["name"], _normalize_name(r["name"]), r["source"], bool(r["is_etf"]))
             for r in deduped],
        )
        con.execute("DELETE FROM ticker_lookup_meta")
        con.execute("INSERT INTO ticker_lookup_meta (built_at) VALUES (?)", (time.time(),))
    return len(deduped)


def _query(sql: str, params: tuple, default):
    """Run a read query, returning `default` if the table doesn't exist yet."""
    try:
        with connect() as con:
            return con.execute(sql, params).fetchall()
    except Exception:
        return default


def lookup_exact(norm_name: str) -> str | None:
    rows = _query(
        "SELECT symbol FROM ticker_lookup WHERE norm_name = ? LIMIT 1",
        (norm_name,), [],
    )
    return rows[0][0] if rows else None


def is_valid_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    rows = _query(
        "SELECT 1 FROM ticker_lookup WHERE symbol = ? LIMIT 1", (symbol.upper(),), [],
    )
    return bool(rows)


def is_etf(symbol: str) -> bool:
    rows = _query(
        "SELECT is_etf FROM ticker_lookup WHERE symbol = ? LIMIT 1", (symbol.upper(),), [],
    )
    return bool(rows[0][0]) if rows else False


def get_name(symbol: str) -> str | None:
    rows = _query(
        "SELECT name FROM ticker_lookup WHERE symbol = ? LIMIT 1", (symbol.upper(),), [],
    )
    return rows[0][0] if rows else None


def all_entries() -> list[tuple[str, str]]:
    """(norm_name, symbol) pairs for fuzzy matching."""
    return _query("SELECT norm_name, symbol FROM ticker_lookup", (), [])


def _download(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "research test@example.com"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def download_and_build() -> int:
    """Download SEC + NASDAQ in full, dedup, and rebuild the table. Returns count."""
    rows: list[dict] = []
    try:
        from edgar import get_company_tickers
        rows.extend(_rows_from_sec(get_company_tickers()))
    except Exception as e:
        logging.warning("ticker_db: SEC ticker download failed: %s", e)
    for url in (NASDAQ_LISTED_URL, OTHER_LISTED_URL):
        try:
            rows.extend(_parse_nasdaq(_download(url)))
        except Exception as e:
            logging.warning("ticker_db: NASDAQ download failed (%s): %s", url, e)
    if not rows:
        raise RuntimeError("no ticker data could be downloaded from SEC or NASDAQ")
    return build_lookup(rows)


def _is_fresh(ttl_days: int) -> bool:
    rows = _query("SELECT built_at FROM ticker_lookup_meta LIMIT 1", (), [])
    if not rows:
        return False
    return (time.time() - rows[0][0]) / 86400 < ttl_days


def ensure_built(ttl_days: int = REFRESH_TTL_DAYS) -> None:
    """Build the table if missing or stale. Fails open — on download failure the
    last cached table is kept (or resolution degrades to verbatim-only)."""
    if _is_fresh(ttl_days):
        return
    try:
        download_and_build()
    except Exception as e:
        logging.warning("ticker_db: ensure_built failed, keeping existing table: %s", e)
