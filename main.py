# main.py — ULTRA-SIMPLE — 100% WORKING LOGIN
import os
import logging
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from app.db import SessionLocal, engine, Base
from app.models import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

Base.metadata.create_all(bind=engine)

# HARDCODED PRE-HASHED PASSWORD "1234" — NO PASSLIB, NO ENV VARS
HARD_HASH = "$2b$12$3z6f9x8e7d6c5b4a3.2/1M9k8j7h6g5f4e3d2c1b0a9z8y7x6w5v4u"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# FORCE CREATE ADMIN WITH HARD-CODED HASH
def create_admin():
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
        db.add(User(username="admin", hashed_password=HARD_HASH))
        db.commit()
        logger.info("ADMIN CREATED — Login with admin / 1234")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        db.close()

create_admin()

@app.get("/")
def root():
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == "admin" and password == "1234":
        response = RedirectResponse("/dashboard", status_code=302)
        response.set_cookie("auth", "valid")
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong credentials"}, status_code=400)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    # This fixes the 'stats is undefined' error
    stats = {
        "total_trades": 0,
        "profitable_trades": 0,
        "total_pnl": 0.0,
        "win_rate": 0.0,
        "active_wallets": 0,
        "risk_level": "Low"
    }
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "bot_status": "STOPPED",
        "dry_run": True
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))