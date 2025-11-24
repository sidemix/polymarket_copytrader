# app/main.py
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from app.db import get_db, Base, engine
from app.models import User, LeaderWallet, SystemEvent, SettingsSingleton

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static", html=True), name="static")
templates = Jinja2Templates(directory="app/templates")

# Simple session-based auth (no external lib needed)
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in ["/login", "/static/", "/favicon.ico"]:
        return await call_next(request)
    
    if not request.session.get("authenticated"):
        return RedirectResponse("/login")
    
    response = await call_next(request)
    return response

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    
    user = db.query(User).filter(User.username == username).first()
    from passlib.handlers.argon2 import argon2
    if user and argon2.verify(password or "", user.password_hash):
        request.session["authenticated"] = True
        request.session["username"] = username
        return RedirectResponse("/", status_code=303)
    
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    # Ensure settings row exists
    settings = db.query(SettingsSingleton).first()
    if not settings:
        settings = SettingsSingleton()
        db.add(settings)
        db.commit()

    # Safe stats
    total_trades = db.query(SystemEvent).filter(SystemEvent.event_type == "trade_executed").count()
    active_wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active == True).count()

    context = {
        "request": request,
        "stats": {
            "total_trades": total_trades,
            "profitable_trades": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0
        },
        "leader_wallets": db.query(LeaderWallet).all(),
        "recent_logs": db.query(SystemEvent).order_by(SystemEvent.id.desc()).limit(50).all(),
        "active_wallets_count": active_wallets,
        "top_wallets": [],
        "bot_status": getattr(settings, "global_trading_status", "STOPPED"),
        "trading_mode": getattr(settings, "global_trading_mode", "TEST"),
        "dry_run": getattr(settings, "dry_run_enabled", True),
        "risk_level": "Low",
        "risk_settings": {"copy_percentage": 20, "max_trade_amount": 100, "daily_loss_limit": 200, "max_trades_per_hour": 10},
        "balances": {"available_cash": 5920, "portfolio_value": 10019},
        "risk_status": "All systems normal",
        "daily_pnl": 0.0,
        "trades_today": 0,
        "bot_settings": {"min_trade_amount": 5, "trade_cooldown": 30, "auto_stop_enabled": True, "push_notifications": False}
    }
    
    return templates.TemplateResponse("dashboard.html", context)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")