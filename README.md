# TraceGuard
### Trust-Aware Agricultural Supply Chain Traceability

**Single-use QR handovers · Cryptographic verification · Role-based access control · Explainable anomaly detection · Tamper-evident audit trails**

TraceGuard is a full-stack agricultural supply chain traceability platform that records produce shipments, verifies handovers, and identifies suspicious shipment activity. It combines cryptographically signed QR labels and server-side single-use token validation with shipment lifecycle checks, risk-prioritized anomaly findings, and auditable review workflows.

Unlike conventional QR tracking systems, TraceGuard does not treat a successful scan as proof that a shipment is legitimate. Every handover must pass backend validation, including checks against the QR token's state and the shipment's recorded history.

The platform is designed for farmers, transporters, inspectors, and administrators who need a more accountable way to track agricultural produce across supply chain checkpoints.

## Key Technical Highlights

| Capability | Engineering approach |
|---|---|
| Single-use QR handovers | Server-tracked tokens consumed after successful handovers |
| Cryptographic verification | Signed QR payloads validated by the backend |
| Replay prevention | Previously consumed tokens cannot authorize a new handover |
| Duplicate-request safety | Idempotency handling for safe retries without repeating a transaction |
| Access control | Backend-enforced role-based authorization and shipment permissions |
| Anomaly detection | Rule-based lifecycle, checkpoint, timing, quantity, and QR-reuse checks |
| Risk prioritization | Explainable risk scoring and deduplicated findings |
| Audit integrity | Hash-linked audit records and verifiable audit-anchor receipts |
| Data resilience | Persistent SQLite storage and integrity-checked backups |
| Application security | Password hashing, expiring bearer tokens, login throttling, request limits, and security headers |

## Features

### 1. End-to-End Shipment Traceability

- Register shipments with produce details, origin, destination, quantity, unit, and dispatch date.
- Maintain a chronological record of shipment checkpoints and handovers.
- View shipment status, event timelines, and relevant alerts according to user permissions.
- Generate and download QR labels for shipment handovers.
- Support shipment assignment and role-specific operational workflows.

### 2. Single-Use, Cryptographically Signed QR Handovers

TraceGuard implements a controlled QR handover protocol designed to prevent previously used shipment labels from authorizing additional handovers.

- **Cryptographic authenticity:** QR payloads are signed and validated by the backend.
- **Single-use tokens:** Each rolling QR label uses a server-tracked token that can authorize a handover only once.
- **Replay prevention:** After a successful handover, the token is consumed. Replaying the same label for another handover is rejected.
- **Server-side validation:** The backend checks token validity, expiry, consumption state, and shipment context instead of trusting the frontend.
- **Duplicate-request protection:** Idempotency handling supports safe retries while distinguishing them from attempts to reuse a token for a new transaction.
- **Invalid-label rejection:** Forged, expired, invalid, or already-consumed tokens cannot authorize a new handover.
- **Camera-based scanning:** Transporters scan labels through the browser interface to record checkpoint handovers.
- **Controlled workflow:** Shipment handovers are validated against server-side state rather than accepting a shipment ID alone as proof of authenticity.

**Why it matters:** A conventional QR image can be photographed, copied, and scanned repeatedly. TraceGuard combines signed payloads with server-side token state so that a previously consumed token cannot authorize a second handover.

Single-use enforcement applies to the tracked handover token. It does not prevent someone from copying the QR image itself or independently prove the physical identity of the produce.

### 3. Explainable Shipment Anomaly Detection

TraceGuard evaluates recorded shipment events against operational rules to identify suspicious activity.

Detection checks include:

- Invalid or unexpected shipment lifecycle transitions.
- Repeated checkpoint activity and patterns consistent with QR reuse.
- Implausible travel intervals between checkpoints.
- Inconsistent event timestamps or shipment quantities.
- Other rule-defined inconsistencies in shipment history.

The anomaly engine assigns risk-priority scores to help users focus on higher-priority findings. Recurring findings are deduplicated to reduce repetitive alerts.

Inspectors can investigate findings, record review decisions, dismiss supported alerts with a reason, and preserve an auditable trail of those decisions.

**Important:** These are rule-based anomaly indicators, not definitive proof of food fraud, physical tampering, or counterfeit produce.

### 4. Role-Based Access Control (RBAC)

Authorization is enforced by the backend rather than relying solely on frontend visibility.

| Role | Responsibilities |
|---|---|
| Seller / Farmer | Register shipments, access owned shipments, generate QR labels |
| Transporter / Operator | Access assigned shipments and record authorized checkpoint handovers by scanning labels |
| Inspector | Investigate shipment histories, review alerts, and record findings and decisions |
| Administrator | Manage users and assignments, access operational records, and perform authorized administrative audit actions |

Development mode can automatically assign newly created shipments to the demo transporter account. This behavior is configurable.

### 5. Tamper-Evident Audit Trail

TraceGuard maintains a linked audit history designed to make unauthorized record alteration detectable.

- Connect audit records using a hash chain.
- Verify the integrity and continuity of recorded audit events.
- Export and verify signed audit-anchor receipts.
- Support verification of a retained audit-chain head independently of the application's current database state, subject to the available receipt and verification material.
- Record supported review and administrative actions for accountability.

A hash chain does not guarantee that every event was recorded or prevent all forms of database manipulation. Independently retained anchor receipts strengthen verification of previously recorded history.

### 6. Authentication and Application Security

- Password hashing for stored credentials.
- Expiring bearer-token authentication.
- Login throttling and request rate limits.
- Security response headers and bounded request schemas.
- Server-side permission checks on protected routes.
- Production startup checks for required secrets, permitted origins, and unchanged default demo passwords.
- Configurable checkpoint-device token requirements.

Production deployments still require HTTPS, secure secret management, access restrictions, and appropriate operational monitoring.

### 7. Dashboard, Reports, and Administration

- Shipment status summaries and operational dashboards.
- Risk indicators and anomaly finding views.
- Shipment details and chronological event histories.
- Inspector review workflows.
- Administrative user and assignment management.
- Audit-related operational tools.

## Technology Stack

### Frontend
- **React + TypeScript** — component-based user interface and typed application code.
- **Vite** — frontend development server and production bundler.
- **Tailwind CSS** — interface styling.
- **React Router** — client-side page navigation.
- **qr-scanner** — browser-based QR scanning.

### Backend
- **Python 3.12** — application and rule-engine implementation.
- **FastAPI** — REST API and request handling.
- **Pydantic** — request and data-schema validation.
- **Uvicorn** — ASGI application server.

### Data, Security, and Testing
- **SQLite** — persistent application data.
- **`qrcode` + Pillow** — QR label generation.
- **Cryptographic signing and hashing** — QR authenticity checks and audit integrity.
- **pytest + HTTPX** — automated backend and API testing.
- **Python standard library** — supporting utilities and unit tests.

## Architecture

```text
┌──────────────────────────────────────────────┐
│            React + TypeScript UI             │
│ Dashboard · Shipments · QR Scanner · Reports │
└──────────────────────┬───────────────────────┘
                       │ HTTP API
┌──────────────────────▼───────────────────────┐
│                  FastAPI                     │
│ Authentication · Validation · RBAC           │
├──────────────────────────────────────────────┤
│              Shipment Services               │
│ Registration · Assignment · Handovers        │
├──────────────────────────────────────────────┤
│            QR Security Layer                 │
│ Signed Payloads · Single-Use Tokens           │
│ Server-Side Validation · Replay Prevention    │
├──────────────────────────────────────────────┤
│                Rule Engine                   │
│ Lifecycle Checks · QR Reuse · Risk Scoring   │
├──────────────────────────────────────────────┤
│                 Audit Layer                  │
│ Hash Chain · Audit-Anchor Verification       │
├──────────────────────────────────────────────┤
│                  SQLite                      │
│ Shipments · Events · Findings · Audit Data   │
└──────────────────────────────────────────────┘
```

## Getting Started

### Prerequisites

- Windows 10/11 or another compatible operating system.
- Python 3.12.
- Node.js and npm.
- Git, if cloning the repository.

### Windows Quick Start

Run the following commands from the project root in PowerShell.

**1. Set up the backend**

```powershell
.\setup_windows.ps1
```

The setup script creates the backend virtual environment, installs dependencies, and prepares demo data.

**2. Start the backend**

Open a terminal in the project root:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**3. Start the frontend**

Open a second terminal in the project root:

```powershell
cd frontend
npm ci
npm run dev
```

**4. Open the application**

- Frontend: http://127.0.0.1:5173
- API health check: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

The backend binds to a loopback address for local development. The API documentation is intended for development and should not be exposed publicly without appropriate controls.

### Manual Backend Setup

From the repository root:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Manual Frontend Setup

In a separate terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Using the virtual environment's Python executable directly helps ensure dependencies are installed into the intended environment.

## Demo Accounts

The development seed script creates missing demo accounts using the default development password `TraceGuardDemo!2026`, unless `TRACEGUARD_DEMO_PASSWORD` is configured before seeding. Existing accounts are not automatically reset.

| Role | Username |
|---|---|
| Seller / Farmer | `seller` |
| Transporter / Operator | `transporter` |
| Inspector | `inspector` |
| Administrator | `admin` |

**Demo credentials are for local testing only.** Never reuse these credentials in a public or production deployment.

To choose a different password before seeding, run from the `backend` directory:

```powershell
$env:TRACEGUARD_DEMO_PASSWORD = "Choose-A-Long-Password!"
.\.venv\Scripts\python.exe seed.py
```

To reset the four demo account passwords without deleting shipment records:

```powershell
$env:TRACEGUARD_DEMO_PASSWORD = "Choose-A-Long-Password!"
.\.venv\Scripts\python.exe seed.py --reset-demo-passwords
```

The destructive `seed.py --reset` option replaces the configured local database. Use it only when you intentionally want to reset demo data.

## Suggested Demonstration Workflow

1. Sign in as the seller and register a produce shipment.
2. Generate and download its QR label.
3. Sign in as the assigned transporter and scan the label at a checkpoint.
4. Review the updated shipment timeline and handover status.
5. Attempt to reuse the consumed QR token and observe the server's rejection.
6. Retry a previously processed request, where supported, to demonstrate idempotency handling.
7. Sign in as the inspector and investigate available anomaly findings.
8. Record a review decision and inspect the associated history.
9. Explore administrative assignments and audit-related features.

The availability of a particular anomaly depends on the seeded scenario and recorded events. Browser camera access requires permission and generally works on `localhost` or HTTPS.

## Testing and Quality Checks

Run backend tests from the `backend` directory:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The test suite covers areas including:

- API authentication and role restrictions.
- Shipment ownership and transporter assignments.
- Signed QR validation and handover behavior.
- Idempotency and duplicate request handling.
- Anomaly rules and finding-review workflows.
- Audit-chain integrity.
- Repeatable demo seeding.
- Database backup integrity.

Build the frontend for production from the `frontend` directory:

```powershell
npm ci
npm run build
```

Running the development server alone does not establish that the production build succeeds.

## Configuration

The application stores its SQLite database and development signing key under `backend/data/` by default. This directory is excluded from version control.

| Environment variable | Purpose |
|---|---|
| `TRACEGUARD_ENV` | Enables production startup checks when set to `production` |
| `TRACEGUARD_DB` | Overrides the SQLite database path |
| `TRACEGUARD_DATA_DIR` | Overrides the application data directory |
| `TRACEGUARD_SECRET` | Supplies the master secret |
| `TRACEGUARD_SECRET_FILE` | Loads the master secret from a protected file |
| `TRACEGUARD_ORIGINS` | Defines permitted frontend origins for CORS |
| `TRACEGUARD_AUTO_ASSIGN_TRANSPORTER` | Sets the default transporter username, or `off` to disable automatic assignment |
| `TRACEGUARD_REQUIRE_CHECKPOINT_DEVICE` | Enables checkpoint-device token requirements |
| `TRACEGUARD_CHECKPOINT_DEVICE_TOKENS` | Configures checkpoint IDs and associated secrets as a JSON mapping |

For production deployment:

- Configure a strong secret of at least 32 bytes through a protected file or secret manager.
- Use explicit HTTPS frontend origins and serve the application over HTTPS.
- Replace all demo credentials.
- Restrict database and backup access.
- Protect signing material and rotate secrets according to an operational policy.
- Review authentication, authorization, backup recovery, and audit-verification behavior before deployment.

Production mode includes startup checks for required configuration and default demo passwords, but these checks do not replace a full security review.

## Database Backups

Run from the `backend` directory:

```powershell
.\.venv\Scripts\python.exe backup_db.py
```

Backups are written to `backend/data/backups/` by default. The utility checks SQLite integrity and refuses to overwrite an existing destination.

Keep production backups in access-controlled storage separate from the application host where possible.

## Project Structure

```text
traceguard-v2/
├── backend/
│   ├── app/
│   │   ├── engine/
│   │   │   ├── audit_chain.py
│   │   │   ├── checkpoints.py
│   │   │   ├── clone.py
│   │   │   ├── risk.py
│   │   │   ├── rules.py
│   │   │   └── states.py
│   │   ├── auth.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── main.py
│   │   ├── qr.py
│   │   ├── schemas.py
│   │   ├── security.py
│   │   └── service.py
│   ├── tests/
│   ├── seed.py
│   ├── backup_db.py
│   ├── rotate_secret.py
│   └── requirements*.txt
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   └── pages/
│   ├── package.json
│   └── vite.config.ts
├── setup_windows.ps1
├── .gitignore
└── README.md
```

## Project Goal

TraceGuard explores how single-use cryptographic QR handovers, least-privilege access, event-consistency rules, and tamper-evident records can work together to improve agricultural supply chain transparency and make suspicious activity easier to investigate.

**Built with React, TypeScript, FastAPI, Python, SQLite, and cryptographic verification.**

