# TraceGuard

**Agricultural shipment traceability with signed QR handovers, role-based access, and evidence-backed anomaly alerts.**

TraceGuard is a web application prototype for recording produce shipments and their handovers across a supply chain. Sellers register shipments and issue QR labels; assigned transporters scan labels at checkpoints; inspectors review suspicious histories; administrators manage users and assignments.

It is designed to demonstrate how a traceability workflow can detect inconsistencies that a QR scan alone cannot prevent.

## Features

### Shipment traceability
- Register produce shipments with product, origin, destination, quantity, unit, and dispatch date.
- Create a shipment history from checkpoint events and handovers.
- View shipment details, event timelines, status, and relevant alerts according to the signed-in user's permissions.
- Generate and download QR labels for shipment handovers.

### Signed QR handovers
- QR payloads are cryptographically signed and checked by the backend.
- Rolling labels use server-tracked, single-use tokens; a successful handover consumes the token.
- Reject invalid, expired, consumed, or forged labels for new handovers.
- Idempotency handling protects against accidental duplicate submissions and supports safe retries.
- Camera scanning is available in the browser. Manual entry is not treated as proof of a valid signed label.

### Anomaly detection and review
- Check shipment event order and lifecycle consistency.
- Flag suspicious histories such as repeated checkpoint activity, implausible travel between checkpoints, and inconsistent timestamps or quantities.
- Detect patterns consistent with QR reuse across checkpoints.
- Calculate an explainable risk-priority score and deduplicate recurring findings.
- Let inspectors review or dismiss findings with a recorded reason; supported manual exceptions are auditable.

### Access control and administration
The backend enforces role-based access control (RBAC) on API routes and shipment data.

| Role | Main capabilities |
|---|---|
| Seller / farmer | Register shipments, view owned shipments, download labels |
| Transporter / operator | View assigned shipments and record checkpoint handovers by scanning labels |
| Inspector | Review shipment histories, investigate alerts, record review decisions |
| Admin | Manage users and assignments, access operational records, and perform administrative audit actions |

New shipments are assigned to the demo `transporter` account by default in development. This can be configured or disabled using `TRACEGUARD_AUTO_ASSIGN_TRANSPORTER`.

### Security and data integrity
- Password hashing and expiring bearer-token authentication.
- Login throttling, request rate limits, security response headers, and bounded request schemas.
- Audit records linked by a tamper-evident hash chain.
- Export and verify signed audit-anchor receipts so a chain head can be checked outside the application database.
- Persistent SQLite storage and an integrity-checked backup utility.
- Production-mode startup checks for secrets, HTTPS origins, and unchanged demo passwords.

### Dashboard and reports
- Shipment dashboard, status summaries, risk indicators, and alert views.
- Shipment detail and event history views.
- Reports and administrative screens.

## Technology stack

- **Frontend:** React, TypeScript, Vite, Tailwind CSS, React Router, `qr-scanner`
- **Backend:** Python 3.12, FastAPI, Pydantic, Uvicorn
- **Database:** SQLite
- **QR generation:** `qrcode` with Pillow
- **Testing:** pytest and HTTPX, plus standard-library unit tests

## Requirements

- Windows 10/11 or another Python-compatible operating system
- Python **3.12** (Windows setup script uses the Python Launcher: `py -3.12`)
- Node.js and npm
- Git (optional, for cloning)

## Quick start on Windows

Open PowerShell in the project root.

1. Create the backend virtual environment, install dependencies, and seed demo data:

   ```powershell
   .\setup_windows.ps1
   ```

2. Start the backend in a PowerShell terminal:

   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

3. In a second terminal, install frontend packages and start the UI:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

4. Open the application at **http://127.0.0.1:5173**.

   API health check: http://127.0.0.1:8000/health  
   Interactive API docs: http://127.0.0.1:8000/docs

The setup script expects standard Python 3.12. It intentionally calls the virtual environment's Python executable directly to avoid accidentally installing packages into a different Python installation.

## Manual setup

### Backend

Run these commands from the repository root in PowerShell:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend

In a separate terminal from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

### Demo credentials

The seed script creates missing demo accounts using the development password `TraceGuardDemo!2026`, unless `TRACEGUARD_DEMO_PASSWORD` is set before running the seed script. Existing accounts are not automatically reset.

| Role | Username |
|---|---|
| Seller / farmer | `seller` |
| Transporter / operator | `transporter` |
| Inspector | `inspector` |
| Admin | `admin` |

These are **local demonstration credentials only**. Do not reuse them for a public deployment or shared environment. For a fresh demo password in PowerShell, set it before seeding:

```powershell
$env:TRACEGUARD_DEMO_PASSWORD = "Choose-A-Long-Password!"
.\.venv\Scripts\python.exe seed.py
```

To reset the four demo account passwords without deleting shipment records:

```powershell
$env:TRACEGUARD_DEMO_PASSWORD = "Choose-A-Long-Password!"
.\.venv\Scripts\python.exe seed.py --reset-demo-passwords
```

The destructive `seed.py --reset` option replaces the configured local database. Do not use it if you need to preserve existing records.

## Suggested demo flow

1. Sign in as `seller` and register a produce shipment.
2. Download its QR label.
3. Sign in as `transporter`, open the assigned shipment workflow, and scan the label at a checkpoint.
4. Review the updated shipment timeline.
5. Open the inspector view to examine any generated findings and record a review decision.
6. Open the admin view to explore users, assignments, and audit-related tools.
7. Try the seeded example journeys to compare normal and suspicious histories.

Camera scanning requires browser camera permission. Camera access is generally available on `localhost` or over HTTPS.

## Tests

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The test suite covers API authentication and role restrictions, shipment ownership and assignments, signed QR validation, handover idempotency, anomaly rules, finding reviews, audit-chain integrity, repeatable demo seeding, and database backups.

## Configuration and data

The application creates its SQLite database and development signing key under `backend/data/` by default. This directory is excluded from version control. The database persists across backend restarts.

| Variable | Purpose |
|---|---|
| `TRACEGUARD_ENV` | Set to `production` to enable production startup checks |
| `TRACEGUARD_DB` | Override the SQLite database file path |
| `TRACEGUARD_DATA_DIR` | Override the application data directory |
| `TRACEGUARD_SECRET` | Supply a master secret (at least 32 bytes) |
| `TRACEGUARD_SECRET_FILE` | Read the master secret from a protected file |
| `TRACEGUARD_ORIGINS` | Comma-separated frontend origins allowed by CORS |
| `TRACEGUARD_AUTO_ASSIGN_TRANSPORTER` | Default transporter username, or `off` to disable automatic assignment |
| `TRACEGUARD_REQUIRE_CHECKPOINT_DEVICE` | Require configured checkpoint-device tokens when enabled |
| `TRACEGUARD_CHECKPOINT_DEVICE_TOKENS` | JSON mapping of checkpoint IDs to unique secrets |

For a production deployment, configure a secret of at least 32 bytes through a secret manager or protected secret file, set explicit HTTPS frontend origins, replace demo credentials, use HTTPS, restrict database and backup access, and conduct a security review. Production mode intentionally refuses to start if required configuration is missing or active accounts still use the default demo password.

Create a consistent backup from the `backend` directory:

```powershell
.\.venv\Scripts\python.exe backup_db.py
```

Backups are written under `backend/data/backups/` by default. The utility checks SQLite integrity and refuses to overwrite an existing destination.

## Project structure

```text
traceguard-v2/
├── backend/
│   ├── app/
│   │   ├── engine/          Shipment rules, checkpoint checks, risk scoring, QR-reuse detection, audit chain
│   │   ├── main.py          FastAPI routes and role enforcement
│   │   ├── auth.py          Authentication and tokens
│   │   ├── security.py      Signed QR payloads and request protections
│   │   ├── service.py       Shipment and handover workflows
│   │   ├── db.py            SQLite persistence
│   │   └── schemas.py       Request validation
│   ├── tests/               API, service, and engine tests
│   ├── seed.py              Demo accounts and example shipment histories
│   ├── backup_db.py         Integrity-checked database backups
│   └── requirements*.txt    Python dependencies
├── frontend/
│   ├── src/pages/           Login, dashboard, registration, scanning, shipment, reports, admin
│   ├── src/api/client.ts    Typed API client
│   └── package.json
├── setup_windows.ps1
└── README.md
```

## Scope and limitations

TraceGuard is a **prototype**, not a production-certified food-safety or anti-counterfeiting system.

- A valid signed QR proves that a label payload was issued by this application; it does not prove the physical produce is genuine or that the label has not been copied.
- A copied current label may be used before the legitimate token is consumed. Single-use tokens and anomaly alerts reduce some risks but cannot eliminate them.
- Browser camera scanning is a user-interface workflow, not cryptographic proof that a camera was used.
- Checkpoints and coordinates are demonstration data. The system does not independently prove a user's physical location.
- The audit hash chain helps reveal changes when compared with a trusted reference. If an attacker controls the database and its only reference, they may be able to rewrite the chain; export audit anchors to independently controlled storage.
- SQLite and in-process rate limiting are intended for a local demonstration, not a horizontally scaled deployment.

