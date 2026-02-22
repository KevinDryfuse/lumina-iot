#!/usr/bin/env python3
"""
Create a new user for Lumina IoT.

Usage:
    docker compose exec api python scripts/create_user.py <username>
"""

import sys
import getpass

# Add parent directory to path for imports
sys.path.insert(0, "/app")

from src.db import SessionLocal, init_db, User
from src.auth import create_user, hash_password


def main():
    if len(sys.argv) < 2:
        print("Usage: python create_user.py <username>")
        sys.exit(1)

    username = sys.argv[1]

    # Get password securely
    password = getpass.getpass(f"Password for {username}: ")
    password_confirm = getpass.getpass("Confirm password: ")

    if password != password_confirm:
        print("Error: Passwords do not match")
        sys.exit(1)

    if len(password) < 8:
        print("Error: Password must be at least 8 characters")
        sys.exit(1)

    # Initialize database tables
    init_db()

    # Create user
    db = SessionLocal()
    try:
        # Check if user already exists
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"Error: User '{username}' already exists")
            sys.exit(1)

        user = create_user(db, username, password)
        print(f"✓ User '{user.username}' created successfully")

    finally:
        db.close()


if __name__ == "__main__":
    main()
