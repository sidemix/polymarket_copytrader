from fastapi import FastAPI, Depends, HTTPException, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import json
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta

from app.database import get_db
from app.models import (
    User, LeaderWallet, LeaderTrade, FollowerTrade, 
    Position, Settings, SystemEvent
)
from app.auth import get_current_user, create_access_token, verify_password
from app.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Polymarket Copytrader", version="1.0.0")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get current settings
def get_current_settings(db: Session = Depends(get_db)) -> Settings:
    settings_obj = db.query(Settings).first()
    if not settings_obj:
        settings_obj = Settings()
        db.add(settings_obj)
        db.commit()
    return settings_obj

# Authentication Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/dashboard")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password) or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create session
    request.session["user_id"] = user.id
    
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out successfully"}

# Dashboard Routes
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Get current settings
    current_settings = get_current_settings(db)
    
    # Get stats for dashboard
    total_trades = db.query(FollowerTrade).count()
    profitable_trades = db.query(FollowerTrade).filter(FollowerTrade.pnl > 0).count()
    total_profit = db.query(FollowerTrade).filter(FollowerTrade.pnl > 0).with_entities(
        db.func.sum(FollowerTrade.pnl)
    ).scalar() or 0
    active_wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active == True).count()
    
    win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0
    
    # Get recent system events
    recent_events = db.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(50).all()
    
    # Get top wallets
    top_wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active == True).all()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": current_user,
        "settings": current_settings,
        "stats": {
            "total_trades": total_trades,
            "profitable_trades": profitable_trades,
            "total_profit": total_profit,
            "win_rate": win_rate,
            "active_wallets": active_wallets,
            "risk_level": "Low"
        },
        "recent_events": recent_events,
        "top_wallets": top_wallets
    })

# API Routes for Dashboard Data
@app.get("/api/stats")
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    total_trades = db.query(FollowerTrade).count()
    profitable_trades = db.query(FollowerTrade).filter(FollowerTrade.pnl > 0).count()
    total_profit = db.query(FollowerTrade).filter(FollowerTrade.pnl > 0).with_entities(
        db.func.sum(FollowerTrade.pnl)
    ).scalar() or 0
    active_wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active == True).count()
    
    win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0
    
    return {
        "totalTrades": total_trades,
        "profitableTrades": profitable_trades,
        "totalProfit": round(total_profit, 2),
        "winRate": round(win_rate, 1),
        "activeWallets": active_wallets,
        "riskLevel": "Low"
    }

@app.get("/api/wallets")
async def get_wallets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    wallets = db.query(LeaderWallet).all()
    return [
        {
            "id": wallet.id,
            "address": wallet.address,
            "nickname": wallet.nickname,
            "is_active": wallet.is_active,
            "created_at": wallet.created_at.isoformat(),
            "last_monitored": wallet.last_monitored.isoformat() if wallet.last_monitored else None,
            "trade_count": len(wallet.trades)
        }
        for wallet in wallets
    ]

@app.post("/api/wallets")
async def add_wallet(
    nickname: str = Form(...),
    address: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate address format (basic check)
    if not address.startswith("0x") or len(address) != 42:
        raise HTTPException(status_code=400, detail="Invalid wallet address format")
    
    # Check if wallet already exists
    existing = db.query(LeaderWallet).filter(LeaderWallet.address == address).first()
    if existing:
        raise HTTPException(status_code=400, detail="Wallet already exists")
    
    wallet = LeaderWallet(
        nickname=nickname,
        address=address,
        is_active=True
    )
    
    db.add(wallet)
    db.commit()
    
    # Log system event
    event = SystemEvent(
        event_type="WALLET_ADDED",
        message=f"Added new wallet: {nickname} ({address})",
        level="INFO"
    )
    db.add(event)
    db.commit()
    
    return {"message": "Wallet added successfully"}

@app.delete("/api/wallets/{wallet_id}")
async def delete_wallet(
    wallet_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    wallet = db.query(LeaderWallet).filter(LeaderWallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    db.delete(wallet)
    db.commit()
    
    event = SystemEvent(
        event_type="WALLET_REMOVED",
        message=f"Removed wallet: {wallet.nickname}",
        level="INFO"
    )
    db.add(event)
    db.commit()
    
    return {"message": "Wallet deleted successfully"}

# Bot Control Routes
@app.post("/api/bot/start")
async def start_bot(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    current_settings = get_current_settings(db)
    
    if current_settings.global_trading_status == "RUNNING":
        raise HTTPException(status_code=400, detail="Bot is already running")
    
    # Update settings
    current_settings.global_trading_status = "RUNNING"
    db.commit()
    
    event = SystemEvent(
        event_type="BOT_STARTED",
        message="Trading bot started",
        level="INFO"
    )
    db.add(event)
    db.commit()
    
    return {"message": "Bot started successfully"}

@app.post("/api/bot/stop")
async def stop_bot(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    current_settings = get_current_settings(db)
    
    if current_settings.global_trading_status == "STOPPED":
        raise HTTPException(status_code=400, detail="Bot is already stopped")
    
    # Update settings
    current_settings.global_trading_status = "STOPPED"
    db.commit()
    
    event = SystemEvent(
        event_type="BOT_STOPPED",
        message="Trading bot stopped",
        level="INFO"
    )
    db.add(event)
    db.commit()
    
    return {"message": "Bot stopped successfully"}

@app.post("/api/bot/pause")
async def pause_bot(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    current_settings = get_current_settings(db)
    
    if current_settings.global_trading_status == "PAUSED":
        raise HTTPException(status_code=400, detail="Bot is already paused")
    
    current_settings.global_trading_status = "PAUSED"
    db.commit()
    
    event = SystemEvent(
        event_type="BOT_PAUSED",
        message="Trading bot paused",
        level="INFO"
    )
    db.add(event)
    db.commit()
    
    return {"message": "Bot paused successfully"}

# Settings Routes
@app.get("/api/settings")
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    settings = get_current_settings(db)
    return {
        "global_trading_mode": settings.global_trading_mode,
        "global_trading_status": settings.global_trading_status,
        "dry_run_enabled": settings.dry_run_enabled,
        "min_market_volume": settings.min_market_volume,
        "max_days_to_resolution": settings.max_days_to_resolution,
        "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
        "max_open_markets": settings.max_open_markets,
        "max_exposure_per_market": settings.max_exposure_per_market,
        "copy_trade_percentage": settings.copy_trade_percentage,
        "max_trade_amount": settings.max_trade_amount,
        "daily_loss_limit": settings.daily_loss_limit,
        "max_trades_per_hour": settings.max_trades_per_hour
    }

@app.post("/api/settings")
async def update_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    data = await request.json()
    current_settings = get_current_settings(db)
    
    # Update settings from request data
    for key, value in data.items():
        if hasattr(current_settings, key):
            setattr(current_settings, key, value)
    
    current_settings.updated_at = datetime.utcnow()
    db.commit()
    
    event = SystemEvent(
        event_type="SETTINGS_UPDATED",
        message="Bot settings updated",
        level="INFO",
        metadata=data
    )
    db.add(event)
    db.commit()
    
    return {"message": "Settings updated successfully"}

# Trade History
@app.get("/api/trades")
async def get_trades(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trades = db.query(FollowerTrade).order_by(FollowerTrade.executed_at.desc()).limit(100).all()
    return [
        {
            "id": trade.id,
            "market_id": trade.market_id,
            "outcome_id": trade.outcome_id,
            "side": trade.side,
            "size": trade.size,
            "price": trade.price,
            "executed_at": trade.executed_at.isoformat(),
            "status": trade.status,
            "pnl": trade.pnl,
            "is_dry_run": trade.is_dry_run,
            "leader_trade": {
                "wallet_nickname": trade.leader_trade.wallet.nickname if trade.leader_trade else "Unknown"
            } if trade.leader_trade else None
        }
        for trade in trades
    ]

# System Events
@app.get("/api/events")
async def get_events(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    events = db.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(100).all()
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "message": event.message,
            "level": event.level,
            "created_at": event.created_at.isoformat(),
            "metadata": event.metadata
        }
        for event in events
    ]

# Health check
@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        # Test database connection
        db.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}
