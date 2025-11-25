# app/main.py — FIXED CSRF TOKEN VERSION
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
from fastapi.templating import Jinja2Templates
from fastapi import Request
from app.sockets import manager
from app.background import start_background_tasks

# Add WebSocket route
app.include_router(socket_router)

# Start background tasks on startup
@app.on_event("startup")
async def startup_event():
    start_background_tasks()

# 1. Create tables + admin user (safe)
inspector = inspect(engine)
if not inspector.has_table("users"):
    print("First run → creating tables + admin")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        db.add(User(username="admin", password_hash=argon2.hash("admin123")))
        db.add(SettingsSingleton())
        db.commit()
else:
    print("Database ready")

# 2. Create app with SessionMiddleware
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# 3. Add CSRF token function to template context
def csrf_token():
    """Dummy CSRF token function for templates"""
    return ""

# Make CSRF token available to all templates
templates.env.globals["csrf_token"] = csrf_token

# 4. Simple auth dependency (NO MIDDLEWARE HEADACHES)
def get_current_user(request: Request):
    """Dependency to check if user is authenticated"""
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return True

# 5. Routes
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
    return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong username or password"})

@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    db: Session = Depends(get_db),
    auth: bool = Depends(get_current_user)
):
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