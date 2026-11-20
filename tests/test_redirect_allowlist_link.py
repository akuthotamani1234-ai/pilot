"""A redirect allowlist stays in this install. A link is left unwritten."""
from backend.blueprint_progress import progress
from backend.studio_sso_redirect_allowlist_enforcement_drill import (
    run_studio_sso_redirect_allowlist_enforcement_drill,
)


def test_a_redirect_allowlist_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-redirect"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "studio_sso_redirect_allowlist_enforcement_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_studio_sso_redirect_allowlist_enforcement_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_i_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_studio_sso_redirect_allowlist_enforcement_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()

    planted.unlink()
    saved = run_studio_sso_redirect_allowlist_enforcement_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_i_complete"] is False
    assert saved["ok"] is True
    assert saved["bad_rejected"] is True
    assert "listed URI accepted" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_redirect_allowlist_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-redirect-allowlist-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-redirect-allowlist-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert snap["complete"] is False
