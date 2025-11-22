from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class LeaderWallet(Base):
    __tablename__ = "leader_wallets"
    
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String(42), unique=True, index=True, nullable=False)
    nickname = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_monitored = Column(DateTime, nullable=True)
    
    trades = relationship("LeaderTrade", back_populates="wallet")

class LeaderTrade(Base):
    __tablename__ = "leader_trades"
    
    id = Column(Integer, primary_key=True, index=True)
    external_trade_id = Column(String(100), unique=True, index=True, nullable=False)
    wallet_id = Column(Integer, ForeignKey("leader_wallets.id"), nullable=False)
    market_id = Column(String(100), nullable=False)
    outcome_id = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)  # "YES" or "NO"
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    executed_at = Column(DateTime, nullable=False)
    category = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    wallet = relationship("LeaderWallet", back_populates="trades")
    follower_trades = relationship("FollowerTrade", back_populates="leader_trade")

class FollowerTrade(Base):
    __tablename__ = "follower_trades"
    
    id = Column(Integer, primary_key=True, index=True)
    leader_trade_id = Column(Integer, ForeignKey("leader_trades.id"), nullable=False)
    market_id = Column(String(100), nullable=False)
    outcome_id = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    executed_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="EXECUTED")  # EXECUTED, FAILED, SIMULATED
    pnl = Column(Float, default=0.0)
    is_dry_run = Column(Boolean, default=False)
    
    leader_trade = relationship("LeaderTrade", back_populates="follower_trades")

class Position(Base):
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    market_id = Column(String(100), nullable=False)
    outcome_id = Column(String(50), nullable=False)
    size = Column(Float, nullable=False)
    average_price = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    global_trading_mode = Column(String(10), default="TEST")  # TEST, LIVE
    global_trading_status = Column(String(10), default="STOPPED")  # RUNNING, PAUSED, STOPPED
    dry_run_enabled = Column(Boolean, default=True)
    min_market_volume = Column(Float, default=1000.0)
    max_days_to_resolution = Column(Integer, default=30)
    max_risk_per_trade_pct = Column(Float, default=2.0)
    max_open_markets = Column(Integer, default=10)
    max_exposure_per_market = Column(Float, default=100.0)
    copy_trade_percentage = Column(Float, default=20.0)
    max_trade_amount = Column(Float, default=100.0)
    daily_loss_limit = Column(Float, default=200.0)
    max_trades_per_hour = Column(Integer, default=10)
    updated_at = Column(DateTime, default=datetime.utcnow)

class SystemEvent(Base):
    __tablename__ = "system_events"
    
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50), nullable=False)  # TRADE, RISK_ALERT, SYSTEM, ERROR
    message = Column(Text, nullable=False)
    level = Column(String(20), default="INFO")  # INFO, WARNING, ERROR
    metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
