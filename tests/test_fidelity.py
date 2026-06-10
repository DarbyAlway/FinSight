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
    nums = extract_numbers("In FY2024 across 3 segments and 2025 guidance")
    assert nums == []


def test_dollar_and_suffix_not_double_counted():
    nums = extract_numbers("$1.23B")
    assert len(nums) == 1
    assert nums[0].kind == "money_millions"


from tools.fidelity import extract_year_bound_numbers


def test_year_from_date_on_line():
    pairs = extract_year_bound_numbers("Revenue: 391,035M  (Sep 28, 2024)")
    assert (2024, 391035.0, "money_millions") in [(y, n.value, n.kind) for y, n in pairs]


def test_year_from_fy_token():
    pairs = extract_year_bound_numbers("FY2025 revenue was $383,058M")
    assert (2025, 383058.0, "money_millions") in [(y, n.value, n.kind) for y, n in pairs]


def test_number_without_year_has_none():
    pairs = extract_year_bound_numbers("Gross margin is 45.2%")
    assert (None, 45.2, "percent") in [(y, n.value, n.kind) for y, n in pairs]


from tools.fidelity import verify
from tools.income import get_income_statement
from tools.balance_sheet import get_balance_sheet
from tools.db import load_earnings

# Real tool outputs fetched from the live cache — these are the exact strings the
# orchestrator receives and passes into verify(). No fabricated data.
_INCOME_BLOCK = get_income_statement("AAPL")
_BALANCE_BLOCK = get_balance_sheet("AAPL")
_EARNINGS_BLOCK = load_earnings("AAPL")

_TOOL_BLOCKS = {
    "get_income_statement({\"ticker\": \"AAPL\"})": _INCOME_BLOCK,
    "get_balance_sheet({\"ticker\": \"AAPL\"})": _BALANCE_BLOCK,
    "get_earnings({\"ticker\": \"AAPL\"})": _EARNINGS_BLOCK,
}


def test_exact_match_no_mismatch():
    # Real FY2024 (Sep 28, 2024) net sales from 10-K: 391,035M
    assert verify("Net sales were 391,035M in FY2024", _TOOL_BLOCKS) == []


def test_reformatted_unit_matches():
    # Same value written with a leading $ — fidelity must still pass
    assert verify("Net sales were $391,035M in FY2024", _TOOL_BLOCKS) == []


def test_rounded_within_tolerance_matches():
    # 391,000M is within 1% of the real 391,035M
    assert verify("Roughly $391,000M in FY2024", _TOOL_BLOCKS) == []


def test_genuinely_wrong_number_flagged():
    # 500,000M has no grounding in any year's data — must be flagged as HARD
    ms = verify("FY2024 net sales were 500,000M", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].number.value == 500000.0
    assert ms[0].hard is True  # absent from every fetched year


def test_year_mislabel_flagged():
    # Real FY2023 (Sep 30, 2023) net sales: 383,285M.
    # Labeling near-match 383,058M as FY2025 must be flagged:
    # FY2025 (Sep 27, 2025) net sales = 416,161M — 383,058M is not within 1%.
    ms = verify("FY2025 net sales were $383,058M", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].year == 2025
    # 383,058 is within 1% of FY2023's real 383,285 -> real for another year -> SOFT
    assert ms[0].hard is False


def test_balance_sheet_value_passes():
    # Real Sep 28, 2024 cash (balance sheet, no year on value line → any-year):
    # $29,943M. Answer has no year token so any-year lookup is used.
    assert verify("Cash and cash equivalents were $29,943M", _TOOL_BLOCKS) == []


def test_earnings_eps_passes():
    # Real EPS $1.85 from AAPL Q3 2025. Earnings lines carry no year token, so
    # grounded in any_year. Answer must also carry no year token to use any-year
    # lookup (a year token would route to by_year which has no EPS entries).
    assert verify("AAPL EPS was $1.85", _TOOL_BLOCKS) == []


def test_empty_grounding_flags_all_numbers():
    ms = verify("Net sales were 391,035M and margin 45%", {})
    assert len(ms) == 2


# ----------------------------------------------------------------------------
# Edge cases: word-form magnitudes, ranges, multi-number lines, kind mismatch.
# Real synthesis models routinely write "$391 billion" rather than "391,035M".
# ----------------------------------------------------------------------------

def test_word_form_billion_is_money_millions():
    assert (391000.0, "money_millions") in _kinds("Revenue was $391 billion")


def test_word_form_million():
    assert (1500.0, "money_millions") in _kinds("Net income of 1,500 million")


def test_word_form_trillion():
    assert (3000000.0, "money_millions") in _kinds("Market cap of $3 trillion")


def test_word_form_not_double_counted_with_dollars():
    nums = extract_numbers("$391 billion")
    assert len(nums) == 1
    assert nums[0].kind == "money_millions"


def test_word_form_matches_suffix_grounding():
    # Grounding income block has 391,035M; "$391 billion" == 391,000M, within 1%.
    # Cross-format match is the whole point — a model reformatting must still pass.
    assert verify("Net sales were $391 billion in FY2024", _TOOL_BLOCKS) == []


def test_negative_loss_margin_percent_extracted():
    # Real loss-makers report negative margins. The sign is currently DROPPED
    # (both answer and grounding parse the same way, so matching still works).
    # KNOWN LIMITATION: a pure sign-flip (+5.2% vs -5.2%) would not be flagged.
    assert (5.2, "percent") in _kinds("Operating margin was -5.2%")


def test_multiple_numbers_one_line():
    vals = {(n.value, n.kind) for n in extract_numbers("Revenue $391,035M, net income $93,736M")}
    assert (391035.0, "money_millions") in vals
    assert (93736.0, "money_millions") in vals


def test_money_range_yields_two_numbers():
    vals = [n.value for n in extract_numbers("guidance of $100M to $120M")]
    assert 100.0 in vals and 120.0 in vals


def test_kind_mismatch_is_flagged():
    # answer says "1.85%" but grounding only has 1.85 as a ratio (x) — wrong kind.
    blocks = {"get_ratios({})": "Current ratio: 1.85x  (Sep 28, 2024)"}
    ms = verify("The figure was 1.85% in FY2024", blocks)
    assert len(ms) == 1
    assert ms[0].number.kind == "percent"


def test_ratio_grounds_correctly():
    blocks = {"get_ratios({})": "Current ratio: 1.85x  (Sep 28, 2024)"}
    assert verify("Current ratio was 1.85x in FY2024", blocks) == []


# ----------------------------------------------------------------------------
# Regression: a live SambaNova run produced the CORRECT answer below, but the
# old last-year-wins heuristic bound BOTH figures to FY2023, false-flagging the
# FY2024 value. Year association must be per-figure (proximity-based).
# ----------------------------------------------------------------------------

def test_multi_figure_sentence_assigns_year_by_proximity():
    pairs = extract_year_bound_numbers(
        "Apple's revenue was $391,035 million in FY2024 and $383,285 million in FY2023."
    )
    d = {(y, n.kind): n.value for y, n in pairs}
    assert d[(2024, "money_millions")] == 391035.0
    assert d[(2023, "money_millions")] == 383285.0


def test_year_before_number_still_associates():
    # 'FY2024 revenue was $391,035M' — year precedes the value
    pairs = extract_year_bound_numbers("FY2024 revenue was $391,035M")
    assert (2024, 391035.0, "money_millions") in [(y, n.value, n.kind) for y, n in pairs]


def test_real_correct_multi_year_answer_not_flagged():
    # The exact live-run answer. Both figures are real and correctly labeled,
    # so a faithful verifier must report ZERO mismatches.
    answer = "Apple's revenue was $391,035 million in FY2024 and $383,285 million in FY2023."
    assert verify(answer, _TOOL_BLOCKS) == []


# ----------------------------------------------------------------------------
# Regression: a second live run (MSFT) gave the CORRECT answer in 'years-then-
# values respectively' form. The old proximity binding put every value under the
# last preceding year (FY2025), false-flagging the FY2023/FY2024 figures.
# Enumeration binding must map i-th year to i-th value.
# ----------------------------------------------------------------------------

def test_enumeration_years_then_values_binds_in_order():
    s = ("FY2023, FY2024, and FY2025, which are $211,915 million, "
         "$245,122 million, and $281,724 million, respectively.")
    d = {(y, n.kind): n.value for y, n in extract_year_bound_numbers(s)}
    assert d[(2023, "money_millions")] == 211915.0
    assert d[(2024, "money_millions")] == 245122.0
    assert d[(2025, "money_millions")] == 281724.0


def test_enumeration_correct_answer_not_flagged():
    # Real MSFT revenue in real income-statement format; the live-run phrasing.
    blocks = {"get_income_statement({\"ticker\": \"MSFT\"})": (
        "MSFT Income Statement (cached)\n"
        "  Revenue\n"
        "    Total revenue: 211,915M  (Jun 30, 2023)\n"
        "    Total revenue: 245,122M  (Jun 30, 2024)\n"
        "    Total revenue: 281,724M  (Jun 30, 2025)\n"
    )}
    answer = ("FY2023, FY2024, and FY2025 revenues are $211,915 million, "
              "$245,122 million, and $281,724 million, respectively.")
    assert verify(answer, blocks) == []


# ----------------------------------------------------------------------------
# Out-of-coverage-year hallucination (live-reported): grounding covers
# FY2023-FY2025 only, but synthesis answers with FY2022 figures recalled from
# pretraining. Apple's REAL FY2022 revenue ($394.3B) is within 1% of FY2024's
# $391,035M, so the value-only check calls it soft and the self-critique never
# fires. A figure bound to a year the tools never returned cannot be a
# mislabel-between-fetched-years — it must be HARD.
# ----------------------------------------------------------------------------

from tools.fidelity import build_grounding
from tools.cash_flow import get_cash_flow_statement

_CF_BLOCK = get_cash_flow_statement("KO")  # real 10-K cash flow, cached


def test_grounding_years_are_dynamic_not_hardcoded():
    # Coverage windows differ per ticker (AAPL 2023-2025; ARM/SNOW 2024-2026),
    # so the year set must come from THIS query's tool blocks.
    by_year, _ = build_grounding(_TOOL_BLOCKS)
    years = {y for (y, _k) in by_year}
    assert 2023 in years and 2025 in years
    assert 2022 not in years


def test_out_of_coverage_year_is_hard():
    ms = verify("In FY2022, Apple reported revenue of $394.3 billion.", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].year == 2022
    assert ms[0].hard is True  # 2022 was never fetched — prior knowledge


def test_out_of_coverage_future_year_is_hard():
    # Real FY2025 value relabeled to a year beyond coverage must also be HARD.
    ms = verify("FY2030 revenue is projected at $416,161M.", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].hard is True


def test_in_coverage_mislabel_stays_soft():
    # Guard: the out-of-coverage rule must NOT harden in-coverage mislabels
    # (FY2025 is fetched; 383,058M matches FY2023) — re-prompt churn risk.
    ms = verify("FY2025 net sales were $383,058M", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].hard is False


def test_yearless_grounding_keeps_year_claims_soft():
    # When the grounding carries NO year tokens at all, the verifier cannot
    # judge year claims — a correct value with a year label must stay SOFT
    # (flag-only), never trigger the self-critique re-prompt.
    blocks = {"calculate_current_ratio({})": "Current ratio: 1.85x"}
    ms = verify("Current ratio was 1.85x in FY2024", blocks)
    assert len(ms) == 1
    assert ms[0].hard is False


# ----------------------------------------------------------------------------
# Block-scoped year binding: the cash-flow (and balance-sheet) tool formats put
# the date on a HEADER line ("  Dec 31, 2025") with the figures on the lines
# below. Per-line year binding loses the year, so every year-labeled cash-flow
# figure in an answer false-flags soft today — and would false-HARD under the
# out-of-coverage rule. Header years must be inherited by following lines when
# building grounding.
# ----------------------------------------------------------------------------

def test_cash_flow_header_year_inherited_in_grounding():
    by_year, _ = build_grounding({"get_cash_flow_statement({})": _CF_BLOCK})
    years = {y for (y, _k) in by_year}
    assert years, "cash-flow grounding lost all year bindings"


def test_correct_year_labeled_cash_flow_answer_not_flagged():
    # Real KO FY2025 figure from the 10-K, under the "Dec 31, 2025" header:
    # "Net Cash Provided by Operating Activities: $7,408M"
    blocks = {"get_cash_flow_statement({})": _CF_BLOCK}
    assert verify("Operating cash flow was $7,408M in FY2025", blocks) == []


def test_answer_side_lines_do_not_inherit_years():
    # Inheritance applies to GROUNDING only. Answer prose keeps per-line
    # binding so a yearless sentence still gets the lenient any-year match.
    pairs = extract_year_bound_numbers("FY2024 was strong.\nGross margin is 45.2%")
    assert (None, 45.2, "percent") in [(y, n.value, n.kind) for y, n in pairs]


# ----------------------------------------------------------------------------
# Prevention (prompt side): synthesis must be told the data covers specific
# fiscal years and that uncovered years are unavailable — not recalled.
# ----------------------------------------------------------------------------

def test_synthesis_prompt_has_year_coverage_rule():
    from prompts import SYNTHESIS_SYSTEM
    assert "fiscal year that is not in the agent outputs" in SYNTHESIS_SYSTEM


def test_enumeration_does_not_mask_real_mislabel():
    # A genuine year-mislabel inside an enumeration must STILL flag: here the
    # FY2024 slot carries 999,999M, which is real for no MSFT year.
    blocks = {"get_income_statement({\"ticker\": \"MSFT\"})": (
        "MSFT Income Statement (cached)\n"
        "    Total revenue: 211,915M  (Jun 30, 2023)\n"
        "    Total revenue: 245,122M  (Jun 30, 2024)\n"
        "    Total revenue: 281,724M  (Jun 30, 2025)\n"
    )}
    answer = ("FY2023, FY2024, and FY2025 revenues are $211,915 million, "
              "$999,999 million, and $281,724 million, respectively.")
    ms = verify(answer, blocks)
    assert len(ms) == 1
    assert ms[0].number.value == 999999.0
    assert ms[0].year == 2024
