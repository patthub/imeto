"""All config in one place, typed (§7). Replaces scattered
`os.getenv`. Secrets only from env/.env — never in code."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM layer (OpenAI-compatible; swappable = change URL/model, §8)
    llm_base_url: str = "http://localhost:8888/v1"
    llm_api_key: str = "sk-none"
    llm_model: str = ""  # validated on use (LLM client), not on import
    llm_json_mode: bool = False
    llm_temperature: float = 0.2
    chunk_chars: int = 6000  # text-splitting threshold (for the model's context)

    # Data: db_url doubles as the SQLite ↔ Postgres engine switch (§9.4)
    db_url: str = "sqlite:///imeto.db"
    knowledge_dir: str = "knowledge"

    # Metadata anchors (loaders API). One e-mail for the Crossref and
    # OpenAlex "polite pool" — friendlier limits, same value for both.
    contact_email: str | None = None


settings = Settings()  # imported by CLI/app (the core reads values explicitly)
