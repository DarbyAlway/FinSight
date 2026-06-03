"""Shared tool-execution helper: runs a tool call inside a Langfuse span."""
import logging
import time

from langfuse import get_client

_MAX_RESULT_CHARS = 3000
_PREVIEW_CHARS = 300


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
