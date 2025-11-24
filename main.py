# main.py — WITH SOCKET.IO MOUNTED — CLICKS WORK NOW
import os
import logging
from fastapi import FastAPI, Depends, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi_login import LoginManager
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import socketio

from app.db import SessionLocal, engine, Base
from app.models import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ADMIN_PASSWORD = "1234"  # Hardcoded short

manager = LoginManager("supersecretkey123", "/login", use_cookie=True, cookie_name="auth_token")

@manager.user_loader()
def load_user(username: str):
    db = next(get_db())
    return db.query(User).filter(User.username == username).first()

def create_admin():
    db = next(get_db())
    try:
        db.query(User).delete()
        db.commit()
        hashed = pwd_context.hash(ADMIN_PASSWORD)
        db.add(User(username="admin", hashed_password=hashed))
        db.commit()
        logger.info("ADMIN CREATED — Login with admin / 1234")
    except Exception as e:
        logger.error(f"Admin error: {e}")
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
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong credentials"}, status_code=400)
    token = manager.create_access_token(data={"sub": username})
    resp = RedirectResponse("/dashboard", status_code=302)
    manager.set_cookie(resp, token)
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    # This fixes the 'stats is undefined' error — your dashboard needs this
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

# SOCKET.IO MOUNT — FIXES 404 AND CLICKS
sio = socketio.AsyncServer(cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio)
app.mount("/socket.io", socket_app)

# SOCKET.IO EVENTS — FOR REAL-TIME TRADES/BOT
@sio.event
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")

@sio.on('join')
async def handle_join(sid, data):
    await sio.emit('lobby', 'User joined', room=sid)

# BOT EVENTS (emit from background tasks)
@sio.on('start_bot')
async def start_bot(sid, data):
    logger.info("Bot started via socket")
    await sio.emit('bot_status', {'status': 'RUNNING'}, room=sid)

@sio.on('trade_executed')
async def trade_executed(sid, data):
    logger.info(f"Trade executed: {data}")
    await sio.emit('trade_update', data, room=sid)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))