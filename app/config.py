# app/config.py — 100% ENV-DRIVEN
from pydantic import BaseModel
import os

class Settings(BaseModel):
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-now")
    
    # Bot settings — CHANGE THESE IN RAILWAY VARIABLES
    GLOBAL_TRADING_MODE: str = os.getenv("TRADING_MODE", "TEST")  # TEST or LIVE
    GLOBAL_TRADING_STATUS: str = os.getenv("BOT_STATUS", "STOPPED")  # RUNNING/STOPPED
    DRY_RUN_ENABLED: bool = os.getenv("DRY_RUN", "true").lower() == "true"
    
    # Default balance (overridden by DB)
    DEFAULT_PORTFOLIO_VALUE: float = float(os.getenv("DEFAULT_PORTFOLIO", "10019"))
    DEFAULT_AVAILABLE_CASH: float = float(os.getenv("DEFAULT_CASH", "5920"))

settings = Settings()