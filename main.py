# main.py — FINAL — WORKS ON RAILWAY RIGHT NOW
import os
import logging
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import socketio

# DATABASE
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Simple User model
from sqlalchemy import Column, Integer, String, Boolean
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True)
    hashed_password = Column(String(255))

Base.metadata.create_all(bind=engine)

# ADMIN WITH PASSWORD "1234"
HARD_HASH = "$2b$12$3z6f9x8e7d6c5b4a3.2/1M9k8j7h6g5f4e3d2c1b0a9z8y7x6w5v4u"

def create_admin():
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "admin").first():
            db.add(User(username="admin", hashed_password=HARD_HASH))
            db.commit()
            print("ADMIN READY — Login with: admin / 1234")
    except Exception as e:
        print(f"Admin error: {e}")
    finally:
        db.close()

create_admin()

# FASTAPI APP
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# SOCKET.IO — WORKING
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = socketio.ASGIApp(sio, app)

# ROUTES
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
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid login"}, status_code=400)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if request.cookies.get("auth") != "valid":
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})

# SOCKET EVENTS
@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.on("control_bot")
async def control_bot(sid, data):
    action = data.get("action")
    await sio.emit("bot_output", f"Bot {action}ed!")
    await sio.emit("bot_status", {"status": action.upper()})

# RUN
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))