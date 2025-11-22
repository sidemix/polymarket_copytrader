from fastapi import FastAPI
import uvicorn
import os
import logging

from app.database import engine, Base
from app.models import User, LeaderWallet, LeaderTrade, FollowerTrade, Position, Settings, SystemEvent
from app.auth import create_default_admin

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
    
    # Create default admin user
    from app.database import SessionLocal
    db = SessionLocal()
    create_default_admin(db)
    db.close()
    
except Exception as e:
    logger.error(f"Database initialization failed: {e}")

app = FastAPI(title="Polymarket Copytrader")

# Import and include your API routes
from app.api import app as api_app
app.include_router(api_app)

@app.get("/")
async def root():
    return {"status": "Polymarket Copytrader", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "database": "connected"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
