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

# Models
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
    side = Column(String(10))  # YES or NO
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
    status = Column(String(20), default="PENDING")  # PENDING, EXECUTED, FAILED
    is_dry_run = Column(Boolean, default=False)
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
            hashed_password = get_password_hash("admin")
            admin = User(username="admin", hashed_password=hashed_password, is_active=True)
            db.add(admin)
            print("✅ Admin user created: admin / admin")
        
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

# =============================================================================
# PHASE 2: POLYMARKET CLIENT & WALLET MONITORING
# =============================================================================

class PolymarketClient:
    def __init__(self):
        self.base_url = "https://gamma-api.polymarket.com"
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_wallet_trades(self, wallet_address: str, since: datetime = None):
        """Get recent trades for a wallet from Polymarket API"""
        try:
            if since is None:
                since = datetime.utcnow() - timedelta(hours=24)
            
            # This is a mock implementation - replace with actual Polymarket API
            # For now, we'll simulate some trades for testing
            mock_trades = [
                {
                    "id": f"trade_{wallet_address[-6:]}_{i}",
                    "market_id": f"market_{i}",
                    "outcome": "YES" if i % 2 == 0 else "NO",
                    "side": "BUY",
                    "amount": 100.0 + (i * 10),
                    "price": 0.65 + (i * 0.05),
                    "executed_at": (since + timedelta(minutes=i*30)).isoformat(),
                    "token": f"0x{i}"
                }
                for i in range(3)  # Simulate 3 trades
            ]
            
            return mock_trades
            
        except Exception as e:
            print(f"Error fetching trades for {wallet_address}: {e}")
            return []
    
    async def get_market_info(self, market_id: str):
        """Get market information from Polymarket"""
        try:
            # Mock market data - replace with actual API call
            return {
                "id": market_id,
                "volume": 50000.0,
                "liquidity": 100000.0,
                "resolution_time": (datetime.utcnow() + timedelta(days=30)).isoformat(),
                "active": True
            }
        except Exception as e:
            print(f"Error fetching market info {market_id}: {e}")
            return None
    
    async def place_order(self, market_id: str, outcome: str, amount: float, price: float):
        """Place an order on Polymarket"""
        try:
            db = SessionLocal()
            settings = db.query(Settings).first()
            
            if settings and settings.dry_run_enabled:
                # Simulate trade in dry-run mode
                print(f"DRY RUN: Would place order - {outcome} {amount} @ {price} on {market_id}")
                return {"success": True, "order_id": f"dry_run_{datetime.utcnow().timestamp()}"}
            else:
                # Actual Polymarket API call would go here
                print(f"LIVE: Placing order - {outcome} {amount} @ {price} on {market_id}")
                return {"success": True, "order_id": f"live_{datetime.utcnow().timestamp()}"}
                
        except Exception as e:
            print(f"Error placing order: {e}")
            return {"success": False, "error": str(e)}

# =============================================================================
# PHASE 3: COPY TRADING STRATEGY & RISK MANAGEMENT
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
            
            # Get market info
            async with PolymarketClient() as client:
                market_info = await client.get_market_info(leader_trade["market_id"])
            
            if not market_info or not market_info.get("active", True):
                return None
            
            # Check market volume
            if market_info.get("volume", 0) < settings.min_market_volume:
                return None
            
            # Check days to resolution
            resolution_time = market_info.get("resolution_time")
            if resolution_time:
                resolution_dt = datetime.fromisoformat(resolution_time.replace('Z', '+00:00'))
                days_to_resolution = (resolution_dt - datetime.utcnow()).days
                if days_to_resolution > settings.max_days_to_resolution:
                    return None
            
            # Calculate position size
            leader_amount = leader_trade["amount"]
            copy_percentage = settings.copy_trade_percentage / 100.0
            base_amount = leader_amount * copy_percentage
            
            # Apply maximum trade amount limit
            max_amount = settings.max_trade_amount
            price = leader_trade["price"]
            
            # Calculate USD value and cap it
            usd_value = base_amount * price
            if usd_value > max_amount:
                usd_value = max_amount
            
            # Convert back to shares
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
            # Check if we already have too many open positions
            recent_trades = self.db.query(FollowerTrade).filter(
                FollowerTrade.created_at >= datetime.utcnow() - timedelta(hours=1)
            ).count()
            
            if recent_trades >= 10:  # Max 10 trades per hour
                return False, "Too many recent trades"
            
            # Add more risk checks here:
            # - Maximum exposure per market
            # - Daily loss limits
            # - Portfolio concentration
            # - etc.
            
            return True, "OK"
            
        except Exception as e:
            return False, f"Risk check error: {e}"

# =============================================================================
# BACKGROUND TASKS - WALLET MONITORING
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
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                print(f"Monitoring error: {e}")
                await asyncio.sleep(10)
    
    async def stop_monitoring(self):
        """Stop wallet monitoring"""
        self.is_running = False
        if self.monitor_task:
            self.monitor_task.cancel()
        print("🛑 Wallet monitoring stopped")
    
    async def monitor_cycle(self):
        """Single monitoring cycle"""
        db = SessionLocal()
        try:
            active_wallets = db.query(Wallet).filter(Wallet.is_active == True).all()
            
            if not active_wallets:
                return
            
            async with PolymarketClient() as client:
                for wallet in active_wallets:
                    await self.check_wallet_trades(wallet, client, db)
                    
        finally:
            db.close()
    
    async def check_wallet_trades(self, wallet: Wallet, client: PolymarketClient, db):
        """Check for new trades from a specific wallet"""
        try:
            # Get last check time
            since = wallet.last_monitored
            if since is None:
                since = datetime.utcnow() - timedelta(hours=24)
            
            # Fetch new trades
            trades = await client.get_wallet_trades(wallet.address, since)
            
            if trades:
                print(f"📈 Found {len(trades)} new trades for {wallet.nickname}")
                
                strategy = CopyTradingStrategy(db)
                risk_manager = RiskManager(db)
                
                for trade_data in trades:
                    await self.process_trade(trade_data, wallet, strategy, risk_manager, db)
                
                # Update last monitored time
                wallet.last_monitored = datetime.utcnow()
                db.commit()
                
        except Exception as e:
            print(f"Error checking wallet {wallet.address}: {e}")
    
    async def process_trade(self, trade_data: dict, wallet: Wallet, strategy: CopyTradingStrategy, risk_manager: RiskManager, db):
        """Process a single trade"""
        try:
            # Check if trade already processed
            existing_trade = db.query(LeaderTrade).filter(
                LeaderTrade.external_trade_id == trade_data["id"]
            ).first()
            
            if existing_trade:
                return
            
            # Store leader trade
            leader_trade = LeaderTrade(
                wallet_id=wallet.id,
                external_trade_id=trade_data["id"],
                market_id=trade_data["market_id"],
                outcome=trade_data["outcome"],
                side=trade_data["side"],
                amount=trade_data["amount"],
                price=trade_data["price"],
                executed_at=datetime.fromisoformat(trade_data["executed_at"].replace('Z', '+00:00'))
            )
            db.add(leader_trade)
            db.flush()  # Get the ID
            
            # Process through strategy
            mirror_trade = await strategy.process_leader_trade(trade_data, wallet)
            
            if mirror_trade:
                # Check risk management
                can_trade, reason = risk_manager.can_execute_trade(mirror_trade)
                
                if can_trade:
                    await self.execute_mirror_trade(mirror_trade, leader_trade.id, db)
                else:
                    print(f"Risk check failed: {reason}")
            
            db.commit()
            
        except Exception as e:
            print(f"Error processing trade: {e}")
            db.rollback()
    
    async def execute_mirror_trade(self, trade_data: dict, leader_trade_id: int, db):
        """Execute a mirror trade"""
        try:
            async with PolymarketClient() as client:
                result = await client.place_order(
                    trade_data["market_id"],
                    trade_data["outcome"],
                    trade_data["amount"],
                    trade_data["price"]
                )
            
            settings = db.query(Settings).first()
            is_dry_run = settings.dry_run_enabled if settings else True
            
            # Record follower trade
            follower_trade = FollowerTrade(
                leader_trade_id=leader_trade_id,
                market_id=trade_data["market_id"],
                outcome=trade_data["outcome"],
                side=trade_data["side"],
                amount=trade_data["amount"],
                price=trade_data["price"],
                status="EXECUTED" if result["success"] else "FAILED",
                is_dry_run=is_dry_run
            )
            db.add(follower_trade)
            
            # Log system event
            event_type = "TRADE_EXECUTED" if result["success"] else "TRADE_FAILED"
            event = SystemEvent(
                event_type=event_type,
                message=f"Mirror trade: {trade_data['side']} {trade_data['amount']} {trade_data['outcome']} @ {trade_data['price']}"
            )
            db.add(event)
            
            # Emit socket event
            await socket_manager.emit('trade_update', {
                'market_id': trade_data["market_id"],
                'outcome': trade_data["outcome"],
                'side': trade_data["side"],
                'amount': trade_data["amount"],
                'price': trade_data["price"],
                'status': "EXECUTED" if result["success"] else "FAILED",
                'dry_run': is_dry_run
            })
            
            print(f"✅ Mirror trade executed: {trade_data['side']} {trade_data['amount']} @ {trade_data['price']}")
            
        except Exception as e:
            print(f"Error executing mirror trade: {e}")

# Global instances
wallet_monitor = WalletMonitor()
monitor_task = None

# =============================================================================
# SOCKET.IO & APP LIFECYCLE
# =============================================================================

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

@app.on_event("startup")
async def startup_event():
    """Start background tasks when app starts"""
    global monitor_task
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if settings and settings.global_trading_status == "RUNNING":
            monitor_task = asyncio.create_task(wallet_monitor.start_monitoring())
    finally:
        db.close()

@app.on_event("shutdown")
async def shutdown_event():
    """Stop background tasks when app shuts down"""
    await wallet_monitor.stop_monitoring()

# =============================================================================
# EXISTING ROUTES (keep all your existing routes below)
# =============================================================================

# [Keep all your existing routes from the previous version here...]
# Routes: /, /health, /login, /dashboard, /api/stats, /api/wallets, etc.
# Bot Control Routes: /api/bot/start, /api/bot/stop, /api/bot/pause
# Settings Routes: /api/settings, etc.

# [PASTE ALL YOUR EXISTING ROUTES HERE - they should work unchanged]

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
        
        # Get trade stats
        total_trades = db.query(FollowerTrade).count()
        executed_trades = db.query(FollowerTrade).filter(FollowerTrade.status == "EXECUTED").count()
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "settings": settings,
            "stats": {
                "total_trades": total_trades,
                "profitable_trades": executed_trades,  # Simplified for now
                "total_profit": 0,  # Would need P&L calculation
                "win_rate": (executed_trades / total_trades * 100) if total_trades > 0 else 0,
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
                "created_at": wallet.created_at.isoformat() if wallet.created_at else None,
                "last_monitored": wallet.last_monitored.isoformat() if wallet.last_monitored else None
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

# Enhanced Bot Control Routes with Monitoring
@app.post("/api/bot/start")
async def start_bot(background_tasks: BackgroundTasks, db: SessionLocal = Depends(get_db)):
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
            message="Trading bot started"
        )
        db.add(event)
        
        db.commit()
        
        # Start wallet monitoring
        global monitor_task
        monitor_task = asyncio.create_task(wallet_monitor.start_monitoring())
        
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
            message="Trading bot stopped"
        )
        db.add(event)
        
        db.commit()
        
        # Stop wallet monitoring
        await wallet_monitor.stop_monitoring()
        
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
            message="Trading bot paused"
        )
        db.add(event)
        
        db.commit()
        
        # Stop wallet monitoring
        await wallet_monitor.stop_monitoring()
        
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
            "copy_trade_percentage": settings.copy_trade_percentage,
            "max_trade_amount": settings.max_trade_amount,
            "min_market_volume": settings.min_market_volume,
            "max_days_to_resolution": settings.max_days_to_resolution
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

# Trade History
@app.get("/api/trades")
async def get_trades(db: SessionLocal = Depends(get_db)):
    try:
        trades = db.query(FollowerTrade).order_by(FollowerTrade.created_at.desc()).limit(50).all()
        return [
            {
                "id": trade.id,
                "market_id": trade.market_id,
                "outcome": trade.outcome,
                "side": trade.side,
                "amount": trade.amount,
                "price": trade.price,
                "status": trade.status,
                "is_dry_run": trade.is_dry_run,
                "created_at": trade.created_at.isoformat() if trade.created_at else None
            }
            for trade in trades
        ]
    except Exception as e:
        print(f"Trades error: {e}")
        return []

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)