# Deterministic Ticker Resolution — Design

**Date:** 2026-06-07
**Branch:** `feature/sambanova`
**Status:** Deterministic core BUILT 2026-06-08 (commits 688a653, b2e0579). `tools/ticker_db.py`
(SEC+NASDAQ table, 16,687 tickers / 5,329 ETFs), `tools/ner.py` (GLiNER, threshold 0.3),
`tools/resolve.py` ladder (tier-0 raw-ticker, exact, alias, token_set fuzzy, ambiguous→refuse,
gated semantic). Verified end-to-end vs edge cases (typos, raw tickers, finance abbrevs,
renames, chitchat); Square→XYZ never VSQTF. **Deferred to the LangGraph migration:** wiring
`resolve_query` into the orchestrator (replacing Gate 1/2), the confirm tier for AMBIGUOUS
(Toyota/Ford/JPMorgan), `ticker_db.ensure_built()` at startup, and company-profile seeding
for the semantic tier.
**Supersedes:** Phase D (LLM name extraction) and Gate 2 (`tools/resolve.py` validation) of `claude/plans/2026-06-04-dual-gate-routing-ticker-validation.md`

## Problem

The planner LLM currently decides which **tickers** the agents use. LLMs hallucinate
and stale-guess symbols:

- Dead/renamed symbols: `TWTR` (Twitter went private), `SQ` (Block → XYZ), `FB` (→ META).
- Outright hallucinated symbols that never existed.
- Wrong-entity: a valid symbol for the wrong company.

Gate 2 (`validate_tickers`) catches *non-existent* symbols against the SEC set, but the
root issue remains: **an LLM is choosing symbols at all.** And the recovery path
(`resolve_name` via yfinance fuzzy search) is unsafe — `resolve_name("Square")` → `VSQTF`
(Victory Square Technologies, the wrong company), silently.

## Goal

Take symbol selection away from the LLM entirely. Establish one principle:

> **The model names the company; deterministic code looks up the ticker.**

No LLM-invented symbols on the first pass. Names are extracted by a purpose-built NER
model (GLiNER) and resolved to tickers by lookup against an authoritative local
database. Ambiguous/low-confidence cases **refuse cleanly** rather than guess wrong.

## Non-goals (YAGNI)

- **No "did you mean?" interactive confirmation in this spec.** That requires a
  pause/resume control flow; it is deferred to the LangGraph migration, where
  human-in-the-loop `interrupt()` is native. v1 behavior for ambiguity = refuse.
- **No international coverage** beyond what SEC (ADRs/filers) + US exchanges provide.
- **No commercial symbology source.** Free data only (SEC + NASDAQ Trader).
- **No replacement of Gate 1** (MAG7/FAANG group manifest) — it stays as-is.

## Architecture

```
query
 ├─ Gate 1: group manifest (MAG7/FAANG)?  ── yes ─→ expand to tickers ─→ DONE
 │                                                   (tools/groups.py, unchanged)
 ├─ verbatim tokens that ARE valid symbols ─→ keep as-is (trust user-typed AAPL)
 └─ GLiNER.extract_companies(query)  →  list[str] of NAME spans
        ├─ names found → resolve_company() ladder ①②③ ( ④ refuse in v1 )
        └─ no names    → semantic tier ⑤ over the whole query
 → final ticker list  (valid by construction: every ticker came FROM the lookup table)
```

Key property: **nothing invents a symbol.** GLiNER only ever emits *name strings*; the
only component that emits a *ticker* is a lookup against the authoritative table. This is
why the separate Gate 2 validation step becomes redundant — a resolved ticker is valid
because it came out of the table.

## Components

### 1. `tools/ticker_db.py` — the authoritative lookup table

A local DuckDB table built from two free sources, downloaded in full and deduped.

**Schema:**

```
ticker_lookup(
    symbol     TEXT,   -- uppercase, e.g. "MSFT"
    name       TEXT,   -- display name, e.g. "Microsoft Corp"
    norm_name  TEXT,   -- normalized for matching, e.g. "microsoft"
    source     TEXT,   -- "sec" | "nasdaq"
    is_etf     BOOLEAN,
    PRIMARY KEY (symbol)
)
```

**Data sources (download all, dedup on symbol):**

1. **SEC EDGAR — normal tickers.** `edgar.get_company_tickers()` (already a dependency,
   already loaded in `resolve.py`). Returns the full filer list (~10.7k) with **symbol +
   company name** (the company-name column; current code at `resolve.py:41` keeps only
   the ticker and discards the name — we stop discarding it). Covers US common stocks and
   foreign companies that file (ADRs). Does **not** reliably cover ETFs.

2. **NASDAQ Trader — ETFs (and full US-exchange listings).** Download both pipe-delimited
   files in full:
   - `nasdaqlisted.txt` — columns include `Symbol | Security Name | … | ETF (Y/N)`.
   - `otherlisted.txt` — NYSE/AMEX; columns include `ACT Symbol | Security Name |
     Exchange | … | ETF (Y/N)`.
   - Source: `https://www.nasdaqtrader.com/dynamic/SymDir/{nasdaqlisted,otherlisted}.txt`
     (FTP mirror: `ftp.nasdaqtrader.com/SymbolDirectory/`).
   - **Skip the trailing `File Creation Time…` footer line** in each file.
   - The `ETF` flag populates `is_etf`. This is the source ETFs come from, since SEC misses them.

**Dedup rule:** union both sources, key on uppercased `symbol`, **one row per symbol**.
On collision prefer the row with the cleaner/shorter display name; carry `is_etf=true` if
*either* source marks it an ETF. Record `source` for debugging.

**Normalization (`norm_name`), precomputed at build time:**
lowercase → strip punctuation → drop trailing corporate suffixes
(`inc, incorporated, corp, corporation, co, company, ltd, limited, plc, holdings, group,
the`). `"NVIDIA CORP"` → `nvidia`; `"Alphabet Inc."` → `alphabet`.

**Build & refresh:** built once into the existing DuckDB (`tools/db.py` / `DB_PATH`),
cached, refreshed on a TTL (weekly). **Fails open:** if a download fails, keep the last
cached table; if there is no table at all, resolution degrades to verbatim-symbol-only
(never crashes a query).

### 2. `tools/ner.py` — GLiNER name extraction

```
extract_companies(query: str) -> list[str]
```

- New dependency: `gliner`. Lazy-load `GLiNER.from_pretrained("urchade/gliner_medium-v2.1")`
  once via a module singleton (same pattern as `_get_encoders()` in `vector.py:20`).
- `model.predict_entities(query, labels=["company", "organization"], threshold=…)`
  returns spans with `text`, `label`, `score`. Keep the `text` of company/org spans,
  dedupe, return as `list[str]`.
- Returns the **literal span**, including typos (`"microsft"`) — spelling is fixed
  downstream by the fuzzy tier. Returns `[]` for descriptive references with no proper
  noun (`"the iPhone maker"`) — that empty result is the trigger for the semantic tier.
- **Fails open:** if the model can't load, return `[]` (pipeline falls back to semantic /
  verbatim path) and log a warning.

### 3. `tools/resolve.py` — rewritten as the resolution ladder

Replaces the current Gate 2 module. New core:

```
resolve_company(name: str) -> ResolveResult        # one name → ticker or refusal
resolve_query(query: str)  -> (tickers, unresolved) # full pipeline orchestration
```

`ResolveResult` carries the outcome: `RESOLVED(symbol)`, `AMBIGUOUS(candidates)` (v1
treats as refuse; LangGraph phase turns into a confirm prompt), or `UNRESOLVED(name)`.

The ladder for a single name (stop at first confident hit):

1. **Exact** — `WHERE norm_name = normalize(name)` → symbol. *(string, 0 risk)*
2. **Alias map** — small curated dict for common-names/renames the table can't match:
   `google→GOOGL, facebook→META, square→XYZ, twitter→XYZ`. *(string)*
3. **Fuzzy — high confidence** — `rapidfuzz` over the `norm_name` column; accept only if
   top score ≥ floor (≈90) **and** top beats #2 by a margin (≈15). Catches typos:
   `microsft → MSFT`. *(new dependency: `rapidfuzz`)*
4. **Fuzzy — medium** — a hit exists but below the confident bar, or two near-ties →
   `AMBIGUOUS`. **v1: refuse.** (LangGraph phase: confirm prompt.)
5. **Semantic (descriptive guardrail)** — only when GLiNER returned **no** name span.
   Run `search_company_profiles(query)` (already in `vector.py:138`) over the whole query
   against the company-profile embeddings in Qdrant. Accept the top symbol if score ≥
   confident floor; medium → `AMBIGUOUS` (refuse in v1); low → `UNRESOLVED`. Catches
   `"the iPhone maker"` → AAPL.

**Verbatim-symbol rule (kept from current `resolve_entities`, `resolve.py:100`):** before
NER, scan query tokens; if a token *is* a symbol present in the lookup table, trust it
directly (user typed `AAPL`). Only *names* go through GLiNER + the ladder.

### 4. Semantic tier infra (already exists — wiring only)

`tools/vector.py` already has `COMPANY_PROFILES_COLLECTION`, `upsert_company_profile()`,
and `search_company_profiles()`. Remaining work: ensure company profiles are populated for
the universe we care about (lazy upsert on first sighting / batch seed), and gate results
by score. No new collection or model.

### 5. Orchestrator integration (`orchestrator.py`)

- The planner LLM is **slimmed to intent + agent routing only** — its `tickers` output is
  no longer trusted/used for symbol selection.
- After the plan: `Gate 1 (groups)` → `verbatim symbols` → `resolve_query(user_input)`
  produces the ticker list. Replaces the current Gate 1 + Gate 2 blocks
  (`orchestrator.py:124–150`).
- If `resolve_query` yields no tickers and none were verbatim/group, set
  `agents_to_run = []` and let synthesis explain cheaply (same skip-agents behavior the
  current Gate 2 has at `orchestrator.py:148`).

## Error handling

Every external/optional component **fails open** so a query never crashes on reference
data:

| Failure | Behavior |
|---|---|
| NASDAQ download fails | keep last cached table |
| SEC feed fails | keep last cached table |
| No lookup table at all | verbatim-symbol-only resolution |
| GLiNER model can't load | `extract_companies` returns `[]` → semantic/verbatim path |
| Qdrant/semantic down | semantic tier returns nothing → `UNRESOLVED` (refuse), no crash |
| Ambiguous (tier 4 / medium tier 5) | **refuse** with a clear message (v1) |

## Testing

TDD, run with `C:\Users\Yatta\miniconda3\envs\stock\python.exe -m pytest`. Per project
rule, no paid SambaNova in tests — GLiNER/rapidfuzz/DuckDB/Qdrant are all local.

- `tests/test_ticker_db.py` — build table from fixture SEC + NASDAQ rows; assert dedup on
  symbol, `is_etf` set from NASDAQ, `norm_name` strips suffixes, fail-open on bad download.
- `tests/test_ner.py` — `extract_companies` returns expected spans for direct names,
  typos, multi-company; returns `[]` for descriptive phrasing.
- `tests/test_resolve.py` (rewrite) — ladder per tier: exact, alias, fuzzy-high accepts
  `microsft→MSFT`, fuzzy-medium refuses, **`square` refuses (never VSQTF)**, verbatim
  `AAPL` trusted, semantic `"the iPhone maker"→AAPL` (mock `search_company_profiles`).
- `tests/test_orchestrator.py` (extend) — planner tickers ignored; resolution drives the
  dispatched list; all-unresolved → `agents_to_run == []`.

## What this retires

- `tools/resolve.py` `resolve_name()` (unsafe yfinance fuzzy) — **deleted**.
- Gate 2 `validate_tickers` as a separate step — **absorbed** (table membership = validity).
- Planner LLM `tickers` field — **ignored** (kept in prompt only if harmless; ideally
  dropped from the plan schema).
- Phase D (LLM name extraction) from the dual-gate plan — **superseded** by GLiNER.

## Deferred to the LangGraph migration

- The **confirm tier**: turn `AMBIGUOUS` into a human-in-the-loop `interrupt()` —
  "Which company did you mean — Microsoft (MSFT) or MicroStrategy (MSTR)?" — and resume on
  the user's reply. Native in LangGraph; clumsy before it. This is a motivating use case
  for the migration, not a blocker for shipping the deterministic core.

## New dependencies

- `gliner` (+ its torch/transformers stack) — local NER.
- `rapidfuzz` — fast fuzzy string matching for tier 3.

(`edgar`, `duckdb`, `qdrant-client[fastembed]` already present.)

## Open questions

1. Exact column name for the company name in `edgar.get_company_tickers()` output —
   confirm at implementation (`title`/`company`).
2. Fuzzy thresholds (floor ≈90, margin ≈15) — tune against a small labeled set of real
   queries during implementation.
3. Company-profile coverage for the semantic tier — seed strategy (batch vs lazy upsert).
