from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".envs" / ".env.local"),
        env_ignore_empty=True,
        extra="ignore",
    )

    PROJECT_NAME: str = ""
    PROJECT_DESCRIPTION: str = ""
    API_V1_STR: str = ""
    SITE_NAME: str = ""

    DATABASE_URL: str = ""


settings = Settings()
