"""Cała konfiguracja w jednym miejscu, typowana (§7). Zastępuje rozsiane
`os.getenv`. Sekrety wyłącznie z env/.env — nigdy w kodzie."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Warstwa LLM (OpenAI-compatible; wymienność = zmiana URL/modelu, §8)
    llm_base_url: str = "http://localhost:8888/v1"
    llm_api_key: str = "sk-none"
    llm_model: str = ""  # walidowany przy użyciu (klient LLM), nie przy imporcie
    llm_json_mode: bool = False
    llm_temperature: float = 0.2

    # Dane: db_url to zarazem przełącznik silnika SQLite ↔ Postgres (§9.4)
    db_url: str = "sqlite:///imeto.db"
    knowledge_dir: str = "knowledge"

    # Kotwice metadanych (loaders API). Jeden e-mail do "polite pool"
    # Crossref i OpenAlex — grzeczniejsze limity, ta sama wartość dla obu.
    contact_email: str | None = None


settings = Settings()  # importowane przez CLI/app (rdzeń bierze wartości jawnie)
