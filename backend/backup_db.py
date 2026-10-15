"""Create a consistent, integrity-checked SQLite backup of TraceGuard data.

Usage from backend/: python backup_db.py [optional-destination.db]
The SQLite backup API includes committed WAL data; copying traceguard.db alone
while the app is running is not a safe backup strategy.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import config


def backup_database(destination: str | Path | None = None) -> Path:
    source_path = Path(config.db_path()).resolve()
    if not source_path.exists():
        raise FileNotFoundError(
            f"TraceGuard database does not exist yet: {source_path}. Start the API or run seed.py first."
        )

    if destination is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = source_path.parent / "backups" / f"traceguard-{stamp}.db"
    else:
        target = Path(destination).expanduser().resolve()
    if target == source_path:
        raise ValueError("Backup destination must not be the live database file")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {target}")

    source = sqlite3.connect(str(source_path), timeout=10)
    target_conn = sqlite3.connect(str(target), timeout=10)
    try:
        source.backup(target_conn)
        result = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            target_conn.close()
            target.unlink(missing_ok=True)
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {result}")
    except Exception:
        target_conn.close()
        target.unlink(missing_ok=True)
        raise
    finally:
        source.close()
        try:
            target_conn.close()
        except Exception:
            pass
    try:
        target.chmod(0o600)  # owner-only on POSIX; Windows ACLs must be configured separately
    except OSError:
        pass
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the persistent TraceGuard SQLite database.")
    parser.add_argument("destination", nargs="?", help="Optional destination .db path (must not already exist)")
    args = parser.parse_args()
    path = backup_database(args.destination)
    print(f"Backup created and integrity-checked: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
