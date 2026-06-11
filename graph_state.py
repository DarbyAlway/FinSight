"""LangGraph state schema for the orchestrator turn graph (Phase 1 parity).

Reducers replace the ThreadPoolExecutor `as_completed` merging: parallel
Send-dispatched agent nodes each return their slice; LangGraph merges them.
"""
from typing import Annotated, TypedDict


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


def add_token_counts(a: dict | None, b: dict | None) -> dict:
    out = dict(a or {})
    for key, value in (b or {}).items():
        out[key] = out.get(key, 0) + value
    return out


class TurnState(TypedDict, total=False):
    # inputs
    user_input: str
    history: list          # prior conversation messages (role/content dicts)
    persona_system: str | None
    # derived once in plan_node
    synth_sys: str
    time_sensitive: bool
    # planning
    intent: str | None
    agents_to_run: list
    tickers: list
    # agent results — merged by reducers from parallel Send nodes
    agent_results: Annotated[dict, merge_dicts]
    agent_tool_blocks: Annotated[dict, merge_dicts]
    # synthesis
    accumulated_context: str
    synthesis_messages: list   # kept for critique/escalation re-prompts
    answer: str
    web_used: bool             # True once a web-grounded answer replaced the agent
                               # answer; read by _route_after_web_fallback (empty web
                               # result keeps the original answer → fidelity_check);
                               # otherwise an observability/checkpoint marker
    web_urls: list             # proactive (market_news) source urls
    # fidelity control
    hard_raws: list            # raw strings of HARD-mismatched figures
    mismatch_count: int        # total untraced numbers from last verify pass
    critique_done: bool        # observability/checkpoint marker only — no route reads
                               # it (the critique is single-pass by graph topology)
    # accounting
    tokens: Annotated[dict, add_token_counts]
    # Send-payload fields (set per agent_node invocation only)
    agent_name: str
    agent_input: str
