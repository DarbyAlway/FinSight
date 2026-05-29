import logging
import os
import time

from openai import OpenAI

_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
_client: OpenAI | None = None
_langfuse = None
_langfuse_checked: bool = False


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_API_KEY not set in environment")
        base_url = os.getenv("LLM_BASE_URL", _DEFAULT_BASE_URL)
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def _get_langfuse():
    global _langfuse, _langfuse_checked
    if _langfuse_checked:
        return _langfuse
    _langfuse_checked = True
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if public_key and secret_key:
        try:
            from langfuse import Langfuse
            host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
            _langfuse = Langfuse(host=host, public_key=public_key, secret_key=secret_key)
            logging.info("LangFuse dashboard enabled (%s)", host)
        except Exception as e:
            logging.warning("LangFuse init failed — dashboard disabled: %s", e)
    return _langfuse


def llm_chat(model: str, messages: list[dict], temperature: float = 0.0) -> str:
    start = time.perf_counter()
    try:
        response = _get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content or ""
        latency = round(time.perf_counter() - start, 3)
        lf = _get_langfuse()
        if lf:
            try:
                gen = lf.generation(
                    name="llm_chat",
                    model=model,
                    input=messages,
                    output=content,
                    metadata={"temperature": temperature, "latency_s": latency},
                )
                gen.end()
            except Exception as e:
                logging.warning("LangFuse logging failed: %s", e)
        return content
    except Exception as e:
        logging.error("llm_chat failed: %s", e)
        raise
