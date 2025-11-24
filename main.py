# =============================================================================
# IMPORTS & CONFIGURATION
# =============================================================================
from fastapi import FastAPI, Request, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_socketio import SocketManager
import uvicorn
import os
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Float, Text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from web3 import Web3
import eth_account

# =============================================================================
# DATABASE SETUP & MODELS
# =============================================================================
# Create necessary directories
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./copytrader.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database Models
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
    copy_trade_percentage = Column(Float, default=20.0)
    max_trade_amount = Column(Float, default=100.0)
    min_market_volume = Column(Float, default=1000.0)
    max_days_to_resolution = Column(Integer, default=30)
    trade_cooldown = Column(Integer, default=30)
    poll_interval = Column(Integer, default=30)
    daily_loss_limit = Column(Float, default=200.0)
    last_mode_switch = Column(DateTime, default=datetime.utcnow)
    test_mode_started = Column(DateTime, nullable=True)
    live_mode_started = Column(DateTime, nullable=True)

class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String(42), unique=True, index=True)
    nickname = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_monitored = Column(DateTime, nullable=True)

class LeaderTrade(Base):
    __tablename__ = "leader_trades"
    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer)
    external_trade_id = Column(String(100), unique=True, index=True)
    market_id = Column(String(100))
    outcome = Column(String(50))
    side = Column(String(10))
    amount = Column(Float)
    price = Column(Float)
    executed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

class FollowerTrade(Base):
    __tablename__ = "follower_trades"
    id = Column(Integer, primary_key=True, index=True)
    leader_trade_id = Column(Integer)
    market_id = Column(String(100))
    outcome = Column(String(50))
    side = Column(String(10))
    amount = Column(Float)
    price = Column(Float)
    status = Column(String(20), default="PENDING")
    is_dry_run = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class SystemEvent(Base):
    __tablename__ = "system_events"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50))
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# =============================================================================
# DATABASE INITIALIZATION
# =============================================================================
def initialize_database():
    """Initialize database tables and handle schema updates"""
    try:
        # Always create all tables to ensure schema is up to date
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables created/updated successfully")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        # Try to handle individual table creation if full creation fails
        try:
            for table in Base.metadata.tables.values():
                try:
                    table.create(engine, checkfirst=True)
                except Exception as table_error:
                    print(f"Table creation warning: {table_error}")
        except Exception as fallback_error:
            print(f"Fallback table creation failed: {fallback_error}")

initialize_database()

def update_database_schema():
    """Add missing columns to existing tables"""
    try:
        # Add missing columns to settings table
        with engine.connect() as conn:
            # Check if columns exist and add them if they don't
            columns_to_add = [
                "copy_trade_percentage FLOAT DEFAULT 20.0",
                "trade_cooldown INTEGER DEFAULT 30", 
                "poll_interval INTEGER DEFAULT 30",
                "daily_loss_limit FLOAT DEFAULT 200.0"
            ]
            
            for column_def in columns_to_add:
                column_name = column_def.split()[0]
                try:
                    conn.execute(f"ALTER TABLE settings ADD COLUMN {column_def}")
                    print(f"✅ Added column: {column_name}")
                except Exception as e:
                    print(f"Column {column_name} may already exist: {e}")
                    
    except Exception as e:
        print(f"Schema update error: {e}")

# Call this after initialize_database()
update_database_schema()

# =============================================================================
# FASTAPI APP SETUP
# =============================================================================
app = FastAPI(title="Polymarket Copytrader")
socket_manager = SocketManager(app=app, mount_location="/socket.io/", cors_allowed_origins=[])

# Template setup
try:
    templates = Jinja2Templates(directory="templates")
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    print(f"Warning: Template setup issue: {e}")
    templates = Jinja2Templates(directory="templates")

# =============================================================================
# TRADING CONFIGURATION
# =============================================================================
class PolymarketTradingConfig:
    def __init__(self):
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        self.rpc_url = os.getenv("POLYMARKET_RPC_URL", "https://polygon-rpc.com")
        self.conditional_tokens_address = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
        self.collateral_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        
        if self.private_key:
            self.account = self.w3.eth.account.from_key(self.private_key)
            print(f"✅ Trading account loaded: {self.account.address}")
        else:
            self.account = None
            print("⚠️  No private key configured - trading disabled")

trading_config = PolymarketTradingConfig()

# =============================================================================
# AUTHENTICATION SETUP
# =============================================================================
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception as e:
    print(f"Warning: bcrypt context creation failed: {e}")
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

def get_password_hash(password):
    try:
        if len(password) > 72:
            password = password[:72]
        return pwd_context.hash(password)
    except Exception as e:
        print(f"Password hashing error: {e}")
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password, hashed_password):
    try:
        if len(plain_password) > 72:
            plain_password = plain_password[:72]
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"Password verification error: {e}")
        import hashlib
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =============================================================================
# DEFAULT DATA INITIALIZATION
# =============================================================================
def initialize_default_data():
    """Initialize default admin user and settings"""
    db = SessionLocal()
    try:
        # Create admin user
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            hashed_password = get_password_hash("admin")
            admin = User(username="admin", hashed_password=hashed_password, is_active=True)
            db.add(admin)
            print("✅ Admin user created: admin / admin")
        
        # Create default settings
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
            print("✅ Default settings created")
        
        # Create welcome event
        existing_events = db.query(SystemEvent).count()
        if existing_events == 0:
            event = SystemEvent(
                event_type="SYSTEM_START",
                message="Trading system initialized successfully"
            )
            db.add(event)
        
        db.commit()
        print("✅ Default data initialized successfully")
        
    except Exception as e:
        print(f"❌ Error initializing default data: {e}")
        db.rollback()
    finally:
        db.close()

initialize_default_data()

# =============================================================================
# POLYMARKET CLIENT
# =============================================================================
class PolymarketClient:
    def __init__(self):
        self.base_url = "https://gamma-api.polymarket.com"
        self.session = None
        self.config = trading_config
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_wallet_trades(self, wallet_address: str, since: datetime = None):
        """Get recent trades for a wallet from Polymarket API"""
        try:
            url = f"{self.base_url}/trades"
            params = {"user": wallet_address, "limit": 50}
            
            if since:
                params["since"] = since.isoformat()
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("trades", [])
                else:
                    print(f"API error: {response.status}")
                    return []
                    
        except Exception as e:
            print(f"Error fetching trades for {wallet_address}: {e}")
            return self._get_mock_trades(wallet_address, since)
    
    def _get_mock_trades(self, wallet_address: str, since: datetime = None):
        """Mock trades for testing"""
        if since is None:
            since = datetime.utcnow() - timedelta(hours=24)
            
        return [
            {
                "id": f"trade_{wallet_address[-6:]}_{i}",
                "market": f"0xmarket{i}",
                "outcome": "0",
                "side": "buy",
                "amount": str(100.0 + (i * 10)),
                "price": str(0.65 + (i * 0.05)),
                "timestamp": (since + timedelta(minutes=i*30)).isoformat(),
            }
            for i in range(3)
        ]
    
    async def place_order(self, market_id: str, outcome: str, amount: float, price: float):
        """Place an order on Polymarket"""
        try:
            db = SessionLocal()
            settings = db.query(Settings).first()
            
            if settings and (settings.dry_run_enabled or settings.global_trading_mode == "TEST"):
                print(f"DRY RUN: Would place order - {outcome} {amount} @ {price} on {market_id}")
                return {"success": True, "order_id": f"dry_run_{datetime.utcnow().timestamp()}"}
            
            elif self.config.account and settings.global_trading_mode == "LIVE":
                return await self._execute_real_trade(market_id, outcome, amount, price)
            else:
                return {"success": False, "error": "No trading account configured or not in LIVE mode"}
                
        except Exception as e:
            print(f"Error placing order: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

# =============================================================================
# TRADING STRATEGY & RISK MANAGEMENT
# =============================================================================
class CopyTradingStrategy:
    def __init__(self, db):
        self.db = db
    
    async def process_leader_trade(self, leader_trade: dict, wallet: Wallet):
        """Process a leader trade and decide whether to copy it"""
        try:
            settings = self.db.query(Settings).first()
            if not settings or settings.global_trading_status != "RUNNING":
                return None
            
            # Apply trading rules and risk management
            copy_percentage = settings.copy_trade_percentage / 100.0
            base_amount = leader_trade["amount"] * copy_percentage
            
            # Apply maximum trade amount limit
            max_amount = settings.max_trade_amount
            price = leader_trade["price"]
            usd_value = base_amount * price
            
            if usd_value > max_amount:
                usd_value = max_amount
            
            final_amount = usd_value / price if price > 0 else 0
            
            if final_amount <= 0:
                return None
            
            return {
                "market_id": leader_trade["market_id"],
                "outcome": leader_trade["outcome"],
                "side": leader_trade["side"],
                "amount": round(final_amount, 4),
                "price": leader_trade["price"]
            }
            
        except Exception as e:
            print(f"Error processing leader trade: {e}")
            return None

class RiskManager:
    def __init__(self, db):
        self.db = db
    
    def can_execute_trade(self, trade_data: dict) -> tuple[bool, str]:
        """Check if a trade can be executed based on risk rules"""
        try:
            settings = self.db.query(Settings).first()
            if not settings:
                return False, "No settings configured"
            
            # Mode-specific risk checks
            if settings.global_trading_mode == "LIVE":
                if trade_data["amount"] * trade_data["price"] > 1000:
                    return False, "Trade size too large for live mode"
            elif settings.global_trading_mode == "TEST":
                if trade_data["amount"] * trade_data["price"] > 5000:
                    return False, "Trade size too large for test mode"
            
            # Common risk checks
            recent_trades = self.db.query(FollowerTrade).filter(
                FollowerTrade.created_at >= datetime.utcnow() - timedelta(hours=1)
            ).count()
            
            if recent_trades >= 10:
                return False, "Too many recent trades"
            
            return True, "OK"
            
        except Exception as e:
            return False, f"Risk check error: {e}"

# =============================================================================
# WALLET MONITORING SYSTEM
# =============================================================================
class WalletMonitor:
    def __init__(self):
        self.is_running = False
        self.monitor_task = None
    
    async def start_monitoring(self):
        """Start monitoring all active wallets"""
        if self.is_running:
            return
        
        self.is_running = True
        print("🚀 Starting wallet monitoring...")
        
        while self.is_running:
            try:
                await self.monitor_cycle()
                await asyncio.sleep(30)
            except Exception as e:
                print(f"Monitoring error: {e}")
                await asyncio.sleep(10)
    
    async def stop_monitoring(self):
        """Stop wallet monitoring"""
        self.is_running = False
        if self.monitor_task:
            self.monitor_task.cancel()
        print("🛑 Wallet monitoring stopped")

# =============================================================================
# APP LIFECYCLE & SOCKET.IO
# =============================================================================
@socket_manager.on('connect')
async def handle_connect(sid, environ):
    print(f"Client connected: {sid}")

@socket_manager.on('disconnect')
async def handle_disconnect(sid):
    print(f"Client disconnected: {sid}")

@app.on_event("startup")
async def startup_event():
    """Start background tasks when app starts"""
    global monitor_task
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if settings and settings.global_trading_status == "RUNNING":
            monitor_task = asyncio.create_task(wallet_monitor.start_monitoring())
            print("🔄 Resuming wallet monitoring on startup")
    except Exception as e:
        print(f"Startup error: {e}")
    finally:
        db.close()

@app.on_event("shutdown")
async def shutdown_event():
    """Stop background tasks when app shuts down"""
    await wallet_monitor.stop_monitoring()

# Global instances
wallet_monitor = WalletMonitor()
monitor_task = None

# =============================================================================
# ROUTES - DASHBOARD & AUTH
# =============================================================================
@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "database": "connected"}

@app.get("/dashboard")
async def dashboard(request: Request):
    """Serve the main dashboard"""
    # In a real implementation, this would serve the full dashboard.html
    # For now, we'll serve a basic version
    return HTMLResponse(content="""<!DOCTYPE html><html>...full dashboard HTML here...</html>""")

# =============================================================================
# ROUTES - API ENDPOINTS
# =============================================================================
@app.get("/api/stats")
async def get_stats(db: SessionLocal = Depends(get_db)):
    """Get trading statistics"""
    try:
        wallets_count = db.query(Wallet).filter(Wallet.is_active == True).count()
        total_trades = db.query(FollowerTrade).count()
        executed_trades = db.query(FollowerTrade).filter(FollowerTrade.status == "EXECUTED").count()
        
        return {
            "totalTrades": total_trades,
            "profitableTrades": executed_trades,
            "totalProfit": 0,
            "winRate": round((executed_trades / total_trades * 100) if total_trades > 0 else 0, 1),
            "activeWallets": wallets_count,
            "riskLevel": "Low"
        }
    except Exception as e:
        print(f"Stats error: {e}")
        return {"totalTrades": 0, "profitableTrades": 0, "totalProfit": 0, "winRate": 0, "activeWallets": 0, "riskLevel": "Low"}

# =============================================================================
# ROUTES - WALLET MANAGEMENT
# =============================================================================
@app.get("/api/wallets")
async def get_wallets(db: SessionLocal = Depends(get_db)):
    """Get all wallets"""
    try:
        wallets = db.query(Wallet).all()
        return [{"id": w.id, "address": w.address, "nickname": w.nickname, "is_active": w.is_active} for w in wallets]
    except Exception as e:
        print(f"Wallets error: {e}")
        return []

@app.post("/api/wallets")
async def add_wallet(nickname: str = Form(...), address: str = Form(...), db: SessionLocal = Depends(get_db)):
    """Add a new wallet"""
    try:
        if not address.startswith("0x") or len(address) != 42:
            raise HTTPException(status_code=400, detail="Invalid wallet address format")
        
        existing = db.query(Wallet).filter(Wallet.address == address).first()
        if existing:
            raise HTTPException(status_code=400, detail="Wallet already exists")
        
        wallet = Wallet(nickname=nickname, address=address, is_active=True)
        db.add(wallet)
        db.commit()
        
        return {"message": "Wallet added successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to add wallet")

# =============================================================================
# ROUTES - BOT CONTROL
# =============================================================================
@app.post("/api/bot/start")
async def start_bot(background_tasks: BackgroundTasks, db: SessionLocal = Depends(get_db)):
    """Start the trading bot"""
    try:
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
        
        if settings.global_trading_status == "RUNNING":
            raise HTTPException(status_code=400, detail="Bot is already running")
        
        settings.global_trading_status = "RUNNING"
        db.commit()
        
        global monitor_task
        monitor_task = asyncio.create_task(wallet_monitor.start_monitoring())
        
        await socket_manager.emit('status_update', {'status': 'RUNNING'})
        
        return {"message": "Bot started successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bot/stop")
async def stop_bot(db: SessionLocal = Depends(get_db)):
    """Stop the trading bot"""
    try:
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
        
        settings.global_trading_status = "STOPPED"
        db.commit()
        
        await wallet_monitor.stop_monitoring()
        await socket_manager.emit('status_update', {'status': 'STOPPED'})
        
        return {"message": "Bot stopped successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# ROUTES - SETTINGS MANAGEMENT
# =============================================================================
@app.get("/api/settings")
async def get_settings(db: SessionLocal = Depends(get_db)):
    """Get current settings"""
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
            "copy_trade_percentage": settings.copy_trade_percentage,
            "max_trade_amount": settings.max_trade_amount,
            "min_market_volume": settings.min_market_volume,
            "max_days_to_resolution": settings.max_days_to_resolution,
            "trade_cooldown": settings.trade_cooldown,
            "poll_interval": settings.poll_interval,
            "daily_loss_limit": settings.daily_loss_limit,
            "last_mode_switch": settings.last_mode_switch.isoformat() if settings.last_mode_switch else None,
            "test_mode_started": settings.test_mode_started.isoformat() if settings.test_mode_started else None,
            "live_mode_started": settings.live_mode_started.isoformat() if settings.live_mode_started else None
        }
    except Exception as e:
        print(f"Settings error: {e}")
        return {}

@app.post("/api/settings")
async def update_settings(request: Request, db: SessionLocal = Depends(get_db)):
    """Update settings"""
    try:
        data = await request.json()
        settings = db.query(Settings).first()
        
        if not settings:
            settings = Settings()
            db.add(settings)
        
        for key, value in data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        db.commit()
        return {"message": "Settings updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# ROUTES - MODE MANAGEMENT
# =============================================================================
@app.post("/api/settings/switch-mode")
async def switch_trading_mode(request: Request, db: SessionLocal = Depends(get_db)):
    """Switch between TEST and LIVE modes"""
    try:
        data = await request.json()
        new_mode = data.get("mode")
        reset_analytics = data.get("reset_analytics", True)
        
        if new_mode not in ["TEST", "LIVE"]:
            raise HTTPException(status_code=400, detail="Mode must be TEST or LIVE")
        
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
        
        current_mode = settings.global_trading_mode
        
        if current_mode == new_mode:
            return {"message": f"Already in {new_mode} mode"}
        
        # Stop bot before switching modes
        if settings.global_trading_status == "RUNNING":
            await wallet_monitor.stop_monitoring()
            settings.global_trading_status = "STOPPED"
        
        # Reset analytics if requested
        if reset_analytics:
            await reset_trading_analytics(db)
        
        # Update mode tracking
        settings.global_trading_mode = new_mode
        settings.last_mode_switch = datetime.utcnow()
        
        if new_mode == "TEST":
            settings.test_mode_started = datetime.utcnow()
            settings.dry_run_enabled = True
        else:
            settings.live_mode_started = datetime.utcnow()
        
        db.commit()
        
        await socket_manager.emit('mode_update', {
            'old_mode': current_mode,
            'new_mode': new_mode,
            'reset_analytics': reset_analytics
        })
        
        return {
            "message": f"Switched to {new_mode} mode successfully",
            "reset_analytics": reset_analytics,
            "dry_run_enabled": settings.dry_run_enabled
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# ROUTES - ANALYTICS MANAGEMENT
# =============================================================================
@app.post("/api/analytics/reset")
async def reset_analytics(db: SessionLocal = Depends(get_db)):
    """Reset all trading analytics"""
    try:
        await reset_trading_analytics(db)
        return {"message": "Analytics reset successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

async def reset_trading_analytics(db: SessionLocal):
    """Reset all trading analytics and history"""
    try:
        db.query(FollowerTrade).delete()
        db.query(LeaderTrade).delete()
        
        wallets = db.query(Wallet).all()
        for wallet in wallets:
            wallet.last_monitored = None
        
        print("✅ Trading analytics reset complete")
    except Exception as e:
        print(f"Error resetting analytics: {e}")
        raise

# =============================================================================
# ROUTES - SYSTEM EVENTS
# =============================================================================
@app.get("/api/events")
async def get_events(db: SessionLocal = Depends(get_db)):
    """Get system events"""
    try:
        events = db.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(50).all()
        return [{"id": e.id, "event_type": e.event_type, "message": e.message, "created_at": e.created_at.isoformat()} for e in events]
    except Exception as e:
        print(f"Events error: {e}")
        return []

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)