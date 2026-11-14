"""Enumerate controls without sampling and require evidence for functional credit."""
from types import SimpleNamespace

import pytest

from backend.android import AndroidEnvironmentError, validate_mobile_config
from backend.android_app import AppSession
from backend.android_coverage import full_run
from backend.android_features import feature_matrix
from backend.android_interact import Budget, Session
from backend.android_reporting import control_coverage
from tests.test_android_form_identity import screen


def button(screen_id, number=0):
    return {"id": f"{screen_id}:button{number}", "type": "button", "class_name": "android.widget.Button",
            "text": "Choose", "resource_id": f"com.example:id/choice{number}", "accessibility_id": "",
            "visible": True, "enabled": True, "clickable": True, "locator_unique": True,
            "locators": [{"strategy": "resource_id", "value": f"com.example:id/choice{number}"}]}


def test_every_unique_control_is_planned_even_with_matching_labels():
    first = {"id": "first", "package_name": "com.example", "screen_name": "First", "elements": [button("first", n) for n in range(40)]}
    second = {"id": "second", "package_name": "com.example", "screen_name": "Second", "elements": [button("second", n) for n in range(40)]}
    device = SimpleNamespace(config={"app_mode": "installed"}, screens=[first, second])
    session = AppSession(device)
    assert len(session.controls(first)) == 40
    assert session.controls(first) == []
    assert len(session.controls(second)) == 40
    assert not session.coverage  # no controls were silently replaced by a sampling note


def test_shared_locator_does_not_credit_another_screen():
    first, second = button("first"), button("second")
    locator = first["locators"][0]
    state = {
        "screens": [{"id": "first", "elements": [first]}, {"id": "second", "elements": [second]}],
        "config": {"qa_contract": {"test_environment": True, "flows": [
            {"id": "choose", "title": "Choose on the first screen", "approved": True,
             "steps": [{"action": "assert_visible", "locator": locator}]}]}},
        "test_cases": [{"id": "case", "title": "Choose", "contract_id": "choose", "element_ids": [first["id"]]}],
        "results": [{"id": "case", "outcome": "passed", "checks": 1}],
    }
    components = {row["screen_id"]: row for row in feature_matrix(state)["components"]}
    assert components["first"]["passing_configured_checks"] == ["case"]
    assert components["second"]["passing_configured_checks"] == []
    assert components["second"]["needs_functional_check"]


def test_presence_only_is_not_reported_as_a_functionally_passed_control():
    element = button("screen")
    state = {"screens": [{"id": "screen", "elements": [element]}],
             "test_cases": [{"id": "visible", "element_ids": [element["id"]]}],
             "results": [{"id": "visible", "outcome": "passed", "checks": 1}]}
    features = feature_matrix(state)
    report = control_coverage(state, features, state["test_cases"], state["results"])
    assert report["rows"][0]["status"] == "not tested"
    assert report["rows"][0]["presence_checked"]
    assert report["counts"] == {"passed": 0, "failed": 0, "not tested": 1}


def test_a_generic_button_opens_a_new_form_and_queues_its_validation(monkeypatch):
    parent, login = screen(), screen("login")
    opener = button(parent["id"], 99)
    opener["text"] = "Open account"
    parent["elements"].append(opener)
    device = SimpleNamespace(config={"app_mode": "installed"}, screens=[parent])
    session = AppSession(device)
    monkeypatch.setattr(session, "observe_after", lambda *args: (parent, login))
    monkeypatch.setattr(session, "keep", lambda *args, **kwargs: True)
    session.tap_check(parent, opener)
    assert len(session.states) == 1
    planned = next(session.feature_items())
    assert planned["area"] == "form" and planned["args"][1]["kind"] == "login"
    inventory = session.state_inventory()
    assert inventory[0]["id"] == session.states[0]["id"]
    assert "nav_steps" not in inventory[0]


def test_reached_state_inventory_masks_private_values():
    parent, login = screen(), screen("login")
    device = SimpleNamespace(config={"app_mode": "installed"}, screens=[parent])
    session = AppSession(device)
    session.secrets["BLOWAI_SECRET_TEST_VALUE"] = "private-test-value"
    login["screen_name"] = "Welcome private-test-value"
    login["nav_steps"] = [{"value": "private-test-value"}]
    session.states.append(login)
    assert "private-test-value" not in str(session.state_inventory())


def test_reached_panels_are_included_in_functional_coverage():
    element = button("panel")
    state = {"screens": [], "interaction": {"state_inventory": [{"id": "panel", "elements": [element]}]}}
    matrix = feature_matrix(state)
    assert matrix["controls_needing_functional_checks_count"] == 1
    assert matrix["components"][0]["screen_id"] == "panel"


def test_full_run_requires_test_build_authorization():
    assert not full_run({"test_all_discovered": True})
    assert full_run({"test_all_discovered": True, "interaction_testing": True})
    with pytest.raises(AndroidEnvironmentError, match="Test-all-discovered"):
        validate_mobile_config({"app_mode": "installed", "package_name": "com.example", "device_id": "emulator-5554",
                                "test_all_discovered": "true"})


def test_full_run_removes_count_cutoff_but_preserves_stop_and_time_guards(monkeypatch):
    parent = screen()
    device = SimpleNamespace(config={"app_mode": "installed", "interaction_testing": True, "test_all_discovered": True},
                             screens=[parent], max_tries=1, deadline=float("inf"),
                             stop_path=SimpleNamespace(exists=lambda: False))
    session = Session(device)
    session.used = 1000
    session.spend()
    assert session.used == 1001
    device.stop_path = SimpleNamespace(exists=lambda: True)
    with pytest.raises(Budget, match="Stop requested"):
        session.spend()
    device.stop_path = SimpleNamespace(exists=lambda: False)
    device.deadline = 0
    with pytest.raises(Budget, match="time limit"):
        session.spend()


@pytest.mark.parametrize("limit,recorded", [(0, True), (1, False)])
def test_zero_page_limit_does_not_silently_turn_into_a_one_page_limit(limit, recorded):
    from backend.android_site import SiteSession
    home = {"id": "home", "web_url": "https://example.test/", "screen_name": "Home", "elements": []}
    device = SimpleNamespace(config={"app_mode": "web", "start_url": home["web_url"], "max_screens": limit},
                             screens=[home], record=lambda page: None)
    session = SiteSession(device)
    second = {"id": "account", "web_url": "https://example.test/account", "screen_name": "Account", "elements": []}
    page = session.add_page(second, "page", "Account link")
    assert (page is not None) is recorded
    assert len(session.pages) == (2 if recorded else 1)
    if not recorded:
        assert "limit of 1 pages" in session.tried[-1]["reason"]
