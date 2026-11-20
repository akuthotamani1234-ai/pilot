"""Opt-in REAL Android runs. Never required by the normal regression suite."""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from backend import android, cost
from backend.config import settings
from backend.graph import build_graph


def _tap_visible_text(device, adb, label):
    """Tap a fixture control by exact visible UIAutomator text/content description."""
    subprocess.run([adb, "-s", device, "shell", "uiautomator", "dump", "/sdcard/qpilot-window.xml"],
                   check=True, capture_output=True)
    hierarchy = subprocess.run([adb, "-s", device, "shell", "cat", "/sdcard/qpilot-window.xml"],
                              check=True, capture_output=True, text=True).stdout
    escaped = re.escape(label)
    match = re.search(
        rf'<node(?=[^>]*(?:text|content-desc)="(?:{escaped})")[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        hierarchy,
    )
    assert match, f"Control {label!r} not found in UI hierarchy"
    x1, y1, x2, y2 = map(int, match.groups())
    subprocess.run([adb, "-s", device, "shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2)],
                   check=True, capture_output=True)


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("BLOWAI_ANDROID_E2E") != "1", reason="Set BLOWAI_ANDROID_E2E=1 for a real Android device"
    ),
]


@pytest.mark.parametrize("bugs,expected", [("none", "Ready with Risks"), ("about_navigation", "Not Ready")])
def test_real_android_fixture_pipeline(tmp_path, monkeypatch, bugs, expected):
    device = os.environ.get("BLOWAI_ANDROID_DEVICE", "emulator-5554")
    environment = android.android_environment()
    assert environment["ok"], environment["errors"]
    android.require_device(device, environment["devices"])
    adb = environment["adb"]
    subprocess.run([adb, "-s", device, "shell", "am", "force-stop", "com.qpilot.demo"], check=True, capture_output=True)
    subprocess.run(
        [adb, "-s", device, "shell", "am", "start", "-n", "com.qpilot.demo/.MainActivity", "--es", "blowai_bugs", bugs],
        check=True,
        capture_output=True,
    )
    run_id = "android_device_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + bugs
    run_dir = Path(os.environ.get("BLOWAI_ANDROID_ARTIFACTS", str(tmp_path))) / run_id
    private = run_dir / ".private"
    private.mkdir(parents=True)
    config = android.validate_mobile_config(
        {
            "app_mode": "installed",
            "package_name": "com.qpilot.demo",
            "app_activity": ".MainActivity",
            "device_id": device,
            "max_screens": 3,
            "max_actions": 8,
            "max_depth": 1,
            "max_test_cases": 10,
            "discovery_timeout_s": 120,
            "contract_only": True,
            "qa_contract": {
                "version": 1,
                "test_environment": True,
                "android_package": "com.qpilot.demo",
                "flows": [
                    {
                        "id": "valid_login",
                        "title": "Approved local demo account reaches Dashboard",
                        "approved": True,
                        "authentication": True,
                        "steps": [
                            {
                                "action": "tap",
                                "locator": {"strategy": "accessibility_id", "value": "Open login screen"},
                            },
                            {
                                "action": "fill",
                                "locator": {"strategy": "accessibility_id", "value": "Username"},
                                "value": "demo",
                            },
                            {
                                "action": "fill",
                                "locator": {"strategy": "accessibility_id", "value": "Password"},
                                "secret_ref": "BLOWAI_SECRET_DEMO_PASSWORD",
                            },
                            {
                                "action": "tap",
                                "locator": {"strategy": "accessibility_id", "value": "Login"},
                                "purpose": "test_form",
                            },
                            {"action": "assert_screen", "value": "Dashboard"},
                        ],
                    }
                ],
            },
            "expected_destinations": {"about": "About", "open login screen": "Login"},
        }
    )
    (private / "android_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    monkeypatch.setattr(settings, "llm_provider", os.getenv("BLOWAI_ANDROID_AI", "none"))
    monkeypatch.setattr(settings, "llm_model", os.getenv("BLOWAI_ANDROID_MODEL", "qwen2.5:3b"))
    monkeypatch.setattr(settings, "llm_timeout", 90)
    cost.set_run_dir(run_dir)
    with SqliteSaver.from_conn_string(str(private / "checkpoint.sqlite")) as saver:
        final = build_graph(checkpointer=saver, target_type="mobile").invoke(
            {
                "target_type": "mobile",
                "config": config,
                "run_dir": str(run_dir),
                "run_id": run_id,
                "source": "Android fixture on " + device,
                "log": [],
            },
            {"configurable": {"thread_id": run_id}},
        )
    print("REAL_ANDROID_REPORT=" + str(run_dir / "report.html"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    print("REAL_ANDROID_SUMMARY=" + json.dumps(
        {key: summary.get(key) for key in ("verdict", "reasons", "gates", "incomplete", "incomplete_reason",
                                           "counts", "interaction", "account_setup")},
        sort_keys=True,
    ))
    result_rows = final.get("results") or []
    if isinstance(result_rows, dict):
        result_rows = list(result_rows.values())
    print("REAL_ANDROID_RESULT_ERRORS=" + json.dumps(
        [{key: row.get(key) for key in ("id", "outcome", "exception_type", "error")}
         for row in result_rows if isinstance(row, dict) and row.get("outcome") in ("error", "inconclusive")],
        sort_keys=True,
    ))
    assert final["verdict"] == expected, final
    assert len(final["screens"]) >= 2
    assert any(s["screen_name"] == "Login" for s in final["screens"])
    assert (run_dir / "test_cases.xlsx").is_file()
    assert any(r["outcome"] == "passed" for r in final["results"])
    assert any(r["outcome"] == "blocked" for r in final["results"])
    safety = subprocess.run(
        [adb, "-s", device, "shell", "run-as", "com.qpilot.demo", "cat", "shared_prefs/demo.xml"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert 'name="unsafe_action_count" value="0"' in safety.stdout
    if bugs != "none":
        failed = [r for r in final["results"] if r["outcome"] == "failed"]
        assert any(r.get("exception_type") == "AssertionError" and r.get("screenshot") for r in failed)


@pytest.mark.parametrize("bugs,expected", [("none", "Ready with Risks"), ("wrong_total", "Not Ready")])
def test_real_android_value_contract(tmp_path, monkeypatch, bugs, expected):
    device = os.environ.get("BLOWAI_ANDROID_DEVICE", "emulator-5554")
    environment = android.android_environment()
    assert environment["ok"], environment["errors"]
    adb = environment["adb"]
    subprocess.run([adb, "-s", device, "shell", "am", "force-stop", "com.qpilot.demo"], check=True, capture_output=True)
    subprocess.run(
        [adb, "-s", device, "shell", "am", "start", "-n", "com.qpilot.demo/.MainActivity", "--es", "blowai_bugs", bugs],
        check=True,
        capture_output=True,
    )
    run_id = "android_values_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + bugs
    run_dir = Path(os.environ.get("BLOWAI_ANDROID_ARTIFACTS", str(tmp_path))) / run_id
    private = run_dir / ".private"
    private.mkdir(parents=True)
    config = android.validate_mobile_config(
        {
            "app_mode": "installed",
            "package_name": "com.qpilot.demo",
            "app_activity": ".MainActivity",
            "device_id": device,
            "max_screens": 2,
            "max_actions": 6,
            "max_depth": 1,
            "max_test_cases": 6,
            "expected_destinations": {"cart": "Cart"},
            "expected_values": {"cart total": "Total: $0.00"},
        }
    )
    (private / "android_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    monkeypatch.setattr(settings, "llm_provider", "none")
    cost.set_run_dir(run_dir)
    with SqliteSaver.from_conn_string(str(private / "checkpoint.sqlite")) as saver:
        final = build_graph(checkpointer=saver, target_type="mobile").invoke(
            {"target_type": "mobile", "config": config, "run_dir": str(run_dir), "run_id": run_id, "log": []},
            {"configurable": {"thread_id": run_id}},
        )
    print("REAL_VALUE_REPORT=" + str(run_dir / "report.html"))
    assert final["verdict"] == expected, final
    assert any(s["screen_name"] == "Cart" for s in final["screens"])
    if bugs == "wrong_total":
        assert any("Expected text" in r.get("error", "") and r["outcome"] == "failed" for r in final["results"])


@pytest.mark.parametrize(
    "bugs,expected_message",
    [("none", "Name is required"), ("validation_accepts_empty", "Local form accepted")],
)
def test_real_android_empty_name_validation_behavior(bugs, expected_message):
    """Directly reproduce the seeded empty-name defect on the emulator."""
    device = os.environ.get("BLOWAI_ANDROID_DEVICE", "emulator-5554")
    environment = android.android_environment()
    assert environment["ok"], environment["errors"]
    android.require_device(device, environment["devices"])
    adb = environment["adb"
    ]
    subprocess.run([adb, "-s", device, "shell", "am", "force-stop", "com.qpilot.demo"],
                   check=True, capture_output=True)
    subprocess.run(
        [adb, "-s", device, "shell", "am", "start", "-n", "com.qpilot.demo/.MainActivity",
         "--es", "blowai_bugs", bugs],
        check=True, capture_output=True,
    )
    _tap_visible_text(device, adb, "Form validation")
    _tap_visible_text(device, adb, "Submit")
    subprocess.run([adb, "-s", device, "shell", "uiautomator", "dump", "/sdcard/qpilot-validation.xml"],
                   check=True, capture_output=True)
    hierarchy = subprocess.run([adb, "-s", device, "shell", "cat", "/sdcard/qpilot-validation.xml"],
                              check=True, capture_output=True, text=True).stdout
    assert expected_message in hierarchy, f"Expected {expected_message!r} after empty submission"
    safety = subprocess.run(
        [adb, "-s", device, "shell", "run-as", "com.qpilot.demo", "cat", "shared_prefs/demo.xml"],
        check=True, capture_output=True, text=True,
    )
    assert 'name="unsafe_action_count" value="0"' in safety.stdout
