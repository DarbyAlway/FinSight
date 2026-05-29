import logging
import os

from openai import OpenAI

_client: OpenAI | None = None


def get_groq_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set in environment")
        _client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
    return _client


def groq_chat(model: str, messages: list[dict], temperature: float = 0.0) -> str:
    try:
        response = get_groq_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logging.error("Groq API call failed: %s", e)
        raise
