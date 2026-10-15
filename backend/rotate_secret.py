"""Generate a new 256-bit TraceGuard master secret outside the project tree.

Usage: python rotate_secret.py D:\\TraceGuardSecrets\\traceguard.secret --force
After running, set TRACEGUARD_SECRET_FILE to that absolute path and restart.
Rotating this key invalidates existing signed QR labels and active sessions.
"""
from __future__ import annotations
import argparse, os, secrets, tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate/rotate the external TraceGuard signing secret")
    parser.add_argument("destination", help="Absolute path outside the TraceGuard project directory")
    parser.add_argument("--force", action="store_true", help="Replace an existing secret file")
    args = parser.parse_args()
    target = Path(args.destination).expanduser().resolve()
    try:
        target.relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    else:
        raise SystemExit("Refusing to store the secret inside the project/archive directory")
    if target.exists() and not args.force:
        raise SystemExit(f"Secret already exists: {target}; pass --force to rotate it")
    target.parent.mkdir(parents=True, exist_ok=True)
    value = (secrets.token_hex(32) + "\n").encode("ascii")
    fd, tmp_name = tempfile.mkstemp(prefix=".traceguard-secret-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(value); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    finally:
        try: os.unlink(tmp_name)
        except FileNotFoundError: pass
    print(f"Created a new 256-bit secret at: {target}")
    print("Set TRACEGUARD_ENV=production and TRACEGUARD_SECRET_FILE to this absolute path.")
    print("Also set TRACEGUARD_ORIGINS to explicit HTTPS frontend origins.")
    print("On Windows, restrict this file's NTFS permissions to the service account and administrators.")
    print("Existing sessions and signed QR labels must be replaced after rotation.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
