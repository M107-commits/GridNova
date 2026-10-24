from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Household(Base):
    __tablename__ = "households"
    id = __import__("sqlalchemy").Column(Integer, primary_key=True)
    name = __import__("sqlalchemy").Column(String(100), nullable=False)
    city = __import__("sqlalchemy").Column(String(50), nullable=False)
    locality = __import__("sqlalchemy").Column(String(80), nullable=False)
    source = __import__("sqlalchemy").Column(String(30), nullable=False, default="solar")
    capacity_wh = __import__("sqlalchemy").Column(Integer, nullable=False, default=5000)
    generation_wh = __import__("sqlalchemy").Column(Integer, nullable=False, default=0)
    consumption_wh = __import__("sqlalchemy").Column(Integer, nullable=False, default=0)
    preferred_price_paise = __import__("sqlalchemy").Column(Integer, nullable=False, default=1200)
    share_surplus = __import__("sqlalchemy").Column(Boolean, nullable=False, default=True)
    created_at = __import__("sqlalchemy").Column(DateTime(timezone=True), default=utcnow, nullable=False)
    records = relationship("GenerationRecord", back_populates="household", cascade="all, delete-orphan")

class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (CheckConstraint("quantity_wh > 0"), CheckConstraint("price_paise_per_kwh >= 0"))
    id = __import__("sqlalchemy").Column(Integer, primary_key=True)
    seller_id = __import__("sqlalchemy").Column(Integer, ForeignKey("households.id"), nullable=False)
    buyer_id = __import__("sqlalchemy").Column(Integer, ForeignKey("households.id"), nullable=False)
    quantity_wh = __import__("sqlalchemy").Column(Integer, nullable=False)
    price_paise_per_kwh = __import__("sqlalchemy").Column(Integer, nullable=False)
    total_paise = __import__("sqlalchemy").Column(Integer, nullable=False)
    status = __import__("sqlalchemy").Column(String(20), nullable=False, default="completed")
    created_at = __import__("sqlalchemy").Column(DateTime(timezone=True), default=utcnow, nullable=False)
    cancelled_at = __import__("sqlalchemy").Column(DateTime(timezone=True), nullable=True)

class GenerationRecord(Base):
    __tablename__ = "generation_records"
    __table_args__ = (UniqueConstraint("certificate_reference", name="uq_generation_certificate_reference"), CheckConstraint("quantity_wh > 0"))
    id = __import__("sqlalchemy").Column(Integer, primary_key=True)
    household_id = __import__("sqlalchemy").Column(Integer, ForeignKey("households.id"), nullable=False)
    quantity_wh = __import__("sqlalchemy").Column(Integer, nullable=False)
    source = __import__("sqlalchemy").Column(String(30), nullable=False)
    certificate_reference = __import__("sqlalchemy").Column(String(100), nullable=True)
    recorded_at = __import__("sqlalchemy").Column(DateTime(timezone=True), default=utcnow, nullable=False)
    status = __import__("sqlalchemy").Column(String(20), nullable=False, default="pending")
    reviewed_by = __import__("sqlalchemy").Column(String(50), nullable=True)
    review_note = __import__("sqlalchemy").Column(Text, nullable=True)
    household = relationship("Household", back_populates="records")

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = __import__("sqlalchemy").Column(Integer, primary_key=True)
    household_id = __import__("sqlalchemy").Column(Integer, ForeignKey("households.id"), nullable=True)
    actor_role = __import__("sqlalchemy").Column(String(30), nullable=False)
    action = __import__("sqlalchemy").Column(String(60), nullable=False)
    entity_type = __import__("sqlalchemy").Column(String(40), nullable=False)
    entity_id = __import__("sqlalchemy").Column(Integer, nullable=True)
    details = __import__("sqlalchemy").Column(Text, nullable=False, default="{}")
    created_at = __import__("sqlalchemy").Column(DateTime(timezone=True), default=utcnow, nullable=False)

class HouseholdSetting(Base):
    __tablename__ = "household_settings"
    id = __import__("sqlalchemy").Column(Integer, primary_key=True)
    household_id = __import__("sqlalchemy").Column(Integer, ForeignKey("households.id"), unique=True, nullable=False)
    preferred_price_paise = __import__("sqlalchemy").Column(Integer, nullable=False, default=1200)
    share_surplus = __import__("sqlalchemy").Column(Boolean, nullable=False, default=True)
    updated_at = __import__("sqlalchemy").Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
