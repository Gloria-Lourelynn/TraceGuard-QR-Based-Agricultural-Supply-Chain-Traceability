"""Create demo accounts and repeatable example journeys without wiping user data.

    python seed.py                       # add accounts and demo scenarios
    python seed.py --reset                # destructive: replace configured DB
    python seed.py --reset-demo-passwords # reset only the four demo account passwords
    $env:TRACEGUARD_DEMO_PASSWORD='...'   # password for new/reset demo users

Existing demo shipment scenarios are detected by their product/route signature,
so rerunning this script does not duplicate their events. Existing non-demo
shipments are preserved and do not prevent the example scenarios from being added.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import auth, config, db, service

COOP = "Coimbatore Growers Co-op"


def _ship(conn, product, origin, dest, qty, unit, dispatch_at, owner_id, audit_actor_id):
    """Return (shipment_id, should_add_events), adopting older seed records safely."""
    existing = conn.execute(
        "SELECT * FROM shipments WHERE product=? AND origin=? AND destination=? AND created_by=? "
        "ORDER BY created_at DESC LIMIT 1",
        (product, origin, dest, COOP),
    ).fetchone()
    if existing:
        sid = existing["id"]
        if not existing["owner_id"] and owner_id:
            conn.execute("UPDATE shipments SET owner_id=? WHERE id=?", (owner_id, sid))
            conn.commit()
        has_events = conn.execute("SELECT 1 FROM events WHERE shipment_id=? LIMIT 1", (sid,)).fetchone()
        return sid, has_events is None

    sid = service.register_shipment(conn, {
        "product": product, "origin": origin, "destination": dest, "quantity": qty,
        "unit": unit, "dispatch_date": dispatch_at.date(), "created_by": COOP,
        "owner_id": owner_id, "actor_id": audit_actor_id,
    })["shipment"]["id"]
    return sid, True


def _ev(conn, sid, etype, checkpoint, actor, ts, now, audit_actor_id, **extra):
    service.add_event(conn, sid, {
        "type": etype, "checkpoint": checkpoint, "actor": actor, "timestamp": ts,
        "note": "", "actor_id": audit_actor_id, **extra,
    }, now)


def seed(conn, seller_id: str | None = None, admin_id: str | None = None,
         transporter_id: str | None = None) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    t = lambda h: now - timedelta(hours=h)  # noqa: E731
    ids: dict[str, str] = {}

    def scenario(key, product, origin, dest, qty, unit, dispatch_hours, events):
        sid, add_events = _ship(conn, product, origin, dest, qty, unit, t(dispatch_hours), seller_id, admin_id)
        ids[key] = sid
        if add_events:
            for ev in events:
                etype, checkpoint, actor, hours_ago, extra = ev
                _ev(conn, sid, etype, checkpoint, actor, t(hours_ago), now, admin_id, **extra)

    # A clean route. No rules should flag this history.
    scenario("legitimate", "Tomatoes", "Coimbatore", "Chennai", 500, "kg", 30, [
        ("DISPATCHED", "Coimbatore Farm Gate", "Ravi (farmer)", 29, {}),
        ("IN_TRANSIT", "Salem Toll Plaza", "Driver K. Mani", 22, {}),
        ("RECEIVED", "Chennai Koyambedu Market", "Meena (distributor)", 10, {}),
        ("DELIVERED", "Chennai Retail Store 12", "Arun (retailer)", 6, {}),
    ])

    # Suspicious: a second arrival at a distant checkpoint.
    scenario("double_arrival", "Bananas", "Theni", "Chennai", 800, "kg", 28, [
        ("DISPATCHED", "Theni Packhouse", "Lakshmi", 27, {}),
        ("IN_TRANSIT", "Madurai Checkpost", "Driver S. Raj", 20, {}),
        ("RECEIVED", "Chennai Koyambedu Market", "Meena (distributor)", 9, {}),
        ("RECEIVED", "Bengaluru Yeshwanthpur Yard", "Unknown", 8, {}),
    ])

    # Suspicious: delivery before receipt.
    scenario("skipped_step", "Onions", "Salem", "Chennai", 1200, "kg", 26, [
        ("DISPATCHED", "Salem Mandi", "Gopal", 25, {}),
        ("IN_TRANSIT", "Vellore Toll", "Driver P. Das", 18, {}),
        ("DELIVERED", "Chennai Retail Store 3", "Unknown", 5, {}),
    ])

    # Edge cases: quantity mismatch plus an out-of-order event timestamp.
    scenario("mismatch", "Mangoes", "Krishnagiri", "Chennai", 300, "crate", 20, [
        ("DISPATCHED", "Krishnagiri Orchard", "Selvi", 19, {}),
        ("IN_TRANSIT", "Hosur Toll", "Driver V. Kumar", 12, {"quantity": 240}),
        ("IN_TRANSIT", "Vellore Toll", "Driver V. Kumar", 14, {}),
    ])

    # Repeated transitions at one checkpoint in a short interval.
    scenario("rapid_scans", "Rice", "Thanjavur", "Coimbatore", 40, "bag", 3, [
        ("DISPATCHED", "Thanjavur Mill", "Kannan", 2.5, {}),
        ("IN_TRANSIT", "Trichy Checkpost", "Scanner 7", 5 / 60, {}),
        ("IN_TRANSIT", "Trichy Checkpost", "Scanner 7", 4 / 60, {}),
        ("IN_TRANSIT", "Trichy Checkpost", "Scanner 7", 3 / 60, {}),
        ("IN_TRANSIT", "Trichy Checkpost", "Scanner 7", 2 / 60, {}),
    ])

    # All demo scenarios are visible to the demo seller and assigned to the demo
    # transporter, even if the database already contained unrelated shipments.
    if transporter_id and admin_id:
        for sid in ids.values():
            db.assign_shipment(conn, {"shipment_id": sid, "user_id": transporter_id,
                "checkpoint_id": None, "assigned_by": admin_id, "created_at": db.utcnow().isoformat()})
    return ids


if __name__ == "__main__":
    if config.is_production():
        raise SystemExit("Demo seeding is disabled in production. Provision named accounts through the authenticated admin workflow.")
    path = config.db_path()
    reset = "--reset" in sys.argv
    if reset:
        for suffix in ("", "-wal", "-shm"):
            Path(path + suffix).unlink(missing_ok=True)
    conn = db.connect(path)
    db.init_db(conn)

    demo_password = os.environ.get("TRACEGUARD_DEMO_PASSWORD", "TraceGuardDemo!2026")
    accounts = [
        ("admin", "TraceGuard Admin", "admin"),
        ("seller", "Demo Seller", "seller"),
        ("transporter", "Demo Transporter", "transporter"),
        ("inspector", "Demo Inspector", "inspector"),
    ]
    newly_created = []
    password_reset_users = []
    reset_demo_passwords = "--reset-demo-passwords" in sys.argv
    for username, display_name, role in accounts:
        existing = db.get_user_by_username(conn, username)
        if not existing:
            service.create_user(conn, username, display_name, role, demo_password)
            newly_created.append(username)
        elif reset_demo_passwords:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                         (auth.hash_password(demo_password), existing["id"]))
            conn.commit()
            password_reset_users.append(username)

    seller = db.get_user_by_username(conn, "seller")
    admin = db.get_user_by_username(conn, "admin")
    transporter = db.get_user_by_username(conn, "transporter")
    ids = seed(conn,
        seller_id=seller["id"] if seller else None,
        admin_id=admin["id"] if admin else None,
        transporter_id=transporter["id"] if transporter else None)

    print("\nDemo accounts:")
    for username, _, role in accounts:
        print(f"  {role:11s} username={username:12s}")
    if newly_created:
        print("\nInitial password for newly created demo accounts:", demo_password)
        print("New accounts:", ", ".join(newly_created))
    if password_reset_users:
        print("\nPassword reset for demo accounts:", ", ".join(password_reset_users))
        print("New demo password:", demo_password)
    if not newly_created and not password_reset_users:
        print("\nExisting account passwords were not changed by this run.")
    print("\nDemo shipments (visible to seller; assigned to transporter):")
    for name, sid in ids.items():
        print(f"{name:15s} {sid}")
    print("\nExisting unrelated shipment records were preserved.")
    conn.close()
