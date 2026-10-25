from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Household(Base):
    __tablename__ = "households"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    city = Column(String(50), nullable=False)
    locality = Column(String(80), nullable=False)
    source = Column(String(30), nullable=False, default="solar")
    capacity_wh = Column(Integer, nullable=False, default=5000)
    generation_wh = Column(Integer, nullable=False, default=0)
    offer_limit_wh = Column(Integer, nullable=False, default=100000)
    consumption_wh = Column(Integer, nullable=False, default=0)
    preferred_price_paise = Column(Integer, nullable=False, default=1200)
    share_surplus = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    records = relationship("GenerationRecord", back_populates="household", cascade="all, delete-orphan")
    offers = relationship("Offer", back_populates="household", cascade="all, delete-orphan")

class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (CheckConstraint("quantity_wh > 0"), CheckConstraint("price_paise_per_kwh >= 0"))
    id = Column(Integer, primary_key=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    quantity_wh = Column(Integer, nullable=False)
    price_paise_per_kwh = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    household = relationship("Household", back_populates="offers")

class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (CheckConstraint("quantity_wh > 0"), CheckConstraint("price_paise_per_kwh >= 0"))
    id = Column(Integer, primary_key=True)
    offer_id = Column(Integer, ForeignKey("offers.id"), nullable=True)
    idempotency_key = Column(String(120), nullable=True, unique=True)
    seller_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    quantity_wh = Column(Integer, nullable=False)
    price_paise_per_kwh = Column(Integer, nullable=False)
    total_paise = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="completed")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

class GenerationRecord(Base):
    __tablename__ = "generation_records"
    __table_args__ = (UniqueConstraint("certificate_reference", name="uq_generation_certificate_reference"), CheckConstraint("quantity_wh > 0"))
    id = Column(Integer, primary_key=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    quantity_wh = Column(Integer, nullable=False)
    source = Column(String(30), nullable=False)
    certificate_reference = Column(String(100), nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    reviewed_by = Column(String(50), nullable=True)
    review_note = Column(Text, nullable=True)
    household = relationship("Household", back_populates="records")

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)
    actor_role = Column(String(30), nullable=False)
    action = Column(String(60), nullable=False)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class TradeLedgerEntry(Base):
    """Hash-linked trade event; SQLite remains the authoritative application store."""
    __tablename__ = "trade_ledger_entries"
    id = Column(Integer, primary_key=True)
    event_json = Column(Text, nullable=False)
    previous_hash = Column(String(64), nullable=False)
    entry_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

class HouseholdSetting(Base):
    __tablename__ = "household_settings"
    id = Column(Integer, primary_key=True)
    household_id = Column(Integer, ForeignKey("households.id"), unique=True, nullable=False)
    preferred_price_paise = Column(Integer, nullable=False, default=1200)
    share_surplus = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class UserAccount(Base):
    __tablename__ = "user_accounts"
    id = Column(Integer, primary_key=True)
    household_id = Column(Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(254), nullable=False, unique=True, index=True)
    display_name = Column(String(100), nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(20), nullable=False, default="homeowner")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash = Column(String(64), primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

