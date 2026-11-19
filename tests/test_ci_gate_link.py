"""A CI artifact gate pack stays in this install. A link does not start the bundled checks."""
from backend.blueprint_progress import progress
from backend.hosted_ci_artifact_gate_pack_drill import (
    run_hosted_ci_artifact_gate_pack_drill,
)


def test_a_ci_gate_pack_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.ci_artifact_upload_rehearsal_drill as upload
    import backend.hosted_dispatch_payload_rehearsal_drill as dispatch
    import backend.hosted_runner_readiness_drill as ready

    calls = {"n": 0}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(ready, "run_hosted_runner_readiness_drill", _pass)
    monkeypatch.setattr(dispatch, "run_hosted_dispatch_payload_rehearsal_drill", _pass)
    monkeypatch.setattr(upload, "run_ci_artifact_upload_rehearsal_drill", _pass)

    secret = "tenant-b-gate"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "hosted_ci_artifact_gate_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_ci_artifact_gate_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert refused["gate_f_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_hosted_ci_artifact_gate_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_hosted_ci_artifact_gate_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert saved["live_hosted_runners"] is False
    assert saved["ok"] is True
    assert saved["parts"]["runner_readiness"] is True
    assert calls["n"] == 3
    assert "artifact gate pack ok" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_ci_gate_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-ci-gate-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-ci-gate-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
