import logging
import os

from openai import OpenAI

_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_API_KEY not set in environment")
        base_url = os.getenv("LLM_BASE_URL", _DEFAULT_BASE_URL)
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def llm_chat(model: str, messages: list[dict], temperature: float = 0.0) -> str:
    try:
        response = _get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logging.error("llm_chat failed: %s", e)
        raise
