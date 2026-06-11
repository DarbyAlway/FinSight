import json
import logging
import os
import re
import time
from datetime import date

from langfuse import observe

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
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from graph_state import TurnState
from tools.search_guardrails import is_uncertain, _web_search_with_sources, agents_returned_nothing
from tools.groups import detect_group_in_query
from tools.resolve import validate_tickers
from tools.fidelity import verify as verify_fidelity


def _score_fidelity(n_mismatches: int) -> None:
    """Best-effort Langfuse trace score; never raises into the request path."""
    try:
        from langfuse import get_client
        get_client().score_current_trace(name="fidelity_mismatches", value=n_mismatches)
    except Exception as e:  # scoring is observability only
        logging.debug("[fidelity] score skipped: %s", e)

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


def _web_synthesis_messages(
    synth_sys: str, history: list[dict], user_input: str, snippets: str
) -> list[dict]:
    """Build synthesis messages for answering FROM WEB RESULTS. Deliberately
    rebuilt from scratch: reusing the agent-grounded messages leaks the
    'using ONLY the agent outputs' instruction, which overrides the web snippets
    (live failure: escalation searched the web, then the answer still said the
    data was 'not provided in the agent outputs')."""
    return [
        {"role": "system", "content": synth_sys},
        *history,
        {"role": "user", "content": (
            f"Question: {user_input}\n\n"
            f"Live web search results:\n{snippets}\n\n"
            "The internal data sources could not answer this question. Answer it "
            "using the web search results above — figures from these results are "
            "allowed and take precedence here. If the results do not contain the "
            "answer, say so plainly."
        )},
    ]


def _route_after_gates(state: dict):
    """Fan out one Send per planned agent, or skip straight to collect."""
    agents_to_run = state.get("agents_to_run") or []
    if not agents_to_run:
        return "collect"
    tickers = state.get("tickers") or []
    ticker_hint = f"[Use exactly these tickers: {', '.join(tickers)}]\n" if tickers else ""
    agent_input = ticker_hint + state["user_input"]
    return [
        Send("agent", {
            "agent_name": name,
            "agent_input": agent_input,
            "history": state.get("history", []),
            "tickers": tickers,
        })
        for name in agents_to_run
    ]


def _route_after_collect(state: dict) -> str:
    return "proactive_web" if state.get("intent") == "market_news" else "synthesize"


def _route_after_synthesis(state: dict) -> str:
    """market_news is web-sourced → finalize directly (never fidelity-checked).
    Empty/uncertain agent data → web fallback. Grounded + tool blocks → fidelity."""
    if state.get("intent") == "market_news":
        return "finalize"
    agents_to_run = state.get("agents_to_run") or []
    if agents_to_run and (
        agents_returned_nothing(state.get("agent_results") or {})
        or is_uncertain(state.get("answer", ""), threshold=0.85)
    ):
        return "web_fallback"
    if state.get("agent_tool_blocks"):
        return "fidelity_check"
    return "finalize"


def _route_after_fidelity(state: dict) -> str:
    return "self_critique" if state.get("hard_raws") else "finalize"


def _route_after_critique(state: dict) -> str:
    return "web_escalate" if state.get("hard_raws") else "finalize"


_SOURCE_LABELS = {
    "financials": "MARKET DATA",
    "news": "NEWS",
    "calc": "CALCULATIONS",
    "ratios": "SEC RATIOS",
}


@observe(name="plan_node")
def _plan_node(state: dict) -> dict:
    user_input = state["user_input"]
    time_sensitive = _is_time_sensitive(user_input)
    today_str = date.today().strftime("%B %d, %Y") if time_sensitive else ""
    today_prefix = f"Today is {today_str}. " if today_str else ""
    plan_sys = PLAN_SYSTEM.replace("{today}", today_prefix)
    synth_sys = (state.get("persona_system") or SYNTHESIS_SYSTEM).replace("{today}", today_prefix)

    planning_messages = [
        {"role": "system", "content": plan_sys},
        *state.get("history", []),
        {"role": "user", "content": user_input},
    ]
    plan_content, plan_tokens = _plan_step(planning_messages)
    intent = None
    try:
        plan = _parse_plan(plan_content)
        agents_to_run = plan.get("agents", [])
        tickers = plan.get("tickers", [])
        intent = plan.get("intent")
        logging.info("[Orchestrator] plan → intent=%s agents=%s  tickers=%s  reason=%s",
                     intent, agents_to_run, tickers, plan.get("reason", ""))
    except (json.JSONDecodeError, ValueError):
        logging.warning("[Orchestrator] plan JSON malformed — using keyword fallback")
        agents_to_run = _keyword_fallback(user_input)
        tickers = []
        logging.info("[Orchestrator] keyword fallback → agents=%s", agents_to_run)
    return {
        "intent": intent, "agents_to_run": agents_to_run, "tickers": tickers,
        "time_sensitive": time_sensitive, "synth_sys": synth_sys,
        "tokens": {"plan": plan_tokens},
    }


def _gates_node(state: dict) -> dict:
    user_input = state["user_input"]
    tickers = list(state.get("tickers") or [])
    agents_to_run = list(state.get("agents_to_run") or [])
    group_tickers = detect_group_in_query(user_input)
    if group_tickers:
        if set(group_tickers) != set(tickers):
            logging.info("[Gate1] manifest override: planner tickers=%s → %s", tickers, group_tickers)
        tickers = group_tickers
    if tickers:
        valid_tickers, invalid_tickers = validate_tickers(tickers)
        if invalid_tickers:
            logging.info("[Gate2] dropped invalid/unlisted tickers %s (kept %s)",
                         invalid_tickers, valid_tickers)
            tickers = valid_tickers
            if not tickers:
                logging.info("[Gate2] all requested tickers invalid — skipping data agents")
                agents_to_run = []
    return {"tickers": tickers, "agents_to_run": agents_to_run}


@observe(name="agent_node")
def _agent_node(state: dict) -> dict:
    # Build the map at CALL time so tests can patch orchestrator.run_financials etc.
    agent_map = {"financials": run_financials, "news": run_news,
                 "calc": run_calc, "ratios": run_ratios}
    name = state["agent_name"]
    fn = agent_map.get(name)
    if fn is None:
        logging.warning("[Orchestrator] unknown agent '%s' — skipping", name)
        return {"agent_results": {}, "agent_tool_blocks": {}, "tokens": {"agents": 0}}
    try:
        logging.info("[Orchestrator] → calling agent: %s", name)
        t1 = time.time()
        result, agent_tokens, tool_blocks = fn(
            state["agent_input"], "", history=state.get("history", []),
            expected_tickers=state.get("tickers") or None,
        )
        logging.info("[Orchestrator] ✓ agent %s done (%.2fs)", name, time.time() - t1)
        return {
            "agent_results": {name: result} if result is not None else {},
            "agent_tool_blocks": {name: tool_blocks} if tool_blocks else {},
            "tokens": {"agents": agent_tokens},
        }
    except Exception as e:
        logging.warning("[Orchestrator] %s agent failed — %s", name, e)
        _log_agent_error(name, e)
        return {"agent_results": {}, "agent_tool_blocks": {}, "tokens": {"agents": 0}}


def _collect_node(state: dict) -> dict:
    accumulated_context = ""
    agent_results = state.get("agent_results") or {}
    for name in state.get("agents_to_run") or []:
        if name in agent_results:
            label = _SOURCE_LABELS.get(name, name.upper())
            accumulated_context += f"\n\n[{label}]\n{agent_results[name]}"
    return {"accumulated_context": accumulated_context}


def _proactive_web_node(state: dict) -> dict:
    web_snippets, urls = _web_search_with_sources(
        state["user_input"], time_sensitive=state.get("time_sensitive", False))
    updates: dict = {"web_urls": urls}
    if web_snippets:
        updates["accumulated_context"] = (
            state.get("accumulated_context", "") + f"\n\n[WEB SEARCH RESULTS]\n{web_snippets}")
        logging.info("[Orchestrator] market_news → proactive web search (%d sources)", len(urls))
    return updates


@observe(name="synthesize_node")
def _synthesize_node(state: dict) -> dict:
    accumulated_context = state.get("accumulated_context", "")
    synthesis_messages = [{"role": "system", "content": state["synth_sys"]},
                          *state.get("history", [])]
    if accumulated_context:
        synthesis_messages.append({
            "role": "user",
            "content": (
                f"Question: {state['user_input']}\n\n"
                f"Agent outputs:\n{accumulated_context}\n\n"
                "Answer the question above using ONLY the agent outputs. "
                "Quote specific figures directly from the outputs."
            ),
        })
    else:
        synthesis_messages.append({"role": "user", "content": state["user_input"]})
    logging.info("[Synthesis] model=%s agents_context=%d chars", MODEL_SYNTHESIS, len(accumulated_context))
    answer, synth_tokens = _synthesis_step(synthesis_messages)
    logging.info("[Synthesis] output preview: %s", answer[:120].replace("\n", " "))
    return {"answer": answer, "synthesis_messages": synthesis_messages,
            "tokens": {"synthesis": synth_tokens}}


def _web_fallback_node(state: dict) -> dict:
    snippets, urls = _web_search_with_sources(
        state["user_input"], time_sensitive=state.get("time_sensitive", False))
    if not snippets:
        return {}
    web_messages = _web_synthesis_messages(
        state["synth_sys"], state.get("history", []), state["user_input"], snippets)
    fallback_answer, fallback_tokens = _synthesis_step(web_messages)
    answer = fallback_answer or state.get("answer", "")
    logging.info("[Synthesis] web-fallback output preview: %s", answer[:120].replace("\n", " "))
    if urls:
        answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in urls)
    logging.info("[Orchestrator] Tavily fallback used (%d sources)", len(urls))
    return {"answer": answer, "web_used": True, "tokens": {"synthesis": fallback_tokens}}


def _fidelity_check_node(state: dict) -> dict:
    merged_blocks: dict = {}
    for blocks in (state.get("agent_tool_blocks") or {}).values():
        merged_blocks.update(blocks)
    if not merged_blocks:
        return {"hard_raws": [], "mismatch_count": 0}
    mismatches = verify_fidelity(state["answer"], merged_blocks)
    for m in mismatches:
        logging.warning("[fidelity] %s untraced number %r (kind=%s, year=%s)",
                        "HARD" if m.hard else "soft", m.number.raw, m.number.kind, m.year)
    hard_raws = sorted({m.number.raw for m in mismatches if m.hard})
    if not hard_raws:
        logging.info("[fidelity] checked answer: %d untraced unit-bearing number(s)", len(mismatches))
        _score_fidelity(len(mismatches))
    return {"hard_raws": hard_raws, "mismatch_count": len(mismatches)}


def _self_critique_node(state: dict) -> dict:
    merged_blocks: dict = {}
    for blocks in (state.get("agent_tool_blocks") or {}).values():
        merged_blocks.update(blocks)
    bad = ", ".join(state["hard_raws"])
    logging.warning("[fidelity] %d HARD mismatch(es) [%s] → self-critique re-prompt",
                    len(state["hard_raws"]), bad)
    critique_messages = state["synthesis_messages"] + [
        {"role": "assistant", "content": state["answer"]},
        {"role": "user", "content": (
            f"Self-check: the figures [{bad}] in your answer do NOT appear in the agent "
            "outputs above — they look like prior knowledge, not the provided data. "
            "Re-read the agent outputs and rewrite your answer using ONLY figures that "
            "appear there. For any value not present, state that it is not available "
            "rather than estimating or recalling it."
        )},
    ]
    corrected, corr_tokens = _synthesis_step(critique_messages)
    answer = state["answer"]
    hard_raws = state["hard_raws"]
    mismatch_count = state.get("mismatch_count", 0)
    if corrected:
        answer = corrected
        mismatches = verify_fidelity(answer, merged_blocks)
        hard_raws = sorted({m.number.raw for m in mismatches if m.hard})
        mismatch_count = len(mismatches)
        logging.info("[fidelity] after self-critique: %d untraced (%d hard)",
                     len(mismatches), sum(1 for m in mismatches if m.hard))
    logging.info("[fidelity] checked answer: %d untraced unit-bearing number(s)", mismatch_count)
    _score_fidelity(mismatch_count)
    return {"answer": answer, "hard_raws": hard_raws, "mismatch_count": mismatch_count,
            "critique_done": True, "tokens": {"synthesis": corr_tokens}}


def _web_escalate_node(state: dict) -> dict:
    bad_after = ", ".join(state["hard_raws"])
    logging.warning("[fidelity] %d HARD mismatch(es) [%s] survived self-critique → web escalation",
                    len(state["hard_raws"]), bad_after)
    snippets, urls = _web_search_with_sources(
        state["user_input"], time_sensitive=state.get("time_sensitive", False))
    if snippets:
        web_messages = _web_synthesis_messages(
            state["synth_sys"], state.get("history", []), state["user_input"], snippets)
        web_answer, web_tokens = _synthesis_step(web_messages)
        if web_answer:
            answer = web_answer
            if urls:
                answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in urls)
            logging.info("[fidelity] escalation: web-grounded re-answer (%d sources)", len(urls))
            return {"answer": answer, "web_used": True, "tokens": {"synthesis": web_tokens}}
        return {"tokens": {"synthesis": web_tokens}}
    answer = state["answer"] + (
        "\n\n**Data caveat:** the figures "
        f"[{bad_after}] could not be verified against the fetched data — "
        "treat them as unreliable."
    )
    logging.warning("[fidelity] escalation: web empty — shipped with unverified-figures caveat")
    return {"answer": answer}


def _finalize_node(state: dict) -> dict:
    answer = state.get("answer", "")
    if state.get("intent") == "market_news" and state.get("web_urls"):
        answer += "\n\n**Web sources:**\n" + "\n".join(f"- {url}" for url in state["web_urls"])
    return {"answer": answer}


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


def build_graph(checkpointer=None):
    g = StateGraph(TurnState)
    g.add_node("plan", _plan_node)
    g.add_node("gates", _gates_node)
    g.add_node("agent", _agent_node)
    g.add_node("collect", _collect_node)
    g.add_node("proactive_web", _proactive_web_node)
    g.add_node("synthesize", _synthesize_node)
    g.add_node("web_fallback", _web_fallback_node)
    g.add_node("fidelity_check", _fidelity_check_node)
    g.add_node("self_critique", _self_critique_node)
    g.add_node("web_escalate", _web_escalate_node)
    g.add_node("finalize", _finalize_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "gates")
    g.add_conditional_edges("gates", _route_after_gates, ["agent", "collect"])
    g.add_edge("agent", "collect")
    g.add_conditional_edges("collect", _route_after_collect, ["proactive_web", "synthesize"])
    g.add_edge("proactive_web", "synthesize")
    g.add_conditional_edges("synthesize", _route_after_synthesis,
                            ["finalize", "web_fallback", "fidelity_check"])
    g.add_edge("web_fallback", "finalize")
    g.add_conditional_edges("fidelity_check", _route_after_fidelity, ["self_critique", "finalize"])
    g.add_conditional_edges("self_critique", _route_after_critique, ["web_escalate", "finalize"])
    g.add_edge("web_escalate", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


_GRAPH = build_graph()


@observe(name="process_turn")
def process_turn(
    user_input: str,
    messages: list[dict],
    persona_system: str | None = None,
) -> tuple[str, list[dict]]:
    t0 = time.time()
    initial_state = {
        "user_input": user_input,
        "history": messages,
        "persona_system": persona_system,
        "agent_results": {},
        "agent_tool_blocks": {},
        "accumulated_context": "",
        "answer": "",
        "web_used": False,
        "web_urls": [],
        "hard_raws": [],
        "critique_done": False,
        "tokens": {},
    }
    final_state = _GRAPH.invoke(initial_state)
    answer = final_state.get("answer", "")
    tokens = final_state.get("tokens", {})
    logging.info("[tokens] plan=%d agents=%d synthesis=%d total=%d",
                 tokens.get("plan", 0), tokens.get("agents", 0),
                 tokens.get("synthesis", 0), sum(tokens.values()))
    logging.info("[timing] total turn: %.2fs", time.time() - t0)
    updated_messages = messages + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, updated_messages
