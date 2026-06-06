"""Gate 2 — ticker validation + name resolution.

The planner LLM emits tickers it can't be trusted on: dead/renamed symbols
(TWTR after Twitter went private, SQ after Block renamed to XYZ, FB after Meta),
and occasionally symbols that never existed at all (hallucinations). All of these
share one property: they are NOT in the current SEC filer list.

- `validate_tickers()` partitions a list against the authoritative SEC ticker set
  (edgar.get_company_tickers(), ~10.7k current filers). This is the cheap,
  high-value guard: it catches dead and hallucinated tickers before we dispatch
  agents on them. Fails OPEN — if the SEC list can't load, nothing is dropped.

- `resolve_name()` turns a company NAME into a ticker via yfinance Search (first
  EQUITY hit), which handles brand renames the SEC name index misses
  (Facebook → META, Google → GOOG). Network call; used only for recovery.

- `resolve_entities()` applies the plan's rule: a ticker is trusted only if the
  user typed it verbatim AND it's a valid symbol; otherwise resolve as a name.
"""

import logging
import re
import threading

_LOCK = threading.Lock()
_SEC_TICKERS: set[str] = set()
_loaded = False


def _ensure_loaded() -> None:
    """Load the SEC ticker set once (thread-safe, lazy)."""
    global _loaded, _SEC_TICKERS
    if _loaded:
        return
    with _LOCK:
        if _loaded:
            return
        try:
            from edgar import get_company_tickers
            df = get_company_tickers()
            _SEC_TICKERS = {str(t).upper() for t in df["ticker"]}
            logging.info("resolve: loaded %d SEC tickers", len(_SEC_TICKERS))
        except Exception as e:  # pragma: no cover - network/edgar failure path
            logging.warning("resolve: could not load SEC ticker list: %s", e)
            _SEC_TICKERS = set()
        _loaded = True


def is_valid_ticker(symbol: str) -> bool:
    """True if `symbol` is a currently-listed SEC filer."""
    if not symbol:
        return False
    _ensure_loaded()
    return symbol.upper() in _SEC_TICKERS


def validate_tickers(tickers: list[str]) -> tuple[list[str], list[str]]:
    """Partition tickers into (valid, invalid) against the SEC filer set.

    Fails open: if the SEC list is unavailable, all tickers are treated as valid
    so we never drop everything just because reference data didn't load.
    """
    _ensure_loaded()
    if not _SEC_TICKERS:
        return list(tickers), []
    valid = [t for t in tickers if t and t.upper() in _SEC_TICKERS]
    invalid = [t for t in tickers if not t or t.upper() not in _SEC_TICKERS]
    return valid, invalid


def resolve_name(name: str) -> str | None:
    """Resolve a company NAME to a ticker via yfinance Search (first EQUITY hit)."""
    if not name or not name.strip():
        return None
    try:
        import yfinance as yf
        search = yf.Search(name, max_results=5)
        for quote in (getattr(search, "quotes", None) or []):
            if quote.get("quoteType") == "EQUITY" and quote.get("symbol"):
                return str(quote["symbol"]).upper()
    except Exception as e:
        logging.warning("resolve_name(%r) failed: %s", name, e)
    return None


def resolve_entities(entities: list[str], query: str) -> tuple[list[str], list[str]]:
    """Resolve LLM-extracted entities to tickers, returning (resolved, unresolved).

    A symbol is kept as-is only if the user typed it verbatim and it's a valid
    ticker; otherwise it's treated as a company name and resolved deterministically.
    Resolved tickers are de-duplicated, preserving order.
    """
    query_tokens = set(re.findall(r"[A-Za-z0-9.]+", (query or "").upper()))
    resolved: list[str] = []
    unresolved: list[str] = []
    for entity in entities:
        if not entity:
            continue
        sym = entity.upper()
        if sym in query_tokens and is_valid_ticker(sym):
            resolved.append(sym)
            continue
        recovered = resolve_name(entity)
        if recovered:
            resolved.append(recovered)
        else:
            unresolved.append(entity)

    seen: set[str] = set()
    deduped = [s for s in resolved if not (s in seen or seen.add(s))]
    return deduped, unresolved
