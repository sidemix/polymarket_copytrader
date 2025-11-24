# app/config.py
from pydantic_settings import BaseSettings
from typing import Literal

class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str = "change-me"
    GLOBAL_TRADING_MODE: Literal["TEST", "LIVE"] = "TEST"
    GLOBAL_TRADING_STATUS: Literal["RUNNING", "PAUSED", "STOPPED"] = "STOPPED"
    DRY_RUN_ENABLED: bool = True
    MONITOR_INTERVAL_SECONDS: int = 15

    class Config:
        env_file = ".env"

settings = Settings()