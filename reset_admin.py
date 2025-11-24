# reset_admin.py — RUN THIS ONCE
import os
from app.db import SessionLocal, engine, Base
from app.models import User
from passlib.context import CryptContext

# Force create tables
Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
db = SessionLocal()

# DELETE ANY OLD USERS
db.query(User).delete()
db.commit()

# CREATE NEW ADMIN WITH PASSWORD "1234"
hashed = pwd_context.hash("1234")
admin = User(username="admin", hashed_password=hashed)
db.add(admin)
db.commit()
db.close()

print("SUCCESS: Admin user created!")
print("Username: admin")
print("Password: 1234")
print("You can now login at your domain!")