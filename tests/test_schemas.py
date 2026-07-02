import pytest
from pydantic import ValidationError

from imeto.core.schemas import Extraction


def _fact(**kw: object) -> dict:
    base = {"statement": "Rada.", "kind": "direct", "quotes": ["uchwałę nr 12"]}
    base.update(kw)
    return {"facts": [base]}


def test_valid_extraction_parses():
    ex = Extraction.model_validate(_fact())
    assert ex.facts[0].kind == "direct"
    assert ex.facts[0].quotes == ["uchwałę nr 12"]


def test_inferred_kind_parses():
    ex = Extraction.model_validate(
        _fact(kind="inferred", quotes=["3 konferencje", "po 100 osób"])
    )
    assert ex.facts[0].kind == "inferred"
    assert len(ex.facts[0].quotes) == 2


def test_empty_facts_list_is_valid():
    assert Extraction.model_validate({"facts": []}).facts == []


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        Extraction.model_validate(_fact(start=0))


def test_missing_quotes_rejected():
    with pytest.raises(ValidationError):
        Extraction.model_validate({"facts": [{"statement": "x", "kind": "direct"}]})


def test_empty_quotes_list_rejected():
    with pytest.raises(ValidationError):
        Extraction.model_validate(_fact(quotes=[]))


def test_invalid_kind_rejected():
    with pytest.raises(ValidationError):
        Extraction.model_validate(_fact(kind="zgadywane"))


def test_blank_quote_rejected():
    with pytest.raises(ValidationError):
        Extraction.model_validate(_fact(quotes=["   "]))
