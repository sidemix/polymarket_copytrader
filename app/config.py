# app/config.py
from pydantic import BaseSettings, Field
from typing import Literal

class Settings(BaseSettings):
    # Core
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    
    # Bot Modes
    GLOBAL_TRADING_MODE: Literal["TEST", "LIVE"] = "TEST"
    GLOBAL_TRADING_STATUS: Literal["RUNNING", "PAUSED", "STOPPED"] = "STOPPED"
    DRY_RUN_ENABLED: bool = True
    
    # Security
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD_HASH: str = Field(..., env="ADMIN_PASSWORD_HASH")  # argon2
    
    # Monitoring
    MONITOR_INTERVAL_SECONDS: int = 15
    EXECUTOR_QUEUE_SIZE: int = 100
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()