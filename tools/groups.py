"""Gate 1 — group membership manifest.

A bounded, hand-curated map of well-known market group names (MAG7, FAANG) to
their canonical ticker lists. Group membership is NOT something an LLM can be
trusted to expand reliably (it produced FB/BABA and dropped META/NVDA for "MAG7"),
so we resolve named groups deterministically from this manifest — 0ms, exact.

This manifest is deliberately small: it only holds well-known acronyms with a
*fixed, stable* membership. Any group name not found here returns None, which is
the router's signal to take the dynamic web-search path (`trigger_grounded_search`)
and discover the membership live — appropriate for time-varying themes
("top 5 AI penny stocks") that would go stale if hardcoded. This is the bounded
sibling of Gate 2 (per-ticker resolution via the authoritative SEC index).
"""

# Canonical membership. Keep tickers in their current, correct form (META not FB).
GROUP_MANIFEST: dict[str, list[str]] = {
    "MAG7": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
    "FAANG": ["META", "AAPL", "AMZN", "NFLX", "GOOGL"],
}

# Alias spellings (normalized) -> canonical group key. Lets "Magnificent Seven",
# "mag 7", etc. all resolve to MAG7.
_ALIASES: dict[str, str] = {
    "mag7": "MAG7",
    "magnificent7": "MAG7",
    "magnificentseven": "MAG7",
    "faang": "FAANG",
}


def _normalize(name: str) -> str:
    """Lowercase and strip everything but alphanumerics ('MAG 7' -> 'mag7')."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def check_local_manifest(name: str) -> list[str] | None:
    """Return the canonical ticker list for a known group name, else None.

    Case- and spacing-insensitive. Returns a fresh copy so callers can't mutate
    the manifest. A None return is the signal to fall back to the dynamic
    web-search path — the group is not one of our bounded, stable acronyms.
    """
    key = _ALIASES.get(_normalize(name))
    if key is None:
        return None
    return list(GROUP_MANIFEST[key])


def detect_group_in_query(query: str) -> list[str] | None:
    """Find a known group mention anywhere in a free-text query, else None.

    The planner LLM can't be trusted to expand a group correctly, so the
    orchestrator uses this to override its ticker list when the user names a
    group ("analyze MAG7", "the magnificent seven"). Matches an alias as a
    substring of the alphanumeric-normalized query, so spacing/case don't matter.
    """
    norm = _normalize(query)
    if not norm:
        return None
    for alias, key in _ALIASES.items():
        if alias in norm:
            return list(GROUP_MANIFEST[key])
    return None
