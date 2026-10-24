# GridNova — A New Era of Connected Energy

GridNova is a local-first renewable-energy marketplace simulation. It uses FastAPI, SQLAlchemy, SQLite, and a responsive vanilla HTML/CSS/JavaScript client. The five starter households and their offers are fictional sample listings. New users create an account for one household; that account can buy energy or sell surplus without switching among other households.

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

Open http://127.0.0.1:8000. Create a household account on the sign-in page, or sign in with the email and password you registered. Existing fictional starter listings remain visible in the marketplace; starter profiles do not have sign-in credentials. SQLite creates `gridnova.db` in the current working directory. Set `GRIDNOVA_DATABASE_URL` to use another SQLAlchemy database URL.

## Account and session behavior

- Registration creates one household and one homeowner account. A household profile is tied to that account; the interface has no person or city switcher.
- Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes. Session tokens are random, stored as SHA-256 digests in SQLite, expire after 12 hours, and are sent in HttpOnly, SameSite=Strict cookies.
- State-changing API calls require a double-submit CSRF token. Set `GRIDNOVA_COOKIE_SECURE=1` when serving over HTTPS.
- Ownership and reviewer/admin roles come from the server-side account record. Forged `X-Demo-Role` and `X-Household-Id` headers do not grant access. Public registration can only create homeowner accounts; reviewer/admin accounts require trusted server-side provisioning.
- The server still defaults to loopback-only access. `GRIDNOVA_ALLOW_REMOTE_DEMO=1` disables that boundary and is not a production deployment setting.
- This is a starter authentication system, not a production identity service: there is no email verification, password reset, MFA, or login rate limiting. Use a maintained identity provider and deployment hardening before exposing real user data or remote access.

## Tests

Run the backend/API suite with:

```sh
python -m pytest -q
```

Browser tests use Playwright with Chromium at desktop and mobile viewports:

```sh
npm ci
npx playwright install chromium
npm run test:e2e
```

The API suite includes the authenticated account fixture, ownership boundaries, forged-role denial, purchase accounting/idempotency, lifecycle, and audit behavior. Browser workflows cover account creation/sign-in, separate buyer and seller accounts, marketplace, ledger, settings, simulator, and mobile navigation. Tests have been updated for household accounts; results for this revision have not yet been run.

## Application pages

- **Overview:** household and neighborhood energy balances, activity, and illustrative impact.
- **Energy Marketplace:** city-scoped offers, search/sort, and purchase dialogs.
- **My Energy:** household generation/consumption, offers, and generation record submission.
- **Transactions:** household ledger, search/filter, details, cancellation, and CSV export.
- **Verification & Impact:** household records and illustrative community analytics. Internal review statuses are not meter or authority verification.
- **Microgrid Simulator:** adjust assumptions and run a synthetic model.
- **Settings:** household sharing and offer-rate preferences.

## Simulation limits

All starter household profiles, production figures, offers, prices, and environmental estimates are synthetic. A purchase writes a simulated ledger entry; it does not transfer electricity or money. The app has no real meter connection, physical generation validation, official renewable-energy certification, or regulatory approval. “Verified” means reviewed in the application only. CO₂ values are estimates, not certified environmental claims.
