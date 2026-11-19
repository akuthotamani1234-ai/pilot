"""A readiness drill is this install's file. A link is not treated as evidence."""
import json

from backend.blueprint_progress import progress
from backend.enterprise import readiness
from backend.migrate import migration_status


def test_a_readiness_drill_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.enterprise as enterprise
    import backend.migrate as migrate

    secret = "tenant-b-only-evidence"
    other = tmp_path / "other"
    other.mkdir()
    (other / "postgres_isolation_drill.json").write_text(
        json.dumps({"ok": True, "secret": secret}), encoding="utf-8")
    (other / "swarm_control_drill.json").write_text(
        json.dumps({"secret": secret}), encoding="utf-8")
    (other / "keep.txt").write_text(secret, encoding="utf-8")
    root = tmp_path / "root"
    evidence = root / "docs" / "ops-evidence"
    evidence.mkdir(parents=True)
    (evidence / "postgres_isolation_drill.json").symlink_to(other / "postgres_isolation_drill.json")
    (evidence / "swarm_control_drill.json").symlink_to(other / "swarm_control_drill.json")
    monkeypatch.setattr(enterprise, "ROOT", root)
    monkeypatch.setattr(migrate, "ROOT", root)
    monkeypatch.setenv("POSTGRES_URL", "postgresql://example.invalid/qpilot")
    for name in ("DATABASE_URL", "QPILOT_DB_URL", "REDIS_URL", "QPILOT_REDIS_URL", "OBJECT_STORE_URI", "MINIO_URL"):
        monkeypatch.delenv(name, raising=False)

    refused = readiness()
    status = migration_status()
    dumped = json.dumps({"readiness": refused, "migration": status})
    assert refused["components"]["postgres"]["ready"] is False
    assert refused["components"]["swarm_control"]["ready"] is False
    assert status["ready"] is False
    assert secret not in dumped
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret
    assert json.loads((other / "postgres_isolation_drill.json").read_text(encoding="utf-8"))["secret"] == secret

    for name in ("postgres_isolation_drill.json", "swarm_control_drill.json"):
        (evidence / name).unlink()
        (evidence / name).write_text(json.dumps({"ok": True, "marker": "home-own-evidence"}), encoding="utf-8")
    saved = readiness()
    saved_status = migration_status()
    assert saved["components"]["postgres"]["ready"] is True
    assert saved["components"]["swarm_control"]["ready"] is True
    assert saved_status["ready"] is True
    assert secret not in json.dumps({"readiness": saved, "migration": saved_status})
    assert saved["gate_g_complete"] is False
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret


def test_evidence_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-evidence-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
