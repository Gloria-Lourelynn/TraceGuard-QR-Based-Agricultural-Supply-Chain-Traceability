"""Business logic between the API routes, the repository and the engine.

Kept free of FastAPI so it can be tested directly. The flow for every event:
API -> service.add_event -> repository saves it -> engine replays the history
-> new flags are stored. Flagged events are saved (history stays complete).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from . import auth, config, db
from .engine.rules import DEFAULT_CONFIG, SEVERITY, RuleConfig, evaluate_history, unknown_id_flag
from .engine.states import State, expected_next
from .security import parse_token, parse_rolling_payload, make_rolling_payload, derive_rolling_token
from .engine import audit_chain, checkpoints, clone, risk

log = logging.getLogger("traceguard")
_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I - readable on labels


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class Conflict(Exception):
    pass


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def new_shipment_id(now: datetime | None = None) -> str:
    year = (now or db.utcnow()).year
    return f"TG-{year}-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(6))


def _verdict(open_count: int) -> str:
    return "REQUIRES_INVESTIGATION" if open_count else "VERIFIED"


def register_shipment(conn: sqlite3.Connection, data: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or db.utcnow()
    dd = data["dispatch_date"]
    row = {
        "product": data["product"],
        "origin": data["origin"],
        "destination": data["destination"],
        "quantity": data["quantity"],
        "unit": data["unit"],
        "dispatch_date": dd.isoformat() if isinstance(dd, date) else str(dd),
        "created_by": data["created_by"],
        "owner_id": data.get("owner_id"),
        "created_at": _iso(now),
    }
    for _ in range(10):  # random IDs: retry on the (very unlikely) collision
        row["id"] = new_shipment_id(now)
        try:
            db.insert_shipment(conn, row)
            break
        except sqlite3.IntegrityError:
            continue
    else:  # pragma: no cover
        raise RuntimeError("could not allocate a shipment id")
    db.append_audit(conn, "SHIPMENT_REGISTERED", _iso(now), data.get("actor_id") or data.get("owner_id"),
                    {"shipment_id": row["id"], "product": row["product"], "origin": row["origin"],
                     "destination": row["destination"]})
    log.info("registered %s by %s", row["id"], row["created_by"])
    return detail(conn, row["id"], now)


def detail(conn: sqlite3.Connection, shipment_id: str, now: datetime | None = None,
           cfg: RuleConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    shipment = db.get_shipment(conn, shipment_id)
    if shipment is None:
        raise NotFound(shipment_id)
    events = db.list_events(conn, shipment_id)
    evaluation = evaluate_history(shipment, events, now, cfg)
    flags = db.list_flags(conn, shipment_id)
    by_event: dict[int, list[dict[str, Any]]] = {}
    for f in flags:
        by_event.setdefault(f["event_id"], []).append(f)
    open_count = sum(1 for f in flags if f["status"] == "open")
    return {
        "shipment": shipment,
        "status": evaluation.status.value,
        "verdict": _verdict(open_count),
        "open_flag_count": open_count,
        "expected_next": expected_next(evaluation.status),
        "events": [
            {
                **e,
                "timestamp": _iso(e["timestamp"]),
                "valid": e["id"] in evaluation.valid_event_ids,
                "flags": by_event.get(e["id"], []),
            }
            for e in events
        ],
        "flags": flags,
        "scans": [
            {**scan, "scanned_at": _iso(scan["timestamp"]), "timestamp": _iso(scan["timestamp"])}
            for scan in db.list_scans(conn, shipment_id)
        ],
        "risk": risk.assess([
            {"incident_key": f.get("incident_key") or f"{f['rule_code']}:{f.get('event_id') or f['id']}",
             "rule_code": f["rule_code"], "severity": f["severity"], "status": f["status"]}
            for f in flags
        ]),
    }


def _summary(shipment: dict[str, Any], status: str, open_count: int) -> dict[str, Any]:
    return {**shipment, "status": status, "verdict": _verdict(open_count), "open_flag_count": open_count}


def list_shipments(conn: sqlite3.Connection, q: str | None = None) -> list[dict[str, Any]]:
    counts = db.open_flag_counts(conn)
    out = []
    for s in db.search_shipments(conn, q):
        status = evaluate_history(s, db.list_events(conn, s["id"])).status.value
        out.append(_summary(s, status, counts.get(s["id"], 0)))
    return out


def add_event(conn: sqlite3.Connection, shipment_id: str, data: dict[str, Any],
              now: datetime | None = None, cfg: RuleConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    now = now or db.utcnow()
    shipment = db.get_shipment(conn, shipment_id)
    if shipment is None:
        raise NotFound(shipment_id)
    ts = data.get("timestamp") or now
    event_id = db.insert_event(conn, {
        "shipment_id": shipment_id,
        "type": str(data["type"].value if isinstance(data["type"], State) else data["type"]),
        "checkpoint": data["checkpoint"],
        "actor": data["actor"],
        "timestamp": _iso(ts),
        "note": data.get("note", ""),
        "destination": data.get("destination"),
        "quantity": data.get("quantity"),
        "source_scan_id": data.get("source_scan_id"),
    })
    db.append_audit(conn, "SHIPMENT_EVENT_RECORDED", _iso(now), data.get("actor_id"), {
        "shipment_id": shipment_id, "event_id": event_id, "type": str(data["type"].value if isinstance(data["type"], State) else data["type"]),
        "checkpoint": data["checkpoint"], "actor": data["actor"], "timestamp": _iso(ts),
    })
    evaluation = evaluate_history(shipment, db.list_events(conn, shipment_id), now, cfg)
    new = [f for f in evaluation.flags if f.event_id == event_id]
    flag_ids = db.insert_flags(conn, shipment_id, new, _iso(now))
    for flag_id, flag in zip(flag_ids, new):
        db.append_audit(conn, "RULE_FINDING_RAISED", _iso(now), data.get("actor_id"),
                        {"flag_id": flag_id, "shipment_id": shipment_id, "event_id": event_id,
                         "rule_code": flag.rule_code, "severity": flag.severity})
    log.info("event %s on %s -> status=%s new_flags=%s", event_id, shipment_id,
             evaluation.status.value, [f.rule_code for f in new])
    d = detail(conn, shipment_id, now, cfg)
    return {"event_id": event_id, "new_flags": [
        {"rule_code": f.rule_code, "severity": f.severity, "explanation": f.explanation} for f in new
    ], "detail": d}


def verify(conn: sqlite3.Connection, scanned: str, now: datetime | None = None) -> dict[str, Any]:
    rolling_sid, rolling_status = rolling_token_status(conn, scanned)
    if rolling_sid:
        shipment_id, sig_ok = rolling_sid, rolling_status == "active"
    else:
        shipment_id, sig_ok = parse_token(scanned)
    shipment = db.get_shipment(conn, shipment_id) if shipment_id else None
    if shipment is None or sig_ok is False:
        # Same response for "unknown" and "bad signature": don't reveal which IDs exist.
        f = unknown_id_flag(scanned)
        log.warning("verify UNKNOWN_ID input=%r", scanned[:40])
        return {
            "found": False,
            "verdict": "UNKNOWN",
            "signature_checked": sig_ok is not None,
            "flags": [{"rule_code": f.rule_code, "severity": f.severity, "explanation": f.explanation}],
            "detail": None,
        }
    d = detail(conn, shipment["id"], now)
    log.info("verify %s -> %s", shipment["id"], d["verdict"])
    return {"found": True, "verdict": d["verdict"], "signature_checked": sig_ok is True,
            "flags": [], "detail": d, "rolling_label": bool(rolling_sid)}


def report(conn: sqlite3.Connection, shipment_id: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or db.utcnow()
    d = detail(conn, shipment_id, now)
    d["generated_at"] = _iso(now)
    d["conclusion"] = (
        "No open flags. The recorded history is consistent with the rules checked."
        if d["verdict"] == "VERIFIED"
        else f"{d['open_flag_count']} open flag(s) require investigation. "
             "This report does not conclude that fraud occurred."
    )
    d["rules_checked"] = sorted(set(SEVERITY) | {"CROSS_CHECKPOINT_REUSE", "REPEATED_SCAN", "UNVERIFIABLE_SCANS"})
    return d


def dashboard(conn: sqlite3.Connection) -> dict[str, Any]:
    items = list_shipments(conn)
    by_status = {s.value: 0 for s in State}
    for i in items:
        by_status[i["status"]] += 1
    flagged = [i for i in items if i["open_flag_count"]]
    open_flags = db.open_flags(conn, 8)
    return {
        "total_shipments": len(items),
        "verified": len(items) - len(flagged),
        "under_investigation": len(flagged),
        "by_status": by_status,
        "open_flags": sum(i["open_flag_count"] for i in items),
        "investigation_list": flagged[:10],
        "recent_events": db.recent_events(conn, 8),
        "alerts": open_flags,
    }


def update_flag(conn: sqlite3.Connection, flag_id: int, status: str, reviewer_id: str | None = None, reason: str = "Reviewed via service") -> dict[str, Any]:
    if db.get_flag(conn, flag_id) is None:
        raise NotFound(str(flag_id))
    db.set_flag_status(conn, flag_id, status)
    now = db.utcnow()
    if reviewer_id:
        db.add_flag_review(conn, flag_id, reviewer_id, status, reason, _iso(now))
    db.append_audit(conn, "FLAG_REVIEWED", _iso(now), reviewer_id, {"flag_id": flag_id, "status": status, "reason": reason})
    log.info("flag %s -> %s", flag_id, status)
    return db.get_flag(conn, flag_id)  # type: ignore[return-value]

def create_user(conn: sqlite3.Connection, username: str, display_name: str, role: str,
                password: str, now: datetime | None = None) -> dict[str, Any]:
    if role not in auth.ROLES:
        raise ValueError("Invalid role")
    username = username.strip()
    if db.get_user_by_username(conn, username):
        raise Conflict("That username already exists")
    user_id = secrets.token_hex(12)
    timestamp = _iso(now or db.utcnow())
    db.create_user(conn, {"id": user_id, "username": username, "display_name": display_name.strip(),
                          "role": role, "password_hash": auth.hash_password(password), "active": 1,
                          "created_at": timestamp})
    return db.get_user(conn, user_id)  # type: ignore[return-value]


def assign_shipment(conn: sqlite3.Connection, shipment_id: str, username: str, checkpoint_id: str | None,
                    assigned_by: str, now: datetime | None = None) -> dict[str, Any]:
    if db.get_shipment(conn, shipment_id) is None:
        raise NotFound(shipment_id)
    user = db.get_user_by_username(conn, username)
    if not user:
        raise NotFound(username)
    if user["role"] != "transporter":
        raise Conflict("Shipments can only be assigned to transporter accounts")
    if checkpoint_id and not checkpoints.get(checkpoint_id):
        raise Conflict("Unknown checkpoint")
    timestamp = _iso(now or db.utcnow())
    assignment_id = db.assign_shipment(conn, {"shipment_id": shipment_id, "user_id": user["id"],
        "checkpoint_id": checkpoint_id, "assigned_by": assigned_by, "created_at": timestamp})
    db.append_audit(conn, "SHIPMENT_ASSIGNED", timestamp, assigned_by,
                    {"shipment_id": shipment_id, "username": user["username"], "checkpoint_id": checkpoint_id})
    return {"id": assignment_id, "shipment_id": shipment_id, "user": auth.public_user(user), "checkpoint_id": checkpoint_id}




def auto_assign_default_transporter(conn: sqlite3.Connection, shipment_id: str,
                                    assigned_by: str | None, now: datetime | None = None) -> bool:
    """Assign a shipment to the configured default transporter (see config.auto_assign_transporter).

    Returns True if a new assignment was created. Does nothing when the feature is off,
    the account is missing/inactive/not a transporter, or the shipment is already assigned.
    Goes through assign_shipment so the assignment is written to the audit chain.
    """
    username = config.auto_assign_transporter()
    if not username or not assigned_by:
        return False
    user = db.get_user_by_username(conn, username)
    if not user or not user.get("active") or user["role"] != "transporter":
        return False
    if db.is_assigned(conn, shipment_id, user["id"]):
        return False
    assign_shipment(conn, shipment_id, user["username"], None, assigned_by, now)
    return True


def backfill_default_transporter(conn: sqlite3.Connection) -> int:
    """Give the default transporter access to older shipments that nobody has been assigned to."""
    username = config.auto_assign_transporter()
    admin = conn.execute("SELECT id FROM users WHERE role='admin' AND active=1 ORDER BY created_at LIMIT 1").fetchone()
    if not username or not admin:
        return 0
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM shipments WHERE id NOT IN (SELECT shipment_id FROM shipment_assignments)")]
    return sum(auto_assign_default_transporter(conn, sid, admin[0]) for sid in ids)


def _record_scan_findings(conn: sqlite3.Connection, shipment_id: str, actor_id: str | None,
                          now: datetime) -> None:
    """Persist detector findings once per stable incident key and audit new findings."""
    persisted = db.list_scans(conn, shipment_id)
    detector_input = [{"id": x["id"], "timestamp": x["timestamp"], "checkpoint_id": x["checkpoint_id"],
                       "signature_valid": bool(x["signature_valid"])} for x in persisted]
    for finding in clone.detect(detector_input):
        existed = conn.execute("SELECT 1 FROM flags WHERE shipment_id=? AND incident_key=?",
                               (shipment_id, finding["incident_key"])).fetchone() is not None
        flag_id = db.insert_flag_finding(conn, shipment_id, finding, _iso(now))
        if flag_id and not existed:
            db.append_audit(conn, "ANOMALY_RAISED", _iso(now), actor_id,
                            {"flag_id": flag_id, "shipment_id": shipment_id,
                             "incident_key": finding["incident_key"], "rule_code": finding["rule_code"],
                             "scan_ids": finding.get("scan_ids", [])})


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def issue_rolling_qr(conn: sqlite3.Connection, shipment_id: str, issued_by: str,
                     now: datetime | None = None) -> str:
    """Return the current label if one exists; otherwise issue exactly one new label.

    The QR secret is never stored in plaintext in the database. A random nonce is
    stored and the opaque token is derived with the external server secret, so a
    download retry cannot accidentally invalidate the label already in use.
    """
    now = now or db.utcnow()
    if db.get_shipment(conn, shipment_id) is None: raise NotFound(shipment_id)
    ts = _iso(now)
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Old-format active rows had no nonce and cannot be safely re-downloaded; revoke them.
        conn.execute("UPDATE qr_tokens SET consumed_at=?, consumed_by=?, consumed_checkpoint='ROTATED' WHERE shipment_id=? AND consumed_at IS NULL AND nonce IS NULL", (ts, issued_by, shipment_id))
        active = conn.execute("SELECT nonce FROM qr_tokens WHERE shipment_id=? AND consumed_at IS NULL ORDER BY issued_at DESC LIMIT 1", (shipment_id,)).fetchone()
        if active and active["nonce"]:
            token = derive_rolling_token(shipment_id, active["nonce"])
            conn.commit()
            return make_rolling_payload(shipment_id, token)
        nonce = secrets.token_urlsafe(32)
        token = derive_rolling_token(shipment_id, nonce)
        conn.execute("INSERT INTO qr_tokens(token_hash, shipment_id, issued_by, issued_at, nonce) VALUES(?,?,?,?,?)",
                     (_token_hash(token), shipment_id, issued_by, ts, nonce))
        db.append_audit(conn, "ROLLING_QR_ISSUED", ts, issued_by, {"shipment_id": shipment_id})
        conn.commit()
    except Exception:
        conn.rollback(); raise
    return make_rolling_payload(shipment_id, token)

def rolling_token_status(conn: sqlite3.Connection, raw: str) -> tuple[str | None, str]:
    """Return (shipment_id, status): active, stale, or invalid."""
    sid, token = parse_rolling_payload(raw)
    if not sid or not token:
        return None, "invalid"
    row = conn.execute("SELECT shipment_id, consumed_at FROM qr_tokens WHERE token_hash=?", (_token_hash(token),)).fetchone()
    if not row or row["shipment_id"] != sid:
        return None, "invalid"
    return sid, "stale" if row["consumed_at"] is not None else "active"

def _consume_rolling_token(conn: sqlite3.Connection, raw: str, shipment_id: str, user_id: str,
                           checkpoint_id: str, now: datetime) -> bool:
    sid, token = parse_rolling_payload(raw)
    if sid != shipment_id or not token:
        return False
    cur = conn.execute("UPDATE qr_tokens SET consumed_at=?, consumed_by=?, consumed_checkpoint=? "
                       "WHERE token_hash=? AND shipment_id=? AND consumed_at IS NULL",
                       (_iso(now), user_id, checkpoint_id, _token_hash(token), shipment_id))
    return cur.rowcount == 1

def _process_scan_handover_locked(conn: sqlite3.Connection, user: dict[str, Any], scanned: str, checkpoint_id: str,
                           action: str, idempotency_key: str, note: str = "", destination: str | None = None,
                           quantity: float | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Record a physical signed-QR scan and its handover. Timestamp is server-side.

    Idempotency is enforced on the scan key. Invalid/unsigned labels are logged
    as attempts but cannot create an ordinary verified handover.
    """
    now = now or db.utcnow()
    cp = checkpoints.get(checkpoint_id)
    if not cp:
        raise Conflict("Choose a registered checkpoint")
    rolling_sid, rolling_status = rolling_token_status(conn, scanned)
    is_rolling_payload = parse_rolling_payload(scanned)[0] is not None
    if is_rolling_payload:
        requested_sid, requested_signature_ok = rolling_sid, rolling_status == "active"
    else:
        # Legacy static labels remain verifiable for audit, but cannot authorize a new handover.
        requested_sid, requested_signature_ok = parse_token(scanned)
        requested_signature_ok = False if requested_signature_ok is True else requested_signature_ok
    payload_hash = hashlib.sha256((scanned or "").strip().encode("utf-8")).hexdigest()
    requested_shipment = db.get_shipment(conn, requested_sid) if requested_sid and requested_signature_ok is True else None
    prior = conn.execute("SELECT * FROM scans WHERE idempotency_key=?", (idempotency_key,)).fetchone()
    if prior:
        row = dict(prior)
        if row["scanned_by"] != user["id"]:
            raise Forbidden("This idempotency key belongs to another operator")
        same_scan_payload = row.get("payload_hash") in (None, payload_hash)
        if is_rolling_payload and row.get("payload_hash") == payload_hash and row["scan_result"] == "valid":
            # A completed token is stale now, but an exact retry with the original
            # idempotency key must return its stored result rather than reprocess it.
            expected_result = "valid"
        elif requested_signature_ok is True:
            expected_result = "valid" if requested_shipment else "unknown_id"
        elif requested_signature_ok is False:
            expected_result = "invalid_signature"
        else:
            expected_result = "manual_exception"
        expected_shipment_id = (row["shipment_id"] if is_rolling_payload and row.get("payload_hash") == payload_hash
                                and row["scan_result"] == "valid" else (requested_shipment["id"] if requested_shipment else None))
        different_request = (row["shipment_id"] != expected_shipment_id
                or row["scan_result"] != expected_result
                or row["checkpoint_id"] != checkpoint_id or row["action"] != action
                or row.get("destination") != destination or row.get("quantity") != quantity
                or not same_scan_payload)
        if row["scan_result"] == "valid":
            different_request = different_request or row["note"] != note
        if different_request:
            raise Conflict("This idempotency key was already used for a different scan request")
        # Re-check current authorisation before returning any shipment details for a
        # retry. An assignment may have been narrowed or revoked since the first call.
        if row["shipment_id"] and user["role"] == "transporter" and not db.is_assigned(
                conn, row["shipment_id"], user["id"], checkpoint_id):
            raise Forbidden("Your assignment no longer permits this checkpoint")
        if row["shipment_id"] and row["scan_result"] == "valid" and row["event_id"] is None:
            # Recover a request interrupted after the scan was saved but before its event was linked.
            existing_event = conn.execute("SELECT id FROM events WHERE source_scan_id=?", (row["id"],)).fetchone()
            if existing_event:
                db.attach_scan_event(conn, row["id"], int(existing_event[0]))
            else:
                shipment = db.get_shipment(conn, row["shipment_id"])
                ev = add_event(conn, row["shipment_id"], {"type": row["action"], "checkpoint": row["checkpoint"],
                    "actor": user["display_name"], "note": row["note"], "actor_id": user["id"],
                    "destination": row.get("destination"), "quantity": row.get("quantity"),
                    "source_scan_id": row["id"]}, now)
                db.attach_scan_event(conn, row["id"], int(ev["event_id"]))
                db.append_audit(conn, "QR_HANDOVER_RECOVERED", _iso(now), user["id"],
                    {"scan_id": row["id"], "event_id": ev["event_id"], "shipment_id": row["shipment_id"],
                     "checkpoint_id": row["checkpoint_id"], "action": row["action"]})
            return {"duplicate": True, "found": True, "scan_id": row["id"], "event_id": int(conn.execute("SELECT event_id FROM scans WHERE id=?", (row["id"],)).fetchone()[0]),
                    "detail": detail(conn, row["shipment_id"], now), "new_flags": []}
        if row["shipment_id"]:
            return {"duplicate": True, "found": True, "scan_id": row["id"], "event_id": row["event_id"],
                    "detail": detail(conn, row["shipment_id"], now), "new_flags": []}
        return {"duplicate": True, "found": False, "scan_id": row["id"], "event_id": None,
                "detail": None, "new_flags": [{"rule_code": "UNKNOWN_ID", "severity": "high",
                "explanation": "The submitted code was not accepted. No shipment data was disclosed."}]}

    sid, signature_ok = requested_sid, requested_signature_ok
    shipment = requested_shipment
    if signature_ok is None:
        result = "manual_exception"
    elif signature_ok is False:
        result = "invalid_signature"
    elif shipment is None:
        result = "unknown_id"
    else:
        result = "valid"

    # Don't reveal whether a forged or unknown signed id exists; persist the failed attempt.
    if result != "valid":
        scan, created = db.insert_scan(conn, {"shipment_id": None, "scanned_by": user["id"],
            "checkpoint_id": checkpoint_id, "checkpoint": cp.name, "action": action,
            "scanned_at": _iso(now), "signature_valid": 0, "scan_result": result,
            "idempotency_key": idempotency_key, "event_id": None,
            "note": "Unsigned/manual entry rejected for ordinary handover" if result == "manual_exception" else "QR was not accepted",
            "destination": destination, "quantity": quantity, "payload_hash": payload_hash})
        if not created:
            if scan["scanned_by"] != user["id"]:
                raise Forbidden("This idempotency key belongs to another operator")
            if (scan["scan_result"] != result or scan["checkpoint_id"] != checkpoint_id
                    or scan["action"] != action or scan.get("payload_hash") not in (None, payload_hash)
                    or scan.get("destination") != destination or scan.get("quantity") != quantity):
                raise Conflict("This idempotency key was already used for a different scan request")
        else:
            db.append_audit(conn, "QR_SCAN_REJECTED", _iso(now), user["id"],
                            {"scan_id": scan["id"], "checkpoint_id": checkpoint_id, "result": result, "action": action})
            if is_rolling_payload and rolling_status == "stale" and rolling_sid:
                flag = {"rule_code": "STALE_LABEL_REUSE", "severity": "high",
                        "summary": "Previously consumed QR token reused",
                        "explanation": "A previously consumed or rotated QR token was scanned again. Investigate possible copied-label reuse.",
                        "incident_key": f"STALE_LABEL_REUSE:{payload_hash}"}
                flag_id = db.insert_flag_finding(conn, rolling_sid, flag, _iso(now))
                db.append_audit(conn, "STALE_QR_REUSE_DETECTED", _iso(now), user["id"],
                                {"shipment_id": rolling_sid, "scan_id": scan["id"], "flag_id": flag_id,
                                 "checkpoint_id": checkpoint_id})
        return {"duplicate": not created, "found": False, "scan_id": scan["id"], "event_id": None,
                "detail": None, "new_flags": [{"rule_code": "UNKNOWN_ID", "severity": "high",
                "explanation": "The QR was not accepted. Check the physical label; no shipment data was disclosed."}],
                "message": "A signed QR is required for an ordinary handover. Manual entry must use the authorised exception workflow."}

    if user["role"] == "transporter" and not db.is_assigned(conn, shipment["id"], user["id"], checkpoint_id):
        db.append_audit(conn, "UNASSIGNED_SCAN_ATTEMPT", _iso(now), user["id"],
                        {"shipment_id": shipment["id"], "checkpoint_id": checkpoint_id})
        raise Forbidden("This shipment is not assigned to your account at this checkpoint. Ask an admin to assign it.")

    if not is_rolling_payload or not _consume_rolling_token(conn, scanned, shipment["id"], user["id"], checkpoint_id, now):
        db.append_audit(conn, "STALE_QR_REUSE_DETECTED", _iso(now), user["id"],
                        {"shipment_id": shipment["id"], "checkpoint_id": checkpoint_id, "payload_hash": payload_hash})
        db.insert_flag_finding(conn, shipment["id"], {"rule_code": "STALE_LABEL_REUSE", "severity": "high",
            "summary": "Inactive QR token used for handover",
            "explanation": "A QR token was reused or was not an active single-use label.",
            "incident_key": f"STALE_LABEL_REUSE:{payload_hash}"}, _iso(now))
        raise Conflict("This QR label has already been used or rotated. Download the current label before continuing.")
    scan, created = db.insert_scan(conn, {"shipment_id": shipment["id"], "scanned_by": user["id"],
        "checkpoint_id": checkpoint_id, "checkpoint": cp.name, "action": action, "scanned_at": _iso(now),
        "signature_valid": 1, "scan_result": "valid", "idempotency_key": idempotency_key,
        "event_id": None, "note": note, "destination": destination, "quantity": quantity,
        "payload_hash": payload_hash})
    if not created:
        if scan["scanned_by"] != user["id"]:
            raise Forbidden("This idempotency key belongs to another operator")
        if (scan["shipment_id"] != shipment["id"] or scan["checkpoint_id"] != checkpoint_id
                or scan["action"] != action or scan["note"] != note
                or scan.get("destination") != destination or scan.get("quantity") != quantity
                or scan.get("payload_hash") not in (None, payload_hash)):
            raise Conflict("This idempotency key was already used for a different scan request")
        if user["role"] == "transporter" and not db.is_assigned(conn, shipment["id"], user["id"], checkpoint_id):
            raise Forbidden("Your assignment no longer permits this checkpoint")
        return {"duplicate": True, "found": True, "scan_id": scan["id"], "event_id": scan["event_id"],
                "detail": detail(conn, shipment["id"], now), "new_flags": []}

    event_data = {"type": action, "checkpoint": cp.name, "actor": user["display_name"], "note": note,
                  "destination": destination, "quantity": quantity, "actor_id": user["id"], "source_scan_id": scan["id"]}
    out = add_event(conn, shipment["id"], event_data, now)
    db.attach_scan_event(conn, int(scan["id"]), int(out["event_id"]))
    db.append_audit(conn, "QR_HANDOVER_COMPLETED", _iso(now), user["id"],
                    {"scan_id": scan["id"], "event_id": out["event_id"], "shipment_id": shipment["id"],
                     "checkpoint_id": checkpoint_id, "action": action, "idempotency_key": idempotency_key})

    # Run the evidence detector over persisted scans (including manual exceptions).
    _record_scan_findings(conn, shipment["id"], user["id"], now)
    out["detail"] = detail(conn, shipment["id"], now)
    out["scan_id"] = scan["id"]
    out["found"] = True
    out["duplicate"] = False
    return out



def process_scan_handover(conn: sqlite3.Connection, user: dict[str, Any], scanned: str, checkpoint_id: str,
                           action: str, idempotency_key: str, note: str = "", destination: str | None = None,
                           quantity: float | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Atomically consume the QR and persist scan, shipment event, findings, and audit rows."""
    # BEGIN IMMEDIATE serializes concurrent attempts so only one request can consume a token.
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _process_scan_handover_locked(conn, user, scanned, checkpoint_id, action,
            idempotency_key, note, destination, quantity, now)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        # Preserve a durable investigation record for stale-token attempts even though
        # the rejected handover transaction is rolled back.
        try:
            sid, status = rolling_token_status(conn, scanned)
            if sid and status == "stale":
                ts = _iso(now or db.utcnow())
                payload_hash = hashlib.sha256((scanned or "").strip().encode("utf-8")).hexdigest()
                conn.execute("BEGIN IMMEDIATE")
                db.append_audit(conn, "STALE_QR_REUSE_DETECTED", ts, user.get("id"),
                    {"shipment_id": sid, "checkpoint_id": checkpoint_id, "payload_hash": payload_hash})
                db.insert_flag_finding(conn, sid, {"rule_code":"STALE_LABEL_REUSE", "severity":"high",
                    "summary":"Previously consumed QR token reused",
                    "explanation":"A consumed or rotated single-use QR was scanned again; investigate possible copied-label reuse.",
                    "incident_key":f"STALE_LABEL_REUSE:{payload_hash}"}, ts)
                conn.commit()
        except Exception:
            conn.rollback()
            log.exception("Could not persist stale QR reuse finding")
        raise


def process_manual_handover(conn: sqlite3.Connection, user: dict[str, Any], shipment_id: str,
                            checkpoint_id: str, action: str, reason: str, idempotency_key: str,
                            now: datetime | None = None) -> dict[str, Any]:
    """Exceptional manual pathway; inspector/admin only and always auditable."""
    now = now or db.utcnow()
    if user["role"] not in {"inspector", "admin"}:
        raise Forbidden("Only an inspector or admin can approve a manual handover exception")
    shipment = db.get_shipment(conn, shipment_id)
    cp = checkpoints.get(checkpoint_id)
    if shipment is None:
        raise NotFound(shipment_id)
    if cp is None:
        raise Conflict("Choose a registered checkpoint")
    prior = conn.execute("SELECT * FROM scans WHERE idempotency_key=?", (idempotency_key,)).fetchone()
    if prior:
        row = dict(prior)
        if row["scanned_by"] != user["id"]:
            raise Forbidden("This idempotency key belongs to another operator")
        if (row["shipment_id"] != shipment_id or row["scan_result"] != "manual_exception"
                or row["checkpoint_id"] != checkpoint_id or row["action"] != action
                or row["note"] != f"MANUAL EXCEPTION: {reason}" or row.get("destination") is not None
                or row.get("quantity") is not None):
            raise Conflict("This idempotency key was already used for a different scan request")
        return {"duplicate": True, "found": True, "scan_id": row["id"], "event_id": row["event_id"],
                "detail": detail(conn, shipment_id, now), "new_flags": []}
    scan, _ = db.insert_scan(conn, {"shipment_id": shipment_id, "scanned_by": user["id"],
        "checkpoint_id": checkpoint_id, "checkpoint": cp.name, "action": action, "scanned_at": _iso(now),
        "signature_valid": 0, "scan_result": "manual_exception", "idempotency_key": idempotency_key,
        "event_id": None, "note": f"MANUAL EXCEPTION: {reason}"})
    out = add_event(conn, shipment_id, {"type": action, "checkpoint": cp.name, "actor": user["display_name"],
                     "note": f"MANUAL EXCEPTION: {reason}", "actor_id": user["id"], "source_scan_id": scan["id"]}, now)
    db.attach_scan_event(conn, int(scan["id"]), int(out["event_id"]))
    db.append_audit(conn, "MANUAL_HANDOVER_OVERRIDE", _iso(now), user["id"],
                    {"scan_id": scan["id"], "event_id": out["event_id"], "shipment_id": shipment_id,
                     "checkpoint_id": checkpoint_id, "action": action, "reason": reason})
    _record_scan_findings(conn, shipment_id, user["id"], now)
    out.update({"scan_id": scan["id"], "duplicate": False, "detail": detail(conn, shipment_id, now)})
    return out


def verify_audit_chain(conn: sqlite3.Connection) -> dict[str, Any]:
    records = db.get_audit_records(conn)
    return audit_chain.verify(records, expected_head=db.audit_head(conn))


def generate_audit_anchor(conn: sqlite3.Connection, actor_id: str | None = None) -> dict[str, Any]:
    """Generate a cryptographically signed anchor receipt for external storage/verification."""
    head = db.get_audit_head_record(conn)
    total = db.count_audit_records(conn)
    ts = _iso(db.utcnow())
    receipt = audit_chain.make_anchor_receipt(head, total, ts, config.secret_key())
    db.append_audit(conn, "AUDIT_ANCHOR_GENERATED", ts, actor_id, {
        "sequence": receipt["sequence"],
        "head_hash": receipt["head_hash"],
        "record_count": receipt["record_count"],
    })
    return receipt


def verify_audit_anchor(conn: sqlite3.Connection, anchor: dict[str, Any], actor_id: str | None = None) -> dict[str, Any]:
    """Verify local database records against an external signed anchor receipt."""
    records = db.get_audit_records(conn)
    res = audit_chain.verify_against_anchor(records, anchor, config.secret_key())
    ts = _iso(db.utcnow())
    db.append_audit(conn, "AUDIT_ANCHOR_VERIFIED", ts, actor_id, {
        "ok": res["ok"],
        "anchored_sequence": res.get("anchored_sequence"),
        "anchored_hash": res.get("anchored_hash"),
        "reason": res.get("reason"),
    })
    return res


def list_audit_log(conn: sqlite3.Connection, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Return paginated audit records for inspection."""
    total = db.count_audit_records(conn)
    records = db.list_audit_records(conn, limit=limit, offset=offset)
    return {"total": total, "limit": limit, "offset": offset, "records": records}


def logout_user(conn: sqlite3.Connection, token: str, user_id: str) -> None:
    """Revoke session token on the server so it cannot be replayed."""
    claims = auth.verify_token(token)
    exp = claims["exp"] if claims and "exp" in claims else int(db.utcnow().timestamp()) + auth.TOKEN_TTL_SECONDS
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    ts = _iso(db.utcnow())
    db.revoke_token(conn, token_hash, user_id, ts, exp)
    db.append_audit(conn, "LOGOUT_SUCCESS", ts, user_id, {"token_hash_prefix": token_hash[:16]})

