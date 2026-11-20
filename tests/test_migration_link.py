"""A migration applies this install's SQL. A link is left unread."""
import sqlite3

from backend.blueprint_progress import progress
from backend.migrate import apply_sqlite, list_migrations


def test_a_migration_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-migration"
    other = tmp_path / "other"
    other.mkdir()
    stolen = other / "stolen.sql"
    stolen.write_text(
        "CREATE TABLE leaked (note TEXT); INSERT INTO leaked VALUES ('tenant-b-only-migration');",
        encoding="utf-8")
    original = stolen.read_bytes()
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "001_link.sql").symlink_to(stolen)
    monkeypatch.setattr("backend.migrate.MIGRATIONS", folder)

    names = [path.name for path in list_migrations()]
    assert names == []
    db = tmp_path / "app.sqlite"
    refused = apply_sqlite(db)
    assert refused["applied"] == []
    assert stolen.read_bytes() == original
    with sqlite3.connect(db) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "leaked" not in tables
    assert secret not in " ".join(tables)

    (folder / "002_real.sql").write_text(
        "CREATE TABLE home_own (note TEXT); INSERT INTO home_own VALUES ('home-own-migration');",
        encoding="utf-8")
    saved = apply_sqlite(db)
    assert saved["applied"] == ["002_real.sql"]
    assert "001_link.sql" not in saved["versions"]
    with sqlite3.connect(db) as conn:
        note = conn.execute("SELECT note FROM home_own").fetchone()[0]
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert note == "home-own-migration"
    assert secret not in note
    assert "leaked" not in tables
    assert stolen.read_bytes() == original


def test_a_postgres_migration_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-migration"
    other = tmp_path / "other"
    other.mkdir()
    stolen = other / "stolen.sql"
    stolen.write_text("-- tenant-b-only-migration\nSELECT 1;\n", encoding="utf-8")
    original = stolen.read_bytes()
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "001_link.sql").symlink_to(stolen)
    monkeypatch.setattr("backend.migrate.MIGRATIONS", folder)
    calls = []

    def _run(args, **kwargs):
        calls.append(list(args))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("backend.postgres_drill.subprocess.run", _run)
    from backend.postgres_drill import apply_migrations_psql
    refused = apply_migrations_psql(dsn="postgresql://example.invalid/qpilot")
    assert refused["applied"] == []
    assert calls == []
    assert stolen.read_bytes() == original

    real = folder / "002_real.sql"
    real.write_text("SELECT 'home-own-migration';\n", encoding="utf-8")
    saved = apply_migrations_psql(dsn="postgresql://example.invalid/qpilot")
    joined = " ".join(" ".join(args) for args in calls)
    assert str(real) in joined
    assert str(stolen) not in joined
    assert secret not in joined
    assert saved["applied"] == ["002_real.sql"]
    assert saved["ok"] is True
    assert stolen.read_bytes() == original


def test_migration_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-migration-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
