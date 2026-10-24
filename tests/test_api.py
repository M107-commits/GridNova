from concurrent.futures import ThreadPoolExecutor\nfrom datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import Base, get_db
from backend.models import Household, Offer

def household(name, generation, consumption, price=1200, share=True):
    return Household(name=name, city="Bengaluru", locality="Demo Block", source="solar",
        capacity_wh=8000, generation_wh=generation, consumption_wh=consumption,
        preferred_price_paise=price, share_surplus=share)

import pytest

@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "gridnova-test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as db:
        db.add_all([
            household("Seller Sun", 5000, 1000, 500),
            household("Buyer Breeze", 1000, 4000),
            household("Buyer Cloud", 1000, 4000),
            household("Third Home", 2000, 3000),
            household("Fifth Home", 4500, 2000),
        ])
        db.commit()
    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()

def owner(household_id):
    return {"X-Demo-Role": "homeowner", "X-Household-Id": str(household_id)}

def test_seed_shape_and_dashboard(client):
    homes = client.get("/api/households").json()
    assert len(homes) == 5
    data = client.get("/api/dashboard?household_id=1").json()
    assert data["simulation"] is True
    assert data["household"]["surplus_wh"] == 4000
    assert data["household"]["eligible_demand_wh"] == 0

def test_purchase_accounting_round_half_up_and_audit(client):
    response = client.post("/api/offers/1/purchase", headers=owner(2),
                           json={"buyer_household_id": 2, "quantity_wh": 1})
    assert response.status_code == 201
    assert response.json()["total_paise"] == 1
    assert client.get("/api/households").json()[0]["id"] == 1
    events = client.get("/api/audit-events", headers=owner(2)).json()
    assert any(e["action"] == "trade_purchased" for e in events)
    seller = next(h for h in client.get("/api/households").json() if h["id"] == 1)
    assert seller["surplus_wh"] == 3999

def test_prevent_self_purchase_overselling_and_excess_demand(client):
    self_buy = client.post("/api/offers/1/purchase", headers=owner(1),
                           json={"buyer_household_id": 1, "quantity_wh": 1})
    assert self_buy.status_code == 409
    too_much = client.post("/api/offers/1/purchase", headers=owner(2),
                           json={"buyer_household_id": 2, "quantity_wh": 3001})
    assert too_much.status_code == 409
    beyond_supply = client.post("/api/offers/1/purchase", headers=owner(2),
                           json={"buyer_household_id": 2, "quantity_wh": 4001})
    assert beyond_supply.status_code == 409

def test_owner_scope_duplicate_commitment_and_cancel_ledger(client):
    denied = client.patch("/api/households/1/energy", headers=owner(2),
                          json={"generation_wh": 4000, "consumption_wh": 1000})
    assert denied.status_code == 403
    payload = {"buyer_household_id": 2, "quantity_wh": 1000}
    first = client.post("/api/offers/1/purchase", headers=owner(2), json=payload)
    assert first.status_code == 201
    duplicate = client.post("/api/offers/1/purchase", headers=owner(2), json=payload)
    assert duplicate.status_code == 409
    trade_id = first.json()["id"]
    cancelled = client.post(f"/api/trades/{trade_id}/cancel", headers=owner(2))
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    rows = client.get("/api/trades").json()
    assert len(rows) == 1 and rows[0]["status"] == "cancelled"
    assert next(h for h in client.get("/api/households").json() if h["id"] == 1)["surplus_wh"] == 4000
    assert any(e["action"] == "trade_cancelled" for e in client.get("/api/audit-events", headers=owner(2)).json())

def test_certificate_uniqueness_and_reviewer_permissions(client):
    data = {"household_id": 1, "quantity_wh": 1200, "source": "solar",
            "certificate_reference": "CERT-UNIQUE"}
    a = client.post("/api/generation-records", headers=owner(1), json=data)
    b = client.post("/api/generation-records", headers=owner(1), json=data)
    assert a.status_code == 201
    assert b.status_code == 409
    record_id = a.json()["id"]
    denied = client.post(f"/api/generation-records/{record_id}/verify", headers=owner(1), json={"note": "x"})
    assert denied.status_code == 403
    reviewer = {"X-Demo-Role": "verifier"}
    verified = client.post(f"/api/generation-records/{record_id}/verify", headers=reviewer, json={"note": "demo check"})
    assert verified.status_code == 200
    again = client.post(f"/api/generation-records/{record_id}/reject", headers=reviewer, json={"note": "late"})
    assert again.status_code == 409
    assert any(e["action"] == "generation_verified" for e in client.get("/api/audit-events", headers=owner(1)).json())

def test_simulation_and_settings_are_persisted_and_audited(client):
    role = owner(2)
    saved = client.put("/api/settings/2", headers=role,
                       json={"preferred_price_paise": 1234, "share_surplus": False})
    assert saved.status_code == 200 and saved.json()["share_surplus"] is False
    assert client.get("/api/settings/2", headers=role).json()["preferred_price_paise"] == 1234
    sim = client.post("/api/simulations/run", headers=role,
                      json={"solar_percent": 70, "demand_percent": 50})
    assert sim.status_code == 200 and sim.json()["simulation_only"] is True
    actions = [e["action"] for e in client.get("/api/audit-events", headers=role).json()]
    assert "settings_updated" in actions and "simulation_run" in actions

def test_competing_purchases_cannot_oversell(client):
    def buy(household_id):
        return client.post("/api/offers/1/purchase", headers=owner(household_id),
            json={"buyer_household_id": household_id, "quantity_wh": 3000}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(buy, [2, 3]))
    assert sorted(codes) == [201, 409]
    seller = next(h for h in client.get("/api/households").json() if h["id"] == 1)
    assert seller["surplus_wh"] == 1000

def test_household_scoped_reads(client):
    create = client.post("/api/generation-records", headers=owner(1),
        json={"household_id": 1, "quantity_wh": 600, "source": "solar"})
    assert create.status_code == 201
    own = client.get("/api/generation-records", headers=owner(1))
    assert all(r["household_id"] == 1 for r in own.json())
    denied = client.get("/api/generation-records?household_id=2", headers=owner(1))
    assert denied.status_code == 403
    cross_trades = client.get("/api/trades?household_id=2", headers=owner(1))
    assert cross_trades.status_code == 403

def test_offer_records_expire_and_can_be_withdrawn(client):
    made = client.post("/api/offers", headers=owner(5),
        json={"household_id": 5, "quantity_wh": 500, "price_paise_per_kwh": 900,
              "expires_in_hours": 12})
    assert made.status_code == 201
    offer_id = made.json()["id"]
    listed = client.get("/api/offers?seller_household_id=5", headers=owner(5)).json()
    assert any(o["id"] == offer_id and o["quantity_wh"] == 500 for o in listed)
    withdrawn = client.post(f"/api/offers/{offer_id}/cancel", headers=owner(5))
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "cancelled"
    remaining = client.get("/api/offers?seller_household_id=5", headers=owner(5)).json()
    assert all(o["id"] != offer_id for o in remaining)

def test_purchase_requires_idempotency_key(client):
    result = client.post("/api/offers/1/purchase", headers=owner(2),
        json={"buyer_household_id": 2, "quantity_wh": 100})
    assert result.status_code == 422
