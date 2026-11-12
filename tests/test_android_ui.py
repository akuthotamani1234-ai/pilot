"""Opt-in browser UI -> real APK upload -> Appium -> report integration."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from playwright.sync_api import sync_playwright

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.getenv("BLOWAI_ANDROID_UI_E2E") != "1", reason="Opt in to a real emulator UI run"),
]
ROOT = Path(__file__).resolve().parent.parent


def test_android_ui_upload_runs_to_report(tmp_path):
    apk = Path(os.environ["BLOWAI_ANDROID_APK"])
    assert apk.is_file()
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log = (tmp_path / "server.log").open("w", encoding="utf-8")
    env = {**os.environ, "LLM_PROVIDER": "none", "PYTHONUTF8": "1"}
    service = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if requests.get(url, timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.locator("#mobileModeBtn").click()
            page.wait_for_function("document.getElementById('androidStart').disabled === false", timeout=60000)
            page.locator("#androidDevice").select_option(os.getenv("BLOWAI_ANDROID_DEVICE", "emulator-5554"))
            page.locator("#androidApk").set_input_files(str(apk))
            page.locator("#androidProvider").select_option("none")
            page.locator("details.mobile-advanced > summary").click()
            page.locator("#androidMaxScreens").fill("2")
            page.locator("#androidMaxActions").fill("6")
            page.locator("#androidDepth").fill("1")
            page.locator("#androidDiscoveryTimeout").fill("300")
            page.locator("#androidExpectations").fill("About = About")
            page.locator("#androidAuthorized").check()
            with page.expect_response(
                lambda response: response.url.endswith("/api/mobile/runs") and response.request.method == "POST",
                timeout=60000,
            ) as submission:
                page.locator("#androidStart").click()
            response = submission.value
            assert response.status == 200, response.text()
            job = response.json()
            print("REAL_UI_RUN=" + job["run"], flush=True)
            page.wait_for_function(
                "document.getElementById('androidRunNote').textContent.includes('complete')", timeout=900000
            )
            report = page.request.get(url + "/api/report/" + job["run"]).json()
            assert report["summary"]["verdict"] == "Ready with Risks", report
            run_dir = ROOT / "runs" / job["run"]
            page.screenshot(path=str(run_dir / "ui-proof.png"), full_page=True)
            cases = page.request.get(url + "/api/cases/" + job["run"])
            assert cases.status == 200
            assert cases.json()["passed"] > 0
            assert (run_dir / ".private" / "app.apk").is_file()
            assert (run_dir / ".private" / "checkpoint.sqlite").is_file()
            config = json.loads((run_dir / ".private/android_config.json").read_text(encoding="utf-8"))
            assert config['discovery_timeout_s'] == 300
            assert page.request.get(url + "/runs/" + job["run"] + "/.private/app.apk").status == 404
            assert not errors, errors
            (run_dir / "ui-verification.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "browser_errors": errors,
                        "apk_upload": "real fixture APK",
                        "run": job["run"],
                        "verdict": report["summary"]["verdict"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            browser.close()
    finally:
        if os.name == 'nt' and service.poll() is None:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(service.pid)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            service.terminate()
        try:
            service.wait(timeout=15)
        except subprocess.TimeoutExpired:
            service.kill()
            service.wait(timeout=5)
        log.close()
