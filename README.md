# GridNova — A New Era of Connected Energy

GridNova is a local-first peer-to-peer renewable-energy marketplace simulation for fictional Indian households. The API uses FastAPI, SQLAlchemy, and SQLite; the client is responsive vanilla HTML, CSS, and JavaScript. Five seeded demo households represent Bengaluru, Hyderabad, Pune, Chennai, and Jaipur.

## Run locally

Use Python 3.10 or newer.

```sh
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 for the app and http://127.0.0.1:8000/docs for the API. SQLite creates `gridnova.db` in the current working directory. Set `GRIDNOVA_DATABASE_URL` to use another SQLAlchemy database URL.

## Test

Backend/API tests:

```sh
python -m pytest -q
```

Browser tests use Playwright and run the app on port 8765. Install Node.js, install the pinned dependency, and download Chromium once:

```sh
npm ci
npx playwright install chromium
npm run test:e2e
```

The browser suite uses real Chromium at desktop and Pixel 7 sized viewports. It checks all seven page routes, household/profile editing, offer creation, partial and complete purchase fills, same-key retries, offer withdrawal, transaction details and cancellation, generation submission and verifier review, settings, the simulator, and demo reset. Expiry is exercised against an expired database record in the API tests because the UI does not expose a clock-advance control.

## Verification results

Latest verification ran against the connected repository revision in an isolated scratch checkout:

- `python -m pytest -q`: **21 passed**. One upstream Starlette deprecation warning notes that its TestClient currently uses httpx; it did not affect the test results.
- `npm run test:e2e`: **2 passed, 2 skipped**. The two projects each run their matching scenario (one desktop workflow and one mobile navigation workflow); the other scenario is explicitly skipped in each project.
- Browser checks ran in Chromium on desktop (1440×1000) and mobile (Pixel 7 profile, then explicitly 390×844). This was a real browser run, not a DOM-only check.

## Application pages

- **Overview:** API-backed household and community generation, consumption, surplus, demand, ledger activity, and illustrative impact.
- **Energy Marketplace:** searchable and sortable independent offers, expiry, withdrawal, purchase dialogs, and idempotency keys.
- **My Energy:** edit synthetic generation and consumption, set rates, and submit generation records.
- **Transactions:** search and filter the persistent ledger, inspect trade details, cancel eligible trades, and export CSV.
- **Verification & Impact:** demo review of generation records, community analytics, and clearly labeled environmental estimates.
- **Microgrid Simulator:** adjust solar and demand assumptions and run the server-side synthetic model.
- **Settings:** household sharing/rate preferences and demo reset.

## Security model and audit notes

The role selector and `X-Demo-Role` / `X-Household-Id` headers are a **demo convention, not authentication**. A caller who can reach the API can forge those headers. Ownership checks and reviewer-only rules enforce intended behavior in the simulation and are covered by API tests; they do not establish the caller's real identity.

The API rejects non-loopback clients by default. `GRIDNOVA_ALLOW_REMOTE_DEMO=1` disables that boundary and is explicitly insecure. Do not expose this app to a network or put it behind a reverse proxy as a production service. In particular, a local proxy can make a remote caller appear loopback to this simple demo boundary. Use real identity, server-side authorization, CSRF protections, transport security, secret management, and deployment hardening before any multi-user or remote use.

- Homeowners are scoped to the selected household for household-specific reads and writes. Marketplace and synthetic aggregate reads are shared.
- Verifiers can review pending generation records but are blocked from household and trade mutation routes and simulator runs. Admin is a demo role with reset and cross-household demo actions.
- Reset clears prior demo ledger, listing, generation, setting, and audit rows, reseeds the demo database, and records a new reset event.
- Purchases, cancellations, offer withdrawals, and generation reviews serialize their SQLite write transactions; purchases use `BEGIN IMMEDIATE`, integer Wh/paise accounting, a unique idempotency key, and rollback on failure.

## Simulation limits

All household profiles, generation values, offers, prices, trades, and environmental estimates are synthetic. A purchase only writes a demo ledger entry; it does not transfer electricity or money. The app has no real meter connection, physical generation validation, official renewable-energy certification, or regulatory approval. “Verified” is an internal demo review status only. CO₂ values are illustrative estimates, not certified environmental claims.
