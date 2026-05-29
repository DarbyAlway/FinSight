import json
import logging
import os
import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_agent_counts: dict[str, int] = defaultdict(int)
_tool_counts: dict[str, int] = defaultdict(int)

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "agent_usage.jsonl")


def record_agent_call(agent_name: str):
    with _lock:
        _agent_counts[agent_name] += 1
        count = _agent_counts[agent_name]
    logging.info("[Monitor] agent=%s total_calls=%d", agent_name, count)
    _append({"event": "agent_call", "agent": agent_name, "total_calls": count})


def record_tool_call(agent_name: str, tool_name: str, args: dict):
    key = f"{agent_name}.{tool_name}"
    with _lock:
        _tool_counts[key] += 1
        count = _tool_counts[key]
    logging.info("[Monitor] agent=%s tool=%s args=%s total_calls=%d", agent_name, tool_name, args, count)
    _append({"event": "tool_call", "agent": agent_name, "tool": tool_name, "args": args, "total_calls": count})


def get_stats() -> dict:
    with _lock:
        return {"agents": dict(_agent_counts), "tools": dict(_tool_counts)}


def _append(entry: dict):
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
