from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.sql import func
from .db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

class LeaderWallet(Base):
    __tablename__ = "leader_wallets"
    id = Column(Integer, primary_key=True)
    address = Column(String(42), unique=True, nullable=False, index=True)
    nickname = Column(String(100))
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

class LeaderTrade(Base):
    __tablename__ = "leader_trades"
    id = Column(Integer, primary_key=True)
    leader_wallet_id = Column(Integer, ForeignKey("leader_wallets.id"))
    external_trade_id = Column(String(100), unique=True, index=True)
    market_id = Column(String(100), index=True)
    outcome_id = Column(Integer)
    side = Column(String(10))  # YES / NO
    size = Column(Float)
    price = Column(Float)
    executed_at = Column(DateTime(timezone=True))
    raw_data = Column(JSON)

class FollowerTrade(Base):
    __tablename__ = "follower_trades"
    id = Column(Integer, primary_key=True)
    leader_trade_id = Column(Integer, ForeignKey("leader_trades.id"))
    market_id = Column(String(100), index=True)
    outcome_id = Column(Integer)
    side = Column(String(10))
    size_usd = Column(Float)
    executed = Column(Boolean, default=False)
    executed_at = Column(DateTime(timezone=True))
    dry_run = Column(Boolean)
    result = Column(Text)

class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True)
    market_id = Column(String(100), index=True)
    outcome_id = Column(Integer)
    size = Column(Float)
    avg_price = Column(Float)
    unrealized_pnl = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, default=1)
    copy_percentage = Column(Float, default=20.0)
    max_trade_usd = Column(Float, default=100.0)
    daily_loss_limit = Column(Float, default=200.0)
    min_market_volume = Column(Float, default=10000.0)
    max_days_to_resolution = Column(Integer, default=180)

class SystemEvent(Base):
    __tablename__ = "system_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(50))
    message = Column(Text)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())