"""Fast execution, worker ordering and reloads must not erase visible progress."""
import json

import pytest

from backend.execution_events import read_events


def test_actions_between_polls_and_late_workers_are_retained(tmp_path):
    first = tmp_path / "events.first.gw0.jsonl"
    first.write_text("".join(json.dumps({"id": str(i), "timestamp": i, "text": "action"}) + "\n" for i in range(220)), encoding="utf-8")
    batch = read_events(tmp_path)
    assert len(batch["events"]) == 150
    rest = read_events(tmp_path, batch["cursor"])
    assert len(rest["events"]) == 70
    (tmp_path / "events.second.gw1.jsonl").write_text(json.dumps({"id": "late", "timestamp": 1}) + "\n", encoding="utf-8")
    late = read_events(tmp_path, rest["cursor"])
    assert [e["id"] for e in late["events"]] == ["late"]
    assert len(read_events(tmp_path, limit=500)["events"]) == 221  # page refresh/replay


def test_partial_event_is_consumed_only_after_newline(tmp_path):
    path = tmp_path / "events.worker.main.jsonl"
    path.write_text('{"id":"one"}', encoding="utf-8")
    incomplete = read_events(tmp_path)
    assert incomplete["events"] == []
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n")
    assert read_events(tmp_path, incomplete["cursor"])["events"][0]["id"] == "one"


def test_invalid_cursor_is_an_explicit_error(tmp_path):
    with pytest.raises(ValueError, match="cursor"):
        read_events(tmp_path, "not a cursor!")


def test_reference_navigation_does_not_authorize_payment_controls():
    from backend.actions import action_class
    context = {"tag": "a", "role": "menuitem", "in_form": False, "href": "#"}
    assert action_class("Pay Grades", "a.menuitem", context) == "safe"
    assert action_class("Payment History", "a.menuitem", context) == "safe"
    assert action_class("Pay Grades", "button") == "pay"
    assert action_class("Pay now", "a", context) == "pay"
    assert action_class("Pay Grades", "a", dict(context, href="/pay/confirm")) == "pay"
    assert action_class("Confirm payment", "button", {"tag": "button", "in_form": True}) == "pay"


def test_dynamic_media_progress_is_not_an_executable_oracle():
    from backend.agents.test_design import learned_cases
    page = {"slug": "home", "url": "https://fixture.test", "inputs": [], "forms": [], "buttons": [], "links": [],
            "behaviour": [{"selector": ".progress", "control": "Loaded: 1.05%", "effect": "text", "action": "click",
                           "added": ["Video Player is loading.", "Loaded: 0.00%"]}]}
    assert learned_cases([page]) == []
