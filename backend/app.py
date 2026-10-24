"""GridNova - SIMULATED P2P renewable energy marketplace (India). Not a real exchange.
Units: energy stored as integer Wh, prices as integer paise/kWh, money as integer paise.
amount_paise = round_half_up(qty_wh * price_paise / 1000)  (Decimal, never float)."""
import os, re, json, datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Text, text
from sqlalchemy.orm import declarative_base, sessionmaker

DB = os.environ.get("GRIDNOVA_DB", str(Path(__file__).parent / "gridnova.db"))
engine = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False, "timeout": 30})
Session = sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()
CFG = dict(max_price_paise=1000, grid_tariff_paise=800, export_baseline_paise=250, fee_paise=0, currency="INR")
now = lambda: dt.datetime.utcnow()


class Household(Base):
    __tablename__ = "households"
    id = Column(Integer, primary_key=True); name = Column(String, unique=True); city = Column(String)
    gen_wh = Column(Integer, default=0); cons_wh = Column(Integer, default=0)


class GenRecord(Base):
    __tablename__ = "generation_records"
    id = Column(Integer, primary_key=True); household_id = Column(Integer, ForeignKey("households.id"), index=True)
    period = Column(String); qty_wh = Column(Integer); meter_ref = Column(String)
    status = Column(String, default="pending")  # pending|verified|rejected|flagged
    cert_ref = Column(String, unique=True, nullable=True)  # DB-level duplicate certificate prevention


class Offer(Base):
    __tablename__ = "energy_offers"
    id = Column(Integer, primary_key=True); seller_id = Column(Integer, ForeignKey("households.id"), index=True)
    qty_wh = Column(Integer); remaining_wh = Column(Integer); price_paise = Column(Integer)
    slot = Column(String); status = Column(String, default="open", index=True); created = Column(DateTime, default=now)


class Trade(Base):
    __tablename__ = "energy_trades"
    id = Column(Integer, primary_key=True); offer_id = Column(Integer, ForeignKey("energy_offers.id"), index=True)
    buyer_id = Column(Integer, ForeignKey("households.id"), index=True); seller_id = Column(Integer, ForeignKey("households.id"))
    qty_wh = Column(Integer); price_paise = Column(Integer); amount_paise = Column(Integer)
    status = Column(String, default="completed", index=True); gen_record_id = Column(Integer, ForeignKey("generation_records.id"))
    created = Column(DateTime, default=now)


class Audit(Base):  # append-only by convention: application code only inserts
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True); ts = Column(DateTime, default=now); type = Column(String, index=True)
    entity = Column(String); details = Column(Text)


def err(code, msg): raise HTTPException(code, msg)
def audit(db, typ, entity, **d): db.add(Audit(type=typ, entity=entity, details=json.dumps(d)))


def conv(v, mult, label):
    d = Decimal(str(v)) * mult
    if d != d.to_integral_value(): err(422, f"{label} supports at most {'3' if mult == 1000 else '2'} decimal places")
    return int(d)


def amount(q_wh, p): return int((Decimal(q_wh) * Decimal(p) / 1000).quantize(Decimal(1), ROUND_HALF_UP))
def tid(t): return f"TXN-{t.id:04d}"
def surplus(h): return max(0, h.gen_wh - h.cons_wh)  # per simulated day
def deficit(h): return max(0, h.cons_wh - h.gen_wh)


def committed(db, hid):
    o = sum(x.remaining_wh for x in db.query(Offer).filter_by(seller_id=hid, status="open"))
    s = sum(x.qty_wh for x in db.query(Trade).filter_by(seller_id=hid, status="completed"))
    return o, s


def available(db, h): o, s = committed(db, h.id); return max(0, surplus(h) - o - s)
def bought(db, hid): return sum(x.qty_wh for x in db.query(Trade).filter_by(buyer_id=hid, status="completed"))
def demand_left(db, h): return max(0, deficit(h) - bought(db, h.id))


def need_role(actual, want):
    if actual != want:
        err(403, f"Demo role '{want}' required (current: '{actual}'). Demo-only role switching, not real authentication.")


SEED = [("Hyderabad Solar Home", "Hyderabad", 20000, 8000), ("Bengaluru Green Apartment", "Bengaluru", 12000, 9000),
        ("Pune Eco Household", "Pune", 6000, 14000), ("Chennai Solar Studio", "Chennai", 5000, 11000),
        ("Jaipur Renewable Home", "Jaipur", 18000, 10000)]


def seed():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with Session.begin() as db:
        for i, (n, c, g, k) in enumerate(SEED, 1):
            db.add(Household(id=i, name=n, city=c, gen_wh=g, cons_wh=k))
            ver = i in (1, 5)
            db.add(GenRecord(id=i, household_id=i, period="Simulated day 2026-10-23", qty_wh=g, meter_ref=f"SIM-METER-{c[:3].upper()}-0001",
                             status="verified" if ver else "pending", cert_ref=f"REC-SIM-{c[:3].upper()}-001" if ver else None))
        audit(db, "seed", "system", note="Deterministic demo data loaded")


app = FastAPI(title="GridNova API (simulation)", version="1.0")


@app.on_event("startup")
def _init():
    Base.metadata.create_all(engine)
    with Session() as db:
        empty = not db.query(Household).count()
    if empty: seed()


def hh_out(db, h):
    o, s = committed(db, h.id)
    return dict(id=h.id, name=h.name, city=h.city, generation_wh=h.gen_wh, consumption_wh=h.cons_wh, surplus_wh=surplus(h), deficit_wh=deficit(h),
                listed_wh=o, sold_wh=s, available_wh=available(db, h), purchased_wh=bought(db, h.id), demand_left_wh=demand_left(db, h))


def offer_out(db, o):
    h = db.get(Household, o.seller_id); g = db.query(GenRecord).filter_by(household_id=h.id).first()
    return dict(id=o.id, seller_id=h.id, seller=h.name, city=h.city, qty_wh=o.qty_wh, remaining_wh=o.remaining_wh, price_paise=o.price_paise,
                slot=o.slot, status=o.status, verification=g.status if g else "none", created=o.created.isoformat())


def trade_out(db, t):
    g = db.get(GenRecord, t.gen_record_id)
    return dict(id=t.id, tid=tid(t), offer_id=t.offer_id, buyer_id=t.buyer_id, seller_id=t.seller_id, buyer=db.get(Household, t.buyer_id).name,
                seller=db.get(Household, t.seller_id).name, qty_wh=t.qty_wh, price_paise=t.price_paise, amount_paise=t.amount_paise, status=t.status,
                gen_record_id=t.gen_record_id, verification=g.status if g else "none", settlement_ref=f"SIM-SET-{t.id:04d}", created=t.created.isoformat())


class OfferIn(BaseModel):
    seller_id: int; quantity_kwh: float; price_inr_per_kwh: float; slot: str = "Simulated day, 10:00-16:00"
class OfferPatch(BaseModel):
    price_inr_per_kwh: Optional[float] = None; cancel: bool = False
class PurchaseIn(BaseModel):
    buyer_id: int; quantity_kwh: float
class EnergyIn(BaseModel):
    generation_kwh: Optional[float] = None; consumption_kwh: Optional[float] = None
class GenIn(BaseModel):
    household_id: int; period: str; quantity_kwh: float; meter_ref: str
class VerifyIn(BaseModel):
    cert_ref: str
class SimIn(BaseModel):
    households: int = 20; producer_share_pct: float = 40; generation_kwh: float = 8; demand_kwh: float = 5
    capacity_kwh: float = 30; price_inr: float = 5; battery_kwh: float = 0; battery_soc_kwh: float = 0; battery_rate_kwh: float = 5


@app.post("/api/reset")
def reset(): seed(); return {"ok": True}
@app.get("/api/config")
def config(): return CFG


@app.get("/api/households")
def households():
    with Session() as db: return [hh_out(db, h) for h in db.query(Household).order_by(Household.id)]


@app.patch("/api/households/{hid}/energy")
def set_energy(hid: int, b: EnergyIn):
    with Session.begin() as db:
        h = db.get(Household, hid) or err(404, "Household not found")
        g = h.gen_wh if b.generation_kwh is None else conv(b.generation_kwh, 1000, "Generation")
        c = h.cons_wh if b.consumption_kwh is None else conv(b.consumption_kwh, 1000, "Consumption")
        if g < 0 or c < 0: err(422, "Generation and consumption must be nonnegative")
        o, s = committed(db, hid)
        if max(0, g - c) < o + s: err(409, "New surplus would fall below energy already listed or sold; cancel offers first")
        if max(0, c - g) < bought(db, hid): err(409, "New demand would fall below energy already purchased")
        h.gen_wh, h.cons_wh = g, c
        rec = db.query(GenRecord).filter_by(household_id=hid).first()
        if rec and rec.qty_wh != g:
            rec.qty_wh = g
            if rec.status != "pending": rec.status = "pending"; audit(db, "verification_reset", f"GEN-{rec.id}", reason="generation changed")
        audit(db, "energy_updated", f"HH-{hid}", generation_wh=g, consumption_wh=c)
        return hh_out(db, h)


@app.get("/api/offers")
def offers():
    with Session() as db: return [offer_out(db, o) for o in db.query(Offer).order_by(Offer.id.desc())]


@app.post("/api/offers", status_code=201)
def create_offer(b: OfferIn, x_demo_role: str = Header("seller")):
    need_role(x_demo_role, "seller")
    q = conv(b.quantity_kwh, 1000, "Quantity"); p = conv(b.price_inr_per_kwh, 100, "Price")
    if q <= 0: err(422, "Quantity must be greater than zero")
    if p < 0 or p > CFG["max_price_paise"]: err(422, f"Price must be between 0 and ₹{CFG['max_price_paise'] / 100:.2f}/kWh (configured cap)")
    with Session.begin() as db:
        h = db.get(Household, b.seller_id) or err(404, "Seller not found")
        if q > available(db, h): err(409, f"Only {available(db, h) / 1000:.3f} kWh of uncommitted surplus is available")
        o = Offer(seller_id=h.id, qty_wh=q, remaining_wh=q, price_paise=p, slot=b.slot); db.add(o); db.flush()
        audit(db, "offer_created", f"OFFER-{o.id}", seller=h.name, qty_wh=q, price_paise=p)
        return offer_out(db, o)


@app.patch("/api/offers/{oid}")
def patch_offer(oid: int, b: OfferPatch, x_demo_role: str = Header("seller")):
    need_role(x_demo_role, "seller")
    with Session.begin() as db:
        o = db.get(Offer, oid) or err(404, "Offer not found")
        if o.status != "open": err(409, f"Offer is {o.status}; only open offers can change")
        if b.cancel: o.status = "cancelled"; audit(db, "offer_cancelled", f"OFFER-{o.id}", released_wh=o.remaining_wh)
        elif b.price_inr_per_kwh is not None:
            p = conv(b.price_inr_per_kwh, 100, "Price")
            if p < 0 or p > CFG["max_price_paise"]: err(422, "Price outside configured range")
            audit(db, "offer_price_changed", f"OFFER-{o.id}", old=o.price_paise, new=p); o.price_paise = p
        return offer_out(db, o)


@app.post("/api/offers/{oid}/purchase", status_code=201)
def purchase(oid: int, b: PurchaseIn, x_demo_role: str = Header("buyer")):
    need_role(x_demo_role, "buyer")
    q = conv(b.quantity_kwh, 1000, "Quantity")
    if q <= 0: err(422, "Quantity must be greater than zero")
    with Session.begin() as db:
        o = db.get(Offer, oid) or err(404, "Offer not found")
        buyer = db.get(Household, b.buyer_id) or err(404, "Buyer not found")
        if o.seller_id == buyer.id: err(409, "A household cannot buy its own offer")
        if o.status != "open": err(409, f"Offer is {o.status}")
        if q > demand_left(db, buyer): err(409, f"Exceeds eligible buyer demand ({demand_left(db, buyer) / 1000:.3f} kWh remaining)")
        # atomic conditional decrement guards against overselling under concurrent requests
        n = db.execute(text("UPDATE energy_offers SET remaining_wh=remaining_wh-:q WHERE id=:i AND status='open' AND remaining_wh>=:q"), dict(q=q, i=oid)).rowcount
        if n != 1: err(409, f"Exceeds remaining offer quantity ({o.remaining_wh / 1000:.3f} kWh)")
        db.refresh(o)
        if o.remaining_wh == 0: o.status = "filled"
        g = db.query(GenRecord).filter_by(household_id=o.seller_id).first()
        t = Trade(offer_id=o.id, buyer_id=buyer.id, seller_id=o.seller_id, qty_wh=q, price_paise=o.price_paise,
                  amount_paise=amount(q, o.price_paise) + CFG["fee_paise"], gen_record_id=g.id); db.add(t); db.flush()
        audit(db, "trade_completed", tid(t), offer=o.id, qty_wh=q, amount_paise=t.amount_paise)
        return dict(trade=trade_out(db, t), offer=offer_out(db, o))


@app.post("/api/trades/{trid}/cancel")
def cancel_trade(trid: int):
    """Rule: trade becomes 'cancelled' (never deleted). Quantity returns to the offer if it is open/filled; if the offer was cancelled it is released to the seller."""
    with Session.begin() as db:
        t = db.get(Trade, trid) or err(404, "Trade not found")
        if t.status != "completed": err(409, "Only completed trades can be cancelled")
        t.status = "cancelled"; o = db.get(Offer, t.offer_id)
        if o.status in ("open", "filled"): o.remaining_wh += t.qty_wh; o.status = "open"
        audit(db, "trade_cancelled", tid(t), original=tid(t), restored_wh=t.qty_wh)
        return trade_out(db, t)


@app.get("/api/trades")
def trades():
    with Session() as db: return [trade_out(db, t) for t in db.query(Trade).order_by(Trade.id.desc())]


@app.get("/api/trades/{trid}")
def trade(trid: int):
    with Session() as db: return trade_out(db, db.get(Trade, trid) or err(404, "Trade not found"))


def gen_out(db, r):
    return dict(id=r.id, household_id=r.household_id, household=db.get(Household, r.household_id).name, period=r.period, qty_wh=r.qty_wh,
                meter_ref=r.meter_ref, status=r.status, cert_ref=r.cert_ref,
                trades=[tid(t) for t in db.query(Trade).filter_by(gen_record_id=r.id, status="completed")])


@app.get("/api/generation-records")
def gen_records():
    with Session() as db: return [gen_out(db, r) for r in db.query(GenRecord).order_by(GenRecord.id)]


@app.post("/api/generation-records", status_code=201)
def add_gen(b: GenIn):
    q = conv(b.quantity_kwh, 1000, "Quantity")
    if q <= 0: err(422, "Quantity must be greater than zero")
    with Session.begin() as db:
        db.get(Household, b.household_id) or err(404, "Household not found")
        r = GenRecord(household_id=b.household_id, period=b.period, qty_wh=q, meter_ref=b.meter_ref); db.add(r); db.flush()
        audit(db, "generation_record_created", f"GEN-{r.id}", note="synthetic meter reference"); return gen_out(db, r)


@app.post("/api/generation-records/{rid}/verify")
def verify(rid: int, b: VerifyIn, x_demo_role: str = Header("reviewer")):
    need_role(x_demo_role, "reviewer")
    ref = b.cert_ref.strip().upper()
    if not re.fullmatch(r"[A-Z0-9-]{6,40}", ref): err(422, "Certificate reference must be 6-40 chars: A-Z, 0-9, hyphen")
    dup_id = None
    with Session.begin() as db:
        r = db.get(GenRecord, rid) or err(404, "Generation record not found")
        dup = db.query(GenRecord).filter(GenRecord.cert_ref == ref, GenRecord.id != rid).first()
        if dup:
            dup_id = dup.id; r.status = "flagged"
            audit(db, "duplicate_certificate_rejected", f"GEN-{rid}", cert_ref=ref, already_used_by=f"GEN-{dup.id}")
        else:
            r.cert_ref = ref; r.status = "verified"
            audit(db, "generation_verified", f"GEN-{rid}", cert_ref=ref, note="application-level check only; not an official REC")
            return gen_out(db, r)
    err(409, f"Certificate {ref} is already attached to generation record GEN-{dup_id}. Duplicate claim rejected; record flagged.")


@app.post("/api/generation-records/{rid}/reject")
def reject(rid: int, x_demo_role: str = Header("reviewer")):
    need_role(x_demo_role, "reviewer")
    with Session.begin() as db:
        r = db.get(GenRecord, rid) or err(404, "Generation record not found"); r.status = "rejected"
        audit(db, "generation_rejected", f"GEN-{rid}"); return gen_out(db, r)


@app.get("/api/audit-events")
def audits():
    with Session() as db:
        return [dict(id=a.id, ts=a.ts.isoformat(), type=a.type, entity=a.entity, details=json.loads(a.details)) for a in db.query(Audit).order_by(Audit.id.desc())]


def run_sim(b: SimIn):
    if b.households < 1 or min(b.generation_kwh, b.demand_kwh, b.capacity_kwh, b.price_inr, b.battery_kwh, b.battery_soc_kwh, b.battery_rate_kwh) < 0:
        err(422, "Inputs must be nonnegative and households >= 1")
    if not 0 <= b.producer_share_pct <= 100: err(422, "Producer share must be 0-100")
    soc = min(b.battery_soc_kwh, b.battery_kwh); n = b.households; sellers = round(n * b.producer_share_pct / 100)
    gen = sellers * b.generation_kwh; dem = n * b.demand_kwh
    sup = sellers * max(0, b.generation_kwh - b.demand_kwh)
    need = sellers * max(0, b.demand_kwh - b.generation_kwh) + (n - sellers) * b.demand_kwh
    matched = min(sup, need, b.capacity_kwh)
    cap_left = max(0, min(sup, need) - matched)
    charge = min(sup - matched, max(0, b.battery_kwh - soc), b.battery_rate_kwh)
    dis = min(need - matched, soc, b.battery_rate_kwh)
    r = lambda x: round(x, 3)
    return dict(sellers=sellers, generation_kwh=r(gen), demand_kwh=r(dem), surplus_kwh=r(sup), buyer_demand_kwh=r(need), matched_kwh=r(matched),
                unmet_demand_kwh=r(need - matched - dis), grid_import_kwh=r(need - matched - dis), grid_export_kwh=r(sup - matched - charge),
                unmatched_due_to_capacity_kwh=r(cap_left), battery_charge_kwh=r(charge), battery_discharge_kwh=r(dis),
                battery_soc_end_kwh=r(soc + charge - dis), trade_value_inr=r(matched * b.price_inr),
                model="Conceptual single-time-step model: matched = min(seller surplus, buyer demand, capacity). Not an electrical power-flow model.")


@app.post("/api/simulations/run")
def sim(b: SimIn):
    res = run_sim(b)
    with Session.begin() as db: audit(db, "simulation_run", "microgrid", **res)
    return res


def metrics(db):
    hs = db.query(Household).all(); ts = db.query(Trade).filter_by(status="completed").all()
    traded = sum(t.qty_wh for t in ts); vol = sum(t.amount_paise for t in ts); dem = sum(deficit(h) for h in hs)
    sav = sum(t.qty_wh * (CFG["grid_tariff_paise"] - t.price_paise) / 1000 for t in ts)
    gain = sum(t.qty_wh * (t.price_paise - CFG["export_baseline_paise"]) / 1000 for t in ts)
    bad = sum(1 for t in ts if t.amount_paise != amount(t.qty_wh, t.price_paise) + CFG["fee_paise"])
    last = db.query(Audit).filter_by(type="simulation_run").order_by(Audit.id.desc()).first(); ld = json.loads(last.details) if last else None
    return dict(generation_wh=sum(h.gen_wh for h in hs), consumption_wh=sum(h.cons_wh for h in hs), surplus_wh=sum(surplus(h) for h in hs),
                listed_wh=sum(o.remaining_wh for o in db.query(Offer).filter_by(status="open")), traded_wh=traded,
                verified_wh=sum(r.qty_wh for r in db.query(GenRecord).filter_by(status="verified")), trades=len(ts), volume_paise=vol,
                buyer_savings_paise=round(sav), seller_earnings_paise=vol, seller_net_gain_paise=round(gain), eligible_demand_wh=dem,
                match_rate=(traded / dem if dem else None), avg_trade_paise=(round(vol / len(ts)) if ts else None),
                duplicates_rejected=db.query(Audit).filter_by(type="duplicate_certificate_rejected").count(),
                settlement_error_rate=(bad / len(ts) if ts else None),
                sim_import_kwh=ld["grid_import_kwh"] if ld else None, sim_export_kwh=ld["grid_export_kwh"] if ld else None,
                baselines=dict(grid_tariff_inr=CFG["grid_tariff_paise"] / 100, export_baseline_inr=CFG["export_baseline_paise"] / 100))


@app.get("/api/analytics")
def analytics():
    with Session() as db: return metrics(db)


@app.get("/api/dashboard")
def dashboard():
    with Session() as db:
        return dict(metrics=metrics(db), households=[hh_out(db, h) for h in db.query(Household)],
                    recent_trades=[trade_out(db, t) for t in db.query(Trade).order_by(Trade.id.desc()).limit(5)],
                    open_offers=[offer_out(db, o) for o in db.query(Offer).filter_by(status="open").order_by(Offer.id.desc()).limit(5)],
                    activity=[dict(ts=a.ts.isoformat(), type=a.type, entity=a.entity) for a in db.query(Audit).order_by(Audit.id.desc()).limit(8)],
                    verification={s: db.query(GenRecord).filter_by(status=s).count() for s in ("pending", "verified", "rejected", "flagged")})


FE = Path(__file__).parent.parent / "frontend"


@app.get("/")
def index(): return FileResponse(FE / "index.html")