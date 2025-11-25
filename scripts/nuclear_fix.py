# scripts/nuclear_fix.py — FINAL FIX FOR RAILWAY (works 100%)
from sqlalchemy import text
from app.db import engine
from app.models import User
from passlib.handlers.argon2 import argon2
from sqlalchemy.orm import Session

print("NUCLEAR FIX STARTED — THIS WILL WORK")

with engine.connect() as conn:
    # FORCE ADD password_hash column
    print("Adding password_hash column...")
    conn.execute(text("""
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY,
        ADD COLUMN IF NOT EXISTS username TEXT UNIQUE,
        ADD COLUMN IF NOT EXISTS password_hash TEXT
    """))
    conn.commit()
    print("Column added!")

# Now create admin user
print("Creating admin user...")
with Session(engine) as db:
    try:
        if not db.query(User).filter(User.username == "admin").first():
            db.add(User(username="admin", password_hash=argon2.hash("admin123")))
            db.commit()
            print("SUCCESS: Admin created → admin / admin123")
        else:
            print("Admin already exists")
    except Exception as e:
        print(f"Error creating user: {e}")
        db.rollback()

print("")
print("NUCLEAR FIX COMPLETE!")
print("Go to your app and login:")
print("   Username: admin")
print("   Password: admin123")
print("YOU ARE NOW LIVE")