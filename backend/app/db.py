"""SQLite storage and a thin repository layer.

Every query is parameterised (no string-built SQL with user input). Foreign
keys and CHECK constraints are enforced by the database as a second line of
defence behind Pydantic.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments (
    id            TEXT PRIMARY KEY,
    product       TEXT NOT NULL,
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    quantity      REAL NOT NULL CHECK (quantity > 0),
    unit          TEXT NOT NULL,
    dispatch_date TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    owner_id      TEXT REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id TEXT NOT NULL REFERENCES shipments(id),
    type        TEXT NOT NULL CHECK (type IN ('DISPATCHED','IN_TRANSIT','RECEIVED','DELIVERED')),
    checkpoint  TEXT NOT NULL,
    actor       TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    destination TEXT,
    quantity    REAL CHECK (quantity IS NULL OR quantity > 0),
    source_scan_id INTEGER UNIQUE
);
CREATE TABLE IF NOT EXISTS flags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id TEXT NOT NULL REFERENCES shipments(id),
    event_id    INTEGER REFERENCES events(id),
    rule_code   TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('high','medium','low')),
    explanation TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewed','dismissed')),
    created_at  TEXT NOT NULL,
    evidence_json TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('seller','transporter','inspector','admin')),
    password_hash TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shipment_assignments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id   TEXT NOT NULL REFERENCES shipments(id),
    user_id       TEXT NOT NULL REFERENCES users(id),
    checkpoint_id TEXT,
    assigned_by   TEXT NOT NULL REFERENCES users(id),
    created_at    TEXT NOT NULL,
    UNIQUE(shipment_id, user_id)
);
CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id     TEXT REFERENCES shipments(id),
    scanned_by      TEXT NOT NULL REFERENCES users(id),
    checkpoint_id   TEXT,
    checkpoint      TEXT NOT NULL,
    action          TEXT,
    scanned_at      TEXT NOT NULL,
    signature_valid INTEGER NOT NULL CHECK (signature_valid IN (0,1)),
    scan_result     TEXT NOT NULL CHECK (scan_result IN ('valid','invalid_signature','unknown_id','manual_exception')),
    idempotency_key TEXT NOT NULL UNIQUE,
    event_id        INTEGER REFERENCES events(id),
    note            TEXT NOT NULL DEFAULT '',
    destination     TEXT,
    quantity        REAL CHECK (quantity IS NULL OR quantity > 0),
    payload_hash    TEXT
);
CREATE TABLE IF NOT EXISTS flag_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    flag_id     INTEGER NOT NULL REFERENCES flags(id),
    reviewer_id TEXT NOT NULL REFERENCES users(id),
    status      TEXT NOT NULL CHECK (status IN ('reviewed','dismissed')),
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_chain (
    seq         INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,
    ts          TEXT NOT NULL,
    actor_id    TEXT,
    payload_json TEXT NOT NULL,
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qr_tokens (
    token_hash  TEXT PRIMARY KEY,
    shipment_id TEXT NOT NULL REFERENCES shipments(id),
    issued_by   TEXT NOT NULL REFERENCES users(id),
    issued_at   TEXT NOT NULL,
    consumed_at TEXT,
    consumed_by TEXT REFERENCES users(id),
    consumed_checkpoint TEXT
);
CREATE INDEX IF NOT EXISTS idx_qr_tokens_shipment ON qr_tokens(shipment_id, issued_at);
CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    revoked_at  TEXT NOT NULL,
    expires_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_revoked_tokens_exp ON revoked_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_scans_shipment ON scans(shipment_id, scanned_at, id);
CREATE INDEX IF NOT EXISTS idx_assignments_user ON shipment_assignments(user_id, shipment_id);
CREATE INDEX IF NOT EXISTS idx_audit_hash ON audit_chain(hash);
CREATE INDEX IF NOT EXISTS idx_events_shipment ON events(shipment_id, id);
CREATE INDEX IF NOT EXISTS idx_flags_shipment ON flags(shipment_id);
CREATE INDEX IF NOT EXISTS idx_flags_status ON flags(status);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def connect(path: str) -> sqlite3.Connection:
    # One connection per request; check_same_thread=False because FastAPI may
    # run the dependency and the endpoint on different worker threads.
    # A bounded wait avoids transient "database is locked" errors when two
    # local requests write at once. WAL allows readers while a writer commits.
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Small in-place migrations for databases created by the earlier V2 draft.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(shipments)")}
    if "owner_id" not in cols:
        conn.execute("ALTER TABLE shipments ADD COLUMN owner_id TEXT REFERENCES users(id)")
    event_cols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
    if "source_scan_id" not in event_cols:
        conn.execute("ALTER TABLE events ADD COLUMN source_scan_id INTEGER")
    scan_cols = {r[1] for r in conn.execute("PRAGMA table_info(scans)")}
    if "destination" not in scan_cols:
        conn.execute("ALTER TABLE scans ADD COLUMN destination TEXT")
    if "quantity" not in scan_cols:
        conn.execute("ALTER TABLE scans ADD COLUMN quantity REAL")
    if "payload_hash" not in scan_cols:
        conn.execute("ALTER TABLE scans ADD COLUMN payload_hash TEXT")
    flag_cols = {r[1] for r in conn.execute("PRAGMA table_info(flags)")}
    if "incident_key" not in flag_cols:
        conn.execute("ALTER TABLE flags ADD COLUMN incident_key TEXT")
    if "evidence_json" not in flag_cols:
        conn.execute("ALTER TABLE flags ADD COLUMN evidence_json TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_flags_incident ON flags(shipment_id, incident_key)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS revoked_tokens ("
        "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), "
        "revoked_at TEXT NOT NULL, expires_at INTEGER NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_revoked_tokens_exp ON revoked_tokens(expires_at)")
    conn.execute("CREATE TABLE IF NOT EXISTS qr_tokens (token_hash TEXT PRIMARY KEY, shipment_id TEXT NOT NULL REFERENCES shipments(id), issued_by TEXT NOT NULL REFERENCES users(id), issued_at TEXT NOT NULL, consumed_at TEXT, consumed_by TEXT REFERENCES users(id), consumed_checkpoint TEXT, nonce TEXT)")
    qr_cols = {r[1] for r in conn.execute("PRAGMA table_info(qr_tokens)")}
    if "nonce" not in qr_cols: conn.execute("ALTER TABLE qr_tokens ADD COLUMN nonce TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qr_tokens_shipment ON qr_tokens(shipment_id, issued_at)")
    conn.commit()


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def insert_shipment(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO shipments (id, product, origin, destination, quantity, unit,"
        " dispatch_date, created_at, created_by, owner_id)"
        " VALUES (:id, :product, :origin, :destination, :quantity, :unit,"
        " :dispatch_date, :created_at, :created_by, :owner_id)",
        row,
    )
    conn.commit()


def get_shipment(conn: sqlite3.Connection, shipment_id: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone())


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_shipments(conn: sqlite3.Connection, q: str | None, limit: int = 200) -> list[dict[str, Any]]:
    if q:
        pat = f"%{_like_escape(q.strip())}%"
        cur = conn.execute(
            "SELECT * FROM shipments WHERE id LIKE ? ESCAPE '\\' OR product LIKE ? ESCAPE '\\'"
            " OR origin LIKE ? ESCAPE '\\' OR destination LIKE ? ESCAPE '\\'"
            " ORDER BY created_at DESC, id LIMIT ?",
            (pat, pat, pat, pat, limit),
        )
    else:
        cur = conn.execute("SELECT * FROM shipments ORDER BY created_at DESC, id LIMIT ?", (limit,))
    return [dict(r) for r in cur.fetchall()]


def count_shipments(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]


def insert_event(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    started_transaction = not conn.in_transaction
    cur = conn.execute(
        "INSERT INTO events (shipment_id, type, checkpoint, actor, timestamp, note, destination, quantity, source_scan_id)"
        " VALUES (:shipment_id, :type, :checkpoint, :actor, :timestamp, :note, :destination, :quantity, :source_scan_id)",
        row,
    )
    if started_transaction: conn.commit()
    return int(cur.lastrowid)


def list_events(conn: sqlite3.Connection, shipment_id: str) -> list[dict[str, Any]]:
    """Events in the order they were recorded, timestamps parsed to datetimes."""
    out = []
    for r in conn.execute("SELECT * FROM events WHERE shipment_id = ? ORDER BY id", (shipment_id,)):
        d = dict(r)
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        out.append(d)
    return out


def recent_events(conn: sqlite3.Connection, limit: int = 8) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT e.id, e.shipment_id, e.type, e.checkpoint, e.actor, e.timestamp, s.product"
            " FROM events e JOIN shipments s ON s.id = e.shipment_id ORDER BY e.id DESC LIMIT ?",
            (limit,),
        )
    ]


def insert_flags(conn: sqlite3.Connection, shipment_id: str, flags: Iterable[Any], created_at: str) -> list[int]:
    started_transaction = not conn.in_transaction
    ids = []
    for f in flags:
        cur = conn.execute(
            "INSERT INTO flags (shipment_id, event_id, rule_code, severity, explanation, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'open', ?)",
            (shipment_id, f.event_id, f.rule_code, f.severity, f.explanation, created_at),
        )
        ids.append(int(cur.lastrowid))
    if started_transaction: conn.commit()
    return ids


def _flag_dict(r: sqlite3.Row) -> dict[str, Any]:
    import json
    d = dict(r)
    raw = d.pop("evidence_json", None)
    d["evidence"] = json.loads(raw) if raw else None
    return d


def list_flags(conn: sqlite3.Connection, shipment_id: str) -> list[dict[str, Any]]:
    return [_flag_dict(r) for r in conn.execute("SELECT * FROM flags WHERE shipment_id = ? ORDER BY id", (shipment_id,))]


def get_flag(conn: sqlite3.Connection, flag_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM flags WHERE id = ?", (flag_id,)).fetchone()
    return _flag_dict(row) if row else None


def set_flag_status(conn: sqlite3.Connection, flag_id: int, status: str) -> None:
    conn.execute("UPDATE flags SET status = ? WHERE id = ?", (status, flag_id))
    conn.commit()


def open_flags(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    return [
        {**_flag_dict(r), "product": r["product"]}
        for r in conn.execute(
            "SELECT f.*, s.product FROM flags f JOIN shipments s ON s.id = f.shipment_id"
            " WHERE f.status = 'open'"
            " ORDER BY CASE f.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, f.id DESC LIMIT ?",
            (limit,),
        )
    ]


def open_flag_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Number of open flags per shipment id (only shipments with at least one)."""
    return {
        r[0]: r[1]
        for r in conn.execute("SELECT shipment_id, COUNT(*) FROM flags WHERE status = 'open' GROUP BY shipment_id")
    }

def create_user(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO users (id, username, display_name, role, password_hash, active, created_at) "
        "VALUES (:id, :username, :display_name, :role, :password_hash, :active, :created_at)", row
    )
    conn.commit()


def get_user_by_username(conn: sqlite3.Connection, username: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone())


def get_user(conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def list_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT id, username, display_name, role, active, created_at FROM users ORDER BY role, username"
    )]


def set_user_active(conn: sqlite3.Connection, user_id: str, active: bool) -> None:
    conn.execute("UPDATE users SET active = ? WHERE id = ?", (int(active), user_id))
    conn.commit()


def assign_shipment(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    conn.execute(
        "INSERT INTO shipment_assignments (shipment_id, user_id, checkpoint_id, assigned_by, created_at) "
        "VALUES (:shipment_id, :user_id, :checkpoint_id, :assigned_by, :created_at) "
        "ON CONFLICT(shipment_id,user_id) DO UPDATE SET checkpoint_id=excluded.checkpoint_id, assigned_by=excluded.assigned_by, created_at=excluded.created_at",
        row,
    )
    conn.commit()
    return int(conn.execute("SELECT id FROM shipment_assignments WHERE shipment_id=? AND user_id=?",
                            (row["shipment_id"], row["user_id"])).fetchone()[0])


def is_assigned(conn: sqlite3.Connection, shipment_id: str, user_id: str, checkpoint_id: str | None = None) -> bool:
    sql = "SELECT 1 FROM shipment_assignments WHERE shipment_id=? AND user_id=?"
    args: list[Any] = [shipment_id, user_id]
    if checkpoint_id:
        sql += " AND (checkpoint_id IS NULL OR checkpoint_id=?)"
        args.append(checkpoint_id)
    return conn.execute(sql, args).fetchone() is not None


def assignments_for_user(conn: sqlite3.Connection, user_id: str) -> list[str]:
    return [r[0] for r in conn.execute("SELECT shipment_id FROM shipment_assignments WHERE user_id=?", (user_id,))]


def insert_scan(conn: sqlite3.Connection, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    started_transaction = not conn.in_transaction
    if started_transaction:
        # The idempotency-key lookup and insert must be one serialised operation.
        conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute("SELECT * FROM scans WHERE idempotency_key=?", (row["idempotency_key"],)).fetchone()
        if existing:
            if started_transaction: conn.commit()
            return dict(existing), False
        row = {"destination": None, "quantity": None, "payload_hash": None, **row}
        cur = conn.execute(
            "INSERT INTO scans (shipment_id, scanned_by, checkpoint_id, checkpoint, action, scanned_at, signature_valid, scan_result, idempotency_key, event_id, note, destination, quantity, payload_hash) "
            "VALUES (:shipment_id, :scanned_by, :checkpoint_id, :checkpoint, :action, :scanned_at, :signature_valid, :scan_result, :idempotency_key, :event_id, :note, :destination, :quantity, :payload_hash)", row
        )
        if started_transaction: conn.commit()
        return dict(conn.execute("SELECT * FROM scans WHERE id=?", (cur.lastrowid,)).fetchone()), True
    except Exception:
        if started_transaction:
            conn.rollback()
        raise


def attach_scan_event(conn: sqlite3.Connection, scan_id: int, event_id: int) -> None:
    started_transaction = not conn.in_transaction
    conn.execute("UPDATE scans SET event_id=? WHERE id=?", (event_id, scan_id))
    if started_transaction: conn.commit()


def list_scans(conn: sqlite3.Connection, shipment_id: str) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT * FROM scans WHERE shipment_id=? ORDER BY scanned_at, id", (shipment_id,)):
        d = dict(r)
        d.pop("payload_hash", None)  # internal idempotency check; don't expose the digest in APIs
        d["timestamp"] = datetime.fromisoformat(d["scanned_at"])
        out.append(d)
    return out


def append_audit(conn: sqlite3.Connection, kind: str, ts: str, actor_id: str | None,
                 payload: dict[str, Any]) -> dict[str, Any]:
    import json
    from .engine.audit_chain import make_record
    started_transaction = not conn.in_transaction
    if started_transaction:
        # Serialise the read-last-hash + append operation so concurrent requests
        # cannot choose the same next sequence number for the audit chain.
        conn.execute("BEGIN IMMEDIATE")
    try:
        last = conn.execute("SELECT seq, hash FROM audit_chain ORDER BY seq DESC LIMIT 1").fetchone()
        prev = {"seq": last["seq"], "hash": last["hash"]} if last else None
        # Hash the actor id inside the payload too, while keeping the dedicated column
        # for queries. Existing pre-V2.1 records remain verifiable because their payload
        # has no _actor_id field and the canonical record format has not changed.
        protected_payload = {**payload, "_actor_id": actor_id}
        rec = make_record(prev, kind, ts, protected_payload)
        encoded = json.dumps(rec["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        conn.execute(
            "INSERT INTO audit_chain (seq, kind, ts, actor_id, payload_json, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
            (rec["seq"], rec["kind"], rec["ts"], actor_id, encoded, rec["prev_hash"], rec["hash"]),
        )
        if started_transaction: conn.commit()
        return {"seq": rec["seq"], "hash": rec["hash"]}
    except Exception:
        if started_transaction:
            conn.rollback()
        raise


def get_audit_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    import json
    return [{"seq": r["seq"], "kind": r["kind"], "ts": r["ts"], "actor_id": r["actor_id"],
             "payload": json.loads(r["payload_json"]), "prev_hash": r["prev_hash"], "hash": r["hash"]}
            for r in conn.execute("SELECT * FROM audit_chain ORDER BY seq")]


def audit_head(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT hash FROM audit_chain ORDER BY seq DESC LIMIT 1").fetchone()
    return row[0] if row else None


def insert_flag_finding(conn: sqlite3.Connection, shipment_id: str, finding: dict[str, Any], created_at: str) -> int | None:
    started_transaction = not conn.in_transaction
    try:
        import json
        cur = conn.execute(
            "INSERT INTO flags (shipment_id, event_id, rule_code, severity, explanation, status, created_at, incident_key, evidence_json) "
            "VALUES (?, NULL, ?, ?, ?, 'open', ?, ?, ?)",
            (shipment_id, finding["rule_code"], finding["severity"], finding["summary"], created_at, finding["incident_key"],
             json.dumps(finding, sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
        )
        if started_transaction: conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        # The same incident can be rediscovered after each subsequent scan.
        if started_transaction: conn.rollback()
        row = conn.execute("SELECT id FROM flags WHERE shipment_id=? AND incident_key=?",
                           (shipment_id, finding["incident_key"])).fetchone()
        return int(row[0]) if row else None


def add_flag_review(conn: sqlite3.Connection, flag_id: int, reviewer_id: str, status: str, reason: str, created_at: str) -> None:
    conn.execute("INSERT INTO flag_reviews (flag_id, reviewer_id, status, reason, created_at) VALUES (?,?,?,?,?)",
                 (flag_id, reviewer_id, status, reason, created_at))
    conn.commit()


def revoke_token(conn: sqlite3.Connection, token_hash: str, user_id: str, revoked_at: str, expires_at: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO revoked_tokens (token_hash, user_id, revoked_at, expires_at) VALUES (?, ?, ?, ?)",
        (token_hash, user_id, revoked_at, expires_at),
    )
    conn.commit()


def is_token_revoked(conn: sqlite3.Connection, token_hash: str) -> bool:
    return conn.execute("SELECT 1 FROM revoked_tokens WHERE token_hash=?", (token_hash,)).fetchone() is not None


def cleanup_revoked_tokens(conn: sqlite3.Connection, now_ts: int) -> None:
    conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now_ts,))
    conn.commit()


def get_audit_head_record(conn: sqlite3.Connection) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM audit_chain ORDER BY seq DESC LIMIT 1").fetchone()
    if not r:
        return None
    import json
    return {
        "seq": r["seq"], "kind": r["kind"], "ts": r["ts"], "actor_id": r["actor_id"],
        "payload": json.loads(r["payload_json"]), "prev_hash": r["prev_hash"], "hash": r["hash"],
    }


def count_audit_records(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM audit_chain").fetchone()[0]


def list_audit_records(conn: sqlite3.Connection, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    import json
    rows = conn.execute(
        "SELECT a.*, u.username as actor_username, u.display_name as actor_name "
        "FROM audit_chain a LEFT JOIN users u ON u.id = a.actor_id "
        "ORDER BY a.seq DESC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    return [{
        "seq": r["seq"], "kind": r["kind"], "ts": r["ts"], "actor_id": r["actor_id"],
        "actor_username": r["actor_username"], "actor_name": r["actor_name"],
        "payload": json.loads(r["payload_json"]), "prev_hash": r["prev_hash"], "hash": r["hash"]
    } for r in rows]

