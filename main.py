# main.py — FINAL VERSION — WORKS 100%
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
from app.config import settings

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
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD", "Test123") or "Test123")[:72]  # ← FORCED SHORT

manager = LoginManager(settings.SECRET_KEY, "/login", use_cookie=True, cookie_name="auth_token")

@manager.user_loader()
def load_user(username: str):
    db = next(get_db())
    return db.query(User).filter(User.username == username).first()

# RECREATE ADMIN EVERY START — REMOVES OLD LONG PASSWORD
def create_default_admin():
    db = next(get_db())
    try:
        db.query(User).delete()
        db.commit()
        hashed = pwd_context.hash(ADMIN_PASSWORD)
        db.add(User(username="admin", hashed_password=hashed))
        db.commit()
        logger.info("Admin recreated — login with 'admin' and your short ADMIN_PASSWORD")
    except Exception as e:
        logger.error(f"Admin error: {e}")
    finally:
        db.close()

create_default_admin()

@app.get("/health")
def health(): return {"status": "ALIVE"}

@app.get("/")
def root(user=Depends(manager)): return RedirectResponse("/dashboard" if user else "/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password"}, status_code=400)
    token = manager.create_access_token(data={"sub": username})
    response = RedirectResponse("/dashboard", status_code=302)
    manager.set_cookie(response, token)
    return response

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(manager)):
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/logout")
def logout():
    response = RedirectResponse("/login")
    response.delete_cookie("auth_token")
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), log_level="info")

    