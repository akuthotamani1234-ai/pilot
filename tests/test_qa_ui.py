"""Opt-in real browser submission of an approved native flow and QA-lab presentation."""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
import requests
from playwright.sync_api import sync_playwright

from tests.qa_mobile_contracts import native_contract

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("BLOWAI_QA_UI_E2E") != "1", reason="Opt in to advanced browser/emulator UI verification"
    ),
]
ROOT = Path(__file__).resolve().parent.parent


def test_native_contract_form_and_accuracy_lab(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log = (tmp_path / "ui-service.log").open("w", encoding="utf-8")
    env = {**os.environ, "LLM_PROVIDER": "none", "BLOWAI_SECRET_DEMO_PASSWORD": "demo123", "PYTHONUTF8": "1"}
    service = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    job_id = None
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if requests.get(url, timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.25)
        contract = native_contract(url)
        contract.update(flows=[contract["flows"][0]], rules=[], checks=[], allowed_origins=[])
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1380, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.locator("#mobileModeBtn").click()
            page.wait_for_function("!document.getElementById('androidStart').disabled", timeout=60000)
            page.locator("#androidMode").select_option("installed")
            page.locator("#androidPackage").fill("com.blowai.demo")
            page.locator("#androidActivity").fill(".MainActivity")
            page.locator("#androidDevice").select_option("emulator-5554")
            page.locator("#androidProvider").select_option("none")
            page.locator("#androidMaxScreens").fill("1")
            page.locator("#androidMaxActions").fill("0")
            page.locator("#androidContract").fill(json.dumps(contract))
            page.locator("#androidContractOnly").check()
            page.locator("#androidAuthorized").check()
            with page.expect_response(
                lambda response: response.url.endswith("/api/mobile/runs") and response.request.method == "POST",
                timeout=60000,
            ) as submitted:
                page.locator("#androidStart").click()
            response = submitted.value
            assert response.status == 200, response.text()
            job = response.json()
            job_id = job["id"]
            print("ADVANCED_UI_RUN=" + job["run"], flush=True)
            page.wait_for_function(
                "document.getElementById('androidRunNote').textContent.includes('complete')", timeout=300000
            )
            run = ROOT / "runs" / job["run"]
            results = json.loads((run / "results.json").read_text(encoding="utf-8"))
            assert len(results) == 1 and results[0]["id"] == "contract_valid_login"
            assert results[0]["outcome"] == "passed" and results[0]["authentication_verified"]
            assert not (run / ".private/contract_inputs.json").exists()
            assert page.request.get(url + f"/runs/{job['run']}/.private/android_config.json").status == 404
            page.screenshot(path=str(run / "advanced-ui-proof.png"), full_page=True)
            page.goto(url + "/qa-lab")
            page.locator("#condition").fill("Approved login UI check")
            page.locator("#runs").select_option(job["run"])
            page.locator("#expected").fill(json.dumps({"contract_valid_login": "passed"}))
            page.locator("#add").click()
            with page.expect_response(
                lambda response: response.url.endswith("/api/qa/benchmark") and response.request.method == "POST"
            ) as built:
                page.locator("#build").click()
            result = built.value.json()
            assert built.value.status == 200, result
            assert result["measurement"]["counts"]["tn"] == 1
            assert result["measurement"]["precision"] is None
            page.locator("#report").click()
            assert page.get_by_role("heading", name="QA results you can verify").is_visible()
            assert page.get_by_text("Not measured", exact=True).count() == 2
            page.screenshot(path=str(run / "accuracy-lab-proof.png"), full_page=True)
            assert not errors, errors
            (run / "advanced-ui-verification.json").write_text(
                json.dumps(
                    {
                        "verified_at": datetime.now().isoformat(),
                        "native_login": "passed",
                        "contract_form": "passed",
                        "accuracy_lab": "passed",
                        "browser_errors": errors,
                        "presentation": result["report"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            browser.close()
    finally:
        if job_id is not None:
            try:
                status = requests.get(url + f"/api/runs/{job_id}", timeout=3).json()
                if status.get("status") == "running":
                    requests.post(url + f"/api/runs/{job_id}/stop", headers={"X-Agentic-QA": "1"}, timeout=10)
            except requests.RequestException:
                pass
        service.terminate()
        service.wait(timeout=15)
        log.close()
