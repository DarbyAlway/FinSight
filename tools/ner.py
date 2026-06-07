"""Company-name extraction via GLiNER (zero-shot NER).

GLiNER pulls the literal company/organization name spans out of a query — typos
included (the fuzzy tier fixes spelling later). It is the extraction half of the
"LLM names the company, code assigns the ticker" pipeline: it never emits a
symbol, only name strings.

Returns [] for queries with no proper-noun company (e.g. "the iPhone maker") —
that empty result is the signal for the semantic-search tier downstream. Fails
open: if the model can't load, returns [] rather than crashing the query.
"""

import logging

_model = None
_LABELS = ["company", "organization"]
_MODEL_NAME = "urchade/gliner_medium-v2.1"


def _get_model():
    """Lazily load the GLiNER model once (first call pays the load)."""
    global _model
    if _model is None:
        from gliner import GLiNER
        _model = GLiNER.from_pretrained(_MODEL_NAME)
    return _model


def extract_companies(query: str, threshold: float = 0.3) -> list[str]:
    """Return de-duplicated company/organization name spans found in `query`.

    Default threshold is intentionally low (0.3): recall matters more than
    precision here because every extracted name is gated by the deterministic
    ticker lookup downstream — a falsely-tagged non-company simply fails to
    resolve, it can never produce a wrong ticker. At 0.5 GLiNER drops real
    companies in multi-company queries and misses typo'd names entirely.
    """
    if not query or not query.strip():
        return []
    try:
        entities = _get_model().predict_entities(query, _LABELS, threshold=threshold)
    except Exception as e:
        logging.warning("ner: extraction failed, returning []: %s", e)
        return []

    seen: set[str] = set()
    out: list[str] = []
    for ent in entities:
        text = (ent.get("text") or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out
