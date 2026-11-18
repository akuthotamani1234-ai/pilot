"""Phase 5 Gate D: device matrix stays unverified without executed evidence."""
from backend.device_matrix import default_matrix, evaluate_matrix


def test_default_matrix_lists_required_web_and_android_profiles():
    ids = [p["id"] for p in default_matrix()]
    assert ids == ["web.desktop", "web.phone", "android.emulator", "android.api24+"]


def test_empty_evidence_leaves_matrix_incomplete():
    out = evaluate_matrix([])
    assert out["complete"] is False
    assert out["unverified"] == ["web.desktop", "web.phone", "android.emulator", "android.api24+"]
    assert out["live_emulator_required"] is True


def test_executed_evidence_verifies_matching_profiles_only():
    out = evaluate_matrix([
        {"surface": "web", "viewport": "1366x900", "outcome": "passed"},
        {"surface": "web", "viewport": "390x844", "outcome": "failed"},
        {"surface": "android", "device_id": "emulator-5554", "api_level": 30, "outcome": "blocked"},
        {"surface": "android", "device_id": "emulator-5554", "api_level": 30, "outcome": "planned"},
    ])
    assert out["complete"] is True
    assert out["unverified"] == []
    assert "android.emulator" in out["verified"]
    assert "android.api24+" in out["verified"]
