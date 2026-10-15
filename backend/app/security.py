"""Security helpers: signed QR payloads, rate limiting, response headers.

QR payload format:  <SHIPMENT_ID>.<SIGNATURE>
The signature is HMAC-SHA256(secret, SHIPMENT_ID), truncated to 20 hex chars,
so a made-up ID cannot be turned into a code the server will accept as
authentic. (It does NOT stop a perfect copy of a real code - that is what the
event rules are for.)
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
import secrets
from collections import defaultdict, deque

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import config

ID_RE = re.compile(r"^TG-\d{4}-[A-Z2-9]{6}$")
SIG_LEN = 20


def sign(shipment_id: str) -> str:
    mac = hmac.new(config.secret_key(), shipment_id.encode(), hashlib.sha256)
    return mac.hexdigest()[:SIG_LEN]


def make_token(shipment_id: str) -> str:
    return f"{shipment_id}.{sign(shipment_id)}"


ROLLING_PREFIX = "TG1"

def make_rolling_payload(shipment_id: str, random_token: str) -> str:
    """Payload for a server-tracked, single-use QR token."""
    return f"{ROLLING_PREFIX}|{shipment_id}|{random_token}"


def derive_rolling_token(shipment_id: str, nonce: str) -> str:
    """Derive a re-downloadable opaque token from a random DB nonce and server secret."""
    raw = hmac.new(config.secret_key(), f"traceguard-rolling-v1|{shipment_id}|{nonce}".encode(), hashlib.sha256).digest()
    import base64
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def parse_rolling_payload(raw: str) -> tuple[str | None, str | None]:
    """Return shipment id and opaque token for the rolling-label format."""
    parts = (raw or "").strip().split("|")
    if len(parts) != 3 or parts[0] != ROLLING_PREFIX or not ID_RE.fullmatch(parts[1]):
        return None, None
    token = parts[2]
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,60}", token):
        return None, None
    return parts[1], token

def parse_token(raw: str) -> tuple[str | None, bool | None]:
    """Return (shipment_id, signature_ok).

    signature_ok is None when the input carried no signature (a manually typed
    ID), True/False when one was present. shipment_id is None if the format is
    invalid.
    """
    raw = (raw or "").strip()
    sid, _, sig = raw.partition(".")
    if not ID_RE.match(sid):
        return None, None
    if not sig:
        return sid, None
    return sid, hmac.compare_digest(sig.lower(), sign(sid))


class RateLimiter:
    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self.hits) > 10_000:  # bound memory actively across all keys
            self._prune(now)
        return True

    def _prune(self, now: float) -> None:
        to_del = []
        for k, q in list(self.hits.items()):
            while q and now - q[0] > self.window:
                q.popleft()
            if not q:
                to_del.append(k)
        for k in to_del:
            self.hits.pop(k, None)
        if len(self.hits) > 10_000:
            # Force-drop oldest entries if under massive multi-IP attack
            excess = len(self.hits) - 5_000
            for k in list(self.hits.keys())[:excess]:
                self.hits.pop(k, None)


class LoginThrottle:
    """Protect /auth/login against credential stuffing and brute-force attacks."""

    def __init__(self, max_attempts: int = 5, window: float = 300.0, lockout: float = 60.0):
        self.max_attempts = max_attempts
        self.window = window
        self.lockout = lockout
        self.failures: dict[str, deque[float]] = defaultdict(deque)
        self.locked_until: dict[str, float] = {}

    def is_locked(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        until = self.locked_until.get(key, 0.0)
        if now < until:
            return True, int(until - now) + 1
        if key in self.locked_until:
            del self.locked_until[key]
        return False, 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        q = self.failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        q.append(now)
        if len(q) >= self.max_attempts:
            self.locked_until[key] = now + self.lockout

    def record_success(self, key: str) -> None:
        self.failures.pop(key, None)
        self.locked_until.pop(key, None)


login_throttle = LoginThrottle(max_attempts=5, window=300.0, lockout=60.0)


class RateLimitMiddleware:
    """Stricter budget for writes than for reads."""

    def __init__(self, app: ASGIApp, read_limit: int = 240, write_limit: int = 60):
        self.app = app
        self.reads = RateLimiter(read_limit)
        self.writes = RateLimiter(write_limit)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        client = scope.get("client")
        key = client[0] if client else "unknown"
        limiter = self.reads if scope["method"] in ("GET", "HEAD") else self.writes
        if not limiter.allow(key):
            resp = JSONResponse({"detail": "Too many requests. Slow down."}, 429)
            return await resp(scope, receive, send)
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cache-control", b"no-store"),
        (b"x-xss-protection", b"1; mode=block"),
        (b"permissions-policy", b"camera=(self), microphone=()"),
        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    ]

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message["headers"]}
                security_headers = list(self.HEADERS)
                if config.is_production():
                    security_headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = list(message["headers"]) + [
                    h for h in security_headers if h[0] not in existing
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)

