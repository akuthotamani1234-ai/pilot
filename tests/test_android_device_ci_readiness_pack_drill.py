"""Android device CI readiness pack stays incomplete for Gate D."""
from backend.android_device_ci_readiness_pack_drill import (
    run_android_device_ci_readiness_pack_drill,
)


def test_android_device_ci_readiness_pack_stays_partial(tmp_path):
    import backend.android_device_ci_readiness_pack_drill as mod

    for name, _ in mod.ARTIFACTS:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    evidence = run_android_device_ci_readiness_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert evidence["score"] == evidence["score_of"]
    assert (tmp_path / "android_device_ci_readiness_pack_drill.json").is_file()
