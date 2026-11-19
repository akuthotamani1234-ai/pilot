"""A browser CI pack stays in this install. A link is left unread."""
from backend.blueprint_progress import progress
from backend.browser_portfolio_ci_readiness_pack_drill import (
    ARTIFACTS,
    run_browser_portfolio_ci_readiness_pack_drill,
)


def test_a_browser_ci_pack_does_not_follow_a_link(tmp_path):
    secret = "tenant-b-browser"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "browser_portfolio_ci_readiness_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_browser_portfolio_ci_readiness_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_f_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_browser_portfolio_ci_readiness_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    linked_artifact = real / ARTIFACTS[0][0]
    linked_artifact.symlink_to(kept)
    unread = run_browser_portfolio_ci_readiness_pack_drill(ops_dir=real)
    assert unread["ok"] is False
    assert unread["score"] == 0
    assert secret not in str(unread)
    assert secret not in planted.read_text(encoding="utf-8")
    assert kept.read_bytes() == original
    linked_artifact.unlink()

    for name, _label in ARTIFACTS:
        (real / name).write_text("{}", encoding="utf-8")
    saved = run_browser_portfolio_ci_readiness_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_f_complete"] is False
    assert saved["live_hosted_runners"] is False
    assert saved["ok"] is True
    assert saved["score"] == len(ARTIFACTS)
    assert "Browser portfolio CI readiness" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_browser_ci_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-browser-ci-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-browser-ci-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
