"""Gate D Appium product matrix stays incomplete; skips gracefully offline."""
from pathlib import Path

from backend.android_appium_product_matrix_drill import (
    run_android_appium_product_matrix_drill,
)


def test_android_appium_product_matrix_drill_reports_honestly(tmp_path: Path):
    evidence = run_android_appium_product_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert (tmp_path / "android_appium_product_matrix_drill.json").is_file()
    if evidence.get("ok"):
        assert evidence["api_level"] >= 26
        assert str(evidence.get("device_id") or "").startswith("emulator-")
        assert int(evidence.get("apps_passed") or 0) >= 2
        assert "android.emulator" in evidence.get("android_profiles_verified", [])
        assert "android.api24+" in evidence.get("android_profiles_verified", [])
    else:
        # Offline / no Appium / API < 26 — still emits an honest reason.
        assert evidence.get("reason")
