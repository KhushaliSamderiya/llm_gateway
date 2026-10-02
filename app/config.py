from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str
    database_url: str
    redis_url: str
    mock_delay_ms: int = 200
    mock_failure_rate: float = 0.0


settings = Settings()
