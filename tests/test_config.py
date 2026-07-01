import pytest

from imeto.config import Settings


def test_defaults_load():
    s = Settings()
    assert s.db_url.startswith("sqlite")
    assert s.llm_temperature == 0.2
    assert s.llm_model == ""  # nie wymagany przy imporcie


def test_env_overrides_and_coerces_types(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DB_URL", "postgresql+psycopg://x")
    monkeypatch.setenv("LLM_JSON_MODE", "true")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.0")
    s = Settings()
    assert s.db_url == "postgresql+psycopg://x"
    assert s.llm_json_mode is True  # str -> bool
    assert s.llm_temperature == 0.0
