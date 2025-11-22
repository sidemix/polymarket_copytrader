#!/usr/bin/env python3
"""
Create admin user script
Run this to create or update the admin user
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db
from app.auth import create_default_admin

def main():
    """Create default admin user"""
    print("Creating default admin user...")
    
    try:
        db = next(get_db())
        create_default_admin(db)
        print("✅ Default admin user created/verified!")
        print("   Username: admin")
        print("   Password: admin123")
        print("   ⚠️  Change the password in production!")
        
    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
