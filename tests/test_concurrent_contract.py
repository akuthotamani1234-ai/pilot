"""Regression checks for the opt-in discovery/contract handoff."""
import json

import pytest

from backend import concurrent_contract
from backend.agents.executor import _merge_contract_rows
from backend.config import settings
from tests.local_demo import quote_contract


@pytest.mark.parametrize("case", ["review", "discovery_only", "contract_only", "resuming", "flow"])
def test_modes_that_require_ordinary_execution_keep_the_existing_crawl(tmp_path, monkeypatch, case):
    state = {"run_dir": str(tmp_path), "url": "http://127.0.0.1"}
    contract = quote_contract()
    if case == "flow":
        contract["flows"] = [{"id": "login", "title": "Login form", "approved": True, "steps": [
            {"action": "assert_visible", "locator": {"strategy": "css", "value": "#login"}}]}]
    else:
        state[case] = True
    monkeypatch.setattr(settings, "review", "on" if case == "review" else "off")
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 2)
    monkeypatch.setenv("QA_CONTRACT_JSON", json.dumps(contract))
    monkeypatch.setattr(concurrent_contract, "discovery_agent", lambda original: {"state": original})
    assert concurrent_contract.discover_with_contract(state)["state"] is state


def test_checkpoint_merge_keeps_generated_and_other_completed_contract_cases():
    generated = {"id": "generated"}
    previous = [generated, {"contract_id": "first"}, {"contract_id": "quote", "outcome": "failed"}]
    current = [{"contract_id": "quote", "outcome": "passed"}]
    assert _merge_contract_rows(previous, current) == [generated, {"contract_id": "first"}, *current]
