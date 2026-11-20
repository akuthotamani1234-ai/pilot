"""Plugin assertions become tests, a broken API workflow is held, and a stub answers a fault."""
import json

from backend.agents.script_generator import _hold_broken_workflows, plugin_script, validate_script
from backend.browser_controls import load_controls, stub_response
from backend.replay_pack import saved_replays


def test_an_accepted_plugin_assertion_becomes_a_test():
    code = plugin_script([{"id": "plugin_price_0", "title": "the price is shown", "expected": "₹ 500", "url": "/saree"}])
    assert validate_script(code) is None
    assert "assert '₹ 500' in body" in code
    assert "page.goto('/saree')" in code


def test_a_changed_api_workflow_is_not_trusted(tmp_path):
    (tmp_path / "qx_schema.json").write_text(json.dumps({
        "trust_broken": True,
        "broken": [{"operation": "POST /orders"}],
        "removed": [],
    }), encoding="utf-8")
    kept, held = _hold_broken_workflows(
        {"run_dir": str(tmp_path)},
        [{"id": "orders", "url": "https://shop.example/orders", "title": "create an order"},
         {"id": "home", "url": "https://shop.example/", "title": "home"}],
    )
    assert [case["id"] for case in kept] == ["home"]
    assert held[0]["skip_reason"].startswith("this workflow changed")


def test_a_stub_answers_a_fault_and_never_a_payment(tmp_path):
    (tmp_path / "qx_environment.json").write_text(json.dumps({
        "environment": "staging",
        "controls": {"stub_api": {"enabled": True}, "fixed_clock": {"enabled": False},
                     "network_fault": {"enabled": True}},
    }), encoding="utf-8")
    controls = load_controls(tmp_path)
    fault = dict(controls, start_url="https://shop.example/", navigation=False)
    assert stub_response("https://shop.example/app.js", fault)["body"] == '{"stub":true}'
    assert stub_response("https://shop.example/checkout", fault) is None
    start = dict(controls, start_url="https://shop.example/", navigation=True)
    assert stub_response("https://shop.example/", start) is None


def test_a_complete_package_names_the_test_that_can_run_again(tmp_path, monkeypatch):
    from backend.replay_pack import replay_tests, run_saved
    (tmp_path / "qx_replay.json").write_text(json.dumps({
        "packages": [
            {"id": "test_price.py::test_see", "replay": {"ran": True, "executed": True, "steps": ["open the product"]}},
            {"id": "12", "replay": {"ran": True, "executed": False, "steps": ["a crawl finding"]}},
        ],
    }), encoding="utf-8")
    (tmp_path / "generated_tests").mkdir()
    assert replay_tests(tmp_path) == ["test_price.py::test_see"]
    monkeypatch.setattr("backend.recheck.recheck", lambda folder, names: {"results": {names[0]: {"verdict": "fixed", "outcome": "passed"}}})
    played = run_saved(tmp_path)
    assert played["ran"] is True
    assert played["results"]["test_price.py::test_see"]["verdict"] == "fixed"


def test_the_rule_count_is_eighteen_capabilities_and_seven_release_steps():
    from backend.qx_status import card, status
    counted = status()
    assert counted["total"] == 25
    assert counted["completed"] == 25
    assert counted["remaining"] == 0
    shown = card({"discovered": 12, "tested": 4, "passed": 3, "failed": 1, "blocked": 2, "unknown": 5})
    assert shown["completed"] == 25
    assert shown["counts"] == {"discovered": 12, "tested": 4, "passed": 3, "failed": 1, "blocked": 2, "unknown": 5}


def test_a_saved_replay_can_be_read_back(tmp_path):
    (tmp_path / "qx_replay.json").write_text(json.dumps({
        "packages": [{"id": "price", "replay": {"ran": True, "steps": ["open the product"]}}],
    }), encoding="utf-8")
    rows = saved_replays(tmp_path)
    assert rows[0]["replay"]["ran"] is True
    assert saved_replays(tmp_path / "missing") == []


def test_replay_selection_requires_actual_execution_marker(tmp_path):
    from backend.replay_pack import replay_tests
    (tmp_path / "qx_replay.json").write_text(json.dumps({
        "packages": [
            {"id": "test_price.py::test_see", "replay": {"ran": True, "steps": ["legacy ran flag only"]}},
            {"id": "test_api.py::test_get", "replay": {"ran": True, "executed": False, "steps": ["prepared only"]}},
            {"id": "test_cart.py::test_total", "replay": {"ran": True, "executed": True, "steps": ["executed"]}},
        ],
    }), encoding="utf-8")
    assert replay_tests(tmp_path) == ["test_cart.py::test_total"]
