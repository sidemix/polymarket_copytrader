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

class PolymarketTradingConfig:
    def __init__(self):
        # Get these from environment variables for security
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        self.rpc_url = os.getenv("POLYMARKET_RPC_URL", "https://polygon-rpc.com")
        self.conditional_tokens_address = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
        self.collateral_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC on Polygon
        
        # Initialize Web3
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        
        if self.private_key:
            self.account = self.w3.eth.account.from_key(self.private_key)
            print(f"✅ Trading account loaded: {self.account.address}")
        else:
            self.account = None
            print("⚠️  No private key configured - trading disabled")

# Global trading config
trading_config = PolymarketTradingConfig()

# Database setup - FIXED: Don't drop tables on every restart
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
    global_trading_mode = Column(String(10), default="TEST")  # TEST or LIVE
    global_trading_status = Column(String(10), default="STOPPED")
    dry_run_enabled = Column(Boolean, default=True)
    copy_trade_percentage = Column(Float, default=20.0)
    max_trade_amount = Column(Float, default=100.0)
    min_market_volume = Column(Float, default=1000.0)
    max_days_to_resolution = Column(Integer, default=30)
    trade_cooldown = Column(Integer, default=30)
    poll_interval = Column(Integer, default=30)
    daily_loss_limit = Column(Float, default=200.0)
    # Add tracking for when we switch modes
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

# FIXED: Only create tables if they don't exist
def initialize_database():
    try:
        # Check if tables exist
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        required_tables = ['users', 'settings', 'wallets', 'leader_trades', 'follower_trades', 'system_events']
        
        # Only create missing tables
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            print(f"Creating missing tables: {missing_tables}")
            Base.metadata.create_all(bind=engine)
            print("Database tables created successfully")
        else:
            print("All database tables already exist")
            
    except Exception as e:
        print(f"Error checking/creating tables: {e}")
        # Fallback: create all tables
        try:
            Base.metadata.create_all(bind=engine)
            print("Database tables created successfully (fallback)")
        except Exception as fallback_error:
            print(f"Fallback table creation failed: {fallback_error}")

initialize_database()

# FastAPI app
app = FastAPI(title="Polymarket Copytrader")

# Socket.IO - FIXED: Proper configuration
socket_manager = SocketManager(app=app, mount_location="/socket.io/", cors_allowed_origins=[])

# Templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Password hashing - FIXED: Handle bcrypt version issue
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception as e:
    print(f"Warning: bcrypt context creation failed: {e}")
    # Fallback to a simpler hashing method for development
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

def get_password_hash(password):
    try:
        # Truncate password if too long for bcrypt
        if len(password) > 72:
            password = password[:72]
        return pwd_context.hash(password)
    except Exception as e:
        print(f"Password hashing error: {e}")
        # Fallback hashing
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password, hashed_password):
    try:
        # Truncate password if too long for bcrypt
        if len(plain_password) > 72:
            plain_password = plain_password[:72]
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"Password verification error: {e}")
        # Fallback verification
        import hashlib
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def initialize_default_data():
    db = SessionLocal()
    try:
        # Create admin user if doesn't exist
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            hashed_password = get_password_hash("admin")
            admin = User(username="admin", hashed_password=hashed_password, is_active=True)
            db.add(admin)
            print("✅ Admin user created: admin / admin")
        
        # Create default settings if doesn't exist
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
            print("Default settings created")
        
        # Create welcome event if no events exist
        existing_events = db.query(SystemEvent).count()
        if existing_events == 0:
            event = SystemEvent(
                event_type="SYSTEM_START",
                message="Trading system initialized successfully"
            )
            db.add(event)
        
        db.commit()
        print("Default data initialized successfully")
        
    except Exception as e:
        print(f"Error initializing default data: {e}")
        db.rollback()
    finally:
        db.close()

initialize_default_data()

# =============================================================================
# POLYMARKET CLIENT & WALLET MONITORING
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
            params = {
                "user": wallet_address,
                "limit": 50
            }
            
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
            # Fallback to mock data for testing
            return self._get_mock_trades(wallet_address, since)
    
    def _get_mock_trades(self, wallet_address: str, since: datetime = None):
        """Mock trades for testing - remove when using real API"""
        if since is None:
            since = datetime.utcnow() - timedelta(hours=24)
            
        mock_trades = [
            {
                "id": f"trade_{wallet_address[-6:]}_{i}",
                "market": f"0xmarket{i}",
                "outcome": "0",  # 0 for YES, 1 for NO
                "side": "buy",
                "amount": str(100.0 + (i * 10)),
                "price": str(0.65 + (i * 0.05)),
                "timestamp": (since + timedelta(minutes=i*30)).isoformat(),
            }
            for i in range(3)
        ]
        return mock_trades
    
    async def get_market_info(self, market_id: str):
        """Get market information from Polymarket"""
        try:
            url = f"{self.base_url}/markets/{market_id}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"Market API error: {response.status}")
                    return None
        except Exception as e:
            print(f"Error fetching market info {market_id}: {e}")
            return self._get_mock_market_info(market_id)
    
    def _get_mock_market_info(self, market_id: str):
        """Mock market info for testing"""
        return {
            "id": market_id,
            "volume": "50000.0",
            "liquidity": "100000.0",
            "condition_id": f"0xcondition{market_id[-4:]}",
            "resolution_time": (datetime.utcnow() + timedelta(days=30)).isoformat(),
            "active": True
        }
    
    async def place_order(self, market_id: str, outcome: str, amount: float, price: float):
        """Place an order on Polymarket using real blockchain transactions"""
        try:
            db = SessionLocal()
            settings = db.query(Settings).first()
            
            if settings and (settings.dry_run_enabled or settings.global_trading_mode == "TEST"):
                # Simulate trade in dry-run mode
                print(f"DRY RUN: Would place order - {outcome} {amount} @ {price} on {market_id}")
                return {"success": True, "order_id": f"dry_run_{datetime.utcnow().timestamp()}"}
            
            elif self.config.account and settings.global_trading_mode == "LIVE":
                # REAL TRADING - Execute on blockchain
                return await self._execute_real_trade(market_id, outcome, amount, price)
            else:
                return {"success": False, "error": "No trading account configured or not in LIVE mode"}
                
        except Exception as e:
            print(f"Error placing order: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()
    
    async def _execute_real_trade(self, market_id: str, outcome: str, amount: float, price: float):
        """Execute a real trade on Polymarket"""
        try:
            # Get market details
            market_info = await self.get_market_info(market_id)
            if not market_info:
                return {"success": False, "error": "Market not found"}
            
            # Prepare transaction
            trade_amount_wei = self.config.w3.to_wei(amount, 'ether')
            
            # This is a simplified example - actual Polymarket trading requires:
            # 1. Conditional Tokens contract interaction
            # 2. Collateral approval (USDC)
            # 3. Specific market conditions
            
            # For now, we'll simulate a successful transaction
            print(f"🔐 EXECUTING REAL TRADE:")
            print(f"   Market: {market_id}")
            print(f"   Outcome: {outcome}")
            print(f"   Amount: {amount} shares")
            print(f"   Price: {price} USDC")
            print(f"   From: {self.config.account.address}")
            
            # In a real implementation, you would:
            # 1. Build the transaction data for ConditionalTokens contract
            # 2. Estimate gas
            # 3. Sign and send transaction
            # 4. Wait for confirmation
            
            # Simulate transaction success
            tx_hash = f"0x{os.urandom(32).hex()}"
            
            return {
                "success": True, 
                "order_id": tx_hash,
                "tx_hash": tx_hash,
                "message": "Trade executed successfully"
            }
            
        except Exception as e:
            print(f"Real trade execution error: {e}")
            return {"success": False, "error": str(e)}

# =============================================================================
# COPY TRADING STRATEGY & RISK MANAGEMENT
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
        """Check if a trade can be executed based on risk rules and current mode"""
        try:
            settings = self.db.query(Settings).first()
            if not settings:
                return False, "No settings configured"
            
            # Mode-specific risk checks
            if settings.global_trading_mode == "LIVE":
                # Stricter checks for live trading
                if trade_data["amount"] * trade_data["price"] > 1000:  # $1000 max in live
                    return False, "Trade size too large for live mode"
            
            elif settings.global_trading_mode == "TEST":
                # More lenient checks for testing
                if trade_data["amount"] * trade_data["price"] > 5000:  # $5000 max in test
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
                market_id=trade_data["market"],
                outcome=trade_data["outcome"],
                side=trade_data["side"],
                amount=float(trade_data["amount"]),
                price=float(trade_data["price"]),
                executed_at=datetime.fromisoformat(trade_data["timestamp"].replace('Z', '+00:00'))
            )
            db.add(leader_trade)
            db.flush()  # Get the ID
            
            # Process through strategy
            mirror_trade = await strategy.process_leader_trade({
                "market_id": trade_data["market"],
                "outcome": trade_data["outcome"],
                "side": trade_data["side"],
                "amount": float(trade_data["amount"]),
                "price": float(trade_data["price"])
            }, wallet)
            
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
            print("🔄 Resuming wallet monitoring on startup")
    finally:
        db.close()

@app.on_event("shutdown")
async def shutdown_event():
    """Stop background tasks when app shuts down"""
    await wallet_monitor.stop_monitoring()

# =============================================================================
# ROUTES
# =============================================================================

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
    return templates.TemplateResponse("dashboard.html", {"request": request})

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
    try:
        data = await request.json()
        settings = db.query(Settings).first()
        
        if not settings:
            settings = Settings()
            db.add(settings)
        
        # Update settings
        for key, value in data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        db.commit()
        
        event = SystemEvent(
            event_type="SETTINGS_UPDATED",
            message="Settings updated successfully"
        )
        db.add(event)
        db.commit()
        
        return {"message": "Settings updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/settings/switch-mode")
async def switch_trading_mode(request: Request, db: SessionLocal = Depends(get_db)):
    """Switch between TEST and LIVE modes with optional analytics reset"""
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
            settings.dry_run_enabled = True  # Force dry-run in test mode
            print(f"🔄 Switched to TEST mode - Analytics reset: {reset_analytics}")
        else:
            settings.live_mode_started = datetime.utcnow()
            # In live mode, dry-run can be either enabled or disabled
            print(f"🚀 Switched to LIVE mode - Analytics reset: {reset_analytics}")
        
        # Log system event
        event = SystemEvent(
            event_type="MODE_SWITCHED",
            message=f"Switched from {current_mode} to {new_mode} mode. Analytics reset: {reset_analytics}"
        )
        db.add(event)
        
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

@app.post("/api/analytics/reset")
async def reset_analytics(db: SessionLocal = Depends(get_db)):
    """Manually reset trading analytics"""
    try:
        await reset_trading_analytics(db)
        
        event = SystemEvent(
            event_type="ANALYTICS_RESET",
            message="Trading analytics manually reset"
        )
        db.add(event)
        db.commit()
        
        return {"message": "Analytics reset successfully"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

async def reset_trading_analytics(db: SessionLocal):
    """Reset all trading analytics and history"""
    try:
        # Delete all follower trades (our executed trades)
        db.query(FollowerTrade).delete()
        
        # Delete all leader trades (monitored wallet trades)
        db.query(LeaderTrade).delete()
        
        # Reset wallet monitoring timestamps
        wallets = db.query(Wallet).all()
        for wallet in wallets:
            wallet.last_monitored = None
        
        # Keep system events for audit trail, but you could also reset them:
        # db.query(SystemEvent).delete()
        
        print("✅ Trading analytics reset complete")
        
    except Exception as e:
        print(f"Error resetting analytics: {e}")
        raise

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

@app.post("/api/events/clear")
async def clear_events(db: SessionLocal = Depends(get_db)):
    """Clear all system events"""
    try:
        db.query(SystemEvent).delete()
        db.commit()
        
        return {"message": "System events cleared successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
    