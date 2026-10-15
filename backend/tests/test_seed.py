"""Regression tests for demo-data ownership and repeatable seeding."""
from datetime import date

from app import db, service
import seed


def test_seed_adds_examples_to_nonempty_db_and_scopes_them_to_demo_roles():
    conn = db.connect(":memory:")
    db.init_db(conn)
    seller = service.create_user(conn, "seller", "Demo Seller", "seller", "LongDemoPassword!2026")
    admin = service.create_user(conn, "admin", "Demo Admin", "admin", "LongDemoPassword!2026")
    transporter = service.create_user(conn, "transporter", "Demo Transporter", "transporter", "LongDemoPassword!2026")

    # A real, unrelated record must not cause the seed script to skip its demo cases.
    service.register_shipment(conn, {
        "product": "Private shipment", "origin": "A", "destination": "B", "quantity": 1,
        "unit": "kg", "dispatch_date": date.today(), "created_by": "Existing user",
        "owner_id": seller["id"], "actor_id": seller["id"],
    })
    ids = seed.seed(conn, seller["id"], admin["id"], transporter["id"])

    assert set(ids) == {"legitimate", "double_arrival", "skipped_step", "mismatch", "rapid_scans"}
    assert db.count_shipments(conn) == 6
    for sid in ids.values():
        row = db.get_shipment(conn, sid)
        assert row["owner_id"] == seller["id"]
        assert db.is_assigned(conn, sid, transporter["id"])
        assert conn.execute("SELECT COUNT(*) FROM events WHERE shipment_id=?", (sid,)).fetchone()[0] > 0

    before_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    second_ids = seed.seed(conn, seller["id"], admin["id"], transporter["id"])
    assert second_ids == ids
    assert db.count_shipments(conn) == 6
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before_events
    conn.close()
