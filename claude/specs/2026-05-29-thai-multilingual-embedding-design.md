# Thai Language Support — Multilingual Embedding Design

**Date:** 2026-05-29
**Branch:** feature/thai-multilingual-embedding
**Status:** Approved for implementation

---

## Motivation

Thai users can ask questions in Thai (e.g. "AAPL รายได้เท่าไหร่?"). The LLMs (Groq llama-3.3-70b, Ollama qwen3:14b) already understand and respond in Thai natively — no changes needed there. The only gap is the news vector search: the current embedding model (`bge-large-en-v1.5`) is English-only and cannot match Thai queries against English articles.

Data sources remain US/English only. Thai support means Thai users can query in Thai and receive Thai responses — not Thai data.

---

## Scope

| Component | Change |
|---|---|
| `tools/config.py` | `DENSE_MODEL`: `bge-large-en-v1.5` → `bge-m3` |
| `tools/vector.py` | Update comment only (no logic change) |
| `orchestrator.py` | Add Thai financial keywords to `_FINANCIAL_KEYWORDS` |
| Qdrant collections | Wipe once on deploy — rebuild naturally on next user query |

**Out of scope:** Thai news sources, Thai data providers, prompt translation.

---

## Section 1: Embedding model change

`bge-m3` (BAAI) is a multilingual model that handles cross-lingual retrieval — Thai query matches English documents correctly. It outputs **1024-dim vectors**, identical to `bge-large-en-v1.5`, so:

- Qdrant collection schema is unchanged
- `DENSE_DIM = 1024` in `tools/vector.py` is unchanged
- Hybrid search logic is unchanged
- `SPARSE_MODEL = "Qdrant/bm25"` is unchanged

**One line changes in `tools/config.py`:**
```python
DENSE_MODEL = "BAAI/bge-m3"   # was: BAAI/bge-large-en-v1.5
```

---

## Section 2: Qdrant wipe

Existing vectors were built with the English model and are incompatible with bge-m3's embedding space. Collections must be wiped once after the model change.

**How:** A `wipe_and_reinit_collections()` helper drops both collections and calls `init_qdrant()` to recreate them empty. Data repopulates automatically as users query tickers — `store_articles` and `upsert_company_profile` re-embed with the new model on next use.

No migration script. No batch re-embedding. On-demand rebuild.

---

## Section 3: Thai routing keywords

`_is_conversational()` in `orchestrator.py` checks English keywords. Queries containing a stock ticker (`[A-Z]{1,5}`) already route correctly. Adding Thai financial keywords covers pure-Thai queries without a ticker:

```python
"รายได้", "กำไร", "หุ้น", "งบการเงิน", "ราคา", "ปันผล", "ข่าว", "นักวิเคราะห์", "ตลาด"
```

These are added to the existing `_FINANCIAL_KEYWORDS` set — no structural change.

---

## What stays unchanged

- All 4 agents (no prompt changes — LLMs respond in Thai automatically)
- Qdrant collection schema and hybrid search logic
- All SEC/yfinance data fetching
- `DENSE_DIM = 1024`
- `SPARSE_MODEL`
- News sources (US English only)
