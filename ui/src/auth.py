"""
Authentication module for the UI service.

Handles user login, sessions, and password hashing.
"""

import os
from typing import Optional

import bcrypt
from fastapi import Request, HTTPException, status, Depends
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.orm import Session

from .db import get_db, User

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
SESSION_COOKIE_NAME = "lumina_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

serializer = URLSafeTimedSerializer(SECRET_KEY)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_token(user_id: int) -> str:
    """Create a signed session token."""
    return serializer.dumps({"user_id": user_id})


def verify_session_token(token: str) -> Optional[dict]:
    """Verify and decode a session token."""
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Get the current logged-in user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    data = verify_session_token(token)
    if not data:
        return None

    return db.query(User).filter(User.id == data["user_id"]).first()


def require_auth(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency that requires authentication."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticate a user by username and password."""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_user(db: Session, username: str, password: str) -> User:
    """Create a new user."""
    password_hash = hash_password(password)
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
