"""Ticker resolution — the LLM names a company, this assigns the ticker.

Two layers:

1. Legacy Gate-2 validators (`is_valid_ticker`, `validate_tickers`) — still used by
   the current orchestrator to drop dead/hallucinated tickers against the SEC set.
   These stay until the LangGraph migration swaps the orchestrator over to the ladder.

2. The resolution ladder (`resolve_company`, `resolve_query`) — the new deterministic
   path. A name is resolved against the authoritative `ticker_db` table by an ordered
   ladder, never by an LLM symbol guess:

     1. exact normalized match        (tools.ticker_db.lookup_exact)
     2. curated alias / rename map     (google->GOOGL, facebook->META, square->XYZ)
     3. fuzzy match, high confidence   (rapidfuzz; fixes typos like microsft->MSFT)
     4. fuzzy match, ambiguous         -> AMBIGUOUS (refuse now; confirm under LangGraph)
     5. semantic search (descriptive)  -> "the iPhone maker" -> AAPL, gated by score

   Plus a verbatim-symbol rule: a token the user literally typed that is a valid
   symbol is trusted as-is — but finance abbreviations that happen to be tickers
   (PEG=PSEG, AI=C3.ai, ALL=Allstate) are excluded so "PEG of Tesla" doesn't resolve PSEG.
"""

import logging
import re
import threading
from dataclasses import dataclass, field

from rapidfuzz import process, fuzz

from tools import ticker_db

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


# --------------------------------------------------------------------------
# Resolution ladder
# --------------------------------------------------------------------------

# Tier 2 — curated common-names and renames the exact match can't catch.
_ALIASES: dict[str, str] = {
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "facebook": "META",
    "meta": "META",
    "square": "XYZ",   # Block Inc (renamed from Square); ticker SQ -> XYZ
    "block": "XYZ",
}

# Finance/English abbreviations that are ALSO real tickers but are almost never
# meant as one in a query (PEG=PSEG, AI=C3.ai, ALL=Allstate, ON=ON Semi,
# NOW=ServiceNow, IT=Gartner, SO=Southern, GO, BIG, CASH, REAL, OPEN, KEY...).
_VERBATIM_STOPWORDS: set[str] = {
    "PEG", "PE", "DCF", "CAGR", "YOY", "ROE", "ROA", "ROI", "ROIC", "EPS", "EBIT",
    "EBITDA", "FCF", "ETF", "IPO", "CEO", "CFO", "COO", "AI", "ML", "US", "USA",
    "UK", "EU", "GDP", "FY", "Q1", "Q2", "Q3", "Q4", "SEC", "IRS", "GAAP",
    "ALL", "ON", "IT", "SO", "GO", "BIG", "CASH", "REAL", "OPEN", "KEY", "NOW",
    "FOR", "ARE", "AND", "THE", "NEW", "BUY", "OR", "AN", "AS", "AT", "BE", "BY",
    "DO", "IF", "IN", "IS", "OF", "TO", "VS", "A", "I",
}

FUZZY_FLOOR = 88   # rapidfuzz WRatio (0-100): below this, no auto-accept
FUZZY_MARGIN = 8   # top must beat #2 by this much to auto-accept
SEMANTIC_FLOOR = 0.82  # cosine sim floor for the descriptive semantic tier

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"


@dataclass
class ResolveResult:
    status: str                       # RESOLVED | AMBIGUOUS | UNRESOLVED
    name: str | None = None           # the input name
    symbol: str | None = None         # set when RESOLVED
    candidates: list[str] = field(default_factory=list)  # set when AMBIGUOUS


_entries_cache: list[tuple[str, str]] | None = None


def _entries() -> list[tuple[str, str]]:
    """(norm_name, symbol) pairs for fuzzy matching, cached per process."""
    global _entries_cache
    if _entries_cache is None:
        _entries_cache = ticker_db.all_entries()
    return _entries_cache


def clear_cache() -> None:
    """Drop the cached fuzzy entries (call after rebuilding the ticker table)."""
    global _entries_cache
    _entries_cache = None


def resolve_company(name: str) -> ResolveResult:
    """Resolve one company NAME to a ticker via the ordered ladder (tiers 0-4)."""
    raw = (name or "").strip()

    # Tier 0 — the "name" is itself a raw ticker (GLiNER sometimes tags AAPL as a
    # company). Trust it only if it's typed in caps, valid, and not a finance
    # abbreviation (PEG/AI/ALL...) — so it can't be mistaken for the ratio etc.
    if raw.isupper() and raw not in _VERBATIM_STOPWORDS and ticker_db.is_valid_symbol(raw):
        return ResolveResult(RESOLVED, name=name, symbol=raw.upper())

    norm = ticker_db._normalize_name(name)
    if not norm:
        return ResolveResult(UNRESOLVED, name=name)

    # Tier 1 — exact normalized match.
    sym = ticker_db.lookup_exact(norm)
    if sym:
        return ResolveResult(RESOLVED, name=name, symbol=sym)

    # Tier 2 — curated alias / rename.
    if norm in _ALIASES:
        return ResolveResult(RESOLVED, name=name, symbol=_ALIASES[norm])

    # Tiers 3/4 — fuzzy string match against all normalized names. token_set_ratio
    # (not WRatio) avoids substring false-matches — WRatio scores "ford" highest
    # against "Ashford" via partial overlap, whereas token_set requires shared
    # whole tokens, so "ford" tops out at "Ford Motor" (F). Typos still resolve.
    entries = _entries()
    if entries:
        choices = [e[0] for e in entries]
        matches = process.extract(norm, choices, scorer=fuzz.token_set_ratio, limit=2)
        if matches:
            top_score = matches[0][1]
            second_score = matches[1][1] if len(matches) > 1 else 0
            if top_score >= FUZZY_FLOOR and (top_score - second_score) >= FUZZY_MARGIN:
                return ResolveResult(RESOLVED, name=name, symbol=entries[matches[0][2]][1])
            if top_score >= FUZZY_FLOOR:
                # near-tie -> ambiguous (refuse now; confirm under LangGraph)
                cands = [entries[m[2]][1] for m in matches]
                return ResolveResult(AMBIGUOUS, name=name, candidates=cands)

    return ResolveResult(UNRESOLVED, name=name)


def _verbatim_symbols(query: str) -> list[str]:
    """Tickers the user literally typed (uppercase, valid, not a finance stopword)."""
    out: list[str] = []
    for tok in re.findall(r"[A-Za-z][A-Za-z.\-]{0,5}", query or ""):
        if tok.isupper() and tok not in _VERBATIM_STOPWORDS and ticker_db.is_valid_symbol(tok):
            out.append(tok.upper())
    return out


def _alias_in_query(query: str) -> list[str]:
    """Apply curated aliases to CAPITALIZED tokens in the query, so common-word
    company names GLiNER won't tag (Square, Block) still resolve. Capitalization
    is required to avoid firing on the ordinary verb ("block these ads")."""
    out: list[str] = []
    for tok in re.findall(r"[A-Z][A-Za-z.\-]+", query or ""):
        sym = _ALIASES.get(ticker_db._normalize_name(tok))
        if sym:
            out.append(sym)
    return out


def _semantic_lookup(query: str, floor: float = SEMANTIC_FLOOR) -> str | None:
    """Tier 5 — descriptive references ("the iPhone maker") via company-profile
    embeddings, gated by score. Fails open (returns None) if Qdrant is down."""
    try:
        from tools.vector import _get_qdrant, search_company_profiles_scored
        hits = search_company_profiles_scored(_get_qdrant(), query, top_k=1)
    except Exception as e:
        logging.warning("resolve: semantic tier unavailable: %s", e)
        return None
    if hits:
        payload, score = hits[0]
        if score >= floor and payload.get("symbol"):
            return str(payload["symbol"]).upper()
    return None


def resolve_query(query: str, names: list[str] | None = None) -> tuple[list[str], list[ResolveResult]]:
    """Resolve a full query to a ticker list.

    Returns (tickers, unresolved_or_ambiguous). `names` may be supplied (e.g. from
    GLiNER); if omitted they're extracted here. Order: verbatim symbols, then each
    extracted name through the ladder, then — only if nothing resolved — the
    semantic descriptive tier on the whole query.
    """
    if names is None:
        from tools import ner
        names = ner.extract_companies(query)

    resolved: list[str] = list(_verbatim_symbols(query))
    resolved.extend(_alias_in_query(query))
    pending: list[ResolveResult] = []
    for name in names:
        r = resolve_company(name)
        if r.status == RESOLVED:
            resolved.append(r.symbol)
        else:
            pending.append(r)

    # de-dupe, preserve order
    seen: set[str] = set()
    resolved = [s for s in resolved if not (s in seen or seen.add(s))]

    if not resolved:
        sym = _semantic_lookup(query)
        if sym:
            resolved = [sym]

    return resolved, pending
