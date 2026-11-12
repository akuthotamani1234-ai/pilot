"""Opt-in REAL Android runs. Never required by the normal regression suite."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from backend import android, cost
from backend.config import settings
from backend.graph import build_graph

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
    subprocess.run([adb, "-s", device, "shell", "am", "force-stop", "com.blowai.demo"], check=True, capture_output=True)
    subprocess.run(
        [adb, "-s", device, "shell", "am", "start", "-n", "com.blowai.demo/.MainActivity", "--es", "blowai_bugs", bugs],
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
            "package_name": "com.blowai.demo",
            "app_activity": ".MainActivity",
            "device_id": device,
            "max_screens": 3,
            "max_actions": 8,
            "max_depth": 1,
            "max_test_cases": 10,
            "discovery_timeout_s": 120,
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
    assert final["verdict"] == expected, final
    assert len(final["screens"]) >= 2
    assert any(s["screen_name"] == "Login" for s in final["screens"])
    assert (run_dir / "test_cases.xlsx").is_file()
    assert any(r["outcome"] == "passed" for r in final["results"])
    assert any(r["outcome"] == "blocked" for r in final["results"])
    safety = subprocess.run(
        [adb, "-s", device, "shell", "run-as", "com.blowai.demo", "cat", "shared_prefs/demo.xml"],
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
    subprocess.run([adb, "-s", device, "shell", "am", "force-stop", "com.blowai.demo"], check=True, capture_output=True)
    subprocess.run(
        [adb, "-s", device, "shell", "am", "start", "-n", "com.blowai.demo/.MainActivity", "--es", "blowai_bugs", bugs],
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
            "package_name": "com.blowai.demo",
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
