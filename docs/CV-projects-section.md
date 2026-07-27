# Revised PROJECTS section for "Pattaranon AI Engineer" CV

Paste-ready replacement. Changes: Kadman Market Management and Food Search & Recommendation
removed (not AI-engineering work); FinSight added on top as the flagship project.
Format matches the existing CV exactly: **Name** | Role [GitHub] · dates · bullets · Tech Stack line.

---

## PROJECTS

**FinSight — Multi-Agent Financial Research Assistant** | Solo AI Project [GitHub] May 2026 – Jun 2026

- Built a multi-agent LLM system that answers financial research questions from real SEC
  filings — a planner LLM routes queries to 4 specialist agents (financials, news,
  calculations, ratios) running parallel tool-calling loops over 24 tools.
- Designed a deterministic anti-hallucination pipeline that extracts every figure from the
  model's answer and verifies it against the fetched source data, escalating through
  grounded self-critique → web re-answer → explicit disclosure; caught real fabricated
  revenue figures during live use.
- Migrated orchestration to a LangGraph StateGraph (11 nodes, conditional retry edges,
  parallel fan-out, SQLite crash-resume checkpointing) with zero behavioral regressions
  across a 300+ test suite.
- Replaced LLM ticker guessing with a deterministic resolution ladder (GLiNER NER +
  16,000-ticker SEC/NASDAQ lookup + fuzzy/semantic matching) and instrumented the full
  pipeline with self-hosted Langfuse tracing — per-call token, latency, and cost
  accounting plus a measurable hallucination-rate score.
- Shipped the system as a full-stack web app — a FastAPI backend streaming live pipeline
  stages to a React/TypeScript chat UI over Server-Sent Events, with Postgres-backed chat
  persistence, Argon2 cookie-session auth, and per-user token quotas plus a global
  kill-switch.
- Cut end-to-end query latency ~24× by routing specialist agents to fast Gemma models and
  synthesis to Llama on SambaNova, and running each round's tool calls concurrently.

*Tech Stack: Python, LangGraph, FastAPI, React, TypeScript, Tailwind, SSE, SambaNova/Ollama LLMs, SEC EDGAR, Qdrant, DuckDB/Postgres, Pydantic, GLiNER, Langfuse, Docker, Pytest*

---

**GlossAI** | Full-Stack Side Project [GitHub] Mar 2026 – Apr 2026

- Built a full-stack application that automatically transcribes uploaded videos and extracts
  key vocabulary using locally-run AI — eliminating cloud API costs entirely.
- Integrated Whisper for speech-to-text transcription and local LLMs via Ollama for
  intelligent vocabulary extraction and language learning support.

*Tech Stack: React, FastAPI, Ollama, Local LLMs, spaCy, Whisper*

---

## Removed (and why)

- **Kadman Market Management** — backend/CRUD platform (Flask, MySQL, LINE API); no AI
  content. On a CV titled "AI Engineer" it dilutes the narrative.
- **Food Search & Recommendation System** — primarily a full-stack search platform; the
  only ML is LightGBM image auto-fill. BORDERLINE: restore it as a third project if the
  page looks sparse — its Elasticsearch/retrieval angle complements RAG experience. If
  restored, consider reframing the title toward "Search & Recommendation" relevance.

## Before sending the CV

1. **Push the branch** — DONE. All work is merged to `master` (now the repo's default
   branch on GitHub), so the [GitHub] link shows the full LangGraph/fidelity/web-app work
   the bullets describe.
2. Make the repo README match the claims (the portfolio write-up in
   `docs/PORTFOLIO.md` can seed it).
3. If the repo is private, make it public or remove the [GitHub] link.
