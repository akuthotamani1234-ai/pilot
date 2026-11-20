"""Gate G: SQLite migrations apply; Postgres URLs stay explicitly unready."""
from backend.migrate import apply_migrations, list_migrations


def test_migrations_folder_has_tenancy_sql():
    names = [p.name for p in list_migrations()]
    assert "001_tenancy.sql" in names


def test_sqlite_migrations_apply(tmp_path):
    db = tmp_path / "tenant.sqlite"
    out = apply_migrations(f"sqlite:{db}")
    assert out["ready"] is True
    assert "001_tenancy.sql" in out["versions"]
    # idempotent
    again = apply_migrations(f"sqlite:{db}")
    assert again["applied"] == []
    assert again["ready"] is True


def test_postgres_uri_is_not_silently_ready():
    out = apply_migrations("postgresql://user:pass@localhost:5432/qpilot")
    assert out["ready"] is False
    assert out["backend"] == "postgres"


def test_migration_status_does_not_apply(tmp_path, monkeypatch):
    from backend.migrate import migration_status
    monkeypatch.chdir(tmp_path)
    status = migration_status(f"sqlite:{tmp_path / 'missing.sqlite'}")
    assert status["configured"] is True
    assert status["ready"] is False
    assert status["applied"] == []
    assert not (tmp_path / "missing.sqlite").exists()
