"""A device CI pack stays in this install. A link is left unread."""
from backend.android_device_ci_readiness_pack_drill import (
    ARTIFACTS,
    run_android_device_ci_readiness_pack_drill,
)
from backend.blueprint_progress import progress


def test_a_device_ci_pack_does_not_follow_a_link(tmp_path):
    secret = "tenant-b-device"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "android_device_ci_readiness_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_android_device_ci_readiness_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_android_device_ci_readiness_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    linked_artifact = real / ARTIFACTS[0][0]
    linked_artifact.symlink_to(kept)
    unread = run_android_device_ci_readiness_pack_drill(ops_dir=real)
    assert unread["ok"] is False
    assert unread["score"] == 0
    assert secret not in str(unread)
    assert secret not in planted.read_text(encoding="utf-8")
    assert kept.read_bytes() == original
    linked_artifact.unlink()

    for name, _label in ARTIFACTS:
        (real / name).write_text("{}", encoding="utf-8")
    saved = run_android_device_ci_readiness_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["live_hosted_runners"] is False
    assert saved["ok"] is True
    assert saved["score"] == len(ARTIFACTS)
    assert "Android device CI readiness" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_device_ci_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-device-ci-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-device-ci-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert snap["complete"] is False
