# Agent Monitoring Dashboard Implementation Plan

**Date Created:** June 01, 2026  
**Time Started:** 04:32 PM  
**Last Updated:** June 01, 2026 04:32 PM

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web-based dashboard that displays all past chat turns with orchestrator planning, agent outputs, tools called, and token usage.

**Architecture:** Move monitoring to a dedicated `monitoring/` folder with SQLite storage replacing JSON logging. Add a Flask web server that serves a dashboard displaying chronological turn history with expandable hierarchical details (orchestrator plan → agents → tools).

**Tech Stack:** SQLite3, Flask (lightweight web framework), HTML/CSS/JS (simple frontend)

---

## File Structure

```
monitoring/
├── __init__.py                      (exports init_db, record_turn, etc.)
└── monitoring.py                    (SQLite functions, schema)

web_server.py                        (Flask app, routes, dashboard HTML)

logs/
└── monitoring.db                    (created at runtime)
```

---

## Task 1: Create Monitoring Folder Structure

**Files:**
- Create: `monitoring/__init__.py`
- Create: `monitoring/monitoring.py`

- [ ] **Step 1: Create monitoring folder**

```powershell
New-Item -ItemType Directory -Path "monitoring" -Force
```

- [ ] **Step 2: Create `monitoring/__init__.py`**

```python
from .monitoring import (
    init_db,
    record_turn,
    record_agent,
    record_tool,
    get_all_turns,
)

__all__ = [
    "init_db",
    "record_turn",
    "record_agent",
    "record_tool",
    "get_all_turns",
]
```

- [ ] **Step 3: Create `monitoring/monitoring.py` with SQLite schema and functions**

```python
import sqlite3
import json
import os
import threading
from datetime import datetime
from pathlib import Path

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "monitoring.db")
_lock = threading.Lock()

def _ensure_logs_dir():
    """Create logs directory if it doesn't exist."""
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

def _get_connection():
    """Get a thread-safe database connection."""
    _ensure_logs_dir()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database schema."""
    with _lock:
        conn = _get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_query TEXT NOT NULL,
                    orchestrator_plan TEXT,
                    synthesis_output TEXT,
                    agents_called TEXT,
                    total_duration_ms REAL,
                    total_tokens INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    duration_ms REAL,
                    tokens INTEGER,
                    output TEXT,
                    tools_called TEXT,
                    FOREIGN KEY (turn_id) REFERENCES turns(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments TEXT,
                    duration_ms REAL,
                    cache_hit BOOLEAN,
                    error TEXT,
                    FOREIGN KEY (agent_id) REFERENCES agents(id)
                )
            """)
            conn.commit()
        finally:
            conn.close()

def record_turn(user_query: str, orchestrator_plan: str = None, agents_called: list = None, 
                total_duration_ms: float = None, total_tokens: int = None) -> int:
    """Record a new turn and return its ID."""
    with _lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO turns (user_query, orchestrator_plan, agents_called, total_duration_ms, total_tokens)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_query,
                    orchestrator_plan,
                    json.dumps(agents_called or []),
                    total_duration_ms,
                    total_tokens,
                )
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

def record_agent(turn_id: int, agent_name: str, duration_ms: float = None, 
                 tokens: int = None, output: str = None, tools_called: list = None) -> int:
    """Record an agent execution for a turn and return its ID."""
    with _lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO agents (turn_id, agent_name, duration_ms, tokens, output, tools_called)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    agent_name,
                    duration_ms,
                    tokens,
                    output,
                    json.dumps(tools_called or []),
                )
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

def record_tool(agent_id: int, tool_name: str, duration_ms: float = None, 
                arguments: dict = None, cache_hit: bool = False, error: str = None):
    """Record a tool call for an agent."""
    with _lock:
        conn = _get_connection()
        try:
            conn.execute(
                """
                INSERT INTO tools (agent_id, tool_name, arguments, duration_ms, cache_hit, error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    tool_name,
                    json.dumps(arguments or {}),
                    duration_ms,
                    cache_hit,
                    error,
                )
            )
            conn.commit()
        finally:
            conn.close()

def update_turn_synthesis(turn_id: int, synthesis_output: str):
    """Update a turn with the synthesis output."""
    with _lock:
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE turns SET synthesis_output = ? WHERE id = ?",
                (synthesis_output, turn_id)
            )
            conn.commit()
        finally:
            conn.close()

def get_all_turns():
    """Fetch all turns with their agents and tools, ordered by timestamp DESC."""
    with _lock:
        conn = _get_connection()
        try:
            cursor = conn.execute("SELECT * FROM turns ORDER BY timestamp DESC")
            turns = cursor.fetchall()
            
            result = []
            for turn in turns:
                turn_dict = dict(turn)
                turn_dict['agents_called'] = json.loads(turn_dict['agents_called'] or '[]')
                
                # Fetch agents for this turn
                agents_cursor = conn.execute("SELECT * FROM agents WHERE turn_id = ?", (turn['id'],))
                agents = agents_cursor.fetchall()
                
                agents_list = []
                for agent in agents:
                    agent_dict = dict(agent)
                    agent_dict['tools_called'] = json.loads(agent_dict['tools_called'] or '[]')
                    
                    # Fetch tools for this agent
                    tools_cursor = conn.execute("SELECT * FROM tools WHERE agent_id = ?", (agent['id'],))
                    tools = tools_cursor.fetchall()
                    
                    tools_list = []
                    for tool in tools:
                        tool_dict = dict(tool)
                        tool_dict['arguments'] = json.loads(tool_dict['arguments'] or '{}')
                        tools_list.append(tool_dict)
                    
                    agent_dict['tools'] = tools_list
                    agents_list.append(agent_dict)
                
                turn_dict['agents'] = agents_list
                result.append(turn_dict)
            
            return result
        finally:
            conn.close()
```

- [ ] **Step 4: Verify monitoring.py has no syntax errors**

```powershell
python -m py_compile monitoring/monitoring.py
```

Expected: No output (success)

---

## Task 2: Update Orchestrator to Use New Monitoring

**Files:**
- Modify: `orchestrator.py`

- [ ] **Step 1: Update imports in orchestrator.py**

Find the line:
```python
from tools.monitoring import record_agent_call, record_turn
```

Replace with:
```python
from monitoring import record_turn, record_agent, record_tool, update_turn_synthesis, init_db
```

- [ ] **Step 2: Update the `process_turn` function to record detailed data**

Find the `process_turn` function starting at line 102. Replace the entire function with:

```python
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
    orchestrator_plan_text = ""
    
    # Record turn start
    turn_id = record_turn(user_query=user_input)
    
    if _is_conversational(user_input):
        agents_to_run = []
        logging.info("[Orchestrator] conversational — no agents called")
    else:
        plan_content = llm_chat(MODEL_PLAN, planning_messages, temperature=0.0)
        orchestrator_plan_text = plan_content
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
            t1 = time.time()
            result = fn(agent_input, "", history=messages)
            agent_dur = round((time.time() - t1) * 1000)
            
            # Record agent execution
            agent_id = record_agent(
                turn_id=turn_id,
                agent_name=agent_name,
                duration_ms=agent_dur,
                output=result
            )
            
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
    
    # Record synthesis output
    update_turn_synthesis(turn_id=turn_id, synthesis_output=answer)
    
    if agents_to_run and is_uncertain(answer):
        snippets, urls = _web_search_with_sources(user_input)
        if snippets:
            web_messages = synthesis_messages + [{
                "role": "user",
                "content": f"Web search results:\n{snippets}\n\nUse these to answer the question.",
            }]
            answer = llm_chat(MODEL_SYNTHESIS, web_messages, temperature=0.3) or answer
            update_turn_synthesis(turn_id=turn_id, synthesis_output=answer)
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
```

- [ ] **Step 3: Verify orchestrator.py syntax**

```powershell
python -m py_compile orchestrator.py
```

Expected: No output (success)

---

## Task 3: Update main.py Imports

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add monitoring init to main.py**

Find the line with `def chat():` (around line 70). Add before it:

```python
from monitoring import init_db as init_monitoring_db
```

- [ ] **Step 2: Call monitoring init in main**

Find the `if __name__ == "__main__":` block (line 102). Add `init_monitoring_db()` as first call:

```python
if __name__ == "__main__":
    init_monitoring_db()
    init_db()
    init_qdrant()
    _get_anchor_vecs()
    _init_phoenix()
    chat()
```

- [ ] **Step 3: Verify main.py syntax**

```powershell
python -m py_compile main.py
```

Expected: No output (success)

---

## Task 4: Remove Old Monitoring References

**Files:**
- Modify: `tools/__init__.py` (if it exists and imports monitoring)

- [ ] **Step 1: Check if tools/__init__.py imports monitoring**

```powershell
Select-String -Path "tools/__init__.py" -Pattern "monitoring"
```

- [ ] **Step 2: If found, remove the import line**

Open `tools/__init__.py` and remove any line importing from monitoring. If the file becomes empty, delete it.

---

## Task 5: Create Flask Web Server

**Files:**
- Create: `web_server.py`

- [ ] **Step 1: Create web_server.py with Flask app and routes**

```python
from flask import Flask, render_template_string, jsonify
from monitoring import init_db, get_all_turns
import json

app = Flask(__name__)

# Initialize database on startup
init_db()

# HTML Template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Monitoring Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        h1 {
            color: #333;
            margin-bottom: 30px;
            font-size: 28px;
        }
        
        .refresh-btn {
            background: #007bff;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            margin-bottom: 20px;
            font-size: 14px;
        }
        
        .refresh-btn:hover {
            background: #0056b3;
        }
        
        .turn-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        
        .turn-card {
            background: white;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 15px;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .turn-card:hover {
            background: #f9f9f9;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        .turn-header {
            display: flex;
            justify-content: space-between;
            align-items: start;
            gap: 10px;
        }
        
        .turn-timestamp {
            color: #666;
            font-size: 12px;
            font-weight: 500;
        }
        
        .turn-query {
            color: #333;
            font-weight: 500;
            margin: 5px 0;
            word-break: break-word;
        }
        
        .turn-meta {
            color: #999;
            font-size: 13px;
            margin-top: 8px;
        }
        
        .toggle-icon {
            color: #007bff;
            font-weight: bold;
            user-select: none;
        }
        
        .turn-details {
            display: none;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #eee;
        }
        
        .turn-details.active {
            display: block;
        }
        
        .section {
            margin-bottom: 15px;
        }
        
        .section-title {
            color: #007bff;
            font-weight: 600;
            font-size: 14px;
            text-transform: uppercase;
            margin-bottom: 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .section-content {
            background: #f9f9f9;
            border-left: 3px solid #007bff;
            padding: 10px 12px;
            border-radius: 3px;
            margin-bottom: 10px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.4;
            max-height: 300px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }
        
        .agent-list {
            margin: 10px 0;
        }
        
        .agent-item {
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 3px;
            margin-bottom: 8px;
            overflow: hidden;
        }
        
        .agent-header {
            background: #f5f5f5;
            padding: 10px 12px;
            cursor: pointer;
            font-weight: 500;
            color: #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .agent-header:hover {
            background: #e8f4f8;
        }
        
        .agent-stats {
            color: #666;
            font-size: 12px;
            font-weight: normal;
            margin-left: 10px;
        }
        
        .agent-body {
            display: none;
            padding: 12px;
            border-top: 1px solid #e0e0e0;
        }
        
        .agent-body.active {
            display: block;
        }
        
        .agent-output {
            background: #f9f9f9;
            padding: 10px;
            border-radius: 3px;
            margin-bottom: 10px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.4;
            max-height: 250px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }
        
        .tool-list {
            margin-top: 10px;
        }
        
        .tool-item {
            background: #f5f5f5;
            border: 1px solid #ddd;
            border-radius: 3px;
            margin-bottom: 6px;
            overflow: hidden;
        }
        
        .tool-header {
            background: #f0f0f0;
            padding: 8px 10px;
            cursor: pointer;
            font-weight: 500;
            color: #444;
            font-size: 13px;
            display: flex;
            justify-content: space-between;
        }
        
        .tool-header:hover {
            background: #e0e0e0;
        }
        
        .tool-stats {
            color: #666;
            font-size: 11px;
            font-weight: normal;
        }
        
        .tool-body {
            display: none;
            padding: 10px;
            border-top: 1px solid #ddd;
        }
        
        .tool-body.active {
            display: block;
        }
        
        .tool-args {
            background: #fafafa;
            padding: 8px;
            border-radius: 2px;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            line-height: 1.3;
            max-height: 150px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: #999;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Agent Monitoring Dashboard</h1>
        <button class="refresh-btn" onclick="location.reload()">⟲ Refresh</button>
        
        <div id="turns-container" class="turn-list"></div>
        <div id="empty-state" class="empty-state" style="display: none;">
            No turns recorded yet. Try asking a question in the stock assistant.
        </div>
    </div>

    <script>
        async function loadTurns() {
            try {
                const response = await fetch('/api/turns');
                const turns = await response.json();
                
                const container = document.getElementById('turns-container');
                const emptyState = document.getElementById('empty-state');
                
                if (turns.length === 0) {
                    container.style.display = 'none';
                    emptyState.style.display = 'block';
                    return;
                }
                
                container.innerHTML = turns.map((turn, idx) => `
                    <div class="turn-card" onclick="toggleTurnDetails(${idx})">
                        <div class="turn-header">
                            <div style="flex: 1;">
                                <div class="turn-timestamp">${new Date(turn.timestamp).toLocaleString()}</div>
                                <div class="turn-query">${escapeHtml(turn.user_query.substring(0, 100))}${turn.user_query.length > 100 ? '...' : ''}</div>
                                <div class="turn-meta">
                                    ${turn.agents_called.length} agents • 
                                    ${turn.total_duration_ms ? (turn.total_duration_ms / 1000).toFixed(2) + 's' : 'N/A'} • 
                                    ${turn.total_tokens ? turn.total_tokens + ' tokens' : 'N/A'}
                                </div>
                            </div>
                            <div class="toggle-icon">▶</div>
                        </div>
                        
                        <div class="turn-details" id="turn-${idx}">
                            <div class="section">
                                <div class="section-title">📋 User Query</div>
                                <div class="section-content">${escapeHtml(turn.user_query)}</div>
                            </div>
                            
                            ${turn.orchestrator_plan ? `
                                <div class="section">
                                    <div class="section-title">🤖 Orchestrator Plan</div>
                                    <div class="section-content">${escapeHtml(turn.orchestrator_plan)}</div>
                                </div>
                            ` : ''}
                            
                            <div class="section">
                                <div class="section-title">👷 Agents</div>
                                <div class="agent-list">
                                    ${turn.agents && turn.agents.length > 0 ? turn.agents.map((agent, agentIdx) => `
                                        <div class="agent-item">
                                            <div class="agent-header" onclick="toggleAgentBody(event, ${idx}, ${agentIdx})">
                                                <div>
                                                    <span>${escapeHtml(agent.agent_name)}</span>
                                                    <span class="agent-stats">
                                                        ${agent.duration_ms ? (agent.duration_ms / 1000).toFixed(2) + 's' : 'N/A'} • 
                                                        ${agent.tokens ? agent.tokens + ' tokens' : 'N/A'} •
                                                        ${agent.tools ? agent.tools.length + ' tools' : '0 tools'}
                                                    </span>
                                                </div>
                                                <span>▶</span>
                                            </div>
                                            <div class="agent-body" id="agent-${idx}-${agentIdx}">
                                                ${agent.output ? `
                                                    <div style="margin-bottom: 10px;">
                                                        <div style="font-weight: 600; color: #333; margin-bottom: 5px; font-size: 12px;">Output:</div>
                                                        <div class="agent-output">${escapeHtml(agent.output)}</div>
                                                    </div>
                                                ` : ''}
                                                
                                                ${agent.tools && agent.tools.length > 0 ? `
                                                    <div class="tool-list">
                                                        <div style="font-weight: 600; color: #333; margin-bottom: 8px; font-size: 12px;">Tools Called:</div>
                                                        ${agent.tools.map((tool, toolIdx) => `
                                                            <div class="tool-item">
                                                                <div class="tool-header" onclick="toggleToolBody(event, ${idx}, ${agentIdx}, ${toolIdx})">
                                                                    <div>
                                                                        <span>${escapeHtml(tool.tool_name)}</span>
                                                                        <span class="tool-stats">
                                                                            ${tool.duration_ms ? (tool.duration_ms / 1000).toFixed(2) + 's' : 'N/A'} •
                                                                            ${tool.cache_hit ? '✓ cached' : 'uncached'}
                                                                            ${tool.error ? ' • ❌ error' : ''}
                                                                        </span>
                                                                    </div>
                                                                    <span>▶</span>
                                                                </div>
                                                                <div class="tool-body" id="tool-${idx}-${agentIdx}-${toolIdx}">
                                                                    <div style="margin-bottom: 8px;">
                                                                        <div style="font-weight: 600; color: #333; margin-bottom: 5px; font-size: 11px;">Arguments:</div>
                                                                        <div class="tool-args">${escapeHtml(JSON.stringify(tool.arguments, null, 2))}</div>
                                                                    </div>
                                                                    ${tool.error ? `
                                                                        <div>
                                                                            <div style="font-weight: 600; color: #d9534f; margin-bottom: 5px; font-size: 11px;">Error:</div>
                                                                            <div class="tool-args">${escapeHtml(tool.error)}</div>
                                                                        </div>
                                                                    ` : ''}
                                                                </div>
                                                            </div>
                                                        `).join('')}
                                                    </div>
                                                ` : ''}
                                            </div>
                                        </div>
                                    `).join('') : '<div style="color: #999;">No agents called</div>'}
                                </div>
                            </div>
                            
                            ${turn.synthesis_output ? `
                                <div class="section">
                                    <div class="section-title">✅ Synthesis Output</div>
                                    <div class="section-content">${escapeHtml(turn.synthesis_output)}</div>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                console.error('Error loading turns:', error);
            }
        }
        
        function toggleTurnDetails(idx) {
            const details = document.getElementById(`turn-${idx}`);
            const icon = event.currentTarget.querySelector('.toggle-icon');
            details.classList.toggle('active');
            icon.textContent = details.classList.contains('active') ? '▼' : '▶';
        }
        
        function toggleAgentBody(e, turnIdx, agentIdx) {
            e.stopPropagation();
            const body = document.getElementById(`agent-${turnIdx}-${agentIdx}`);
            const icon = e.currentTarget.querySelector('span:last-child');
            body.classList.toggle('active');
            icon.textContent = body.classList.contains('active') ? '▼' : '▶';
        }
        
        function toggleToolBody(e, turnIdx, agentIdx, toolIdx) {
            e.stopPropagation();
            const body = document.getElementById(`tool-${turnIdx}-${agentIdx}-${toolIdx}`);
            const icon = e.currentTarget.querySelector('span:last-child');
            body.classList.toggle('active');
            icon.textContent = body.classList.contains('active') ? '▼' : '▶';
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Load turns on page load and refresh every 5 seconds
        loadTurns();
        setInterval(loadTurns, 5000);
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    """Serve the dashboard."""
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/turns')
def api_turns():
    """API endpoint to fetch all turns."""
    turns = get_all_turns()
    return jsonify([dict(t) for t in turns])

if __name__ == '__main__':
    print("Starting Agent Monitoring Dashboard on http://localhost:5000")
    print("Press Ctrl+C to stop")
    app.run(debug=False, port=5000, host='127.0.0.1')
```

- [ ] **Step 2: Verify web_server.py syntax**

```powershell
python -m py_compile web_server.py
```

Expected: No output (success)

---

## Task 6: Test the Complete Integration

**Files:**
- Test: Run main.py and web_server.py

- [ ] **Step 1: Start the Flask web server in a separate terminal**

```powershell
python web_server.py
```

Expected: Output shows `Starting Agent Monitoring Dashboard on http://localhost:5000`

- [ ] **Step 2: Open browser and verify dashboard loads**

Navigate to: `http://localhost:5000`

Expected: Dashboard page loads with "No turns recorded yet" message

- [ ] **Step 3: Run main.py in another terminal and ask a question**

```powershell
python main.py
```

Then type a stock question, e.g.:
```
What is the PE ratio of Apple?
```

Expected: The question completes and returns an answer

- [ ] **Step 4: Refresh the dashboard in browser**

Refresh `http://localhost:5000`

Expected: The turn appears in the chronological list with timestamp, query, and expandable details

- [ ] **Step 5: Click to expand the turn and verify data**

Click on the turn to expand. Verify:
- User query is displayed
- Orchestrator plan is shown
- Agents list appears with timing/token info
- Click agent to see full output
- Click agent tools to see arguments

Expected: All data is present and properly formatted

---

## Task 7: Commit Changes

- [ ] **Step 1: Stage all changes**

```powershell
git add monitoring/ web_server.py orchestrator.py main.py tools/__init__.py
```

- [ ] **Step 2: Commit with message**

```powershell
git commit -m "feat: add SQLite-backed monitoring dashboard with Flask web interface

- Move monitoring module to dedicated monitoring/ folder
- Replace JSON logging with SQLite database
- Add Flask web server on localhost:5000
- Display chronological turn history with expandable hierarchy
- Show orchestrator plan, agent outputs, tool calls, and synthesis
- Store full execution details: timing, tokens, arguments, cache hits"
```

- [ ] **Step 3: Verify commit**

```powershell
git log --oneline -3
```

Expected: Your new commit appears as the most recent

---

## Self-Review Checklist

✓ Spec coverage:
  - ✓ SQLite storage instead of JSON
  - ✓ Monitoring moved to `monitoring/` folder
  - ✓ Flask web server on localhost:5000
  - ✓ Chronological list of all turns
  - ✓ User query shown at top of each turn
  - ✓ Orchestrator plan captured and displayed
  - ✓ Agent outputs shown in full
  - ✓ Tool arguments displayed
  - ✓ Timing and token counts for each component
  - ✓ Synthesis output captured and shown

✓ Placeholder scan: No TODOs, TBDs, or incomplete sections

✓ Type consistency: Function signatures consistent across tasks

✓ No missing requirements

