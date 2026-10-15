"""The three demo scenarios and edge cases, exercised through the service layer."""
from datetime import timedelta

from app import db, service
from app.security import make_token, parse_token

from .helpers import NOW, event_data, fresh_conn, shipment_data


def register(conn):
    return service.register_shipment(conn, shipment_data(), NOW - timedelta(hours=6))["shipment"]["id"]


def test_scenario_1_legitimate_is_verified():
    conn = fresh_conn()
    sid = register(conn)
    for t, m, cp in [("DISPATCHED", 0, "Farm"), ("IN_TRANSIT", 60, "Toll"),
                     ("RECEIVED", 120, "Market"), ("DELIVERED", 180, "Store")]:
        service.add_event(conn, sid, event_data(t, m, cp), NOW)
    d = service.detail(conn, sid, NOW)
    assert d["status"] == "DELIVERED" and d["verdict"] == "VERIFIED"
    assert d["flags"] == [] and len(d["events"]) == 4


def test_scenario_2_unknown_id_shows_warning_and_no_data():
    conn = fresh_conn()
    r = service.verify(conn, "TG-2026-ZZZZZZ", NOW)
    assert r["found"] is False and r["detail"] is None
    assert r["flags"][0]["rule_code"] == "UNKNOWN_ID"


def test_scenario_3_suspicious_double_receive_and_delivered_before_received():
    conn = fresh_conn()
    a = register(conn)
    for t, m, cp in [("DISPATCHED", 0, "Farm"), ("IN_TRANSIT", 60, "Toll"),
                     ("RECEIVED", 120, "Chennai"), ("RECEIVED", 130, "Bengaluru")]:
        out = service.add_event(conn, a, event_data(t, m, cp), NOW)
    assert [f["rule_code"] for f in out["new_flags"]] == ["DUPLICATE_ARRIVAL"]
    d = service.detail(conn, a, NOW)
    assert d["verdict"] == "REQUIRES_INVESTIGATION" and d["open_flag_count"] == 1
    assert len(d["events"]) == 4  # flagged event is saved, history stays complete
    assert service.dashboard(conn)["under_investigation"] == 1

    b = register(conn)
    for t, m, cp in [("DISPATCHED", 0, "Farm"), ("IN_TRANSIT", 60, "Toll"), ("DELIVERED", 120, "Store")]:
        out = service.add_event(conn, b, event_data(t, m, cp), NOW)
    assert [f["rule_code"] for f in out["new_flags"]] == ["INVALID_TRANSITION"]
    assert service.detail(conn, b, NOW)["status"] == "IN_TRANSIT"


def test_flags_are_only_stored_once_per_event():
    conn = fresh_conn()
    sid = register(conn)
    service.add_event(conn, sid, event_data("DELIVERED", 0), NOW)
    service.add_event(conn, sid, event_data("DISPATCHED", 10), NOW)
    flags = db.list_flags(conn, sid)
    # DELIVERED-first is invalid; the later DISPATCHED is valid again, so exactly one flag
    assert [f["rule_code"] for f in flags] == ["INVALID_TRANSITION"]


def test_reviewing_a_flag_clears_the_open_count():
    conn = fresh_conn()
    sid = register(conn)
    service.add_event(conn, sid, event_data("DELIVERED", 0), NOW)
    flag = service.detail(conn, sid, NOW)["flags"][0]
    service.update_flag(conn, flag["id"], "reviewed")
    assert service.detail(conn, sid, NOW)["verdict"] == "VERIFIED"


def test_empty_database_dashboard():
    d = service.dashboard(fresh_conn())
    assert d["total_shipments"] == 0 and d["alerts"] == [] and d["investigation_list"] == []
    assert all(v == 0 for v in d["by_status"].values())


def test_signed_qr_roundtrip_and_forgery_rejected(tmp_path=None):
    import os, tempfile
    os.environ["TRACEGUARD_DATA_DIR"] = tempfile.mkdtemp()
    conn = fresh_conn()
    sid = register(conn)
    token = make_token(sid)
    assert parse_token(token) == (sid, True)
    assert service.verify(conn, token, NOW)["found"] is True
    # valid ID, forged signature -> treated exactly like an unknown ID
    forged = sid + "." + "0" * 20
    assert parse_token(forged) == (sid, False)
    r = service.verify(conn, forged, NOW)
    assert r["found"] is False and r["flags"][0]["rule_code"] == "UNKNOWN_ID"
    # made-up ID with a made-up signature
    assert service.verify(conn, "TG-2026-AAAAAA." + "a" * 20, NOW)["found"] is False
    # manual entry (no signature) still looks up, but signature_checked is False
    manual = service.verify(conn, sid, NOW)
    assert manual["found"] is True and manual["signature_checked"] is False


def test_hostile_input_is_inert():
    conn = fresh_conn()
    sid = register(conn)
    for bad in ["'; DROP TABLE shipments;--", "TG-2026-ABC234' OR '1'='1", "<script>alert(1)</script>", "%", "A" * 500]:
        assert service.verify(conn, bad, NOW)["found"] is False
    assert db.count_shipments(conn) == 1
    assert service.list_shipments(conn, "%") == []          # LIKE wildcards are escaped
    assert service.list_shipments(conn, "'; DROP TABLE")  == []
    assert len(service.list_shipments(conn, "tomato")) == 1


def test_seed_runs_and_produces_expected_verdicts():
    import seed
    conn = fresh_conn()
    ids = seed.seed(conn)
    v = {k: service.detail(conn, sid)["verdict"] for k, sid in ids.items()}
    assert v["legitimate"] == "VERIFIED"
    assert v["double_arrival"] == v["skipped_step"] == "REQUIRES_INVESTIGATION"
    assert v["mismatch"] == v["rapid_scans"] == "REQUIRES_INVESTIGATION"
    codes = {f["rule_code"] for f in service.detail(conn, ids["mismatch"])["flags"]}
    assert codes == {"RECORD_MISMATCH", "TIMESTAMP_ORDER"}
    assert {f["rule_code"] for f in service.detail(conn, ids["rapid_scans"])["flags"]} == {"DUPLICATE_SCAN"}
