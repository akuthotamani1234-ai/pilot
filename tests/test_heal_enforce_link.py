"""A healing escalation check stays in this install. A link is left unread."""
from backend.blueprint_progress import progress
from backend.production_healing_escalation_enforcement_drill import (
    run_production_healing_escalation_enforcement_drill,
)


def test_a_healing_escalation_check_does_not_follow_a_link(tmp_path):
    secret = "tenant-b-enforce"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "production_healing_escalation_enforcement_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_production_healing_escalation_enforcement_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_e_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_production_healing_escalation_enforcement_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_production_healing_escalation_enforcement_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_e_complete"] is False
    assert saved["production_suite_executed"] is False
    assert saved["ok"] is True
    assert saved["auth_blocked"] is True
    assert saved["infrastructure_blocked"] is True
    assert "Healing escalation enforced" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_heal_enforce_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-heal-enforce-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-heal-enforce-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "E")["status"] != "done"
    assert snap["complete"] is False
