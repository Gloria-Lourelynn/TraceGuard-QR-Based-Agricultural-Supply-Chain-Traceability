"""Allowed shipment state transitions.

REGISTERED -> DISPATCHED -> IN_TRANSIT -> RECEIVED -> DELIVERED
IN_TRANSIT may repeat (several checkpoints); every other state occurs once.
"""
from __future__ import annotations

from enum import Enum


class State(str, Enum):
    REGISTERED = "REGISTERED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    DELIVERED = "DELIVERED"


EVENT_TYPES: tuple[State, ...] = (
    State.DISPATCHED,
    State.IN_TRANSIT,
    State.RECEIVED,
    State.DELIVERED,
)

ALLOWED: dict[State, frozenset[State]] = {
    State.REGISTERED: frozenset({State.DISPATCHED}),
    State.DISPATCHED: frozenset({State.IN_TRANSIT}),
    State.IN_TRANSIT: frozenset({State.IN_TRANSIT, State.RECEIVED}),
    State.RECEIVED: frozenset({State.DELIVERED}),
    State.DELIVERED: frozenset(),
}

FINAL = State.DELIVERED


def is_allowed(current: State, nxt: State) -> bool:
    return nxt in ALLOWED[current]


def expected_next(current: State) -> list[str]:
    return sorted(s.value for s in ALLOWED[current])
