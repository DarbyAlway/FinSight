# FinSight — Multi-Agent Financial Research Assistant

Ask stock-market questions in plain English. FinSight plans the work, dispatches specialist
AI agents in parallel to fetch **real SEC filings and market data**, synthesizes an answer —
and then **verifies every number in that answer against the fetched source data before you
see it**.

> LLMs confidently state financial figures from their training data instead of the documents
> in front of them. FinSight treats that as an engineering problem, not a prompting problem:
> a deterministic verifier traces each figure back to source, and unverifiable answers are
> corrected, re-grounded from the web, or explicitly disclosed — never shipped silently.

```
You: What was Apple's revenue in FY2024 and FY2023?

Assistant: Apple's revenue was $391.0B for FY2024 (ended September 28, 2024)
and $383.3B for FY2023 (ended September 30, 2023), per Apple Inc. 10-K income
statements.

  [fidelity] checked answer: 0 untraced unit-bearing number(s)
```

## Architecture

```
user question
    │
    ▼
planner LLM ──→ intent + agents + tickers     (keyword fallback if plan malformed)
    │
    ▼
gates: group-manifest expansion (MAG7/FAANG) + SEC-filer ticker validation
    │
    ▼
parallel agent fan-out (LangGraph Send API + state reducers)
    ├─ financials agent  → SEC EDGAR income / balance sheet / cash flow / 8-K
    ├─ news agent        → market news + Qdrant vector recall
    ├─ calc agent        → CAGR, FCF, runway, PEG, DCF, correlation, ranking
    └─ ratios agent      → margins, D/E, ROA/ROE, liquidity, interest coverage
    │
    ▼
synthesis LLM ──→ answer grounded ONLY in agent outputs
    │
    ▼
fidelity verifier → self-critique → web escalation → disclosure caveat
    │
    ▼
final answer + cited sources
```

The whole turn runs as a **LangGraph `StateGraph`** — 11 nodes, conditional retry edges,
parallel agent dispatch via the Send API, and **SQLite checkpointing**: a turn that crashes
mid-flight resumes from the failed node without re-fetching completed agent work.

## The anti-hallucination pipeline

Detection is fully deterministic — no LLM judging another LLM:

1. **Extract & verify** (`tools/fidelity.py`): every unit-bearing number in the answer
   (currencies incl. word forms like "$391 billion", percentages, ratios) is regex-extracted,
   bound to its nearest fiscal year, and checked against the agents' raw tool outputs
   (±1% tolerance, year-scoped).
2. **Classify**: a figure that exists in *no* fetched year — or is bound to a never-fetched
   year — is **HARD** evidence of fabrication. A real value with a wrong year label is
   **soft** and only flagged (re-prompting on those caused churn without accuracy gains).
3. **Self-critique**: on HARD misses, the model is re-prompted with its own answer plus the
   offending figures and must rewrite using only the agent outputs.
4. **Web escalation**: if fabricated figures survive the critique, the agents demonstrably
   can't support the answer — FinSight re-answers from live web search with cited sources.
5. **Disclosure**: if the web has nothing either, the answer ships with an explicit
   *"these figures could not be verified"* caveat.

Caught live: the model answered with Microsoft FY2020/FY2019 revenue — *correct* numbers
from its training data — when only FY2023–25 had been fetched. The verifier flagged both
figures; the user never saw them. Fidelity results are exported as a Langfuse score, so
hallucination frequency is a tracked metric.

## More engineering under the hood

- **Deterministic ticker resolution** — no LLM ticker guessing. GLiNER extracts company
  names; a DuckDB table built from SEC + NASDAQ feeds (16,687 tickers, 5,329 ETFs) resolves
  them through a 5-tier ladder: exact → alias → fuzzy (rapidfuzz) → ambiguity refusal →
  embedding-gated semantic match.
- **Data integrity below the LLM**: Pydantic schemas validate every parsed statement row;
  margin sanity rules and a balance-sheet identity check (Assets = Liabilities + Equity,
  minority-interest aware) reject bad parses before any model sees them.
- **Observability**: self-hosted Langfuse v3 (Docker Compose: Postgres, ClickHouse, Redis,
  MinIO) with OpenTelemetry auto-instrumentation — one nested trace per turn, per-call
  token/latency/cost accounting.
- **Cost engineering**: compact fetch confirmations cut re-billed statement dumps; the
  synthesis model was selected by an A/B evaluation harness (`eval_models.py`), not vibes.
- **305 automated tests** with a real-data policy: data-path tests hit real EDGAR filings,
  and every live failure becomes a pinned regression test.

## Quick start

**Prerequisites:** Python 3.11+, Docker (for Qdrant and the optional Langfuse stack).

```bash
# 1. Install
pip install -r requirements.txt

# 2. Infrastructure (Qdrant vector DB; Langfuse stack optional)
docker compose up -d qdrant

# 3. Configure — create .env
SAMBANOVA_API_KEY=...        # or run fully local via Ollama
TAVILY_API_KEY=...           # web-search fallback (optional, degrades gracefully)
LANGFUSE_PUBLIC_KEY=...      # optional — tracing
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://localhost:3000

# 4. Set your SEC EDGAR identity (required by SEC fair-use policy)
#    edit set_identity("yourname@email.com") in main.py

# 5. Chat
python main.py
```

Personas: `/persona <name|panel|off>` switches the answer style (e.g. a multi-viewpoint
investor panel).

## Tests

```bash
pytest          # 305 tests; 4 vector tests need the Qdrant container running
```

## Project structure

```
orchestrator.py        # LangGraph StateGraph: planner, gates, fan-out, synthesis, fidelity chain
graph_state.py         # turn state schema + merge reducers for parallel agents
agents/                # financials / news / calc / ratios + shared tool-calling loop
tools/                 # 21 modules: EDGAR parsers, fidelity verifier, ticker resolution,
                       #   Pydantic schemas, vector store, web-search guardrails, LLM client
prompts.py             # planner / synthesis / persona prompts
tests/                 # 305 tests (real-data policy)
docker-compose.yml     # Qdrant + self-hosted Langfuse v3 stack
```

## Roadmap

- Structured planner output (constrained JSON schema) with name-grounded ticker resolution
- Query decomposition for multi-part questions
- Human-in-the-loop ticker disambiguation (LangGraph `interrupt()`)
- Streaming responses

## Tech stack

Python · LangGraph · OpenAI-compatible APIs (SambaNova: gpt-oss-120b, Llama-3.3-70B) ·
Ollama · SEC EDGAR (edgartools) · yfinance · Tavily · Qdrant · DuckDB · SQLite · Pydantic ·
GLiNER · rapidfuzz · Langfuse (self-hosted) · OpenTelemetry · pytest · Docker
