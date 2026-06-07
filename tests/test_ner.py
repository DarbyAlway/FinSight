"""Tests for tools/ner.py — GLiNER company-name extraction.

Empty-query and fail-open behavior are deterministic (no model needed). The
extraction-quality tests load the real GLiNER model and are skipped if it's
unavailable (not installed / no network for the model download).
"""

import pytest

from tools import ner


def test_extract_companies_empty_query_returns_empty():
    assert ner.extract_companies("") == []
    assert ner.extract_companies("   ") == []


def test_extract_companies_fails_open(monkeypatch):
    def boom():
        raise RuntimeError("model down")
    monkeypatch.setattr(ner, "_get_model", boom)
    assert ner.extract_companies("How did Microsoft do?") == []


def _require_model():
    try:
        ner._get_model()
    except Exception as e:
        pytest.skip(f"GLiNER model unavailable: {e}")


def test_extract_companies_finds_named_company():
    _require_model()
    out = [c.lower() for c in ner.extract_companies("How did Microsoft perform last quarter?")]
    assert any("microsoft" in c for c in out)


def test_extract_companies_finds_multiple_companies():
    _require_model()
    out = [c.lower() for c in ner.extract_companies("compare Microsoft and Nvidia revenue growth")]
    assert any("microsoft" in c for c in out)
    assert any("nvidia" in c for c in out)


def test_extract_companies_descriptive_query_does_not_hallucinate():
    _require_model()
    # No proper-noun company → resolution should fall to the semantic tier, and
    # NER must not invent a real company name here.
    out = [c.lower() for c in ner.extract_companies("what's wrong with the market today")]
    assert "microsoft" not in out and "apple" not in out


def test_extract_companies_catches_typos():
    _require_model()
    # The whole point: extract the typo'd span verbatim; the fuzzy tier fixes
    # spelling later. At threshold 0.3 both misspellings are caught.
    out = [c.lower() for c in ner.extract_companies("compare microsft and nvidia revenue")]
    assert "microsft" in out and "nvidia" in out


def test_extract_companies_chitchat_returns_empty():
    _require_model()
    assert ner.extract_companies("hello how are you doing today") == []


def test_extract_companies_does_not_shadow_company_with_product():
    _require_model()
    out = [c.lower() for c in ner.extract_companies("Nvidia's new AI chips are impressive")]
    assert any("nvidia" in c for c in out)


def test_extract_companies_handles_foreign_and_multiword_names():
    _require_model()
    out = [c.lower() for c in ner.extract_companies("Toyota vs Berkshire Hathaway")]
    assert any("toyota" in c for c in out)
    assert any("berkshire" in c for c in out)
