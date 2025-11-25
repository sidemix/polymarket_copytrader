# app/models.py
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, JSON, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

class LeaderWallet(Base):
    __tablename__ = "leader_wallets"
    id = Column(Integer, primary_key=True)
    address = Column(String(44), unique=True, nullable=False, index=True)
    nickname = Column(String(100))
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

class LeaderTrade(Base):
    __tablename__ = "leader_trades"
    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey("leader_wallets.id"), index=True)
    external_trade_id = Column(String(100), unique=True, nullable=False)
    market_id = Column(String(100), index=True)
    outcome_id = Column(Integer)
    side = Column(String(10))  # YES/NO
    size_usd = Column(Float)
    price = Column(Float)
    executed_at = Column(DateTime(timezone=True))
    raw_data = Column(JSON)
    processed = Column(Boolean, default=False, nullable=False)

    wallet = relationship("LeaderWallet")

class FollowerTrade(Base):
    __tablename__ = "follower_trades"
    id = Column(Integer, primary_key=True)
    leader_trade_id = Column(Integer, ForeignKey("leader_trades.id"))
    market_id = Column(String(100), index=True)
    outcome_id = Column(Integer)
    side = Column(String(10))
    size_usd = Column(Float)
    price = Column(Float)
    status = Column(String(20), default="executed")  # executed, failed, simulated
    executed_at = Column(DateTime(timezone=True), server_default=func.now())
    dry_run = Column(Boolean, default=True)

class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True)
    market_id = Column(String(100), index=True)
    outcome_id = Column(Integer)
    size = Column(Float)
    avg_price = Column(Float)
    unrealized_pnl = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

class SystemEvent(Base):
    __tablename__ = "system_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(50))  # trade_executed, risk_block, bot_start, etc.
    message = Column(Text)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SettingsSingleton(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, default=1)
    global_trading_mode = Column(String(10), default="TEST")
    global_trading_status = Column(String(10), default="STOPPED")
    dry_run_enabled = Column(Boolean, default=True)
    risk_max_per_trade_pct = Column(Float, default=2.0)
    risk_max_open_markets = Column(Integer, default=10)