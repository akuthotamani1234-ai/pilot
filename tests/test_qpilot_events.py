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


def test_a_live_event_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-event"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "events.worker.jsonl").write_text(
        json.dumps({"id": secret, "timestamp": 1, "text": secret}) + "\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert read_events(linked / "run")["events"] == []
    assert secret in (nested / "events.worker.jsonl").read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "events.worker.jsonl").write_text(
        json.dumps({"id": "home-own", "timestamp": 1, "text": "kept"}) + "\n", encoding="utf-8")
    events = read_events(real)["events"]
    assert [event["id"] for event in events] == ["home-own"]
    assert secret not in json.dumps(events)
    assert secret in (nested / "events.worker.jsonl").read_text(encoding="utf-8")


def test_reference_navigation_does_not_authorize_payment_controls():
    from backend.actions import action_class
    context = {"tag": "a", "role": "menuitem", "in_form": False, "href": "#"}
    assert action_class("Pay Grades", "a.menuitem", context) == "safe"
    assert action_class("Payment History", "a.menuitem", context) == "safe"
    assert action_class("Pay Grades", "button") == "pay"
    assert action_class("Pay now", "a", context) == "pay"
    assert action_class("Pay Grades", "a", dict(context, href="/pay/confirm")) == "pay"
    assert action_class("Pay Grades", "a", dict(context, href="index.php?page=checkout")) == "pay"
    assert action_class("Pay Grades", "a", dict(context, href="#/checkout")) == "pay"
    assert action_class("Pay Grades", "a", dict(context, href="#/checkout/cart")) == "safe"
    assert action_class("Pay Grades", "a", dict(context, href="index.php?step=payment")) == "pay"
    assert action_class("Pay Grades", "a", dict(context, href="category?page=2")) == "safe"
    assert action_class("Confirm payment", "button", {"tag": "button", "in_form": True}) == "pay"


def test_dynamic_media_progress_is_not_an_executable_oracle():
    from backend.agents.test_design import learned_cases
    page = {"slug": "home", "url": "https://fixture.test", "inputs": [], "forms": [], "buttons": [], "links": [],
            "behaviour": [{"selector": ".progress", "control": "Loaded: 1.05%", "effect": "text", "action": "click",
                           "added": ["Video Player is loading.", "Loaded: 0.00%"]}]}
    assert learned_cases([page]) == []
