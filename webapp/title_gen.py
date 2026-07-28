"""Generate a short chat title from a user's message. Called from
webapp.app.send_message on a chat's first message only, off the request
thread — a background thread calls generate_title() and saves the result via
webapp.db.update_chat_title.
"""
from tools.config import MODEL_AGENT
from tools.llm import llm_chat

_MAX_TITLE_LEN = 60
_TRUNCATE_LEN = 40

_TITLE_PROMPT = (
    "Summarize the user's message into a short chat title, 3-6 words. "
    "Plain text only: no quotes, no trailing punctuation, no markdown."
)


# Truncate text to fallback length, adding ellipsis if needed.
def _truncate_fallback(user_message: str) -> str:
    text = user_message.strip()
    if len(text) <= _TRUNCATE_LEN:
        return text
    return text[:_TRUNCATE_LEN].rstrip() + "…"


def generate_title(user_message: str) -> tuple[str, int]:
    """Returns (title, tokens_used). On any llm_chat failure, falls back to a
    truncated version of user_message and reports 0 tokens (nothing was
    billed)."""
    # Call the LLM to generate a concise title from the user's message.
    try:
        content, tokens = llm_chat(
            model=MODEL_AGENT,
            messages=[
                {"role": "system", "content": _TITLE_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception:
        return _truncate_fallback(user_message), 0

    # Remove whitespace and quotes; if empty, use fallback text; otherwise limit to maximum length.
    title = content.strip().strip('"').strip("'")
    if not title:
        return _truncate_fallback(user_message), tokens
    return title[:_MAX_TITLE_LEN], tokens
