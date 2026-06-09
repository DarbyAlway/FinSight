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
    # 500,000M has no grounding in any year's data — must be flagged
    ms = verify("FY2024 net sales were 500,000M", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].number.value == 500000.0


def test_year_mislabel_flagged():
    # Real FY2023 (Sep 30, 2023) net sales: 383,285M.
    # Labeling near-match 383,058M as FY2025 must be flagged:
    # FY2025 (Sep 27, 2025) net sales = 416,161M — 383,058M is not within 1%.
    ms = verify("FY2025 net sales were $383,058M", _TOOL_BLOCKS)
    assert len(ms) == 1
    assert ms[0].year == 2025


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
