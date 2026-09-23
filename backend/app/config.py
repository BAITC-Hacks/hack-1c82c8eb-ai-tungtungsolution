from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    openai_api_key: str
    openai_model: str
    frontend_dist: str | None = None


settings = Settings()  # pyright: ignore[reportCallIssue]
