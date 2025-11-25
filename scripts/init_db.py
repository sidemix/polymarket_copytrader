# scripts/init_db.py — ONE-CLICK DATABASE SETUP (Railway safe)
from sqlalchemy import inspect, text
from app.db import Base, engine
from app.models import User, SettingsSingleton
from passlib.handlers.argon2 import argon2
from sqlalchemy.orm import Session

print("Starting database initialization...")

inspector = inspect(engine)

# Step 1: Create tables if they don't exist
print("Checking for missing tables...")
Base.metadata.create_all(bind=engine)
print("All tables ensured")

# Step 2: Fix missing password_hash column (old DBs)
if inspector.has_table("users"):
    columns = [col["name"] for col in inspector.get_columns("users")]
    if "password_hash" not in columns:
        print("Adding missing 'password_hash' column...")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN password_hash TEXT"))
            conn.commit()
        print("password_hash column added")

# Step 3: Create admin user if not exists
with Session(engine) as db:
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", password_hash=argon2.hash("admin123")))
        print("Created admin user → username: admin | password: admin123")
    else:
        print("Admin user already exists")

    # Ensure settings row exists
    if not db.query(SettingsSingleton).first():
        db.add(SettingsSingleton())
        print("Created settings row")
    else:
        print("Settings row already exists")

    db.commit()

print("")
print("DATABASE FULLY INITIALIZED!")
print("Login at your Railway URL with:")
print("   Username: admin")
print("   Password: admin123")
print("")
print("You can now delete this script or keep it — it's safe to run anytime.")