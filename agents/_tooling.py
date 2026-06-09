"""Shared tool-execution helpers: a single Langfuse-traced tool call, and the
guarded agent tool-calling loop used by all four agents."""
import json
import logging
import time

from langfuse import get_client

_MAX_RESULT_CHARS = 3000
_PREVIEW_CHARS = 300

# Phase A guardrail defaults (token-explosion safety net). A single runaway
# agent once burned 85k tokens looping on one tool — these brakes cap that.
_MAX_ITERATIONS = 8       # hard universal cap on tool-call rounds
_TOKEN_BUDGET = 30000     # per-agent token ceiling
_NO_PROGRESS_ERRORS = 3   # consecutive error results before bailing


def execute_tool(agent_tag: str, name: str, args: dict, fn) -> str:
    """Execute a tool call, trace it as a Langfuse 'tool' span, log a preview.

    Returns the (possibly truncated) tool result string.
    """
    lf = get_client()
    t0 = time.perf_counter()
    with lf.start_as_current_observation(name=name, as_type="tool", input=args) as span:
        result = fn(**args) if fn else f"Unknown tool: {name}"
        if isinstance(result, str) and len(result) > _MAX_RESULT_CHARS:
            result = result[:_MAX_RESULT_CHARS] + "\n... [truncated]"
        span.update(output=result)
    dur = round((time.perf_counter() - t0) * 1000)
    preview = (result if isinstance(result, str) else str(result)).replace("\n", " ")[:_PREVIEW_CHARS]
    logging.info("[%s] %s(%s) → %dms\n  ↳ %s", agent_tag, name, args, dur, preview)
    return result


def _is_error_result(result) -> bool:
    """True if a tool result looks like an error / no-data string."""
    if not isinstance(result, str):
        return False
    head = result.lstrip()[:80].lower()
    return head.startswith(("error", "unknown tool", "no ", "could not", "failed"))


def run_tool_loop(
    agent_tag: str,
    client,
    model: str,
    messages: list[dict],
    tools: list[dict],
    tool_functions: dict,
    temperature: float = 0.1,
    max_iterations: int = _MAX_ITERATIONS,
    token_budget: int = _TOKEN_BUDGET,
    expected_tickers: list[str] | None = None,
) -> tuple[str, int, dict]:
    """Run an agent's tool-calling loop with layered guardrails.
    also this is a loggin for tools loop function
    Guardrails (cheapest/earliest first) — each logs a warning when it trips:
      a. max-iteration cap        — hard universal brake on runaway loops
      b. duplicate-call cache     — identical (tool, args) served from cache, never re-run
      c. no-progress detection    — N consecutive error/no-data results → stop
      d. per-agent token budget   — accumulated tokens over budget → stop

    On any guardrail trip the loop forces one final, tool-free answer from the
    data already gathered (so we degrade gracefully instead of erroring out).

    Returns ``(answer_text, total_tokens, tool_blocks)`` where ``tool_blocks``
    is a ``dict[str, str]`` mapping ``"name(args_json)"`` to each tool's raw
    result (already capped at 3000 chars by ``execute_tool``).
    """
    usage = {"prompt": 0, "completion": 0}

    def _chat(**kwargs):
        # I1: log each LLM round's latency + tokens so a slow agent is visible
        # (the per-agent total hides which round was slow / rate-limited).
        t0 = time.perf_counter()
        try:
            r = client.chat.completions.create(**kwargs)
        except Exception as e:
            dur = round((time.perf_counter() - t0) * 1000)
            logging.warning("[%s] llm call FAILED after %dms: %s", agent_tag, dur, e)
            raise
        dur = round((time.perf_counter() - t0) * 1000)
        if r.usage:
            usage["prompt"] += r.usage.prompt_tokens
            usage["completion"] += r.usage.completion_tokens
            logging.info(
                "[%s] llm call: %dms prompt=%d completion=%d",
                agent_tag, dur, r.usage.prompt_tokens, r.usage.completion_tokens,
            )
        else:
            logging.info("[%s] llm call: %dms (no usage)", agent_tag, dur)
        return r

    response = _chat(
        model=model, messages=messages, tools=tools,
        tool_choice="required", temperature=temperature,
    )
    msg = response.choices[0].message

    seen: dict[tuple, str] = {}   # (name, args_json) -> cached result
    result_log: list[bool] = []   # per-tool-call: True if error-like
    iterations = 0

    while msg.tool_calls:
        iterations += 1
        if iterations > max_iterations:
            logging.warning("[%s] guardrail: hit max iterations (%d) — stopping tool loop", agent_tag, max_iterations)
            break
        used = usage["prompt"] + usage["completion"]
        if used > token_budget:
            logging.warning("[%s] guardrail: token budget exceeded (%d > %d) — stopping tool loop", agent_tag, used, token_budget)
            break

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            key = (name, json.dumps(args, sort_keys=True))
            if key in seen:
                logging.warning("[%s] guardrail: duplicate call %s(%s) — serving cached result", agent_tag, name, args)
                cached = seen[key]
                result = (cached + "\n[NOTE: this exact call was already made — use the result above; do not repeat it.]"
                          if isinstance(cached, str) else cached)
            else:
                fn = tool_functions.get(name)
                result = execute_tool(agent_tag, name, args, fn)
                seen[key] = result
            result_log.append(_is_error_result(result))
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

        if len(result_log) >= _NO_PROGRESS_ERRORS and all(result_log[-_NO_PROGRESS_ERRORS:]):
            logging.warning("[%s] guardrail: %d consecutive error/no-data results — stopping tool loop", agent_tag, _NO_PROGRESS_ERRORS)
            break

        response = _chat(model=model, messages=messages, tools=tools, temperature=temperature)
        msg = response.choices[0].message

    if msg.tool_calls:
        # A guardrail interrupted the loop. Force a final answer with no tools so
        # the agent summarizes whatever it has rather than returning empty.
        messages.append({
            "role": "user",
            "content": "Stop calling tools. Using ONLY the data already gathered above, write your final answer now.",
        })
        final = _chat(model=model, messages=messages, temperature=temperature)
        summary = final.choices[0].message.content or ""
    else:
        summary = msg.content or ""

    if expected_tickers:
        missing = [t for t in expected_tickers if t not in summary]
        if missing:
            logging.info("[%s] self-critique: missing %s — requesting completion", agent_tag, missing)
            messages.append({"role": "assistant", "content": summary})
            messages.append({
                "role": "user",
                "content": (
                    f"Your response is missing data for: {', '.join(missing)}. "
                    "Return ONLY the ## TICKER sections for these missing tickers — "
                    "do not repeat tickers already covered."
                ),
            })
            fix = _chat(model=model, messages=messages, tools=tools, temperature=temperature)
            if fix.choices[0].message.content:
                summary += "\n\n" + fix.choices[0].message.content

    tool_blocks = {
        f"{name}({args_json})": result
        for (name, args_json), result in seen.items()
        if isinstance(result, str)
    }
    total = usage["prompt"] + usage["completion"]
    logging.info("[%s] tokens: prompt=%d completion=%d total=%d",
                 agent_tag, usage["prompt"], usage["completion"], total)
    return summary, total, tool_blocks
