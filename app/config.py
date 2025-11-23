from pydantic_settings import BaseSettings
from typing import Literal

class Settings(BaseSettings):
    ENVIRONMENT: Literal["TEST", "LIVE"] = "TEST"
    DRY_RUN: bool = True
    BOT_STATUS: Literal["RUNNING", "PAUSED", "STOPPED"] = "STOPPED"

    DATABASE_URL: str
    SECRET_KEY: str
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str

    POLYMARKET_API_KEY: str | None = None
    POLYMARKET_WALLET_PRIVATE_KEY: str | None = None

    WALLET_POLL_INTERVAL: int = 15

    model_config = {"env_file": ".env"}

settings = Settings()