"""The live healer does not write a level-3 test-mistake repair without approval."""
from backend.agents.self_healing import _replace_selector, self_healing_agent
from backend.healing_policy import issue_healing_approval, reset_healing_approvals

CODE = (
    "import re\nimport pytest\nfrom playwright.sync_api import expect\n\n\n@pytest.mark.guest\n"
    "def test_ai_flow_6(page):\n    \"\"\"User opens the About Us popup\"\"\"\n    page.goto('https://x.test')\n"
    "    page.locator(\"button[aria-label='Close']\").click()\n"
    "    expect(page.locator('#about')).to_be_hidden()\n"
)
ERR = (
    "Locator.click: Error: strict mode violation: "
    "locator(\"button[aria-label='Close']\") resolved to 4 elements:"
)
BAD = "button[aria-label='Close']"
GOOD = f"{BAD} >> visible=true >> nth=0"


def _state(tmp_path, *, category: str, token: str = ""):
    tests = tmp_path / "generated_tests"
    tests.mkdir(parents=True)
    (tests / "test_flows_ai.py").write_text(CODE, encoding="utf-8")
    failure = {
        "source": "test", "category": category,
        "nodeid": "test_flows_ai.py::test_ai_flow_6",
        "file": "test_flows_ai.py", "test": "test_ai_flow_6", "error": ERR,
    }
    if token:
        failure["approval_token"] = token
    return {
        "run_dir": str(tmp_path), "app_map": [], "failures": [failure],
    }


def test_a_test_mistake_is_not_written_until_it_is_approved(tmp_path, monkeypatch):
    from backend.agents import self_healing
    monkeypatch.setattr(self_healing, "llm_enabled", lambda: False)
    reset_healing_approvals()
    out = self_healing_agent(_state(tmp_path, category="test_mistake"))
    text = (tmp_path / "generated_tests" / "test_flows_ai.py").read_text(encoding="utf-8")
    assert text == CODE
    assert out["rerun_only"] == []
    assert "human_approval" in out["healing_log"][0]["change"] or "test_mistake" in out["healing_log"][0]["change"]

    new = _replace_selector(CODE, BAD, GOOD)
    token = issue_healing_approval(CODE, new, "test_mistake")["token"]
    approved = tmp_path / "approved"
    out = self_healing_agent(_state(approved, category="test_mistake", token=token))
    fixed = (approved / "generated_tests" / "test_flows_ai.py").read_text(encoding="utf-8")
    assert "visible=true" in fixed and "to_be_hidden()" in fixed
    assert out["healing_log"][0]["status"] == "pending"

    again = tmp_path / "again"
    out = self_healing_agent(_state(again, category="test_mistake", token=token))
    kept = (again / "generated_tests" / "test_flows_ai.py").read_text(encoding="utf-8")
    assert kept == CODE
    assert out["rerun_only"] == []
    assert "already used" in out["healing_log"][0]["change"]


def test_the_same_selector_in_another_file_is_repaired_there(tmp_path, monkeypatch):
    from backend.agents import self_healing
    monkeypatch.setattr(self_healing, "llm_enabled", lambda: False)
    tests = tmp_path / "generated_tests"
    tests.mkdir()
    other = CODE.replace("def test_ai_flow_6", "def test_ai_flow_7")
    (tests / "test_flows_ai.py").write_text(CODE, encoding="utf-8")
    (tests / "test_flows_b.py").write_text(other, encoding="utf-8")
    failures = []
    for file, test in (("test_flows_ai.py", "test_ai_flow_6"), ("test_flows_b.py", "test_ai_flow_7")):
        failures.append({
            "source": "test", "category": "test_defect",
            "nodeid": f"{file}::{test}", "file": file, "test": test, "error": ERR,
        })
    out = self_healing_agent({"run_dir": str(tmp_path), "app_map": [], "failures": failures})
    for name in ("test_flows_ai.py", "test_flows_b.py"):
        text = (tests / name).read_text(encoding="utf-8")
        assert "visible=true" in text and "to_be_hidden()" in text
    assert {h["file"] for h in out["healing_log"]} == {"test_flows_ai.py", "test_flows_b.py"}
    assert set(out["rerun_only"]) == {
        "test_flows_ai.py::test_ai_flow_6", "test_flows_b.py::test_ai_flow_7",
    }
