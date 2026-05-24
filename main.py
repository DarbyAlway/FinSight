import logging
import os

from dotenv import load_dotenv
load_dotenv()

from edgar import set_identity

from tools.config import MODEL
from tools.db import init_db
from tools.vector import init_qdrant
from tools.search_guardrails import _get_anchor_vecs, web_search_fallback, is_uncertain
from orchestrator import process_turn
from prompts import SYNTHESIS_SYSTEM, PERSONAS, PANEL_PROMPT

# Re-exports for tests/test_tools.py compatibility
from tools.db import (
    is_cache_fresh, save_to_cache, load_from_cache, fuzzy_query,
    save_ticker_info, load_ticker_info, is_ticker_info_fresh, get_summary_hash,
    is_quarterly_cache_fresh, save_quarterly_cache, load_quarterly_cache,
)
from tools.income import parse_income_statement, get_income_statement, get_quarterly_statement
from tools.vector import (
    init_qdrant,  # noqa: F811 — re-export for test_tools.py
    store_articles, hybrid_search, upsert_company_profile, search_company_profiles,
)
from tools.news import get_stock_news, search_news
from tools.company import get_company_info
from tools.config import DB_PATH, QDRANT_COLLECTION, COMPANY_PROFILES_COLLECTION

set_identity("yourname@email.com")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)



def _build_persona_system(persona_key: str | None) -> str | None:
    if persona_key == "panel":
        return SYNTHESIS_SYSTEM + " " + PANEL_PROMPT
    if persona_key and persona_key in PERSONAS:
        return SYNTHESIS_SYSTEM + " " + PERSONAS[persona_key][1]
    return None


def chat():
    persona: str | None = None
    messages: list[dict] = []
    names = ", ".join(PERSONAS.keys())
    print(f"Stock Assistant ({MODEL}) — type 'exit' to quit")
    print(f"Personas: /persona <{names}|panel|off>\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        if user_input.startswith("/persona"):
            parts = user_input.split()
            key = parts[1].lower() if len(parts) > 1 else "off"
            if key == "off":
                persona = None
                print("[Persona off — back to default]\n")
            elif key in ("panel", *PERSONAS):
                persona = key
                label = "investor panel" if key == "panel" else PERSONAS[key][0]
                print(f"[Persona: {label}]\n")
            else:
                print(f"[Unknown persona '{key}'. Available: {names}, panel, off]\n")
            continue

        answer, messages = process_turn(user_input, messages, _build_persona_system(persona))
        print(f"\nAssistant: {answer}\n")


if __name__ == "__main__":
    init_db()
    init_qdrant()
    _get_anchor_vecs()
    chat()
