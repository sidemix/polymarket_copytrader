# app/main.py — FIXED VERSION
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, Column, Integer, Boolean
from sqlalchemy.orm import Session
from app.db import get_db, Base, engine
from app.models import User, LeaderWallet, SettingsSingleton
from app.config import settings
from passlib.handlers.argon2 import argon2
from app.background import start_background_tasks
from app.sockets import websocket_endpoint

class LeaderTrade(Base):
    __tablename__ = "leader_trades"
    id = Column(Integer, primary_key=True)
    # ... your existing columns ...
    processed = Column(Boolean, default=False, nullable=False)

# 1. CREATE APP FIRST
app = FastAPI()

# 2. ADD MIDDLEWARE
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

# 3. MOUNT STATIC + TEMPLATES
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

def get_csrf_token():
    return "dummy"

# Make it available in templates (AFTER templates is defined)
templates.env.globals["csrf_token"] = get_csrf_token

# 4. WEBSOCKET
app.add_api_websocket_route("/ws", websocket_endpoint)

# 5. BACKGROUND TASKS
@app.on_event("startup")
async def startup():
    start_background_tasks()

# 6. CREATE TABLES + ADMIN USER (AFTER app is created)
inspector = inspect(engine)
if not inspector.has_table("users"):
    print("Creating tables + admin")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        # Check if admin already exists
        existing_admin = db.query(User).filter(User.username == "admin").first()
        if not existing_admin:
            db.add(User(username="admin", password_hash=argon2.hash("admin123")))
        
        # Check if settings already exist
        existing_settings = db.query(SettingsSingleton).first()
        if not existing_settings:
            db.add(SettingsSingleton())
        
        db.commit()
    print("Database initialized")
else:
    print("Database ready")

# 7. AUTH
def get_current_user(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return True

# 8. ROUTES
@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username")
    password = form.get("password", "")
    
    user = db.query(User).filter(User.username == username).first()
    if user and argon2.verify(password, user.password_hash):
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), auth: bool = Depends(get_current_user)):
    context = {
        "request": request,
        "stats": {"total_trades": 0, "profitable_trades": 0, "total_pnl": 0.0, "win_rate": 0.0},
        "leader_wallets": db.query(LeaderWallet).all(),
        "active_wallets_count": db.query(LeaderWallet).filter(LeaderWallet.is_active == True).count(),
        "bot_status": "STOPPED",
        "trading_mode": "TEST",
        "dry_run": True,
        "risk_level": "Low",
        "risk_settings": {"copy_percentage": 20},
        "balances": {"available_cash": 5920, "portfolio_value": 10019},
        "risk_status": "All systems normal",
        "daily_pnl": 0.0,
        "trades_today": 0,
        "bot_settings": {"min_trade_amount": 5}
    }
    return templates.TemplateResponse("dashboard.html", context)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")