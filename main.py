# main.py (ROOT LEVEL)
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
# Logging & App Setup
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
# Authentication
# ==============================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# SAFE PASSWORD — always ≤72 chars
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or "CopyTrader2025!")[:72]

manager = LoginManager(
    secret=settings.SECRET_KEY,
    token_url="/login",
    use_cookie=True,
    cookie_name="auth_token",
    default_expiry=3600 * 24 * 30  # 30 days
)

@manager.user_loader()
def load_user(username: str):
    db = next(get_db())
    return db.query(User).filter(User.username == username).first()

# ==============================
# Create Admin User (SAFE)
# ==============================
def create_default_admin():
    db = next(get_db())
    try:
        if not db.query(User).filter(User.username == "admin").first():
            hashed = pwd_context.hash(ADMIN_PASSWORD)
            admin_user = User(username="admin", hashed_password=hashed)
# TEMPORARY — DELETE AFTER LOGIN WORKS
db.query(User).delete()  # Deletes old admin
db.commit()
            db.add(admin_user)
            db.commit()
            logger.info("Admin user created with password from ADMIN_PASSWORD")
        else:
            logger.info("Admin user already exists")
    except Exception as e:
        logger.error(f"Failed to create admin user: {e}")
    finally:
        db.close()

create_default_admin()

# ==============================
# Routes
# ==============================
@app.get("/health")
def health():
    return {
        "status": "alive",
        "environment": settings.ENVIRONMENT,
        "dry_run": settings.DRY_RUN,
        "bot_status": settings.BOT_STATUS
    }

@app.get("/")
def root(user=Depends(manager)):
    return RedirectResponse("/dashboard" if user else "/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
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
    
    stats = {
        "total_trades": 0,
        "total_pnl": 0.0,
        "active_wallets": 0,
        "win_rate": 0.0
    }
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "bot_status": settings.BOT_STATUS,
        "dry_run": settings.DRY_RUN,
        "environment": settings.ENVIRONMENT.upper()
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
    logger.info("Polymarket Copytrader is now running!")
    logger.info(f"Mode: {settings.ENVIRONMENT} | DRY_RUN: {settings.DRY_RUN}")

# ==============================
# Railway PORT Fix
# ==============================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")