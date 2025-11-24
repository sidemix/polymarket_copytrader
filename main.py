from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_socketio import SocketManager
import uvicorn
import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Float, Text
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

# Simple models - minimal columns to avoid schema conflicts
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    hashed_password = Column(String(255))
    is_active = Column(Boolean, default=True)

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    global_trading_mode = Column(String(10), default="TEST")
    global_trading_status = Column(String(10), default="STOPPED")
    dry_run_enabled = Column(Boolean, default=True)

class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String(42), unique=True, index=True)
    nickname = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class SystemEvent(Base):
    __tablename__ = "system_events"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50))
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# Drop and recreate all tables to ensure clean schema
try:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("Database tables recreated successfully")
except Exception as e:
    print(f"Error recreating tables: {e}")

# FastAPI app
app = FastAPI(title="Polymarket Copytrader")

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

def initialize_database():
    db = SessionLocal()
    try:
        # Create admin user
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            hashed_password = get_password_hash("1234")
            admin = User(username="admin", hashed_password=hashed_password, is_active=True)
            db.add(admin)
            print("Admin user created: admin / 1234")
        
        # Create default settings
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
            print("Default settings created")
        
        # Create welcome event
        event = SystemEvent(
            event_type="SYSTEM_START",
            message="Trading system initialized successfully"
        )
        db.add(event)
        
        db.commit()
        print("Database initialized successfully")
        
    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
    finally:
        db.close()

initialize_database()

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
        return RedirectResponse(url="/dashboard", status_code=303)
    finally:
        db.close()

@app.get("/dashboard")
async def dashboard(request: Request):
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
            db.commit()
        
        # Get wallets count
        wallets_count = db.query(Wallet).filter(Wallet.is_active == True).count()
        
        # Get recent events
        recent_events = db.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(10).all()
        
        # Get wallets
        wallets = db.query(Wallet).filter(Wallet.is_active == True).all()
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "settings": settings,
            "stats": {
                "total_trades": 0,
                "profitable_trades": 0,
                "total_profit": 0,
                "win_rate": 0,
                "active_wallets": wallets_count,
                "risk_level": "Low"
            },
            "recent_events": recent_events,
            "wallets": wallets
        })
    except Exception as e:
        print(f"Dashboard error: {e}")
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "settings": Settings(),
            "stats": {
                "total_trades": 0,
                "profitable_trades": 0,
                "total_profit": 0,
                "win_rate": 0,
                "active_wallets": 0,
                "risk_level": "Low"
            },
            "recent_events": [],
            "wallets": []
        })
    finally:
        db.close()

# API Routes
@app.get("/api/stats")
async def get_stats(db: SessionLocal = Depends(get_db)):
    try:
        wallets_count = db.query(Wallet).filter(Wallet.is_active == True).count()
        return {
            "totalTrades": 0,
            "profitableTrades": 0,
            "totalProfit": 0,
            "winRate": 0,
            "activeWallets": wallets_count,
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
        wallets = db.query(Wallet).all()
        return [
            {
                "id": wallet.id,
                "address": wallet.address,
                "nickname": wallet.nickname,
                "is_active": wallet.is_active,
                "created_at": wallet.created_at.isoformat() if wallet.created_at else None
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
        
        # Check if wallet already exists
        existing = db.query(Wallet).filter(Wallet.address == address).first()
        if existing:
            raise HTTPException(status_code=400, detail="Wallet already exists")
        
        # Create new wallet
        wallet = Wallet(
            nickname=nickname,
            address=address,
            is_active=True
        )
        db.add(wallet)
        
        # Log system event
        event = SystemEvent(
            event_type="WALLET_ADDED",
            message=f"Added new wallet: {nickname} ({address})"
        )
        db.add(event)
        
        db.commit()
        
        return {"message": "Wallet added successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Add wallet error: {e}")
        raise HTTPException(status_code=500, detail="Failed to add wallet")

@app.delete("/api/wallets/{wallet_id}")
async def delete_wallet(wallet_id: int, db: SessionLocal = Depends(get_db)):
    try:
        wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")
        
        db.delete(wallet)
        
        event = SystemEvent(
            event_type="WALLET_REMOVED",
            message=f"Removed wallet: {wallet.nickname}"
        )
        db.add(event)
        
        db.commit()
        
        return {"message": "Wallet deleted successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Delete wallet error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete wallet")

# Bot Control Routes
@app.post("/api/bot/start")
async def start_bot(db: SessionLocal = Depends(get_db)):
    try:
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
        
        settings.global_trading_status = "RUNNING"
        
        event = SystemEvent(
            event_type="BOT_STARTED",
            message="Trading bot started"
        )
        db.add(event)
        
        db.commit()
        
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
        
        settings.global_trading_status = "STOPPED"
        
        event = SystemEvent(
            event_type="BOT_STOPPED",
            message="Trading bot stopped"
        )
        db.add(event)
        
        db.commit()
        
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
        
        settings.global_trading_status = "PAUSED"
        
        event = SystemEvent(
            event_type="BOT_PAUSED",
            message="Trading bot paused"
        )
        db.add(event)
        
        db.commit()
        
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
            "dry_run_enabled": settings.dry_run_enabled
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
        
        event = SystemEvent(
            event_type="SETTINGS_UPDATED",
            message="Bot settings updated"
        )
        db.add(event)
        
        db.commit()
        
        return {"message": "Settings updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

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
                "created_at": event.created_at.isoformat() if event.created_at else None
            }
            for event in events
        ]
    except Exception as e:
        print(f"Events error: {e}")
        return []

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)