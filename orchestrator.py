import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

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
from tools.monitoring import record_agent_call
from agents.financials import run as run_financials
from agents.news import run as run_news
from agents.calc import run as run_calc
from agents.ratios import run as run_ratios
from prompts import PLAN_SYSTEM, SYNTHESIS_SYSTEM, TIME_SENSITIVE_KEYWORDS
from tools.search_guardrails import is_uncertain, _web_search_with_sources

OPT_PLAN = {"temperature": 0.0}
OPT_SYNTH = {"temperature": 0.3}


def _parse_plan(content: str) -> dict:
    content = content.strip()
    match = re.search(r'\{.*\}', content, re.DOTALL)
    parsed = json.loads(match.group() if match else content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Plan JSON is not an object: {type(parsed).__name__}")
    return parsed


_FINANCIAL_KEYWORDS = {
    "revenue", "income", "earnings", "profit", "loss", "sales", "margin",
    "cagr", "dcf", "peg", "valuation", "p/e", "pe ratio", "eps",
    "news", "headline", "article", "filing", "10-k", "10-q",
    "stock", "share", "price", "dividend", "sector", "analyst",
    "correlation", "rank", "compare", "quarterly", "annual",
    "debt", "equity", "roa", "roe", "balance sheet",
    "cash", "burn", "runway", "liquidity", "free cash flow", "fcf",
    "cash flow", "operating cash", "capex", "interest coverage",
    "current ratio", "price target", "target price",
    "guidance", "outlook", "forecast", "beat", "miss", "report", "trend",
}

import re as _re
_TICKER_RE = _re.compile(r'\b[A-Z]{1,5}\b')

def _is_time_sensitive(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in TIME_SENSITIVE_KEYWORDS)


def _is_conversational(question: str) -> bool: # check if it is a normal conversation or not
    q = question.lower()
    if any(kw in q for kw in _FINANCIAL_KEYWORDS): # check if its contain a financial keyword or not
        return False
    if _TICKER_RE.search(question): # check if its a ticker pattern
        return False
    return True


def _keyword_fallback(question: str) -> list[str]:
    q = question.lower()
    if any(w in q for w in ["news", "headline", "article", "latest"]):
        return ["news"]
    if any(w in q for w in ["p/e", "pe ratio", "price to earnings", "price-to-earnings", "trailing pe", "forward pe"]):
        return ["financials"]
    if any(w in q for w in ["cash flow", "cash burn", "fcf", "free cash flow", "runway"]):
        return ["financials", "calc"]
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
    if _is_conversational(user_input):
        agents_to_run = []
        logging.info("[Orchestrator] conversational — no agents called")
    else:
        plan_content = llm_chat(MODEL_PLAN, planning_messages, temperature=0.0)
        logging.info("[timing] plan call: %.2fs", time.time() - t0)
        try:
            plan = _parse_plan(plan_content)
            agents_to_run: list[str] = plan.get("agents", [])
            tickers = plan.get("tickers", [])
            reason = plan.get("reason", "")
            logging.info("[Orchestrator] plan → agents=%s  tickers=%s  reason=%s", agents_to_run, tickers, reason)
        except (json.JSONDecodeError, ValueError):
            logging.warning("[Orchestrator] plan JSON malformed — using keyword fallback")
            agents_to_run = _keyword_fallback(user_input)
            logging.info("[Orchestrator] keyword fallback → agents=%s", agents_to_run)

    accumulated_context = ""
    agent_map = {
        "financials": run_financials,
        "news": run_news,
        "calc": run_calc,
        "ratios": run_ratios,
    }

    ticker_hint = f"[Use exactly these tickers: {', '.join(tickers)}]\n" if tickers else ""
    agent_input = ticker_hint + user_input

    def _run_agent(agent_name: str):
        fn = agent_map.get(agent_name)
        if fn is None:
            logging.warning("[Orchestrator] unknown agent '%s' — skipping", agent_name)
            return agent_name, None
        try:
            logging.info("[Orchestrator] → calling agent: %s", agent_name)
            record_agent_call(agent_name)
            t1 = time.time()
            result = fn(agent_input, "", history=messages)
            logging.info("[Orchestrator] ✓ agent %s done (%.2fs)", agent_name, time.time() - t1)
            return agent_name, result
        except Exception as e:
            logging.warning("[Orchestrator] %s agent failed — %s", agent_name, e)
            _log_agent_error(agent_name, e)
            return agent_name, None

    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_run_agent, name): name for name in agents_to_run}
        agent_results = {}
        for future in as_completed(futures):
            name, result = future.result()
            if result is not None:
                agent_results[name] = result

    # Preserve plan order in accumulated context
    for name in agents_to_run:
        if name in agent_results:
            accumulated_context += f"\n\n[{name.upper()} AGENT]\n{agent_results[name]}"

    synthesis_system = synth_sys
    synthesis_messages = [{"role": "system", "content": synthesis_system}, *messages]
    synthesis_messages.append({"role": "user", "content": user_input})
    if accumulated_context:
        synthesis_messages.append({
            "role": "user",
            "content": (
                f"Agent outputs:\n{accumulated_context}\n\n"
                "Based ONLY on the above agent outputs, answer the user's question. "
                "Quote specific figures directly from the outputs."
            ),
        })

    t2 = time.time()
    answer = llm_chat(MODEL_SYNTHESIS, synthesis_messages, temperature=0.3)
    if is_uncertain(answer):
        snippets, urls = _web_search_with_sources(user_input)
        if snippets:
            web_messages = synthesis_messages + [{
                "role": "user",
                "content": f"Web search results:\n{snippets}\n\nUse these to answer the question.",
            }]
            answer = llm_chat(MODEL_SYNTHESIS, web_messages, temperature=0.3) or answer
            if urls:
                answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in urls)
            logging.info("[Orchestrator] Tavily fallback used (%d sources)", len(urls))
    logging.info("[timing] synthesis call: %.2fs", time.time() - t2)
    logging.info("[timing] total turn: %.2fs", time.time() - t0)

    updated_messages = messages + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, updated_messages
