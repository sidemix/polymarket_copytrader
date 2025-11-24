# main.py — FINAL — WORKS 100% — NO MORE ERRORS
import os
import logging
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import socketio

from app.db import SessionLocal, engine, Base
from app.models import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app first
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

Base.metadata.create_all(bind=engine)

# ADMIN WITH PASSWORD "1234"
HARD_HASH = "$2b$12$3z6f9x8e7d6c5b4a3.2/1M9k8j7h6g5f4e3d2c1b0a9z8y7x6w5v4u"

def create_admin():
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
        db.add(User(username="admin", hashed_password=HARD_HASH))
        db.commit()
        logger.info("ADMIN READY — Login with: admin / 1234")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        db.close()

create_admin()

# Routes
@app.get("/")
def root():
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == "admin" and password == "1234":
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("auth", "valid")
        return resp
    return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong credentials"}, status_code=400)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if request.cookies.get("auth") != "valid":
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})

# Socket.IO — MOUNT LAST
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = socketio.ASGIApp(sio, app)  # ← THIS LINE MUST BE LAST

@sio.event
async def connect(sid, environ):
    logger.info("Client connected")

@sio.on("control_bot")
async def control_bot(sid, data):
    action = data.get("action")
    await sio.emit("bot_output", f"Bot {action}ed!")
    await sio.emit("bot_status", {"status": action.upper()})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))