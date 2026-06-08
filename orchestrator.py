import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from langfuse import observe
from opentelemetry import context as otel_context

import ollama

_FAILURE_LOG = os.path.join(os.path.dirname(__file__), "tests", "failure_log.jsonl")


def _log_agent_error(agent_name: str, error: Exception):
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "test": f"agent:{agent_name}",
        "error": f"{type(error).__name__}: {error}",
    }
    try:
        with open(_FAILURE_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass

from tools.config import MODEL, MODEL_PLAN, MODEL_SYNTHESIS
from tools.llm import llm_chat
from agents.financials import run as run_financials
from agents.news import run as run_news
from agents.calc import run as run_calc
from agents.ratios import run as run_ratios
from prompts import PLAN_SYSTEM, SYNTHESIS_SYSTEM, TIME_SENSITIVE_KEYWORDS
from tools.search_guardrails import is_uncertain, _web_search_with_sources, agents_returned_nothing
from tools.groups import detect_group_in_query
from tools.resolve import validate_tickers

OPT_PLAN = {"temperature": 0.0}
OPT_SYNTH = {"temperature": 0.3}


@observe(name="planner")
def _plan_step(messages: list[dict]) -> tuple[str, int]:
    return llm_chat(MODEL_PLAN, messages, temperature=0.0)


@observe(name="synthesis")
def _synthesis_step(messages: list[dict], temperature: float = 0.3) -> tuple[str, int]:
    return llm_chat(MODEL_SYNTHESIS, messages, temperature=temperature)


def _parse_plan(content: str) -> dict:
    content = content.strip()
    match = re.search(r'\{.*\}', content, re.DOTALL)
    parsed = json.loads(match.group() if match else content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Plan JSON is not an object: {type(parsed).__name__}")
    return parsed


def _is_time_sensitive(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in TIME_SENSITIVE_KEYWORDS)


def _keyword_fallback(question: str) -> list[str]:
    q = question.lower()
    if any(w in q for w in ["news", "headline", "article", "latest"]):
        return ["news"]
    if any(w in q for w in ["p/e", "pe ratio", "price to earnings", "price-to-earnings", "trailing pe", "forward pe"]):
        return ["financials"]
    if any(w in q for w in ["cash flow", "cash burn", "fcf", "free cash flow", "runway"]):
        return ["calc"]  # calc fetches its own SEC cash-flow data — financials no longer needed
    if any(w in q for w in ["current ratio", "interest coverage", "liquidity ratio"]):
        return ["ratios"]
    if any(w in q for w in ["price target", "target price", "analyst target"]):
        return ["financials"]
    if any(w in q for w in ["debt", "equity ratio", "d/e", "roa", "roe", "return on"]):
        return ["ratios"]
    if any(w in q for w in ["margin", "profit margin", "gross margin"]):
        return ["ratios"]
    if any(w in q for w in ["dcf", "cagr", "correlation", "peg", "rank", "valuation", "calculate"]):
        return ["calc"]
    return ["financials"]


@observe(name="process_turn")
def process_turn(
    user_input: str,
    messages: list[dict],
    persona_system: str | None = None,
) -> tuple[str, list[dict]]:
    today_str = date.today().strftime("%B %d, %Y") if _is_time_sensitive(user_input) else ""
    today_prefix = f"Today is {today_str}. " if today_str else ""
    plan_sys = PLAN_SYSTEM.replace("{today}", today_prefix)
    synth_sys = (persona_system or SYNTHESIS_SYSTEM).replace("{today}", today_prefix)

    planning_messages = [
        {"role": "system", "content": plan_sys},
        *messages,
        {"role": "user", "content": user_input},
    ]
    t0 = time.time()
    tickers: list[str] = []
    intent: str | None = None
    # Always let the planner LLM classify chat vs. financial — it returns
    # agents=[] for greetings and agents=[...] for real requests. (Replaces a
    # brittle keyword heuristic that misread "analyze rocket lab" as chitchat.)
    plan_content, plan_tokens = _plan_step(planning_messages)
    orchestrator_plan_text = plan_content
    logging.info("[timing] plan call: %.2fs", time.time() - t0)
    try:
        plan = _parse_plan(plan_content)
        agents_to_run: list[str] = plan.get("agents", [])
        tickers = plan.get("tickers", [])
        reason = plan.get("reason", "")
        intent = plan.get("intent")
        logging.info("[Orchestrator] plan → intent=%s agents=%s  tickers=%s  reason=%s", intent, agents_to_run, tickers, reason)
    except (json.JSONDecodeError, ValueError):
        logging.warning("[Orchestrator] plan JSON malformed — using keyword fallback")
        agents_to_run = _keyword_fallback(user_input)
        logging.info("[Orchestrator] keyword fallback → agents=%s", agents_to_run)

    # Gate 1 — group membership. If the user named a known group (MAG7, FAANG),
    # the planner LLM can't be trusted to expand it (it produced FB/BABA and
    # dropped META/NVDA), so override with the canonical manifest list.
    group_tickers = detect_group_in_query(user_input)
    if group_tickers:
        if set(group_tickers) != set(tickers):
            logging.info(
                "[Gate1] manifest override: planner tickers=%s → %s", tickers, group_tickers
            )
        tickers = group_tickers

    # Gate 2 — validation. Drop tickers that aren't currently-listed SEC filers:
    # dead/renamed (TWTR, SQ, FB) or hallucinated symbols. Catch them before
    # dispatch so we don't spend agents fetching nothing. If every requested
    # ticker is invalid, skip the data agents entirely and let synthesis explain
    # cheaply (instead of burning ~17k tokens discovering a dead ticker).
    if tickers:
        valid_tickers, invalid_tickers = validate_tickers(tickers)
        if invalid_tickers:
            logging.info(
                "[Gate2] dropped invalid/unlisted tickers %s (kept %s)",
                invalid_tickers, valid_tickers,
            )
            tickers = valid_tickers
            if not tickers:
                logging.info("[Gate2] all requested tickers invalid — skipping data agents")
                agents_to_run = []

    accumulated_context = ""
    agent_map = {
        "financials": run_financials,
        "news": run_news,
        "calc": run_calc,
        "ratios": run_ratios,
    }

    ticker_hint = f"[Use exactly these tickers: {', '.join(tickers)}]\n" if tickers else ""
    agent_input = ticker_hint + user_input

    # I7: agents run in worker threads, but Langfuse (OTEL) nests spans via the
    # OpenTelemetry context, which does NOT cross thread boundaries — so each
    # agent's @observe would start a NEW root trace (one Langfuse row per agent).
    # Capture the current context here and re-attach it inside each worker so all
    # agent spans nest under this query's process_turn trace (one row).
    parent_ctx = otel_context.get_current()

    def _run_agent(agent_name: str):
        ctx_token = otel_context.attach(parent_ctx)
        try:
            fn = agent_map.get(agent_name)
            if fn is None:
                logging.warning("[Orchestrator] unknown agent '%s' — skipping", agent_name)
                return agent_name, None, 0
            try:
                logging.info("[Orchestrator] → calling agent: %s", agent_name)
                t1 = time.time()
                result, agent_tokens = fn(agent_input, "", history=messages, expected_tickers=tickers if tickers else None)
                logging.info("[Orchestrator] ✓ agent %s done (%.2fs)", agent_name, time.time() - t1)
                return agent_name, result, agent_tokens
            except Exception as e:
                logging.warning("[Orchestrator] %s agent failed — %s", agent_name, e)
                _log_agent_error(agent_name, e)
                return agent_name, None, 0
        finally:
            otel_context.detach(ctx_token)

    agent_tokens_total = 0
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_run_agent, name): name for name in agents_to_run}
        agent_results = {}
        for future in as_completed(futures):
            name, result, agent_tokens = future.result()
            agent_tokens_total += agent_tokens
            if result is not None:
                agent_results[name] = result

    # Preserve plan order in accumulated context
    for name in agents_to_run:
        if name in agent_results:
            accumulated_context += f"\n\n[{name.upper()} AGENT]\n{agent_results[name]}"

    # I5 proactive: market_news queries need live web data the local cache
    # cannot provide ("why is the market down today"). Search up front and feed
    # the results into synthesis as a source block.
    proactive_web_urls: list[str] = []
    if intent == "market_news":
        web_snippets, proactive_web_urls = _web_search_with_sources(user_input)
        if web_snippets:
            accumulated_context += f"\n\n[WEB SEARCH RESULTS]\n{web_snippets}"
            logging.info("[Orchestrator] market_news → proactive web search (%d sources)", len(proactive_web_urls))

    synthesis_system = synth_sys
    synthesis_messages = [{"role": "system", "content": synthesis_system}, *messages]
    if accumulated_context:
        synthesis_messages.append({
            "role": "user",
            "content": (
                f"Question: {user_input}\n\n"
                f"Agent outputs:\n{accumulated_context}\n\n"
                "Answer the question above using ONLY the agent outputs. "
                "Quote specific figures directly from the outputs."
            ),
        })
    else:
        synthesis_messages.append({"role": "user", "content": user_input})

    t2 = time.time()
    logging.info("[Synthesis] model=%s agents_context=%d chars", MODEL_SYNTHESIS, len(accumulated_context))
    answer, synth_tokens = _synthesis_step(synthesis_messages)
    logging.info("[Synthesis] output preview: %s", answer[:120].replace("\n", " "))
    if intent == "market_news":
        if proactive_web_urls:
            answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in proactive_web_urls)
    elif agents_to_run and (agents_returned_nothing(agent_results) or is_uncertain(answer, threshold=0.85)):
        snippets, urls = _web_search_with_sources(user_input)
        if snippets:
            web_messages = synthesis_messages + [{
                "role": "user",
                "content": f"Web search results:\n{snippets}\n\nUse these to answer the question.",
            }]
            fallback_answer, fallback_tokens = _synthesis_step(web_messages)
            answer = fallback_answer or answer
            synth_tokens += fallback_tokens
            logging.info("[Synthesis] web-fallback output preview: %s", answer[:120].replace("\n", " "))
            if urls:
                answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in urls)
            logging.info("[Orchestrator] Tavily fallback used (%d sources)", len(urls))
    logging.info("[timing] synthesis call: %.2fs", time.time() - t2)

    total_tokens = plan_tokens + agent_tokens_total + synth_tokens
    logging.info("[tokens] plan=%d agents=%d synthesis=%d total=%d",
                 plan_tokens, agent_tokens_total, synth_tokens, total_tokens)
    logging.info("[timing] total turn: %.2fs", time.time() - t0)

    updated_messages = messages + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, updated_messages
