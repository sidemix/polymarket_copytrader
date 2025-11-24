# main.py — FINAL VERSION — HARD-CODED PASSWORD "1234" — WORKS
import os
import logging
from fastapi import FastAPI, Depends, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi_login import LoginManager
from sqlalchemy.orm import Session
from passlib.context import CryptContext

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

# HARDCODED PASSWORD — NO MORE ENV VAR PROBLEMS
ADMIN_PASSWORD = "1234"   # ← THIS IS THE ONLY PASSWORD THAT MATTERS NOW

manager = LoginManager("supersecretkey123", "/login", use_cookie=True, cookie_name="auth_token")

@manager.user_loader()
def load_user(username: str):
    db = next(get_db())
    return db.query(User).filter(User.username == username).first()

# FORCE CREATE ADMIN WITH PASSWORD "1234"
def create_admin():
    db = next(get_db())
    try:
        db.query(User).delete()
        db.commit()
        hashed = pwd_context.hash(ADMIN_PASSWORD)
        db.add(User(username="admin", hashed_password=hashed))
        db.commit()
        logger.info("ADMIN FORCED: username=admin, password=1234")
    except Exception as e:
        logger.error(f"Admin error: {e}")
    finally:
        db.close()

create_admin()  # Runs every startup

@app.get("/")
def root(user=Depends(manager)):
    return RedirectResponse("/dashboard" if user else "/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong username or password"}, status_code=400)
    token = manager.create_access_token(data={"sub": username})
    resp = RedirectResponse("/dashboard", status_code=302)
    manager.set_cookie(resp, token)
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(manager)):
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request, "message": "Welcome! You're in!"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), log_level="info")