# main.py (ROOT LEVEL — THIS IS THE FINAL VERSION)
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

# ==============================
# Logging & App
# ==============================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Polymarket Copytrader")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ==============================
# Database
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

# SAFE PASSWORD — always ≤72 chars
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD", "Test123") or "Test123")[:72]

manager = LoginManager(
    secret=settings.SECRET_KEY,
    token_url="/login",
    use_cookie=True,
    cookie_name="auth_token",
    default_expiry=3600 * 24 * 30
)

@manager.user_loader()
def load_user(username: str):
    db = next(get_db())
    return db.query(User).filter(User.username == username).first()

# ==============================
# FORCE CREATE ADMIN (deletes old one every startup — REMOVE AFTER FIRST LOGIN)
# ==============================
def create_default_admin():
    db = next(get_db())
    try:
        # DELETE ANY OLD ADMIN
        db.query(User).delete()
        db.commit()
        
        # CREATE FRESH ONE
        hashed = pwd_context.hash(ADMIN_PASSWORD)
        admin_user = User(username="admin", hashed_password=hashed)
        db.add(admin_user)
        db.commit()
        logger.info(f"Admin user created/updated with password: {ADMIN_PASSWORD}")
    except Exception as e:
        logger.error(f"Admin creation failed: {e}")
    finally:
        db.close()

create_default_admin()  # ← This runs every startup — safe for now

# ==============================
# Routes
# ==============================
@app.get("/health")
def health():
    return {"status": "alive", "mode": settings.ENVIRONMENT}

@app.get("/")
def root(user=Depends(manager)):
    return RedirectResponse("/dashboard" if user else "/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": Request, "error": "Invalid username or password"},
            status_code=400
        )
    
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
        "bot_status": "STOPPED",
        "dry_run": True,
        "environment": "TEST"
    })

@app.get("/logout")
def logout():
    response = RedirectResponse("/login")
    response.delete_cookie("auth_token")
    return response

# ==============================
# Startup
# ==============================
@app.on_event("startup")
async def startup_event():
    logger.info("Polymarket Copytrader is LIVE!")

# ==============================
# Railway PORT Fix
# ==============================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")