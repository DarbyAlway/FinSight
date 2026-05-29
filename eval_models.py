"""
Model benchmark: compares two Ollama models on plan routing and agent tool selection.

Usage:
    python eval_models.py                        # qwen3:14b vs qwen3:8b
    python eval_models.py qwen3:14b llama3.1:8b  # custom pair
"""

import json
import sys
import time

import ollama

from orchestrator import PLAN_SYSTEM, OPT_PLAN, _parse_plan, _keyword_fallback
from agents.financials import SYSTEM_PROMPT as FIN_PROMPT, TOOLS as FIN_TOOLS
from agents.news import SYSTEM_PROMPT as NEWS_PROMPT, TOOLS as NEWS_TOOLS
from agents.calc import SYSTEM_PROMPT as CALC_PROMPT, TOOLS as CALC_TOOLS

MODEL_A = sys.argv[1] if len(sys.argv) > 1 else "qwen3:14b"
MODEL_B = sys.argv[2] if len(sys.argv) > 2 else "qwen3:8b"

# --- Plan routing cases ---
# expected_agents: list of acceptable agent combinations (any match = PASS)
# Use multiple entries when multi-agent routing is also a valid answer
PLAN_CASES = [
    {"q": "What is AAPL's revenue for the last 3 years?",           "expected": [["financials"]]},
    {"q": "Show me the latest news about Tesla today",               "expected": [["news"]]},
    {"q": "Calculate MSFT revenue CAGR",                            "expected": [["calc"], ["financials", "calc"]]},
    {"q": "Hello, how are you?",                                    "expected": [[]]},
    {"q": "Show INTC income statement",                             "expected": [["financials"]]},
    {"q": "What is the correlation between AAPL and MSFT?",         "expected": [["calc"]]},
    {"q": "Any recent articles about NVDA earnings?",               "expected": [["news"]]},
    # DCF needs income data first — financials+calc is equally valid
    {"q": "DCF valuation for GOOGL",                                "expected": [["calc"], ["financials", "calc"]]},
    # company info already includes sector + P/E — financials alone is correct
    {"q": "What sector is JPM in and what is its P/E?",             "expected": [["financials"], ["financials", "calc"]]},
    # margin_trend is a calc tool but needs income data — both routings acceptable
    {"q": "Compare AAPL and MSFT margin trends",                    "expected": [["calc"], ["financials", "calc"]]},
]

# --- Agent tool-selection cases ---
# expected_tool: first tool_call the agent should make
AGENT_CASES = [
    {
        "agent": "financials",
        "q": "Fetch the annual income statement for AAPL",
        "expected_tool": "get_income_statement",
        "prompt": FIN_PROMPT, "tools": FIN_TOOLS,
    },
    {
        "agent": "financials",
        "q": "What were MSFT's Q3 2024 earnings?",
        "expected_tool": "get_quarterly_statement",
        "prompt": FIN_PROMPT, "tools": FIN_TOOLS,
    },
    {
        "agent": "financials",
        "q": "Get company profile and sector for NVDA",
        "expected_tool": "get_company_info",
        "prompt": FIN_PROMPT, "tools": FIN_TOOLS,
    },
    {
        "agent": "news",
        "q": "What is the latest breaking news about TSLA today?",
        "expected_tool": "get_stock_news",
        "prompt": NEWS_PROMPT, "tools": NEWS_TOOLS,
    },
    {
        "agent": "news",
        "q": "Search past articles about Apple supply chain issues",
        "expected_tool": "search_news",
        "prompt": NEWS_PROMPT, "tools": NEWS_TOOLS,
    },
    {
        "agent": "calc",
        "q": "Calculate revenue CAGR for AAPL over 3 years",
        "expected_tool": "calculate_revenue_cagr",
        "prompt": CALC_PROMPT, "tools": CALC_TOOLS,
    },
    {
        "agent": "calc",
        "q": "What is NVDA's PEG ratio?",
        "expected_tool": "calculate_peg",
        "prompt": CALC_PROMPT, "tools": CALC_TOOLS,
    },
    {
        "agent": "calc",
        "q": "Run a DCF valuation for MSFT",
        "expected_tool": "calculate_dcf",
        "prompt": CALC_PROMPT, "tools": CALC_TOOLS,
    },
    {
        "agent": "calc",
        "q": "How does AAPL's P/E compare to its sector peers?",
        "expected_tool": "calculate_pe_vs_sector",
        "prompt": CALC_PROMPT, "tools": CALC_TOOLS,
    },
    {
        "agent": "calc",
        "q": "Show the price correlation between AAPL and MSFT",
        "expected_tool": "calculate_correlation",
        "prompt": CALC_PROMPT, "tools": CALC_TOOLS,
    },
]


def eval_plan(model: str, cases: list[dict]) -> tuple[list[dict], float]:
    results = []
    total_time = 0.0
    for case in cases:
        messages = [
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": case["q"]},
        ]
        t0 = time.time()
        try:
            resp = ollama.chat(model=model, messages=messages, options=OPT_PLAN)
            elapsed = time.time() - t0
            total_time += elapsed
            content = resp.message.content or ""
            try:
                plan = _parse_plan(content)
                got = plan.get("agents", [])
            except (ValueError, Exception):
                got = _keyword_fallback(case["q"])
            correct = sorted(got) in [sorted(e) for e in case["expected"]]
            results.append({
                "q": case["q"], "expected": case["expected"],
                "got": got, "correct": correct, "time": elapsed,
            })
        except Exception as e:
            elapsed = time.time() - t0
            total_time += elapsed
            results.append({
                "q": case["q"], "expected": case["expected"],
                "got": f"ERROR: {e}", "correct": False, "time": elapsed,
            })

    return results, total_time


def eval_tools(model: str, cases: list[dict]) -> tuple[list[dict], float]:
    results = []
    total_time = 0.0
    for case in cases:
        messages = [
            {"role": "system", "content": case["prompt"]},
            {"role": "user", "content": case["q"]},
        ]
        t0 = time.time()
        try:
            resp = ollama.chat(model=model, messages=messages,
                               tools=case["tools"], options={"temperature": 0.1})
            elapsed = time.time() - t0
            total_time += elapsed
            calls = resp.message.tool_calls or []
            got_tool = calls[0].function.name if calls else None
            correct = got_tool == case["expected_tool"]
            results.append({
                "agent": case["agent"], "q": case["q"],
                "expected_tool": case["expected_tool"],
                "got_tool": got_tool, "correct": correct, "time": elapsed,
            })
        except Exception as e:
            elapsed = time.time() - t0
            total_time += elapsed
            results.append({
                "agent": case["agent"], "q": case["q"],
                "expected_tool": case["expected_tool"],
                "got_tool": f"ERROR: {e}", "correct": False, "time": elapsed,
            })
    return results, total_time


def print_plan_results(model: str, results: list[dict], total_time: float):
    correct = sum(1 for r in results if r["correct"])
    print(f"\n{'='*60}")
    print(f"PLAN ROUTING — {model}  ({correct}/{len(results)} correct, {total_time:.1f}s total)")
    print(f"{'='*60}")
    for r in results:
        mark = "PASS" if r["correct"] else "FAIL"
        print(f"  [{mark}] {r['q'][:50]:<50}  {r['time']:.2f}s")
        if not r["correct"]:
            acceptable = " or ".join(str(e) for e in r["expected"])
            print(f"         expected={acceptable}  got={r['got']}")


def print_tool_results(model: str, results: list[dict], total_time: float):
    correct = sum(1 for r in results if r["correct"])
    print(f"\n{'='*60}")
    print(f"TOOL SELECTION — {model}  ({correct}/{len(results)} correct, {total_time:.1f}s total)")
    print(f"{'='*60}")
    for r in results:
        mark = "PASS" if r["correct"] else "FAIL"
        print(f"  [{mark}] [{r['agent']:11}] {r['q'][:44]:<44}  {r['time']:.2f}s")
        if not r["correct"]:
            print(f"         expected={r['expected_tool']}  got={r['got_tool']}")


def print_summary(model: str, plan_results, tool_results):
    p = sum(1 for r in plan_results if r["correct"])
    t = sum(1 for r in tool_results if r["correct"])
    total = len(plan_results) + len(tool_results)
    score = p + t
    avg_time = (
        sum(r["time"] for r in plan_results + tool_results) / total
    )
    print(f"  {model:<20}  score={score}/{total}  avg_latency={avg_time:.2f}s/call")


if __name__ == "__main__":
    from tools.db import init_db
    init_db()

    print(f"Comparing  {MODEL_A}  vs  {MODEL_B}")
    print(f"Plan cases: {len(PLAN_CASES)}  |  Tool cases: {len(AGENT_CASES)}\n")

    print(f"Running {MODEL_A}...")
    plan_a, pt_a = eval_plan(MODEL_A, PLAN_CASES)
    tool_a, tt_a = eval_tools(MODEL_A, AGENT_CASES)

    print(f"Running {MODEL_B}...")
    plan_b, pt_b = eval_plan(MODEL_B, PLAN_CASES)
    tool_b, tt_b = eval_tools(MODEL_B, AGENT_CASES)

    print_plan_results(MODEL_A, plan_a, pt_a)
    print_tool_results(MODEL_A, tool_a, tt_a)

    print_plan_results(MODEL_B, plan_b, pt_b)
    print_tool_results(MODEL_B, tool_b, tt_b)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print_summary(MODEL_A, plan_a, tool_a)
    print_summary(MODEL_B, plan_b, tool_b)

    out = {
        MODEL_A: {"plan": plan_a, "tools": tool_a},
        MODEL_B: {"plan": plan_b, "tools": tool_b},
    }
    with open("eval_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nFull results saved to eval_results.json")
