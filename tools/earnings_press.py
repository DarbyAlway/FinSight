import logging
import re
import time

import yfinance as yf
from edgar import Company

from tools.db import is_earnings_fresh, save_earnings, load_earnings


_GUIDANCE_KEYWORDS = ["expect", "guidance", "outlook", "forecast", "anticipate", "project"]


def _parse_beat_miss(actual: float, estimate: float) -> str:
    if not estimate or estimate == 0:
        return "in-line"
    pct = (actual - estimate) / abs(estimate) * 100
    if pct > 2:
        return "beat"
    if pct < -2:
        return "miss"
    return "in-line"


def _extract_guidance_text(text: str) -> str | None:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    found = []
    for sentence in sentences:
        if any(kw in sentence.lower() for kw in _GUIDANCE_KEYWORDS):
            found.append(sentence.strip())
            if len(found) >= 2:
                break
    return " ".join(found) if found else None
