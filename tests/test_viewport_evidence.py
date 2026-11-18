"""Gate D: discovery viewports become device-matrix evidence."""
import json

from backend.device_matrix import android_evidence_from_run, evaluate_matrix, viewport_evidence_from_app_map


def test_viewport_evidence_marks_desktop_and_phone():
    rows = viewport_evidence_from_app_map([
        {"url": "https://shop.test/", "status": 200, "mobile_only": [], "layout": []},
        {"url": "https://shop.test/cart", "status": 200, "mobile_only": [{"text": "Menu"}]},
    ])
    assert {r["viewport"] for r in rows} == {"1366x900", "390x844"}
    assert all(r["outcome"] == "passed" for r in rows)
    matrix = evaluate_matrix(rows)
    assert "web.desktop" in matrix["verified"]
    assert "web.phone" in matrix["verified"]
    assert "android.emulator" in matrix["unverified"]
    assert matrix["complete"] is False


def test_viewport_evidence_without_phone_stays_desktop_only():
    rows = viewport_evidence_from_app_map([{"url": "https://shop.test/", "status": 200}])
    assert [r["viewport"] for r in rows] == ["1366x900"]


def test_android_evidence_only_when_device_and_results_exist(tmp_path):
    assert android_evidence_from_run(tmp_path, config={}, results=[{"status": "passed"}]) == []
    (tmp_path / "android_environment.json").write_text(json.dumps({
        "ok": True,
        "devices": [{"device_id": "emulator-5554", "status": "device"}],
    }), encoding="utf-8")
    # Probe alone is not verification.
    assert android_evidence_from_run(tmp_path, config={"device_id": "emulator-5554", "api_level": 30},
                                     results=[]) == []
    rows = android_evidence_from_run(
        tmp_path,
        config={"device_id": "emulator-5554", "api_level": 30},
        results=[{"status": "passed"}],
    )
    assert rows[0]["form"] == "emulator"
    matrix = evaluate_matrix(rows)
    assert "android.emulator" in matrix["verified"]
    assert "android.api24+" in matrix["verified"]
