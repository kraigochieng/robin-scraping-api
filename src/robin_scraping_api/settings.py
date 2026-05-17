from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    profiles_encryption_key: str
    environment: str
    
    model_config = SettingsConfigDict(
        extra="allow", env_file=find_dotenv(), env_file_encoding="utf-8"
    )


settings = Settings()
