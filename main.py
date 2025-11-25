# app/main.py — FIXED VERSION
from fastapi import FastAPI, Request, Depends, Form
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

# 2. Create app
app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# 3. Custom auth middleware class that runs AFTER SessionMiddleware
class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        
        # Skip auth for these paths
        if request.url.path in ["/login", "/health"] or request.url.path.startswith("/static"):
            await self.app(scope, receive, send)
            return
        
        # Now session should be available since we'll wrap this with SessionMiddleware
        if not request.session.get("authenticated"):
            response = RedirectResponse("/login")
            await response(scope, receive, send)
            return
        
        await self.app(scope, receive, send)

# 4. Apply middleware in correct order: SessionMiddleware wraps AuthMiddleware
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.add_middleware(AuthMiddleware)

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
async def dashboard(request: Request, db: Session = Depends(get_db)):
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