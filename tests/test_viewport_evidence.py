"""Gate D: discovery viewports become device-matrix evidence."""
from backend.device_matrix import evaluate_matrix, viewport_evidence_from_app_map


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
