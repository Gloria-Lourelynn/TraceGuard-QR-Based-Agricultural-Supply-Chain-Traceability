"""Small, dependency-light authentication for the local-first V2 demo.

Passwords are PBKDF2-SHA256 hashes. Bearer tokens are short-lived HMAC-signed
JSON tokens; this is intentionally not advertised as a general OAuth/JWT server.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from . import config, db

TOKEN_TTL_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 260_000
ROLES = {"seller", "transporter", "inspector", "admin"}


def _token_key() -> bytes:
    # Domain-separate login tokens from QR label signatures while deriving both
    # from the same persistent master secret.
    return hmac.new(config.secret_key(), b"traceguard:auth-token:v1", hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, expected = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(rounds))
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


def create_token(user_id: str, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else int(now)
    payload = {"sub": user_id, "iat": issued, "exp": issued + TOKEN_TTL_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(_token_key(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def verify_token(token: str, now: int | None = None) -> dict[str, Any] | None:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(_token_key(), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature)):
            return None
        payload = json.loads(_unb64(body))
        current = int(time.time()) if now is None else int(now)
        if not isinstance(payload.get("sub"), str) or int(payload["exp"]) <= current:
            return None
        if int(payload.get("iat", 0)) > current + 60:
            return None
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {k: user[k] for k in ("id", "username", "display_name", "role", "active", "created_at") if k in user}


def login(conn, username: str, password: str) -> tuple[str, dict[str, Any]] | None:
    user = db.get_user_by_username(conn, username.strip())
    # Keep response wording uniform for missing, inactive and incorrect credentials.
    if not user or not user.get("active") or not verify_password(password, user["password_hash"]):
        return None
    return create_token(user["id"]), public_user(user)
