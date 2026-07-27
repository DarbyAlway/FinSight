# Interview Prep — FinSight (Multi-Agent Financial Research Assistant)

Answers below are grounded in the actual code (file:line refs included) so you can
speak specifics, not generic LangGraph theory. Each question has:
- **Spoken answer** — what to say out loud, ~45–90s, in plain sentences.
- **If pressed / backup detail** — the deeper technical stuff to have ready when they dig in.

---

## THE INTERVIEW IS 30 MINUTES — read this first, every time

You will not get through everything below. Trying to will cost you more than skipping
material — rambling eats the clock and crowds out the follow-up that actually shows
understanding. Realistic budget: **3-5 questions total** get asked, not the full list.

**Time budget:** 0-3min intro → 3-5min "walk me through the project" (below) → 5-22min
technical Q&A (3-5 questions) → 22-28min more Q&A or an exercise → 27-30min "questions for
me?" (**pick ONE**, see Section 6).

**The 65-second opener — have this cold, no notes:**
"FinSight is a multi-agent financial research assistant. You ask a stock question in plain
English, and instead of one model answering from memory, it plans the work, dispatches four
specialist agents in parallel to pull real SEC filings and market data, and synthesizes an
answer from only what they actually fetched. The part I'm most proud of: before you ever see
that answer, a deterministic verifier — no LLM judging another LLM — checks every number in
it against the real fetched data, for the right year. If something doesn't trace back, it
gets rewritten, escalated to a live web search, or the answer just tells you honestly it
couldn't verify a figure. It's built as a LangGraph state graph with parallel dispatch and
crash-resume checkpointing, backed by 305 tests that run against real SEC data, not mocks."

**Priority tiers:**
- **Tier 1 — fluent, no notes:** the opener above · the fidelity pipeline (your standout —
  steer here whenever an open question allows it) · why multi-agent (Section 5 Q5) · **the
  24× latency number and the full-stack deployment, below — these are literal CV bullets
  the interviewer has already read, treat them as near-certain.**
- **Tier 2 — 20-30s compressed version ready, don't lead with it:** guardrails/robustness
  (merge Q2+Q3) · evaluation (Q4) · why LangGraph (Q6, only if asked "why this stack") ·
  ticker resolution, below.
- **Tier 3 — skim once morning-of, don't rehearse:** the fidelity line-by-line deep dive,
  the sharp-edges honesty section, LangChain-vs-LangGraph.

---

## Opening questions — "tell me about yourself" / strengths / weaknesses

These land in the first 0-3 minutes, before any technical material. A weak answer here sets
a bad frame before you ever reach the parts you're strong on.

### "Tell me about yourself"

**Fill in the bracketed placeholders yourself** — this is the one spot in this document where
you know the facts and this doc doesn't. Don't leave them blank or invent something on the spot.

**Spoken answer template (~45-60s), past → present → future:**
"[YOUR CURRENT ROLE/STATUS — e.g. 'I'm currently a final-year student in ___' or 'I currently
work as ___ at ___']. Over the past [TIMEFRAME], I've been building hands-on experience with AI
agent systems — most recently a multi-agent financial research assistant that plans a query,
dispatches four specialist agents in parallel to pull real SEC filings and market data, and —
the part I'm proudest of — verifies every number in its own final answer against the real
fetched data before it ships, because I wanted to actually solve the hallucination problem
instead of building another chatbot wrapper. Separately, I lead a small pipeline for my team
that grows an under-sized QA dataset using retrieval plus an LLM-as-judge filter instead of
manual labeling. What connects both is the same instinct: don't just call an LLM, build the
deterministic checks and architecture around it so the output is actually trustworthy. That's
what draws me to an AI Agent Developer role — I want to keep building systems like that in
production, not just prototype one."

**If pressed on "why are you looking now":** [PLACEHOLDER — fill in your real reason. Don't
guess at this on the spot; it's the one thing an interviewer can trivially follow up on.]

### "What is your greatest strength?"

**Spoken answer (~30-40s):**
"I don't trust an LLM's output by default anywhere a wrong answer would actually matter — I
build a deterministic check around it instead of hoping the model gets it right. The clearest
example is the fidelity verifier in my financial assistant: every number in the final answer
gets traced back to the actual data that was fetched, with no LLM judging another LLM. The same
instinct shows up in how I make performance decisions — when I cut a query from 167 seconds
down to about 7, I didn't guess which part was slow, I timed every round before and after and
picked the fix based on real numbers, not a hunch. I'd rather ship something I can defend with
evidence than something that just looks impressive until someone asks 'how do you know that's
right.'"

### "What is your weakness?"

**Spoken answer (~30-40s):**
"I tend to build the hard, interesting part of a system before the operational hardening around
it. In my financial assistant, I built a fairly sophisticated hallucination-detection pipeline,
but there's no retry-with-backoff or rate limiting yet on the actual external calls to SEC EDGAR
or yfinance — if one of those gets rate-limited or times out, the call just fails instead of
retrying gracefully. I know exactly what's missing and how I'd build it — a token-bucket rate
limiter, exponential backoff with jitter — I just hadn't gotten to it yet because the
correctness problem pulled my attention harder than the resilience problem. I've been trying to
treat operational robustness as part of 'done' from the start of a feature, not something I
circle back for later."

**Why this works:** it's real (verified against the actual code in a live prep session, not
invented for the interview), specific, and has a concrete fix attached — it isn't a disguised
humble-brag ("I work too hard"), which interviewers hear constantly and discount immediately.

---

## CV deep-dives — bullets your interviewer has already read

These three are on your CV word-for-word and were **not covered by the questions you were
given** — that makes them higher-risk than the prepared list, not lower, because there's no
polished script yet and they're an obvious thing to ask about a resume in front of them.

### "Tell me about the ~24× speedup" (CV: "~24× faster responses through smart model routing")

**Spoken answer (~35s):**
"That's a real measured number, not a rounded guess — a single-ticker query went from 167
seconds down to about 7. The specialist agents were originally on a reasoning model, and its
hidden chain-of-thought made every tool-call round take anywhere from 8 to 57 seconds —
worst case, one query hit 167 seconds end to end. I switched the four agents to a smaller,
non-reasoning model that's fast and reliable specifically at tool-calling — about 1.4 seconds
a round — and kept a separate model for planning and synthesis, since neither of those needs
tools and a reasoning model was overkill there too. I also made tool calls within a single
round run concurrently instead of serially, since they're just network I/O. Together that
took the worst case from 167 seconds to about 7 — and I confirmed it wasn't a speed-for-
accuracy trade: the fidelity checker still showed zero hard mismatches after the change."

**If pressed — "how exactly did you measure that?":**
"I timed real queries before and after the model swap directly — not synthetic
benchmarks. Single-ticker went 167s→~7s, a multi-company comparison landed around 8
seconds, a ratios-heavy query around 5. It's in the commit message from when I made the
change, with the reasoning for each model choice attached."

**Backup detail:** commit `5d61347` — *"Agents were gpt-oss-120b (a reasoning model): hidden
chain-of-thought made each tool-loop round 8-57s on SambaNova (single-ticker queries hit
167s); synthesis on gpt-oss was 27-44s. Switch agents to gemma-4-31B-it (non-reasoning,
~1.4s/round, reliable parallel tool calls on SambaNova where Llama-3.3 400s) and synthesis
to Meta-Llama-3.3-70B-Instruct (~1-2s vs 27-44s). Live: single-ticker 167s→~7s, multi-compare
~8s, ratios ~5s, 0 HARD fidelity mismatches."* Concurrent tool execution within a round
(`agents/_tooling.py`, `ThreadPoolExecutor`) was a separate follow-up commit
(`83adc0f`) stacked on top of the model swap.

### "Walk me through the full-stack deployment" (CV: "FastAPI backend streaming live results to a React chat interface, with secure login, saved chat history")

**Spoken answer (~45s):**
"Backend's FastAPI, frontend's React with TypeScript. The part I'd actually call out: the
orchestrator itself is a blocking call — one full LangGraph turn — so I run it on a
background thread and push stage updates and the final answer onto a queue, and a generator
drains that queue into Server-Sent Events for the frontend. That decouples the real work from
the HTTP request lifecycle, so if a client disconnects mid-turn, it doesn't kill the
in-flight LangGraph run underneath it. On top of that there's cookie-session auth with
hashed passwords, Postgres-backed chat history so conversations persist across sessions, and
real usage controls — a per-user token quota and a global kill-switch — because this is a
deployed app with real API costs behind it, not a local demo script."

**Backup detail:** `webapp/turn_runner.py:22-58` — `stream_turn` spawns a daemon `threading.Thread`
running `process_turn`, and the SSE generator blocks on `queue.Queue.get()` until a sentinel;
the stage callback (`on_stage`) and the terminal `answer`/`error` event both flow through the
same queue, so the consumer never touches the orchestrator directly. `webapp/app.py:130-170`
— `send_message` checks a global token kill-switch (`accounts.global_tokens_used() >=
_global_cap()`) before a per-user lifetime cap (owner exempt), saves the user message
immediately (so a failed turn doesn't lose what the user typed), and meters usage via the
orchestrator's own `on_usage` callback after the turn completes.

### "Tell me about replacing ticker guessing" (CV: "reliable lookup over 16,000 tickers")

**Spoken answer (~30s):**
"Originally the planner LLM just guessed ticker symbols directly from company names, which
is exactly the kind of thing you don't want an LLM doing — it hallucinated dead or renamed
tickers. I replaced that with a deterministic resolution ladder: exact match against a real
SEC/NASDAQ ticker table first, then a curated alias list for renames like Facebook to META,
then fuzzy string matching for typos, and only as a last resort an embedding-gated semantic
search for descriptive references like 'the iPhone maker.' If nothing resolves cleanly, it
refuses rather than guessing. The model never invents a symbol anymore — it only ever points
at a name, and a deterministic lookup decides the ticker."

**Backup detail:** `tools/resolve.py` — the ladder in `resolve_company()`: tier 0 verbatim-
symbol trust (with a stopword exclusion list so abbreviations like PEG/AI/ALL aren't
mistaken for tickers PSEG/C3.ai/Allstate), tier 1 exact match, tier 2 curated alias map, tiers
3-4 `rapidfuzz` fuzzy match (floor 88, margin 8 to auto-accept, else `AMBIGUOUS`), tier 5
Qdrant-backed semantic search (cosine floor 0.82). Backed by a DuckDB table of 16,687 tickers
+ 5,329 ETFs built from SEC + NASDAQ feeds.

---

## Cheat sheet — numbers to have on the tip of your tongue

- **11-node LangGraph `StateGraph`**: plan → gates → agent (parallel `Send`) → collect →
  [proactive_web] → synthesize → [web_fallback] → [fidelity_check] → [self_critique] →
  [web_escalate] → finalize. (`orchestrator.py:449-476`)
- **4 specialist agents**: financials, news, calc, ratios (`agents/`), each with its own
  scoped tool list and a shared guarded tool-calling loop (`agents/_tooling.py`).
- **Guardrails** on every agent's tool loop: max 8 tool-call rounds, 30k token budget,
  break after 3 consecutive error/no-data results, duplicate-call cache.
  (`agents/_tooling.py:16-18`)
- **Deterministic fidelity verifier**: regex-extracts every unit-bearing number from the
  final answer, binds it to a fiscal year, checks it against the raw tool outputs at
  ±1% tolerance. No LLM-judges-LLM. (`tools/fidelity.py`)
- **305 pytest tests**, real-data policy (hits real SEC EDGAR filings, not synthetic
  fixtures); live failures get logged to `tests/failure_log.jsonl` and turned into pinned
  regressions.
- **Checkpointing**: Postgres in prod (`DATABASE_URL` set), SQLite offline/tests —
  crash-mid-turn resume without re-running completed nodes. (`tools/pg.py`)
- **Model routing isn't one-size-fits-all**: planner/synthesis = `Meta-Llama-3.3-70B-Instruct`
  (reliable JSON, no tools, ~1-2s); agents = `gemma-4-31B-it` (non-reasoning, ~1.4s/round,
  reliable *parallel* tool calls — `gpt-oss-120b` reasoning was 8-57s variable and
  Llama-3.3 was hitting 400s on tool calls at volume on SambaNova). (`tools/config.py:21-24`)
- **Offline eval harness** (`eval_models.py`): A/B two models head-to-head on plan-routing
  accuracy (10 cases) and tool-selection accuracy (10 cases), dumps `eval_results.json`.
- **Observability**: self-hosted Langfuse v3, one nested trace per turn, fidelity mismatch
  count exported as a trace score — so hallucination rate is a tracked metric over time,
  not a vibe.

---

## Plain-English layer — lead with this if the interviewer isn't deeply technical

**How to use this:** don't decide in advance that the interviewer is or isn't technical —
read the room in your first answer. Lead with the plain-English version below for *any*
question on your first pass, no matter who's asking. If they nod and move on, you've
communicated well. If they lean in and ask "how does that actually work," that's your
signal to drop into the full technical answer in the matching numbered section. Going
jargon-first with a non-technical interviewer reads as "can't explain what I built" even
when the work is strong — simple-first, jargon-on-request is the safer default with anyone.

**The 10-second pitch, if they just ask "what did you build":**
"It's a chatbot for stock research. You ask it something like 'what was Apple's revenue
last year,' and instead of just answering from memory — which is where AI tools usually get
financial numbers wrong — it actually looks up the real filing, writes an answer from that,
and then double-checks every number in its own answer against what it actually looked up
before showing it to you."

| If they ask... | Say this (no jargon) | Full technical version |
|---|---|---|
| "Walk me through the architecture" | "Think of it like a small research team, not one person. When you ask a question, a 'planner' figures out what you're really asking and who needs to work on it. Then a few specialists go to work at the same time — one pulls financial filings, one pulls news, one does math like growth rates. Once they're done, a writer drafts an answer using *only* what those specialists actually found. And before you ever see it, a fact-checker scans every number in that draft and confirms it really came from the real data — not from the AI's memory." | Section 5, Q1 |
| "How do you handle failures / errors?" | "AI models sometimes format their requests sloppily — like filling out a form with something in the wrong box. Instead of the whole system crashing, every step has a simpler backup plan it falls back to, so one small hiccup degrades gracefully instead of breaking the conversation." | Section 5, Q2 |
| "What if an agent gets stuck looping?" | "Occasionally an AI keeps asking for the same information over and over, like someone re-checking a fact five times. I put hard limits in: a cap on how many tries it gets, a memory so it never re-checks the same thing twice, and a rule that if it keeps hitting dead ends, it stops and just answers with whatever it already has instead of spinning forever." | Section 5, Q3 |
| "How do you know an update actually helped?" | "Whenever I change how the AI works, I don't just eyeball it. I keep a fixed set of test questions with known right answers and score accuracy before and after. I also keep hundreds of automated tests on real data, and every real answer the system gives gets a live 'trust score' logged, so I can watch reliability trend over time instead of guessing." | Section 5, Q4 |
| "Why multiple AI agents instead of one big one?" | "You could ask one AI to plan, research everything, and write the answer — but that's like asking one person to be the accountant, the journalist, and the analyst all at once off one giant instruction sheet. Splitting it into specialists means each one only has to know its own small job, they can all work at the same time instead of one after another, and if one gets confused, it doesn't take the whole team down." | Section 5, Q5 |
| "Why this particular tool (LangGraph) instead of just writing code?" | "Honestly, most of this I could've written by hand — nothing exotic there. The one piece that's genuinely hard to build well yourself is 'if the whole thing crashes halfway through, pick back up exactly where it left off instead of starting over' — that's real infrastructure work I'd rather not reinvent. Beyond that, it's less about 'couldn't do it otherwise' and more like the difference between a flowchart and one giant paragraph of instructions — every decision stays its own clear, testable box instead of turning into a tangle of if/else as more get added." | Section 5, Q6 |
| "Tell me about the fidelity / hallucination-checking part" | "This is the part I'm most proud of. AI models will confidently state a financial number that's just wrong — pulled from something they memorized in training instead of the actual document in front of them. So after the AI writes an answer, an automatic checker goes through every single number in it — every dollar figure, every percentage — and confirms it actually came from the real data that was looked up, for the right year. If a number can't be traced back, it doesn't get shipped as-is: the AI rewrites it, or the system double-checks it live on the web, or the final answer just tells you honestly 'this number couldn't be verified.' It's like having a fact-checker read the final draft against the source documents before it's allowed to go out — automatically, every single time." | Bonus deep-dive (fidelity) |

---

# Section 5 — Practice Interview Questions

## 1. "Walk me through the architecture of your multi-agent financial assistant from user input to final response."

**Spoken answer:**
"It's a LangGraph `StateGraph` with 11 nodes. A user question comes in, and the first
node is a **planner** LLM — low temperature, JSON-only — that classifies intent, decides
which of the four specialist agents to run (financials, news, calc, ratios), and extracts
tickers. If that JSON is malformed I don't crash, I fall back to a keyword heuristic.

Next is a **gates** node that I don't trust the planner LLM with: if the user named a
group like 'FAANG' or 'MAG7', I override whatever tickers the LLM guessed with a canonical
manifest list — I caught the planner dropping META and NVDA and hallucinating FB/BABA.
Then every ticker is validated against a real SEC filer list and dead or hallucinated
tickers get dropped before any agent burns tokens on them.

Then it fans out — LangGraph's `Send` API dispatches one node per planned agent, running
concurrently, and a **collect** node merges their outputs via state reducers instead of
manual thread-pool bookkeeping. Each agent has its own scoped tool list and runs a shared
guarded tool-calling loop with its own token and iteration budget.

Those outputs get concatenated into context and handed to a **synthesis** LLM that's
instructed to answer *only* from that context. Then — and this is the part I'm proudest
of — a **deterministic fidelity verifier** regex-extracts every dollar figure, percentage,
and ratio out of that answer, binds each one to a fiscal year, and checks it against the
raw tool call outputs. If a number doesn't trace back, the model gets one grounded
self-critique re-prompt with the exact bad figures. If it still can't fix it, I escalate to
a live web search and re-answer from that. If even that comes up empty, the answer ships
with an explicit 'these figures could not be verified' caveat — it never ships a
silently-wrong number.

The whole thing is checkpointed — Postgres in production, SQLite locally — so a crash
mid-turn resumes from the last completed node instead of re-running finished agent work."

**If pressed / backup detail:**
- Reducers: `graph_state.py` uses `Annotated[dict, merge_dicts]` for `agent_results` /
  `agent_tool_blocks` and `Annotated[dict, add_token_counts]` for token accounting — this
  replaced a manual `ThreadPoolExecutor.as_completed` merge from an earlier version.
- `market_news` intent is a special case: routed straight to a proactive web search
  (`_route_after_collect`) and *never* fidelity-checked — it's Tavily-sourced, not
  agent-grounded, so there's nothing to trace against.
- The whole turn is one Langfuse trace (`@observe(name="process_turn")`), with nested
  spans for planner, each agent, synthesis, and each tool call — so a slow or wrong turn is
  fully replayable in the trace UI, not just in logs.

---

## 2. "How do you handle tool-calling failures or LLM schema parsing errors in LangGraph?"

**Spoken answer:**
"There are three separate layers, because I don't trust any single one of them to catch
everything.

First, the planner's JSON output: I regex out the first `{...}` block and `json.loads` it.
If that throws — malformed JSON, or the model wrapped it in prose — I don't retry the LLM,
I fall back to a cheap keyword heuristic that at least picks a reasonable agent set, so a
bad planner call degrades the routing quality instead of crashing the turn.

Second, individual tool-call arguments: each tool call's `arguments` field is JSON, and if
that fails to parse I don't blow up the loop — I default to an empty args dict, which just
means that specific call comes back as a normal tool-level error the agent can react to and
retry differently.

Third — and this is the one I think is more interesting — I don't just handle *malformed*
tool calls, I have a Pydantic layer underneath everything a tool *successfully* returns.
Parsed financial statement rows go through validators that reject non-finite values, values
outside a sane magnitude bound, gross margins over 100%, or a balance sheet where assets
don't equal liabilities plus equity. That came out of a real bug — I had a unit-scale error
that put Microsoft's gross margin at 220%. The principle I landed on: the LLM should never
have to *type* a number correctly, and the data layer should never be allowed to *store* an
impossible one. Bad rows get logged and dropped, not silently kept.

At the orchestrator level, each agent node is wrapped in try/except — if an agent throws
for any reason, I log it to a failure log file that becomes raw material for a new
regression test, and the node returns an empty result. Because agents run as independent
`Send`-dispatched nodes, one agent failing doesn't take down the others."

**If pressed / backup detail:**
- `_parse_plan` (`orchestrator.py:64-70`) raises `ValueError` if the parsed JSON isn't a
  dict, which routes into the same except branch as `json.JSONDecodeError`.
- `_is_error_result` (`agents/_tooling.py:39-44`) is a cheap string-prefix heuristic
  (`error`, `no `, `could not`, `unable`, `unknown tool`) that feeds the no-progress
  guardrail — it's intentionally dumb/fast rather than another LLM call judging the result.
- `tools/schemas.py`: `StatementRow`, `MarginRow`, `BalanceSheetIdentity` — the balance
  sheet check has a primary robust path (grand-total line, which naturally absorbs
  mezzanine/NCI) and a conservative fallback that only *trusts* a positive match, never
  false-flags, because some real companies (LCID, PLUG) have balance sheets that fail a
  naive two-bucket check for legitimate reasons.

---

## 3. "If an agent gets stuck in an infinite tool-calling loop, how does your system recover?"

**Spoken answer:**
"This actually happened before I put guardrails in — one agent burned about 85k tokens
looping on a single tool. So the tool-calling loop has four layered brakes, cheapest and
earliest first.

One, a hard cap on iterations — 8 rounds, non-negotiable. Two, a duplicate-call cache: if
the model asks for the exact same tool with the exact same arguments again, it's served the
cached result and told explicitly not to repeat the call, instead of re-hitting the API.
Three, no-progress detection — three consecutive error or no-data results in a row and the
loop bails, because at that point more calls aren't going to help. Four, a per-agent token
budget, 30,000 tokens, as the final ceiling.

The important part is what happens *when* a guardrail trips: I don't just error out. I
force one final tool-free completion — 'stop calling tools, summarize what you already
have' — so the agent degrades gracefully to a partial answer instead of the turn failing
outright. There's a unit test for exactly this: a mock model that never stops requesting
tools, and I assert the loop still terminates and still returns a string.

One more detail — tool calls within a single round are I/O-bound, so if a model asks for,
say, three tickers' worth of data in one round, I run those concurrently in a thread pool
rather than serially, with each one carried in its own copied context so it still nests
correctly under the parent trace span in Langfuse."

**If pressed / backup detail:**
- Constants: `_MAX_ITERATIONS = 8`, `_TOKEN_BUDGET = 30000`, `_NO_PROGRESS_ERRORS = 3`
  (`agents/_tooling.py:16-18`).
- `tests/test_tool_loop.py::test_max_iterations_cap_stops_runaway_loop` — asserts exact
  call count (1 initial + 3 loop rounds + 1 forced final) with `max_iterations=3` to prove
  the cap plus graceful-degradation path both fire.
- This is agent-level looping. Graph-level "looping" (self-critique → web-escalate) is
  bounded by topology, not a counter — see Q6 below, that's a different mechanism on
  purpose.

---

## 4. "How do you evaluate whether an agent system update actually improved performance vs. introduced regressions?"

**Spoken answer:**
"Three tools, at three different layers.

At the routing/tool-selection layer, I have an offline eval harness that runs two models
head-to-head on a fixed set of hand-labeled cases — ten plan-routing questions like 'what's
AAPL's revenue' with the expected agent set, and ten tool-selection questions per agent with
the expected first tool call. Some cases deliberately accept more than one correct answer,
because for something like a DCF valuation, routing to `calc` alone or `financials+calc`
are both defensible. It scores accuracy and per-call latency and dumps the results to JSON
so I can diff two models or two prompt versions against each other — that's literally how I
picked the current model split instead of going by feel.

At the regression layer, I've got 305 pytest tests that hit real SEC EDGAR data, not
mocked fixtures — because a mocked fixture can't tell you the parser broke against a real
filing. The policy is: every live failure becomes a pinned regression test. So the MSFT
220% gross margin bug, the group-manifest planner mismatch, the web-fallback message-reuse
bug — those aren't just fixed, they're permanent tests now.

At the production layer, the fidelity verifier's mismatch count gets pushed to Langfuse as
a trace score on every real turn. So hallucination rate isn't something I eyeball
qualitatively — it's a number I can watch trend after I change a prompt or swap a model,
and I can go pull the specific traces where it spiked."

**If pressed / backup detail:**
- `eval_models.py` usage: `python eval_models.py qwen3:14b llama3.1:8b` — compares any two
  Ollama models, defaults to `qwen3:14b` vs `qwen3:8b`.
- `_score_fidelity` (`orchestrator.py:43-49`) — best-effort, wrapped so a Langfuse outage
  never breaks the request path; scores `fidelity_mismatches` on the current trace.
- `fidelity_live_check.py` — a one-shot manual smoke test: run one real query through the
  full pipeline and read the `[fidelity]` log line, for a fast "did my change break
  grounding" sanity check before running the full suite.
- Honest gap to name if asked: there's no automated *offline* fidelity regression suite yet
  (that check runs live per-turn) — the closest to a fixed benchmark is `eval_models.py`'s
  routing/tool cases plus the pinned pytest regressions. If you want to go further, that's
  a good "what would you build next" answer.

---

## 5. "Why use multi-agent architecture instead of a single long-prompted LLM with all tools?"

**Spoken answer:**
"A few concrete reasons, not just 'multi-agent is trendy.'

First, tool-selection accuracy. Each agent only sees its own scoped tool list — financials
never sees the calc agent's DCF tools. A smaller decision surface means fewer wrong-tool
picks, and it's something I can actually measure per-agent in isolation with the eval
harness instead of debugging tool confusion inside one giant 20-tool prompt.

Second, model-to-task fit. The agents run on a fast, non-reasoning model that's reliable at
*parallel* tool calling. The planner and synthesis steps run on a different model that's
better at clean JSON and prose but doesn't need tools at all. I found this the hard way —
a reasoning model was taking 8 to 57 seconds variably, and a different model was hitting
400 errors on tool calls at any volume. A single-prompt design can't make that trade per
sub-task; you're stuck with whatever one model's weaknesses are for the whole turn.

Third, real wall-clock parallelism. LangGraph's `Send` API dispatches all planned agents
concurrently, so the turn's latency is roughly the slowest single agent, not the sum of
four agents run serially inside one big tool loop.

Fourth, blast radius. Each agent's guardrails — the 8-iteration cap, the 30k token budget —
are scoped *per agent*. One agent looping doesn't eat the whole turn's budget or pollute
another agent's tool-call history.

And fifth, it's what makes the fidelity verification possible at all. Because each agent's
tool calls come back as a discrete, labeled block, I can trace a number in the final answer
back to which specific tool call produced it. If everything were one interleaved
conversation, building a clean 'is this number grounded' check would be a lot harder.

The honest trade-off is added complexity — there's a planning hop before any real work
happens, more orchestration surface to test, and some risk of duplicate fetches across
agents. I mitigate the last one with a shared cache layer with a TTL, so repeated fetches
within that window are served locally instead of re-hitting SEC or yfinance."

**If pressed / backup detail:**
- `tools/config.py:21-24` — the actual model assignment comment explains the *why*, not
  just the *what*: gemma for agents (cheap, ~1.4s/round, reliable parallel tool calls
  vs. Llama-3.3 hitting 400s on SambaNova at volume); Llama-3.3 for plan/synthesis
  (reliable JSON; no tools so no 400 risk; fast because non-reasoning).
- Cache: `cache.db` + `CACHE_TTL_DAYS = 90` (`tools/config.py:4`) — DuckDB-backed, shared
  across agents/turns, so this isn't a purely theoretical mitigation.
- `graph_state.py` reducers are the concrete LangGraph mechanism that makes fan-out safe:
  `merge_dicts` for agent results/tool blocks, `add_token_counts` for accounting.

---

## 6. "Why does this need LangGraph specifically — instead of LangChain, or just plain Python?"

**Spoken answer:**
"Two separate questions in there, so let me take them one at a time — and I want to be
upfront that most of this individually *can* be done in plain Python without much trouble.
I'm not going to pretend otherwise.

Dynamic fan-out — `asyncio.gather` over a runtime list does that in one line. Merging
concurrent results — filling a dict as futures complete is five lines. The retry/escalation
branching — a handful of `if`/`elif` functions does the same job. None of that is exotic,
and I don't think 'you literally can't do this without a framework' is an honest argument
for any of those three.

The one piece that's genuinely expensive to build well by hand is crash-mid-turn resume.
That means correctly serializing arbitrary state to a real database after every step, keyed
by session, with idempotent resume logic that skips already-completed work, handled
correctly under partial writes and concurrent access. That's real persistence-layer
engineering with a lot of edge cases — not a for-loop — and LangGraph's checkpointer gives
me that, Postgres in production and SQLite locally, as basically a couple of lines to wire
up. That's the one justification I'd actually defend as 'hard to replicate cheaply.'

Past that one piece, the honest reason I used a framework for the rest is maintainability as
the thing grows, not raw capability. At 11 nodes with several conditional retry paths, the
hand-rolled version of all this accumulates into nested conditionals checking flags that
were set three functions earlier — that's a real, common failure mode of orchestration code,
not a hypothetical one. The graph model keeps every routing decision a small,
independently-testable pure function — `test_graph_routes.py` unit-tests all of them without
running a single real LLM call — and the whole shape stays visualizable no matter how many
nodes get added later; the architecture diagram in the README is generated straight from the
compiled graph object, so it can't drift out of sync with the code. A disciplined engineer
can write hand-rolled code in that same shape — the framework just makes it the default
instead of something you have to remember to enforce every time you touch it.

As for LangChain specifically — this project barely uses it. There's no `AgentExecutor`, no
LCEL chains, no `Tool` wrapper classes; agents call an OpenAI-compatible client directly and
parse tool calls by hand in a shared loop. LangGraph is a separate, lower-level
graph-execution library that happens to come from the same ecosystem — I'm using it for
'nodes, conditional edges, parallel fan-out, persisted state,' not because I bought into a
LangChain stack wholesale."

**If they push further — 'okay but couldn't you just write all of this in plain Python?':**
"Yes, honestly, for maybe 90% of it — and if this were a smaller or more linear pipeline I
would have. I specifically scoped this project to include the pieces that don't show up
until you actually need them at scale — safe concurrent merging and crash recovery — because
I wanted hands-on experience with that class of problem using a tool built for it, rather
than either avoiding it or hand-rolling my own first attempt at a persistence layer. That's
also a fair thing to just say directly if asked: part of why I picked LangGraph was
wanting real experience with graph-based agent orchestration, since it's becoming a common
production pattern — and the project turned out to genuinely need the parts that matter most
in that library, which is what confirmed it was a fit and not just a good story after the
fact."

**If pressed / backup detail:**
- `graph_state.py:1-5` docstring says this explicitly: *"Reducers replace the
  ThreadPoolExecutor `as_completed` merging: parallel Send-dispatched agent nodes each
  return their slice; LangGraph merges them."* — direct evidence this was a deliberate
  migration, not a from-scratch choice.
- `_route_after_gates` (`orchestrator.py:95-111`) is the actual dynamic fan-out: it returns
  a *list* of `Send("agent", {...})` objects sized to however many agents the planner
  picked that turn — not a static graph shape.
- `docs/orchestrator-graph.md` / `.mmd` / `.png` are generated via
  `_GRAPH.get_graph().draw_mermaid()` (`_gen_graph.py`) — worth having open on your screen
  or phone if this comes up, it's a strong visual to point to.
- Resume logic: `process_turn` (`orchestrator.py:537`) checks
  `_GRAPH.get_state(config).next` to detect a thread with pending nodes and calls
  `invoke(None, config)` to continue from the checkpoint rather than replaying finished work.
- Honest limitation to volunteer if asked: a `thread_id` must never be reused for a *new*
  question, only to resume a crashed one — because the reducer channels merge across
  invokes on the same thread, so reusing it for a fresh question would leak stale
  `agent_results`/`tool_blocks` into routing and fidelity checks. That's a real sharp edge
  of the checkpointing model, called out directly in the `process_turn` docstring.

---

# Sections 1–4 — Key Follow-Up Questions

## "How do you decide when an agent should loop back vs. finish execution?"

**Spoken answer:**
"There are two different loops and I use a different decision rule for each on purpose.

Inside one agent's tool-calling turn, it's simple: keep looping while the model is still
requesting tools and no guardrail has tripped; stop the instant it returns plain content,
or the instant a guardrail (iteration cap, token budget, no-progress) fires — and on a
guardrail trip I force one tool-free completion so it still finishes with something.

At the graph level, the loop-back decision is about *evidence quality*, not a counter. After
synthesis, if the agents returned essentially nothing or the answer reads as uncertain, I
go to a web fallback. If there's real tool-grounded evidence, I run the fidelity check. Only
a HARD mismatch — a figure that doesn't exist for *any* fetched year, which is the strongest
signal of the model pulling from training data instead of the fetched documents — sends it
to a self-critique re-prompt. A softer mismatch, like a real number attached to the wrong
year label, is flagged in logs but doesn't trigger a re-prompt, because I tried that and it
just caused churn without actually improving accuracy.

And critically, self-critique never loops back into the fidelity check again — that edge
doesn't exist in the graph. It goes to web escalation if the bad figures survive, and web
escalation always finalizes. So the retry depth is bounded by the graph's shape, not by a
runtime counter — there's no path through this graph that can cycle indefinitely, by
construction."

## "How do you structure Pydantic schemas or function signatures so the agent doesn't invoke the wrong tool?"

**Spoken answer:**
"A few layers, mostly upstream of the LLM rather than trying to out-prompt it.

Each of the four agents gets its own tool list — financials' tools are invisible to the
news agent and vice versa — so the model is choosing from maybe 4-6 relevant functions,
not twenty. I also force `tool_choice='required'` on the first round so there's no ambiguity
about whether it meant to call a tool.

For arguments, malformed JSON in a tool call doesn't crash anything — it defaults to an
empty dict and the tool itself returns a normal error string, which then feeds the
no-progress guardrail if it keeps happening.

The part I'd call out as the more interesting design choice: I don't rely on the tool's
input schema alone to keep bad data out — there's a Pydantic layer *validating what tools
return* before it ever reaches the LLM's context again. So even a correctly-invoked tool
that returns a bad parse — NaN, an impossible margin, a balance sheet that doesn't balance —
gets caught and dropped there, not passed forward for the model to reason over and
accidentally trust.

And for the specific failure mode of 'wrong ticker' rather than 'wrong tool,' I don't let
the model free-type ticker symbols into the pipeline at all — there's a deterministic
resolution ladder (exact match, alias table, fuzzy match, ambiguity refusal, embedding
search) sitting in front of it, and a validation gate that drops any ticker that isn't a
real currently-listed SEC filer before agents even run."

## "What happens when an external API (like SEC EDGAR, DuckDB, or web search) fails, times out, or returns empty results?"

**Spoken answer:**
"Every external dependency in this system is written to fail *open* or fail *loud-but-
contained*, never to take the whole turn down silently.

At the tool-loop level, an error or empty result from SEC/yfinance/news comes back as a
normal string, gets flagged by a cheap prefix check, and feeds the no-progress guardrail —
three in a row and the loop bails to a summary instead of hammering a dead API for the full
8 rounds.

At the orchestrator level, each agent node is wrapped in try/except; an exception gets
logged to a failure file — which is also how new regression tests get seeded — and the node
just returns empty. Because agents are independent `Send`-dispatched nodes, one agent
throwing doesn't block or corrupt the others.

Ticker validation fails open on purpose: if the SEC ticker list itself can't be loaded —
say EDGAR is down — I don't reject every ticker in the query, I treat them all as valid
rather than nuking the whole turn over a reference-data outage. Same idea for the semantic
ticker-resolution tier — if Qdrant is unreachable, that tier just returns 'no match' and the
ladder falls through, it doesn't propagate the exception.

At the very top, if the agents collectively returned nothing, or the synthesized answer
reads as uncertain, that routes to a live web search fallback. If Tavily's not configured or
errors, that function logs a warning and returns empty — which the graph treats as a no-op,
not a crash — and falls through to the last resort: the answer ships with an explicit
'these figures could not be verified' caveat appended. So the worst-case failure mode for
any single external dependency is a visible caveat on the answer, never a stack trace and
never — which is the property I actually care about — a confidently wrong number shipped
silently.

And one level above all of that: if the *process itself* dies mid-turn, not just one API
call, the LangGraph checkpointer — Postgres in production, SQLite locally — has the turn's
state saved per thread, so it resumes from the last completed node instead of starting the
whole turn over."

---

## Bonus deep-dive — "Walk me through how the fidelity verifier's guardrails actually work" (`tools/fidelity.py`)

This is the single most distinctive piece of the project, so expect a drill-down. It's five
separate, stacked guardrails, each defending a different failure mode — not one big check.

**Spoken answer:**
"It's a pure, deterministic function — `verify(answer, tool_blocks)` — with no LLM in the
loop at all. Five things have to go right for it to be trustworthy.

First, extraction has to avoid double-counting. A string like `$391,035M` could in theory
match more than one number pattern. So I extract in strict priority order — money-with-
suffix, then money spelled as a word like '391 billion', then plain dollars, then percent,
then ratio — and once a span of text is claimed by a higher-priority match, nothing lower
priority is allowed to re-match inside it. There's also a regex-level guard doing the same
job redundantly: the plain-dollars pattern has a negative lookahead that refuses to match if
the number's immediately followed by a magnitude suffix or percent sign.

Second, I only extract *unit-bearing* numbers — currency, percentages, ratios. Bare
integers, counts, and 4-digit years are never candidates at all. That's the primary
false-positive defense — otherwise something like 'reported in 2024' would get treated as
an ungrounded figure.

Third, every number gets bound to a fiscal year, and prose presents years two different
ways that need different logic. Interleaved phrasing — '$391B in FY2024 and $383B in
FY2023' — binds each number to its nearest year token. But enumerated phrasing — 'FY2023,
FY2024, FY2025... are $X, $Y, $Z respectively' — would break that: nearest-year would bind
all three values to the last year listed. So there's a separate positional pass that
detects when N years precede N same-kind values and binds them index to index instead.

Fourth, matching uses a relative tolerance, not exact equality — one percent — because the
model restating '391,035M' as '$391.0B' is a legitimate reformat, not a fabrication, and
exact match would false-flag constantly.

Fifth, and this is the part that actually drives behavior: mismatches get classified hard
or soft, and only hard mismatches are expensive. A number that matches the tool data for
*some* other fetched year is soft — probably a mislabel, just flagged and logged, no
re-prompt, because I tried re-prompting on those and it caused churn without improving
accuracy. A number that matches *no* fetched year at all is hard — that's the strongest
signal it came from the model's training data instead of the actual fetched documents, and
that's what triggers the self-critique retry.

There's one more layer on top of that I'm particularly happy with: even if a number's
*value* happens to coincidentally match some other year that WAS fetched — say a company's
revenue two years ago happens to be within a percent of last year's — if the number is
explicitly labeled with a year that was never fetched this turn at all, it still gets forced
to hard. Coincidental value overlap across years doesn't make a specific year-claim
grounded. That's exactly the mechanism that caught a real bug live: the model answered with
Microsoft's FY2020 and FY2019 revenue — correct numbers, straight from training data — when
only FY2023 through FY2025 had actually been fetched that turn. The verifier flagged both,
the self-critique rewrote the answer, and the user never saw it."

**If pressed / backup detail (with line refs):**
- `_iter_number_matches` (`tools/fidelity.py:45-75`) — the `_claim()` span-consumption
  function is the de-overlap mechanism; priority order is explicit in the code comment.
- `extract_numbers` (`tools/fidelity.py:78-83`) — docstring literally says "primary
  false-positive defense."
- `_nearest_year` (`tools/fidelity.py:86-96`) — prefers a year token *at or after* the
  number, falls back to before; mirrors both natural prose and the tools' own output format.
- `extract_year_bound_numbers` (`tools/fidelity.py:99-147`) — the enumeration pass only
  fires when `len(year_positions) == len(values of that kind)` AND all years precede all
  values; otherwise falls back to nearest-year. `inherit_block_year` is used only when
  indexing tool outputs (not the answer) because tool formats put dates on header lines
  above the figures.
- `_close` (`tools/fidelity.py:173-178`) — `rel_tol=0.01`, denominator is
  `max(abs(value), abs(candidate), 1e-9)` to stay stable near zero.
- `verify` (`tools/fidelity.py:181-207`) — the core loop: strict year-scoped match first,
  then the any-year fallback to classify hard vs. soft, then the
  `year not in grounded_years` override that forces hard even on coincidental value
  matches. That override is itself guarded — it only fires when `grounded_years` is
  non-empty, so a tool response with no year info at all doesn't get false-flagged.
- The function is **pure and flag-only** — it never mutates `answer`. That decoupling is
  itself a design choice: the deterministic checker can't be corrupted by bugs in the
  generative retry logic, and it's independently unit-testable without any LLM calls.
- Honest limitation if asked: it's regex-based, so it wouldn't catch a fabricated figure
  written entirely in prose with no unit token, and it only checks numbers — it has no way
  to verify a qualitative claim ("margins are improving") against the source data.

---

## Additional Q&A — added from live prep session (2026-07-26)

Four items that surfaced in a deep prep conversation and aren't polished anywhere else in this
doc. Treat these as Tier 2 — know them, don't lead with them unprompted.

### "Walk me through how you resolve a company name to a ticker" — the honest version

**Spoken answer:**
"I built a GLiNER-based deterministic resolution pipeline for this. GLiNER is a zero-shot NER
model that pulls literal company/organization name spans out of the query — typos included,
e.g. it still catches 'microsft' as a company mention. Each extracted name then goes through an
ordered ladder: exact match against a real SEC/NASDAQ ticker table, a curated alias list for
renames, fuzzy string matching for typos, and — only as a last resort — an embedding-gated
semantic search for descriptive references like 'the iPhone maker,' which refuses rather than
guessing below a confidence floor. It's fully built and unit-tested.

The honest caveat, if asked directly whether it's live: it isn't wired into the orchestrator's
actual turn path yet. Right now the planner LLM still extracts tickers directly as part of its
plan JSON, and the gates node only validates that list against real SEC filers — it doesn't do
name-to-ticker resolution itself. The GLiNER pipeline is the intended replacement for
LLM-guessed tickers, ready to wire in, but I haven't made that switch yet."

**If pressed on why it's not wired in yet:** [PLACEHOLDER — give your real reason if you have
one. If not, "next thing on my list" is fine — just don't imply it's already live.]

**Backup detail:** `tools/ner.py::extract_companies` (GLiNER, threshold 0.3, fails open to `[]`
if the model can't load); `tools/resolve.py::resolve_company`/`resolve_query` (the tier 0-5
ladder); tested in `tests/test_ner.py` and `tests/test_resolve.py`.

### "Tell me about a concurrency bug you've hit"

**Spoken answer:**
"One came from combining two independently reasonable choices that didn't compose safely under
load. I use DuckDB as a local cache for fetched financial data, and DuckDB only allows one
writer on its database file at a time. But my agents run in parallel — LangGraph's `Send` API
dispatches financials, calc, and ratios as concurrent worker threads — and several of them write
to that same cache. That caused real crashes: 'conflict on update' errors under concurrent
access. I fixed it with a process-wide lock that serializes every DuckDB connection through one
gate, so only one agent writes at a time. Since each cache operation is sub-50 milliseconds, the
serialization cost is negligible — but it's a good example of why you have to test two
reasonable tools together under real concurrency, not just trust that each is fine in
isolation."

**Backup detail:** `tools/db.py:15-23` — a `threading.RLock` wraps every `connect()` call; the
code comment states the cause directly: "Agents run in parallel (LangGraph dispatches
Send-fanned agent nodes on worker threads); when two of them each open their own connection and
one writes, the others crash."

### "How would you fix the latency on your external data calls (SEC EDGAR / yfinance)?"

**Spoken answer:**
"There's a difference between latency I've already solved and latency I haven't. What I've
solved: repeat-query latency, via a DuckDB cache with a TTL — 90 days for annual filings, 7 for
quarterly/earnings — so a second query for the same ticker never re-hits EDGAR or yfinance. And
within one round, if an agent needs data for multiple tickers, those fetches run concurrently
rather than serially.

What I haven't solved: first-time, cold-fetch latency, and rate-limit risk. There's no
retry-with-backoff on either data source right now, and no rate limiter — my concurrent fetches
could in principle exceed SEC EDGAR's fair-access limit under load. What I'd build next is a
token-bucket rate limiter shared across concurrent calls, retry-with-backoff for transient
failures, and — the bigger structural fix — eager, speculative fetching: as soon as a ticker is
resolved, fire off income statement, balance sheet, cash flow, and price fetches concurrently in
the background, before the agent's LLM has even decided what it needs. Right now latency
compounds because the model asks for one piece of data, waits a full round-trip, then asks for
the next — prefetching turns that into one wave of parallel I/O instead of several sequential
ones."

### "Why LangGraph?" — refined opening (lead into the existing Q6 answer below)

**Spoken answer (opening line, then continue straight into Q6):**
"Honestly, I built this as a learning project — my first real step into multiagent systems —
and I'd heard LangGraph was built specifically for this kind of orchestration, so I wanted
hands-on experience with it rather than hand-rolling my own first attempt. [Continue directly
into the Q6 answer: 'Most of what it does individually — dynamic fan-out, merging results,
retry branching — I could've written in plain Python without much trouble...']"

**Why lead with this:** it's honest and disarming, but on its own it invites "was it actually
the right choice?" — pairing it with the checkpointing payoff from Q6 turns "I wanted to learn a
trendy tool" into "I explored it to learn, and here's specifically what justified it."

---

# Section 6 — Questions to Ask Mr. Dor Haim at the End

These aren't rhetorical — actually listen and let the answer steer follow-ups. For each,
a quick note on *why it's a good question to ask* and how to bridge back to your project
if the conversation stalls.

### "What is the primary architecture pattern currently used for agents here — autonomous loop agents, strictly routed graph workflows, or a mix?"

Why ask it: it tells you whether their production system optimizes for flexibility
(autonomous ReAct-style loops) or predictability (a graph with fixed edges like yours).
Real production systems are very often a mix — a routed skeleton with a bounded loop
inside one or two nodes, which is exactly your own shape (bounded agent tool loop nested
inside a routed graph). If they say "mostly autonomous," a good follow-up is asking how
they bound runaway loops in practice — you have a concrete, specific answer to compare
notes on (the 4-guardrail design) rather than just nodding along.

### "How does the team handle agent evaluation and regression testing when deploying prompt/model updates to production?"

Why ask it: this is the question most candidates *can't* engage with substantively because
they haven't built the muscle themselves. You have — the offline model-comparison harness,
the real-data pinned regression policy, and the Langfuse trace-scoring loop. Listen for
whether they have anything playing the role your fidelity-score-on-every-trace plays: a
production signal that's checked continuously, not just a pre-deploy test suite. If they
don't have that, it's a legitimate, honest thing to note as a gap you'd be excited to help
close.

### "What's the primary use case you're building AI agents for here — customer-facing (property search, chat), internal (document/lease analysis, lead qualification), or both?"

Why ask it: this is the real-estate-specific version of "what will I actually work on." A
real-estate company hiring an "AI Agent Developer" is very likely building one of: a
customer-facing property-matching/chat assistant, an internal document pipeline (lease/contract
analysis — structurally similar to your SEC-filing pipeline), or a lead-qualification/CRM
automation agent. Their answer tells you which of your existing stories to lean on: document
extraction + verification maps directly to your fidelity-checked SEC pipeline; a chat assistant
maps to your orchestrator + synthesis architecture; CRM/lead automation maps to your tool-calling
and guardrail work. Don't assume domain knowledge of real estate is what they're testing for —
this question confirms it's the AI systems skill they want, which is what you should hear back.

### "What is the biggest technical bottleneck the team is currently facing with your AI agents (e.g., latency, tool accuracy, context size)?"

Why ask it: their answer tells you what you'd actually be working on day one. It also
gives you a natural, non-arrogant opening to mention your own version of whichever
bottleneck they name — you've hit and solved a version of latency (model routing by
task — reasoning models are too slow/unreliable for tool-heavy agent roles), tool
accuracy (per-agent scoped tool lists + the eval harness), and context size (agents run
in isolated sub-conversations rather than one shared, ballooning context) already. Let
their answer pick which story you tell — don't dump all three.

---

## A few sharp edges to be ready to admit honestly

Interviewers probe for self-awareness as much as competence. If asked "what's the weakest
part of this system," these are real, defensible answers — not conversation-enders:

- **The fidelity verifier is regex-based**, tuned for currency/percent/ratio patterns —
  it wouldn't catch a fabricated figure phrased in spelled-out prose with no unit
  ("about four hundred billion dollars" without a `$`/`B`), and it doesn't validate
  qualitative claims at all, only numbers.
- **The group-manifest override (MAG7/FAANG) is a hardcoded canonical list**, not a
  general solution — it fixes a specific planner failure mode but doesn't generalize to
  arbitrary group names the planner might invent.
- **Self-critique is intentionally single-pass** — a deliberate bound against runaway
  retries, but it means a stubborn hallucination that survives one re-prompt goes straight
  to web escalation rather than getting a second internal attempt.
- **No offline regression suite for fidelity specifically** — it's checked live per-turn
  and scored to Langfuse, but there's no fixed benchmark of "known-tricky prompts" run in
  CI the way the routing/tool-selection eval harness works. Good honest "what's next."
