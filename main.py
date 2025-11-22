from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Float, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import uvicorn
from jose import JWTError, jwt
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

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    global_trading_mode = Column(String(10), default="TEST")
    global_trading_status = Column(String(10), default="STOPPED")
    dry_run_enabled = Column(Boolean, default=True)

# Create tables
Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI(title="Polymarket Copytrader")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_default_admin():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            hashed_password = get_password_hash("admin123")
            admin = User(
                username="admin",
                hashed_password=hashed_password,
                is_active=True
            )
            db.add(admin)
            db.commit()
            print("Default admin user created: admin / admin123")
        return admin
    finally:
        db.close()

# Create admin user on startup
create_default_admin()

# Routes
@app.get("/")
async def root():
    return {"status": "Polymarket Copytrader is running!", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "database": "connected"}

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.hashed_password) or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Create session
        request.session["user_id"] = user.id
        
        return RedirectResponse(url="/dashboard", status_code=303)
    finally:
        db.close()

@app.get("/dashboard")
async def dashboard(request: Request):
    db = SessionLocal()
    try:
        # Check if user is logged in
        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return RedirectResponse(url="/login")
        
        # Get settings
        settings = db.query(Settings).first()
        if not settings:
            settings = Settings()
            db.add(settings)
            db.commit()
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user": user,
            "settings": settings,
            "stats": {
                "total_trades": 0,
                "profitable_trades": 0,
                "total_profit": 0,
                "win_rate": 0,
                "active_wallets": 0,
                "risk_level": "Low"
            },
            "recent_events": [],
            "top_wallets": []
        })
    finally:
        db.close()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
