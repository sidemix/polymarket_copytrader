# scripts/fix_db.py — ONE-TIME FIX FOR RAILWAY
from sqlalchemy import text
from app.db import engine
from app.db import Base
from app.models import User, SettingsSingleton
from passlib.handlers.argon2 import argon2
from sqlalchemy.orm import Session

print("Fixing database schema...")

with engine.connect() as conn:
    # Add missing password_hash column
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT"))
    # Ensure other critical columns exist
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT UNIQUE"))
    conn.commit()
print("Missing columns added")

# Recreate all other tables safely
print("Ensuring all tables exist...")
Base.metadata.create_all(bind=engine)
print("All tables created/updated")

# Create admin user
with Session(engine) as db:
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        db.add(User(username="admin", password_hash=argon2.hash("admin123")))
        print("Admin created → username: admin | password: admin123")
    else:
        print("Admin already exists")

    if not db.query(SettingsSingleton).first():
        db.add(SettingsSingleton())
    db.commit()

print("")
print("DATABASE FIXED AND READY!")
print("Go to your app and login with:")
print("   Username: admin")
print("   Password: admin123")
print("")
print("You can delete this script now.")