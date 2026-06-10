# Number-Fidelity Verifier (#14) + Tool-Output Plumbing (#13 Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plumb each agent's raw tool outputs up to the orchestrator, then deterministically flag (never mutate) any unit-bearing number in the final answer that cannot be traced — year-aware — to those tool outputs.

**Architecture:** Two phases. **Phase 1** surfaces the raw tool results that `run_tool_loop` already captures in its `seen` dict and currently discards, threading them through each agent `run()` and into the orchestrator. **Phase 2** adds a pure, unit-tested `tools/fidelity.py` that extracts unit-bearing numbers from the answer, builds a year-scoped grounding index from the tool outputs, and logs mismatches + a best-effort Langfuse score. Flag-only: the answer is never changed. This measures the real retype-drift rate before any decision on the bigger #13 structured-handoff refactor (Phase 3, **out of scope here** — gated on Phase-2 evidence, see the spec).

**Tech Stack:** Python 3, pytest, langfuse (v3 client, best-effort scoring), existing `agents/_tooling.py` tool loop, `tools/schemas.py` Pydantic patterns.

**Source spec:** `claude/specs/2026-06-09-structured-handoff-fidelity-design.md`

**Env / test runner:** `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest` (pytest.ini `testpaths=tests`). Tests need no permission. Use REAL tool-output formats (below), not fabricated strings.

---

## Real tool-output formats (ground truth — derive regexes from these, do not invent)

From `tools/db.py`:
- **Income statement** (`load_income`, line 162): `    Revenue: 391,035M  (Sep 28, 2024)` — **no `$`**, magnitude suffix `M`, fiscal year is a **date** `(Sep 28, 2024)`.
- **Cash flow / balance sheet** (lines 281/329/385): `      Net income: $93,736M` — **with `$`**, suffix `M`, year header elsewhere as a date `Sep 28, 2024`.
- **Earnings** (lines 439–443): `Revenue: $391,035M actual`, EPS `$1.64`, estimates `$1.60`.
- Margins/ratios in agent prose: `45.2%`, `1.85x`, `0.733`.
- Stock price: `$182.50` (plain dollars, no magnitude suffix).

So a money figure = optional `$`, grouped digits, optional `.dd`, **required** magnitude suffix `T|B|M|K`. A plain `$` number with no suffix = dollars (price/EPS). A 4-digit `19xx`/`20xx` is a year, never a money value.

---

## File Structure

- **Modify** `agents/_tooling.py` — `run_tool_loop` returns a 3-tuple `(summary, total, tool_blocks)`; build `tool_blocks` from `seen`.
- **Modify** `agents/financials.py`, `agents/news.py`, `agents/calc.py`, `agents/ratios.py` — propagate the 3rd value; update return annotation to `tuple[str, int, dict]`.
- **Modify** `tests/test_tool_loop.py` — unpack the new 3-tuple.
- **Modify** `orchestrator.py` — `_run_agent` returns tool_blocks; collect into `agent_tool_blocks`; after the final answer, run the flag-only verifier.
- **Create** `tools/fidelity.py` — pure extraction + year-aware verification.
- **Create** `tests/test_fidelity.py` — unit tests over real formats and the year-mislabel case.
- **Modify** `tests/test_orchestrator.py` — assert tool_blocks reach the verifier and a planted wrong number is logged while the answer is unchanged.

---

## Phase 1 — Plumb raw tool outputs up

### Task 1: `run_tool_loop` returns `tool_blocks`

**Files:**
- Modify: `agents/_tooling.py:45-185`
- Test: `tests/test_tool_loop.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tool_loop.py`:

```python
def test_tool_loop_returns_tool_blocks():
    # One tool call, one round, then a final text answer (no more tool_calls).
    client = _make_client([
        _tool_msg("get_x", {"ticker": "AAPL"}),   # round 1: call the tool
        _text_msg("Revenue is 391,035M"),          # round 2: final answer
    ])
    out, tokens, tool_blocks = run_tool_loop(
        "T", client, "m", [], [_dummy_tool("get_x")],
        {"get_x": lambda ticker: f"{ticker} Revenue: 391,035M"},
        temperature=0.0,
    )
    assert out == "Revenue is 391,035M"
    assert isinstance(tool_blocks, dict)
    # keyed by "name(args_json)" -> raw result
    assert any("get_x" in k for k in tool_blocks)
    assert any("391,035M" in v for v in tool_blocks.values())
```

> If `_make_client`/`_tool_msg`/`_text_msg`/`_dummy_tool` helpers don't already exist in this file, reuse the existing fake-client construction already used by the other tests in `tests/test_tool_loop.py` (read the top of that file and mirror its pattern — do not invent a new mock style).

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_tool_loop.py::test_tool_loop_returns_tool_blocks -v`
Expected: FAIL — `ValueError: not enough values to unpack (expected 3, got 2)`.

- [ ] **Step 3: Implement — build and return `tool_blocks`**

In `agents/_tooling.py`, change the signature return annotation (line 56) from `-> tuple[str, int]:` to `-> tuple[str, int, dict]:`.

Update the docstring return line (currently line 68) to:
```python
    Returns ``(answer_text, total_tokens, tool_blocks)`` where ``tool_blocks`` is a
    ``dict[str, str]`` mapping ``"name(args_json)"`` to each tool's raw result
    (already capped at 3000 chars by ``execute_tool``). Duplicate-cache and the
    final tool-free answer never add new tool results, so ``seen`` is the complete set.
```

At the **end** of the function, just before `return summary, total` (currently line 185), build the blocks from the already-existing `seen` dict and return all three:
```python
    tool_blocks = {
        f"{name}({args_json})": result
        for (name, args_json), result in seen.items()
        if isinstance(result, str)
    }
    total = usage["prompt"] + usage["completion"]
    logging.info("[%s] tokens: prompt=%d completion=%d total=%d",
                 agent_tag, usage["prompt"], usage["completion"], total)
    return summary, total, tool_blocks
```
(Delete the old `total = ...`/`logging`/`return summary, total` trio it replaces.)

- [ ] **Step 4: Update the other tests in this file to unpack 3 values**

In `tests/test_tool_loop.py`, change every existing call site:
- `out, tokens = run_tool_loop(...)` → `out, tokens, _ = run_tool_loop(...)`
- `out, _ = run_tool_loop(...)` → `out, _, _ = run_tool_loop(...)`

(The `with pytest.raises(...): run_tool_loop(...)` call that does not unpack stays as-is.)

- [ ] **Step 5: Run the full file to verify all pass**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_tool_loop.py -v`
Expected: PASS (all, including the new test).

- [ ] **Step 6: Commit**

```bash
git add agents/_tooling.py tests/test_tool_loop.py
git commit -m "feat(#13): run_tool_loop surfaces raw tool_blocks (phase 1)"
```

### Task 2: Agents propagate `tool_blocks`

**Files:**
- Modify: `agents/financials.py:104-119`, `agents/news.py:52-`, `agents/calc.py:82-`, `agents/ratios.py:159-`

- [ ] **Step 1: Update each agent's return annotation and pass-through**

Each agent's `run()` currently ends with `return run_tool_loop(...)` and is annotated `-> tuple[str, int]:`. `run_tool_loop` now returns a 3-tuple, so the pass-through already forwards it — only the **annotation** must change. For all four files (`financials.py`, `news.py`, `calc.py`, `ratios.py`), change:
```python
def run(user_question: str, context: str = "", history: list[dict] | None = None, expected_tickers: list[str] | None = None) -> tuple[str, int]:
```
to:
```python
def run(user_question: str, context: str = "", history: list[dict] | None = None, expected_tickers: list[str] | None = None) -> tuple[str, int, dict]:
```
Leave the `return run_tool_loop(...)` body unchanged (it now forwards 3 values).

- [ ] **Step 2: Verify nothing else unpacks the agent return as a 2-tuple yet**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest -q`
Expected: orchestrator-related tests may FAIL here (they still unpack `result, agent_tokens = fn(...)`). That is expected and fixed in Task 3. Confirm the failures are only the `result, agent_tokens` unpack in `orchestrator.py`/`tests/test_orchestrator.py`, nothing else.

- [ ] **Step 3: Commit**

```bash
git add agents/financials.py agents/news.py agents/calc.py agents/ratios.py
git commit -m "feat(#13): agents propagate tool_blocks 3-tuple (phase 1)"
```

### Task 3: Orchestrator collects `agent_tool_blocks`

**Files:**
- Modify: `orchestrator.py:172-205`

- [ ] **Step 1: Update `_run_agent` to return tool_blocks**

In `orchestrator.py`, the `None`-path return (line 178) and exception-path return (line 188) currently return `agent_name, None, 0`. Add a 4th element so the shape is uniform. Change both to:
```python
                return agent_name, None, 0, None
```
And the success path (line 182-184) from:
```python
                result, agent_tokens = fn(agent_input, "", history=messages, expected_tickers=tickers if tickers else None)
                logging.info("[Orchestrator] ✓ agent %s done (%.2fs)", agent_name, time.time() - t1)
                return agent_name, result, agent_tokens
```
to:
```python
                result, agent_tokens, tool_blocks = fn(agent_input, "", history=messages, expected_tickers=tickers if tickers else None)
                logging.info("[Orchestrator] ✓ agent %s done (%.2fs)", agent_name, time.time() - t1)
                return agent_name, result, agent_tokens, tool_blocks
```

- [ ] **Step 2: Collect tool_blocks in the fan-out loop**

Change the collection loop (lines 192-200) from:
```python
    agent_tokens_total = 0
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_run_agent, name): name for name in agents_to_run}
        agent_results = {}
        for future in as_completed(futures):
            name, result, agent_tokens = future.result()
            agent_tokens_total += agent_tokens
            if result is not None:
                agent_results[name] = result
```
to:
```python
    agent_tokens_total = 0
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_run_agent, name): name for name in agents_to_run}
        agent_results = {}
        agent_tool_blocks: dict[str, dict] = {}
        for future in as_completed(futures):
            name, result, agent_tokens, tool_blocks = future.result()
            agent_tokens_total += agent_tokens
            if result is not None:
                agent_results[name] = result
            if tool_blocks:
                agent_tool_blocks[name] = tool_blocks
```

- [ ] **Step 3: Run orchestrator tests — expect them green again (no verifier yet)**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py -q`
Expected: PASS (the 3-tuple unpack is fixed; behavior otherwise unchanged).

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "feat(#13): orchestrator collects agent_tool_blocks (phase 1)"
```

---

## Phase 2 — `#14` year-aware fidelity verifier (flag-only)

### Task 4: `extract_numbers` — unit-bearing number extraction

**Files:**
- Create: `tools/fidelity.py`
- Test: `tests/test_fidelity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fidelity.py`:
```python
from tools.fidelity import extract_numbers


def _kinds(text):
    return [(n.value, n.kind) for n in extract_numbers(text)]


def test_money_with_suffix_no_dollar():
    # income-statement format: "391,035M" (no $)
    assert (391035.0, "money_millions") in _kinds("Revenue: 391,035M  (Sep 28, 2024)")


def test_money_with_dollar_and_suffix():
    assert (93736.0, "money_millions") in _kinds("Net income: $93,736M")


def test_billions_normalized_to_millions():
    assert (1230.0, "money_millions") in _kinds("Cash of $1.23B on hand")


def test_trillions_normalized_to_millions():
    assert (3000000.0, "money_millions") in _kinds("Market cap $3T")


def test_plain_dollars_is_dollars_not_millions():
    assert (182.50, "dollars") in _kinds("Trading at $182.50")
    assert all(k != "money_millions" for _, k in _kinds("Trading at $182.50"))


def test_percent():
    assert (45.2, "percent") in _kinds("Gross margin 45.2%")


def test_ratio():
    assert (1.85, "ratio") in _kinds("Current ratio 1.85x")


def test_years_and_counts_are_ignored():
    # 4-digit years and bare counts must NOT be extracted as numbers
    nums = extract_numbers("In FY2024 across 3 segments and 2025 guidance")
    assert nums == []


def test_dollar_and_suffix_not_double_counted():
    # "$1.23B" must yield exactly one money figure, not also a $1.23 dollars hit
    nums = extract_numbers("$1.23B")
    assert len(nums) == 1
    assert nums[0].kind == "money_millions"
```

- [ ] **Step 2: Run to verify it fails**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_fidelity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.fidelity'`.

- [ ] **Step 3: Implement `extract_numbers`**

Create `tools/fidelity.py`:
```python
"""#14 — year-aware number-fidelity verifier.

Deterministically check that every unit-bearing number in the final answer can be
traced, FOR ITS FISCAL YEAR, to a number the tools actually returned. Flag-only:
callers log mismatches; the answer is never mutated. See
claude/specs/2026-06-09-structured-handoff-fidelity-design.md.
"""
import re
from collections import defaultdict
from dataclasses import dataclass

# magnitude suffix -> multiplier to normalize money into MILLIONS of USD
_MAG = {"T": 1_000_000.0, "B": 1_000.0, "M": 1.0, "K": 0.001}

# money: optional '$', grouped digits with optional decimals, REQUIRED magnitude
# suffix. Matches "391,035M", "$93,736M", "$1.23B", "$3T".
_MONEY_RE = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([TBMK])\b")
# plain dollars (price/EPS): '$' + number, NO magnitude suffix. "$182.50", "$1.64"
_DOLLARS_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)(?![0-9TBMK%])")
_PCT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
_RATIO_RE = re.compile(r"(?<![A-Za-z0-9.])([0-9]+(?:\.[0-9]+)?)\s*x\b")
# a 4-digit fiscal year, optionally prefixed FY. Used only to EXCLUDE years from
# the number set and (later) to associate a number with its year.
_YEAR_RE = re.compile(r"(?:FY[\s-]?)?((?:19|20)\d{2})\b")


@dataclass(frozen=True)
class Number:
    raw: str
    value: float
    kind: str  # "money_millions" | "dollars" | "percent" | "ratio"


def _to_float(digits: str) -> float:
    return float(digits.replace(",", ""))


def extract_numbers(text: str) -> list[Number]:
    """Extract only UNIT-BEARING numbers. Bare integers, counts, and 4-digit
    years are deliberately ignored (primary false-positive defense)."""
    if not text:
        return []
    consumed: list[tuple[int, int]] = []  # spans already claimed, highest priority first

    def _claim(m) -> bool:
        s, e = m.span()
        for cs, ce in consumed:
            if s < ce and cs < e:  # overlaps an already-claimed span
                return False
        consumed.append((s, e))
        return True

    out: list[Number] = []
    # priority: money (suffix) > dollars > percent > ratio
    for m in _MONEY_RE.finditer(text):
        if _claim(m):
            out.append(Number(m.group(0).strip(), _to_float(m.group(1)) * _MAG[m.group(2)], "money_millions"))
    for m in _DOLLARS_RE.finditer(text):
        if _claim(m):
            out.append(Number(m.group(0).strip(), _to_float(m.group(1)), "dollars"))
    for m in _PCT_RE.finditer(text):
        if _claim(m):
            out.append(Number(m.group(0).strip(), _to_float(m.group(1)), "percent"))
    for m in _RATIO_RE.finditer(text):
        if _claim(m):
            out.append(Number(m.group(0).strip(), _to_float(m.group(1)), "ratio"))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_fidelity.py -v`
Expected: PASS.

> Note for the implementer: `test_years_and_counts_are_ignored` is the critical defense. `2025` and `3` carry no `$`/`%`/`x`, so no regex claims them. If a future regex change makes a year match, that test must stay green.

- [ ] **Step 5: Commit**

```bash
git add tools/fidelity.py tests/test_fidelity.py
git commit -m "feat(#14): extract_numbers — unit-bearing number extraction"
```

### Task 5: `extract_year_bound_numbers` — associate numbers with fiscal years

**Files:**
- Modify: `tools/fidelity.py`
- Test: `tests/test_fidelity.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fidelity.py`:
```python
from tools.fidelity import extract_year_bound_numbers


def test_year_from_date_on_line():
    # income format: number and its (Sep 28, 2024) date on the same line
    pairs = extract_year_bound_numbers("Revenue: 391,035M  (Sep 28, 2024)")
    assert (2024, 391035.0, "money_millions") in [(y, n.value, n.kind) for y, n in pairs]


def test_year_from_fy_token():
    pairs = extract_year_bound_numbers("FY2025 revenue was $383,058M")
    assert (2025, 383058.0, "money_millions") in [(y, n.value, n.kind) for y, n in pairs]


def test_number_without_year_has_none():
    pairs = extract_year_bound_numbers("Gross margin is 45.2%")
    assert (None, 45.2, "percent") in [(y, n.value, n.kind) for y, n in pairs]
```

- [ ] **Step 2: Run to verify it fails**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_fidelity.py -k year -v`
Expected: FAIL — `ImportError: cannot import name 'extract_year_bound_numbers'`.

- [ ] **Step 3: Implement**

Append to `tools/fidelity.py`:
```python
def extract_year_bound_numbers(text: str) -> list[tuple[int | None, Number]]:
    """Pair each unit-bearing number with the fiscal year on its own line, if any.
    A line like 'Revenue: 391,035M  (Sep 28, 2024)' -> (2024, <391035 money>).
    When no year token is on the line, the year is None (any-year matching)."""
    out: list[tuple[int | None, Number]] = []
    for line in text.splitlines():
        years = _YEAR_RE.findall(line)
        year = int(years[-1]) if years else None  # date "Sep 28, 2024" -> 2024
        for num in extract_numbers(line):
            out.append((year, num))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_fidelity.py -k year -v`
Expected: PASS.

> Edge note: `_YEAR_RE` could in principle match a 4-digit run inside a value like `$2,025M`. That is acceptable noise for line-level association — verification is tolerance-based and any-year fallback still applies; do not add special-casing unless a real-data test fails.

- [ ] **Step 5: Commit**

```bash
git add tools/fidelity.py tests/test_fidelity.py
git commit -m "feat(#14): extract_year_bound_numbers — year association"
```

### Task 6: `build_grounding` + `verify` — the year-aware check

**Files:**
- Modify: `tools/fidelity.py`
- Test: `tests/test_fidelity.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fidelity.py`:
```python
from tools.fidelity import verify

# Real grounding: AAPL income, FY2024 = 391,035M, FY2023 = 383,285M
_TOOL_BLOCKS = {
    "get_income_statement({\"ticker\": \"AAPL\"})": (
        "AAPL Income Statement (cached)\n"
        "  Revenue\n"
        "    Total revenue: 391,035M  (Sep 28, 2024)\n"
        "    Total revenue: 383,285M  (Sep 30, 2023)\n"
        "    Net income: 93,736M  (Sep 28, 2024)\n"
    ),
}


def test_exact_match_no_mismatch():
    assert verify("FY2024 revenue was 391,035M", _TOOL_BLOCKS) == []


def test_reformatted_unit_matches():
    # $391,035M and the grounding 391,035M are the same value+kind
    assert verify("Revenue was $391,035M in FY2024", _TOOL_BLOCKS) == []


def test_rounded_within_tolerance_matches():
    # 391,000M is within 1% of 391,035M
    assert verify("Roughly $391,000M in FY2024", _TOOL_BLOCKS) == []


def test_genuinely_wrong_number_flagged():
    ms = verify("FY2024 revenue was 500,000M", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].number.value == 500000.0


def test_year_mislabel_flagged():
    # THE CASE: $383,058M labeled FY2025 is ~0.06% from FY2023's 383,285M.
    # A value-only check would pass it; year-scoping MUST flag it (no FY2025 data).
    ms = verify("FY2025 revenue was $383,058M", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].number.year == 2025 or ms[0].year == 2025


def test_empty_grounding_flags_all_numbers():
    # no-agent / no-data path: every unit-bearing number is untraceable
    ms = verify("Revenue was 391,035M and margin 45%", {})
    assert len(ms) == 2
```

> If the `Mismatch` shape below uses `m.year`/`m.number` differently than this test asserts, align the test to the implemented dataclass in Step 3 (keep one consistent shape). The implementation in Step 3 is the source of truth.

- [ ] **Step 2: Run to verify it fails**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_fidelity.py -k "match or flagged or grounding" -v`
Expected: FAIL — `ImportError: cannot import name 'verify'`.

- [ ] **Step 3: Implement `build_grounding` + `verify`**

Append to `tools/fidelity.py`:
```python
@dataclass(frozen=True)
class Mismatch:
    number: Number
    year: int | None


def build_grounding(tool_blocks: dict[str, str]):
    """Index the tools' raw outputs into year-scoped and any-year value sets,
    keyed by number kind. Returns (by_year, any_year)."""
    by_year: dict[tuple[int, str], set[float]] = defaultdict(set)
    any_year: dict[str, set[float]] = defaultdict(set)
    for block in (tool_blocks or {}).values():
        if not isinstance(block, str):
            continue
        for year, num in extract_year_bound_numbers(block):
            any_year[num.kind].add(num.value)
            if year is not None:
                by_year[(year, num.kind)].add(num.value)
    return by_year, any_year


def _close(value: float, candidates, rel_tol: float) -> bool:
    for c in candidates:
        denom = max(abs(value), abs(c), 1e-9)
        if abs(value - c) <= rel_tol * denom:
            return True
    return False


def verify(answer: str, tool_blocks: dict[str, str], rel_tol: float = 0.01) -> list[Mismatch]:
    """Flag every unit-bearing number in `answer` that cannot be traced to the
    tool outputs. Year-aware: a number carrying a fiscal year must match a value
    grounded FOR THAT YEAR; a number with no year falls back to any-year matching.
    Pure + flag-only — never mutates `answer`."""
    by_year, any_year = build_grounding(tool_blocks)
    mismatches: list[Mismatch] = []
    for year, num in extract_year_bound_numbers(answer):
        if year is not None:
            candidates = by_year.get((year, num.kind), set())
        else:
            candidates = any_year.get(num.kind, set())
        if not _close(num.value, candidates, rel_tol):
            mismatches.append(Mismatch(number=num, year=year))
    return mismatches
```

> `Number` has no `year` field, so the test's `ms[0].number.year` alternative is not valid — the year lives on `Mismatch.year`. Keep the test assertion as `ms[0].year == 2025`. (Adjust the `test_year_mislabel_flagged` assertion to `assert ms[0].year == 2025`.)

- [ ] **Step 4: Run the whole fidelity suite**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_fidelity.py -v`
Expected: PASS (all, including `test_year_mislabel_flagged` and `test_empty_grounding_flags_all_numbers`).

- [ ] **Step 5: Commit**

```bash
git add tools/fidelity.py tests/test_fidelity.py
git commit -m "feat(#14): year-aware verify + build_grounding"
```

### Task 7: Wire the verifier into the orchestrator (flag-only)

**Files:**
- Modify: `orchestrator.py` (after the final answer is settled, ~line 253)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py` (mirror the existing patching style in that file — patch `orchestrator.llm_chat`, `run_financials`, etc. as the neighboring tests do):
```python
def test_fidelity_logs_untraced_number_and_does_not_mutate_answer(caplog):
    import logging, orchestrator
    # Agent returns real tool data for FY2024 = 391,035M; synthesis prints a WRONG
    # number (500,000M). Verifier must log it; answer must be returned unchanged.
    answer = run_a_turn_returning(  # helper pattern from existing tests in this file
        orchestrator,
        agent_name="financials",
        agent_result="AAPL Total revenue: 391,035M  (Sep 28, 2024)",
        agent_tool_blocks={"get_income_statement({})": "Total revenue: 391,035M  (Sep 28, 2024)"},
        synthesis_text="FY2024 revenue was 500,000M.",
        caplog=caplog,
    )
    assert "500,000M" in answer  # answer unchanged
    assert any("fidelity" in r.message.lower() for r in caplog.records)
```

> The exact harness call depends on the existing test scaffolding in `tests/test_orchestrator.py`. Read the I5 tests already there (`test_market_news_intent_triggers_proactive_web_search`, `test_reactive_fallback_when_all_agents_return_no_data`) and follow their patch/side_effect pattern exactly. The behavioral assertions that matter: (1) the answer string is returned byte-for-byte unchanged, (2) a `WARNING`-level record containing `fidelity` is emitted. If the neighboring tests don't expose `agent_tool_blocks`, patch `orchestrator._run_agent`'s return to include a tool_blocks dict, OR patch the agent `run` to return the 3-tuple `(result, tokens, tool_blocks)`.

- [ ] **Step 2: Run to verify it fails**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py -k fidelity -v`
Expected: FAIL — no `fidelity` log record emitted.

- [ ] **Step 3: Implement the wiring**

In `orchestrator.py`, add the import near the other tool imports at the top of the file:
```python
from tools.fidelity import verify as verify_fidelity
```

Insert the flag-only check **after** the web-fallback block and **before** `total_tokens = ...` (currently line 255). It must see the final `answer` (post web-fallback):
```python
    # Phase 2 (#14): flag-only number-fidelity check. NEVER mutates `answer`.
    # Skip market_news: those figures legitimately come from live web search, not
    # the local tool outputs, so they are not expected in the grounding.
    if intent != "market_news" and agents_to_run:
        merged_blocks: dict[str, str] = {}
        for blocks in agent_tool_blocks.values():
            merged_blocks.update(blocks)
        mismatches = verify_fidelity(answer, merged_blocks)
        for m in mismatches:
            logging.warning(
                "[fidelity] untraced number %r (kind=%s, year=%s) not found in tool outputs",
                m.number.raw, m.number.kind, m.year,
            )
        logging.info("[fidelity] checked answer: %d untraced unit-bearing number(s)", len(mismatches))
        _score_fidelity(len(mismatches))
```

Add a best-effort Langfuse scorer helper near the top-level helpers in `orchestrator.py` (so a scoring API change can never break a turn):
```python
def _score_fidelity(n_mismatches: int) -> None:
    """Best-effort Langfuse trace score; never raises into the request path."""
    try:
        from langfuse import get_client
        get_client().score_current_trace(name="fidelity_mismatches", value=n_mismatches)
    except Exception as e:  # scoring is observability only
        logging.debug("[fidelity] score skipped: %s", e)
```

> Design note (deviation from spec, intentional): the spec line 69 suggested the empty-grounding no-agent path doubles as a routing-hallucination detector. We gate on `agents_to_run` instead, because the genuine no-agent case (planner said "conversational") is **indistinguishable from real chit-chat** ("hello") and would false-flag. When agents WERE dispatched but returned nothing, `merged_blocks` is empty and every number is still flagged — that no-data case is covered. The pure no-agent routing bug stays in the separate routing workstream. Record this in the active-plans memory.

- [ ] **Step 4: Run to verify pass**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest tests/test_orchestrator.py -k fidelity -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" -m pytest -q`
Expected: PASS (all prior tests + the new fidelity/tool_blocks tests).

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat(#14): wire flag-only fidelity verifier into orchestrator"
```

---

## Phase 3 — `#13` structured hand-off (OUT OF SCOPE — gated)

**Do not build in this plan.** Per the spec's build order and the user's decision, Phase 3 (tools return code-filled `StatementRow` structured data + number-free agent summary + synthesis quoting the structured block) is built **only if** the Phase-2 Langfuse `fidelity_mismatches` score shows meaningful retype-drift. After Phase 2 has run against real queries, review the drift rate and write a separate plan for Phase 3 if justified. Reference: `claude/specs/2026-06-09-structured-handoff-fidelity-design.md` §"Phase 3".

---

## Manual verification (after Task 7, before declaring done)

Run one real Ollama-backed turn (NOT paid SambaNova) that triggers an agent, and confirm the `[fidelity]` log line appears with a mismatch count. Per testing rules: use a real ticker (e.g. AAPL) so the agent fetches real SEC data.

```bash
& "C:\Users\Yatta\miniconda3\envs\stock\python.exe" inspect_agent_io.py   # or the project's normal Ollama entry point
```
Expected: a `[fidelity] checked answer: N untraced ...` INFO line; `N` should be 0 for a faithful answer. Capture the line as evidence.

---

## Self-review checklist (run before handoff)
- Spec coverage: Phase 1 plumb (Tasks 1–3) ✓; #14 verifier `extract_numbers`/`extract_year_bound_numbers`/`build_grounding`/`verify` (Tasks 4–6) ✓; year-mislabel test ✓; empty-grounding test ✓; orchestrator flag-only wiring + no-mutation (Task 7) ✓; Phase 3 explicitly gated/out-of-scope ✓.
- Type consistency: `run_tool_loop` → `tuple[str,int,dict]`; agents → `tuple[str,int,dict]`; `_run_agent` → 4-tuple; `Number(raw,value,kind)`; `Mismatch(number,year)`; `verify(answer, tool_blocks, rel_tol)`.
- Flag-only invariant: the answer string is never reassigned in the fidelity block.
