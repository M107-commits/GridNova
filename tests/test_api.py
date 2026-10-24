from concurrent.futures import ThreadPoolExecutor
import hashlib
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import Base, get_db
from backend.models import Household, Offer, Trade, GenerationRecord, AuditEvent, UserAccount, AuthSession

def household(name, generation, consumption, price=1200, share=True):
    return Household(name=name, city="Bengaluru", locality="Demo Block", source="solar",
        capacity_wh=8000, generation_wh=generation, consumption_wh=consumption,
        preferred_price_paise=price, share_surplus=share)

import pytest

@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "gridnova-test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 30})
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
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
        db.flush()
        accounts = []
        for hid in range(1, 6):
            account = UserAccount(household_id=hid, email=f"home{hid}@example.test",
                display_name=f"Home {hid}", password_hash="unused-test-hash",
                role="homeowner")
            db.add(account)
            accounts.append(("homeowner", hid, account))
        accounts.extend([
            ("verifier", 2, UserAccount(household_id=2, email="reviewer@example.test",
                display_name="Reviewer", password_hash="unused-test-hash", role="verifier")),
            ("admin", 1, UserAccount(household_id=1, email="admin@example.test",
                display_name="Admin", password_hash="unused-test-hash", role="admin")),
        ])
        for role_name, hid, account in accounts[5:]:
            db.add(account)
        db.flush()
        for role_name, hid, account in accounts:
            token = f"test-{role_name}-{hid}"
            db.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                account_id=account.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=3)))
        db.add(Offer(household_id=1, quantity_wh=4000, price_paise_per_kwh=500,
            status="open", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        db.commit()
    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        c.cookies.set("gridnova_session", "test-homeowner-1")
        c.cookies.set("gridnova_csrf", "csrf-homeowner-1")
        c.test_session = Session
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()

def account_headers(role, household_id):
    token = f"test-{role}-{household_id}"
    csrf = f"csrf-{role}-{household_id}"
    return {"Cookie": f"gridnova_session={token}; gridnova_csrf={csrf}",
            "X-CSRF-Token": csrf}

def owner(household_id):
    return account_headers("homeowner", household_id)

def reviewer_headers(household_id=2):
    return account_headers("verifier", household_id)

def admin_headers(household_id=1):
    return account_headers("admin", household_id)

def purchase_headers(household_id, key):
    return {**owner(household_id), "Idempotency-Key": key}

def test_seed_shape_and_dashboard(client):
    homes = client.get("/api/households").json()
    assert len(homes) == 1 and homes[0]["id"] == 1
    data = client.get("/api/dashboard?household_id=1").json()
    assert data["simulation"] is True
    assert data["household"]["surplus_wh"] == 4000
    assert data["household"]["eligible_demand_wh"] == 0

def test_purchase_accounting_round_half_up_and_audit(client):
    response = client.post("/api/offers/1/purchase", headers=purchase_headers(2, "purchase-key-1"),
                           json={"buyer_household_id": 2, "quantity_wh": 1})
    assert response.status_code == 201
    assert response.json()["total_paise"] == 1
    assert client.get("/api/households").json()[0]["id"] == 1
    events = client.get("/api/audit-events", headers=owner(2)).json()
    assert any(e["action"] == "trade_purchased" for e in events)
    seller = next(h for h in client.get("/api/households").json() if h["id"] == 1)
    assert seller["surplus_wh"] == 3999

def test_prevent_self_purchase_overselling_and_excess_demand(client):
    self_buy = client.post("/api/offers/1/purchase", headers=purchase_headers(1, "purchase-key-2"),
                           json={"buyer_household_id": 1, "quantity_wh": 1})
    assert self_buy.status_code == 409
    too_much = client.post("/api/offers/1/purchase", headers=purchase_headers(2, "purchase-key-3"),
                           json={"buyer_household_id": 2, "quantity_wh": 3001})
    assert too_much.status_code == 409
    beyond_supply = client.post("/api/offers/1/purchase", headers=purchase_headers(2, "purchase-key-4"),
                           json={"buyer_household_id": 2, "quantity_wh": 4001})
    assert beyond_supply.status_code == 409

def test_owner_scope_duplicate_commitment_and_cancel_ledger(client):
    denied = client.patch("/api/households/1/energy", headers=owner(2),
                          json={"generation_wh": 4000, "consumption_wh": 1000})
    assert denied.status_code == 403
    payload = {"buyer_household_id": 2, "quantity_wh": 1000}
    keyed_headers = purchase_headers(2, "purchase-retry-key-01")
    first = client.post("/api/offers/1/purchase", headers=keyed_headers, json=payload)
    assert first.status_code == 201
    retry = client.post("/api/offers/1/purchase", headers=keyed_headers, json=payload)
    assert retry.status_code == 201 and retry.json()["id"] == first.json()["id"]
    collision = client.post("/api/offers/1/purchase", headers=keyed_headers,
        json={"buyer_household_id": 2, "quantity_wh": 999})
    assert collision.status_code == 409
    duplicate = client.post("/api/offers/1/purchase",
        headers=purchase_headers(2, "duplicate-commit-key-01"), json=payload)
    assert duplicate.status_code == 409
    trade_id = first.json()["id"]
    cancelled = client.post(f"/api/trades/{trade_id}/cancel", headers=owner(2))
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    rows = client.get("/api/trades").json()
    assert len(rows) == 1 and rows[0]["status"] == "cancelled"
    assert next(h for h in client.get("/api/households").json() if h["id"] == 1)["surplus_wh"] == 4000
    assert any(e["action"] == "trade_cancelled" for e in client.get("/api/audit-events", headers=owner(2)).json())
    replay = client.post("/api/offers/1/purchase", headers=keyed_headers, json=payload)
    assert replay.status_code == 201 and replay.json()["status"] == "cancelled"
    assert next(h for h in client.get("/api/households").json() if h["id"] == 1)["surplus_wh"] == 4000

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
    reviewer = reviewer_headers()
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
        return client.post("/api/offers/1/purchase", headers=purchase_headers(household_id, f"parallel-key-{household_id}"),
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
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"
    remaining = client.get("/api/offers?seller_household_id=5", headers=owner(5)).json()
    assert next(o for o in remaining if o["id"] == offer_id)["status"] == "withdrawn"

def test_purchase_requires_idempotency_key(client):
    result = client.post("/api/offers/1/purchase", headers=owner(2),
        json={"buyer_household_id": 2, "quantity_wh": 100})
    assert result.status_code == 422


def test_same_idempotency_key_concurrent_retry_creates_one_trade(client):
    payload = {"buyer_household_id": 2, "quantity_wh": 1000}
    headers = purchase_headers(2, "concurrent-retry-key-01")
    def buy(_):
        return client.post("/api/offers/1/purchase", headers=headers, json=payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(buy, range(2)))
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json()["id"] == results[1].json()["id"]
    assert len(client.get("/api/trades", headers=owner(2)).json()) == 1
    with client.test_session() as db:
        assert db.query(Trade).filter_by(idempotency_key="concurrent-retry-key-01").count() == 1
        assert db.query(AuditEvent).filter_by(action="trade_purchased").count() == 1

def test_expired_offer_cannot_be_listed_or_purchased(client):
    made = client.post("/api/offers", headers=owner(5), json={
        "household_id": 5, "quantity_wh": 500, "price_paise_per_kwh": 900, "expires_in_hours": 12})
    assert made.status_code == 201
    offer_id = made.json()["id"]
    with client.test_session() as db:
        offer = db.get(Offer, offer_id)
        offer.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert all(row["id"] != offer_id for row in client.get("/api/offers").json())
    result = client.post(f"/api/offers/{offer_id}/purchase",
        headers=purchase_headers(2, "expired-offer-key-01"),
        json={"buyer_household_id": 2, "quantity_wh": 100})
    assert result.status_code == 404

def test_partial_fills_and_withdrawal_do_not_release_twice(client):
    first = client.post("/api/offers/1/purchase",
        headers=purchase_headers(2, "partial-fill-key-001"),
        json={"buyer_household_id": 2, "quantity_wh": 1000})
    assert first.status_code == 201
    partial = next(o for o in client.get("/api/offers").json() if o["id"] == 1)
    assert partial["quantity_wh"] == 3000
    second = client.post("/api/offers/1/purchase",
        headers=purchase_headers(2, "partial-fill-key-002"),
        json={"buyer_household_id": 2, "quantity_wh": 2000})
    assert second.status_code == 201
    remainder = next(o for o in client.get("/api/offers").json() if o["id"] == 1)
    assert remainder["quantity_wh"] == 1000
    withdrawn = client.post("/api/offers/1/cancel", headers=owner(1))
    assert withdrawn.status_code == 200
    assert all(o["id"] != 1 for o in client.get("/api/offers").json())
    with client.test_session() as db:
        assert db.query(Trade).filter_by(status="completed").count() == 2
        assert db.query(Trade).filter_by(status="cancelled").count() == 0

def test_cancel_is_single_transition_and_verifier_cannot_mutate_household(client):
    response = client.post("/api/offers/1/purchase",
        headers=purchase_headers(2, "cancel-once-key-001"),
        json={"buyer_household_id": 2, "quantity_wh": 1000})
    trade_id = response.json()["id"]
    reviewer = reviewer_headers(2)
    assert client.post(f"/api/trades/{trade_id}/cancel", headers=reviewer).status_code == 403
    assert client.patch("/api/households/2/energy", headers=reviewer,
        json={"generation_wh": 2000, "consumption_wh": 3000}).status_code == 403
    assert client.post(f"/api/trades/{trade_id}/cancel", headers=owner(2)).status_code == 200
    assert client.post(f"/api/trades/{trade_id}/cancel", headers=owner(2)).status_code == 409
    seller = next(h for h in client.get("/api/households").json() if h["id"] == 1)
    assert seller["surplus_wh"] == 4000

def test_reset_reseeds_the_request_database_and_removes_offers(client):
    create = client.post("/api/offers", headers=owner(5),
        json={"household_id": 5, "quantity_wh": 500, "price_paise_per_kwh": 900})
    assert create.status_code == 201
    reset = client.post("/api/reset", headers=admin_headers())
    assert reset.status_code == 410
    assert len(client.get("/api/households").json()) == 1
    assert len(client.get("/api/offers").json()) == 4
    assert client.post("/api/reset", headers=owner(1)).status_code == 403

def test_purchase_commit_failure_rolls_back_trade_and_audit(client, monkeypatch):
    from sqlalchemy.orm import Session as SASession
    def fail_commit(self):
        raise RuntimeError("synthetic database commit failure")
    with monkeypatch.context() as patch:
        patch.setattr(SASession, "commit", fail_commit)
        failed = client.post("/api/offers/1/purchase",
            headers=purchase_headers(2, "commit-failure-key-01"),
            json={"buyer_household_id": 2, "quantity_wh": 1000})
    assert failed.status_code == 500
    assert client.get("/api/trades", headers=owner(2)).json() == []
    events = client.get("/api/audit-events", headers=owner(2)).json()
    assert all(e["action"] != "trade_purchased" for e in events)
    seller = next(h for h in client.get("/api/households").json() if h["id"] == 1)
    assert seller["surplus_wh"] == 4000

def test_non_loopback_cannot_forge_admin_header(client):
    remote = TestClient(app, client=("203.0.113.8", 54321), raise_server_exceptions=False)
    denied = remote.post("/api/reset", headers={"X-Demo-Role": "admin"})
    assert denied.status_code == 403


def test_partial_then_full_offer_fill_removes_offer(client):
    first = client.post("/api/offers/1/purchase",
        headers=purchase_headers(2, "fill-partial-key-001"),
        json={"buyer_household_id": 2, "quantity_wh": 1000})
    assert first.status_code == 201
    second = client.post("/api/offers/1/purchase",
        headers=purchase_headers(2, "fill-partial-key-002"),
        json={"buyer_household_id": 2, "quantity_wh": 2000})
    assert second.status_code == 201
    remainder = next(o for o in client.get("/api/offers").json() if o["id"] == 1)
    assert remainder["quantity_wh"] == 1000
    final = client.post("/api/offers/1/purchase",
        headers=purchase_headers(3, "fill-final-key-0001"),
        json={"buyer_household_id": 3, "quantity_wh": 1000})
    assert final.status_code == 201
    assert all(o["id"] != 1 for o in client.get("/api/offers").json())


def test_dashboard_default_household_scope_and_cross_household_offer_cancel(client):
    assert client.get("/api/dashboard?household_id=1",
        headers=owner(1)).status_code == 200
    assert client.get("/api/dashboard?household_id=2",
        headers=owner(1)).status_code == 403
    denied = client.post("/api/offers/1/cancel", headers=owner(2))
    assert denied.status_code == 403
    offer = client.get("/api/offers?seller_household_id=1", headers=owner(1)).json()
    assert any(item["id"] == 1 for item in offer)

def test_verifier_cannot_run_audited_simulation_and_sim_input_is_bounded(client):
    before = client.get("/api/audit-events", headers={"X-Demo-Role": "admin"}).json()
    denied = client.post("/api/simulations/run", headers=reviewer_headers(),
        json={"solar_percent": 50, "demand_percent": 50})
    assert denied.status_code == 403
    too_many = client.post("/api/simulations/run", headers=owner(2),
        json={"solar_percent": 50, "demand_percent": 50, "household_ids": [1, 2, 3, 4, 5, 6]})
    assert too_many.status_code == 422
    after = client.get("/api/audit-events", headers={"X-Demo-Role": "admin"}).json()
    assert len(after) == len(before)


def test_generation_rejection_is_audited_and_final(client):
    submitted = client.post("/api/generation-records", headers=owner(4), json={
        "household_id": 4, "quantity_wh": 900, "source": "solar"})
    assert submitted.status_code == 201
    reviewer = reviewer_headers()
    rejected = client.post(f"/api/generation-records/{submitted.json()['id']}/reject",
        headers=reviewer, json={"note": "Synthetic demo rejection"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    retry = client.post(f"/api/generation-records/{submitted.json()['id']}/verify",
        headers=reviewer, json={"note": "late"})
    assert retry.status_code == 409
    events = client.get("/api/audit-events", headers={"X-Demo-Role": "admin"}).json()
    assert any(event["action"] == "generation_rejected" for event in events)


def test_energy_profile_cannot_invalidate_open_offers_or_completed_trades(client):
    too_low_for_listing = client.patch("/api/households/1/energy", headers=owner(1),
        json={"generation_wh": 4900, "consumption_wh": 1000})
    assert too_low_for_listing.status_code == 409
    assert client.post("/api/offers/1/cancel", headers=owner(1)).status_code == 200
    updated = client.patch("/api/households/1/energy", headers=owner(1),
        json={"generation_wh": 4900, "consumption_wh": 1000})
    assert updated.status_code == 200
    made = client.post("/api/offers", headers=owner(1), json={
        "household_id": 1, "quantity_wh": 2000, "price_paise_per_kwh": 700})
    assert made.status_code == 201
    bought = client.post(f"/api/offers/{made.json()['id']}/purchase",
        headers=purchase_headers(2, "profile-lock-sale-key"),
        json={"buyer_household_id": 2, "quantity_wh": 1000})
    assert bought.status_code == 201
    seller_change = client.patch("/api/households/1/energy", headers=owner(1),
        json={"generation_wh": 2900, "consumption_wh": 1000})
    assert seller_change.status_code == 409
    buyer_change = client.patch("/api/households/2/energy", headers=owner(2),
        json={"generation_wh": 1000, "consumption_wh": 1900})
    assert buyer_change.status_code == 409

def test_offer_lifecycle_statuses_are_visible_in_seller_and_trade_views(client):
    made = client.post("/api/offers", headers=owner(5), json={
        "household_id": 5, "quantity_wh": 500, "price_paise_per_kwh": 900})
    offer_id = made.json()["id"]
    partial = client.post(f"/api/offers/{offer_id}/purchase",
        headers=purchase_headers(2, "lifecycle-partial-key"),
        json={"buyer_household_id": 2, "quantity_wh": 100})
    assert partial.status_code == 201
    assert partial.json()["offer_status"] == "partially_filled"
    own = client.get("/api/offers?seller_household_id=5", headers=owner(5)).json()
    row = next(item for item in own if item["id"] == offer_id)
    assert row["status"] == "partially_filled"
    assert row["filled_quantity_wh"] == 100 and row["quantity_wh"] == 400
    assert client.post(f"/api/offers/{offer_id}/cancel", headers=owner(5)).status_code == 200
    own = client.get("/api/offers?seller_household_id=5", headers=owner(5)).json()
    assert next(item for item in own if item["id"] == offer_id)["status"] == "withdrawn"
    expired = client.post("/api/offers", headers=owner(5), json={
        "household_id": 5, "quantity_wh": 100, "price_paise_per_kwh": 900})
    with client.test_session() as db:
        db.get(Offer, expired.json()["id"]).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    own = client.get("/api/offers?seller_household_id=5", headers=owner(5)).json()
    assert next(item for item in own if item["id"] == expired.json()["id"])["status"] == "expired"


def test_real_account_registration_login_logout_and_forged_role_headers(client):
    client.cookies.clear()
    payload = {"name": "Asha Rao", "household_name": "Rao Home",
        "email": "asha@example.test", "password": "GridNova-password-10",
        "city": "Bengaluru", "locality": "Indiranagar"}
    registered = client.post("/api/auth/register", json=payload)
    assert registered.status_code == 201
    assert registered.json()["household_name"] == "Rao Home"
    assert "httponly" in registered.headers.get("set-cookie", "").lower()
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "asha@example.test"
    own_homes = client.get("/api/households").json()
    assert len(own_homes) == 1 and own_homes[0]["name"] == "Rao Home"
    forged = client.post("/api/reset", headers={"X-Demo-Role": "admin",
        "X-CSRF-Token": client.cookies.get("gridnova_csrf")})
    assert forged.status_code == 403
    client.post("/api/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get("gridnova_csrf")})
    assert client.get("/api/auth/me").status_code == 401

    login = client.post("/api/auth/login", json={
        "email": "ASHA@example.test", "password": "GridNova-password-10"})
    assert login.status_code == 200
    assert client.get("/api/auth/me").json()["household_id"] == registered.json()["household_id"]
    bad_login = client.post("/api/auth/login", json={
        "email": "asha@example.test", "password": "wrong-password"})
    assert bad_login.status_code == 401
