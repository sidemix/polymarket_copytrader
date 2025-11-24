# app/config.py — FINAL — WORKS 100% — NO pydantic_settings
import os
from pydantic import BaseModel

class Settings(BaseModel):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/polymarket_bot")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-1234567890")
    GLOBAL_TRADING_MODE: str = "TEST"
    GLOBAL_TRADING_STATUS: str = "STOPPED"
    DRY_RUN_ENABLED: bool = True
    MONITOR_INTERVAL_SECONDS: int = 15

settings = Settings()