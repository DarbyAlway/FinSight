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

def update_agent_output(agent_id: int, output: str):
    """Update an agent record with its final output."""
    with _lock:
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE agents SET output = ? WHERE id = ?",
                (output, agent_id)
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
