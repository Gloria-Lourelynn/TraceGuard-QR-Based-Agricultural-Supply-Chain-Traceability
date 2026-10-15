"""Pydantic request models. Every field is bounded; unknown fields are rejected."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Unit = Literal["kg", "quintal", "tonne", "crate", "bag", "litre", "unit"]
EventTypeName = Literal["DISPATCHED", "IN_TRANSIT", "RECEIVED", "DELIVERED"]

Short = Field(min_length=1, max_length=80)
Person = Field(min_length=1, max_length=60)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="after")
    @classmethod
    def _no_control_chars(cls, v):
        if isinstance(v, str) and any(ord(c) < 32 and c not in "\n\t" for c in v):
            raise ValueError("control characters are not allowed")
        return v


class ShipmentCreate(_Strict):
    product: str = Short
    origin: str = Short
    destination: str = Short
    quantity: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    unit: Unit
    dispatch_date: date
    created_by: str = Person


class EventCreate(_Strict):
    type: EventTypeName
    checkpoint: str = Short
    actor: str = Person
    timestamp: datetime | None = None  # defaults to "now" on the server
    note: str = Field(default="", max_length=280)
    destination: str | None = Field(default=None, min_length=1, max_length=80)
    quantity: float | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)




class LoginRequest(_Strict):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class UserCreate(_Strict):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal["seller", "transporter", "inspector", "admin"]
    password: str = Field(min_length=10, max_length=200)


class AssignmentCreate(_Strict):
    shipment_id: str = Field(min_length=1, max_length=20)
    username: str = Field(min_length=1, max_length=60)
    checkpoint_id: str | None = Field(default=None, max_length=30)


class HandoverCreate(_Strict):
    scanned: str = Field(min_length=1, max_length=120)
    checkpoint_id: str = Field(min_length=1, max_length=30)
    action: EventTypeName
    idempotency_key: str = Field(min_length=8, max_length=100)
    note: str = Field(default="", max_length=280)
    destination: str | None = Field(default=None, min_length=1, max_length=80)
    quantity: float | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)


class ManualHandoverCreate(_Strict):
    shipment_id: str = Field(min_length=1, max_length=20)
    checkpoint_id: str = Field(min_length=1, max_length=30)
    action: EventTypeName
    reason: str = Field(min_length=10, max_length=280)
    idempotency_key: str = Field(min_length=8, max_length=100)


class FlagPatch(_Strict):
    status: Literal["reviewed", "dismissed"]
    reason: str = Field(min_length=3, max_length=280)


class AnchorVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    anchor: dict[str, Any]

