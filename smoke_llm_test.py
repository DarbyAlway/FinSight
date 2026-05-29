import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from main import init_db
from orchestrator import process_turn

init_db()

question = "Which products does SNOW have and how much profit does each make?"
print(f"Question: {question}")
print("=" * 60)

answer, history = process_turn(question, [])

print("--- ANSWER ---")
print(answer)
print("--- END ---")
