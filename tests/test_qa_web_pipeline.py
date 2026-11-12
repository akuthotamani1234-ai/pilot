"""Real existing web pipeline with an approved QA contract; no AI calls."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import server
from tests.qa_contract_fixture import ContractFixture
from tests.test_qa_contracts import web_contract

pytestmark = pytest.mark.slow


def test_web_submission_runs_contracts_through_existing_report(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOWAI_SECRET_DEMO_PASSWORD", "demo123")
    monkeypatch.setenv("BLOWAI_DB_DEMO", str(tmp_path / "backend.sqlite"))
    job_id = None
    with ContractFixture(tmp_path / "backend.sqlite", broken=True) as fixture:
        client = TestClient(server.app, base_url="http://127.0.0.1:8000")
        try:
            response = client.post("/api/runs", headers={"X-Agentic-QA": "1"}, json={
                "source": fixture.url, "authorized": True, "llm_provider": "none", "max_pages": 1,
                "qa_contract": web_contract(fixture.url),
            })
            assert response.status_code == 200, response.text
            job_id = response.json()["id"]
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                status = client.get(f"/api/runs/{job_id}").json()
                if status["status"] != "running":
                    break
                time.sleep(.5)
            assert status["status"] != "running", status
            assert status.get("run"), status
            run = Path(server.RUNS) / status["run"]
            print("WEB_CONTRACT_REPORT=" + str(run / "report.html"), flush=True)
            summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
            results = json.loads((run / "results.json").read_text(encoding="utf-8"))
            contracts = [r for r in results if r.get("contract_id")]
            assert len(contracts) == 5, contracts
            assert sum(r["outcome"] == "failed" for r in contracts) == 4, contracts
            assert not [r for r in contracts if r["outcome"] == "error"]
            assert summary["verdict"] == "Not Ready", summary
            assert (run / "test_cases.xlsx").is_file()
            assert "demo123" not in (run / "results.json").read_text(encoding="utf-8")
            failures = json.loads((run / "failures.json").read_text(encoding="utf-8"))
            assert any(f["category"] == "product_defect" for f in failures), failures
        finally:
            if job_id is not None:
                job = server.jobs.get(job_id)
                if job and job["status"] == "running":
                    server._kill(job)
                server.jobs.pop(job_id, None)
