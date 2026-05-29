import json
import os
import threading
import time
from collections import defaultdict
from datetime import datetime

_lock = threading.Lock()
_agent_counts: dict[str, int] = defaultdict(int)
_tool_counts: dict[str, int] = defaultdict(int)
_error_counts: dict[str, int] = defaultdict(int)

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")

# Tool calls under this threshold are DuckDB cache hits
_CACHE_HIT_MS = 300


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _append_to(filename: str, entry: dict):
    """Read existing JSON array, append entry, write back — serialized via lock."""
    path = os.path.join(_LOG_DIR, filename)
    with _lock:
        try:
            os.makedirs(_LOG_DIR, exist_ok=True)
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
            else:
                data = []
            data.append(entry)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except (OSError, json.JSONDecodeError):
            pass


def record_agent_call(agent_name: str, duration_ms: int | None = None):
    with _lock:
        _agent_counts[agent_name] += 1
        count = _agent_counts[agent_name]
    _append_to(
        f"app_events_{_today()}.json",
        {
            "event": "agent_call",
            "agent": agent_name,
            "total_calls": count,
            "duration_ms": duration_ms,
            "ts": _now_ts(),
        },
    )


def record_tool_call(agent_name: str, tool_name: str, args: dict,
                     duration_ms: int | None = None, error: str | None = None):
    key = f"{agent_name}.{tool_name}"
    cache_hit = duration_ms is not None and duration_ms < _CACHE_HIT_MS
    with _lock:
        _tool_counts[key] += 1
        count = _tool_counts[key]
        if error:
            _error_counts[key] += 1
    _append_to(
        f"agent_tools_{_today()}.json",
        {
            "event": "tool_call",
            "agent": agent_name,
            "tool": tool_name,
            "args": args,
            "duration_ms": duration_ms,
            "cache_hit": cache_hit,
            "error": error,
            "total_calls": count,
            "ts": _now_ts(),
        },
    )


def record_turn(agents_called: list[str], duration_ms: int):
    _append_to(
        f"app_events_{_today()}.json",
        {
            "event": "turn",
            "agents": agents_called,
            "duration_ms": duration_ms,
            "ts": _now_ts(),
        },
    )


def record_token_usage(agent_name: str, prompt_tokens: int, completion_tokens: int):
    _append_to(
        f"app_events_{_today()}.json",
        {
            "event": "token_usage",
            "agent": agent_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "ts": _now_ts(),
        },
    )


def get_stats() -> dict:
    with _lock:
        return {
            "agents": dict(_agent_counts),
            "tools": dict(_tool_counts),
            "errors": dict(_error_counts),
        }
