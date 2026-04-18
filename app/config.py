from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379"
    eonet_api_url: str = "https://eonet.gsfc.nasa.gov/api/v3"
    poll_interval_seconds: int = 60
    max_events_per_poll: int = 50
    event_days_window: int = 7

    # Gemini AI — optional; if blank, heuristic engine is used
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-1.5-flash"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
