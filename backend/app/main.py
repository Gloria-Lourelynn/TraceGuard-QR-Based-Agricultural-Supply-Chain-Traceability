"""TraceGuard V2 API: authenticated roles, signed-QR handovers and auditable reviews."""
from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Iterator

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from . import auth, config, db, service
from .engine import checkpoints
from .qr import qr_png
from .schemas import (
    AnchorVerifyRequest,
    AssignmentCreate,
    EventCreate,
    FlagPatch,
    HandoverCreate,
    LoginRequest,
    ManualHandoverCreate,
    ShipmentCreate,
    UserCreate,
)
from .security import ID_RE, RateLimitMiddleware, SecurityHeadersMiddleware, login_throttle, parse_token, parse_rolling_payload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("traceguard")


def get_conn() -> Iterator:
    conn = db.connect(config.db_path())
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate production secrets before touching the persistent database.
    config.secret_key()
    conn = db.connect(config.db_path())
    db.init_db(conn)
    if config.is_production():
        # Fail closed if a database still contains the well-known shipped demo password.
        for row in conn.execute("SELECT username, password_hash FROM users WHERE active=1"):
            if auth.verify_password("TraceGuardDemo!2026", row["password_hash"]):
                conn.close()
                raise RuntimeError(f"Production startup blocked: account {row['username']!r} still uses the default demo password")
    filled = service.backfill_default_transporter(conn)
    if filled:
        log.info("auto-assigned %d older shipment(s) to the default transporter", filled)
    conn.close()
    yield


app = FastAPI(title="TraceGuard API", version="2.3.0", description="Role-based, evidence-driven agricultural shipment traceability.", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins(),
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
)


@app.exception_handler(service.NotFound)
async def _not_found(_: Request, __: service.NotFound):
    return JSONResponse({"detail": "Not found"}, 404)


@app.exception_handler(service.Forbidden)
async def _forbidden(_: Request, exc: service.Forbidden):
    return JSONResponse({"detail": str(exc)}, 403)


@app.exception_handler(service.Conflict)
async def _conflict(_: Request, exc: service.Conflict):
    return JSONResponse({"detail": str(exc)}, 409)


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    log.exception("unhandled error", exc_info=exc)
    return JSONResponse({"detail": "Internal server error"}, 500)


ShipmentId = Annotated[str, Path(pattern=ID_RE.pattern, max_length=20)]


def current_user(request: Request, conn=Depends(get_conn)) -> dict:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    claims = auth.verify_token(token) if scheme.lower() == "bearer" and token else None
    if not claims:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    if db.is_token_revoked(conn, token_hash):
        raise HTTPException(status_code=401, detail="Session has been signed out. Please sign in again.")
    user = db.get_user(conn, claims["sub"])
    if not user or not user.get("active"):
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user


def require_roles(*roles: str):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Your role is not allowed to perform this action")
        return user
    return dep


def ensure_can_access(conn, user: dict, shipment_id: str) -> dict:
    shipment = db.get_shipment(conn, shipment_id)
    if shipment is None:
        raise service.NotFound(shipment_id)
    role = user["role"]
    ok = role in {"admin", "inspector"}
    if role == "seller":
        ok = shipment.get("owner_id") == user["id"]
    elif role == "transporter":
        ok = db.is_assigned(conn, shipment_id, user["id"])
    if not ok:
        # Avoid confirming the existence of records outside the caller's scope.
        raise service.NotFound(shipment_id)
    return shipment


def visible_ids(conn, user: dict) -> set[str] | None:
    if user["role"] in {"admin", "inspector"}:
        return None
    if user["role"] == "seller":
        return {r[0] for r in conn.execute("SELECT id FROM shipments WHERE owner_id=?", (user["id"],))}
    return set(db.assignments_for_user(conn, user["id"]))


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.3.0"}


@app.post("/auth/login")
def login(body: LoginRequest, request: Request, conn=Depends(get_conn)):
    client_ip = request.client.host if request.client else "unknown"
    user_key = f"{body.username.strip().lower()}:{client_ip}"
    ip_key = f"ip:{client_ip}"

    locked_user, rem_user = login_throttle.is_locked(user_key)
    locked_ip, rem_ip = login_throttle.is_locked(ip_key)
    if locked_user or locked_ip:
        rem = max(rem_user, rem_ip)
        db.append_audit(conn, "LOGIN_BLOCKED_RATE_LIMIT", db.utcnow().isoformat(), None, {
            "username": body.username.strip(), "ip": client_ip, "remaining_seconds": rem
        })
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Temporarily locked for {rem} seconds."
        )

    result = auth.login(conn, body.username, body.password)
    if not result:
        login_throttle.record_failure(user_key)
        login_throttle.record_failure(ip_key)
        db.append_audit(conn, "LOGIN_FAILED", db.utcnow().isoformat(), None, {
            "username": body.username.strip(), "ip": client_ip
        })
        raise HTTPException(status_code=401, detail="Invalid username or password")

    login_throttle.record_success(user_key)
    login_throttle.record_success(ip_key)
    token, user = result
    db.append_audit(conn, "LOGIN_SUCCESS", db.utcnow().isoformat(), user["id"], {"username": user["username"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer", "expires_in": auth.TOKEN_TTL_SECONDS, "user": user}


@app.post("/auth/logout")
def logout(request: Request, conn=Depends(get_conn), user=Depends(current_user)):
    header = request.headers.get("Authorization", "")
    _, _, token = header.partition(" ")
    if token:
        service.logout_user(conn, token, user["id"])
    return {"status": "ok", "message": "Signed out successfully"}


@app.get("/auth/me")
def who_am_i(user=Depends(current_user)):
    return auth.public_user(user)


@app.get("/users")
def list_users(conn=Depends(get_conn), user=Depends(require_roles("admin"))):
    return db.list_users(conn)


@app.post("/users", status_code=201)
def create_user(body: UserCreate, conn=Depends(get_conn), user=Depends(require_roles("admin"))):
    created = service.create_user(conn, body.username, body.display_name, body.role, body.password)
    db.append_audit(conn, "USER_CREATED", db.utcnow().isoformat(), user["id"],
                    {"user_id": created["id"], "username": created["username"], "role": created["role"]})
    return auth.public_user(created)


@app.post("/assignments", status_code=201)
def assign(body: AssignmentCreate, conn=Depends(get_conn), user=Depends(require_roles("admin"))):
    return service.assign_shipment(conn, body.shipment_id, body.username, body.checkpoint_id, user["id"])


@app.get("/checkpoints")
def get_checkpoints(user=Depends(current_user)):
    return [{"id": x.id, "name": x.name, "demo_coordinates": x.demo} for x in checkpoints.CHECKPOINTS.values()]


@app.post("/shipments", status_code=201)
def register_shipment(body: ShipmentCreate, conn=Depends(get_conn), user=Depends(require_roles("seller", "admin"))):
    data = body.model_dump()
    data["created_by"] = user["display_name"]
    data["actor_id"] = user["id"]
    data["owner_id"] = user["id"] if user["role"] == "seller" else data.get("owner_id")
    registered = service.register_shipment(conn, data)
    # The transporter must be assigned before their first scan works; do it here so nobody
    # has to run a repair script (set TRACEGUARD_AUTO_ASSIGN_TRANSPORTER=off to disable).
    if service.auto_assign_default_transporter(conn, registered["shipment"]["id"], user["id"]):
        registered = service.detail(conn, registered["shipment"]["id"])
    return registered


@app.get("/shipments")
def list_shipments(q: str | None = Query(default=None, max_length=60), conn=Depends(get_conn), user=Depends(current_user)):
    allowed = visible_ids(conn, user)
    return [s for s in service.list_shipments(conn, q) if allowed is None or s["id"] in allowed]


@app.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: ShipmentId, conn=Depends(get_conn), user=Depends(current_user)):
    ensure_can_access(conn, user, shipment_id)
    return service.detail(conn, shipment_id)


@app.get("/shipments/{shipment_id}/qr")
def get_qr(shipment_id: ShipmentId, conn=Depends(get_conn), user=Depends(current_user)):
    shipment = db.get_shipment(conn, shipment_id)
    if shipment is None:
        raise service.NotFound(shipment_id)
    if user["role"] == "seller" and shipment.get("owner_id") != user["id"]:
        raise service.NotFound(shipment_id)
    if user["role"] == "transporter" and not db.is_assigned(conn, shipment_id, user["id"]):
        raise service.Forbidden("This shipment is not assigned to your account")
    if user["role"] not in {"seller", "admin", "transporter"}:
        raise service.Forbidden("Your role cannot issue shipment labels")
    payload = service.issue_rolling_qr(conn, shipment_id, user["id"])
    db.append_audit(conn, "QR_LABEL_DOWNLOADED", db.utcnow().isoformat(), user["id"], {"shipment_id": shipment_id})
    return Response(qr_png(payload), media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{shipment_id}-current.png"'})


@app.get("/shipments/{shipment_id}/scans")
def get_shipment_scans(shipment_id: ShipmentId, conn=Depends(get_conn), user=Depends(current_user)):
    ensure_can_access(conn, user, shipment_id)
    return db.list_scans(conn, shipment_id)


@app.post("/shipments/{shipment_id}/events", status_code=201)
def add_legacy_event(body: EventCreate, shipment_id: ShipmentId, conn=Depends(get_conn), user=Depends(require_roles("admin"))):
    """Admin-only correction/simulation route. Routine handovers must use signed QR scans."""
    data = body.model_dump()
    data["actor"] = user["display_name"]
    data["actor_id"] = user["id"]
    if body.timestamp is not None:
        # The admin-only route is explicitly an exception/simulation path; it preserves supplied historical times.
        pass
    return service.add_event(conn, shipment_id, data)


@app.post("/scans/handover", status_code=201)
def scan_handover(body: HandoverCreate, request: Request, conn=Depends(get_conn), user=Depends(require_roles("transporter", "admin"))):
    if not config.valid_checkpoint_device(body.checkpoint_id, request.headers.get("X-Checkpoint-Token")):
        raise HTTPException(status_code=403, detail="This checkpoint requires its registered device credential.")
    out = service.process_scan_handover(conn, user, body.scanned, body.checkpoint_id, body.action,
        body.idempotency_key, body.note, body.destination, body.quantity)
    if not out.get("found"):
        raise HTTPException(status_code=400, detail=out.get("message", "The QR was not accepted. No handover was recorded."))
    return out


@app.post("/scans/manual-handover", status_code=201)
def manual_handover(body: ManualHandoverCreate, conn=Depends(get_conn), user=Depends(require_roles("inspector", "admin"))):
    return service.process_manual_handover(conn, user, body.shipment_id, body.checkpoint_id,
        body.action, body.reason, body.idempotency_key)


@app.get("/verify/{scanned}")
def verify(scanned: str = Path(max_length=120), conn=Depends(get_conn), user=Depends(current_user)):
    rolling_sid, rolling_status = service.rolling_token_status(conn, scanned)
    if parse_rolling_payload(scanned)[0] is not None:
        sid, signature_ok = rolling_sid, rolling_status == "active"
    else:
        sid, signature_ok = parse_token(scanned)
    # Unsigned, expired, consumed, or forged labels must not disclose shipment data.
    if not sid or signature_ok is not True:
        return {"found": False, "verdict": "UNKNOWN", "signature_checked": False,
                "flags": [{"rule_code": "UNKNOWN_ID", "severity": "high",
                           "explanation": "A valid signed QR payload is required. No shipment data was disclosed."}],
                "detail": None}
    shipment = db.get_shipment(conn, sid)
    if shipment is None:
        return service.verify(conn, scanned)
    try:
        ensure_can_access(conn, user, sid)
    except service.NotFound:
        # Don't disclose whether a shipment exists outside this user's scope.
        return {"found": False, "verdict": "UNKNOWN", "signature_checked": True,
                "flags": [{"rule_code": "UNKNOWN_ID", "severity": "high",
                           "explanation": "This shipment is not available to your account."}], "detail": None}
    return service.verify(conn, scanned)


@app.get("/shipments/{shipment_id}/report")
def get_report(shipment_id: ShipmentId, conn=Depends(get_conn), user=Depends(current_user)):
    ensure_can_access(conn, user, shipment_id)
    return service.report(conn, shipment_id)


@app.get("/dashboard")
def get_dashboard(conn=Depends(get_conn), user=Depends(current_user)):
    allowed = visible_ids(conn, user)
    d = service.dashboard(conn)
    if allowed is None:
        return d
    items = [x for x in d["investigation_list"] if x["id"] in allowed]
    # Recalculate counts for this role's scope instead of leaking other users' totals.
    shipments = [x for x in service.list_shipments(conn) if x["id"] in allowed]
    flagged = [x for x in shipments if x["open_flag_count"]]
    by_status = {k: 0 for k in d["by_status"]}
    for x in shipments:
        by_status[x["status"]] = by_status.get(x["status"], 0) + 1
    # Build scoped alerts/events from the caller's own shipments instead of filtering
    # only the global top-eight lists (which could hide this user's older alerts).
    alerts = []
    recent_events = []
    if allowed:
        for sid in allowed:
            shipment = db.get_shipment(conn, sid)
            if not shipment:
                continue
            alerts.extend({**flag, "product": shipment["product"]}
                          for flag in db.list_flags(conn, sid) if flag["status"] == "open")
        placeholders = ",".join("?" for _ in allowed)
        recent_events = [dict(r) for r in conn.execute(
            f"SELECT e.id, e.shipment_id, e.type, e.checkpoint, e.actor, e.timestamp, s.product "
            f"FROM events e JOIN shipments s ON s.id=e.shipment_id "
            f"WHERE e.shipment_id IN ({placeholders}) ORDER BY e.id DESC LIMIT 8", tuple(allowed))]
    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda f: (severity_order.get(f["severity"], 3), -f["id"]))
    d.update({"total_shipments": len(shipments), "verified": len(shipments)-len(flagged),
              "under_investigation": len(flagged), "open_flags": sum(x["open_flag_count"] for x in shipments),
              "by_status": by_status, "investigation_list": flagged[:10],
              "alerts": alerts[:8], "recent_events": recent_events})
    return d


@app.patch("/flags/{flag_id}")
def patch_flag(body: FlagPatch, flag_id: int = Path(ge=1, le=2**31), conn=Depends(get_conn), user=Depends(require_roles("inspector", "admin"))):
    return service.update_flag(conn, flag_id, body.status, user["id"], body.reason)


@app.get("/audit/verify")
def audit_verify(conn=Depends(get_conn), user=Depends(require_roles("inspector", "admin"))):
    return {**service.verify_audit_chain(conn), "head_hash": db.audit_head(conn),
            "warning": "The chain detects edits/deletions if the expected head is trusted. Use external anchor receipts to detect database-level rewrites."}


@app.get("/audit/anchor")
def get_audit_anchor(conn=Depends(get_conn), user=Depends(require_roles("inspector", "admin"))):
    """Generate an externally verifiable, cryptographically signed audit anchor receipt."""
    return service.generate_audit_anchor(conn, user["id"])


@app.post("/audit/verify-anchor")
def verify_audit_anchor(body: AnchorVerifyRequest, conn=Depends(get_conn), user=Depends(require_roles("inspector", "admin"))):
    """Verify local database records against an external signed anchor receipt."""
    return service.verify_audit_anchor(conn, body.anchor, user["id"])


@app.get("/audit/records")
def list_audit_records(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conn=Depends(get_conn),
    user=Depends(require_roles("inspector", "admin"))
):
    """Inspect the live cryptographic audit chain."""
    return service.list_audit_log(conn, limit=limit, offset=offset)

