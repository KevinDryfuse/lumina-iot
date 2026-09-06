"""
Database models and connection for Lumina IoT.

Uses SQLAlchemy with PostgreSQL.
"""

import os
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, text, JSON
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

    # ---- hardware configuration ----
    #
    # What used to be #defines in the sketch. The server owns these so that one
    # firmware image runs every strip in the house; the device caches whatever
    # it was last told, so it can boot correctly with the server down.
    #
    # NULL means "never been told" - the first announce adopts whatever the
    # device reports, and after that this row is the authority. That ordering is
    # deliberate: a strip already working should not be reconfigured by the mere
    # act of the server learning about it.
    led_count = Column(Integer, nullable=True)
    led_pin = Column(Integer, nullable=True)
    led_type = Column(String(20), nullable=True)
    led_order = Column(String(8), nullable=True)

    # Reported by the device on announce; what OTA decisions are made against.
    fw_version = Column(Integer, nullable=True)

    state = relationship("DeviceState", back_populates="device", uselist=False)

    def config_dict(self) -> dict | None:
        """The device's hardware configuration, or None if never set."""
        if self.led_count is None:
            return None
        return {
            "led_count": self.led_count,
            "pin": self.led_pin,
            "type": self.led_type,
            "order": self.led_order,
        }


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


class Effect(Base):
    """An effect stored as data rather than compiled into the firmware.

    See docs/RECIPES.md for the payload shape. The recipe column is the payload
    verbatim - deliberately not decomposed into columns, because the format will
    grow and the device stores the same JSON it was sent.
    """
    __tablename__ = "effects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    label = Column(String(50), nullable=True)
    category = Column(String(20), default="custom")
    recipe = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label or self.name.upper(),
            "category": self.category or "custom",
            "recipe": self.recipe,
        }


def get_db():
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the devices table already existed in production.
# create_all() only creates missing TABLES - it will not alter an existing one -
# and there is no migration tool in this project, so they are added by hand.
# ADD COLUMN IF NOT EXISTS makes this safe to run on every start.
_ADDED_COLUMNS = [
    ("led_count", "INTEGER"),
    ("led_pin", "INTEGER"),
    ("led_type", "VARCHAR(20)"),
    ("led_order", "VARCHAR(8)"),
    ("fw_version", "INTEGER"),
]


def init_db():
    """Create all tables, and add any columns a pre-existing table is missing."""
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        for name, coltype in _ADDED_COLUMNS:
            conn.execute(text(
                f"ALTER TABLE devices ADD COLUMN IF NOT EXISTS {name} {coltype}"
            ))
