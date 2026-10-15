"""Shared test helpers (no pytest fixtures, so these tests also run under plain python)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
SHIPMENT = {"id": "TG-2026-ABC234", "destination": "Chennai", "quantity": 500.0, "unit": "kg"}


def ev(i: int, etype: str, minutes: float = 0, checkpoint: str = "CP-A", **extra):
    """An event i recorded `minutes` after a fixed base time (negative = earlier)."""
    base = NOW - timedelta(hours=5)
    return {"id": i, "type": etype, "checkpoint": checkpoint,
            "timestamp": base + timedelta(minutes=minutes), **extra}


def codes(evaluation) -> list[str]:
    return [f.rule_code for f in evaluation.flags]


def fresh_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def shipment_data(**over):
    d = {"product": "Tomatoes", "origin": "Coimbatore", "destination": "Chennai",
         "quantity": 500, "unit": "kg", "dispatch_date": NOW.date(), "created_by": "tester"}
    d.update(over)
    return d


def event_data(etype: str, minutes: float, checkpoint: str = "CP-A", **extra):
    return {"type": etype, "checkpoint": checkpoint, "actor": "tester",
            "timestamp": NOW - timedelta(hours=5) + timedelta(minutes=minutes), **extra}
