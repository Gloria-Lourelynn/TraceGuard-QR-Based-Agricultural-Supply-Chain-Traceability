"""A new seller shipment must be scannable by the default transporter without any repair script."""
import os
from unittest.mock import patch
import pytest
from datetime import date

from app import db, service
from app.security import make_token

PW = "LongDemoPassword!2026"


def _setup(env=None):
    os.environ.pop("TRACEGUARD_AUTO_ASSIGN_TRANSPORTER", None)
    if env is not None:
        os.environ["TRACEGUARD_AUTO_ASSIGN_TRANSPORTER"] = env
    conn = db.connect(":memory:")
    db.init_db(conn)
    seller = service.create_user(conn, "seller", "Seller", "seller", PW)
    admin = service.create_user(conn, "admin", "Admin", "admin", PW)
    transporter = service.create_user(conn, "transporter", "Transporter", "transporter", PW)
    return conn, seller, admin, transporter


def _register(conn, seller):
    return service.register_shipment(conn, {
        "product": "Tomatoes", "origin": "A", "destination": "B", "quantity": 5, "unit": "kg",
        "dispatch_date": date.today(), "created_by": "Seller", "owner_id": seller["id"],
        "actor_id": seller["id"]})["shipment"]["id"]


def test_new_shipment_is_assigned_and_first_scan_is_accepted():
    conn, seller, admin, transporter = _setup()
    sid = _register(conn, seller)
    assert service.auto_assign_default_transporter(conn, sid, seller["id"]) is True
    assert service.auto_assign_default_transporter(conn, sid, seller["id"]) is False  # no duplicate
    payload = service.issue_rolling_qr(conn, sid, seller["id"])
    out = service.process_scan_handover(conn, transporter, payload, "CBE-FARM", "DISPATCHED", "first-scan-key-01")
    assert out["found"] is True and out["event_id"]


def test_backfill_covers_older_unassigned_shipments_once():
    conn, seller, admin, transporter = _setup()
    sid = _register(conn, seller)
    assert service.backfill_default_transporter(conn) == 1
    assert db.is_assigned(conn, sid, transporter["id"])
    assert service.backfill_default_transporter(conn) == 0


def test_feature_can_be_turned_off():
    conn, seller, admin, transporter = _setup("off")
    sid = _register(conn, seller)
    assert service.auto_assign_default_transporter(conn, sid, seller["id"]) is False
    assert not db.is_assigned(conn, sid, transporter["id"])
    os.environ.pop("TRACEGUARD_AUTO_ASSIGN_TRANSPORTER", None)


def test_downloading_current_qr_is_idempotent_and_does_not_invalidate_label():
    conn, seller, admin, transporter = _setup()
    sid = _register(conn, seller)
    old_payload = service.issue_rolling_qr(conn, sid, seller["id"])
    assert service.rolling_token_status(conn, old_payload) == (sid, "active")
    new_payload = service.issue_rolling_qr(conn, sid, seller["id"])
    assert new_payload == old_payload
    assert service.rolling_token_status(conn, old_payload) == (sid, "active")


def test_failed_handover_rolls_back_token_scan_event_and_audit_together():
    conn, seller, admin, transporter = _setup()
    sid = _register(conn, seller)
    assert service.auto_assign_default_transporter(conn, sid, seller["id"]) is True
    payload = service.issue_rolling_qr(conn, sid, seller["id"])
    before_audit = conn.execute("SELECT COUNT(*) FROM audit_chain").fetchone()[0]
    with patch("app.service.add_event", side_effect=RuntimeError("simulated persistence failure")):
        with pytest.raises(RuntimeError):
            service.process_scan_handover(conn, transporter, payload, "CBE-FARM", "DISPATCHED", "atomic-failure-key")
    assert service.rolling_token_status(conn, payload) == (sid, "active")
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM events WHERE shipment_id=?", (sid,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_chain").fetchone()[0] == before_audit
