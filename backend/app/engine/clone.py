"""Cross-checkpoint QR-reuse detector. Pure functions, no HTTP, no database.

Input: the scan records of ONE shipment. Output: findings with evidence.

What this can and cannot say
- Valid signature + two far-apart checkpoints too close in time means the
  recorded scans are physically implausible. It does NOT prove cloning: a
  checkpoint could have mis-stamped a time, mislabelled itself, or a human
  could have scanned a photo of the label.
- Scans without a trusted checkpoint id, or with an invalid signature, are
  never used for the travel-time comparison; they are reported as unknowns.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from . import checkpoints as cps


@dataclass(frozen=True)
class CloneConfig:
    max_speed_kmh: float = 90.0            # fastest plausible freight speed
    clock_skew: timedelta = timedelta(minutes=5)   # forgiveness for bad clocks
    min_distance_km: float = 20.0          # ignore nearby checkpoints (same yard/town)
    repeat_max: int = 3                    # flag when MORE than this many ...
    repeat_window: timedelta = timedelta(minutes=10)  # ... at one checkpoint in this window


DEFAULT = CloneConfig()


def _fmt(dt: datetime) -> str:
    return dt.isoformat()


def detect(scans: Sequence[Mapping[str, Any]], cfg: CloneConfig = DEFAULT) -> list[dict[str, Any]]:
    """Scan keys: id, timestamp (aware), checkpoint_id (or None), signature_valid (bool).

    Network retries must already be collapsed by the idempotency key before
    scans reach this function; every scan here is a distinct physical scan.
    """
    usable, unknown = [], []
    for s in sorted(scans, key=lambda s: (s["timestamp"], s["id"])):
        if s.get("signature_valid") is True and cps.get(s.get("checkpoint_id")):
            usable.append(s)
        else:
            unknown.append(s["id"])

    findings: list[dict[str, Any]] = []

    # 1) implausible travel between consecutive trusted scans at different checkpoints
    for a, b in zip(usable, usable[1:]):
        if a["checkpoint_id"] == b["checkpoint_id"]:
            continue
        ca, cb = cps.get(a["checkpoint_id"]), cps.get(b["checkpoint_id"])
        dist = cps.distance_km(ca, cb)
        if dist < cfg.min_distance_km:
            continue
        elapsed = b["timestamp"] - a["timestamp"]
        needed = timedelta(hours=dist / cfg.max_speed_kmh)
        if elapsed + cfg.clock_skew < needed:
            findings.append({
                "rule_code": "CROSS_CHECKPOINT_REUSE",
                "severity": "high",
                "incident_key": f"CROSS_CHECKPOINT_REUSE:{a['id']}:{b['id']}",
                "scan_ids": [a["id"], b["id"]],
                "summary": (f"The same valid QR was scanned at {ca.name} and {cb.name} "
                            f"{int(elapsed.total_seconds() // 60)} min apart; the trip needs at least "
                            f"{int(needed.total_seconds() // 60)} min at {cfg.max_speed_kmh:g} km/h."),
                "observed": {
                    "scans": [
                        {"scan_id": x["id"], "checkpoint": c.name, "checkpoint_id": c.id, "timestamp": _fmt(x["timestamp"])}
                        for x, c in ((a, ca), (b, cb))
                    ],
                    "elapsed_seconds": int(elapsed.total_seconds()),
                    "straight_line_km": round(dist, 1),
                },
                "expected": {
                    "min_travel_seconds": int(needed.total_seconds()),
                    "max_speed_kmh": cfg.max_speed_kmh,
                    "clock_skew_allowance_seconds": int(cfg.clock_skew.total_seconds()),
                },
                "why_suspicious": "Both signatures are valid, but one physical label cannot be in both places this quickly.",
                "unknowns": [
                    "Whether either checkpoint clock was wrong beyond the allowance.",
                    "Whether the label was legitimately photographed or re-printed by an authorised party.",
                    "Whether checkpoint ids were selected correctly by the scanner operator.",
                ],
                "next_steps": [
                    "Ask both checkpoint operators to confirm the scan time and the physical consignment present.",
                    "Compare the consignment seen at each site with the registered quantity and product.",
                ],
            })

    # 2) repeated scans at one checkpoint inside the window
    by_cp: dict[str, list[Mapping[str, Any]]] = {}
    for s in usable:
        by_cp.setdefault(s["checkpoint_id"], []).append(s)
    for cp_id, lst in by_cp.items():
        for i, last in enumerate(lst):
            window = [x for x in lst[: i + 1] if last["timestamp"] - x["timestamp"] < cfg.repeat_window]
            if len(window) > cfg.repeat_max:
                cp = cps.get(cp_id)
                ids = [x["id"] for x in window]
                findings.append({
                    "rule_code": "REPEATED_SCAN",
                    "severity": "medium",
                    "incident_key": f"REPEATED_SCAN:{cp_id}:{ids[0]}",  # stable per burst start
                    "scan_ids": ids,
                    "summary": f"{cp.name} recorded {len(window)} distinct scans within {int(cfg.repeat_window.total_seconds() // 60)} min.",
                    "observed": {"count": len(window), "checkpoint": cp.name,
                                 "timestamps": [_fmt(x["timestamp"]) for x in window]},
                    "expected": {"max_scans": cfg.repeat_max, "window_seconds": int(cfg.repeat_window.total_seconds())},
                    "why_suspicious": "Ordinary use is one scan per handover; bursts can mean a copied label or a stuck scanner.",
                    "unknowns": ["Whether an operator was simply re-checking the label."],
                    "next_steps": ["Ask the checkpoint operator whether re-scans were intentional."],
                })
                break  # one finding per burst, not one per extra scan

    if unknown:
        findings.append({
            "rule_code": "UNVERIFIABLE_SCANS",
            "severity": "low",
            "incident_key": f"UNVERIFIABLE_SCANS:{','.join(str(i) for i in unknown)}",
            "scan_ids": list(unknown),
            "summary": f"{len(unknown)} scan(s) lack a valid signature or a known checkpoint and were excluded from reuse checks.",
            "observed": {"excluded_scan_ids": list(unknown)},
            "expected": {"requires": "valid signature AND registered checkpoint id"},
            "why_suspicious": "Cross-checkpoint reuse cannot be assessed for these scans.",
            "unknowns": ["Where and when these scans really happened."],
            "next_steps": ["Re-scan with a registered checkpoint selected."],
        })
    return findings
