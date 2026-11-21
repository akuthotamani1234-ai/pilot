"""Verify the studio renders live browser worker targets during a real local fixture run."""
import argparse
import json
import os
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
import uvicorn
from playwright.sync_api import sync_playwright

from tests.local_demo import quote_contract
from tests.qa_contract_fixture import ContractFixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="Open the Studio dashboard on screen during the demo.")
    args = parser.parse_args()
    root = Path("runs/local-demo").resolve() / datetime.now().strftime("studio_%Y%m%d_%H%M%S_%f")
    root.mkdir(parents=True)
    os.environ.update(RUNS_DIR=str(root / "runs"), BASELINE_DIR=str(root / "baseline"),
                      WORKSPACE_DIR=str(root / "workspace"), REVIEW="off", LLM_PROVIDER="none",
                      QPILOT_CONCURRENT_CONTRACT="1", TEST_WORKERS="2", VISION="off",
                      SLACK_WEBHOOK_URL="", JIRA_URL="")
    from backend.server import app

    service = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    with socket.socket() as sock, ContractFixture(root / "fixture.sqlite", broken=True, demo_links=True) as fixture:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        thread = threading.Thread(target=service.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=not args.watch)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 960})
                    response = requests.post(base + "/api/runs", headers={"X-Agentic-QA": "1"}, timeout=30,
                                             json={"source": fixture.url, "authorized": True, "execution_mode": "fast",
                                                   "auth_mode": "public", "llm_provider": "none", "max_pages": 5,
                                                   "qa_contract": quote_contract()})
                    response.raise_for_status()
                    job = response.json()
                    page.goto(base, timeout=90000)
                    seen = False
                    deadline = time.monotonic() + 1200
                    while job["status"] == "running" and time.monotonic() < deadline:
                        if not seen and page.locator("#liveSwarm .swarm-cursor:visible").count() >= 2:
                            page.locator("#liveSwarm").screenshot(path=root / "workers.png")
                            seen = True
                        page.wait_for_timeout(500)
                        response = requests.get(f"{base}/api/runs/{job['id']}", timeout=30)
                        response.raise_for_status()
                        job = response.json()
                finally:
                    browser.close()
            run = root / "runs" / (job.get("run") or "_missing")
            rows = json.loads((run / "contract_results.json").read_text(encoding="utf-8"))
            result = {"visible_cursors": seen, "job_status": job["status"], "report": str(run / "report.html"),
                      "seeded_quote_detected": any(row["contract_id"] == "quote_total" and row["outcome"] == "failed"
                                                   for row in rows)}
            result["passed"] = seen and result["seeded_quote_detected"] and (run / "report.html").is_file()
            print(json.dumps(result), flush=True)
            (root / "evidence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            return int(not result["passed"])
        finally:
            service.should_exit = True
            thread.join(10)


if __name__ == "__main__":
    raise SystemExit(main())
