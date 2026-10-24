# GridNova — A New Era of Connected Energy

GridNova is a local-first web application concept for a peer-to-peer renewable-energy marketplace for Indian households. It includes a FastAPI + SQLAlchemy + SQLite API and a responsive vanilla HTML/CSS/JavaScript client. The five seeded households are fictional and located in Bengaluru, Hyderabad, Pune, Chennai, and Jaipur.

## Run locally

Use Python 3.10 or newer.

```sh
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.app:app --reload
```

Open http://127.0.0.1:8000 for the client and http://127.0.0.1:8000/docs for the API. The database is created as `gridnova.db` in the working directory on first startup. Set `GRIDNOVA_DATABASE_URL` to use a different SQLAlchemy database URL. The UI calls the same-origin `/api` endpoints.

## Test

```sh
pytest -q
```

The API tests use an isolated temporary SQLite database and exercise household scope, generation reference uniqueness, review permissions, round-half-up paise accounting, offer expiry/withdrawal, idempotent retries, duplicate commitments, cancellation and release, audit persistence, simulator/settings persistence, and concurrent purchases.

## Application features

- **Overview:** API-backed household and community generation, consumption, surplus, demand, trade activity, and illustrative impact estimates.
- **Energy Marketplace:** persisted independent offers with expiry and withdrawal, source/city search and sorting, listing, and purchase dialogs. Purchases require idempotency keys for safe retries.
- **My Energy:** edit synthetic generation/consumption, set a price, and submit generation records.
- **Transactions:** search and filter persistent trades, inspect details, cancel eligible trades, and export CSV.
- **Verification & Impact:** verifier-role review actions, generation records, community analytics, and clearly labeled impact estimates.
- **Microgrid Simulator:** adjustable solar and demand inputs with server-computed share potential.
- **Settings:** household sharing/rate preferences and admin demo reset.

The role selector is a presentation/demo feature, not authentication or production authorization. API ownership checks demonstrate the intended boundary only; do not deploy this demo as a secure multi-user service without real authentication and authorization.

## Simulation limits

All household profiles, generation values, offers, prices, trades, and environmental estimates are fictional/synthetic. A purchase only creates a demo ledger entry; it does not transfer electricity or money. The application does not connect to real meters, validate physical generation, issue official renewable-energy certificates, or claim regulatory approval. “Verified” is an internal demo review status only.
