"""HTTP tests for V2 auth, role controls, scan handovers and validation."""
import pytest
from fastapi.testclient import TestClient

from app import config, db, service
from app.security import make_token

BODY = {"product": "Tomatoes", "origin": "Coimbatore", "destination": "Chennai",
        "quantity": 500, "unit": "kg", "dispatch_date": "2026-10-10", "created_by": "spoofed name"}
PASSWORD = "TestPassword!2026"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACEGUARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRACEGUARD_DB", str(tmp_path / "t.db"))
    from app.main import app
    with TestClient(app) as c:
        # Each pytest case uses a fresh temporary DB; reset process-local rate-limit buckets too.
        layer = app.middleware_stack
        while layer is not None:
            if hasattr(layer, "writes") and hasattr(layer, "reads"):
                layer.writes.hits.clear(); layer.reads.hits.clear()
            layer = getattr(layer, "app", None)
        conn = db.connect(config.db_path())
        for username, label, role in [("admin", "Test Admin", "admin"), ("seller", "Test Seller", "seller"),
                                      ("driver", "Test Driver", "transporter"), ("inspector", "Test Inspector", "inspector")]:
            service.create_user(conn, username, label, role, PASSWORD)
        conn.close()
        response = c.post("/auth/login", json={"username": "admin", "password": PASSWORD})
        assert response.status_code == 200
        c.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
        yield c


def register(c):
    r = c.post("/shipments", json=BODY)
    assert r.status_code == 201, r.text
    return r.json()["shipment"]["id"]



def rolling_qr(c, sid):
    """Issue the same server-tracked token that the QR download endpoint would print."""
    conn = db.connect(config.db_path())
    try:
        admin = db.get_user_by_username(conn, "admin")
        return service.issue_rolling_qr(conn, sid, admin["id"])
    finally:
        conn.close()


def post_event(c, sid, t, cp="CP-A"):
    return c.post(f"/shipments/{sid}/events", json={"type": t, "checkpoint": cp, "actor": "spoofed actor"})


def login(c, username):
    response = c.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    c.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
    return response.json()["user"]


def test_requires_login_and_rejects_bad_credentials(client):
    client.headers.pop("Authorization", None)
    assert client.get("/dashboard").status_code == 401
    assert client.post("/auth/login", json={"username": "admin", "password": "wrong password"}).status_code == 401


def test_empty_dashboard(client):
    d = client.get("/dashboard").json()
    assert d["total_shipments"] == 0 and d["alerts"] == []


def test_scenario_1_legitimate_admin_correction_path(client):
    sid = register(client)
    for t, cp in [("DISPATCHED", "Farm"), ("IN_TRANSIT", "Toll"), ("RECEIVED", "Market"), ("DELIVERED", "Store")]:
        assert post_event(client, sid, t, cp).status_code == 201
    d = client.get(f"/shipments/{sid}").json()
    assert d["verdict"] == "VERIFIED" and d["status"] == "DELIVERED" and d["flags"] == []


def test_scenario_2_unknown_id(client):
    r = client.get("/verify/TG-2026-ZZZZZZ").json()
    assert r["found"] is False and r["detail"] is None and r["flags"][0]["rule_code"] == "UNKNOWN_ID"


def test_scenario_3_suspicious(client):
    sid = register(client)
    for t, cp in [("DISPATCHED", "Farm"), ("IN_TRANSIT", "Toll"), ("RECEIVED", "Chennai"), ("RECEIVED", "Bengaluru")]:
        out = post_event(client, sid, t, cp).json()
    assert out["new_flags"][0]["rule_code"] == "DUPLICATE_ARRIVAL"
    assert client.get("/dashboard").json()["under_investigation"] == 1


def test_qr_png_and_signed_scan(client):
    sid = register(client)
    r = client.get(f"/shipments/{sid}/qr")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    current = rolling_qr(client, sid)
    from urllib.parse import quote
    assert client.get(f"/verify/{quote(current, safe='')}").json()["found"] is True
    assert client.get(f"/verify/{make_token(sid)}").json()["found"] is True
    assert client.get(f"/verify/{sid}.{'0' * 20}").json()["found"] is False


@pytest.mark.parametrize("patch", [
    {"quantity": -5}, {"quantity": 0}, {"quantity": "lots"}, {"unit": "parsecs"},
    {"product": ""}, {"product": "x" * 500}, {"dispatch_date": "not-a-date"},
    {"extra_field": 1}, {"product": "bad\x00name"},
])
def test_malformed_shipment_payloads_rejected(client, patch):
    assert client.post("/shipments", json={**BODY, **patch}).status_code == 422


def test_malformed_event_and_flag_payloads_rejected(client):
    sid = register(client)
    base = {"type": "DISPATCHED", "checkpoint": "A", "actor": "x"}
    for bad in [{"type": "TELEPORTED"}, {"checkpoint": ""}, {"timestamp": "yesterdayish"}, {"quantity": -1}]:
        assert client.post(f"/shipments/{sid}/events", json={**base, **bad}).status_code == 422
    assert client.patch("/flags/1", json={"status": "deleted", "reason": "invalid"}).status_code == 422


def test_bad_ids_and_missing_resources(client):
    assert client.get("/shipments/TG-2026-ZZZZZZ").status_code == 404
    assert client.get("/shipments/not-an-id").status_code == 422
    assert client.get("/shipments/TG-2026-ZZZZZZ/qr").status_code == 404
    assert client.patch("/flags/999", json={"status": "reviewed", "reason": "not found"}).status_code == 404


def test_security_headers_and_sql_injection_in_search(client):
    register(client)
    r = client.get("/shipments", params={"q": "'; DROP TABLE shipments;--"})
    assert r.status_code == 200 and r.json() == []
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert len(client.get("/shipments").json()) == 1


def test_cors_rejects_unlisted_origin(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_rbac_prevents_seller_from_writing_events_or_reviewing_flags(client):
    sid = register(client)
    login(client, "seller")
    assert client.get("/shipments").status_code == 200
    assert client.post(f"/shipments/{sid}/events", json={"type": "DISPATCHED", "checkpoint": "Farm", "actor": "x"}).status_code == 403
    assert client.patch("/flags/1", json={"status": "reviewed", "reason": "checked"}).status_code == 403
    assert client.get("/shipments/TG-2026-ZZZZZZ").status_code == 404


def test_transporter_must_be_assigned_and_use_signed_qr(client):
    sid = register(client)
    login(client, "driver")
    signed = rolling_qr(client, sid)
    payload = {"scanned": signed, "checkpoint_id": "CBE-FARM", "action": "DISPATCHED", "idempotency_key": "first-scan-key-01"}
    assert client.post("/scans/handover", json=payload).status_code == 403
    login(client, "admin")
    assert client.post("/assignments", json={"shipment_id": sid, "username": "driver"}).status_code == 201
    login(client, "driver")
    # An ID typed by hand is not a signed QR and must not produce an event.
    unsigned = {**payload, "scanned": sid, "idempotency_key": "unsigned-scan-01"}
    assert client.post("/scans/handover", json=unsigned).status_code == 400
    # The same rejected scan stays idempotent, but the key cannot be re-used for another payload.
    assert client.post("/scans/handover", json=unsigned).status_code == 400
    other_unsigned = {**unsigned, "scanned": "TG-2026-AAAAAA"}
    assert client.post("/scans/handover", json=other_unsigned).status_code == 409
    assert client.get(f"/shipments/{sid}").status_code == 200
    first = client.post("/scans/handover", json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/scans/handover", json=payload)
    assert second.status_code == 201 and second.json()["duplicate"] is True
    detail = client.get(f"/shipments/{sid}").json()
    assert detail["status"] == "DISPATCHED" and len(detail["scans"]) == 1


def test_only_inspector_admin_can_use_manual_exception(client):
    sid = register(client)
    body = {"shipment_id": sid, "checkpoint_id": "CBE-FARM", "action": "DISPATCHED",
            "reason": "camera was broken and label was not readable", "idempotency_key": "manual-exception-key-1"}
    login(client, "driver")
    assert client.post("/scans/manual-handover", json=body).status_code == 403
    login(client, "inspector")
    r = client.post("/scans/manual-handover", json=body)
    assert r.status_code == 201, r.text
    assert "MANUAL EXCEPTION" in r.json()["detail"]["events"][0]["note"]
    unverifiable = next(f for f in r.json()["detail"]["flags"] if f["rule_code"] == "UNVERIFIABLE_SCANS")
    assert unverifiable["evidence"]["scan_ids"] and unverifiable["evidence"]["next_steps"]


def test_admin_user_creation_and_audit_chain(client):
    r = client.post("/users", json={"username": "new-user", "display_name": "New User", "role": "seller", "password": "StrongPass!123"})
    assert r.status_code == 201, r.text
    a = client.get("/audit/verify")
    assert a.status_code == 200 and a.json()["ok"] and a.json()["checked"] >= 2


def test_unsigned_id_lookup_does_not_disclose_shipment_details(client):
    sid = register(client)
    r = client.get(f"/verify/{sid}")
    assert r.status_code == 200
    assert r.json()["found"] is False and r.json()["detail"] is None
    assert client.get(f"/verify/{make_token(sid)}").json()["found"] is True



def test_cross_checkpoint_reuse_creates_persistent_evidence_and_audit(client):
    sid = register(client)
    assert client.post("/assignments", json={"shipment_id": sid, "username": "driver"}).status_code == 201
    login(client, "driver")
    token = rolling_qr(client, sid)
    first = client.post("/scans/handover", json={
        "scanned": token, "checkpoint_id": "CBE-FARM", "action": "DISPATCHED",
        "idempotency_key": "clone-scenario-first-01"})
    assert first.status_code == 201, first.text
    second = client.post("/scans/handover", json={
        "scanned": token, "checkpoint_id": "MAA-KOY", "action": "IN_TRANSIT",
        "idempotency_key": "clone-scenario-second-01"})
    assert second.status_code == 400, second.text
    detail = client.get(f"/shipments/{sid}").json()
    finding = next(f for f in detail["flags"] if f["rule_code"] == "STALE_LABEL_REUSE")
    assert finding["status"] == "open" and finding["severity"] == "high"
    login(client, "inspector")
    audit = client.get("/audit/verify").json()
    assert audit["ok"]
    conn = db.connect(config.db_path())
    kinds = {r[0] for r in conn.execute("SELECT kind FROM audit_chain")}
    conn.close()
    assert "STALE_QR_REUSE_DETECTED" in kinds


def test_idempotency_key_cannot_be_reused_for_different_handover(client):
    sid = register(client)
    assert client.post("/assignments", json={"shipment_id": sid, "username": "driver"}).status_code == 201
    login(client, "driver")
    payload = {"scanned": rolling_qr(client, sid), "checkpoint_id": "CBE-FARM", "action": "DISPATCHED",
               "idempotency_key": "same-key-different-action"}
    assert client.post("/scans/handover", json=payload).status_code == 201
    conflicting = {**payload, "action": "RECEIVED"}
    assert client.post("/scans/handover", json=conflicting).status_code == 409
    changed_payload = {**payload, "quantity": 10}
    assert client.post("/scans/handover", json=changed_payload).status_code == 409


def test_seller_label_is_limited_to_owned_shipment(client):
    client.headers.pop("Authorization", None)
    seller = login(client, "seller")
    own = client.post("/shipments", json=BODY)
    assert own.status_code == 201, own.text
    own_id = own.json()["shipment"]["id"]
    client.headers["Authorization"] = "Bearer " + client.post(
        "/auth/login", json={"username": "admin", "password": PASSWORD}).json()["access_token"]
    other_id = register(client)
    login(client, "seller")
    assert client.get(f"/shipments/{own_id}/qr").status_code == 200
    assert client.get(f"/shipments/{other_id}/qr").status_code == 404



def test_idempotent_retry_rechecks_current_checkpoint_assignment(client):
    sid = register(client)
    assert client.post("/assignments", json={"shipment_id": sid, "username": "driver"}).status_code == 201
    login(client, "driver")
    payload = {"scanned": rolling_qr(client, sid), "checkpoint_id": "CBE-FARM", "action": "DISPATCHED",
               "idempotency_key": "assignment-check-retry-01"}
    assert client.post("/scans/handover", json=payload).status_code == 201
    login(client, "admin")
    assert client.post("/assignments", json={"shipment_id": sid, "username": "driver",
        "checkpoint_id": "MAA-KOY"}).status_code == 201
    login(client, "driver")
    assert client.post("/scans/handover", json=payload).status_code == 403



def test_audit_chain_detects_tampered_actor_column(client):
    conn = db.connect(config.db_path())
    db.append_audit(conn, "TEST_ACTOR_INTEGRITY", db.utcnow().isoformat(), "original-actor", {"sample": "value"})
    conn.execute("UPDATE audit_chain SET actor_id=? WHERE kind=?", ("changed-actor", "TEST_ACTOR_INTEGRITY"))
    conn.commit()
    result = service.verify_audit_chain(conn)
    conn.close()
    assert result["ok"] is False
    assert "actor id" in result["reason"]



def test_shipment_registration_audit_names_authenticated_creator(client):
    r = client.post("/shipments", json=BODY)
    assert r.status_code == 201
    conn = db.connect(config.db_path())
    record = conn.execute("SELECT payload_json, actor_id FROM audit_chain WHERE kind='SHIPMENT_REGISTERED' ORDER BY seq DESC LIMIT 1").fetchone()
    conn.close()
    assert record["actor_id"] is not None
    assert '"_actor_id"' in record["payload_json"]


def test_logout_invalidates_session_token(client):
    login(client, "admin")
    # Verified user can access auth/me
    me_resp = client.get("/auth/me")
    assert me_resp.status_code == 200

    # Log out
    out_resp = client.post("/auth/logout")
    assert out_resp.status_code == 200
    assert out_resp.json()["status"] == "ok"

    # Token should now be rejected immediately
    me_after = client.get("/auth/me")
    assert me_after.status_code == 401
    assert "signed out" in me_after.json()["detail"].lower()


def test_login_brute_force_throttling(client):
    from app.security import login_throttle
    login_throttle.failures.clear()
    login_throttle.locked_until.clear()

    # 4 invalid attempts should return 401
    for _ in range(4):
        res = client.post("/auth/login", json={"username": "seller", "password": "WrongPassword123!"})
        assert res.status_code == 401

    # 5th failed attempt triggers lockout
    res5 = client.post("/auth/login", json={"username": "seller", "password": "WrongPassword123!"})
    assert res5.status_code == 401

    # 6th attempt should be blocked with 429
    res6 = client.post("/auth/login", json={"username": "seller", "password": "WrongPassword123!"})
    assert res6.status_code == 429
    assert "too many failed login attempts" in res6.json()["detail"].lower()

    # Clean up throttle
    login_throttle.failures.clear()
    login_throttle.locked_until.clear()


def test_audit_anchor_export_and_external_verification(client):
    login(client, "admin")
    # Export signed anchor receipt
    anchor_resp = client.get("/audit/anchor")
    assert anchor_resp.status_code == 200
    receipt = anchor_resp.json()
    assert "signature" in receipt
    assert "head_hash" in receipt
    assert receipt["sequence"] >= 1

    # Verify against the exported receipt
    ver_resp = client.post("/audit/verify-anchor", json={"anchor": receipt})
    assert ver_resp.status_code == 200
    ver_body = ver_resp.json()
    assert ver_body["ok"] is True
    assert ver_body["anchored_sequence"] == receipt["sequence"]

    # Tampered anchor receipt is rejected
    fake_receipt = dict(receipt, head_hash="0" * 64)
    bad_ver = client.post("/audit/verify-anchor", json={"anchor": fake_receipt})
    assert bad_ver.status_code == 200
    assert bad_ver.json()["ok"] is False


def test_audit_records_endpoint_pagination(client):
    login(client, "admin")
    resp = client.get("/audit/records?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "records" in data
    assert isinstance(data["records"], list)
    assert len(data["records"]) <= 10

