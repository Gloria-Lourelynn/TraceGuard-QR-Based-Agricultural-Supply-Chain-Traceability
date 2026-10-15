"""Verification rules.

Pure module: no HTTP, no database. Give it a shipment and its events (in the
order they were recorded) and it returns the derived status plus any flags,
each with a plain-language explanation. It only ever says an event "requires
investigation" - it never declares fraud.

All thresholds live in RuleConfig, so tuning the engine is a one-file change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from .states import FINAL, State, expected_next, is_allowed

SEVERITY: dict[str, str] = {
    "UNKNOWN_ID": "high",
    "INVALID_TRANSITION": "high",
    "EVENT_AFTER_FINAL": "high",
    "DUPLICATE_ARRIVAL": "high",
    "TIMESTAMP_ORDER": "medium",
    "FUTURE_TIMESTAMP": "medium",
    "DUPLICATE_SCAN": "medium",
    "RECORD_MISMATCH": "medium",
}


@dataclass(frozen=True)
class RuleConfig:
    duplicate_scan_max: int = 2  # flag when MORE than this many ...
    duplicate_scan_window: timedelta = timedelta(minutes=10)  # ... in this window
    future_tolerance: timedelta = timedelta(minutes=2)  # allowed clock skew


DEFAULT_CONFIG = RuleConfig()


@dataclass(frozen=True)
class FlagDraft:
    rule_code: str
    explanation: str
    event_id: int | None = None

    @property
    def severity(self) -> str:
        return SEVERITY[self.rule_code]


@dataclass
class Evaluation:
    status: State = State.REGISTERED
    flags: list[FlagDraft] = field(default_factory=list)
    valid_event_ids: set[int] = field(default_factory=set)


def unknown_id_flag(scanned: str) -> FlagDraft:
    shown = scanned[:40]
    return FlagDraft(
        "UNKNOWN_ID",
        f"No shipment matches the scanned code '{shown}'. The code may be mistyped, "
        "damaged, forged or from another system. This requires investigation.",
    )


def _norm(s: str | None) -> str:
    return (s or "").strip().casefold()


def evaluate_history(
    shipment: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    now: datetime | None = None,
    cfg: RuleConfig = DEFAULT_CONFIG,
) -> Evaluation:
    """Replay `events` (oldest recorded first) and return status + flags.

    Event mapping keys: id, type, checkpoint, timestamp (aware datetime),
    destination (optional), quantity (optional).
    Status is the state after the last *valid* event; invalid events are kept
    in the history (so it stays complete) but never advance the status.
    """
    now = now or datetime.now(timezone.utc)
    result = Evaluation()
    state = State.REGISTERED
    valid_received_checkpoints: list[str] = []

    for i, ev in enumerate(events):
        etype = State(ev["type"])
        eid = ev.get("id")
        ts: datetime = ev["timestamp"]
        checkpoint = ev["checkpoint"]

        def flag(code: str, text: str) -> None:
            result.flags.append(FlagDraft(code, text, eid))

        if state == FINAL:
            flag(
                "EVENT_AFTER_FINAL",
                f"A {etype.value} event was recorded at '{checkpoint}' after the shipment "
                "was already DELIVERED. Delivered is the final state, so nothing should follow it.",
            )
            valid = False
        elif etype == State.RECEIVED and any(
            _norm(c) != _norm(checkpoint) for c in valid_received_checkpoints
        ):
            flag(
                "DUPLICATE_ARRIVAL",
                f"The shipment was already RECEIVED at '{valid_received_checkpoints[0]}' and is now "
                f"reported RECEIVED again at '{checkpoint}'. A shipment can only arrive once.",
            )
            valid = False
        elif not is_allowed(state, etype):
            flag(
                "INVALID_TRANSITION",
                f"{etype.value} was recorded while the shipment was {state.value}. "
                f"Expected next: {', '.join(expected_next(state))}. The step was skipped or repeated.",
            )
            valid = False
        else:
            valid = True
            state = etype
            if etype == State.RECEIVED:
                valid_received_checkpoints.append(checkpoint)

        if valid and eid is not None:
            result.valid_event_ids.add(eid)

        if i > 0 and ts < events[i - 1]["timestamp"]:
            flag(
                "TIMESTAMP_ORDER",
                f"This event is stamped {ts.isoformat()}, earlier than the previous recorded event "
                f"({events[i - 1]['timestamp'].isoformat()}). Events should be in time order.",
            )

        if ts > now + cfg.future_tolerance:
            flag("FUTURE_TIMESTAMP", f"The event timestamp {ts.isoformat()} is in the future.")

        dest = ev.get("destination")
        if dest is not None and _norm(dest) != _norm(shipment["destination"]):
            flag(
                "RECORD_MISMATCH",
                f"Event destination '{dest}' differs from the registered destination "
                f"'{shipment['destination']}'.",
            )
        qty = ev.get("quantity")
        if qty is not None and abs(float(qty) - float(shipment["quantity"])) > 1e-9:
            flag(
                "RECORD_MISMATCH",
                f"Event quantity {qty:g} differs from the registered quantity "
                f"{float(shipment['quantity']):g} {shipment['unit']}.",
            )

        window_start = ts - cfg.duplicate_scan_window
        in_window = sum(
            1
            for prev in events[: i + 1]
            if _norm(prev["checkpoint"]) == _norm(checkpoint)
            and window_start < prev["timestamp"] <= ts
        )
        if in_window > cfg.duplicate_scan_max:
            minutes = int(cfg.duplicate_scan_window.total_seconds() // 60)
            flag(
                "DUPLICATE_SCAN",
                f"'{checkpoint}' has recorded this shipment {in_window} times within {minutes} minutes "
                f"(limit {cfg.duplicate_scan_max}). This may be a retry, or a copied code being scanned.",
            )

    result.status = state
    return result
