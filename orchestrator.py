import json
import logging
import re

import ollama

from tools.config import MODEL
from agents.financials import run as run_financials
from agents.news import run as run_news
from agents.calc import run as run_calc

PLAN_SYSTEM = (
    "You are a stock analysis orchestrator. Given the user's question, output a JSON plan "
    "with the agents to call and the tickers involved. "
    "Available agents: 'financials' (income statements, company info), "
    "'news' (headlines, news search), 'calc' (valuation ratios, growth metrics, portfolio analysis). "
    "If the question is conversational or can be answered from conversation context alone, use agents=[]. "
    "Respond with ONLY valid JSON in this format: "
    '{"agents": ["financials"], "tickers": ["AAPL"], "reason": "one line"}'
)

SYNTHESIS_SYSTEM = (
    "You are a stock analysis assistant. "
    "Synthesise the agent outputs below into a clear, direct answer. "
    "Cite which agent/tool provided each fact. "
    "Only state facts that came from agent outputs. "
    "If agent data is insufficient, say so rather than guessing."
)

OPT_PLAN = {"temperature": 0.0}
OPT_SYNTH = {"temperature": 0.3}


def _parse_plan(content: str) -> dict:
    content = content.strip()
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(content)


def _keyword_fallback(question: str) -> list[str]:
    q = question.lower()
    if any(w in q for w in ["news", "headline", "article", "latest"]):
        return ["news"]
    if any(w in q for w in ["dcf", "cagr", "correlation", "peg", "margin", "rank", "valuation", "calculate"]):
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
    plan_response = ollama.chat(model=MODEL, messages=planning_messages, options=OPT_PLAN)
    plan_content = plan_response.message.content or ""

    try:
        plan = _parse_plan(plan_content)
        agents_to_run: list[str] = plan.get("agents", [])
    except (json.JSONDecodeError, ValueError):
        logging.warning("Orchestrator plan JSON malformed — using keyword fallback")
        agents_to_run = _keyword_fallback(user_input)

    accumulated_context = ""
    agent_map = {
        "financials": run_financials,
        "news": run_news,
        "calc": run_calc,
    }

    for agent_name in agents_to_run:
        fn = agent_map.get(agent_name)
        if fn is None:
            continue
        try:
            result = fn(user_input, accumulated_context)
            accumulated_context += f"\n\n[{agent_name.upper()} AGENT]\n{result}"
            logging.info("Orchestrator: %s agent completed", agent_name)
        except Exception as e:
            logging.warning("Orchestrator: %s agent failed — %s", agent_name, e)

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

    synthesis_response = ollama.chat(model=MODEL, messages=synthesis_messages, options=OPT_SYNTH)
    answer = synthesis_response.message.content or ""

    updated_messages = messages + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, updated_messages
