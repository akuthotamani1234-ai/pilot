"""Gate D android emulator smoke stays incomplete; skips when no emulator."""
from pathlib import Path

from backend.android_emulator_smoke_drill import run_android_emulator_smoke_drill


def test_android_emulator_smoke_drill_reports_honestly(tmp_path: Path):
    evidence = run_android_emulator_smoke_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert (tmp_path / "android_emulator_smoke_drill.json").is_file()
    if evidence.get("ok"):
        assert evidence["api_level"] >= 24
        assert str(evidence.get("device_id") or "").startswith("emulator-")
        assert "android.emulator" in evidence.get("android_profiles_verified", [])
        assert "android.api24+" in evidence.get("android_profiles_verified", [])
    else:
        assert evidence.get("devices_online", 0) == 0
