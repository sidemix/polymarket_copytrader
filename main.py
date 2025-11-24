# app/main.py — FINAL VERSION
from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from app.db import get_db, Base, engine
from app.models import User, LeaderWallet, SettingsSingleton
from app.config import settings
from passlib.handlers.argon2 import argon2

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if str(request.url.path) in ["/login", "/health"] or str(request.url.path).startswith("/static"):
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
    user = db.query(User).filter(User.username == form.get("username")).first()
    if user and argon2.verify(form.get("password", ""), user.password_hash):
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid"})

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    s = db.query(SettingsSingleton).first() or SettingsSingleton()
    context = {
        "request": request,
        "stats": {"total_trades": 0, "profitable_trades": 0, "total_pnl": 0.0, "win_rate": 0.0},
        "leader_wallets": db.query(LeaderWallet).all(),
        "recent_logs": [],
        "active_wallets_count": 0,
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