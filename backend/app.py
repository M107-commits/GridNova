from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_db
from .models import AuditEvent, GenerationRecord, Household, HouseholdSetting, Trade
from .schemas import (GenerationCreate, HouseholdEnergyUpdate, OfferCreate,
                      PurchaseRequest, ReviewRequest, SettingsUpdate,
                      SimulationRequest)

CITIES = [
    ("Aarav Mehta", "Bengaluru", "Indiranagar", 7200, 3100, "solar"),
    ("Kavya Reddy", "Hyderabad", "Jubilee Hills", 2600, 4800, "solar"),
    ("Ishaan Kulkarni", "Pune", "Baner", 5400, 3400, "solar"),
    ("Meera Iyer", "Chennai", "Adyar", 6100, 4200, "solar"),
    ("Arjun Sharma", "Jaipur", "Malviya Nagar", 4900, 2600, "solar"),
]

def money_paise(quantity_wh: int, price_paise_per_kwh: int) -> int:
    value = Decimal(quantity_wh) * Decimal(price_paise_per_kwh) / Decimal(1000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def audit(db: Session, role: str, action: str, entity: str, entity_id: int | None,
          household_id: int | None = None, details: dict | None = None):
    db.add(AuditEvent(household_id=household_id, actor_role=role, action=action,
                      entity_type=entity, entity_id=entity_id,
                      details=json.dumps(details or {}, sort_keys=True)))

def current_available(db: Session, household: Household) -> int:
    committed = db.scalar(select(func.coalesce(func.sum(Trade.quantity_wh), 0)).where(
        Trade.seller_id == household.id, Trade.status == "completed")) or 0
    return max(0, household.generation_wh - household.consumption_wh - int(committed))

def current_demand(db: Session, household: Household) -> int:
    bought = db.scalar(select(func.coalesce(func.sum(Trade.quantity_wh), 0)).where(
        Trade.buyer_id == household.id, Trade.status == "completed")) or 0
    return max(0, household.consumption_wh - household.generation_wh - int(bought))

def serialize_household(db: Session, h: Household):
    return {
        "id": h.id, "name": h.name, "city": h.city, "locality": h.locality,
        "source": h.source, "capacity_wh": h.capacity_wh,
        "generation_wh": h.generation_wh, "consumption_wh": h.consumption_wh,
        "surplus_wh": current_available(db, h), "eligible_demand_wh": current_demand(db, h),
        "preferred_price_paise": h.preferred_price_paise,
        "share_surplus": h.share_surplus,
    }

def serialize_trade(t: Trade, seller: Household, buyer: Household):
    return {"id": t.id, "seller_id": t.seller_id, "seller_name": seller.name,
            "seller_city": seller.city, "buyer_id": t.buyer_id, "buyer_name": buyer.name,
            "buyer_city": buyer.city, "quantity_wh": t.quantity_wh,
            "price_paise_per_kwh": t.price_paise_per_kwh, "total_paise": t.total_paise,
            "status": t.status, "created_at": t.created_at.isoformat(),
            "cancelled_at": t.cancelled_at.isoformat() if t.cancelled_at else None}

def role_context(x_demo_role: str = Header(default="homeowner"),
                 x_household_id: Optional[int] = Header(default=None)):
    # This is intentionally a presentation/demo role switcher, not authentication.
    role = x_demo_role.lower().strip()
    if role not in {"homeowner", "verifier", "admin"}:
        raise HTTPException(400, "Demo role must be homeowner, verifier, or admin")
    return {"role": role, "household_id": x_household_id}

def require_household(db: Session, household_id: int, ctx: dict, allow_admin: bool = False):
    if ctx["role"] != "admin" and ctx["household_id"] != household_id:
        raise HTTPException(403, "Select this household in the demo household selector to act for it")
    h = db.get(Household, household_id)
    if not h:
        raise HTTPException(404, "Household not found")
    return h

def require_reviewer(ctx: dict):
    if ctx["role"] not in {"verifier", "admin"}:
        raise HTTPException(403, "This action requires the demo verifier role")

def seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.scalar(select(func.count(Household.id))) == 0:
            for name, city, locality, generation, consumption, source in CITIES:
                h = Household(name=name, city=city, locality=locality, source=source,
                              capacity_wh=8000, generation_wh=generation,
                              consumption_wh=consumption, preferred_price_paise=1200,
                              share_surplus=True)
                db.add(h)
            db.flush()
            db.add_all([
                GenerationRecord(household_id=1, quantity_wh=7200, source="solar", status="pending"),
                GenerationRecord(household_id=2, quantity_wh=2600, source="solar",
                                 certificate_reference="DEMO-HYD-001", status="pending"),
                GenerationRecord(household_id=3, quantity_wh=5400, source="solar", status="verified",
                                 reviewed_by="verifier"),
                GenerationRecord(household_id=4, quantity_wh=6100, source="solar", status="pending"),
                GenerationRecord(household_id=5, quantity_wh=4900, source="solar", status="verified",
                                 reviewed_by="verifier"),
            ])
            db.commit()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed()
    yield

app = FastAPI(title="GridNova API", version="1.0.0",
              description="Fictional peer-to-peer renewable energy marketplace simulation.",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

@app.get("/api/health")
def health():
    return {"status": "ok", "simulation": True}

@app.get("/api/households")
def households(db: Session = Depends(get_db)):
    return [serialize_household(db, h) for h in db.scalars(select(Household).order_by(Household.city))]

@app.patch("/api/households/{household_id}/energy")
def update_energy(household_id: int, payload: HouseholdEnergyUpdate,
                  ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    h = require_household(db, household_id, ctx)
    h.generation_wh = payload.generation_wh
    h.consumption_wh = payload.consumption_wh
    if payload.preferred_price_paise is not None:
        h.preferred_price_paise = payload.preferred_price_paise
    audit(db, ctx["role"], "energy_profile_updated", "household", h.id, h.id,
          {"generation_wh": h.generation_wh, "consumption_wh": h.consumption_wh})
    db.commit()
    return serialize_household(db, h)

@app.get("/api/dashboard")
def dashboard(household_id: int | None = Query(default=None), ctx: dict = Depends(role_context),
              db: Session = Depends(get_db)):
    selected_id = household_id or ctx["household_id"] or 1
    selected = db.get(Household, selected_id)
    if not selected:
        raise HTTPException(404, "Household not found")
    all_homes = list(db.scalars(select(Household)))
    available = sum(current_available(db, h) for h in all_homes)
    trade_rows = list(db.execute(select(Trade, Household, Household).join(
        Household, Trade.seller_id == Household.id).join(
        Household, Trade.buyer_id == Household.id)))
    # Keep dashboard activity derived from the persistent trade ledger.
    recent = []
    for t in db.scalars(select(Trade).order_by(Trade.created_at.desc()).limit(5)):
        seller, buyer = db.get(Household, t.seller_id), db.get(Household, t.buyer_id)
        recent.append(serialize_trade(t, seller, buyer))
    return {
        "simulation": True, "household": serialize_household(db, selected),
        "totals": {"generation_wh": sum(h.generation_wh for h in all_homes),
                   "consumption_wh": sum(h.consumption_wh for h in all_homes),
                   "available_surplus_wh": available, "households": len(all_homes),
                   "completed_trades": db.scalar(select(func.count(Trade.id)).where(Trade.status == "completed")) or 0,
                   "estimated_co2_grams": int(sum(h.generation_wh for h in all_homes) * 0.55)},
        "recent_trades": recent,
    }

@app.get("/api/offers")
def offers(household_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Household).where(Household.share_surplus.is_(True)).order_by(Household.preferred_price_paise)
    if household_id is not None:
        stmt = stmt.where(Household.id != household_id)
    results = []
    for h in db.scalars(stmt):
        qty = current_available(db, h)
        if qty:
            results.append({"id": h.id, "household_id": h.id, "seller_name": h.name,
                "city": h.city, "locality": h.locality, "source": h.source,
                "quantity_wh": qty, "price_paise_per_kwh": h.preferred_price_paise})
    return results

@app.post("/api/offers", status_code=201)
def create_offer(payload: OfferCreate, ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    h = require_household(db, payload.household_id, ctx)
    if not h.share_surplus:
        raise HTTPException(409, "Surplus sharing is paused for this household")
    if payload.quantity_wh > current_available(db, h):
        raise HTTPException(409, "Offer quantity exceeds available surplus")
    h.preferred_price_paise = payload.price_paise_per_kwh
    audit(db, ctx["role"], "offer_listed", "household", h.id, h.id,
          {"quantity_wh": payload.quantity_wh, "price_paise_per_kwh": payload.price_paise_per_kwh})
    db.commit()
    return {"household_id": h.id, "available_quantity_wh": current_available(db, h),
            "price_paise_per_kwh": h.preferred_price_paise}

@app.post("/api/offers/{offer_id}/purchase", status_code=201)
def purchase_offer(offer_id: int, payload: PurchaseRequest,
                   ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    # BEGIN IMMEDIATE serializes competing writers in SQLite before quantities are read.
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        buyer = require_household(db, payload.buyer_household_id, ctx)
        seller = db.get(Household, offer_id)
        if not seller or not seller.share_surplus:
            raise HTTPException(404, "Offer not found or no longer available")
        if seller.id == buyer.id:
            raise HTTPException(409, "A household cannot purchase its own surplus")
        if payload.quantity_wh > current_available(db, seller):
            raise HTTPException(409, "Purchase exceeds the seller's available surplus")
        if payload.quantity_wh > current_demand(db, buyer):
            raise HTTPException(409, "Purchase exceeds this household's eligible demand")
        duplicate = db.scalar(select(Trade.id).where(
            Trade.seller_id == seller.id, Trade.buyer_id == buyer.id,
            Trade.quantity_wh == payload.quantity_wh, Trade.status == "completed"))
        if duplicate:
            raise HTTPException(409, "An identical active commitment already exists")
        total = money_paise(payload.quantity_wh, seller.preferred_price_paise)
        trade = Trade(seller_id=seller.id, buyer_id=buyer.id,
                      quantity_wh=payload.quantity_wh,
                      price_paise_per_kwh=seller.preferred_price_paise,
                      total_paise=total, status="completed")
        db.add(trade)
        db.flush()
        audit(db, ctx["role"], "trade_purchased", "trade", trade.id, buyer.id,
              {"seller_id": seller.id, "quantity_wh": payload.quantity_wh,
               "total_paise": total})
        db.commit()
        return serialize_trade(trade, seller, buyer)
    except Exception:
        db.rollback()
        raise

@app.get("/api/trades")
def trades(household_id: int | None = None, status: str | None = None,
           search: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Trade).order_by(Trade.created_at.desc())
    if household_id is not None:
        stmt = stmt.where((Trade.seller_id == household_id) | (Trade.buyer_id == household_id))
    if status:
        stmt = stmt.where(Trade.status == status)
    rows = []
    for t in db.scalars(stmt):
        seller, buyer = db.get(Household, t.seller_id), db.get(Household, t.buyer_id)
        item = serialize_trade(t, seller, buyer)
        if search and search.lower() not in json.dumps(item).lower():
            continue
        rows.append(item)
    return rows

@app.post("/api/trades/{trade_id}/cancel")
def cancel_trade(trade_id: int, ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        trade = db.get(Trade, trade_id)
        if not trade:
            raise HTTPException(404, "Trade not found")
        if ctx["role"] != "admin" and ctx["household_id"] not in {trade.seller_id, trade.buyer_id}:
            raise HTTPException(403, "Only a participating household can cancel this trade")
        if trade.status != "completed":
            raise HTTPException(409, "Only completed demo trades can be cancelled")
        trade.status = "cancelled"
        trade.cancelled_at = datetime.now(timezone.utc)
        audit(db, ctx["role"], "trade_cancelled", "trade", trade.id, ctx["household_id"],
              {"quantity_wh_released": trade.quantity_wh})
        seller, buyer = db.get(Household, trade.seller_id), db.get(Household, trade.buyer_id)
        db.commit()
        return serialize_trade(trade, seller, buyer)
    except Exception:
        db.rollback()
        raise

@app.get("/api/generation-records")
def generation_records(household_id: int | None = None, status: str | None = None,
                       db: Session = Depends(get_db)):
    stmt = select(GenerationRecord).order_by(GenerationRecord.recorded_at.desc())
    if household_id:
        stmt = stmt.where(GenerationRecord.household_id == household_id)
    if status:
        stmt = stmt.where(GenerationRecord.status == status)
    return [{"id": r.id, "household_id": r.household_id,
             "household_name": db.get(Household, r.household_id).name,
             "quantity_wh": r.quantity_wh, "source": r.source,
             "certificate_reference": r.certificate_reference,
             "recorded_at": r.recorded_at.isoformat(), "status": r.status,
             "reviewed_by": r.reviewed_by, "review_note": r.review_note}
            for r in db.scalars(stmt)]

@app.post("/api/generation-records", status_code=201)
def add_generation_record(payload: GenerationCreate, ctx: dict = Depends(role_context),
                          db: Session = Depends(get_db)):
    h = require_household(db, payload.household_id, ctx)
    ref = payload.certificate_reference.strip() if payload.certificate_reference else None
    if ref and db.scalar(select(GenerationRecord.id).where(
            GenerationRecord.certificate_reference == ref)):
        raise HTTPException(409, "Certificate reference has already been recorded")
    record = GenerationRecord(household_id=h.id, quantity_wh=payload.quantity_wh,
                              source=payload.source, certificate_reference=ref)
    db.add(record)
    try:
        db.flush()
        audit(db, ctx["role"], "generation_record_added", "generation_record", record.id, h.id,
              {"quantity_wh": record.quantity_wh, "source": record.source})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Certificate reference has already been recorded")
    return {"id": record.id, "status": record.status}

def review_record(record_id: int, payload: ReviewRequest, decision: str,
                  ctx: dict, db: Session):
    require_reviewer(ctx)
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        record = db.get(GenerationRecord, record_id)
        if not record:
            raise HTTPException(404, "Generation record not found")
        if record.status != "pending":
            raise HTTPException(409, "Only pending generation records can be reviewed")
        record.status = decision
        record.reviewed_by = ctx["role"]
        record.review_note = payload.note
        audit(db, ctx["role"], "generation_" + decision, "generation_record",
              record.id, record.household_id, {"note": payload.note})
        db.commit()
        return {"id": record.id, "status": record.status, "review_note": record.review_note}
    except Exception:
        db.rollback()
        raise

@app.post("/api/generation-records/{record_id}/verify")
def verify_record(record_id: int, payload: ReviewRequest = ReviewRequest(),
                  ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    return review_record(record_id, payload, "verified", ctx, db)

@app.post("/api/generation-records/{record_id}/reject")
def reject_record(record_id: int, payload: ReviewRequest = ReviewRequest(),
                  ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    return review_record(record_id, payload, "rejected", ctx, db)

@app.get("/api/audit-events")
def audit_events(household_id: int | None = None, limit: int = Query(default=100, ge=1, le=500),
                 db: Session = Depends(get_db)):
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if household_id is not None:
        stmt = stmt.where(AuditEvent.household_id == household_id)
    return [{"id": e.id, "household_id": e.household_id, "actor_role": e.actor_role,
             "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id,
             "details": json.loads(e.details), "created_at": e.created_at.isoformat()}
            for e in db.scalars(stmt)]

@app.get("/api/analytics")
def analytics(db: Session = Depends(get_db)):
    homes = list(db.scalars(select(Household)))
    completed = list(db.scalars(select(Trade).where(Trade.status == "completed")))
    sold_wh = sum(t.quantity_wh for t in completed)
    return {"simulation": True, "households": len(homes),
            "generation_wh": sum(h.generation_wh for h in homes),
            "consumption_wh": sum(h.consumption_wh for h in homes),
            "surplus_wh": sum(current_available(db, h) for h in homes),
            "traded_wh": sold_wh, "trade_count": len(completed),
            "transaction_value_paise": sum(t.total_paise for t in completed),
            "estimated_co2_avoided_grams": int(sold_wh * 0.55),
            "city_breakdown": [{"city": city,
                "generation_wh": sum(h.generation_wh for h in homes if h.city == city),
                "consumption_wh": sum(h.consumption_wh for h in homes if h.city == city)}
                for city in sorted({h.city for h in homes})]}

@app.post("/api/simulations/run")
def run_simulation(payload: SimulationRequest, ctx: dict = Depends(role_context),
                   db: Session = Depends(get_db)):
    homes = list(db.scalars(select(Household).where(
        Household.id.in_(payload.household_ids) if payload.household_ids else True)))
    if not homes:
        raise HTTPException(400, "No households selected")
    generation = sum(h.capacity_wh for h in homes) * payload.solar_percent // 100
    demand = sum(h.consumption_wh for h in homes) * payload.demand_percent // 100
    shareable = max(0, generation - demand)
    result = {"households": len(homes), "solar_percent": payload.solar_percent,
              "demand_percent": payload.demand_percent, "generation_wh": generation,
              "demand_wh": demand, "share_potential_wh": shareable,
              "estimated_evening_households": shareable // 2500,
              "simulation_only": True}
    audit(db, ctx["role"], "simulation_run", "simulation", None, ctx["household_id"], result)
    db.commit()
    return result

@app.get("/api/settings/{household_id}")
def get_settings(household_id: int, ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    h = require_household(db, household_id, ctx)
    setting = db.scalar(select(HouseholdSetting).where(HouseholdSetting.household_id == h.id))
    if setting:
        return {"household_id": h.id, "preferred_price_paise": setting.preferred_price_paise,
                "share_surplus": setting.share_surplus}
    return {"household_id": h.id, "preferred_price_paise": h.preferred_price_paise,
            "share_surplus": h.share_surplus}

@app.put("/api/settings/{household_id}")
def update_settings(household_id: int, payload: SettingsUpdate,
                   ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    h = require_household(db, household_id, ctx)
    setting = db.scalar(select(HouseholdSetting).where(HouseholdSetting.household_id == h.id))
    if not setting:
        setting = HouseholdSetting(household_id=h.id)
        db.add(setting)
    setting.preferred_price_paise = payload.preferred_price_paise
    setting.share_surplus = payload.share_surplus
    h.preferred_price_paise = payload.preferred_price_paise
    h.share_surplus = payload.share_surplus
    audit(db, ctx["role"], "settings_updated", "household", h.id, h.id,
          {"preferred_price_paise": payload.preferred_price_paise,
           "share_surplus": payload.share_surplus})
    db.commit()
    return {"household_id": h.id, "preferred_price_paise": h.preferred_price_paise,
            "share_surplus": h.share_surplus}

@app.post("/api/reset")
def reset_demo(ctx: dict = Depends(role_context), db: Session = Depends(get_db)):
    if ctx["role"] != "admin":
        raise HTTPException(403, "Choose the demo admin role to reset application data")
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        db.query(Trade).delete()
        db.query(GenerationRecord).delete()
        db.query(HouseholdSetting).delete()
        db.query(AuditEvent).delete()
        db.query(Household).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    seed()
    with SessionLocal() as check:
        audit(check, "admin", "demo_reset", "application", None, None, {"seed_households": len(CITIES)})
        check.commit()
    return {"status": "reset", "households": len(CITIES), "simulation": True}

@app.get("/api/trades.csv")
def export_trades(household_id: int | None = None, db: Session = Depends(get_db)):
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["trade_id", "seller", "buyer", "quantity_wh", "price_paise_per_kwh",
                     "total_paise", "status", "created_at", "cancelled_at"])
    stmt = select(Trade).order_by(Trade.created_at.desc())
    if household_id:
        stmt = stmt.where((Trade.seller_id == household_id) | (Trade.buyer_id == household_id))
    for t in db.scalars(stmt):
        writer.writerow([t.id, db.get(Household, t.seller_id).name, db.get(Household, t.buyer_id).name,
                         t.quantity_wh, t.price_paise_per_kwh, t.total_paise, t.status,
                         t.created_at.isoformat(), t.cancelled_at.isoformat() if t.cancelled_at else ""])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=gridnova-trades.csv"})

@app.get("/")
def index():
    path = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
    if path.exists():
        return FileResponse(path)
    return {"name": "GridNova API", "docs": "/docs", "simulation": True}
