# app/main.py
from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware  # CORRECT
from sqlalchemy.orm import Session
from app.db import get_db, Base, engine
from app.models import User, LeaderWallet, SystemEvent, SettingsSingleton
from app.config import settings
from passlib.handlers.argon2 import argon2

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if str(request.url.path).startswith(("/login", "/static", "/favicon.ico", "/health")):
        return await call_next(request)
    if not request.session.get("authenticated"):
        return RedirectResponse("/login")
    return await call_next(request)

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    user = db.query(User).filter(User.username == username).first()
    if user and argon2.verify(password or "", user.password_hash):
        request.session["authenticated"] = True
        request.session["username"] = username
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong credentials"})

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    settings_row = db.query(SettingsSingleton).first() or SettingsSingleton()
    total_trades = db.query(SystemEvent).filter(SystemEvent.event_type == "trade_executed").count()
    active_wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active == True).count()

    context = {
        "request": request,
        "stats": {"total_trades": total_trades, "profitable_trades": 0, "total_pnl": 0.0, "win_rate": 0.0},
        "leader_wallets": db.query(LeaderWallet).all(),
        "recent_logs": db.query(SystemEvent).order_by(SystemEvent.id.desc()).limit(50).all(),
        "active_wallets_count": active_wallets,
        "bot_status": getattr(settings_row, "global_trading_status", "STOPPED"),
        "trading_mode": getattr(settings_row, "global_trading_mode", "TEST"),
        "dry_run": getattr(settings_row, "dry_run_enabled", True),
        "risk_level": "Low",
        "risk_settings": {"copy_percentage": 20},
        "balances": {"available_cash": 5920, "portfolio_value": 10019},
        "risk_status": "All systems normal",
        "daily_pnl": 0.0,
        "trades_today": 0,
        "bot_settings": {"min_trade_amount": 5, "trade_cooldown": 30}
    }
    return templates.TemplateResponse("dashboard.html", context)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")

@app.get("/health")
def health():
    return {"status": "ok"}