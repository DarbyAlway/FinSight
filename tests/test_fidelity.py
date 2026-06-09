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
