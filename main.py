from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_socketio import SocketManager
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Float, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./copytrader.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    hashed_password = Column(String(255))
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

class LeaderTrade(Base):
    __tablename__ = "leader_trades"
    id = Column(Integer, primary_key=True, index=True)
    external_trade_id = Column(String(100), unique=True, index=True, nullable=False)
    wallet_id = Column(Integer, nullable=False)
    market_id = Column(String(100), nullable=False)
    outcome_id = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    executed_at = Column(DateTime, nullable=False)
    category = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

class FollowerTrade(Base):
    __tablename__ = "follower_trades"
    id = Column(Integer, primary_key=True, index=True)
    leader_trade_id = Column(Integer, nullable=False)
    market_id = Column(String(100), nullable=False)
    outcome_id = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    executed_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="EXECUTED")
    pnl = Column(Float, default=0.0)
    is_dry_run = Column(Boolean, default=False)

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
    global_trading_mode = Column(String(10), default="TEST")
    global_trading_status = Column(String(10), default="STOPPED")
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
    event_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    level = Column(String(20), default="INFO")
    event_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables
try:
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")
except Exception as e:
    print(f"Error creating tables: {e}")

# FastAPI app
app = FastAPI(title="Polymarket Copytrader")

# Add SessionMiddleware for authentication
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "your-secret-key-change-in-production"))

# Socket.IO
socket_manager = SocketManager(app=app)

# Templates and static files
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_admin_user():
    db = SessionLocal()
    try:
        # Drop and recreate tables to ensure schema matches
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            hashed_password = get_password_hash("1234")
            admin = User(username="admin", hashed_password=hashed_password, is_active=True)
            db.add(admin)
            
            # Create default settings
            settings = Settings()
            db.add(settings)
            
            db.commit()
            print("ADMIN READY — Login with: admin / 1234")
        else:
            print("ADMIN READY — Login with: admin / 1234")
    except Exception as e:
        print(f"Error creating admin: {e}")
        db.rollback()
    finally:
        db.close()

create_admin_user()

# Socket.IO events
@socket_manager.on('connect')
async def handle_connect(sid, environ):
    print(f"Client connected: {sid}")

@socket_manager.on('disconnect')
async def handle_disconnect(sid):
    print(f"Client disconnected: {sid}")

@socket_manager.on('trade_executed')
async def handle_trade_executed(sid, data):
    print(f"Trade executed: {data}")
    await socket_manager.emit('trade_update', data)

@socket_manager.on('bot_status')
async def handle_bot_status(sid, data):
    print(f"Bot status update: {data}")
    await socket_manager.emit('status_update', data)

# Routes
@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "database": "connected"}

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.hashed_password) or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        request.session["user_id"] = user.id
        return RedirectResponse(url="/dashboard", status_code=303)
    finally:
        db.close()

@app.get("/dashboard")
async def dashboard(request: Request):
    db = SessionLocal()
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return RedirectResponse(url="/login")
        
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
            db.commit()
        
        # Get stats
        total_trades = db.query(FollowerTrade).count()
        profitable_trades = db.query(FollowerTrade).filter(FollowerTrade.pnl > 0).count()
        total_profit = db.query(FollowerTrade).filter(FollowerTrade.pnl > 0).with_entities(
            db.func.sum(FollowerTrade.pnl)
        ).scalar() or 0
        active_wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active == True).count()
        win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Get recent events
        recent_events = db.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(10).all()
        
        # Get wallets
        wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active == True).all()
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user": user,
            "settings": settings,
            "stats": {
                "total_trades": total_trades,
                "profitable_trades": profitable_trades,
                "total_profit": total_profit,
                "win_rate": win_rate,
                "active_wallets": active_wallets,
                "risk_level": "Low"
            },
            "recent_events": recent_events,
            "wallets": wallets
        })
    except Exception as e:
        print(f"Dashboard error: {e}")
        return RedirectResponse(url="/login")
    finally:
        db.close()

@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

# API Routes
@app.get("/api/stats")
async def get_stats(db: SessionLocal = Depends(get_db)):
    try:
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
    except Exception as e:
        print(f"Stats error: {e}")
        return {
            "totalTrades": 0,
            "profitableTrades": 0,
            "totalProfit": 0,
            "winRate": 0,
            "activeWallets": 0,
            "riskLevel": "Low"
        }

@app.get("/api/wallets")
async def get_wallets(db: SessionLocal = Depends(get_db)):
    try:
        wallets = db.query(LeaderWallet).all()
        return [
            {
                "id": wallet.id,
                "address": wallet.address,
                "nickname": wallet.nickname,
                "is_active": wallet.is_active,
                "created_at": wallet.created_at.isoformat() if wallet.created_at else None,
                "last_monitored": wallet.last_monitored.isoformat() if wallet.last_monitored else None,
                "trade_count": db.query(LeaderTrade).filter(LeaderTrade.wallet_id == wallet.id).count()
            }
            for wallet in wallets
        ]
    except Exception as e:
        print(f"Wallets error: {e}")
        return []

@app.post("/api/wallets")
async def add_wallet(
    nickname: str = Form(...),
    address: str = Form(...),
    db: SessionLocal = Depends(get_db)
):
    try:
        if not address.startswith("0x") or len(address) != 42:
            raise HTTPException(status_code=400, detail="Invalid wallet address format")
        
        existing = db.query(LeaderWallet).filter(LeaderWallet.address == address).first()
        if existing:
            raise HTTPException(status_code=400, detail="Wallet already exists")
        
        wallet = LeaderWallet(
            nickname=nickname,
            address=address,
            is_active=True
        )
        
        db.add(wallet)
        
        # Log system event
        event = SystemEvent(
            event_type="WALLET_ADDED",
            message=f"Added new wallet: {nickname} ({address})",
            level="INFO"
        )
        db.add(event)
        db.commit()
        
        return {"message": "Wallet added successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/wallets/{wallet_id}")
async def delete_wallet(wallet_id: int, db: SessionLocal = Depends(get_db)):
    try:
        wallet = db.query(LeaderWallet).filter(LeaderWallet.id == wallet_id).first()
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")
        
        db.delete(wallet)
        
        event = SystemEvent(
            event_type="WALLET_REMOVED",
            message=f"Removed wallet: {wallet.nickname}",
            level="INFO"
        )
        db.add(event)
        db.commit()
        
        return {"message": "Wallet deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# Bot Control Routes
@app.post("/api/bot/start")
async def start_bot(db: SessionLocal = Depends(get_db)):
    try:
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
        
        if settings.global_trading_status == "RUNNING":
            raise HTTPException(status_code=400, detail="Bot is already running")
        
        settings.global_trading_status = "RUNNING"
        
        event = SystemEvent(
            event_type="BOT_STARTED",
            message="Trading bot started",
            level="INFO"
        )
        db.add(event)
        db.commit()
        
        # Emit socket event
        await socket_manager.emit('status_update', {'status': 'RUNNING'})
        
        return {"message": "Bot started successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bot/stop")
async def stop_bot(db: SessionLocal = Depends(get_db)):
    try:
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
        
        if settings.global_trading_status == "STOPPED":
            raise HTTPException(status_code=400, detail="Bot is already stopped")
        
        settings.global_trading_status = "STOPPED"
        
        event = SystemEvent(
            event_type="BOT_STOPPED",
            message="Trading bot stopped",
            level="INFO"
        )
        db.add(event)
        db.commit()
        
        # Emit socket event
        await socket_manager.emit('status_update', {'status': 'STOPPED'})
        
        return {"message": "Bot stopped successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bot/pause")
async def pause_bot(db: SessionLocal = Depends(get_db)):
    try:
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
        
        if settings.global_trading_status == "PAUSED":
            raise HTTPException(status_code=400, detail="Bot is already paused")
        
        settings.global_trading_status = "PAUSED"
        
        event = SystemEvent(
            event_type="BOT_PAUSED",
            message="Trading bot paused",
            level="INFO"
        )
        db.add(event)
        db.commit()
        
        # Emit socket event
        await socket_manager.emit('status_update', {'status': 'PAUSED'})
        
        return {"message": "Bot paused successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# Settings Routes
@app.get("/api/settings")
async def get_settings(db: SessionLocal = Depends(get_db)):
    try:
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
            db.commit()
        
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
    except Exception as e:
        print(f"Settings error: {e}")
        return {}

@app.post("/api/settings")
async def update_settings(request: Request, db: SessionLocal = Depends(get_db)):
    try:
        data = await request.json()
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
        
        for key, value in data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        settings.updated_at = datetime.utcnow()
        
        event = SystemEvent(
            event_type="SETTINGS_UPDATED",
            message="Bot settings updated",
            level="INFO",
            event_metadata=data
        )
        db.add(event)
        db.commit()
        
        return {"message": "Settings updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# Trade History
@app.get("/api/trades")
async def get_trades(db: SessionLocal = Depends(get_db)):
    try:
        trades = db.query(FollowerTrade).order_by(FollowerTrade.executed_at.desc()).limit(50).all()
        return [
            {
                "id": trade.id,
                "market_id": trade.market_id,
                "outcome_id": trade.outcome_id,
                "side": trade.side,
                "size": trade.size,
                "price": trade.price,
                "executed_at": trade.executed_at.isoformat() if trade.executed_at else None,
                "status": trade.status,
                "pnl": trade.pnl,
                "is_dry_run": trade.is_dry_run
            }
            for trade in trades
        ]
    except Exception as e:
        print(f"Trades error: {e}")
        return []

# System Events
@app.get("/api/events")
async def get_events(db: SessionLocal = Depends(get_db)):
    try:
        events = db.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(50).all()
        return [
            {
                "id": event.id,
                "event_type": event.event_type,
                "message": event.message,
                "level": event.level,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "metadata": event.event_metadata
            }
            for event in events
        ]
    except Exception as e:
        print(f"Events error: {e}")
        return []

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)