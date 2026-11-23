from pathlib import Path

from dotenv import find_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings read from the environment and the .env file."""

    profiles_encryption_key: SecretStr = SecretStr("change-me")
    environment: str = "prod"
    profile_lock_timeout_seconds: float = 30.0
    scraping_proxy: SecretStr | None = None
    classify_min_words: int = 50
    domain_memory_path: Path = Path("domain_memory.sqlite3")
    memory_ttl_seconds: float = 24 * 3600
    memory_probe_every: int = 20
    memory_failure_threshold: int = 3
    request_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        extra="allow", env_file=find_dotenv(), env_file_encoding="utf-8"
    )


settings = Settings()
