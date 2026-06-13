# Web UI — Chat Frontend + Backend — Design

**Date:** 2026-06-13
**Branch:** `feature/web-ui-chat`
**Status:** Approved by user 2026-06-13
**Source:** Brainstormed in session 2026-06-13. Exposes the existing LangGraph orchestrator (`orchestrator.process_turn`, parity + checkpointing complete per `claude/specs/2026-06-10-langgraph-migration-design.md`) to a browser. Builds on Phase 2 checkpointing — the ask-back/resume flow depends on the `thread_id`-keyed SqliteSaver already in place.

---

## Motivation (user-confirmed)

Today the assistant is terminal-only (`main.py` chat loop). The user wants a **real, daily-use tool**: open a browser, chat with the finance assistant, keep multiple saved conversations. Forward-looking: the same shell will later host a portfolio-analysis agent, so the chat-management surface (multiple saved chats) is in scope now even though only the current assistant is wired up.

**Scope grew during brainstorming** from "personal local tool" to a **public, multi-user service deployed on a VPS**, reachable by URL. This adds an auth + per-user usage-accounting layer (below) and a deployment story. The owner does not want to keep a home PC running 24/7, so the app must live on always-on infrastructure.

## Decisions (user-confirmed)

- **Purpose:** real personal daily-use tool, not a demo. Local-first.
- **Multiple saved chats** with a sidebar; persisted so they survive restarts. (Future portfolio agent will reuse this shell.)
- **Progress = high-level stages, NOT logs.** The user sees what the pipeline is doing right now (`Planning…`, `Fetching data…`, `Writing answer…`, `Verifying numbers…`) — never raw log lines or token streams.
- **UI surface = chat + web source links only.** No dashboards, charts, or raw tool dumps. Answers render as markdown (incl. tables); web sources render as links.
- **Stack = FastAPI (backend) + React (frontend)** — "Approach A".
- **Orchestrator can ask the user back** via `interrupt()` for (a) an unclear/ambiguous request and (b) an ambiguous company (e.g. "Toyota" → Toyota Motor vs Toyota Industries). The paused graph resumes on the user's reply.
- **Streaming = progress stages only.** The verified answer is delivered whole, as one block, AFTER fidelity verification. Token-by-token (typewriter) answer streaming is explicitly OUT — streaming unverified numbers would defeat the anti-hallucination guarantee. A cosmetic client-side typewriter replay of already-verified text is a deferred polish item, not in scope.
- **Markdown table rendering required.** Agents/synthesis emit tables as markdown text; the chat pane must render them as real tables (and render source links). A synthesis-prompt addition will ask the model to use markdown tables for multi-period/multi-company comparisons.
- **Ask-back option buttons:** when the orchestrator's question carries `options`, render them as clickable choices that pre-fill the composer; free-text reply is always also allowed.

### Deployment & multi-user decisions

- **Multi-user public service** (not single-user/local). Auth required.
- **Auth = email + password, open signup.** Anyone can register. Abuse is contained by quota + global cap, not by gating signups.
- **Per-user quota = one-time 200,000-token lifetime cap.** Once a user's cumulative token usage crosses 200k, their account is blocked from new turns (manual bump only). **The owner's own account is exempt (unlimited)** — every other account is capped.
- **Global budget cap** = a hard system-wide token ceiling (kill-switch) so total SambaNova spend is bounded even under abuse, independent of per-user counting.
- **Soft abuse signals only:** log IP + browser fingerprint per request as a *flag* for suspicious patterns. Explicitly NOT relied on for enforcement — "per-PC" quota is not reliably enforceable on the web (IP sharing/rotation, fingerprint reset). Accepted limitation.
- **LLM provider = SambaNova API** (cloud; no GPU on the box).
- **Hosting = single VPS, Hetzner CX33** (4 vCPU, 8 GB RAM, 80 GB NVMe, ~€6.49/mo), Docker Compose. Hetzner chosen for price/performance + real NVMe. **8 GB (not 4 GB) because** the app holds the `multilingual-e5-large` embedding model resident (~1–1.5 GB) alongside Python/pandas + Qdrant + Postgres; a 4 GB box risks OOM when the model loads during a concurrent turn. The 4→8 GB jump is only ~€2.50/mo. 4 vCPU also covers concurrent embedding under load.
- **Primary app DB = PostgreSQL** (on the VPS), holding users, chats, messages, usage ledger, and *future* portfolios. Qdrant stays vectors-only. `cache.db` stays **DuckDB** (single-purpose SEC/yfinance fetch cache — not SQLite). LangGraph checkpoints move from `SqliteSaver` to **`PostgresSaver`** (concurrency: SQLite locks the whole file per write — unsafe under many simultaneous turns).
- **Observability = Langfuse runs locally on the owner's PC, not on the VPS.** This keeps the heavy ClickHouse/Postgres/Redis/MinIO stack off the VPS, which is why an 8 GB box suffices (rather than the 16 GB+ the full Langfuse stack would force).
- **Trace delivery = store-and-forward, no trace loss.** The app exports to a local **OpenTelemetry Collector on the VPS** (`localhost`, always reachable → export never blocks a turn). The Collector forwards over a **Tailscale tunnel** to Langfuse's OTLP endpoint on the PC. When the PC is unreachable it **persists traces to VPS disk** (file_storage + persistent sending_queue) and **retries until accepted; delivered batches are then deleted from the VPS**. PC comes back → backlog backfills automatically. A **disk/retention cap** bounds the queue (e.g. cap MB / N days, drop oldest) so a long-off PC can't fill the disk.

---

## Architecture

```
                         Hetzner CX33 VPS (4 vCPU / 8 GB, always on, Docker Compose)
 Browser ──REST+SSE──▶  ┌──────────────────────────────────────────────┐
                        │ FastAPI app (auth, usage, SSE)               │
                        │   │ worker thread per turn                   │
                        │   ▼                                          │
                        │ orchestrator.process_turn(thread_id,on_stage)│
                        │   │ LangGraph StateGraph + PostgresSaver     │
                        │   ▼                                          │
                        │ PostgreSQL   Qdrant       cache.db (DuckDB)  │
                        │ (users,      (vectors)    (SEC/yfinance)     │
                        │  chats, msgs,                                │
                        │  usage,                                      │
                        │  portfolios*)                                │
                        └───────┬──────────────────────────────────────┘
       SambaNova API ◀──────────┘   └──traces (best-effort, non-blocking)──┐
       (LLM, external)                                                     │
                                                          Tailscale tunnel │
                                          Owner's home PC (when on): ◀──────┘
                                          Langfuse stack (ClickHouse/PG/Redis/MinIO)
```

- The browser never talks to LangGraph directly — only to FastAPI (which also enforces auth + the per-user quota before a turn runs).
- A turn runs in a **worker thread**, decoupled from the HTTP/SSE connection, so a browser disconnect never kills an in-flight turn. The turn is tied to its `thread_id` in the Postgres checkpoint store, not to the socket.
- **Storage map:** PostgreSQL = primary app DB (users, chats, messages, usage ledger, future portfolios) and LangGraph checkpoints (`PostgresSaver`). Qdrant = ticker/company anchor vectors only. `cache.db` = DuckDB SEC/yfinance fetch cache (single-purpose). `*portfolios` = future agent, schema designed extensible now.
- **Tracing is off-box, no loss:** Langfuse lives on the owner's PC; the app exports to a local OTel Collector on the VPS that forwards over Tailscale, **persisting to disk and retrying when the PC is offline** (delivered batches then deleted). App functions identically whether or not the PC is reachable.

### Orchestrator changes (small, additive)

1. **`on_stage` callback** on `process_turn` — fired from LangGraph streaming mode as each node completes. Maps node names → friendly stage:

   ```
   plan                                   → "planning"
   agent fan-out / collect                → "fetching"   (+ detail: "AAPL: financials, news")
   synthesize                             → "writing"
   fidelity_check/self_critique/escalate  → "verifying"
   finalize                               → (terminal)
   ```
   ~5 events per turn max. No log parsing. Callback is optional → terminal `main.py` path unaffected.

2. **Two `interrupt()` sites** (HITL, Phase-3 capability of the migration plan):
   - unclear/ambiguous request → ask the user to clarify what they want
   - ambiguous company → ask which entity (with `options` when resolvable)

   Both pause the graph; checkpoint stores position; resume on the same `thread_id`.

---

## Data flow

### Normal turn
1. User sends → `POST /chats/{id}/messages` → server saves the user message, starts the turn in a worker thread, responds with an **SSE stream**.
2. Stream emits `stage` events as nodes complete (`planning` → `fetching` → `writing` → `verifying`).
3. Turn finishes → server saves the assistant message → stream emits one `answer` (markdown) → frontend renders it (tables, source links); stage indicator disappears.
4. Reopen anytime → `GET /chats/{id}` reloads history from Postgres.

### Ask-back turn
1. Same start, but mid-graph an `interrupt()` fires → graph pauses, checkpoint saved.
2. Stream emits one `question` (text + optional `options`) and closes. Chat marked **`awaiting-reply`** with its paused `thread_id`.
3. The user's next message in that chat does NOT start a new turn — it **resumes the paused graph** with the reply as the interrupt value, on the same thread. Stream continues with `stage` events → `answer`. No re-fetching: anything fetched before the pause is in the checkpoint.
4. Survives tab-close/return: pending question is in Postgres, resume works because the checkpoint is in Postgres (`PostgresSaver`).

---

## API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/chats` | list saved chats (id, title, updated_at) for sidebar |
| `POST` | `/chats` | create empty chat → returns id |
| `GET` | `/chats/{id}` | full history + `awaiting-reply` state (paused thread_id) |
| `POST` | `/chats/{id}/messages` | send message → **returns SSE stream** |
| `DELETE` | `/chats/{id}` | delete a chat |

`POST …/messages` does double duty, decided **server-side** by the chat's state:
- chat idle → **start** a new turn
- chat `awaiting-reply` → **resume** the paused graph with the message as the interrupt answer

Concurrency: while a chat is `streaming` or `awaiting-reply`, a second `POST` to it is rejected (one turn per chat at a time).

### SSE event types

```
event: stage    data: {"stage": "fetching", "detail": "AAPL: financials, news"}
event: question data: {"text": "...", "options": ["Toyota Motor (TM)", "Toyota Industries"]}
event: answer   data: {"markdown": "...", "message_id": "..."}
event: error    data: {"message": "EDGAR timed out — try again"}
```

A turn emits ≥0 `stage` events, then terminates with **exactly one** of `answer` | `question` | `error`.

---

## Frontend (React)

Components:
- **`ChatSidebar`** — list from `GET /chats`, new-chat button, switch, delete.
- **`MessageList`** — renders history; assistant messages through `react-markdown` + `remark-gfm` → real tables + links.
- **`StageIndicator`** — live `● Fetching data…` line; consumes `stage` events; clears on `answer`/`question`/`error`.
- **`Composer`** — text box; when chat is `awaiting-reply`, shows the pending question above it (option buttons pre-fill composer if present) so it's clear the next message answers that question.

State store (Zustand or Context): current chat id, message list, stream status (`idle | streaming | awaiting-reply | error`). `awaiting-reply` drives the Composer's behavior change.

---

## Error handling

| Failure | Behavior |
|---|---|
| EDGAR/yfinance timeout mid-turn | turn ends with `error` event → inline notice; message stays in history for retry |
| LLM/provider down | same `error` path, distinct message |
| Browser disconnects mid-stream | turn keeps running server-side (worker thread → checkpoint); reconnect `GET /chats/{id}` shows finished answer or pending question — nothing lost |
| Resume a thread whose checkpoint is gone | server detects empty `get_state`, returns clean error (no silent restart) |
| Two sends race on one chat | second rejected while `streaming`/`awaiting-reply` |
| User over 200k quota | turn rejected before it starts; clear "quota reached" message (owner exempt) |
| Global budget cap hit | all new turns refused (kill-switch); admin must raise ceiling |
| Unauthenticated request | 401; frontend redirects to login |
| Home PC / Langfuse unreachable | traces queued on VPS disk by the OTel Collector, delivered when PC returns; turn unaffected (export to local Collector never blocks) |

Disconnect-resilience is free from checkpointing: the turn is tied to the `thread_id` in Postgres, not the HTTP connection.

---

## Testing

Conventions: real data, broad edge cases, pytest, run via `miniconda3/envs/stock/python.exe`.

- **Backend API (pytest + FastAPI `TestClient`):** each endpoint; SSE stream yields the right event sequence; dual-meaning POST (start vs resume); race rejection; missing-checkpoint error.
- **Fidelity-under-tables:** a synthesized answer formatted as a markdown table — verifier still traces every cell. Proves table output didn't weaken the guarantee.
- **Frontend (Vitest + React Testing Library):** three render states (streaming / answer-with-table / awaiting-reply); markdown tables + links actually render.
- **E2E smoke (deferred, marker-gated):** real chat → real answer; excluded from default run.

---

## Multi-user, auth & quota

- **Users table** in Postgres: id, email, password hash (argon2/bcrypt), `is_owner` flag (the one exempt account), `tokens_used` running total, created_at.
- **Auth:** email+password registration (open), login issues a session (signed cookie or JWT). All `/chats*` endpoints require a valid session.
- **Usage accounting:** the orchestrator already counts tokens per turn; after each turn the count is added to the user's `tokens_used` in a `usage_ledger` (per-turn rows) + the running total. Enforcement runs **before** starting a turn: if `not is_owner and tokens_used >= 200_000` → reject with a clear "quota reached" response.
- **Global budget cap:** a system-wide token ceiling in config; when crossed, the service refuses new turns for everyone (kill-switch) until raised. Independent safety net against runaway SambaNova spend.
- **Soft signals:** store request IP + browser fingerprint on the usage rows for after-the-fact abuse review. Not used for enforcement (documented limitation: per-PC quota is not web-enforceable).

## Deployment

- **Box:** Hetzner CX33 (4 vCPU / 8 GB / 80 GB NVMe, ~€6.49/mo), Ubuntu, Docker Compose. (8 GB needed for the resident embedding model — see Decisions.)
- **Compose services:** `app` (FastAPI + built React bundle), `postgres`, `qdrant`, `otel-collector` (trace store-and-forward queue). SambaNova is external (API key). No Langfuse on the box.
- **Frontend serving:** React built to static assets, served by FastAPI (or an nginx sidecar); single origin avoids CORS.
- **HTTPS:** Caddy or nginx + Let's Encrypt in front (public URL needs TLS for the login).
- **Secrets** via env: SambaNova key, Tavily key, Postgres creds, session secret, `LANGFUSE_HOST` (PC tailnet IP) + Langfuse keys, global-budget ceiling, owner email.
- **Tailscale** installed on both VPS and home PC. The app exports traces to the local OTel Collector (`localhost`); the Collector forwards to Langfuse at the PC's tailnet IP and store-and-forwards when it's offline. App→Collector is local so it never stalls a turn.
- **Backups:** `pg_dump` of Postgres (the irreplaceable data — users, chats, usage); Qdrant + cache.db are rebuildable.

---

## Out of scope

- Gated/invite-only signup (chose open signup + global cap instead).
- Deploying the Langfuse stack on the VPS (runs on owner's PC via Tailscale instead).
- Token-by-token answer streaming (anti-hallucination conflict). Cosmetic verified-replay typewriter = deferred polish.
- Dashboards, charts, raw tool-dump views.
- The future portfolio-analysis agent itself (only the chat shell + extensible "user owns things" schema that will host it are in scope).
