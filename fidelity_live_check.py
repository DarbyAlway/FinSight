"""One-shot live fidelity check: run ONE real query through process_turn and
show the answer plus the [fidelity] verifier log line. Uses whatever LLM the
env selects (SambaNova when SAMBANOVA_API_KEY is set).

Run:  python fidelity_live_check.py "What was Apple's revenue in FY2024 and FY2023?"
"""
import io
import logging
import sys

# Windows console is cp874/cp1252; model output contains unicode (→, —, ✓).
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()
from edgar import set_identity
set_identity("yourname@email.com")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

from orchestrator import process_turn

query = sys.argv[1] if len(sys.argv) > 1 else "What was Apple's revenue in FY2024 and FY2023?"
print("=" * 72)
print("QUERY:", query)
print("=" * 72)
answer, _ = process_turn(query, [])
print("\n" + "=" * 72)
print("ANSWER:")
print(answer)
print("=" * 72)
