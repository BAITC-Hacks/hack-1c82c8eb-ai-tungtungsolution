from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    openai_api_key: str
    openai_model: str
    frontend_dist: str | None = None
    agent_timeout_seconds: float = Field(default=10, gt=0, le=10)
    agent_max_rounds: int = Field(default=4, ge=1, le=4)
    recommendation_cache_ttl_seconds: float = Field(default=300, gt=0)
    recommendation_cache_max_entries: int = Field(default=256, ge=1)


settings = Settings()  # pyright: ignore[reportCallIssue]
