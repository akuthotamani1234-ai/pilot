"""Opt-in real Android verification of reusable advanced contracts."""

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
from tests.qa_contract_fixture import ContractFixture
from tests.qa_mobile_contracts import native_contract

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("BLOWAI_ADVANCED_E2E") != "1", reason="Opt-in real Android advanced QA"),
]


@pytest.mark.parametrize("broken", [False, True, False], ids=["clean", "seeded", "clean-repeat"])
def test_real_native_and_hybrid_contracts(tmp_path, monkeypatch, broken):
    environment = android.android_environment()
    assert environment["ok"], environment["errors"]
    device = os.environ.get("BLOWAI_ANDROID_DEVICE", "emulator-5554")
    adb = environment["adb"]
    driver_path = Path(os.environ.get("BLOWAI_CHROMEDRIVER", "tools/chromedriver/chromedriver.exe")).resolve()
    assert driver_path.is_file()
    monkeypatch.setenv("BLOWAI_CHROMEDRIVER", str(driver_path))
    monkeypatch.setenv("BLOWAI_SECRET_DEMO_PASSWORD", "demo123")
    monkeypatch.setenv("BLOWAI_SECRET_INVALID_PASSWORD", "invalid-demo-password")
    database = tmp_path / "backend.sqlite"
    monkeypatch.setenv("BLOWAI_DB_DEMO", str(database))
    with ContractFixture(database, broken=broken) as fixture:
        port = fixture.server.server_port
        subprocess.run([adb, "-s", device, "reverse", f"tcp:{port}", f"tcp:{port}"], check=True, capture_output=True)
        try:
            subprocess.run(
                [adb, "-s", device, "shell", "am", "force-stop", "com.blowai.demo"], check=True, capture_output=True
            )
            flags = "validation_accepts_empty,wrong_total" if broken else "none"
            subprocess.run(
                [
                    adb,
                    "-s",
                    device,
                    "shell",
                    "am",
                    "start",
                    "-n",
                    "com.blowai.demo/.MainActivity",
                    "--es",
                    "blowai_bugs",
                    flags,
                    "--es",
                    "web_url",
                    fixture.url + "/hybrid",
                ],
                check=True,
                capture_output=True,
            )
            run_id = (
                "advanced_android_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ("_seeded" if broken else "_clean")
            )
            run = Path(os.environ.get("BLOWAI_ANDROID_ARTIFACTS", str(tmp_path))) / run_id
            (run / ".private").mkdir(parents=True)
            config = android.validate_mobile_config(
                {
                    "app_mode": "installed",
                    "device_id": device,
                    "package_name": "com.blowai.demo",
                    "app_activity": ".MainActivity",
                    "max_screens": 1,
                    "max_actions": 0,
                    "max_test_cases": 20,
                    "contract_only": True,
                    "qa_contract": native_contract(fixture.url),
                }
            )
            (run / ".private/android_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
            monkeypatch.setattr(settings, "llm_provider", "none")
            cost.set_run_dir(run)
            with SqliteSaver.from_conn_string(str(run / ".private/checkpoint.sqlite")) as saver:
                final = build_graph(checkpointer=saver, target_type="mobile").invoke(
                    {
                        "target_type": "mobile",
                        "config": config,
                        "run_id": run_id,
                        "run_dir": str(run.resolve()),
                        "source": "Controlled advanced Android verification",
                        "log": [],
                    },
                    {"configurable": {"thread_id": run_id}},
                )
            print("ADVANCED_ANDROID_REPORT=" + str(run / "report.html"), flush=True)
            results = final["results"]
            by_id = {r["id"]: r for r in results}
            assert len(results) == 13
            assert not [r for r in results if r["outcome"] == "error"], results
            failing = (
                {
                    "contract_required_name",
                    "contract_cart_total",
                    "contract_hybrid_total",
                    "contract_api_total",
                    "contract_database_total",
                }
                if broken
                else set()
            )
            assert {r["id"] for r in results if r["outcome"] == "failed"} == failing
            assert by_id["contract_valid_login"]["authentication_verified"]
            assert by_id["contract_hybrid_journey"]["outcome"] == "passed"
            assert final["verdict"] == ("Not Ready" if broken else "Ready with Risks")
            assert not (run / ".private/contract_inputs.json").exists()
            assert not (run / ".private/active_appium_session.json").exists()
            serialized = (run / "results.json").read_text(encoding="utf-8")
            assert "demo123" not in serialized and "invalid-demo-password" not in serialized
            for row in results:
                if row["id"] in {"contract_required_name", "contract_valid_login", "contract_invalid_login"}:
                    assert not row.get("screenshot")
            safety = subprocess.run(
                [adb, "-s", device, "shell", "run-as", "com.blowai.demo", "cat", "shared_prefs/demo.xml"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert 'name="unsafe_action_count" value="0"' in safety.stdout
        finally:
            subprocess.run([adb, "-s", device, "reverse", "--remove", f"tcp:{port}"], check=False, capture_output=True)
