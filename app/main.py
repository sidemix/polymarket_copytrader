# app/main.py
import os
import logging
from fastapi import FastAPI, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi_login import LoginManager
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from .db import SessionLocal, engine, Base
from .models import User
from .config import settings

# ==============================
# Logging & App
# ==============================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Polymarket Copytrader")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ==============================
# DB
# ==============================
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==============================
# Auth
# ==============================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# THIS IS THE ONLY PLACE PASSWORD IS READ — SHORT & SAFE
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or "admin123")[:72]  # ← NEVER longer than 72

manager = LoginManager(
    secret=settings.SECRET_KEY,
    token_url="/login",
    use_cookie=True,
    cookie_name="auth_token"
)

@manager.user_loader()
def load_user(username: str):
    db = next(get_db())
    return db.query(User).filter(User.username == username).first()

# ==============================
# Admin Creation — FIXED FOREVER
# ==============================
def create_default_admin():
    db = next(get_db())
    try:
        if not db.query(User).filter(User.username == "admin").first():
            hashed = pwd_context.hash(ADMIN_PASSWORD)  # ← Uses safe short password
            admin = User(username="admin", hashed_password=hashed)
            db.add(admin)
            db.commit()
            logger.info("Admin user created successfully")
    except Exception as e:
        logger.error(f"Admin creation failed: {e}")
    finally:
        db.close()

# Run on startup
create_default_admin()

# ==============================
# Routes
# ==============================
@app.get("/health")
def health():
    return {"status": "ok", "mode": settings.ENVIRONMENT, "dry_run": settings.DRY_RUN}

@app.get("/")
def root(user=Depends(manager)):
    return RedirectResponse("/dashboard" if user else "/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(username: str = Form(), password: str = Form(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": Request, "error": "Wrong credentials"}, status_code=400)
    
    token = manager.create_access_token(data={"sub": username})
    response = RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    manager.set_cookie(response, token)
    return response

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(manager)):
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "bot_status": settings.BOT_STATUS,
        "dry_run": settings.DRY_RUN,
        "environment": settings.ENVIRONMENT.upper()
    })

@app.get("/logout")
def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie("auth_token")
    return resp

# ==============================
# Startup
# ==============================
@app.on_event("startup")
async def startup():
    logger.info("Polymarket Copytrader started!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)