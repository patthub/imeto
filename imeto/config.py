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
    upload_dir: str = "data/uploads"  # GUI uploads, kept by name (= source id)

    # Metadata anchors (loaders API). One e-mail for the Crossref and
    # OpenAlex "polite pool" — friendlier limits, same value for both.
    contact_email: str | None = None
    # optional: OpenAlex's free tier is ~$0.10/day (~1000 list calls); a full SSH
    # profile of a big university costs ~100+ calls — a key lifts that ceiling
    openalex_api_key: str | None = None

    @property
    def openalex_params(self) -> dict[str, str]:
        """Auth/politeness query params for every OpenAlex call."""
        p = {"mailto": self.contact_email} if self.contact_email else {}
        return p | ({"api_key": self.openalex_api_key} if self.openalex_api_key else {})


settings = Settings()  # imported by CLI/app (the core reads values explicitly)
