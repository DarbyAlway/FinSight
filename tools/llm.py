import logging
import os
import time

from langfuse.openai import OpenAI

_SAMBANOVA_BASE_URL = "https://api.sambanova.ai/v1"
_OLLAMA_BASE_URL = "http://localhost:11434/v1"
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        base_url = os.getenv("LLM_BASE_URL") or (
            _SAMBANOVA_BASE_URL if os.getenv("SAMBANOVA_API_KEY")
            else _OLLAMA_BASE_URL
        )
        if "sambanova" in base_url:
            api_key = os.getenv("SAMBANOVA_API_KEY")
        elif "localhost" in base_url:
            api_key = "not-needed"
        else:
            api_key = os.getenv("LLM_API_KEY", "not-needed")
        _client = OpenAI(api_key=api_key, base_url=base_url)
        logging.info("LLM client: %s", base_url)
    return _client


def llm_chat(model: str, messages: list[dict], temperature: float = 0.0) -> tuple[str, int]:
    """Returns (content, total_tokens)."""
    start = time.perf_counter()
    try:
        response = _get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = prompt_tokens + completion_tokens
        latency = round(time.perf_counter() - start, 3)
        logging.info("[LLM] model=%s prompt=%d completion=%d total=%d latency=%.2fs",
                     model, prompt_tokens, completion_tokens, total_tokens, latency)
        return content, total_tokens
    except Exception as e:
        logging.error("llm_chat failed: %s", e)
        raise
