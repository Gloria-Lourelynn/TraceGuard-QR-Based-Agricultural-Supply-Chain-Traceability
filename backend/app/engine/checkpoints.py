"""Central checkpoint registry (DEMO DATA).

Coordinates are approximate, hand-entered for the Coimbatore -> Chennai
simulation. They are NOT survey data and no GPS hardware is involved.
In a real deployment this table would be managed by an administrator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Checkpoint:
    id: str
    name: str
    lat: float
    lon: float
    demo: bool = True


CHECKPOINTS: dict[str, Checkpoint] = {c.id: c for c in (
    Checkpoint("CBE-FARM", "Coimbatore Farm Gate", 11.0168, 76.9558),
    Checkpoint("SLM-TOLL", "Salem Toll Plaza", 11.6643, 78.1460),
    Checkpoint("TRY-POST", "Trichy Checkpost", 10.7905, 78.7047),
    Checkpoint("BLR-YARD", "Bengaluru Yeshwanthpur Yard", 13.0285, 77.5409),
    Checkpoint("MAA-KOY", "Chennai Koyambedu Market", 13.0694, 80.1948),
    Checkpoint("MAA-ST12", "Chennai Retail Store 12", 13.0827, 80.2707),
)}


def get(checkpoint_id: str | None) -> Checkpoint | None:
    """Unknown or missing ids return None: callers must not guess a location."""
    return CHECKPOINTS.get(checkpoint_id) if checkpoint_id else None


def distance_km(a: Checkpoint, b: Checkpoint) -> float:
    """Great-circle (haversine) distance. Straight-line, so it UNDER-states
    road distance - which makes the impossible-travel rule conservative."""
    r = 6371.0088
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
