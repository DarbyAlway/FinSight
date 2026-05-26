import json
import logging
import os
import re
import time

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

from tools.config import MODEL
from agents.financials import run as run_financials
from agents.news import run as run_news
from agents.calc import run as run_calc
from agents.ratios import run as run_ratios
from prompts import PLAN_SYSTEM, SYNTHESIS_SYSTEM

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
}

import re as _re
_TICKER_RE = _re.compile(r'\b[A-Z]{1,5}\b')


def _is_conversational(question: str) -> bool: # check if it is a normal conversation or not
    q = question.lower()
    if any(kw in q for kw in _FINANCIAL_KEYWORDS): # check if its contain a financial keyword or not
        return False
    if _TICKER_RE.search(question): # check if its a ticker pattern
        return False
    return True


def _keyword_fallback(question: str) -> list[str]: # Check for the specific keyword, so the orchestrator can called the right agents
    q = question.lower()
    if any(w in q for w in ["news", "headline", "article", "latest"]):
        return ["news"]
    if any(w in q for w in ["p/e", "pe ratio", "price to earnings", "price-to-earnings", "trailing pe", "forward pe"]):
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
    planning_messages = [
        {"role": "system", "content": PLAN_SYSTEM},
        *messages,
        {"role": "user", "content": user_input},
    ]
    t0 = time.time()
    if _is_conversational(user_input):
        agents_to_run = []
        logging.info("[Orchestrator] conversational — no agents called")
    else:
        plan_response = ollama.chat(model=MODEL, messages=planning_messages, options=OPT_PLAN)
        plan_content = plan_response.message.content or ""
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

    for agent_name in agents_to_run:
        fn = agent_map.get(agent_name)
        if fn is None:
            logging.warning("[Orchestrator] unknown agent '%s' — skipping", agent_name)
            continue
        try:
            logging.info("[Orchestrator] → calling agent: %s", agent_name)
            t1 = time.time()
            result = fn(user_input, accumulated_context, history=messages)
            accumulated_context += f"\n\n[{agent_name.upper()} AGENT]\n{result}"
            logging.info("[Orchestrator] ✓ agent %s done (%.2fs)", agent_name, time.time() - t1)
        except Exception as e:
            logging.warning("[Orchestrator] %s agent failed — %s", agent_name, e)
            _log_agent_error(agent_name, e)

    synthesis_system = persona_system or SYNTHESIS_SYSTEM
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
    synthesis_response = ollama.chat(model=MODEL, messages=synthesis_messages, options=OPT_SYNTH)
    answer = synthesis_response.message.content or ""
    logging.info("[timing] synthesis call: %.2fs", time.time() - t2)
    logging.info("[timing] total turn: %.2fs", time.time() - t0)

    updated_messages = messages + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, updated_messages
