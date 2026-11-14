"""Android progress, continuation and combined UI/backend outcomes."""
import json
import sqlite3

import pytest

from backend.android_coverage import dashboard
from backend.android_events import Timeline
from backend.android_resume import plan
from backend.android_scenarios import Draft, draft
from backend.execution_events import read_events
from backend.qa_contracts import contract_cases, parse_contract
from backend.qa_oracles import resolve_private_inputs
from backend.qa_runtime import ContractRuntime


def save(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def journal(root, name, rows):
    (root / name).write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding="utf-8")


def case(cid, read_only=False):
    return {"id": cid, "title": cid, "plan": [["open_screen", ["launch"]], ["assert_visible", ["heading"]]]
            if read_only else [["assert_flow", [cid]]]}


def test_action_is_visible_before_it_finishes_and_never_discloses_inputs(tmp_path):
    timeline = Timeline(tmp_path, {"id": "login", "title": "Login"}, secrets=["private-pass"])
    with timeline.action({"action": "fill", "value": "private-pass"}):
        assert read_events(tmp_path)["events"][0]["status"] == "started"
    with pytest.raises(AssertionError), timeline.action({"action": "assert_text"}):
        raise AssertionError("private-pass was wrong")
    data = read_events(tmp_path)
    assert [row["status"] for row in data["events"]] == ["started", "passed", "started", "failed"]
    assert "private-pass" not in json.dumps(data)
    assert data["events"][-1]["observed"] == "AssertionError"
    assert read_events(tmp_path, data["cursor"])["events"] == []


def test_short_numeric_private_values_cannot_corrupt_event_json(tmp_path):
    timeline = Timeline(tmp_path, secrets=["1"])
    timeline.emit("passed", "private value 1", elapsed=1.0)
    timeline.close()
    event = read_events(tmp_path)["events"][0]
    assert event["status"] == "passed" and event["elapsed"] == 1.0
    assert event["text"] == "private value [REDACTED]"


def test_event_reader_preserves_numeric_metadata_when_it_matches_a_private_value(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOWAI_SECRET_COLLISION", "1234")
    journal(tmp_path, "events.fixture.jsonl", [{"id": "event", "timestamp": 1234.5, "elapsed": 1234,
                                              "status": "passed", "text": "private value 1234"}])
    event = read_events(tmp_path)["events"][0]
    assert event["timestamp"] == 1234.5 and event["elapsed"] == 1234
    assert event["text"] == "private value [REDACTED]"


def test_resume_preserves_passes_failures_and_quarantines_interrupted_writes(tmp_path):
    cases = [case("passed"), case("failed"), case("uncertain"), case("reading", True), case("new")]
    journal(tmp_path, "android_results.jsonl", [{"id": "passed", "outcome": "passed"}, {"id": "failed", "outcome": "failed"}])
    journal(tmp_path, "android_attempts.jsonl", [{"id": "uncertain"}, {"id": "reading"}])
    result = plan(tmp_path, cases)
    assert [row["id"] for row in result["pending"]] == ["reading", "new"]
    assert [row["id"] for row in result["completed"]] == ["passed", "failed"]
    assert result["uncertain"][0]["id"] == "uncertain"
    assert result["uncertain"][0]["outcome"] == "blocked"


def test_legacy_runs_without_attempt_journal_do_not_replay_unknown_mutations(tmp_path):
    journal(tmp_path, "android_results.jsonl", [{"id": "old", "outcome": "passed"}])
    result = plan(tmp_path, [case("old"), case("maybe_started"), case("safe", True)])
    assert [row["id"] for row in result["pending"]] == ["safe"]
    assert result["uncertain"][0]["id"] == "maybe_started"


def test_coverage_keeps_zero_assertions_and_pending_work_visible(tmp_path):
    save(tmp_path, "test_cases.json", [case("zero"), case("pending"), {**case("blocked"), "blocked": True,
                                                                              "automation_note": "Permission missing"}])
    journal(tmp_path, "android_results.jsonl", [{"id": "zero", "outcome": "passed", "checks": 0}])
    save(tmp_path, "summary.json", {"controls": {"rows": [{"name": "Submit", "status": "not tested"}]}})
    result = dashboard(tmp_path)
    assert result["counts"] == {"inconclusive": 1, "pending": 1, "blocked": 1}
    assert result["cases"][2]["reason"] == "Permission missing"
    assert result["controls"][0]["name"] == "Submit"
    assert result["resume"]["uncertain"][0]["id"] == "pending"  # old journal has no start evidence


class Adapter:
    def __init__(self):
        self.taps = 0

    def guard(self):
        pass

    def context(self, value):
        pass

    def find(self, locator):
        return locator.value

    def identity(self, element):
        return "Submit form"

    def tap(self, element):
        self.taps += 1

    def visible(self, element):
        return True

    def enabled(self, element):
        return True


def combined_contract():
    return {"test_environment": True, "flows": [{"id": "submit", "title": "Submit and verify stored outcome",
            "approved": True, "steps": [{"action": "tap", "locator": {"strategy": "css", "value": "#submit"},
                                           "purpose": "test_form"},
                                          {"action": "assert_visible", "locator": {"strategy": "css", "value": "#success"}}],
            "backend_checks": ["stored"]}], "checks": [{"id": "stored", "title": "Stored status", "kind": "sqlite",
            "database_ref": "BLOWAI_DB_TEST", "query": "SELECT status FROM result", "expected": "accepted"}]}


@pytest.mark.parametrize("stored", ["accepted", "incorrect"])
def test_ui_and_database_are_checked_in_one_workflow_without_repeating_submission(tmp_path, stored):
    path = tmp_path / "test.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE result(status TEXT)")
        connection.execute("INSERT INTO result VALUES (?)", [stored])
    contract = parse_contract(combined_contract())
    assert [row["id"] for row in contract_cases(contract)] == ["contract_submit"]
    inputs = resolve_private_inputs(contract, {"BLOWAI_DB_TEST": str(path)})
    adapter = Adapter()
    runtime = ContractRuntime(adapter, contract.model_dump(), inputs)
    if stored == "accepted":
        runtime.execute("submit")
        assert runtime.checks == 2
        assert runtime.evidence[-1]["matched"]
    else:
        with pytest.raises(AssertionError):
            runtime.execute("submit")
    assert adapter.taps == 1


@pytest.mark.parametrize("change", ["unknown", "duplicate", "setup"])
def test_attached_backend_check_reference_rules(change):
    raw = combined_contract()
    if change == "unknown":
        raw["flows"][0]["backend_checks"] = ["missing"]
    elif change == "duplicate":
        raw["flows"][0]["backend_checks"].append("stored")
    else:
        raw["checks"][0]["setup_flow"] = "submit"
    with pytest.raises(ValueError):
        parse_contract(raw)


def test_ai_draft_uses_observed_targets_stays_unapproved_and_does_not_execute(tmp_path):
    save(tmp_path, "screens.json", [{"package_name": "com.example.app", "screen_name": "Account", "elements": [
        {"id": "heading", "visible": True, "text": "Account", "locators": [{"strategy": "text", "value": "Account"}]}]}])
    def ask(prompt, shape, **kwargs):
        assert shape is Draft and "E1" in prompt
        return Draft(title="Account heading", expected_basis="User requirement: Account is displayed",
                     steps=[{"action": "assert_visible", "target": "E1"}])
    result = draft(tmp_path, "Verify Account is displayed", ask)
    contract = parse_contract(result["contract"])
    assert contract.android_package == "com.example.app"
    assert not contract.test_environment and not contract.flows[0].approved
    assert contract_cases(contract)[0]["blocked"]
    with pytest.raises(ValueError, match="not observed"):
        draft(tmp_path, "Verify Account", lambda *args, **kw: Draft(title="Bad alias", expected_basis="Requirement",
              steps=[{"action": "assert_visible", "target": "E99"}]))


def test_draft_cannot_use_inline_credentials(tmp_path):
    save(tmp_path, "screens.json", [{"screen_name": "Login", "elements": [
        {"visible": True, "input_capable": True, "resource_id": "password", "text": "private-value",
         "locators": [{"strategy": "resource_id", "value": "password"}]}]}])
    def ask(prompt, shape, **kwargs):
        assert "private-value" not in prompt
        return Draft(title="Login", expected_basis="User requirement", steps=[{"action": "fill", "target": "E1", "value": "bad"}])
    with pytest.raises(ValueError, match="private test-data"):
        draft(tmp_path, "Sign in", ask)


def test_benchmark_counts_real_app_crashes_but_not_zero_assertion_passes(tmp_path):
    from backend.qa_benchmark import measure
    folder = tmp_path / "run"
    folder.mkdir()
    save(folder, "results.json", [{"id": "crash", "outcome": "failed", "exception_type": "AppCrash"},
                                  {"id": "zero", "outcome": "passed", "checks": 0}])
    data = measure(tmp_path, {"groups": [{"name": "Seeded", "runs": ["run"],
                                         "expected": {"crash": "failed", "zero": "passed"}}]})
    assert data["counts"]["tp"] == 1 and data["counts"]["unanswered_negative"] == 1
    assert data["overall_accuracy_percent"] is None
