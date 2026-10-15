"""Transparent shipment risk-PRIORITISATION score. Pure functions.

This is NOT a probability of fraud and is NOT statistically calibrated: the
weights are judgement calls, kept in WEIGHTS so they can be argued about.
score = min(100, sum of weights of distinct incidents).
- An incident counts once, however many times it was re-detected (incident_key).
- Dismissed findings contribute 0 but stay visible (evidence is preserved).
- Reviewed findings still count: a human looked, the underlying records are unchanged.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

WEIGHTS = {"high": 40, "medium": 15, "low": 5}
CAP = 100
BANDS = ((60, "HIGH", "Review first. Several or severe findings."),
         (25, "ELEVATED", "Review soon. At least one notable finding."),
         (1, "LOW", "Minor findings only."),
         (0, "NONE", "No findings. This does not prove authenticity."))


def band(score: int) -> tuple[str, str]:
    for floor, name, meaning in BANDS:
        if score >= floor:
            return name, meaning
    return "NONE", BANDS[-1][2]


def assess(findings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """finding keys: rule_code, severity, status ('open'|'reviewed'|'dismissed'), incident_key."""
    seen: set[str] = set()
    parts, total = [], 0
    for f in findings:
        key = f["incident_key"]
        dup = key in seen
        seen.add(key)
        if dup:
            pts, why = 0, "duplicate detection of an incident already counted"
        elif f["status"] == "dismissed":
            pts, why = 0, "dismissed by a reviewer (evidence retained)"
        else:
            pts, why = WEIGHTS[f["severity"]], f"{f['severity']} severity weight"
        total += pts
        parts.append({"incident_key": key, "rule_code": f["rule_code"], "points": pts, "reason": why})
    score = min(CAP, total)
    name, meaning = band(score)
    return {"score": score, "band": name, "meaning": meaning, "uncapped": total, "contributions": parts,
            "disclaimer": "Prioritisation aid only. Not a probability of fraud; not statistically calibrated."}
