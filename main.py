# app/main.py — FINAL ULTIMATE VERSION — FULL DASHBOARD CONTROL
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from app.db import get_db, Base, engine
from app.models import User, LeaderWallet, SettingsSingleton
from app.config import settings
from passlib.handlers.argon2 import argon2
from app.background import start_background_tasks
from app.sockets import websocket_endpoint

# === 1. Initialize Database + Admin User (safe) ===
inspector = inspect(engine)
if not inspector.has_table("users"):
    print("First run → creating tables + admin user")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        db.add(User(username="admin", password_hash=argon2.hash("admin123")))
        db.add(SettingsSingleton(
            trading_mode="TEST",
            bot_status="STOPPED",
            dry_run_enabled=True,
            portfolio_value=10019.0,
            available_cash=5920.0,
            copy_percentage=20.0
        ))
        db.commit()
    print("Admin created → username: admin | password: admin123")
else:
    print("Database ready")

# === 2. FastAPI App ===
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
app.add_api_websocket_route("/ws", websocket_endpoint)

@app.on_event("startup")
async def startup():
    start_background_tasks()

# === 3. Auth Guard ===
def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return True

# === 4. Routes ===
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
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_auth)):
    s = db.query(SettingsSingleton).first() or SettingsSingleton()
    
    context = {
        "request": request,
        "leader_wallets": db.query(LeaderWallet).all(),
        "active_wallets_count": db.query(LeaderWallet).filter(LeaderWallet.is_active == True).count(),
        "s": s,  # All settings for dashboard
        "stats": {"total_trades": 0, "profitable_trades": 0, "total_pnl": 0.0, "win_rate": 0.0},
        "risk_status": "All systems normal",
        "daily_pnl": 0.0,
        "trades_today": 0,
    }
    return templates.TemplateResponse("dashboard.html", context)

# === 5. DASHBOARD CONTROLS ===
@app.post("/api/wallets/add")
async def add_wallet(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    address = form.get("address", "").strip().lower()
    nickname = form.get("nickname", "").strip() or None
    if not address.startswith("0x") or len(address) != 42:
        return RedirectResponse("/", status_code=303)
    if not db.query(LeaderWallet).filter(LeaderWallet.address == address).first():
        db.add(LeaderWallet(address=address, nickname=nickname, is_active=True))
        db.commit()
    return RedirectResponse("/", status_code=303)

@app.post("/api/settings/bot")
async def update_bot_settings(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    s = db.query(SettingsSingleton).first() or SettingsSingleton()
    s.trading_mode = form.get("trading_mode", "TEST")
    s.bot_status = form.get("bot_status", "STOPPED")
    s.dry_run_enabled = form.get("dry_run_enabled") == "on"
    db.add(s)
    db.commit()
    return RedirectResponse("/", status_code=303)

@app.post("/api/settings/balance")
async def update_balance(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    s = db.query(SettingsSingleton).first() or SettingsSingleton()
    s.portfolio_value = float(form.get("portfolio_value", s.portfolio_value or 10019))
    s.available_cash = float(form.get("available_cash", s.available_cash or 5920))
    s.risk_tolerance = form.get("risk_tolerance", "medium")
    db.add(s)
    db.commit()
    return RedirectResponse("/", status_code=303)

@app.post("/api/settings/risk")
async def update_risk(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    s = db.query(SettingsSingleton).first() or SettingsSingleton()
    s.copy_percentage = float(form.get("copy_percentage", s.copy_percentage))
    db.add(s)
    db.commit()
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")