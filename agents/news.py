import json
import time
import logging

from tools.llm import _get_client
from monitoring import record_tool, update_agent_tokens
from tools.config import MODEL_AGENT
from tools.news import get_stock_news, search_news
from prompts import NEWS_SYSTEM as SYSTEM_PROMPT

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_news",
            "description": "Fetch live news headlines for a ticker from Yahoo Finance and Google News. Use for: latest news, breaking headlines, fresh articles, what happened today/recently.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Hybrid semantic+keyword search over stored news articles. Use for: searching past articles, thematic queries, finding news about a specific topic across stored results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "ticker": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "days_back": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_stock_news": get_stock_news,
    "search_news": search_news,
}

OPT = {"temperature": 0.1}


def run(user_question: str, context: str = "", history: list[dict] | None = None, agent_id: int | None = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages += history[-6:]
    if context:
        messages += [
            {"role": "user", "content": f"Context from prior analysis:\n{context}"},
            {"role": "assistant", "content": "Understood. I have the prior context."},
        ]
    messages.append({"role": "user", "content": user_question})

    client = _get_client()
    total_prompt_tokens = 0
    total_completion_tokens = 0

    def _chat(*args, **kwargs):
        nonlocal total_prompt_tokens, total_completion_tokens
        r = client.chat.completions.create(*args, **kwargs)
        if r.usage:
            total_prompt_tokens += r.usage.prompt_tokens
            total_completion_tokens += r.usage.completion_tokens
        return r

    response = _chat(
        model=MODEL_AGENT,
        messages=messages,
        tools=TOOLS,
        tool_choice="required",
        temperature=OPT["temperature"],
    )
    msg = response.choices[0].message

    while msg.tool_calls:
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
            args = json.loads(tool_call.function.arguments)
            fn = TOOL_FUNCTIONS.get(name)
            _t = time.perf_counter()
            result = fn(**args) if fn else f"Unknown tool: {name}"
            if isinstance(result, str) and len(result) > 3000:
                result = result[:3000] + "\n... [truncated]"
            _dur = round((time.perf_counter() - _t) * 1000)
            _err = result[:120] if isinstance(result, str) and result.startswith("TOOL_ERROR") else None
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
            logging.info("[NewsAgent] %s(%s)", name, args)
            if agent_id is not None:
                record_tool(agent_id=agent_id, tool_name=name, duration_ms=_dur, arguments=args, result=result if not _err else None, error=_err)
        response = _chat(
            model=MODEL_AGENT,
            messages=messages,
            tools=TOOLS,
            temperature=OPT["temperature"],
        )
        msg = response.choices[0].message

    total_tokens = total_prompt_tokens + total_completion_tokens
    logging.info("[NewsAgent] tokens: prompt=%d completion=%d total=%d",
                 total_prompt_tokens, total_completion_tokens, total_tokens)
    if agent_id is not None:
        update_agent_tokens(agent_id, total_tokens)
    return msg.content or ""
