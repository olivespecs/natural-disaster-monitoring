from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379"
    eonet_api_url: str = "https://eonet.gsfc.nasa.gov/api/v3"
    poll_interval_seconds: int = 60
    max_events_per_poll: int = 50
    event_days_window: int = 7
    eonet_timeout_seconds: float = 30.0
    eonet_max_retries: int = 3
    eonet_retry_backoff_seconds: float = 1.2
    job_max_retries: int = 2
    max_queue_depth: int = 500
    inference_batch_size: int = 8

    # Gemini AI — optional; if blank, heuristic engine is used
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemma-4-26b-a4b-it"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
