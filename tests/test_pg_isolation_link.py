"""A Postgres isolation drill stays in this install. A link does not start psql."""
import subprocess

from backend.blueprint_progress import progress
from backend.postgres_drill import isolation_drill


def test_a_postgres_isolation_drill_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.postgres_drill as mod

    calls = {"n": 0}

    def _migrate(*, dsn=None):
        calls["n"] += 1
        return {"ok": True, "applied": [], "files": []}

    def _psql(sql, *, dsn=None):
        calls["n"] += 1
        if "run_id='drill-run-b'" in sql:
            stdout = "0\n"
        elif "tenant_id='drill-a'" in sql:
            stdout = "drill-run-a\n"
        elif "tenant_id='drill-b'" in sql:
            stdout = "drill-run-b\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(mod, "apply_migrations_psql", _migrate)
    monkeypatch.setattr(mod, "run_psql", _psql)
    monkeypatch.setenv("POSTGRES_URL", "postgresql://example.invalid/qpilot")

    secret = "tenant-b-pg"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "postgres_isolation_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = isolation_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = isolation_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = isolation_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_g_complete"] is False
    assert saved["ok"] is True
    assert saved["tenant_a_runs"] == ["drill-run-a"]
    assert saved["cross_tenant_hits"] == "0"
    assert calls["n"] == 5
    assert "tenant-filtered" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_pg_isolation_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-pg-isolation-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-pg-isolation-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
