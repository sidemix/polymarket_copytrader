# app/config.py — WORKS EVERYWHERE
import os
from pydantic import BaseModel

class Settings(BaseModel):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/polymarket_bot")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-in-production-1234567890")
    GLOBAL_TRADING_MODE: str = os.getenv("GLOBAL_TRADING_MODE", "TEST")
    GLOBAL_TRADING_STATUS: str = os.getenv("GLOBAL_TRADING_STATUS", "STOPPED")
    DRY_RUN_ENABLED: bool = os.getenv("DRY_RUN_ENABLED", "true").lower() == "true"
    MONITOR_INTERVAL_SECONDS: int = int(os.getenv("MONITOR_INTERVAL_SECONDS", "15"))

settings = Settings()