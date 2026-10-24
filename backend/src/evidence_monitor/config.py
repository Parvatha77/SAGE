"""Load configuration from environment / .env file."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv(Path(__file__).parent.parent.parent / ".env")  # backend/.env


class Settings(BaseSettings):
    # Phase 1
    openalex_api_key: str = Field(default="", alias="OPENALEX_API_KEY")
    crossref_mailto: str = Field(default="", alias="CROSSREF_MAILTO")
    db_url: str = Field(default="sqlite:///evidence.db", alias="DB_URL")
    cache_dir: Path = Field(default=Path(".cache"), alias="CACHE_DIR")

    # Phase 2
    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_api_keys: str = Field(default="", alias="GROQ_API_KEYS")  # comma-separated extra keys
    extraction_model: str = Field(default="qwen/qwen3.8-27b", alias="EXTRACTION_MODEL")
    groq_rpm_cap: int = Field(default=30, alias="GROQ_RPM_CAP")

    # Domo / OpenAI-compatible endpoint
    domo_base_url: str = Field(default="", alias="DOMO_BASE_URL")
    domo_api_key: str = Field(default="", alias="DOMO_API_KEY")
    assessment_model: str = Field(default="domo.openai.gpt-4o-mini", alias="ASSESSMENT_MODEL")

    def all_groq_keys(self) -> list[str]:
        """Return all unique non-empty Groq API keys."""
        from dotenv import dotenv_values
        env_path = Path(__file__).parent.parent.parent / ".env"
        raw = dotenv_values(env_path)
        keys = []
        single = raw.get("GROQ_API_KEY", "") or self.groq_api_key
        multi = raw.get("GROQ_API_KEYS", "") or self.groq_api_keys
        if single:
            keys.append(single.strip())
        for k in multi.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
        return keys

    model_config = {"populate_by_name": True}


settings = Settings()
