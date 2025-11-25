# app/main.py — FINAL SAFE VERSION (NO DATA LOSS EVER)
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from app.db import get_db, Base, engine
from app.models import User, LeaderWallet, SettingsSingleton
from app.config import settings
from passlib.handlers.argon2 import argon2
from app.background import start_background_tasks
from app.sockets import websocket_endpoint

print("Starting Polymarket Copytrader...")

# SAFE DATABASE INITIALIZATION
inspector = inspect(engine)

# 1. Create tables if they don't exist
if not inspector.has_table("users"):
    print("First run → creating tables + admin")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        db.add(User(username="admin", password_hash=argon2.hash("admin123")))
        db.add(SettingsSingleton())
        db.commit()
    print("Admin created → admin / admin123")
else:
    print("Database exists — checking for missing columns...")

    # 2. FIX: Add 'processed' column to leader_trades if missing
    if inspector.has_table("leader_trades"):
        columns = [col["name"] for col in inspector.get_columns("leader_trades")]
        if "processed" not in columns:
            print("Adding missing 'processed' column to leader_trades...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE leader_trades ADD COLUMN processed BOOLEAN DEFAULT FALSE"))
                conn.commit()
            print("Fixed: leader_trades.processed column added")

print("Bot ready — go to /login")

# APP SETUP
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
app.add_api_websocket_route("/ws", websocket_endpoint)

@app.on_event("startup")
async def startup():
    start_background_tasks()

def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return True

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
        "s": s,
        "stats": {"total_trades": 0, "profitable_trades": 0, "total_pnl": 0.0, "win_rate": 0.0},
        "risk_status": "All systems normal",
        "daily_pnl": 0.0,
        "trades_today": 0,
    }
    return templates.TemplateResponse("dashboard.html", context)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")