"""
Database models and connection for Lumina IoT.

Uses SQLAlchemy with PostgreSQL.
"""

import os
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://lumina:changeme@localhost:5432/lumina")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """User account for authentication."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Device(Base):
    """Registered IoT device."""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(100), unique=True, nullable=False, index=True)
    friendly_name = Column(String(100), nullable=True)
    device_type = Column(String(50), default="led_strip")
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    state = relationship("DeviceState", back_populates="device", uselist=False)


class DeviceState(Base):
    """Current state of a device (persisted for recovery)."""
    __tablename__ = "device_state"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(100), ForeignKey("devices.device_id"), unique=True, nullable=False)
    brightness = Column(Integer, default=100)
    color_r = Column(Integer, default=255)
    color_g = Column(Integer, default=255)
    color_b = Column(Integer, default=255)
    effect = Column(String(50), default="none")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = relationship("Device", back_populates="state")


def get_db():
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)
