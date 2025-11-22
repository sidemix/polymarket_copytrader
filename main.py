import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from app.database import engine, Base, get_db
from app.models import User, Settings
from app.auth import create_default_admin
from app.api import app as api_app
from app.config import settings as app_settings
from app.wallet_monitor import WalletMonitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('copytrader.log')
    ]
)

logger = logging.getLogger(__name__)

# Global variables
wallet_monitor = None
monitor_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Polymarket Copytrader...")
    
    # Create database tables
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified")
        
        # Create default admin user
        with next(get_db()) as db:
            create_default_admin(db)
            logger.info("Default admin user verified")
            
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    
    # Start wallet monitor if in RUNNING mode
    with next(get_db()) as db:
        current_settings = db.query(Settings).first()
        if current_settings and current_settings.global_trading_status == "RUNNING":
            logger.info("Starting wallet monitor...")
            await start_wallet_monitor(db)
    
    yield
    
    # Shutdown
    logger.info("Shutting down Polymarket Copytrader...")
    await stop_wallet_monitor()

async def start_wallet_monitor(db):
    """Start the wallet monitor"""
    global wallet_monitor, monitor_task
    try:
        wallet_monitor = WalletMonitor(db)
        monitor_task = asyncio.create_task(wallet_monitor.start_monitoring())
        logger.info("Wallet monitor started successfully")
    except Exception as e:
        logger.error(f"Failed to start wallet monitor: {e}")

async def stop_wallet_monitor():
    """Stop the wallet monitor"""
    global wallet_monitor, monitor_task
    if wallet_monitor:
        await wallet_monitor.stop_monitoring()
    if monitor_task:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
    logger.info("Wallet monitor stopped")

# Create FastAPI app with lifespan
app = FastAPI(
    title="Polymarket Copytrader",
    description="Production-grade copytrading system for Polymarket",
    version="1.0.0",
    lifespan=lifespan
)

# Security middleware (enable in production)
if app_settings.GLOBAL_TRADING_MODE == "LIVE":
    app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["your-domain.com", "*.your-domain.com"]
    )

# Include API routes
app.include_router(api_app)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception handler: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

# Signal handlers for graceful shutdown
def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    asyncio.create_task(stop_wallet_monitor())
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=app_settings.GLOBAL_TRADING_MODE == "TEST",
        log_level="info"
    )
