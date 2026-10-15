import sqlite3

import pytest

from app import db
from backup_db import backup_database


def test_backup_is_consistent_and_preserves_persisted_rows(tmp_path, monkeypatch):
    source = tmp_path / "live" / "traceguard.db"
    source.parent.mkdir(parents=True)
    monkeypatch.setenv("TRACEGUARD_DB", str(source))
    monkeypatch.setenv("TRACEGUARD_DATA_DIR", str(tmp_path / "data"))

    conn = db.connect(str(source))
    db.init_db(conn)
    conn.execute(
        "INSERT INTO users(id,username,display_name,role,password_hash,active,created_at) "
        "VALUES ('u1','seller','Seller','seller','test-hash',1,'2026-10-13T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    target = backup_database(tmp_path / "backups" / "copy.db")
    with sqlite3.connect(target) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT username FROM users WHERE id='u1'").fetchone()[0] == "seller"

    with pytest.raises(FileExistsError):
        backup_database(target)


def test_backup_refuses_missing_source(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACEGUARD_DB", str(tmp_path / "missing.db"))
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "backup.db")
