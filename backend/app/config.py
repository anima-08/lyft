from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    llm_api_keys: Annotated[list[str], NoDecode] = Field(default_factory=list, validation_alias="LLM_API_KEYS")
    llm_model: str = Field(default="gemini/gemini-3.5-flash-lite", validation_alias="LLM_MODEL")
    database_url: str = Field(default="sqlite:////data/app.db", validation_alias="DATABASE_URL")
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        validation_alias="ALLOWED_ORIGINS",
    )
    enable_failure_simulation: bool = Field(default=True, validation_alias="ENABLE_FAILURE_SIMULATION")
    cache_ttl_seconds: int = Field(default=3600, ge=1, validation_alias="CACHE_TTL_SECONDS")
    request_timeout_seconds: float = Field(default=45.0, gt=0, validation_alias="REQUEST_TIMEOUT_SECONDS")
    max_output_tokens: int = Field(default=4096, ge=1, validation_alias="MAX_OUTPUT_TOKENS")
    temperature: float | None = Field(default=None, ge=0, le=2, validation_alias="TEMPERATURE")
    default_system_prompt: str = Field(
        default=(
            "You are Lyftr AI, a thoughtful and concise assistant. "
            "Use the conversation history to answer follow-up questions. "
            "If you are uncertain, say so clearly."
        ),
        validation_alias="DEFAULT_SYSTEM_PROMPT",
    )

    @field_validator("llm_api_keys", "allowed_origins", mode="before")
    @classmethod
    def split_comma_separated_values(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def database_must_be_sqlite(cls, value: str) -> str:
        if not value.startswith("sqlite:///"):
            raise ValueError("DATABASE_URL must be a SQLite URL")
        return value

    @field_validator("default_system_prompt")
    @classmethod
    def prompt_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("default system prompt must not be empty")
        return value

    def validate_runtime(self) -> None:
        if len(self.llm_api_keys) < 2:
            raise ValueError("LLM_API_KEYS must contain at least two API keys")
        if not self.llm_model.strip():
            raise ValueError("LLM_MODEL must not be empty")
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("DATABASE_URL must be a SQLite URL")

    @property
    def sqlite_path(self) -> Path:
        database_url = self.database_url
        if database_url.startswith("sqlite:////"):
            return Path("/" + database_url.removeprefix("sqlite:////"))
        if database_url.startswith("sqlite:///"):
            return Path(database_url.removeprefix("sqlite:///"))
        raise ValueError("DATABASE_URL must be a SQLite URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
