from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./copytrader.db"
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    
    # Polymarket API
    POLYMARKET_API_KEY: str = ""
    POLYMARKET_API_BASE_URL: str = "https://api.polymarket.com/v1"
    
    # Trading Settings
    GLOBAL_TRADING_MODE: str = "TEST"
    GLOBAL_TRADING_STATUS: str = "STOPPED"
    DRY_RUN_ENABLED: bool = True
    
    # Monitoring
    WALLET_POLL_INTERVAL: int = 30
    MAX_DAYS_TO_RESOLUTION: int = 30
    MIN_MARKET_VOLUME: float = 1000.0
    
    # Risk Management
    MAX_RISK_PER_TRADE_PCT: float = 2.0
    MAX_OPEN_MARKETS: int = 10
    MAX_EXPOSURE_PER_MARKET: float = 100.0
    
    class Config:
        env_file = ".env"

settings = Settings()
