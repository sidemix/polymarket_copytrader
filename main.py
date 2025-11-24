# app/main.py
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_login import LoginManager
from fastapi_login.exceptions import InvalidCredentialsException
from .config import settings
from .db import Base, engine, get_db
from .models import User, LeaderWallet, SystemEvent, SettingsSingleton
from .auth import verify_password
import secrets

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Polymarket Copytrader")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Simple session-based auth (single user)
SECRET = settings.SECRET_KEY or secrets.token_urlsafe(32)
manager = LoginManager(SECRET, token_url="/login", use_cookie=True)
manager.cookie_name = "auth"

@manager.user_loader()
def load_user(username: str):
    db = next(get_db())
    return db.query(User).filter(User.username == username).first()

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(response: Response, request: Request, db=Depends(get_db),
                form_data: OAuth2PasswordRequestForm = Depends()):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise InvalidCredentialsException
    access_token = manager.create_access_token(data={"sub": user.username})
    manager.set_cookie(response, access_token)
    return RedirectResponse("/", status_code=303)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user=Depends(manager), db=Depends(get_db)):
    # === GET SETTINGS (singleton row) ===
    bot_settings = db.query(SettingsSingleton).first()
    if not bot_settings:
        bot_settings = SettingsSingleton()
        db.add(bot_settings)
        db.commit()

    # === BASIC STATS (safe defaults) ===
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
        "bot_status": bot_settings.global_trading_status or "STOPPED",
        "trading_mode": bot_settings.global_trading_mode or "TEST",
        "dry_run": bot_settings.dry_run_enabled or True,
        "risk_level": "Low",
        "risk_settings": {"copy_percentage": 20, "max_trade_amount": 100},
        "balances": {"available_cash": 5920, "portfolio_value": 10019},
        "risk_status": "All systems normal",
        "daily_pnl": 0.0,
        "trades_today": 0,
        "bot_settings": {"min_trade_amount": 5, "trade_cooldown": 30}
    }
    return templates.TemplateResponse("dashboard.html", context)

# Health check
@app.get("/health")
async def health():
    return {"status": "ok"}