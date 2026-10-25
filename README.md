# GridNova — A New Era of Connected Energy

GridNova is a household-focused prototype for exploring how rooftop solar surplus might be matched with nearby household demand. Solar production and consumption are often out of sync across homes; local energy sharing is one possible way to use surplus more productively. GridNova demonstrates the matching and accounting experience with synthetic data. It does not transfer electricity or money.

## What is implemented

- FastAPI + SQLAlchemy + SQLite backend, and responsive vanilla HTML/CSS/JavaScript frontend.
- Household accounts with server-side household ownership, password hashes, sessions, and CSRF protection. Public registration creates homeowner accounts; trusted reviewer accounts require server-side provisioning.
- City-scoped offers, partial purchases, demand/supply validation, idempotent purchase requests, cancellations, transaction history, generation review, analytics, simulator, and household settings.
- A SHA-256 hash-linked sequence for trade creation and cancellation events. SQLite remains the source of application state. This demonstrates detection of edits to the stored sequence; it is not a blockchain, does not prevent a database owner from rewriting the full chain, and does not decentralize settlement.

The project’s technical contribution is a demonstrable combination of local offer matching, server-enforced supply/demand limits, partial fills, transparent INR-per-kWh prices, idempotent writes, and an inspectable hash-linked trade history. This is a prototype implementation, not a claim of a novel market mechanism or a production energy exchange.

## Run locally

Use Python 3.10 or newer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000, create a household account, then list surplus or explore offers. Existing profiles and starter offers are fictional. SQLite creates `gridnova.db` in the current working directory. To use a different database URL, set `GRIDNOVA_DATABASE_URL` before starting the server. Set `GRIDNOVA_COOKIE_SECURE=1` when serving over HTTPS. The application defaults to loopback-only access; `GRIDNOVA_ALLOW_REMOTE_DEMO=1` disables that local boundary and is not a production setting.

## Climate impact method and data path

The interface labels the CO₂ figure as a modeled estimate and exposes its formula and assumptions:

`completed simulated traded energy (kWh) × 0.55 kg CO₂e/kWh = modeled CO₂ proxy`

The 0.55 factor is an illustrative prototype assumption, not a sourced current grid factor. The model assumes one traded kWh displaces one grid kWh. Cancelled trades are excluded. The displayed quantity is an estimate, not measured or verified avoided emissions. It does not account for time-specific marginal generation, network losses, rebound effects, or uncertainty. No external generation, meter, utility, or grid-emissions data source is integrated.

A responsible integration path would add (1) consented, interval-based generation and consumption readings from compatible meters or utility systems, with provenance and validation; (2) a documented, versioned, time- and region-specific grid-emissions factor from a selected authoritative dataset; and (3) matching interval boundaries, losses, uncertainty, and an independently reviewed displacement method. The app should expose source, version, timestamp, and calculation inputs with every result. No source or integration is assumed to exist today.

## Users and real-world scope

The intended users to explore are household solar sellers, household buyers, and community energy groups coordinating a local pilot. Today these are users of a simulation only. Deployment as a real service would depend on:

- compatible meters and trusted readings, consent, correction, and dispute flows;
- utility or distribution-network integration, grid constraints, and permission to exchange energy;
- a lawful settlement model, payment provider, tariffs, tax handling, and applicable regulatory approvals;
- privacy controls for household energy profiles and location, secure operations, identity recovery, monitoring, and incident response.

GridNova currently has no meter validation, utility integration, energy delivery, payment settlement, official renewable-energy certificate issuance, or regulatory approval. In-app “reviewed” status only means a reviewer changed the prototype record. It is not meter- or authority-verified.

Accounts and sessions are implemented for this local prototype, but authentication is not production-ready: there is no email verification, account recovery, MFA, or login rate limiting. Reviewer/admin roles require trusted server-side provisioning; the UI role display is not a security boundary.

## Tests and verification

Run the API suite:

```powershell
python -m pytest -q
```

Run the browser suite (real Chromium browser required):

```powershell
npm ci
npx playwright install chromium
npm run test:e2e
```

**Verified for this revision (2026-10-25):** `python -m pytest -q` — 26 passed, with one Starlette/httpx deprecation warning. `python -m compileall -q backend tests`, `node --check` on the extracted inline client script, and a direct SQLite ledger create/verify/tamper check also completed successfully. Focused Playwright runs in real Chromium reported `ok` for the full desktop buyer/seller journey including the guided tour and for mobile navigation across all seven pages. The Playwright runner did not return its final aggregate exit status in this environment, so the complete four-case Playwright matrix is not reported as passing; viewport-inapplicable duplicate cases were skipped in the full run.

## Guided demo

After signing in, use **Quick guided tour** on the Overview page. It navigates the live app pages and describes the actual seller, buyer, review, impact, and transaction paths. It does not inject trades or pretend to complete actions; create an offer, purchase, or generation record using the normal controls to see persisted state update.

## Pages

- **Overview:** signed-in household balance, neighborhood activity, climate context, and simulated scope.
- **Energy Marketplace:** city-scoped offers, filters, prices, and partial purchase dialog.
- **My Energy:** profile values, offer history, and generation record submission.
- **Transactions:** household trade history, details, cancellation, and CSV export.
- **Verification & Impact:** review status, modeled estimate assumptions, and trade-sequence integrity check.
- **Microgrid Simulator:** adjustable synthetic supply and demand scenarios.
- **Settings:** sharing preference and offer rate.

All quantities are stored as integer Wh and prices as integer paise. Offer and trade mutations are persisted in SQLite. The hash-linked ledger is a tamper-evidence demonstration layered over the conventional database; it is not blockchain and does not make records immutable against a database administrator.

