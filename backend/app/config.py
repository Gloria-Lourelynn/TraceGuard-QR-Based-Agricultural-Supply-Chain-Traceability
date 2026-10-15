"""Runtime configuration with fail-closed production checks."""
from __future__ import annotations
import json, os, secrets, hmac
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent

def is_production() -> bool:
    return os.environ.get("TRACEGUARD_ENV", "development").strip().lower() == "production"

def data_dir() -> Path:
    d = Path(os.environ.get("TRACEGUARD_DATA_DIR", BASE_DIR / "data")); d.mkdir(parents=True, exist_ok=True); return d

def db_path() -> str:
    return os.environ.get("TRACEGUARD_DB") or str(data_dir() / "traceguard.db")

def allowed_origins() -> list[str]:
    raw = os.environ.get("TRACEGUARD_ORIGINS")
    if is_production() and not raw:
        raise RuntimeError("TRACEGUARD_ORIGINS must explicitly list the deployed HTTPS frontend origin(s) in production")
    origins = [o.strip().rstrip("/") for o in (raw or "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
    if is_production() and any(not o.startswith("https://") for o in origins):
        raise RuntimeError("Production CORS origins must use HTTPS")
    return origins

def auto_assign_transporter() -> str | None:
    default = "off" if is_production() else "transporter"
    raw = os.environ.get("TRACEGUARD_AUTO_ASSIGN_TRANSPORTER", default).strip()
    return None if raw.lower() in {"", "off", "none", "false", "0"} else raw

def secret_key() -> bytes:
    """Use an externally supplied secret in production; generate a local dev key otherwise."""
    secret_file = os.environ.get("TRACEGUARD_SECRET_FILE")
    env = os.environ.get("TRACEGUARD_SECRET")
    if secret_file:
        key = Path(secret_file).expanduser().read_bytes().strip()
        if len(key) < 32: raise RuntimeError("TRACEGUARD_SECRET_FILE must contain at least 32 bytes")
        return key
    if env:
        key = env.encode()
        if len(key) < 32: raise RuntimeError("TRACEGUARD_SECRET must be at least 32 bytes")
        return key
    if is_production():
        raise RuntimeError("TRACEGUARD_SECRET must be supplied by the deployment secret manager in production")
    path = data_dir() / "secret.key"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f: f.write(secrets.token_hex(32))
    key = path.read_text().strip().encode()
    if len(key) < 32: raise RuntimeError("Local secret key is too short; remove it and restart to regenerate")
    return key

def require_checkpoint_device() -> bool:
    return os.environ.get("TRACEGUARD_REQUIRE_CHECKPOINT_DEVICE", "0").strip().lower() in {"1", "true", "yes", "on"}

def checkpoint_device_tokens() -> dict[str, str]:
    """JSON map checkpoint_id -> high-entropy device secret, configured out-of-band."""
    raw = os.environ.get("TRACEGUARD_CHECKPOINT_DEVICE_TOKENS", "{}")
    try: value = json.loads(raw)
    except json.JSONDecodeError as e: raise RuntimeError("TRACEGUARD_CHECKPOINT_DEVICE_TOKENS must be a JSON object") from e
    if not isinstance(value, dict) or any(not isinstance(k,str) or not isinstance(v,str) or len(v) < 32 for k,v in value.items()):
        raise RuntimeError("Each checkpoint device token must be a string of at least 32 characters")
    return value

def valid_checkpoint_device(checkpoint_id: str, presented: str | None) -> bool:
    if not require_checkpoint_device(): return True
    expected = checkpoint_device_tokens().get(checkpoint_id)
    return bool(expected and presented and hmac.compare_digest(expected, presented))
