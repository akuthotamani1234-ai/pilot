"""Bounded recovery for changing Android screens. No device, browser, or network."""
import json

import pytest
from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException

from backend.android import AndroidEnvironmentError, validate_mobile_config
from backend.android_dynamic import (
    BLOCKED_DYNAMIC,
    LOW_CONFIDENCE,
    PRODUCTION_WRITE,
    ActionRecovery,
    data_change_blocked,
    exact_label,
    has_visible_content,
    is_exact_safe_dismiss,
    locator_confidence,
    perform_tap,
    plan_overlay,
    scroll_stalled,
    security_reason,
    stable_fingerprint,
)
from backend.qa_contracts import parse_contract


def screen(elements, identity=None):
    return {"fingerprint": "page", "activity": ".Main", "elements": elements, "identity": identity or []}


def test_safe_dismiss_is_exact():
    assert is_exact_safe_dismiss(" Close ")
    assert is_exact_safe_dismiss("Not now")
    assert is_exact_safe_dismiss("×")
    assert not is_exact_safe_dismiss("Cancel order")
    assert not is_exact_safe_dismiss("Close account")
    assert exact_label("  No   thanks ") == "no thanks"


def test_popup_without_a_safe_label_is_blocked():
    popup = screen(
        [{"visible": True, "text": "Please select the store", "clickable": False},
         {"visible": True, "text": "Continue shopping", "clickable": True}],
        ["dialog", "please select the store"],
    )
    plan = plan_overlay(popup, {})
    assert plan["action"] == "blocked"
    assert "Please select the store" in plan["overlay_text"]


def test_one_exact_close_is_dismissed():
    popup = screen(
        [{"visible": True, "text": "A note", "clickable": False},
         {"visible": True, "text": "Close", "clickable": True}],
        ["dialog", "a note"],
    )
    plan = plan_overlay(popup, {})
    assert plan["action"] == "dismiss" and plan["target_text"] == "Close"


def test_approved_choice_is_exact_and_protected_targets_are_rejected():
    contract = parse_contract({
        "version": 1,
        "overlay_choices": [{
            "match_text": "Please select the store",
            "action": "tap_text",
            "target_text": "North",
            "purpose": "required_site_selection",
        }],
    })
    popup = screen(
        [{"visible": True, "text": "Please select the store", "clickable": False},
         {"visible": True, "text": "North", "clickable": True}],
        ["dialog", "please select the store"],
    )
    assert plan_overlay(popup, contract)["action"] == "choice"
    with pytest.raises(ValueError, match="payment|purchase|delete|permission|account"):
        parse_contract({"version": 1, "overlay_choices": [{
            "match_text": "Offer", "action": "tap_text", "target_text": "Buy now", "purpose": "offer",
        }]})


def test_prices_and_carousel_do_not_change_the_signature_but_a_popup_does():
    base = screen([
        {"visible": True, "text": "Shoes", "class_name": "Text", "resource_id": "title"},
        {"visible": True, "text": "$19.00", "class_name": "Text", "resource_id": "price"},
        {"visible": True, "text": "Slide A", "class_name": "Carousel", "resource_id": "home_carousel"},
    ])
    changed = screen([
        {"visible": True, "text": "Shoes", "class_name": "Text", "resource_id": "title"},
        {"visible": True, "text": "$24.50", "class_name": "Text", "resource_id": "price"},
        {"visible": True, "text": "Slide B", "class_name": "Carousel", "resource_id": "home_carousel"},
    ])
    covered = screen([
        {"visible": True, "text": "Shoes", "class_name": "Text", "resource_id": "title"},
        {"visible": True, "text": "Accept cookies", "region": "dialog", "clickable": True},
    ], ["dialog", "cookies"])
    assert stable_fingerprint(base) == stable_fingerprint(changed)
    assert stable_fingerprint(base) != stable_fingerprint(covered)


def test_blank_and_security_are_not_a_loaded_shop():
    assert not has_visible_content({"loading": True, "elements": [{"visible": True, "text": "Shoes"}]})
    assert not has_visible_content({"elements": []})
    assert has_visible_content({"elements": [{"visible": True, "text": "Shoes"}]})
    assert security_reason({"screen_name": "Just a moment...", "elements": [{"visible": True, "text": "Checking your browser"}]})
    assert not security_reason({"screen_name": "Shoes", "elements": [{"visible": True, "text": "Leather boots"}]})


def test_production_and_weak_locators_cannot_change_data():
    structural = {"strategy": "css", "value": "div:nth-of-type(3) > button"}
    named = {"strategy": "text", "value": "Add to cart"}
    assert PRODUCTION_WRITE in data_change_blocked("Add to cart", test_build=False, locator=named)
    assert data_change_blocked("Shoes", test_build=False, locator=structural) == ""
    assert LOW_CONFIDENCE in data_change_blocked("Add to cart", test_build=True, locator=structural, contract={})
    contract = {"flows": [{"approved": True, "steps": [
        {"action": "tap", "locator": {"strategy": "text", "value": "Add to cart"}}]}]}
    assert data_change_blocked("Add to cart", test_build=True, locator=structural, contract=contract) == ""
    assert locator_confidence({"strategy": "resource_id", "value": "add"}) == "high"
    assert locator_confidence(structural) == "low"


def test_a_stale_control_is_retried_once_and_then_stopped():
    recovery = ActionRecovery()
    seen = {"clicks": 0}

    def click(_element):
        seen["clicks"] += 1
        if seen["clicks"] < 3:
            raise StaleElementReferenceException()

    page = {"fingerprint": "same"}
    with pytest.raises(RuntimeError, match=BLOCKED_DYNAMIC):
        perform_tap({"text": "Shoes"}, click=click, refind=lambda: {"text": "Shoes"}, recovery=recovery, screen=page)
    assert seen["clicks"] == 2
    with pytest.raises(RuntimeError, match=BLOCKED_DYNAMIC):
        perform_tap({"text": "Shoes"}, click=click, refind=lambda: {"text": "Shoes"}, recovery=recovery, screen=page)
    assert seen["clicks"] == 2


def test_a_covered_control_is_not_clicked_through(tmp_path):
    pressed = []

    def click(_element):
        raise ElementClickInterceptedException()

    recovery = ActionRecovery()
    with pytest.raises(RuntimeError, match=BLOCKED_DYNAMIC):
        perform_tap(
            {"text": "Shoes", "locators": [{"strategy": "text", "value": "Shoes"}]},
            click=click, refind=lambda: {"text": "Shoes"}, recovery=recovery, screen={"fingerprint": "page"},
            run_dir=tmp_path,
        )
    saved = json.loads((tmp_path / "dynamic.json").read_text(encoding="utf-8"))
    assert saved["events"][-1]["blocked_reason"] == BLOCKED_DYNAMIC
    assert saved["events"][-1]["retries"] == 1
    assert "password" not in json.dumps(saved).casefold()
    assert pressed == []


def test_scroll_stops_when_content_does_not_change():
    stalls, stop = scroll_stalled(1000, 1000, 0, 2)
    assert not stop and stalls == 1
    stalls, stop = scroll_stalled(1000, 1000, stalls, 2)
    assert stop
    stalls, stop = scroll_stalled(1000, 1400, 5, 2)
    assert stalls == 0 and not stop


def test_config_wait_has_a_ceiling():
    config = validate_mobile_config({
        "app_mode": "web", "device_id": "emulator-5554", "start_url": "https://example.test/",
    })
    assert config["dynamic_wait_s"] == 12
    assert config["dynamic_retries"] == 1
    assert config["scroll_stalls"] == 2
    with pytest.raises(AndroidEnvironmentError):
        validate_mobile_config({
            "app_mode": "web", "device_id": "emulator-5554", "start_url": "https://example.test/",
            "dynamic_wait_s": 0,
        })
