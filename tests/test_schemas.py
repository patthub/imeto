import pytest
from pydantic import ValidationError

from imeto.core.schemas import Extraction


def test_valid_extraction_parses():
    ex = Extraction.model_validate(
        {"facts": [{"quote": "przyjęła uchwałę nr 12", "statement": "Rada przyjęła."}]}
    )
    assert ex.facts[0].quote == "przyjęła uchwałę nr 12"


def test_empty_facts_list_is_valid():
    # model może nie znaleźć nic — to nie błąd formatu
    assert Extraction.model_validate({"facts": []}).facts == []


def test_extra_field_rejected():
    # twardy kontrakt: model nie może dokładać pól (np. zmyślonych offsetów)
    with pytest.raises(ValidationError):
        Extraction.model_validate(
            {"facts": [{"quote": "x", "statement": "y", "start": 0}]}
        )


def test_blank_quote_rejected():
    with pytest.raises(ValidationError):
        Extraction.model_validate({"facts": [{"quote": "  ", "statement": "y"}]})


def test_missing_statement_rejected():
    with pytest.raises(ValidationError):
        Extraction.model_validate({"facts": [{"quote": "x"}]})
