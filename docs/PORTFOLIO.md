# NYSE Analysis — Multi-Agent Financial Research Assistant

**Portfolio write-up** · Python · LangGraph · LLM orchestration · May–June 2026 · 185 commits · 305 automated tests

---

## One-liner (for the CV header)

> Built a production-grade multi-agent LLM system that answers financial research questions from real SEC filings, with a deterministic anti-hallucination pipeline that verifies every number the model outputs against the fetched source data.

**Plain-English version (for recruiters / non-technical readers):**

> Built an AI assistant that answers stock-market questions using companies' official financial reports — and automatically fact-checks every number in its own answers, because AI chatbots are known to confidently make figures up.

---

## Plain-English summary (read this first if you're not an engineer)

**What it does:** You ask a question in normal English — *"How much money did Apple make last year?"* or *"Compare the big tech companies on profitability."* The assistant looks up the answer in companies' official financial filings (the audited reports every US public company must submit to the government) and replies in seconds, with sources.

**The problem it solves:** AI chatbots like ChatGPT often state financial figures that are simply wrong — they "remember" old numbers from their training instead of looking up real ones, and they say them confidently. For financial information, a confidently wrong number is worse than no answer.

**How this project fixes that — in three steps:**
1. **Look it up, don't recall it.** The AI is never allowed to answer from memory. A team of four specialized AI "workers" fetches real data: one reads official financial reports, one gathers news, one does the math (growth rates, valuations), one computes financial health ratios. They work simultaneously, so answers stay fast.
2. **Fact-check the answer.** Before anything reaches the user, a separate checking program (not AI — ordinary, predictable code) extracts every number from the answer and verifies it appears in the data that was actually fetched.
3. **Catch and correct.** If a number can't be verified, the AI is told to rewrite its answer using only real data. If it still can't be supported, the system searches the live web for the answer — and if even that fails, it openly tells the user which figures couldn't be verified instead of hiding it.

**Proof it works:** During real use, the AI tried to state Microsoft revenue figures from years it had never looked up — the fact-checker caught it and the wrong numbers never reached the user. The whole system is covered by 305 automated tests that run on every change, and if the program crashes mid-answer, it can resume where it stopped instead of starting over.

**Scale of the work:** Solo project · 185 code contributions over ~4 weeks · 4 AI agents · 24 distinct data tools · searchable database of 16,687 stock tickers · full monitoring dashboard tracking cost, speed, and accuracy of every AI call.

---

## What it is

A conversational stock-analysis assistant. A user asks questions in plain English ("What was Apple's revenue in FY2024 and FY2023?", "Compare the MAG7 on free cash flow") and the system plans the work, dispatches specialist agents in parallel, fetches real data from SEC EDGAR and market APIs, synthesizes an answer, and then **proves the answer's numbers are traceable to the fetched data before shipping it**.

## Architecture

```
user question
    │
    ▼
planner LLM ──→ intent + agents + tickers   (keyword fallback if the plan is malformed)
    │
    ▼
gates: group-manifest expansion (MAG7/FAANG) + SEC-filer ticker validation
    │
    ▼
parallel agent fan-out (LangGraph Send API + state reducers)
    ├─ financials agent  → SEC EDGAR income statement / balance sheet / cash flow
    ├─ news agent        → market news + Qdrant vector recall
    ├─ calc agent        → derived metrics (FCF, cash burn, runway, correlation)
    └─ ratios agent      → liquidity / leverage / margin ratios
    │
    ▼
synthesis LLM ──→ answer grounded ONLY in agent outputs
    │
    ▼
fidelity verifier (deterministic) ──→ self-critique ──→ web escalation ──→ disclosure caveat
    │
    ▼
final answer + cited sources
```

- **4 specialist agents**, each running its own tool-calling loop against typed tools (21 tool modules).
- **Orchestration as a LangGraph `StateGraph`**: 11 nodes, 6 conditional routes, parallel agent dispatch via the Send API with dict-merge/token-sum reducers, SQLite checkpointing so a crashed turn resumes without re-fetching completed agent work.
- **Data layer**: SEC EDGAR filings (edgartools) with SQLite caching + TTL, yfinance prices/news, Tavily web search with guardrails (advanced search depth, recency filters, mandatory source citation).
- **Ticker resolution**: GLiNER NER extracts company names; a DuckDB lookup table built from SEC + NASDAQ feeds (16,687 tickers, 5,329 ETFs) resolves them through a 5-tier ladder — exact → alias → fuzzy (rapidfuzz token-set) → ambiguity refusal → embedding-gated semantic match — replacing unsafe LLM ticker guessing (which had produced FB→wrong ETF and BABA-in-MAG7 errors live).
- **Vector memory**: Qdrant collections for news articles and company profiles (semantic recall + the resolution ladder's semantic tier).
- **LLM layer**: provider-agnostic client (SambaNova cloud — gpt-oss-120b / Llama-3.3-70B — and local Ollama), with an A/B evaluation harness used to select the synthesis model on measured accuracy and cost.

## Engineering highlight 1 — Deterministic anti-hallucination pipeline

The hardest problem: the synthesis LLM occasionally answered with figures from its training data instead of the fetched filings (observed live: fabricated MSFT FY2020/FY2019 revenue, fabricated week-over-week price moves). Prompting alone did not fix it. The solution is a **detect → correct → escalate → disclose** chain where detection is fully deterministic:

1. **Fidelity verifier** (`tools/fidelity.py`): regex-extracts every unit-bearing number from the answer (currencies with magnitude suffixes and word forms, percentages, ratios), binds each to its nearest fiscal year, and checks it against the agents' raw tool outputs with ±1% tolerance — year-scoped.
2. **HARD vs SOFT classification**: a figure that exists in *no* fetched year (or is bound to a never-fetched year) is HARD evidence of fabrication; a real value with a wrong year label is SOFT and only flagged — re-prompting on those caused churn without improving accuracy.
3. **One grounded self-critique**: on HARD misses the model is re-prompted with its own answer plus the offending figures and required to rewrite using only agent outputs.
4. **Web escalation**: if fabricated figures *survive* the critique, the agents demonstrably cannot support the answer — the system re-answers from live web search with cited sources.
5. **Disclosure**: if the web has nothing either, the answer ships with an explicit "these figures could not be verified" caveat instead of shipping silently.

False-positive patterns (multi-figure sentences, "respectively" enumerations, header-line dates in cash-flow statements) were found via live testing against real filings and fixed with proximity/positional year-binding — each one locked in with a regression test. Fidelity results are exported as a Langfuse score, so hallucination frequency is a measurable metric, not an anecdote.

## Engineering highlight 2 — Zero-regression LangGraph migration

Migrated the orchestrator from a hand-rolled loop (ThreadPoolExecutor fan-out, nested if/else retry logic) to a LangGraph `StateGraph` with a **parity-first strategy**: the legacy implementation stayed in place as the executable specification while nodes and routes were transplanted one task at a time, each gated by the full 300+ test suite. The conditional-retry behaviors (web fallback, fidelity critique, escalation) became explicit graph edges.

- Behavioral parity was enforced down to log strings and token accounting; review caught and fixed three subtle divergences (a skipped fidelity score on the empty-critique path, an escalation edge that bypassed verification when web search returned nothing, a resume API that silently re-ran the whole turn).
- **Crash-resume**: SQLite checkpointing with per-turn thread IDs; a crashed turn resumed on the same thread continues from the failed node without re-fetching agent data (proven by a kill-at-synthesis regression test).
- **Observability preserved**: verified live that Langfuse traces stay correctly nested (one trace per turn, agent spans under the orchestrator) across LangGraph's worker threads.

## Engineering highlight 3 — Data integrity at the parser layer

Financial data is validated before any LLM sees it: Pydantic schemas reject malformed statement rows, margin sanity rules (gross ≤ 100%, operating ≤ gross), and a balance-sheet identity check (Assets = Liabilities + Equity, minority-interest aware) — validated against ~21 real filings with zero false rejections.

## Testing & process

- **305 automated tests**, run on every change. Policy: tests exercise **real data** (live EDGAR fetches, real filings) rather than synthetic fixtures, and every live failure becomes a pinned regression test.
- Token/latency accounting per LLM round; cost-driven model selection (the synthesis model switch was decided by an A/B harness, not vibes).
- Spec-driven workflow: design specs and reviewed implementation plans precede code; every task passed independent spec-compliance and code-quality review before merging.

## Complete tool inventory

### Agent-callable tools (LLM function-calling, OpenAI tool schema)

Each agent runs `run_tool_loop` (`agents/_tooling.py`) — a multi-round tool-calling loop with per-call error capture, loop guardrails, and raw tool-output capture for the fidelity verifier.

**Financials agent** (5 tools — SEC filings & market snapshot):
| Tool | What it does |
|---|---|
| `get_income_statement` | 3-year annual income statement from SEC 10-K filings |
| `get_quarterly_statement` | Quarterly income statement from SEC 10-Q filings |
| `get_cash_flow_statement` | 2-year cash flow statement from SEC 10-K filings |
| `get_company_info` | Live market metrics: price, market cap, trailing/forward P/E, beta, analyst targets, sector |
| `get_earnings_press_release` | Latest earnings press release (8-K exhibit) |

**News agent** (2 tools):
| Tool | What it does |
|---|---|
| `get_stock_news` | Recent news for a ticker (yfinance), stored to Qdrant for recall |
| `search_news` | Semantic search over previously stored articles (vector similarity) |

**Calc agent** (15 tools — derived metrics & valuation):
| Tool | What it does |
|---|---|
| `get_company_info` / `get_income_statement` / `get_cash_flow_statement` / `get_balance_sheet` / `get_price_history` | Data-fetch tools that populate the cache the calculators read from (compact-confirmation variants to cut token cost) |
| `calculate_revenue_cagr` | Revenue CAGR over N years |
| `calculate_margin_trend` | Gross/net margin trend by year |
| `calculate_yoy` | Year-over-year change for any income-statement metric |
| `calculate_free_cash_flow` | FCF from operating cash flow − capex |
| `calculate_cash_runway` | Cash runway from burn rate + cash balance |
| `calculate_peg` | PEG ratio (P/E ÷ EPS growth) |
| `calculate_dcf` | 5-year DCF valuation |
| `calculate_pe_vs_sector` | P/E vs. sector peers |
| `calculate_correlation` | Price-return correlation between 2+ tickers |
| `rank_tickers` | Rank tickers by any financial metric |

**Ratios agent** (8 tools — financial-health ratios):
| Tool | What it does |
|---|---|
| `get_income_statement` / `get_company_info` / `get_balance_sheet` | SEC/market data fetch (shared implementations) |
| `calculate_all_margins` | Gross / operating / net margins (with sanity validation) |
| `calculate_debt_to_equity` | Leverage |
| `calculate_roa_roe` | Return on assets / equity |
| `calculate_current_ratio` | Liquidity |
| `calculate_interest_coverage` | Solvency |

30 tool registrations total (24 unique functions; data-fetch tools are shared across agents with per-agent descriptions tuned to each agent's workflow).

### Supporting modules (`tools/`, 21 modules)

| Module | Responsibility |
|---|---|
| `income.py` / `balance_sheet.py` / `cash_flow.py` / `earnings_press.py` | SEC EDGAR 10-K/10-Q/8-K parsers (edgartools) with SQLite caching + TTL |
| `company.py` / `price.py` / `news.py` | Market snapshot, price history, news (yfinance) |
| `calc.py` / `ratios.py` | Derived-metric and ratio calculators (pure, cache-fed) |
| `fetch_compact.py` | Token-cost optimization: compact fetch confirmations instead of full statement dumps |
| `fidelity.py` | Deterministic number-fidelity verifier (extraction, year binding, HARD/soft classification) |
| `schemas.py` | Pydantic data-integrity layer (statement rows, margin sanity, balance-sheet identity) |
| `groups.py` | Canonical index-group manifests (MAG7, FAANG, …) overriding LLM expansion |
| `ticker_db.py` | SEC + NASDAQ ticker lookup table in DuckDB (16,687 tickers, 5,329 ETFs) |
| `ner.py` | GLiNER company-name extraction (fail-open) |
| `resolve.py` | 5-tier deterministic ticker-resolution ladder + SEC-filer validation |
| `vector.py` | Qdrant collections: news articles + company profiles (embedding search) |
| `search_guardrails.py` | Tavily web search with uncertainty detection, recency filters, source citation |
| `llm.py` | Provider-agnostic LLM client (SambaNova / Ollama) with Langfuse tracing |
| `db.py` / `config.py` | SQLite cache layer, model/provider configuration |

## Tech stack

**Language & core:** Python 3 · pandas · numpy · matplotlib

**LLM & agents:** LangGraph (StateGraph, Send API, conditional edges, SQLite checkpointing) · OpenAI SDK against OpenAI-compatible APIs — SambaNova cloud (gpt-oss-120b, Llama-3.3-70B) and local Ollama · OpenAI function-calling tool schemas · GLiNER (zero-shot NER)

**Data sources & APIs:** SEC EDGAR via edgartools (10-K / 10-Q / 8-K parsing) · yfinance (prices, market metrics, news) · gnews · Tavily (web search SDK)

**Storage & search:** SQLite (data cache + graph checkpoints) · DuckDB (16k-row ticker lookup table) · Qdrant vector DB with fastembed embeddings (news + company-profile collections, semantic search)

**Quality & validation:** Pydantic v2 (statement schemas, accounting-identity checks) · rapidfuzz (token-set fuzzy matching) · pytest (305 tests, real-data policy) · custom deterministic fidelity verifier

**Observability & ops:** Langfuse v3 — **self-hosted** via Docker Compose (Postgres, ClickHouse, Redis, MinIO services) · OpenTelemetry / OpenInference auto-instrumentation of LLM calls · Arize Phoenix (earlier tracing backend, kept compatible) · per-call token & latency accounting · Docker (Qdrant + Langfuse stack)

**One-line version (for the CV):** Python · LangGraph · OpenAI-compatible LLM APIs (SambaNova/Ollama) · SEC EDGAR · Qdrant · DuckDB · SQLite · Pydantic · GLiNER · Langfuse (self-hosted) · OpenTelemetry · pytest · Docker

---

## Ready-to-paste CV bullets

**Project title:** Multi-Agent Financial Research Assistant (Python, LangGraph, LLM orchestration)

How to use this section: each bullet below follows the *action verb → what you built → quantified evidence* pattern recruiters scan for. Under each one, **Demonstrates** lists the competencies the bullet signals (useful for matching against a job posting's keywords), and **Interview backup** is the concrete story to tell when asked "tell me more about that" — every claim is traceable to this repo, so you can walk an interviewer through the actual code.

### Full version (6 bullets)

**1.** *Built a multi-agent LLM system that answers financial research questions from real SEC filings: a planner LLM routes queries to 4 specialist agents (financials, news, derived metrics, ratios) running parallel tool-calling loops over SEC EDGAR, market data, and web search.*

- **Demonstrates:** LLM orchestration, agentic system design, function calling / tool use, parallel execution, API integration.
- **Interview backup:** Walk through the architecture diagram — planner intent classification, the two validation gates, Send-API fan-out, synthesis. Mention the 30 tool registrations (24 unique functions) and that shared fetch tools carry per-agent descriptions tuned to each agent's workflow — a real prompt-engineering detail.

**2.** *Designed a deterministic anti-hallucination pipeline that regex-extracts every figure from model answers and verifies it against fetched source data (year-bound, ±1% tolerance), then escalates through grounded self-critique → web re-answer → explicit disclosure; caught and corrected real fabricated revenue figures in production use.*

- **Demonstrates:** The differentiator bullet. LLM reliability engineering, grounding/verification beyond prompting, layered defense design, metric-driven quality (hallucination rate as a Langfuse score).
- **Interview backup:** The MSFT story — the model answered with FY2020/FY2019 revenue ($143,015M/$125,843M, correct numbers from its *training data*) when only FY2023–25 had been fetched. Prompt rules alone didn't stop it. Explain HARD vs SOFT classification and why SOFT (right value, wrong year label) is flag-only: re-prompting on those caused churn without accuracy gains. Also: the false positives (multi-figure sentences, "respectively" enumerations) were found by testing against real filings, not synthetic data — each became a regression test.

**3.** *Migrated a hand-rolled async orchestration loop to a LangGraph StateGraph (11 nodes, conditional retry edges, Send-API parallel fan-out, SQLite crash-resume checkpointing) with a parity-first strategy that kept all 300+ tests green throughout — zero behavioral regressions.*

- **Demonstrates:** Refactoring at scale, migration strategy, modern agent frameworks (LangGraph), state-machine design, checkpointing/durability.
- **Interview backup:** The parity-first method is the story: the legacy loop stayed in the codebase as the executable spec while nodes were transplanted one reviewed task at a time, with behavior matched down to log strings and token accounting. Reviews caught three real parity bugs before merge (a skipped fidelity score on one path, an escalation edge that bypassed verification, and a resume API that silently re-ran the whole turn and double-counted tokens). The crash-resume proof: a kill-at-synthesis test that resumes on the same thread ID without re-fetching agent data.

**4.** *Eliminated LLM ticker-guessing errors with a deterministic resolution ladder: GLiNER named-entity extraction + a 16k-ticker SEC/NASDAQ DuckDB lookup table + fuzzy and embedding-gated semantic matching, with explicit refusal on ambiguity.*

- **Demonstrates:** Knowing when *not* to use an LLM — replacing probabilistic guessing with deterministic lookup. NER, fuzzy matching, vector search, failure-mode analysis.
- **Interview backup:** The incidents that motivated it: the planner expanded "FB" to a wrong ETF, put BABA in MAG7, and naive name resolution mapped "Square" to VSQTF (an unrelated company). Each ladder tier exists because a simpler tier failed on a real query; ambiguity (Toyota? Ford? JPMorgan?) refuses rather than guesses.

**5.** *Enforced data integrity below the LLM layer with Pydantic statement validation, margin sanity rules, and balance-sheet identity checks (Assets = Liabilities + Equity, minority-interest aware) — validated against ~21 real filings with zero false rejections; instrumented the full pipeline with Langfuse tracing (nested spans per agent, per-call token/latency accounting).*

- **Demonstrates:** Data engineering rigor, domain modeling (accounting identities), observability/LLMOps, cost awareness.
- **Interview backup:** The principle: garbage data poisons every downstream LLM step, so validation happens at the parser, not the prompt. Token accounting fed real decisions — e.g., compact fetch confirmations (`fetch_compact.py`) cut re-billed statement dumps, and the synthesis-model switch (Llama-3.3-70B → gpt-oss-120b) was decided by an A/B harness on accuracy and cost, not preference.

**6.** *Maintained 305 automated tests run on every change, with a real-data policy (live SEC EDGAR fetches, real filings — no synthetic fixtures for data paths) and every live failure converted into a pinned regression test.*

- **Demonstrates:** Testing discipline, regression culture, CI mindset.
- **Interview backup:** Two live bugs that unit tests missed but real-data tests caught: the multi-figure year-binding false positive, and cash-flow statements carrying dates on header lines (which silently broke year extraction). Both are now permanent tests.

### Short version (2 bullets, space-constrained CVs)

- *Built a multi-agent LLM financial research assistant (Python, LangGraph) over SEC EDGAR data: planner-routed parallel agents, crash-resumable graph orchestration, full Langfuse observability, 305 tests.*
- *Designed a deterministic hallucination-verification pipeline that traces every number in a model's answer back to fetched source data and escalates (self-critique → web search → disclosure) when figures can't be verified — turning LLM accuracy into a measured metric.*

### Recruiter-friendly version (plain language, keeps the keywords HR scans for)

Use these when the first reader is HR or a non-technical hiring manager; they keep the searchable keywords (Python, AI, LLM, testing) but drop the engineering jargon:

- *Built an AI assistant (Python) that answers stock-market questions from companies' official SEC financial reports, using a team of 4 specialized AI agents working in parallel.*
- *Solved the biggest problem with AI chatbots — confidently making up numbers — by adding an automatic fact-checker that verifies every figure in the AI's answer against the real source data before the user sees it; it caught genuine fabricated revenue figures during live use.*
- *Upgraded the system's core to a modern AI workflow framework (LangGraph) with zero disruption — all 300+ automated tests kept passing throughout the rewrite.*
- *Quality discipline: 305 automated tests using real financial filings, full cost and accuracy monitoring of every AI call, and crash recovery that resumes interrupted work instead of starting over.*

### One-bullet version (when the project is one line among many)

- *Multi-agent LLM financial research assistant (Python, LangGraph, SEC EDGAR): parallel tool-calling agents with a deterministic number-verification pipeline that catches and corrects model hallucinations; 305 tests, full tracing.*

### Tailoring guide — which bullets to lead with, by role

| Target role | Lead with | Why |
|---|---|---|
| AI/ML engineer, LLM engineer | 2, 3, 1 | Reliability engineering and agent frameworks are the differentiators; everyone has "built a RAG app" |
| Backend / general SWE | 3, 6, 5 | Migration discipline, testing culture, and data integrity translate to any stack |
| Data engineer | 5, 4, 6 | Parser-level validation, deterministic resolution, real-data testing |
| Fintech | 1, 5, 2 | Domain fluency (10-K/10-Q parsing, accounting identities) plus LLM safety |
| MLOps / platform | 5, 3, 6 | Observability, checkpointing, cost instrumentation |

### Writing notes (if you edit the bullets)

- Keep one number per bullet minimum — quantified bullets get read ("305 tests", "16k tickers", "±1% tolerance", "zero regressions").
- Past tense, no "I"; start with a strong verb (Built / Designed / Migrated / Eliminated / Enforced).
- Bullet 2 is your signature claim — never cut it. If space forces a choice, cut 4 or 6 first.
- Everything here is verifiable in the repo; don't inflate numbers when tailoring, since this project holds up well to deep technical questioning as-is.
