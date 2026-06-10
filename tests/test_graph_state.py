from graph_state import merge_dicts, add_token_counts


def test_merge_dicts_combines_parallel_agent_results():
    assert merge_dicts({"financials": "a"}, {"news": "b"}) == {"financials": "a", "news": "b"}


def test_merge_dicts_handles_none_sides():
    assert merge_dicts(None, {"x": 1}) == {"x": 1}
    assert merge_dicts({"x": 1}, None) == {"x": 1}
    assert merge_dicts(None, None) == {}


def test_merge_dicts_right_side_wins_on_collision():
    assert merge_dicts({"x": 1}, {"x": 2}) == {"x": 2}


def test_add_token_counts_sums_per_key():
    assert add_token_counts({"agents": 100}, {"agents": 50, "plan": 10}) == {"agents": 150, "plan": 10}


def test_add_token_counts_handles_none():
    assert add_token_counts(None, {"plan": 5}) == {"plan": 5}
