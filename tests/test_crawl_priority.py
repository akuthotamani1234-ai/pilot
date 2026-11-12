"""Navigation must not be starved by a revealed widget's descendants."""
import time

from playwright.sync_api import sync_playwright

from backend.agents.discovery import EXTRACT_JS
from backend.config import settings
from backend.observe import Explorer
from backend.page_status import exploration_status


def test_action_budget_cannot_claim_complete_exploration():
    status = exploration_status({"visited": 11, "not_visited_count": 0,
                                 "actions": {"not_tried_limit": 8}})
    assert status["status"] == "partial"
    assert not status["within_selected_scope"]
    assert not status["frontier_exhausted"]
    assert status["actions_limited"]


def test_root_pagination_is_tried_before_widget_descendants(monkeypatch):
    monkeypatch.setattr(settings, "max_interactions_per_page", 2)
    monkeypatch.setattr(settings, "explore_repeated_controls", True)
    monkeypatch.setattr(settings, "discovery_only", True)
    html = """<button id="about" onclick="document.querySelector('#widget').hidden=false">About</button>
    <div id="widget" hidden><button id="play">Play</button><button id="mute">Mute</button>
    <button id="volume">Volume</button><button id="fullscreen">Fullscreen</button></div>
    <button id="next" onclick="document.querySelector('#items').innerHTML=\'<a href=https://example.test/product/2>Product two</a>\'">Next</button>
    <div id="items"><a href="https://example.test/product/1">Product one</a></div>"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("https://example.test/**", lambda route: route.fulfill(content_type="text/html", body=html))
        page.goto("https://example.test/")
        entry = page.evaluate(EXTRACT_JS)
        entry["itemLinks"] = {"selector": "#items a"}
        # Extraction may see both controls as ordinary buttons; root traversal still
        # must not let About's newly revealed children consume Next's action.
        explorer = Explorer(EXTRACT_JS, lambda *args: None, time.time() + 20)
        urls, _ = explorer.explore(page, "https://example.test/", entry)
        assert "https://example.test/product/2" in urls
        next_action = next(b for b in entry["behaviour"] if b["control"] == "Next")
        assert next_action["effect"] != "error"
        browser.close()
