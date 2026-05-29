import json
import logging
import os
import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_agent_counts: dict[str, int] = defaultdict(int)
_tool_counts: dict[str, int] = defaultdict(int)
_error_counts: dict[str, int] = defaultdict(int)

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "agent_usage.jsonl")

# Tool calls under this threshold are DuckDB cache hits
_CACHE_HIT_MS = 300


def record_agent_call(agent_name: str, duration_ms: int | None = None):
    with _lock:
        _agent_counts[agent_name] += 1
        count = _agent_counts[agent_name]
    _append({"event": "agent_call", "agent": agent_name, "total_calls": count, "duration_ms": duration_ms})


def record_tool_call(agent_name: str, tool_name: str, args: dict,
                     duration_ms: int | None = None, error: str | None = None):
    key = f"{agent_name}.{tool_name}"
    cache_hit = (duration_ms is not None and duration_ms < _CACHE_HIT_MS)
    with _lock:
        _tool_counts[key] += 1
        count = _tool_counts[key]
        if error:
            _error_counts[key] += 1
    _append({
        "event": "tool_call",
        "agent": agent_name,
        "tool": tool_name,
        "args": args,
        "duration_ms": duration_ms,
        "cache_hit": cache_hit,
        "error": error,
        "total_calls": count,
    })


def record_turn(agents_called: list[str], duration_ms: int):
    _append({"event": "turn", "agents": agents_called, "duration_ms": duration_ms})


def get_stats() -> dict:
    with _lock:
        return {
            "agents": dict(_agent_counts),
            "tools": dict(_tool_counts),
            "errors": dict(_error_counts),
        }


def _append(entry: dict):
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
