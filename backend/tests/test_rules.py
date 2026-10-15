"""Every rule gets a failing case (flag raised) and a passing case (no flag)."""
from datetime import timedelta

from app.engine.rules import RuleConfig, evaluate_history, unknown_id_flag
from app.engine.states import State

from .helpers import NOW, SHIPMENT, codes, ev

HAPPY = [
    ev(1, "DISPATCHED", 0, "Farm"),
    ev(2, "IN_TRANSIT", 60, "Toll"),
    ev(3, "RECEIVED", 120, "Market"),
    ev(4, "DELIVERED", 180, "Store"),
]


def run(events, **kw):
    return evaluate_history(SHIPMENT, events, NOW, **kw)


def test_happy_path_has_no_flags_and_ends_delivered():
    r = run(HAPPY)
    assert r.flags == [] and r.status == State.DELIVERED
    assert r.valid_event_ids == {1, 2, 3, 4}


def test_empty_history_is_registered():
    assert run([]).status == State.REGISTERED


def test_in_transit_may_repeat():
    r = run([ev(1, "DISPATCHED", 0), ev(2, "IN_TRANSIT", 60, "A"), ev(3, "IN_TRANSIT", 120, "B")])
    assert r.flags == [] and r.status == State.IN_TRANSIT


def test_unknown_id_flag():
    f = unknown_id_flag("TG-2026-ZZZZZZ")
    assert f.rule_code == "UNKNOWN_ID" and f.severity == "high" and "investigation" in f.explanation


def test_invalid_transition_skipped_step():
    r = run([ev(1, "DISPATCHED", 0), ev(2, "IN_TRANSIT", 60), ev(3, "DELIVERED", 120, "Store")])
    assert codes(r) == ["INVALID_TRANSITION"]
    assert r.status == State.IN_TRANSIT  # invalid event does not advance status
    assert 3 not in r.valid_event_ids


def test_invalid_transition_not_dispatched_first():
    assert codes(run([ev(1, "DELIVERED", 0)])) == ["INVALID_TRANSITION"]


def test_invalid_transition_repeat_of_once_only_state():
    r = run([ev(1, "DISPATCHED", 0), ev(2, "DISPATCHED", 30, "B")])
    assert codes(r) == ["INVALID_TRANSITION"]


def test_event_after_final():
    r = run(HAPPY + [ev(5, "IN_TRANSIT", 240, "Store")])
    assert codes(r) == ["EVENT_AFTER_FINAL"] and r.status == State.DELIVERED


def test_timestamp_order_flagged_and_equal_timestamps_ok():
    bad = run([ev(1, "DISPATCHED", 60), ev(2, "IN_TRANSIT", 30, "B")])
    assert codes(bad) == ["TIMESTAMP_ORDER"]
    same = run([ev(1, "DISPATCHED", 60), ev(2, "IN_TRANSIT", 60, "B")])
    assert same.flags == []


def test_future_timestamp_flagged_but_small_skew_tolerated():
    far = ev(1, "DISPATCHED", 0)
    far["timestamp"] = NOW + timedelta(hours=3)
    assert codes(run([far])) == ["FUTURE_TIMESTAMP"]
    near = ev(1, "DISPATCHED", 0)
    near["timestamp"] = NOW + timedelta(seconds=30)
    assert run([near]).flags == []


def test_duplicate_scan_threshold_edge():
    def scans(n, gap):
        return [ev(1, "DISPATCHED", 0, "Farm")] + [
            ev(i + 2, "IN_TRANSIT", 60 + i * gap, "Toll") for i in range(n)
        ]
    assert run(scans(2, 1)).flags == []                 # exactly 2 in window: ok
    assert codes(run(scans(3, 1))) == ["DUPLICATE_SCAN"]  # 3rd within 10 min: flagged
    assert run(scans(3, 6)).flags == []                 # spread over >10 min: ok
    cfg = RuleConfig(duplicate_scan_max=5)
    assert run(scans(5, 1), cfg=cfg).flags == []        # configurable threshold


def test_record_mismatch_destination_and_quantity():
    a = run([ev(1, "DISPATCHED", 0, destination="Bengaluru")])
    b = run([ev(1, "DISPATCHED", 0, quantity=400.0)])
    assert codes(a) == ["RECORD_MISMATCH"] and codes(b) == ["RECORD_MISMATCH"]
    ok = run([ev(1, "DISPATCHED", 0, destination=" chennai ", quantity=500.0)])
    assert ok.flags == []


def test_duplicate_arrival_at_different_checkpoint():
    r = run([ev(1, "DISPATCHED", 0), ev(2, "IN_TRANSIT", 30), ev(3, "RECEIVED", 60, "Chennai"),
             ev(4, "RECEIVED", 90, "Bengaluru")])
    assert codes(r) == ["DUPLICATE_ARRIVAL"]
    assert r.status == State.RECEIVED


def test_second_received_at_same_checkpoint_is_invalid_transition_not_duplicate_arrival():
    r = run([ev(1, "DISPATCHED", 0), ev(2, "IN_TRANSIT", 30), ev(3, "RECEIVED", 60, "Chennai"),
             ev(4, "RECEIVED", 90, "Chennai")])
    assert codes(r) == ["INVALID_TRANSITION"]


def test_severities_match_plan():
    from app.engine.rules import SEVERITY
    assert {k for k, v in SEVERITY.items() if v == "high"} == {
        "UNKNOWN_ID", "INVALID_TRANSITION", "EVENT_AFTER_FINAL", "DUPLICATE_ARRIVAL"}
    assert len(SEVERITY) == 8
